"""Integration checks for separate email threads per mail thread, draft-only visibility, and 2-draft generation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.inbox.routes import _build_live_threads
from app.api.inbox.thread_batch import inbox_stats_counts
from app.contracts import ActionType, Category, Channel, Direction, OutboundMode, Urgency
from app.core.ids import new_id
from app.db.enums import ActionStatus, ApprovalStatus, LinkMethod, SendStatus
from app.db.models import ActionRow, Approval, Case, CaseLink, Company, MessageRow, RawEvent, Send, UnderstandingRow

pytestmark = pytest.mark.integration
T0 = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def _add_gmail(
    s: Session,
    company_id,
    case_id,
    *,
    thread_ref: str,
    sender: str,
    minutes: int,
    direction: Direction = Direction.inbound,
    subject: str = "Onderwerp",
    requires_reply: bool = True,
) -> MessageRow:
    raw = RawEvent(company_id=company_id, provider=Channel.gmail, provider_msg_id=f"raw-{uuid4()}", payload={})
    s.add(raw)
    s.flush()
    msg = MessageRow(
        company_id=company_id,
        raw_event_id=raw.id,
        channel=Channel.gmail,
        provider_msg_id=raw.provider_msg_id,
        thread_ref=thread_ref,
        sender_identity=sender,
        direction=direction,
        sent_at=T0 + timedelta(minutes=minutes),
        text=f"Bericht {minutes}",
        meta={"subject": subject, "mailbox": "info@hr.nl", "to": ["info@hr.nl"]},
    )
    s.add(msg)
    s.flush()
    s.add(CaseLink(company_id=company_id, case_id=case_id, message_id=msg.id, method=LinkMethod.thread))
    if direction is Direction.inbound:
        s.add(
            UnderstandingRow(
                company_id=company_id,
                message_id=msg.id,
                category=Category.maintenance,
                urgency=Urgency.normal,
                body={"intent": subject, "requires_reply": requires_reply},
                prompt_version="understanding/v4",
            )
        )
    s.flush()
    return msg


def test_draft_mode_sends_never_hide_pending_drafts_or_count_as_replied(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    with Session(migrated_engine) as s, s.begin():
        company = s.get(Company, cid)
        assert company is not None
        company.outbound_mode = OutboundMode.draft
        c = Case(company_id=cid, category=Category.maintenance, urgency=Urgency.normal, summary="Lek")
        s.add(c)
        s.flush()
        m1 = _add_gmail(s, cid, c.id, thread_ref="thr-a", sender="a@b.nl", minutes=0, subject="Lekkage")
        notify = ActionRow(
            company_id=cid,
            case_id=c.id,
            type=ActionType.notify_owner,
            payload={"kind": "notify_owner", "text": "FYI"},
            rationale="FYI",
            context_ref=[m1.id],
            draft_version=1,
            status=ActionStatus.executed,
        )
        reply = ActionRow(
            company_id=cid,
            case_id=c.id,
            type=ActionType.reply_draft,
            payload={"kind": "reply_draft", "channel": "gmail", "subject": "Re: Lekkage", "body_variants": ["A", "B"]},
            rationale="Reply",
            context_ref=[m1.id],
            draft_version=1,
            status=ActionStatus.pending_approval,
        )
        s.add_all([notify, reply])
        s.flush()
        s.add(Approval(company_id=cid, action_id=reply.id, draft_version=1, status=ApprovalStatus.pending))
        s.add(
            Send(
                company_id=cid,
                action_id=notify.id,
                idempotency_key=f"notify:{new_id()}",
                channel=Channel.dashboard,
                target="owner:1",
                status=SendStatus.sent,
                attempted_at=T0 + timedelta(minutes=1),
            )
        )

    with Session(migrated_engine) as s:
        [thread] = _build_live_threads(s, cid, include_html=False)
        assert thread["status"] == "needs_approval"
        assert [d["text"] for d in thread["gmailDrafts"]] == ["A", "B"]
        assert len(thread["messages"]) == 1
        stats = inbox_stats_counts(s, cid)
        assert stats["needsYouCount"] == 1
