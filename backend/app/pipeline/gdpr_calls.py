"""Erasure of the model-call log (M13): every call whose prompt or output carried the erased person's words.

Two ways in. Calls made for messages record their ids (`model_calls.message_ids`) and are judged by them alone. Calls
that put a person's words in a prompt without an id (owner commands, the Super Agent, briefings, older rows) are found
by text: the person's
addresses and numbers, a full name, and a line of each of their messages. A match blanks the whole call: the log is
an audit trail, and losing a row's text is better than keeping a trace of the person.
"""

import re
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, Text, Uuid, any_, cast, func, or_, select, update
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.orm import Session

from app.db.models import ChannelIdentity, MessageRow, ModelCall, Person, PersonProfile

ERASED_CALL = {"redacted": "erased person"}
MIN_FRAGMENT = 24  # a shorter line ("Ok", "Dank je wel") also appears in other people's mail
FRAGMENT = 60
MAX_MESSAGES = 500
MAX_TERMS = 200
# Sign-offs and client footers appear in everyone's mail: never a sign of the erased person.
_BOILERPLATE = re.compile(
    r"groet|regards|verzonden (vanaf|met)|sent (from|with)|get outlook|disclaimer|vertrouwelijk|confidential",
    re.IGNORECASE,
)


def _fragment(text: str) -> str | None:
    lines = (" ".join(part.split()) for part in text.split("\n"))
    line = max((ln for ln in lines if not _BOILERPLATE.search(ln)), key=len, default="")
    return line[:FRAGMENT].lower() if len(line) >= MIN_FRAGMENT else None


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _terms(session: Session, company_id: UUID, person_id: UUID, msg_ids: Sequence[UUID]) -> list[str]:
    identities = session.scalars(
        select(ChannelIdentity.identity).where(
            ChannelIdentity.company_id == company_id, ChannelIdentity.person_id == person_id
        )
    )
    name = session.scalar(select(Person.display_name).where(Person.company_id == company_id, Person.id == person_id))
    texts = session.scalars(
        select(MessageRow.text)
        .where(MessageRow.company_id == company_id, MessageRow.id.in_(msg_ids))
        .order_by(MessageRow.sent_at.desc())
        .limit(MAX_MESSAGES)
    )
    terms = {i.strip().lower() for i in identities if len(i.strip()) >= 6}
    if name and len(name.split()) >= 2:  # a single first name matches too many strangers
        terms.add(" ".join(name.split()).lower())
    terms |= {f for t in texts if (f := _fragment(t))}
    return sorted(terms)[:MAX_TERMS]


def _matches(content: ColumnElement[str], terms: Sequence[str]) -> ColumnElement[bool]:
    return func.lower(content).like(any_(cast(array([_like(t) for t in terms]), ARRAY(Text))))


def _forget_in_memories(session: Session, company_id: UUID, terms: Sequence[str]) -> None:
    """Other people's memory (a contractor's, a co-tenant's) can name the person: it is rebuilt on the next refresh,
    from mail that no longer holds them."""
    session.execute(
        update(PersonProfile)
        .where(PersonProfile.company_id == company_id, _matches(cast(PersonProfile.memory, Text), terms))
        .values(memory=None, memory_at=None)
    )


def erase_model_calls(session: Session, company_id: UUID, person_id: UUID, msg_ids: Sequence[UUID]) -> int:
    """Blank input, output and error of the person's calls, and forget other people's memory that names them. Run
    before the messages and identities are scrubbed."""
    terms = _terms(session, company_id, person_id, msg_ids)
    if terms:
        _forget_in_memories(session, company_id, terms)
    content = func.lower(
        func.coalesce(ModelCall.input["prompt"].astext, "") + " " + func.coalesce(cast(ModelCall.output, Text), "")
    )
    found = [ModelCall.message_ids.overlap(array(list(msg_ids)))] if msg_ids else []
    if terms:
        untagged = ModelCall.message_ids == cast(array([], type_=Uuid), ARRAY(Uuid))
        found.append(untagged & _matches(content, terms))  # a tagged call names every message in its prompt
    if not found:
        return 0
    res = session.execute(
        update(ModelCall)
        .where(ModelCall.company_id == company_id, ModelCall.input != ERASED_CALL, or_(*found))
        .values(input=ERASED_CALL, output=ERASED_CALL, error=None)
    )
    return int(res.rowcount)  # type: ignore[attr-defined]
