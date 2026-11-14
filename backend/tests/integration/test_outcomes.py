"""Outcome capture (#8): what Harjot actually sent vs the approved draft → unchanged / edited / rewritten."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import ActionType, ButtonChoice, Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.db.enums import ActionStatus, LinkMethod, OutcomeLabel, OutcomeSource, PersonKind, SendStatus
from app.db.models import ActionRow, Company, MessageRow, Outcome, Person, RawEvent, Send
from app.outcomes.capture import capture_outcomes, label_for
from app.pipeline import approvals, case_repo

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
DRAFT_B = "Geachte heer/mevrouw,\n\nKunt u een foto sturen van de lekkage?\n\nMet vriendelijke groet,\nHarjot"


def _msg(s: Session, cid: UUID, channel: Channel, direction: Direction, text: str, at: datetime, thread: str) -> UUID:
    raw = RawEvent(company_id=cid, provider=channel, provider_msg_id=str(new_id()), payload={})
    s.add(raw)
    s.flush()
    m = MessageRow(
        company_id=cid,
        raw_event_id=raw.id,
        channel=channel,
        provider_msg_id=raw.provider_msg_id,
        thread_ref=thread,
        sender_identity="sanne@example.test",
        direction=direction,
        sent_at=at,
        text=text,
        meta={"echo": True} if channel is Channel.whatsapp else {},
    )
    s.add(m)
    s.flush()
    return m.id


def _executed_reply(engine: Engine, cid: UUID, channel: Channel) -> UUID:
    with Session(engine) as s, s.begin():
        p = Person(company_id=cid, kind=PersonKind.tenant, display_name="Sanne", valid_from=date(2026, 1, 1))
        s.add(p)
        s.flush()
        inbound = _msg(s, cid, channel, Direction.inbound, "Lekkage", NOW, "thr-1")
        case_id = case_repo.create_case(s, cid, p.id, Category.maintenance, Urgency.normal)
        case_repo.link_message(s, cid, case_id, inbound, LinkMethod.new_case, None)
        a = ActionRow(
            company_id=cid,
            case_id=case_id,
            type=ActionType.reply_draft,
            payload={
                "kind": "reply_draft",
                "channel": channel.value,
                "subject": None,
                "body_variants": ["Optie A", DRAFT_B],
            },
            rationale="r",
            context_ref=[inbound],
            status=ActionStatus.pending_approval,
        )
        s.add(a)
        s.flush()
        approval = approvals.open_approval(s, cid, a.id, 1, urgency=Urgency.normal, now=NOW)
        approvals.decide(s, cid, approval, ButtonChoice.d2, at=NOW)
        a.status = ActionStatus.executed
        s.add(
            Send(
                company_id=cid,
                action_id=a.id,
                idempotency_key=f"exec:{a.id}:1",
                channel=channel,
                target="t",
                status=SendStatus.sent,
                attempted_at=NOW + timedelta(minutes=1),
            )
        )
        return a.id


@pytest.mark.parametrize(
    ("sent", "label"),
    [
        (DRAFT_B, OutcomeLabel.unchanged),
        (
            DRAFT_B.replace("een foto sturen van de lekkage", "morgen voor 12 uur foto's sturen van de meterkast"),
            OutcomeLabel.edited,
        ),
        ("Ik bel u morgen.", OutcomeLabel.rewritten),
    ],
)
def test_gmail_sent_reply_is_labelled(
    migrated_engine: Engine, committed_company: Company, sent: str, label: OutcomeLabel
) -> None:
    cid = committed_company.id
    action_id = _executed_reply(migrated_engine, cid, Channel.gmail)
    with Session(migrated_engine) as s, s.begin():
        _msg(s, cid, Channel.gmail, Direction.outbound, sent, NOW + timedelta(hours=1), "thr-1")
    assert capture_outcomes(migrated_engine, NOW + timedelta(hours=2)) == 1
    assert capture_outcomes(migrated_engine, NOW + timedelta(hours=3)) == 0  # captured once
    with Session(migrated_engine) as s:
        outcome = s.scalar(select(Outcome).where(Outcome.action_id == action_id))
    assert outcome is not None
    assert (outcome.label, outcome.source, outcome.draft_version) == (label, OutcomeSource.sent_folder, 1)


def test_whatsapp_echo_is_labelled_and_nothing_sent_means_no_outcome(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    action_id = _executed_reply(migrated_engine, cid, Channel.whatsapp)
    assert capture_outcomes(migrated_engine, NOW + timedelta(hours=2)) == 0
    with Session(migrated_engine) as s, s.begin():
        _msg(s, cid, Channel.whatsapp, Direction.outbound, DRAFT_B, NOW + timedelta(hours=3), "thr-1")
    assert capture_outcomes(migrated_engine, NOW + timedelta(hours=4)) == 1
    with Session(migrated_engine) as s:
        outcome = s.scalar(select(Outcome).where(Outcome.action_id == action_id))
    assert outcome is not None
    assert (outcome.label, outcome.source) == (OutcomeLabel.unchanged, OutcomeSource.echo)


def test_label_thresholds() -> None:
    assert label_for(0.96) is OutcomeLabel.unchanged
    assert label_for(0.6) is OutcomeLabel.edited
    assert label_for(0.59) is OutcomeLabel.rewritten
