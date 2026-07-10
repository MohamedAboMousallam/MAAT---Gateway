"""A well-behaved agent: varied prompts, stays under budget.
Shows MAAT metering normal traffic without interfering.

Run:  python demo/good_agent.py
"""
import os

from openai import OpenAI

GATEWAY = os.getenv("MAAT_URL", "http://localhost:8080/v1")
MODEL = os.getenv("DEMO_MODEL", "gemma-mock-small")

client = OpenAI(base_url=GATEWAY, api_key="demo-key",
                default_headers={"X-Workflow-Id": "demo-good"})

TASKS = [
    "Summarize the tradeoffs of ECS Fargate vs EC2 launch type in two sentences.",
    "Write a one-line commit message for adding retry backoff to a Lambda.",
    "Name three signals that an AI agent is stuck in a loop.",
    "Explain per-workflow budget attribution to a finance stakeholder in 30 words.",
]

print(f"good-agent → {GATEWAY} (model={MODEL})\n")
for i, task in enumerate(TASKS, 1):
    r = client.chat.completions.create(model=MODEL, max_tokens=150, messages=[
        {"role": "system", "content": "Answer directly and concisely. No preamble."},
        {"role": "user", "content": task}])
    text = (r.choices[0].message.content or "").replace("\n", " ")[:90]
    print(f"  task {i}: {text}…")
print("\n  all tasks completed — check the dashboard for spend attribution.")
