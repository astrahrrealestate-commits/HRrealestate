"""Inbox & Triage REST API Routes.

Feeds communications triage threads (Gmail & WhatsApp), AI multi-draft proposals,
audience filtering, and 1-click owner approval execution to the Next.js frontend.
"""

import contextlib
import hashlib
import re
import threading
import urllib.parse
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import Engine, exists, func, or_, select
from sqlalchemy import case as sql_case
from sqlalchemy.orm import Session

from app.api.deps import WorkflowClient, get_engine, get_ingest_deps, get_storage, get_workflow_client
from app.api.inbox import decide as inbox_decide
from app.api.inbox.summary import headline_only
from app.api.inbox.thread_batch import (
    ThreadDetailsBatch,
    ThreadMessagesBatch,
    inbox_stats_counts,
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
from app.channels.gmail.html_sanitize import (
    html_to_clean_text,
    looks_like_html,
    normalize_message_whitespace,
    sanitize_email_html,
)
from app.context.sender_label import UNASSIGNED_UNIT, resolve_sender_label, role_hint_of, unit_display
from app.context.shown_sender import sender_person_ids, shown_sender_name
from app.contracts import ActionType, ButtonChoice, CaseState, Category, Channel, Direction, OutboundMode, Urgency
from app.core.errors import NotFoundError
from app.core.ids import case_ref, new_id
from app.core.language import detect_language
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.db.enums import (
    ActionStatus,
    ApprovalStatus,
    CaseEventKind,
    PersonKind,
    PipelineStatus,
    RawEventStatus,
    SendStatus,
)
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
from app.pipeline import case_repo, dashboard_decisions
from app.pipeline.dashboard_decisions import is_suspicious
from app.pipeline.enhance import enhance_draft
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
    attachment_ids: list[str] = Field(default_factory=list, description="Optional uploaded attachment UUIDs")


# Rich default seeds so the frontend displays complete live data even before first email webhook arrives
DEFAULT_SEEDED_THREADS: list[dict[str, Any]] = []


def _is_contractor_case(case: Case, person: Any, sender_email: str, messages: list[MessageRow]) -> bool:
    return (
        (person is not None and person.kind == PersonKind.contractor)
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


_VARIANT_TAG_RE = re.compile(r"\s*\((?:Variant|Draft)\s+([12])\)\.?\s*$", re.IGNORECASE)


def _commitments_for_variant(raw_commitments: list[str], variant_idx: int) -> list[str]:
    """Filter commitments tagged for a specific variant (1 or 2) and strip the `(Variant N)` suffix."""
    out: list[str] = []
    for item in raw_commitments:
        text = item.strip()
        if not text:
            continue
        match = _VARIANT_TAG_RE.search(text)
        if match is not None:
            if int(match.group(1)) != variant_idx:
                continue
            cleaned = text[: match.start()].rstrip(" .")
            if text.endswith(".") and not cleaned.endswith("."):
                cleaned += "."
            text = cleaned
        if text and text not in out:
            out.append(text)
    return out


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
        variants = (reply_action.payload.get("body_variants") or [])[:2]
        raw_commitments = [str(c) for c in reply_action.payload.get("commitments") or []]
        if not variants and reply_action.payload.get("text"):
            variants = [reply_action.payload["text"]]
        elif not variants and reply_action.payload.get("body"):
            variants = [reply_action.payload["body"]]

        for idx, text in enumerate(variants, start=1):
            commitments = _commitments_for_variant(raw_commitments, idx)
            gmail_drafts.append(
                {
                    "id": f"gd{idx}",
                    "label": f"Draft {idx} (Recommended)" if idx == 1 else f"Draft {idx} (Alternative)",
                    "channel": "gmail",
                    "text": text,
                    "commitments": commitments,  # every promise the draft makes, shown next to Approve (M13)
                }
            )
            whatsapp_drafts.append(
                {
                    "id": f"wd{idx}",
                    "label": f"WhatsApp {idx} (Quick Confirmation)" if idx == 1 else f"WhatsApp {idx} (Detailed)",
                    "channel": "whatsapp",
                    "text": text,
                    "commitments": commitments,  # every promise the draft makes, shown next to Approve (M13)
                }
            )

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


@lru_cache(maxsize=512)
def _cached_resanitized(stored_html: str) -> str | None:
    """Stored HTML cleaned by the current sanitizer, cached across inbox polls."""
    return sanitize_email_html(stored_html)


@lru_cache(maxsize=512)
def _cached_clean_and_html(raw_text: str, need_html: bool) -> tuple[str | None, str]:
    """Cache HTML sanitization and whitespace-normalized text across 8s inbox polls."""
    if not looks_like_html(raw_text):
        return None, normalize_message_whitespace(raw_text)
    clean_body = html_to_clean_text(raw_text)
    html_body = sanitize_email_html(raw_text) if need_html else None
    return html_body, clean_body


def _assemble_thread(
    prep: _PreparedCase,
    msg_batch: ThreadMessagesBatch,
    details: ThreadDetailsBatch,
    *,
    company_tz: ZoneInfo,
    now_dt: datetime,
    include_html: bool = True,
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
        meta_html = _cached_resanitized(stored_html) if isinstance(stored_html, str) else None
        raw_text = m.text or ""
        raw_html: str | None = None
        if include_html:
            if meta_html:
                raw_html = meta_html
                _, clean_body = _cached_clean_and_html(raw_text, False)
            else:
                raw_html, clean_body = _cached_clean_and_html(raw_text, True)
        else:
            _, clean_body = _cached_clean_and_html(raw_text, False)
        to_list = m_meta.get("to") if isinstance(m_meta.get("to"), list) else []
        if not to_list and m_is_incoming and isinstance(m_meta.get("mailbox"), str):
            to_list = [m_meta["mailbox"]]
        cc_list = m_meta.get("cc") if isinstance(m_meta.get("cc"), list) else []
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
                "to": to_list,
                "cc": cc_list,
            }
        )

    is_send_mode = msg_batch.company is not None and msg_batch.company.outbound_mode is OutboundMode.send
    if is_send_mode:
        for act in actions:
            if act.type is not ActionType.reply_draft:
                continue
            act_approvals = details.approvals_by_action.get(act.id, ())
            approved_ap = next((ap for ap in act_approvals if ap.status == ApprovalStatus.approved), None)
            choice = approved_ap.choice if approved_ap and approved_ap.choice else ButtonChoice.d1
            choice_idx = {ButtonChoice.d2: 1, ButtonChoice.d3: 2}.get(choice, 0)
            act_payload = act.payload if isinstance(act.payload, dict) else {}
            variants = act_payload.get("body_variants") or []
            body_txt = variants[min(choice_idx, len(variants) - 1)] if variants else "Replied to tenant."
            for s in details.sends_by_action.get(act.id, ()):
                if s.status is not SendStatus.sent or s.channel is Channel.dashboard:
                    continue
                if any(
                    not m.get("isIncoming") and (m.get("body") or "").strip() == body_txt.strip() for m in msgs_data
                ):
                    continue
                s_dt = s.attempted_at or now_dt
                if s_dt.tzinfo is None:
                    s_dt = s_dt.replace(tzinfo=UTC)
                s_time_fmt = when_label(s_dt, now_dt, company_tz)
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
                        "senderContact": owner_email if s.channel is Channel.gmail else "+31 20 000 0001",
                        "sentAt": s_iso,
                        "timeFormatted": s_time_fmt,
                        "content": body_txt,
                        "body": body_txt,
                        "isIncoming": False,
                        "channel": s.channel.value if s.channel else "whatsapp",
                        "subject": act_payload.get("subject") or "Reply",
                        "to": [s.target] if s.target else [],
                        "cc": [],
                        "replyTo": reply_to_info,
                    }
                )

    msgs_data.sort(key=lambda x: x.get("sentAt", ""))
    last_msg_is_owner = bool(msgs_data) and msgs_data[-1].get("sender") == "owner"
    has_pending_reply = (
        approval is not None and approval.status == ApprovalStatus.pending and bool(gmail_drafts or whatsapp_drafts)
    )
    has_pending_action = any(a.status in (ActionStatus.pending_approval, ActionStatus.exception) for a in actions)
    requires_reply = und_body.get("requires_reply") if isinstance(und_body, dict) else None
    status_str = "needs_approval"
    if case.state in (CaseState.closed, CaseState.resolved):
        status_str = "closed"
    elif has_pending_reply and not last_msg_is_owner:
        status_str = "needs_approval"
    elif (approval and approval.status == ApprovalStatus.approved) or last_msg_is_owner:
        status_str = "approved"
    elif approval and approval.status == ApprovalStatus.rejected:
        status_str = "rejected"
    elif approval is None and not has_pending_action and requires_reply is False:
        status_str = "fyi"

    last_read = getattr(case, "last_read_at", None)
    if last_read is not None and last_read.tzinfo is None:
        last_read = last_read.replace(tzinfo=UTC)
    is_read = bool(last_msg_is_owner or (last_read is not None and last_read >= sent_dt) or status_str == "closed")
    snoozed_until = getattr(case, "snoozed_until", None)
    subject_str = (
        prep.latest_msg.meta.get("subject") if isinstance(prep.latest_msg.meta, dict) else None
    ) or " - ".join(filter(None, (case.category.value.title(), unit_label)))
    hide_drafts = status_str == "approved" or last_msg_is_owner
    ticket_code = f"BRIXX-{case.brixx_ref}" if case.brixx_ref else f"#{case_ref(case.id)}"

    latest_raw_text = prep.latest_msg.text or ""
    _, latest_clean_snippet = _cached_clean_and_html(latest_raw_text, False)

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


def _assemble_cases(
    session: Session,
    company_id: UUID,
    cases: list[Case],
    *,
    has_filters: bool = False,
    channel: str = "all",
    audience: str = "all",
    category: str = "all",
    limit: int = 20,
    offset: int = 0,
    include_html: bool = True,
) -> list[dict[str, Any]]:
    """Hydrates a list of Case rows into frontend thread dicts."""
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

    live_threads = [
        _assemble_thread(p, msg_batch, details, company_tz=company_tz, now_dt=now_dt, include_html=include_html)
        for p in prepared
    ]
    all_msgs = [m for t in live_threads for m in t["messages"]]
    all_drafts = [d for t in live_threads for d in (*t["gmailDrafts"], *t["whatsappDrafts"])]
    annotate_translations(session, company_id, all_msgs, all_drafts)
    return live_threads


def _period_bounds(
    period: str, now_dt: datetime, tz_name: str = "Europe/Amsterdam"
) -> tuple[datetime, datetime] | None:
    """UTC `[start, end)` bounds for `this_week`, `YYYY-MM`, or `YYYY`; None for `all` or invalid."""
    p = (period or "all").strip().lower()
    if not p or p == "all":
        return None
    tz = ZoneInfo(tz_name)
    if p == "this_week":
        return (now_dt - timedelta(days=7), now_dt + timedelta(days=1))
    if len(p) == 7 and p[4] == "-":
        try:
            year_s, month_s = p.split("-", 1)
            y, m = int(year_s), int(month_s)
            _, last_day = monthrange(y, m)
            start = datetime(y, m, 1, tzinfo=tz).astimezone(UTC)
            end = (datetime(y, m, last_day, tzinfo=tz) + timedelta(days=1)).astimezone(UTC)
            return (start, end)
        except ValueError:
            return None
    if len(p) == 4 and p.isdigit():
        y = int(p)
        start = datetime(y, 1, 1, tzinfo=tz).astimezone(UTC)
        end = datetime(y + 1, 1, 1, tzinfo=tz).astimezone(UTC)
        return (start, end)
    return None


def _inbox_base_query(
    session: Session,
    company_id: UUID,
    *,
    category: str = "all",
    tab: str = "all",
    urgency: str = "all",
    period: str = "all",
    search: str = "",
    sort: str = "recent",
    now_dt: datetime,
) -> Any:
    base_q = session.query(Case).filter(Case.company_id == company_id)
    if category not in ("all", "contractor_repairs", "contractor_money"):
        with contextlib.suppress(ValueError):
            base_q = base_q.filter(Case.category == Category(category))
    if urgency == "emergency":
        base_q = base_q.filter(Case.urgency == Urgency.emergency)
    elif urgency == "high":
        base_q = base_q.filter(Case.urgency == Urgency.high)
    elif urgency == "low":
        base_q = base_q.filter(Case.urgency.in_((Urgency.normal, Urgency.low)))
    elif urgency == "urgent":
        base_q = base_q.filter(Case.urgency.in_((Urgency.emergency, Urgency.high)))
    if tab == "done":
        base_q = base_q.filter(Case.state.in_((CaseState.closed, CaseState.resolved)))
    elif tab == "snoozed":
        base_q = base_q.filter(Case.snoozed_until.is_not(None), Case.snoozed_until > now_dt)
    elif tab == "unread":
        base_q = base_q.filter(
            Case.last_read_at.is_(None),
            ~Case.state.in_((CaseState.closed, CaseState.resolved)),
        )
    elif tab == "needs_you":
        base_q = base_q.filter(
            ~Case.state.in_((CaseState.closed, CaseState.resolved)),
            or_(Case.snoozed_until.is_(None), Case.snoozed_until <= now_dt),
        )
    q_text = search.strip()
    if q_text:
        pat = f"%{q_text}%"
        msg_match = exists(
            select(1)
            .select_from(CaseLink)
            .join(MessageRow, MessageRow.id == CaseLink.message_id)
            .where(
                CaseLink.case_id == Case.id,
                MessageRow.company_id == company_id,
                or_(
                    MessageRow.sender_identity.ilike(pat),
                    MessageRow.text.ilike(pat),
                    MessageRow.meta["subject"].astext.ilike(pat),
                ),
            )
        )
        person_match = exists(
            select(1)
            .select_from(Person)
            .where(
                Person.id == Case.primary_person_id,
                Person.company_id == company_id,
                Person.display_name.ilike(pat),
            )
        )
        base_q = base_q.filter(or_(Case.summary.ilike(pat), msg_match, person_match))
    latest_msg_at = (
        select(func.max(MessageRow.sent_at))
        .select_from(CaseLink)
        .join(MessageRow, MessageRow.id == CaseLink.message_id)
        .where(CaseLink.case_id == Case.id, MessageRow.company_id == company_id)
        .correlate(Case)
        .scalar_subquery()
    )
    activity_at = func.coalesce(latest_msg_at, Case.opened_at)
    bounds = _period_bounds(period, now_dt)
    if bounds is not None:
        base_q = base_q.filter(activity_at >= bounds[0], activity_at < bounds[1])
    if sort == "priority":
        closed_rank = sql_case((Case.state.in_((CaseState.closed, CaseState.resolved)), 1), else_=0)
        urgency_rank = sql_case(
            (Case.urgency == Urgency.emergency, 0),
            (Case.urgency == Urgency.high, 1),
            (Case.urgency == Urgency.normal, 2),
            else_=3,
        )
        base_q = base_q.order_by(closed_rank.asc(), urgency_rank.asc(), activity_at.desc())
    elif sort == "oldest":
        base_q = base_q.order_by(activity_at.asc())
    else:
        base_q = base_q.order_by(activity_at.desc())
    return base_q


def _build_live_threads(
    session: Session,
    company_id: UUID,
    limit: int = 20,
    offset: int = 0,
    *,
    channel: str = "all",
    audience: str = "all",
    category: str = "all",
    tab: str = "all",
    urgency: str = "all",
    period: str = "all",
    search: str = "",
    sort: str = "recent",
    include_html: bool = True,
) -> list[dict[str, Any]]:
    """Builds frontend-compatible thread structures from PostgreSQL via batched read-only queries."""
    has_python_filters = channel != "all" or audience != "all" or category in ("contractor_repairs", "contractor_money")
    now_dt = datetime.now(UTC)
    base_q = _inbox_base_query(
        session,
        company_id,
        category=category,
        tab=tab,
        urgency=urgency,
        period=period,
        search=search,
        sort=sort,
        now_dt=now_dt,
    )

    if not has_python_filters:
        cases = base_q.offset(offset).limit(limit).all()
        return _assemble_cases(
            session,
            company_id,
            cases,
            has_filters=False,
            channel=channel,
            audience=audience,
            category=category,
            limit=limit,
            offset=0,
            include_html=include_html,
        )

    # Scan in bounded SQL chunks rather than loading every case for the company into Python memory.
    needed = offset + limit
    batch_size = min(max(needed * 2, 100), 200)
    sql_offset = 0
    kept_prepared: list[_PreparedCase] = []
    last_msg_batch: ThreadMessagesBatch | None = None
    now_dt = datetime.now(UTC)

    while len(kept_prepared) < needed:
        chunk = base_q.offset(sql_offset).limit(batch_size).all()
        if not chunk:
            break
        sql_offset += len(chunk)
        msg_batch = load_messages_batch(session, company_id, chunk)
        last_msg_batch = msg_batch
        matched = _prepare_cases(
            chunk,
            msg_batch,
            has_filters=True,
            channel=channel,
            audience=audience,
            category=category,
            limit=needed - len(kept_prepared),
            offset=0,
        )
        kept_prepared.extend(matched)
        if len(chunk) < batch_size:
            break

    page_prepared = kept_prepared[offset:needed]
    if not page_prepared or last_msg_batch is None:
        return []

    # Re-load message batch only for the final page so ThreadMessagesBatch maps match all kept cases across chunks.
    page_cases = [p.case for p in page_prepared]
    final_msg_batch = load_messages_batch(session, company_id, page_cases)
    company_tz = ZoneInfo(final_msg_batch.company.timezone if final_msg_batch.company else "Europe/Amsterdam")
    kept_case_ids = [p.case.id for p in page_prepared]
    kept_msg_ids = [m.id for p in page_prepared for m in p.messages]
    unit_labels = {p.raw_unit_label for p in page_prepared if p.raw_unit_label != UNASSIGNED_UNIT}
    details = load_details_batch(session, company_id, kept_case_ids, kept_msg_ids, unit_labels, now_dt.date())

    live_threads = [
        _assemble_thread(p, final_msg_batch, details, company_tz=company_tz, now_dt=now_dt, include_html=include_html)
        for p in page_prepared
    ]
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
    category: str = Query(default="all", description="all, maintenance, finance, legal, or contractor_*"),
    tab: str = Query(default="all", description="all, needs_you, unread, done, snoozed"),
    urgency: str = Query(default="all", description="all, emergency, high, low"),
    period: str = Query(default="all", description="all, this_week, YYYY-MM, or YYYY"),
    search: str = Query(default="", description="Filter by sender, subject, or summary"),
    sort: str = Query(default="recent", description="recent, oldest, or priority"),
    limit: int = Query(default=20, ge=1, le=100, description="Max threads to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    include_html: bool = Query(default=True, description="Include sanitized HTML email bodies"),
    *,
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    """Retrieves inbox threads enriched with agent-drafted proposals."""
    # Safe parameter normalization (handles both FastAPI dependency injection and direct calls)
    chan = channel if isinstance(channel, str) else getattr(channel, "default", "all")
    aud = audience if isinstance(audience, str) else getattr(audience, "default", "all")
    cat = category if isinstance(category, str) else getattr(category, "default", "all")
    tab_val = tab if isinstance(tab, str) else getattr(tab, "default", "all")
    urg_val = urgency if isinstance(urgency, str) else getattr(urgency, "default", "all")
    period_val = period if isinstance(period, str) else getattr(period, "default", "all")
    search_val = search if isinstance(search, str) else getattr(search, "default", "")
    sort_mode = sort if isinstance(sort, str) else getattr(sort, "default", "recent")
    lim = limit if isinstance(limit, int) else getattr(limit, "default", 20)
    off = offset if isinstance(offset, int) else getattr(offset, "default", 0)
    inc_html = include_html if isinstance(include_html, bool) else getattr(include_html, "default", True)

    with Session(engine) as session:
        live_threads = _build_live_threads(
            session,
            principal.company_id,
            limit=lim,
            offset=off,
            channel=chan,
            audience=aud,
            category=cat,
            tab=tab_val,
            urgency=urg_val,
            period=period_val,
            search=search_val,
            sort=sort_mode,
            include_html=inc_html,
        )
        raw_total = _inbox_base_query(
            session,
            principal.company_id,
            category=cat,
            tab=tab_val,
            urgency=urg_val,
            period=period_val,
            search=search_val,
            sort=sort_mode,
            now_dt=datetime.now(UTC),
        ).count()
        total_cases = raw_total if isinstance(raw_total, int) else 0
        month_col = func.to_char(func.timezone("Europe/Amsterdam", MessageRow.sent_at), "YYYY-MM")
        month_rows = session.scalars(
            select(month_col).where(MessageRow.company_id == principal.company_id).group_by(month_col)
        ).all()
        available_periods = (
            sorted([r for r in month_rows if isinstance(r, str)], reverse=True) if isinstance(month_rows, list) else []
        )
    if not principal.access.can("inbox"):
        live_threads = [headline_only(t) for t in live_threads]

    threads = list(live_threads)

    has_python_filters = chan != "all" or aud != "all" or cat in ("contractor_repairs", "contractor_money")
    has_more = (off + len(live_threads)) < total_cases if not has_python_filters else len(live_threads) == lim
    return {
        "threads": threads,
        "total": total_cases,
        "has_more": has_more,
        "offset": off,
        "limit": lim,
        "availablePeriods": available_periods,
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


@router.get(
    "/threads/{case_id}",
    summary="Get Single Inbox Thread",
    description="Fetches one communications thread by case ID (used for direct deep-links from Today/Dashboard).",
)
def get_inbox_thread(
    case_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    """Fetches a single thread by case ID regardless of pagination offset."""
    clean_id = case_id.replace("case-", "")
    try:
        c_uuid = UUID(clean_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID") from None

    with Session(engine) as session:
        case = session.scalar(select(Case).where(Case.company_id == principal.company_id, Case.id == c_uuid))
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        built = _assemble_cases(session, principal.company_id, [case], limit=1)
    if not built:
        raise HTTPException(status_code=404, detail="Thread not available")
    thread = built[0]
    if not principal.access.can("inbox"):
        thread = headline_only(thread)
    return {"thread": thread}


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


_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_WA_IMAGE_LIMIT = 16 * 1024 * 1024


def _owned_attachment_ids(session: Session, company_id: UUID, raw_ids: list[str]) -> list[str]:
    parsed: list[UUID] = []
    for raw in raw_ids:
        try:
            parsed.append(UUID(str(raw)))
        except ValueError:
            continue
    if not parsed:
        return []
    found = set(
        session.scalars(
            select(AttachmentRow.id).where(AttachmentRow.company_id == company_id, AttachmentRow.id.in_(parsed))
        ).all()
    )
    return [str(aid) for aid in parsed if aid in found]


@router.post(
    "/threads/{case_id}/attachments",
    summary="Upload an Attachment for Outbound Reply + Drive/RAG Filing",
    description=(
        "Stores an attachment once in ObjectStorage, links it to the thread, and enqueues background classification, "
        "RAG chunk indexing, and Google Drive upload into `EstateOS/<unit>/<kind>/<year>/`."
    ),
)
async def upload_thread_attachment(
    case_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    storage: Annotated[ObjectStorage, Depends(get_storage)],
    client: Annotated[WorkflowClient, Depends(get_workflow_client)],
    principal: Annotated[Principal, Depends(require_session)],
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    try:
        c_uuid = UUID(case_id.replace("case-", ""))
    except ValueError:
        raise HTTPException(status_code=404, detail="Thread not found") from None

    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=422, detail="File is empty.")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 25 MB limit.")

    company_id = principal.company_id
    raw_name = (file.filename or "attachment").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._") or "attachment"
    mime_type = (file.content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    att_id = new_id()
    s3_key = f"attachments/{company_id}/{c_uuid}/{att_id}/{safe_name[:120]}"
    sha256 = hashlib.sha256(raw).hexdigest()

    with Session(engine) as session, session.begin():
        case = session.scalar(select(Case).where(Case.id == c_uuid, Case.company_id == company_id))
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        msg_id = session.scalar(
            select(CaseLink.message_id)
            .where(CaseLink.company_id == company_id, CaseLink.case_id == c_uuid)
            .order_by(CaseLink.created_at.desc())
            .limit(1)
        )
        if msg_id is None:
            raise HTTPException(status_code=422, detail="Thread has no message to attach files to yet.")
        storage.put(s3_key, raw, mime_type)
        session.add(
            AttachmentRow(
                id=att_id,
                company_id=company_id,
                message_id=msg_id,
                s3_key=s3_key,
                mime_type=mime_type[:255],
                filename=raw_name[:255],
                size_bytes=len(raw),
                sha256=sha256,
            )
        )

    enqueue.enqueue_document(client, company_id, att_id)
    is_image = mime_type.startswith("image/")
    whatsapp_allowed = (len(raw) <= _WA_IMAGE_LIMIT) if is_image else True
    return {
        "ok": True,
        "attachmentId": str(att_id),
        "filename": raw_name[:255],
        "mimeType": mime_type,
        "sizeBytes": len(raw),
        "gmailAllowed": True,
        "whatsappAllowed": whatsapp_allowed,
        "driveQueued": True,
    }


class ThreadReplyRequest(BaseModel):
    body: str = Field(min_length=1, max_length=20000)
    channel: str | None = None
    reply_to_message_id: str | None = None
    confirm_suspicious: bool = False
    attachment_ids: list[str] = Field(default_factory=list)


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
        owned_atts = _owned_attachment_ids(session, company_id, req.attachment_ids)
        payload: dict[str, Any] = {
            "kind": "reply_draft",
            "channel": chosen_channel.value,
            "body_variants": [body_text],
            **({"attachment_ids": owned_atts} if owned_atts else {}),
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


class EnhanceDraftRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=500, description="How to improve or redraft the reply")
    current_text: str = Field(default="", max_length=8000, description="Current text in the composer")
    message_id: str | None = Field(default=None, description="Optional target message UUID on this thread")


@router.post(
    "/threads/{case_id}/enhance",
    summary="Enhance or Redraft Reply with AI",
    description=(
        "Plans any missing RAG/mail/web/DB lookups from the owner's instruction, enriches the message dossier, "
        "runs the quality proposer, and updates or creates the pending draft approval."
    ),
)
def enhance_thread_draft(
    case_id: str,
    req: EnhanceDraftRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    """Instruction-aware redraft for Inbox Gmail and WhatsApp composers."""
    try:
        c_uuid = UUID(case_id.removeprefix("case-"))
    except ValueError:
        raise HTTPException(status_code=404, detail="Thread not found") from None
    m_uuid: UUID | None = None
    if req.message_id:
        try:
            m_uuid = UUID(req.message_id.removeprefix("msg-"))
        except ValueError:
            m_uuid = None
    res = enhance_draft(
        engine,
        get_settings(),
        principal.company_id,
        c_uuid,
        instruction=req.instruction,
        current_text=req.current_text,
        message_id=m_uuid,
    )
    if not res.ok:
        raise HTTPException(status_code=422, detail=res.problem or "Could not enhance draft.")
    raw_commitments = list(res.commitments)
    per_variant = [_commitments_for_variant(raw_commitments, idx) for idx in (1, 2)]
    return {
        "ok": True,
        "draftText": res.variants[0] if res.variants else "",
        "variants": list(res.variants),
        "commitments": per_variant[0],
        "commitmentsByVariant": per_variant,
        "approvalId": str(res.approval_id) if res.approval_id else None,
        "draftVersion": res.draft_version,
        "sourcesUsed": list(res.sources_used),
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
            owned_atts = _owned_attachment_ids(session, principal.company_id, req.attachment_ids)
            if owned_atts and target.action is not None:
                target.action.payload = {**target.action.payload, "attachment_ids": owned_atts}
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
        case_repo.close_case_pending(session, principal.company_id, case.id)
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
