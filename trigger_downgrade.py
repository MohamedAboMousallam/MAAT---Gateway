"""Drive the gpu-demo workflow across its downgrade threshold, so you can
watch MAAT reroute it to the $0 local AMD/ROCm tier live on the dashboard.

Run:  python trigger_downgrade.py            (against mock)
      DEMO_MODEL=accounts/fireworks/models/gemma-3-27b-it python trigger_downgrade.py
"""
import os
from openai import OpenAI

MODEL = os.getenv("DEMO_MODEL", "gemma-mock-large")
c = OpenAI(base_url=os.getenv("MAAT_URL", "http://localhost:8080/v1"),
           api_key="demo", default_headers={"X-Workflow-Id": "gpu-demo"})
TASKS = [
    "Explain ECS task placement in one sentence.",
    "One-line commit message for fixing a Lambda timeout.",
    "Name two signs an agent is stuck in a loop.",
    "Define blue/green deployment in ten words.",
    "What does rocm-smi show? One sentence.",
    "Why cap agent budgets? One sentence.",
    "Describe vLLM in one sentence.",
    "What is graceful degradation? One sentence.",
]
for i, t in enumerate(TASKS, 1):
    r = c.chat.completions.create(model=MODEL, max_tokens=150, messages=[
        {"role": "system", "content": "Answer directly and concisely. No preamble."},
        {"role": "user", "content": t}])
    print(f"call {i}: {r.model} -> {r.choices[0].message.content[:70]}")
