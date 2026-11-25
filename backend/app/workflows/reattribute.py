"""One-off repair (ADR 0016): mail stored under one of our own addresses, because the team forwarded it, gets the
original sender. Not a DBOS workflow; run by hand with `python -m app.workflows.reattribute_cli`.

Each candidate's original is read again from Gmail and passed through the ingestion rule (`to_message`), so old mail
gets the sender new mail would. Only the message changes: sender, name, direction and contact. Cases and flats are
left as they are and listed for a person; their unsent replies are cancelled. Mail Gmail marks as sent, and mail
naming nobody else, is left alone. Reading comes first; every write then happens in one transaction, which a dry run
rolls back, so its report is what an applying run would do. A second run finds nothing: a repaired row no longer
carries our address.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.channels.gmail.google import GmailApiError
from app.channels.gmail.inbound import to_message
from app.channels.gmail.ports import GmailMailbox
from app.contracts import Channel, Direction, Message
from app.core.errors import IgnoredMessageError, NotFoundError, UnroutableMessageError
from app.db.models import Case, CaseLink, Company, MessageRow, Person
from app.directory.identity import resolve_person
from app.ingestion.process import company_mailboxes, owner_addresses
from app.ingestion.repository import resolve_channel_account
from app.workflows.reattribute_replies import (
    CancelledReply,
    CaseToCheck,
    RepairRefusedError,
    cancel_unsent_replies,
)

__all__ = ["Change", "RepairRefusedError", "Report", "gmail_api_id", "reattribute"]

Mailboxes = Callable[[str], GmailMailbox]
MIN_IMAP_ID_DIGITS = 18  # X-GM-MSGID in decimal; a 16-character API id that happens to be all digits is shorter
_HEADER_KEYS = ("from", "from_name", "header_from", "forwarded_by", "mailbox", "labels")


@dataclass(frozen=True)
class Change:
    message_id: UUID
    old_sender: str
    new_sender: str
    was_marked_sent: bool = False


@dataclass
class Report:
    changes: list[Change] = field(default_factory=list)
    cancelled: list[CancelledReply] = field(default_factory=list)
    cases: list[CaseToCheck] = field(default_factory=list)
    unchanged: int = 0  # really ours: sent by the mailbox, or no other sender named
    unrecoverable: int = 0  # the original cannot be read again
    uncertain: int = 0  # stored as sent, and only quoted text names someone else: left alone


@dataclass(frozen=True)
class _Candidate:
    message_id: UUID
    provider_msg_id: str
    sender: str
    stored_as_sent: bool


@dataclass(frozen=True)
class _Found:
    candidate: _Candidate
    message: Message
    meta: dict[str, Any]


@dataclass(frozen=True)
class _Scope:
    company_id: UUID
    mailbox: str
    team: frozenset[str]
    boxes: frozenset[str]


def gmail_api_id(stored: str) -> str | None:
    """The Gmail API id behind a stored provider message id; None for a hashed history row."""
    if stored.startswith("hist_"):
        return None
    if stored.isdigit() and len(stored) >= MIN_IMAP_ID_DIGITS:
        return format(int(stored), "x")
    return stored


def _scope(engine: Engine, mailbox: str) -> _Scope:
    with Session(engine) as session:
        company_id = resolve_channel_account(session, Channel.gmail, mailbox).company_id
    return _Scope(company_id, mailbox, owner_addresses(engine, company_id), company_mailboxes(engine, company_id))


def _candidates(engine: Engine, scope: _Scope) -> list[_Candidate]:
    received_in = func.lower(MessageRow.meta["mailbox"].astext)
    query = (
        select(MessageRow)
        .where(
            MessageRow.company_id == scope.company_id,
            MessageRow.channel == Channel.gmail,
            func.lower(MessageRow.sender_identity).in_(scope.team | scope.boxes),
            (received_in == scope.mailbox) | received_in.is_(None),  # history imports record no mailbox
        )
        .order_by(MessageRow.sent_at, MessageRow.id)
    )
    with Session(engine) as session:
        return [
            _Candidate(r.id, r.provider_msg_id, r.sender_identity.lower(), r.direction is Direction.outbound)
            for r in session.scalars(query)
        ]


def _reread(gmail: GmailMailbox, candidate: _Candidate, scope: _Scope) -> _Found | str:
    """The candidate as ingestion would store it today, or why it stays: the name of a `Report` counter."""
    api_id = gmail_api_id(candidate.provider_msg_id)
    if api_id is None:
        return "unrecoverable"
    try:
        message, meta, _ = to_message(
            gmail.get_message(api_id), company_id=scope.company_id, raw_event_id=candidate.message_id,
            mailbox=scope.mailbox, forwarders=scope.team, own_addresses=scope.boxes,
        )  # fmt: skip
    except GmailApiError as exc:
        if exc.status != 400:  # an outage or a lost login stops the run; only an id Gmail rejects is skipped
            raise
        return "unrecoverable"
    except (NotFoundError, IgnoredMessageError, UnroutableMessageError, ValueError):
        return "unrecoverable"
    if message.direction is Direction.outbound or message.sender_identity in scope.team | scope.boxes:
        return "unchanged"
    if candidate.stored_as_sent and meta.get("forwarded_by"):
        return "uncertain"  # a reply of ours that quotes a forward looks the same
    return _Found(candidate, message, meta)


def _read_all(gmail: GmailMailbox, scope: _Scope, candidates: list[_Candidate], report: Report) -> list[_Found]:
    found = []
    for candidate in candidates:
        outcome = _reread(gmail, candidate, scope)
        if isinstance(outcome, _Found):
            found.append(outcome)
        else:
            setattr(report, outcome, getattr(report, outcome) + 1)
    return found


def _rewrite(session: Session, company_id: UUID, found: _Found) -> MessageRow | None:
    """Give one row its real sender and contact, keeping the old values in `meta.reattributed_from`."""
    row = session.scalar(
        select(MessageRow)
        .where(MessageRow.company_id == company_id, MessageRow.id == found.candidate.message_id)
        .with_for_update()
    )
    if row is None or row.sender_identity.lower() != found.candidate.sender:
        return None
    meta = row.meta or {}
    before = {
        "sender": row.sender_identity,
        "direction": row.direction.value,
        "person_id": str(row.person_id) if row.person_id else None,
        "headers": {k: meta[k] for k in _HEADER_KEYS if k in meta},
    }
    kept = {k: v for k, v in meta.items() if k not in _HEADER_KEYS}
    fresh = {k: found.meta[k] for k in _HEADER_KEYS if k in found.meta}
    row.meta = {**kept, **fresh, "reattributed_from": before}
    row.sender_identity = found.message.sender_identity
    row.direction = Direction.inbound
    row.person_id = resolve_person(
        session, company_id, Channel.gmail, row.sender_identity, found.meta.get("from_name"),
        today=row.sent_at.date(),
    )  # fmt: skip
    return row


def _affected_case_ids(session: Session, company_id: UUID, rows: list[MessageRow]) -> list[UUID]:
    """Cases linked to a repaired message, or to any message of its thread: the inbox shows a thread on each of them."""
    ids = [row.id for row in rows]
    threads = [row.thread_ref for row in rows if row.thread_ref]
    return list(
        session.scalars(
            select(CaseLink.case_id)
            .join(MessageRow, MessageRow.id == CaseLink.message_id)
            .where(
                CaseLink.company_id == company_id,
                MessageRow.company_id == company_id,
                MessageRow.channel == Channel.gmail,
                MessageRow.id.in_(ids) | MessageRow.thread_ref.in_(threads),
            )
            .distinct()
            .order_by(CaseLink.case_id)
        )
    )


def _case_to_check(session: Session, company_id: UUID, case_id: UUID) -> CaseToCheck:
    senders = session.scalars(
        select(MessageRow.sender_identity)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(
            CaseLink.company_id == company_id,
            CaseLink.case_id == case_id,
            MessageRow.company_id == company_id,
            MessageRow.direction == Direction.inbound,
        )
        .distinct()
    )
    state, contact = session.execute(
        select(Case.state, Person.display_name)
        .outerjoin(Person, (Person.id == Case.primary_person_id) & (Person.company_id == company_id))
        .where(Case.company_id == company_id, Case.id == case_id)
    ).one()
    return CaseToCheck(case_id, tuple(sorted(senders)), contact=contact, state=state.value)


def _write(session: Session, company_id: UUID, found: list[_Found], report: Report) -> None:
    session.scalar(select(Company).where(Company.id == company_id).with_for_update(key_share=True))  # as the sender
    rows = []
    for item in found:
        row = _rewrite(session, company_id, item)
        if row is None:
            continue
        rows.append(row)
        sent = item.candidate.stored_as_sent
        report.changes.append(Change(row.id, item.candidate.sender, row.sender_identity, was_marked_sent=sent))
    session.flush()
    case_ids = _affected_case_ids(session, company_id, rows)
    report.cases = [_case_to_check(session, company_id, case_id) for case_id in case_ids]
    report.cancelled = cancel_unsent_replies(session, company_id, case_ids, at=datetime.now(UTC))


def reattribute(engine: Engine, mailboxes: Mailboxes, mailbox: str, *, apply: bool) -> Report:
    """Repair the mail of one connected mailbox. `apply=False` changes nothing."""
    scope = _scope(engine, mailbox.strip().lower())
    candidates = _candidates(engine, scope)
    report = Report()
    found = _read_all(mailboxes(scope.mailbox), scope, candidates, report)
    if apply and report.unrecoverable and report.unrecoverable == len(candidates):
        raise RepairRefusedError("not one original could be read: check the mailbox and its Google connection")
    with Session(engine) as session:
        _write(session, scope.company_id, found, report)
        if apply:
            session.commit()
        else:
            session.rollback()
    return report
