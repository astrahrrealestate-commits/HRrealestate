"""Context compiler specifications and dataclasses (spec: 2026-10-23-agent-memory-context-design §7.1)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Slice:
    """A declared slice of agent context. Ordered by stability (stable first for prefix caching)."""

    name: str  # "data", "brief", "history", "page_facts", "client_state", "message", ...
    stability: int  # 0 static … 5 per-message; sets block ordering
    budget_chars: int  # character cap for this slice
    trusted: bool  # server facts (True) vs untrusted input/snapshot (False)
    drop_order: int  # who gives way first when total budget is exceeded


@dataclass(frozen=True)
class ContextSpec:
    """Agent context specification declaring slices, order, and total budget."""

    agent: str
    slices: tuple[Slice, ...]
    total_chars: int


@dataclass(frozen=True)
class CompiledContext:
    """Result of context compilation ready for the model call."""

    blocks: tuple[str, ...]
    prefix_hash: str
    aliases: dict[str, str]
    dropped: tuple[str, ...]

    @property
    def prompt_text(self) -> str:
        return "\n".join(b for b in self.blocks if b)


# Agent Context Specifications (spec §7.4, Task C12)
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

PROPOSER_SPEC = ContextSpec(
    agent="proposer",
    slices=(
        Slice(name="company_constants", stability=1, budget_chars=3000, trusted=True, drop_order=6),
        Slice(name="owner_preferences", stability=1, budget_chars=2000, trusted=True, drop_order=5),
        Slice(name="person_profile", stability=3, budget_chars=1000, trusted=False, drop_order=4),
        Slice(name="case_memory", stability=3, budget_chars=3000, trusted=True, drop_order=3),
        Slice(name="document_excerpts", stability=4, budget_chars=6000, trusted=True, drop_order=2),
        Slice(name="message", stability=5, budget_chars=2000, trusted=False, drop_order=7),
        Slice(name="guidance", stability=5, budget_chars=1000, trusted=False, drop_order=1),
    ),
    total_chars=20000,
)

OWNER_QA_SPEC = ContextSpec(
    agent="owner_qa",
    slices=(
        Slice(name="company_constants", stability=1, budget_chars=3000, trusted=True, drop_order=4),
        Slice(name="brief", stability=2, budget_chars=4000, trusted=True, drop_order=3),
        Slice(name="page_facts", stability=4, budget_chars=8000, trusted=True, drop_order=2),
        Slice(name="message", stability=5, budget_chars=2000, trusted=False, drop_order=5),
    ),
    total_chars=16000,
)

UNDERSTANDING_SPEC = ContextSpec(
    agent="understanding",
    slices=(
        Slice(name="glossary", stability=1, budget_chars=2000, trusted=True, drop_order=3),
        Slice(name="message", stability=5, budget_chars=3000, trusted=False, drop_order=4),
        Slice(name="attachment_metadata", stability=5, budget_chars=2000, trusted=True, drop_order=2),
    ),
    total_chars=8000,
)

LINK_CHECK_SPEC = ContextSpec(
    agent="link_check",
    slices=(
        Slice(name="candidate_cases", stability=2, budget_chars=4000, trusted=True, drop_order=3),
        Slice(name="person_profile_line", stability=3, budget_chars=500, trusted=False, drop_order=2),
        Slice(name="message", stability=5, budget_chars=2500, trusted=False, drop_order=4),
    ),
    total_chars=10000,
)

CASE_SUMMARY_SPEC = ContextSpec(
    agent="case_summary",
    slices=(
        Slice(name="previous_summary", stability=2, budget_chars=2000, trusted=True, drop_order=3),
        Slice(name="last_events", stability=3, budget_chars=2000, trusted=True, drop_order=2),
        Slice(name="new_message", stability=5, budget_chars=2500, trusted=False, drop_order=4),
    ),
    total_chars=8000,
)

BRIEFING_SPEC = ContextSpec(
    agent="briefing",
    slices=(
        Slice(name="company_constants", stability=1, budget_chars=3000, trusted=True, drop_order=3),
        Slice(name="collected_items", stability=4, budget_chars=8000, trusted=True, drop_order=2),
    ),
    total_chars=12000,
)
