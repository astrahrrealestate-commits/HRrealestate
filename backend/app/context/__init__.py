"""Context compiler and memory workspace package (spec: 2026-10-23-agent-memory-context-design)."""

from app.context.compiler import CONCIERGE_SPEC, compile_concierge_context
from app.context.conversation_summary import (
    count_unsummarized_turns,
    should_summarize,
    summarize_conversation_rolling,
    update_conversation_summary,
)
from app.context.focus_trail import append_focus_trail, page_to_focus_item, render_focus_trail
from app.context.memory_items import (
    format_owner_preferences_block,
    get_active_preferences,
    record_owner_memory,
    retire_memory,
    screen_memory_text,
)
from app.context.person_profile import (
    get_or_create_profile,
    mark_stale,
    person_profile_line,
    refresh_profile_deterministic,
    update_case_counts,
)
from app.context.spec import CompiledContext, ContextSpec, Slice

__all__ = [
    "CONCIERGE_SPEC",
    "CompiledContext",
    "ContextSpec",
    "Slice",
    "append_focus_trail",
    "compile_concierge_context",
    "count_unsummarized_turns",
    "format_owner_preferences_block",
    "get_active_preferences",
    "get_or_create_profile",
    "mark_stale",
    "page_to_focus_item",
    "person_profile_line",
    "record_owner_memory",
    "refresh_profile_deterministic",
    "render_focus_trail",
    "retire_memory",
    "screen_memory_text",
    "should_summarize",
    "summarize_conversation_rolling",
    "update_case_counts",
    "update_conversation_summary",
]
