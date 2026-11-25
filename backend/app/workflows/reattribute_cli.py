"""Preview, or apply, the repair of mail stored under our own address.

`python -m app.workflows.reattribute_cli --mailbox <address>` previews and writes nothing. To write, stop the worker
and do not draft replies from the dashboard until the run ends (either could draft from the old sender), take a
database snapshot, then add
`--apply --worker-stopped`. The report lists contact
names, email addresses and numbers, never subjects or text: run it where output is not kept, and do not paste it
anywhere public.
"""

import argparse
import sys

from app.channels import registry
from app.channels.gmail.fake import FakeMailbox
from app.channels.gmail.ports import GmailMailbox
from app.core.settings import get_settings
from app.db.session import make_engine
from app.workflows.reattribute import RepairRefusedError, Report, reattribute
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
    )
    lines += [f"{label}: {count}" for label, count in counts]
    lines.append("APPLIED" if applied else "DRY RUN: nothing was changed")
    return "\n".join(lines) + "\n"


def real_mailbox(mailbox: GmailMailbox) -> GmailMailbox:
    if isinstance(mailbox, FakeMailbox):
        raise RepairRefusedError("this environment has no real Gmail connection for that mailbox")
    return mailbox


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mailbox", required=True, help="connected company mailbox to repair")
    parser.add_argument("--apply", action="store_true", help="write the changes (default: preview only)")
    parser.add_argument("--worker-stopped", action="store_true", help="confirm the worker is stopped")
    args = parser.parse_args(argv)
    if args.apply and not args.worker_stopped:
        parser.error("--apply needs --worker-stopped: stop the worker first")
    settings = get_settings()
    report = reattribute(
        make_engine(settings.sqlalchemy_url),
        lambda address: real_mailbox(registry.gmail_mailbox(settings, address)),
        args.mailbox,
        apply=args.apply,
    )
    sys.stdout.write(render(report, applied=args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())
