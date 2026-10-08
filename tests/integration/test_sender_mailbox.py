"""N1: a Gmail reply draft goes to the mailbox the tenant's thread arrived in, never another company mailbox."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.contracts import ActionType, Category, Channel, Direction, Urgency
from app.db.enums import LinkMethod
from app.db.models import ActionRow, Case, CaseLink, ChannelAccount, Company, MessageRow, RawEvent
from app.sender.targets import SendBlockedError, plan_for

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


def _mailboxes(db: Session, company: Company) -> tuple[str, str]:
    a, b = f"verhuur-{uuid4().hex[:8]}@example.test", f"onderhoud-{uuid4().hex[:8]}@example.test"
    db.add_all([ChannelAccount(company_id=company.id, channel=Channel.gmail, address=x) for x in (a, b)])
    db.flush()
    return a, b


def _thread(db: Session, company: Company, raw_mailbox: str, meta: dict[str, Any]) -> ActionRow:
    raw = RawEvent(company_id=company.id, provider=Channel.gmail, provider_msg_id=f"gm-{uuid4()}",
                   payload={"mailbox": raw_mailbox, "message_id": "m1"})  # fmt: skip
    case = Case(company_id=company.id, category=Category.maintenance, urgency=Urgency.normal)
    db.add_all([raw, case])
    db.flush()
    msg = MessageRow(
        company_id=company.id, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id=raw.provider_msg_id,
        thread_ref="thread-42", sender_identity="huurder@example.test", direction=Direction.inbound, sent_at=NOW,
        text="Lekkage", meta={"subject": "Lekkage", "message_id": "<m1@x>", **meta},
    )  # fmt: skip
    db.add(msg)
    db.flush()
    db.add(CaseLink(company_id=company.id, case_id=case.id, message_id=msg.id, method=LinkMethod.new_case))
    action = ActionRow(company_id=company.id, case_id=case.id, type=ActionType.reply_draft, rationale="r",
                       payload={"kind": "reply_draft", "channel": "gmail", "subject": None,
                                "body_variants": ["Beste, a", "Beste, b"]},
                       context_ref=[msg.id], draft_version=1)  # fmt: skip
    db.add(action)
    db.flush()
    return action


def test_draft_goes_to_the_mailbox_the_thread_arrived_in(db: Session, company: Company) -> None:
    first, second = _mailboxes(db, company)
    for mailbox in (first, second):  # whichever account row comes back first, the thread's own mailbox wins
        plan = plan_for(db, _thread(db, company, mailbox, {"mailbox": mailbox}), 0, f"k-{mailbox}")
        assert plan.mailbox == mailbox
        assert plan.draft is not None


def test_rows_ingested_before_meta_mailbox_use_the_raw_event(db: Session, company: Company) -> None:
    _, second = _mailboxes(db, company)
    plan = plan_for(db, _thread(db, company, second, {}), 1, "k-legacy")
    assert plan.mailbox == second


def test_a_mailbox_that_is_not_the_companys_is_blocked(db: Session, company: Company) -> None:
    _mailboxes(db, company)
    action = _thread(db, company, "someone-else@example.test", {"mailbox": "someone-else@example.test"})
    with pytest.raises(SendBlockedError, match="not one of the company's accounts"):
        plan_for(db, action, 0, "k-foreign")
