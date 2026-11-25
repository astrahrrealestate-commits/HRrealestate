"""The inbox filters by each of the six categories (M13 T4)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.api.inbox.routes import _build_live_threads
from app.api.inbox.thread_batch import inbox_stats_counts
from app.contracts import Category, Channel, Direction, Urgency
from app.contracts.categories import SHOWN_CATEGORIES
from app.db.enums import LinkMethod
from app.db.models import Case, CaseLink, Company, MessageRow, RawEvent, UnderstandingRow

pytestmark = pytest.mark.integration
T0 = datetime(2026, 11, 1, tzinfo=UTC)


def _case(db: Session, company: Company, category: Category, role: str | None = None) -> None:
    case = Case(company_id=company.id, category=category, urgency=Urgency.normal, summary=category.value)
    raw = RawEvent(company_id=company.id, provider=Channel.gmail, provider_msg_id=f"m-{uuid4()}", payload={})
    db.add_all([case, raw])
    db.flush()
    msg = MessageRow(company_id=company.id, raw_event_id=raw.id, channel=Channel.gmail,
                     provider_msg_id=raw.provider_msg_id, thread_ref=f"t-{uuid4()}", sender_identity="a@b.nl",
                     direction=Direction.inbound, sent_at=T0, text=category.value)  # fmt: skip
    db.add(msg)
    db.flush()
    db.add(CaseLink(company_id=company.id, case_id=case.id, message_id=msg.id, method=LinkMethod.thread))
    db.add(UnderstandingRow(company_id=company.id, message_id=msg.id, category=category, urgency=Urgency.normal,
                            body={"sender_role": role}, prompt_version="understanding/v4"))  # fmt: skip
    db.flush()


@pytest.mark.parametrize("category", SHOWN_CATEGORIES, ids=lambda c: c.value)
def test_inbox_filter_by_each_category(db: Session, company: Company, category: Category) -> None:
    for c in SHOWN_CATEGORIES:
        _case(db, company, c)
    threads = _build_live_threads(db, company.id, category=category.value, include_html=False)
    assert threads
    assert {t["category"] for t in threads} == {category.value}


def test_contractor_count_uses_the_senders_role_not_the_category(db: Session, company: Company) -> None:
    """With no `contractor_update` category left, a contractor thread is one whose sender the model called a
    contractor (or a directory contractor); a tenant's repair report is not one."""
    _case(db, company, Category.maintenance, role="contractor")
    _case(db, company, Category.maintenance, role="tenant")
    assert inbox_stats_counts(db, company.id)["contractorsCount"] == 1
