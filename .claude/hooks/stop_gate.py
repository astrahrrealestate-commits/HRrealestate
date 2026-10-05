#!/usr/bin/env python3
"""Stop hook — quality gate before Claude ends a turn.

If Python files changed (vs HEAD, incl. untracked) and the toolchain exists, run the fast tier:
ruff check → mypy → pytest tests/unit. On failure, block the stop and hand the tail of the output back to Claude.

Speed: result is cached by a hash of the working-tree diff, so an unchanged tree is never re-checked.
Loop safety: when `stop_hook_active` is set (Claude already continued once because of this hook), only report.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import PROJECT_DIR, VENV_BIN, emit, git, has_python_toolchain, read_input, tail  # noqa: E402

CACHE = PROJECT_DIR / ".claude" / ".cache" / "stop_gate_green"
CODE_DIRS = ("app", "workers", "evals", "tests")


def changed_py() -> list[str]:
    out = git("status", "--porcelain", "--untracked-files=all").stdout
    files = []
    for line in out.splitlines():
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if path.endswith(".py") and path.split("/", 1)[0] in CODE_DIRS:
            files.append(path)
    return files


def tree_fingerprint(files: list[str]) -> str:
    h = hashlib.sha256()
    for f in sorted(files):
        p = PROJECT_DIR / f
        h.update(f.encode())
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()


def run(label: str, args: list[str], timeout: int) -> tuple[bool, str]:
    try:
        r = subprocess.run(args, cwd=PROJECT_DIR, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return False, f"[{label}] timed out after {timeout}s"
    return r.returncode == 0, f"[{label}]\n{tail(r.stdout + r.stderr, 40)}"


def main() -> None:
    data = read_input()
    if not has_python_toolchain():
        return
    files = changed_py()
    if not files:
        return
    fp = tree_fingerprint(files)
    if CACHE.exists() and CACHE.read_text().strip() == fp:
        return

    py = str(VENV_BIN / "python")
    existing_dirs = [d for d in ("app", "workers", "evals") if (PROJECT_DIR / d).is_dir()]
    steps: list[tuple[str, list[str], int]] = [
        ("ruff", [py, "-m", "ruff", "check", *existing_dirs, "tests"], 60),
    ]
    if existing_dirs:
        steps.append(("mypy", [py, "-m", "mypy", *existing_dirs], 180))
    if (PROJECT_DIR / "tests" / "unit").is_dir():
        steps.append(("pytest unit", [py, "-m", "pytest", "tests/unit", "-x", "-q", "--no-header", "-p", "no:randomly"], 180))

    for label, args, timeout in steps:
        ok, output = run(label, args, timeout)
        if not ok:
            if data.get("stop_hook_active"):
                emit({"systemMessage": f"EstateOS stop gate still failing on {label} — left for the user to see."})
            emit(
                {
                    "decision": "block",
                    "reason": f"Stop gate failed on {label}. Fix before finishing (or explain why it cannot be fixed):\n{output}",
                }
            )

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(fp)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"stop_gate internal error: {exc}", file=sys.stderr)
    sys.exit(0)
