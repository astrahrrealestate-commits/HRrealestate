"""Instruction-aware draft enhancement: gap planner → targeted lookups → quality redraft."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.context.message_origin import is_owner_authored
from app.context.persona import load_persona
from app.contracts import Category, Direction, Understanding
from app.contracts.enhance import EnhancePlan
from app.contracts.research import Finding
from app.core.errors import AgentFailedError, EstateOSError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import DocLinkKind
from app.db.models import Case, CaseLink, MessageRow, UnderstandingRow
from app.db.models.ingestion import not_chat_only
from app.llm.agents.doc_qa import Passage
from app.llm.agents.enhance_planner import ENHANCE_PLANNER, enhance_planner_prompt
from app.llm.agents.enhance_style import ENHANCE_STYLE, enhance_style_prompt
from app.llm.calls import CallContext, is_transient, run_agent
from app.llm.embeddings import TextEmbedder, build_embedder
from app.pipeline import dashboard_decisions, propose, redraft
from app.pipeline.supersede import supersede_draft
from app.pipeline.conversation import ThreadLine
from app.pipeline.document_qa import case_scope, strip_risky
from app.pipeline.document_search import DocFilter
from app.pipeline.dossier import Dossier, build_dossier
from app.pipeline.draft_guidance import guidance_for
from app.pipeline.draft_research import Searcher, ad_hoc_research
from app.pipeline.injection_scan import scan
from app.pipeline.propose_load import Loaded, with_defaults, with_dossier
from app.pipeline.rag import retrieve_cheap
from app.tools.message_rag.search import search_messages
from app.tools.query_agent.agent import run_query_agent

log = get_logger(__name__)

_FAST_STYLE_PHRASES = frozenset(
    {
        "shorter",
        "make it shorter",
        "firmer",
        "make it firmer",
        "more polite",
        "friendlier",
        "make it friendlier",
        "formal",
        "more formal",
        "korter",
        "zakelijker",
        "vriendelijker",
    }
)


@dataclass(frozen=True)
class EnhanceResult:
    ok: bool
    variants: tuple[str, ...] = ()
    commitments: tuple[str, ...] = ()
    approval_id: UUID | None = None
    draft_version: int | None = None
    sources_used: tuple[str, ...] = ()
    problem: str | None = None


def _target_message(session: Session, company_id: UUID, case_id: UUID, message_id: UUID | None) -> MessageRow | None:
    if message_id is not None:
        msg = session.get(MessageRow, message_id)
        if msg is not None and msg.company_id == company_id:
            linked = session.scalar(
                select(CaseLink.id).where(
                    CaseLink.company_id == company_id, CaseLink.case_id == case_id, CaseLink.message_id == message_id
                )
            )
            if linked is not None:
                return msg
    rows = list(
        session.scalars(
            select(MessageRow)
            .join(CaseLink, (CaseLink.message_id == MessageRow.id) & (CaseLink.company_id == company_id))
            .where(CaseLink.company_id == company_id, CaseLink.case_id == case_id, not_chat_only())
            .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
            .limit(15)
        ).all()
    )
    inbound = next((m for m in rows if m.direction is Direction.inbound and not is_owner_authored(m)), None)
    return inbound or (rows[0] if rows else None)


def _plan_lookups(
    engine: Engine,
    settings: Settings,
    loaded: Loaded,
    instruction: str,
    current_text: str,
) -> EnhancePlan:
    norm = " ".join(instruction.lower().split())
    if norm in _FAST_STYLE_PHRASES:
        return EnhancePlan()
    ctx = CallContext(loaded.company_id, "enhance_planner", message_ids=loaded.message_ids[:1])
    prompt = enhance_planner_prompt(
        instruction,
        current_text,
        case_summary=loaded.ctx.case_summary,
        category=loaded.ctx.understanding.category.value,
        loaded_sources=loaded.sources,
    )
    try:
        return run_agent(engine, settings, ENHANCE_PLANNER, prompt, ctx).output
    except Exception as exc:
        if not (isinstance(exc, EstateOSError) or is_transient(exc)):
            raise
        log.warning("enhance.planner_failed", reason=type(exc).__name__)
        return EnhancePlan()


def _rag_links(session: Session, company_id: UUID, case: Case, msg: MessageRow) -> tuple[tuple[DocLinkKind, UUID], ...]:
    if case.primary_person_id is not None and msg.person_id == case.primary_person_id:
        return case_scope(session, company_id, case.id)
    return ((DocLinkKind.person, msg.person_id),) if msg.person_id else ()


def _extra_rag(
    session: Session,
    company_id: UUID,
    case: Case,
    msg: MessageRow,
    queries: Sequence[str],
    embedder: TextEmbedder,
    existing_ids: set[UUID],
) -> tuple[list[Passage], list[str]]:
    if not queries:
        return [], []
    links = _rag_links(session, company_id, case, msg)
    flt = DocFilter(any_link=links, readable_only=True)
    added: list[Passage] = []
    labels: list[str] = []
    for q in queries:
        for hit in retrieve_cheap(session, company_id, q, flt, embedder, limit=3):
            if hit.document_id in existing_ids:
                continue
            existing_ids.add(hit.document_id)
            added.append(replace(hit, text=strip_risky(hit.text)))
            labels.append(f"Doc: {hit.title}")
    return added, list(dict.fromkeys(labels))


def _extra_mail(
    session: Session,
    company_id: UUID,
    case: Case,
    msg: MessageRow,
    queries: Sequence[str],
    embedder: TextEmbedder,
    existing_mids: set[UUID],
) -> tuple[list[ThreadLine], list[UUID], list[str]]:
    if not queries:
        return [], [], []
    person_scope = msg.person_id
    case_scope_id = case.id if person_scope is None else None
    lines: list[ThreadLine] = []
    mids: list[UUID] = []
    labels: list[str] = []
    for q in queries:
        hits = search_messages(
            session, company_id, q, person_id=person_scope, case_id=case_scope_id, embedder=embedder, limit=3
        )
        for hit in hits:
            mid = hit.last_message_id
            if mid in existing_mids:
                continue
            existing_mids.add(mid)
            mids.append(mid)
            snippet = strip_risky(hit.text)[:500]
            lines.append(
                ThreadLine(
                    message_id=mid,
                    sent_at=hit.last_sent_at,
                    direction=Direction.inbound,
                    author=hit.person_name or "Past thread",
                    subject=hit.context,
                    text=snippet,
                    flagged=scan(hit.text) is not None,
                )
            )
            labels.append(f"Mail: {hit.person_name or hit.channel}")
    return lines, mids, list(dict.fromkeys(labels))


def _extra_db(
    engine: Engine, settings: Settings, company_id: UUID, db_question: str | None
) -> tuple[str | None, str | None]:
    if not db_question:
        return None, None
    try:
        res = run_query_agent(engine, settings, company_id, db_question, max_retries=1)
    except Exception as exc:
        log.warning("enhance.db_failed", reason=type(exc).__name__)
        return None, None
    if res.ok and res.answer.strip():
        return f"Portfolio lookup ({db_question}): {res.answer.strip()[:600]}", "Portfolio DB"
    return None, None


def _enrich_dossier(
    engine: Engine,
    settings: Settings,
    company_id: UUID,
    case: Case,
    msg: MessageRow,
    category: Category,
    plan: EnhancePlan,
    embedder: TextEmbedder,
    searcher: Searcher | None,
) -> tuple[Dossier, tuple[str, ...]]:
    with Session(engine) as session:
        dossier = build_dossier(session, company_id, msg.id, embedder)
        existing_doc_ids = {p.document_id for p in (*dossier.documents, *dossier.references)}
        existing_mids = {
            line.message_id for line in (dossier.current, *dossier.thread, *dossier.sender_history, *dossier.older_mail)
        }
        docs, doc_labels = _extra_rag(session, company_id, case, msg, plan.rag_queries, embedder, existing_doc_ids)
        mails, mail_mids, mail_labels = _extra_mail(
            session, company_id, case, msg, plan.mail_queries, embedder, existing_mids
        )
    findings: tuple[Finding, ...] = ()
    web_labels: list[str] = []
    if plan.web_questions:
        findings = ad_hoc_research(
            engine, settings, company_id, msg.id, plan.web_questions, category, searcher=searcher
        )
        web_labels = [f.url for f in findings]
    db_fact, db_label = _extra_db(engine, settings, company_id, plan.db_question)

    enriched = replace(
        dossier,
        documents=(*dossier.documents, *docs)[:7],
        older_mail=(*dossier.older_mail, *mails)[:8],
        extra_message_ids=(*dossier.extra_message_ids, *mail_mids),
        research=(*dossier.research, *findings),
        tenancy=(*dossier.tenancy, *([db_fact] if db_fact else ())),
    )
    sources_used = tuple(dict.fromkeys([*doc_labels, *mail_labels, *web_labels, *([db_label] if db_label else [])]))
    return enriched, sources_used


def _fast_style_rewrite(
    engine: Engine,
    settings: Settings,
    company_id: UUID,
    msg: MessageRow,
    und: Understanding,
    pending_approval_id: UUID,
    instruction: str,
    current_text: str,
    now: datetime,
) -> EnhanceResult | None:
    """Single fast-tier rewrite for pure style instructions (avoids rebuilding dossier + heavy proposer)."""
    ctx = CallContext(company_id, "enhance_style", message_ids=(msg.id,))
    prompt = enhance_style_prompt(instruction, current_text, channel=msg.channel.value)
    try:
        out = run_agent(engine, settings, ENHANCE_STYLE, prompt, ctx).output
    except Exception as exc:
        if not (isinstance(exc, EstateOSError) or is_transient(exc)):
            raise
        log.warning("enhance.fast_style_failed", reason=type(exc).__name__)
        return None
    variants = tuple(v.strip() for v in out.variants if v and v.strip())[:2]
    if not variants:
        return None
    turn_key = f"enhance:{new_id()}"
    with Session(engine) as session, session.begin():
        propose.lock_message(session, msg.id)
        persona = load_persona(session, company_id)
        revision = supersede_draft(
            session,
            company_id,
            pending_approval_id,
            list(variants),
            editor=turn_key,
            urgency=und.urgency,
            now=now,
            persona=persona,
        )
        if revision is None:
            return None
        dashboard_decisions.resolve_feed(session, company_id, pending_approval_id, at=now)
    return EnhanceResult(
        ok=True,
        variants=variants,
        approval_id=revision.approval_id,
        draft_version=revision.draft_version,
    )


def enhance_draft(
    engine: Engine,
    settings: Settings,
    company_id: UUID,
    case_id: UUID,
    *,
    instruction: str,
    current_text: str = "",
    message_id: UUID | None = None,
    searcher: Searcher | None = None,
) -> EnhanceResult:
    """Enhance a reply draft using the owner's instruction, fetching only missing RAG/mail/web/DB context."""
    now = datetime.now(UTC)
    embedder = build_embedder(settings)
    with Session(engine) as session:
        case = session.get(Case, case_id)
        if case is None or case.company_id != company_id:
            return EnhanceResult(ok=False, problem="Case not found.")
        msg = _target_message(session, company_id, case_id, message_id)
        if msg is None:
            return EnhanceResult(ok=False, problem="No message found on this thread to draft against.")
        und_row = session.scalar(
            select(UnderstandingRow).where(
                UnderstandingRow.company_id == company_id, UnderstandingRow.message_id == msg.id
            )
        )
        if und_row is None:
            return EnhanceResult(ok=False, problem="Message has not finished analysis yet.")
        und = Understanding.model_validate(with_defaults(und_row.body))
        state = redraft.message_state(session, company_id, msg.id, now)
        if state.kind in ("busy", "held"):
            return EnhanceResult(ok=False, problem=redraft.BUSY if state.kind == "busy" else redraft.HELD)
        msg_copy = MessageRow(
            id=msg.id, company_id=msg.company_id, person_id=msg.person_id, channel=msg.channel,
            direction=msg.direction, sent_at=msg.sent_at, meta=msg.meta,
        )  # fmt: skip

    clean_guidance = guidance_for(instruction).text or instruction.strip()[:400]
    norm_instruction = " ".join(clean_guidance.lower().split())
    if norm_instruction in _FAST_STYLE_PHRASES and current_text.strip() and state.kind == "pending" and state.pending:
        fast_result = _fast_style_rewrite(
            engine, settings, company_id, msg_copy, und, state.pending, clean_guidance, current_text.strip(), now
        )
        if fast_result is not None:
            return fast_result

    with Session(engine) as session:
        case = session.get(Case, case_id)
        if case is None or case.company_id != company_id:
            return EnhanceResult(ok=False, problem="Case not found.")
        base_loaded = propose.load_message(engine, msg_copy.id, embedder=embedder)
        if base_loaded is None:
            return EnhanceResult(ok=False, problem=redraft.NOTHING)
        # Detach scalar fields before session closes
        case_copy = Case(
            id=case.id, company_id=case.company_id, unit_id=case.unit_id, lease_id=case.lease_id,
            primary_person_id=case.primary_person_id, state=case.state, category=case.category,
            urgency=case.urgency, summary=case.summary, brixx_ref=case.brixx_ref,
        )  # fmt: skip

    current_variants = (current_text.strip(),) if current_text.strip() else state.current
    plan = _plan_lookups(engine, settings, base_loaded, clean_guidance, current_variants[0] if current_variants else "")

    sources_used: tuple[str, ...] = ()
    enriched_loaded = base_loaded
    if plan.rag_queries or plan.mail_queries or plan.web_questions or plan.db_question:
        enriched_dossier, sources_used = _enrich_dossier(
            engine, settings, company_id, case_copy, msg_copy, und.category, plan, embedder, searcher
        )
        enriched_loaded = with_dossier(base_loaded, enriched_dossier)

    guided_loaded = enriched_loaded.guided(clean_guidance, current_variants)
    try:
        decision = propose.guided_reply(engine, settings, guided_loaded)
    except AgentFailedError:
        return EnhanceResult(ok=False, problem=redraft.NO_DRAFT)
    if decision is None:
        return EnhanceResult(ok=False, problem=redraft.NO_DRAFT)

    turn_key = f"enhance:{new_id()}"
    req = redraft.Request(
        company_id=company_id,
        message_id=msg_copy.id,
        guidance=clean_guidance,
        prefix=turn_key,
        key=turn_key,
        now=now,
    )
    saved = redraft.persist_decision(engine, req, guided_loaded, decision)
    commitments = tuple(getattr(decision.action.payload, "commitments", ()) or ())
    if saved.revision is None:
        return EnhanceResult(
            ok=False,
            variants=saved.variants,
            commitments=commitments,
            sources_used=sources_used,
            problem=saved.problem or redraft.NO_DRAFT,
        )
    return EnhanceResult(
        ok=True,
        variants=saved.variants,
        commitments=commitments,
        approval_id=saved.revision.approval_id,
        draft_version=saved.revision.draft_version,
        sources_used=sources_used,
    )
