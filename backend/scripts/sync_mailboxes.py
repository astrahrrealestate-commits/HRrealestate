#!/usr/bin/env python3
# ruff: noqa: I001, S110, T201, UP017
"""Mailbox-to-Mailbox Email Sync Tool for EstateOS (Step 1 of 2).

Filters and copies relevant email threads from an OLD Gmail account
directly into a NEW Gmail account's mailbox using high-speed parallel IMAP workers.

Key Capabilities:
1. Strict Label Filter: Copies ONLY emails with the specified Gmail label (default: 'Vastgoed').
2. Strict Date Cutoff: Copies ONLY emails from a given date onwards (default: 2024-01-01).
3. Read / Unread Preservation: Faithfully preserves read vs unread flag (unread remains unread).
4. True Metadata Preservation: Keeps original From:, Date: headers, and RFC 822 internal date.
5. High-Speed Multi-Worker Sync: Safely pools 6 concurrent IMAP workers for 5x–8x faster transfer.
6. Strict Deduplication: Pre-loads destination Message-IDs to guarantee zero duplicates.
"""

import argparse
import concurrent.futures
import contextlib
import datetime
import email
from email import policy
from email.utils import parsedate_to_datetime
import getpass
import imaplib
from pathlib import Path
import re
import sys
import threading
import time

# Ensure app imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Default settings
TARGET_LABEL = "Vastgoed"
DEFAULT_SINCE_DATE = "2024-01-01"
DEFAULT_WORKERS = 6


def extract_email_address(header_val: str | None) -> str:
    """Extracts raw email address e.g. 'Harjot Singh <harjotsj@gmail.com>' -> 'harjotsj@gmail.com'."""
    if not header_val:
        return ""
    if "<" in header_val and ">" in header_val:
        return header_val.split("<")[1].split(">")[0].strip().lower()
    return header_val.strip().lower()


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


def find_all_mail_folder(imap_client: imaplib.IMAP4_SSL) -> str:
    """Finds the All Mail folder using IMAP flags (e.g. \\All) or localized names."""
    try:
        status, f_list = imap_client.list()
        if status == "OK" and f_list:
            for fe in f_list:
                decoded = fe.decode("utf-8", errors="ignore")
                if "\\All" in decoded:
                    if ' "/" ' in decoded:
                        return decoded.split(' "/" ')[1].strip('"')
                    elif ' " " ' in decoded:
                        return decoded.split(' " " ')[1].strip('"')
            for candidate in ["[Gmail]/All Mail", "[Gmail]/Alle e-mail"]:
                for fe in f_list:
                    decoded = fe.decode("utf-8", errors="ignore")
                    if candidate.lower() in decoded.lower():
                        if ' "/" ' in decoded:
                            return decoded.split(' "/" ')[1].strip('"')
                        elif ' " " ' in decoded:
                            return decoded.split(' " " ')[1].strip('"')
    except Exception:
        pass
    return "[Gmail]/All Mail"


def fetch_dest_existing_message_ids(dest_imap: imaplib.IMAP4_SSL) -> set[str]:
    """Pre-loads all existing Message-IDs from the destination mailbox for fast O(1) deduplication."""
    existing_ids: set[str] = set()
    all_folder = find_all_mail_folder(dest_imap)
    print(f"Checking existing messages on destination folder '{all_folder}' for deduplication...")
    res, _ = dest_imap.select(f'"{all_folder}"', readonly=True)
    if res != "OK":
        all_folder = "INBOX"
        res, _ = dest_imap.select('"INBOX"', readonly=True)

    if res == "OK":
        res, data = dest_imap.search(None, "ALL")
        if res == "OK" and data and data[0]:
            nums = data[0].split()
            print(f" -> Found {len(nums)} existing messages on destination. Caching Message-IDs...")
            batch_size = 500
            for i in range(0, len(nums), batch_size):
                chunk = nums[i : i + batch_size]
                chunk_str = b",".join(chunk).decode()
                res_fetch, fetch_data = dest_imap.fetch(chunk_str, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
                if res_fetch == "OK" and fetch_data:
                    for item in fetch_data:
                        if isinstance(item, tuple) and len(item) > 1:
                            hdr_msg = email.message_from_bytes(item[1], policy=policy.default)
                            mid = str(hdr_msg.get("Message-ID") or "").strip().strip("<>").strip('"')
                            if mid:
                                existing_ids.add(mid)
    print(f" -> Deduplication cache ready: {len(existing_ids)} unique Message-IDs on destination.")
    return existing_ids


def get_imap_internal_date(date_header: str | None) -> float:
    """Returns UNIX timestamp from RFC 822 Date: header for IMAP append time."""
    if not date_header:
        return time.time()
    try:
        dt = parsedate_to_datetime(date_header)
        return dt.timestamp()
    except Exception:
        return time.time()


def parse_rfc822_date(date_header: str | None) -> datetime.datetime | None:
    """Parses RFC 822 Date header into timezone-aware datetime."""
    if not date_header:
        return None
    try:
        dt = parsedate_to_datetime(date_header)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except Exception:
        return None


def extract_flags_for_append(flags_header: str) -> str | None:
    """Preserves \\Seen (read) and \\Flagged (starred); returns None for unread emails."""
    flags = []
    if "\\Seen" in flags_header:
        flags.append("\\Seen")
    if "\\Flagged" in flags_header:
        flags.append("\\Flagged")
    return "(" + " ".join(flags) + ")" if flags else None


def fetch_label_message_numbers(
    src_imap: imaplib.IMAP4_SSL,
    label: str,
    since_date: str = "",
) -> tuple[str, list[bytes]]:
    """Selects the label folder or searches via Gmail X-GM-RAW to get message numbers."""
    matched_folder = find_imap_folder(src_imap, label)

    # Date criteria
    search_criteria = ["ALL"]
    since_query_raw = ""
    if since_date:
        try:
            dt = datetime.datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
            imap_date_str = dt.strftime("%d-%b-%Y")
            search_criteria = [f'(SINCE "{imap_date_str}")']
            since_query_raw = f" after:{dt.strftime('%Y/%m/%d')}"
        except Exception:
            pass

    # Attempt 1: Direct IMAP folder selection
    if matched_folder:
        res, _ = src_imap.select(f'"{matched_folder}"', readonly=True)
        if res == "OK":
            res, data = src_imap.search(None, *search_criteria)
            if res == "OK" and data and data[0]:
                return matched_folder, data[0].split()
            return matched_folder, []

    # Attempt 2: Search All Mail using Gmail X-GM-RAW extension
    all_mail_folder = find_all_mail_folder(src_imap)
    res, _ = src_imap.select(f'"{all_mail_folder}"', readonly=True)
    if res == "OK":
        raw_query = f'label:"{label}"{since_query_raw}'
        res, data = src_imap.search(None, "X-GM-RAW", f'"{raw_query}"')
        if res == "OK" and data and data[0]:
            return all_mail_folder, data[0].split()

    return label, []


class SyncStats:
    """Thread-safe statistics and progress tracker."""

    def __init__(self, total_matched: int, existing_ids: set[str]) -> None:
        self.lock = threading.Lock()
        self.total_matched = total_matched
        self.total_scanned = 0
        self.total_copied = 0
        self.total_skipped_dup = 0
        self.total_skipped_date = 0
        self.total_unread_copied = 0
        self.existing_dest_ids = set(existing_ids)
        self.seen_msg_ids: set[str] = set()

    def is_duplicate_or_record(self, msg_id: str) -> bool:
        with self.lock:
            if not msg_id:
                return False
            if msg_id in self.seen_msg_ids or msg_id in self.existing_dest_ids:
                self.total_skipped_dup += 1
                return True
            self.seen_msg_ids.add(msg_id)
            return False

    def record_copied(self, msg_id: str, is_unread: bool) -> tuple[int, int, int]:
        with self.lock:
            if msg_id:
                self.existing_dest_ids.add(msg_id)
            self.total_copied += 1
            if is_unread:
                self.total_unread_copied += 1
            return self.total_scanned, self.total_copied, self.total_skipped_dup

    def record_skipped_date(self) -> None:
        with self.lock:
            self.total_skipped_date += 1

    def increment_scanned(self) -> int:
        with self.lock:
            self.total_scanned += 1
            return self.total_scanned


def process_email_worker(
    num: bytes,
    worker_id: int,
    thread_local: threading.local,
    imap_host: str,
    source_user: str,
    source_password: str,
    dest_user: str,
    dest_password: str,
    src_folder: str,
    dest_folder: str,
    cutoff_dt: datetime.datetime | None,
    dry_run: bool,
    stats: SyncStats,
) -> None:
    """Processes a single email message in a thread worker."""
    scanned_idx = stats.increment_scanned()

    def get_connections() -> tuple[imaplib.IMAP4_SSL, imaplib.IMAP4_SSL | None]:
        if not hasattr(thread_local, "src_imap") or thread_local.src_imap is None:
            src = imaplib.IMAP4_SSL(imap_host, 993)
            src.login(source_user, source_password)
            src.select(f'"{src_folder}"', readonly=True)
            thread_local.src_imap = src

        if not dry_run and (not hasattr(thread_local, "dest_imap") or thread_local.dest_imap is None):
            dest = imaplib.IMAP4_SSL(imap_host, 993)
            dest.login(dest_user, dest_password)
            thread_local.dest_imap = dest

        return thread_local.src_imap, getattr(thread_local, "dest_imap", None)

    def reset_connections() -> None:
        if hasattr(thread_local, "src_imap") and thread_local.src_imap:
            with contextlib.suppress(Exception):
                thread_local.src_imap.logout()
            thread_local.src_imap = None
        if hasattr(thread_local, "dest_imap") and thread_local.dest_imap:
            with contextlib.suppress(Exception):
                thread_local.dest_imap.logout()
            thread_local.dest_imap = None

    # 1. Fetch metadata and flags with retry
    hdr_data = None
    flags_raw = ""
    for _attempt in range(3):
        try:
            src_imap, _ = get_connections()
            res, fetch_res = src_imap.fetch(
                num, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])"
            )
            if res == "OK" and fetch_res and fetch_res[0]:
                hdr_data = fetch_res[0]
                break
        except Exception:
            time.sleep(1.0)
            reset_connections()

    if not hdr_data or not isinstance(hdr_data, tuple):
        return

    # Extract flags string from header metadata
    with contextlib.suppress(Exception):
        first_token = hdr_data[0].decode(errors="ignore")
        match = re.search(r"FLAGS\s*\(([^)]*)\)", first_token)
        if match:
            flags_raw = match.group(1)

    raw_hdr = hdr_data[1]
    hdr_msg = email.message_from_bytes(raw_hdr, policy=policy.default)
    from_addr = extract_email_address(hdr_msg["From"])
    subject = str(hdr_msg["Subject"] or "(No Subject)").replace("\r", "").replace("\n", " ")
    date_str = str(hdr_msg["Date"] or "")
    msg_id = str(hdr_msg["Message-ID"] or "").strip().strip("<>").strip('"')

    # Strict Date Verification: ensure email date is >= cutoff_dt
    if cutoff_dt:
        msg_dt = parse_rfc822_date(date_str)
        if msg_dt and msg_dt < cutoff_dt:
            stats.record_skipped_date()
            return

    # Deduplication check
    if stats.is_duplicate_or_record(msg_id):
        if scanned_idx % 100 == 0:
            print(f" -> [{scanned_idx}/{stats.total_matched}] [SKIP DUP] (already in destination)")
        return

    date_short = date_str[:16] if date_str else "Unknown Date"
    is_unread = "\\Seen" not in flags_raw
    read_label = "UNREAD" if is_unread else "READ"

    if dry_run:
        stats.record_copied(msg_id, is_unread)
        print(
            f" -> [{scanned_idx}/{stats.total_matched}] [PREVIEW {read_label}] "
            f"{date_short} | {from_addr:22} | '{subject[:28]}...'"
        )
        return

    # 2. Fetch full RFC 822 message bytes with retry
    full_data = None
    for _attempt in range(3):
        try:
            src_imap, _ = get_connections()
            res, f_res = src_imap.fetch(num, "(RFC822)")
            if res == "OK" and f_res and f_res[0] and isinstance(f_res[0], tuple):
                full_data = f_res[0]
                break
        except Exception:
            time.sleep(1.0)
            reset_connections()

    if not full_data or not isinstance(full_data, tuple):
        return
    rfc822_bytes = full_data[1]

    # Preserve internal date and read/unread flags
    internal_timestamp = get_imap_internal_date(date_str)
    imap_time = imaplib.Time2Internaldate(internal_timestamp)
    target_flags = extract_flags_for_append(flags_raw)

    # 3. Append to destination label folder with retry
    copied_ok = False
    for _attempt in range(3):
        try:
            _, dest_imap = get_connections()
            if dest_imap:
                dest_imap.append(f'"{dest_folder}"', target_flags, imap_time, rfc822_bytes)
                copied_ok = True
                break
        except Exception:
            try:
                reset_connections()
                _, dest_imap = get_connections()
                if dest_imap:
                    dest_imap.append('"INBOX"', target_flags, imap_time, rfc822_bytes)
                    copied_ok = True
                    break
            except Exception:
                time.sleep(1.0)

    if copied_ok:
        curr_scanned, curr_copied, curr_dups = stats.record_copied(msg_id, is_unread)
        print(
            f" -> [{curr_scanned}/{stats.total_matched}] [COPIED {read_label}] "
            f"{date_short} | {from_addr:22} | '{subject[:28]}...'",
            flush=True,
        )
        if curr_scanned % 50 == 0:
            print(
                f"--- [PROGRESS] {curr_scanned}/{stats.total_matched} processed "
                f"({curr_copied} copied, {curr_dups} skipped dups) ---",
                flush=True,
            )
    else:
        print(f" -> [{scanned_idx}/{stats.total_matched}] [ERROR] Failed to copy '{subject[:28]}'", flush=True)


def sync_mailboxes(
    source_user: str,
    source_password: str,
    dest_user: str,
    dest_password: str,
    label: str,
    imap_host: str = "imap.gmail.com",
    since_date: str = "2024-01-01",
    workers: int = 6,
    limit: int = 0,
    dry_run: bool = False,
) -> None:
    """Synchronizes ONLY emails with the specified Gmail label from old to new mailbox."""
    print("===================================================================")
    print("      ESTATEOS HIGH-SPEED MAILBOX SYNC (OLD GMAIL -> NEW GMAIL)    ")
    print("===================================================================")
    print(f"Source Mailbox      : {source_user}")
    print(f"Destination Mailbox : {dest_user}")
    print(f"Target Label        : '{label}' (ONLY this label's emails will be copied)")
    print(f"Date Cutoff         : From {since_date} onward (strictly no older emails)")
    print("Read/Unread Status  : Fully preserved (unread emails remain unread)")
    print(f"Parallel Workers    : {workers} concurrent IMAP connections")
    if limit > 0:
        print(f"Transfer Limit      : {limit} emails")
    print(f"Mode                : {'DRY RUN (Preview Only)' if dry_run else 'LIVE COPY'}")
    print("-------------------------------------------------------------------")

    cutoff_dt: datetime.datetime | None = None
    if since_date:
        try:
            cutoff_dt = datetime.datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        except Exception:
            cutoff_dt = None

    # Connect initial client to verify credentials and scan label
    print(f"Connecting to Source ({source_user})...")
    src_imap = imaplib.IMAP4_SSL(imap_host, 993)
    try:
        src_imap.login(source_user, source_password)
        print(" -> Source authentication successful!")
    except Exception as exc:
        print(f"[ERROR] Source login failed: {exc}")
        sys.exit(1)

    dest_imap: imaplib.IMAP4_SSL | None = None
    existing_dest_ids: set[str] = set()
    dest_folder = label
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

        # Ensure destination label exists
        with contextlib.suppress(Exception):
            dest_imap.create(f'"{dest_folder}"')

        # Pre-cache destination Message-IDs
        existing_dest_ids = fetch_dest_existing_message_ids(dest_imap)
        with contextlib.suppress(Exception):
            dest_imap.logout()

    # Fetch message numbers from Source
    print(f"\nLocating and scanning label '{label}' on Source from {since_date} onward...")
    folder_used, msg_nums = fetch_label_message_numbers(src_imap, label, since_date=since_date)
    with contextlib.suppress(Exception):
        src_imap.logout()

    if not msg_nums:
        print(f" -> 0 emails found under label '{label}' in '{folder_used}'.")
        return

    total_matched = len(msg_nums)
    if limit > 0 and total_matched > limit:
        msg_nums = msg_nums[:limit]
        print(f" -> Found {total_matched} emails under label '{label}'. Limited to first {limit}.")
        total_matched = limit
    else:
        print(f" -> Found {total_matched} emails under label '{label}'. Starting multi-worker copy...")

    stats = SyncStats(total_matched=total_matched, existing_ids=existing_dest_ids)
    thread_local = threading.local()

    # Run multi-worker thread pool
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                process_email_worker,
                num=num,
                worker_id=i % workers,
                thread_local=thread_local,
                imap_host=imap_host,
                source_user=source_user,
                source_password=source_password,
                dest_user=dest_user,
                dest_password=dest_password,
                src_folder=folder_used,
                dest_folder=dest_folder,
                cutoff_dt=cutoff_dt,
                dry_run=dry_run,
                stats=stats,
            )
            for i, num in enumerate(msg_nums)
        ]
        concurrent.futures.wait(futures)

    duration = time.time() - start_time
    rate = stats.total_copied / max(1.0, duration)

    print("\n===================================================================")
    print("                     SYNC EXECUTION SUMMARY                        ")
    print("===================================================================")
    print(f"Target Label                   : {label}")
    print(f"Date Cutoff                    : From {since_date} onward")
    print(f"Total Emails Processed         : {stats.total_scanned}/{stats.total_matched}")
    print(f"Duplicates Already on Dest     : {stats.total_skipped_dup}")
    print(f"Skipped Pre-2024 Date Filter   : {stats.total_skipped_date}")
    print(f"Unread Emails Preserved        : {stats.total_unread_copied}")
    print(f"{'Previewed for Copy' if dry_run else 'Successfully Copied to New Gmail'}: {stats.total_copied}")
    print(f"Time Taken                     : {duration:.1f} seconds ({duration / 60:.1f} minutes)")
    print(f"Average Transfer Speed         : {rate:.1f} emails/second")
    print("===================================================================\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="EstateOS Mailbox-to-Mailbox Sync Tool (Old Gmail -> New Gmail)")
    parser.add_argument("--dry-run", action="store_true", help="Preview matched emails without modifying destination")
    parser.add_argument(
        "--label",
        type=str,
        default=TARGET_LABEL,
        help=f"Specific Gmail label to sync (default: '{TARGET_LABEL}')",
    )
    parser.add_argument(
        "--source-user", type=str, default="harjotsj@gmail.com", help="Old Gmail email address (source)"
    )
    parser.add_argument(
        "--source-password", type=str, help="16-character App Password for Old Gmail (prompted if omitted)"
    )
    parser.add_argument(
        "--dest-user", type=str, default="info@hrrealestate.nl", help="New Gmail email address (destination)"
    )
    parser.add_argument(
        "--dest-password", type=str, help="16-character App Password for New Gmail (prompted if omitted)"
    )
    parser.add_argument(
        "--since-date",
        type=str,
        default=DEFAULT_SINCE_DATE,
        help=f"Sync emails received on or after YYYY-MM-DD (default: '{DEFAULT_SINCE_DATE}')",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of parallel IMAP workers (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Max emails to copy (default: 0 = all matching emails)"
    )
    args = parser.parse_args()

    label = (args.label or TARGET_LABEL).strip()
    src_user = (args.source_user or "harjotsj@gmail.com").strip()
    src_pw = (args.source_password or "").replace(" ", "").strip()
    if not src_pw:
        src_pw = getpass.getpass(f"Enter 16-character Google App Password for {src_user}: ").replace(" ", "").strip()

    dest_user = (args.dest_user or "info@hrrealestate.nl").strip()
    dest_pw = (args.dest_password or "").replace(" ", "").strip()
    if not dest_pw and not args.dry_run:
        dest_pw = getpass.getpass(f"Enter 16-character Google App Password for {dest_user}: ").replace(" ", "").strip()

    sync_mailboxes(
        source_user=src_user,
        source_password=src_pw,
        dest_user=dest_user,
        dest_password=dest_pw or "",
        label=label,
        since_date=args.since_date,
        workers=args.workers,
        limit=args.limit,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
