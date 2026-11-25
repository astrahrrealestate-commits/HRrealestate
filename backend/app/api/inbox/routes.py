"""Inbox & Triage REST API Routes.

Feeds communications triage threads (Gmail & WhatsApp), AI multi-draft proposals,
audience filtering, and 1-click owner approval execution to the Next.js frontend.
"""

import contextlib
import threading
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, select
from sqlalchemy import case as sql_case
from sqlalchemy.orm import Session

from app.api.deps import WorkflowClient, get_engine, get_ingest_deps, get_storage, get_workflow_client
from app.api.inbox import decide as inbox_decide
from app.api.inbox.summary import headline_only
from app.api.inbox.thread_batch import (
    ThreadDetailsBatch,
    ThreadMessagesBatch,
    inbox_stats_counts,
    is_automated_sender,
    load_details_batch,
    load_messages_batch,
)
from app.api.inbox.time_labels import when_label
from app.api.inbox.translate import annotate_translations
from app.api.inbox.translate import router as translate_router
from app.api.inbox.unit_match import unit_named_in
from app.api.v1 import enqueue
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.api.v1.session_limits import decide_limit, sync_limit
from app.channels.gmail.html_sanitize import html_to_clean_text, looks_like_html, sanitize_email_html
from app.context.sender_label import UNASSIGNED_UNIT, resolve_sender_label, role_hint_of, unit_display
from app.context.shown_sender import greeting_name, sender_person_ids, shown_sender_name
from app.contracts import ActionType, ButtonChoice, CaseState, Category, Channel, Direction, Urgency
from app.core.errors import NotFoundError
from app.core.ids import case_ref, new_id
from app.core.language import detect_language
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.db.enums import ActionStatus, ApprovalStatus, CaseEventKind, PersonKind, PipelineStatus, RawEventStatus
from app.db.models import (
    ActionRevision,
    ActionRow,
    Approval,
    AttachmentRow,
    Case,
    CaseEvent,
    CaseLink,
    ChannelAccount,
    ChannelIdentity,
    Company,
    GmailSyncState,
    Lease,
    LeaseParty,
    MessageRow,
    Person,
    RawEvent,
    Unit,
)
from app.directory.contacts import link_secondary_identity
from app.ingestion.gmail_sync import sync_mailbox
from app.ingestion.process import IngestDeps, company_mailboxes, owner_addresses
from app.pipeline import dashboard_decisions
from app.pipeline.dashboard_decisions import is_suspicious
from app.storage.ports import ObjectStorage

router = APIRouter(
    prefix="/api/inbox", tags=["inbox"], dependencies=[Depends(require_section("inbox", also_read=("dashboard",)))]
)
router.include_router(translate_router)
log = get_logger(__name__)


class ApprovalDecideRequest(BaseModel):
    """Payload for Harjot's 1-click approval button decision."""

    choice: str = Field(default="d1", description="Choice button: d1, d2, d3, ok, edit, or reject")
    edited_text: str | None = Field(default=None, description="Optional edited text for the draft")
    reply_to_message_id: str | None = Field(
        default=None, description="Optional message ID to quote in contextual reply"
    )


# Rich default seeds so the frontend displays complete live data even before first email webhook arrives
DEFAULT_SEEDED_THREADS: list[dict[str, Any]] = []


def _is_contractor_case(case: Case, person: Any, sender_email: str, messages: list[MessageRow]) -> bool:
    return (
        (person is not None and person.kind == PersonKind.contractor)
        or (
            case.category is not None
            and case.category.value in ("contractor_update", "contractor_invoices", "contractor_repairs")
        )
        or any(c_kw in sender_email.lower() for c_kw in ("chahalbouw.nl", "contractor", "loodgieter"))
        or any("chahalbouw.nl" in (m.sender_identity or "").lower() for m in messages)
    )


def _resolve_unit_label(
    case: Case,
    messages: list[MessageRow],
    units_by_id: dict[UUID, Unit],
    company_units: list[tuple[str, str | None]],
) -> str:
    unit = units_by_id.get(case.unit_id) if case.unit_id else None
    label = (unit.address or unit.label) if unit else None
    if not label or label == UNASSIGNED_UNIT:
        all_text = " ".join(
            (m.text or "") + " " + (str(m.meta.get("subject", "")) if isinstance(m.meta, dict) else "")
            for m in messages
        ).lower()
        label = unit_named_in(all_text, company_units)
    return label or UNASSIGNED_UNIT


def _build_custom_facts(
    case: Case,
    *,
    und_intent: str,
    und_entities: dict[str, Any],
    unit_label: str,
    sender_name: str,
    sender_email: str,
    is_unregistered_sender: bool,
    matched_tenant_info: dict[str, str] | None,
) -> list[dict[str, Any]]:
    custom_facts: list[dict[str, Any]] = [
        {"label": "Intent", "value": und_intent, "checked": True},
        {"label": "Category", "value": case.category.value.upper(), "checked": True},
        {"label": "Priority", "value": (case.urgency.value if case.urgency else "normal").upper(), "checked": True},
        *([{"label": "Unit", "value": unit_label, "checked": True}] if unit_label else []),
        {"label": "Sender", "value": sender_name, "checked": True},
    ]
    if case.category == Category.maintenance:
        if case.brixx_ref:
            custom_facts.append(
                {
                    "label": "BRIXX Ticket",
                    "value": f"BRIXX-{case.brixx_ref} (Linked)",
                    "checked": True,
                    "isAlert": False,
                }
            )
        else:
            custom_facts.append(
                {
                    "label": "BRIXX Ticket",
                    "value": "Not in BRIXX (Pending Work Order)",
                    "checked": True,
                    "isAlert": True,
                }
            )
    for amt in und_entities.get("amounts") or ():
        custom_facts.append(
            {"label": "Amount", "value": f"€ {amt.get('amount')} {amt.get('currency', 'EUR')}", "checked": True}
        )
    for d in und_entities.get("dates") or ():
        custom_facts.append({"label": "Date Mentioned", "value": str(d), "checked": True})
    if und_entities.get("people"):
        custom_facts.append({"label": "People", "value": ", ".join(und_entities["people"]), "checked": True})
    if is_unregistered_sender and matched_tenant_info:
        custom_facts.append(
            {
                "label": "Sender Status",
                "value": f"⚠️ Unregistered ({sender_email}) · Leaseholder: {matched_tenant_info['name']}",
                "checked": True,
                "isAlert": True,
            }
        )
    return custom_facts


# Cancelled, held by the rules for review, refused or failed: none of these may come back as an approvable draft.
_NEVER_OFFERED = (ActionStatus.superseded, ActionStatus.exception, ActionStatus.rejected, ActionStatus.failed)


def _offered_reply(actions: list[ActionRow], messages: list[MessageRow], shown: MessageRow) -> ActionRow | None:
    """The newest reply draft the composer may prefill, addressed there to `shown`'s sender. None when it was
    cancelled, held or refused (never an older one instead) or, on a case holding repaired mail (ADR 0016), answers
    someone else."""
    action = next((a for a in actions if a.type == ActionType.reply_draft), None)
    if action is None or action.status in _NEVER_OFFERED:
        return None
    if any("reattributed_from" in (m.meta or {}) for m in messages):
        senders = {m.id: m.sender_identity.lower() for m in messages}
        if {senders[ref] for ref in action.context_ref or () if ref in senders} != {shown.sender_identity.lower()}:
            return None
    return action


def _build_drafts(
    reply_action: ActionRow | None, sender_name: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    gmail_drafts: list[dict[str, Any]] = []
    whatsapp_drafts: list[dict[str, Any]] = []
    draft_persona: dict[str, Any] | None = None

    if reply_action and reply_action.payload:
        if reply_action.persona_name:
            draft_persona = {
                "actingAs": "Harjot",
                "name": reply_action.persona_name,
                "version": reply_action.persona_version,
            }
        variants = reply_action.payload.get("body_variants") or []
        if not variants and reply_action.payload.get("text"):
            variants = [reply_action.payload["text"]]
        elif not variants and reply_action.payload.get("body"):
            variants = [reply_action.payload["body"]]

        for idx, text in enumerate(variants, start=1):
            gmail_drafts.append(
                {
                    "id": f"gd{idx}",
                    "label": f"Draft {idx} (Recommended)" if idx == 1 else f"Draft {idx} (Alternative)",
                    "channel": "gmail",
                    "text": text,
                    "confidence": 98 if idx == 1 else 95,
                }
            )
            whatsapp_drafts.append(
                {
                    "id": f"wd{idx}",
                    "label": f"WhatsApp {idx} (Quick Confirmation)" if idx == 1 else f"WhatsApp {idx} (Detailed)",
                    "channel": "whatsapp",
                    "text": text,
                    "confidence": 98 if idx == 1 else 95,
                }
            )

    if not gmail_drafts:
        # No agent draft yet: neutral acknowledgements only. They state no fact, date, amount or commitment.
        greet = greeting_name(sender_name)
        hello = f" {greet}" if greet else ""
        d1_en = (
            f"Dear {greet or 'sir/madam'},\n\nThank you for your message. We have received it and will get back to you "
            "shortly.\n\nBest regards,\nHarjot"
        )
        d2_en = (
            f"Hello{hello},\n\nThanks for reaching out. I am looking into this and will follow up as soon "
            "as I can.\n\nKind regards,\nHarjot"
        )
        d1_wa = f"Hi{hello}, thank you for your message. We have received it and will reply shortly."
        d2_wa = f"Hello{hello}, thanks for reaching out. I am looking into this and will get back to you."

        gmail_drafts = [
            {"id": "gd1", "label": "Draft 1 (Recommended)", "channel": "gmail", "text": d1_en, "confidence": 98},
            {"id": "gd2", "label": "Draft 2 (Alternative)", "channel": "gmail", "text": d2_en, "confidence": 95},
        ]
        whatsapp_drafts = [
            {
                "id": "wd1",
                "label": "WhatsApp 1 (Quick Confirmation)",
                "channel": "whatsapp",
                "text": d1_wa,
                "confidence": 98,
            },
            {"id": "wd2", "label": "WhatsApp 2 (Detailed)", "channel": "whatsapp", "text": d2_wa, "confidence": 95},
        ]
    return gmail_drafts, whatsapp_drafts, draft_persona


@dataclass
class _PreparedCase:
    case: Case
    messages: list[MessageRow]
    tenant_msg: MessageRow
    latest_msg: MessageRow
    sender_email: str
    sender_name: str
    person: Any
    sender_label: Any
    raw_unit_label: str
    channel_str: str


def _prepare_cases(
    cases: list[Case],
    msg_batch: ThreadMessagesBatch,
    *,
    has_filters: bool,
    channel: str,
    audience: str,
    category: str,
    limit: int,
    offset: int,
) -> list[_PreparedCase]:
    kept: list[_PreparedCase] = []
    for case in cases:
        messages = msg_batch.msgs_by_case.get(case.id)
        if not messages:
            continue
        inbound_msgs = [m for m in messages if m.direction != Direction.outbound]
        tenant_msg = inbound_msgs[-1] if inbound_msgs else messages[0]
        latest_msg = messages[-1]
        sender_email = tenant_msg.sender_identity
        if is_automated_sender(sender_email):
            continue

        contact = msg_batch.people_by_id.get(case.primary_person_id) if case.primary_person_id else None
        # Label and flat belong to the sender shown, who on a shared or older case is not the case's contact.
        writer_id = msg_batch.sender_person_by_msg.get(tenant_msg.id) if tenant_msg in inbound_msgs else None
        writer = msg_batch.people_by_id.get(writer_id) if writer_id else None
        # An unknown writer stays unknown: only a thread nobody has written in takes the contact's label.
        person = writer if tenant_msg in inbound_msgs else contact
        is_contractor = _is_contractor_case(case, person, sender_email, messages)
        sender_und = msg_batch.und_by_msg_id.get(tenant_msg.id)
        und_body_hint = sender_und.body if sender_und and isinstance(sender_und.body, dict) else {}
        is_lp = person is not None and person.id in msg_batch.lease_party_ids
        sender_label = resolve_sender_label(
            person_kind=person.kind if person else None,
            trade=person.trade if person else None,
            is_lease_party=is_lp,
            contractor_hint=is_contractor,
            role_hint=role_hint_of(und_body_hint, tenant_msg.meta),
        )
        channel_str = latest_msg.channel.value if latest_msg.channel else "gmail"
        case_cat = case.category.value if case.category else "maintenance"
        if has_filters and (
            (channel != "all" and channel_str != channel)
            or (audience != "all" and sender_label.audience != audience)
            or (category != "all" and case_cat != category)
        ):
            continue

        if tenant_msg.direction != Direction.outbound:
            sender_name = shown_sender_name(tenant_msg, msg_batch.saved_names.get(tenant_msg.id))
        else:  # nobody has written in yet: the thread is named after the case's contact
            sender_name = person.display_name if person else sender_email
        # The flat a case is about stays; the writer's own flat only fills a case that has none.
        own_flat = msg_batch.unit_by_person.get(person.id) if person is not None and not case.unit_id else None
        raw_unit = own_flat or _resolve_unit_label(case, messages, msg_batch.units_by_id, msg_batch.company_units)
        kept.append(
            _PreparedCase(
                case=case,
                messages=messages,
                tenant_msg=tenant_msg,
                latest_msg=latest_msg,
                sender_email=sender_email,
                sender_name=sender_name,
                person=person,
                sender_label=sender_label,
                raw_unit_label=raw_unit,
                channel_str=channel_str,
            )
        )
        if not has_filters and len(kept) >= limit:
            break
    return kept[offset : offset + limit] if has_filters else kept


def _assemble_thread(
    prep: _PreparedCase,
    msg_batch: ThreadMessagesBatch,
    details: ThreadDetailsBatch,
    *,
    company_tz: ZoneInfo,
    now_dt: datetime,
) -> dict[str, Any]:
    case = prep.case
    messages = prep.messages
    unit_label = prep.raw_unit_label
    is_unregistered_sender = False
    matched_tenant_info: dict[str, str] | None = None

    if unit_label != UNASSIGNED_UNIT:
        lease_rows = details.leases_by_unit_key.get(unit_label)
        if lease_rows:
            tenant_id, tenant_name, _ = lease_rows[0]
            known_identities = {str(row[2]).lower().strip() for row in lease_rows if row[2]}
            sender_clean = prep.sender_email.lower().strip()
            if (
                sender_clean not in known_identities
                and (not prep.person or prep.person.kind == PersonKind.other)
                and prep.sender_label.may_be_tenant
            ):
                is_unregistered_sender = True
                matched_tenant_info = {"id": str(tenant_id), "name": tenant_name, "unit": unit_label}

    if unit_label == UNASSIGNED_UNIT:
        unit_label = unit_display(prep.sender_label.kind, None, prep.sender_email)

    actions = details.actions_by_case.get(case.id, [])
    reply_action = _offered_reply(actions, messages, prep.tenant_msg)
    approval = None
    if reply_action:
        approvals = details.approvals_by_action.get(reply_action.id, [])
        approval = next(
            (ap for ap in approvals if ap.status == ApprovalStatus.pending), approvals[0] if approvals else None
        )

    und_row = msg_batch.und_by_msg_id.get(prep.latest_msg.id)
    und_body = und_row.body if und_row and isinstance(und_row.body, dict) else {}
    und_entities = und_body.get("entities") or {}
    raw_intent = und_body.get("intent") or case.summary or "Incoming communication analyzed by Gemini AI agent."
    und_intent = (
        raw_intent.replace("_", " ").strip().capitalize()
        if isinstance(raw_intent, str) and "_" in raw_intent and " " not in raw_intent.strip()
        else raw_intent
    )
    detected_lang_label = {"nl": "Dutch (detected)", "en": "English (detected)"}.get(
        detect_language(prep.latest_msg.text or ""), "Language not detected"
    )
    custom_facts = _build_custom_facts(
        case,
        und_intent=und_intent,
        und_entities=und_entities,
        unit_label=unit_label,
        sender_name=prep.sender_name,
        sender_email=prep.sender_email,
        is_unregistered_sender=is_unregistered_sender,
        matched_tenant_info=matched_tenant_info,
    )
    # A draft's text is offered only while an approval waits for it. One without (paused before the rules checked its
    # links and account numbers, or already decided) would be sent as a typed reply by one click.
    waiting = reply_action if approval is not None and approval.status is ApprovalStatus.pending else None
    gmail_drafts, whatsapp_drafts, draft_persona = _build_drafts(waiting, prep.sender_name)

    sent_dt = prep.latest_msg.sent_at or now_dt
    if sent_dt.tzinfo is None:
        sent_dt = sent_dt.replace(tzinfo=UTC)
    rel_label = when_label(sent_dt, now_dt, company_tz, weekdays=True)

    attachments_map: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    all_thread_attachments: list[dict[str, Any]] = []
    for m in messages:
        for att in details.attachments_by_msg.get(m.id, ()):
            size_kb = (att.size_bytes or 0) / 1024
            size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
            doc_row = details.docs_by_att.get(att.id)
            drive_url = (
                f"https://drive.google.com/file/d/{doc_row.drive_file_id}/view"
                if doc_row and doc_row.drive_file_id
                else None
            )
            att_item = {
                "id": str(att.id),
                "name": att.filename or "Attachment",
                "filename": att.filename or "Attachment",
                "type": att.mime_type or "application/octet-stream",
                "mimeType": att.mime_type or "application/octet-stream",
                "size": size_str,
                "sizeBytes": att.size_bytes,
                "url": f"/api/inbox/attachments/{att.id}",
                "driveUrl": drive_url,
            }
            attachments_map[att.message_id].append(att_item)
            all_thread_attachments.append(att_item)

    owner_email = get_settings().owner_email or "owner@estateos.com"
    msgs_data: list[dict[str, Any]] = []
    for m in messages:
        m_dt = m.sent_at or now_dt
        if m_dt.tzinfo is None:
            m_dt = m_dt.replace(tzinfo=UTC)
        m_time_fmt = when_label(m_dt, now_dt, company_tz)
        m_is_incoming = m.direction != Direction.outbound
        if m.direction == Direction.outbound:
            m_sender_type, m_sender_name, m_sender_contact = "owner", "Harjot Singh", m.sender_identity or owner_email
        else:
            m_sender_type, m_sender_name, m_sender_contact = (
                prep.sender_label.kind.value,
                shown_sender_name(m, msg_batch.saved_names.get(m.id)),
                m.sender_identity,
            )
        m_meta = m.meta if isinstance(m.meta, dict) else {}
        stored_html = m_meta.get("body_html")
        # Cleaned again on read: HTML stored by an earlier sanitizer version is not trusted.
        raw_html = sanitize_email_html(stored_html) if isinstance(stored_html, str) else None
        raw_text = m.text or ""
        if not raw_html and looks_like_html(raw_text):
            raw_html = sanitize_email_html(raw_text)
        clean_body = html_to_clean_text(raw_text) if looks_like_html(raw_text) else raw_text
        msgs_data.append(
            {
                "id": str(m.id),
                "sender": m_sender_type,
                "senderName": m_sender_name,
                "senderContact": m_sender_contact,
                "sentAt": m_dt.isoformat(),
                "timeFormatted": m_time_fmt,
                "content": clean_body,
                "body": clean_body,
                "bodyHtml": raw_html,
                "isIncoming": m_is_incoming,
                "channel": m.channel.value if m.channel else "gmail",
                "attachments": attachments_map.get(m.id, []),
                "subject": m_meta.get("subject", "Communication"),
            }
        )

    actions_by_id = {a.id: a for a in actions}
    for act in actions:
        for s in details.sends_by_action.get(act.id, ()):
            s_dt = s.attempted_at or now_dt
            if s_dt.tzinfo is None:
                s_dt = s_dt.replace(tzinfo=UTC)
            s_time_fmt = when_label(s_dt, now_dt, company_tz)
            act_row = actions_by_id.get(s.action_id) if s.action_id is not None else act
            act_payload = act_row.payload if act_row and isinstance(act_row.payload, dict) else {}
            variants = act_payload.get("body_variants") or []
            body_txt = variants[0] if variants else "Replied to tenant."
            s_iso = s_dt.isoformat()
            preceding_incoming = [m for m in msgs_data if m.get("isIncoming") and (m.get("sentAt") or "") <= s_iso]
            reply_to_info = None
            if preceding_incoming:
                target_in = preceding_incoming[-1]
                clean_in_text = (target_in.get("body") or "").strip().strip('"').strip("'")
                reply_to_info = {
                    "id": str(target_in.get("id")),
                    "sender": target_in.get("senderName") or "Tenant",
                    "text": clean_in_text[:120],
                }
            elif act_payload.get("reply_to"):
                reply_to_info = act_payload.get("reply_to")
            msgs_data.append(
                {
                    "id": str(s.id),
                    "sender": "owner",
                    "senderName": "Harjot Singh",
                    "senderContact": "+31 20 000 0001",
                    "sentAt": s_iso,
                    "timeFormatted": s_time_fmt,
                    "content": body_txt,
                    "body": body_txt,
                    "isIncoming": False,
                    "channel": s.channel.value if s.channel else "whatsapp",
                    "subject": "Reply",
                    "replyTo": reply_to_info,
                }
            )

    msgs_data.sort(key=lambda x: x.get("sentAt", ""))
    has_owner_reply = any(m.get("sender") == "owner" for m in msgs_data)
    status_str = "needs_approval"
    if case.state in (CaseState.closed, CaseState.resolved):
        status_str = "closed"
    elif (approval and approval.status == ApprovalStatus.approved) or has_owner_reply:
        status_str = "approved"
    elif approval and approval.status == ApprovalStatus.rejected:
        status_str = "rejected"

    last_read = getattr(case, "last_read_at", None)
    if last_read is not None and last_read.tzinfo is None:
        last_read = last_read.replace(tzinfo=UTC)
    is_read = bool(has_owner_reply or (last_read is not None and last_read >= sent_dt) or status_str == "closed")
    snoozed_until = getattr(case, "snoozed_until", None)
    subject_str = (
        prep.latest_msg.meta.get("subject") if isinstance(prep.latest_msg.meta, dict) else None
    ) or " - ".join(filter(None, (case.category.value.title(), unit_label)))
    hide_drafts = status_str == "approved" or (bool(msgs_data) and msgs_data[-1].get("sender") == "owner")
    ticket_code = f"BRIXX-{case.brixx_ref}" if case.brixx_ref else f"#{case_ref(case.id)}"

    latest_raw_text = prep.latest_msg.text or ""
    latest_clean_snippet = html_to_clean_text(latest_raw_text) if looks_like_html(latest_raw_text) else latest_raw_text

    return {
        "id": f"case-{case.id}",
        "caseId": str(case.id),
        "senderMessageId": str(prep.tenant_msg.id),  # the mail whose sender the card names ("Link to Tenant")
        "ticketNumber": ticket_code,
        "caseRef": ticket_code,
        "approvalId": str(approval.id) if approval else f"case-{case.id}",
        "audience": prep.sender_label.audience,
        "senderKind": prep.sender_label.kind.value,
        "recipientRole": prep.sender_label.recipient_role,
        "recipientRoleDetail": prep.sender_label.role_detail,
        "isUnregisteredSender": is_unregistered_sender,
        "matchedTenant": matched_tenant_info,
        "category": case.category.value if case.category else "maintenance",
        "urgency": case.urgency.value if case.urgency else "normal",
        "unit": unit_label,
        "title": subject_str,
        "lastMessageSnippet": latest_clean_snippet[:140],
        "timestamp": rel_label,
        "receivedAt": sent_dt.isoformat(),
        "channel": prep.channel_str,
        "channelBadge": f"{prep.channel_str.title()} · {rel_label}",
        "sourceIdentifier": f"{prep.channel_str.title()} · {prep.sender_email}",
        "subject": subject_str,
        "externalMessageId": prep.latest_msg.provider_msg_id or str(prep.latest_msg.id),
        "externalThreadId": prep.latest_msg.thread_ref,
        "sender": {
            "name": prep.sender_name,
            "contact": prep.sender_email,
            "role": prep.sender_label.role_detail,
            "unit": unit_label,
        },
        "aiSummary": und_intent,
        "aiConfidence": int((und_body.get("confidence") or 0.95) * 100),
        "detectedLanguage": detected_lang_label,
        "aiUnderstanding": {
            "ticket": ticket_code,
            "problem": und_intent,
            "unit": unit_label,
            "priority": (case.urgency.value if case.urgency else "normal").upper(),
            "suggestedContractor": None,
            "customFacts": custom_facts,
        },
        "activeChannel": prep.channel_str,
        "status": status_str,
        "isRead": is_read,
        "snoozedUntil": snoozed_until.isoformat() if snoozed_until else None,
        "gmailDrafts": [] if hide_drafts else gmail_drafts,
        "whatsappDrafts": [] if hide_drafts else whatsapp_drafts,
        "draftPersona": draft_persona,
        "attachments": all_thread_attachments,
        "messages": msgs_data,
    }


def _build_live_threads(
    session: Session,
    company_id: UUID,
    limit: int = 20,
    offset: int = 0,
    *,
    channel: str = "all",
    audience: str = "all",
    category: str = "all",
    sort: str = "recent",
) -> list[dict[str, Any]]:
    """Builds frontend-compatible thread structures from PostgreSQL via batched read-only queries."""
    has_filters = channel != "all" or audience != "all" or category != "all"
    base_q = session.query(Case).filter(Case.company_id == company_id)
    if sort == "priority":
        closed_rank = sql_case((Case.state.in_((CaseState.closed, CaseState.resolved)), 1), else_=0)
        urgency_rank = sql_case(
            (Case.urgency == Urgency.emergency, 0),
            (Case.urgency == Urgency.high, 1),
            (Case.urgency == Urgency.normal, 2),
            else_=3,
        )
        base_q = base_q.order_by(closed_rank.asc(), urgency_rank.asc(), Case.opened_at.desc())
    else:
        base_q = base_q.order_by(Case.opened_at.desc())
    if category not in ("all", "contractor_repairs", "contractor_money"):
        with contextlib.suppress(ValueError):
            base_q = base_q.filter(Case.category == Category(category))
    cases = base_q.all() if has_filters else base_q.offset(offset).limit(limit).all()
    if not cases:
        return []

    now_dt = datetime.now(UTC)
    msg_batch = load_messages_batch(session, company_id, cases)
    company_tz = ZoneInfo(msg_batch.company.timezone if msg_batch.company else "Europe/Amsterdam")
    prepared = _prepare_cases(
        cases,
        msg_batch,
        has_filters=has_filters,
        channel=channel,
        audience=audience,
        category=category,
        limit=limit,
        offset=offset,
    )
    if not prepared:
        return []

    kept_case_ids = [p.case.id for p in prepared]
    kept_msg_ids = [m.id for p in prepared for m in p.messages]
    unit_labels = {p.raw_unit_label for p in prepared if p.raw_unit_label != UNASSIGNED_UNIT}
    details = load_details_batch(session, company_id, kept_case_ids, kept_msg_ids, unit_labels, now_dt.date())

    live_threads = [_assemble_thread(p, msg_batch, details, company_tz=company_tz, now_dt=now_dt) for p in prepared]
    all_msgs = [m for t in live_threads for m in t["messages"]]
    all_drafts = [d for t in live_threads for d in (*t["gmailDrafts"], *t["whatsappDrafts"])]
    annotate_translations(session, company_id, all_msgs, all_drafts)
    return live_threads


@router.get(
    "/threads",
    summary="Get Communications Inbox Threads",
    description="Retrieves communications threads enriched with AI-drafted replies from PostgreSQL.",
)
def get_inbox_threads(
    engine: Annotated[Engine, Depends(get_engine)],
    channel: str = Query(default="all", description="all, gmail, whatsapp"),
    audience: str = Query(default="all", description="all, tenants, contractors"),
    category: str = Query(default="all", description="all, contractor_repairs, contractor_money"),
    sort: str = Query(default="recent", description="recent or priority"),
    limit: int = Query(default=20, ge=1, le=100, description="Max threads to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    *,
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    """Retrieves inbox threads enriched with agent-drafted proposals."""
    # Safe parameter normalization (handles both FastAPI dependency injection and direct calls)
    chan = channel if isinstance(channel, str) else getattr(channel, "default", "all")
    aud = audience if isinstance(audience, str) else getattr(audience, "default", "all")
    cat = category if isinstance(category, str) else getattr(category, "default", "all")
    sort_mode = sort if isinstance(sort, str) else getattr(sort, "default", "recent")
    lim = limit if isinstance(limit, int) else getattr(limit, "default", 20)
    off = offset if isinstance(offset, int) else getattr(offset, "default", 0)

    with Session(engine) as session:
        live_threads = _build_live_threads(
            session,
            principal.company_id,
            limit=lim,
            offset=off,
            channel=chan,
            audience=aud,
            category=cat,
            sort=sort_mode,
        )
        total_cases = session.query(func.count(Case.id)).filter(Case.company_id == principal.company_id).scalar() or 0
    if not principal.access.can("inbox"):
        live_threads = [headline_only(t) for t in live_threads]

    threads = list(live_threads)

    unfiltered = chan == "all" and aud == "all" and cat == "all"
    has_more = (off + len(live_threads)) < total_cases if unfiltered else len(live_threads) == lim
    return {
        "threads": threads,
        "total": total_cases,
        "has_more": has_more,
        "offset": off,
        "limit": lim,
        "syncedAt": datetime.now(UTC).isoformat(),
    }


@router.get(
    "/stats",
    summary="Get Inbox Badge Statistics",
    description="Returns aggregate metric counters for the inbox navigation badge counts.",
)
def get_inbox_stats(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, int]:
    """Returns metric counters for inbox triage badges computed via lightweight SQL counts."""
    with Session(engine) as session:
        return inbox_stats_counts(session, principal.company_id)


_SYNC_LOCK = threading.Lock()


def _reset_dummy_cursor(session: Session, account_id: UUID) -> None:
    """Clear an invalid/dummy history cursor so the next sync lists recent mail instead."""
    state = session.scalars(select(GmailSyncState).where(GmailSyncState.channel_account_id == account_id)).first()
    if state and (state.history_id == "99999999" or not state.history_id):
        state.history_id = None
        session.commit()


def sync_gmail_accounts(deps: IngestDeps, company_id: UUID | None = None) -> int:
    """Pull connected Gmail mailboxes once without holding DB connections open during Gmail RPCs."""
    if not _SYNC_LOCK.acquire(blocking=False):
        return 0
    try:
        synced_count = 0
        with Session(deps.engine) as session:
            query = select(ChannelAccount).where(ChannelAccount.channel == Channel.gmail)
            if company_id is not None:
                query = query.where(ChannelAccount.company_id == company_id)
            acct_rows = [(acct.id, acct.address) for acct in session.scalars(query).all()]
            for acct_id, _ in acct_rows:
                try:
                    _reset_dummy_cursor(session, acct_id)
                except Exception as e:
                    log.warning("sync_inbox.cursor_reset_error", error=str(e))
        for acct_id, address in acct_rows:
            try:
                current = deps.gmail_mailbox(address).current_history_id()
                synced_count += sync_mailbox(deps, acct_id, current)
            except Exception as e:
                log.warning("sync_inbox.mailbox_error", account=address, error=str(e))
        return synced_count
    finally:
        _SYNC_LOCK.release()


@router.post(
    "/sync",
    dependencies=[Depends(sync_limit)],
    summary="Sync Inbound Communications",
    description="Pulls new Gmail messages directly from Google and runs the Gemini ingestion pipeline.",
)
def sync_inbox(
    deps: Annotated[IngestDeps, Depends(get_ingest_deps)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    """Triggers an on-demand sync of the signed-in owner's Gmail and enqueues new emails for AI processing."""
    synced_count = sync_gmail_accounts(deps, principal.company_id)
    waiting = _waiting_for_processing(deps.engine, principal.company_id)
    message = f"Synced {synced_count} new messages."
    if waiting:
        message += f" {waiting} already fetched, still being processed."
    return {
        "synced": True,
        "newMessages": synced_count,
        "processing": waiting,
        "message": message,
        "syncedAt": datetime.now(UTC).isoformat(),
    }


def _waiting_for_processing(engine: Engine, company_id: UUID) -> int:
    """Gmail mail already fetched but not yet an inbox thread: raw events not stored, messages not yet understood."""
    with Session(engine) as session:
        unstored = session.scalar(
            select(func.count())
            .select_from(RawEvent)
            .where(
                RawEvent.company_id == company_id,
                RawEvent.provider == Channel.gmail,
                RawEvent.status == RawEventStatus.pending,
            )
        )
        unread = session.scalar(
            select(func.count())
            .select_from(MessageRow)
            .where(
                MessageRow.company_id == company_id,
                MessageRow.channel == Channel.gmail,
                MessageRow.direction == Direction.inbound,
                MessageRow.pipeline_status == PipelineStatus.pending,
            )
        )
    return (unstored or 0) + (unread or 0)


class CreateGmailDraftRequest(BaseModel):
    to_email: str
    subject: str
    body: str
    thread_id: str | None = None
    case_id: str | None = None


def _quoted_message(session: Session, req: CreateGmailDraftRequest, company_id: UUID) -> MessageRow | None:
    if req.thread_id:
        msg = session.scalars(
            select(MessageRow).where(MessageRow.company_id == company_id, MessageRow.thread_ref == req.thread_id)
        ).first()
        if msg is not None:
            return msg
    if not req.case_id:
        return None
    try:
        case_id = UUID(req.case_id.replace("case-", ""))
    except ValueError:
        return None
    link = session.scalars(
        select(CaseLink)
        .where(CaseLink.company_id == company_id, CaseLink.case_id == case_id)
        .order_by(CaseLink.created_at.desc())
    ).first()
    return session.get(MessageRow, link.message_id) if link else None


@router.post(
    "/create-draft",
    summary="Open a Gmail Thread or Compose Window for a Reply",
    description=(
        "Returns a Gmail URL for the existing mail chain (#all/<thread_id>) when replying to an email thread, "
        "or a fresh compose URL (?view=cm) when composing a brand-new email."
    ),
)
def create_gmail_draft(
    req: CreateGmailDraftRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    """Opens the existing Gmail thread when thread_id/msg.thread_ref exists; fresh compose only for new emails."""
    with Session(engine) as session:
        msg = _quoted_message(session, req, principal.company_id)
        in_reply_to = msg.meta.get("message_id") if msg is not None and isinstance(msg.meta, dict) else None
        resolved_thread = (req.thread_id or "").strip() or (
            msg.thread_ref if msg is not None and msg.channel == Channel.gmail else None
        )
    if resolved_thread:
        return {
            "ok": True,
            "threaded": True,
            "thread_id": resolved_thread,
            "web_url": f"https://mail.google.com/mail/#all/{urllib.parse.quote(resolved_thread)}",
        }
    sub = req.subject
    if in_reply_to and not sub.lower().startswith("re:"):
        sub = f"Re: {sub}"
    query = urllib.parse.urlencode({"view": "cm", "fs": "1", "to": req.to_email, "su": sub, "body": req.body})
    return {
        "ok": True,
        "threaded": False,
        "web_url": f"https://mail.google.com/mail/?{query}",
    }


def _quoted_inbound(
    session: Session, company_id: UUID, case_id: UUID, channel: Channel, ref: str | None
) -> UUID | None:
    """`ref` when it is an incoming message on `channel` that the case shows (linked, or in a linked thread)."""
    try:
        message_id = UUID(ref) if ref else None
    except ValueError:
        return None
    if message_id is None:
        return None
    linked = (
        select(MessageRow.id, MessageRow.thread_ref)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(CaseLink.company_id == company_id, CaseLink.case_id == case_id, MessageRow.company_id == company_id)
        .subquery()
    )
    return session.scalar(
        select(MessageRow.id).where(
            MessageRow.company_id == company_id,
            MessageRow.id == message_id,
            MessageRow.channel == channel,
            MessageRow.direction == Direction.inbound,
            MessageRow.id.in_(select(linked.c.id)) | MessageRow.thread_ref.in_(select(linked.c.thread_ref)),
        )
    )


class ThreadReplyRequest(BaseModel):
    body: str = Field(min_length=1, max_length=20000)
    channel: str | None = None
    reply_to_message_id: str | None = None
    confirm_suspicious: bool = False


@router.post(
    "/threads/{case_id}/reply",
    dependencies=[Depends(decide_limit)],
    summary="Send a Threaded Owner Reply on an Inbox Case",
    description=(
        "Records an owner-authored reply on a case and enqueues it for `app/sender` (`exec:{action_id}:1`), "
        "which replies inside the existing Gmail thread (with In-Reply-To/References) or WhatsApp window."
    ),
)
def send_thread_reply(
    case_id: str,
    req: ThreadReplyRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    client: Annotated[WorkflowClient, Depends(get_workflow_client)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    body_text = req.body.strip()
    if not body_text:
        raise HTTPException(status_code=422, detail="reply body cannot be blank")
    try:
        c_uuid = UUID(case_id.replace("case-", ""))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID") from None

    now = datetime.now(UTC)
    company_id = principal.company_id
    with Session(engine) as session, session.begin():
        case = session.scalar(select(Case).where(Case.id == c_uuid, Case.company_id == company_id))
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        company = session.get(Company, company_id)
        if company is not None and company.paused:
            raise HTTPException(status_code=409, detail="Company communications are paused.")

        chosen_channel = Channel.whatsapp if req.channel == Channel.whatsapp.value else Channel.gmail
        if req.channel is None:
            latest_in = session.scalar(
                select(MessageRow)
                .join(CaseLink, CaseLink.message_id == MessageRow.id)
                .where(
                    CaseLink.company_id == company_id,
                    CaseLink.case_id == c_uuid,
                    MessageRow.company_id == company_id,
                    MessageRow.direction == Direction.inbound,
                )
                .order_by(MessageRow.sent_at.desc())
                .limit(1)
            )
            if latest_in is not None and latest_in.channel in (Channel.gmail, Channel.whatsapp):
                chosen_channel = latest_in.channel

        # Same confirmation as approving a draft: with no quoted mail, any flagged mail on the case counts.
        if not req.confirm_suspicious and is_suspicious(
            session, company_id, ActionRow(id=new_id(), company_id=company_id, case_id=c_uuid, context_ref=[])
        ):
            raise HTTPException(status_code=409, detail="confirm_suspicious_required")
        quoted_id = _quoted_inbound(session, company_id, c_uuid, chosen_channel, req.reply_to_message_id)
        payload: dict[str, Any] = {
            "kind": "reply_draft",
            "channel": chosen_channel.value,
            "body_variants": [body_text],
        }
        action = ActionRow(
            company_id=company_id,
            case_id=c_uuid,
            type=ActionType.reply_draft,
            payload=payload,
            rationale="Owner reply from Inbox",
            # Only what the owner quoted. The draft guard compares it with the recipient (ADR 0016), so filling in
            # the latest sender here would make that comparison pass by itself.
            context_ref=[quoted_id] if quoted_id else [],
            draft_version=1,
            status=ActionStatus.approved,
        )
        session.add(action)
        session.flush()
        if req.reply_to_message_id:
            inbox_decide.remember_quote(session, action, req.reply_to_message_id)
        session.add(
            ActionRevision(
                company_id=company_id,
                action_id=action.id,
                draft_version=1,
                payload=dict(action.payload),
                edited_by="owner",
            )
        )
        session.add(
            Approval(
                company_id=company_id,
                action_id=action.id,
                draft_version=1,
                status=ApprovalStatus.approved,
                choice=ButtonChoice.d1,
                decided_at=now,
            )
        )
        inbox_decide.record_dispatch(session, case, action, now)
        action_id = action.id

    enqueue.enqueue_execute(client, action_id, 1, False)
    log.info("inbox.manual_reply_queued", case_id=str(c_uuid), action_id=str(action_id), channel=chosen_channel.value)
    return {
        "status": "approved",
        "actionId": str(action_id),
        "decision": "execute",
        "message": f"Reply queued for sending via {chosen_channel.value}.",
        "executedAt": now.isoformat(),
    }


@router.post(
    "/approvals/{approval_id}/decide",
    dependencies=[Depends(decide_limit)],
    summary="Decide Inbox Approval",
    description=(
        "Records Harjot's 1-click decision through the canonical approval path; an approved reply is queued for "
        "the sender (`exec:{action_id}:{draft_version}`), which sends it behind `outbound_mode`."
    ),
)
def decide_approval(
    approval_id: str,
    req: ApprovalDecideRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    client: Annotated[WorkflowClient, Depends(get_workflow_client)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    """Postgres first (decision, case state), then the send is enqueued by name (invariants 1 and 5). Only the
    signed-in owner's own company can be decided; a ref that names nothing of theirs is a 404."""
    choice = inbox_decide.CHOICES.get(req.choice, ButtonChoice.d1)
    if req.edited_text is not None and not req.edited_text.strip() and choice is not ButtonChoice.rej:
        raise HTTPException(status_code=422, detail="edited_text_blank")  # never fall back to a draft the owner cleared
    now = datetime.now(UTC)
    try:
        with Session(engine) as session, session.begin():
            target = inbox_decide.resolve(session, approval_id, principal.company_id)
            if target.approval is None or target.action is None:
                raise NotFoundError("approval not found")
            early = inbox_decide.guard(session, target, now)
            if early is not None:
                return early
            outcome = inbox_decide.decide(session, target, choice, req.edited_text, now)
            approved = outcome.decision is None or outcome.decision.kind == "execute"
            if target.action is not None and approved:
                inbox_decide.remember_quote(session, target.action, req.reply_to_message_id)
            if target.case is not None and approved and choice is not ButtonChoice.rej:
                inbox_decide.record_dispatch(session, target.case, target.action, now)
    except dashboard_decisions.SuspiciousNeedsConfirmError:
        raise HTTPException(status_code=409, detail="confirm_suspicious_required") from None
    except dashboard_decisions.NotEditableError:
        raise HTTPException(status_code=409, detail="approval_not_editable") from None
    except NotFoundError:
        raise HTTPException(status_code=404, detail="not found") from None
    decision = outcome.decision
    if decision is not None and decision.kind == "execute":  # after commit; DBOS dedupes a repeated id
        enqueue.enqueue_execute(client, decision.action_id, decision.draft_version, outcome.local)
    log.info("approval.decided", approval_id=approval_id, choice=req.choice, queued=decision is not None)
    return {
        "status": "rejected" if choice is ButtonChoice.rej else "approved",
        "approvalId": approval_id,
        "gmailDraftId": None,
        "gmailMessageId": None,
        "whatsappMessageId": None,
        "decision": decision.kind if decision is not None else "execute",
        "choice": req.choice,
        "message": (
            f"Successfully approved draft ({req.choice}); the reply is queued for sending."
            if decision is not None and decision.kind == "execute"
            else f"Recorded decision ({req.choice})."
        ),
        "executedAt": now.isoformat(),
    }


# Types a browser can show without running anything from the sender. Everything else (html, svg, xml, scripts, unknown)
# is downloaded as an opaque attachment: it came from an inbound email and must never execute on the API origin, which
# holds the session cookie.
INLINE_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp"})


@router.get(
    "/attachments/{attachment_id}",
    summary="Download or view an attachment file",
    dependencies=[Depends(require_section("inbox"))],
)
def get_attachment_file(
    attachment_id: UUID,
    engine: Annotated[Engine, Depends(get_engine)],
    storage: Annotated[ObjectStorage, Depends(get_storage)],
    principal: Annotated[Principal, Depends(require_session)],
) -> Response:
    with Session(engine) as session:
        att = session.scalars(
            select(AttachmentRow).where(
                AttachmentRow.id == attachment_id, AttachmentRow.company_id == principal.company_id
            )
        ).first()
        if not att:
            raise HTTPException(status_code=404, detail="Attachment not found")
        try:
            content = storage.get(att.s3_key)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="File not found in storage") from exc
        mime = (att.mime_type or "").split(";")[0].strip().lower()
        inline = mime in INLINE_TYPES
        filename = urllib.parse.quote(att.filename or "attachment", safe="")
        return Response(
            content=content,
            media_type=mime if inline else "application/octet-stream",
            headers={
                "Content-Disposition": f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{filename}",
                "X-Content-Type-Options": "nosniff",
            },
        )


def _linkable_sender(session: Session, company_id: UUID, case: Case, message_id: UUID) -> UUID:
    """The person "Link to Tenant" may move: the writer of the mail the screen named, which must still be the thread's
    latest incoming one. Linking moves their addresses, mail and cases, so it never guesses: only an unclassified
    contact with no lease and no BRIXX record, and never one of our own addresses."""
    messages = load_messages_batch(session, company_id, [case]).msgs_by_case.get(case.id, [])
    shown = next((m for m in reversed(messages) if m.direction != Direction.outbound), None)
    if shown is None or shown.id != message_id:
        raise HTTPException(status_code=409, detail="The thread has changed: reload it and try again")
    person_id = sender_person_ids(session, company_id, [shown]).get(shown.id)
    person = session.scalar(select(Person).where(Person.id == person_id, Person.company_id == company_id))
    if person is None:
        raise HTTPException(status_code=400, detail="That sender is not in the contact list yet")
    if _holds_our_address(session, company_id, person.id):
        raise HTTPException(status_code=409, detail="That sender is one of our own addresses and cannot be moved")
    leased = session.scalar(
        select(LeaseParty.id).where(LeaseParty.company_id == company_id, LeaseParty.person_id == person.id).limit(1)
    )
    if person.kind != PersonKind.other or person.trade or person.brixx_ref is not None or leased is not None:
        raise HTTPException(status_code=409, detail="That sender is already a known contact and cannot be moved")
    return person.id


def _is_tenant(session: Session, company_id: UUID, person_id: UUID) -> bool:
    person = session.scalar(select(Person).where(Person.id == person_id, Person.company_id == company_id))
    if person is None:
        return False
    leased = select(LeaseParty.id).where(LeaseParty.company_id == company_id, LeaseParty.person_id == person_id)
    return person.kind == PersonKind.tenant or session.scalar(leased.limit(1)) is not None


def _holds_our_address(session: Session, company_id: UUID, person_id: UUID) -> bool:
    """Linking moves a person's addresses, messages and cases, so it must never be one of the team's own."""
    engine = session.get_bind()
    ours = owner_addresses(engine, company_id) | company_mailboxes(engine, company_id)  # type: ignore[arg-type]
    held = session.scalars(
        select(ChannelIdentity.identity).where(
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.person_id == person_id,
            ChannelIdentity.valid_to.is_(None),
        )
    )
    return any(identity.lower() in ours for identity in held)


class LinkTenantRequest(BaseModel):
    tenant_id: UUID | None = None
    message_id: UUID  # the thread's `senderMessageId`: an action names what it acts on


@router.post(
    "/threads/{case_id}/link-tenant",
    summary="Link sender to Tenant as secondary contact",
    description=(
        "Attaches the sender identity to an active leaseholder as a secondary contact, preserving case history."
    ),
    dependencies=[Depends(require_section("inbox"))],
)
def link_thread_tenant(
    case_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    req: LinkTenantRequest,
) -> dict[str, Any]:
    company_id = principal.company_id
    raw_id = case_id.replace("case-", "")
    try:
        c_uuid = UUID(raw_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID") from None

    today = datetime.now(UTC).date()
    with Session(engine) as session, session.begin():
        case = session.scalar(select(Case).where(Case.id == c_uuid, Case.company_id == company_id))
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")

        source_person_id = _linkable_sender(session, company_id, case, req.message_id)

        target_tenant_id = req.tenant_id
        if not target_tenant_id and case.unit_id:
            target_tenant_id = session.scalar(
                select(LeaseParty.person_id)
                .join(Lease, Lease.id == LeaseParty.lease_id)
                .where(
                    Lease.unit_id == case.unit_id,
                    Lease.company_id == company_id,
                    (Lease.valid_to.is_(None)) | (Lease.valid_to >= today),
                )
            )

        if not target_tenant_id:
            raise HTTPException(status_code=400, detail="Target tenant ID required or unit has no active leaseholder")

        if not _is_tenant(session, company_id, target_tenant_id):
            raise HTTPException(status_code=400, detail="The target contact is not a tenant")

        linked_tenant = link_secondary_identity(
            session,
            company_id,
            source_person_id=source_person_id,
            target_tenant_id=target_tenant_id,
            today=today,
        )

        return {
            "ok": True,
            "tenantId": str(linked_tenant.id),
            "tenantName": linked_tenant.display_name,
        }


class ThreadReadRequest(BaseModel):
    read: bool = True


class ThreadSnoozeRequest(BaseModel):
    until: str | None = None


def _parse_case_uuid(case_id: str) -> UUID:
    try:
        return UUID(case_id.replace("case-", ""))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID") from None


@router.post(
    "/threads/{case_id}/read",
    summary="Mark Inbox Thread Read or Unread",
    dependencies=[Depends(require_section("inbox"))],
)
def mark_thread_read(
    case_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    req: ThreadReadRequest | None = None,
) -> dict[str, Any]:
    c_uuid = _parse_case_uuid(case_id)
    mark_read = req.read if req else True
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        case = session.scalar(select(Case).where(Case.id == c_uuid, Case.company_id == principal.company_id))
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        case.last_read_at = now if mark_read else None
    return {"ok": True, "caseId": str(c_uuid), "isRead": mark_read}


@router.post(
    "/threads/{case_id}/done",
    summary="Mark Inbox Thread Done",
    dependencies=[Depends(require_section("inbox"))],
)
def mark_thread_done(
    case_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    c_uuid = _parse_case_uuid(case_id)
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        case = session.scalar(select(Case).where(Case.id == c_uuid, Case.company_id == principal.company_id))
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        prev_state = case.state
        case.state = CaseState.closed
        case.resolved_at = now
        case.last_read_at = now
        case.snoozed_until = None
        if prev_state is not CaseState.closed:
            session.add(
                CaseEvent(
                    company_id=principal.company_id,
                    case_id=case.id,
                    kind=CaseEventKind.state_change,
                    from_state=prev_state,
                    to_state=CaseState.closed,
                    note="Owner marked inbox thread as done.",
                    actor="owner",
                )
            )
    return {"ok": True, "caseId": str(c_uuid), "status": "closed"}


@router.post(
    "/threads/{case_id}/snooze",
    summary="Snooze Inbox Thread",
    dependencies=[Depends(require_section("inbox"))],
)
def snooze_thread(
    case_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    req: ThreadSnoozeRequest | None = None,
) -> dict[str, Any]:
    c_uuid = _parse_case_uuid(case_id)
    now = datetime.now(UTC)
    if req and req.until:
        try:
            snooze_dt = datetime.fromisoformat(req.until)
            if snooze_dt.tzinfo is None:
                snooze_dt = snooze_dt.replace(tzinfo=UTC)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid snooze timestamp") from None
    else:
        tomorrow = (now + timedelta(days=1)).date()
        snooze_dt = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 8, 0, tzinfo=UTC)
    with Session(engine) as session, session.begin():
        case = session.scalar(select(Case).where(Case.id == c_uuid, Case.company_id == principal.company_id))
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        case.snoozed_until = snooze_dt
        case.last_read_at = now
        session.add(
            CaseEvent(
                company_id=principal.company_id,
                case_id=case.id,
                kind=CaseEventKind.note,
                note=f"Owner snoozed thread until {snooze_dt.isoformat()}.",
                actor="owner",
            )
        )
    return {"ok": True, "caseId": str(c_uuid), "snoozedUntil": snooze_dt.isoformat()}
