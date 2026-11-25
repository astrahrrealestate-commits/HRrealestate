"""Document RAG evaluation (ADR 0008): seeds the synthetic corpus for a company, asks every question through the real
retrieval pipeline and scores what comes back. Needs Postgres with pgvector (the pipeline is SQL).

Scores (per run, offline models or real ones): `context_hit` (an expected fragment is in the retrieved context),
`doc_hit` (the expected document is), `mrr` (rank of the first chunk holding the fragment among the fused candidates),
`fact_accuracy` (single-fact questions answered from stored facts), `abstain_accuracy` (nothing relevant means nothing
retrieved), and two safety counts that must stay 0: `isolation_violations` (another tenant's text, or the injected
clause, in the context). `real_only` questions are scored but never asserted offline.

Run it against a scratch database with real models: `make rag-eval` (EMBEDDING_MODEL, LLM_MODEL in the environment).
"""

import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import CaseState, Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import DocLinkKind, DocumentStatus, PersonKind
from app.db.models import (
    AttachmentRow,
    Case,
    Company,
    DocumentChunk,
    DocumentLink,
    DocumentRow,
    Lease,
    MessageRow,
    Person,
    RawEvent,
    Unit,
)
from app.llm.embeddings import TextEmbedder
from app.pipeline.document_embed import embed_chunks, embed_documents_summary
from app.pipeline.document_index import write_chunks
from app.pipeline.document_qa import case_scope
from app.pipeline.document_search import DocFilter, any_of
from app.pipeline.injection_scan import scan
from app.pipeline.rag import retrieve_context
from app.pipeline.rag_retrieval import hybrid_candidates, words_ranking
from evals.rag_corpus import DOCS, QUESTIONS, CorpusDoc, Question

TENANTS = {
    "anna": ("Anna de Vries", "Kerkstraat 12-2"),
    "pieter": ("Pieter Jansen", "Zeestraat 7"),
    "jane": ("Jane Smith", "Dorpsweg 3"),
}


@dataclass
class Seeded:
    company_id: UUID
    doc_ids: dict[str, UUID]
    cases: dict[str, UUID]
    titles: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Outcome:
    question: Question
    context_hit: bool
    doc_hit: bool
    rank: int | None
    fact_ok: bool
    abstained: bool
    violated: bool
    route: str


def _message(s: Session, cid: UUID, sent: date) -> UUID:
    raw = RawEvent(company_id=cid, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
    s.add(raw)
    s.flush()
    at = datetime(sent.year, sent.month, sent.day, tzinfo=UTC)
    msg = MessageRow(company_id=cid, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id=raw.provider_msg_id,
                     thread_ref="t", sender_identity="x@example.test", direction=Direction.inbound, sent_at=at,
                     text="bijlage", meta={})  # fmt: skip
    s.add(msg)
    s.flush()
    return msg.id


def _people(s: Session, cid: UUID) -> tuple[dict[str, UUID], dict[str, UUID]]:
    since = date(2025, 1, 1)
    people, cases = {}, {}
    for key, (name, unit_label) in TENANTS.items():
        person = Person(company_id=cid, kind=PersonKind.tenant, display_name=name, valid_from=since)
        unit = Unit(company_id=cid, label=unit_label, address=f"{unit_label}, NL", valid_from=since)
        s.add_all([person, unit])
        s.flush()
        lease = Lease(company_id=cid, unit_id=unit.id, valid_from=since)
        s.add(lease)
        s.flush()
        case = Case(company_id=cid, unit_id=unit.id, lease_id=lease.id, primary_person_id=person.id,
                    state=CaseState.open, category=Category.administration, urgency=Urgency.normal)  # fmt: skip
        s.add(case)
        s.flush()
        people[key], cases[key] = person.id, case.id
    return people, cases


def seed(engine: Engine, embedder: TextEmbedder, company_id: UUID) -> Seeded:
    seeded = Seeded(company_id, {}, {})
    with Session(engine) as s, s.begin():
        people, seeded.cases = _people(s, company_id)
        for d in DOCS:
            seeded.doc_ids[d.key] = _document(s, company_id, d, people, seeded.cases)
            seeded.titles[d.key] = d.title
    embed_chunks(engine, embedder, company_id, limit=10_000)
    embed_documents_summary(engine, embedder, company_id, limit=1_000)
    return seeded


def _document(s: Session, cid: UUID, d: CorpusDoc, people: dict[str, UUID], cases: dict[str, UUID]) -> UUID:
    day = date.fromisoformat(d.date)
    sha = new_id().hex.ljust(64, "0")
    att = AttachmentRow(company_id=cid, message_id=_message(s, cid, day), s3_key="k", mime_type="application/pdf",
                        filename=f"{d.key}.pdf", size_bytes=len(d.text), sha256=sha)  # fmt: skip
    s.add(att)
    s.flush()
    doc = DocumentRow(company_id=cid, attachment_id=att.id, doc_type=d.doc_type, title=d.title,
                      file_name=f"{d.key}.pdf", confidence=0.9, status=DocumentStatus.filed, document_date=day,
                      facts=d.facts, summary=d.title, drive_file_id=f"drive-{d.key}",
                      suspicious=scan(d.text) is not None)  # fmt: skip
    s.add(doc)
    s.flush()
    label = TENANTS[d.owner][1] if d.owner else None
    write_chunks(s, doc, d.text, label)
    if d.owner:
        for kind, ref in ((DocLinkKind.case, cases[d.owner]), (DocLinkKind.person, people[d.owner])):
            s.add(DocumentLink(company_id=cid, document_id=doc.id, kind=kind, ref_id=ref, method="message", score=1.0))
        lease_id = s.get(Case, cases[d.owner]).lease_id  # type: ignore[union-attr]
        if lease_id:
            s.add(DocumentLink(company_id=cid, document_id=doc.id, kind=DocLinkKind.lease, ref_id=lease_id,
                               method="message", score=1.0))  # fmt: skip
    return doc.id


def _flt(engine: Engine, seeded: Seeded, q: Question) -> DocFilter:
    if q.scope is None:
        return DocFilter(readable_only=True)
    with Session(engine) as s:
        return DocFilter(any_link=case_scope(s, seeded.company_id, seeded.cases[q.scope]), readable_only=True)


def ask(engine: Engine, settings: Settings, embedder: TextEmbedder | None, seeded: Seeded, q: Question) -> Outcome:
    flt = _flt(engine, seeded, q)
    ctx = retrieve_context(engine, settings, seeded.company_id, q.text, flt, embedder)
    joined = "\n".join(p.text for p in ctx.passages) + (f"\n{ctx.fact.value} {ctx.fact.label}" if ctx.fact else "")
    titles = {p.title for p in ctx.passages} | ({ctx.fact.title} if ctx.fact else set())
    rank = None
    if q.expect:
        with Session(engine) as s:
            cands = hybrid_candidates(s, seeded.company_id, q.text, flt, embedder)
        rank = next((i for i, c in enumerate(cands, 1) if any(e.lower() in c.text.lower() for e in q.expect)), None)
    expect_title = seeded.titles.get(q.expect_doc or "")
    fact_ok = bool(ctx.fact and q.fact and q.fact in f"{ctx.fact.value} {ctx.fact.label}")
    return Outcome(
        q,
        context_hit=bool(q.expect) and any(e.lower() in joined.lower() for e in q.expect),
        doc_hit=expect_title in titles if expect_title else False,
        rank=rank, fact_ok=fact_ok, abstained=not ctx.passages and ctx.fact is None,
        violated=any(f.lower() in joined.lower() for f in q.forbid), route=ctx.route,
    )  # fmt: skip


def score(outcomes: list[Outcome]) -> dict[str, float]:
    graded = [o for o in outcomes if not o.question.real_only]

    def rate(items: list[bool]) -> float:
        return sum(items) / len(items) if items else 1.0

    content = [o for o in graded if o.question.expect and not o.question.fact]
    facts = [o for o in graded if o.question.fact]
    return {
        "context_hit": rate([o.context_hit for o in content]),
        "doc_hit": rate([o.doc_hit for o in graded if o.question.expect_doc and not o.question.fact]),
        "mrr": sum(1 / o.rank for o in content if o.rank) / (len(content) or 1),
        "fact_accuracy": rate([o.fact_ok for o in facts]),
        "abstain_accuracy": rate([o.abstained for o in graded if o.question.expect_doc is None]),
        "isolation_violations": float(sum(o.violated for o in graded)),
    }


def run(engine: Engine, settings: Settings, embedder: TextEmbedder | None, seeded: Seeded) -> list[Outcome]:
    return [ask(engine, settings, embedder, seeded, q) for q in QUESTIONS]


def baseline(engine: Engine, seeded: Seeded, q: Question) -> Outcome:
    """The M10 behaviour: full-text only, no glossary, no vectors, no planner, no reranker, one chunk per document."""
    flt = _flt(engine, seeded, q)
    with Session(engine) as s:
        ids = words_ranking(s, seeded.company_id, any_of(q.text), flt, 6)
        chunks = list(s.execute(select(DocumentChunk.text, DocumentRow.title).join(
            DocumentRow, DocumentRow.id == DocumentChunk.document_id).where(DocumentChunk.id.in_(ids))))  # fmt: skip
    joined = "\n".join(t for t, _ in chunks)
    titles = {title for _, title in chunks}
    expect_title = seeded.titles.get(q.expect_doc or "")
    rank = next((i for i, (t, _) in enumerate(chunks, 1) if any(e.lower() in t.lower() for e in q.expect)), None)
    return Outcome(
        q, context_hit=bool(q.expect) and any(e.lower() in joined.lower() for e in q.expect),
        doc_hit=expect_title in titles if expect_title else False, rank=rank, fact_ok=False, abstained=not chunks,
        violated=any(f.lower() in joined.lower() for f in q.forbid), route="words",
    )  # fmt: skip


def run_baseline(engine: Engine, seeded: Seeded) -> list[Outcome]:
    return [baseline(engine, seeded, q) for q in QUESTIONS]


def _purge(engine: Engine, company_id: UUID) -> None:  # pragma: no cover
    """Delete the evaluation company and everything it owns, children first."""
    from sqlalchemy import delete

    from app.db.base import Base

    with Session(engine) as s, s.begin():
        for table in reversed(Base.metadata.sorted_tables):
            if "company_id" in table.c:
                s.execute(delete(table).where(table.c.company_id == company_id))
        s.execute(delete(Company).where(Company.id == company_id))


def main() -> int:  # pragma: no cover  (needs a scratch database and, for real runs, provider keys)
    from app.db.session import make_engine
    from app.llm.embeddings import build_embedder
    from evals.common import eval_settings

    settings = eval_settings()
    engine = make_engine(settings.sqlalchemy_url)
    embedder = build_embedder(settings)
    with Session(engine) as s, s.begin():
        company = Company(name="rag-eval")
        s.add(company)
        s.flush()
        company_id = company.id
    try:
        seeded = seed(engine, embedder, company_id)
        hybrid = run(engine, settings, embedder, seeded)
        for label, outcomes in (("M10 baseline (full-text only)", run_baseline(engine, seeded)),
                                ("hybrid + planner + rerank", hybrid)):  # fmt: skip
            scores = score(outcomes)
            sys.stdout.write(f"\n{label}\n" + "\n".join(f"  {k}: {v:.2f}" for k, v in scores.items()) + "\n")
        misses = [o for o in hybrid if not (o.context_hit or o.fact_ok or o.abstained)]
        sys.stdout.write("\nmisses:\n" + "\n".join(f"  [{o.question.group}] {o.question.text}" for o in misses) + "\n")
    finally:
        _purge(engine, company_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
