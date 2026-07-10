# 𓆄 MAAT — the kill switch for runaway AI agents

Agents don't crash. They loop. A broken tool call doesn't throw — it retries the same prompt, with the same fat context, at full API price, at 2 a.m., on your key. **MAAT is a drop-in gateway that watches agent *behavior* at runtime**: it detects the loop, kills the workflow (or reroutes it to a $0 local model on an AMD GPU), pings Slack, and writes the verdict to a live ledger. Adoption is one line — change the `base_url`.

Named for Ma'at, who weighed every heart against a feather. MAAT weighs every request against its budget.

## Why not LiteLLM / Portkey / Helicone?

Those are excellent **spend meters**: per-key and per-team budgets, usage logs, alerts. They tell you what you spent. None of them watches for agent *failure behavior* — the runaway retry loop, the no-progress cycle of near-identical prompts, the rate spike — and none takes graduated action against it. MAAT's core is a **runtime judgment layer**: loop detection, rate ceilings, then warn → downgrade → kill, per workflow. (They compose, too: MAAT can sit in front of a LiteLLM router.)

A newer wave of agent circuit breakers is emerging — gateway kill switches (Loopers, agentgateway) and in-process SDKs (AgentGuard) — which validates the category. MAAT's wedge against them is judgment quality and grace: **progress-aware detection** (a growing conversation is a working agent; only stagnant repetition is a loop — blunt N-calls-per-minute triggers kill healthy agents) and **degrade-don't-die** — near budget, workflows reroute to a $0 local model on an AMD GPU instead of being executed.

## What it does

```
 agents (any OpenAI-compatible SDK)
        │  base_url = http://maat:8080/v1
        │  identity: workflow API key (or X-Workflow-Id in dev)
        ▼
 ┌────────────────────────────────────────────────┐
 │ MAAT gateway                                   │
 │  behavior gate   identical / near-duplicate    │
 │                  loops, call-rate ceiling      │
 │  budget gate     warn → downgrade → kill       │
 │  enforcement     enforce | observe (shadow)    │
 │  settle          tokens → $ → per-workflow     │
 │  ledger · Slack alerts · live dashboard (/)    │
 └────────────────────────────────────────────────┘
        ▼                          ▼ (near budget)
 Fireworks AI                Gemma 3 on AMD MI300X
 (Kimi K2.6 serverless)      via vLLM/ROCm — $0 tier
```

A killed workflow gets an OpenAI-shaped `403`, so SDKs raise cleanly instead of retrying. Enforcement lives outside the model's context, so a prompt-injected or jailbroken agent cannot talk its way past it. Every killed workflow gets a one-click **incident report**: timeline, per-call ledger, and the measured burn rate projected forward. **Observe mode** runs the same judgments in shadow — it flags what it *would* kill without blocking, so you can tune thresholds on production traffic risk-free (and exempt legitimately repetitive agents like pollers).

## Quickstart (60 seconds, $0, no API key)

```bash
docker compose up --build -d        # MAAT in mock mode on :8080
open http://localhost:8080          # the dashboard

pip install openai httpx
python demo/good_agent.py           # normal traffic: metered, attributed
python demo/rogue_agent.py          # retry loop: killed on the 3rd call
```

The rogue agent carries a ~2k-token context on a frontier-priced mock model, like real loops do. Watch it take the red **JUDGED** stamp, then read the extrapolation it prints: the measured burn rate of the loop MAAT just stopped, projected over an unattended weekend.

## The real deployment (AMD Developer Cloud)

Live on an MI300X droplet for judging — dashboard: **http://129.212.191.62:8080**

```bash
cp .env.example .env    # UPSTREAM_MODE=fireworks, UPSTREAM_API_KEY=fw_..., HF_TOKEN=hf_...
docker compose -f docker-compose.yml -f docker-compose.amd.yml up --build -d
```

One command starts both tiers on one AMD GPU instance ([full steps](deploy/amd-developer-cloud.md)):

- **Primary tier**: Fireworks AI serverless — Kimi K2.6 at real prices ($0.95/$4.00 per 1M tokens, see [config/policies.amd.yaml](config/policies.amd.yaml))
- **$0 downgrade tier**: Gemma 3 4B served by vLLM **on the MI300X via ROCm** — near-budget workflows degrade to AMD-hosted Gemma instead of dying

Verified on real traffic: a retry loop carrying ~4.9k tokens/call on Kimi K2.6 was killed on its 3rd identical call — $0.0124 burned in 8.3s, a measured pace of ~$322 over an unattended weekend. A workflow at 95% budget kept answering, rerouted to on-GPU Gemma with its cost meter frozen.

### Try it against the live gateway

```python
from openai import OpenAI
client = OpenAI(base_url="http://129.212.191.62:8080/v1",
                api_key="maat-sk-keyed-demo-ROTATE-ME")  # public on purpose — read on
r = client.chat.completions.create(model="accounts/fireworks/models/gpt-oss-120b",
                                   max_tokens=300,  # reasoning models think before they speak
                                   messages=[{"role": "user", "content": "Who weighs the tokens?"}])
print(r.choices[0].message.content)
```

Yes, that key is public on purpose. It is bound to the `keyed-demo` workflow with a **$0.50 hard budget** — a leaked key bounded by MAAT costs at most its budget, which is the product. Unknown keys are rejected (`MAAT_REQUIRE_AUTH=true` on the deployment), the dashboard is read-only for visitors, and your call shows up on the live ledger.

## Workflow identity

```python
client = OpenAI(base_url="http://localhost:8080/v1",
                api_key="maat-sk-invoice-bot-...")   # the key IS the workflow
```

Assign each workflow an `api_key` in `policies.yaml`; the bearer key resolves the identity, so an agent can't spend another workflow's budget by lying in a header. Set `MAAT_REQUIRE_AUTH=true` to reject unknown keys. Without keys (dev mode), the `X-Workflow-Id` header is used. Works unchanged with LangChain, CrewAI, LlamaIndex, or raw HTTP, streaming included; responses carry `X-MAAT-Spent-USD` / `X-MAAT-Budget-USD`.

## Policies

`config/policies.yaml` sets per-workflow budgets, `mode: enforce|observe`, warn/downgrade thresholds, loop sensitivity (identical-call threshold, near-duplicate similarity, rate ceiling), pricing, and the optional local tier. Runtime controls: `POST /admin/workflows/{id}/kill | /resume | /budget`, all also buttons on the dashboard. Set `MAAT_ADMIN_TOKEN` to protect mutating admin routes.

## Running on AMD

Built for the AMD Developer Hackathon ACT II (Unicorn Track). The gateway runs on an AMD Developer Cloud MI300X droplet; the remote tier is Fireworks AI serverless; the downgrade tier is Gemma 3 4B on a vLLM OpenAI server on the same AMD GPU via ROCm — so Gemma lives where it counts, on AMD silicon, and near-budget workflows degrade to $0 on-GPU inference instead of dying. Full steps: [deploy/amd-developer-cloud.md](deploy/amd-developer-cloud.md).

## Overhead

Measured with `bench/overhead.py` (150 sequential requests against a local echo upstream, same host): direct p50 ~1.0 ms vs via-MAAT p50 ~8.3 ms — **~7 ms p50 / ~8 ms p95 added**, covering loop analysis, budget gating, SQLite accounting, and the event ledger. Against LLM calls that take 800–3,000 ms, that is noise — and unlike "zero-delay" pass-through meters, every one of those milliseconds is judgment.

## Honest limitations (v0.1)

Streaming cost uses upstream-reported usage when available and a character-based estimate otherwise. Near-duplicate detection is a similarity heuristic — tune it per fleet, or start in observe mode; embedding-based no-progress detection is on the roadmap. Protocol support is OpenAI-compatible chat completions; Anthropic and embeddings adapters are next. Budget gates are checked pre-call and settled post-call, so highly concurrent workflows can briefly overshoot a budget by a few in-flight calls; per-call cost reservation is on the roadmap.

## Tests

```bash
python -m pytest tests/ -q   # guard logic + full HTTP integration (kill, observe, key identity)
```

## Roadmap

Embedding-based no-progress detection; cost-velocity alerts; per-call cost reservation for concurrent workflows; Redis state backend and fail-open sidecar mode for HA; OpenTelemetry export; embeddings and completions endpoints; team budgets with monthly reset; Anthropic protocol adapter.

## License

MIT — see [LICENSE](LICENSE).
