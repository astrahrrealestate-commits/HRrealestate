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
