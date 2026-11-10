"""The step badges shown under a Super Agent answer: real steps only, never labels made up from keywords."""

_DRAFT_STEPS = ["Retrieved ticket context", "Prepared draft reply", "Queued for approval"]
_CHATTER = ("opening ", "which", "not waiting", "based on active portfolio", "open tasks:", "are you", "can you")
_CHATTER_ANYWHERE = (*_CHATTER, "what do you mean")
_MAX_STEP = 80


def _is_chatter(step: str) -> bool:
    low = step.lower()
    return (
        any(p in low for p in _CHATTER_ANYWHERE)
        or (len(step) > 90 and not step.startswith("⚠️"))
        or low.startswith("first,")
    )


def display_steps(steps: list[str], *, has_draft_card: bool) -> list[str]:
    """Steps worth showing. Model chatter or no steps at all show nothing, except the fixed draft steps when a
    draft card was really prepared."""
    if not steps or any(_is_chatter(s) for s in steps):
        return list(_DRAFT_STEPS) if has_draft_card else []
    shown: list[str] = []
    for step in steps:
        if len(step) > _MAX_STEP:
            shown.append(step[: _MAX_STEP - 3] + "...")
        else:
            shown.append(step)
    return shown
