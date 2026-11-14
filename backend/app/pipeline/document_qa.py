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
from app.llm.agents.doc_qa import DOC_QA, Passage, doc_qa_prompt, pages_label, ref_of
from app.llm.calls import CallContext, run_agent
from app.llm.embeddings import TextEmbedder, build_embedder
from app.pipeline.concierge_sanitize import REDACTED, sanitize
from app.pipeline.document_search import DocFilter
from app.pipeline.output_guard import URL
from app.pipeline.rag import FactAnswer, retrieve_context

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
    doc_type: str = "other"
    document_date: date | None = None
    pages: tuple[int, ...] = ()


@dataclass(frozen=True)
class DocQaResult:
    found: bool
    text: str  # owner-facing, assembled here
    quotes: list[Quote] = field(default_factory=list)
    call_made: bool = False
    route: str = "none"  # "fact" (stored fact, no generation) | "hybrid" (retrieved passages) | "none"
    data: dict[str, object] = field(default_factory=dict)  # structured extras for the dashboard (fact, pages, counts)


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
            verified.append(
                Quote(
                    passage.document_id,
                    passage.title,
                    q.text.strip(),
                    passage.doc_type,
                    passage.document_date,
                    passage.pages,
                )
            )
    return verified


def _day(d: date | None) -> str:
    return d.isoformat() if d else "undated"


_NUMBER = re.compile(r"\d[\d.,]*\d|\d")


def _grounded(answer: str, quotes: list[Quote]) -> bool:
    """Every number, amount and date in the model's sentence appears in a verified quote: it adds no figure of its own
    (a document that talks the model into "pay 12.34.56.789 today" cannot reach the owner in the assistant's voice)."""
    quoted = " ".join(q.text for q in quotes)
    return all(n in quoted for n in _NUMBER.findall(answer))


def render(answer: DocAnswer, quotes: list[Quote], passages: list[Passage]) -> str:
    """The shown text: the model's answer when it is clean, then each verified quote under its document title."""
    lines: list[str] = []
    plain = _SPACE.sub(" ", answer.answer).strip()
    if plain and strip_risky(plain) == plain and _grounded(plain, quotes):  # else only the quotes are shown
        lines.append(plain[:600])
    for q in quotes:
        where = f"{q.doc_type}, {_day(q.document_date)}{pages_label(q.pages)}"
        lines.append(f"From {sanitize(q.title)[:80]} ({where}): «{strip_risky(q.text)}»")
    return "\n".join(line for line in lines if line.strip())


def case_scope(session: Session, company_id: UUID, case_id: UUID) -> tuple[tuple[DocLinkKind, UUID], ...]:
    """What places a document with THIS case: the case, its lease and its main person. Not its unit: a unit's
    documents include earlier tenants' and co-tenants' papers, which must never reach another tenant's draft."""
    case = session.scalar(select(Case).where(Case.id == case_id, Case.company_id == company_id))
    if case is None:
        return ()
    refs = (
        (DocLinkKind.case, case.id),
        (DocLinkKind.lease, case.lease_id),
        (DocLinkKind.person, case.primary_person_id),
    )
    return tuple((kind, ref) for kind, ref in refs if ref is not None)


def fact_text(fact: FactAnswer) -> str:
    """A stored fact, shown with its source and without generation. Labels and values are stripped like quotes."""
    label = strip_risky(fact.label.replace("_", " "))
    day = _day(fact.document_date if isinstance(fact.document_date, date) else None)
    return f"From {sanitize(fact.title)[:80]} ({fact.doc_type}, {day}): {label}: {strip_risky(fact.value)}"


def answer_from_documents(
    engine: Engine, settings: Settings, company_id: UUID, question: str, case_id: UUID | None = None,
    embedder: TextEmbedder | None = None,
) -> DocQaResult:  # fmt: skip
    """Retrieve (fact route or hybrid), ask, verify. Budget stops propagate to the caller (a fixed limit answer)."""
    with Session(engine) as session:
        scope = case_scope(session, company_id, case_id) if case_id else ()
    if case_id and not scope:
        return DocQaResult(False, NO_DOCUMENTS_TEXT)
    flt = DocFilter(any_link=scope, readable_only=True)
    found = retrieve_context(engine, settings, company_id, question, flt, embedder or build_embedder(settings))
    if found.fact is not None:
        fact_data: dict[str, object] = {"fact": {"label": found.fact.label, "value": strip_risky(found.fact.value)}}
        return DocQaResult(True, fact_text(found.fact), route="fact", data=fact_data)
    if not found.passages:
        return DocQaResult(False, NO_DOCUMENTS_TEXT if case_id else NOT_FOUND_TEXT, route="none")
    result = run_agent(
        engine, settings, DOC_QA, doc_qa_prompt(question, found.passages), CallContext(company_id, "doc_qa")
    )
    quotes = verify_quotes(result.output, found.passages) if result.output.found else []
    data: dict[str, object] = {
        "candidates": found.candidates,
        "reranked": found.reranked,
        "passages": len(found.passages),
    }
    if not quotes:
        return DocQaResult(False, NOT_FOUND_TEXT, call_made=True, route="hybrid", data=data)
    return DocQaResult(True, render(result.output, quotes, found.passages), quotes, True, "hybrid", data)
