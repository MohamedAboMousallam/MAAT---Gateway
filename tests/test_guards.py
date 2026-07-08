from maat.guards import LoopDetector, budget_tier, cost_usd


def test_kills_on_identical_repeats():
    d = LoopDetector(repeat_threshold=3, window_seconds=120)
    assert d.check_and_record("wf", "h1", "same prompt", now=100.0)[0] == "allow"
    assert d.check_and_record("wf", "h1", "same prompt", now=101.0)[0] == "allow"
    action, reasons = d.check_and_record("wf", "h1", "same prompt", now=102.0)
    assert action == "kill" and "identical" in reasons[0]


def test_allows_varied_prompts():
    d = LoopDetector(repeat_threshold=3)
    for i, msg in enumerate(["plan the sprint", "write the report",
                             "review the PR", "deploy to staging"]):
        action, _ = d.check_and_record("wf", f"h{i}", msg, now=100.0 + i)
        assert action == "allow"


def test_kills_on_near_duplicates():
    d = LoopDetector(repeat_threshold=3, similarity=0.9)
    base = "retry reading the file /tmp/report.csv attempt {}"
    a1, _ = d.check_and_record("wf", "hA", base.format(1), now=10.0)
    a2, _ = d.check_and_record("wf", "hB", base.format(2), now=11.0)
    a3, r = d.check_and_record("wf", "hC", base.format(3), now=12.0)
    assert (a1, a2) == ("allow", "allow")
    assert a3 == "kill" and "near-duplicate" in r[0]


def test_repeats_outside_window_do_not_kill():
    d = LoopDetector(repeat_threshold=3, window_seconds=60)
    d.check_and_record("wf", "h1", "x", now=0.0)
    d.check_and_record("wf", "h1", "x", now=100.0)
    action, _ = d.check_and_record("wf", "h1", "x", now=200.0)
    assert action == "allow"


def test_budget_tiers():
    assert budget_tier(0.10, 1.00) == "ok"
    assert budget_tier(0.75, 1.00) == "warn"
    assert budget_tier(0.95, 1.00) == "downgrade"
    assert budget_tier(1.00, 1.00) == "exceeded"
    assert budget_tier(0.01, 0.0) == "exceeded"


def test_cost_math():
    pricing = {"default": {"input_per_1m": 0.20, "output_per_1m": 0.80},
               "big": {"input_per_1m": 1.0, "output_per_1m": 4.0}}
    assert abs(cost_usd(pricing, "big", 1_000_000, 500_000) - 3.0) < 1e-9
    assert abs(cost_usd(pricing, "unknown", 1_000_000, 0) - 0.20) < 1e-9


def test_growing_conversation_is_progress_not_loop():
    """A healthy multi-step agent: same original task as last user message,
    but history grows every call. Must never be flagged."""
    d = LoopDetector(repeat_threshold=3, similarity=0.9)
    for i in range(6):
        action, _ = d.check_and_record(
            "wf", f"h{i}", "summarize the quarterly report", now=10.0 + i,
            n_msgs=1 + 2 * i, total_chars=500 + 400 * i)
        assert action == "allow", f"legit agent killed at step {i + 1}"


def test_stagnant_conversation_is_a_loop():
    """Same task, same conversation size, no new content = stuck agent."""
    d = LoopDetector(repeat_threshold=3, similarity=0.9)
    a1, _ = d.check_and_record("wf", "hA", "read the file and report",
                               now=10.0, n_msgs=5, total_chars=2000)
    a2, _ = d.check_and_record("wf", "hB", "read the file and report!",
                               now=11.0, n_msgs=5, total_chars=2010)
    a3, r = d.check_and_record("wf", "hC", "read the file and report",
                               now=12.0, n_msgs=5, total_chars=2005)
    assert (a1, a2) == ("allow", "allow")
    assert a3 == "kill" and "no new context" in r[0]
