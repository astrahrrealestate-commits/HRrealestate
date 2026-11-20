#!/usr/bin/env python3
# ruff: noqa: E501, I001, F401, T201, UP017
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
]


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
    """Classifies email into Category using Dutch and English real estate terms."""
    combined = (subject + " " + body_text).lower()
    if re.search(
        r"\b(leak|warm|koud|reparatie|lekkage|verwarming|radiator|kraan|water|stroom|boiler|ketel|slot|deur|groepenkast|monteur|loodgieter|pijp|schade)\b",
        combined,
    ):
        return Category.maintenance
    if re.search(
        r"\b(betaling|borg|factuur|afrekening|servicekosten|kosten|huurprijs|rekening|incasso|betaald)\b", combined
    ):
        return Category.payment
    if re.search(
        r"\b(contract|opzegging|verlenging|parkeer|parkeervergunning|vergunning|verklaring|sleutel|bezichtiging|appartement|huurovereenkomst|verhuurdersverklaring)\b",
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
    dry_run: bool = False,
) -> dict[str, Any]:
    """Ingests a single email message, creates/links Case, stores attachments, and creates draft if needed."""
    person_id, unit_id, lease_id, display_name, person_kind = find_or_link_person(session, company_id, sender_email)

    now = datetime.datetime.now(datetime.timezone.utc)
    is_recent = (now - sent_at).days <= 7
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
            "is_recent": is_recent,
            "draft_created": is_recent and direction == Direction.inbound,
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
        if direction == Direction.outbound:
            existing_case.state = CaseState.resolved
            existing_case.resolved_at = sent_at
        elif is_recent and direction == Direction.inbound:
            existing_case.state = CaseState.open
            existing_case.resolved_at = None
        elif not is_recent:
            existing_case.state = CaseState.resolved
            if not existing_case.resolved_at:
                existing_case.resolved_at = sent_at
    else:
        case_created = True
        case_id = new_id()
        case_state = CaseState.open if (is_recent and direction == Direction.inbound) else CaseState.resolved
        category = classify_category(subject, body_text)
        urgency = Urgency.high if (is_recent and category == Category.maintenance) else Urgency.normal

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
            resolved_at=None if case_state == CaseState.open else sent_at,
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

    # 5. For active, unanswered recent message (< 7 days) -> generate an AI draft reply for Inbox
    if is_recent and direction == Direction.inbound:
        draft_created = True
        recipient_name = display_name or "Beste bewoner"
        draft_text = (
            f"Beste {recipient_name},\n\n"
            f"Hartelijk dank voor uw bericht inzake '{normalize_subject(subject)}'. "
            f"Wij hebben uw melding in goede orde ontvangen en onze technische dienst geïnformeerd om dit zo snel mogelijk voor u op te lossen.\n\n"
            f"Wij nemen spoedig contact met u op voor een afspraak.\n\n"
            f"Met vriendelijke groet,\n"
            f"Harjot Singh\n"
            f"HR Real Estate"
        )
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
            rationale="Automated response draft created during historical email migration for active unresolved inquiry.",
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

    session.commit()

    # 6. Index into Vector RAG
    rag_status = "skipped"
    try:
        rag_status = index_message(session.get_bind(), settings, message_id)
    except Exception as exc:
        rag_status = f"error: {exc}"

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
    mgr_patterns = ["hausverwaltung", "hrrealestate", "beheer", "owner@"]
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
    allowed_emails: set[str],
    include_unregistered: bool = True,
) -> tuple[bool, str]:
    """Determines whether an email should be imported based on tenant/contractor matching or property topic."""
    sender = item["sender_email"].lower().strip()
    recipient = item.get("recipient_email", "").lower().strip()

    # 1. Direct match with tenant or contractor
    if sender in allowed_emails:
        return True, "Sender matches registered directory contact"
    if recipient in allowed_emails:
        return True, "Recipient matches registered directory contact (outbound/reply)"

    # 2. Skip obvious automated marketing/recruiting spam
    if any(domain in sender for domain in MARKETING_SPAM_DOMAINS):
        return False, f"Skipped spam/marketing sender ({sender})"

    # 3. Unregistered senders: check for property-related topic
    if include_unregistered:
        subject = item["subject"]
        body = item["body_text"]
        cat = classify_category(subject, body)
        if cat in (Category.maintenance, Category.payment, Category.lease):
            return True, f"Unregistered inquiry matched property topic ({cat.value})"

    return False, "Sender does not match active tenants/contractors"


def process_parsed_emails(
    session: Session,
    storage: Any,
    settings: Settings,
    company_id: UUID,
    parsed_emails: list[dict[str, Any]],
    allowed_emails: set[str] | None = None,
    include_unregistered: bool = True,
    dry_run: bool = False,
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

    print(f"\nProcessing {len(parsed_emails)} emails in chronological order:")
    imported_count = 0
    skipped_count = 0
    drafts_count = 0

    for item in parsed_emails:
        sender = item["sender_email"]
        if allowed_emails is not None:
            relevant, reason = is_relevant_email(item, allowed_emails, include_unregistered=include_unregistered)
            if not relevant:
                print(f" -> [SKIPPED] {item['sent_at'].strftime('%Y-%m-%d')} | {sender:28} | {reason}")
                skipped_count += 1
                continue

        res = import_message(
            session=session,
            storage=storage,
            settings=settings,
            company_id=company_id,
            sender_email=sender,
            subject=item["subject"],
            body_text=item["body_text"],
            sent_at=item["sent_at"],
            direction=item["direction"],
            thread_ref=item["thread_ref"],
            attachments_data=item["attachments"],
            dry_run=dry_run,
        )
        imported_count += 1
        if res.get("draft_created"):
            drafts_count += 1

        att_str = f"({res.get('attachments_count', res.get('attachments', 0))} att)"
        draft_tag = " [AI DRAFT]" if res.get("draft_created") else ""
        print(
            f" -> [{res['status'].upper()}] {item['sent_at'].strftime('%Y-%m-%d %H:%M')} | {item['direction'].value.upper():8} | {sender:28} | '{item['subject'][:38]}...' {att_str}{draft_tag}"
        )

    print("\n-------------------------------------------------------------------")
    print(
        f"SUMMARY: {imported_count} imported | {skipped_count} skipped | {drafts_count} active AI reply drafts generated"
    )
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


def fetch_and_import_imap(
    session: Session,
    storage: Any,
    settings: Settings,
    company_id: UUID,
    imap_host: str,
    imap_user: str,
    imap_password: str,
    since_days: int = 60,
    folders: list[str] | None = None,
    allowed_emails: set[str] | None = None,
    include_unregistered: bool = True,
    dry_run: bool = False,
) -> None:
    """Connects to IMAP (Gmail), retrieves emails, and processes them chronologically."""
    if not folders:
        folders = ["INBOX", "[Gmail]/Sent Mail"]

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

    # Get available server folders
    status, f_list = mail.list()
    available_folders = []
    if status == "OK":
        for fe in f_list:
            decoded = fe.decode("utf-8", errors="ignore")
            if ' "/" ' in decoded:
                available_folders.append(decoded.split(' "/" ')[1].strip('"'))

    search_criteria = ["ALL"]
    if since_days > 0:
        since_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=since_days)
        search_criteria = [f'(SINCE "{since_date.strftime("%d-%b-%Y")}")']

    parsed_emails: list[dict[str, Any]] = []
    seen_msg_ids: set[str] = set()

    for folder in folders:
        folder_target = folder
        if folder not in available_folders:
            # Fallback for sent mail names
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
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="EstateOS Historical Email Ingestion Pipeline (Staging/Production)")
    parser.add_argument("--dry-run", action="store_true", help="Preview email matches without modifying database")
    parser.add_argument("--eml-dir", type=str, help="Path to local directory of .eml files")
    parser.add_argument("--imap-user", type=str, help="Gmail / IMAP email address to connect to")
    parser.add_argument("--imap-password", type=str, help="16-character Google App Password (prompted if omitted)")
    parser.add_argument(
        "--imap-host", type=str, default="imap.gmail.com", help="IMAP server hostname (default: imap.gmail.com)"
    )
    parser.add_argument(
        "--since-days", type=int, default=60, help="Import emails received in the last N days (default: 60, 0 = all)"
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

    print("===================================================================")
    print("      ESTATEOS HISTORICAL EMAIL INGESTION PIPELINE (STAGE)         ")
    print("===================================================================")
    print(f"Database URL : {settings.database_url}")
    print(f"Company ID   : {company_id}")
    print(f"Mode         : {'DRY RUN (Preview Only)' if args.dry_run else 'LIVE INGESTION'}")

    with Session(engine) as session:
        # Step 1: Auto-discover active tenants and contractors from database
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

        active_filter = None if args.all_senders else allowed_emails
        if active_filter:
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
        print("1. Direct IMAP (Gmail with App Password):")
        print(
            "   python backend/scripts/import_historical_emails.py --imap-user client@gmail.com --imap-password 'abcd efgh ijkl mnop'"
        )
        print("\n2. Dry-Run Preview (Test IMAP without modifying DB):")
        print("   python backend/scripts/import_historical_emails.py --imap-user client@gmail.com --dry-run")
        print("\n3. Local .eml Directory:")
        print("   python backend/scripts/import_historical_emails.py --eml-dir backend/scripts/edgecase_emails")
        sys.exit(0)


if __name__ == "__main__":
    main()
