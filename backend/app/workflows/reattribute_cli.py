"""Preview, or apply, the repair of mail stored under our own address.

`python -m app.workflows.reattribute_cli --mailbox <address>` previews, writes nothing and calls no model.
`--apply` repairs only: stop the worker and do not draft replies from the dashboard until it ends (either could draft
from the old sender), take a database snapshot, then add `--apply --worker-stopped`. `--label` then runs the one-time
label pass (`reattribute_labels`), with the worker running again. The report lists contact names, email addresses and
numbers, never subjects or text: do not paste it anywhere public.
"""

import argparse
import sys
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.channels import registry
from app.channels.gmail.fake import FakeMailbox
from app.channels.gmail.ports import GmailMailbox
from app.contracts import Channel
from app.core.settings import Settings, get_settings
from app.db.session import make_engine
from app.ingestion.repository import resolve_channel_account
from app.workflows.reattribute import RepairRefusedError, Report, reattribute
from app.workflows.reattribute_labels import DEFAULT_MAX_CALLS, LabelReport, label_senders
from app.workflows.reattribute_replies import CaseToCheck


def _case_line(case: CaseToCheck) -> str:
    several = len(case.senders) > 1
    sort_first = "  << SORT FIRST" if several and case.state not in ("resolved", "closed") else ""
    return (
        f"  {case.case_id}  {case.state}, contact {case.contact or 'none'}  "
        f"{len(case.senders)} sender{'s' if several else ''}: {', '.join(case.senders)}{sort_first}"
    )


def render(report: Report, *, applied: bool) -> str:
    lines = ["Messages given their original sender:"]
    lines += [
        f"  {c.message_id}  {c.old_sender} -> {c.new_sender}" + (" (was marked sent)" if c.was_marked_sent else "")
        for c in report.changes
    ]
    lines.append("Unsent replies cancelled:")
    lines += [f"  {r.action_id}  case {r.case_id}  was {r.was}" for r in report.cancelled]
    lines.append("Cases to check (contact and flat NOT changed):")
    lines += [_case_line(c) for c in report.cases]
    counts = (
        ("messages repaired", len(report.changes)),
        ("replies cancelled", len(report.cancelled)),
        ("cases to check", len(report.cases)),
        ("left as ours (sent by the mailbox, or no other sender named)", report.unchanged),
        ("original cannot be read again", report.unrecoverable),
        ("marked sent, only quoted text names someone else (left alone)", report.uncertain),
        ("AI label calls (made only when applying)", report.to_label),
    )
    lines += [f"{label}: {count}" for label, count in counts]
    lines.append("APPLIED" if applied else "DRY RUN: nothing was changed")
    return "\n".join(lines) + "\n"


def render_labels(labels: LabelReport) -> str:
    lines = [
        f"labels written: {labels.labelled}",
        f"label calls failed: {labels.failed}",
        f"still to label: {labels.remaining}",
    ]
    if labels.stopped:
        lines.append(f"labelling stopped early: {labels.stopped}")
    if labels.stopped or labels.failed or labels.remaining:
        lines.append("run again to finish: mail already labelled is not asked again")
    return "\n".join(lines) + "\n"


def company_of(engine: Engine, mailbox: str) -> UUID:
    with Session(engine) as session:
        return resolve_channel_account(session, Channel.gmail, mailbox.strip().lower()).company_id


def real_mailbox(mailbox: GmailMailbox) -> GmailMailbox:
    if isinstance(mailbox, FakeMailbox):
        raise RepairRefusedError("this environment has no real Gmail connection for that mailbox")
    return mailbox


def _parsed(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mailbox", required=True, help="connected company mailbox to repair")
    step = parser.add_mutually_exclusive_group()
    step.add_argument("--apply", action="store_true", help="write the repair (default: preview only)")
    step.add_argument("--label", action="store_true", help="run the label pass; the worker may stay running")
    parser.add_argument("--worker-stopped", action="store_true", help="confirm the worker is stopped")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS, help="model calls allowed for --label")
    args = parser.parse_args(argv)
    if args.apply and not args.worker_stopped:
        parser.error("--apply needs --worker-stopped: stop the worker first")
    if args.max_calls < 1:
        parser.error("--max-calls must be at least 1")
    return args


def _require_model(settings: Settings) -> None:
    if settings.llm_model == "fake":
        raise RepairRefusedError("no real model is configured (LLM_MODEL=fake), so the labels would be made up")


def _label(engine: Engine, settings: Settings, mailbox: str, max_calls: int) -> int:
    try:
        labels = label_senders(engine, settings, company_of(engine, mailbox), max_calls=max_calls)
    except Exception as exc:  # the repair is already stored: say what failed and that a rerun is safe
        sys.stdout.write(f"labelling failed: {type(exc).__name__}\nrun again to finish\n")
        return 2
    sys.stdout.write(render_labels(labels))
    return 2 if labels.stopped or labels.failed or labels.remaining else 0


def main(argv: list[str] | None = None) -> int:
    args = _parsed(argv)
    settings = get_settings()
    if args.apply or args.label:
        _require_model(settings)
    engine = make_engine(settings.sqlalchemy_url)
    if args.label:
        return _label(engine, settings, args.mailbox, args.max_calls)
    report = reattribute(
        engine,
        lambda address: real_mailbox(registry.gmail_mailbox(settings, address)),
        args.mailbox,
        apply=args.apply,
    )
    sys.stdout.write(render(report, applied=args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())
