# Deploying MAAT on AMD Developer Cloud (with a zero-cost ROCm tier)

Two services on one AMD GPU instance: the MAAT gateway, and a vLLM
OpenAI-compatible server on the GPU that acts as MAAT's **$0 downgrade
tier** — workflows near budget fall back to on-GPU Gemma instead of dying.

## 1. Provision

Create an AMD Developer Cloud GPU instance (an MI300X droplet works; any
ROCm-supported Instinct GPU is fine). SSH in and confirm the GPU:

```bash
rocm-smi          # should list the GPU
docker --version  # preinstalled on the AMD images; install if missing
```

## 2. Run vLLM on the GPU (official ROCm image)

vLLM publishes official ROCm images on Docker Hub as `vllm/vllm-openai-rocm`
(AMD's older `rocm/vllm*` images are deprecated in favor of these — check
the vLLM docs for the current tag):

```bash
docker run -d --name vllm \
  --device /dev/kfd --device /dev/dri \
  --group-add=video --ipc=host \
  --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  --env "HF_TOKEN=$HF_TOKEN" \
  -p 8000:8000 \
  vllm/vllm-openai-rocm:latest \
  --model google/gemma-3-4b-it --port 8000
```

Pick any Gemma size that fits the GPU; adjust `--max-model-len` if needed.
Verify: `curl localhost:8000/v1/models`.

## 3. Point MAAT at both tiers

```bash
git clone <your-repo> && cd maat
cp .env.example .env    # set UPSTREAM_MODE=fireworks + your fw_ key
```

Uncomment in `config/policies.yaml`:

```yaml
local_tier:
  base_url: http://172.17.0.1:8000/v1   # docker bridge to the vllm container
  model: google/gemma-3-4b-it
```

(If you run vLLM via compose in the same network, `http://vllm:8000/v1`.)

```bash
docker compose up --build -d
```

## 4. What you get

Requests route to Fireworks (AMD-hosted models) normally. At 90% of a
workflow's budget, MAAT reroutes it to the on-GPU Gemma at $0 — graceful
degradation on AMD silicon instead of a dead agent. The dashboard event
reads `downgrading to local AMD/ROCm tier`.

For the demo video: set a tiny budget, let a workflow cross 90%, and show
the same agent continuing to get answers with the cost meter frozen.
