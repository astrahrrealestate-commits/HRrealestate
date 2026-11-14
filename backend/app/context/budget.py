"""Enforcing a ContextSpec's declared budgets (spec: 2026-10-23-agent-memory-context-design §7.1).

Each slice is clipped to its own `budget_chars`; if the slices together still exceed `total_chars`, slices give way
in `drop_order` (lowest first) until the prompt fits. Text under budget is returned byte-identical, so a small prompt
is never changed by this module.
"""

from collections.abc import Mapping

from app.context.spec import ContextSpec

TRIM_MARKER = "\n[…trimmed]"


def clip(text: str, limit: int) -> str:
    """At most `limit` characters; a cut prefers a line boundary and ends with a visible marker."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    room = limit - len(TRIM_MARKER)
    if room <= 0:
        return text[:limit]
    head = text[:room]
    line_end = head.rfind("\n")
    if line_end >= room // 2:
        head = head[:line_end]
    return head.rstrip() + TRIM_MARKER


def fit_to_budget(spec: ContextSpec, contents: Mapping[str, str]) -> tuple[dict[str, str], tuple[str, ...]]:
    """Clip each declared slice to its budget, then trim in `drop_order` until `total_chars` holds.

    Returns the fitted contents (names outside the spec pass through untouched) and the names squeezed to nothing.
    """
    fitted = dict(contents)
    for s in spec.slices:
        if s.name in fitted:
            fitted[s.name] = clip(fitted[s.name], s.budget_chars)

    overflow = sum(len(fitted[s.name]) for s in spec.slices if s.name in fitted) - spec.total_chars
    dropped: list[str] = []
    for s in sorted(spec.slices, key=lambda sl: sl.drop_order):
        if overflow <= 0:
            break
        text = fitted.get(s.name)
        if not text:
            continue
        shrunk = clip(text, max(0, len(text) - overflow))
        overflow -= len(text) - len(shrunk)
        fitted[s.name] = shrunk
        if not shrunk:
            dropped.append(s.name)
    return fitted, tuple(dropped)
