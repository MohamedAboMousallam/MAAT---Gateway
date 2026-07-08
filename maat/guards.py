"""Runaway-loop detection and budget tiering. Pure logic, unit-testable."""
import time
from collections import defaultdict, deque
from difflib import SequenceMatcher


class LoopDetector:
    """Per-workflow sliding window over recent calls.

    Kills on: N exact-identical prompts, N near-duplicate user messages,
    or a call rate above 2x the throttle limit. Throttles above 1x.
    """

    def __init__(self, repeat_threshold=3, window_seconds=120,
                 similarity=0.92, rate_per_minute=30):
        self.repeat_threshold = repeat_threshold
        self.window_seconds = window_seconds
        self.similarity = similarity
        self.rate_per_minute = rate_per_minute
        self._calls = defaultdict(lambda: deque(maxlen=200))  # wf -> (ts, hash, last_user)

    def check_and_record(self, wf_id: str, prompt_hash: str,
                         last_user: str, now: float | None = None,
                         n_msgs: int = 0, total_chars: int = 0):
        """Returns (action, reasons). action in {'allow','throttle','kill'}.

        Near-duplicate detection is progress-aware: a growing conversation
        (more messages, or meaningfully more content) is a healthy multi-step
        agent whose original task naturally repeats as the last user message.
        Only stagnant conversations with repeating prompts count as loops.
        """
        now = now or time.time()
        window = self._calls[wf_id]
        cutoff = now - self.window_seconds
        recent = [c for c in window if c[0] >= cutoff]

        reasons = []
        exact = 1 + sum(1 for _, h, _, _, _ in recent if h == prompt_hash)
        if exact >= self.repeat_threshold:
            reasons.append(
                f"{exact} identical calls in {int(self.window_seconds)}s (runaway retry loop)")

        if last_user and not reasons:
            near = 1
            for _, h, prev, p_msgs, p_chars in list(recent)[-8:]:
                if h == prompt_hash or not prev:
                    continue
                grew = n_msgs > p_msgs or total_chars > p_chars * 1.02
                if grew:
                    continue  # new context since then = progress, not a loop
                if SequenceMatcher(None, last_user, prev).ratio() >= self.similarity:
                    near += 1
            if near >= self.repeat_threshold:
                reasons.append(
                    f"{near} near-duplicate prompts in {int(self.window_seconds)}s "
                    "with no new context (agent not making progress)")

        last_minute = sum(1 for t, _, _, _, _ in recent if t >= now - 60) + 1
        action = "allow"
        if reasons:
            action = "kill"
        elif last_minute > 2 * self.rate_per_minute:
            action = "kill"
            reasons.append(f"{last_minute} calls/min (hard rate ceiling)")
        elif last_minute > self.rate_per_minute:
            action = "throttle"
            reasons.append(f"{last_minute} calls/min above {self.rate_per_minute}/min limit")

        window.append((now, prompt_hash, (last_user or "")[:2000], n_msgs, total_chars))
        return action, reasons

    def forget(self, wf_id: str):
        self._calls.pop(wf_id, None)


def budget_tier(spent: float, budget: float, warn_at=0.70, downgrade_at=0.90) -> str:
    """'ok' | 'warn' | 'downgrade' | 'exceeded'"""
    if budget <= 0:
        return "exceeded"
    frac = spent / budget
    if frac >= 1.0:
        return "exceeded"
    if frac >= downgrade_at:
        return "downgrade"
    if frac >= warn_at:
        return "warn"
    return "ok"


def cost_usd(pricing: dict, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p = pricing.get(model) or pricing.get("default") or {"input_per_1m": 0, "output_per_1m": 0}
    return (prompt_tokens * p["input_per_1m"] + completion_tokens * p["output_per_1m"]) / 1_000_000
