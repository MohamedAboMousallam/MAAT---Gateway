"""Upstream LLM client.

Modes:
  mock      -> deterministic offline responses (demo without credits)
  fireworks -> forwards to any OpenAI-compatible /chat/completions endpoint
               (Fireworks AI by default; base URL and key from env)
"""
import asyncio
import json
import os
import random
import time

import httpx


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _last_user_text(messages: list) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            return str(c)
    return ""


class Upstream:
    def __init__(self, mode: str, base_url: str, api_key: str):
        self.mode = mode
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=120)

    # ---- non-streaming ------------------------------------------------------
    async def complete(self, payload: dict) -> tuple[int, dict]:
        if self.mode == "mock":
            return 200, await self._mock_completion(payload)
        try:
            r = await self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except httpx.TimeoutException:
            return 504, {"error": {"message": "upstream timed out",
                                   "type": "upstream_error", "code": "upstream_timeout"}}
        except httpx.HTTPError as e:
            return 502, {"error": {"message": f"upstream unreachable ({e.__class__.__name__})",
                                   "type": "upstream_error", "code": "upstream_unreachable"}}
        try:
            body = r.json()
        except Exception:
            body = {"error": {"message": r.text[:500], "type": "upstream_error"}}
        return r.status_code, body

    # ---- streaming -----------------------------------------------------------
    async def stream(self, payload: dict):
        """Yields raw SSE bytes; final item is ('__usage__', dict) sentinel."""
        if self.mode == "mock":
            async for item in self._mock_stream(payload):
                yield item
            return

        payload = dict(payload)
        if os.getenv("MAAT_INJECT_STREAM_USAGE", "true").lower() != "false":
            so = dict(payload.get("stream_options") or {})
            so["include_usage"] = True
            payload["stream_options"] = so

        usage = None
        content_chars = 0
        async with self._client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
        ) as r:
            async for line in r.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() and data.strip() != "[DONE]":
                        try:
                            obj = json.loads(data)
                            if obj.get("usage"):
                                usage = obj["usage"]
                            for ch in obj.get("choices", []):
                                content_chars += len(
                                    (ch.get("delta") or {}).get("content") or "")
                        except Exception:
                            pass
                yield (line + "\n").encode()
        if usage is None:  # upstream didn't report usage; estimate output side
            usage = {
                "prompt_tokens": _est_tokens(json.dumps(payload.get("messages", []))),
                "completion_tokens": max(1, content_chars // 4),
            }
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        yield ("__usage__", usage)

    # ---- mock implementation -------------------------------------------------
    async def _mock_body(self, payload: dict) -> tuple[str, dict]:
        last = _last_user_text(payload.get("messages", []))
        if "FAIL_TOOL" in last:
            text = ("Error: tool `read_file` failed with ENOENT on "
                    "/tmp/report.csv. The file was not found. You could retry "
                    "the same call in case the file appears.")
        else:
            text = (f"Mock answer ({payload.get('model', 'mock')}): "
                    f"{last[:120] or 'Hello from MAAT mock upstream.'} "
                    "— this response was generated offline; flip UPSTREAM_MODE="
                    "fireworks to use real models.")
        pt = _est_tokens(json.dumps(payload.get("messages", [])))
        ct = _est_tokens(text) + random.randint(20, 80)
        usage = {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}
        await asyncio.sleep(random.uniform(0.15, 0.35))
        return text, usage

    async def _mock_completion(self, payload: dict) -> dict:
        text, usage = await self._mock_body(payload)
        return {
            "id": f"chatcmpl-maatmock-{int(time.time()*1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model", "mock"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": usage,
        }

    async def _mock_stream(self, payload: dict):
        text, usage = await self._mock_body(payload)
        base = {"id": f"chatcmpl-maatmock-{int(time.time()*1000)}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": payload.get("model", "mock")}
        words = text.split(" ")
        step = max(1, len(words) // 6)
        for i in range(0, len(words), step):
            chunk = dict(base, choices=[{
                "index": 0,
                "delta": {"content": " ".join(words[i:i + step]) + " "},
                "finish_reason": None,
            }])
            yield f"data: {json.dumps(chunk)}\n\n".encode()
            await asyncio.sleep(0.05)
        final = dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}],
                     usage=usage)
        yield f"data: {json.dumps(final)}\n\n".encode()
        yield b"data: [DONE]\n\n"
        yield ("__usage__", usage)

    async def aclose(self):
        await self._client.aclose()
