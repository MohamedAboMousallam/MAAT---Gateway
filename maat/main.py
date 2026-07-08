"""MAAT — budget guardrails gateway for AI agents.

Point any OpenAI-compatible SDK at this server (base_url = http://host:8080/v1),
tag requests with an X-Workflow-Id header, and MAAT meters spend, detects
runaway loops, downgrades models near budget, and kills workflows that
exceed it — with Slack alerts and a live dashboard at /.
"""
import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path

import yaml
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               StreamingResponse)

from .alerts import Alerter
from .guards import LoopDetector, budget_tier, cost_usd
from .proxy import Upstream, _last_user_text
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = os.getenv("MAAT_CONFIG", str(ROOT / "config" / "policies.yaml"))
DB_PATH = os.getenv("MAAT_DB", str(ROOT / "data" / "maat.db"))
ADMIN_TOKEN = os.getenv("MAAT_ADMIN_TOKEN", "").strip()

with open(CONFIG_PATH, encoding="utf-8") as f:
    CFG = yaml.safe_load(f) or {}

DEFAULTS = CFG.get("defaults", {})
WORKFLOW_POLICIES = CFG.get("workflows", {}) or {}
LOOP_CFG = CFG.get("loop", {})
PRICING = CFG.get("pricing", {"default": {"input_per_1m": 0, "output_per_1m": 0}})

store = Store(DB_PATH)
alerter = Alerter(os.getenv("SLACK_WEBHOOK_URL"))
loops = LoopDetector(
    repeat_threshold=LOOP_CFG.get("repeat_threshold", 3),
    window_seconds=LOOP_CFG.get("window_seconds", 120),
    similarity=LOOP_CFG.get("similarity", 0.92),
    rate_per_minute=LOOP_CFG.get("rate_per_minute", 30),
)
upstream = Upstream(
    mode=os.getenv("UPSTREAM_MODE", "mock"),
    base_url=os.getenv("UPSTREAM_BASE_URL", "https://api.fireworks.ai/inference/v1"),
    api_key=os.getenv("UPSTREAM_API_KEY", ""),
)

# Optional per-workflow API keys: the bearer key IS the workflow identity,
# so a lying agent can't spend another workflow's budget.
KEY_MAP = {v["api_key"]: k for k, v in WORKFLOW_POLICIES.items()
           if isinstance(v, dict) and v.get("api_key")}
REQUIRE_AUTH = os.getenv("MAAT_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")

# Optional zero-cost local tier: a vLLM OpenAI server on the same AMD GPU.
LOCAL_TIER = CFG.get("local_tier") or {}
local_upstream = (
    Upstream(mode="openai", base_url=LOCAL_TIER["base_url"],
             api_key=LOCAL_TIER.get("api_key", ""))
    if LOCAL_TIER.get("base_url") else None
)

OBSERVED: set[tuple[str, str]] = set()  # (workflow, event-type) dedup, observe mode
WF_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")

app = FastAPI(title="MAAT gateway", version="0.1.0")


def policy_for(wf_id: str) -> dict:
    p = dict(DEFAULTS)
    p.update(WORKFLOW_POLICIES.get(wf_id) or {})
    p.setdefault("budget_usd", 1.0)
    p.setdefault("warn_at", 0.70)
    p.setdefault("downgrade_at", 0.90)
    p.setdefault("downgrade_model", None)
    p.setdefault("mode", "enforce")
    return p


def guard_error(message: str, code: str, status: int = 403) -> JSONResponse:
    """OpenAI-shaped error so agent SDKs raise cleanly instead of retrying."""
    return JSONResponse(
        status_code=status,
        content={"error": {"message": f"MAAT: {message}", "type": "maat_guardrail",
                           "code": code}},
    )


async def kill_workflow(wf_id: str, reason: str, spent: float, budget: float, etype: str):
    store.update_workflow(wf_id, status="killed", killed_reason=reason)
    store.add_event(wf_id, "kill", etype, reason)
    await alerter.send(
        f"MAAT ⚖️ KILLED workflow `{wf_id}` — {reason}. "
        f"Spent ${spent:.4f} of ${budget:.2f}. Resume from the dashboard."
    )


async def observe_flag(wf_id: str, etype: str, reason: str, spent: float, budget: float):
    """Observe mode: record the verdict without enforcing it. Fires once per type."""
    key = (wf_id, etype)
    if key in OBSERVED:
        return
    OBSERVED.add(key)
    store.add_event(wf_id, "warn", etype, f"OBSERVE — would kill: {reason}")
    await alerter.send(
        f"MAAT ⚖️ [observe] would kill `{wf_id}` — {reason} "
        f"(${spent:.4f}/${budget:.2f}). Enforcement is off for this workflow.")


# --------------------------------------------------------------------------
# The proxy route agents talk to
# --------------------------------------------------------------------------
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return guard_error("request body must be JSON", "bad_request", 400)

    auth = request.headers.get("Authorization", "")
    bearer = auth[7:] if auth.startswith("Bearer ") else auth
    if bearer in KEY_MAP:
        wf_id = KEY_MAP[bearer]  # key-based identity: spoof-proof attribution
    elif REQUIRE_AUTH:
        return guard_error("unknown workflow key — assign api_key in policies.yaml",
                           "unauthorized", 401)
    else:
        wf_id = request.headers.get("X-Workflow-Id", "default")
        if not WF_ID_RE.match(wf_id):
            return guard_error(
                "invalid X-Workflow-Id (letters, digits, . _ : - only, max 64 chars)",
                "bad_request", 400)
    pol = policy_for(wf_id)
    wf = store.get_or_create_workflow(wf_id, pol["budget_usd"])
    budget, spent = wf["budget_usd"], wf["spent_usd"]

    enforcing = pol.get("mode", "enforce") != "observe"

    # 0. Already judged?
    if wf["status"] == "killed":
        return guard_error(
            f"workflow '{wf_id}' is killed ({wf['killed_reason'] or 'manual kill'}). "
            "Resume it from the MAAT dashboard.", "workflow_killed")

    # 1. Budget gate: warn -> downgrade -> kill (or flag-only, in observe mode)
    tier = budget_tier(spent, budget, pol["warn_at"], pol["downgrade_at"])
    is_local = False
    if tier == "exceeded":
        reason = f"budget exhausted (${spent:.4f} of ${budget:.2f})"
        if enforcing:
            await kill_workflow(wf_id, reason, spent, budget, "budget_kill")
            return guard_error(f"workflow '{wf_id}' {reason}", "budget_exceeded")
        await observe_flag(wf_id, "budget_kill", reason, spent, budget)

    elif tier == "downgrade" and (LOCAL_TIER.get("model") or pol["downgrade_model"]):
        dg_model = LOCAL_TIER.get("model") or pol["downgrade_model"]
        is_local = bool(local_upstream and LOCAL_TIER.get("model"))
        if not wf["downgraded"]:
            store.update_workflow(wf_id, downgraded=1)
            where = f"local AMD/ROCm tier ({dg_model}, $0)" if is_local else dg_model
            msg = f"at {spent / budget:.0%} of budget — downgrading to {where}"
            store.add_event(wf_id, "warn", "budget_downgrade", msg)
            await alerter.send(f"MAAT ⚖️ `{wf_id}` {msg}")
        payload["model"] = dg_model

    elif tier == "warn" and not wf["warned"]:
        store.update_workflow(wf_id, warned=1)
        msg = f"at {spent / budget:.0%} of ${budget:.2f} budget"
        store.add_event(wf_id, "warn", "budget_warn", msg)
        await alerter.send(f"MAAT ⚖️ `{wf_id}` {msg}")

    # 2. Loop / rate gate (progress-aware)
    messages = payload.get("messages", [])
    msgs_json = json.dumps({"m": payload.get("model"), "msgs": messages},
                           sort_keys=True, default=str)
    prompt_hash = hashlib.sha256(msgs_json.encode()).hexdigest()[:16]
    action, reasons = loops.check_and_record(
        wf_id, prompt_hash, _last_user_text(messages),
        n_msgs=len(messages), total_chars=len(msgs_json))
    if action == "kill":
        reason = "; ".join(reasons)
        if enforcing:
            await kill_workflow(wf_id, reason, spent, budget, "loop_kill")
            return guard_error(f"workflow '{wf_id}' killed — {reason}", "workflow_killed")
        await observe_flag(wf_id, "loop_kill", reason, spent, budget)
    elif action == "throttle":
        store.add_event(wf_id, "warn", "rate_throttle", reasons[0])
        if enforcing:
            await asyncio.sleep(1.5)

    # 3. Forward
    use_upstream = local_upstream if is_local else upstream
    model = payload.get("model", "unknown")
    started = time.time()

    def settle(usage: dict):
        pt = int(usage.get("prompt_tokens") or 0)
        ct = int(usage.get("completion_tokens") or 0)
        cost = 0.0 if is_local else cost_usd(PRICING, model, pt, ct)
        new_spent = store.add_spend(wf_id, cost)
        store.record_call(wf_id, model, pt, ct, cost,
                          int((time.time() - started) * 1000), prompt_hash)
        tier_note = " · local ROCm tier" if is_local else ""
        store.add_event(wf_id, "info", "call",
                        f"{model} · {pt}→{ct} tok · ${cost:.4f}{tier_note}")
        return new_spent

    async def settle_and_judge(usage: dict) -> float:
        new_spent = settle(usage)
        if new_spent >= budget:
            reason = f"budget exhausted (${new_spent:.4f} of ${budget:.2f})"
            if enforcing:
                await kill_workflow(wf_id, reason, new_spent, budget, "budget_kill")
            else:
                await observe_flag(wf_id, "budget_kill", reason, new_spent, budget)
        return new_spent

    if payload.get("stream"):
        async def tee():
            usage = {}
            async for item in use_upstream.stream(payload):
                if isinstance(item, tuple) and item[0] == "__usage__":
                    usage = item[1]
                else:
                    yield item
            await settle_and_judge(usage)
        return StreamingResponse(tee(), media_type="text/event-stream")

    status, body = await use_upstream.complete(payload)
    if status != 200:
        store.add_event(wf_id, "warn", "upstream_error", f"HTTP {status} from upstream")
        return JSONResponse(status_code=status, content=body)

    new_spent = await settle_and_judge(body.get("usage") or {})
    return JSONResponse(content=body, headers={
        "X-MAAT-Workflow": wf_id,
        "X-MAAT-Spent-USD": f"{new_spent:.6f}",
        "X-MAAT-Budget-USD": f"{budget:.2f}",
    })


# --------------------------------------------------------------------------
# Admin API + dashboard
# --------------------------------------------------------------------------
def _authorized(request: Request) -> bool:
    if not ADMIN_TOKEN:
        return True
    return request.headers.get("Authorization") == f"Bearer {ADMIN_TOKEN}"


@app.get("/admin/state")
async def admin_state():
    s = store.state()
    for w in s["workflows"]:
        w["mode"] = policy_for(w["id"]).get("mode", "enforce")
    s["config"] = {
        "upstream_mode": upstream.mode,
        "local_tier": bool(local_upstream),
        "auth_required": REQUIRE_AUTH,
        "warn_at": DEFAULTS.get("warn_at", 0.7),
        "downgrade_at": DEFAULTS.get("downgrade_at", 0.9),
        "loop": LOOP_CFG,
    }
    return s


@app.post("/admin/workflows/{wf_id}/kill")
async def admin_kill(wf_id: str, request: Request):
    if not WF_ID_RE.match(wf_id):
        return guard_error("invalid workflow id", "bad_request", 400)
    if not _authorized(request):
        return guard_error("admin token required", "unauthorized", 401)
    wf = store.get_or_create_workflow(wf_id, policy_for(wf_id)["budget_usd"])
    await kill_workflow(wf_id, "manual kill from dashboard",
                        wf["spent_usd"], wf["budget_usd"], "manual_kill")
    return {"ok": True}


@app.post("/admin/workflows/{wf_id}/resume")
async def admin_resume(wf_id: str, request: Request):
    if not WF_ID_RE.match(wf_id):
        return guard_error("invalid workflow id", "bad_request", 400)
    if not _authorized(request):
        return guard_error("admin token required", "unauthorized", 401)
    store.update_workflow(wf_id, status="active", killed_reason=None, warned=0)
    loops.forget(wf_id)
    for k in [k for k in OBSERVED if k[0] == wf_id]:
        OBSERVED.discard(k)
    store.add_event(wf_id, "info", "resume", "workflow resumed from dashboard")
    return {"ok": True}


@app.post("/admin/workflows/{wf_id}/budget")
async def admin_budget(wf_id: str, request: Request):
    if not WF_ID_RE.match(wf_id):
        return guard_error("invalid workflow id", "bad_request", 400)
    if not _authorized(request):
        return guard_error("admin token required", "unauthorized", 401)
    body = await request.json()
    budget = float(body.get("budget_usd", 0))
    if budget <= 0:
        return guard_error("budget_usd must be > 0", "bad_request", 400)
    store.get_or_create_workflow(wf_id, budget)
    store.update_workflow(wf_id, budget_usd=budget)
    store.add_event(wf_id, "info", "budget_set", f"budget set to ${budget:.2f}")
    return {"ok": True}


@app.post("/admin/demo/rogue")
async def admin_demo_rogue(request: Request):
    """Unleash a self-contained rogue agent against this gateway (mock mode
    only — never burns real credits). Lets reviewers trigger a kill live."""
    if not _authorized(request):
        return guard_error("admin token required", "unauthorized", 401)
    if upstream.mode != "mock":
        return guard_error(
            "the chaos demo only runs when UPSTREAM_MODE=mock (protects real credits)",
            "demo_disabled", 400)
    wf_id = f"chaos-{int(time.time() * 1000) % 1000000}"
    store.get_or_create_workflow(wf_id, 0.25)
    prompt = ("You are a reporting agent. Read /tmp/report.csv and summarize. "
              "Partial data so far: " + "date,region,sku,qty,revenue; " * 60 +
              "Tool result for the remainder: FAIL_TOOL ENOENT. Retry the read.")
    calls_survived, detail = 0, None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://maat") as c:
        for _ in range(12):
            r = await c.post("/v1/chat/completions",
                             headers={"X-Workflow-Id": wf_id},
                             json={"model": "gemma-mock-large",
                                   "messages": [{"role": "user", "content": prompt}]})
            if r.status_code == 403:
                detail = r.json().get("error", {}).get("message")
                break
            calls_survived += 1
            await asyncio.sleep(0.35)
    return {"ok": True, "workflow": wf_id, "calls_survived": calls_survived,
            "killed": detail is not None, "detail": detail}


@app.get("/admin/workflows/{wf_id}/report")
async def admin_report(wf_id: str):
    """Plain-text post-mortem for a workflow: timeline, spend, verdict."""
    if not WF_ID_RE.match(wf_id):
        return guard_error("invalid workflow id", "bad_request", 400)
    wf = store.find_workflow(wf_id)
    if wf is None:
        return guard_error(f"no workflow '{wf_id}'", "not_found", 404)
    calls, events = store.calls_for(wf_id), store.events_for(wf_id)

    def t(ts):
        return time.strftime("%H:%M:%S", time.localtime(ts))

    lines = [
        f"MAAT incident report — {wf_id}",
        "=" * (24 + len(wf_id)),
        f"status:  {wf['status'].upper()}"
        + (f"  ({wf['killed_reason']})" if wf["killed_reason"] else ""),
        f"spend:   ${wf['spent_usd']:.4f} of ${wf['budget_usd']:.2f} budget"
        f"  ·  {wf['calls']} calls",
        "",
        "Timeline",
        "--------",
    ]
    for e in events:
        lines.append(f"{t(e['ts'])}  [{e['severity']:>4}] {e['type']}: {e['message']}")
    lines += ["", "Calls", "-----"]
    for c in calls:
        lines.append(f"{t(c['ts'])}  {c['model']}  "
                     f"{c['prompt_tokens']}→{c['completion_tokens']} tok  "
                     f"${c['cost_usd']:.4f}  hash={c['prompt_hash']}")
    if len(calls) >= 2 and wf["spent_usd"] > 0:
        window = max(calls[-1]["ts"] - calls[0]["ts"], 1.0)
        rate = wf["spent_usd"] / window * 3600
        lines += ["", "Projection",
                  "----------",
                  f"measured pace: ${rate:,.2f}/hour"
                  f"  ·  ~${rate * 60:,.0f} over an unattended weekend (60h)"]
    return PlainTextResponse("\n".join(lines) + "\n")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "upstream_mode": upstream.mode}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return (Path(__file__).parent / "dashboard" / "index.html").read_text(encoding="utf-8")
