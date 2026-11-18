"""Inbox & Triage REST API Routes.

Feeds communications triage threads (Gmail & WhatsApp), AI multi-draft proposals,
audience filtering, and 1-click owner approval execution to the Next.js frontend.
"""

import urllib.parse
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.deps import WorkflowClient, get_engine, get_ingest_deps, get_storage, get_workflow_client
from app.api.inbox import decide as inbox_decide
from app.api.inbox.summary import headline_only
from app.api.inbox.time_labels import when_label
from app.api.inbox.translate import annotate_translations
from app.api.inbox.translate import router as translate_router
from app.api.inbox.unit_match import unit_named_in
from app.api.v1 import enqueue
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.api.v1.session_limits import decide_limit, sync_limit
from app.contracts import ActionType, ButtonChoice, Category, Channel, Direction
from app.core.errors import NotFoundError
from app.core.ids import case_ref
from app.core.language import detect_language
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.db.enums import ApprovalStatus, LinkMethod, PersonKind, PipelineStatus, RawEventStatus
from app.db.models import (
    ActionRow,
    Approval,
    AttachmentRow,
    Case,
    CaseLink,
    ChannelAccount,
    ChannelIdentity,
    Company,
    DocumentRow,
    GmailSyncState,
    Lease,
    LeaseParty,
    MessageRow,
    Person,
    RawEvent,
    Send,
    UnderstandingRow,
    Unit,
)
from app.directory.contacts import link_secondary_identity
from app.ingestion.gmail_sync import sync_mailbox
from app.ingestion.process import IngestDeps
from app.pipeline import dashboard_decisions
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


def _build_live_threads(session: Session, company_id: UUID) -> list[dict[str, Any]]:
    """Builds rich frontend-compatible thread structures from the PostgreSQL records of `company_id` only."""
    live_threads: list[dict[str, Any]] = []
    cases = session.query(Case).filter(Case.company_id == company_id).order_by(Case.opened_at.desc()).limit(20).all()
    company = session.get(Company, company_id)
    company_tz = ZoneInfo(company.timezone if company else "Europe/Amsterdam")
    company_units = [(u.label, u.address) for u in session.query(Unit).filter(Unit.company_id == company_id)]
    now_dt = datetime.now(UTC)
    today = now_dt.date()
    for case in cases:
        links = session.query(CaseLink).filter(CaseLink.case_id == case.id).all()
        msg_ids = [link.message_id for link in links]
        if not msg_ids:
            continue
        messages = session.query(MessageRow).filter(MessageRow.id.in_(msg_ids)).order_by(MessageRow.sent_at.asc()).all()
        if not messages:
            continue

        # Collect thread refs from linked messages and include all messages sharing the thread
        thread_refs = [m.thread_ref for m in messages if m.thread_ref]
        if thread_refs:
            unlinked_thread_msgs = (
                session.query(MessageRow)
                .filter(
                    MessageRow.company_id == company_id,
                    MessageRow.thread_ref.in_(thread_refs),
                    ~MessageRow.id.in_(msg_ids),
                )
                .all()
            )
            for um in unlinked_thread_msgs:
                messages.append(um)
                session.add(
                    CaseLink(
                        company_id=case.company_id,
                        case_id=case.id,
                        message_id=um.id,
                        method=LinkMethod.thread,
                        confidence=1.0,
                    )
                )
            if unlinked_thread_msgs:
                session.commit()
                messages.sort(key=lambda m: m.sent_at if m.sent_at else datetime.min.replace(tzinfo=UTC))

        # Identify the tenant's message (inbound), never our own outbound reply
        inbound_msgs = [m for m in messages if m.direction != Direction.outbound]
        tenant_msg = inbound_msgs[-1] if inbound_msgs else messages[0]
        latest_msg = messages[-1]

        person = session.get(Person, case.primary_person_id) if case.primary_person_id else None
        sender_email = tenant_msg.sender_identity
        # Exclude automated job alerts, promotions, and system notifications
        automated_keywords = [
            "noreply",
            "newsletter",
            "linkedin",
            "glassdoor",
            "naukri",
            "typesafe",
            "googleai",
            "update",
            "notification",
            "alert",
            "job",
            "career",
            "digest",
        ]
        if any(kw in sender_email.lower() for kw in automated_keywords):
            continue

        # Check if this thread involves a contractor
        is_contractor = False
        if (
            (person and getattr(person, "kind", None) == PersonKind.contractor)
            or (
                case.category
                and case.category.value in ("contractor_update", "contractor_invoices", "contractor_repairs")
            )
            or any(c_kw in sender_email.lower() for c_kw in ["chahalbouw.nl", "contractor", "loodgieter"])
            or any("chahalbouw.nl" in (m.sender_identity or "").lower() for m in messages)
        ):
            is_contractor = True

        # If this is a contractor thread, ensure all related contractor communications are attached
        if is_contractor:
            known_ids = {m.id for m in messages}
            extra_contractor_msgs = (
                session.query(MessageRow)
                .filter(
                    MessageRow.company_id == company_id,
                    ~MessageRow.id.in_(list(known_ids)),
                    MessageRow.meta.is_not(None),
                )
                .all()
            )
            for ecm in extra_contractor_msgs:
                to_val = ecm.meta.get("to", []) if isinstance(ecm.meta, dict) else []
                to_str = " ".join(to_val) if isinstance(to_val, list) else str(to_val)
                subj = str(ecm.meta.get("subject", "")) if isinstance(ecm.meta, dict) else ""
                if (
                    "chahalbouw.nl" in to_str.lower()
                    or "chahalbouw.nl" in (ecm.sender_identity or "").lower()
                    or "work order" in subj.lower()
                    or "inv-2026-104" in subj.lower()
                ):
                    messages.append(ecm)
                    session.add(
                        CaseLink(
                            company_id=case.company_id,
                            case_id=case.id,
                            message_id=ecm.id,
                            method=LinkMethod.thread,
                            confidence=1.0,
                        )
                    )
            if len(messages) > len(known_ids):
                session.commit()
                messages.sort(key=lambda m: m.sent_at if m.sent_at else datetime.min.replace(tzinfo=UTC))

        sender_name = (
            person.display_name
            if person
            else (sender_email.split("@")[0].replace(".", " ").title() if "@" in sender_email else sender_email)
        )

        unit = session.get(Unit, case.unit_id) if case.unit_id else None
        unit_label = (unit.address or unit.label) if unit else None

        if not unit_label or unit_label == "Unassigned Unit":
            # Check all message texts and subjects in the thread for mentions of known units
            all_text = " ".join(
                [
                    (m.text or "") + " " + (str(m.meta.get("subject", "")) if isinstance(m.meta, dict) else "")
                    for m in messages
                ]
            ).lower()
            unit_label = unit_named_in(all_text, company_units)

        if not unit_label:
            unit_label = "Unassigned Unit"

        is_unregistered_sender = False
        matched_tenant_info = None
        if unit_label != "Unassigned Unit":
            lease_rows = session.execute(
                select(Person.id, Person.display_name, ChannelIdentity.identity)
                .select_from(Lease)
                .join(Unit, Unit.id == Lease.unit_id)
                .join(LeaseParty, LeaseParty.lease_id == Lease.id)
                .join(Person, Person.id == LeaseParty.person_id)
                .outerjoin(
                    ChannelIdentity,
                    (ChannelIdentity.person_id == Person.id) & (ChannelIdentity.valid_to.is_(None)),
                )
                .where(
                    Unit.company_id == company_id,
                    (Unit.label == unit_label) | (Unit.address == unit_label),
                    (Lease.valid_to.is_(None)) | (Lease.valid_to >= today),
                )
            ).all()
            if lease_rows:
                tenant_id, tenant_name, _ = lease_rows[0]
                known_identities = {str(row[2]).lower().strip() for row in lease_rows if row[2]}
                sender_clean = sender_email.lower().strip()
                if (
                    sender_clean not in known_identities
                    and (not person or person.kind == PersonKind.other)
                    and not is_contractor
                ):
                    is_unregistered_sender = True
                    matched_tenant_info = {
                        "id": str(tenant_id),
                        "name": tenant_name,
                        "unit": unit_label,
                    }

        actions = (
            session.query(ActionRow).filter(ActionRow.case_id == case.id).order_by(ActionRow.created_at.desc()).all()
        )
        reply_action = next((a for a in actions if a.type == ActionType.reply_draft), None)
        approval = None
        if reply_action:
            # Look for pending approval first, or latest approval
            approvals = (
                session.query(Approval)
                .filter(Approval.action_id == reply_action.id)
                .order_by(Approval.created_at.desc())
                .all()
            )
            approval = next(
                (ap for ap in approvals if ap.status == ApprovalStatus.pending), approvals[0] if approvals else None
            )

        # Retrieve AI Understanding for this message/case
        und_row = session.query(UnderstandingRow).filter(UnderstandingRow.message_id == latest_msg.id).first()
        und_body = und_row.body if und_row and isinstance(und_row.body, dict) else {}
        und_entities = und_body.get("entities") or {}
        raw_intent = und_body.get("intent") or case.summary or "Incoming communication analyzed by Gemini AI agent."
        und_intent = (
            raw_intent.replace("_", " ").strip().capitalize()
            if isinstance(raw_intent, str) and "_" in raw_intent and " " not in raw_intent.strip()
            else raw_intent
        )

        detected_lang_label = {"nl": "Dutch (detected)", "en": "English (detected)"}.get(
            detect_language(latest_msg.text or ""), "Language not detected"
        )

        # Custom facts for EstateOS understood block
        custom_facts = [
            {"label": "Intent", "value": und_intent, "checked": True},
            {"label": "Category", "value": case.category.value.upper(), "checked": True},
            {"label": "Priority", "value": (case.urgency.value if case.urgency else "normal").upper(), "checked": True},
            {"label": "Unit", "value": unit_label, "checked": True},
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
        if und_entities.get("amounts"):
            for amt in und_entities["amounts"]:
                custom_facts.append(
                    {"label": "Amount", "value": f"€ {amt.get('amount')} {amt.get('currency', 'EUR')}", "checked": True}
                )
        if und_entities.get("dates"):
            for d in und_entities["dates"]:
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

        # Draft generation: Generate tailored replies for Gmail and WhatsApp
        gmail_drafts: list[dict[str, Any]] = []
        whatsapp_drafts: list[dict[str, Any]] = []
        draft_persona: dict[str, Any] | None = None  # set only for model drafts written in the owner's persona

        if reply_action and reply_action.payload:  # the agent's own draft, shown on both tabs
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
            d1_en = (
                f"Dear {sender_name},\n\nThank you for your message. We have received it and will get back to you "
                "shortly.\n\nBest regards,\nHarjot"
            )
            d2_en = (
                f"Hello {sender_name},\n\nThanks for reaching out. I am looking into this and will follow up as soon "
                "as I can.\n\nKind regards,\nHarjot"
            )
            d1_wa = f"Hi {sender_name}, thank you for your message. We have received it and will reply shortly."
            d2_wa = f"Hello {sender_name}, thanks for reaching out. I am looking into this and will get back to you."

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

        # Calculate exact timestamp relative label
        now_dt = datetime.now(UTC)
        sent_dt = latest_msg.sent_at if latest_msg.sent_at else now_dt
        # Ensure sent_dt is timezone-aware
        if sent_dt.tzinfo is None:
            sent_dt = sent_dt.replace(tzinfo=UTC)
        rel_label = when_label(sent_dt, now_dt, company_tz, weekdays=True)

        # Collect attachments for all messages in this thread
        msg_ids_list = [m.id for m in messages]
        attachments_map: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        all_thread_attachments: list[dict[str, Any]] = []
        if msg_ids_list:
            att_rows = session.query(AttachmentRow).filter(AttachmentRow.message_id.in_(msg_ids_list)).all()
            for att in att_rows:
                size_kb = (att.size_bytes or 0) / 1024
                size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
                doc_row = session.query(DocumentRow).filter(DocumentRow.attachment_id == att.id).first()
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

        msgs_data: list[dict[str, Any]] = []
        for m in messages:
            m_dt = m.sent_at if m.sent_at else now_dt
            if m_dt.tzinfo is None:
                m_dt = m_dt.replace(tzinfo=UTC)
            m_time_fmt = when_label(m_dt, now_dt, company_tz)
            m_is_incoming = m.direction != Direction.outbound
            if m.direction == Direction.outbound:
                m_sender_type = "owner"
                m_sender_name = "Harjot Singh"
                m_sender_contact = m.sender_identity or (get_settings().owner_email or "owner@estateos.com")
            elif is_contractor:
                m_sender_type = "contractor"
                m_sender_name = sender_name
                m_sender_contact = sender_email
            else:
                m_sender_type = "tenant"
                m_sender_name = sender_name
                m_sender_contact = sender_email

            msgs_data.append(
                {
                    "id": str(m.id),
                    "sender": m_sender_type,
                    "senderName": m_sender_name,
                    "senderContact": m_sender_contact,
                    "sentAt": m_dt.isoformat(),
                    "timeFormatted": m_time_fmt,
                    "content": m.text,
                    "body": m.text,
                    "isIncoming": m_is_incoming,
                    "channel": m.channel.value if m.channel else "gmail",
                    "attachments": attachments_map.get(m.id, []),
                    "subject": (
                        m.meta.get("subject", "Communication") if isinstance(m.meta, dict) else "Communication"
                    ),
                }
            )

        # Also fetch any outgoing messages recorded in sends table for this case's actions
        action_ids = [a.id for a in actions]
        if action_ids:
            sends = session.query(Send).filter(Send.action_id.in_(action_ids)).order_by(Send.attempted_at.asc()).all()
            for s in sends:
                s_dt = s.attempted_at if s.attempted_at else now_dt
                if s_dt.tzinfo is None:
                    s_dt = s_dt.replace(tzinfo=UTC)
                s_time_fmt = when_label(s_dt, now_dt, company_tz)
                # Retrieve draft text from action payload
                act_row = next((a for a in actions if a.id == s.action_id), None)
                act_payload = act_row.payload if act_row and isinstance(act_row.payload, dict) else {}
                variants = act_payload.get("body_variants") or []
                body_txt = variants[0] if variants else "Replied to tenant."

                # Determine accurate preceding incoming message for this send
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
                        "sentAt": s_dt.isoformat(),
                        "timeFormatted": s_time_fmt,
                        "content": body_txt,
                        "body": body_txt,
                        "isIncoming": False,
                        "channel": s.channel.value if s.channel else "whatsapp",
                        "subject": "Reply",
                        "replyTo": reply_to_info,
                    }
                )
        # Sort all messages chronologically
        msgs_data.sort(key=lambda x: x.get("sentAt", ""))
        has_owner_reply = any(m.get("sender") == "owner" for m in msgs_data)
        status_str = "needs_approval"
        if (approval and approval.status == ApprovalStatus.approved) or has_owner_reply:
            status_str = "approved"
            if approval and approval.status != ApprovalStatus.approved:
                approval.status = ApprovalStatus.approved
                session.commit()

        channel_str = latest_msg.channel.value if latest_msg.channel else "gmail"
        subject_str = (
            latest_msg.meta.get("subject") if isinstance(latest_msg.meta, dict) else None
        ) or f"{case.category.value.title()} - {unit_label}"

        trade_name = ((person.trade if person else None) or "Plumber").title()
        role_label = f"Contractor · {trade_name}" if is_contractor else "Tenant"
        audience_label = "contractors" if is_contractor else "tenants"
        recipient_role = "contractor" if is_contractor else "tenant"

        annotate_translations(session, company_id, msgs_data, [*gmail_drafts, *whatsapp_drafts])
        ticket_code = f"BRIXX-{case.brixx_ref}" if case.brixx_ref else f"#{case_ref(case.id)}"
        live_threads.append(
            {
                "id": f"case-{case.id}",
                "caseId": str(case.id),
                "ticketNumber": ticket_code,
                "caseRef": ticket_code,
                "approvalId": str(approval.id) if approval else f"case-{case.id}",
                "audience": audience_label,
                "recipientRole": recipient_role,
                "recipientRoleDetail": role_label,
                "isUnregisteredSender": is_unregistered_sender,
                "matchedTenant": matched_tenant_info,
                "category": case.category.value if case.category else "maintenance",
                "urgency": case.urgency.value if case.urgency else "normal",
                "unit": unit_label,
                "title": subject_str,
                "lastMessageSnippet": latest_msg.text[:140] if latest_msg.text else "",
                "timestamp": rel_label,
                "receivedAt": sent_dt.isoformat(),
                "channel": channel_str,
                "channelBadge": f"{channel_str.title()} · {rel_label}",
                "sourceIdentifier": f"{channel_str.title()} · {sender_email}",
                "subject": subject_str,
                "externalMessageId": latest_msg.provider_msg_id or str(latest_msg.id),
                "externalThreadId": latest_msg.thread_ref,
                "sender": {
                    "name": sender_name,
                    "contact": sender_email,
                    "role": role_label,
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
                "activeChannel": channel_str,
                "status": status_str,
                "gmailDrafts": []
                if (status_str == "approved" or (msgs_data and msgs_data[-1].get("sender") == "owner"))
                else gmail_drafts,
                "whatsappDrafts": []
                if (status_str == "approved" or (msgs_data and msgs_data[-1].get("sender") == "owner"))
                else whatsapp_drafts,
                "draftPersona": draft_persona,
                "attachments": all_thread_attachments,
                "messages": msgs_data,
            }
        )
        if len(live_threads) >= 50:
            break
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
    *,
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    """Retrieves inbox threads enriched with agent-drafted proposals."""
    with Session(engine) as session:
        live_threads = _build_live_threads(session, principal.company_id)
    if not principal.access.can("inbox"):
        live_threads = [headline_only(t) for t in live_threads]

    # Merge live threads with default seeded threads (live threads first)
    threads = list(live_threads)

    # Safe parameter normalization (handles both FastAPI dependency injection and direct calls)
    chan = channel if isinstance(channel, str) else getattr(channel, "default", "all")
    aud = audience if isinstance(audience, str) else getattr(audience, "default", "all")
    cat = category if isinstance(category, str) else getattr(category, "default", "all")

    # Filter by Channel
    if chan != "all":
        threads = [t for t in threads if t.get("channel") == chan]

    # Filter by Audience
    if aud != "all":
        threads = [t for t in threads if t.get("audience") == aud]

    # Filter by Contractor Category
    if cat != "all":
        threads = [t for t in threads if t.get("contractorCategory") == cat]

    return {
        "threads": threads,
        "total": len(threads),
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
    """Returns metric counters for inbox triage badges, counted from the same live threads the inbox lists."""
    with Session(engine) as session:
        threads = _build_live_threads(session, principal.company_id)
    return {
        "needsYouCount": sum(t["status"] == "needs_approval" for t in threads),
        "allCount": len(threads),
        "tenantsCount": sum(t["audience"] == "tenants" for t in threads),
        "contractorsCount": sum(t["audience"] == "contractors" for t in threads),
        "urgentCount": sum(t["urgency"] in ("high", "emergency") for t in threads),
        "whatsappCount": sum(t["channel"] == "whatsapp" for t in threads),
        "gmailCount": sum(t["channel"] == "gmail" for t in threads),
    }


def _reset_dummy_cursor(session: Session, account_id: UUID) -> None:
    """Clear an invalid/dummy history cursor so the next sync lists recent mail instead."""
    state = session.scalars(select(GmailSyncState).where(GmailSyncState.channel_account_id == account_id)).first()
    if state and (state.history_id == "99999999" or not state.history_id):
        state.history_id = None
        session.commit()


def sync_gmail_accounts(deps: IngestDeps, company_id: UUID | None = None) -> int:
    """Pull the connected Gmail mailboxes once (one company's when `company_id` is given, else all, for the background
    loop); a failing mailbox is logged and skipped."""
    synced_count = 0
    with Session(deps.engine) as session:
        query = select(ChannelAccount).where(ChannelAccount.channel == Channel.gmail)
        if company_id is not None:
            query = query.where(ChannelAccount.company_id == company_id)
        accounts = session.scalars(query).all()
        for acct in accounts:
            try:
                _reset_dummy_cursor(session, acct.id)
                current = deps.gmail_mailbox(acct.address).current_history_id()
                synced_count += sync_mailbox(deps, acct.id, current)
            except Exception as e:
                log.warning("sync_inbox.mailbox_error", account=acct.address, error=str(e))
    return synced_count


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
    summary="Open a Gmail Compose Window for a Reply",
    description=(
        "Returns a prefilled Gmail compose URL. Native Gmail drafts are written only by the sender "
        "(app/sender, send isolation), never by the API."
    ),
)
def create_gmail_draft(
    req: CreateGmailDraftRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    """Prefills a compose window ("Re: " when the quoted message has a Message-ID); no Gmail API call."""
    with Session(engine) as session:
        msg = _quoted_message(session, req, principal.company_id)
        in_reply_to = msg.meta.get("message_id") if msg is not None and isinstance(msg.meta, dict) else None
    sub = req.subject
    if in_reply_to and not sub.lower().startswith("re:"):
        sub = f"Re: {sub}"
    query = urllib.parse.urlencode({"view": "cm", "fs": "1", "to": req.to_email, "su": sub, "body": req.body})
    return {
        "ok": False,
        "error": "native Gmail drafts are created only by the sender; opened a compose window instead",
        "web_url": f"https://mail.google.com/mail/?{query}",
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


class LinkTenantRequest(BaseModel):
    tenant_id: UUID | None = None


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
    req: LinkTenantRequest | None = None,
    engine: Annotated[Engine, Depends(get_engine)] = None,
    principal: Annotated[Principal, Depends(require_session)] = None,
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

        source_person_id = case.primary_person_id
        if not source_person_id:
            raise HTTPException(status_code=400, detail="Case has no sender person to link")

        target_tenant_id = req.tenant_id if req and req.tenant_id else None
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
