"""Message search evaluation: indexes the synthetic threads with the real indexer, asks every question the way Astra
searches, and scores the hits. Needs Postgres with pgvector, like `rag_eval`.

Scores: `context_hit` (an expected fragment is in the returned text), `mrr` (rank of the first hit holding it),
`abstain_accuracy` (nothing relevant means nothing returned) and `isolation_violations` (must stay 0: forbidden text,
such as another person's mail, in a scoped answer).

Run it with real models: `make rag-eval` (EMBEDDING_MODEL, LLM_MODEL in the environment).
"""

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import PersonKind
from app.db.models import Company, Lease, LeaseParty, MessageRow, Person, RawEvent, Unit
from app.llm.embeddings import TextEmbedder
from app.tools.message_rag.indexer import index_message
from app.tools.message_rag.search import MessageChunkHit, search_messages
from evals.message_rag_corpus import PEOPLE, QUESTIONS, THREADS, Mail, MessageQuestion, Thread

LIMIT = 5  # what Astra's search tool asks for
Search = Callable[[MessageQuestion], list[MessageChunkHit]]


@dataclass
class SeededThreads:
    company_id: UUID
    people: dict[str, UUID] = field(default_factory=dict)


@dataclass(frozen=True)
class MessageOutcome:
    question: MessageQuestion
    context_hit: bool
    rank: int | None
    abstained: bool
    violated: bool


def _person(s: Session, cid: UUID, key: str) -> UUID:
    name, kind, unit_label = PEOPLE[key]
    since = date(2025, 1, 1)
    person = Person(company_id=cid, kind=PersonKind(kind), display_name=name, valid_from=since)
    s.add(person)
    s.flush()
    if unit_label:
        unit = Unit(company_id=cid, label=unit_label, address=f"{unit_label}, NL", valid_from=since)
        s.add(unit)
        s.flush()
        lease = Lease(company_id=cid, unit_id=unit.id, valid_from=since)
        s.add(lease)
        s.flush()
        s.add(LeaseParty(company_id=cid, lease_id=lease.id, person_id=person.id, role="tenant"))
    return person.id


def _body(thread: Thread, i: int) -> str:
    """The mail as a client sends it: a reply that quotes carries the previous body, with its own quotes, below."""
    mail = thread.mails[i]
    if not mail.quotes_previous or i == 0:
        return mail.text
    prev = thread.mails[i - 1]
    author = "Harjot" if prev.outbound else PEOPLE[thread.person][0]
    quoted = "\n".join(f"> {line}" for line in _body(thread, i - 1).splitlines())
    return f"{mail.text}\n\nOp {prev.day} schreef {author}:\n{quoted}"


def _message(s: Session, seeded: SeededThreads, thread: Thread, i: int) -> UUID:
    mail: Mail = thread.mails[i]
    channel = Channel(thread.channel)
    raw = RawEvent(company_id=seeded.company_id, provider=channel, provider_msg_id=str(new_id()), payload={})
    s.add(raw)
    s.flush()
    sent = datetime.combine(date.fromisoformat(mail.day), datetime.min.time(), tzinfo=UTC) + timedelta(hours=9 + i)
    sender = "harjot@example.test" if mail.outbound else f"{thread.person}@example.test"
    msg = MessageRow(
        company_id=seeded.company_id, raw_event_id=raw.id, channel=channel, provider_msg_id=raw.provider_msg_id,
        thread_ref=thread.key, sender_identity=sender,
        direction=Direction.outbound if mail.outbound else Direction.inbound, sent_at=sent, text=_body(thread, i),
        person_id=None if mail.outbound else seeded.people[thread.person],
        meta={"subject": thread.subject} if thread.subject else {},
    )  # fmt: skip
    s.add(msg)
    s.flush()
    return msg.id


def seed(engine: Engine, settings: Settings, company_id: UUID) -> SeededThreads:
    seeded = SeededThreads(company_id)
    with Session(engine) as s, s.begin():
        seeded.people = {key: _person(s, company_id, key) for key in PEOPLE}
        ids = [_message(s, seeded, t, i) for t in THREADS for i in range(len(t.mails))]
    for message_id in ids:
        index_message(engine, settings, message_id)
    return seeded


def astra_search(engine: Engine, embedder: TextEmbedder | None, seeded: SeededThreads) -> Search:
    def search(q: MessageQuestion) -> list[MessageChunkHit]:
        person_id = seeded.people[q.person] if q.person else None
        with Session(engine) as s:
            return search_messages(s, seeded.company_id, q.text, embedder, person_id=person_id, limit=LIMIT)

    return search


def grade(q: MessageQuestion, hits: list[MessageChunkHit]) -> MessageOutcome:
    texts = [h.text.lower() for h in hits]
    rank = next((i for i, t in enumerate(texts, 1) if any(e.lower() in t for e in q.expect)), None)
    joined = "\n".join(texts)
    return MessageOutcome(
        q, context_hit=rank is not None, rank=rank, abstained=not hits,
        violated=any(f.lower() in joined for f in q.forbid),
    )  # fmt: skip


def run(engine: Engine, embedder: TextEmbedder | None, seeded: SeededThreads) -> list[MessageOutcome]:
    search = astra_search(engine, embedder, seeded)
    return [grade(q, search(q)) for q in QUESTIONS]


def score(outcomes: list[MessageOutcome]) -> dict[str, float]:
    content = [o for o in outcomes if o.question.expect]
    empty = [o for o in outcomes if not o.question.expect]
    return {
        "context_hit": sum(o.context_hit for o in content) / (len(content) or 1),
        "mrr": sum(1 / o.rank for o in content if o.rank) / (len(content) or 1),
        "abstain_accuracy": sum(o.abstained for o in empty) / (len(empty) or 1),
        "isolation_violations": float(sum(o.violated for o in outcomes)),
    }


def main() -> int:  # pragma: no cover  (needs a scratch database and, for real runs, provider keys)
    from app.db.session import make_engine
    from app.llm.embeddings import build_embedder
    from evals.common import eval_settings, write_rag_report
    from evals.rag_eval import _purge

    settings = eval_settings()
    engine = make_engine(settings.sqlalchemy_url)
    with Session(engine) as s, s.begin():
        company = Company(name="message-rag-eval")
        s.add(company)
        s.flush()
        company_id = company.id
    try:
        seeded = seed(engine, settings, company_id)
        outcomes = run(engine, build_embedder(settings), seeded)
        scores = score(outcomes)
        misses = [
            f"[{o.question.group}] {o.question.text}"
            for o in outcomes
            if (not o.context_hit if o.question.expect else not o.abstained)
        ]
        path = write_rag_report("message-rag", settings.embedding_model, settings.llm_model, scores, misses)
        sys.stdout.write("\nmessage search\n" + "\n".join(f"  {k}: {v:.2f}" for k, v in scores.items()))
        sys.stdout.write(f"\nmisses: {len(misses)} · report: {path}\n")
    finally:
        _purge(engine, company_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
