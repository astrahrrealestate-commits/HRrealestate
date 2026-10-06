#!/usr/bin/env python3
"""PreToolUse(Edit|Write|MultiEdit|NotebookEdit) guard for EstateOS.

Path rules (inside the project only):
  - .env files (except .env.example) are never written.
  - Committed Alembic migrations are immutable — write a new revision.
  - Committed prompt files under app/llm/prompts/<version>/ are immutable — create a new version dir.
  - Committed recorded fixtures under tests/fixtures/recorded/ are immutable — add a new file.
Content rules:
  - Send credentials / outbound adapters referenced outside app/sender/ (and tests) are blocked.
  - Hard-coded secrets (OpenAI, Meta, Google keys, private keys) are blocked anywhere.
Fails open on internal error.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import PROJECT_DIR, is_tracked, pre_tool_decision, read_input, rel  # noqa: E402

ENV_FILE = re.compile(r"(^|/)\.env(\.(?!example$)[\w.-]+)?$")
MIGRATION = re.compile(r"^app/db/alembic/versions/.+\.py$")
PROMPT = re.compile(r"^app/llm/prompts/v\d+/.+")
FIXTURE = re.compile(r"^tests/fixtures/recorded/.+")

SEND_ONLY = re.compile(
    r"\bSenderSettings\b"
    r"|\bapp\.sender\.settings\b"
    r"|\bfrom\s+app\.sender\s+import\s+settings\b"
    r"|\bapp\.channels\.\w+\.(outbound|drafts)\b"
    r"|\bfrom\s+app\.channels\.\w+\s+import\s+(outbound|drafts)\b"
    r"|\bapp\.sender\.whatsapp\b"
    r"|\b(WHATSAPP_ACCESS_TOKEN|WA_ACCESS_TOKEN|GMAIL_SEND_\w+)\b"
)
SEND_ALLOWED = re.compile(r"^(app/sender/|tests/|\.claude/|docs/|CLAUDE\.md$|\.env\.example$)")
MEDIA_CREDS = re.compile(r"\bmedia_settings\b|\bWhatsAppMediaSettings\b|\bWHATSAPP_MEDIA_TOKENS?\b|\bwhatsapp_media_tokens?\b")
MEDIA_ALLOWED = re.compile(
    r"^(app/channels/registry\.py|app/channels/whatsapp/media_settings\.py|tests/|\.claude/|docs/|\.env\.example$)"
)

RETIRED_STACK = re.compile(r"^\s*(from|import)\s+(celery|redis|kombu|rq)\b", re.MULTILINE)
SKIP_TEST = re.compile(r"pytest\.mark\.(skip|skipif|xfail)\b|pytest\.(skip|xfail)\(")

SECRETS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsk-(proj-)?[A-Za-z0-9_-]{24,}"), "OpenAI API key"),
    (re.compile(r"\bEAA[A-Za-z0-9]{60,}"), "Meta access token"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "Google API key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"\bsk-lf-[0-9a-f-]{30,}"), "Langfuse secret key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
]


def new_content(tool_input: dict[str, object]) -> str:
    parts: list[str] = []
    for key in ("content", "new_string", "new_source"):
        v = tool_input.get(key)
        if isinstance(v, str):
            parts.append(v)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for e in edits:
            if isinstance(e, dict) and isinstance(e.get("new_string"), str):
                parts.append(e["new_string"])
    return "\n".join(parts)


def main() -> None:
    data = read_input()
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(path, str):
        return
    relpath = rel(path)
    if relpath is None:
        return  # outside project (memory dir, scratchpad) — not our concern

    if ENV_FILE.search(relpath):
        pre_tool_decision("deny", f"{relpath}: .env files hold live credentials. Edit .env.example instead.")

    if (PROJECT_DIR / relpath).exists() and is_tracked(relpath):
        if MIGRATION.match(relpath):
            pre_tool_decision(
                "deny",
                f"{relpath} is a committed migration — immutable. Create a new revision: "
                "`make migration m=\"<msg>\"` (see /new-migration skill).",
            )
        if PROMPT.match(relpath):
            pre_tool_decision(
                "deny",
                f"{relpath} is a published prompt — immutable (model_calls rows reference its sha256). "
                "Copy to the next version dir (see /new-prompt-version skill).",
            )
        if FIXTURE.match(relpath):
            pre_tool_decision(
                "deny",
                f"{relpath} is a committed recorded payload — immutable. Add a new fixture file instead.",
            )

    content = new_content(tool_input)
    if not content:
        return

    if relpath.endswith(".py") and not SEND_ALLOWED.match(relpath):
        m = SEND_ONLY.search(content)
        if m:
            pre_tool_decision(
                "deny",
                f"`{m.group(0)}` referenced in {relpath}. Only app/sender/ may touch send credentials or outbound "
                "adapters. Other modules create Action/approval rows; the sender acts on them.",
            )

    if relpath.endswith(".py") and not MEDIA_ALLOWED.match(relpath) and MEDIA_CREDS.search(content):
        pre_tool_decision(
            "deny",
            f"WhatsApp media credentials referenced in {relpath}. Only app/channels/registry.py may read them "
            "(they can send messages; ADR 0003 amendment).",
        )

    if relpath.endswith(".py") and RETIRED_STACK.search(content):
        pre_tool_decision(
            "deny",
            f"Celery/Redis import in {relpath}. Stack uses DBOS for queues, cron and retries (docs/adr/0001). "
            "Use @DBOS.workflow/@DBOS.step/Queue/@DBOS.scheduled instead.",
        )

    if relpath.startswith("tests/") and SKIP_TEST.search(content):
        pre_tool_decision(
            "ask",
            f"{relpath} adds skip/xfail. Pipeline rule: never skip a test to get green. Approve only for a "
            "documented external reason (e.g. Docker unavailable marker).",
        )

    for pattern, label in SECRETS:
        if pattern.search(content):
            pre_tool_decision(
                "deny",
                f"Looks like a hard-coded {label} in {relpath}. Secrets come from env via pydantic-settings only.",
            )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # fail open
        print(f"guard_edit internal error (allowed): {exc}", file=sys.stderr)
    sys.exit(0)
