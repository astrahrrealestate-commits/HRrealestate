"""Outcome capture (#8): compare what Harjot actually sent with the draft he approved.

In `outbound_mode=draft` Harjot sends the Gmail draft himself (it comes back through the Sent folder as an outbound
message in the same thread) or pastes the WhatsApp text (it comes back as an echo). The first outbound message in
that thread after delivery is compared with the chosen draft (rapidfuzz, normalised whitespace). In `send` mode the
sender delivers the approved text itself, so the comparison reads `unchanged` (follow-up: label those sends apart).
"""

from datetime import datetime, timedelta

from rapidfuzz import fuzz
from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contracts import ActionType, ButtonChoice, Channel, Direction
from app.db.enums import ActionStatus, ApprovalStatus, OutcomeLabel, OutcomeSource, SendStatus
from app.db.models import ActionRow, Approval, CaseLink, MessageRow, Outcome, Send

LOOKBACK = timedelta(days=14)
UNCHANGED, EDITED = 0.95, 0.60
_VARIANT = {ButtonChoice.d2: 1, ButtonChoice.d3: 2}


def label_for(similarity: float) -> OutcomeLabel:
    if similarity >= UNCHANGED:
        return OutcomeLabel.unchanged
    return OutcomeLabel.edited if similarity >= EDITED else OutcomeLabel.rewritten


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _pending(session: Session, now: datetime) -> list[tuple[ActionRow, Send]]:
    captured = select(Outcome.action_id)
    return list(
        session.execute(
            select(ActionRow, Send)
            .join(Send, Send.action_id == ActionRow.id)
            .where(
                ActionRow.status == ActionStatus.executed,
                ActionRow.type == ActionType.reply_draft,
                Send.status == SendStatus.sent,
                Send.attempted_at >= now - LOOKBACK,
                ActionRow.id.not_in(captured),
            )
        ).all()
    )


def _chosen_text(session: Session, action: ActionRow) -> str:
    choice = session.scalar(
        select(Approval.choice).where(
            Approval.company_id == action.company_id,
            Approval.action_id == action.id,
            Approval.draft_version == action.draft_version,
            Approval.status == ApprovalStatus.approved,
        )
    )
    variants: list[str] = action.payload.get("body_variants") or [""]
    return variants[min(_VARIANT.get(choice, 0) if choice else 0, len(variants) - 1)]


def _sent_message(session: Session, action: ActionRow, send: Send) -> MessageRow | None:
    channel = Channel(action.payload.get("channel", Channel.whatsapp.value))
    threads = (
        select(MessageRow.thread_ref)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(
            CaseLink.company_id == action.company_id,
            CaseLink.case_id == action.case_id,
            MessageRow.channel == channel,
            MessageRow.direction == Direction.inbound,
        )
    )
    return session.scalar(
        select(MessageRow)
        .where(
            MessageRow.company_id == action.company_id,
            MessageRow.channel == channel,
            MessageRow.direction == Direction.outbound,
            MessageRow.thread_ref.in_(threads),
            MessageRow.sent_at >= send.attempted_at,
        )
        .order_by(MessageRow.sent_at)
        .limit(1)
    )


def _record(session: Session, action: ActionRow, msg: MessageRow, draft: str) -> bool:
    similarity = fuzz.ratio(_norm(draft), _norm(msg.text)) / 100.0
    source = OutcomeSource.sent_folder if msg.channel is Channel.gmail else OutcomeSource.echo
    inserted = session.execute(
        insert(Outcome)
        .values(
            company_id=action.company_id,
            action_id=action.id,
            draft_version=action.draft_version,
            final_text=msg.text,
            label=label_for(similarity),
            similarity=similarity,
            source=source,
        )
        .on_conflict_do_nothing(index_elements=["action_id", "draft_version"])
        .returning(Outcome.id)
    ).scalar()
    return inserted is not None


def capture_outcomes(engine: Engine, now: datetime) -> int:
    """Label every executed reply whose sent version has arrived (system cron, all companies). Returns new rows."""
    created = 0
    with Session(engine) as session, session.begin():
        for action, send in _pending(session, now):
            msg = _sent_message(session, action, send)
            if msg is not None:
                created += _record(session, action, msg, _chosen_text(session, action))
    return created
