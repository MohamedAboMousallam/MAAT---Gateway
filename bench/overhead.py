"""Measures the latency MAAT adds to a request.

Prereqs (same host):
  1. echo upstream:  uvicorn bench.echo_upstream:app --port 9000
  2. MAAT pointed at it:
       UPSTREAM_MODE=fireworks UPSTREAM_BASE_URL=http://127.0.0.1:9000/v1 \
       uvicorn maat.main:app --port 8080

Each request uses a unique workflow id so the loop guard (correctly)
doesn't judge the benchmark itself as a runaway loop.
"""
import statistics
import time

import httpx

N, WARMUP = 150, 10
PAYLOAD = {"model": "bench",
           "messages": [{"role": "user", "content": "ping " + "x" * 200}]}


def run(url: str, wf_prefix: str | None):
    lat = []
    with httpx.Client(timeout=10) as c:
        for i in range(N + WARMUP):
            headers = {"X-Workflow-Id": f"{wf_prefix}-{i}"} if wf_prefix else {}
            t = time.perf_counter()
            c.post(url, json=PAYLOAD, headers=headers).raise_for_status()
            ms = (time.perf_counter() - t) * 1000
            if i >= WARMUP:
                lat.append(ms)
    lat.sort()
    return lat


def pct(lat, p):
    return lat[int(len(lat) * p)]


direct = run("http://127.0.0.1:9000/v1/chat/completions", None)
via = run("http://127.0.0.1:8080/v1/chat/completions", "bench")

d50, d95 = statistics.median(direct), pct(direct, 0.95)
v50, v95 = statistics.median(via), pct(via, 0.95)
print(f"direct   p50 {d50:6.2f} ms   p95 {d95:6.2f} ms")
print(f"via MAAT p50 {v50:6.2f} ms   p95 {v95:6.2f} ms")
print(f"overhead p50 {v50 - d50:6.2f} ms   p95 {v95 - d95:6.2f} ms   (n={N})")
