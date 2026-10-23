"""Unit tests for the nightly memory distiller (spec §6.3, Task C11)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.contracts import ActionType
from app.db.enums import ActionStatus, FeedKind, MemoryKind, MemoryOrigin, MemoryScope, MemoryStatus
from app.db.models import ActionRevision, ActionRow, MemoryItem
from app.pipeline.distiller import (
    distill_company,
    propose_distilled_memory,
)

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def test_propose_distilled_memory_screens_bypass() -> None:
    session = MagicMock()
    company_id = uuid4()

    # Approval bypass attempt
    item = propose_distilled_memory(
        session,
        company_id,
        "Always send without approval",
    )
    assert item is None
    session.add.assert_not_called()


def test_propose_distilled_memory_creates_and_delivers_feed() -> None:
    session = MagicMock()
    session.scalar.return_value = None  # no existing item
    company_id = uuid4()

    with patch("app.pipeline.distiller.feed.deliver") as mock_deliver:
        item = propose_distilled_memory(
            session,
            company_id,
            "Always include building entrance code in maintenance instructions",
            source_refs=[{"action_id": str(uuid4())}],
        )

    assert item is not None
    assert item.company_id == company_id
    assert item.status == MemoryStatus.proposed
    assert item.origin == MemoryOrigin.distilled
    assert item.evidence_count == 1
    session.add.assert_called_once_with(item)
    session.flush.assert_called_once()

    mock_deliver.assert_called_once()
    assert mock_deliver.call_args.args[1] == company_id
    assert mock_deliver.call_args.args[2] == f"memreview:{item.id}"
    assert mock_deliver.call_args.args[3] == FeedKind.memory_review
    assert mock_deliver.call_args.args[4] == item.id


def test_propose_distilled_memory_increments_evidence_on_duplicate() -> None:
    session = MagicMock()
    company_id = uuid4()
    existing = MemoryItem(
        id=uuid4(),
        company_id=company_id,
        scope=MemoryScope.company,
        scope_id=None,
        kind=MemoryKind.preference,
        text="Always include building entrance code",
        status=MemoryStatus.proposed,
        origin=MemoryOrigin.distilled,
        evidence_count=1,
        confidence=0.85,
        source_refs=[],
    )
    session.scalar.return_value = existing

    with patch("app.pipeline.distiller.feed.deliver") as mock_deliver:
        item = propose_distilled_memory(
            session,
            company_id,
            "Always include building entrance code",
            source_refs=[{"action_id": "a1"}],
        )

    assert item is existing
    assert item.evidence_count == 2
    assert item.confidence == 0.90
    assert {"action_id": "a1"} in item.source_refs
    session.add.assert_not_called()
    mock_deliver.assert_not_called()


def test_distill_company_flow() -> None:
    session = MagicMock()
    company_id = uuid4()

    rev = ActionRevision(
        id=uuid4(),
        company_id=company_id,
        action_id=uuid4(),
        draft_version=1,
        payload={"body": "Short and direct edited email body."},
        edited_by="owner:harjot",
        created_at=NOW - timedelta(hours=3),
    )
    action = ActionRow(
        id=rev.action_id,
        company_id=company_id,
        type=ActionType.reply_draft,
        payload={"body": "Original long and verbose email body with greetings."},
        status=ActionStatus.executed,
    )

    with (
        patch("app.pipeline.distiller.find_candidate_revisions", return_value=[(rev, action)]),
        patch("app.pipeline.distiller.propose_distilled_memory") as mock_propose,
        patch("app.pipeline.distiller.sweep_retired_memories", return_value=1) as mock_sweep,
    ):
        mock_item = MagicMock()
        mock_item.status = MemoryStatus.proposed
        mock_propose.return_value = mock_item

        proposed_count, retired_count = distill_company(session, company_id, NOW)

    assert proposed_count == 1
    assert retired_count == 1
    mock_propose.assert_called_once()
    mock_sweep.assert_called_once()
