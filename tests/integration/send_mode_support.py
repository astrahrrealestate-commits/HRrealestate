"""Shared send-mode integration setup: a company in send mode, a tenant with Gmail and WhatsApp identities."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.channels.dashboard import feed
from app.channels.gmail.drafts import FakeDrafts
from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.channels.whatsapp.outbound import FakeWhatsAppOutbound
from app.contracts import ActionType, ButtonChoice, Category, Channel, Direction, OutboundMode, Urgency
from app.core.ids import new_id
from app.db.enums import ActionStatus, FeedKind, LinkMethod, PersonKind, SendStatus
from app.db.models import (
    ActionRow,
    ChannelAccount,
    ChannelIdentity,
    Company,
    MessageRow,
    OwnerAccount,
    OwnerFeed,
    Person,
    RawEvent,
    Send,
)
from app.pipeline import approvals, case_repo
from app.sender.execute import SenderDeps, execute_action

MAILBOX, OWNER, OWNER_MAIL = "beheer@example.test", "+31600000100", "harjot@example.test"
TENANT_MAIL, TENANT_NR, VALID_FROM = "sanne@example.test", "+31612345678", date(2026, 1, 1)
REPLY: dict[str, Any] = {
    "kind": "reply_draft",
    "channel": "gmail",
    "subject": None,
    "body_variants": ["Optie A", "Optie B"],
}


@dataclass
class Env:
    engine: Engine
    company_id: UUID
    case_id: UUID
    deps: SenderDeps
    wa: FakeWhatsAppOutbound
    drafts: FakeDrafts
    replies: FakeDrafts


def inbound(s: Session, cid: UUID, person_id: UUID, channel: Channel, sender: str, at: datetime) -> MessageRow:
    raw = RawEvent(company_id=cid, provider=channel, provider_msg_id=f"in-{new_id()}", payload={})
    s.add(raw)
    s.flush()
    msg = MessageRow(
        company_id=cid, raw_event_id=raw.id, channel=channel, provider_msg_id=raw.provider_msg_id,
        thread_ref="thr-1" if channel is Channel.gmail else sender, sender_identity=sender,
        direction=Direction.inbound, sent_at=at, created_at=at, text="Lekkage", person_id=person_id,
        meta={"subject": "Lekkage badkamer", "message_id": "<m1@example.test>", "mailbox": MAILBOX},
    )  # fmt: skip
    s.add(msg)
    s.flush()
    return msg


def make_env(migrated_engine: Engine, committed_company: Company) -> Env:
    cid, recent = committed_company.id, datetime.now(UTC) - timedelta(hours=1)
    with Session(migrated_engine) as s:
        s.execute(update(Company).where(Company.id == cid).values(outbound_mode=OutboundMode.send))
        owner = OwnerAccount(company_id=cid, display_name="Harjot", whatsapp_e164=OWNER, email=OWNER_MAIL)
        s.add_all([ChannelAccount(company_id=cid, channel=Channel.gmail, address=MAILBOX), owner])
        person = Person(company_id=cid, kind=PersonKind.tenant, display_name="Sanne", valid_from=VALID_FROM)
        s.add(person)
        s.flush()
        for channel, identity in ((Channel.gmail, TENANT_MAIL), (Channel.whatsapp, TENANT_NR)):
            s.add(ChannelIdentity(company_id=cid, person_id=person.id, channel=channel, identity=identity,
                                  valid_from=VALID_FROM))  # fmt: skip
        case_id = case_repo.create_case(s, cid, person.id, Category.maintenance, Urgency.high)
        for channel, sender in ((Channel.gmail, "Sanne@Example.TEST"), (Channel.whatsapp, TENANT_NR)):
            msg = inbound(s, cid, person.id, channel, sender, recent)
            case_repo.link_message(s, cid, case_id, msg.id, LinkMethod.new_case, None)
        s.commit()
    mailbox = FakeMailbox(MAILBOX, MemoryMailboxStore())
    wa, drafts, replies = FakeWhatsAppOutbound(), FakeDrafts(mailbox), FakeDrafts(mailbox)
    deps = SenderDeps(migrated_engine, wa, lambda _a: drafts, gmail_sender=lambda _a: replies)
    return Env(migrated_engine, cid, case_id, deps, wa, drafts, replies)


def approved(env: Env, kind: ActionType, payload: dict[str, Any], choice: ButtonChoice = ButtonChoice.d2) -> UUID:
    with Session(env.engine) as s:
        a = ActionRow(company_id=env.company_id, case_id=env.case_id, type=kind, payload=payload, rationale="r",
                      context_ref=[], status=ActionStatus.pending_approval)  # fmt: skip
        s.add(a)
        s.flush()
        aid = approvals.open_approval(s, env.company_id, a.id, 1, urgency=Urgency.normal, now=datetime.now(UTC))
        approvals.decide(s, env.company_id, aid, choice, at=datetime.now(UTC))
        s.commit()
        return a.id


def set_rows(env: Env, model: Any, **values: Any) -> None:
    with Session(env.engine) as s, s.begin():
        s.execute(update(model).where(model.company_id == env.company_id).values(**values))


def set_company(env: Env, **values: Any) -> None:
    with Session(env.engine) as s, s.begin():
        s.execute(update(Company).where(Company.id == env.company_id).values(**values))


def alert_row(env: Env, action_id: UUID) -> OwnerFeed | None:
    key = feed.stored_key(env.company_id, f"blocked:exec:{action_id}:1")
    with Session(env.engine) as s:
        return s.scalar(
            select(OwnerFeed).where(OwnerFeed.company_id == env.company_id, OwnerFeed.idempotency_key == key)
        )


def send_count(env: Env) -> int:
    with Session(env.engine) as s:
        return int(s.scalar(select(func.count()).select_from(Send).where(Send.company_id == env.company_id)) or 0)


def assert_blocked(env: Env, action_id: UUID, reason: str) -> None:
    outcome = execute_action(env.deps, action_id, 1)
    assert outcome.status == "blocked"
    assert reason in (outcome.reason or "")
    assert (env.wa.sent, env.drafts.created, env.replies.replies) == ([], [], [])
    alert = alert_row(env, action_id)
    assert alert is not None
    assert alert.kind is FeedKind.alert
    assert reason in alert.payload["text"]
    assert "Optie" not in alert.payload["text"]  # the reason only, never the message body


def prior_send(
    env: Env,
    target: str,
    *,
    status: SendStatus = SendStatus.sent,
    channel: Channel = Channel.whatsapp,
    key: str | None = None,
    action_id: UUID | None = None,
) -> None:
    with Session(env.engine) as s, s.begin():
        s.add(Send(company_id=env.company_id, idempotency_key=key or f"prior:{new_id()}", channel=channel,
                   target=target, status=status, action_id=action_id))  # fmt: skip
