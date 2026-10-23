"""Context compiler implementation (spec: 2026-10-23-agent-memory-context-design §7, Task C2).

Assembles budgeted, escaped prompt blocks for agents. For concierge, byte-identical prompt guarantees are preserved.
"""

import hashlib
from collections.abc import Sequence

from app.context.spec import CompiledContext, ContextSpec, Slice
from app.llm.agents.owner_qa import CaseBrief
from app.llm.page_blocks import page_blocks
from app.llm.render import data_block

MAX_HISTORY = 12
MAX_HISTORY_LINE = 420

CONCIERGE_SPEC = ContextSpec(
    agent="concierge",
    slices=(
        Slice(name="data", stability=2, budget_chars=12000, trusted=True, drop_order=3),
        Slice(name="history", stability=3, budget_chars=5000, trusted=False, drop_order=2),
        Slice(name="page_facts", stability=4, budget_chars=12000, trusted=True, drop_order=4),
        Slice(name="page_snapshot", stability=5, budget_chars=6000, trusted=False, drop_order=1),
        Slice(name="page_filters", stability=5, budget_chars=500, trusted=True, drop_order=5),
        Slice(name="message", stability=6, budget_chars=2000, trusted=False, drop_order=6),
    ),
    total_chars=25000,
)


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
) -> CompiledContext:
    """Compile concierge context blocks.

    When owner_preferences is empty, output prompt_text is byte-identical to concierge_prompt.
    """
    lines = [
        f"case: {c.case_id} | {c.label} | {c.state} | {c.urgency}\n  {' '.join(c.summary.split())[:400]}" for c in cases
    ]
    tasks = [f"task: {t}" for t in open_tasks]
    data_content = "\n".join([*lines, *tasks]) or "no open cases or tasks"
    history_content = (
        "\n".join(" ".join(r.split())[:MAX_HISTORY_LINE] for r in recent[-MAX_HISTORY:]) or "no earlier messages"
    )

    data_b = data_block("data", data_content)
    pref_b = (
        [data_block("owner_preferences", "\n".join(f"- {p}" for p in owner_preferences))] if owner_preferences else []
    )
    history_b = data_block("history", history_content)
    page_bs = page_blocks(page_facts_text, snapshot, filters)
    message_b = data_block("message", question)

    blocks = (data_b, *pref_b, history_b, *page_bs, message_b)
    # Prefix hash covers stable parts (stability <= 2: data_block and owner preferences)
    prefix_seed = f"{data_b}\n{pref_b[0]}" if pref_b else data_b
    prefix_hash = hashlib.sha256(prefix_seed.encode("utf-8")).hexdigest()

    return CompiledContext(
        blocks=blocks,
        prefix_hash=prefix_hash,
        aliases={},
        dropped=(),
    )
