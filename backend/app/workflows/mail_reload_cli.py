"""Purge and reload one mailbox (M13 T2). Run on a deployed environment through `scripts/mail_reload.sh`.

`python -m app.workflows.mail_reload_cli --mailbox <address>` plus exactly one mode:
`--preview` · `--purge --worker-stopped --confirm "purge <address>"` · `--reingest --days N` · `--run-history` ·
`--settle [--idle-days N]` · `--draft-open [--max-age-days N] [--dry-run]` · `--draft-report [--days N]`.
`--purge` prints the draft report of the last 30 days first: the purge deletes the rows it counts.

Every mode prints counts and case ids only, never message text, names or addresses: CloudWatch keeps the output.
"""

import argparse
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from functools import partial
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.channels import google_store
from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.pipeline.person_memory import refresh_person_memory
from app.storage.drive import CONTENT_PROPERTY, DriveApiError, DriveStore, content_value
from app.workflows.deps import get_deps, get_drive
from app.workflows.draft_report_cli import report_text
from app.workflows.mail_draft_open import MAX_AGE_DAYS, DraftOpenReport, draft_open
from app.workflows.mail_purge import FileHash, PurgeRefusedError, ReloadPreview, preview, purge
from app.workflows.mail_purge_scope import mailbox_company
from app.workflows.mail_reload import IDLE_DAYS, reingest, run_history, settle_history
from app.workflows.prepare import prepare_for_draft

log = get_logger(__name__)
DEFAULT_DAYS = 90
REPORT_DAYS = 30
DraftReport = Callable[[Engine, str, int], str]


def mailbox_report(engine: Engine, mailbox: str, days: int) -> str:
    """T16's draft report for the mailbox's company: counts and ratios only."""
    with Session(engine) as session:
        company_id = mailbox_company(session, mailbox)
    return report_text(engine, company_id, days, datetime.now(UTC)) + "\n"


def render_preview(report: ReloadPreview, *, purged: bool) -> str:
    counts = [
        ("messages", report.messages),
        ("attachments", report.attachments),
        ("raw events", report.raw_events),
        ("cases left with no message", report.cases),
        ("actions", report.actions),
        ("approvals", report.approvals),
        ("documents", report.documents),
        ("quotes", report.quotes),
        ("sends kept, detached from their action", report.sends),
    ]
    lines = [f"{label}: {count}" for label, count in counts]
    if report.oldest is not None and report.newest is not None:
        lines.append(f"mail from {report.oldest:%Y-%m-%d} to {report.newest:%Y-%m-%d}")
    lines.append("rows per table:")
    lines += [f"  {table}: {count}" for table, count in sorted(report.tables.items()) if count]
    lines.append("PURGED" if purged else "PREVIEW: nothing was changed")
    return "\n".join(lines) + "\n"


def render_drafts(report: DraftOpenReport, *, dry_run: bool) -> str:
    verb = "would be drafted" if dry_run else "drafted"
    lines = [f"  {case_id}" for case_id in report.drafted]
    reasons = Counter(reason.value for _, reason in report.skipped)
    return "\n".join(
        [
            f"cases {verb}: {len(report.drafted)}",
            *lines,
            f"cases skipped: {len(report.skipped)}",
            *(f"  {reason}: {count}" for reason, count in sorted(reasons.items())),
            "DRY RUN: nothing was written" if dry_run else "DONE: drafts wait for approval, nothing was sent",
        ]
    ) + "\n"  # fmt: skip


def stamp_files(drive: DriveStore, company_id: UUID, files: Sequence[FileHash]) -> None:
    """Write each file's content hash onto it in Drive, so the reload finds it. A file that is gone is skipped; any
    other Drive failure stops the purge before anything is deleted."""
    missing = 0
    for file_id, sha256 in files:
        try:
            drive.annotate(file_id, None, {CONTENT_PROPERTY: content_value(company_id, sha256)})
        except DriveApiError as exc:
            if exc.status != 404:
                raise
            missing += 1
    sys.stdout.write(f"Drive files marked: {len(files) - missing}, gone from Drive: {missing}\n")


def _has_drive(settings: Settings) -> bool:
    if settings.drive_provider == "fake":
        return False
    return settings.drive_credentials_file is not None or google_store.refresh(settings).exists()


def _parsed(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mailbox", required=True, help="connected company mailbox")
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ("preview", "purge", "reingest", "run-history", "settle", "draft-open", "draft-report"):
        mode.add_argument(f"--{name}", action="store_true")
    parser.add_argument("--worker-stopped", action="store_true", help="confirm the worker is stopped (--purge)")
    parser.add_argument("--confirm", default="", help='exactly "purge <mailbox>" (--purge)')
    parser.add_argument("--days", type=int, default=None, help="days of mail (--reingest 90, --draft-report 30)")
    parser.add_argument("--idle-days", type=int, default=IDLE_DAYS, help="quiet for this long: resolved (--settle)")
    parser.add_argument("--max-age-days", type=int, default=MAX_AGE_DAYS, help="newest mail at most this old")
    parser.add_argument("--dry-run", action="store_true", help="list what --draft-open would draft")
    args = parser.parse_args(argv)
    if args.purge and not args.worker_stopped:
        parser.error("--purge needs --worker-stopped: stop the worker first")
    if min(args.days or 1, args.idle_days, args.max_age_days) < 1:
        parser.error("a number of days must be at least 1")
    return args


def _purge(engine: Engine, settings: Settings, args: argparse.Namespace, draft_report: DraftReport) -> str:
    sys.stdout.write(draft_report(engine, args.mailbox, REPORT_DAYS))  # it counts rows the purge deletes: first
    if _has_drive(settings):
        stamp = partial(stamp_files, get_drive())
        return render_preview(purge(engine, args.mailbox, confirm=args.confirm, stamp=stamp), purged=True)
    return render_preview(purge(engine, args.mailbox, confirm=args.confirm), purged=True)


def _prepare(engine: Engine, settings: Settings, message_id: UUID) -> None:
    """Read attachments, review any quote, and research web/reference sources before the draft (T8)."""
    prepare_for_draft(engine, settings, message_id, research=True)


def _memory(engine: Engine, settings: Settings, company_id: UUID, person_id: UUID) -> None:
    refresh_person_memory(engine, settings, company_id, person_id)


def _run(args: argparse.Namespace, draft_report: DraftReport) -> str:
    settings, deps = get_settings(), get_deps()
    engine, mailbox = deps.engine, args.mailbox
    if args.preview:
        return render_preview(preview(engine, mailbox), purged=False)
    if args.purge:
        return _purge(engine, settings, args, draft_report)
    if args.draft_report:
        return draft_report(engine, mailbox, args.days or REPORT_DAYS)
    if args.reingest:
        return f"history mail recorded: {reingest(deps, mailbox, days=args.days or DEFAULT_DAYS)}\n"
    if args.run_history:
        return f"held messages queued: {run_history(engine, deps.enqueuer, mailbox)}\n"
    if args.settle:
        return f"cases resolved: {settle_history(engine, mailbox, idle_days=args.idle_days)}\n"
    report = draft_open(
        engine, settings, mailbox, max_age_days=args.max_age_days, dry_run=args.dry_run, prepare=_prepare,
        refresh_memory=_memory,
    )  # fmt: skip
    return render_drafts(report, dry_run=args.dry_run)


def main(argv: list[str] | None = None, *, draft_report: DraftReport = mailbox_report) -> int:
    args = _parsed(argv)
    try:
        sys.stdout.write(_run(args, draft_report))
    except PurgeRefusedError as exc:
        sys.stdout.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
