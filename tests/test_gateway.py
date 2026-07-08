"""Integration tests: the gateway's actual HTTP behavior in mock mode."""
import os
import pathlib

os.environ.setdefault("MAAT_DB", "/tmp/maat-test.db")
os.environ.setdefault("UPSTREAM_MODE", "mock")
for p in pathlib.Path("/tmp").glob("maat-test.db*"):
    p.unlink(missing_ok=True)

from fastapi.testclient import TestClient  # noqa: E402
from maat.main import app  # noqa: E402

client = TestClient(app)


def _chat(wf=None, key=None, content="hello there"):
    headers = {}
    if wf:
        headers["X-Workflow-Id"] = wf
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return client.post(
        "/v1/chat/completions",
        json={"model": "gemma-mock-small",
              "messages": [{"role": "user", "content": content}]},
        headers=headers)


def test_enforce_mode_kills_third_identical_call():
    assert _chat(wf="t-rogue", content="retry the tool").status_code == 200
    assert _chat(wf="t-rogue", content="retry the tool").status_code == 200
    r3 = _chat(wf="t-rogue", content="retry the tool")
    assert r3.status_code == 403
    assert r3.json()["error"]["code"] == "workflow_killed"
    # and it stays dead
    assert _chat(wf="t-rogue", content="anything else").status_code == 403


def test_observe_mode_flags_but_never_blocks():
    for _ in range(4):
        assert _chat(wf="demo-observe", content="poll the queue").status_code == 200
    state = client.get("/admin/state").json()
    flags = [e for e in state["events"]
             if e["workflow_id"] == "demo-observe" and "OBSERVE" in e["message"]]
    assert flags, "observe mode should record a would-kill flag"
    wf = next(w for w in state["workflows"] if w["id"] == "demo-observe")
    assert wf["status"] == "active" and wf["mode"] == "observe"


def test_api_key_is_workflow_identity():
    r = _chat(key="maat-sk-keyed-demo-ROTATE-ME")  # no header at all
    assert r.status_code == 200
    assert r.headers["X-MAAT-Workflow"] == "keyed-demo"
    # a spoofed header cannot override the key
    r2 = _chat(wf="someone-elses-budget", key="maat-sk-keyed-demo-ROTATE-ME",
               content="a different question entirely")
    assert r2.headers["X-MAAT-Workflow"] == "keyed-demo"


def test_kill_and_resume_roundtrip():
    assert _chat(wf="t-manual").status_code == 200
    assert client.post("/admin/workflows/t-manual/kill").json()["ok"]
    assert _chat(wf="t-manual", content="new question").status_code == 403
    assert client.post("/admin/workflows/t-manual/resume").json()["ok"]
    assert _chat(wf="t-manual", content="another new question").status_code == 200


def test_multistep_agent_with_growing_history_is_not_killed():
    """The false-positive regression test: LangChain/CrewAI-style loops keep
    the original user task constant while history grows. Must stay alive."""
    msgs = [{"role": "user", "content": "plan and execute the deployment"}]
    for step in range(5):
        r = client.post("/v1/chat/completions",
                        json={"model": "gemma-mock-small", "messages": msgs},
                        headers={"X-Workflow-Id": "t-legit-agent"})
        assert r.status_code == 200, f"healthy agent killed at step {step + 1}"
        msgs = msgs + [
            {"role": "assistant", "content": f"executing step {step}: ran terraform plan"},
            {"role": "tool", "content": f"step {step} output: 4 resources to change " * 3},
        ]


def test_invalid_workflow_header_rejected():
    r = client.post("/v1/chat/completions",
                    json={"model": "gemma-mock-small",
                          "messages": [{"role": "user", "content": "hi"}]},
                    headers={"X-Workflow-Id": "<img src=x onerror=alert(1)>"})
    assert r.status_code == 400


def test_chaos_demo_gets_judged():
    r = client.post("/admin/demo/rogue")
    d = r.json()
    assert d["ok"] and d["killed"] and d["calls_survived"] <= 3
    state = client.get("/admin/state").json()
    wf = next(w for w in state["workflows"] if w["id"] == d["workflow"])
    assert wf["status"] == "killed"


def test_incident_report_for_killed_workflow():
    rep = client.get("/admin/workflows/t-rogue/report")
    assert rep.status_code == 200
    assert "incident report" in rep.text.lower()
    assert "runaway retry loop" in rep.text
    assert client.get("/admin/workflows/never-existed-wf/report").status_code == 404
