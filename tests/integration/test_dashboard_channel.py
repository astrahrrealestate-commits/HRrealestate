"""Dashboard owner channel against real Postgres: feed delivery is idempotent, writes no Send/outbox row, and the
edit route puts the new revision's card in the feed."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.api.v1.decisions import _deliver_revision_card
from app.channels.dashboard import feed
from app.channels.whatsapp.outbound import FakeWhatsAppOutbound
from app.contracts import ActionType, Category, InteractiveChannel, OwnerChoice, OwnerMessage, Urgency
from app.core.settings import Settings
from app.db.enums import ActionStatus, ApprovalStatus, FeedKind
from app.db.models import ActionRow, Approval, Case, Company, OwnerAccount, OwnerFeed, OwnerOutbox, Send
from app.main import create_app
from app.owner.card_data import load_card
from app.owner.cards import approval_messages
from app.sender.execute import SenderDeps, send_to_owner
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
H = {CSRF_HEADER: CSRF_VALUE}


@pytest.fixture
def owner(migrated_engine: Engine, committed_company: Company) -> OwnerAccount:
    with Session(migrated_engine, expire_on_commit=False) as s:
        o = OwnerAccount(
            company_id=committed_company.id,
            display_name="Harjot",
            whatsapp_e164="+31600000100",
            interactive_channel=InteractiveChannel.dashboard,
        )
        s.add(o)
        s.commit()
    return o


def _count(engine: Engine, model: Any, company_id: UUID) -> int:
    with Session(engine) as s:
        return s.scalar(select(func.count()).select_from(model).where(model.company_id == company_id)) or 0


def test_deliver_is_idempotent_and_returns_the_same_id(migrated_engine: Engine, committed_company: Company) -> None:
    cid, ref = committed_company.id, uuid4()
    msg = OwnerMessage(text="hi", choices=(OwnerChoice(f"apr:{ref}:ok", "Approve"),))
    with Session(migrated_engine) as s, s.begin():
        first = feed.deliver(s, cid, f"approval:{ref}:0", FeedKind.approval, ref, msg)
    with Session(migrated_engine) as s, s.begin():
        again = feed.deliver(s, cid, f"approval:{ref}:0", FeedKind.approval, ref, OwnerMessage(text="ignored"))
    assert first == again
    with Session(migrated_engine) as s:
        row = s.scalars(select(OwnerFeed).where(OwnerFeed.company_id == cid)).one()
    assert (row.kind, row.ref_id, row.payload["text"]) == (FeedKind.approval, ref, "hi")
    assert row.payload["choices"][0]["id"] == f"apr:{ref}:ok"


def test_send_to_owner_dashboard_writes_feed_only(
    migrated_engine: Engine, committed_company: Company, owner: OwnerAccount
) -> None:
    cid, approval = committed_company.id, uuid4()
    wa = FakeWhatsAppOutbound()
    deps = SenderDeps(migrated_engine, wa, lambda _a: pytest.fail("gmail is not used"))
    msg = OwnerMessage(text="pick", choices=(OwnerChoice(f"apr:{approval}:d1", "Send draft 1"),))
    key = f"approval:{approval}:0"
    first = send_to_owner(deps, cid, key, msg)
    second = send_to_owner(deps, cid, key, lambda to: pytest.fail("built twice"))
    assert first is not None
    assert first == second
    assert _count(migrated_engine, OwnerFeed, cid) == 1
    assert _count(migrated_engine, Send, cid) == 0
    assert _count(migrated_engine, OwnerOutbox, cid) == 0
    assert wa.sent == []
    with Session(migrated_engine) as s:
        row = s.scalars(select(OwnerFeed).where(OwnerFeed.company_id == cid)).one()
    assert (str(row.id), row.kind, row.ref_id) == (first, FeedKind.approval, approval)


def _pending(engine: Engine, company_id: UUID) -> UUID:
    with Session(engine) as s:
        case = Case(company_id=company_id, category=Category.other, urgency=Urgency.normal, summary="s")
        s.add(case)
        s.flush()
        action = ActionRow(
            company_id=company_id, case_id=case.id, type=ActionType.reply_draft,
            payload={"body_variants": ["a", "b"]}, rationale="r", context_ref=[],
            status=ActionStatus.pending_approval,
        )  # fmt: skip
        s.add(action)
        s.flush()
        approval = Approval(company_id=company_id, action_id=action.id, draft_version=1)
        s.add(approval)
        s.commit()
        return approval.id


@pytest.fixture
def client(
    migrated_engine: Engine, pg_url: str, committed_company: Company, owner: OwnerAccount
) -> Iterator[TestClient]:
    settings = Settings(
        database_url=pg_url,  # type: ignore[arg-type]
        env="test",
        dashboard_session_secret=SecretStr("x" * 32),
        _env_file=None,
    )
    principal = Principal(company_id=committed_company.id, owner_id=owner.id, email="h@a.test")
    with TestClient(create_app(settings, engine=migrated_engine, workflow_client=MagicMock())) as c:
        c.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
        yield c


def test_edit_delivers_new_revision_card_once(
    migrated_engine: Engine, committed_company: Company, client: TestClient
) -> None:
    cid = committed_company.id
    old = _pending(migrated_engine, cid)
    with Session(migrated_engine) as s, s.begin():
        s.get(Approval, old).status = ApprovalStatus.edited  # type: ignore[union-attr]  # tapped "edit"
        s.get(Approval, old).decided_at = datetime.now(UTC)  # type: ignore[union-attr]
    r = client.post(f"/api/v1/approvals/{old}/edit", json={"text": "my own words"}, headers=H)
    assert r.status_code == 200, r.text
    new = UUID(r.json()["approval_id"])
    with Session(migrated_engine) as s:
        rows = s.scalars(select(OwnerFeed).where(OwnerFeed.company_id == cid, OwnerFeed.ref_id == new)).all()
        card = load_card(s, cid, new)
    keys = {x.idempotency_key for x in rows}
    assert keys == {feed.stored_key(cid, f"approval:{new}:{n}") for n in range(len(approval_messages(card)))}
    assert all(x.kind is FeedKind.approval for x in rows)
    feed_before = _count(migrated_engine, OwnerFeed, cid)

    _deliver_revision_card(migrated_engine, cid, new)  # a retry inserts nothing
    assert _count(migrated_engine, OwnerFeed, cid) == feed_before


def test_foreign_company_cannot_resolve_other_cards(migrated_engine: Engine, committed_company: Company) -> None:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other")
        s.add(other)
        s.commit()
    try:
        ref = _pending(migrated_engine, other.id)
        with Session(migrated_engine) as s, pytest.raises(Exception, match="not found"):
            load_card(s, committed_company.id, ref)
    finally:
        purge_company(migrated_engine, other.id)


def test_two_companies_sharing_a_key_each_get_their_own_row(
    migrated_engine: Engine, committed_company: Company
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other")
        s.add(other)
        s.commit()
    try:
        ids = []
        for company_id in (committed_company.id, other.id):
            with Session(migrated_engine) as s, s.begin():
                ids.append(
                    feed.deliver(s, company_id, "briefing:shared", FeedKind.briefing, None, OwnerMessage(text="x"))
                )
        assert ids[0] != ids[1]
        assert _count(migrated_engine, OwnerFeed, committed_company.id) == 1
        assert _count(migrated_engine, OwnerFeed, other.id) == 1
    finally:
        purge_company(migrated_engine, other.id)
