"""Context & Turn measurement report (spec: 2026-10-23-agent-memory-context-design §9, Task C1).

Prints p50/p95 per stage, warm hit rate, prompt cache hit ratio and tokens per turn over the last N turns.
CLI: python -m app.dev.context_report [--turns 100]
"""

import argparse
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.settings import Settings, get_settings
from app.db.models import AgentTurn, ModelCall
from app.db.session import make_engine


@dataclass(frozen=True)
class TurnMetric:
    timings: dict[str, Any]
    has_page: bool


@dataclass(frozen=True)
class CallMetric:
    tokens_in: int
    tokens_cached: int
    tokens_out: int
    prefix_hash: str | None


def percentile(values: Sequence[float | int], p: float) -> float:
    """Calculate the p-th percentile (0.0 to 1.0) of values."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(s[int(k)])
    d0 = float(s[f]) * (c - k)
    d1 = float(s[c]) * (k - f)
    return d0 + d1


STAGE_KEYS = (
    ("queue_wait_ms", "Queue wait"),
    ("page_resolve_ms", "Page resolve"),
    ("planner_ms", "Planner model"),
    ("first_delta_ms", "First visible delta"),
    ("executor_ms", "Executor"),
    ("total_ms", "Total turn"),
)


def calculate_report(turns: Sequence[TurnMetric], calls: Sequence[CallMetric]) -> dict[str, Any]:
    """Pure calculation of report metrics from turn and call objects."""
    stage_stats: dict[str, dict[str, Any]] = {}
    for key, label in STAGE_KEYS:
        vals = [int(t.timings[key]) for t in turns if key in t.timings and isinstance(t.timings[key], int | float)]
        stage_stats[key] = {
            "label": label,
            "count": len(vals),
            "p50": round(percentile(vals, 0.50)),
            "p95": round(percentile(vals, 0.95)),
        }

    turns_with_page = [t for t in turns if t.has_page]
    warm_hits = sum(1 for t in turns_with_page if t.timings.get("warm_hit") in ("facts", "blocks"))
    warm_rate = (warm_hits / len(turns_with_page)) if turns_with_page else 0.0

    total_in = sum(c.tokens_in for c in calls)
    total_cached = sum(c.tokens_cached for c in calls)
    total_out = sum(c.tokens_out for c in calls)
    cache_hit_ratio = (total_cached / total_in) if total_in > 0 else 0.0
    tokens_per_turn = ((total_in + total_out) / len(turns)) if turns else 0.0

    return {
        "turn_count": len(turns),
        "call_count": len(calls),
        "stages": stage_stats,
        "warm_hits": warm_hits,
        "turns_with_page": len(turns_with_page),
        "warm_rate": warm_rate,
        "total_in": total_in,
        "total_cached": total_cached,
        "total_out": total_out,
        "cache_hit_ratio": cache_hit_ratio,
        "tokens_per_turn": tokens_per_turn,
    }


def format_report(report: dict[str, Any]) -> str:
    """Format the report dictionary into an aligned text table."""
    lines: list[str] = [
        "=======================================================================",
        f"Context & Performance Report ({report['turn_count']} turns, {report['call_count']} model calls)",
        "=======================================================================",
        f"{'Stage':<24} {'Count':<8} {'p50 (ms)':<12} {'p95 (ms)':<12}",
        "-----------------------------------------------------------------------",
    ]
    for key, _ in STAGE_KEYS:
        st = report["stages"][key]
        lines.append(f"{st['label']:<24} {st['count']:<8} {st['p50']:<12} {st['p95']:<12}")

    lines.append("-----------------------------------------------------------------------")
    w_hits = report["warm_hits"]
    w_total = report["turns_with_page"]
    w_pct = report["warm_rate"] * 100
    lines.append(f"Page warm hit rate:       {w_hits}/{w_total} ({w_pct:.1f}%)")

    c_in = report["total_in"]
    c_cached = report["total_cached"]
    c_pct = report["cache_hit_ratio"] * 100
    lines.append(f"Prompt cache hit ratio:   {c_cached}/{c_in} tokens ({c_pct:.1f}%)")
    lines.append(f"Tokens per turn (avg):    {report['tokens_per_turn']:.1f}")
    lines.append("=======================================================================")
    return "\n".join(lines)


def run_report(settings: Settings, limit: int = 100) -> str:
    engine = make_engine(str(settings.database_url))
    with Session(engine) as session:
        turns_rows = session.scalars(select(AgentTurn).order_by(desc(AgentTurn.created_at)).limit(limit)).all()
        calls_rows = session.scalars(select(ModelCall).order_by(desc(ModelCall.created_at)).limit(limit * 3)).all()

    turn_metrics = [TurnMetric(timings=row.timings or {}, has_page=row.page_context is not None) for row in turns_rows]
    call_metrics = [
        CallMetric(
            tokens_in=row.tokens_in or 0,
            tokens_cached=row.tokens_cached or 0,
            tokens_out=row.tokens_out or 0,
            prefix_hash=row.prefix_hash,
        )
        for row in calls_rows
    ]
    return format_report(calculate_report(turn_metrics, call_metrics))


def main() -> None:
    parser = argparse.ArgumentParser(description="Context and turn metrics report")
    parser.add_argument("--turns", type=int, default=100, help="Number of turns to analyze (default: 100)")
    args = parser.parse_args()
    sys.stdout.write(run_report(get_settings(), limit=args.turns) + "\n")


if __name__ == "__main__":
    main()
