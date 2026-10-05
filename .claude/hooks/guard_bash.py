#!/usr/bin/env python3
"""PreToolUse(Bash) guard for EstateOS.

Blocks: git writes outside the EstateOS repo (parent is a home-dir repo), force pushes, hook bypass,
reading secret files, live calls to WhatsApp/Gmail/OpenAI from the shell, destructive rm.
Asks: hard resets, volume wipes, alembic downgrade, raw SQL DROP/TRUNCATE, dependency changes.
Fails open (exit 0) on internal error so a hook bug never bricks the session.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import PROJECT_DIR, git, pre_tool_decision, read_input  # noqa: E402

GIT_WRITE = re.compile(
    r"\bgit\s+(?:-C\s+\S+\s+)?(add|commit|push|reset|checkout|switch|restore|stash|clean|rebase|merge|cherry-pick|tag|rm|mv|am|apply)\b"
)

DENY: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bgit\s+push\b.*(\s--force(?!-with-lease)\b|\s-f\b)"),
        "Force push is blocked. Use --force-with-lease on a feature branch if truly needed, and ask the user first.",
    ),
    (
        re.compile(r"\bgit\b[^|;&\n]*\s--no-verify\b|\bgit\s+commit\b[^|;&\n]*\s-[a-zA-Z]*n[a-zA-Z]*\b"),
        "Bypassing git hooks (--no-verify / -n) is blocked. Fix the failing check instead.",
    ),
    (
        re.compile(r"(^|[\s;&|])(cat|less|more|head|tail|bat|grep|rg|sed|awk|source|\.)\s+[^|;&]*\.env(\.(?!example\b)\w+)?(\s|$)"),
        "Reading .env files is blocked — they hold live credentials. Use .env.example for shape; ask the user for values.",
    ),
    (
        re.compile(r"\b(curl|wget|http|httpx|xh)\b[^|;&]*(graph\.facebook\.com|gmail\.googleapis\.com|api\.openai\.com|pubsub\.googleapis\.com)"),
        "Live calls to Meta/Gmail/OpenAI/PubSub from the shell are blocked. Use recorded fixtures (tests/fixtures/) and adapters.",
    ),
    (
        re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?[a-zA-Z]*\s+(/|~|\$HOME|\.\.?/?)(\s|$)"),
        "Recursive delete of /, ~, . or .. is blocked.",
    ),
    (
        re.compile(r"\b(python3?|uv\s+run\s+python)\b.*\b(SenderSettings|send_message|create_draft)\b"),
        "Ad-hoc scripts that exercise send paths are blocked. Sending is tested only through app/sender with fakes.",
    ),
]

ASK: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "git reset --hard discards work."),
    (re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"), "git clean -f deletes untracked files."),
    (re.compile(r"\bgit\s+push\b"), "Pushing publishes commits to a remote."),
    (re.compile(r"\bdocker\s+compose\b.*\bdown\b.*\s-v\b|\bdocker\s+volume\s+(rm|prune)\b"), "This wipes the Postgres volume."),
    (re.compile(r"\balembic\b.*\bdowngrade\b"), "alembic downgrade drops schema objects."),
    (re.compile(r"\b(DROP\s+(TABLE|DATABASE|SCHEMA)|TRUNCATE)\b", re.IGNORECASE), "Destructive SQL."),
    (re.compile(r"\buv\s+(add|remove)\b|\bpip\s+install\b"), "Dependency change — confirm the package and version."),
]


def outside_repo_git_write(command: str, cwd: str | None) -> str | None:
    if not GIT_WRITE.search(command):
        return None
    m = re.search(r"\bgit\s+-C\s+(\S+)", command)
    target = Path(m.group(1)).expanduser() if m else Path(cwd or PROJECT_DIR)
    if not target.is_absolute():
        target = Path(cwd or PROJECT_DIR) / target
    cd = re.search(r"(?:^|[;&|]\s*)cd\s+(\S+)", command)
    if cd:
        dest = Path(cd.group(1)).expanduser()
        target = dest if dest.is_absolute() else target / dest
    try:
        top = git("rev-parse", "--show-toplevel", cwd=target.resolve()).stdout.strip()
    except (OSError, ValueError):
        return None
    if top and Path(top).resolve() != PROJECT_DIR:
        return (
            f"git write blocked: target repo is {top}, not EstateOS ({PROJECT_DIR}). "
            "The parent home-directory repo must never receive EstateOS changes."
        )
    return None


def main() -> None:
    data = read_input()
    command = str(data.get("tool_input", {}).get("command", ""))
    if not command:
        return
    for pattern, reason in DENY:
        if pattern.search(command):
            pre_tool_decision("deny", reason)
    reason = outside_repo_git_write(command, data.get("cwd"))
    if reason:
        pre_tool_decision("deny", reason)
    for pattern, reason in ASK:
        if pattern.search(command):
            pre_tool_decision("ask", f"EstateOS guard: {reason}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # fail open
        print(f"guard_bash internal error (allowed): {exc}", file=sys.stderr)
    sys.exit(0)
