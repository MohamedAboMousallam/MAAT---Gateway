# MAAT — 2:00 demo video storyboard

Screen recording + voiceover. No face needed. Record at 1080p, terminal
font large. Two windows side by side: terminal (left), dashboard (right).

**0:00–0:15 — The hook (cold open, rogue loop running)**
Terminal shows `rogue_agent.py` retrying; dashboard spend beam climbing.
VO: "This agent's tool broke an hour ago. It didn't crash — it's retrying
the same call, with the same huge context, on a frontier model. Agents
don't fail loudly. They fail expensively."

**0:15–0:35 — The problem**
Static slide or dashboard zoom. VO: "Provider spend caps are account-wide
and after the fact. Kill switches are emerging, but most are blunt — N calls
per minute, then dead — which kills healthy agents too. MAAT judges
*progress*: growing conversations pass, stagnant loops get executed."

**0:35–1:05 — The kill (money shot)**
Rerun rogue agent live. On attempt 3: 403 in terminal, JUDGED stamp on the
dashboard, Slack notification pops. Read the burn-rate line out loud:
"MAAT caught it in under three seconds. Unguarded, this loop was pacing
thousands of dollars by Monday."

**1:05–1:25 — One line to adopt + attribution**
Show the base_url diff and the good agent running. VO: "Adoption is one
line — change the base URL. Every workflow gets a budget, an identity via
its API key, and a ledger. Finance finally knows *which* agent spent what."

**1:25–1:45 — AMD moment (graceful degradation)**
Show a workflow crossing 90%: event reads "downgrading to local AMD/ROCm
tier", answers keep flowing, cost meter frozen at $0. VO: "Near budget,
MAAT reroutes to Gemma running on this AMD GPU via ROCm and vLLM — the
agent degrades gracefully on AMD silicon instead of dying."

**1:45–2:00 — Close**
Dashboard wide shot. VO: "Observe mode for safe rollout, kill switches for
bad nights. MAAT — every token, weighed. Built solo on AMD Developer Cloud,
Fireworks AI, and Gemma. MIT-licensed, containerized, running now."

Tips: record the kill and downgrade segments with UPSTREAM_MODE=fireworks (real models — judges discount mock footage); rehearse twice, record in one take, kill notifications except Slack,
and keep the cursor still while talking.
