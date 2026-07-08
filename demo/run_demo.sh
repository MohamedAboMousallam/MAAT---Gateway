#!/usr/bin/env bash
# Full demo: good agent meters normally, rogue agent gets judged.
set -e
echo "── good agent (normal traffic) ──────────────────────"
python demo/good_agent.py
echo
echo "── rogue agent (runaway retry loop) ─────────────────"
python demo/rogue_agent.py
echo
echo "── gateway state ────────────────────────────────────"
curl -s localhost:8080/admin/state | python -m json.tool | head -40
