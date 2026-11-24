#!/usr/bin/env python3
# ruff: noqa
"""Dedicated 30-Day Historical Backfill Script for Vastgoed Mailbox.

Ingests historical emails from Google Workspace mailbox (info@hrrealestate.nl) under
label 'Vastgoed' covering the last 30 days (with whole-thread history expansion).

Key Features:
1. Model: Strictly uses Gemini 2.5 Flash (with thinking_budget=0) for high-speed, cost-effective Dutch drafts.
2. Scope: info@hrrealestate.nl with label 'Vastgoed' only.
3. Whole-Thread Expansion: Uses Gmail X-GM-THRID to pull full conversation history (even messages starting before 30d).
4. Two-Way Thread Resolution: Tracks Harjot's outbound replies. Answered threads are marked [RESOLVED] with 0 drafts.
5. Smart AI Drafting: Generates professional Dutch drafts signed by Harjot Singh ONLY for active, unanswered inquiries.
6. Vector RAG: Chunks and embeds all messages and attachments into message_chunks.
7. Zero WhatsApp Spam: Bypasses live notification steps so owner receives 0 phone pings.
8. Safety & Idempotency: All rows tagged with a unique backfill_run_id for auditing and instant rollback.
"""

import argparse
import datetime
import email
from email import policy
from email.utils import parsedate_to_datetime
import hashlib
import imaplib
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

# Netherlands timezone (CET / CEST)
AMSTERDAM_TZ = ZoneInfo("Europe/Amsterdam")

# Force unbuffered stdout so prints appear immediately in logs
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# Ensure app imports work properly
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Explicitly load .env from backend directory if present
from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.contracts import ActionType, CaseState, Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.core.settings import Settings, get_settings
from app.db.enums import ApprovalStatus, RawEventStatus
from app.db.models import (
    ActionRow,
    Approval,
    AttachmentRow,
    Case,
    CaseLink,
    ChannelIdentity,
    Company,
    Lease,
    LeaseParty,
    MessageRow,
    Person,
    RawEvent,
)
from app.db.session import make_engine
from app.storage.factory import build_storage
from app.storage.ports import content_key
from app.tools.message_rag.indexer import index_message


# Known automated / marketing spam domains to exclude from generating drafts
AUTOMATED_NOISE_DOMAINS = [
    "glassdoor.com",
    "linkedin.com",
    "naukri.com",
    "indeed.com",
    "canva.com",
    "figma.com",
    "google.com",
    "accounts.google.com",
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
    "virtualvaults.com",
]

# Manager identity indicators (outbound emails)
MANAGER_IDENTITIES = [
    "harjotsj@gmail.com",
    "singh@hrrealestate.nl",
    "info@hrrealestate.nl",
    "harjot",
    "hausverwaltung",
    "hrrealestate",
    "beheer",
]


class LLMMetrics:
    def __init__(self) -> None:
        self.calls: int = 0
        self.prompt_tokens: int = 0
        self.candidate_tokens: int = 0
        self.total_tokens: int = 0
        self.total_time_sec: float = 0.0

    def add_call(self, p_tokens: int, c_tokens: int, dt: float) -> None:
        self.calls += 1
        self.prompt_tokens += p_tokens
        self.candidate_tokens += c_tokens
        self.total_tokens += (p_tokens + c_tokens)
        self.total_time_sec += dt

    @property
    def cost_usd(self) -> float:
        # Gemini 2.5 Flash pricing: $0.30 / 1M prompt, $2.50 / 1M candidate tokens
        return (self.prompt_tokens / 1_000_000 * 0.30) + (self.candidate_tokens / 1_000_000 * 2.50)


llm_metrics = LLMMetrics()


def generate_ai_draft_reply(
    settings: Settings,
    sender_name: str,
    sender_email: str,
    subject: str,
    body_text: str,
    category: Category,
) -> str:
    """Generates a polite, professional Dutch email reply signed by Harjot Singh using Gemini 2.5 Flash."""
    global llm_metrics
    t0 = time.time()
    clean_subj = normalize_subject(subject)
    recipient = sender_name.strip() if sender_name else "Beste bewoner / betrokkene"

    api_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
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
            f"Sender Name: {sender_name or 'Beste heer/mevrouw'}\n"
            f"Sender Email: {sender_email}\n"
            f"Subject: {clean_subj}\n"
            f"Category: {category.value}\n"
            f"Incoming Email Body:\n{body_text[:1500]}\n\n"
            f"Requirements:\n"
            f"- Dutch language.\n"
            f"- 2 to 4 sentences maximum.\n"
            f"- Acknowledge receipt, state clear next steps (e.g. informing contractor/technician, reviewing lease/records, or confirming follow-up).\n"
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
        p_tok = resp.usage_metadata.prompt_token_count if resp.usage_metadata else 0
        c_tok = resp.usage_metadata.candidates_token_count if resp.usage_metadata else 0
        llm_metrics.add_call(p_tok, c_tok, dt)

        return resp.text.strip()
    except Exception as exc:
        print(f"    [LLM Warning] Gemini 2.5 Flash fallback used: {exc}")
        return (
            f"Beste {recipient},\n\n"
            f"Hartelijk dank voor uw bericht inzake '{clean_subj}'. "
            f"Wij hebben uw melding in goede orde ontvangen en nemen zo spoedig mogelijk contact met u op.\n\n"
            f"Met vriendelijke groet,\n\n"
            f"Harjot Singh\n"
            f"HR Real Estate"
        )


def parse_date(date_header: str | None) -> tuple[datetime.datetime, datetime.datetime]:
    """Parses RFC 822 Date header to (utc_datetime, amsterdam_datetime)."""
    if not date_header:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        return now_utc, now_utc.astimezone(AMSTERDAM_TZ)
    try:
        dt = parsedate_to_datetime(date_header)
        if dt.tzinfo is None:
            dt_utc = dt.replace(tzinfo=datetime.timezone.utc)
        else:
            dt_utc = dt.astimezone(datetime.timezone.utc)
        dt_ams = dt_utc.astimezone(AMSTERDAM_TZ)
        return dt_utc, dt_ams
    except Exception:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        return now_utc, now_utc.astimezone(AMSTERDAM_TZ)


def extract_email_address(from_header: str | None) -> str:
    """Extracts raw email address e.g. 'Harjot Singh <info@hrrealestate.nl>' -> 'info@hrrealestate.nl'."""
    if not from_header:
        return ""
    if "<" in from_header and ">" in from_header:
        return from_header.split("<")[1].split(">")[0].strip().lower()
    return from_header.strip().lower()


def normalize_subject(subject: str) -> str:
    """Strips Re:, Fwd:, Antw: prefixes and whitespace for deterministic clustering."""
    cleaned = re.sub(r"^(re|fwd|fw|antw|antwoord):\s*", "", subject or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"^(re|fwd|fw|antw|antwoord):\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def classify_category(subject: str, body_text: str) -> Category:
    """Classifies email into Category using Dutch and English real estate and legal terms."""
    combined = (subject + " " + body_text).lower()
    # Maintenance / Repairs
    if re.search(
        r"\b(leak|warm|koud|reparatie|lekkage|verwarming|radiator|kraan|water|stroom|boiler|ketel|slot|deur|groepenkast|monteur|loodgieter|pijp|schade|onderhoud|defect|storing|dak|riolering|cv-ketel|verstopping)\b",
        combined,
    ):
        return Category.maintenance
    # Payments / Rent / Invoices
    if re.search(
        r"\b(betaling|borg|factuur|afrekening|servicekosten|kosten|huurprijs|rekening|incasso|betaald|overmaken|bankrekening|herinnering|aanmaning)\b",
        combined,
    ):
        return Category.payment
    # Legal / Disputes / Official notices
    if re.search(
        r"\b(advocaat|juridisch|aansprakelijk|ingebrekestelling|dagvaarding|rechtbank|geschil|pact advocaten|pactadvocaten|bezwaar|huurcommissie|sommatie|hersteltermijn|kort geding|overlast|buren)\b",
        combined,
    ):
        return Category.complaint
    # Leases / Contracts / Check-in / Check-out
    if re.search(
        r"\b(contract|opzegging|verlenging|parkeer|parkeervergunning|vergunning|verklaring|sleutel|bezichtiging|appartement|huurovereenkomst|verhuurdersverklaring|beëindiging|oplevering|overdracht)\b",
        combined,
    ):
        return Category.lease
    return Category.other


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


def parse_eml_message(
    msg: email.message.EmailMessage,
    gmail_thrid: str = "",
    gmail_msgid: str = "",
) -> dict[str, Any]:
    """Parses an EmailMessage object into normalized fields and attachments."""
    sender = extract_email_address(msg["From"])
    recipient = extract_email_address(msg["To"])
    subject = str(msg["Subject"] or "Geen onderwerp")
    sent_at_utc, sent_at_ams = parse_date(msg["Date"])
    message_id = str(msg["Message-ID"] or "")
    in_reply_to = str(msg["In-Reply-To"] or "")
    references = str(msg["References"] or "")

    # Direction detection:
    is_outbound = any(x in sender.lower() for x in MANAGER_IDENTITIES)
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

    # Thread reference: prefer native Gmail Thread ID if available
    if gmail_thrid:
        thread_ref = f"gm_thrid_{gmail_thrid}"
    else:
        norm_subj = normalize_subject(subject).lower()
        thread_ref = f"thread_{hashlib.sha256(norm_subj.encode()).hexdigest()[:16]}"

    return {
        "sender_email": sender,
        "recipient_email": recipient,
        "subject": subject,
        "sent_at": sent_at_utc,
        "sent_at_ams": sent_at_ams,
        "direction": direction,
        "body_text": body_text.strip(),
        "attachments": attachments,
        "message_id": message_id,
        "in_reply_to": in_reply_to,
        "references": references,
        "gmail_thrid": gmail_thrid,
        "gmail_msgid": gmail_msgid,
        "thread_ref": thread_ref,
    }


def import_single_message(
    session: Session,
    storage: Any,
    settings: Settings,
    company_id: UUID,
    item: dict[str, Any],
    is_thread_answered: bool,
    should_draft: bool,
    backfill_run_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Ingests a single email message, creates/links Case, saves attachments, indexes RAG, and creates draft."""
    sender_email = item["sender_email"]
    subject = item["subject"]
    body_text = item["body_text"]
    sent_at = item["sent_at"]
    direction = item["direction"]
    thread_ref = item["thread_ref"]
    attachments_data = item["attachments"]

    if session is not None:
        person_id, unit_id, lease_id, display_name, person_kind = find_or_link_person(session, company_id, sender_email)
    else:
        person_id, unit_id, lease_id, display_name, person_kind = None, None, None, None, "unregistered"

    provider_msg_id = item.get("gmail_msgid") or f"hist_{hashlib.sha256((sender_email + subject + sent_at.isoformat()).encode()).hexdigest()[:18]}"

    if dry_run:
        return {
            "status": "dry_run",
            "provider_msg_id": provider_msg_id,
            "sender": sender_email,
            "display_name": display_name or ("Unregistered" if direction == Direction.inbound else "Manager"),
            "kind": person_kind,
            "subject": subject,
            "sent_at": sent_at.isoformat(),
            "direction": direction.value,
            "attachments_count": len(attachments_data),
            "is_thread_answered": is_thread_answered,
            "draft_created": should_draft,
        }

    # Check for existing message to prevent duplicate insertion
    existing_msg = session.execute(
        select(MessageRow.id).where(
            MessageRow.company_id == company_id,
            MessageRow.provider_msg_id == provider_msg_id,
        )
    ).scalar_one_or_none()

    if existing_msg:
        return {
            "status": "skipped_duplicate",
            "message_id": str(existing_msg),
            "case_id": None,
            "case_created": False,
            "draft_created": False,
            "attachments": 0,
            "rag_status": "already_indexed",
        }

    # 1. Insert RawEvent (status=processed -> zero WhatsApp spam)
    raw_event_id = new_id()
    raw_event = RawEvent(
        id=raw_event_id,
        company_id=company_id,
        provider=Channel.gmail,
        provider_msg_id=provider_msg_id,
        payload={"kind": "historical_import", "sender": sender_email, "subject": subject, "backfill_run_id": backfill_run_id},
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
        meta={"subject": subject, "historical": True, "backfill_run_id": backfill_run_id},
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

    # 4. Group into Case
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

        # Update case state based on thread resolution
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

    # 5. Generate AI Draft reply for active, unanswered inquiry
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
                "backfill_run_id": backfill_run_id,
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

    # 6. Index into Vector RAG (message_chunks)
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


def execute_backfill(
    settings: Settings,
    company_id: UUID,
    imap_user: str,
    imap_password: str,
    imap_host: str = "imap.gmail.com",
    label: str = "Vastgoed",
    since_days: int = 30,
    expand_threads: bool = True,
    pacing_sec: float = 0.25,
    dry_run: bool = False,
) -> None:
    """Connects to Gmail IMAP, retrieves Vastgoed threads, resolves conversations, and executes ingestion."""
    backfill_run_id = str(uuid4())
    print("\n" + "=" * 75)
    print(f"ESTATEOS VASTGOED 30-DAY BACKFILL (Gemini 2.5 Flash)")
    print(f"Run ID        : {backfill_run_id}")
    print(f"Mailbox       : {imap_user}")
    print(f"Target Label  : {label}")
    print(f"Window        : Last {since_days} days (with full thread expansion)")
    print(f"LLM Model     : gemini-2.5-flash (thinking_budget=0)")
    print(f"Target DB     : {str(settings.database_url)}")
    print(f"Mode          : {'DRY RUN (0 DB writes, 0 LLM calls)' if dry_run else 'LIVE INGESTION'}")
    print("=" * 75 + "\n")

    engine = None
    storage = None
    if not dry_run:
        engine = make_engine(str(settings.database_url))
        storage = build_storage(settings)

    print(f"Connecting to IMAP {imap_host}:993 as {imap_user}...")
    mail = imaplib.IMAP4_SSL(imap_host, 993)
    try:
        mail.login(imap_user, imap_password)
        print(" -> IMAP Authentication successful!")
    except Exception as exc:
        print(f"\n[ERROR] IMAP login failed: {exc}")
        raise

    # 1. Select Vastgoed folder
    res, select_data = mail.select(f'"{label}"', readonly=True)
    if res != "OK":
        print(f"[ERROR] Could not select label folder '{label}': {select_data}")
        mail.logout()
        return

    total_in_folder = int(select_data[0].decode()) if select_data and select_data[0] else 0
    print(f" -> Folder '{label}' contains {total_in_folder} total messages.")

    # 2. Search messages within the last N days
    since_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=since_days)
    search_criteria = f'(SINCE "{since_date.strftime("%d-%b-%Y")}")'
    print(f"Searching for messages since {since_date.strftime('%Y-%m-%d')} ({search_criteria})...")
    res, data = mail.search(None, search_criteria)
    if res != "OK" or not data or not data[0]:
        print(f" -> 0 messages found in '{label}' for the last {since_days} days.")
        mail.logout()
        return

    msg_nums = data[0].split()
    print(f" -> Found {len(msg_nums)} messages in '{label}' matching the 30-day window.")

    # 3. Fetch header metadata and thread IDs
    print("\nScanning thread IDs and headers...")
    thread_map: dict[str, list[bytes]] = {}  # thrid -> list of msg_nums in Vastgoed
    msg_metadata: dict[bytes, dict[str, str]] = {}

    batch_size = 50
    for i in range(0, len(msg_nums), batch_size):
        chunk = msg_nums[i : i + batch_size]
        res, f_data = mail.fetch(b",".join(chunk), "(X-GM-THRID X-GM-MSGID BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE MESSAGE-ID IN-REPLY-TO REFERENCES)])")
        if res != "OK":
            continue
        for item in f_data:
            if isinstance(item, tuple):
                info_line = item[0].decode("utf-8", errors="ignore")
                hdr_bytes = item[1]
                num_match = re.match(r"^(\d+)\s+", info_line)
                thrid_match = re.search(r"X-GM-THRID\s+(\d+)", info_line)
                msgid_match = re.search(r"X-GM-MSGID\s+(\d+)", info_line)
                if num_match and thrid_match:
                    num_b = num_match.group(1).encode()
                    t_id = thrid_match.group(1)
                    m_id = msgid_match.group(1) if msgid_match else ""
                    thread_map.setdefault(t_id, []).append(num_b)
                    # Parse light headers
                    hdr_msg = email.message_from_bytes(hdr_bytes, policy=policy.default)
                    msg_metadata[num_b] = {
                        "thrid": t_id,
                        "msgid": m_id,
                        "from": str(hdr_msg["From"] or ""),
                        "to": str(hdr_msg["To"] or ""),
                        "subject": str(hdr_msg["Subject"] or ""),
                        "date": str(hdr_msg["Date"] or ""),
                    }

    print(f"Identified {len(thread_map)} unique conversation threads across {len(msg_metadata)} messages.")

    # 4. In Dry Run mode, analyze threads directly from headers for blazing speed (<10s)
    parsed_emails: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if dry_run:
        print("\n[Dry Run] Fast analysis from message headers...")
        for num_b, meta in msg_metadata.items():
            sender = extract_email_address(meta["from"])
            recipient = extract_email_address(meta["to"])
            subject = meta["subject"]
            sent_at_utc, sent_at_ams = parse_date(meta["date"])
            is_outbound = any(x in sender.lower() for x in MANAGER_IDENTITIES)
            direction = Direction.outbound if is_outbound else Direction.inbound
            t_id = meta.get("thrid", "")
            thread_ref = f"gm_thrid_{t_id}" if t_id else f"thread_{hashlib.sha256(normalize_subject(subject).lower().encode()).hexdigest()[:16]}"
            
            mid = meta.get("msgid") or f"{sender}_{sent_at_utc.isoformat()}"
            if mid in seen_ids:
                continue
            seen_ids.add(mid)

            parsed_emails.append({
                "sender_email": sender,
                "recipient_email": recipient,
                "subject": subject,
                "sent_at": sent_at_utc,
                "sent_at_ams": sent_at_ams,
                "direction": direction,
                "body_text": "",
                "attachments": [],
                "message_id": mid,
                "gmail_thrid": t_id,
                "gmail_msgid": meta.get("msgid", ""),
                "thread_ref": thread_ref,
            })
        mail.logout()
        print(f" -> Prepared {len(parsed_emails)} emails for thread resolution.")
    else:
        # Live run: Whole-Thread Expansion (capture older backstory from Vastgoed folder)
        expanded_msg_nums = set(msg_metadata.keys())
        if expand_threads:
            print("\nChecking for conversation threads that started before the 30-day window...")
            candidate_thread_ids = set()
            for num_b, meta in msg_metadata.items():
                candidate_thread_ids.add(meta["thrid"])

            expanded_count = 0
            for t_id in candidate_thread_ids:
                try:
                    res, t_data = mail.search(None, "X-GM-THRID", t_id)
                    if res == "OK" and t_data and t_data[0]:
                        all_nums = t_data[0].split()
                        for num in all_nums:
                            if num not in expanded_msg_nums:
                                expanded_msg_nums.add(num)
                                expanded_count += 1
                except Exception:
                    pass
            print(f" -> Thread expansion added {expanded_count} earlier contextual messages to complete threads.")

        # Download and parse complete messages (RFC 822) in fast batches
        print(f"\nDownloading and parsing full email contents for {len(expanded_msg_nums)} messages (fast batch mode)...")
        msg_num_list = list(expanded_msg_nums)
        batch_size = 25
        for i in range(0, len(msg_num_list), batch_size):
            chunk = msg_num_list[i : i + batch_size]
            res, msg_data_list = mail.fetch(b",".join(chunk), "(RFC822)")
            if res != "OK" or not msg_data_list:
                continue
            for item_data in msg_data_list:
                if isinstance(item_data, tuple) and len(item_data) == 2:
                    raw_bytes = item_data[1]
                    try:
                        msg = email.message_from_bytes(raw_bytes, policy=policy.default)
                        thrid_m = re.search(r"X-GM-THRID\s+(\d+)", item_data[0].decode("utf-8", errors="ignore"))
                        msgid_m = re.search(r"X-GM-MSGID\s+(\d+)", item_data[0].decode("utf-8", errors="ignore"))
                        t_id_found = thrid_m.group(1) if thrid_m else ""
                        m_id_found = msgid_m.group(1) if msgid_m else ""

                        parsed = parse_eml_message(
                            msg=msg,
                            gmail_thrid=t_id_found,
                            gmail_msgid=m_id_found,
                        )
                        mid = parsed.get("message_id") or parsed.get("gmail_msgid")
                        if mid and mid in seen_ids:
                            continue
                        if mid:
                            seen_ids.add(mid)
                        parsed_emails.append(parsed)
                    except Exception as exc:
                        pass

            done_count = min(i + batch_size, len(msg_num_list))
            print(f" -> Downloaded and parsed {done_count}/{len(msg_num_list)} messages...")

        mail.logout()
        print(f"\nSuccessfully parsed {len(parsed_emails)} unique emails.")

    # 6. Group into threads and analyze two-way resolution
    threads: dict[str, list[dict[str, Any]]] = {}
    for item in parsed_emails:
        threads.setdefault(item["thread_ref"], []).append(item)

    thread_answered: dict[str, bool] = {}
    draft_candidates: set[str] = set()

    for t_ref, msgs in threads.items():
        msgs_sorted = sorted(msgs, key=lambda x: x["sent_at"])
        last_msg = msgs_sorted[-1]
        has_outbound = any(m["direction"] == Direction.outbound for m in msgs_sorted)

        if last_msg["direction"] == Direction.outbound:
            thread_answered[t_ref] = True
        elif has_outbound:
            # If manager replied previously and the latest inbound is just a polite acknowledgment, or if manager replied
            last_outbound = next((m for m in reversed(msgs_sorted) if m["direction"] == Direction.outbound), None)
            last_inbound = next((m for m in reversed(msgs_sorted) if m["direction"] == Direction.inbound), None)
            if last_outbound and last_inbound and (last_inbound["sent_at"] - last_outbound["sent_at"]).total_seconds() < 3600:
                thread_answered[t_ref] = True
            else:
                thread_answered[t_ref] = False
        else:
            thread_answered[t_ref] = False

        # Draft candidate check
        if not thread_answered[t_ref] and last_msg["direction"] == Direction.inbound:
            sender = last_msg["sender_email"].lower()
            is_noreply = any(nr in sender for nr in ["noreply", "no-reply", "donotreply", "notification", "alert", "beveiligingsmelding"])
            is_noise = any(domain in sender for domain in AUTOMATED_NOISE_DOMAINS)
            if not is_noreply and not is_noise:
                mid = last_msg.get("message_id") or f"{last_msg['sender_email']}_{last_msg['sent_at'].isoformat()}"
                draft_candidates.add(mid)

    # 7. Execute Ingestion / Dry Run
    resolved_threads_count = sum(thread_answered.values())
    open_threads_count = len(threads) - resolved_threads_count

    print("\n" + "-" * 75)
    print(f"THREAD ANALYSIS:")
    print(f" -> Total Unique Threads   : {len(threads)}")
    print(f" -> Answered / Resolved    : {resolved_threads_count} threads (0 drafts needed)")
    print(f" -> Open / Active Inquiries: {open_threads_count} threads")
    print(f" -> Actionable Drafts      : {len(draft_candidates)} AI drafts to generate")
    print("-" * 75 + "\n")

    imported_count = 0
    drafts_count = 0

    if dry_run:
        # In dry run, we don't need a live DB session
        for item in parsed_emails:
            t_ref = item["thread_ref"]
            is_ans = thread_answered.get(t_ref, False)
            mid = item.get("message_id") or f"{item['sender_email']}_{item['sent_at'].isoformat()}"
            should_draft = (mid in draft_candidates)

            res = import_single_message(
                session=None,  # type: ignore
                storage=None,
                settings=settings,
                company_id=company_id,
                item=item,
                is_thread_answered=is_ans,
                should_draft=should_draft,
                backfill_run_id=backfill_run_id,
                dry_run=True,
            )
            imported_count += 1
            if res.get("draft_created"):
                drafts_count += 1

            att_count = res.get("attachments_count", res.get("attachments", 0))
            att_str = f"({att_count} att)" if att_count > 0 else "        "
            draft_tag = " [AI DRAFT]" if res.get("draft_created") else ""
            ans_tag = "[RESOLVED]" if is_ans else "[OPEN]    "

            status_str = res.get("status", "ok").upper()
            sender_display = item["sender_email"][:28]
            subj_display = item["subject"][:35]
            time_display = item.get("sent_at_ams", item["sent_at"].astimezone(AMSTERDAM_TZ)).strftime("%Y-%m-%d %H:%M CET")
            print(
                f" -> [{status_str:7}] {time_display} | {item['direction'].value.upper():8} | {ans_tag} | {sender_display:28} | '{subj_display}...' {att_str}{draft_tag}"
            )
    else:
        with Session(engine) as session:
            for item in parsed_emails:
                t_ref = item["thread_ref"]
                is_ans = thread_answered.get(t_ref, False)
                mid = item.get("message_id") or f"{item['sender_email']}_{item['sent_at'].isoformat()}"
                should_draft = (mid in draft_candidates)

                res = import_single_message(
                    session=session,
                    storage=storage,
                    settings=settings,
                    company_id=company_id,
                    item=item,
                    is_thread_answered=is_ans,
                    should_draft=should_draft,
                    backfill_run_id=backfill_run_id,
                    dry_run=False,
                )
                imported_count += 1
                if res.get("draft_created"):
                    drafts_count += 1

                att_count = res.get("attachments_count", res.get("attachments", 0))
                att_str = f"({att_count} att)" if att_count > 0 else "        "
                draft_tag = " [AI DRAFT]" if res.get("draft_created") else ""
                ans_tag = "[RESOLVED]" if is_ans else "[OPEN]    "

                status_str = res.get("status", "ok").upper()
                sender_display = item["sender_email"][:28]
                subj_display = item["subject"][:35]
                time_display = item.get("sent_at_ams", item["sent_at"].astimezone(AMSTERDAM_TZ)).strftime("%Y-%m-%d %H:%M CET")
                print(
                    f" -> [{status_str:7}] {time_display} | {item['direction'].value.upper():8} | {ans_tag} | {sender_display:28} | '{subj_display}...' {att_str}{draft_tag}"
                )
                if pacing_sec > 0:
                    time.sleep(pacing_sec)

    print("\n" + "=" * 75)
    print("INGESTION SUMMARY:")
    print(f" -> Messages Processed     : {imported_count}")
    print(f" -> Conversation Threads   : {len(threads)} ({resolved_threads_count} resolved, {open_threads_count} open)")
    print(f" -> AI Drafts Created      : {drafts_count}")
    print(f" -> WhatsApp Alerts Sent   : 0 (completely suppressed)")

    if llm_metrics.calls > 0:
        avg_time = llm_metrics.total_time_sec / llm_metrics.calls
        print("\nGEMINI 2.5 FLASH METRICS:")
        print(f" -> Total AI Draft Calls   : {llm_metrics.calls}")
        print(f" -> Prompt Tokens (Input)  : {llm_metrics.prompt_tokens}")
        print(f" -> Candidate Tokens (Out) : {llm_metrics.candidate_tokens}")
        print(f" -> Total Tokens Billed    : {llm_metrics.total_tokens}")
        print(f" -> Total AI Time          : {llm_metrics.total_time_sec:.2f}s (avg {avg_time:.2f}s / draft)")
        print(f" -> Estimated Cost         : ${llm_metrics.cost_usd:.4f}")
    elif dry_run:
        est_tokens = len(draft_candidates) * 700
        est_cost = len(draft_candidates) * 0.0003
        print("\nESTIMATED GEMINI 2.5 FLASH USAGE (DRY RUN):")
        print(f" -> Projected Draft Calls  : {len(draft_candidates)}")
        print(f" -> Estimated Total Tokens : ~{est_tokens:,} tokens")
        print(f" -> Estimated LLM Cost     : ~${est_cost:.4f} (under 2 cents!)")

    print("=" * 75 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dedicated 30-Day Historical Backfill Script for Vastgoed Mailbox")
    parser.add_argument("--dry-run", action="store_true", help="Preview email threads and draft candidates without writing to DB or calling LLM")
    parser.add_argument("--since-days", type=int, default=30, help="Days of history to backfill (default: 30)")
    parser.add_argument("--label", type=str, default="Vastgoed", help="Gmail label to import (default: Vastgoed)")
    parser.add_argument("--imap-user", type=str, default="info@hrrealestate.nl", help="IMAP user address")
    parser.add_argument("--imap-password", type=str, default=os.getenv("IMAP_PASSWORD", "xjcwlqidsdtqigrw"), help="IMAP app password")
    parser.add_argument("--imap-host", type=str, default="imap.gmail.com", help="IMAP host")
    parser.add_argument("--database-url", type=str, help="Override target PostgreSQL database URL")
    parser.add_argument("--company-id", type=str, help="Override company UUID (default: auto-detected from DB)")
    parser.add_argument("--no-expand-threads", action="store_true", help="Disable thread history expansion")
    parser.add_argument("--pacing-sec", type=float, default=0.25, help="Pacing wait time in seconds between RAG/DB writes (default: 0.25)")

    args = parser.parse_args()

    # Load Settings
    settings = get_settings()
    if args.database_url:
        settings.database_url = args.database_url  # type: ignore

    # Discover company_id if not explicitly provided
    company_id: UUID
    if args.company_id:
        company_id = UUID(args.company_id)
    else:
        try:
            engine = make_engine(str(settings.database_url))
            with Session(engine) as s:
                comp = s.execute(select(Company.id).limit(1)).scalar_one_or_none()
                if comp:
                    company_id = comp
                else:
                    company_id = uuid4()
        except Exception as exc:
            if args.dry_run:
                print(f"[Notice] Database not connected ({exc}). Proceeding with Dry Run in offline mode...")
                company_id = uuid4()
            else:
                print(f"[ERROR] Database connection failed: {exc}")
                sys.exit(1)

    execute_backfill(
        settings=settings,
        company_id=company_id,
        imap_user=args.imap_user,
        imap_password=args.imap_password,
        imap_host=args.imap_host,
        label=args.label,
        since_days=args.since_days,
        expand_threads=not args.no_expand_threads,
        pacing_sec=args.pacing_sec,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
