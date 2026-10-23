"""Unit tests for context_report metrics calculation and formatting."""

from app.dev.context_report import CallMetric, TurnMetric, calculate_report, format_report, percentile


def test_percentile_empty_and_single() -> None:
    assert percentile([], 0.5) == 0.0
    assert percentile([100], 0.5) == 100.0
    assert percentile([100], 0.95) == 100.0


def test_percentile_interpolation() -> None:
    data = [10, 20, 30, 40, 50]
    assert percentile(data, 0.5) == 30.0
    assert percentile(data, 0.0) == 10.0
    assert percentile(data, 1.0) == 50.0


def test_calculate_report_empty() -> None:
    report = calculate_report([], [])
    assert report["turn_count"] == 0
    assert report["call_count"] == 0
    assert report["warm_rate"] == 0.0
    assert report["cache_hit_ratio"] == 0.0
    assert report["tokens_per_turn"] == 0.0


def test_calculate_report_with_metrics() -> None:
    turns = [
        TurnMetric(
            timings={
                "queue_wait_ms": 10,
                "page_resolve_ms": 50,
                "planner_ms": 1200,
                "first_delta_ms": 800,
                "executor_ms": 200,
                "total_ms": 1500,
                "warm_hit": "facts",
            },
            has_page=True,
        ),
        TurnMetric(
            timings={
                "queue_wait_ms": 15,
                "planner_ms": 1000,
                "first_delta_ms": 600,
                "total_ms": 1100,
                "warm_hit": "none",
            },
            has_page=True,
        ),
        TurnMetric(
            timings={
                "queue_wait_ms": 5,
                "planner_ms": 900,
                "total_ms": 950,
            },
            has_page=False,
        ),
    ]

    calls = [
        CallMetric(tokens_in=1000, tokens_cached=800, tokens_out=150, prefix_hash="hash1"),
        CallMetric(tokens_in=1200, tokens_cached=0, tokens_out=200, prefix_hash="hash2"),
    ]

    rep = calculate_report(turns, calls)
    assert rep["turn_count"] == 3
    assert rep["call_count"] == 2
    assert rep["turns_with_page"] == 2
    assert rep["warm_hits"] == 1
    assert rep["warm_rate"] == 0.5
    assert rep["total_in"] == 2200
    assert rep["total_cached"] == 800
    assert rep["total_out"] == 350
    assert round(rep["cache_hit_ratio"], 4) == round(800 / 2200, 4)
    assert round(rep["tokens_per_turn"], 1) == round(2550 / 3, 1)

    # Check stage percentiles
    stages = rep["stages"]
    assert stages["queue_wait_ms"]["count"] == 3
    assert stages["queue_wait_ms"]["p50"] == 10
    assert stages["page_resolve_ms"]["count"] == 1
    assert stages["planner_ms"]["count"] == 3
    assert stages["first_delta_ms"]["count"] == 2

    # Check format text table
    formatted = format_report(rep)
    assert "Context & Performance Report (3 turns, 2 model calls)" in formatted
    assert "Page warm hit rate:       1/2 (50.0%)" in formatted
    assert "Prompt cache hit ratio:   800/2200 tokens (36.4%)" in formatted
