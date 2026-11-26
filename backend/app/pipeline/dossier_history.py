"""Older mail of the same person that matches the mail being answered (M13): beyond the newest messages the dossier
already holds, found by message search. Only chunks of this person's own conversations: a chunk that holds anyone
else's words is left out."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Direction
from app.db.models import MessageChunk
from app.llm.embeddings import TextEmbedder
from app.pipeline.concierge_sanitize import redact_contact
from app.pipeline.conversation import ThreadLine
from app.pipeline.injection_scan import scan
from app.tools.message_rag.search import search_messages

MAX_OLDER = 6
MAX_PRECEDENTS = 3
OLDER = "earlier mail of this sender"
PRECEDENT = "precedent from another case (style & policy pattern only)"


def older_mail(
    session: Session, company_id: UUID, person_id: UUID, query: str, embedder: TextEmbedder | None,
    shown: Collection[UUID],
) -> tuple[tuple[ThreadLine, ...], tuple[UUID, ...]]:  # fmt: skip
    """Lines, and every message id they hold (for the call log and erasure)."""
    if not query.strip():
        return (), ()
    hits = search_messages(session, company_id, query, embedder, person_id=person_id, limit=MAX_OLDER * 2)
    fresh = [h for h in hits if h.person_id == person_id and not set(h.message_ids) <= set(shown)]
    rows = session.execute(
        select(MessageChunk.id, MessageChunk.participant_ids).where(
            MessageChunk.company_id == company_id, MessageChunk.id.in_([h.chunk_id for h in fresh])
        )
    )
    participants = {row[0]: row[1] for row in rows}
    own = [h for h in fresh if set(participants.get(h.chunk_id) or []) <= {person_id}][:MAX_OLDER]
    lines = tuple(
        ThreadLine(
            h.first_message_id, h.first_sent_at, Direction.inbound, OLDER, None, h.text, False, bool(scan(h.text))
        )
        for h in own
    )
    return lines, tuple(dict.fromkeys(i for h in own for i in h.message_ids))


def similar_conversations(
    session: Session,
    company_id: UUID,
    person_id: UUID | None,
    query: str,
    embedder: TextEmbedder | None,
    shown: Collection[UUID],
) -> tuple[ThreadLine, ...]:
    """Redacted outbound precedents from similar company cases when a current reply is ambiguous.

    Only uses outbound (Harjot/team) messages from other contacts, skips anything flagged for prompt injection, and
    strips links, emails, phones and IBANs so no other party's contact details leak into a dossier."""
    if not query.strip():
        return ()
    hits = search_messages(session, company_id, query, embedder, direction="outbound", limit=MAX_PRECEDENTS * 4)
    seen = set(shown)
    out: list[ThreadLine] = []
    for h in hits:
        if person_id is not None and h.person_id == person_id:
            continue
        if set(h.message_ids) <= seen or scan(h.text) is not None:
            continue
        cleaned = redact_contact(h.text).strip()
        if not cleaned:
            continue
        out.append(
            ThreadLine(h.first_message_id, h.first_sent_at, Direction.outbound, PRECEDENT, None, cleaned, False, False)
        )
        if len(out) >= MAX_PRECEDENTS:
            break
    return tuple(out)
