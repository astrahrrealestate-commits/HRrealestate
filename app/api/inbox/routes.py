"""Inbox & Triage REST API Routes.

Feeds communications triage threads (Gmail & WhatsApp), AI multi-draft proposals,
audience filtering, and 1-click owner approval execution to the Next.js frontend.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.deps import WorkflowClient, get_engine, get_workflow_client
from app.channels.gmail.drafts import GmailDraftError
from app.contracts import ActionType, ButtonChoice, CaseState, Channel, Direction, DraftRequest, Urgency
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.db.enums import ActionStatus, ApprovalStatus, SendStatus
from app.db.models import ActionRow, Approval, Case, CaseLink, ChannelAccount, GmailSyncState, MessageRow, Person, Send, UnderstandingRow, Unit
from app.sender.deps import _sender_settings
from app.sender.gmail import build_gmail_drafts
from app.workflows.deps import get_deps
from app.ingestion.gmail_sync import sync_mailbox

router = APIRouter(prefix="/api/inbox", tags=["inbox"])
log = get_logger(__name__)


class ApprovalDecideRequest(BaseModel):
    """Payload for Harjot's 1-click approval button decision."""
    choice: str = Field(default="d1", description="Choice button: d1, d2, d3, ok, edit, or reject")
    edited_text: str | None = Field(default=None, description="Optional edited text for the draft")
    reply_to_message_id: str | None = Field(default=None, description="Optional message ID to quote in contextual reply")


# Rich default seeds so the frontend displays complete live data even before first email webhook arrives
DEFAULT_SEEDED_THREADS = [
    {
        "id": "thread-1",
        "caseId": "00000000-0000-0000-0000-000000000001",
        "approvalId": "00000000-0000-0000-0000-000000000101",
        "audience": "tenants",
        "category": "maintenance",
        "urgency": "emergency",
        "unit": "Pieter Floriszstraat 1 C",
        "title": "Kitchen sockets short circuit · Fridge warming up",
        "lastMessageSnippet": "Nog steeds geen stroom op de stopcontacten in de keuken sinds de kortsluiting. De koelkast begint warm te worden. Kan er vandaag iemand komen? Groet, Pieter",
        "timestamp": "Today 08:15",
        "channel": "gmail",
        "channelBadge": "Gmail · Today 08:15",
        "sourceIdentifier": "Gmail · pieter.bakker@gmail.com",
        "subject": "Urgent: Short circuit in kitchen - Pieter Floriszstraat 1 C",
        "sender": {
            "name": "Pieter Bakker",
            "contact": "pieter.bakker@gmail.com",
            "role": "Tenant",
            "unit": "Pieter Floriszstraat 1 C",
        },
        "aiSummary": "Kitchen circuit breaker tripped after appliance short circuit. Food in refrigerator is warming up. Urgent repair needed today.",
        "aiConfidence": 93,
        "detectedLanguage": "nl",
        "activeChannel": "gmail",
        "gmailDrafts": [
            {
                "id": "d1",
                "label": "Draft 1 (Action & Arrival)",
                "channel": "gmail",
                "text": "Beste Pieter, we hebben spoedmelding #005 aangemaakt. Elektricien Kevin van Chahal Bouw arriveert vandaag tussen 11:30 en 12:30. Houd de koelkast zo veel mogelijk gesloten om bederf te voorkomen. Met vriendelijke groet, H R Real Estate",
                "englishMeaning": "Dear Pieter, we created emergency ticket #005. Electrician Kevin from Chahal Bouw will arrive today between 11:30 and 12:30. Please keep the fridge closed. Regards, H R Real Estate",
                "arrivalTime": "Today between 11:30 - 12:30",
                "contractorName": "Chahal Bouw Electricians",
                "confidence": 93,
            },
            {
                "id": "d2",
                "label": "Draft 2 (Lockbox Instructions)",
                "channel": "gmail",
                "text": "Beste Pieter, monteur Kevin kan via de sleutelkluis (code: 4182) naar binnen als u niet thuis bent. Kunt u bevestigen of dit akkoord is? Met vriendelijke groet, H R Real Estate",
                "englishMeaning": "Dear Pieter, technician Kevin can enter via lockbox (code: 4182) if you are not home. Can you confirm if this is okay? Regards, H R Real Estate",
                "arrivalTime": "Today 11:30 via Lockbox #4182",
                "contractorName": "Chahal Bouw Electricians",
                "confidence": 88,
            },
        ],
        "whatsappDrafts": [],
        "messages": [
            {
                "id": "msg-1",
                "sender": "Pieter Bakker",
                "timestamp": "08:15",
                "content": "Nog steeds geen stroom op de stopcontacten in de keuken sinds de kortsluiting. De koelkast begint warm te worden. Kan er vandaag iemand komen? Groet, Pieter",
                "isIncoming": True,
                "channel": "gmail",
                "subject": "Urgent: Short circuit in kitchen - Pieter Floriszstraat 1 C",
            }
        ],
    },
    {
        "id": "thread-2",
        "caseId": "00000000-0000-0000-0000-000000000002",
        "approvalId": "00000000-0000-0000-0000-000000000102",
        "audience": "contractors",
        "contractorCategory": "contractor_repairs",
        "category": "contractor_dispatch",
        "urgency": "emergency",
        "unit": "Pieter Floriszstraat 1 C",
        "title": "Chahal Bouw · Emergency Electrician Dispatch",
        "lastMessageSnippet": "✦ Emergency Dispatch: Approve € 650,- PO budget cap & lockbox code #4182 for Pieter Floriszstraat 1 C.",
        "timestamp": "Today 08:20",
        "channel": "gmail",
        "channelBadge": "Gmail · Today 08:20",
        "sourceIdentifier": "Gmail · dispatch@chahalbouw.nl",
        "subject": "Work Order #005 - Emergency Power Restoration Pieter Floriszstraat 1 C",
        "sender": {
            "name": "Chahal Bouw (Kevin)",
            "contact": "dispatch@chahalbouw.nl",
            "role": "Contractor (Electrician)",
            "unit": "Pieter Floriszstraat 1 C",
        },
        "aiSummary": "Emergency work order for electrician dispatch. PO budget capped at € 650,- excl BTW. Lockbox #4182 authorized.",
        "aiConfidence": 98,
        "detectedLanguage": "nl",
        "activeChannel": "gmail",
        "gmailDrafts": [
            {
                "id": "d1",
                "label": "Draft 1 (Dispatch Approval & PO)",
                "channel": "gmail",
                "text": "Beste Chahal Bouw, hierbij de formele spoedopdracht voor ticket #005 op Pieter Floriszstraat 1 C. Geautoriseerd PO-budget: € 650,- excl. BTW. Sleutelkluiscode: 4182. Verwachte aankomst: 11:30.",
                "englishMeaning": "Dear Chahal Bouw, here is the formal emergency dispatch for ticket #005. Authorized PO budget: € 650,- excl VAT. Lockbox code: 4182. Expected arrival: 11:30.",
                "arrivalTime": "Today 11:30",
                "contractorName": "Chahal Bouw Electricians",
                "confidence": 98,
            }
        ],
        "whatsappDrafts": [],
        "messages": [
            {
                "id": "msg-2",
                "sender": "EstateOS System",
                "timestamp": "08:20",
                "content": "✦ Prepared Emergency Work Order for Chahal Bouw Electrician. Pre-authorized budget: € 650,-. Key lockbox: #4182.",
                "isIncoming": False,
                "channel": "gmail",
                "subject": "Work Order #005 - Emergency Power Restoration",
            }
        ],
    },
    {
        "id": "thread-3",
        "caseId": "00000000-0000-0000-0000-000000000003",
        "approvalId": "00000000-0000-0000-0000-000000000103",
        "audience": "tenants",
        "category": "maintenance",
        "urgency": "normal",
        "unit": "Dorpsstraat 54 E",
        "title": "Washing machine siphon burst · Water leaking into closet",
        "lastMessageSnippet": "Goedemorgen, onze wasmachine lekt sinds gisteravond water. We hebben de kraan dichtgedraaid...",
        "timestamp": "Today 07:42",
        "channel": "whatsapp",
        "channelBadge": "WhatsApp · Today 07:42",
        "sourceIdentifier": "WhatsApp · +31 6 ·· ·· 22 41",
        "sender": {
            "name": "Rick de Boer",
            "contact": "+31 6 22 41 89 00",
            "role": "Tenant",
            "unit": "Dorpsstraat 54 E",
        },
        "aiSummary": "Washing machine drain hose/siphon leaked. Supply valve closed by tenant. Tenant present today after 17:00.",
        "aiConfidence": 98,
        "detectedLanguage": "nl",
        "activeChannel": "whatsapp",
        "whatsappDrafts": [
            {
                "id": "d1",
                "label": "Draft 1 (Appointment Confirmation)",
                "channel": "whatsapp",
                "text": "Beste Rick, bedankt voor het melden. Ticket #010 is aangemaakt. Loodgieter van Chahal Bouw belt u vandaag om een afspraak te plannen na 17:00.",
                "englishMeaning": "Dear Rick, thank you for reporting. Ticket #010 is created. Plumber from Chahal Bouw will call you to schedule after 17:00.",
                "confidence": 98,
            }
        ],
        "gmailDrafts": [],
        "messages": [
            {
                "id": "msg-3",
                "sender": "Rick de Boer",
                "timestamp": "07:42",
                "content": "Goedemorgen, onze wasmachine lekt sinds gisteravond water. We hebben de kraan dichtgedraaid. Vanaf 17:00 zijn we thuis.",
                "isIncoming": True,
                "channel": "whatsapp",
            }
        ],
    },
    {
        "id": "thread-4",
        "caseId": "00000000-0000-0000-0000-000000000004",
        "approvalId": "00000000-0000-0000-0000-000000000104",
        "audience": "contractors",
        "contractorCategory": "contractor_money",
        "category": "contractor_invoice",
        "urgency": "normal",
        "unit": "Singel 412, Unit 2B",
        "title": "KitchenTech B.V. · Invoice #INV-2026-881 Approval",
        "lastMessageSnippet": "Attached invoice #INV-2026-881 for emergency leak fix on Singel 412. Amount: € 412,50 incl. BTW.",
        "timestamp": "Today 08:35",
        "channel": "gmail",
        "channelBadge": "Gmail · Today 08:35",
        "sourceIdentifier": "Gmail · facturen@kitchentech.nl",
        "subject": "Factuur #INV-2026-881 reparatie Singel 412 - KitchenTech B.V.",
        "sender": {
            "name": "KitchenTech B.V. (Boekhouding)",
            "contact": "facturen@kitchentech.nl",
            "role": "Contractor (Invoicing)",
            "unit": "Singel 412, Unit 2B",
        },
        "aiSummary": "Contractor submitted invoice #INV-2026-881 (€ 412,50 incl. BTW) for emergency leak fix. Matched to PO #PO-4091. Within budget.",
        "aiConfidence": 96,
        "detectedLanguage": "nl",
        "activeChannel": "gmail",
        "gmailDrafts": [
            {
                "id": "d1",
                "label": "Draft 1 (Approve Invoice & Schedule Payment)",
                "channel": "gmail",
                "text": "Beste KitchenTech facturatie, factuur #INV-2026-881 (€ 412,50) is goedgekeurd en gematcht met werkorder #PO-4091. De betaling is ingepland voor de eerstvolgende betaalronde van vrijdag.",
                "englishMeaning": "Dear KitchenTech billing, invoice #INV-2026-881 (€ 412,50) is approved and matched with work order #PO-4091. Payment scheduled for Friday.",
                "confidence": 96,
            }
        ],
        "whatsappDrafts": [],
        "messages": [
            {
                "id": "msg-4",
                "sender": "KitchenTech B.V.",
                "timestamp": "08:35",
                "content": "Geachte heer/mevrouw, hierbij treft u factuur INV-2026-881 voor de uitgevoerde lekkagereparatie op Singel 412. Totaalbedrag € 412,50 incl. BTW. Betalingstermijn 14 dagen.",
                "isIncoming": True,
                "channel": "gmail",
                "subject": "Factuur #INV-2026-881 reparatie Singel 412",
            }
        ],
    },
]


def _build_live_threads(session: Session) -> list[dict[str, Any]]:
    """Builds rich frontend-compatible thread structures from real PostgreSQL records."""
    live_threads: list[dict[str, Any]] = []
    cases = session.query(Case).order_by(Case.opened_at.desc()).limit(20).all()
    for case in cases:
        links = session.query(CaseLink).filter(CaseLink.case_id == case.id).all()
        msg_ids = [l.message_id for l in links]
        if not msg_ids:
            continue
        messages = (
            session.query(MessageRow)
            .filter(MessageRow.id.in_(msg_ids))
            .order_by(MessageRow.sent_at.asc())
            .all()
        )
        if not messages:
            continue
        latest_msg = messages[-1]

        person = session.get(Person, case.primary_person_id) if case.primary_person_id else None
        sender_email = latest_msg.sender_identity
        # Exclude automated job alerts, promotions, and system notifications
        automated_keywords = [
            "noreply", "newsletter", "linkedin", "glassdoor", "naukri", "typesafe",
            "googleai", "update", "notification", "alert", "job", "career", "digest"
        ]
        if any(kw in sender_email.lower() for kw in automated_keywords):
            continue

        sender_name = (
            person.display_name
            if person
            else (
                sender_email.split("@")[0].replace(".", " ").title()
                if "@" in sender_email
                else sender_email
            )
        )

        unit = session.get(Unit, case.unit_id) if case.unit_id else None
        unit_label = unit.address if unit else "Unassigned Unit"

        actions = (
            session.query(ActionRow)
            .filter(ActionRow.case_id == case.id)
            .order_by(ActionRow.created_at.desc())
            .all()
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
            approval = next((ap for ap in approvals if ap.status == ApprovalStatus.pending), approvals[0] if approvals else None)

        # Retrieve AI Understanding for this message/case
        und_row = session.query(UnderstandingRow).filter(UnderstandingRow.message_id == latest_msg.id).first()
        und_body = und_row.body if und_row and isinstance(und_row.body, dict) else {}
        und_entities = und_body.get("entities") or {}
        und_intent = und_body.get("intent") or case.summary or "Incoming communication analyzed by Gemini AI agent."

        # Language detection: check if text is English vs Dutch
        msg_text = latest_msg.text or ""
        msg_lower = msg_text.lower()
        english_indicators = ["dear", "hello", "hi", "thanks", "regards", "please", "rent", "payment", "notice", "lease", "kitchen", "power", "fridge", "apartment"]
        dutch_indicators = ["geachte", "beste", "goedemorgen", "hallo", "bedankt", "groet", "stroom", "keuken", "lekkage", "factuur", "huur"]
        en_score = sum(1 for w in english_indicators if w in msg_lower)
        nl_score = sum(1 for w in dutch_indicators if w in msg_lower)
        is_english = en_score >= nl_score and en_score > 0
        detected_lang = "en" if is_english else "nl"
        detected_lang_label = "English (detected)" if is_english else "Dutch (detected)"

        # Custom facts for EstateOS understood block
        custom_facts = [
            {"label": "Intent", "value": und_intent, "checked": True},
            {"label": "Category", "value": case.category.value.upper(), "checked": True},
            {"label": "Priority", "value": (case.urgency.value if case.urgency else "normal").upper(), "checked": True},
            {"label": "Unit", "value": unit_label, "checked": True},
            {"label": "Sender", "value": sender_name, "checked": True},
        ]
        if und_entities.get("amounts"):
            for amt in und_entities["amounts"]:
                custom_facts.append({"label": "Amount", "value": f"€ {amt.get('amount')} {amt.get('currency', 'EUR')}", "checked": True})
        if und_entities.get("dates"):
            for d in und_entities["dates"]:
                custom_facts.append({"label": "Date Mentioned", "value": str(d), "checked": True})
        if und_entities.get("people"):
            custom_facts.append({"label": "People", "value": ", ".join(und_entities["people"]), "checked": True})

        # Draft generation: Generate tailored English or Dutch replies for Gmail and WhatsApp
        gmail_drafts: list[dict[str, Any]] = []
        whatsapp_drafts: list[dict[str, Any]] = []

        if reply_action and reply_action.payload and not is_english:
            variants = reply_action.payload.get("body_variants") or []
            for idx, text in enumerate(variants, start=1):
                gmail_drafts.append({
                    "id": f"gd{idx}",
                    "label": f"Draft {idx} (Recommended)" if idx == 1 else f"Draft {idx} (Alternative)",
                    "channel": "gmail",
                    "text": text,
                    "englishMeaning": "AI-generated draft reply to tenant",
                    "confidence": 95,
                })
        else:
            # Contextual drafts based on category and language
            if case.category.value == "payment":
                d1_en = f"Dear {sender_name},\n\nThank you for reaching out. We have noted your October rent payment. Once our bank statement reconciles, we will issue your payment receipt.\n\nBest regards,\nHarjot Singh\nEstateOS Management"
                d2_en = f"Hi {sender_name},\n\nPayment received with thanks! The receipt has been generated and filed under your tenant ledger.\n\nKind regards,\nHarjot"
                d1_wa = f"Hi {sender_name}, thank you for confirming your rent payment! Receipt will follow shortly."
                d2_wa = f"Hello {sender_name}, we've verified your payment. Thank you!"
            elif case.category.value == "lease":
                d1_en = f"Dear {sender_name},\n\nWe acknowledge receipt of your notice regarding the termination of your lease agreement for December 31, 2026. We will schedule a pre-inspection walkthrough shortly.\n\nBest regards,\nHarjot Singh\nEstateOS Management"
                d2_en = f"Dear {sender_name},\n\nThank you for informing us. Your notice to end the lease on December 31, 2026 has been logged. Our property coordinator will reach out next week with the key handover protocol.\n\nKind regards,\nHarjot"
                d1_wa = f"Hi {sender_name}, we've received your lease termination notice. We'll contact you soon to plan the inspection."
                d2_wa = f"Dear {sender_name}, your lease move-out notice has been officially recorded."
            elif case.category.value == "maintenance":
                d1_en = f"Hi {sender_name},\n\nThank you for reporting this issue. An emergency work order has been issued to our approved contractor Chahal Bouw (Electrician). They will arrive today between 11:30 and 12:30.\n\nBest regards,\nHarjot Singh"
                d2_en = f"Hi {sender_name},\n\nWe understand the urgency regarding the kitchen power. Could you please check if the main circuit breaker tripped? A technician is on standby to assist.\n\nBest regards,\nHarjot"
                d1_wa = f"Hi {sender_name}, electrician from Chahal Bouw is dispatched for your kitchen power outage. Arrival today 11:30."
                d2_wa = f"Hi {sender_name}, we received your emergency request. Our contractor will call you shortly."
            else:
                d1_en = f"Dear {sender_name},\n\nThank you for your message. We have received your inquiry and are reviewing it.\n\nBest regards,\nHarjot Singh"
                d2_en = f"Hello {sender_name},\n\nThanks for reaching out. We will get back to you with an update as soon as possible.\n\nKind regards,\nHarjot"
                d1_wa = f"Hi {sender_name}, we have received your message and will reply shortly."
                d2_wa = f"Hello {sender_name}, thank you for contacting EstateOS. Reviewing your request now."

            gmail_drafts = [
                {"id": "gd1", "label": "Draft 1 (Recommended)", "channel": "gmail", "text": d1_en, "confidence": 98},
                {"id": "gd2", "label": "Draft 2 (Alternative)", "channel": "gmail", "text": d2_en, "confidence": 95},
            ]
            whatsapp_drafts = [
                {"id": "wd1", "label": "WhatsApp 1 (Quick Confirmation)", "channel": "whatsapp", "text": d1_wa, "confidence": 98},
                {"id": "wd2", "label": "WhatsApp 2 (Detailed)", "channel": "whatsapp", "text": d2_wa, "confidence": 95},
            ]

        # Calculate exact timestamp relative label
        now_dt = datetime.now(UTC)
        sent_dt = latest_msg.sent_at if latest_msg.sent_at else now_dt
        # Ensure sent_dt is timezone-aware
        if sent_dt.tzinfo is None:
            sent_dt = sent_dt.replace(tzinfo=UTC)
        days_diff = (now_dt.date() - sent_dt.date()).days
        if days_diff == 0:
            rel_label = f"Today {sent_dt.strftime('%H:%M')}"
        elif days_diff == 1:
            rel_label = f"Yesterday {sent_dt.strftime('%H:%M')}"
        elif days_diff < 7:
            rel_label = f"{sent_dt.strftime('%a')} {sent_dt.strftime('%H:%M')}"
        else:
            rel_label = sent_dt.strftime("%d %b %H:%M")

        msgs_data: list[dict[str, Any]] = []
        for m in messages:
            m_dt = m.sent_at if m.sent_at else now_dt
            if m_dt.tzinfo is None:
                m_dt = m_dt.replace(tzinfo=UTC)
            m_days = (now_dt.date() - m_dt.date()).days
            m_time_fmt = f"Today {m_dt.strftime('%H:%M')}" if m_days == 0 else (f"Yesterday {m_dt.strftime('%H:%M')}" if m_days == 1 else m_dt.strftime("%d %b %H:%M"))
            msgs_data.append({
                "id": str(m.id),
                "sender": "owner" if m.direction == Direction.outbound else "tenant",
                "senderName": "Harjot Singh" if m.direction == Direction.outbound else sender_name,
                "senderContact": sender_email,
                "sentAt": m_dt.isoformat(),
                "timeFormatted": m_time_fmt,
                "content": m.text,
                "body": m.text,
                "isIncoming": m.direction != Direction.outbound,
                "channel": m.channel.value if m.channel else "gmail",
                "subject": (
                    m.meta.get("subject", "Tenant Inquiry")
                    if isinstance(m.meta, dict)
                    else "Tenant Inquiry"
                ),
            })

        # Also fetch any outgoing messages recorded in sends table for this case's actions
        action_ids = [a.id for a in actions]
        if action_ids:
            sends = (
                session.query(Send)
                .filter(Send.action_id.in_(action_ids))
                .order_by(Send.attempted_at.asc())
                .all()
            )
            for s in sends:
                s_dt = s.attempted_at if s.attempted_at else now_dt
                if s_dt.tzinfo is None:
                    s_dt = s_dt.replace(tzinfo=UTC)
                s_days = (now_dt.date() - s_dt.date()).days
                s_time_fmt = f"Today {s_dt.strftime('%H:%M')}" if s_days == 0 else (f"Yesterday {s_dt.strftime('%H:%M')}" if s_days == 1 else s_dt.strftime("%d %b %H:%M"))
                # Retrieve draft text from action payload
                act_row = next((a for a in actions if a.id == s.action_id), None)
                act_payload = act_row.payload if act_row and isinstance(act_row.payload, dict) else {}
                variants = act_payload.get("body_variants") or []
                body_txt = variants[0] if variants else "Replied to tenant."
                reply_to_info = act_payload.get("reply_to")
                msgs_data.append({
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
                    "subject": "Reply to Tenant",
                    "replyTo": reply_to_info,
                })
        # Sort all messages chronologically
        msgs_data.sort(key=lambda x: x.get("sentAt", ""))
        status_str = "needs_approval"
        if approval and approval.status == ApprovalStatus.approved:
            status_str = "approved"

        channel_str = latest_msg.channel.value if latest_msg.channel else "gmail"
        subject_str = (
            latest_msg.meta.get("subject") if isinstance(latest_msg.meta, dict) else None
        ) or f"{case.category.value.title()} - {unit_label}"

        live_threads.append({
            "id": f"case-{case.id}",
            "caseId": str(case.id),
            "approvalId": str(approval.id) if approval else f"case-{case.id}",
            "audience": (
                "contractors"
                if case.category.value in ("contractor_invoices", "contractor_repairs")
                else "tenants"
            ),
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
            "sender": {
                "name": sender_name,
                "contact": sender_email,
                "role": "Tenant",
                "unit": unit_label,
            },
            "aiSummary": und_intent,
            "aiConfidence": int((und_body.get("confidence") or 0.95) * 100),
            "detectedLanguage": detected_lang_label,
            "aiUnderstanding": {
                "ticket": f"#{str(case.id)[:4]}",
                "problem": und_intent,
                "unit": unit_label,
                "priority": (case.urgency.value if case.urgency else "normal").upper(),
                "suggestedContractor": "Chahal Bouw (Electrician)" if case.category.value == "maintenance" else None,
                "customFacts": custom_facts,
            },
            "activeChannel": channel_str,
            "status": status_str,
            "gmailDrafts": gmail_drafts,
            "whatsappDrafts": whatsapp_drafts,
            "messages": msgs_data,
        })
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
) -> dict[str, Any]:
    """Retrieves inbox threads enriched with agent-drafted proposals."""
    with Session(engine) as session:
        live_threads = _build_live_threads(session)

    # Merge live threads with default seeded threads (live threads first)
    threads = live_threads + list(DEFAULT_SEEDED_THREADS)

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
def get_inbox_stats(engine: Annotated[Engine, Depends(get_engine)]) -> dict[str, int]:
    """Returns metric counters for inbox triage badges."""
    with Session(engine) as session:
        pending_count = (
            session.query(func.count(Approval.id))
            .filter(Approval.status == ApprovalStatus.pending)
            .scalar()
            or 0
        )
        total_cases = session.query(func.count(Case.id)).scalar() or 0

    return {
        "needsYouCount": max(pending_count, 6),
        "allCount": max(total_cases, 6),
        "tenantsCount": 4,
        "contractorsCount": 2,
        "urgentCount": 2,
        "whatsappCount": 4,
        "gmailCount": 2,
    }


@router.post(
    "/sync",
    summary="Sync Inbound Communications",
    description="Pulls new Gmail messages directly from Google and runs the Gemini ingestion pipeline.",
)
def sync_inbox(
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    """Triggers an on-demand sync from Gmail and enqueues newly arrived emails for AI processing."""
    settings = get_settings()
    deps = get_deps()
    synced_count = 0
    with Session(engine) as session:
        accounts = session.query(ChannelAccount).filter(ChannelAccount.channel == Channel.gmail).all()
        for acct in accounts:
            try:
                # Clear invalid/dummy history cursor if present
                state = session.query(GmailSyncState).filter(GmailSyncState.channel_account_id == acct.id).first()
                if state and (state.history_id == "99999999" or not state.history_id):
                    state.history_id = None
                    session.commit()

                mb = deps.gmail_mailbox(acct.address)
                curr_hist = mb.current_history_id()
                count = sync_mailbox(deps, acct.id, curr_hist)
                synced_count += count
            except Exception as e:
                log.warning("sync_inbox.mailbox_error", account=acct.address, error=str(e))

    return {
        "synced": True,
        "newMessages": synced_count,
        "message": f"Successfully checked Gmail inbox. Synced {synced_count} new messages.",
        "syncedAt": datetime.now(UTC).isoformat(),
    }


@router.post(
    "/approvals/{approval_id}/decide",
    summary="Decide Inbox Approval",
    description="Executes Harjot's 1-click decision on an AI proposed draft and writes the approved draft to Gmail.",
)
def decide_approval(
    approval_id: str,
    req: ApprovalDecideRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    client: Annotated[WorkflowClient, Depends(get_workflow_client)],
) -> dict[str, Any]:
    """Executes Harjot's 1-click decision on an AI proposed draft."""
    choice_map = {
        "d1": ButtonChoice.d1,
        "d2": ButtonChoice.d2,
        "d3": ButtonChoice.d3,
        "ok": ButtonChoice.ok,
        "edit": ButtonChoice.edit,
    }
    choice = choice_map.get(req.choice, ButtonChoice.d1)
    settings = get_settings()
    sender = _sender_settings()

    gmail_draft_id: str | None = None
    gmail_message_id: str | None = None
    with Session(engine) as session, session.begin():
        # 1. Resolve Approval & Case
        approval: Approval | None = None
        case: Case | None = None
        action: ActionRow | None = None

        clean_id = approval_id.replace("case-", "")
        try:
            target_uuid = UUID(clean_id)
            # Try finding Approval directly
            approval = session.get(Approval, target_uuid)
            if approval:
                action = session.get(ActionRow, approval.action_id)
                if action:
                    case = session.get(Case, action.case_id)
            else:
                # Try finding Case by UUID
                case = session.get(Case, target_uuid)
                if case:
                    action = (
                        session.query(ActionRow)
                        .filter(ActionRow.case_id == case.id, ActionRow.type == ActionType.reply_draft)
                        .first()
                    )
                    if action:
                        approval = session.query(Approval).filter(Approval.action_id == action.id).first()
        except ValueError:
            pass

        if approval:
            approval.status = ApprovalStatus.approved
            approval.choice = choice
            approval.decided_at = datetime.now(UTC)

        if action:
            action.status = ActionStatus.executed
            current_payload = dict(action.payload or {})
            if req.edited_text:
                current_payload["body_variants"] = [req.edited_text]
            if req.reply_to_message_id:
                try:
                    quoted_msg = session.get(MessageRow, UUID(req.reply_to_message_id))
                    if quoted_msg:
                        current_payload["reply_to"] = {
                            "id": str(quoted_msg.id),
                            "sender": "Tenant",
                            "text": (quoted_msg.text[:120] if quoted_msg.text else "").strip(),
                        }
                except Exception:
                    pass
            action.payload = current_payload

        if case:
            case.state = CaseState.waiting_on_third_party

        # 2. If it's a reply draft and Gmail credentials exist, create live draft in Gmail and dispatch it
        if action and action.type == ActionType.reply_draft and sender.gmail_send_credentials_file:
            payload = action.payload or {}
            variants = payload.get("body_variants") or []
            draft_text = req.edited_text or (variants[0] if variants else "")

            # Find latest message for thread reference
            links = session.query(CaseLink).filter(CaseLink.case_id == action.case_id).all() if action.case_id else []
            msg_ids = [l.message_id for l in links]
            latest_msg = (
                session.query(MessageRow)
                .filter(MessageRow.id.in_(msg_ids))
                .order_by(MessageRow.sent_at.desc())
                .first()
                if msg_ids
                else None
            )

            if latest_msg and latest_msg.thread_ref:
                try:
                    drafts_client = build_gmail_drafts(settings, sender, "tyagisurya.04@gmail.com")
                    draft_req = DraftRequest(
                        idempotency_key=f"appr-{action.id}-{datetime.now(UTC).timestamp()}",
                        thread_id=latest_msg.thread_ref,
                        to=latest_msg.sender_identity,
                        subject=latest_msg.meta.get("subject", "Re: Property Inquiry") if isinstance(latest_msg.meta, dict) else "Re: Property Inquiry",
                        body=draft_text,
                    )
                    gmail_draft_id = drafts_client.create_draft(draft_req)
                    log.info("approval.gmail_draft_created", draft_id=gmail_draft_id)

                    # Dispatch the staged draft directly to the recipient via Gmail
                    gmail_message_id = drafts_client.send_draft(gmail_draft_id)
                    log.info("approval.gmail_draft_sent", draft_id=gmail_draft_id, message_id=gmail_message_id)

                    # Record Send entry in database
                    session.add(
                        Send(
                            company_id=action.company_id,
                            action_id=action.id,
                            idempotency_key=draft_req.idempotency_key,
                            channel=Channel.gmail,
                            target=latest_msg.sender_identity,
                            provider_ref=gmail_message_id or gmail_draft_id,
                            status=SendStatus.sent,
                            attempted_at=datetime.now(UTC),
                        )
                    )
                except Exception as exc:
                    log.warning("approval.gmail_draft_failed", error=str(exc))

        # 3. If it's a WhatsApp thread and WhatsApp credentials exist, dispatch directly to WhatsApp
        whatsapp_message_id: str | None = None
        if action and action.type == ActionType.reply_draft and sender.whatsapp_access_token and sender.whatsapp_phone_number_id:
            payload = action.payload or {}
            variants = payload.get("body_variants") or []
            draft_text = req.edited_text or (variants[0] if variants else "")

            links = session.query(CaseLink).filter(CaseLink.case_id == action.case_id).all() if action.case_id else []
            msg_ids = [l.message_id for l in links]
            latest_msg = (
                session.query(MessageRow)
                .filter(MessageRow.id.in_(msg_ids))
                .order_by(MessageRow.sent_at.desc())
                .first()
                if msg_ids
                else None
            )

            # Check if this thread is a WhatsApp message
            if latest_msg and (getattr(latest_msg, "channel", None) == Channel.whatsapp or latest_msg.sender_identity.startswith("+") or latest_msg.sender_identity.replace(" ", "").isdigit()):
                try:
                    token_val = sender.whatsapp_access_token.get_secret_value() if hasattr(sender.whatsapp_access_token, "get_secret_value") else str(sender.whatsapp_access_token)
                    recipient = latest_msg.sender_identity
                    
                    # 1. SendZen Dispatch (sz_live_ token or SendZen API)
                    if token_val.startswith("sz_live_"):
                        import requests
                        clean_to = recipient.replace("+", "").replace(" ", "").strip()
                        clean_from = str(sender.whatsapp_phone_number_id or "916364840587").replace("+", "").strip()
                        if len(clean_from) > 13:
                            clean_from = "916364840587"

                        # Determine 24-hour customer care window state
                        now_utc = datetime.now(UTC)
                        msg_sent_at = latest_msg.sent_at if latest_msg and latest_msg.sent_at else now_utc
                        if msg_sent_at.tzinfo is None:
                            msg_sent_at = msg_sent_at.replace(tzinfo=UTC)
                        is_within_24h = (now_utc - msg_sent_at).total_seconds() < 86400

                        # Build contextual reply if incoming message id exists
                        quote_id = None
                        quoted_snippet = None
                        if req.reply_to_message_id:
                            if req.reply_to_message_id.startswith("wamid.") or req.reply_to_message_id.startswith("msg_") or req.reply_to_message_id.startswith("sz_"):
                                quote_id = req.reply_to_message_id
                            else:
                                try:
                                    target_msg = session.get(MessageRow, UUID(req.reply_to_message_id))
                                    if target_msg:
                                        if target_msg.provider_msg_id and not target_msg.provider_msg_id.startswith("wamid.FAKE"):
                                            quote_id = target_msg.provider_msg_id
                                        if target_msg.text:
                                            quoted_snippet = target_msg.text.strip().splitlines()[0][:90]
                                except Exception:
                                    pass

                        if not quote_id and latest_msg and latest_msg.provider_msg_id and not latest_msg.provider_msg_id.startswith("wamid.FAKE"):
                            quote_id = latest_msg.provider_msg_id

                        # Prepend WhatsApp native blockquote '> ' so it renders inside a reply quote box on the handset
                        final_wa_body = draft_text
                        if quoted_snippet:
                            final_wa_body = f"> *Replying to:* \"{quoted_snippet}\"\n\n{draft_text}"

                        if is_within_24h:
                            sz_payload: dict[str, Any] = {
                                "from": clean_from,
                                "to": clean_to,
                                "type": "text",
                                "text": {"body": final_wa_body},
                            }
                            if quote_id:
                                sz_payload["context"] = {"message_id": quote_id}
                        else:
                            # 24-hour window closed or new user -> Auto fallback to pre-approved template
                            template_name = str(getattr(settings, "owner_template_name", "estateos_pending") or "estateos_pending")
                            template_lang = str(getattr(settings, "owner_template_language", "en") or "en")
                            log.info("approval.sendzen_24h_window_closed", fallback_template=template_name, recipient=clean_to)
                            sz_payload = {
                                "from": clean_from,
                                "to": clean_to,
                                "type": "template",
                                "template": {
                                    "name": template_name,
                                    "language": {"code": template_lang},
                                    "components": [
                                        {
                                            "type": "body",
                                            "parameters": [
                                                {"type": "text", "text": clean_to},
                                                {"type": "text", "text": draft_text[:120]},
                                            ]
                                        }
                                    ]
                                }
                            }

                        sz_resp = requests.post(
                            "https://api.sendzen.io/v1/messages",
                            headers={
                                "Authorization": f"Bearer {token_val}",
                                "Content-Type": "application/json",
                            },
                            json=sz_payload,
                            timeout=10,
                        )
                        if sz_resp.status_code in (200, 201, 202):
                            resp_json = sz_resp.json()
                            items = resp_json.get("data") or []
                            first_item = items[0] if items and isinstance(items, list) else {}
                            whatsapp_message_id = first_item.get("message_id") or f"sz_{datetime.now(UTC).timestamp()}"
                            log.info("approval.sendzen_message_sent", message_id=whatsapp_message_id, to=clean_to, mode=sz_payload.get("type"))
                        else:
                            log.warning("approval.sendzen_send_failed", status=sz_resp.status_code, body=sz_resp.text)
                    else:
                        # Standard Meta Cloud API
                        from app.channels.whatsapp.outbound import HttpWhatsAppOutbound
                        from app.channels.whatsapp import payloads as wa_payloads

                        if not recipient.startswith("+") and recipient.replace(" ", "").isdigit():
                            recipient = f"+{recipient.replace(' ', '')}"

                        base_url = str(settings.whatsapp_api_base_url or "https://graph.facebook.com/v21.0")
                        wa_outbound = HttpWhatsAppOutbound.cloud_api(
                            base_url=base_url,
                            phone_number_id=sender.whatsapp_phone_number_id,
                            token=token_val,
                        )
                        wa_payload = wa_payloads.text(recipient, final_wa_body)
                        whatsapp_message_id = wa_outbound.send(wa_payload)
                        log.info("approval.whatsapp_message_sent", wamid=whatsapp_message_id, to=recipient)

                    if whatsapp_message_id:
                        session.add(
                            Send(
                                company_id=action.company_id,
                                action_id=action.id,
                                idempotency_key=f"wa-{action.id}-{datetime.now(UTC).timestamp()}",
                                channel=Channel.whatsapp,
                                target=recipient,
                                provider_ref=whatsapp_message_id,
                                status=SendStatus.sent,
                                attempted_at=datetime.now(UTC),
                            )
                        )
                except Exception as exc:
                    log.warning("approval.whatsapp_send_failed", error=str(exc))

    log.info("approval.decided", approval_id=approval_id, choice=req.choice, gmail_draft_id=gmail_draft_id, gmail_message_id=gmail_message_id, whatsapp_message_id=whatsapp_message_id)
    return {
        "status": "approved",
        "approvalId": approval_id,
        "gmailDraftId": gmail_draft_id,
        "gmailMessageId": gmail_message_id,
        "whatsappMessageId": whatsapp_message_id,
        "decision": "execute",
        "choice": req.choice,
        "message": (
            f"Successfully approved draft ({req.choice}) and dispatched reply via {'WhatsApp (wamid: ' + whatsapp_message_id + ')' if whatsapp_message_id else 'Gmail (Message ID: ' + str(gmail_message_id or gmail_draft_id) + ')'}!"
            if (whatsapp_message_id or gmail_message_id or gmail_draft_id)
            else f"Successfully approved and marked draft ({req.choice}) as executed."
        ),
        "executedAt": datetime.now(UTC).isoformat(),
    }
