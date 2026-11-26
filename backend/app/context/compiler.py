"""Context compiler implementation (spec: 2026-10-23-agent-memory-context-design §7, Task C2).

Assembles budgeted, escaped prompt blocks for agents. For concierge, byte-identical prompt guarantees are preserved.
"""

import hashlib
from collections.abc import Sequence

from app.context.budget import fit_to_budget
from app.context.selection import render_case_lines
from app.context.spec import (
    BRIEFING_SPEC,
    CASE_SUMMARY_SPEC,
    LINK_CHECK_SPEC,
    OWNER_QA_SPEC,
    UNDERSTANDING_SPEC,
    CompiledContext,
    ContextSpec,
)
from app.context.spec import (
    CONCIERGE_SPEC as CONCIERGE_SPEC,
)
from app.llm.agents.owner_qa import CaseBrief
from app.llm.page_blocks import page_blocks
from app.llm.render import data_block, escape

MAX_HISTORY = 24  # lines: `owner:` and `assistant:` for each of 12 turns
MAX_HISTORY_LINE = 1220  # an `owner: ` prefix plus 1,200 characters
SUMMARY_PREFIX = "Summary of earlier conversation: "
HISTORY_CHARS = 12000  # the history slice of CONCIERGE_SPEC


def _newest_first_fit(lines: list[str], budget: int = HISTORY_CHARS) -> list[str]:
    """The newest lines that fit the history budget, oldest first: a follow-up needs the last turns most."""
    kept: list[str] = []
    used = 0
    for line in reversed(lines):
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1
    return kept[::-1]


def _turns(recent: Sequence[str], named: bool) -> tuple[str, list[str]]:
    """The conversation summary (its own block for a prompt that names one) and the capped history lines."""
    if not named:
        return "", _newest_first_fit([" ".join(r.split())[:MAX_HISTORY_LINE] for r in recent[-MAX_HISTORY:]])
    summaries = [r.removeprefix(SUMMARY_PREFIX) for r in recent if r.startswith(SUMMARY_PREFIX)]
    turns = [r for r in recent if not r.startswith(SUMMARY_PREFIX)]
    lines = _newest_first_fit([" ".join(r.split())[:MAX_HISTORY_LINE] for r in turns[-MAX_HISTORY:]])
    return " ".join(" ".join(summaries).split()), lines


def compile_concierge_context(
    question: str,
    recent: Sequence[str],
    cases: Sequence[CaseBrief],
    open_tasks: Sequence[str],
    page_facts_text: str = "",
    snapshot: str = "",
    filters: str = "",
    owner_preferences: Sequence[str] = (),
    spec: ContextSpec = CONCIERGE_SPEC,
    entities: str = "",
    named_blocks: bool = False,
) -> CompiledContext:
    """Compile concierge context blocks, each slice fitted to the spec's budgets.

    The first DETAIL_CASES cases carry a summary and the rest are index lines, so pass them most relevant first
    (`selection.rank_cases`). `named_blocks` (concierge/v10+): the matched `entities` and the conversation summary
    get blocks of their own; an older prompt never sees blocks it does not know. When the prompt is under budget, there
    are at most DETAIL_CASES cases, no named blocks and owner_preferences is empty, prompt_text is byte-identical to
    concierge_prompt.
    """
    conversation, history = _turns(recent, named_blocks)
    fitted, dropped = fit_to_budget(
        spec,
        {
            "data": "\n".join([*render_case_lines(cases), *(f"task: {t}" for t in open_tasks)])
            or "no open cases or tasks",
            "entities": entities if named_blocks else "",
            "conversation": conversation,
            "history": "\n".join(history) or "no earlier messages",
            "page_facts": page_facts_text,
            "page_snapshot": snapshot,
            "page_filters": filters,
            "message": question,
        },
    )
    if history and len(fitted["history"]) < len("\n".join(history)):  # the total budget trimmed it: keep the newest
        fitted["history"] = "\n".join(_newest_first_fit(history, len(fitted["history"])))
    return _compiled(fitted, owner_preferences, dropped)


def _compiled(fitted: dict[str, str], owner_preferences: Sequence[str], dropped: tuple[str, ...]) -> CompiledContext:
    data_b = data_block("data", fitted["data"])
    pref_b = (
        [data_block("owner_preferences", "\n".join(f"- {p}" for p in owner_preferences))] if owner_preferences else []
    )
    named = [data_block(tag, fitted[tag]) for tag in ("entities", "conversation") if fitted[tag].strip()]
    history_b = data_block("history", fitted["history"], HISTORY_CHARS)
    page_bs = page_blocks(fitted["page_facts"], fitted["page_snapshot"], fitted["page_filters"])
    message_b = data_block("message", fitted["message"])
    blocks = (data_b, *pref_b, *named, history_b, *page_bs, message_b)
    # Prefix hash covers stable parts (stability <= 2: data_block and owner preferences)
    prefix_seed = f"{data_b}\n{pref_b[0]}" if pref_b else data_b
    prefix_hash = hashlib.sha256(prefix_seed.encode("utf-8")).hexdigest()
    return CompiledContext(blocks=blocks, prefix_hash=prefix_hash, aliases={}, dropped=dropped)


def compile_owner_qa_context(
    question: str,
    cases: Sequence[CaseBrief],
    open_tasks: Sequence[str],
    page_facts_text: str = "",
    *,
    company_constants: str = "",
    spec: ContextSpec = OWNER_QA_SPEC,
) -> CompiledContext:
    """Compile owner QA fallback context (spec §7.4)."""
    lines = [f"{c.case_id} | {c.label} | {c.state} | {c.urgency}" for c in cases]
    tasks = [f"task: {t}" for t in open_tasks]
    brief_content = "\n".join([*lines, *tasks]) or "no open cases or tasks"

    blocks: list[str] = []
    if company_constants.strip():
        blocks.append(data_block("company_constants", company_constants.strip()))
    blocks.append(data_block("brief", brief_content))
    if page_facts_text.strip():
        blocks.append(data_block("page_facts", page_facts_text.strip()))
    blocks.append(data_block("message", question))

    prefix_seed = blocks[0] if blocks else ""
    prefix_hash = hashlib.sha256(prefix_seed.encode("utf-8")).hexdigest()

    return CompiledContext(
        blocks=tuple(blocks),
        prefix_hash=prefix_hash,
        aliases={},
        dropped=(),
    )


def compile_understanding_context(
    message_text: str,
    *,
    glossary: str = "",
    attachment_metadata: str = "",
    spec: ContextSpec = UNDERSTANDING_SPEC,
) -> CompiledContext:
    """Compile understanding context without memory (spec §7.4)."""
    blocks: list[str] = []
    if glossary.strip():
        blocks.append(data_block("glossary", glossary.strip()))
    blocks.append(data_block("message", message_text))
    if attachment_metadata.strip():
        blocks.append(data_block("attachments", attachment_metadata.strip()))

    prefix_seed = blocks[0] if glossary.strip() else ""
    prefix_hash = hashlib.sha256(prefix_seed.encode("utf-8")).hexdigest()

    return CompiledContext(
        blocks=tuple(blocks),
        prefix_hash=prefix_hash,
        aliases={},
        dropped=(),
    )


def compile_link_check_context(
    message_text: str,
    category_value: str,
    candidate_lines: Sequence[str],
    *,
    person_profile_line: str | None = None,
    spec: ContextSpec = LINK_CHECK_SPEC,
) -> CompiledContext:
    """Compile link check context (spec §7.4)."""
    lines = list(candidate_lines)
    if person_profile_line:
        lines.insert(0, escape(person_profile_line, "data"))
    listing = "\n".join(lines)

    header = f"Message category: {category_value}"
    data_b = data_block("data", listing)
    msg_b = data_block("message", message_text)
    blocks = (header, data_b, msg_b)

    prefix_seed = f"{header}\n{data_b}"
    prefix_hash = hashlib.sha256(prefix_seed.encode("utf-8")).hexdigest()

    return CompiledContext(
        blocks=blocks,
        prefix_hash=prefix_hash,
        aliases={},
        dropped=(),
    )


def compile_case_summary_context(
    previous_summary: str,
    new_messages: Sequence[tuple[str, str]],
    *,
    last_events: Sequence[str] = (),
    spec: ContextSpec = CASE_SUMMARY_SPEC,
) -> CompiledContext:
    """Compile rolling case summary context (spec §7.4)."""
    data_b = data_block("data", previous_summary.strip() or "none")
    event_blocks = [data_block("event", e) for e in last_events if e.strip()]
    msg_blocks = [data_block("message", f"{sender}:\n{text}") for sender, text in new_messages]

    blocks = (data_b, *event_blocks, *msg_blocks)
    prefix_seed = data_b
    prefix_hash = hashlib.sha256(prefix_seed.encode("utf-8")).hexdigest()

    return CompiledContext(
        blocks=blocks,
        prefix_hash=prefix_hash,
        aliases={},
        dropped=(),
    )


def compile_briefing_context(
    collected_items_text: str,
    *,
    company_constants: str = "",
    spec: ContextSpec = BRIEFING_SPEC,
) -> CompiledContext:
    """Compile morning briefing context (spec §7.4)."""
    blocks: list[str] = []
    if company_constants.strip():
        blocks.append(data_block("company_constants", company_constants.strip()))
    blocks.append(data_block("items", collected_items_text))

    prefix_seed = blocks[0] if company_constants.strip() else ""
    prefix_hash = hashlib.sha256(prefix_seed.encode("utf-8")).hexdigest()

    return CompiledContext(
        blocks=tuple(blocks),
        prefix_hash=prefix_hash,
        aliases={},
        dropped=(),
    )
