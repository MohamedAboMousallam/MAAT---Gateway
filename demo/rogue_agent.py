"""A deliberately broken agent: its tool call fails, so it retries the exact
same prompt forever with no backoff — carrying a fat context on a
frontier-priced model, the way real agents do. MAAT kills it on the 3rd
identical call, then we extrapolate what the unguarded loop would have cost.

Run:  python demo/rogue_agent.py
"""
import os
import time

import httpx
from openai import OpenAI, PermissionDeniedError

GATEWAY = os.getenv("MAAT_URL", "http://localhost:8080/v1")
MODEL = os.getenv("DEMO_MODEL", "gemma-mock-large")
MAX_TOKENS = int(os.getenv("DEMO_MAX_TOKENS", "400"))  # keeps reasoning models snappy

client = OpenAI(base_url=GATEWAY, api_key="demo-key", max_retries=0,
                default_headers={"X-Workflow-Id": "demo-rogue"})

# Real runaway loops carry real context: here, a partially-read CSV the
# agent keeps re-sending on every retry (~2k tokens per attempt).
CSV = "\n".join(
    f"2026-06-{i % 28 + 1:02d},eu-west,SKU-{i % 40:03d},{i % 9 + 1},{(i * 7) % 500}.00"
    for i in range(240))
PROMPT = (
    "You are a reporting agent. Read /tmp/report.csv fully and produce the "
    "weekly revenue summary.\n\nPartial tool output so far:\n"
    "date,region,sku,qty,revenue\n" + CSV +
    "\n\nTool result for the remainder: FAIL_TOOL ENOENT. Retry the read.")

print(f"rogue-agent → {GATEWAY} (model={MODEL})\n")
t0 = time.time()
for attempt in range(1, 51):
    try:
        r = client.chat.completions.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": PROMPT}])
        u = r.usage
        print(f"  attempt {attempt:2d}: {u.prompt_tokens}->{u.completion_tokens} tok "
              "— tool still failing, retrying same call…")
    except PermissionDeniedError as e:
        elapsed = time.time() - t0
        detail = e.body.get("message") if isinstance(e.body, dict) else str(e)
        print("\n  ⚖  MAAT KILLED THIS WORKFLOW")
        print(f"  {detail}")
        try:
            state = httpx.get(GATEWAY.replace("/v1", "") + "/admin/state").json()
            wf = next(w for w in state["workflows"] if w["id"] == "demo-rogue")
            rate = wf["spent_usd"] / max(elapsed, 0.001) * 3600
            print(f"\n  Burned ${wf['spent_usd']:.4f} in {elapsed:.1f}s before the kill.")
            print(f"  Unguarded at this measured pace: ~${rate:,.0f}/hour — "
                  f"~${rate * 60:,.0f} over an unattended weekend (60h).")
        except Exception:
            pass
        break
else:
    print("\n  loop finished without intervention — guardrails misconfigured?")
