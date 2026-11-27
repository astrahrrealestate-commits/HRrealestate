#!/usr/bin/env python3
# ruff: noqa: I001, T201
"""Vastgoed Gmail IMAP History Backfill for M13 (read-only dry-run + M13 pipeline ingestion).

Fetches emails strictly from Gmail label `Vastgoed` within `[--since, --until]` over IMAP,
normalises them with M13's `channels.gmail.inbound.to_message`, stores attachments and rows as
M13 history (`pipeline_status = held`), and optionally enqueues them onto DBOS `HISTORY_QUEUE`
(which categorises into the 6 M13 areas, links threads, and indexes RAG with 0 WhatsApp alerts).
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from collections.abc import Sequence
import contextlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
import imaplib
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
from uuid import UUID

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import Engine, func, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.channels.gmail.inbound import IGNORED_LABELS, to_message as gmail_to_message  # noqa: E402
from app.channels.gmail.models import GmailMessage  # noqa: E402
from app.contracts import Channel, Direction  # noqa: E402
from app.core.errors import IgnoredMessageError, UnroutableMessageError  # noqa: E402
from app.core.ids import new_id  # noqa: E402
from app.core.settings import Settings, get_settings  # noqa: E402
from app.db.enums import PipelineStatus, RawEventStatus  # noqa: E402
from app.db.models import ChannelAccount, Company, MessageRow, RawEvent  # noqa: E402
from app.db.session import make_engine  # noqa: E402
from app.ingestion.process import company_mailboxes, owner_addresses  # noqa: E402
from app.ingestion.media import store_attachment  # noqa: E402
from app.ingestion.repository import mark_raw_event, save_message  # noqa: E402
from app.workflows.prepare import prepare_for_draft as _prepare  # noqa: E402
from app.storage.factory import build_storage  # noqa: E402
from app.storage.ports import ObjectStorage  # noqa: E402
from app.tools.message_rag import index_message  # noqa: E402
from app.workflows.deps import get_deps  # noqa: E402
from app.workflows.mail_draft_open import DraftOpenReport, draft_open  # noqa: E402
from app.workflows.mail_reload import run_history, settle_history  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
META_BATCH = 400
BODY_BATCH = 50
DEFAULT_OWNER_HINT_EMAILS = frozenset({"info@hrrealestate.nl", "singh@hrrealestate.nl", "harjotsj@gmail.com"})

_IMAP_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_UID_RE = re.compile(rb"UID\s+(\d+)")
_MSGID_RE = re.compile(rb"X-GM-MSGID\s+(\d+)")
_THRID_RE = re.compile(rb"X-GM-THRID\s+(\d+)")
_LABELS_RE = re.compile(rb"X-GM-LABELS\s+\(([^)]*)\)")
_DATE_RE = re.compile(rb'INTERNALDATE\s+"([^"]+)"')


@dataclass(frozen=True)
class ImapMeta:
    uid: str
    gmail_msg_id: str
    gmail_thread_id: str
    label_ids: tuple[str, ...]
    internal_date: datetime


def _imap_date(d: date) -> str:
    return f"{d.day:02d}-{_IMAP_MONTHS[d.month - 1]}-{d.year}"


def _to_gmail_hex(decimal_id: str) -> str:
    return format(int(decimal_id), "x")


def _parse_labels(raw_labels: bytes | None) -> tuple[str, ...]:
    if not raw_labels:
        return ()
    text = raw_labels.decode("utf-8", errors="replace")
    mapped: list[str] = []
    lower = text.lower()
    if "\\sent" in lower:
        mapped.append("SENT")
    if "\\draft" in lower:
        mapped.append("DRAFT")
    if "\\trash" in lower:
        mapped.append("TRASH")
    if "\\junk" in lower:
        mapped.append("SPAM")
    return tuple(mapped)


def _extract_meta(fetch_items: Sequence[Any]) -> list[ImapMeta]:
    results: list[ImapMeta] = []
    for item in fetch_items:
        header = item[0] if isinstance(item, tuple) else item
        if not isinstance(header, bytes):
            continue
        uid_m = _UID_RE.search(header)
        mid_m = _MSGID_RE.search(header)
        tid_m = _THRID_RE.search(header)
        date_m = _DATE_RE.search(header)
        if not (uid_m and mid_m and tid_m and date_m):
            continue
        labels_m = _LABELS_RE.search(header)
        dt = parsedate_to_datetime(date_m.group(1).decode("ascii", errors="replace"))
        dt_utc = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
        results.append(
            ImapMeta(
                uid=uid_m.group(1).decode("ascii"),
                gmail_msg_id=_to_gmail_hex(mid_m.group(1).decode("ascii")),
                gmail_thread_id=_to_gmail_hex(tid_m.group(1).decode("ascii")),
                label_ids=_parse_labels(labels_m.group(1) if labels_m else None),
                internal_date=dt_utc,
            )
        )
    return results


def _fetch_metadata(conn: imaplib.IMAP4_SSL, uids: Sequence[str]) -> list[ImapMeta]:
    out: list[ImapMeta] = []
    for start in range(0, len(uids), META_BATCH):
        chunk = ",".join(uids[start : start + META_BATCH])
        status, data = conn.uid("fetch", chunk, "(UID X-GM-MSGID X-GM-THRID X-GM-LABELS INTERNALDATE)")
        if status != "OK":
            raise RuntimeError(f"IMAP metadata fetch failed: {status}")
        out.extend(_extract_meta(data))
    return out


def _fetch_raw_bodies(conn: imaplib.IMAP4_SSL, uids: Sequence[str]) -> dict[str, bytes]:
    bodies: dict[str, bytes] = {}
    if not uids:
        return bodies
    chunk = ",".join(uids)
    status, data = conn.uid("fetch", chunk, "(UID BODY.PEEK[])")
    if status != "OK":
        raise RuntimeError(f"IMAP body fetch failed: {status}")
    for item in data:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        header, payload = item[0], item[1]
        if not isinstance(header, bytes) or not isinstance(payload, bytes):
            continue
        uid_m = _UID_RE.search(header)
        if uid_m:
            bodies[uid_m.group(1).decode("ascii")] = payload
    return bodies


def _resolve_company_id(session: Session, company_id_arg: str | None) -> UUID:
    if company_id_arg:
        cid = UUID(company_id_arg)
        if session.get(Company, cid) is None:
            raise SystemExit(f"Company not found: {cid}")
        return cid
    row = session.scalar(select(Company).order_by(Company.created_at).limit(1))
    if row is None:
        raise SystemExit("No company found in Postgres. Run `make seed` first.")
    return row.id


def _ensure_gmail_account(session: Session, company_id: UUID, mailbox: str) -> ChannelAccount:
    norm = mailbox.strip().lower()
    existing = session.scalar(
        select(ChannelAccount).where(
            ChannelAccount.company_id == company_id,
            ChannelAccount.channel == Channel.gmail,
            func.lower(ChannelAccount.address) == norm,
        )
    )
    if existing is not None:
        return existing
    acc = ChannelAccount(id=new_id(), company_id=company_id, channel=Channel.gmail, address=norm)
    session.add(acc)
    session.flush()
    return acc


def _existing_provider_ids(session: Session, company_id: UUID, candidate_ids: Sequence[str]) -> set[str]:
    existing: set[str] = set()
    for start in range(0, len(candidate_ids), 1000):
        chunk = list(candidate_ids[start : start + 1000])
        rows = session.scalars(
            select(MessageRow.provider_msg_id).where(
                MessageRow.company_id == company_id,
                MessageRow.channel == Channel.gmail,
                MessageRow.provider_msg_id.in_(chunk),
            )
        ).all()
        existing.update(rows)
    return existing


def _insert_raw_event(session: Session, account: ChannelAccount, meta: ImapMeta) -> UUID | None:
    payload = {
        "v": 1,
        "kind": "imap_backfill",
        "mailbox": account.address,
        "message_id": meta.gmail_msg_id,
        "history": True,
    }
    return session.scalar(
        insert(RawEvent)
        .values(
            company_id=account.company_id,
            provider=Channel.gmail,
            provider_msg_id=meta.gmail_msg_id,
            payload=payload,
            status=RawEventStatus.processed,
        )
        .on_conflict_do_nothing(index_elements=["company_id", "provider", "provider_msg_id"])
        .returning(RawEvent.id)
    )


def _ingest_one(
    engine: Engine,
    storage: ObjectStorage,
    settings: Settings,
    account: ChannelAccount,
    meta: ImapMeta,
    raw_bytes: bytes,
    forwarders: frozenset[str],
    own: frozenset[str],
    cutoff_date: date | None = None,
) -> str:
    gm = GmailMessage(
        id=meta.gmail_msg_id,
        thread_id=meta.gmail_thread_id,
        label_ids=list(meta.label_ids),
        internal_date=str(int(meta.internal_date.timestamp() * 1000)),
        raw=base64.urlsafe_b64encode(raw_bytes).decode("ascii"),
    )
    with Session(engine) as session, session.begin():
        raw_id = _insert_raw_event(session, account, meta)
        if raw_id is None:
            return "duplicate"
        try:
            message, row_meta, parts = gmail_to_message(
                gm,
                company_id=account.company_id,
                raw_event_id=raw_id,
                mailbox=account.address,
                forwarders=forwarders,
                own_addresses=own,
            )
        except IgnoredMessageError as exc:
            mark_raw_event(session, account.company_id, raw_id, RawEventStatus.ignored, str(exc))
            return "ignored"
        except (UnroutableMessageError, ValueError) as exc:
            mark_raw_event(session, account.company_id, raw_id, RawEventStatus.failed, f"{type(exc).__name__}: {exc}")
            return "failed"

        stored = [store_attachment(storage, account.company_id, p.data, p.mime_type, p.filename) for p in parts]
        full_meta = {**row_meta, "history": True}
        msg_id, created = save_message(session, message, full_meta, stored)
        row = session.get(MessageRow, msg_id)
        is_older_tier = cutoff_date is not None and meta.internal_date.date() < cutoff_date
        if row is not None and row.pipeline_status is PipelineStatus.pending:
            if is_older_tier or message.direction is Direction.outbound:
                next_status = PipelineStatus.done
            else:
                next_status = PipelineStatus.held
            row.pipeline_status = next_status
    if created and (is_older_tier or message.direction is Direction.outbound):
        with contextlib.suppress(Exception):
            index_message(engine, settings, msg_id)
    if is_older_tier:
        return "ingested_history_done"
    return "ingested_outbound" if message.direction is Direction.outbound else "ingested_inbound"


def _print_dry_run(
    mailbox: str,
    label: str,
    since_d: date,
    until_d: date,
    total_label: int,
    metas: Sequence[ImapMeta],
    existing_ids: set[str],
) -> None:
    threads = {m.gmail_thread_id for m in metas}
    ignored = sum(1 for m in metas if IGNORED_LABELS.intersection(m.label_ids))
    outbound = sum(1 for m in metas if "SENT" in m.label_ids and not IGNORED_LABELS.intersection(m.label_ids))
    inbound = len(metas) - ignored - outbound
    already = sum(1 for m in metas if m.gmail_msg_id in existing_ids)
    by_month = Counter(m.internal_date.strftime("%Y-%m") for m in metas)

    print("=== Vastgoed IMAP Backfill (DRY RUN) ===")
    print(f"Mailbox:         {mailbox}")
    print(f"Label:           {label} ({total_label} total messages in label)")
    print(f"Date window:     {since_d.isoformat()} .. {until_d.isoformat()} (inclusive)")
    print(f"Matched emails:  {len(metas)} across {len(threads)} unique Gmail threads")
    print(f"  Inbound:       {inbound}")
    print(f"  Sent/Outbound: {outbound}")
    print(f"  Ignored label: {ignored} (DRAFT/SPAM/TRASH)")
    print(f"Already in DB:   {already}")
    print(f"New to ingest:   {max(0, len(metas) - already - ignored)}")
    print("Monthly volume:")
    for ym in sorted(by_month):
        print(f"  {ym}: {by_month[ym]}")
    print("DRY RUN: 0 DB writes, 0 LLM calls.")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mailbox", default="info@hrrealestate.nl")
    p.add_argument("--password", default=os.environ.get("VASTGOED_IMAP_PASSWORD") or os.environ.get("IMAP_PASSWORD"))
    p.add_argument("--label", default="Vastgoed")
    p.add_argument("--since", default="2025-01-01", help="Start date YYYY-MM-DD (inclusive)")
    p.add_argument("--until", default="2026-11-23", help="End date YYYY-MM-DD (inclusive)")
    p.add_argument("--company-id", default=None, help="Target company UUID (defaults to primary DB company)")
    p.add_argument("--limit", type=int, default=None, help="Max new messages to ingest (for small test batches)")
    p.add_argument(
        "--cutoff-days",
        type=int,
        default=90,
        help="Messages older than N days are marked done with RAG embeddings (skips LLM understand/link)",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Write messages into Postgres as M13 history (default is dry-run)",
    )
    p.add_argument("--enqueue", action="store_true", help="Enqueue held inbound messages onto DBOS HISTORY_QUEUE")
    p.add_argument("--settle-days", type=int, default=None, help="Resolve history cases quiet for N days")
    p.add_argument("--draft-open-days", type=int, default=None, help="Run M13 draft_open for last N days (live)")
    p.add_argument("--draft-open-dry-run", action="store_true", help="Preview draft_open without writing drafts")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.password:
        raise SystemExit("IMAP password required: pass --password or set VASTGOED_IMAP_PASSWORD")
    since_d = date.fromisoformat(args.since)
    until_d = date.fromisoformat(args.until)
    if until_d < since_d:
        raise SystemExit("--until must be >= --since")

    settings = get_settings()
    engine = make_engine(settings.sqlalchemy_url)
    with Session(engine) as session:
        company_id = _resolve_company_id(session, args.company_id)

    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    try:
        conn.login(args.mailbox, args.password.replace(" ", ""))
        sel_status, sel_data = conn.select(args.label, readonly=True)
        if sel_status != "OK":
            raise SystemExit(f"Could not select label {args.label!r}: {sel_status}")
        total_label = int(sel_data[0])
        before_d = until_d + timedelta(days=1)
        st, raw_uids = conn.uid("search", None, "SINCE", _imap_date(since_d), "BEFORE", _imap_date(before_d))
        if st != "OK":
            raise SystemExit(f"IMAP search failed: {st}")
        t0 = time.monotonic()
        uids = [u.decode("ascii") for u in (raw_uids[0].split() if raw_uids[0] else [])]
        metas = _fetch_metadata(conn, uids)
        metas.sort(key=lambda m: (m.internal_date, int(m.uid)))
        t_meta = time.monotonic() - t0
        print(f"Metadata scan complete: {len(metas)} emails in {t_meta:.1f}s")

        with Session(engine) as session:
            existing_ids = _existing_provider_ids(session, company_id, [m.gmail_msg_id for m in metas])

        if not args.apply:
            _print_dry_run(args.mailbox, args.label, since_d, until_d, total_label, metas, existing_ids)
            return 0

        t_ingest_start = time.monotonic()
        to_ingest = [
            m for m in metas if m.gmail_msg_id not in existing_ids and not IGNORED_LABELS.intersection(m.label_ids)
        ]
        if args.limit is not None:
            to_ingest = to_ingest[: args.limit]

        storage = build_storage(settings)
        with Session(engine) as session, session.begin():
            account = _ensure_gmail_account(session, company_id, args.mailbox)
            session.expunge(account)

        fwd = owner_addresses(engine, company_id) | DEFAULT_OWNER_HINT_EMAILS
        own = company_mailboxes(engine, company_id) | {args.mailbox.strip().lower()}
        counts: Counter[str] = Counter()

        cutoff_date = (date.today() - timedelta(days=args.cutoff_days)) if args.cutoff_days else None
        for start in range(0, len(to_ingest), BODY_BATCH):
            batch = to_ingest[start : start + BODY_BATCH]
            raw_map = _fetch_raw_bodies(conn, [m.uid for m in batch])
            for m in batch:
                raw_bytes = raw_map.get(m.uid)
                if raw_bytes is None:
                    counts["missing_body"] += 1
                    continue
                outcome = _ingest_one(engine, storage, settings, account, m, raw_bytes, fwd, own, cutoff_date)
                counts[outcome] += 1
            print(f"Processed {min(start + BODY_BATCH, len(to_ingest))}/{len(to_ingest)} new emails...")
        print(f"Body download + DB ingest elapsed: {time.monotonic() - t_ingest_start:.1f}s")
    finally:
        with contextlib.suppress(Exception):
            conn.logout()

    print(f"Ingestion complete: {dict(counts)}")
    if args.enqueue:
        deps = get_deps()
        released = run_history(engine, deps.enqueuer, args.mailbox.strip().lower())
        print(f"Enqueued onto HISTORY_QUEUE: {released} inbound held messages")
    if args.settle_days is not None:
        settled = settle_history(engine, args.mailbox.strip().lower(), idle_days=args.settle_days)
        print(f"Settled quiet cases: {settled}")
    if args.draft_open_days is not None:
        report: DraftOpenReport = draft_open(
            engine,
            settings,
            args.mailbox.strip().lower(),
            max_age_days=args.draft_open_days,
            dry_run=args.draft_open_dry_run,
            prepare=_prepare,
        )
        print(
            f"draft_open: drafted={len(report.drafted)}, skipped={len(report.skipped)}, "
            f"dry_run={args.draft_open_dry_run}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
