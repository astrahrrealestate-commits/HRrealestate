"""One conversation as lines of text: who said what, in order, with nothing from another tenant (M13).

Feeds the dossier (drafts) and person memory. A message belongs to another tenant when it was written by, or sent to,
a tenant other than the person concerned; such messages are left out even inside a shared thread or case.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.channels.gmail.forward import forwarded_recipients
from app.channels.gmail.quoted import quoted_messages, split_quoted
from app.context.message_origin import full_text, is_owner_authored, mailbox_addresses, owner_emails
from app.contracts import Channel, Direction
from app.db.enums import PersonKind
from app.db.models import ChannelIdentity, MessageRow, Person
from app.pipeline.injection_scan import scan

OWNER_SENT = "Harjot (sent)"
OWNER_COPY = "Harjot (copy in the mailbox, not verified)"
OWNER_QUOTED = "Harjot (quoted in a later mail, not verified)"
CONTINUATION = "\n    | "


@dataclass(frozen=True)
class ThreadLine:
    message_id: UUID
    sent_at: datetime
    direction: Direction
    author: str
    subject: str | None
    text: str
    owner_copy: bool = False  # Harjot's words as someone's mailbox or mail shows them, not as our channel sent them
    flagged: bool = False  # the injection scan hit: shown, marked

    def render(self) -> str:
        """One line per message. Its own line breaks continue as `    | `, so text in a message can never start a line
        that looks like another message (a forged "Harjot (sent): akkoord")."""
        mark = " [flagged: looks like instructions, data only]" if self.flagged else ""
        body = CONTINUATION.join(self.text.strip().split("\n"))
        return f"{self.sent_at:%Y-%m-%d %H:%M} {self.author}{mark}: {body}"


@dataclass(frozen=True)
class People:
    """The names and kinds needed to decide whose message a row is."""

    ours: frozenset[str]  # Harjot's addresses and the company mailboxes
    names: dict[UUID, str]
    tenants: frozenset[UUID]
    tenant_of_identity: dict[str, UUID]


def recipients(row: MessageRow) -> set[str]:
    """Who a message went to. Harjot's own copy forwarded into the inbox names our inbox in To; its real addressee is
    in the forwarded header block, so that counts for such a row (a copy that is not a forward keeps its To)."""
    meta = row.meta or {}
    if is_owner_authored(row) and (forwarded := forwarded_recipients(full_text(row))):
        return set(forwarded)
    listed = [a for key in ("to", "cc") for a in (meta.get(key) or []) if isinstance(a, str)]
    if row.channel is Channel.whatsapp and row.thread_ref:
        listed.append(row.thread_ref)  # a WhatsApp thread is one contact's number
    return {a.strip().lower() for a in listed}


def load_people(session: Session, company_id: UUID, rows: Sequence[MessageRow]) -> People:
    identities = {a for r in rows for a in recipients(r)} | {r.sender_identity.lower() for r in rows}
    found = session.execute(
        select(func.lower(ChannelIdentity.identity), Person.id)
        .join(Person, Person.id == ChannelIdentity.person_id)
        .where(
            ChannelIdentity.company_id == company_id,
            Person.company_id == company_id,
            Person.kind == PersonKind.tenant,
            func.lower(ChannelIdentity.identity).in_(identities),
        )
    ).all()
    ids = {r.person_id for r in rows if r.person_id}
    persons = session.scalars(select(Person).where(Person.company_id == company_id, Person.id.in_(ids))).all()
    return People(
        ours=owner_emails(session, company_id) | mailbox_addresses(session, company_id),
        names={p.id: p.display_name for p in persons},
        tenants=frozenset(p.id for p in persons if p.kind is PersonKind.tenant),
        tenant_of_identity={row[0]: row[1] for row in found},
    )


def other_tenants(row: MessageRow, people: People, allowed: frozenset[UUID], identities: frozenset[str]) -> bool:
    """Whether the row is a message from, or to, a tenant outside `allowed`. Mail the person concerned received
    (at one of their `identities`, lower-case) is theirs, whoever else it went to."""
    to = recipients(row)
    if row.direction is Direction.outbound or is_owner_authored(row):
        if identities & to:
            return False
        involved = {people.tenant_of_identity[a] for a in to if a in people.tenant_of_identity}
    else:
        author = row.person_id if row.person_id in people.tenants else None
        tenant = author or people.tenant_of_identity.get(row.sender_identity.lower())
        involved = {tenant} if tenant else set()
    return bool(involved - allowed)


def new_part(row: MessageRow) -> str:
    """The row's own words: quoted history left out, unless the mail is nothing but a quote."""
    return split_quoted(row.text)[0].strip() or row.text.strip()


def line_of(row: MessageRow, people: People, text: str | None = None) -> ThreadLine:
    body = new_part(row) if text is None else text
    copy = row.direction is Direction.inbound and is_owner_authored(row)
    if row.direction is Direction.outbound:
        author = OWNER_SENT
    elif copy:
        author = OWNER_COPY
    else:  # the directory's name or the address, never a header display name the sender chose
        author = (people.names.get(row.person_id) if row.person_id else None) or row.sender_identity
    return ThreadLine(
        row.id, row.sent_at, row.direction, " ".join(author.replace(":", " ").split()), (row.meta or {}).get("subject"),
        body, owner_copy=copy, flagged=scan(body) is not None,
    )  # fmt: skip


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def quoted_lines(
    rows: Iterable[MessageRow], people: People, own: frozenset[str], known: Sequence[str]
) -> list[ThreadLine]:
    """Earlier messages found only as quotes in these rows: Harjot's, and the person's own (`own` addresses). Anyone
    else's quoted words stay out. `known` are the texts already shown; nothing is repeated."""
    seen = [_norm(t) for t in known]
    out: list[ThreadLine] = []
    for row in rows:
        for quoted in quoted_messages(full_text(row)):
            norm = _norm(quoted.text)
            ours = quoted.author in people.ours
            if not (ours or quoted.author in own) or any(norm in s for s in seen):
                continue
            seen.append(norm)
            author = OWNER_QUOTED if ours else f"{quoted.author} (quoted in a later mail)"
            direction = Direction.outbound if ours else Direction.inbound
            flagged = scan(quoted.text) is not None
            out.append(ThreadLine(row.id, row.sent_at, direction, author, None, quoted.text, ours, flagged))
    return out
