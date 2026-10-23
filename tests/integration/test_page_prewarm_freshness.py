"""Server-side freshness of warmed page facts (Task 4 fix round 1) against real Postgres: a message, an approval
(created or decided) or a case event newer than the warmed row makes the next turn resolve cold."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, inspect, update
from sqlalchemy.orm import Session

from app.contracts import ActionType, Channel, Direction
from app.core.ids import new_id
from app.db.enums import ApprovalStatus
from app.db.models import ActionRow, Approval, CaseEvent, MessageRow, RawEvent
from app.pipeline import concierge_page, page_facts
from tests.integration.concierge_support import seed_case
from tests.integration.page_prewarm_support import RESOLVER, World, make_world, page, post, put

pytestmark = pytest.mark.integration


@pytest.fixture
def world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    with make_world(migrated_engine, pg_url) as w:
        yield w


def _seed_old_case_with_approval(w: World) -> tuple[UUID, UUID]:
    """A case with a message, its events and a pending approval, all dated an hour ago; returns (case, approval)."""
    case_id, _ = seed_case(w.engine, w.company)
    with Session(w.engine) as s, s.begin():
        action = ActionRow(
            company_id=w.company, case_id=case_id, type=ActionType.reply_draft, payload={}, rationale="r",
            context_ref=[],
        )  # fmt: skip
        s.add(action)
        s.flush()
        approval = Approval(company_id=w.company, action_id=action.id, draft_version=1)
        s.add(approval)
        s.flush()
        for model in (MessageRow, Approval, CaseEvent):
            s.execute(
                update(model).where(model.company_id == w.company).values(created_at=func.now() - timedelta(hours=1))
            )
        return case_id, approval.id


def _post_spied(w: World, body: dict[str, Any]) -> tuple[dict[str, Any] | None, int]:
    """POST, then the run's resolve step; returns the stored page_context and how often the resolver ran."""
    with patch(RESOLVER, wraps=page_facts.resolve_page_facts) as spy:
        stored = post(w, body)
        assert stored is not None
        concierge_page.resolve_once(w.engine, w.company, stored)
    return stored, spy.call_count


def test_no_change_since_the_put_reuses_the_facts(world: World) -> None:
    case_id, _ = _seed_old_case_with_approval(world)
    put(world, page(view="case", case_id=str(case_id)))
    stored, calls = _post_spied(world, page(view="case", case_id=str(case_id)))
    assert stored is not None
    assert "resolved" in stored
    assert calls == 0


def test_a_message_after_the_put_resolves_cold(world: World) -> None:
    case_id, _ = _seed_old_case_with_approval(world)
    put(world, page(view="case", case_id=str(case_id)))
    with Session(world.engine) as s, s.begin():
        raw = RawEvent(company_id=world.company, provider=Channel.whatsapp, provider_msg_id=str(new_id()), payload={})
        s.add(raw)
        s.flush()
        s.add(
            MessageRow(
                company_id=world.company, raw_event_id=raw.id, channel=Channel.whatsapp,
                provider_msg_id=raw.provider_msg_id, thread_ref=None, sender_identity="+31612345670",
                direction=Direction.inbound, sent_at=datetime.now(UTC), text="De kraan lekt nog steeds",
            )
        )  # fmt: skip
    stored, calls = _post_spied(world, page(view="case", case_id=str(case_id)))
    assert stored is not None
    assert "resolved" not in stored  # cold: the turn's own run resolves (and sees the new message)
    assert calls == 1


def test_an_approval_decided_after_the_put_resolves_cold(world: World) -> None:
    case_id, approval_id = _seed_old_case_with_approval(world)
    put(world, page(view="case", case_id=str(case_id)))
    with Session(world.engine) as s, s.begin():
        s.execute(
            update(Approval)
            .where(Approval.company_id == world.company, Approval.id == approval_id)
            .values(status=ApprovalStatus.approved, decided_at=func.now())
        )
    stored, calls = _post_spied(world, page(view="case", case_id=str(case_id)))
    assert stored is not None
    assert "resolved" not in stored
    assert calls == 1


def test_0016_freshness_indexes(migrated_engine: Engine) -> None:
    insp = inspect(migrated_engine)
    expected = {
        "messages": {"ix_messages_company_id_messages_created_at": ["company_id", "created_at"]},
        "approvals": {
            "ix_approvals_company_id_approvals_created_at": ["company_id", "created_at"],
            "ix_approvals_company_id_approvals_decided_at": ["company_id", "decided_at"],
        },
        "case_events": {"ix_case_events_company_id_case_events_created_at": ["company_id", "created_at"]},
    }
    for table, wanted in expected.items():
        indexes = {i["name"]: i["column_names"] for i in insp.get_indexes(table)}
        for name, columns in wanted.items():
            assert indexes[name] == columns, name
        assert f"ix_{table}_company_id" not in indexes
