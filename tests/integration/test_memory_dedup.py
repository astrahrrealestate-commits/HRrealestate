"""Memory dedup against real Postgres: an owner restatement merges into the owner's rule, never into a distilled one."""

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.context.memory_items import record_owner_memory
from app.core.ids import new_id
from app.db.enums import MemoryKind, MemoryOrigin, MemoryScope, MemoryStatus
from app.db.models import Company, MemoryItem
from app.pipeline.distiller import propose_distilled_memory

pytestmark = pytest.mark.integration


def _item(company: Company, text: str, origin: MemoryOrigin, status: MemoryStatus = MemoryStatus.active) -> MemoryItem:
    return MemoryItem(
        id=new_id(),
        company_id=company.id,
        scope=MemoryScope.company,
        scope_id=None,
        kind=MemoryKind.rule,
        text=text,
        status=status,
        origin=origin,
        source_refs=[],
        evidence_count=1,
        confidence=0.9,
    )


def test_owner_restatement_merges_into_the_owner_rule_and_leaves_the_distilled_one(
    migrated_engine: Engine, committed_company: Company
) -> None:
    with Session(migrated_engine) as session:
        owner_rule = _item(committed_company, "Always use the plumber Jansen", MemoryOrigin.owner)
        distilled = _item(committed_company, "Always use plumber Jansen!", MemoryOrigin.distilled)
        session.add_all([owner_rule, distilled])
        session.commit()

        item, message = record_owner_memory(session, committed_company.id, "always use plumber jansen")
        session.commit()

        assert item is not None
        assert item.id == owner_rule.id
        assert "updated evidence count: 2" in message
        session.refresh(distilled)
        assert distilled.evidence_count == 1


def test_owner_rule_is_stored_even_when_only_a_distilled_item_says_the_same(
    migrated_engine: Engine, committed_company: Company
) -> None:
    with Session(migrated_engine) as session:
        distilled = _item(committed_company, "Always use the plumber Jansen", MemoryOrigin.distilled)
        session.add(distilled)
        session.commit()

        item, _ = record_owner_memory(session, committed_company.id, "Always use plumber Jansen")
        session.commit()

        assert item is not None
        assert item.id != distilled.id
        assert item.origin == MemoryOrigin.owner
        rows = session.scalars(select(MemoryItem).where(MemoryItem.company_id == committed_company.id)).all()
        assert len(rows) == 2


def test_distilled_proposal_never_raises_an_owner_rule(migrated_engine: Engine, committed_company: Company) -> None:
    with Session(migrated_engine) as session:
        owner_rule = _item(
            committed_company, "Preference observed from edit on action reply: Dear Mr Jansen", MemoryOrigin.owner
        )
        session.add(owner_rule)
        session.commit()

        proposed = propose_distilled_memory(
            session, committed_company.id, "Preference observed from edit on action reply: Dear Mr Jansen!"
        )
        session.commit()

        assert proposed is not None
        assert proposed.id != owner_rule.id
        assert proposed.status == MemoryStatus.proposed
        session.refresh(owner_rule)
        assert owner_rule.evidence_count == 1
