"""Minimal OpenAI-compatible echo upstream. Used only to measure MAAT's
own overhead: run me on :9000, point MAAT at me, compare direct vs via-MAAT.
    uvicorn bench.echo_upstream:app --port 9000
"""
from fastapi import FastAPI

app = FastAPI()


@app.post("/v1/chat/completions")
async def cc(body: dict):
    return {"id": "echo", "object": "chat.completion",
            "model": body.get("model", "echo"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 60, "completion_tokens": 8,
                      "total_tokens": 68}}
