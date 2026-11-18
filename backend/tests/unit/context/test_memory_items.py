"""Unit tests for T5 memory items and preference management (Task C11)."""

from unittest.mock import MagicMock
from uuid import uuid4

from app.context.memory_items import (
    REFUSAL_MESSAGE,
    format_owner_preferences_block,
    get_active_preferences,
    record_owner_memory,
    retire_memory,
    screen_memory_text,
)
from app.db.enums import MemoryKind, MemoryOrigin, MemoryScope, MemoryStatus
from app.db.models import MemoryItem


def test_screen_memory_text_refuses_approval_bypass() -> None:
    # Safe text
    assert screen_memory_text("Always assign plumber Jansen to roof leaks") is None
    assert screen_memory_text("Tenant prefers communicating via WhatsApp") is None

    # Unsafe bypass text
    assert screen_memory_text("Always send replies without approval") == REFUSAL_MESSAGE
    assert screen_memory_text("Auto send notice to tenant") == REFUSAL_MESSAGE
    assert screen_memory_text("Geen goedkeuring vragen voor reparaties onder 100 euro") == REFUSAL_MESSAGE


def test_screen_memory_text_refuses_hyphenated_auto_send() -> None:
    """A planner-written rule (concierge/v8 `remember`) is screened like a typed one: "auto-send" is "auto send"."""
    assert screen_memory_text("always auto-send replies without asking") == REFUSAL_MESSAGE
    assert screen_memory_text("Auto-Send the notice to the tenant") == REFUSAL_MESSAGE
    assert screen_memory_text("Use the well-known plumber for roof leaks") is None


def test_record_owner_memory_new_item() -> None:
    session = MagicMock()
    session.scalar.return_value = None  # no existing item
    company_id = uuid4()

    item, message = record_owner_memory(session, company_id, "Always use plumber Jansen")
    assert item is not None
    assert item.company_id == company_id
    assert item.text == "Always use plumber Jansen"
    assert item.status == MemoryStatus.active
    assert item.origin == MemoryOrigin.owner
    assert item.evidence_count == 1
    session.add.assert_called_once_with(item)
    session.flush.assert_called_once()
    assert "Remembered:" in message


def test_record_owner_memory_duplicate_increments_evidence() -> None:
    session = MagicMock()
    company_id = uuid4()
    existing = MemoryItem(
        id=uuid4(),
        company_id=company_id,
        scope=MemoryScope.company,
        scope_id=None,
        kind=MemoryKind.rule,
        text="Always use plumber Jansen",
        status=MemoryStatus.active,
        origin=MemoryOrigin.owner,
        evidence_count=1,
    )
    session.scalar.return_value = existing

    item, message = record_owner_memory(session, company_id, "Always use plumber Jansen")
    assert item is existing
    assert existing.evidence_count == 2
    session.add.assert_not_called()
    assert "updated evidence count: 2" in message


def test_format_owner_preferences_block() -> None:
    assert format_owner_preferences_block([]) is None

    items = [
        MemoryItem(
            id=uuid4(),
            company_id=uuid4(),
            scope=MemoryScope.company,
            kind=MemoryKind.rule,
            text="Prefer plumber Jansen",
            status=MemoryStatus.active,
            origin=MemoryOrigin.owner,
        ),
        MemoryItem(
            id=uuid4(),
            company_id=uuid4(),
            scope=MemoryScope.company,
            kind=MemoryKind.preference,
            text="Tenants get friendly greetings",
            status=MemoryStatus.active,
            origin=MemoryOrigin.owner,
        ),
    ]
    block = format_owner_preferences_block(items)
    assert block is not None
    assert "<owner_preferences>" in block
    assert "- Prefer plumber Jansen" in block
    assert "- Tenants get friendly greetings" in block


def test_retire_memory() -> None:
    session = MagicMock()
    company_id = uuid4()
    memory_id = uuid4()
    item = MemoryItem(
        id=memory_id,
        company_id=company_id,
        scope=MemoryScope.company,
        kind=MemoryKind.rule,
        text="Old rule",
        status=MemoryStatus.active,
        origin=MemoryOrigin.owner,
    )
    session.scalar.return_value = item

    success = retire_memory(session, company_id, memory_id)
    assert success is True
    assert item.status == MemoryStatus.retired
    session.flush.assert_called_once()


def test_get_active_preferences() -> None:
    session = MagicMock()
    company_id = uuid4()
    item = MemoryItem(
        id=uuid4(),
        company_id=company_id,
        scope=MemoryScope.company,
        kind=MemoryKind.rule,
        text="A rule",
        status=MemoryStatus.active,
        origin=MemoryOrigin.owner,
    )
    session.scalars.return_value.all.return_value = [item]

    items = get_active_preferences(session, company_id)
    assert items == [item]
