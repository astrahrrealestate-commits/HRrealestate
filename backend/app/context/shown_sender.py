"""The name the screen shows for the sender of one message. Each message is named from its own row, never from the
case's main contact, so the name and the address shown beside it always belong to the same sender."""

import re
import unicodedata
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.db.models import ChannelIdentity, MessageRow, Person

MAX_SHOWN_NAME = 80
_INVISIBLE = frozenset({"⠀", "ᅟ", "ᅠ", "ㅤ"})  # blank glyphs that are not format characters
_GREETABLE = re.compile(r"(?:[^\W\d_]|[ .,'’\-]){1,60}")
MAX_GREETING_WORDS = 5


def saved_names(session: Session, company_id: UUID, messages: Iterable[MessageRow]) -> dict[UUID, str]:
    """Saved contact name of each message's sender, by message id: the message's person, or, before the pipeline has
    linked one, the person who currently holds that address or number."""
    rows = list(messages)
    ids = {m.person_id for m in rows if m.person_id}
    unlinked = {m.sender_identity for m in rows if not m.person_id}
    by_person: dict[UUID, str] = {}
    by_identity: dict[tuple[Channel, str], str] = {}
    if ids:
        query = select(Person.id, Person.display_name).where(Person.company_id == company_id, Person.id.in_(ids))
        by_person = {row.id: row.display_name for row in session.execute(query)}
    if unlinked:
        held = (
            select(ChannelIdentity.channel, ChannelIdentity.identity, Person.display_name)
            .join(Person, Person.id == ChannelIdentity.person_id)
            .where(
                ChannelIdentity.company_id == company_id,
                Person.company_id == company_id,
                ChannelIdentity.identity.in_(unlinked),
                ChannelIdentity.valid_to.is_(None),
            )
        )
        by_identity = {(row.channel, row.identity): row.display_name for row in session.execute(held)}
    found = {
        m.id: by_person.get(m.person_id) if m.person_id else by_identity.get((m.channel, m.sender_identity))
        for m in rows
    }
    return {message_id: name for message_id, name in found.items() if name}


def _tidy(name: object) -> str:
    """A sender-chosen name without invisible or direction-changing characters, short enough to leave the address
    visible beside it."""
    kept = "".join(
        " " if c.isspace() else c
        for c in str(name or "")
        if c.isspace() or (c not in _INVISIBLE and unicodedata.category(c) not in ("Cc", "Cf"))
    )
    return " ".join(kept.split())[:MAX_SHOWN_NAME].strip()


def shown_sender_name(msg: MessageRow, person_name: str | None) -> str:
    """An email shows what its own headers said (Reply-To first, ADR 0016): that name, else the address. The saved
    contact name is for mail stored without headers (history imports) and for chats, then the chat profile name."""
    meta = msg.meta if isinstance(msg.meta, dict) else {}
    if msg.channel is Channel.gmail:
        header_name = _tidy(meta.get("from_name"))
        if header_name:
            return header_name
        if meta.get("from"):
            return msg.sender_identity
    return person_name or _tidy(meta.get("contact_name")) or msg.sender_identity


def greeting_name(name: str) -> str | None:
    """`name` when it can open a letter; None for an address, a number, a link or a sentence."""
    if not _GREETABLE.fullmatch(name) or "www." in name.lower() or len(name.split()) > MAX_GREETING_WORDS:
        return None
    return name
