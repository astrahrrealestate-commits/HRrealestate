"""AI Copilot / Super Agent REST API Route.

Exposes the autonomous CONCIERGE (Super Agent) and executor pipeline to the Next.js frontend Top Command Bar (⌘K).
Executes multi-step plans (case status, drafting replies, task completions/snoozing, inbox search, view navigation).
"""

import asyncio
import contextlib
import contextvars
import json
import queue
import re
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import quote_plus
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, select
from sqlalchemy import case as sql_case
from sqlalchemy.orm import Session

from app.api.agent.calendar_match import open_case_on, unit_named
from app.api.agent.cards import ActionButtonData, AssistantCardData, PreviewCardData, build_cards_list
from app.api.agent.cards import CardActionData as CardActionData  # re-exported: callers import the card shapes here
from app.api.agent.draft_requests import channel_note
from app.api.agent.fallback import domain_fallback_answer
from app.api.agent.focus import new_chat_fact, next_focus
from app.api.agent.intent_responses import (
    STAGES,
    Segment,
    calendar_segment,
    compose,
    merge,
    preview_cards,
    remember_segment,
    rest_plan,
    rest_position,
)
from app.api.agent.property_scope import property_scope
from app.api.agent.steps import asks_for_clarification, display_steps
from app.api.deps import get_engine, get_settings_dep
from app.api.v1.access import require_agent
from app.api.v1.auth import Principal, require_session
from app.api.v1.session_limits import ask_limit
from app.channels.calendar import CalendarUnavailableError, get_calendar_client
from app.context.compiler import SUMMARY_PREFIX, compile_concierge_context
from app.context.selection import rank_cases
from app.context.super_agent_prompt import build_super_agent_system_prompt
from app.contracts import ActionType, Channel, ConciergePlan, Direction, Intent, PlanStep, Urgency
from app.contracts.sourced_answer import Source
from app.core.errors import AgentFailedError, NotFoundError
from app.core.ids import case_ref as short_case_ref
from app.core.ids import new_id
from app.core.localtime import to_local
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import MemoryStatus, PersonKind, PipelineStatus, TurnStatus
from app.db.models import (
    ActionRow,
    AgentConversation,
    AgentPageState,
    AgentTurn,
    Approval,
    Case,
    CaseLink,
    ChannelIdentity,
    DocumentChunk,
    DocumentRow,
    MemoryItem,
    MessageRow,
    Person,
    UnderstandingRow,
    Unit,
)
from app.db.models.calendar import CalendarEventRow
from app.db.models.finance import QuoteRow
from app.llm.agents.calendar import TimeNotStatedError, propose_calendar_event
from app.llm.agents.concierge import CONCIERGE, MAX_HISTORY, NAMED_BLOCKS, concierge_prompt
from app.llm.agents.owner_qa import CaseBrief
from app.llm.budget import CONCIERGE_PURPOSE
from app.llm.calls import CallContext, run_agent
from app.llm.embeddings import build_embedder
from app.llm.fakes_concierge import fake_concierge
from app.llm.runtime import describe_model_error
from app.pipeline import case_repo, owner_commands, understand, work_repo
from app.pipeline.concierge import StepResult, run_plan
from app.pipeline.concierge_entities import NO_ENTITIES, Entities, resolve_entities
from app.pipeline.concierge_outcome import task_brief
from app.pipeline.concierge_reply import screen_reply
from app.pipeline.document_search import DocFilter
from app.pipeline.rag import search_hybrid
from app.superagent.chat import chat_answer
from app.superagent.research import ResearchResult, run_research
from app.superagent.turn import make_researcher
from app.tools.query_agent.agent import sanitize_rows_for_display

router = APIRouter(prefix="/api/agent", tags=["agent"], dependencies=[Depends(require_agent)])
log = get_logger(__name__)


class AskAgentRequest(BaseModel):
    query: str = Field(description="The question or command by Harjot / owner")
    context: str | None = Field(default=None, description="Optional page context e.g. Inbox, Maintenance, Money")
    conversation_id: str | None = Field(default=None, description="Existing conversation UUID or null for new thread")
    history: list[str] | None = Field(default=None, description="Recent conversation turns for context")


class DebugInfo(BaseModel):
    pipeline_stage: str = Field(
        default="llm_concierge",
        description="llm_concierge | calendar | regex_document | memory_rule | fake_router | domain_fallback",
    )
    fallback_reason: str | None = None


class AskAgentResponse(BaseModel):
    conversation_id: str = Field(default="", description="ID of the conversation thread in Postgres")
    conversation_title: str = Field(default="New Chat", description="Title of the thread")
    answer: str
    caseRefs: list[str] = Field(default_factory=list)
    suggestedAction: str | None = None
    actions: list[ActionButtonData] = Field(default_factory=list)
    executedAt: str
    steps: list[str] = Field(default_factory=list, description="Execution steps performed by agent")
    previewCard: PreviewCardData | None = None
    previewCards: list[PreviewCardData] = Field(default_factory=list, description="Top preview cards up to limit of 3")
    cards: list[AssistantCardData] = Field(default_factory=list, description="Polymorphic assistant cards")
    debugInfo: DebugInfo | None = None
    suggestedPrompts: list[str] = Field(default_factory=list, description="Dynamic 3 workflow suggestion pills")
    focus_state: dict[str, Any] = Field(default_factory=dict, description="Active thread focus")
    sources: list[Source] = Field(default_factory=list, description="What a researched answer rests on")


class ConversationSummaryItem(BaseModel):
    id: str
    title: str
    last_turn_at: str
    snippet: str
    pinned: bool = False
    time_bucket: str  # "Today" | "Yesterday" | "Earlier"


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummaryItem]


class TurnReplayItem(BaseModel):
    id: str
    sender: str  # "user" | "assistant"
    text: str
    timestamp: str
    steps: list[str] = Field(default_factory=list)
    previewCard: PreviewCardData | None = None
    previewCards: list[PreviewCardData] = Field(default_factory=list, description="Top preview cards up to limit of 3")
    cards: list[AssistantCardData] = Field(default_factory=list)
    actions: list[ActionButtonData] = Field(default_factory=list)
    suggestedPrompts: list[str] = Field(default_factory=list)


class ConversationDetailResponse(BaseModel):
    id: str
    title: str
    pinned: bool
    last_turn_at: str
    focus_state: dict[str, Any] = Field(default_factory=dict)
    turns: list[TurnReplayItem] = Field(default_factory=list)


class UpdateConversationRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    hidden: bool | None = None


def _case_label(session: Session, case: Case) -> str:
    unit = session.get(Unit, case.unit_id) if case.unit_id else None
    person = session.get(Person, case.primary_person_id) if case.primary_person_id else None
    addr = (unit.address or unit.label) if unit else "General"
    name = person.display_name if person else "Unknown sender"
    cat = case.category.value if case.category else "general"
    return f"{name} · {addr} ({cat})"


def _message_coverage_fact(session: Session, company_id: UUID, now: datetime) -> str:
    """Compact per-channel message date coverage (earliest, latest, days ago, count) for <page_facts>."""
    local_now = to_local(now)
    lines = [f"Current local time: {local_now:%Y-%m-%d %H:%M} ({local_now:%A})"]
    try:
        is_chat = MessageRow.pipeline_status == PipelineStatus.skipped
        rows = session.execute(
            select(
                MessageRow.channel,
                is_chat,
                func.count(MessageRow.id),
                func.min(MessageRow.sent_at),
                func.max(MessageRow.sent_at),
            )
            .where(MessageRow.company_id == company_id)
            .group_by(MessageRow.channel, is_chat)
            .order_by(MessageRow.channel, is_chat)
        ).all()
        if not rows:
            lines.append("Message archive coverage: no messages stored yet.")
        else:
            lines.append("Message archive coverage (verified SQL):")
            for ch, chat_only, cnt, first_dt, last_dt in rows:
                ch_val = getattr(ch, "value", str(ch))
                scope = (
                    "WhatsApp (Chats)"
                    if (ch_val == "whatsapp" and chat_only)
                    else ("WhatsApp (Inbox cases)" if ch_val == "whatsapp" else "Gmail (Inbox)")
                )
                first_loc = to_local(first_dt) if first_dt else None
                last_loc = to_local(last_dt) if last_dt else None
                first_str = f"{first_loc:%Y-%m-%d %H:%M}" if first_loc else "unknown"
                if last_loc:
                    days_ago = max(0, (local_now.date() - last_loc.date()).days)
                    last_str = f"{last_loc:%Y-%m-%d %H:%M} ({days_ago} day{'s' if days_ago != 1 else ''} ago)"
                else:
                    last_str = "unknown"
                lines.append(f"- {scope}: {int(cnt or 0)} messages, from {first_str} to {last_str}")
    except Exception:
        return ""
    return "\n".join(lines)


def _system_prompt(
    query: str,
    *,
    memory_rules: Sequence[str] = (),
    page_facts: str = "",
    cases: Sequence[CaseBrief] = (),
    thread_summary: str = "",
    focus_case_id: str | None = None,
) -> str:
    return build_super_agent_system_prompt(
        cases=cases,
        query=query,
        memory_rules=memory_rules,
        page_facts=page_facts,
        thread_summary=thread_summary,
        focus_case_id=focus_case_id,
    )


def _generate_chat_answer(
    query: str,
    settings: Settings,
    engine: Engine,
    company_id: UUID,
    system_prompt: str,
    history: list[str] | None = None,
) -> str | None:
    """The direct answer on the configured model (Gemini via Pydantic AI); None means use the deterministic fallback."""
    return chat_answer(engine, settings, company_id, system_prompt, history or [], query)


def _step_sources(results: Sequence[StepResult]) -> list[Source]:
    """The sources a researched `answer` step carried (the plan's research loop, run inside run_plan)."""
    found: list[Source] = []
    for r in results:
        for raw in (r.data or {}).get("sources") or []:
            source = Source.model_validate(raw)
            if source not in found:
                found.append(source)
    return found


def _entities(engine: Engine, company_id: UUID, question: str) -> Entities:
    """Who and what the question names, inside the company; a failure costs the hint, never the answer."""
    try:
        with Session(engine) as session:
            return resolve_entities(session, company_id, question)
    except Exception as exc:
        log.warning("api.superagent.entities_failed", error=type(exc).__name__)
        return NO_ENTITIES


_STEP_CALLBACK: contextvars.ContextVar[Callable[[str], None] | None] = contextvars.ContextVar(
    "agent_step_callback", default=None
)


def _emit_step(step: str) -> None:
    cb = _STEP_CALLBACK.get()
    if cb is not None:
        with contextlib.suppress(Exception):
            cb(step)


def _research_answer(
    query: str,
    settings: Settings,
    engine: Engine,
    company_id: UUID,
    system_prompt: str,
    history: list[str] | None = None,
) -> ResearchResult | None:
    """The answer from the read-only research loop (database, messages, documents); None means use the chat answer."""
    return run_research(
        engine,
        settings,
        company_id,
        system_prompt,
        history or [],
        query,
        embedder=build_embedder(settings),
        on_step=_STEP_CALLBACK.get(),
    )


def _find_case_recipient(session: Session, target_case: Case | UUID) -> tuple[str, str, str | None, str | None]:
    """WP1 Recipient resolver rules:
    - Target case can be a Case object or a case UUID.
    - If inbound message exists: use its channel, find matching identity for case.primary_person_id.
    - If no inbound message: inspect tenant identity directly on case.primary_person_id.
    - Never use an outbound message's sender as the recipient.
    - If no recipient exists, return clear reason.
    Returns: (recipient, channel, thread_ref, reason_if_missing)
    """
    try:
        case_obj = session.get(Case, target_case) if isinstance(target_case, UUID) else target_case
        if not case_obj:
            return "", "whatsapp", None, "case_not_found"

        inbound_msg = session.scalars(
            select(MessageRow)
            .join(CaseLink, CaseLink.message_id == MessageRow.id)
            .where(
                CaseLink.case_id == case_obj.id,
                MessageRow.direction == Direction.inbound,
            )
            .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
            .limit(1)
        ).first()

        if inbound_msg:
            ch_raw = inbound_msg.channel
            chan_str = ch_raw.value if hasattr(ch_raw, "value") else str(ch_raw)
            thread_ref = inbound_msg.thread_ref

            # Primary: person channel identity matching this inbound channel
            if case_obj.primary_person_id:
                ident = session.scalars(
                    select(ChannelIdentity)
                    .where(
                        ChannelIdentity.person_id == case_obj.primary_person_id,
                        ChannelIdentity.channel == ch_raw,
                        ChannelIdentity.valid_to.is_(None),
                    )
                    .order_by(ChannelIdentity.created_at.desc())
                    .limit(1)
                ).first()
                if ident and ident.identity:
                    return str(ident.identity).strip(), chan_str, thread_ref, None

            # Secondary fallback for inbound: sender_identity on the inbound message
            if inbound_msg.sender_identity:
                sender_id = str(inbound_msg.sender_identity).strip()
                if (chan_str == "gmail" and "@" in sender_id) or (
                    chan_str == "whatsapp" and re.sub(r"[^0-9]", "", sender_id)
                ):
                    return sender_id, chan_str, thread_ref, None

            reason = f"no_{chan_str}_on_file" if case_obj.primary_person_id else "no_primary_person"
            return "", chan_str, thread_ref, reason

        # No inbound message found: inspect tenant identity directly
        if case_obj.primary_person_id:
            ident = session.scalars(
                select(ChannelIdentity)
                .where(
                    ChannelIdentity.person_id == case_obj.primary_person_id,
                    ChannelIdentity.valid_to.is_(None),
                )
                .order_by(ChannelIdentity.created_at.desc())
                .limit(1)
            ).first()
            if ident and ident.identity:
                ch_raw = ident.channel
                chan_str = ch_raw.value if hasattr(ch_raw, "value") else str(ch_raw)
                return str(ident.identity).strip(), chan_str, None, None

        return "", "whatsapp", None, "no_inbound_or_identity"
    except Exception as err:
        log.warning("api.superagent.find_case_recipient_failed", error=str(err), exc_info=True)
        return "", "whatsapp", None, "lookup_error"


def _resolve_draft_card(
    engine: Engine,
    approval_ids: list[str] | None = None,
    company_id: UUID | None = None,
    prefer_contractor: bool = False,
) -> PreviewCardData | None:
    """Consolidated helper to fetch draft message or notice preview data in a single session scope."""
    if not approval_ids:
        return None

    with Session(engine) as session:
        try:
            target_appr = None
            target_act = None

            # If prefer_contractor is requested, look for request_contractor first
            if prefer_contractor:
                for aid_str in approval_ids or []:
                    try:
                        a = session.get(Approval, UUID(aid_str))
                        if not a:
                            continue
                        act_candidate = session.get(ActionRow, a.action_id)
                        if not act_candidate or not act_candidate.payload:
                            continue
                        if act_candidate.type == ActionType.request_contractor:
                            target_appr = a
                            target_act = act_candidate
                            break
                    except Exception as skip_err:
                        log.warning("api.superagent.draft_candidate_skipped", error=type(skip_err).__name__)
                        continue

            # Prioritize reply_draft action, fallback to first valid action
            if not target_act:
                for aid_str in approval_ids or []:
                    try:
                        a = session.get(Approval, UUID(aid_str))
                        if not a:
                            continue
                        act_candidate = session.get(ActionRow, a.action_id)
                        if not act_candidate or not act_candidate.payload:
                            continue
                        if act_candidate.type == ActionType.reply_draft:
                            target_appr = a
                            target_act = act_candidate
                            break
                        elif not target_appr:
                            target_appr = a
                            target_act = act_candidate
                    except Exception as skip_err:
                        log.warning("api.superagent.draft_candidate_skipped", error=type(skip_err).__name__)
                        continue

            if not target_appr or not target_act or not target_act.payload:
                return None

            appr = target_appr
            act = target_act

            payload = act.payload
            target_case = session.get(Case, act.case_id) if act.case_id else None
            unit = session.get(Unit, target_case.unit_id) if target_case and target_case.unit_id else None
            unit_label = unit.address if unit else "Portfolio Unit"
            case_id_str = str(act.case_id) if act.case_id else None
            action_id_str = str(act.id)
            appr_status_str = appr.status.value if hasattr(appr.status, "value") else str(appr.status)

            # Check if this is a request_contractor action
            if act.type == ActionType.request_contractor:
                cp_raw = act.payload.get("contractor_person_id")
                contractor_p = None
                if cp_raw:
                    try:
                        contractor_p = session.get(Person, cp_raw if isinstance(cp_raw, UUID) else UUID(str(cp_raw)))
                    except (ValueError, TypeError):
                        contractor_p = None
                contractor_name = (
                    contractor_p.display_name
                    if contractor_p
                    else str(act.payload.get("assigned_to_name") or "Assigned Contractor")
                )
                contractor_email = str(act.payload.get("to") or "").strip()
                if not contractor_email and contractor_p is not None:
                    c_ident = session.scalars(
                        select(ChannelIdentity)
                        .where(
                            ChannelIdentity.company_id == act.company_id,
                            ChannelIdentity.person_id == contractor_p.id,
                            ChannelIdentity.valid_to.is_(None),
                        )
                        .order_by(ChannelIdentity.created_at.desc())
                        .limit(1)
                    ).first()
                    if c_ident and c_ident.identity:
                        contractor_email = str(c_ident.identity).strip()
                contractor_recipient = (
                    f"{contractor_name} <{contractor_email}>" if contractor_email else contractor_name
                )
                chan_str = "gmail"
                case_topic = (
                    target_case.summary.split(".")[0][:60] if target_case and target_case.summary else "Maintenance"
                )
                subj_str = str(act.payload.get("subject") or f"Work Order: {case_topic} — {unit_label}")
                variants = act.payload.get("body_variants") or []
                extracted_body = variants[0] if variants else (act.payload.get("text") or "")
                draft_body = extracted_body.strip()
                raw_variants = variants or [draft_body]
                card_variants = [str(v) for v in raw_variants if v]
                contractor_url = (
                    f"https://mail.google.com/mail/?view=cm&fs=1&to={quote_plus(contractor_email)}"
                    f"&su={quote_plus(subj_str)}&body={quote_plus(draft_body)}"
                    if contractor_email
                    else None
                )
                contractor_thread_url = (
                    f"https://mail.google.com/mail/u/0/#search/{quote_plus(contractor_email)}"
                    if contractor_email
                    else None
                )

                return PreviewCardData(
                    type="draft_message",
                    channel=chan_str,
                    recipient=contractor_recipient,
                    unitLabel=str(unit_label or "Portfolio Unit"),
                    subject=subj_str,
                    body=draft_body,
                    variants=card_variants,
                    status=appr_status_str,
                    actionId=action_id_str,
                    caseId=case_id_str,
                    externalUrl=contractor_url,
                    threadSearchUrl=contractor_thread_url,
                )

            # notify_owner and other non-reply_draft types render as a notice card, never as a draft
            if act.type != ActionType.reply_draft:
                notice_text = str(
                    payload.get("text") or payload.get("summary") or "Action notice queued for owner review."
                )
                return PreviewCardData(
                    type="notice",
                    badgeLabel="NOTICE",
                    badgeColor="amber",
                    unitLabel=unit_label or "Portfolio Unit",
                    title="Draft Generation Notice",
                    body=notice_text,
                    actionId=action_id_str,
                    caseId=case_id_str,
                    status=appr_status_str,
                    targetUrl=f"/inbox?thread=case-{case_id_str}" if case_id_str else "/inbox",
                )

            # Strict reply_draft cards
            resolved_recipient = payload.get("to") or payload.get("recipient")
            channel = payload.get("channel", "whatsapp")
            resolved_thread_ref = None

            if target_case:
                recip_from_db, resolved_channel, resolved_thread_ref, _missing_reason = _find_case_recipient(
                    session, target_case
                )
                if not resolved_recipient and recip_from_db:
                    resolved_recipient = recip_from_db
                if resolved_channel:
                    channel = resolved_channel

            variants = payload.get("body_variants") or []
            extracted_body = (
                (variants[0] if isinstance(variants, list) and variants else "")
                or payload.get("body")
                or payload.get("text")
                or ""
            )
            draft_body = extracted_body.strip()

            clean_phone = re.sub(r"[^0-9]", "", str(resolved_recipient or ""))
            chan_str = str(channel.value if hasattr(channel, "value") else channel).lower()
            ext_url = None
            thread_url = None
            if chan_str == "whatsapp" and clean_phone:
                ext_url = (
                    f"https://wa.me/{clean_phone}?text={quote_plus(draft_body)}"
                    if draft_body
                    else f"https://wa.me/{clean_phone}"
                )
                thread_url = f"https://wa.me/{clean_phone}"
            elif chan_str == "gmail" and resolved_recipient:
                subj_str = str(payload.get("subject") or "Maintenance Update")
                ext_url = f"https://mail.google.com/mail/?view=cm&fs=1&to={quote_plus(str(resolved_recipient))}&su={quote_plus(subj_str)}&body={quote_plus(draft_body)}"
                if resolved_thread_ref:
                    thread_url = f"https://mail.google.com/mail/u/0/#inbox/{resolved_thread_ref}"
                else:
                    thread_url = f"https://mail.google.com/mail/u/0/#search/{quote_plus(str(resolved_recipient))}"

            raw_variants = payload.get("body_variants") or []
            card_variants = [str(v) for v in raw_variants if v] if isinstance(raw_variants, list) else []
            if not card_variants and draft_body:
                card_variants = [draft_body]

            return PreviewCardData(
                type="draft_message",
                channel=chan_str,
                recipient=str(resolved_recipient or ""),
                unitLabel=str(unit_label or "Portfolio Unit"),
                subject=str(payload.get("subject")) if payload.get("subject") else None,
                body=draft_body,
                variants=card_variants,
                status=appr_status_str,
                actionId=action_id_str,
                caseId=case_id_str,
                externalUrl=ext_url,
                threadSearchUrl=thread_url,
                personaName=act.persona_name,
                personaVersion=act.persona_version,
            )
        except Exception as e:
            log.warning("api.superagent.resolve_draft_failed", error=str(e), exc_info=True)
            return None


def _resolve_calendar_action(
    query: str,
    engine: Engine,
    company_id: UUID,
    briefs: list[CaseBrief],
) -> tuple[str | None, PreviewCardData | None, list[ActionButtonData], list[str]]:
    q_low = query.lower()
    is_inquiry = bool(re.search(r"\b(what|which|show|list|view|check|any|hoeveel|welke|wat)\b", q_low))
    is_schedule_command = not is_inquiry and (
        q_low.startswith(("schedule ", "book ", "set up ", "setup ", "plan "))
        or bool(
            re.search(
                r"\b(schedule\s+(?!to|of\b)|book\s+(?!to|of\b)|set\s*up\s+|plan\s+visit|inplannen|boeken)\b", q_low
            )
        )
    )
    is_calendar_query = bool(
        re.search(
            r"\b(calendar|visit|visits|appointment|appointments|meeting|meetings|scheduled|booked|afspraak|agenda)\b",
            q_low,
        )
    )

    if not (is_schedule_command or is_calendar_query):
        return None, None, [], []

    with Session(engine) as session:
        # 1. HARJOT ASKS TO SCHEDULE / BOOK AN APPOINTMENT
        if is_schedule_command:
            target_unit = unit_named(session, company_id, q_low)
            target_case = open_case_on(session, company_id, target_unit) if target_unit else None

            people = list(
                session.scalars(
                    select(Person)
                    .where(Person.company_id == company_id, Person.valid_to.is_(None))
                    .order_by(Person.created_at.desc())
                    .limit(100)
                ).all()
            )
            matched_c = None
            for person in people:
                name_tokens = [tok for tok in (person.display_name or "").lower().split() if len(tok) > 2]
                if any(tok in q_low for tok in name_tokens):
                    matched_c = person
                    break

            is_block = any(w in q_low for w in ("block", "focus", "internal", "review", "reminder"))
            if target_unit is None and matched_c is None and not is_block:
                return (
                    "Who is this meeting or visit with (and which property if applicable), plus the day and time?",
                    None,
                    [],
                    ["Awaiting appointment details"],
                )

            addr = (target_unit.address or target_unit.label) if target_unit else "HR Real Estate / General"
            attendee_label = (
                f"{matched_c.display_name} ({matched_c.trade.capitalize()})"
                if matched_c and matched_c.trade
                else (matched_c.display_name if matched_c else "Internal / Focus Block")
            )
            contractor_name = attendee_label

            contractor_email: str | None = None
            if matched_c:
                c_ident = session.scalars(
                    select(ChannelIdentity)
                    .where(
                        ChannelIdentity.company_id == company_id,
                        ChannelIdentity.person_id == matched_c.id,
                        ChannelIdentity.channel == Channel.gmail,
                        ChannelIdentity.valid_to.is_(None),
                    )
                    .limit(1)
                ).first()
                if c_ident and c_ident.identity:
                    contractor_email = str(c_ident.identity).strip()

            event_type = (
                "contractor_repair"
                if (matched_c and matched_c.kind == PersonKind.contractor)
                else ("focus_block" if is_block and matched_c is None else "meeting")
            )

            try:
                proposal = propose_calendar_event(
                    message_text=query,
                    property_address=addr,
                    calendar_client=get_calendar_client(),
                    contractor_name=contractor_name,
                    contractor_email=contractor_email,
                    lockbox_pin=getattr(target_unit, "lockbox_code", None),
                )
            except TimeNotStatedError:
                return (
                    "Which day and time should the visit be? I do not guess a meeting time.",
                    None,
                    [],
                    ["Awaiting appointment time"],
                )
            except CalendarUnavailableError as exc:
                return (
                    f"I cannot check your availability or book. {exc}",
                    None,
                    [],
                    ["Google Calendar unavailable"],
                )

            # Persist proposed event in DB
            evt_row = CalendarEventRow(
                company_id=company_id,
                case_id=target_case.id if target_case else None,
                unit_id=target_unit.id if target_unit else None,
                title=proposal.title,
                description=proposal.notes,
                start_time=proposal.start_time,
                end_time=proposal.end_time,
                location=addr,
                status="proposed",
                event_type=event_type,
                attendees=[{"email": contractor_email, "displayName": contractor_name}] if contractor_email else [],
                lockbox_code=proposal.lockbox_code,
            )
            session.add(evt_row)
            session.commit()

            start_str = to_local(proposal.start_time).strftime("%A, %b %d at %H:%M")
            end_str = to_local(proposal.end_time).strftime("%H:%M")
            time_window_str = f"{start_str} – {end_str}"

            access_line = (
                f"• **Lockbox Access**: #{proposal.lockbox_code}\n\n"
                if proposal.lockbox_code
                else "• **Access**: Tenant present / direct access\n\n"
            )
            lockbox_line = (
                f"Lockbox: #{proposal.lockbox_code}\n" if proposal.lockbox_code else "Lockbox: None (Tenant access)\n"
            )

            status_note = f"collision: {proposal.conflict_reason}" if proposal.has_conflict else "no calendar conflicts"
            ans = (
                f"I have checked your schedule and prepared an appointment for **{contractor_name}** at **{addr}** "
                f"on **{time_window_str}**.\n\n"
                f"• **Status**: Proposed ({status_note})\n"
                f"{access_line}"
                f"Tap **Approve & Add to Google Calendar** below to sync."
            )

            preview_card = PreviewCardData(
                type="calendar_item",
                badgeLabel="GOOGLE CALENDAR",
                unitLabel=addr,
                title=f"{contractor_name.split()[0]} Visit · {addr}",
                subtitle=time_window_str,
                body=f"Contractor: {contractor_name}\nTime: {time_window_str}\n{lockbox_line}Notes: {proposal.notes}",
                dueDate=time_window_str,
                contractor=contractor_name,
                status="proposed",
                actionId=str(evt_row.id),
                caseId=str(target_case.id) if target_case else None,
                targetUrl=f"/calendar?event={evt_row.id}",
            )

            actions = [
                ActionButtonData(
                    label="Approve & Add to Google Calendar",
                    actionType="approve_calendar",
                    payload=f"/api/calendar/events/{evt_row.id}/approve",
                    isPrimary=True,
                ),
                ActionButtonData(
                    label="View Calendar",
                    actionType="navigate",
                    payload="/calendar",
                    isPrimary=False,
                ),
            ]
            conflict_summary = (
                f"Collision detected: {proposal.conflict_reason}"
                if proposal.has_conflict
                else "Checked calendar for busy slots (0 conflicts detected)"
            )
            steps = [
                "Parsed appointment timing and contractor details",
                conflict_summary,
                "Generated 1-click scheduling card",
            ]
            return ans, preview_card, actions, steps

        # 2. HARJOT ASKS WHAT VISITS / EVENTS ARE SCHEDULED
        elif is_calendar_query:
            events = session.scalars(
                select(CalendarEventRow)
                .where(CalendarEventRow.company_id == company_id, CalendarEventRow.status != "cancelled")
                .order_by(CalendarEventRow.start_time.asc())
            ).all()

            event_lines: list[str] = []
            for e in events[:5]:
                date_lbl = to_local(e.start_time).strftime("%a %b %d · %H:%M")
                loc = e.location or "no location set"
                st_badge = f"[{e.status.upper()}]"
                event_lines.append(f"• **{e.title}** ({st_badge})\n  {date_lbl} at {loc}")

            live_count = 0
            calendar_problem = ""
            try:
                client = get_calendar_client()
                win_start = datetime.now(UTC)
                win_end = win_start + timedelta(days=14)
                for ev in client.list_events(win_start, win_end)[:8]:
                    live_count += 1
                    date_lbl = to_local(ev.start_time).strftime("%a %b %d · %H:%M")
                    loc = ev.location or "no location set"
                    event_lines.append(f"• **{ev.title}** ([GOOGLE CALENDAR])\n  {date_lbl} at {loc}")
            except CalendarUnavailableError as exc:
                calendar_problem = str(exc)

            if event_lines:
                sched_text = "\n".join(event_lines[:10])
                ans = f"Here are your upcoming scheduled visits and appointments:\n\n{sched_text}"
            else:
                ans = (
                    "I found no appointments in EstateOS."
                    if calendar_problem
                    else "You have no upcoming appointments booked on your calendar."
                )
            if calendar_problem:
                ans += f"\n\nI could not read Google Calendar. {calendar_problem}"

            actions = [
                ActionButtonData(
                    label="Open Calendar",
                    actionType="navigate",
                    payload="/calendar",
                    isPrimary=True,
                )
            ]
            steps = [
                "Queried scheduled property visits and Google Calendar",
                f"Retrieved {len(events)} DB appointments; Google Calendar could not be read"
                if calendar_problem
                else f"Retrieved {len(events)} DB and {live_count} Google Calendar appointments",
            ]
            return ans, None, actions, steps

    return None, None, [], []


_TITLE_STOPWORDS = frozenset(
    {
        "can",
        "could",
        "would",
        "will",
        "you",
        "me",
        "my",
        "our",
        "we",
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "what",
        "which",
        "who",
        "how",
        "many",
        "much",
        "tell",
        "show",
        "give",
        "please",
        "right",
        "now",
        "this",
        "that",
        "us",
    }
)


def _generate_thread_title(query: str, ans: str, cases: list[CaseBrief]) -> str:
    """Generate a concise, query-specific 3-5 word title for the conversation thread."""
    q_low = (query or "").lower()
    has_keizersgracht_case = bool(cases and any("keizersgracht" in getattr(c, "label", "").lower() for c in cases))

    if any(w in q_low for w in ("leak", "water", "pipe", "plumber", "burst")) and (
        "keizersgracht" in q_low or has_keizersgracht_case
    ):
        return "Keizersgracht Pipe Leak"
    if any(w in q_low for w in ("profit", "profitable", "revenue", "margin", "income")):
        return "Property Profitability"
    if any(w in q_low for w in ("rent", "arrear", "overdue", "behind", "collection")):
        if "pieter" in q_low:
            return "Pieter Bakker Arrears"
        if any(w in q_low for w in ("arrear", "overdue", "behind")):
            return "Tenant Rent Arrears"
        return "Rent & Collections"
    if any(w in q_low for w in ("lease", "leases")):
        return "Active Portfolio Leases"
    if any(w in q_low for w in ("draft", "reply", "send", "message")):
        return "Draft Tenant Reply"
    if any(w in q_low for w in ("calendar", "visit", "schedule", "appointment", "afspraak")):
        return "Property Visit & Schedule"
    if any(w in q_low for w in ("invoice", "bill", "factuur", "quote", "rate card", "vendor rate")):
        return "Quotes & Vendor Rates"
    if any(w in q_low for w in ("waiting", "chase", "follow up", "followup")):
        return "Waiting-For Radar"
    if any(w in q_low for w in ("document", "documents", "filed", "pdf")):
        return "Portfolio Documents"
    if any(w in q_low for w in ("open task", "tasks")):
        return "Open Owner Tasks"
    if any(w in q_low for w in ("priority", "first", "emergency", "ticket", "tickets", "open case")):
        return "Urgent Maintenance Queue"
    if "keizersgracht" in q_low:
        return "Keizersgracht 42-A"
    if any(w in q_low for w in ("property", "properties", "units")):
        return "Portfolio Properties"

    raw_words = re.sub(r"[^a-zA-Z0-9\s]", " ", query or "").split()
    meaningful = [w.capitalize() for w in raw_words if w.lower() not in _TITLE_STOPWORDS and len(w) > 1]
    if meaningful:
        return " ".join(meaningful[:5])[:60]
    fallback = [w.capitalize() for w in raw_words if len(w) > 1]
    return " ".join(fallback[:4])[:60] or "Conversation"


def _clean_card_body(body: str) -> str:
    """Strip internal developer debugging, audit logs, and raw message dumps from card bodies."""
    if not body:
        return ""
    # Strip audit logs like [Action Taken: ...]
    cleaned = re.sub(r"\[Action Taken:.*?\]", "", body, flags=re.DOTALL)
    # Strip recent messages trailer like | Recent messages: ...
    if " | Recent messages:" in cleaned:
        cleaned = cleaned.split(" | Recent messages:")[0]
    # Strip any inline message logs: [dd Mmm hh:mm Inbound/Outbound...]: "..."
    cleaned = re.sub(
        r"\[\d{1,2}\s+[A-Za-z]{3}\s+\d{1,2}:\d{2}\s+(Inbound|Outbound)[^\]]*\]:?\s*(\"[^\"]*\"|'[^']*'|[^;\]]*)",
        "",
        cleaned,
    )
    # Strip leading tool chatter
    cleaned = re.sub(
        r"^(Opening (cases|inbox|maintenance|money|properties|calendar|documents|approvals)\.?\s*)+",
        "",
        cleaned.strip(),
        flags=re.IGNORECASE,
    )
    # Strip trailing quotes or separators
    cleaned = re.sub(r"(\s*\|\s*)+$", "", cleaned)
    cleaned = re.sub(r"(\s*;\s*)+$", "", cleaned)
    # Collapse extra whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


_CASE_UUID_RE = re.compile(
    r"\bcase\s+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    re.IGNORECASE,
)
_CASE_ID_LABEL_UUID_RE = re.compile(
    r"\*\*Case\s+ID:?\*\*:?\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    re.IGNORECASE,
)
_RAW_UUID_RE = re.compile(
    r"(?<![/?=&-])\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b(?![/?=&-])",
    re.IGNORECASE,
)
_ISO_DT_INLINE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::\d{2})?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})\b")
_HIDDEN_PIPE_ID_FIELD_RE = re.compile(
    r"\*\*(?:Lease|Company|Unit|Person|Event|Action|Message)\s+id:?\*\*:?\s*#?[0-9a-f-]+\s*\|\s*",
    re.IGNORECASE,
)


def _format_iso_match(match: re.Match[str]) -> str:
    try:
        offset = "+00:00" if match.group(3) == "Z" else match.group(3)
        dt = datetime.fromisoformat(f"{match.group(1)} {match.group(2)}{offset}")
        return to_local(dt).strftime("%d %b %Y, %H:%M")
    except ValueError:
        return match.group(0)


def _clean_executive_answer(text: str) -> str:
    """Strip robotic tool-chatter prefixes, raw UUIDs/timestamps, and pipe dumps while leaving normal prose intact."""
    if not text:
        return ""
    cleaned = re.sub(
        r"^(Opening (cases|inbox|maintenance|money|properties|calendar|documents|approvals)\.?\s*)+",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    ).strip()
    cleaned = _CASE_ID_LABEL_UUID_RE.sub(lambda m: f"**Ticket #{short_case_ref(m.group(1))}**", cleaned)
    cleaned = _CASE_UUID_RE.sub(lambda m: f"Ticket #{short_case_ref(m.group(1))}", cleaned)
    cleaned = _RAW_UUID_RE.sub(lambda m: f"#{short_case_ref(m.group(1))}", cleaned)
    cleaned = re.sub(r"\bcase\s+([0-9a-f]{6,8})\b", r"Ticket #\1", cleaned, flags=re.IGNORECASE)
    cleaned = _ISO_DT_INLINE_RE.sub(_format_iso_match, cleaned)
    cleaned = _HIDDEN_PIPE_ID_FIELD_RE.sub("", cleaned)

    out_lines: list[str] = []
    for line in cleaned.splitlines():
        stripped_line = line.strip()
        is_md_table = stripped_line.startswith("|") and stripped_line.endswith("|")
        if not is_md_table and "|" in line:
            line = re.sub(r"\*\*Case\s+id:?\*\*:?\s*(#[0-9a-f]+)", r"**Ticket \1**", line, flags=re.IGNORECASE)
            line = re.sub(r"[\s\u00a0\u202f]*\|[\s\u00a0\u202f]*", " · ", line).strip(" ·")
        out_lines.append(line)
    cleaned = "\n".join(out_lines)
    return cleaned


_EXPLICIT_DRAFT_ASK_RE = re.compile(
    r"\b(draft|drafts|drafted|prepare|write\s+(?:a|an|me|back)|show\s+(?:me\s+)?(?:the\s+)?draft)\b"
)
_PRIORITIZE_RE = re.compile(
    r"\b(?:whome?|who|which\s+(?:one|ticket|tickets|case|cases|tenant|tenants|message|messages|person|unit|property)"
    r"|what\s+(?:should\s+i|to|needs))\b.*\b(?:first|priorit\w*|most\s+(?:important|urgent)|urgent|important)\b"
    r"|\b(?:most\s+important|most\s+urgent|highest\s+priority|top\s+priority|priorit(?:y|ize|ise)"
    r"|reply\s+first|respond\s+first|do\s+first)\b"
)
_MULTI_DRAFT_RE = re.compile(
    r"\b(?:these\s+(?:tickets?|ticketes|cases?)|those\s+(?:tickets?|ticketes|cases?)|both|"
    r"all(?:\s+of)?(?:\s+the|\s+open)?\s+(?:tickets?|ticketes|cases?)|"
    r"(?:replies|drafts|drafted\s+(?:replies|messages|drafts)|messages|responses)\s+(?:for|to)\s+"
    r"(?:these|those|them|all|open|the\s+open|every|each|(?:the\s+)?(?:tickets|ticketes|cases)))\b"
)
_UNSUPPORTED_PILL_RE = re.compile(
    r"\b(send\s+(?:whatsapp|gmail|email|reply\s+now|now)|"
    r"open\s+ticket\s+drawer|show\s+leak\s+photos|draft\s+plumber\s+order)\b",
    re.IGNORECASE,
)


def _is_prioritization_query(q_low: str) -> bool:
    if _EXPLICIT_DRAFT_ASK_RE.search(q_low):
        return False
    return bool(_PRIORITIZE_RE.search(q_low))


def _is_multi_draft_request(q_low: str) -> bool:
    return bool(_MULTI_DRAFT_RE.search(q_low))


def _sanitize_suggestions(
    raw_suggestions: Sequence[str],
    target_cards: Sequence[PreviewCardData],
    q_low: str,
) -> list[str]:
    """Strip unsafe/unsupported/channel-mismatched pills and always pad to 3 executable suggestions."""
    draft_msg_cards = [c for c in target_cards if c.type == "draft_message"]
    draft_channels = {(c.channel or "").lower() for c in draft_msg_cards if c.channel}

    cleaned: list[str] = []
    for item in raw_suggestions:
        pill = item.strip()
        if not pill:
            continue
        p_low = pill.lower()
        if _UNSUPPORTED_PILL_RE.search(p_low):
            continue
        if draft_channels == {"gmail"} and "whatsapp" in p_low:
            continue
        if draft_channels == {"whatsapp"} and ("gmail" in p_low or "email" in p_low):
            continue
        if pill not in cleaned:
            cleaned.append(pill)

    if draft_msg_cards or any(c.type == "notice" for c in target_cards):
        fallback_pills = ["Show open tickets", "What should I do first?", "Open in Inbox"]
    elif _is_prioritization_query(q_low):
        fallback_pills = ["Draft replies for tickets", "Show open tickets", "List active leases"]
    elif any(k in q_low for k in ["rent", "arrear", "invoice", "money", "overdue", "bouwdepot", "tax"]):
        fallback_pills = ["Draft payment reminder", "Show lease PDF", "Open in Money"]
    elif any(
        k in q_low for k in ["legal", "lawyer", "notary", "roz", "huurcommissie", "evict", "termination", "advocaat"]
    ):
        fallback_pills = ["Draft legal reply", "Read lease clauses", "Open in Messages"]
    elif any(k in q_low for k in ["project", "acquisition", "dd", "due diligence", "permit", "splits", "nieuw"]):
        fallback_pills = ["Show DD reviews", "Search project files", "Open in Messages"]
    elif any(k in q_low for k in ["vve", "utility", "insurance", "municipality", "admin"]):
        fallback_pills = ["Search VvE emails", "Draft admin reply", "Open in Messages"]
    elif any(k in q_low for k in ["viewing", "prospect", "broker", "makelaar", "investor"]):
        fallback_pills = ["Check calendar slots", "Draft viewing reply", "Open in Contacts"]
    elif any(k in q_low for k in ["leak", "boiler", "repair", "maintenance", "ticket", "priority"]):
        fallback_pills = ["What should I do first?", "Draft replies for tickets", "List active leases"]
    elif any(k in q_low for k in ["lease", "contract", "doc", "pdf"]):
        fallback_pills = ["Show open tickets", "Show tenant contact", "Open lease view"]
    else:
        fallback_pills = ["List active leases", "Show open tickets", "What should I do first?"]

    for fp in fallback_pills:
        if fp not in cleaned:
            cleaned.append(fp)
    return cleaned[:3]


def _resolve_query_navigation(question: str, columns: list[str]) -> tuple[str, str]:
    """Determine the optimal target frontend page and button label for an analytical query result."""
    q_low = question.lower()
    col_str = " ".join(str(c).lower() for c in columns)

    # 1. Tenants / Leases check (including common typos)
    if (
        bool(
            re.search(
                r"\b(tenant|tenants|tenat|tenats|tenaant|tenaants|huurder|huurders|lease|leases|huurcontract)\b", q_low
            )
        )
        or "tenant" in col_str
        or "lease" in col_str
    ):
        return "/tenants", "Open Tenants"

    # 2. Properties / Vacancy check
    if (
        bool(re.search(r"\b(property|properties|unit|units|vacant|vacancy|portfolio|building|pand|panden)\b", q_low))
        or "unit" in col_str
        or "address" in col_str
        or "propert" in col_str
        or "vacan" in col_str
    ):
        return "/properties", "Open Properties"

    # 3. Financial / Rates / Rent Money check (word boundaries avoid matching 'currently' for 'rent')
    if bool(
        re.search(
            r"\b(profit|revenue|income|margin|rent|arrears|overdue|collection|ledger|money|rate|quote|quotes|invoice|invoices|factuur|overcharge|spend|expense|cost)\b",
            q_low,
        )
    ) or any(c in col_str for c in ("profit", "spend", "invoice", "overdue", "rate", "eur", "cents")):
        return "/money", "Open Money"

    # 4. Waiting radar
    if bool(re.search(r"\b(waiting|chase|chases)\b", q_low)) or "waiting" in col_str or "chase" in col_str:
        return "/waiting", "Open Waiting"

    # 5. Documents & Due Diligence
    if (
        bool(re.search(r"\b(document|documents|file|filed|pdf|dd_reviews|due\s+diligence)\b", q_low))
        or "doc" in col_str
    ):
        return "/documents", "Open Documents"

    # 6. Maintenance & Tickets (strictly maintenance, not generic cases)
    if (
        bool(re.search(r"\b(ticket|tickets|maintenance|maintnace|repair|brixx)\b", q_low))
        or "ticket" in col_str
        or "urgency" in col_str
    ):
        return "/maintenance", "Open Maintenance"

    # 7. Contacts & Directory (all roles: contractors, legal, vve, business, prospects)
    if (
        bool(re.search(r"\b(contractor|contractors|contact|contacts|vve|lawyer|notary|broker|makelaar)\b", q_low))
        or "contractor" in col_str
        or "brixx_ref" in col_str
    ):
        return "/contacts", "Open Contacts"

    # 8. Inbox / Messages (legal, business, administration, new_projects, general cases)
    if (
        bool(
            re.search(r"\b(case|cases|legal|business|administration|new_projects|email|mail|whatsapp|message)\b", q_low)
        )
        or "case" in col_str
        or "category" in col_str
    ):
        return "/inbox", "Open Messages"

    # 9. Calendar & Visits
    if bool(re.search(r"\b(visit|visits|calendar|schedule|appointment|afspraak)\b", q_low)) or "start" in col_str:
        return "/calendar", "Open Calendar"

    return "/", "Open Dashboard"


def _build_query_preview_card(
    question: str,
    display_rows: list[dict[str, Any]],
    columns: list[str],
    row_count: int,
) -> tuple[PreviewCardData | None, list[ActionButtonData]]:
    """Build a structured preview card (`tenant_lease` or `data_table`) from sanitized query results."""
    if not display_rows or not columns:
        return None, []

    target_url, action_label = _resolve_query_navigation(question, columns)
    nav_action = ActionButtonData(label=action_label, actionType="navigate", payload=target_url, isPrimary=True)

    if row_count == 1 and len(columns) <= 1:
        return None, [nav_action]

    q_low = question.lower()
    money_cols = {
        "Net Profit (€)",
        "Collected Rent (€)",
        "Scheduled Rent (€)",
        "Overdue Rent (€)",
        "Overdue (€)",
        "Paid (€)",
        "Contract Rent (€)",
        "Scheduled (€)",
        "Collected (€)",
        "Collection Rate (%)",
        "Maintenance Cost (€)",
        "Margin (%)",
        "Invoice Number",
        "Billing Month",
        "Overcharge",
        "Amount",
        "Total",
    }
    money_words = (
        "profit",
        "revenue",
        "income",
        "margin",
        "rent",
        "arrears",
        "overdue",
        "collection",
        "money",
        "ledger",
        "rate card",
        "vendor rate",
        "agreed rate",
        "quote",
        "quotes",
        "invoice",
        "factuur",
        "overcharge",
        "spend",
        "expense",
    )
    is_money_query = any(c in money_cols for c in columns) or any(w in q_low for w in money_words)

    if (
        len(display_rows) == 1
        and not is_money_query
        and ("Tenant" in columns or "Lease Start" in columns or "Lease End" in columns)
    ):
        row = display_rows[0]
        tenant_name = str(row.get("Tenant") or row.get("Name") or "Tenant")
        unit_lbl = str(row.get("Property") or row.get("Unit") or "Portfolio Unit")
        lease_start = str(row.get("Lease Start") or "")
        lease_end = str(row.get("Lease End") or "")
        status_val = str(row.get("Status") or "Active")
        extra_bits = [
            f"{k}: {v}"
            for k, v in row.items()
            if v and v != "—" and k not in {"Tenant", "Name", "Property", "Unit", "Lease Start", "Lease End", "Status"}
        ]
        card = PreviewCardData(
            type="tenant_lease",
            badgeLabel="ACTIVE LEASE" if status_val.lower() == "active" else "LEASE",
            badgeColor="emerald" if status_val.lower() == "active" else "blue",
            title=tenant_name,
            subtitle=unit_lbl,
            unitLabel=unit_lbl,
            recipient=tenant_name,
            status=status_val,
            leaseStart=lease_start if lease_start and lease_start != "—" else None,
            leaseEnd=lease_end if lease_end and lease_end != "—" else None,
            body=" · ".join(extra_bits),
            targetUrl="/tenants",
        )
        return card, [ActionButtonData(label="Open Tenants", actionType="navigate", payload="/tenants", isPrimary=True)]

    if is_money_query:
        if "Net Profit (€)" in columns or any(w in q_low for w in ("profit", "margin", "revenue")):
            badge_label = "PROFITABILITY"
            badge_color = "emerald"
            title = f"Property Profitability ({row_count})"
        elif (
            "Invoice Number" in columns
            or "Overdue (€)" in columns
            or any(w in q_low for w in ("rent", "arrears", "overdue", "collection", "ledger"))
        ):
            has_overdue = any(
                str(r.get("Status", "")).lower() in ("overdue", "partial")
                or (str(r.get("Overdue (€)", "0")).replace("—", "0") not in ("0", "0.0", "0.00"))
                for r in display_rows
            )
            badge_label = "RENT LEDGER"
            badge_color = "amber" if has_overdue else "emerald"
            title = f"Rent Ledger & Collections ({row_count})"
        else:
            badge_label = "FINANCE & QUOTES"
            badge_color = "amber"
            title = f"Financial & Rate Records ({row_count})"
        target_url = "/money"
        action_label = "Open Money"
    elif (
        "Lease Start" in columns
        or "Lease End" in columns
        or any("tenant" in str(c).lower() or "lease" in str(c).lower() for c in columns)
        or any(w in q_low for w in ("lease", "leases", "tenant", "tenants", "tenat", "tenats", "tenaant", "tenaants"))
    ):
        badge_label = "LEASES" if ("lease" in q_low or "Lease Start" in columns) else "TENANTS"
        badge_color = "emerald"
        title = f"Active Leases ({row_count})" if "active" in q_low else f"Lease & Tenant Records ({row_count})"
        target_url = "/tenants"
        action_label = "Open Tenants"
    elif "Expected By" in columns or "Chase Count" in columns or any(w in q_low for w in ("waiting", "chase")):
        badge_label = "WAITING RADAR"
        badge_color = "amber"
        title = f"Waiting-For Items ({row_count})"
        target_url = "/waiting"
        action_label = "Open Waiting"
    elif "Doc Type" in columns or "File Name" in columns or any(w in q_low for w in ("document", "documents", "filed")):
        badge_label = "DOCUMENTS"
        badge_color = "blue"
        title = f"Documents ({row_count})"
        target_url = "/documents"
        action_label = "Open Documents"
    elif (
        "Ticket" in columns
        or "Urgency" in columns
        or any(
            w in q_low for w in ("ticket", "tickets", "case", "cases", "maintenance", "maintnace", "repair", "issue")
        )
    ):
        has_urgent = any(str(r.get("Urgency", "")).lower() in ("emergency", "high") for r in display_rows)
        badge_label = "TICKETS"
        badge_color = "rose" if has_urgent else "blue"
        title = f"Maintenance & Support Tickets ({row_count})"
        target_url = "/maintenance"
        action_label = "Open Maintenance"
    elif "Contractor" in columns or "contractor" in q_low:
        badge_label = "CONTRACTORS"
        badge_color = "amber"
        title = f"Contractors ({row_count})"
        target_url = "/contacts"
        action_label = "Open Contacts"
    elif "Starts" in columns or any(w in q_low for w in ("visit", "visits", "calendar", "schedule")):
        badge_label = "SCHEDULE"
        badge_color = "emerald"
        title = f"Scheduled Visits ({row_count})"
        target_url = "/calendar"
        action_label = "Open Calendar"
    elif (
        "Unit" in columns
        or "Address" in columns
        or "Unit Address" in columns
        or "Property" in columns
        or any(
            "unit" in str(c).lower()
            or "address" in str(c).lower()
            or "vacan" in str(c).lower()
            or "propert" in str(c).lower()
            for c in columns
        )
        or any(
            w in q_low
            for w in (
                "property",
                "properties",
                "unit",
                "units",
                "vacant",
                "vacancy",
                "portfolio",
                "building",
                "pand",
                "panden",
            )
        )
    ):
        badge_label = "PROPERTIES" if "vacan" not in q_low else "VACANT UNITS"
        badge_color = "amber" if "vacan" in q_low else "blue"
        title = f"Vacant Properties ({row_count})" if "vacan" in q_low else f"Portfolio Properties ({row_count})"
        target_url = "/properties"
        action_label = "Open Properties"
    else:
        badge_label = "PORTFOLIO DATA"
        badge_color = "blue"
        title = f"Portfolio Records ({row_count})"
        target_url = "/"
        action_label = "Open Dashboard"

    table_card = PreviewCardData(
        type="data_table",
        badgeLabel=badge_label,
        badgeColor=badge_color,
        unitLabel=f"{row_count} record{'s' if row_count != 1 else ''}",
        title=title,
        subtitle=f"Showing {min(len(display_rows), 15)} of {row_count} matching entries"
        if row_count > len(display_rows[:15])
        else None,
        columns=columns,
        rows=display_rows[:15],
        totalCount=row_count,
        targetUrl=target_url,
    )
    return table_card, [ActionButtonData(label=action_label, actionType="navigate", payload=target_url, isPrimary=True)]


def _owned_conversation(session: Session, principal: Principal, conversation_id: UUID) -> AgentConversation | None:
    """A conversation of the signed-in owner; anyone else's (another company's or another owner's) does not exist."""
    return session.scalars(
        select(AgentConversation).where(
            AgentConversation.id == conversation_id,
            AgentConversation.company_id == principal.company_id,
            AgentConversation.owner_id == principal.owner_id,
        )
    ).first()


def _api_steps(
    engine: Engine, company_id: UUID, briefs: list[CaseBrief]
) -> dict[Intent, Callable[[PlanStep], Segment]]:
    """The plan steps this route answers with its own cards (`intent_responses`), each in a short session of its own;
    `compose` sends every other step to `run_plan`. A `calendar` step's text is the planner's: the helper reads a time
    from it and matches it against the company's own cases and contractors; every id and invitee comes from those
    rows."""

    def remember(step: PlanStep) -> Segment:
        with Session(engine) as session:
            return remember_segment(session, company_id, step)

    def calendar(step: PlanStep) -> Segment:
        return calendar_segment(_resolve_calendar_action(step.text or "", engine, company_id, briefs))

    return {Intent.remember: remember, Intent.calendar: calendar}


def _finish_agent_response(
    engine: Engine,
    conv_id: UUID,
    req: AskAgentRequest,
    ans_text: str,
    case_refs: list[str],
    suggested_action: str | None,
    action_buttons: list[ActionButtonData],
    step_descriptions: list[str],
    preview_card: PreviewCardData | None,
    cards_list: list[AssistantCardData],
    pipeline_stage: str,
    fallback_reason: str | None,
    suggestions: list[str],
    now: datetime,
    briefs: list[CaseBrief],
    preview_cards: list[PreviewCardData] | None = None,
    turn_id: UUID | None = None,
    sources: Sequence[Source] = (),
) -> AskAgentResponse:
    ans_text = _clean_executive_answer(ans_text)
    effective_preview_cards = (
        preview_cards
        if (preview_cards is not None and len(preview_cards) > 0)
        else ([preview_card] if preview_card else [])
    )
    suggestions = _sanitize_suggestions(suggestions, effective_preview_cards, req.query.lower())
    with Session(engine) as session:
        conv = session.get(AgentConversation, conv_id)
        if not conv:  # ask_agent created or loaded it for the signed-in owner moments ago
            raise NotFoundError("conversation not found")

        if not conv.title or conv.title == "New Chat":
            conv.title = _generate_thread_title(req.query, ans_text, briefs)

        current_focus = next_focus(conv.focus_state or {}, preview_card.model_dump() if preview_card else None)

        conv.focus_state = current_focus
        conv.last_turn_at = now

        user_turn = AgentTurn(
            company_id=conv.company_id,
            conversation_id=conv.id,
            text=req.query,
            status=TurnStatus.done,
            answer=None,
            page_context={"context": req.context},
        )
        session.add(user_turn)

        agent_turn = AgentTurn(
            id=turn_id or new_id(),
            company_id=conv.company_id,
            conversation_id=conv.id,
            text=req.query,
            status=TurnStatus.done,
            answer=ans_text,
            results={
                "cards": [c.model_dump() for c in cards_list],
                "previewCard": preview_card.model_dump() if preview_card else None,
                "previewCards": [c.model_dump() for c in effective_preview_cards],
                "actions": [a.model_dump() for a in action_buttons],
                "steps": step_descriptions,
                "suggestedPrompts": suggestions,
                "sources": [s.model_dump() for s in sources],
            },
        )
        session.add(agent_turn)
        session.commit()
        conv_title = conv.title or "New Chat"

    return AskAgentResponse(
        conversation_id=str(conv_id),
        conversation_title=conv_title,
        answer=ans_text,
        caseRefs=case_refs,
        suggestedAction=suggested_action,
        actions=action_buttons,
        executedAt=now.isoformat(),
        steps=step_descriptions,
        previewCard=preview_card,
        previewCards=effective_preview_cards,
        cards=cards_list,
        debugInfo=DebugInfo(pipeline_stage=pipeline_stage, fallback_reason=fallback_reason),
        suggestedPrompts=suggestions,
        focus_state=current_focus,
        sources=list(sources),
    )


@router.post(
    "/ask/stream",
    dependencies=[Depends(ask_limit)],
    summary="Stream EstateOS Super Agent response (SSE)",
    description="Streams status heartbeats while Astra researches, followed by the final AskAgentResponse payload.",
)
async def ask_agent_stream(
    req: AskAgentRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    principal: Annotated[Principal, Depends(require_session)],
) -> StreamingResponse:
    async def _events() -> AsyncIterator[str]:
        step_queue: queue.SimpleQueue[str] = queue.SimpleQueue()
        token = _STEP_CALLBACK.set(step_queue.put)
        yield f"event: status\ndata: {json.dumps({'stage': 'thinking'})}\n\n"
        task = asyncio.create_task(run_in_threadpool(ask_agent, req, engine, settings, principal))
        last_heartbeat = asyncio.get_running_loop().time()
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=0.3)
                emitted = False
                while not step_queue.empty():
                    step_text = step_queue.get_nowait()
                    emitted = True
                    yield f"event: status\ndata: {json.dumps({'stage': 'step', 'step': step_text})}\n\n"
                now_t = asyncio.get_running_loop().time()
                if emitted:
                    last_heartbeat = now_t
                elif not task.done() and (now_t - last_heartbeat) >= 2.0:
                    last_heartbeat = now_t
                    yield f"event: status\ndata: {json.dumps({'stage': 'researching'})}\n\n"
            while not step_queue.empty():
                step_text = step_queue.get_nowait()
                yield f"event: status\ndata: {json.dumps({'stage': 'step', 'step': step_text})}\n\n"
            result = await task
            yield f"event: result\ndata: {result.model_dump_json()}\n\n"
        except HTTPException as exc:
            yield f"event: error\ndata: {json.dumps({'status': exc.status_code, 'detail': exc.detail})}\n\n"
        except Exception as exc:
            log.warning("agent.ask_stream.error", error_type=type(exc).__name__)
            yield f"event: error\ndata: {json.dumps({'status': 500, 'detail': 'Internal error'})}\n\n"
        finally:
            _STEP_CALLBACK.reset(token)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/ask",
    dependencies=[Depends(ask_limit)],
    response_model=AskAgentResponse,
    summary="Ask EstateOS Super Agent",
    description=(
        "Natural language queries & autonomous execution across portfolio, leases, arrears, and maintenance "
        "tickets using the CONCIERGE agent."
    ),
)
def ask_agent(
    req: AskAgentRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    principal: Annotated[Principal, Depends(require_session)],
) -> AskAgentResponse:
    now = datetime.now(UTC)
    pipeline_stage = "llm_concierge"
    fallback_reason = None
    with Session(engine) as session:
        company_id = principal.company_id

        # Resolve or initialize the AgentConversation thread: only one of the signed-in owner's own can be continued
        conv: AgentConversation | None = None
        if req.conversation_id:
            try:
                conv = _owned_conversation(session, principal, UUID(req.conversation_id))
            except ValueError:
                conv = None

        if not conv:
            conv = AgentConversation(
                company_id=company_id,
                owner_id=principal.owner_id,
                title="New Chat",
                focus_state={},
            )
            session.add(conv)
            session.commit()
            session.refresh(conv)

        conv_id = conv.id
        history = (req.history or [])[-MAX_HISTORY:]

        q_low = req.query.strip().strip("\"'“”`").lower()

        # Pull active owner memory rules (T5)
        approved_memories = list(
            session.scalars(
                select(MemoryItem.text)
                .where(MemoryItem.company_id == company_id, MemoryItem.status == MemoryStatus.active)
                .order_by(MemoryItem.created_at.desc())
                .limit(15)
            ).all()
        )

        # Pull pre-warmed page facts if available
        page_row = session.scalars(
            select(AgentPageState)
            .where(AgentPageState.company_id == company_id)
            .order_by(AgentPageState.resolved_at.desc())
            .limit(1)
        ).first()
        page_facts_text = ""
        if page_row and isinstance(page_row.resolved, dict):
            page_facts_text = page_row.resolved.get("facts", "") or ""
            trail_line = page_row.resolved.get("focus_trail", "") or ""
            if trail_line:
                page_facts_text = f"{page_facts_text}\n{trail_line}".strip() if page_facts_text else trail_line
        coverage_text = _message_coverage_fact(session, company_id, now)
        if coverage_text:
            page_facts_text = f"{page_facts_text}\n\n{coverage_text}".strip() if page_facts_text else coverage_text

        urgency_order = sql_case(
            (Case.urgency == Urgency.emergency, 0),
            (Case.urgency == Urgency.high, 1),
            (Case.urgency == Urgency.normal, 2),
            else_=3,
        )
        cases = session.scalars(
            select(Case)
            .where(Case.company_id == company_id, Case.state.in_(case_repo.OPEN_STATES))
            .order_by(urgency_order.asc(), Case.opened_at.desc(), Case.id.desc())
            .limit(20)
        ).all()

        # Attach real conversation history (last 3 messages) to the top active cases
        case_ids = [c.id for c in cases[:6]]
        case_msgs_map: dict[UUID, list[str]] = {cid: [] for cid in case_ids}
        if case_ids:
            try:
                msg_rows = session.execute(
                    select(
                        CaseLink.case_id, MessageRow.direction, MessageRow.channel, MessageRow.sent_at, MessageRow.text
                    )
                    .join(MessageRow, MessageRow.id == CaseLink.message_id)
                    .where(CaseLink.company_id == company_id, CaseLink.case_id.in_(case_ids))
                    .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
                    .limit(30)
                ).all()
                for cid, direction, channel, sent_at, text in msg_rows:
                    if len(case_msgs_map.get(cid, [])) < 3:
                        snippet = " ".join(text.split())[:180]
                        dir_val = getattr(direction, "value", str(direction))
                        dir_label = "Inbound" if dir_val == "inbound" else "Outbound"
                        date_str = to_local(sent_at).strftime("%d %b %H:%M") if sent_at else ""
                        case_msgs_map[cid].append(f'[{date_str} {dir_label} via {channel}]: "{snippet}"')
            except Exception as e:
                log.warning("api.superagent.case_msgs_enrich_failed", error=str(e))

        briefs = []
        for c in cases:
            recent_lines = case_msgs_map.get(c.id, [])
            summary = c.summary or ""
            if getattr(c, "brixx_ref", None):
                summary = f"[Linked to BRIXX Work Order #{c.brixx_ref}] {summary}".strip()
            if recent_lines:
                summary += " | Recent messages: " + " ; ".join(reversed(recent_lines))
            briefs.append(CaseBrief(c.id, _case_label(session, c), c.state.value, c.urgency.value, summary))

        # Order briefs by real-world urgency (emergency > high > normal > low), keeping temporal order within a tier
        _urgency_weights = {"emergency": 0, "high": 1, "normal": 2, "low": 3}
        briefs.sort(key=lambda b: _urgency_weights.get((b.urgency or "").lower(), 4))
        open_tasks = work_repo.open_tasks(session, company_id, now=now)[:20]
        tasks = [task_brief(t.id, t.title) for t in open_tasks]

        task_command = owner_commands.parse_command(req.query)
        if task_command.kind in (owner_commands.CommandKind.done, owner_commands.CommandKind.snooze):
            # "done #ref" / "snooze #ref 2d" act on the owner's own task list: never left to the model's plan
            return _finish_agent_response(
                engine=engine,
                conv_id=conv_id,
                req=req,
                ans_text=owner_commands.run_command(engine, settings, company_id, task_command, now=now),
                case_refs=[],
                suggested_action=None,
                action_buttons=[],
                step_descriptions=["Updated your task list"],
                preview_card=None,
                cards_list=[],
                pipeline_stage="owner_command",
                fallback_reason=None,
                suggestions=["Show my tasks", "What should I do first?", "Show open tickets"],
                now=now,
                briefs=briefs,
            )

        # Document RAG ONLY for explicit document/file/PDF retrieval (never for analytics or counts)
        is_explicit_doc_inquiry = (
            bool(re.search(r"\b(pdf|document|drive\b|file\b|clause|agreement for this case|scan\b)\b", q_low))
            and not bool(
                re.search(
                    r"\b(how many|count|list all|show all|total|which|active|who is|who are|expir"
                    r"|profit|spend|revenue|margin|vacan)\b",
                    q_low,
                )
            )
            and not any(
                w in q_low
                for w in [
                    "message",
                    "messages",
                    "reply",
                    "email",
                    "mail",
                    "whatsapp",
                    "sent",
                    "send",
                    "attachment",
                    "attachments",
                    "received",
                    "from",
                    "last",
                    "latest",
                ]
            )
        )
        if is_explicit_doc_inquiry:
            try:
                embedder = build_embedder(settings)
                hits = search_hybrid(session, company_id, req.query, DocFilter(), embedder, limit=3)
                if hits:
                    best_hit = hits[0]
                    matched_doc = session.get(DocumentRow, best_hit.document_id)
                    if matched_doc:
                        drive_url = (
                            f"https://drive.google.com/file/d/{matched_doc.drive_file_id}/view"
                            if matched_doc.drive_file_id
                            else None
                        )
                        clean_snippet = (best_hit.snippet or "").replace("«", "").replace("»", "")
                        matched_chunks = list(
                            session.scalars(
                                select(DocumentChunk.text)
                                .where(DocumentChunk.document_id == matched_doc.id)
                                .order_by(DocumentChunk.ord)
                            ).all()
                        )
                        doc_full_text = "\n".join(matched_chunks) if matched_chunks else clean_snippet
                        doc_context = (
                            f"Matched Document: {matched_doc.title} ({matched_doc.doc_type})\n"
                            f"Full Verified Document Content:\n{doc_full_text}"
                        )
                        chat_doc_ans = _generate_chat_answer(
                            (
                                "Answer this user query directly and concisely in 1-2 bullet points based on the "
                                "document: "
                                f"'{req.query}'. Keep the answer short and executive."
                            ),
                            settings,
                            engine,
                            company_id,
                            _system_prompt(req.query, page_facts=doc_context),
                        )
                        doc_ans = (
                            f"**Document Intelligence (Verified RAG):**\n\n{chat_doc_ans}\n\n"
                            if chat_doc_ans
                            else (
                                f"**Document Intelligence (Verified RAG):**\n\n"
                                f"**{matched_doc.title}** ({matched_doc.doc_type.capitalize()})\n\n{clean_snippet}\n\n"
                            )
                        )
                        if matched_doc.drive_folder:
                            doc_ans += f"📁 **Google Drive Location:** `{matched_doc.drive_folder}`\n"
                        if drive_url:
                            doc_ans += f"🔗 [Open Original Document in Google Drive]({drive_url})"

                        actions = []
                        if drive_url:
                            actions.append(
                                ActionButtonData(
                                    label="Open in Google Drive",
                                    actionType="external_link",
                                    payload=drive_url,
                                    isPrimary=True,
                                )
                            )
                        actions.append(
                            ActionButtonData(
                                label="View in Properties",
                                actionType="navigate",
                                payload="/properties",
                                isPrimary=False,
                            )
                        )
                        unit_label = "Portfolio Document"
                        doc_text_low = (matched_doc.title + " " + (matched_doc.drive_folder or "")).lower()
                        unit_rows = session.scalars(
                            select(Unit).where(Unit.company_id == company_id, Unit.valid_to.is_(None))
                        ).all()
                        for u_it in unit_rows:
                            if u_it.label and u_it.label.lower() in doc_text_low:
                                unit_label = u_it.label
                                break

                        doc_preview_card = PreviewCardData(
                            type="document_item",
                            badgeLabel="GOOGLE DRIVE",
                            unitLabel=unit_label,
                            status="Verified RAG Match",
                            title=matched_doc.title,
                            body=clean_snippet,
                            targetUrl=drive_url or "/documents",
                        )
                        return AskAgentResponse(
                            answer=_clean_executive_answer(doc_ans),
                            suggestedAction="Open in Google Drive" if drive_url else "View in Documents",
                            actions=actions,
                            previewCard=doc_preview_card,
                            previewCards=[doc_preview_card],
                            cards=build_cards_list([doc_preview_card]),
                            executedAt=now.isoformat(),
                            steps=[],
                            debugInfo=DebugInfo(pipeline_stage="regex_document"),
                        )
            except Exception as rag_err:
                log.warning("api.superagent.rag_trigger_failed", error=str(rag_err))

    live_cases_text = (
        "\n".join(
            [
                (
                    f"• Ticket #{short_case_ref(b.case_id)}: {b.label} (State: {b.state}, Urgency: {b.urgency}). "
                    f"Problem: {b.summary}"
                )
                for b in briefs
            ]
        )
        if briefs
        else "• No active open tickets."
    )

    # Build prompt using context compiler with active memory rules and page facts
    history = (req.history or [])[-MAX_HISTORY:]
    entities = _entities(engine, company_id, req.query) if NAMED_BLOCKS else NO_ENTITIES
    summary_line: list[str] = []
    thread_summary = ""
    focus_cid: str | None = None
    try:
        if conv:
            thread_summary = conv.summary or ""
            summary_line = [f"{SUMMARY_PREFIX}{thread_summary}"] if thread_summary.strip() else []
            focus_cid = str((conv.focus_state or {}).get("case_id") or "") or None
    except Exception as focus_err:  # a detached thread only costs the focus hint
        log.warning("api.superagent.focus_read_failed", error=type(focus_err).__name__)
    try:
        # Inject active thread focus if available
        focus_text = ""
        if conv and conv.focus_state:
            f_lines = []
            if conv.focus_state.get("unit_label"):
                f_lines.append(f"• Property / Unit: {conv.focus_state['unit_label']}")
            if conv.focus_state.get("recipient"):
                f_lines.append(f"• Active Contact: {conv.focus_state['recipient']}")
            if conv.focus_state.get("contractor"):
                f_lines.append(f"• Assigned Contractor: {conv.focus_state['contractor']}")
            if conv.focus_state.get("case_id"):
                f_lines.append(f"• Active Ticket: #{short_case_ref(conv.focus_state['case_id'])}")
            if f_lines:
                focus_text = (
                    "\n\nActive Thread Focus (Pronouns like 'he', 'him', 'that ticket' refer to these entities):\n"
                    + "\n".join(f_lines)
                )

        with Session(engine) as turn_session:
            prior_turns = turn_session.scalar(
                select(func.count(AgentTurn.id)).where(
                    AgentTurn.company_id == company_id, AgentTurn.conversation_id == conv_id
                )
            )
        fresh_chat_text = new_chat_fact(prior_turns or 0)
        compiled = compile_concierge_context(
            question=req.query,
            recent=[*summary_line, *history],
            entities=entities.render(),
            named_blocks=NAMED_BLOCKS,
            cases=rank_cases(briefs, req.query, focus_cid),
            open_tasks=tasks,
            page_facts_text="\n\n".join(t for t in ((page_facts_text or "") + focus_text, fresh_chat_text) if t),
            owner_preferences=approved_memories,
        )
        prompt = compiled.prompt_text
        log.info(
            "api.superagent.context",
            prompt_chars=len(prompt),
            open_cases=len(briefs),
            dropped=list(compiled.dropped),
        )
    except Exception:
        prompt = concierge_prompt(req.query, history, briefs, tasks)

    plan: ConciergePlan | None = None
    results: list[StepResult] = []
    segments: list[Segment] = []  # the plan's answers in order; `results` are those of its run_plan segment
    rest_at: int | None = None  # where the run_plan segment sits among them
    case_refs: list[str] = []

    # 1. Try running full CONCIERGE agent via LLM
    llm_failed = False
    try:
        call_res = run_agent(engine, settings, CONCIERGE, prompt, CallContext(company_id, CONCIERGE_PURPOSE))
        plan = call_res.output
    except Exception as exc:
        llm_failed = True
        log.warning(  # a transient provider error is re-raised raw by run_agent: describe it, never log its body
            "api.superagent.llm_fallback",
            error=str(exc) if isinstance(exc, AgentFailedError) else describe_model_error(exc),
        )
        pipeline_stage = "llm_error"
        fallback_reason = f"LLM error: {type(exc).__name__}"
        # Only allow deterministic fake_concierge in offline test environments (settings.env == 'test')
        # In production/dev, reject mock plans so keyword heuristics cannot mutate live data
        if settings.env == "test":
            pipeline_stage = "fake_router"
            try:
                fake_dict = fake_concierge(prompt)
                plan = ConciergePlan.model_validate(fake_dict)
            except Exception as parse_err:
                log.warning("api.superagent.fake_failed", error=str(parse_err))
                plan = None
        else:
            plan = None

    # 2. Guard plan steps, compute property scope, expand multi-drafts, understand un-triaged messages, and dispatch
    turn_id = new_id()
    with Session(engine) as scope_session:
        company_units = [
            (u.label, u.address)
            for u in scope_session.scalars(select(Unit).where(Unit.company_id == company_id, Unit.valid_to.is_(None)))
        ]
    scope = property_scope(req.query, company_units, briefs)

    # Guard: prioritization queries ("whom to reply first", "which ticket is most important") must rank/advise,
    # never invoke draft_reply/show_drafts against an arbitrary or un-understood ticket.
    if plan and plan.in_scope and _is_prioritization_query(q_low):
        filtered_steps = [s for s in plan.steps if s.intent not in (Intent.draft_reply, Intent.show_drafts)]
        if len(filtered_steps) != len(plan.steps):
            plan = plan.model_copy(update={"steps": filtered_steps}) if filtered_steps else None

    auto_expanded_cids: set[UUID] = set()
    _draft_intents = (Intent.draft_reply, Intent.compose_mail, Intent.show_drafts)
    if (
        plan
        and plan.in_scope
        and plan.steps
        and scope.kind != "unknown"
        and any(s.intent in _draft_intents for s in plan.steps)
        and _is_multi_draft_request(q_low)
    ):
        target_pool = list(scope.briefs) if scope.kind == "scoped" else list(briefs)
        urgency_pos = {b.case_id: idx for idx, b in enumerate(target_pool)}
        existing_cids = {s.case_id for s in plan.steps if s.intent in _draft_intents and s.case_id is not None}
        expanded_steps = list(plan.steps)
        draft_step_count = sum(1 for s in expanded_steps if s.intent in _draft_intents)
        for b in target_pool:
            if draft_step_count >= 3 or len(expanded_steps) >= 4:
                break
            if b.case_id not in existing_cids:
                expanded_steps.append(
                    PlanStep(intent=Intent.show_drafts, case_id=b.case_id, task_ref=None, text=None, view=None)
                )
                existing_cids.add(b.case_id)
                auto_expanded_cids.add(b.case_id)
                draft_step_count += 1
        # Order draft steps by urgency rank (emergency > high > normal) while preserving relative order of non-drafts
        draft_steps_sorted = sorted(
            [s for s in expanded_steps if s.intent in _draft_intents],
            key=lambda s: urgency_pos.get(s.case_id, 999) if s.case_id is not None else 999,
        )
        other_steps = [s for s in expanded_steps if s.intent not in _draft_intents]
        plan = plan.model_copy(update={"steps": (draft_steps_sorted + other_steps)[:4]})

    ans_text: str = ""
    try:
        if plan and plan.in_scope and plan.steps:
            known_cases_list = [b.case_id for b in briefs]
            known_cases_list += [c for c in entities.case_ids if c not in known_cases_list]  # found by name
            if conv and conv.focus_state and conv.focus_state.get("case_id"):
                try:
                    f_cid = UUID(str(conv.focus_state["case_id"]))
                    if f_cid not in known_cases_list:
                        known_cases_list.append(f_cid)
                except ValueError:
                    log.warning("api.superagent.focus_case_invalid", conversation_id=str(conv.id))

            # Ensure the latest inbound message on any targeted draft/show_drafts case has an UnderstandingRow
            # so Super Agent requests never get stuck on "still being processed".
            known_set = set(known_cases_list)
            draft_case_ids: list[UUID] = []
            for st in plan.steps:
                if (
                    st.intent in _draft_intents
                    and st.case_id is not None
                    and st.case_id in known_set
                    and st.case_id not in draft_case_ids
                ):
                    draft_case_ids.append(st.case_id)
            if draft_case_ids:
                msgs_to_understand: list[UUID] = []
                with Session(engine) as und_sess:
                    for d_cid in draft_case_ids:
                        latest_msg = und_sess.scalars(
                            select(MessageRow)
                            .join(CaseLink, CaseLink.message_id == MessageRow.id)
                            .where(
                                CaseLink.company_id == company_id,
                                CaseLink.case_id == d_cid,
                                MessageRow.company_id == company_id,
                                MessageRow.direction == Direction.inbound,
                            )
                            .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
                            .limit(1)
                        ).first()
                        if isinstance(latest_msg, MessageRow):
                            existing_und = und_sess.scalars(
                                select(UnderstandingRow)
                                .where(
                                    UnderstandingRow.company_id == company_id,
                                    UnderstandingRow.message_id == latest_msg.id,
                                )
                                .limit(1)
                            ).first()
                            if not isinstance(existing_und, UnderstandingRow):
                                msgs_to_understand.append(latest_msg.id)
                for mid in msgs_to_understand:
                    try:
                        understand.understand_message(engine, settings, mid)
                    except Exception as und_err:
                        log.warning(
                            "api.superagent.inline_understand_failed",
                            message_id=str(mid),
                            error=str(und_err),
                        )

            def run_rest(rest: ConciergePlan) -> list[StepResult]:
                results.extend(
                    run_plan(
                        engine,
                        settings,
                        company_id,
                        rest,
                        question=req.query,
                        now=now,
                        brief_cases=known_cases_list,
                        turn_id=turn_id,
                        research=make_researcher(engine, settings, on_step=_STEP_CALLBACK.get()),
                        history=[*summary_line, *history],
                    )
                )
                return results

            api_steps = _api_steps(engine, company_id, briefs)
            segments = compose(plan, api_steps, run_rest)
            rest_at = rest_position(plan, api_steps)
            if rest_at is not None:  # what follows finishes the run_plan answer: it reads the steps run_plan ran
                ans_text = segments[rest_at].text
                plan = rest_plan(plan, api_steps)
        else:
            # Screened or direct command path via owner_commands
            cmd = owner_commands.parse_command(req.query)
            ans_text = owner_commands.run_command(engine, settings, company_id, cmd, now=now)
    except Exception as exec_err:
        log.warning("api.superagent.run_plan_failed", error=str(exec_err))
        ans_text = ""

    if plan and segments and rest_at is None:  # the API layer answered every step: run_plan had nothing to do
        whole = merge(segments)
        return _finish_agent_response(
            engine=engine,
            conv_id=conv_id,
            req=req,
            ans_text=whole.text,
            case_refs=[],
            suggested_action=whole.actions[0].label if whole.actions else None,
            action_buttons=whole.actions,
            step_descriptions=whole.steps,
            preview_card=whole.preview_card,
            cards_list=whole.cards,
            pipeline_stage=STAGES.get(plan.steps[0].intent, pipeline_stage),
            fallback_reason=fallback_reason,
            suggestions=list(plan.suggestions),
            now=now,
            briefs=briefs,
            preview_cards=preview_cards(segments),
            turn_id=turn_id,
        )

    # If the response is empty or an unhandled placeholder, invoke Gemini or clean executive domain generator
    needs_fallback = (
        not ans_text
        or not ans_text.strip()
        or any(
            phrase in ans_text.lower()
            for phrase in [
                "offline answer",
                "sorry, i could not answer",
                "could not be processed",
                "nothing i can repeat",
            ]
        )
    )
    research_steps: tuple[str, ...] = ()
    sources = _step_sources(results)
    is_only_open_view = bool(results) and all(r.intent == Intent.open_view for r in results)
    is_nav_command = q_low.startswith(("open ", "go to ", "navigate "))
    needs_view_prose = (
        not needs_fallback
        and is_only_open_view
        and not is_nav_command
        and not _clean_executive_answer(ans_text).strip()
    )
    beside_api_answers = len(segments) > 1  # research prose never sits beside a rule or a visit the API layer answered
    if (needs_fallback or needs_view_prose) and not beside_api_answers:
        if needs_fallback:
            pipeline_stage = "domain_fallback"
            fallback_reason = fallback_reason or "Empty or placeholder response"
        system_prompt = _system_prompt(
            req.query,
            memory_rules=approved_memories,
            page_facts=page_facts_text,
            cases=briefs,
            thread_summary=thread_summary,
            focus_case_id=focus_cid,
        )
        try:
            researched = _research_answer(req.query, settings, engine, company_id, system_prompt, req.history)
        except Exception as res_err:
            log.warning("api.superagent.research_fallback_failed", error=type(res_err).__name__)
            researched = None
        if researched is not None:
            research_steps = researched.steps
            sources = list(researched.sources)
            chat_resp: str | None = screen_reply(researched.answer)  # web pages and mail reach it: screen like a reply
        else:
            try:
                chat_resp = _generate_chat_answer(req.query, settings, engine, company_id, system_prompt, req.history)
            except Exception as chat_err:
                log.warning("api.superagent.chat_fallback_failed", error=type(chat_err).__name__)
                chat_resp = None
        if chat_resp:
            ans_text = chat_resp
        elif needs_fallback:
            ans_text = domain_fallback_answer(req.query, live_cases_text=live_cases_text, is_error=llm_failed)

    # 3. Build step badge labels and inspect any generated proposal cards / actions
    step_descriptions: list[str] = list(research_steps)
    dropped_warnings: list[str] = []
    skipped_auto_notes: list[str] = []
    draft_cards: list[PreviewCardData] = []
    seen_draft_keys: set[str] = set()
    preview_card = None
    action_buttons: list[ActionButtonData] = []
    q_low = req.query.lower()

    for idx, r in enumerate(results):
        step_case_id = plan.steps[idx].case_id if (plan and idx < len(plan.steps)) else None
        # Check if step executed successfully or was rejected/dropped
        if not r.ok:
            intent_name = r.intent.value.replace("_", " ")
            summary_low = r.summary.lower()
            is_benign_auto_skip = (
                step_case_id is not None
                and step_case_id in auto_expanded_cids
                and ("does not need a reply" in summary_low or "nothing to reply to" in summary_low)
            )
            if is_benign_auto_skip:
                skipped_auto_notes.append("1 open case needed no reply")
            else:
                if "need more detail" in summary_low:
                    explanation = "Action requires a specific case or task reference."
                elif "not found" in summary_low:
                    explanation = "The referenced case or task was not found."
                elif "open that case" in summary_low or "not shown" in summary_low:
                    explanation = "Open that ticket first to access its details."
                else:
                    explanation = r.summary
                step_descriptions.append(f"⚠️ Could not {intent_name}: {explanation}")
                dropped_warnings.append(f"• **Could not {intent_name}**: {explanation}")
        else:
            if r.intent == Intent.answer:
                if r.data and isinstance(r.data.get("steps"), list):
                    step_descriptions.extend(str(s) for s in r.data["steps"] if isinstance(s, str))
            elif r.intent == Intent.query_data:
                step_descriptions.append("Queried verified portfolio records")
                if r.data and not preview_card:
                    d_rows = r.data.get("display_rows")
                    d_cols = r.data.get("columns")
                    if not (isinstance(d_rows, list) and isinstance(d_cols, list)):
                        raw_rows = r.data.get("rows")
                        if isinstance(raw_rows, list) and raw_rows:
                            d_cols, d_rows = sanitize_rows_for_display(raw_rows)
                        else:
                            d_cols, d_rows = [], []
                    q_card_step, q_actions_step = _build_query_preview_card(
                        str(r.data.get("question") or req.query),
                        d_rows or [],
                        d_cols or [],
                        int(r.data.get("row_count") or len(d_rows or [])),
                    )
                    if q_card_step:
                        preview_card = q_card_step
                    for ab in q_actions_step:
                        if not any(b.label == ab.label or b.payload == ab.payload for b in action_buttons):
                            action_buttons.append(ab)
            elif not r.summary.lower().startswith("opening "):
                step_descriptions.append(r.summary)

        # Check if any step referenced a case
        cid_str = None
        if r.data and "case_id" in r.data and r.data["case_id"]:
            cid_str = str(r.data["case_id"])
            case_refs.append(f"#{short_case_ref(cid_str)}")

        # Check for navigation view requests and map strictly to target frontend views
        if r.view:
            v_low = r.view.lower()
            case_ref = cid_str or (str(briefs[0].case_id) if briefs else "")

            if v_low == "waiting":
                view_label = "View Waiting Radar on Dashboard"
                view_path = "/"
            elif v_low in ("cases", "maintenance"):
                if case_ref:
                    view_label = f"Open Ticket #{short_case_ref(case_ref)} in Maintenance"
                    view_path = f"/maintenance?ticket={case_ref}"
                else:
                    view_label = "Open in Maintenance"
                    view_path = "/maintenance"
            elif v_low in ("inbox", "approvals", "messages", "message", "mail", "emails", "communication"):
                if case_ref:
                    view_label = f"Open Thread #{short_case_ref(case_ref)} in Messages"
                    view_path = f"/inbox?thread=case-{case_ref}"
                else:
                    view_label = "Open Messages"
                    view_path = "/inbox"
            elif v_low in ("tasks", "dashboard", "home"):
                # Disambiguate 'tasks' - quote / PO approvals live in Maintenance, communication drafts live in Inbox
                context_str = (ans_text + " " + q_low).lower()
                is_maint = any(
                    w in context_str
                    for w in [
                        "maintenance",
                        "ticket",
                        "quote",
                        "po",
                        "plumber",
                        "electrician",
                        "leak",
                        "repair",
                        "contractor",
                    ]
                )
                is_inbox = any(w in context_str for w in ["email", "reply", "draft", "message", "whatsapp"])

                if case_ref and is_maint:
                    view_label = f"Review PO & Ticket #{short_case_ref(case_ref)} in Maintenance"
                    view_path = f"/maintenance?ticket={case_ref}"
                elif is_maint:
                    view_label = "Open in Maintenance"
                    view_path = "/maintenance"
                elif case_ref and is_inbox:
                    view_label = f"Open Thread #{short_case_ref(case_ref)} in Inbox"
                    view_path = f"/inbox?thread=case-{case_ref}"
                elif is_inbox:
                    view_label = "Review Approvals in Inbox"
                    view_path = "/inbox?tab=needs_approval"
                elif case_ref:
                    ref_brief = next((b for b in briefs if str(b.case_id) == case_ref), None)
                    ref_is_maint = ref_brief is not None and "(maintenance)" in (ref_brief.label or "").lower()
                    if ref_is_maint:
                        view_label = f"Review Ticket #{short_case_ref(case_ref)} in Maintenance"
                        view_path = f"/maintenance?ticket={case_ref}"
                    else:
                        view_label = f"Open Case #{short_case_ref(case_ref)} in Messages"
                        view_path = f"/inbox?thread=case-{case_ref}"
                else:
                    view_label = "Open Today Overview"
                    view_path = "/"
            elif v_low in ("money", "financial", "arrears"):
                inv_match = None
                for w in q_low.split():
                    if any(c.isdigit() for c in w) and ("." in w or len(w) >= 5):
                        inv_match = w.strip("?:!,.#")
                        break
                if inv_match:
                    view_label = f"Open Invoice {inv_match} in Money"
                    view_path = f"/money?invoice={inv_match}"
                else:
                    view_label = "Open in Money"
                    view_path = "/money"
            elif v_low in ("properties", "units"):
                view_label = "Open in Properties"
                view_path = "/properties"
            elif v_low == "tenants":
                view_label = "Open in Tenants"
                view_path = "/tenants"
            elif v_low == "contacts":
                view_label = "Open in Contacts"
                view_path = "/contacts"
            elif v_low == "calendar":
                view_label = "Open Calendar"
                view_path = "/calendar"
            elif v_low == "documents":
                view_label = "Open Documents"
                view_path = "/documents"
            elif v_low == "reports":
                view_label = "Open Reports"
                view_path = "/reports"
            elif v_low == "knowledge":
                view_label = "Open Knowledge Base"
                view_path = "/knowledge"
            else:
                view_label = "View on Dashboard"
                view_path = "/"

            if not any(b.label == view_label or b.payload == view_path for b in action_buttons):
                action_buttons.append(
                    ActionButtonData(
                        label=view_label,
                        actionType="navigate",
                        payload=view_path,
                        isPrimary=len(action_buttons) == 0,
                    )
                )

        # Check if a proposal was drafted (collect all draft/notice cards, up to 3)
        if (
            r.intent in (Intent.draft_reply, Intent.compose_mail, Intent.show_drafts, Intent.chase_now)
            and r.data
            and "approval_ids" in r.data
            and len(draft_cards) < 3
        ):
            approval_ids = r.data.get("approval_ids", [])
            prefer_contractor = any(
                w in req.query.lower()
                for w in ["contractor", "plumber", "monteur", "loodgieter", "work order", "conractore", "contractore"]
            )
            resolved_card = _resolve_draft_card(engine, approval_ids=approval_ids, prefer_contractor=prefer_contractor)
            if resolved_card:
                dedup_key = resolved_card.actionId or resolved_card.caseId or f"draft-{len(draft_cards)}"
                if dedup_key not in seen_draft_keys:
                    seen_draft_keys.add(dedup_key)
                    draft_cards.append(resolved_card)

        # Check for case status snapshot card
        if r.intent == Intent.case_status and r.data and not preview_card and not draft_cards:
            status_cid = r.data.get("case_id") or cid_str or (str(briefs[0].case_id) if briefs else None)
            unit_lbl_step = (
                r.summary.split(":")[0]
                if ":" in r.summary and len(r.summary.split(":")[0]) < 80
                else "Portfolio Ticket"
            )
            preview_card = PreviewCardData(
                type="case_summary",
                badgeLabel="TICKET",
                unitLabel=unit_lbl_step,
                title=f"Ticket #{short_case_ref(str(status_cid))} · {unit_lbl_step}" if status_cid else unit_lbl_step,
                body=_clean_card_body(r.data.get("summary", r.summary)),
                status=r.data.get("state", "open").replace("_", " "),
                caseId=str(status_cid) if status_cid else None,
                targetUrl=f"/maintenance?ticket={status_cid}" if status_cid else "/maintenance",
            )

    if draft_cards:
        urgency_rank = {str(b.case_id): idx for idx, b in enumerate(briefs)}
        draft_cards.sort(key=lambda c: urgency_rank.get(c.caseId or "", 999))
        preview_card = draft_cards[0]

    # If user specifically asked about contractor draft and no card was resolved yet, resolve it directly
    prefer_contractor = any(
        w in req.query.lower()
        for w in ["contractor", "plumber", "monteur", "loodgieter", "work order", "conractore", "contractore"]
    )
    if prefer_contractor and not preview_card and cases:
        for c in cases:
            c_acts = session.scalars(
                select(ActionRow).where(ActionRow.case_id == c.id, ActionRow.type == ActionType.request_contractor)
            ).all()
            if c_acts:
                c_appr = session.scalars(select(Approval).where(Approval.action_id == c_acts[0].id)).first()
                if c_appr:
                    preview_card = _resolve_draft_card(engine, approval_ids=[str(c_appr.id)], prefer_contractor=True)
                    if "no drafted message" in ans_text.lower() or not ans_text:
                        c_payload = c_acts[0].payload if isinstance(c_acts[0].payload, dict) else {}
                        cp_id = c_payload.get("contractor_person_id")
                        cp_person = None
                        if cp_id:
                            try:
                                cp_person = session.get(Person, cp_id if isinstance(cp_id, UUID) else UUID(str(cp_id)))
                            except (ValueError, TypeError):
                                cp_person = None
                        c_name = (
                            cp_person.display_name
                            if cp_person and cp_person.display_name
                            else str(c_payload.get("assigned_to_name") or "the assigned contractor")
                        )
                        c_variants = c_payload.get("body_variants") or []
                        views_text = ""
                        if c_variants:
                            views_text = "\n\nDraft 1:\n> " + "\n> ".join(str(c_variants[0]).split("\n"))
                            if len(c_variants) > 1:
                                views_text += "\n\nDraft 2:\n> " + "\n> ".join(str(c_variants[1]).split("\n"))
                        ans_text = (
                            f"Yes, a work order for contractor {c_name} is already waiting for your approval. "
                            f"Nothing is sent until you approve it in Approvals.{views_text}"
                        )
                    break

    if dropped_warnings and (
        not ans_text or ans_text.strip() in ["I need more detail", "Something went wrong with that step."]
    ):
        ans_text = "**Action Notice:**\n\n" + "\n".join(dropped_warnings)

    preview_cards_list: list[PreviewCardData] = (
        list(draft_cards) if draft_cards else ([preview_card] if preview_card else [])
    )

    card_briefs = list(scope.briefs) if scope.kind == "scoped" else list(briefs)
    if scope.kind == "unknown":
        ans_text = f"I don't have a property on {scope.street} in your portfolio."
        preview_card = None
        preview_cards_list = []
        action_buttons = []
        case_refs = []
        suggested_action = None

    # Populate dynamic navigation and micro-cards for priority/maintenance inquiries from real DB state
    if _is_prioritization_query(q_low) or any(
        k in q_low for k in ["priority", "first", "ticket", "maintenance", "repair", "urgent", "emergency"]
    ):
        if not preview_card and card_briefs and not asks_for_clarification(_clean_executive_answer(ans_text)):
            # Smartly cap at top 3 cases ordered by priority
            top_briefs = card_briefs[:3]
            all_maintenance = True
            for b in top_briefs:
                cid_str = str(b.case_id)
                cid_short = short_case_ref(cid_str)
                is_maint_case = "(maintenance)" in (b.label or "").lower()
                if not is_maint_case:
                    all_maintenance = False
                target_path = f"/maintenance?ticket={cid_str}" if is_maint_case else f"/inbox?thread=case-{cid_str}"
                clean_body = _clean_card_body(b.summary or "Active case in queue.")

                contractor_name: str | None = None
                if is_maint_case:
                    try:
                        req_act = session.scalars(
                            select(ActionRow)
                            .where(ActionRow.case_id == b.case_id, ActionRow.type == ActionType.request_contractor)
                            .order_by(ActionRow.created_at.desc())
                            .limit(1)
                        ).first()
                        if req_act and isinstance(req_act.payload, dict):
                            cp_id = req_act.payload.get("contractor_person_id")
                            if cp_id:
                                try:
                                    p_obj = session.get(Person, cp_id if isinstance(cp_id, UUID) else UUID(str(cp_id)))
                                    if p_obj and p_obj.display_name:
                                        contractor_name = (
                                            f"{p_obj.display_name} ({p_obj.trade.capitalize()})"
                                            if p_obj.trade
                                            else p_obj.display_name
                                        )
                                except (ValueError, TypeError):
                                    pass
                            if not contractor_name and req_act.payload.get("assigned_to_name"):
                                contractor_name = str(req_act.payload["assigned_to_name"])
                    except Exception as cont_err:
                        log.warning("api.superagent.case_contractor_lookup_failed", error=type(cont_err).__name__)

                lbl_parts = [p.strip() for p in (b.label or "").split("·") if p.strip()]
                unit_lbl = lbl_parts[1] if len(lbl_parts) > 1 else (b.label or "Portfolio Unit")
                is_emergency = (b.urgency or "").lower() in ("emergency", "high")
                title_prefix = f"Ticket #{cid_short}" if is_maint_case else f"Case #{cid_short}"

                card = PreviewCardData(
                    type="case_summary",
                    badgeLabel="URGENT" if is_emergency else ("TICKET" if is_maint_case else "CASE"),
                    badgeColor="rose" if is_emergency else "blue",
                    unitLabel=unit_lbl,
                    title=f"{title_prefix} · {unit_lbl}",
                    body=clean_body,
                    contractor=contractor_name,
                    status=b.state.replace("_", " "),
                    caseId=cid_str,
                    targetUrl=target_path,
                )
                preview_cards_list.append(card)

            if preview_cards_list:
                preview_card = preview_cards_list[0]

            if len(briefs) > 3:
                action_buttons.append(
                    ActionButtonData(
                        label=(
                            f"View all {len(briefs)} cases in Maintenance"
                            if all_maintenance
                            else f"View all {len(briefs)} cases in Messages"
                        ),
                        actionType="navigate",
                        payload="/maintenance" if all_maintenance else "/inbox",
                        isPrimary=False,
                    )
                )
            elif top_briefs:
                cid_short = short_case_ref(top_briefs[0].case_id)
                top_is_maint = "(maintenance)" in (top_briefs[0].label or "").lower()
                action_buttons.append(
                    ActionButtonData(
                        label=(
                            f"Open Ticket #{cid_short} in Maintenance"
                            if top_is_maint
                            else f"Open Case #{cid_short} in Messages"
                        ),
                        actionType="navigate",
                        payload=(
                            f"/maintenance?ticket={top_briefs[0].case_id}"
                            if top_is_maint
                            else f"/inbox?thread=case-{top_briefs[0].case_id}"
                        ),
                        isPrimary=True,
                    )
                )
        elif not action_buttons and not preview_cards_list:
            action_buttons.append(
                ActionButtonData(
                    label="Open Maintenance",
                    actionType="navigate",
                    payload="/maintenance",
                    isPrimary=True,
                )
            )
    elif any(k in q_low for k in ["quote", "quotes", "invoice", "factuur", "bill"]):
        if not preview_card:
            try:
                quote_rows = list(
                    session.scalars(
                        select(QuoteRow)
                        .where(QuoteRow.company_id == company_id)
                        .order_by(QuoteRow.quote_date.desc())
                        .limit(3)
                    ).all()
                )
                for q_row in quote_rows:
                    q_person = session.get(Person, q_row.person_id) if q_row.person_id else None
                    q_case = session.get(Case, q_row.case_id) if q_row.case_id else None
                    q_unit = session.get(Unit, q_case.unit_id) if q_case and q_case.unit_id else None
                    q_unit_lbl = (q_unit.address or q_unit.label) if q_unit else "Portfolio Unit"
                    q_vendor = q_person.display_name if q_person else "Contractor Quote"
                    q_amount = f"{q_row.currency} {q_row.total:,.2f}" if q_row.total is not None else None
                    preview_cards_list.append(
                        PreviewCardData(
                            type="financial_item",
                            badgeLabel="QUOTE",
                            badgeColor="amber",
                            unitLabel=q_unit_lbl,
                            title=f"{q_vendor} · {q_unit_lbl}",
                            body=f"Status: {q_row.status.value.replace('_', ' ')}",
                            amount=q_amount,
                            contractor=q_vendor,
                            dueDate=q_row.quote_date.strftime("%d %b %Y") if q_row.quote_date else None,
                            status=q_row.status.value.replace("_", " "),
                            caseId=str(q_row.case_id) if q_row.case_id else None,
                            targetUrl="/money",
                        )
                    )
                if preview_cards_list:
                    preview_card = preview_cards_list[0]
            except Exception as q_err:
                log.warning("api.superagent.quote_card_lookup_failed", error=type(q_err).__name__)
        money_path = "/money"
        money_label = "Open in Money"
        for w in q_low.split():
            clean_w = w.strip("?:!,.#")
            if any(c.isdigit() for c in clean_w) and ("." in clean_w or len(clean_w) >= 4):
                money_path = f"/money?invoice={clean_w}"
                money_label = f"Open Invoice {clean_w} in Money"
                break
        action_buttons.append(
            ActionButtonData(
                label=money_label,
                actionType="navigate",
                payload=money_path,
                isPrimary=True,
            )
        )

    # Ensure answer text clearly introduces single or multiple draft cards without dumping duplicate Draft 1 blocks
    draft_msg_cards = [c for c in preview_cards_list if c.type == "draft_message"]
    draft_or_notice_cards = [c for c in preview_cards_list if c.type in ("draft_message", "notice")]
    details_removed_note = (
        "\n\nContact, bank or payment details and links in your request were removed before drafting."
        if "Contact, bank or payment details" in ans_text
        else ""
    )

    if len(draft_or_notice_cards) > 1 and draft_msg_cards:
        bullet_lines = []
        for d_card in draft_or_notice_cards:
            unit_name = d_card.unitLabel or d_card.title or "Portfolio Case"
            if d_card.type == "draft_message":
                chan_label = "WhatsApp" if (d_card.channel or "").lower() == "whatsapp" else "Gmail"
                bullet_lines.append(f"• **{unit_name}** ({chan_label})")
            else:
                bullet_lines.append(f"• **{unit_name}** (Notice — review in Inbox)")
        n_d = len(draft_msg_cards)
        noun = "reply" if n_d == 1 else "replies"
        skipped_note = f" ({'; '.join(skipped_auto_notes)})" if skipped_auto_notes else ""
        ans_text = (
            f"Here {'is' if n_d == 1 else 'are'} the {n_d} draft {noun} ready for your review{skipped_note}:\n\n"
            + "\n".join(bullet_lines)
            + "\n\nReview each draft and tap **Accept and send** below."
            + details_removed_note
        )
    elif len(draft_msg_cards) == 1 and (
        not ans_text
        or "Draft 1:" in ans_text
        or any(
            k in ans_text.lower()
            for k in [
                "which",
                "are you",
                "can you",
                "sorry",
                "blocking sla",
                "details",
                "i only answer",
                "only answer",
                "send `help`",
            ]
        )
    ):
        target_name = draft_msg_cards[0].unitLabel or "Portfolio"
        if plan and any(s.intent == Intent.show_drafts for s in plan.steps) and "reply drafted" not in ans_text.lower():
            ans_text = (
                f"Here is the draft reply waiting for **{target_name}**. "
                "You can review the message and tap **Accept and send** below." + details_removed_note
            )
        else:
            ans_text = (
                f"I have prepared a draft reply for **{target_name}**. "
                "You can review the message and tap **Accept and send** below." + details_removed_note
            )

    if len(draft_msg_cards) == 1:
        note = channel_note(req.query, draft_msg_cards[0].channel, draft_msg_cards[0].recipient)
        if note:
            ans_text = f"{note}\n\n{ans_text}"

    # Filter out duplicate Approvals button if a draft card is already shown (draft card has Accept and send)
    if draft_msg_cards:
        action_buttons = [b for b in action_buttons if "approval" not in b.label.lower()]

    step_descriptions = display_steps(step_descriptions, has_draft_card=bool(draft_msg_cards))

    suggested_action = action_buttons[0].label if action_buttons else None

    if not _clean_executive_answer(ans_text).strip():  # cards without a sentence, or a property with nothing open
        if scope.kind == "scoped" and not card_briefs:
            ans_text = "No open cases found for the property you named."
        elif skipped_auto_notes and not preview_cards_list:
            ans_text = "None of the open cases currently need a new reply."
        elif preview_cards_list:
            tail = " for the property you named." if scope.kind == "scoped" else "."
            n_cards = len(preview_cards_list)
            noun = "ticket" if n_cards == 1 else "tickets"
            verb = "is the" if n_cards == 1 else f"are the {n_cards}"
            ans_text = f"Here {verb} highest-priority {noun}{tail}"

    # Build polymorphic AssistantCardData list and 3 safe, executable workflow suggestions
    target_cards = preview_cards_list if preview_cards_list else ([preview_card] if preview_card else [])
    raw_suggestions = (
        [s.strip() for s in plan.suggestions if s.strip()] if (plan and getattr(plan, "suggestions", None)) else []
    )
    suggestions = _sanitize_suggestions(raw_suggestions, target_cards, q_low)
    cards_list = build_cards_list(target_cards)

    if rest_at is not None and len(segments) > 1:  # the API layer's answers go around the run_plan one, in plan order
        before, after = segments[:rest_at], segments[rest_at + 1 :]
        rest = Segment(_clean_executive_answer(ans_text), cards_list, action_buttons, step_descriptions, preview_card)
        whole = merge([*before, rest, *after])
        ans_text, cards_list, action_buttons, step_descriptions = whole.text, whole.cards, whole.actions, whole.steps
        preview_card, target_cards = whole.preview_card, [*preview_cards(before), *target_cards, *preview_cards(after)]
        suggested_action = action_buttons[0].label if action_buttons else None

    return _finish_agent_response(
        engine=engine,
        conv_id=conv_id,
        req=req,
        ans_text=ans_text,
        case_refs=case_refs,
        suggested_action=suggested_action,
        action_buttons=action_buttons,
        step_descriptions=step_descriptions,
        preview_card=preview_card,
        cards_list=cards_list,
        pipeline_stage=pipeline_stage,
        fallback_reason=fallback_reason,
        suggestions=suggestions,
        now=now,
        briefs=briefs,
        preview_cards=target_cards,
        turn_id=turn_id,
        sources=sources,
    )


@router.get("/conversations", response_model=ConversationListResponse, summary="List Super Agent Conversation Threads")
def list_conversations(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> ConversationListResponse:
    with Session(engine) as session:
        company_id = principal.company_id

        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)

        convs = list(
            session.scalars(
                select(AgentConversation)
                .where(
                    AgentConversation.company_id == company_id,
                    AgentConversation.owner_id == principal.owner_id,
                    AgentConversation.hidden_at.is_(None),
                )
                .order_by(AgentConversation.pinned.desc(), AgentConversation.last_turn_at.desc())
                .limit(50)
            ).all()
        )

        items = []
        for c in convs:
            t_at = c.last_turn_at if c.last_turn_at.tzinfo else c.last_turn_at.replace(tzinfo=UTC)
            if t_at >= today_start:
                bucket = "Today"
            elif t_at >= yesterday_start:
                bucket = "Yesterday"
            else:
                bucket = "Earlier"

            snippet = c.summary or ""
            if not snippet:
                last_turn = session.scalars(
                    select(AgentTurn)
                    .where(AgentTurn.conversation_id == c.id, AgentTurn.answer.is_not(None))
                    .order_by(AgentTurn.created_at.desc())
                    .limit(1)
                ).first()
                if last_turn and last_turn.answer:
                    clean = re.sub(r"[#*`]", "", last_turn.answer).strip().splitlines()[0]
                    snippet = clean[:80]

            items.append(
                ConversationSummaryItem(
                    id=str(c.id),
                    title=c.title or "Conversation",
                    last_turn_at=c.last_turn_at.isoformat(),
                    snippet=snippet or "No messages yet",
                    pinned=bool(c.pinned),
                    time_bucket=bucket,
                )
            )
        return ConversationListResponse(conversations=items)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
    summary="Replay Stored Conversation Turns",
)
def get_conversation_detail(
    conversation_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> ConversationDetailResponse:
    with Session(engine) as session:
        try:
            cid = UUID(conversation_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid conversation UUID") from None

        conv = _owned_conversation(session, principal, cid)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        turns_db = list(
            session.scalars(
                select(AgentTurn).where(AgentTurn.conversation_id == cid).order_by(AgentTurn.created_at.asc())
            ).all()
        )

        replay_items = []
        for t in turns_db:
            res_dict: dict[str, Any] = t.results if isinstance(t.results, dict) else {}
            sender = "assistant" if t.answer else "user"
            text = t.answer if t.answer else t.text
            cards_raw = res_dict.get("cards") or []
            preview_raw = res_dict.get("previewCard")
            preview_cards_raw = res_dict.get("previewCards") or ([preview_raw] if preview_raw else [])
            actions_raw = res_dict.get("actions") or []
            steps_raw = res_dict.get("steps") or []
            prompts_raw = res_dict.get("suggestedPrompts") or []

            replay_items.append(
                TurnReplayItem(
                    id=str(t.id),
                    sender=sender,
                    text=text or "",
                    timestamp=to_local(t.created_at).strftime("%H:%M") if t.created_at else "",
                    steps=steps_raw,
                    previewCard=PreviewCardData.model_validate(preview_raw) if preview_raw else None,
                    previewCards=[PreviewCardData.model_validate(pc) for pc in preview_cards_raw if pc],
                    cards=[AssistantCardData.model_validate(card_it) for card_it in cards_raw] if cards_raw else [],
                    actions=[ActionButtonData.model_validate(act_it) for act_it in actions_raw] if actions_raw else [],
                    suggestedPrompts=prompts_raw,
                )
            )

        return ConversationDetailResponse(
            id=str(conv.id),
            title=conv.title or "Conversation",
            pinned=bool(conv.pinned),
            last_turn_at=conv.last_turn_at.isoformat(),
            focus_state=conv.focus_state or {},
            turns=replay_items,
        )


@router.patch("/conversations/{conversation_id}", summary="Rename, Pin or Hide Thread")
def update_conversation(
    conversation_id: str,
    req: UpdateConversationRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    with Session(engine) as session:
        try:
            cid = UUID(conversation_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid conversation UUID") from None

        conv = _owned_conversation(session, principal, cid)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if req.title is not None:
            conv.title = req.title.strip()
        if req.pinned is not None:
            conv.pinned = req.pinned
        if req.hidden is True:
            conv.hidden_at = datetime.now(UTC)
        elif req.hidden is False:
            conv.hidden_at = None

        session.commit()
        return {
            "ok": True,
            "id": str(conv.id),
            "title": conv.title,
            "pinned": conv.pinned,
            "hidden": bool(conv.hidden_at),
        }
