#!/usr/bin/env python3
"""SessionStart — inject a compact project status brief into context (stdout becomes context)."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import PROJECT_DIR, git, has_python_toolchain  # noqa: E402


def current_milestone() -> str:
    progress = PROJECT_DIR / "docs" / "PROGRESS.md"
    if not progress.exists():
        return "unknown (docs/PROGRESS.md missing)"
    heading = None
    for line in progress.read_text().splitlines():
        m = re.match(r"^##\s+(M\d+.*)$", line)
        if m:
            heading = m.group(1)
        if heading and re.match(r"^\s*-\s+\[ \]", line):
            return f"{heading} — next: {line.strip()[6:]}"
    return "all milestones checked"


def docker_state() -> str:
    if not shutil.which("docker"):
        return "docker CLI missing"
    try:
        r = subprocess.run(
            ["docker", "compose", "-f", "docker/compose.yml", "ps", "--format", "{{.Service}}:{{.State}}"],
            cwd=PROJECT_DIR, capture_output=True, text=True, timeout=5, check=False,
        )
    except subprocess.TimeoutExpired:
        return "docker unresponsive (see memory: Docker Desktop zombie backend)"
    if r.returncode != 0:
        return "compose stack not available"
    return ", ".join(r.stdout.split()) or "compose stack down"


def main() -> None:
    branch = git("branch", "--show-current").stdout.strip() or "(detached)"
    dirty = len([line for line in git("status", "--porcelain").stdout.splitlines() if line.strip()])
    last = git("log", "--oneline", "-3").stdout.strip() or "(no commits)"
    lines = [
        "## EstateOS session brief",
        f"- Milestone: {current_milestone()}",
        f"- Branch: {branch} · uncommitted files: {dirty}",
        f"- Toolchain: {'ready (.venv)' if has_python_toolchain() else 'not set up — run `make setup` once pyproject exists'}",
        f"- Stack: {docker_state()}",
        "- Last commits:",
        *[f"    {c}" for c in last.splitlines()],
        "- Rules: CLAUDE.md. Verify with /check before claiming done. Review with estateos-reviewer before commit.",
    ]
    print("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"(session_start brief unavailable: {exc})")
    sys.exit(0)
