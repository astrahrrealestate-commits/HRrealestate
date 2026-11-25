from uuid import uuid4

import pytest

from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.workflows.reattribute import Change, RepairRefusedError, Report, gmail_api_id
from app.workflows.reattribute_cli import main, real_mailbox, render
from app.workflows.reattribute_replies import CancelledReply, CaseToCheck


@pytest.mark.parametrize(
    ("stored", "api_id"),
    [
        ("18c0000000000001", "18c0000000000001"),  # a live-sync row already holds the API id
        ("1785210000000000000", format(1785210000000000000, "x")),  # an IMAP import holds X-GM-MSGID in decimal
        ("hist_0123456789abcdef", None),  # a hashed history row has no Gmail id
    ],
)
def test_the_gmail_api_id_behind_a_stored_message_id(stored: str, api_id: str | None) -> None:
    assert gmail_api_id(stored) == api_id


@pytest.mark.parametrize(("applied", "last"), [(False, "DRY RUN: nothing was changed"), (True, "APPLIED")])
def test_the_report_lists_what_a_person_must_check(applied: bool, last: str) -> None:
    case, action = uuid4(), uuid4()
    report = Report(
        changes=[Change(uuid4(), "us@example.test", "jan@example.test", was_marked_sent=True)],
        cancelled=[CancelledReply(case, action, "approved")],
        cases=[CaseToCheck(case, ("jan@example.test", "piet@example.test"))],
    )
    text = render(report, applied=applied)
    assert "us@example.test -> jan@example.test (was marked sent)" in text
    assert f"{action}  case {case}  was approved" in text
    assert f"{case}  2 senders: jan@example.test, piet@example.test" in text
    assert text.rstrip().endswith(last)


def test_applying_needs_the_worker_to_be_stopped(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--mailbox", "info@example.test", "--apply"])
    assert "--worker-stopped" in capsys.readouterr().err


def test_a_fake_mailbox_is_never_repaired_from() -> None:
    with pytest.raises(RepairRefusedError):
        real_mailbox(FakeMailbox("info@example.test", MemoryMailboxStore()))
