"""`scripts/mail_reload.sh` against a stub `aws`: what each mode runs, and the worker coming back from a purge."""

import signal
import subprocess
import time
from pathlib import Path

import pytest

from tests.unit.test_repair_mail_script import BASH, SHELLS, _commands, _index, _restored, _setup

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "mail_reload.sh"
BOX = "info@hrrealestate.nl"
CONFIRM = f"purge prod {BOX}\n"


def run(tmp_path: Path, *args: str, answer: str = "", shell: str = BASH, **stub_env: str) -> tuple[int, str, list[str]]:
    env, log = _setup(tmp_path, RELOAD_POLL_SECONDS="0", **stub_env)
    done = subprocess.run(
        [shell, str(SCRIPT), *args], input=answer, capture_output=True, text=True, env=env, timeout=60
    )
    return done.returncode, done.stdout + done.stderr, log.read_text().splitlines()


def _writes(calls: list[str]) -> list[str]:
    return [c for c in calls if "update-service" in c or "create-db-snapshot" in c]


@pytest.mark.parametrize("shell", SHELLS)
def test_preview_only_reads(tmp_path: Path, shell: str) -> None:
    code, out, calls = run(tmp_path, "prod", "preview", shell=shell)
    assert code == 0, out
    assert "REPORT LINE" in out
    assert _commands(calls) == [["python", "-m", "app.workflows.mail_reload_cli", "--mailbox", BOX, "--preview"]]
    assert _writes(calls) == []


@pytest.mark.parametrize("shell", SHELLS)
def test_purge_stops_the_worker_snapshots_runs_and_restores(tmp_path: Path, shell: str) -> None:
    code, out, calls = run(tmp_path, "prod", "purge", answer=CONFIRM, shell=shell)
    assert code == 0, out
    [command] = _commands(calls)
    assert command[-4:] == ["--purge", "--worker-stopped", "--confirm", f"purge {BOX}"]
    order = [
        _index(calls, "--desired-count 0"),
        next(i for i, c in enumerate(calls) if "wait tasks-stopped" in c and "oldworker" in c),
        _index(calls, "create-db-snapshot"),
        _index(calls, "wait db-snapshot-available"),
        _index(calls, "run-task"),
        _index(calls, "--desired-count 2"),
    ]
    assert order == sorted(order)


@pytest.mark.parametrize("answer", ["", "yes\n", f"purge {BOX}\n", "purge prod\n", f"purge stage {BOX}\n"])
def test_purge_needs_the_environment_and_the_mailbox_typed(tmp_path: Path, answer: str) -> None:
    code, _, calls = run(tmp_path, "prod", "purge", answer=answer)
    assert code != 0
    assert _commands(calls) == []
    assert _writes(calls) == []


def test_purge_is_refused_when_the_worker_is_already_stopped(tmp_path: Path) -> None:
    code, _, calls = run(tmp_path, "prod", "purge", answer=CONFIRM, STUB_DESIRED="0")
    assert code != 0
    assert _commands(calls) == []
    assert _writes(calls) == []


def test_no_snapshot_means_no_purge_and_the_worker_comes_back(tmp_path: Path) -> None:
    code, _, calls = run(tmp_path, "prod", "purge", answer=CONFIRM, STUB_NO_SNAPSHOT="1")
    assert code != 0
    assert _commands(calls) == []
    assert _restored(calls)


def test_a_failed_purge_restores_the_worker(tmp_path: Path) -> None:
    code, out, calls = run(tmp_path, "prod", "purge", answer=CONFIRM, STUB_EXIT="1")
    assert code != 0, out
    assert _restored(calls)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("reingest",), ["--reingest", "--days", "90"]),
        (("reingest", BOX, "7"), ["--reingest", "--days", "7"]),
        (("run-history",), ["--run-history"]),
        (("settle",), ["--settle"]),
        (("settle", BOX, "21"), ["--settle", "--idle-days", "21"]),
        (("draft-report",), ["--draft-report", "--days", "30"]),
        (("draft-report", BOX, "60"), ["--draft-report", "--days", "60"]),
        (("status",), ["--status"]),
    ],
)
def test_every_other_mode_leaves_the_worker_running(tmp_path: Path, args: tuple[str, ...], expected: list[str]) -> None:
    code, out, calls = run(tmp_path, "prod", *args)
    assert code == 0, out
    [command] = _commands(calls)
    assert command[5:] == expected
    assert _writes(calls) == []


def test_draft_open_runs_dry_first_and_asks_before_the_real_run(tmp_path: Path) -> None:
    code, out, calls = run(tmp_path, "prod", "draft-open", BOX, "10", answer="draft prod\n")
    assert code == 0, out
    dry, real = _commands(calls)
    assert dry[5:] == ["--draft-open", "--max-age-days", "10", "--dry-run"]
    assert real[5:] == ["--draft-open", "--max-age-days", "10"]
    assert _writes(calls) == []


@pytest.mark.parametrize("answer", ["", "yes\n", "draft stage\n"])
def test_draft_open_stops_after_the_dry_run_without_the_typed_answer(tmp_path: Path, answer: str) -> None:
    code, _, calls = run(tmp_path, "prod", "draft-open", answer=answer)
    assert code != 0
    [only] = _commands(calls)
    assert only[-1] == "--dry-run"


def test_a_failed_dry_run_never_drafts(tmp_path: Path) -> None:
    code, _, calls = run(tmp_path, "prod", "draft-open", answer="draft prod\n", STUB_EXIT="1")
    assert code != 0
    assert len(_commands(calls)) == 1


def _interrupt(tmp_path: Path, **stub_env: str) -> tuple[int, str, list[str]]:
    """Starts a purge whose task never finishes, then terminates the script."""
    env, log = _setup(tmp_path, STUB_HANG="1", RELOAD_POLL_SECONDS="0", **stub_env)
    proc = subprocess.Popen(
        [BASH, str(SCRIPT), "prod", "purge"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, env=env,
    )  # fmt: skip
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(CONFIRM)
    proc.stdin.close()
    deadline = time.monotonic() + 30
    while "lastStatus" not in log.read_text() and time.monotonic() < deadline:
        time.sleep(0.05)
    proc.send_signal(signal.SIGTERM)
    out = proc.stdout.read()
    return proc.wait(timeout=30), out, log.read_text().splitlines()


def test_an_interrupted_purge_stops_its_task_before_the_worker_returns(tmp_path: Path) -> None:
    code, out, calls = _interrupt(tmp_path)
    assert code != 0, out
    stopped = next(i for i, c in enumerate(calls) if "wait tasks-stopped" in c and "abc123" in c)
    assert _index(calls, "stop-task") < stopped < _index(calls, "--desired-count 2")


def test_the_worker_stays_stopped_when_the_purge_task_cannot_be_stopped(tmp_path: Path) -> None:
    code, out, calls = _interrupt(tmp_path, STUB_NO_STOP="1")
    assert code != 0
    assert not _restored(calls)
    assert "LEFT STOPPED" in out


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("dev", "preview"),
        ("prod", "delete"),
        ("prod", "preview", "a b@x.nl"),
        ("prod", "reingest", BOX, "many"),
        ("prod", "reingest", BOX, "0"),
        ("prod", "purge", BOX, "90"),
        ("prod", "status", BOX, "7"),
        ("prod", "draft-open", BOX, "14", "--dry-run"),
    ],
)
def test_bad_arguments_do_nothing(tmp_path: Path, args: tuple[str, ...]) -> None:
    code, _, calls = run(tmp_path, *args)
    assert code != 0
    assert calls == []
