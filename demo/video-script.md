# MAAT — demo video shot list (~3 min)

Everything below runs against the live AMD deployment and was verified on
real traffic. Screens: a browser on the dashboard (http://129.212.191.62:8080)
and a terminal SSH'd into the MI300X droplet at `/root/maat`.

## Pre-flight (before recording)

SSH into the droplet, then set up the demo shell — all four lines matter
(the demos need the venv's OpenAI SDK):

```bash
cd /root/maat
source /root/demo-venv/bin/activate            # OpenAI SDK lives here
export DEMO_MODEL=accounts/fireworks/models/kimi-k2p6
bash demo/reset_demo.sh                        # fresh ledger, vLLM stays up
```

Optional, for a cleaner `docker ps` frame in shot 2:
`docker stop rocm` (the quickstart JupyterLab — restore later with `docker start rocm`).

Browser: dashboard open, zoom so 2–3 workflow cards fill the frame.
Terminal: font large, `clear` before each shot.

## Shot 1 — hook (0:00–0:20, title or dashboard)

> "AI agents don't crash — they loop. A broken tool call retries the same
> prompt, with the same fat context, at full API price, at 2 a.m., on your
> key. MAAT is the kill switch. It's running right now on an AMD MI300X."

## Shot 2 — the stack (0:20–0:45, terminal)

```bash
rocm-smi                # the MI300X
docker ps               # maat gateway + vLLM serving Gemma on that GPU
```

> "One GPU, two services: the MAAT gateway, and Gemma 3 served by vLLM over
> ROCm. Agents change one line — the base_url."

## Shot 3 — normal traffic (0:45–1:05, split)

```bash
DEMO_MODEL=accounts/fireworks/models/gpt-oss-120b python demo/good_agent.py
```

> "A well-behaved agent: four calls to gpt-oss-120b through Fireworks, every
> token metered and attributed on the ledger." (Dashboard: demo-good card
> fills.) Note: the inline override is deliberate — the rogue and downgrade
> shots use Kimi K2.6 from the pre-flight export.

## Shot 4 — the kill (1:05–1:50, split) ★ the money shot

```bash
python demo/rogue_agent.py
```

Expected: two real calls (~4.9k tokens each), killed on the 3rd identical
attempt. Dashboard: red JUDGED stamp. Read the script's printout aloud:

> "It burned about a cent in eight seconds. Unguarded, that measured pace is
> ~$5/hour — over three hundred dollars for one unattended weekend, from one
> broken tool call."

Click **Incident report** — show the timeline and projection.

## Shot 5 — degrade, don't die (1:50–2:35, split)

```bash
python trigger_downgrade.py
```

Expected: two or three calls answered by Kimi (a gold budget warning lands in
the ledger), then the `downgraded` badge appears and replies switch to
`google/gemma-3-4b-it` — the Gemma on THIS GPU — while the cost meter freezes.

> "Near budget, MAAT doesn't execute your workflow — it reroutes it to Gemma
> on the same AMD GPU at zero dollars. The agent never stops answering."

## Shot 6 — close (2:35–3:00, code + dashboard)

```python
client = OpenAI(base_url="http://maat:8080/v1",
                api_key="maat-sk-invoice-bot-...")  # the key IS the workflow
```

> "Spoof-proof workflow identity, observe mode for risk-free tuning on prod
> traffic, OpenAI-shaped errors so SDKs fail clean. MAAT — every token,
> weighed."

## Retakes

`bash demo/reset_demo.sh` between takes — the ledger wipes, vLLM keeps
serving, nothing else changes.
