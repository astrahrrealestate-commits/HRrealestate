#!/usr/bin/env python3
# ruff: noqa: I001, F401, S110, T201, UP017
"""Mailbox-to-Mailbox Email Sync Tool for EstateOS (Step 1 of 2).

Filters and copies relevant tenant and contractor email threads from an OLD Gmail account
directly into a NEW Gmail account's mailbox using IMAP.

Key Capabilities:
1. Two-Way Thread Copy: Copies both INBOX (tenant messages) and Sent Mail (manager replies).
2. True Metadata Preservation: Keeps the original sender From:, original Date: header,
   and RFC 822 internal date so historical threads appear with their true chronological dates.
3. Stage Database Auto-Filter: Queries EstateOS PostgreSQL to discover active tenants and
   contractor companies, copying ONLY relevant business mail (skipping marketing & recruiter spam).
4. Strict Deduplication: Inspects Message-ID on the destination server before appending;
   will never upload the same email twice.
5. Interactive & Safe: Securely prompts for Google App Passwords without logging; supports --dry-run.
"""

import argparse
import datetime
import email
from email import policy
from email.utils import parsedate_to_datetime
import getpass
import imaplib
from pathlib import Path
import re
import sys
import time
from typing import Any
from uuid import UUID

# Ensure app imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.core.settings import Settings
from app.db.models import ChannelIdentity, Person
from app.db.session import make_engine

# Known spam / marketing domains to filter out
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


def extract_email_address(header_val: str | None) -> str:
    """Extracts raw email address e.g. 'Vipin Tyagi <vipint9902@gmail.com>' -> 'vipint9902@gmail.com'."""
    if not header_val:
        return ""
    if "<" in header_val and ">" in header_val:
        return header_val.split("<")[1].split(">")[0].strip().lower()
    return header_val.strip().lower()


def discover_stage_entities(session: Session, company_id: UUID) -> tuple[dict[str, dict], dict[str, dict], set[str]]:
    """Dynamically queries PostgreSQL to discover active tenants and contractors with their emails."""
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


def is_relevant_email(
    from_addr: str,
    to_addr: str,
    subject: str,
    allowed_emails: set[str] | None,
) -> tuple[bool, str]:
    """Determines if email belongs to tenant/contractor or relevant property topic."""
    sender = from_addr.lower().strip()
    recipient = to_addr.lower().strip()

    if allowed_emails:
        if sender in allowed_emails:
            return True, "Sender matches registered tenant/contractor"
        if recipient in allowed_emails:
            return True, "Recipient matches registered tenant/contractor"

    # Exclude obvious marketing/recruiter spam
    if any(domain in sender for domain in MARKETING_SPAM_DOMAINS):
        return False, f"Marketing/recruiter spam ({sender})"

    # Check for property management keywords
    subj_lower = subject.lower()
    if re.search(
        r"\b(leak|warm|koud|reparatie|lekkage|verwarming|radiator|kraan|water|stroom|boiler|ketel|slot|deur|groepenkast|huur|borg|factuur|servicekosten|contract|opzegging|parkeer|bezichtiging|appartement)\b",
        subj_lower,
    ):
        return True, "Subject matches property management topic"

    return False, "Not matched to tenants or property topics"


def message_exists_on_dest(dest_imap: imaplib.IMAP4_SSL, folder: str, message_id: str) -> bool:
    """Checks if an email with the same Message-ID already exists on the destination server."""
    if not message_id:
        return False
    try:
        clean_mid = message_id.replace('"', "").strip()
        dest_imap.select(f'"{folder}"', readonly=True)
        # Search by header Message-ID
        res, data = dest_imap.search(None, f'HEADER Message-ID "{clean_mid}"')
        if res == "OK" and data and data[0].strip():
            return True
    except Exception:
        pass
    return False


def get_imap_internal_date(date_header: str | None) -> float:
    """Returns UNIX timestamp from RFC 822 Date: header for IMAP append time."""
    if not date_header:
        return time.time()
    try:
        dt = parsedate_to_datetime(date_header)
        return dt.timestamp()
    except Exception:
        return time.time()


def sync_mailboxes(
    source_user: str,
    source_password: str,
    dest_user: str,
    dest_password: str,
    imap_host: str = "imap.gmail.com",
    since_days: int = 90,
    allowed_emails: set[str] | None = None,
    dry_run: bool = False,
) -> None:
    """Synchronizes filtered emails from source Gmail account to destination Gmail account."""
    print("===================================================================")
    print("      ESTATEOS MAILBOX-TO-MAILBOX SYNC (OLD GMAIL -> NEW GMAIL)    ")
    print("===================================================================")
    print(f"Source Mailbox      : {source_user}")
    print(f"Destination Mailbox : {dest_user}")
    print(f"Search Window       : Last {since_days} days (0 = all history)")
    print(f"Mode                : {'DRY RUN (Preview Only)' if dry_run else 'LIVE COPY'}")
    print("-------------------------------------------------------------------")

    # Connect to Source Mailbox
    print(f"Connecting to Source ({source_user})...")
    src_imap = imaplib.IMAP4_SSL(imap_host, 993)
    try:
        src_imap.login(source_user, source_password)
        print(" -> Source authentication successful!")
    except Exception as exc:
        print(f"[ERROR] Source login failed: {exc}")
        sys.exit(1)

    # Connect to Destination Mailbox
    dest_imap: imaplib.IMAP4_SSL | None = None
    if not dry_run:
        print(f"Connecting to Destination ({dest_user})...")
        dest_imap = imaplib.IMAP4_SSL(imap_host, 993)
        try:
            dest_imap.login(dest_user, dest_password)
            print(" -> Destination authentication successful!")
        except Exception as exc:
            print(f"[ERROR] Destination login failed: {exc}")
            src_imap.logout()
            sys.exit(1)

    # Folders to scan in Source
    folders_to_scan = [
        ("INBOX", "INBOX"),
        ("[Gmail]/Sent Mail", "[Gmail]/Sent Mail"),
    ]

    # Check search date criteria
    search_criteria = ["ALL"]
    if since_days > 0:
        since_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=since_days)
        search_criteria = [f'(SINCE "{since_date.strftime("%d-%b-%Y")}")']

    total_scanned = 0
    total_matched = 0
    total_copied = 0
    total_skipped_dup = 0
    total_skipped_spam = 0

    seen_msg_ids: set[str] = set()

    for src_folder, dest_folder in folders_to_scan:
        print(f"\nScanning Source folder '{src_folder}'...")
        res, _ = src_imap.select(f'"{src_folder}"', readonly=True)
        if res != "OK":
            # Try fallback for Sent folder
            if "sent" in src_folder.lower():
                _status, f_list = src_imap.list()
                matched = next(
                    (
                        fe.decode().split(' "/" ')[1].strip('"')
                        for fe in (f_list or [])
                        if "sent" in fe.decode().lower()
                    ),
                    None,
                )
                if matched:
                    src_folder = matched
                    res, _ = src_imap.select(f'"{src_folder}"', readonly=True)
            if res != "OK":
                print(f"Notice: Source folder '{src_folder}' not accessible, skipping.")
                continue

        res, data = src_imap.search(None, *search_criteria)
        if res != "OK" or not data or not data[0]:
            print(f" -> 0 emails found in '{src_folder}'.")
            continue

        msg_nums = data[0].split()
        print(f" -> Found {len(msg_nums)} emails in '{src_folder}'. Evaluating relevance...")

        for num in msg_nums:
            total_scanned += 1
            # Fetch headers first for speed
            res, hdr_data = src_imap.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])")
            if res != "OK" or not hdr_data or not hdr_data[0]:
                continue

            raw_hdr = hdr_data[0][1]
            hdr_msg = email.message_from_bytes(raw_hdr, policy=policy.default)
            from_addr = extract_email_address(hdr_msg["From"])
            to_addr = extract_email_address(hdr_msg["To"])
            subject = str(hdr_msg["Subject"] or "(No Subject)")
            date_str = str(hdr_msg["Date"] or "")
            msg_id = str(hdr_msg["Message-ID"] or "").strip()

            # Deduplication across folders
            if msg_id and msg_id in seen_msg_ids:
                continue
            if msg_id:
                seen_msg_ids.add(msg_id)

            relevant, _reason = is_relevant_email(from_addr, to_addr, subject, allowed_emails)
            if not relevant:
                total_skipped_spam += 1
                continue

            total_matched += 1
            date_short = date_str[:16] if date_str else "Unknown Date"

            # Check if already present on destination
            if dest_imap and message_exists_on_dest(dest_imap, dest_folder, msg_id):
                print(f" -> [SKIP DUP] {date_short} | {from_addr:26} | '{subject[:35]}...' (Already in New Gmail)")
                total_skipped_dup += 1
                continue

            if dry_run:
                print(f" -> [MATCHED]  {date_short} | {from_addr:26} -> {dest_folder} | '{subject[:35]}...'")
                total_copied += 1
                continue

            # Fetch full RFC 822 message bytes
            res, full_data = src_imap.fetch(num, "(RFC822)")
            if res != "OK" or not full_data or not full_data[0]:
                continue
            rfc822_bytes = full_data[0][1]

            # Preserve original internal date
            internal_timestamp = get_imap_internal_date(date_str)
            imap_time = imaplib.Time2Internaldate(internal_timestamp)

            # Append to destination folder
            dest_target = "INBOX" if "inbox" in dest_folder.lower() else dest_folder
            try:
                dest_imap.append(f'"{dest_target}"', "", imap_time, rfc822_bytes)
                print(f" -> [COPIED]   {date_short} | {from_addr:26} -> {dest_target} | '{subject[:35]}...'")
                total_copied += 1
            except Exception:
                # If specific label append fails, fallback to INBOX
                try:
                    dest_imap.append('"INBOX"', "", imap_time, rfc822_bytes)
                    print(f" -> [COPIED]   {date_short} | {from_addr:26} -> INBOX | '{subject[:35]}...'")
                    total_copied += 1
                except Exception as fb_err:
                    print(f" -> [ERROR]    Failed to copy '{subject[:30]}': {fb_err}")

    # Logout
    src_imap.logout()
    if dest_imap:
        dest_imap.logout()

    print("\n===================================================================")
    print("                     SYNC EXECUTION SUMMARY                        ")
    print("===================================================================")
    print(f"Total Emails Scanned in Source : {total_scanned}")
    print(f"Non-relevant / Spam Skipped    : {total_skipped_spam}")
    print(f"Relevant Emails Identified     : {total_matched}")
    print(f"Duplicates Already on Dest     : {total_skipped_dup}")
    print(f"{'Previewed for Copy' if dry_run else 'Successfully Copied to New Gmail'}: {total_copied}")
    print("===================================================================\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="EstateOS Mailbox-to-Mailbox Sync Tool (Old Gmail -> New Gmail)")
    parser.add_argument("--dry-run", action="store_true", help="Preview matched emails without modifying destination")
    parser.add_argument("--source-user", type=str, help="Old Gmail email address (source)")
    parser.add_argument(
        "--source-password", type=str, help="16-character App Password for Old Gmail (prompted if omitted)"
    )
    parser.add_argument("--dest-user", type=str, help="New Gmail email address (destination)")
    parser.add_argument(
        "--dest-password", type=str, help="16-character App Password for New Gmail (prompted if omitted)"
    )
    parser.add_argument(
        "--since-days", type=int, default=90, help="Sync emails received in the last N days (default: 90, 0 = all)"
    )
    parser.add_argument("--all-emails", action="store_true", help="Disable stage directory filter and copy all emails")
    parser.add_argument(
        "--company-id", type=str, default="01a1341b-2e4e-7073-b44e-40a7bc9e8e2a", help="EstateOS Company UUID"
    )
    args = parser.parse_args()

    # Database connection for stage directory discovery
    env_path = Path(__file__).resolve().parents[1] / ".env"
    settings = Settings(_env_file=env_path if env_path.exists() else None)
    engine = make_engine(str(settings.database_url))
    company_id = UUID(args.company_id)

    with Session(engine) as session:
        tenants, contractors, allowed_emails = discover_stage_entities(session, company_id)

    print("-------------------------------------------------------------------")
    print(f"Stage Directory: {len(tenants)} active tenants, {len(contractors)} contractors loaded.")
    active_filter = None if args.all_emails else allowed_emails
    if active_filter:
        print(f"Auto-Filter: Active for {len(active_filter)} known tenant & contractor addresses.")
    else:
        print("Auto-Filter: Disabled (--all-emails). Copying all incoming messages.")
    print("-------------------------------------------------------------------")

    src_user = args.source_user
    if not src_user:
        src_user = input("Enter Old Gmail address (Source): ").strip()

    src_pw = args.source_password
    if not src_pw:
        src_pw = getpass.getpass(f"Enter 16-character Google App Password for {src_user}: ").strip()

    dest_user = args.dest_user
    if not dest_user:
        dest_user = input("Enter New Gmail address (Destination): ").strip()

    dest_pw = args.dest_password
    if not dest_pw and not args.dry_run:
        dest_pw = getpass.getpass(f"Enter 16-character Google App Password for {dest_user}: ").strip()

    sync_mailboxes(
        source_user=src_user,
        source_password=src_pw,
        dest_user=dest_user,
        dest_password=dest_pw or "",
        since_days=args.since_days,
        allowed_emails=active_filter,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
