# Deploying MAAT on AMD Developer Cloud (with a zero-cost ROCm tier)

Two services on one AMD GPU instance, one compose command: the MAAT gateway,
and a vLLM OpenAI-compatible server on the GPU that acts as MAAT's **$0
downgrade tier** — workflows near budget fall back to on-GPU Gemma instead
of dying.

## 1. Provision

Create an AMD Developer Cloud GPU droplet (an MI300X droplet works; any
ROCm-supported Instinct GPU is fine). SSH in and confirm the GPU:

```bash
rocm-smi          # should list the GPU
docker --version  # preinstalled on the AMD images; install if missing
```

## 2. Clone and configure

```bash
git clone https://github.com/MohamedAboMousallam/MAAT---Gateway.git maat && cd maat
cp .env.example .env
```

Edit `.env`:

```bash
UPSTREAM_MODE=fireworks
UPSTREAM_API_KEY=fw_...        # your Fireworks key
HF_TOKEN=hf_...                # pulls gated Gemma weights for the vLLM tier
VLLM_MODEL=google/gemma-3-4b-it
```

Real model IDs and Fireworks serverless pricing are already set in
[config/policies.amd.yaml](../config/policies.amd.yaml) (Gemma 3 27B primary
at $0.90/1M, small Gemma fallback), which the AMD compose overlay selects
automatically.

## 3. Launch both tiers

```bash
docker compose -f docker-compose.yml -f docker-compose.amd.yml up --build -d
```

This starts MAAT on `:8080` and vLLM (official ROCm image,
`vllm/vllm-openai-rocm`) serving Gemma on the GPU at `:8000` (host-local).
First boot downloads the model weights — watch with
`docker compose logs -f vllm` until it reports the server is running, then:

```bash
curl -s localhost:8000/v1/models   # the on-GPU Gemma
curl -s localhost:8080/healthz     # MAAT, upstream_mode: fireworks
```

## 4. What you get

Requests route to Fireworks (AMD-hosted Gemma 3 27B) normally. At 90% of a
workflow's budget, MAAT reroutes it to the on-GPU Gemma at $0 — graceful
degradation on AMD silicon instead of a dead agent. The dashboard event
reads `downgrading to local AMD/ROCm tier`.

For the demo video: run `python trigger_downgrade.py` with
`DEMO_MODEL=accounts/fireworks/models/gemma-3-27b-it` — the tiny `gpu-demo`
budget crosses 90% within a few calls, and you watch the same agent keep
getting answers with the cost meter frozen.
