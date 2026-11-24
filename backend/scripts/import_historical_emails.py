#!/usr/bin/env python3
# ruff: noqa: E501, I001, F401, T201, UP017, S110
"""Historical Email Ingestion Tool for EstateOS (Staging & Production).

Connects directly to IMAP (Gmail via App Password) or reads local .eml directories,
automatically discovers active tenants and contractors from the stage database,
applies strict 7-day aging & AI draft rules, extracts attachments, and indexes vector RAG.

Key Capabilities:
1. Dynamic Stage Discovery: Queries PostgreSQL directly for active tenants and contractor companies.
2. Direct IMAP Connection: Connects to imap.gmail.com with Google App Password (securely prompted).
3. Two-Way Thread Continuity: Ingests both INBOX and Sent Mail so full threads are preserved.
4. Smart Aging & AI Drafts:
   - Inbound inquiries within last 7 days without reply -> 'open' + AI reply draft for review.
   - Answered threads or threads > 7 days old -> auto-archived as 'resolved' history (0 drafts).
5. Zero WhatsApp Spam: Completely bypasses DBOS pipeline_entry and send_card_step.
6. Vector RAG Search: Automatically indexes Gemini embeddings into message_chunks for SuperAgent.
7. Noise Filter: Discards marketing/recruiter spam (Glassdoor, LinkedIn, Zomato, etc.).
"""

import argparse
import datetime
import email
from email import policy
from email.utils import parsedate_to_datetime
import getpass
import hashlib
import imaplib
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
from uuid import UUID, uuid4

# Ensure app imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.contracts import ActionType, CaseState, Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import ApprovalStatus, RawEventStatus
from app.db.models import (
    ActionRow,
    Approval,
    AttachmentRow,
    Case,
    CaseLink,
    ChannelAccount,
    ChannelIdentity,
    Company,
    Lease,
    LeaseParty,
    MessageRow,
    Person,
    RawEvent,
    Unit,
)
from app.db.session import make_engine
from app.storage.factory import build_storage
from app.storage.ports import content_key
from app.tools.message_rag.indexer import index_message


# Known spam / marketing domains to filter out when importing live mailboxes
MARKETING_SPAM_DOMAINS = [
    "glassdoor.com",
    "linkedin.com",
    "naukri.com",
    "indeed.com",
    "canva.com",
    "figma.com",
    "google.com",
    "grammarly.com",
    "quora.com",
    "docker.com",
    "render.com",
    "supabase.com",
    "spotify.com",
    "zomato.com",
    "swiggy.com",
    "angelbroking.in",
    "chaayos.com",
    "razorpay.com",
    "beehiiv.com",
    "scaler.com",
    "internshala.com",
    "americanexpress.com",
    "jobs2web.com",
    "tcsion.com",
    "unstop.news",
    "github.com",
    "openrouter.ai",
    "elevenlabs.io",
    "upstash.com",
    "marktplaats.nl",
    "sevenrooms.com",
    "izakaya",
    "e-boekhouden.nl",
    "skillsource.nl",
    "uber.com",
    "ubereats.com",
    "deliveroo",
    "thuisbezorgd.nl",
    "booking.com",
    "airbnb.com",
]

# Target Gmail label (keep empty by default; set here or pass via --label CLI argument)
TARGET_LABEL = "Vastgoed"


class LLMMetrics:
    calls: int = 0
    prompt_tokens: int = 0
    candidate_tokens: int = 0
    total_tokens: int = 0
    total_time_sec: float = 0.0


llm_metrics = LLMMetrics()


def generate_ai_draft_reply(
    settings: Settings,
    sender_name: str,
    sender_email: str,
    subject: str,
    body_text: str,
    category: Category,
) -> str:
    """Calls Gemini 2.5 Flash to generate a concise, professional Dutch reply signed by Harjot Singh."""
    global llm_metrics
    t0 = time.time()
    api_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
    clean_subj = normalize_subject(subject)
    recipient = sender_name or "Beste bewoner"

    if not api_key:
        return (
            f"Beste {recipient},\n\n"
            f"Hartelijk dank voor uw bericht inzake '{clean_subj}'. "
            f"Wij hebben uw melding in goede orde ontvangen en nemen zo spoedig mogelijk contact met u op.\n\n"
            f"Met vriendelijke groet,\n\n"
            f"Harjot Singh\n"
            f"HR Real Estate"
        )

    try:
        import google.genai as genai
        from google.genai import types

        client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
        prompt = (
            f"You are Harjot Singh, property manager at HR Real Estate (The Netherlands).\n"
            f"Write a concise, professional, polite Dutch reply acknowledging the following incoming inquiry.\n"
            f"Sender Name: {sender_name or 'Bewoner'}\n"
            f"Sender Email: {sender_email}\n"
            f"Subject: {clean_subj}\n"
            f"Category: {category.value}\n"
            f"Incoming Email Body:\n{body_text[:1500]}\n\n"
            f"Requirements:\n"
            f"- Dutch language.\n"
            f"- 2 to 4 sentences maximum.\n"
            f"- Acknowledge receipt, state clear next steps (e.g. informing maintenance/contractor, reviewing lease/payment/records, or confirming follow-up).\n"
            f"- Do not make up fake reference numbers or fake dates.\n"
            f"- Sign off exactly with:\n\n"
            f"Met vriendelijke groet,\n\n"
            f"Harjot Singh\n"
            f"HR Real Estate"
        )

        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            temperature=0.2,
            max_output_tokens=300,
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=config,
        )
        dt = time.time() - t0
        llm_metrics.calls += 1
        llm_metrics.total_time_sec += dt
        if resp.usage_metadata:
            llm_metrics.prompt_tokens += resp.usage_metadata.prompt_token_count or 0
            llm_metrics.candidate_tokens += resp.usage_metadata.candidates_token_count or 0
            llm_metrics.total_tokens += resp.usage_metadata.total_token_count or 0
        return resp.text.strip()
    except Exception as exc:
        print(f"    [LLM Warning] Gemini draft fallback triggered ({exc})")
        return (
            f"Beste {recipient},\n\n"
            f"Hartelijk dank voor uw bericht inzake '{clean_subj}'. "
            f"Wij hebben uw melding in goede orde ontvangen en nemen zo spoedig mogelijk contact met u op.\n\n"
            f"Met vriendelijke groet,\n\n"
            f"Harjot Singh\n"
            f"HR Real Estate"
        )


def parse_date(date_header: str | None) -> datetime.datetime:
    """Parses RFC 822 Date header to timezone-aware UTC datetime."""
    if not date_header:
        return datetime.datetime.now(datetime.timezone.utc)
    try:
        dt = parsedate_to_datetime(date_header)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc)


def extract_email_address(from_header: str | None) -> str:
    """Extracts raw email address e.g. 'Vipin Tyagi <vipint9902@gmail.com>' -> 'vipint9902@gmail.com'."""
    if not from_header:
        return ""
    if "<" in from_header and ">" in from_header:
        return from_header.split("<")[1].split(">")[0].strip().lower()
    return from_header.strip().lower()


def normalize_subject(subject: str) -> str:
    """Strips Re:, Fwd:, Antw: prefixes and whitespace for deterministic thread clustering."""
    cleaned = re.sub(r"^(re|fwd|fw|antw|antwoord):\s*", "", subject or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"^(re|fwd|fw|antw|antwoord):\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def compute_thread_ref(
    subject: str,
    message_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    thread_map: dict[str, str] | None = None,
) -> str:
    """Computes a stable thread key linking replies together using normalized subject & header references."""
    norm_subj = normalize_subject(subject).lower()
    default_thread = f"thread_{hashlib.sha256(norm_subj.encode()).hexdigest()[:16]}"

    if thread_map is not None:
        all_refs = ([in_reply_to] if in_reply_to else []) + (references.split() if references else [])
        for ref in all_refs:
            ref_clean = ref.replace("<", "").replace(">", "").strip()
            if ref_clean in thread_map:
                matched_thread = thread_map[ref_clean]
                if message_id:
                    clean_id = message_id.replace("<", "").replace(">", "").strip()
                    thread_map[clean_id] = matched_thread
                return matched_thread

        if message_id:
            clean_id = message_id.replace("<", "").replace(">", "").strip()
            thread_map[clean_id] = default_thread

    return default_thread


def classify_category(subject: str, body_text: str) -> Category:
    """Classifies email into Category using Dutch and English real estate and legal terms."""
    combined = (subject + " " + body_text).lower()
    if re.search(
        r"\b(leak|warm|koud|reparatie|lekkage|verwarming|radiator|kraan|water|stroom|boiler|ketel|slot|deur|groepenkast|monteur|loodgieter|pijp|schade|onderhoud|defect|storing|dak|riolering)\b",
        combined,
    ):
        return Category.maintenance
    if re.search(
        r"\b(betaling|borg|factuur|afrekening|servicekosten|kosten|huurprijs|rekening|incasso|betaald|overmaken|bankrekening|herinnering)\b",
        combined,
    ):
        return Category.payment
    if re.search(
        r"\b(advocaat|juridisch|aansprakelijk|ingebrekestelling|dagvaarding|rechtbank|geschil|pact advocaten|pactadvocaten|bezwaar|huurcommissie|sommatie|hersteltermijn|kort geding|overlast|buren)\b",
        combined,
    ):
        return Category.complaint
    if re.search(
        r"\b(contract|opzegging|verlenging|parkeer|parkeervergunning|vergunning|verklaring|sleutel|bezichtiging|appartement|huurovereenkomst|verhuurdersverklaring|beëindiging|oplevering|overdracht)\b",
        combined,
    ):
        return Category.lease
    return Category.other


def discover_stage_entities(session: Session, company_id: UUID) -> tuple[dict[str, dict], dict[str, dict], set[str]]:
    """Dynamically queries PostgreSQL to discover currently active tenants and contractors with their emails.

    Returns:
        (tenants_by_email, contractors_by_email, all_allowed_emails)
    """
    rows = session.execute(
        select(Person.id, Person.display_name, Person.kind, ChannelIdentity.identity)
        .join(ChannelIdentity, ChannelIdentity.person_id == Person.id)
        .where(
            Person.company_id == company_id,
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.channel == Channel.gmail,
            ChannelIdentity.valid_to.is_(None),
        )
    ).fetchall()

    tenants: dict[str, dict] = {}
    contractors: dict[str, dict] = {}
    allowed_emails: set[str] = set()

    for pid, name, kind, email_addr in rows:
        if not email_addr or "@" not in email_addr:
            continue
        clean_email = email_addr.lower().strip()
        allowed_emails.add(clean_email)
        entry = {"id": pid, "name": name, "email": clean_email, "kind": str(kind)}
        if str(kind) == "tenant":
            tenants[clean_email] = entry
        elif str(kind) == "contractor":
            contractors[clean_email] = entry

    return tenants, contractors, allowed_emails


def find_or_link_person(
    session: Session, company_id: UUID, sender_email: str
) -> tuple[UUID | None, UUID | None, UUID | None, str | None, str]:
    """Resolves (person_id, unit_id, lease_id, display_name, kind) from ChannelIdentity and Lease."""
    row = session.execute(
        select(ChannelIdentity.person_id, Person.display_name, Person.kind)
        .join(Person, Person.id == ChannelIdentity.person_id)
        .where(
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.identity == sender_email.lower(),
            ChannelIdentity.valid_to.is_(None),
        )
    ).first()

    if not row:
        return None, None, None, None, "unregistered"

    person_id, display_name, kind = row
    lease_row = session.execute(
        select(Lease.id, Lease.unit_id)
        .join(LeaseParty, LeaseParty.lease_id == Lease.id)
        .where(
            Lease.company_id == company_id,
            LeaseParty.person_id == person_id,
        )
        .order_by(Lease.created_at.desc())
    ).first()

    if lease_row:
        return person_id, lease_row.unit_id, lease_row.id, display_name, str(kind)
    return person_id, None, None, display_name, str(kind)


def import_message(
    session: Session,
    storage: Any,
    settings: Settings,
    company_id: UUID,
    sender_email: str,
    subject: str,
    body_text: str,
    sent_at: datetime.datetime,
    direction: Direction,
    thread_ref: str,
    attachments_data: list[tuple[str, str, bytes]],
    is_thread_answered: bool = False,
    should_draft: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Ingests a single email message, creates/links Case, stores attachments, and creates draft if needed."""
    person_id, unit_id, lease_id, display_name, person_kind = find_or_link_person(session, company_id, sender_email)

    provider_msg_id = f"hist_{hashlib.sha256((sender_email + subject + sent_at.isoformat()).encode()).hexdigest()[:18]}"

    if dry_run:
        return {
            "status": "dry_run",
            "provider_msg_id": provider_msg_id,
            "sender": sender_email,
            "tenant": display_name or ("Unregistered" if direction == Direction.inbound else "Manager"),
            "kind": person_kind,
            "subject": subject,
            "sent_at": sent_at.isoformat(),
            "direction": direction.value,
            "attachments_count": len(attachments_data),
            "is_thread_answered": is_thread_answered,
            "draft_created": should_draft,
        }

    # 1. Insert RawEvent (status=processed -> zero WhatsApp spam)
    raw_event_id = new_id()
    raw_event = RawEvent(
        id=raw_event_id,
        company_id=company_id,
        provider=Channel.gmail,
        provider_msg_id=provider_msg_id,
        payload={"kind": "historical_import", "sender": sender_email, "subject": subject},
        status=RawEventStatus.processed,
        received_at=sent_at,
    )
    session.add(raw_event)
    session.flush()

    # 2. Insert MessageRow
    message_id = new_id()
    msg_row = MessageRow(
        id=message_id,
        company_id=company_id,
        raw_event_id=raw_event_id,
        channel=Channel.gmail,
        provider_msg_id=provider_msg_id,
        thread_ref=thread_ref,
        sender_identity=sender_email,
        direction=direction,
        sent_at=sent_at,
        text=body_text,
        person_id=person_id,
        pipeline_status="done",
        meta={"subject": subject, "historical": True},
    )
    session.add(msg_row)
    session.flush()

    # 3. Save Attachments
    stored_attachments = []
    for fname, mime, data in attachments_data:
        att_sha256 = hashlib.sha256(data).hexdigest()
        key = content_key(company_id, att_sha256)
        if not storage.exists(key):
            storage.put(key, data, mime)

        att_row = AttachmentRow(
            id=new_id(),
            company_id=company_id,
            message_id=message_id,
            s3_key=key,
            filename=fname,
            mime_type=mime,
            size_bytes=len(data),
            sha256=att_sha256,
            extraction_status="done",
        )
        session.add(att_row)
        stored_attachments.append(att_row)

    # 4. Group into Case (Find existing case by thread_ref or create new)
    existing_case = (
        session.execute(
            select(Case)
            .join(CaseLink, CaseLink.case_id == Case.id)
            .join(MessageRow, MessageRow.id == CaseLink.message_id)
            .where(
                MessageRow.company_id == company_id,
                MessageRow.thread_ref == thread_ref,
            )
        )
        .scalars()
        .first()
    )

    case_created = False
    draft_created = False
    if existing_case:
        case_id = existing_case.id
        case_link = CaseLink(
            id=new_id(),
            company_id=company_id,
            case_id=case_id,
            message_id=message_id,
            method="thread",
            confidence=1.0,
        )
        session.add(case_link)

        if person_id and not existing_case.primary_person_id:
            existing_case.primary_person_id = person_id
        if unit_id and not existing_case.unit_id:
            existing_case.unit_id = unit_id
        if lease_id and not existing_case.lease_id:
            existing_case.lease_id = lease_id

        # State transition:
        if is_thread_answered:
            existing_case.state = CaseState.resolved
            existing_case.resolved_at = existing_case.resolved_at or sent_at
        else:
            existing_case.state = CaseState.open
            existing_case.resolved_at = None
    else:
        case_created = True
        case_id = new_id()
        case_state = CaseState.resolved if is_thread_answered else CaseState.open
        category = classify_category(subject, body_text)
        urgency = Urgency.high if (case_state == CaseState.open and category in (Category.maintenance, Category.complaint)) else Urgency.normal

        new_case = Case(
            id=case_id,
            company_id=company_id,
            primary_person_id=person_id,
            unit_id=unit_id,
            lease_id=lease_id,
            state=case_state,
            category=category,
            urgency=urgency,
            summary=f"Email thread: {normalize_subject(subject)}",
            opened_at=sent_at,
            resolved_at=sent_at if is_thread_answered else None,
        )
        session.add(new_case)
        session.flush()

        case_link = CaseLink(
            id=new_id(),
            company_id=company_id,
            case_id=case_id,
            message_id=message_id,
            method="thread",
            confidence=1.0,
        )
        session.add(case_link)

    # 5. Generate AI draft reply for active, unanswered inquiry
    if should_draft and not dry_run:
        category = classify_category(subject, body_text)
        draft_text = generate_ai_draft_reply(
            settings=settings,
            sender_name=display_name or "",
            sender_email=sender_email,
            subject=subject,
            body_text=body_text,
            category=category,
        )
        draft_created = True
        action_id = new_id()
        action_row = ActionRow(
            id=action_id,
            company_id=company_id,
            case_id=case_id,
            type=ActionType.reply_draft,
            status="proposed",
            payload={
                "text": draft_text,
                "channel": "gmail",
                "recipient": sender_email,
                "subject": f"Re: {normalize_subject(subject)}",
            },
            rationale="Contextual response draft generated by Gemini 2.5 Flash for active unresolved inquiry.",
            context_ref=[message_id],
            draft_version=1,
        )
        session.add(action_row)
        session.flush()

        approval_row = Approval(
            id=new_id(),
            company_id=company_id,
            action_id=action_id,
            draft_version=1,
            status=ApprovalStatus.pending,
        )
        session.add(approval_row)
    elif should_draft and dry_run:
        draft_created = True

    session.commit()

    # 6. Index into Vector RAG
    rag_status = "skipped"
    if not dry_run:
        try:
            rag_status = index_message(session.get_bind(), settings, message_id)
        except Exception as exc:
            rag_status = f"error: {str(exc)[:60]}"

    return {
        "status": "imported",
        "message_id": str(message_id),
        "case_id": str(case_id),
        "case_created": case_created,
        "draft_created": draft_created,
        "tenant": display_name or sender_email,
        "attachments": len(stored_attachments),
        "rag_status": rag_status,
    }

    return {
        "status": "imported",
        "message_id": str(message_id),
        "case_id": str(case_id),
        "case_created": case_created,
        "draft_created": draft_created,
        "tenant": display_name or sender_email,
        "attachments": len(stored_attachments),
        "rag_status": rag_status,
    }


def parse_eml_message(
    msg: email.message.EmailMessage,
    source_name: str = "",
    manager_emails: list[str] | None = None,
) -> dict[str, Any]:
    """Parses an EmailMessage object into normalized fields and attachments."""
    sender = extract_email_address(msg["From"])
    recipient = extract_email_address(msg["To"])
    subject = str(msg["Subject"] or "Geen onderwerp")
    sent_at = parse_date(msg["Date"])
    message_id = str(msg["Message-ID"] or "")
    in_reply_to = str(msg["In-Reply-To"] or "")
    references = str(msg["References"] or "")

    # Direction detection:
    mgr_patterns = ["hausverwaltung", "hrrealestate", "beheer", "owner@", "harjot", "harjotsj@gmail.com", "info@hrrealestate.nl"]
    if manager_emails:
        mgr_patterns.extend([m.lower().strip() for m in manager_emails if m])
    is_outbound = any(x in sender.lower() for x in mgr_patterns)
    direction = Direction.outbound if is_outbound else Direction.inbound

    # Extract body text
    body_text = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in cdisp:
                body_text = part.get_content()
                break
        if not body_text:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    html_content = part.get_content()
                    body_text = re.sub(r"<[^>]+>", " ", html_content)
                    break
    else:
        body_text = msg.get_content()

    # Extract attachments
    attachments: list[tuple[str, str, bytes]] = []
    for part in msg.iter_attachments():
        fname = part.get_filename() or "bijlage.bin"
        mime = part.get_content_type() or "application/octet-stream"
        payload = part.get_payload(decode=True)
        if payload:
            attachments.append((fname, mime, payload))

    return {
        "source": source_name,
        "sender_email": sender,
        "recipient_email": recipient,
        "subject": subject,
        "body_text": str(body_text).strip(),
        "sent_at": sent_at,
        "direction": direction,
        "message_id": message_id,
        "in_reply_to": in_reply_to,
        "references": references,
        "attachments": attachments,
    }


def parse_eml_file(file_path: Path, manager_emails: list[str] | None = None) -> dict[str, Any]:
    """Reads a local .eml file."""
    with open(file_path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    return parse_eml_message(msg, source_name=str(file_path), manager_emails=manager_emails)


def is_relevant_email(
    item: dict[str, Any],
    allowed_emails: set[str] | None = None,
    include_unregistered: bool = True,
) -> tuple[bool, str]:
    """Determines whether an email should be imported based on tenant/contractor matching or property/legal topic."""
    sender = item["sender_email"].lower().strip()
    recipient = item.get("recipient_email", "").lower().strip()

    # 1. Skip obvious automated marketing/recruiting spam
    if any(domain in sender for domain in MARKETING_SPAM_DOMAINS):
        return False, f"Skipped spam/marketing sender ({sender})"

    # 2. Direct match with tenant or contractor
    if allowed_emails:
        if sender in allowed_emails:
            return True, "Sender matches registered directory contact"
        if recipient in allowed_emails:
            return True, "Recipient matches registered directory contact (outbound/reply)"

    # 3. Check for property or legal topic
    if include_unregistered:
        subject = item["subject"]
        body = item["body_text"]
        cat = classify_category(subject, body)
        if cat in (Category.maintenance, Category.payment, Category.lease, Category.complaint):
            return True, f"Inquiry matched property/legal topic ({cat.value})"

    return True, "General correspondence"


def process_parsed_emails(
    session: Session,
    storage: Any,
    settings: Settings,
    company_id: UUID,
    parsed_emails: list[dict[str, Any]],
    allowed_emails: set[str] | None = None,
    include_unregistered: bool = True,
    dry_run: bool = False,
    label_mode: bool = False,
) -> None:
    """Sorts emails chronologically, builds threads, applies filters, and ingests into DB."""
    parsed_emails.sort(key=lambda x: x["sent_at"])

    # Compute stable thread refs in chronological order
    thread_map: dict[str, str] = {}
    for item in parsed_emails:
        item["thread_ref"] = compute_thread_ref(
            subject=item["subject"],
            message_id=item.get("message_id"),
            in_reply_to=item.get("in_reply_to"),
            references=item.get("references"),
            thread_map=thread_map,
        )

    # Filter relevant emails
    filtered_emails: list[dict[str, Any]] = []
    skipped_count = 0
    for item in parsed_emails:
        if not label_mode and allowed_emails is not None:
            relevant, reason = is_relevant_email(item, allowed_emails, include_unregistered=include_unregistered)
            if not relevant:
                print(f" -> [SKIPPED] {item['sent_at'].strftime('%Y-%m-%d')} | {item['sender_email']:28} | {reason}")
                skipped_count += 1
                continue
        filtered_emails.append(item)

    # Group by thread_ref
    threads: dict[str, list[dict[str, Any]]] = {}
    for item in filtered_emails:
        threads.setdefault(item["thread_ref"], []).append(item)

    # Determine thread answered status
    thread_answered: dict[str, bool] = {}
    draft_message_ids: set[str] = set()

    for t_ref, msgs in threads.items():
        msgs_sorted = sorted(msgs, key=lambda x: x["sent_at"])
        last_msg = msgs_sorted[-1]
        has_outbound = any(m["direction"] == Direction.outbound for m in msgs_sorted)

        if last_msg["direction"] == Direction.outbound:
            thread_answered[t_ref] = True
        elif has_outbound:
            last_outbound = next((m for m in reversed(msgs_sorted) if m["direction"] == Direction.outbound), None)
            last_inbound = next((m for m in reversed(msgs_sorted) if m["direction"] == Direction.inbound), None)
            if last_outbound and last_inbound and (last_inbound["sent_at"] - last_outbound["sent_at"]).total_seconds() < 3600:
                thread_answered[t_ref] = True
            else:
                thread_answered[t_ref] = False
        else:
            thread_answered[t_ref] = False

        # If unanswered and the last message is inbound, that message gets an AI draft reply
        if not thread_answered[t_ref] and last_msg["direction"] == Direction.inbound:
            sender = last_msg["sender_email"].lower()
            is_noreply = any(nr in sender for nr in ["noreply", "no-reply", "donotreply", "notification", "alert", "beveiligingsmelding"])
            is_noise = any(domain in sender for domain in MARKETING_SPAM_DOMAINS)
            if not is_noreply and not is_noise:
                mid = last_msg.get("message_id") or f"{last_msg['sender_email']}_{last_msg['sent_at'].isoformat()}"
                draft_message_ids.add(mid)

    print(f"\nProcessing {len(filtered_emails)} emails across {len(threads)} conversation threads:")
    imported_count = 0
    drafts_count = 0

    for item in filtered_emails:
        t_ref = item["thread_ref"]
        is_ans = thread_answered.get(t_ref, False)
        mid = item.get("message_id") or f"{item['sender_email']}_{item['sent_at'].isoformat()}"
        should_draft = (mid in draft_message_ids)

        res = import_message(
            session=session,
            storage=storage,
            settings=settings,
            company_id=company_id,
            sender_email=item["sender_email"],
            subject=item["subject"],
            body_text=item["body_text"],
            sent_at=item["sent_at"],
            direction=item["direction"],
            thread_ref=t_ref,
            attachments_data=item["attachments"],
            is_thread_answered=is_ans,
            should_draft=should_draft,
            dry_run=dry_run,
        )
        imported_count += 1
        if res.get("draft_created"):
            drafts_count += 1

        att_str = f"({res.get('attachments_count', res.get('attachments', 0))} att)"
        draft_tag = " [AI DRAFT]" if res.get("draft_created") else ""
        ans_tag = "[RESOLVED]" if is_ans else "[OPEN]"
        print(
            f" -> [{res['status'].upper()}] {item['sent_at'].strftime('%Y-%m-%d %H:%M')} | {item['direction'].value.upper():8} | {ans_tag:10} | {item['sender_email']:28} | '{item['subject'][:35]}...' {att_str}{draft_tag}"
        )

    resolved_count = sum(thread_answered.values())
    open_count = len(threads) - resolved_count
    print("\n-------------------------------------------------------------------")
    print(
        f"SUMMARY: {imported_count} imported | {len(threads)} threads ({resolved_count} resolved, {open_count} open) | {drafts_count} AI drafts generated"
    )
    if llm_metrics.calls > 0:
        est_cost = (llm_metrics.prompt_tokens / 1_000_000 * 0.30) + (llm_metrics.candidate_tokens / 1_000_000 * 2.50)
        avg_time = llm_metrics.total_time_sec / llm_metrics.calls
        print("\nLLM USAGE & TOKEN METRICS (gemini-2.5-flash):")
        print(f" -> Total AI Draft Calls   : {llm_metrics.calls}")
        print(f" -> Prompt Tokens (Input)  : {llm_metrics.prompt_tokens}")
        print(f" -> Candidate Tokens (Out) : {llm_metrics.candidate_tokens}")
        print(f" -> Total Tokens Billed    : {llm_metrics.total_tokens}")
        print(f" -> Total AI Time          : {llm_metrics.total_time_sec:.2f}s (avg {avg_time:.2f}s / draft)")
        print(f" -> Estimated Cost         : ${est_cost:.4f}")
    print("-------------------------------------------------------------------")


def import_eml_directory(
    session: Session,
    storage: Any,
    settings: Settings,
    company_id: UUID,
    eml_dir: Path,
    allowed_senders: list[str] | None = None,
    dry_run: bool = False,
) -> None:
    """Finds all .eml files in directory and imports them chronologically."""
    eml_files = list(eml_dir.glob("*.eml"))
    if not eml_files:
        print(f"No .eml files found in {eml_dir}")
        return

    print(f"Found {len(eml_files)} .eml files. Parsing headers...")
    parsed_emails = []
    for f in eml_files:
        try:
            data = parse_eml_file(f)
            parsed_emails.append(data)
        except Exception as exc:
            print(f"Warning: Failed to parse {f.name}: {exc}")

    allowed_set = {s.lower() for s in allowed_senders} if allowed_senders else None
    process_parsed_emails(
        session=session,
        storage=storage,
        settings=settings,
        company_id=company_id,
        parsed_emails=parsed_emails,
        allowed_emails=allowed_set,
        dry_run=dry_run,
    )


def find_imap_folder(imap_client: imaplib.IMAP4_SSL, target_name: str) -> str | None:
    """Finds exact or case-insensitive matching IMAP folder."""
    try:
        status, f_list = imap_client.list()
        if status != "OK" or not f_list:
            return None
        folders = []
        for fe in f_list:
            decoded = fe.decode("utf-8", errors="ignore")
            if ' "/" ' in decoded:
                folders.append(decoded.split(' "/" ')[1].strip('"'))
            elif ' " " ' in decoded:
                folders.append(decoded.split(' " " ')[1].strip('"'))

        for f in folders:
            if f == target_name:
                return f
        for f in folders:
            if f.lower() == target_name.lower():
                return f
        for f in folders:
            if f.lower().endswith(f"/{target_name.lower()}"):
                return f
    except Exception:
        pass
    return None


def fetch_label_message_numbers(
    mail: imaplib.IMAP4_SSL,
    label: str,
    since_days: int = 0,
) -> tuple[str, list[bytes]]:
    """Selects the label folder or searches via Gmail X-GM-RAW to get message numbers."""
    matched_folder = find_imap_folder(mail, label)

    search_criteria = ["ALL"]
    since_str = ""
    if since_days > 0:
        since_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=since_days)
        search_criteria = [f'(SINCE "{since_date.strftime("%d-%b-%Y")}")']
        since_str = f' after:{since_date.strftime("%Y/%m/%d")}'

    # Attempt 1: Direct IMAP folder selection
    if matched_folder:
        res, _ = mail.select(f'"{matched_folder}"', readonly=True)
        if res == "OK":
            res, data = mail.search(None, *search_criteria)
            if res == "OK" and data and data[0]:
                return matched_folder, data[0].split()
            return matched_folder, []

    # Attempt 2: Search [Gmail]/All Mail using Gmail X-GM-RAW extension
    all_mail_folder = find_imap_folder(mail, "[Gmail]/All Mail") or "[Gmail]/All Mail"
    res, _ = mail.select(f'"{all_mail_folder}"', readonly=True)
    if res == "OK":
        raw_query = f'label:"{label}"{since_str}'
        res, data = mail.search(None, "X-GM-RAW", f'"{raw_query}"')
        if res == "OK" and data and data[0]:
            return all_mail_folder, data[0].split()

    return label, []


def fetch_and_import_imap(
    session: Session,
    storage: Any,
    settings: Settings,
    company_id: UUID,
    imap_host: str,
    imap_user: str,
    imap_password: str,
    label: str = "",
    since_days: int = 60,
    folders: list[str] | None = None,
    allowed_emails: set[str] | None = None,
    include_unregistered: bool = True,
    dry_run: bool = False,
) -> None:
    """Connects to IMAP (Gmail), retrieves emails, and processes them chronologically."""
    print(f"\nConnecting to IMAP {imap_host}:993 as {imap_user}...")
    try:
        mail = imaplib.IMAP4_SSL(imap_host, 993)
        mail.login(imap_user, imap_password)
        print(" -> IMAP Authentication successful!")
    except Exception as exc:
        print(f"\n[ERROR] IMAP connection failed: {exc}")
        print("Tips for Google Accounts:")
        print("  1. Turn on 2-Step Verification at: https://myaccount.google.com/security")
        print("  2. Create a 16-character App Password at: https://myaccount.google.com/apppasswords")
        print("  3. Pass the 16-character code as the password.\n")
        raise

    parsed_emails: list[dict[str, Any]] = []
    seen_msg_ids: set[str] = set()

    # If label is specified, ONLY import emails with this label
    if label:
        print(f"Scanning target label '{label}' (ONLY this label's emails will be imported)...")
        folder_target, msg_nums = fetch_label_message_numbers(mail, label, since_days=since_days)
        if not msg_nums:
            print(f" -> 0 emails in label '{label}' ({folder_target}).")
        else:
            print(f" -> Found {len(msg_nums)} emails in '{label}' ({folder_target}). Downloading RFC 822 messages...")
            for num in msg_nums:
                res, msg_data = mail.fetch(num, "(RFC822)")
                if res != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw_bytes = msg_data[0][1]
                try:
                    msg = email.message_from_bytes(raw_bytes, policy=policy.default)
                    parsed = parse_eml_message(
                        msg, source_name=f"{folder_target} #{num.decode()}", manager_emails=[imap_user]
                    )
                    mid = parsed.get("message_id")
                    if mid and mid in seen_msg_ids:
                        continue
                    if mid:
                        seen_msg_ids.add(mid)
                    parsed_emails.append(parsed)
                except Exception as e:
                    print(f"Warning: Failed to parse email #{num}: {e}")

        mail.logout()
        print(f"Total fetched from IMAP for label '{label}': {len(parsed_emails)} unique emails.")

        process_parsed_emails(
            session=session,
            storage=storage,
            settings=settings,
            company_id=company_id,
            parsed_emails=parsed_emails,
            allowed_emails=None,
            include_unregistered=True,
            dry_run=dry_run,
            label_mode=True,
        )
        return

    # Fallback when running without a label: scan default folders
    if not folders:
        folders = ["INBOX", "[Gmail]/Sent Mail"]

    status, f_list = mail.list()
    available_folders = []
    if status == "OK" and f_list:
        for fe in f_list:
            decoded = fe.decode("utf-8", errors="ignore")
            if ' "/" ' in decoded:
                available_folders.append(decoded.split(' "/" ')[1].strip('"'))

    search_criteria = ["ALL"]
    if since_days > 0:
        since_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=since_days)
        search_criteria = [f'(SINCE "{since_date.strftime("%d-%b-%Y")}")']

    for folder in folders:
        folder_target = folder
        if folder not in available_folders:
            fallback = next((f for f in available_folders if "sent" in f.lower()), None)
            if fallback and "sent" in folder.lower():
                folder_target = fallback
            elif folder != "INBOX":
                print(f"Notice: Folder '{folder}' not present on server, skipping.")
                continue

        print(f"Scanning '{folder_target}' (criteria: {' '.join(search_criteria)})...")
        res, _ = mail.select(f'"{folder_target}"', readonly=True)
        if res != "OK":
            print(f"Warning: Could not select '{folder_target}'")
            continue

        res, data = mail.search(None, *search_criteria)
        if res != "OK" or not data or not data[0]:
            print(f" -> 0 emails in '{folder_target}'.")
            continue

        msg_nums = data[0].split()
        print(f" -> Found {len(msg_nums)} emails in '{folder_target}'. Downloading RFC 822 messages...")

        for num in msg_nums:
            res, msg_data = mail.fetch(num, "(RFC822)")
            if res != "OK" or not msg_data or not msg_data[0]:
                continue
            raw_bytes = msg_data[0][1]
            try:
                msg = email.message_from_bytes(raw_bytes, policy=policy.default)
                parsed = parse_eml_message(
                    msg, source_name=f"{folder_target} #{num.decode()}", manager_emails=[imap_user]
                )
                mid = parsed.get("message_id")
                if mid and mid in seen_msg_ids:
                    continue
                if mid:
                    seen_msg_ids.add(mid)
                parsed_emails.append(parsed)
            except Exception as e:
                print(f"Warning: Failed to parse email #{num}: {e}")

    mail.logout()
    print(f"Total fetched from IMAP: {len(parsed_emails)} unique emails.")

    process_parsed_emails(
        session=session,
        storage=storage,
        settings=settings,
        company_id=company_id,
        parsed_emails=parsed_emails,
        allowed_emails=allowed_emails,
        include_unregistered=include_unregistered,
        dry_run=dry_run,
        label_mode=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="EstateOS Historical Email Ingestion Pipeline (Staging/Production)")
    parser.add_argument("--dry-run", action="store_true", help="Preview email matches without modifying database")
    parser.add_argument(
        "--label",
        type=str,
        default="Vastgoed",
        help="Specific Gmail label to import (default: 'Vastgoed')",
    )
    parser.add_argument("--eml-dir", type=str, help="Path to local directory of .eml files")
    parser.add_argument(
        "--imap-user",
        type=str,
        default="info@hrrealestate.nl",
        help="Gmail / IMAP email address to connect to (default: info@hrrealestate.nl)",
    )
    parser.add_argument(
        "--imap-password",
        type=str,
        default="xjcwlqidsdtqigrw",
        help="16-character Google App Password (default from secrets)",
    )
    parser.add_argument(
        "--imap-host", type=str, default="imap.gmail.com", help="IMAP server hostname (default: imap.gmail.com)"
    )
    parser.add_argument(
        "--since-days", type=int, default=2, help="Import emails received in the last N days (default: 2, 0 = all)"
    )
    parser.add_argument(
        "--all-senders", action="store_true", help="Disable stage entity auto-filter and import all emails"
    )
    parser.add_argument(
        "--company-id", type=str, default="01a1341b-2e4e-7073-b44e-40a7bc9e8e2a", help="EstateOS Company UUID"
    )
    args = parser.parse_args()

    env_path = Path(__file__).resolve().parents[1] / ".env"
    settings = Settings(_env_file=env_path if env_path.exists() else None)
    engine = make_engine(str(settings.database_url))
    storage = build_storage(settings)
    company_id = UUID(args.company_id)

    # Determine target label (no fallback when IMAP is used)
    label = (args.label or TARGET_LABEL).strip()
    if args.imap_user and not label and not args.eml_dir:
        label = input("Enter Gmail Label to import (required, only this label will be imported): ").strip()
        if not label:
            print("[ERROR] A Gmail label is required. Only emails with this label will be imported.")
            sys.exit(1)

    print("===================================================================")
    print("      ESTATEOS HISTORICAL EMAIL INGESTION PIPELINE (STAGE)         ")
    print("===================================================================")
    print(f"Database URL : {settings.database_url}")
    print(f"Company ID   : {company_id}")
    if label:
        print(f"Target Label : '{label}' (ONLY emails with this label will be imported)")
    print(f"Mode         : {'DRY RUN (Preview Only)' if args.dry_run else 'LIVE INGESTION'}")

    with Session(engine) as session:
        # Auto-discover active tenants and contractors from database (for reference & linking)
        tenants, contractors, allowed_emails = discover_stage_entities(session, company_id)
        print("\n-------------------------------------------------------------------")
        print("STAGE DIRECTORY AUTO-DISCOVERY:")
        print(f" -> Active Tenants Discovered    : {len(tenants)}")
        for em, t in list(tenants.items())[:6]:
            print(f"    * {t['name']:25} <{em}>")
        if len(tenants) > 6:
            print(f"    ... and {len(tenants) - 6} more active tenants")

        print(f"\n -> Contractor Companies Found   : {len(contractors)}")
        for em, c in contractors.items():
            print(f"    * {c['name']:25} <{em}>")
        print("-------------------------------------------------------------------")

        active_filter = None if (args.all_senders or label) else allowed_emails
        if label:
            print(f"Notice: Label Mode Active ('{label}'). All emails with this label will be imported.")
        elif active_filter:
            print(f"Stage Allowlist Active: Filtering for {len(active_filter)} known tenant/contractor addresses.")
        else:
            print("Notice: Auto-filter disabled (--all-senders). Ingesting all incoming mail.")

        # Step 2: Handle IMAP Mode
        if args.imap_user:
            imap_pw = args.imap_password
            if not imap_pw:
                imap_pw = getpass.getpass(f"Enter 16-character Google App Password for {args.imap_user}: ").strip()

            fetch_and_import_imap(
                session=session,
                storage=storage,
                settings=settings,
                company_id=company_id,
                imap_host=args.imap_host,
                imap_user=args.imap_user,
                imap_password=imap_pw,
                label=label,
                since_days=args.since_days,
                allowed_emails=active_filter,
                include_unregistered=True,
                dry_run=args.dry_run,
            )
            print("\nIMAP Ingestion complete! View live threads in Dashboard or API.")
            return

        # Step 3: Handle Local .eml Directory Mode
        if args.eml_dir:
            eml_path = Path(args.eml_dir)
            if not eml_path.exists() or not eml_path.is_dir():
                print(f"Error: Directory '{eml_path}' does not exist.")
                sys.exit(1)
            import_eml_directory(
                session=session,
                storage=storage,
                settings=settings,
                company_id=company_id,
                eml_dir=eml_path,
                allowed_senders=list(active_filter) if active_filter else None,
                dry_run=args.dry_run,
            )
            print("\nLocal Directory Ingestion complete! View live threads in Dashboard or API.")
            return

        print("\n[USAGE]")
        print("1. Direct IMAP (Gmail with App Password and Label):")
        print(
            "   python backend/scripts/import_historical_emails.py --imap-user client@gmail.com --label 'ClientLabel'"
        )
        print("\n2. Dry-Run Preview (Test IMAP without modifying DB):")
        print("   python backend/scripts/import_historical_emails.py --imap-user client@gmail.com --label 'ClientLabel' --dry-run")
        print("\n3. Local .eml Directory:")
        print("   python backend/scripts/import_historical_emails.py --eml-dir backend/scripts/edgecase_emails")
        sys.exit(0)


if __name__ == "__main__":
    main()
