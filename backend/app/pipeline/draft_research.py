"""Research before drafting (M13 T8): answer a mail's research questions from sources that can be checked.

Runs only when the understanding asks for it (`needs_research`, at most 3 questions), never for suspicious mail. Each
question is searched on the web (at most `MAX_SEARCHES` searches in all); a legal question first reads the company's
reference library and then searches only official sites. Pages are fetched by our own guarded fetch and reach the
model as data. A claim becomes a `Finding` only when its source exists, was found for that question, and holds the
quoted evidence word for word; its URL is the page's, never the model's. Every finding has a URL.

The result is stored once on the understanding (`research`), with the questions it could not answer. Research has
`DEADLINE_SEC`: what is not done by then is listed as unanswered, and the draft goes ahead without it.
"""

import re
import time
import unicodedata
from collections.abc import Callable, Sequence
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.channels.prices.search import SearchClient
from app.channels.registry import search_client
from app.contracts import Category, Understanding
from app.contracts.research import Finding
from app.core.errors import EstateOSError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import DocumentRow, UnderstandingRow
from app.llm.agents.draft_research import DRAFT_RESEARCH, ResearchSource, draft_research_prompt
from app.llm.calls import CallContext, is_transient, run_agent
from app.pipeline.document_qa import strip_risky
from app.pipeline.document_search import DRIVE_URL, DocFilter
from app.pipeline.rag import retrieve_cheap

log = get_logger(__name__)
MAX_QUESTIONS = 3
MAX_SEARCHES = 5
PAGES_PER_SEARCH = 3
REFERENCES_PER_QUESTION = 2
DEADLINE_SEC = 60.0
SEARCH_UNTIL_SEC = 35.0  # searches stop here: the model needs the rest
LEGAL_DOMAINS = ("wetten.overheid.nl", "rechtspraak.nl", "roz.nl")
REGION = "NL"
_LEGAL = re.compile(
    r"\b(roz|wet|wetboek|bw|artikel|art\.|huurrecht|huurcommissie|opzeg\w*|indexer\w*|huurverhoging|rechtspraak|"
    r"law|legal|statute|eviction|ontbinding|algemene bepalingen)\b",
    re.I,
)
Searcher = Callable[[Sequence[str]], SearchClient]  # allowed domains (empty = any) -> a search client


def _squash(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def is_legal(question: str, category: Category) -> bool:
    return category is Category.legal or _LEGAL.search(question) is not None


def stored_findings(research: dict[str, object] | None) -> tuple[Finding, ...]:
    found = research.get("findings") if research else None
    return tuple(Finding.model_validate(f) for f in found) if isinstance(found, list) else ()


def _references(session: Session, company_id: UUID, question: str, n: int) -> list[ResearchSource]:
    """The company's reference library: documents not tied to any tenant (ROZ provisions, standard terms)."""
    flt = DocFilter(reference_only=True, readable_only=True)
    passages = retrieve_cheap(session, company_id, question, flt, None, REFERENCES_PER_QUESTION)
    drive = dict(
        session.execute(
            select(DocumentRow.id, DocumentRow.drive_file_id).where(
                DocumentRow.company_id == company_id, DocumentRow.id.in_([p.document_id for p in passages])
            )
        ).all()
    )
    return [
        ResearchSource(n, DRIVE_URL.format(drive[p.document_id]), p.title, strip_risky(p.text))
        for p in passages
        if drive.get(p.document_id)
    ]


class _Budget:
    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock, self.started, self.searches = clock, clock(), 0

    def may_search(self) -> bool:
        return self.searches < MAX_SEARCHES and self.clock() - self.started < SEARCH_UNTIL_SEC

    def left(self) -> float:
        return DEADLINE_SEC - (self.clock() - self.started)


def _search(searcher: Searcher, query: str, legal: bool, n: int, budget: _Budget) -> list[ResearchSource]:
    if not budget.may_search():
        return []
    budget.searches += 1
    try:
        hits = searcher(LEGAL_DOMAINS if legal else ()).search(query, region=REGION, limit=PAGES_PER_SEARCH)
    except Exception as exc:  # one search that fails (provider, budget, network) never stops the draft
        log.warning("draft_research.search_failed", reason=type(exc).__name__)
        return []
    return [ResearchSource(n, hit.url, hit.title, hit.text) for hit in hits if hit.text.strip()]


def _gather(
    session: Session, company_id: UUID, questions: Sequence[str], category: Category, searcher: Searcher,
    budget: _Budget,
) -> list[ResearchSource]:  # fmt: skip
    sources: list[ResearchSource] = []
    for n, question in enumerate(questions, start=1):
        legal = is_legal(question, category)
        if legal:
            sources += _references(session, company_id, question, n)
        sources += _search(searcher, question, legal, n, budget)
    for n, question in enumerate(questions, start=1):  # a second try, with what is left, for questions with nothing
        if not any(s.question == n for s in sources):
            sources += _search(searcher, f"{question} Nederland", is_legal(question, category), n, budget)
    return sources


def checked(questions: Sequence[str], sources: Sequence[ResearchSource], claims: Sequence[object]) -> list[Finding]:
    """Only claims whose source exists, belongs to their question and holds the evidence verbatim."""
    findings: list[Finding] = []
    for claim in claims:
        q, s = getattr(claim, "question", 0), getattr(claim, "source", 0)
        if not (1 <= q <= len(questions) and 1 <= s <= len(sources)) or sources[s - 1].question != q:
            continue
        source = sources[s - 1]
        if _squash(str(getattr(claim, "evidence", ""))) not in _squash(f"{source.title}\n{source.text}"):
            continue
        answer = strip_risky(str(getattr(claim, "answer", ""))).strip()
        if answer:
            findings.append(Finding(question=questions[q - 1], answer=answer[:1500], url=source.url))
    return findings


def _ask(
    engine: Engine, settings: Settings, company_id: UUID, message_id: UUID, questions: Sequence[str],
    sources: Sequence[ResearchSource], left: float,
) -> list[Finding]:  # fmt: skip
    if not sources or left <= 1:
        return []
    timed = settings.model_copy(update={"llm_quality_timeout_sec": min(settings.llm_quality_timeout_sec, left)})
    ctx = CallContext(company_id, "draft_research", message_ids=(message_id,))
    try:
        out = run_agent(engine, timed, DRAFT_RESEARCH, draft_research_prompt(questions, sources), ctx).output
    except Exception as exc:  # a refusal, a timeout or a spent budget: draft without research, say what is missing
        if not (isinstance(exc, EstateOSError) or is_transient(exc)):
            raise
        log.warning("draft_research.model_failed", reason=type(exc).__name__)
        return []
    return checked(questions, sources, out.claims)


def _load(session: Session, company_id: UUID, message_id: UUID) -> tuple[UnderstandingRow, Understanding] | None:
    row = session.scalar(
        select(UnderstandingRow).where(
            UnderstandingRow.company_id == company_id, UnderstandingRow.message_id == message_id
        )
    )
    if row is None:
        return None
    try:
        return row, Understanding.model_validate(row.body)
    except ValueError:
        return None


def _store(engine: Engine, company_id: UUID, row_id: UUID, findings: list[Finding], unanswered: list[str]) -> None:
    research = {"findings": [f.model_dump(mode="json") for f in findings], "unanswered": unanswered}
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(UnderstandingRow).where(UnderstandingRow.company_id == company_id, UnderstandingRow.id == row_id)
        )
        if row is not None and row.research is None:
            row.research = research


def research_for(
    engine: Engine, settings: Settings, company_id: UUID, message_id: UUID, *, searcher: Searcher | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[Finding, ...]:  # fmt: skip
    """The findings for one message (stored the first time; a repeat reads them back)."""
    with Session(engine) as session:
        loaded = _load(session, company_id, message_id)
        if loaded is None:
            return ()
        row, und = loaded
        if row.research is not None:
            return stored_findings(row.research)
        if not und.needs_research or und.suspicious.flag:
            return ()
        questions = [q for q in (strip_risky(q).strip() for q in und.research_questions[:MAX_QUESTIONS]) if q]
        search = searcher or (lambda domains: search_client(settings, engine, company_id, domains))
        budget = _Budget(clock)
        sources = _gather(session, company_id, questions, und.category, search, budget) if questions else []
    findings = _ask(engine, settings, company_id, message_id, questions, sources, budget.left())
    unanswered = [q for q in questions if not any(f.question == q for f in findings)]
    _store(engine, company_id, row.id, findings, unanswered)
    log.info("draft_research.done", findings=len(findings), unanswered=len(unanswered), searches=budget.searches)
    return tuple(findings)
