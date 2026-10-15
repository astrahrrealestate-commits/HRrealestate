"""GET /approvals and GET /documents/review against real Postgres: pending only, scoped, suspicious flag, paging."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.contracts import ActionType, Category, Channel, Direction, Urgency
from app.core.settings import Settings
from app.db.enums import ActionStatus, ApprovalStatus, DocumentStatus, LinkMethod
from app.db.models import (
    ActionRow,
    Approval,
    AttachmentRow,
    Case,
    CaseLink,
    Company,
    DocumentRow,
    OwnerAccount,
    UnderstandingRow,
)
from app.db.models.ingestion import MessageRow, RawEvent
from app.main import create_app
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
Ids = tuple[UUID, UUID, UUID]
Seeded = tuple[TestClient, Ids, Ids]
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _seed(s: Session, company_id: UUID, tag: str, *, suspicious: bool) -> tuple[UUID, UUID, UUID]:
    """One pending approval, one review document and one filed document. Returns (approval, case, review attachment)."""
    case = Case(company_id=company_id, category=Category.other, urgency=Urgency.normal, summary=tag)
    s.add(case)
    raw = RawEvent(company_id=company_id, provider=Channel.gmail, provider_msg_id=f"m-{tag}-{uuid4()}", payload={})
    s.add(raw)
    s.flush()
    msg = MessageRow(company_id=company_id, raw_event_id=raw.id, channel=Channel.gmail,
                     provider_msg_id=raw.provider_msg_id, thread_ref="t", sender_identity="x@y.test",
                     direction=Direction.inbound, sent_at=T0, text="hi")  # fmt: skip
    s.add(msg)
    s.flush()
    action = ActionRow(company_id=company_id, case_id=case.id, type=ActionType.reply_draft,
                       payload={"body_variants": ["one", "two"]}, rationale="r", context_ref=[msg.id],
                       status=ActionStatus.pending_approval)  # fmt: skip
    s.add_all(
        [
            action,
            CaseLink(company_id=company_id, case_id=case.id, message_id=msg.id, method=LinkMethod.thread),
            UnderstandingRow(company_id=company_id, message_id=msg.id, category=Category.other, urgency=Urgency.normal,
                             body={"suspicious": {"flag": suspicious}}, prompt_version="understanding/v2"),
        ]
    )  # fmt: skip
    s.flush()
    approval = Approval(company_id=company_id, action_id=action.id, draft_version=1, status=ApprovalStatus.pending)
    done = Approval(company_id=company_id, action_id=action.id, draft_version=1, status=ApprovalStatus.rejected)
    review = AttachmentRow(company_id=company_id, message_id=msg.id, s3_key="k1", mime_type="application/pdf",
                           filename="lease.pdf", size_bytes=1, sha256="0" * 64)  # fmt: skip
    filed = AttachmentRow(company_id=company_id, message_id=msg.id, s3_key="k2", mime_type="application/pdf",
                          filename="done.pdf", size_bytes=1, sha256="1" * 64)  # fmt: skip
    s.add_all([approval, done, review, filed])
    s.flush()
    for att, status in ((review, DocumentStatus.review), (filed, DocumentStatus.filed)):
        s.add(DocumentRow(company_id=company_id, attachment_id=att.id, doc_type="lease", title="t",
                          file_name=att.filename or "", confidence=0.4, status=status))  # fmt: skip
    s.flush()
    return approval.id, case.id, review.id


@pytest.fixture
def seeded(migrated_engine: Engine, pg_url: str, committed_company: Company) -> Iterator[Seeded]:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other")
        s.add(other)
        s.flush()
        owner = OwnerAccount(company_id=committed_company.id, display_name="H", whatsapp_e164="+31699999995",
                             email="h@a.test")  # fmt: skip
        s.add(owner)
        mine = _seed(s, committed_company.id, "a", suspicious=True)
        theirs = _seed(s, other.id, "b", suspicious=False)
        s.commit()
    settings = Settings(
        database_url=pg_url,  # type: ignore[arg-type]
        env="test",
        dashboard_session_secret=SecretStr("x" * 32),
        _env_file=None,
    )
    principal = Principal(company_id=committed_company.id, owner_id=owner.id, email="h@a.test")
    with TestClient(create_app(settings, engine=migrated_engine, workflow_client=MagicMock())) as c:
        c.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
        yield c, mine, theirs
    purge_company(migrated_engine, other.id)


def test_approvals_lists_only_my_pending_with_flag(seeded: Seeded) -> None:
    client, mine, _ = seeded
    body = client.get("/api/v1/approvals").json()
    assert [a["id"] for a in body] == [str(mine[0])]
    assert body[0]["drafts"] == ["one", "two"]
    assert (body[0]["suspicious"], body[0]["draft_version"], body[0]["case_id"]) == (True, 1, str(mine[1]))
    assert body[0]["case_label"] == "Unknown sender · other"
    assert client.get(f"/api/v1/approvals?after={body[0]['cursor']}").json() == []


def test_documents_review_lists_only_status_review(seeded: Seeded) -> None:
    client, mine, _ = seeded
    body = client.get("/api/v1/documents/review").json()
    assert [d["attachment_id"] for d in body] == [str(mine[2])]
    assert (body[0]["filename"], body[0]["mime_type"], body[0]["suggested_type"]) == (
        "lease.pdf", "application/pdf", "lease",
    )  # fmt: skip
    assert body[0]["case_id"] == str(mine[1])
    assert client.get(f"/api/v1/documents/review?after={body[0]['cursor']}").json() == []


def test_batched_suspicious_agrees_with_the_gate(migrated_engine: Engine, seeded: Seeded) -> None:
    from app.pipeline.dashboard_decisions import is_suspicious, suspicious_by_action

    _, mine, _ = seeded
    with Session(migrated_engine) as s:
        company_id = s.scalar(select(Case.company_id).where(Case.id == mine[1]))
        assert company_id is not None
        refd = s.scalars(select(ActionRow).where(ActionRow.case_id == mine[1])).all()
        followup = ActionRow(
            company_id=company_id, case_id=mine[1], type=ActionType.reply_draft, payload={}, rationale="r",
            context_ref=[], status=ActionStatus.pending_approval,
        )  # fmt: skip
        s.add(followup)
        s.flush()
        actions = [*refd, followup]
        batched = suspicious_by_action(s, company_id, actions)
        assert batched == {a.id: is_suspicious(s, company_id, a) for a in actions}
        assert batched[followup.id] is True  # no refs: falls back to the case's flagged message
        s.rollback()
