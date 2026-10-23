"""`redraft.classify`: which redraft path a message's actions lead to (pure; the queries are integration-tested)."""

import pytest

from app.contracts import ActionType
from app.db.enums import ActionStatus
from app.pipeline.redraft import classify

R, E, N = ActionType.reply_draft, ActionType.escalate, ActionType.notify_owner
PENDING, APPROVED, REJECTED = ActionStatus.pending_approval, ActionStatus.approved, ActionStatus.rejected
EXCEPTION, PAUSED = ActionStatus.exception, ActionStatus.paused


@pytest.mark.parametrize(
    ("actions", "live", "kind"),
    [
        ([], False, "new"),
        ([(R, PENDING)], True, "pending"),  # a live pending reply approval: superseded
        ([(R, PENDING), (E, PENDING)], True, "pending"),
        ([(R, PENDING)], False, "busy"),  # approval edited (24 h window) or not opened yet: never redrafted
        ([(R, PENDING), (R, REJECTED)], False, "busy"),
        ([(R, REJECTED)], False, "decided"),
        ([(R, APPROVED), (E, PENDING)], False, "decided"),  # a pending escalation does not block a fresh reply
        ([(E, PENDING)], False, "no_reply"),  # only other actions: a first reply, not "already decided"
        ([(N, PENDING)], False, "no_reply"),  # the could-not-draft notice
        ([(E, APPROVED)], False, "no_reply"),
        ([(R, EXCEPTION)], False, "held"),  # suspicious or an unverified link
        ([(R, PAUSED), (E, PAUSED)], False, "held"),
        ([(R, REJECTED), (E, EXCEPTION)], False, "held"),
    ],
)
def test_every_state_combination(actions: list[tuple[ActionType, ActionStatus]], live: bool, kind: str) -> None:
    assert classify(actions, live) == kind
