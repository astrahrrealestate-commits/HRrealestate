"""#9 Answering from documents (M10): retrieve passages, ask doc_qa, show only what the documents really say.

The owner sees text assembled here, not the model's free text: each fact is a quote that was found word for word in a
retrieved passage, with its document title, and with links, e-mail addresses and IBANs removed (a document is
untrusted, and "pay to this account" must not arrive in the assistant's voice). The model's own `answer` is added only
when it carries none of those either. Documents flagged suspicious never become context.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import DocAnswer
from app.core.settings import Settings
from app.db.enums import DocLinkKind
from app.db.models import Case
from app.llm.agents.doc_qa import DOC_QA, Passage, doc_qa_prompt, ref_of
from app.llm.calls import CallContext, run_agent
from app.pipeline.concierge_sanitize import REDACTED, sanitize
from app.pipeline.document_search import DocFilter, top_passages
from app.pipeline.output_guard import URL

NOT_FOUND_TEXT = "I could not find that in your documents."
NO_DOCUMENTS_TEXT = "I have no documents that match that yet."
_EMAIL = re.compile(r"\S+@\S+")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b", re.IGNORECASE)
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Quote:
    document_id: UUID
    title: str
    text: str


@dataclass(frozen=True)
class DocQaResult:
    found: bool
    text: str  # owner-facing, assembled here
    quotes: list[Quote] = field(default_factory=list)
    call_made: bool = False


def _plain(text: str) -> str:
    return _SPACE.sub(" ", text).strip().lower()


def strip_risky(text: str) -> str:
    """Links, e-mail addresses and IBANs out; everything else (amounts, dates, names) stays: they are the answer."""
    for pattern in (URL, _EMAIL, _IBAN):
        text = pattern.sub(REDACTED, text)
    return text


def verify_quotes(answer: DocAnswer, passages: list[Passage]) -> list[Quote]:
    """Quotes whose words appear in the passage they name (case and spacing aside); the rest are dropped."""
    by_ref = {ref_of(p): p for p in passages}
    seen: set[tuple[UUID, str]] = set()
    verified: list[Quote] = []
    for q in answer.quotes:
        passage = by_ref.get(q.doc_ref)
        needle = _plain(q.text)
        if passage is None or len(needle) < 8 or needle not in _plain(passage.text):
            continue
        if (passage.document_id, needle) not in seen:
            seen.add((passage.document_id, needle))
            verified.append(Quote(passage.document_id, passage.title, q.text.strip()))
    return verified


def _day(d: date | None) -> str:
    return d.isoformat() if d else "undated"


def render(answer: DocAnswer, quotes: list[Quote], passages: list[Passage]) -> str:
    """The shown text: the model's answer when it is clean, then each verified quote under its document title."""
    lines: list[str] = []
    plain = _SPACE.sub(" ", answer.answer).strip()
    if plain and strip_risky(plain) == plain:  # a model answer with a link, address or IBAN in it is left out
        lines.append(plain[:600])
    meta = {p.document_id: p for p in passages}
    for q in quotes:
        p = meta[q.document_id]
        lines.append(f"From {sanitize(q.title)[:80]} ({p.doc_type}, {_day(p.document_date)}): «{strip_risky(q.text)}»")
    return "\n".join(line for line in lines if line.strip())


def case_scope(session: Session, company_id: UUID, case_id: UUID) -> tuple[tuple[DocLinkKind, UUID], ...]:
    """Everything that places a document with this case: the case, its unit, lease and main person."""
    case = session.scalar(select(Case).where(Case.id == case_id, Case.company_id == company_id))
    if case is None:
        return ()
    refs = ((DocLinkKind.case, case.id), (DocLinkKind.unit, case.unit_id), (DocLinkKind.lease, case.lease_id),
            (DocLinkKind.person, case.primary_person_id))  # fmt: skip
    return tuple((kind, ref) for kind, ref in refs if ref is not None)


def answer_from_documents(engine: Engine, settings: Settings, company_id: UUID, question: str,
                          case_id: UUID | None = None) -> DocQaResult:  # fmt: skip
    """Retrieve, ask, verify. Budget stops propagate to the caller (a fixed limit answer); invalid model output too."""
    with Session(engine) as session:
        scope = case_scope(session, company_id, case_id) if case_id else ()
        if case_id and not scope:
            return DocQaResult(False, NO_DOCUMENTS_TEXT)
        passages = top_passages(session, company_id, question, DocFilter(any_link=scope, readable_only=True))
    if not passages:
        return DocQaResult(False, NO_DOCUMENTS_TEXT if case_id else NOT_FOUND_TEXT)
    ctx = CallContext(company_id, "doc_qa")
    result = run_agent(engine, settings, DOC_QA, doc_qa_prompt(question, passages), ctx)
    quotes = verify_quotes(result.output, passages) if result.output.found else []
    if not quotes:
        return DocQaResult(False, NOT_FOUND_TEXT, call_made=True)
    return DocQaResult(True, render(result.output, quotes, passages), quotes, call_made=True)
