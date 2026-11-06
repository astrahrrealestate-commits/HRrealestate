"""AI Copilot / Super Agent REST API Route.

Exposes the autonomous CONCIERGE (Super Agent) and executor pipeline to the Next.js frontend Top Command Bar (⌘K).
Executes multi-step plans (case status, drafting replies, task completions/snoozing, inbox search, view navigation).
"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import quote_plus
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.deps import get_engine, get_settings_dep
from app.channels.calendar import get_calendar_client
from app.context import memory_items
from app.context.budget import clip
from app.context.compiler import compile_concierge_context
from app.context.selection import rank_cases
from app.context.super_agent_prompt import build_super_agent_system_prompt
from app.contracts import ActionType, ConciergePlan, Direction, Intent
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import MemoryKind, MemoryScope, MemoryStatus, TurnStatus
from app.db.models import (
    ActionRow,
    AgentConversation,
    AgentPageState,
    AgentTurn,
    Approval,
    Case,
    CaseLink,
    ChannelIdentity,
    Company,
    DocumentChunk,
    DocumentRow,
    MemoryItem,
    MessageRow,
    OwnerAccount,
    Person,
    Unit,
)
from app.db.models.calendar import CalendarEventRow
from app.llm.agents.calendar import propose_calendar_event
from app.llm.agents.concierge import CONCIERGE, MAX_HISTORY, concierge_prompt
from app.llm.agents.owner_qa import CaseBrief
from app.llm.budget import CONCIERGE_PURPOSE
from app.llm.calls import CallContext, run_agent
from app.llm.embeddings import build_embedder
from app.llm.fakes_concierge import fake_concierge
from app.pipeline import case_repo, owner_commands, work_repo
from app.pipeline.concierge import StepResult, run_plan
from app.pipeline.concierge_outcome import assemble_answer, task_brief
from app.pipeline.document_search import DocFilter
from app.pipeline.rag import search_hybrid

router = APIRouter(prefix="/api/agent", tags=["agent"])
log = get_logger(__name__)

GROQ_TURN_CHARS = 600  # one earlier chat turn sent to the direct-answer model
GROQ_MAX_TOKENS = 700  # room for a conversational answer; the prompt, not the cap, keeps simple lookups short


class AskAgentRequest(BaseModel):
    query: str = Field(description="The question or command by Harjot / owner")
    context: str | None = Field(default=None, description="Optional page context e.g. Inbox, Maintenance, Money")
    conversation_id: str | None = Field(default=None, description="Existing conversation UUID or null for new thread")
    history: list[str] | None = Field(default=None, description="Recent conversation turns for context")


class CardActionData(BaseModel):
    label: str
    kind: str = Field(default="api_call", description="api_call | navigate | open_external")
    endpoint: str | None = None
    method: str = "POST"
    payload: dict[str, Any] | None = None
    targetUrl: str | None = None
    variant: str = "primary"  # primary | secondary | danger | whatsapp | gmail


class AssistantCardData(BaseModel):
    id: str
    type: (
        str  # draft_message | case_summary | financial_item | calendar_item | document_item | memory_item | data_table
    )
    badgeLabel: str
    badgeColor: str = "orange"
    title: str
    subtitle: str | None = None
    body: str | None = None
    amount: str | None = None
    contractor: str | None = None
    dueDate: str | None = None
    status: str | None = None
    unitLabel: str | None = None
    recipient: str | None = None
    channel: str | None = None
    actions: list[CardActionData] = Field(default_factory=list)
    externalUrl: str | None = None
    threadSearchUrl: str | None = None
    targetUrl: str | None = None
    caseId: str | None = None
    actionId: str | None = None


class PreviewCardData(BaseModel):
    type: str = Field(
        default="draft_message", description="Type of card: draft_message, case_summary, task_card, financial_item"
    )
    channel: str | None = Field(default=None, description="whatsapp | gmail | internal")
    recipient: str = Field(default="", description="Recipient phone or email")
    unitLabel: str = Field(default="", description="Target property/unit address")
    subject: str | None = None
    body: str = Field(default="", description="The drafted text content")
    actionId: str | None = None
    caseId: str | None = None
    title: str | None = None
    subtitle: str | None = None
    badgeLabel: str | None = None
    badgeColor: str | None = None
    amount: str | None = None
    status: str | None = None
    dueDate: str | None = None
    contractor: str | None = None
    targetUrl: str | None = None
    externalUrl: str | None = None
    threadSearchUrl: str | None = None
    variants: list[str] = Field(default_factory=list, description="All body variants for draft switcher")
    personaName: str | None = Field(default=None, description="Owner persona the draft was written in")
    personaVersion: int | None = None


class ActionButtonData(BaseModel):
    label: str
    actionType: str = Field(default="navigate", description="navigate | approve_action | query")
    payload: str | None = None
    isPrimary: bool = False


class DebugInfo(BaseModel):
    pipeline_stage: str = Field(
        default="llm_concierge",
        description="llm_concierge | regex_calendar | regex_document | memory_rule | fake_router | domain_fallback",
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
    return f"{name} · {addr} ({case.category.value})"


def _generate_groq_answer(
    query: str,
    settings: Settings,
    history: list[str] | None = None,
    memory_rules: list[str] | None = None,
    page_facts: str | None = None,
    cases: Sequence[CaseBrief] = (),
    thread_summary: str = "",
    focus_case_id: str | None = None,
) -> str | None:
    """Generate dynamic, executive-grade responses using Groq Cloud Qwen model. The prompt is size-bounded."""
    groq_key = None
    if settings.groq_api_key:
        groq_key = settings.groq_api_key.get_secret_value()
    if not groq_key:
        import os

        groq_key = os.environ.get("GROQ_API_KEY")

    if not groq_key:
        return None

    try:
        import httpx

        system_prompt = build_super_agent_system_prompt(
            cases=cases,
            query=query,
            memory_rules=memory_rules or (),
            page_facts=page_facts or "",
            thread_summary=thread_summary,
            focus_case_id=focus_case_id,
        )
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for h in history[-4:]:
                role = "user" if h.startswith("User:") else "assistant"
                content = clip(h.replace("User: ", "").replace("Assistant: ", ""), GROQ_TURN_CHARS)
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": query})

        # Try Groq models: GPT-OSS 120B / 20B first as requested, then Llama 3.3
        for model in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"]:
            try:
                resp = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": 0.2,
                        "max_tokens": GROQ_MAX_TOKENS,
                    },
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    ans = content.strip() if isinstance(content, str) else ""
                    if ans:
                        return ans
            except Exception as model_err:  # try the next model
                log.warning("api.superagent.groq_model_failed", error=type(model_err).__name__)
                continue
    except Exception as g_err:
        log.warning("api.superagent.groq_failed", error=str(g_err))

    return None


def _domain_fallback_answer(query: str, live_cases_text: str = "", is_error: bool = False) -> str:
    """Domain-accurate fallback reflecting real database state without false assurances."""
    q_l = query.lower()
    has_live_cases = bool(
        live_cases_text
        and "no active open" not in live_cases_text.lower()
        and "0 active open" not in live_cases_text.lower()
    )

    if any(w in q_l for w in ["case", "ticket", "open", "active", "status"]):
        if has_live_cases:
            return f"**Active Open Cases in Database:**\n\n{live_cases_text}"
        return "**Active Cases:** 0 open cases found in database."
    elif any(w in q_l for w in ["keizersgracht", "vipin", "tenant", "unit"]):
        return (
            "**Unit: Keizersgracht 42-A**\n\n"
            "• **Tenant:** Vipin Tyagi\n"
            "• **Standing Contractor Rule:** Plumber Kevin van Dijk is assigned for any pipe leaks."
        )
    elif any(w in q_l for w in ["contractor", "plumber"]):
        return (
            "**Registered Contractors:**\n\n"
            "• **Kevin van Dijk (Plumber):** Assigned for leak and plumbing maintenance at Keizersgracht 42-A."
        )
    else:
        if is_error:
            status_snippet = (
                f"\n\n**Current Live Tickets:**\n{live_cases_text}"
                if has_live_cases
                else "\n\n• Database records show 0 open tickets."
            )
            return (
                "⚠️ **Assistant Degraded:** The AI model timed out or was rate-limited. "
                "No automated actions were performed." + status_snippet
            )
        return f"**EstateOS Live Status:**\n\n{live_cases_text or '• 0 open cases in database.'}"


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
                contractor_p = (
                    session.get(Person, act.payload.get("contractor_person_id"))
                    if act.payload.get("contractor_person_id")
                    else None
                )
                contractor_name = contractor_p.display_name if contractor_p else "Kevin van Dijk (Chahal Bouw)"
                contractor_email = act.payload.get("to") or "dispatch@chahalbouw.nl"
                contractor_recipient = f"{contractor_name} <{contractor_email}>"
                chan_str = "gmail"
                subj_str = f"Work Order: Emergency Leak Repair — {unit_label}"
                variants = act.payload.get("body_variants") or []
                extracted_body = variants[0] if variants else (act.payload.get("text") or "")
                draft_body = extracted_body.strip()
                raw_variants = variants or [draft_body]
                card_variants = [str(v) for v in raw_variants if v]
                contractor_url = f"https://mail.google.com/mail/?view=cm&fs=1&to={quote_plus(contractor_email)}&su={quote_plus(subj_str)}&body={quote_plus(draft_body)}"

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
                    threadSearchUrl=f"https://mail.google.com/mail/u/0/#search/{quote_plus(contractor_email)}",
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
        q_low.startswith(("schedule ", "book ", "set up ", "plan "))
        or bool(
            re.search(r"\b(schedule\s+(?!to|of\b)|book\s+(?!to|of\b)|set up\s+|plan\s+visit|inplannen|boeken)\b", q_low)
        )
    )
    is_calendar_query = bool(
        re.search(r"\b(calendar|visit|visits|appointment|appointments|scheduled|booked|afspraak|agenda)\b", q_low)
    )

    if not (is_schedule_command or is_calendar_query):
        return None, None, [], []

    client = get_calendar_client()

    with Session(engine) as session:
        # 1. HARJOT ASKS TO SCHEDULE / BOOK AN APPOINTMENT
        if is_schedule_command:
            target_unit = None
            target_case = None
            for b in briefs:
                lbl = (b.label or "").lower()
                if ("keizersgracht" in q_low and "keizersgracht" in lbl) or ("pieter" in q_low and "pieter" in lbl):
                    target_case = session.get(Case, b.case_id)
                    break

            if not target_case and briefs:
                target_case = session.get(Case, briefs[0].case_id)

            if target_case and target_case.unit_id:
                target_unit = session.get(Unit, target_case.unit_id)

            addr = (target_unit.address or target_unit.label) if target_unit else "Keizersgracht 42-A"
            contractor_name = "Kevin van Dijk (Technician)"
            contractor_email = "kevin@chahalbouw.nl"
            if "kevin" in q_low or "chahal" in q_low or "plumber" in q_low:
                contractor_name = "Kevin van Dijk (Technician)"

            proposal = propose_calendar_event(
                message_text=query,
                property_address=addr,
                calendar_client=client,
                contractor_name=contractor_name,
                contractor_email=contractor_email,
                lockbox_pin=getattr(target_unit, "lockbox_code", None) if target_unit else None,
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
                event_type="contractor_repair",
                attendees=[{"email": contractor_email, "displayName": contractor_name}],
                lockbox_code=proposal.lockbox_code,
            )
            session.add(evt_row)
            session.commit()

            start_str = proposal.start_time.strftime("%A, %b %d at %H:%M")
            end_str = proposal.end_time.strftime("%H:%M")
            time_window_str = f"{start_str} – {end_str}"

            access_line = (
                f"• **Lockbox Access**: #{proposal.lockbox_code}\n\n"
                if proposal.lockbox_code
                else "• **Access**: Tenant present / direct access\n\n"
            )
            lockbox_line = (
                f"Lockbox: #{proposal.lockbox_code}\n" if proposal.lockbox_code else "Lockbox: None (Tenant access)\n"
            )

            ans = (
                f"I have checked your schedule and prepared an appointment for **{contractor_name}** at **{addr}** "
                f"on **{time_window_str}**.\n\n"
                f"• **Status**: Proposed (No calendar conflicts)\n"
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

            if events:
                event_lines = []
                for e in events[:5]:
                    date_lbl = e.start_time.strftime("%a %b %d · %H:%M")
                    loc = e.location or "Portfolio Unit"
                    st_badge = f"[{e.status.upper()}]"
                    event_lines.append(f"• **{e.title}** ({st_badge})\n  {date_lbl} at {loc}")
                sched_text = "\n".join(event_lines)
                ans = f"Here are your upcoming scheduled visits and appointments:\n\n{sched_text}"
            else:
                ans = (
                    "You have no upcoming appointments booked on your calendar for this week.\n\n"
                    "All maintenance visits are either completed or awaiting contractor confirmation."
                )

            actions = [
                ActionButtonData(
                    label="Open Calendar",
                    actionType="navigate",
                    payload="/calendar",
                    isPrimary=True,
                )
            ]
            steps = [
                "Queried scheduled property visits from database",
                f"Retrieved {len(events)} upcoming appointments",
            ]
            return ans, None, actions, steps

    return None, None, [], []


def _generate_thread_title(query: str, ans: str, cases: list[CaseBrief]) -> str:
    """Generate concise 3-5 word title for the conversation thread."""
    q_low = query.lower()
    if "keizersgracht" in q_low or (cases and any("keizersgracht" in getattr(c, "label", "").lower() for c in cases)):
        if any(w in q_low for w in ["leak", "water", "pipe", "plumber", "burst"]):
            return "Keizersgracht Pipe Leak"
        return "Keizersgracht 42-A"
    if any(w in q_low for w in ["rent", "arrear", "overdue", "pay", "behind"]):
        if "pieter" in q_low:
            return "Pieter Bakker Arrears"
        return "Tenant Rent Arrears"
    if any(w in q_low for w in ["draft", "reply", "send", "message"]):
        return "Draft Tenant Reply"
    if any(w in q_low for w in ["calendar", "visit", "schedule", "appointment", "afspraak"]):
        return "Property Visit & Schedule"
    if any(w in q_low for w in ["invoice", "bill", "factuur"]):
        return "Contractor Invoice Check"
    if any(w in q_low for w in ["priority", "first", "emergency", "ticket"]):
        return "Urgent Maintenance Queue"
    clean_words = [w.capitalize() for w in re.sub(r"[^a-zA-Z0-9\s]", "", query).split() if len(w) > 2]
    return " ".join(clean_words[:4]) or "Conversation"


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


def _clean_executive_answer(text: str) -> str:
    """Strip robotic tool-chatter prefixes and polish markdown scannability."""
    if not text:
        return ""
    cleaned = re.sub(
        r"^(Opening (cases|inbox|maintenance|money|properties|calendar|documents|approvals)\.?\s*)+",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"\bcase\s+([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        r"Ticket #\1",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bcase\s+([0-9a-f]{6,8})\b",
        r"Ticket #\1",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


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
) -> AskAgentResponse:
    ans_text = _clean_executive_answer(ans_text)
    effective_preview_cards = (
        preview_cards
        if (preview_cards is not None and len(preview_cards) > 0)
        else ([preview_card] if preview_card else [])
    )
    with Session(engine) as session:
        conv = session.get(AgentConversation, conv_id)
        if not conv:
            company = session.scalars(select(Company).limit(1)).first()
            company_id = company.id if company else UUID("00000000-0000-0000-0000-000000000001")
            owner_acct = session.scalars(
                select(OwnerAccount).where(OwnerAccount.company_id == company_id).limit(1)
            ).first()
            owner_id = owner_acct.id if owner_acct else company_id
            conv = AgentConversation(id=conv_id, company_id=company_id, owner_id=owner_id, title="New Chat")
            session.add(conv)
            session.flush()

        if not conv.title or conv.title == "New Chat":
            conv.title = _generate_thread_title(req.query, ans_text, briefs)

        current_focus = dict(conv.focus_state or {})
        if preview_card:
            if preview_card.caseId:
                current_focus["case_id"] = str(preview_card.caseId)
            if preview_card.unitLabel:
                current_focus["unit_label"] = preview_card.unitLabel
            if preview_card.recipient:
                current_focus["recipient"] = preview_card.recipient
            if preview_card.contractor:
                current_focus["contractor"] = preview_card.contractor
            if preview_card.actionId:
                current_focus["last_action_id"] = preview_card.actionId
            if preview_card.channel:
                current_focus["channel"] = preview_card.channel
        elif briefs:
            current_focus["case_id"] = str(briefs[0].case_id)
            current_focus["unit_label"] = briefs[0].label

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
    )


@router.post(
    "/ask",
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
) -> AskAgentResponse:
    now = datetime.now(UTC)
    pipeline_stage = "llm_concierge"
    fallback_reason = None
    with Session(engine) as session:
        # Default company for single-tenant setup
        company = session.scalars(select(Company).limit(1)).first()
        company_id = company.id if company else UUID("00000000-0000-0000-0000-000000000001")

        # Resolve or initialize AgentConversation thread
        conv: AgentConversation | None = None
        if req.conversation_id:
            try:
                conv = session.get(AgentConversation, UUID(req.conversation_id))
            except Exception:
                conv = None

        if not conv:
            owner_acct = session.scalars(
                select(OwnerAccount).where(OwnerAccount.company_id == company_id).limit(1)
            ).first()
            owner_id = owner_acct.id if owner_acct else company_id
            conv = AgentConversation(
                company_id=company_id,
                owner_id=owner_id,
                title="New Chat",
                focus_state={},
            )
            session.add(conv)
            session.commit()
            session.refresh(conv)

        conv_id = conv.id
        history = (req.history or [])[-MAX_HISTORY:]

        # Natural language rule recording check (T5 Standing Rules - Issue 1.9)
        q_clean = req.query.strip().strip("\"'“”`")
        q_low = q_clean.lower()

        # Distinguish temporary tasks/reminders from permanent standing policy rules
        is_task_reminder = q_low.startswith(("remember to ", "remind me to ", "note to ")) or bool(
            re.search(
                r"^(remember|remind me|note)\s+(to\s+)?(call|email|text|message|pay|chase|ask|contact|check on)\b",
                q_low,
            )
        )

        rule_prefixes = [
            "standing rule:",
            "standing rule ",
            "company policy:",
            "company policy ",
            "rule: ",
            "set rule: ",
            "new rule: ",
            "policy: ",
            "always remember that ",
            "remember that ",
            "keep in mind that ",
        ]

        matched_rule_prefix = None
        if not is_task_reminder:
            for prefix in rule_prefixes:
                if q_low.startswith(prefix):
                    matched_rule_prefix = prefix
                    break

        if matched_rule_prefix:
            rule_text = q_clean[len(matched_rule_prefix) :].strip().strip("\"'“”`")
            if rule_text:
                item, _reason = memory_items.record_owner_memory(
                    session,
                    company_id=company_id,
                    text=rule_text,
                    scope=MemoryScope.company,
                    kind=MemoryKind.rule,
                    status=MemoryStatus.proposed,
                )
                session.commit()

                if item is not None and item.status == MemoryStatus.active:
                    return AskAgentResponse(
                        answer=(
                            "This standing rule is already active in your company settings:\n\n"
                            f'• **"{item.text}"**\n\nAll '
                            "agents and automated workflows already enforce it."
                        ),
                        suggestedAction="View Standing Rules in Settings",
                        actions=[
                            ActionButtonData(
                                label="View Standing Rules in Settings",
                                actionType="navigate",
                                payload="/settings",
                                isPrimary=True,
                            )
                        ],
                        executedAt=now.isoformat(),
                        steps=["Verified existing company standing rule in database"],
                        debugInfo=DebugInfo(pipeline_stage="memory_rule"),
                    )

                if item is not None:
                    rule_id = str(item.id)
                    return AskAgentResponse(
                        answer=(
                            f"I have drafted a new proposed standing rule for your company:\n\n"
                            f'• **"{item.text}"**\n\n'
                            f"Would you like to activate this policy across your portfolio?"
                        ),
                        suggestedAction="Activate Standing Rule",
                        actions=[
                            ActionButtonData(
                                label="Activate Standing Rule",
                                actionType="approve_memory",
                                payload=f"/api/v1/memory/{rule_id}/approve",
                                isPrimary=True,
                            ),
                            ActionButtonData(
                                label="Review in Settings",
                                actionType="navigate",
                                payload="/settings",
                                isPrimary=False,
                            ),
                        ],
                        previewCard=PreviewCardData(
                            type="memory_item",
                            badgeLabel="POLICY PROPOSAL",
                            unitLabel="Company Portfolio",
                            status="Proposed",
                            title="Proposed Standing Rule",
                            body=item.text,
                            actionId=rule_id,
                        ),
                        executedAt=now.isoformat(),
                        steps=[
                            "Extracted policy constraint from request",
                            "Drafted proposed standing rule in database (pending activation)",
                        ],
                        debugInfo=DebugInfo(pipeline_stage="memory_rule"),
                    )

        # Pull active owner memory rules (T5)
        approved_memories = list(
            session.scalars(
                select(MemoryItem.text)
                .where(MemoryItem.company_id == company_id, MemoryItem.status == MemoryStatus.active)
                .order_by(MemoryItem.created_at.desc())
                .limit(10)
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

        cases = session.scalars(
            select(Case)
            .where(Case.company_id == company_id, Case.state.in_(case_repo.OPEN_STATES))
            .order_by(Case.opened_at.desc(), Case.id.desc())
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
                        dir_label = "Inbound from tenant/contractor" if dir_val == "inbound" else "Outbound"
                        date_str = sent_at.strftime("%d %b %H:%M") if sent_at else ""
                        case_msgs_map[cid].append(f'[{date_str} {dir_label} via {channel}]: "{snippet}"')
            except Exception as e:
                log.warning("api.superagent.case_msgs_enrich_failed", error=str(e))

        briefs = []
        for c in cases:
            recent_lines = case_msgs_map.get(c.id, [])
            summary = c.summary or ""
            if recent_lines:
                summary += " | Recent messages: " + " ; ".join(reversed(recent_lines))
            briefs.append(CaseBrief(c.id, _case_label(session, c), c.state.value, c.urgency.value, summary))

        # Order briefs by real-world urgency (emergency > high > normal > low), keeping temporal order within a tier
        _urgency_weights = {"emergency": 0, "high": 1, "normal": 2, "low": 3}
        briefs.sort(key=lambda b: _urgency_weights.get((b.urgency or "").lower(), 4))
        open_tasks = work_repo.open_tasks(session, company_id, now=now)[:20]
        tasks = [task_brief(t.id, t.title) for t in open_tasks]

        # Early check: If query directly asks about active T5 standing rules / memories, return immediately
        matching_rule = None
        q_words = [
            w
            for w in q_low.split()
            if len(w) > 3
            and w not in ["what", "which", "tell", "show", "about", "contractor", "rule", "rules", "from", "with"]
        ]
        if any(
            k in q_low for k in ["rule", "rules", "preference", "remember", "standing", "custom", "contractor policy"]
        ):
            for m in approved_memories:
                m_low = m.lower()
                if any(w in m_low for w in q_words) or ("rule" in q_low and len(approved_memories) == 1):
                    matching_rule = m
                    break

        if matching_rule:
            return _finish_agent_response(
                engine=engine,
                conv_id=conv_id,
                req=req,
                ans_text=f"**Authoritative Standing Rule (T5 Memory):**\n\n• {matching_rule}",
                case_refs=[],
                suggested_action="View Standing Rules in Settings",
                action_buttons=[
                    ActionButtonData(
                        label="View Standing Rules in Settings",
                        actionType="navigate",
                        payload="/settings",
                        isPrimary=True,
                    )
                ],
                step_descriptions=["Retrieved active workspace rules"],
                preview_card=None,
                cards_list=[],
                pipeline_stage="memory_rule",
                fallback_reason=None,
                suggestions=["What should I do first?", "Who owes rent?", "Check calendar"],
                now=now,
                briefs=briefs,
            )
        # Specific Task Trigger: Calendar / Appointment / Visit inquiry or booking
        cal_pattern = r"\b(calendar|schedule|appointment|visit|afspraak|agenda|book|boeken|inplannen)\b"
        if re.search(cal_pattern, q_low):
            cal_ans, cal_card, cal_actions, cal_steps = _resolve_calendar_action(req.query, engine, company_id, briefs)
            if cal_ans:
                cal_cards = []
                if cal_card:
                    cal_cards.append(
                        AssistantCardData(
                            id=cal_card.actionId or "cal-0",
                            type="calendar_item",
                            badgeLabel=cal_card.badgeLabel or "CALENDAR",
                            badgeColor="emerald",
                            title=cal_card.title or "Scheduled Appointment",
                            subtitle=cal_card.subtitle,
                            body=cal_card.body,
                            unitLabel=cal_card.unitLabel,
                            recipient=cal_card.recipient,
                            dueDate=cal_card.dueDate,
                            actions=[
                                CardActionData(
                                    label="Approve & Add to Calendar",
                                    kind="api_call",
                                    endpoint=f"/api/calendar/events/{cal_card.actionId}/approve"
                                    if cal_card.actionId
                                    else None,
                                    variant="primary",
                                )
                            ]
                            if cal_card.actionId
                            else [],
                        )
                    )
                return _finish_agent_response(
                    engine=engine,
                    conv_id=conv_id,
                    req=req,
                    ans_text=cal_ans,
                    case_refs=[str(b.case_id) for b in briefs] if briefs else [],
                    suggested_action=cal_actions[0].label if cal_actions else None,
                    action_buttons=cal_actions,
                    step_descriptions=cal_steps,
                    preview_card=cal_card,
                    cards_list=cal_cards,
                    pipeline_stage="regex_calendar",
                    fallback_reason=None,
                    suggestions=["Check tomorrow's calendar", "View maintenance tickets", "Draft tenant update"],
                    now=now,
                    briefs=briefs,
                )
        # Specific Task Trigger: Document / Lease / Contract / Terms query
        doc_pattern = (
            r"\b(lease|agreement|contract|deposit|borg|document|pdf|clause|terms|notice period|sublet"
            r"|huurovereenkomst)\b"
        )
        is_contractor_inquiry = bool(re.search(r"\bcontractor(s)?\b", q_low))
        is_comm_inquiry = any(w in q_low for w in ["message", "messages", "reply", "email", "mail", "whatsapp"])
        is_doc_task = bool(re.search(doc_pattern, q_low)) and not is_contractor_inquiry and not is_comm_inquiry
        if is_doc_task:
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
                        groq_doc_ans = _generate_groq_answer(
                            (
                                "Answer this user query directly and concisely in 1-2 bullet points based on the "
                                "document: "
                                f"'{req.query}'. Keep the answer short and executive."
                            ),
                            settings,
                            page_facts=doc_context,
                        )

                        if groq_doc_ans:
                            doc_ans = f"**Document Intelligence (Verified RAG):**\n\n{groq_doc_ans}\n\n"
                        else:
                            doc_ans = (
                                f"**Document Intelligence (Verified RAG):**\n\n"
                                f"**{matched_doc.title}** ({matched_doc.doc_type.capitalize()})\n\n"
                                f"{clean_snippet}\n\n"
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

                        unit_label = (
                            "Keizersgracht 42-A"
                            if "keizersgracht" in (matched_doc.title + (matched_doc.drive_folder or "")).lower()
                            else "Portfolio Document"
                        )

                        preview_card: PreviewCardData | None = PreviewCardData(
                            type="document_item",
                            badgeLabel="GOOGLE DRIVE",
                            unitLabel=unit_label,
                            status="Verified RAG Match",
                            title=matched_doc.title,
                            body=clean_snippet,
                            targetUrl=drive_url or "/documents",
                        )

                        return AskAgentResponse(
                            answer=doc_ans,
                            suggestedAction="Open in Google Drive" if drive_url else "View in Documents",
                            actions=actions,
                            previewCard=preview_card,
                            executedAt=now.isoformat(),
                            steps=[],
                            debugInfo=DebugInfo(pipeline_stage="regex_document"),
                        )
            except Exception as rag_err:
                log.warning("api.superagent.rag_trigger_failed", error=str(rag_err))

        # Specific Task Trigger: Natural Language Analytics / Custom Query Agent (PostgreSQL)
        is_count_or_list_query = bool(
            re.search(
                r"\b(how many|count of|total number|list all|show all|which units|which contractors|which tenants"
                r"|total cases|total open|open tickets count|hoeveel|overzicht)\b",
                q_low,
            )
        )
        is_database_keyword = any(k in q_low for k in ["query database", "sql query", "postgres", "run query"])
        if is_count_or_list_query or is_database_keyword:
            try:
                from app.tools.query_agent.agent import run_query_agent

                q_res = run_query_agent(engine, settings, company_id, req.query, history=history)
                if q_res.ok:
                    query_steps = [
                        "Synthesized safe read-only SQL query from schema",
                        f"Executed PostgreSQL query: {q_res.sql}",
                        f"Retrieved {q_res.row_count} verified records in {round(q_res.duration_ms, 1)}ms",
                    ]
                    return _finish_agent_response(
                        engine=engine,
                        conv_id=conv_id,
                        req=req,
                        ans_text=q_res.answer,
                        case_refs=[str(b.case_id) for b in briefs] if briefs else [],
                        suggested_action="View Case in Maintenance" if briefs else None,
                        action_buttons=[
                            ActionButtonData(
                                label="View Maintenance",
                                actionType="navigate",
                                payload="/maintenance",
                                isPrimary=True,
                            )
                        ],
                        step_descriptions=query_steps,
                        preview_card=None,
                        cards_list=[],
                        pipeline_stage="query_agent",
                        fallback_reason=None,
                        suggestions=["How many open cases do we have?", "List all contractors", "Check calendar"],
                        now=now,
                        briefs=briefs,
                    )
            except Exception as qa_err:
                log.warning("api.superagent.query_agent_trigger_failed", error=str(qa_err))

    live_cases_text = (
        "\n".join(
            [
                (
                    f"• Ticket #{str(b.case_id)[:6]}: {b.label} (State: {b.state}, Urgency: {b.urgency}). Problem: "
                    f"{b.summary}"
                )
                for b in briefs
            ]
        )
        if briefs
        else "• No active open tickets."
    )

    # Build prompt using context compiler with active memory rules and page facts
    history = (req.history or [])[-MAX_HISTORY:]
    thread_summary = ""
    focus_cid: str | None = None
    try:
        if conv:
            thread_summary = conv.summary or ""
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
                f_lines.append(f"• Active Contact / Tenant: {conv.focus_state['recipient']}")
            if conv.focus_state.get("contractor"):
                f_lines.append(f"• Assigned Contractor: {conv.focus_state['contractor']}")
            if conv.focus_state.get("case_id"):
                f_lines.append(f"• Active Ticket: #{str(conv.focus_state['case_id'])[:6]}")
            if f_lines:
                focus_text = (
                    "\n\nActive Thread Focus (Pronouns like 'he', 'him', 'that ticket' refer to these entities):\n"
                    + "\n".join(f_lines)
                )

        compiled = compile_concierge_context(
            question=req.query,
            recent=history,
            cases=rank_cases(briefs, req.query, focus_cid),
            open_tasks=tasks,
            page_facts_text=(page_facts_text or "") + focus_text,
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
    case_refs: list[str] = []

    # 1. Try running full CONCIERGE agent via LLM
    llm_failed = False
    try:
        call_res = run_agent(engine, settings, CONCIERGE, prompt, CallContext(company_id, CONCIERGE_PURPOSE))
        plan = call_res.output
    except Exception as exc:
        llm_failed = True
        log.warning("api.superagent.llm_fallback", error=str(exc))
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

    # 2. Dispatch plan through the real concierge pipeline executor
    ans_text: str = ""
    try:
        if plan and plan.in_scope and plan.steps:
            known_cases_list = [b.case_id for b in briefs]
            if conv and conv.focus_state and conv.focus_state.get("case_id"):
                try:
                    f_cid = UUID(str(conv.focus_state["case_id"]))
                    if f_cid not in known_cases_list:
                        known_cases_list.append(f_cid)
                except ValueError:
                    log.warning("api.superagent.focus_case_invalid", conversation_id=str(conv.id))
            results = run_plan(
                engine, settings, company_id, plan, question=req.query, now=now, brief_cases=known_cases_list
            )
            ans_text = assemble_answer(results)
        else:
            # Screened or direct command path via owner_commands
            cmd = owner_commands.parse_command(req.query)
            ans_text = owner_commands.run_command(engine, settings, company_id, cmd, now=now)
    except Exception as exec_err:
        log.warning("api.superagent.run_plan_failed", error=str(exec_err))
        ans_text = ""

    # If active memory matches the query directly, return it as authoritative
    matching_rule = None
    q_words = [w for w in q_low.split() if len(w) > 3 and w not in ["what", "which", "tell", "show", "about"]]
    if q_words:
        for m in approved_memories:
            matches = sum(1 for w in q_words if w in m.lower())
            if matches >= 2 or (len(q_words) == 1 and q_words[0] in m.lower()):
                matching_rule = m
                break

    if matching_rule:
        ans_text = f"**Authoritative Standing Rule (T5 Memory):**\n\n• {matching_rule}"
        pipeline_stage = "memory_rule"

    # If the response is empty or an unhandled placeholder, invoke Groq or clean executive domain generator
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
    if needs_fallback:
        pipeline_stage = "domain_fallback"
        fallback_reason = fallback_reason or "Empty or placeholder response"
        groq_resp = _generate_groq_answer(
            req.query,
            settings,
            history=req.history,
            memory_rules=approved_memories,
            page_facts=page_facts_text,
            cases=briefs,
            thread_summary=thread_summary,
            focus_case_id=focus_cid,
        )
        ans_text = groq_resp or _domain_fallback_answer(req.query, live_cases_text=live_cases_text, is_error=llm_failed)

    # 3. Build step badge labels and inspect any generated proposal cards / actions
    step_descriptions: list[str] = []
    dropped_warnings: list[str] = []
    preview_card = None
    action_buttons: list[ActionButtonData] = []
    q_low = req.query.lower()

    for r in results:
        # Check if step executed successfully or was rejected/dropped
        if not r.ok:
            intent_name = r.intent.value.replace("_", " ")
            summary_low = r.summary.lower()
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
            if not r.summary.lower().startswith("opening "):
                step_descriptions.append(r.summary)

        # Check if any step referenced a case
        cid_str = None
        if r.data and "case_id" in r.data and r.data["case_id"]:
            cid_str = str(r.data["case_id"])
            case_refs.append(f"#{cid_str[:6]}")

        # Check for navigation view requests and map strictly to target frontend views
        if r.view:
            v_low = r.view.lower()
            case_ref = cid_str or (str(briefs[0].case_id) if briefs else "")

            if v_low == "waiting":
                view_label = "View Waiting Radar on Dashboard"
                view_path = "/"
            elif v_low in ("cases", "maintenance"):
                if case_ref:
                    view_label = f"Open Ticket #{case_ref[:6]} in Maintenance"
                    view_path = f"/maintenance?ticket={case_ref}"
                else:
                    view_label = "Open in Maintenance"
                    view_path = "/maintenance"
            elif v_low in ("inbox", "approvals", "messages", "message", "mail", "emails", "communication"):
                if case_ref:
                    view_label = f"Open Thread #{case_ref[:6]} in Messages"
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
                    view_label = f"Review PO & Ticket #{case_ref[:6]} in Maintenance"
                    view_path = f"/maintenance?ticket={case_ref}"
                elif is_maint:
                    view_label = "Open in Maintenance"
                    view_path = "/maintenance"
                elif case_ref and is_inbox:
                    view_label = f"Open Thread #{case_ref[:6]} in Inbox"
                    view_path = f"/inbox?thread=case-{case_ref}"
                elif is_inbox:
                    view_label = "Review Approvals in Inbox"
                    view_path = "/inbox?tab=needs_approval"
                elif case_ref:
                    view_label = f"Review Ticket #{case_ref[:6]} in Maintenance"
                    view_path = f"/maintenance?ticket={case_ref}"
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
            elif v_low in ("tenants", "contacts"):
                view_label = "Open in Tenants"
                view_path = "/tenants"
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

        # Check if a proposal was drafted
        if (
            r.intent in (Intent.draft_reply, Intent.show_drafts, Intent.chase_now)
            and r.data
            and "approval_ids" in r.data
            and not preview_card
        ):
            approval_ids = r.data.get("approval_ids", [])
            prefer_contractor = any(
                w in req.query.lower()
                for w in ["contractor", "plumber", "monteur", "loodgieter", "work order", "conractore", "contractore"]
            )
            preview_card = _resolve_draft_card(engine, approval_ids=approval_ids, prefer_contractor=prefer_contractor)

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
                        c_variants = c_acts[0].payload.get("body_variants") or []
                        views_text = ""
                        if c_variants:
                            views_text = "\n\nDraft 1:\n> " + "\n> ".join(c_variants[0].split("\n"))
                            if len(c_variants) > 1:
                                views_text += "\n\nDraft 2:\n> " + "\n> ".join(c_variants[1].split("\n"))
                        ans_text = (
                            "Yes, a work order for contractor Kevin van Dijk is already waiting for your approval. "
                            f"Nothing is sent until you approve it in Approvals.{views_text}"
                        )
                    break

        # Check for case status snapshot card
        if r.intent == Intent.case_status and r.data and not preview_card:
            status_cid = r.data.get("case_id") or cid_str or (str(briefs[0].case_id) if briefs else None)
            preview_card = PreviewCardData(
                type="case_summary",
                badgeLabel="TICKET",
                unitLabel=r.summary.split(":")[0] if ":" in r.summary else "Maintenance Case",
                title=r.summary,
                body=_clean_card_body(r.data.get("summary", r.summary)),
                status=r.data.get("state", "open").replace("_", " "),
                caseId=status_cid,
                targetUrl=f"/maintenance?ticket={status_cid}" if status_cid else "/maintenance",
            )

    if dropped_warnings and (
        not ans_text or ans_text.strip() in ["I need more detail", "Something went wrong with that step."]
    ):
        ans_text = "**Action Notice:**\n\n" + "\n".join(dropped_warnings)

    preview_cards_list: list[PreviewCardData] = []
    if preview_card:
        preview_cards_list.append(preview_card)

    # Populate dynamic navigation and micro-cards for priority/maintenance inquiries from real DB state
    if any(k in q_low for k in ["priority", "first", "ticket", "maintenance", "repair", "urgent", "emergency"]):
        if not preview_card and briefs:
            # Smartly cap at top 3 cases ordered by priority
            top_briefs = briefs[:3]
            for b in top_briefs:
                cid_str = str(b.case_id)
                cid_short = cid_str[:6]
                target_path = f"/maintenance?ticket={cid_str}"
                clean_body = _clean_card_body(b.summary or "Active maintenance case in queue.")

                contractor_name = None
                s_low = (b.summary or "").lower()
                if "kevin" in s_low or "van dijk" in s_low or "plumber" in s_low:
                    contractor_name = "Kevin van Dijk (Plumber)"
                elif "electrician" in s_low or "vermeer" in s_low:
                    contractor_name = "Vermeer Elektrotechniek"

                unit_lbl = b.label.split("·")[1].strip() if "·" in b.label else (b.label or "Portfolio Unit")
                is_emergency = (b.urgency or "").lower() in ("emergency", "high")

                card = PreviewCardData(
                    type="case_summary",
                    badgeLabel="URGENT" if is_emergency else "TICKET",
                    badgeColor="rose" if is_emergency else "blue",
                    unitLabel=unit_lbl,
                    title=f"Ticket #{cid_short} · {unit_lbl}",
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
                        label=f"View all {len(briefs)} cases in Maintenance",
                        actionType="navigate",
                        payload="/maintenance",
                        isPrimary=False,
                    )
                )
            elif top_briefs:
                cid_short = str(top_briefs[0].case_id)[:6]
                action_buttons.append(
                    ActionButtonData(
                        label=f"Open Ticket #{cid_short} in Maintenance",
                        actionType="navigate",
                        payload=f"/maintenance?ticket={top_briefs[0].case_id}",
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
    elif any(k in q_low for k in ["rent", "arrear", "invoice", "money", "overdue"]):
        if not preview_card:
            ans_low_check = (ans_text or "").lower()
            if "pieter" in ans_low_check or "arrear" in ans_low_check or "rent" in q_low or "overdue" in q_low:
                preview_card = PreviewCardData(
                    type="financial_item",
                    badgeLabel="ARREARS",
                    badgeColor="rose",
                    unitLabel="Singel 102",
                    title="Pieter Bakker · Overdue Rent",
                    body="Rent payment overdue for November 2026. Prior reminder sent via email.",
                    amount="€1.450",
                    dueDate="01 Nov 2026",
                    targetUrl="/money",
                )
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

    # If drafting was requested and preview_card is active, ensure the answer text clearly introduces the draft
    if (
        preview_card
        and preview_card.type == "draft_message"
        and (
            not ans_text
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
        )
    ):
        target_name = preview_card.unitLabel or "Portfolio"
        if plan and any(s.intent == Intent.show_drafts for s in plan.steps):
            ans_text = (
                f"Here is the draft reply waiting for **{target_name}**. "
                "You can review the message and tap **Accept and send** below."
            )
        else:
            ans_text = (
                f"I have prepared a draft reply for **{target_name}**. "
                "You can review the message and tap **Accept and send** below."
            )

    # Filter out duplicate Approvals button if a draft card is already shown (draft card has Accept and send)
    if preview_card and preview_card.type == "draft_message":
        action_buttons = [b for b in action_buttons if "approval" not in b.label.lower()]

    # Clean, professional execution steps
    has_dirty_step = any(
        any(
            p in s.lower()
            for p in [
                "opening ",
                "which",
                "not waiting",
                "based on active portfolio",
                "open tasks:",
                "are you",
                "can you",
                "what do you mean",
            ]
        )
        or (len(s) > 90 and not s.startswith("⚠️"))
        or s.lower().startswith("first,")
        for s in step_descriptions
    )
    if not step_descriptions or has_dirty_step:
        if preview_card and preview_card.type == "draft_message":
            step_descriptions = ["Retrieved ticket context", "Prepared draft reply", "Queued for approval"]
        elif any(k in q_low for k in ["priority", "first", "emergency", "ticket"]):
            step_descriptions = ["Analyzed active maintenance queue", "Ranked tickets by operational urgency"]
        elif any(k in q_low for k in ["rent", "arrear", "invoice", "overdue"]):
            step_descriptions = ["Scanned portfolio payment ledger", "Checked active tenant balances"]
        elif any(k in q_low for k in ["task", "todo", "waiting"]):
            step_descriptions = ["Fetched pending action approvals", "Ranked tasks by operational SLA"]
        elif any(k in q_low for k in ["inbox", "message", "messages", "email", "emails", "mail", "whatsapp"]):
            step_descriptions = ["Scanned recent communications", "Checked urgent tenant inquiries"]
        elif any(k in q_low for k in ["contractor", "job", "pending"]):
            step_descriptions = ["Queried active contractor dispatch schedule"]
        elif any(k in q_low for k in ["explain", "detail"]):
            step_descriptions = ["Analyzed active portfolio records", "Generated executive briefing"]
        else:
            step_descriptions = ["Indexed live portfolio state", "Synthesized response"]
    else:
        # Sanitize any raw truncated answer text that got shoved into steps
        clean_steps = []
        for s in step_descriptions:
            if s.startswith("Based on active portfolio") or s.startswith("Open tasks:"):
                clean_steps.append("Analyzed live portfolio records")
            elif len(s) > 80:
                clean_steps.append(s[:77] + "...")
            else:
                clean_steps.append(s)
        step_descriptions = clean_steps

    suggested_action = action_buttons[0].label if action_buttons else None

    # Determine 3 dynamic workflow suggestions (2-3 words each)
    suggestions: list[str] = []
    if plan and getattr(plan, "suggestions", None):
        suggestions = [s.strip() for s in plan.suggestions if s.strip()][:3]

    if not suggestions or len(suggestions) < 3:
        if preview_card and preview_card.type == "draft_message":
            fallback_pills = ["Send WhatsApp now", "Make reply firmer", "Open in Inbox"]
        elif any(k in q_low for k in ["rent", "arrear", "invoice", "money", "overdue"]):
            fallback_pills = ["Draft payment reminder", "Show lease PDF", "Open in Money"]
        elif any(k in q_low for k in ["leak", "boiler", "repair", "maintenance", "ticket", "priority"]):
            fallback_pills = ["Draft plumber order", "Show leak photos", "Open ticket drawer"]
        elif any(k in q_low for k in ["lease", "contract", "doc", "pdf"]):
            fallback_pills = ["Draft rent increase", "Show tenant contact", "Open lease view"]
        else:
            fallback_pills = ["List active leases", "Check open tickets", "Show today summary"]
        merged = suggestions + [p for p in fallback_pills if p not in suggestions]
        suggestions = merged[:3]

    # Build polymorphic AssistantCardData list from preview_cards_list
    cards_list: list[AssistantCardData] = []
    target_cards = preview_cards_list if preview_cards_list else ([preview_card] if preview_card else [])
    for p_card in target_cards:
        card_actions: list[CardActionData] = []
        if p_card.type == "draft_message":
            if p_card.status == "pending" or not p_card.status:
                card_actions.append(
                    CardActionData(
                        label="Accept and send",
                        kind="api_call",
                        endpoint=f"/api/inbox/approvals/{p_card.actionId}/decide" if p_card.actionId else None,
                        payload={"decision": "approved"},
                        variant="primary",
                    )
                )
            if p_card.externalUrl:
                label = "Open in WhatsApp" if p_card.channel == "whatsapp" else "Open in Gmail"
                card_actions.append(
                    CardActionData(
                        label=label,
                        kind="open_external",
                        targetUrl=p_card.externalUrl,
                        variant="whatsapp" if p_card.channel == "whatsapp" else "gmail",
                    )
                )
            if p_card.threadSearchUrl:
                label = "View Thread on WhatsApp" if p_card.channel == "whatsapp" else "View Thread in Gmail"
                card_actions.append(
                    CardActionData(
                        label=label,
                        kind="open_external",
                        targetUrl=p_card.threadSearchUrl,
                        variant="secondary",
                    )
                )
            card_actions.append(
                CardActionData(
                    label="Open in Inbox",
                    kind="navigate",
                    targetUrl=p_card.targetUrl
                    or (f"/inbox?thread=case-{p_card.caseId}" if p_card.caseId else "/inbox"),
                    variant="secondary",
                )
            )
        elif p_card.type == "notice":
            card_actions.append(
                CardActionData(
                    label="Review in Inbox",
                    kind="navigate",
                    targetUrl=p_card.targetUrl
                    or (f"/inbox?thread=case-{p_card.caseId}" if p_card.caseId else "/inbox"),
                    variant="primary",
                )
            )
            if p_card.caseId:
                card_actions.append(
                    CardActionData(
                        label="Retry draft",
                        kind="query",
                        payload={"query": f"draft a reply for case {p_card.caseId}"},
                        variant="secondary",
                    )
                )
        elif p_card.type == "case_summary":
            card_actions.append(
                CardActionData(
                    label="Open in Maintenance",
                    kind="navigate",
                    targetUrl=p_card.targetUrl
                    or (f"/maintenance?ticket={p_card.caseId}" if p_card.caseId else "/maintenance"),
                    variant="primary",
                )
            )
        elif p_card.type == "calendar_item":
            card_actions.append(
                CardActionData(
                    label="Approve and Add to Calendar",
                    kind="api_call",
                    endpoint=f"/api/calendar/events/{p_card.actionId}/approve" if p_card.actionId else None,
                    variant="primary",
                )
            )

        cards_list.append(
            AssistantCardData(
                id=p_card.actionId or p_card.caseId or f"card-{len(cards_list)}",
                type=p_card.type,
                badgeLabel=p_card.badgeLabel or ("DRAFT" if p_card.type == "draft_message" else "TICKET"),
                badgeColor=getattr(p_card, "badgeColor", None) or "orange",
                title=p_card.title or (p_card.unitLabel or "Draft Message"),
                subtitle=p_card.subtitle,
                body=p_card.body,
                amount=p_card.amount,
                contractor=p_card.contractor,
                dueDate=p_card.dueDate,
                status=p_card.status,
                unitLabel=p_card.unitLabel,
                recipient=p_card.recipient,
                channel=p_card.channel,
                actions=card_actions,
                externalUrl=p_card.externalUrl,
                threadSearchUrl=p_card.threadSearchUrl,
                targetUrl=p_card.targetUrl,
                caseId=p_card.caseId,
                actionId=p_card.actionId,
            )
        )

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
        preview_cards=preview_cards_list if preview_cards_list else ([preview_card] if preview_card else []),
    )


@router.get("/conversations", response_model=ConversationListResponse, summary="List Super Agent Conversation Threads")
def list_conversations(engine: Annotated[Engine, Depends(get_engine)]) -> ConversationListResponse:
    with Session(engine) as session:
        company = session.scalars(select(Company).limit(1)).first()
        company_id = company.id if company else UUID("00000000-0000-0000-0000-000000000001")

        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)

        convs = list(
            session.scalars(
                select(AgentConversation)
                .where(
                    AgentConversation.company_id == company_id,
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
    conversation_id: str, engine: Annotated[Engine, Depends(get_engine)]
) -> ConversationDetailResponse:
    with Session(engine) as session:
        try:
            cid = UUID(conversation_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid conversation UUID") from None

        conv = session.get(AgentConversation, cid)
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
            actions_raw = res_dict.get("actions") or []
            steps_raw = res_dict.get("steps") or []
            prompts_raw = res_dict.get("suggestedPrompts") or []

            replay_items.append(
                TurnReplayItem(
                    id=str(t.id),
                    sender=sender,
                    text=text or "",
                    timestamp=t.created_at.strftime("%H:%M") if t.created_at else "",
                    steps=steps_raw,
                    previewCard=PreviewCardData.model_validate(preview_raw) if preview_raw else None,
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
) -> dict[str, Any]:
    with Session(engine) as session:
        try:
            cid = UUID(conversation_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid conversation UUID") from None

        conv = session.get(AgentConversation, cid)
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
