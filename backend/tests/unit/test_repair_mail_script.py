"""`scripts/repair_mail.sh` against a stub `aws`: the order of steps, and the worker always coming back."""

import json
import os
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "repair_mail.sh"
BASH = shutil.which("bash") or "/bin/bash"
SHELLS = sorted({BASH, "/bin/bash"})  # macOS ships bash 3.2 as /bin/bash
STUB = r"""#!/usr/bin/env bash
echo "$*" >> "$STUB_LOG"
RUN=arn:aws:ecs:eu-north-1:1:task/estateos-prod-cluster/abc123
case "$*" in
  *"describe-services"*"taskDefinition"*) echo "arn:aws:ecs:eu-north-1:1:task-definition/estateos-prod-worker:10" ;;
  *"describe-services"*"networkConfiguration"*) echo '{"awsvpcConfiguration":{"subnets":["s1"]}}' ;;
  *"describe-services"*"desiredCount"*) echo "${STUB_DESIRED:-2}" ;;
  *"describe-task-definition"*"awslogs-group"*) echo "/ecs/estateos-prod-worker" ;;
  *"describe-task-definition"*"awslogs-stream-prefix"*) echo "worker" ;;
  *"describe-task-definition"*"name"*) echo "worker" ;;
  *"list-tasks"*"--service-name"*) echo "arn:aws:ecs:eu-north-1:1:task/estateos-prod-cluster/oldworker" ;;
  *"list-tasks"*"--started-by"*) if [ -f "$STUB_LOG.running" ]; then echo "$RUN"; else echo ""; fi ;;
  *"run-task"*) touch "$STUB_LOG.running"; echo "$RUN" ;;
  *"describe-tasks"*"lastStatus"*)
    if [ -n "$STUB_HANG" ] && [ ! -f "$STUB_LOG.release" ]; then
      echo RUNNING
    else
      rm -f "$STUB_LOG.running"
      echo STOPPED
    fi ;;
  *"describe-tasks"*"exitCode"*) echo "$STUB_EXIT" ;;
  *"stop-task"*)
    case "$*" in *"--task arn:"*) ;; *) exit 252 ;; esac
    [ -z "$STUB_NO_STOP" ] || exit 255; rm -f "$STUB_LOG.running" ;;
  *"filter-log-events"*) echo "REPORT LINE" ;;
  *"create-db-snapshot"*) [ -z "$STUB_NO_SNAPSHOT" ] || exit 255 ;;
  *"update-service"*"--desired-count 2"*) [ -z "$STUB_NO_RESTORE" ] || exit 255 ;;
esac
exit 0
"""


def _setup(tmp_path: Path, **stub_env: str) -> tuple[dict[str, str], Path]:
    stub = tmp_path / "aws"
    stub.write_text(STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    log.touch()
    env = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "STUB_LOG": str(log),
        "STUB_EXIT": "0",
        "REPAIR_POLL_SECONDS": "0",
        **stub_env,
    }
    return env, log


def run(tmp_path: Path, *args: str, answer: str = "", **stub_env: str) -> tuple[int, str, list[str]]:
    env, log = _setup(tmp_path, **stub_env)
    done = subprocess.run([BASH, str(SCRIPT), *args], input=answer, capture_output=True, text=True, env=env, timeout=60)
    return done.returncode, done.stdout + done.stderr, log.read_text().splitlines()


def _index(calls: list[str], needle: str) -> int:
    return next(i for i, call in enumerate(calls) if needle in call)


def _commands(calls: list[str]) -> list[list[str]]:
    runs = [c for c in calls if "run-task" in c]
    overrides = [json.loads(c.split("--overrides ", 1)[1].split(" --query", 1)[0]) for c in runs]
    return [o["containerOverrides"][0]["command"] for o in overrides]


def _restored(calls: list[str]) -> bool:
    return any("update-service" in c and "--desired-count 2" in c for c in calls)


def test_a_preview_only_reads(tmp_path: Path) -> None:
    code, out, calls = run(tmp_path, "prod", "preview")
    assert code == 0, out
    assert "REPORT LINE" in out
    [command] = _commands(calls)
    assert command[-2:] == ["--mailbox", "info@hrrealestate.nl"]
    assert not any("update-service" in c or "create-db-snapshot" in c for c in calls)


def test_apply_backs_up_a_quiet_database_then_labels_with_the_worker_back(tmp_path: Path) -> None:
    code, out, calls = run(tmp_path, "prod", "apply", answer="apply prod\n")
    assert code == 0, out
    repair, label = _commands(calls)
    assert repair[-2:] == ["--apply", "--worker-stopped"]
    assert label[-1] == "--label"
    first_run = _index(calls, "run-task")
    order = [
        _index(calls, "--desired-count 0"),
        next(i for i, c in enumerate(calls) if "wait tasks-stopped" in c and "oldworker" in c),
        _index(calls, "create-db-snapshot"),
        _index(calls, "wait db-snapshot-available"),
        first_run,
        _index(calls, "--desired-count 2"),
        next(i for i, c in enumerate(calls) if "run-task" in c and i > first_run),
    ]
    assert order == sorted(order)


def test_a_failed_repair_restores_the_worker_and_never_labels(tmp_path: Path) -> None:
    code, out, calls = run(tmp_path, "prod", "apply", answer="apply prod\n", STUB_EXIT="1")
    assert code != 0, out
    assert _restored(calls)
    assert len(_commands(calls)) == 1
    assert "APPLIED" in out  # told to look for it before restoring any snapshot


def test_no_backup_means_no_run_and_the_worker_comes_back(tmp_path: Path) -> None:
    code, _, calls = run(tmp_path, "prod", "apply", answer="apply prod\n", STUB_NO_SNAPSHOT="1")
    assert code != 0
    assert _commands(calls) == []
    assert _restored(calls)


def _interrupt(tmp_path: Path, **stub_env: str) -> tuple[int, str, list[str]]:
    """Starts an apply whose task never finishes, then terminates the script."""
    env, log = _setup(tmp_path, STUB_HANG="1", **stub_env)
    proc = subprocess.Popen(
        [BASH, str(SCRIPT), "prod", "apply"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, env=env,
    )  # fmt: skip
    assert proc.stdin is not None
    proc.stdin.write("apply prod\n")
    proc.stdin.close()
    deadline = time.monotonic() + 30
    while "lastStatus" not in log.read_text() and time.monotonic() < deadline:
        time.sleep(0.05)
    proc.send_signal(signal.SIGTERM)
    assert proc.stdout is not None
    out = proc.stdout.read()
    return proc.wait(timeout=30), out, log.read_text().splitlines()


def test_an_interrupted_apply_stops_the_task_before_the_worker_returns(tmp_path: Path) -> None:
    code, out, calls = _interrupt(tmp_path)
    assert code != 0, out
    stopped = next(i for i, c in enumerate(calls) if "wait tasks-stopped" in c and "abc123" in c)
    assert _index(calls, "stop-task") < stopped < _index(calls, "--desired-count 2")


def test_the_worker_stays_stopped_when_the_task_cannot_be_stopped(tmp_path: Path) -> None:
    code, out, calls = _interrupt(tmp_path, STUB_NO_STOP="1")
    assert code != 0
    assert not _restored(calls)
    assert "LEFT STOPPED" in out


@pytest.mark.parametrize("shell", SHELLS)
def test_the_worker_is_restored_when_the_output_closes_during_the_repair(tmp_path: Path, shell: str) -> None:
    """The reader goes away (a closed terminal, `| head`) with no signal, while the repair task is running."""
    env, log = _setup(tmp_path, STUB_HANG="1", REPAIR_POLL_SECONDS="1")
    proc = subprocess.Popen(
        [shell, str(SCRIPT), "prod", "apply"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, env=env,
    )  # fmt: skip
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write("apply prod\n")
    proc.stdin.close()
    deadline = time.monotonic() + 30
    while "lastStatus" not in log.read_text() and time.monotonic() < deadline:
        time.sleep(0.05)
    proc.stdout.close()  # every later write fails
    Path(f"{log}.release").touch()  # now the task finishes
    proc.wait(timeout=60)
    calls = log.read_text().splitlines()
    assert _restored(calls), calls[-8:]


def test_a_failed_restore_is_retried_and_fails_the_run(tmp_path: Path) -> None:
    code, out, calls = run(tmp_path, "prod", "apply", answer="apply prod\n", STUB_NO_RESTORE="1")
    assert code != 0
    assert sum("--desired-count 2" in c for c in calls) >= 3
    assert "COULD NOT RESTORE" in out


def test_apply_is_refused_when_the_worker_is_already_stopped(tmp_path: Path) -> None:
    code, _, calls = run(tmp_path, "prod", "apply", answer="apply prod\n", STUB_DESIRED="0")
    assert code != 0
    assert not any("update-service" in c or "create-db-snapshot" in c or "run-task" in c for c in calls)


def test_the_label_step_runs_alone_and_leaves_the_worker_alone(tmp_path: Path) -> None:
    code, out, calls = run(tmp_path, "prod", "label", STUB_EXIT="2")
    assert code == 2, out
    [command] = _commands(calls)
    assert command[-1] == "--label"
    assert not any("update-service" in c or "create-db-snapshot" in c for c in calls)


@pytest.mark.parametrize("answer", ["", "yes\n", "apply stage\n"])
def test_applying_needs_the_exact_confirmation(tmp_path: Path, answer: str) -> None:
    code, _, calls = run(tmp_path, "prod", "apply", answer=answer)
    assert code != 0
    assert not any("create-db-snapshot" in c or "run-task" in c or "update-service" in c for c in calls)


@pytest.mark.parametrize("args", [(), ("dev", "preview"), ("prod", "delete"), ("prod", "preview", "a b@x.nl")])
def test_bad_arguments_do_nothing(tmp_path: Path, args: tuple[str, ...]) -> None:
    code, _, calls = run(tmp_path, *args)
    assert code != 0
    assert calls == []
