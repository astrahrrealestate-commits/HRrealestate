"""Whether the owner may type into a chat right now. Mirrors the order of the sender's gates (ADR 0013): the sender
still re-checks every one of them in its claim transaction, so this only decides what the composer shows."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.chats.schemas import ComposerKind, ComposerState
from app.contracts import OutboundMode
from app.core.wa_window import window_closes_at, window_open
from app.db.models import Company, MessageRow
from app.db.own_addresses import own_addresses
from app.pipeline import chat_repo


def _anchor(inbound: MessageRow) -> datetime:
    """The older of the two clocks, as the sender anchors the window."""
    return min(inbound.sent_at, inbound.created_at)


def composer_state(
    company: Company | None, inbound: MessageRow | None, now: datetime, *, own_number: bool = False
) -> ComposerState:
    state: ComposerKind
    closes = window_closes_at(_anchor(inbound)) if inbound is not None else None
    if company is None or company.paused:
        state = "paused"
    elif company.outbound_mode is not OutboundMode.send:
        state = "draft_mode"
    elif inbound is None or own_number:  # the company's own numbers are never somebody to answer
        state = "no_recipient"
    elif not window_open(_anchor(inbound), now):
        state = "window_closed"
    else:
        state = "open"
    return ComposerState(state=state, window_closes_at=closes)


def is_own_number(session: Session, company_id: UUID, chat_key: str) -> bool:
    return chat_key in own_addresses(session, company_id)


def read_composer(session: Session, company_id: UUID, chat_key: str, now: datetime) -> ComposerState:
    company = session.get(Company, company_id)
    inbound = chat_repo.latest_inbound(session, company_id, chat_key)
    return composer_state(company, inbound, now, own_number=is_own_number(session, company_id, chat_key))
