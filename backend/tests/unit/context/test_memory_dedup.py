"""Duplicate detection for memory items: only identical wording (after case, punctuation, articles) merges."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.context.memory_dedup import find_near_duplicate, is_near_duplicate
from app.context.memory_items import record_owner_memory
from app.db.enums import MemoryKind, MemoryOrigin, MemoryScope, MemoryStatus
from app.db.models import MemoryItem
from app.pipeline.distiller import propose_distilled_memory


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Always use plumber Jansen", "always use plumber jansen."),
        ("Always use plumber Jansen", "Always use the plumber Jansen"),
        ("Approve repairs under 100 euro", "approve repairs  under 100 euro!"),
        ("Gebruik altijd de loodgieter Jansen", "gebruik altijd loodgieter jansen"),
    ],
)
def test_is_near_duplicate_true(a: str, b: str) -> None:
    assert is_near_duplicate(a, b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Tenant prefers WhatsApp over email", "Tenant prefers email over WhatsApp"),
        ("Always notify the tenant before sending a plumber", "Never notify the tenant before sending a plumber"),
        ("Contact the tenant before sending a plumber", "Do not contact the tenant before sending a plumber"),
        ("Always use plumber Jansen", "Always use electrician Bakker"),
        ("Approve repairs under 100 euro", "Approve repairs under 500 euro"),
        ("Always approve contractor quotes under 500 euro", "Always approve contractor quotes over 500 euro"),
        ("Always call the plumber first", "Always call the plumber last"),
        ("Use formal tone with tenants", "Use informal tone with tenants"),
        ("Always CC the accountant on invoices from tenants", "Always CC the accountant on invoices from contractors"),
        ("Always use plumber Bakker", "Always use plumber Bakkers"),
        ("Increase the rent reminder tone", "Decrease the rent reminder tone"),
        ("Use plumber Jansen", "Use plumber Jansen for roof leaks in the Rotterdam portfolio"),
        ("", "anything"),
        ("the a an", "the a an"),
    ],
)
def test_is_near_duplicate_false(a: str, b: str) -> None:
    assert not is_near_duplicate(a, b)


def _item(
    text: str,
    status: MemoryStatus = MemoryStatus.active,
    origin: MemoryOrigin = MemoryOrigin.owner,
    kind: MemoryKind = MemoryKind.rule,
) -> MemoryItem:
    return MemoryItem(
        id=uuid4(),
        company_id=uuid4(),
        scope=MemoryScope.company,
        scope_id=None,
        kind=kind,
        text=text,
        status=status,
        origin=origin,
        evidence_count=1,
        confidence=0.8,
        source_refs=[],
    )


def _session_with_candidates(candidates: list[MemoryItem]) -> MagicMock:
    session = MagicMock()
    session.scalar.return_value = None  # no exact match
    session.scalars.return_value.all.return_value = candidates
    return session


def test_record_owner_memory_merges_restatement_and_shows_what_it_merged_into() -> None:
    existing = _item("Always use plumber Jansen")
    session = _session_with_candidates([existing])

    item, message = record_owner_memory(session, existing.company_id, "Always use the plumber Jansen.")

    assert item is existing
    assert existing.evidence_count == 2
    session.add.assert_not_called()
    assert "updated evidence count: 2" in message
    assert "'Always use plumber Jansen'" in message


@pytest.mark.parametrize("flipped", ["Approve quotes over 500 euro", "Approve quotes under 500 euro and over 100"])
def test_record_owner_memory_stores_a_flipped_rule_instead_of_merging(flipped: str) -> None:
    session = _session_with_candidates([_item("Approve quotes under 500 euro")])

    item, _ = record_owner_memory(session, uuid4(), flipped)

    assert item is not None
    assert item.text == flipped
    session.add.assert_called_once_with(item)


def test_owner_lookup_only_looks_at_active_owner_items_of_the_same_kind() -> None:
    session = _session_with_candidates([])

    record_owner_memory(session, uuid4(), "Always use plumber Jansen", kind=MemoryKind.preference)

    sql = str(session.scalars.call_args.args[0])
    assert "memory_items.origin" in sql
    assert "memory_items.kind" in sql
    assert "memory_items.status IN" in sql


def test_find_near_duplicate_without_filters_skips_kind_and_origin() -> None:
    session = _session_with_candidates([])

    find_near_duplicate(session, uuid4(), MemoryScope.company, None, "x y", (MemoryStatus.active,))

    sql = str(session.scalars.call_args.args[0])
    assert "memory_items.origin =" not in sql
    assert "memory_items.kind =" not in sql


def test_distiller_merges_restated_proposal_and_adds_source_ref() -> None:
    existing = _item(
        "Preference observed from edit on action reply: Dear Mr Jansen, thanks",
        MemoryStatus.proposed,
        MemoryOrigin.distilled,
        MemoryKind.preference,
    )
    session = _session_with_candidates([existing])
    ref = {"action_id": "a1", "revision_id": "r1"}

    item = propose_distilled_memory(
        session,
        existing.company_id,
        "Preference observed from edit on action reply: Dear Mr Jansen, thanks!",
        source_refs=[ref],
    )

    assert item is existing
    assert existing.evidence_count == 2
    assert existing.source_refs == [ref]
    session.add.assert_not_called()


def test_distiller_lookup_is_limited_to_distilled_items() -> None:
    session = _session_with_candidates([])

    propose_distilled_memory(session, uuid4(), "Preference observed from edit on action reply: Hello")

    sql = str(session.scalars.call_args.args[0])
    assert "memory_items.origin" in sql
