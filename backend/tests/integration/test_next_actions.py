"""Category next actions and API tests (M13 T10)."""

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts import ActionType, Category, Urgency
from app.contracts.finance import SnapshotBasis, Verdict
from app.core.ids import new_id
from app.db.enums import (
    ActionStatus,
    ApprovalStatus,
    DocLinkKind,
    DocumentStatus,
    PersonKind,
    QuoteSource,
)
from app.db.models import (
    ActionRow,
    Approval,
    AttachmentRow,
    Case,
    Company,
    DocumentLink,
    DocumentRow,
    Lease,
    LeaseParty,
    Person,
    QuoteReview,
    QuoteRow,
    TenantRentPayment,
    Unit,
    WaitRow,
)
from app.pipeline.next_actions import ActionViewer, NextAction, category_brief, next_actions
from tests.integration.access_support import add_person_to_team, build_app, signed_in
from tests.integration.conftest import purge_company
from tests.integration.reload_support import NOW, mail, understanding_body

pytestmark = pytest.mark.integration


@pytest.fixture
def other_company(migrated_engine: Engine) -> Iterator[Company]:
    with Session(migrated_engine, expire_on_commit=False) as s, s.begin():
        other = Company(name="Other BV")
        s.add(other)
    yield other
    purge_company(migrated_engine, other.id)


def _seed_case(
    session: Session,
    cid: UUID,
    category: Category,
    urgency: Urgency = Urgency.normal,
    summary: str = "Secret summary",
    name: str = "Sanne",
) -> tuple[UUID, UUID]:
    p = Person(company_id=cid, kind=PersonKind.tenant, display_name=name, valid_from=date(2026, 1, 1))
    session.add(p)
    session.flush()
    c = Case(company_id=cid, primary_person_id=p.id, category=category, urgency=urgency, summary=summary)
    session.add(c)
    session.flush()
    return p.id, c.id


def _seed_approval(
    session: Session,
    cid: UUID,
    case_id: UUID,
    draft_text: str = "Beste Sanne, wij sturen de monteur.",
    *,
    created_at: datetime = NOW,
) -> UUID:
    act = ActionRow(
        company_id=cid,
        case_id=case_id,
        type=ActionType.reply_draft,
        rationale="r",
        context_ref=[],
        status=ActionStatus.pending_approval,
        payload={"kind": "reply_draft", "channel": "gmail", "subject": None, "body_variants": [draft_text]},
        created_at=created_at,
    )
    session.add(act)
    session.flush()
    app = Approval(
        company_id=cid,
        action_id=act.id,
        draft_version=1,
        status=ApprovalStatus.pending,
        created_at=created_at,
    )
    session.add(app)
    session.flush()
    return app.id


def test_each_category_lists_only_its_own_actions(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    with Session(migrated_engine) as s, s.begin():
        _, c_maint = _seed_case(s, cid, Category.maintenance)
        _seed_approval(s, cid, c_maint)
        _, c_legal = _seed_case(s, cid, Category.legal)
        _seed_approval(s, cid, c_legal, "Beste, artikel 14 ROZ.")
        _, c_spam = _seed_case(s, cid, Category.spam)
        _seed_approval(s, cid, c_spam, "Spam draft")
        q = QuoteRow(
            company_id=cid,
            case_id=c_maint,
            source=QuoteSource.message,
            source_id=new_id(),
            quote_date=date(2026, 11, 1),
            currency="EUR",
            total=Decimal("500"),
        )
        s.add(q)
        s.flush()
        s.add(
            QuoteReview(
                company_id=cid,
                quote_id=q.id,
                snapshot_basis=SnapshotBasis.decision_day,
                verdict=Verdict.above_market,
                overcharge=Decimal("100"),
                late_days=0,
                report={},
            )
        )

    viewer = ActionViewer(money=True, inbox=True)
    with Session(migrated_engine) as s:
        maint = next_actions(s, cid, Category.maintenance, viewer)
        fin = next_actions(s, cid, Category.finance, viewer)
        legal = next_actions(s, cid, Category.legal, viewer)
        admin = next_actions(s, cid, Category.administration, viewer)

    assert {a.kind for a in maint} == {"approve_draft", "quote_review"}
    assert [a.kind for a in fin] == ["quote_review"]
    assert [a.kind for a in legal] == ["approve_draft"]
    assert admin == []


def test_actions_rank_by_urgency_then_due_date(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    with Session(migrated_engine) as s, s.begin():
        p, c_norm = _seed_case(s, cid, Category.maintenance, Urgency.normal)
        _seed_approval(s, cid, c_norm, "Normal draft", created_at=NOW - timedelta(hours=5))
        _, c_emg = _seed_case(s, cid, Category.maintenance, Urgency.emergency)
        _seed_approval(s, cid, c_emg, "Emergency draft", created_at=NOW)
        _, c_wait_early = _seed_case(s, cid, Category.maintenance, Urgency.high)
        s.add(
            WaitRow(
                company_id=cid,
                case_id=c_wait_early,
                party_person_id=p,
                about="Early",
                expected_by=NOW - timedelta(days=3),
            )
        )
        _, c_wait_late = _seed_case(s, cid, Category.maintenance, Urgency.high)
        s.add(
            WaitRow(
                company_id=cid,
                case_id=c_wait_late,
                party_person_id=p,
                about="Late",
                expected_by=NOW - timedelta(days=1),
            )
        )

    with Session(migrated_engine) as s:
        items = next_actions(s, cid, Category.maintenance, ActionViewer(money=True, inbox=True), now=NOW)
    assert [i.case_id for i in items] == [c_emg, c_wait_early, c_wait_late, c_norm]


def test_another_companys_actions_never_appear(
    migrated_engine: Engine, committed_company: Company, other_company: Company
) -> None:
    with Session(migrated_engine) as s, s.begin():
        _, their_case = _seed_case(s, other_company.id, Category.legal, summary="Their secret")
        _seed_approval(s, other_company.id, their_case, "Their draft")
    with Session(migrated_engine) as s:
        assert next_actions(s, committed_company.id, Category.legal, ActionViewer(money=True, inbox=True)) == []


def test_arrears_need_the_money_section(migrated_engine: Engine, pg_url: str, committed_company: Company) -> None:
    cid = committed_company.id
    with Session(migrated_engine) as s, s.begin():
        p = Person(
            company_id=cid, kind=PersonKind.tenant, display_name="Jan", brixx_ref="r1", valid_from=date(2026, 1, 1)
        )
        u = Unit(company_id=cid, label="Singel 1", address="Singel 1", brixx_ref="u1", valid_from=date(2026, 1, 1))
        s.add_all([p, u])
        s.flush()
        lease = Lease(company_id=cid, unit_id=u.id, valid_from=date(2025, 1, 1), brixx_ref="l1")
        s.add(lease)
        s.flush()
        s.add(LeaseParty(company_id=cid, lease_id=lease.id, person_id=p.id, role="tenant"))
        s.add(
            TenantRentPayment(
                company_id=cid,
                tenant_id=p.id,
                unit_id=u.id,
                lease_id=lease.id,
                invoice_number="F-1",
                billing_month=date(2026, 9, 1),
                due_date=date(2026, 9, 5),
                contract_rent_cents=120000,
                amount_paid_cents=0,
                status="overdue",
                overdue_days=75,
            )
        )

    app, settings = build_app(migrated_engine, pg_url)
    tag = uuid4().hex[:6]
    no_money = add_person_to_team(migrated_engine, cid, f"nomoney-{tag}@t.test", role="member", sections=["dashboard"])
    with_money = add_person_to_team(
        migrated_engine, cid, f"money-{tag}@t.test", role="member", sections=["dashboard", "money"]
    )
    with signed_in(app, settings, no_money) as client:
        assert client.get("/api/dashboard/categories/finance").json()["actions"] == []
    with signed_in(app, settings, with_money) as client:
        actions = client.get("/api/dashboard/categories/finance").json()["actions"]
        assert len(actions) == 1
        assert actions[0]["kind"] == "rent_arrears"


def test_headline_only_profiles_get_no_message_text(
    migrated_engine: Engine, pg_url: str, committed_company: Company
) -> None:
    cid = committed_company.id
    with Session(migrated_engine) as s, s.begin():
        _, c = _seed_case(s, cid, Category.maintenance, summary="Secret pipe leak", name="secret@tenant.test")
        _seed_approval(s, cid, c, "Secret draft text 0612345678")
        _, c_reply = _seed_case(s, cid, Category.legal, summary="Secret legal summary", name="advocaat@law.test")
    m = mail(migrated_engine, cid, case_id=c_reply, text="Confidential inbound body", understood=understanding_body())
    with Session(migrated_engine) as s, s.begin():
        att = AttachmentRow(
            company_id=cid,
            message_id=m.message_id,
            s3_key="k",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="a" * 64,
            filename="doc.pdf",
        )
        s.add(att)
        s.flush()
        doc = DocumentRow(
            company_id=cid,
            attachment_id=att.id,
            doc_type="other",
            title="Secret title",
            file_name="doc.pdf",
            confidence=0.3,
            status=DocumentStatus.review,
        )
        s.add(doc)
        s.flush()
        s.add(
            DocumentLink(
                company_id=cid, document_id=doc.id, kind=DocLinkKind.case, ref_id=c_reply, method="message", score=1.0
            )
        )

    app, settings = build_app(migrated_engine, pg_url)
    dash_only = add_person_to_team(
        migrated_engine, cid, f"dash-{uuid4().hex[:6]}@t.test", role="member", sections=["dashboard"]
    )
    with signed_in(app, settings, dash_only) as client:
        maint = client.get("/api/dashboard/categories/maintenance").json()
        legal = client.get("/api/dashboard/categories/legal").json()
    blob = repr([maint, legal])
    for secret in (
        "Secret draft text",
        "Secret pipe leak",
        "Secret legal summary",
        "Secret title",
        "secret@tenant",
        "advocaat@law",
    ):
        assert secret not in blob


def test_brief_is_built_from_counts_only() -> None:
    assert category_brief([]) is None
    sample = [
        NextAction(
            id="1",
            category=Category.finance,
            kind="quote_review",
            title="t",
            why="w",
            urgency=Urgency.high,
            due_at=None,
            case_id=None,
            approval_id=None,
            prepared=None,
            target_url="/money",
        ),
        NextAction(
            id="2",
            category=Category.finance,
            kind="quote_review",
            title="t",
            why="w",
            urgency=Urgency.normal,
            due_at=None,
            case_id=None,
            approval_id=None,
            prepared=None,
            target_url="/money",
        ),
        NextAction(
            id="3",
            category=Category.finance,
            kind="approve_draft",
            title="t",
            why="w",
            urgency=Urgency.normal,
            due_at=None,
            case_id=None,
            approval_id=None,
            prepared=None,
            target_url="/inbox",
        ),
    ]
    assert category_brief(sample) == "2 quotes above market, 1 reply ready to approve."


def test_unknown_category_is_422(migrated_engine: Engine, pg_url: str, committed_company: Company) -> None:
    app, settings = build_app(migrated_engine, pg_url)
    dash = add_person_to_team(
        migrated_engine, committed_company.id, f"d-{uuid4().hex[:6]}@t.test", role="member", sections=["dashboard"]
    )
    with signed_in(app, settings, dash) as client:
        assert client.get("/api/dashboard/categories").status_code == 200
        assert client.get("/api/dashboard/categories/unknown").status_code == 422
        assert client.get("/api/dashboard/categories/spam").status_code == 422
