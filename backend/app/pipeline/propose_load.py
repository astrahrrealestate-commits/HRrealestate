"""The proposer's view of one message (M13): its dossier, the role of the mail's own sender and the BRIXX fact."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context.persona import get_persona_row
from app.context.sender_label import sender_label_for
from app.contracts import Category, Understanding
from app.contracts.categories import current_category
from app.db.enums import PersonKind
from app.db.models import Case, Company, MessageRow, Person
from app.llm.agents.proposer import Contractor, Persona, ProposerContext
from app.llm.embeddings import TextEmbedder
from app.pipeline.dossier import Dossier, build_dossier
from app.pipeline.dossier_render import render_dossier


@dataclass(frozen=True)
class Loaded:
    ctx: ProposerContext
    company_id: UUID
    paused: bool
    message_ids: tuple[UUID, ...] = ()  # messages whose text is in the prompt (model_calls, erasure)
    sources: tuple[str, ...] = ()  # documents, references and pages in view, named on the card
    dossier_source: str = ""  # verified dossier text for output_guard (never guidance, draft, flagged or owner_copy)

    def guided(self, guidance: str | None, current: Sequence[str] = ()) -> "Loaded":
        return replace(self, ctx=replace(self.ctx, guidance=guidance, current_draft=tuple(current)))

    def retry(self, feedback: str) -> "Loaded":
        return replace(self, ctx=replace(self.ctx, quality_feedback=feedback))

    @property
    def source(self) -> str:
        """Verified text in view for the output guard: never guidance, earlier drafts, flagged or unverified text."""
        c = self.ctx
        parts = [c.subject or "", c.message_text, c.case_summary, *c.waiting]
        if self.dossier_source:
            parts.append(self.dossier_source)
        return "\n".join(parts)


def with_defaults(body: dict[str, Any]) -> dict[str, Any]:
    """Understandings stored before a field existed: no `requires_reply` (spam never needed an answer, anything else
    did) and no `sender_role` (unknown); a category written by a pre-M13 worker during a deploy."""
    out = {"sender_role": None, **body}
    if isinstance(out.get("category"), str):
        out["category"] = current_category(out["category"]).value
    if "requires_reply" not in out:
        out["requires_reply"] = out.get("category") != Category.spam.value
    return out


def _persona(session: Session, company_id: UUID) -> Persona:
    row = get_persona_row(session, company_id)
    return Persona(row.name, row.version, row.content)


def _contractors(session: Session, company_id: UUID) -> tuple[Contractor, ...]:
    rows = session.execute(
        select(Person.id, Person.display_name, Person.trade).where(
            Person.company_id == company_id, Person.kind == PersonKind.contractor, Person.valid_to.is_(None)
        )
    ).all()
    return tuple(Contractor(r[0], r[1], r[2]) for r in rows)


def _sources(d: Dossier) -> tuple[str, ...]:
    titles = [p.title for p in (*d.documents, *d.references)]
    return tuple(dict.fromkeys([*titles, *(f.url for f in d.research)]))


def _message_ids(d: Dossier) -> tuple[UUID, ...]:
    lines = (d.current, *d.thread, *d.sender_history, *d.similar_conversations)  # every message in the prompt
    return tuple(dict.fromkeys([*(line.message_id for line in lines), *d.extra_message_ids]))


def _dossier_source(d: Dossier) -> str:
    """Verified dossier content for the output guard; flagged, owner-copy and memory text are left out."""
    thread_lines = (*d.thread, *d.sender_history, *d.older_mail)
    lines = [line.text for line in thread_lines if not line.flagged and not line.owner_copy]
    atts = [a.text for a in d.attachments if not a.flagged]
    docs = [p.text for p in (*d.documents, *d.references)]
    research = [part for f in d.research for part in (f.url, f.answer)]
    quote = [d.quote] if d.quote else []
    return "\n".join([*lines, *atts, *docs, *research, *quote, *d.tenancy, *d.owner_rules])


def load(session: Session, msg: MessageRow, case: Case, und: Understanding, embedder: TextEmbedder | None) -> Loaded:
    """The writer's role comes from the mail's own sender, not the case's main person: on a shared case a contractor's
    mail gets a contractor's reply. Without a BRIXX work order no contractor is offered (Harjot creates the ticket)."""
    company = session.get(Company, msg.company_id)
    person = session.get(Person, msg.person_id) if msg.person_id else None
    if person is not None and person.company_id != msg.company_id:
        person = None
    sender = sender_label_for(session, msg.company_id, person, role_hint=und.sender_role, contractor_hint=False)
    brixx_needed = case.category == Category.maintenance and not case.brixx_ref
    d = build_dossier(session, msg.company_id, msg.id, embedder)
    ctx = ProposerContext(
        case_id=case.id, channel=msg.channel, subject=(msg.meta or {}).get("subject"), message_text=d.current.text,
        understanding=und, case_state=case.state.value, case_summary=case.summary, waiting=d.waiting,
        contractors=() if brixx_needed else _contractors(session, msg.company_id), mode="reply",
        persona=_persona(session, msg.company_id), sender_kind=sender.kind.value, dossier=tuple(render_dossier(d)),
        brixx_ref=case.brixx_ref, brixx_needed=brixx_needed,
    )  # fmt: skip
    return Loaded(
        ctx, msg.company_id, bool(company and company.paused), _message_ids(d), _sources(d), _dossier_source(d)
    )


def with_dossier(loaded: Loaded, dossier: Dossier) -> Loaded:
    """Re-render a `Loaded` context after enriching its `Dossier` (e.g. instruction-aware enhancement)."""
    ctx = replace(loaded.ctx, dossier=tuple(render_dossier(dossier)))
    return Loaded(
        ctx, loaded.company_id, loaded.paused, _message_ids(dossier), _sources(dossier), _dossier_source(dossier)
    )
