"""Slack alerts via incoming webhook. No-op if SLACK_WEBHOOK_URL is unset."""
import httpx


class Alerter:
    def __init__(self, webhook_url: str | None):
        self.url = (webhook_url or "").strip() or None

    async def send(self, text: str):
        if not self.url:
            return
        try:
            async with httpx.AsyncClient(timeout=4) as client:
                await client.post(self.url, json={"text": text})
        except Exception:
            pass  # alerts must never take the gateway down
