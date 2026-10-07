"""Briefing agent (#7): Harjot's 07:30 daily and Friday weekly message, written from facts collected by code.

A deterministic template (`fallback_briefing`) renders the same facts when the agent fails, so a briefing is never
skipped.
"""

from dataclasses import dataclass, field
from typing import Literal

from app.contracts import Briefing, BriefingSection, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block

Kind = Literal["daily", "weekly"]
MAX_ITEMS = 8
TEXT_LIMIT = 4096


@dataclass(frozen=True)
class BriefingFacts:
    kind: Kind
    day_label: str  # e.g. "Wed 07 Oct" in the company timezone
    urgent: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    overdue_tasks: list[str] = field(default_factory=list)
    overdue_waits: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def _unchanged(output: Briefing, _loaded: LoadedPrompt) -> Briefing:
    return output


BRIEFING = AgentSpec(
    name="briefing", prompt=PromptRef(name="briefing", version="v1"), output_type=Briefing, finalize=_unchanged
)


def _sections(f: BriefingFacts) -> list[tuple[str, list[str]]]:
    weekly = [f"{name}: {value}" for name, value in f.stats.items()] if f.kind == "weekly" else []
    named = [
        ("Urgent", f.urgent),
        ("Waiting for your decision", f.approvals),
        ("Overdue tasks", f.overdue_tasks),
        ("No answer yet", f.overdue_waits),
        ("Exceptions", f.exceptions),
        ("This week", weekly),
    ]
    return [(title, items) for title, items in named if items]


def briefing_prompt(f: BriefingFacts) -> str:
    lines = [f"kind: {f.kind}", f"day: {f.day_label}"]
    for title, items in _sections(f):
        lines += [f"## {title}", *(f"- {i}" for i in items)]
    return data_block("data", "\n".join(lines))


def _cap(items: list[str]) -> list[str]:
    if len(items) <= MAX_ITEMS:
        return [i[:240] for i in items]
    return [i[:240] for i in items[: MAX_ITEMS - 1]] + [f"+{len(items) - MAX_ITEMS + 1} more"]


def fallback_briefing(f: BriefingFacts) -> Briefing:
    if f.urgent:
        headline = f"{len(f.urgent)} urgent case(s) need you today."
    elif f.approvals:
        headline = f"{len(f.approvals)} decision(s) waiting for you."
    else:
        headline = "Quiet day: nothing waiting for you."
    sections = [BriefingSection(title=t, items=_cap(items)) for t, items in _sections(f)][:6]
    return Briefing(headline=headline, sections=sections)


def render_text(f: BriefingFacts, briefing: Briefing) -> str:
    greeting = f"Good morning. Briefing {f.day_label}" if f.kind == "daily" else f"Week summary, {f.day_label}"
    parts = [f"{greeting}\n{briefing.headline}"]
    parts += ["\n".join([f"*{s.title}*", *(f"- {i}" for i in s.items)]) for s in briefing.sections]
    return "\n\n".join(parts)[:TEXT_LIMIT]
