from uuid import uuid4

import pytest

from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.core.settings import get_settings
from app.workflows.reattribute import Change, RepairRefusedError, Report, gmail_api_id
from app.workflows.reattribute_cli import main, real_mailbox, render
from app.workflows.reattribute_labels import LabelReport
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
        cases=[CaseToCheck(case, ("jan@example.test", "piet@example.test"), contact="Harjot", state="open")],
    )
    text = render(report, applied=applied)
    assert "us@example.test -> jan@example.test (was marked sent)" in text
    assert f"{action}  case {case}  was approved" in text
    assert f"{case}  open, contact Harjot  2 senders: jan@example.test, piet@example.test  << SORT FIRST" in text
    assert text.rstrip().endswith(last)


def test_applying_needs_the_worker_to_be_stopped(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--mailbox", "info@example.test", "--apply"])
    assert "--worker-stopped" in capsys.readouterr().err


def test_a_fake_mailbox_is_never_repaired_from() -> None:
    with pytest.raises(RepairRefusedError):
        real_mailbox(FakeMailbox("info@example.test", MemoryMailboxStore()))


def test_applying_is_refused_without_a_real_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refused before anything is written: the labels would be the fake model's."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:1/none")
    monkeypatch.setenv("LLM_MODEL", "fake")
    get_settings.cache_clear()
    monkeypatch.setattr("app.workflows.reattribute_cli.reattribute", lambda *a, **k: pytest.fail("must not run"))
    try:
        with pytest.raises(RepairRefusedError, match="model"):
            main(["--mailbox", "info@example.test", "--apply", "--worker-stopped"])
    finally:
        get_settings.cache_clear()


def _cli(monkeypatch: pytest.MonkeyPatch, order: list[str], labels: LabelReport | Exception) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:1/none")
    monkeypatch.setenv("LLM_MODEL", "google-gla:gemini-3.8-flash")
    get_settings.cache_clear()
    company = uuid4()
    cli = "app.workflows.reattribute_cli"

    def label(engine: object, settings: object, company_id: object, *, max_calls: int) -> LabelReport:
        order.append(f"label max {max_calls}")
        if isinstance(labels, Exception):
            raise labels
        return labels

    monkeypatch.setattr(f"{cli}.make_engine", lambda url: None)
    monkeypatch.setattr(f"{cli}.reattribute", lambda *a, **k: (order.append("repair"), Report(company_id=company))[1])
    monkeypatch.setattr(f"{cli}.company_of", lambda engine, mailbox: company)
    monkeypatch.setattr(f"{cli}.label_senders", label)


def test_applying_repairs_only_so_the_worker_can_come_back_before_labelling(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    _cli(monkeypatch, order, LabelReport())
    try:
        assert main(["--mailbox", "info@example.test", "--apply", "--worker-stopped"]) == 0
    finally:
        get_settings.cache_clear()
    assert order == ["repair"]


@pytest.mark.parametrize(
    ("labels", "code", "text"),
    [
        (LabelReport(labelled=3), 0, "labels written: 3"),
        (LabelReport(labelled=1, failed=2, stopped="stopped early"), 2, "run again"),
        (LabelReport(labelled=200, remaining=40), 2, "still to label: 40"),
        (RuntimeError("boom"), 2, "labelling failed: RuntimeError"),
    ],
)
def test_the_label_step_says_when_to_run_it_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], labels: LabelReport | Exception, code: int,
    text: str,
) -> None:  # fmt: skip
    order: list[str] = []
    _cli(monkeypatch, order, labels)
    try:
        assert main(["--mailbox", "info@example.test", "--label", "--max-calls", "200"]) == code
    finally:
        get_settings.cache_clear()
    assert order == ["label max 200"]
    assert text in capsys.readouterr().out


@pytest.mark.parametrize("args", [["--label", "--apply", "--worker-stopped"], ["--label", "--max-calls", "0"]])
def test_conflicting_or_empty_label_requests_are_refused(args: list[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--mailbox", "info@example.test", *args])


def test_days_sender_and_redraft_flags_are_forwarded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:1/none")
    monkeypatch.setenv("LLM_MODEL", "google-gla:gemini-3.8-flash")
    get_settings.cache_clear()
    company, msg_id = uuid4(), uuid4()
    seen: dict[str, object] = {}

    def fake_reattribute(engine: object, mailboxes: object, mailbox: str, **kwargs: object) -> Report:
        seen.update(kwargs)
        return Report(
            company_id=company,
            changes=[Change(msg_id, "harjotsj@gmail.com", "tenant@example.test", was_marked_sent=False)],
        )

    redrafted: list[object] = []

    def fake_fresh(engine: object, settings: object, req: object, current: object) -> object:
        redrafted.append(req)
        return type("R", (), {"revision": object()})()

    monkeypatch.setattr("app.workflows.reattribute_cli.make_engine", lambda url: None)
    monkeypatch.setattr("app.workflows.reattribute_cli.reattribute", fake_reattribute)
    monkeypatch.setattr("app.workflows.reattribute_cli.redraft.fresh", fake_fresh)
    try:
        rc = main(
            [
                "--mailbox",
                "info@example.test",
                "--days",
                "90",
                "--sender",
                "harjotsj@gmail.com",
                "--apply",
                "--worker-stopped",
                "--redraft",
            ]
        )
    finally:
        get_settings.cache_clear()
    assert rc == 0
    assert seen == {"apply": True, "days": 90, "sender": "harjotsj@gmail.com"}
    assert len(redrafted) == 1
    assert "redrafted: 1" in capsys.readouterr().out
