#!/usr/bin/env python3
"""PostToolUse(Edit|Write|MultiEdit) — format + autofix the touched .py file, feed leftover lint back to Claude.

Fast path: runs ruff from .venv directly on one file (~50 ms). No-op until the toolchain exists.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import PROJECT_DIR, VENV_BIN, emit, has_python_toolchain, read_input, rel, tail  # noqa: E402


def main() -> None:
    data = read_input()
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path")
    if not isinstance(path, str) or not path.endswith(".py"):
        return
    relpath = rel(path)
    if relpath is None or relpath.startswith(".claude/") or not has_python_toolchain():
        return
    ruff = VENV_BIN / "ruff"
    if not ruff.exists():
        return

    run = lambda *a: subprocess.run(  # noqa: E731
        [str(ruff), *a, relpath], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=30, check=False
    )
    run("format", "--quiet")
    run("check", "--fix", "--quiet")
    result = run("check", "--output-format", "concise")
    if result.returncode != 0:
        emit(
            {
                "decision": "block",
                "reason": f"ruff still reports issues in {relpath} after autofix — fix them now:\n"
                + tail(result.stdout + result.stderr, 30),
            }
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never break the edit loop
        print(f"post_edit internal error: {exc}", file=sys.stderr)
    sys.exit(0)
