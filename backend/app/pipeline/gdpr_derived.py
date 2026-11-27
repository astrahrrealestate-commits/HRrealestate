"""Erasure of what was derived from a person's messages (M13), called by `erase_person` before the redaction.

- `understandings`: the research findings (migration 0060) are dropped and the free text of the stored Understanding
  (intent, people, dates, research questions, open obligation, suspicion reason) is blanked; category, urgency and the
  flags stay, so the inbox still reads the row.
- `attachments.extracted_text` of their messages is cleared, and a document read from one of those attachments loses
  its chunks, title, summary, facts and embedding. The row stays: diligence and Drive plans point at it.
- Astra's dashboard turns that cite one of their messages (`agent_turns.results[*].data.sources`): that source's label
  ("name, channel, date") and the cited answer are blanked, and the conversation's rolling summary is reset so it is
  rebuilt from the blanked turns.
Strictly company-scoped (invariant 4).
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Text, bindparam, delete, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.db.models import AgentConversation, AgentTurn, AttachmentRow, DocumentChunk, DocumentRow, UnderstandingRow
from app.pipeline.concierge_outcome import stored_answer

ERASED_TEXT = "[Content erased per GDPR request]"
ERASED_LABEL = "[Erased person]"
_BLANK_BODY: dict[str, Any] = {
    "intent": ERASED_TEXT,
    "entities": {"people": [], "unit_refs": [], "dates": [], "amounts": []},
    "research_questions": [],
    "open_obligation": None,
}
_CITING = text(
    """
    SELECT DISTINCT t.id FROM agent_turns t
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(t.results) = 'array' THEN t.results ELSE '[]'::jsonb END) r
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(r -> 'data' -> 'sources') = 'array' THEN r -> 'data' -> 'sources' ELSE '[]'::jsonb END) s
    WHERE t.company_id = :company_id AND s ->> 'kind' = 'message' AND s ->> 'ref' = ANY(:refs)
    """
).bindparams(bindparam("refs", type_=ARRAY(Text)))


def erase_derived(session: Session, company_id: UUID, msg_ids: Sequence[UUID]) -> int:
    """Blank everything derived from these messages; returns the number of Astra turns blanked."""
    if not msg_ids:
        return 0
    _erase_understandings(session, company_id, msg_ids)
    _erase_attachment_text(session, company_id, msg_ids)
    return _erase_turns(session, company_id, {str(m) for m in msg_ids})


def _erase_understandings(session: Session, company_id: UUID, msg_ids: Sequence[UUID]) -> None:
    rows = session.scalars(
        select(UnderstandingRow).where(
            UnderstandingRow.company_id == company_id, UnderstandingRow.message_id.in_(msg_ids)
        )
    )
    for row in rows:
        body = {**row.body, **_BLANK_BODY}
        if isinstance(body.get("suspicious"), dict):
            body["suspicious"] = {**body["suspicious"], "reason": None}
        row.body = body
        row.research = None


def _erase_attachment_text(session: Session, company_id: UUID, msg_ids: Sequence[UUID]) -> None:
    attachments = select(AttachmentRow.id).where(
        AttachmentRow.company_id == company_id, AttachmentRow.message_id.in_(msg_ids)
    )
    docs = select(DocumentRow.id).where(
        DocumentRow.company_id == company_id, DocumentRow.attachment_id.in_(attachments)
    )
    session.execute(
        delete(DocumentChunk).where(DocumentChunk.company_id == company_id, DocumentChunk.document_id.in_(docs))
    )
    session.execute(
        update(DocumentRow)
        .where(DocumentRow.company_id == company_id, DocumentRow.attachment_id.in_(attachments))
        .values(title=ERASED_TEXT, summary=None, facts=None, doc_embedding=None)
    )
    session.execute(
        update(AttachmentRow)
        .where(AttachmentRow.company_id == company_id, AttachmentRow.message_id.in_(msg_ids))
        .values(extracted_text=None)
    )


def _erase_turns(session: Session, company_id: UUID, refs: set[str]) -> int:
    ids = list(session.scalars(_CITING, {"company_id": company_id, "refs": sorted(refs)}))
    if not ids:
        return 0
    turns = list(session.scalars(select(AgentTurn).where(AgentTurn.company_id == company_id, AgentTurn.id.in_(ids))))
    for turn in turns:
        results = [_blank_result(r, refs) for r in turn.results or []]
        turn.results = results
        turn.answer = stored_answer(results)
    session.execute(
        update(AgentConversation)
        .where(
            AgentConversation.company_id == company_id,
            AgentConversation.id.in_({t.conversation_id for t in turns}),
        )
        .values(summary="", summary_through=None)
    )
    return len(turns)


def _blank_result(result: Any, refs: set[str]) -> Any:
    sources = (result.get("data") or {}).get("sources") if isinstance(result, dict) else None
    if not isinstance(sources, list) or not any(_cites(s, refs) for s in sources):
        return result
    blanked = [{**s, "label": ERASED_LABEL} if _cites(s, refs) else s for s in sources]
    return {**result, "summary": ERASED_TEXT, "data": {**result["data"], "sources": blanked}}


def _cites(source: Any, refs: set[str]) -> bool:
    return isinstance(source, dict) and source.get("kind") == "message" and source.get("ref") in refs
