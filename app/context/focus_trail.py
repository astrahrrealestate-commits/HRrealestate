"""T1 Session Memory: Focus trail for tracking the owner's last visited entities (spec §6.1, Task C9).

The focus trail tracks up to 5 recently visited pages/entities without requiring model calls.
"""

from typing import Any

from app.contracts import PageContext

MAX_FOCUS_TRAIL = 5


def page_to_focus_item(page: PageContext) -> dict[str, Any]:
    """Extract view and primary entity identifiers from a PageContext."""
    item: dict[str, Any] = {"view": page.view.value}
    if page.case_id is not None:
        item["case_id"] = str(page.case_id)
    if page.approval_id is not None:
        item["approval_id"] = str(page.approval_id)
    if page.task_ref:
        item["task_ref"] = page.task_ref
    if page.attachment_id is not None:
        item["attachment_id"] = str(page.attachment_id)
    if page.thread_key:
        item["thread_key"] = page.thread_key
    return item


def append_focus_trail(
    trail: list[dict[str, Any]],
    item: dict[str, Any],
    max_items: int = MAX_FOCUS_TRAIL,
) -> list[dict[str, Any]]:
    """Prepend item to trail if it has an entity reference, keeping up to max_items without consecutive duplicates."""
    # Only track pages that actually focus on a specific entity
    has_entity = any(k in item for k in ("case_id", "approval_id", "task_ref", "attachment_id", "thread_key"))
    if not has_entity:
        return list(trail)

    # Do not duplicate if identical to most recent entry
    if trail and trail[0] == item:
        return list(trail)

    filtered = [x for x in trail if x != item]
    return [item, *filtered][:max_items]


def render_focus_trail(trail: list[dict[str, Any]]) -> str:
    """Format focus trail into a compact 1-line string for session prompt injection."""
    if not trail:
        return ""
    entries: list[str] = []
    for item in trail:
        parts: list[str] = [f"view:{item.get('view', 'other')}"]
        for key in ("case_id", "approval_id", "task_ref", "attachment_id", "thread_key"):
            if key in item:
                val = item[key]
                if key.endswith("_id") and isinstance(val, str) and len(val) == 36:
                    val = val[:8]  # short prefix for token efficiency
                parts.append(f"{key}:{val}")
        entries.append(" ".join(parts))
    return "Focus trail: " + " -> ".join(entries)
