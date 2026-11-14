"""Unit tests for conversation summary (Task C9)."""

from unittest.mock import MagicMock
from uuid import uuid4

from app.context.conversation_summary import (
    count_unsummarized_turns,
    should_summarize,
    summarize_conversation_rolling,
    update_conversation_summary,
)


def test_should_summarize_threshold() -> None:
    assert not should_summarize(0)
    assert not should_summarize(5)
    assert should_summarize(6)
    assert should_summarize(12)


def test_summarize_conversation_rolling() -> None:
    exchanges = [
        ("What is the status of the roof leak?", "The plumber is scheduled for tomorrow at 10:00."),
        ("Has the tenant paid rent?", "Yes, rent was paid on the 1st."),
    ]
    summary = summarize_conversation_rolling("", exchanges)
    assert "What is the status of the roof leak?" in summary
    assert "The plumber is scheduled" in summary

    # Incremental update with previous summary
    new_exchanges = [("Can you call the contractor?", "Drafting a call notice now.")]
    updated = summarize_conversation_rolling(summary, new_exchanges)
    assert "Earlier:" in updated
    assert "Can you call the contractor?" in updated


def test_count_unsummarized_turns() -> None:
    session = MagicMock()
    session.scalar.return_value = 6
    company_id = uuid4()
    conv_id = uuid4()

    count = count_unsummarized_turns(session, company_id, conv_id)
    assert count == 6


def test_update_conversation_summary_cas() -> None:
    session = MagicMock()
    session.execute.return_value.rowcount = 1
    company_id = uuid4()
    conv_id = uuid4()
    turn_id = uuid4()

    updated = update_conversation_summary(
        session,
        company_id,
        conv_id,
        "New rolling summary",
        turn_id,
        expected_version=2,
    )
    assert updated is True
    session.expire_all.assert_called_once()
