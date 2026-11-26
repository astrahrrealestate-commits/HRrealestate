"""Two model tiers (M13): the quality tier writes what Harjot reads and sends, the fast tier does the triage."""

from typing import Literal

Tier = Literal["quality", "fast"]

# Drafts, the research behind them, Astra's research loop and person memory: the strongest Gemini model, thinking high.
QUALITY_AGENTS: frozenset[str] = frozenset({"proposer", "draft_research", "super_agent_research", "person_memory"})


def tier_of(agent_name: str) -> Tier:
    return "quality" if agent_name in QUALITY_AGENTS else "fast"
