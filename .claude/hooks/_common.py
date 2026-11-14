"""Shared helpers for EstateOS Claude Code hooks. Stdlib only — hooks must run before `uv sync`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2]).resolve()
BACKEND_DIR = PROJECT_DIR / "backend"
VENV_BIN = BACKEND_DIR / ".venv" / "bin"


def read_input() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def emit(obj: dict[str, Any]) -> NoReturn:
    print(json.dumps(obj))
    sys.exit(0)


def pre_tool_decision(decision: str, reason: str) -> NoReturn:
    """decision: 'deny' | 'ask' | 'allow'. Reason is shown to Claude (deny) or user (ask)."""
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        }
    )


def rel(path: str | os.PathLike[str]) -> str | None:
    """Project-relative POSIX path, or None if outside the project."""
    try:
        p = Path(path)
        if not p.is_absolute():
            p = PROJECT_DIR / p
        return p.resolve().relative_to(PROJECT_DIR).as_posix()
    except (ValueError, OSError):
        return None


def git(*args: str, cwd: Path | None = None, timeout: float = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd or PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def is_tracked(relpath: str) -> bool:
    r = git("ls-files", "--error-unmatch", "--", relpath)
    return r.returncode == 0


def has_python_toolchain() -> bool:
    return (BACKEND_DIR / "pyproject.toml").exists() and (VENV_BIN / "python").exists()


def tail(text: str, lines: int = 40) -> str:
    parts = text.strip().splitlines()
    return "\n".join(parts[-lines:])
