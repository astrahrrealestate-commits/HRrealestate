"""Golden set types (pydantic-evals Dataset: inputs + label metadata) and the understanding metrics."""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_evals import Dataset

from app.contracts import Category, Channel, SenderRole, Understanding, Urgency

GOLDEN_DIR = Path(__file__).parent / "golden"


class GoldenInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    channel: Channel
    sender: str | None = None  # the From address a sender-aware prompt sees (email only)


class GoldenLabels(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category: Category
    urgency: Urgency
    suspicious: bool
    requires_reply: bool = True  # a human would owe this sender an answer
    sender_role: SenderRole | None = None  # who a careful human says wrote it; None for noise and unclear senders
    needs_research: bool | None = None  # None: not judged


def load_understanding(
    path: Path = GOLDEN_DIR / "understanding.yaml",
) -> Dataset[GoldenInput, Understanding, GoldenLabels]:
    return Dataset[GoldenInput, Understanding, GoldenLabels].from_file(path)


def _recall(
    pairs: Sequence[tuple[GoldenLabels, Understanding]],
    want: Callable[[GoldenLabels], bool],
    got: Callable[[Understanding], bool],
) -> float:
    relevant = [output for labels, output in pairs if want(labels)]
    return sum(got(output) for output in relevant) / len(relevant) if relevant else 1.0


def _is_unlabelled_noise(labels: GoldenLabels) -> bool:
    return not labels.requires_reply and labels.sender_role is None


def _role_accuracy(pairs: Sequence[tuple[GoldenLabels, Understanding]]) -> float:
    labelled = [(g, o) for g, o in pairs if g.sender_role is not None]
    return sum(g.sender_role is o.sender_role for g, o in labelled) / len(labelled) if labelled else 1.0


def _research_accuracy(pairs: Sequence[tuple[GoldenLabels, Understanding]]) -> float:
    labelled = [(g, o) for g, o in pairs if g.needs_research is not None]
    return sum(g.needs_research is o.needs_research for g, o in labelled) / len(labelled) if labelled else 1.0


def score_understanding(labels: Sequence[GoldenLabels], outputs: Sequence[Understanding]) -> dict[str, float]:
    pairs = list(zip(labels, outputs, strict=True))
    n = len(pairs) or 1
    return {
        "category_accuracy": sum(g.category is o.category for g, o in pairs) / n,
        "urgency_accuracy": sum(g.urgency is o.urgency for g, o in pairs) / n,
        "emergency_recall": _recall(
            pairs, lambda g: g.urgency is Urgency.emergency, lambda o: o.urgency is Urgency.emergency
        ),
        "suspicious_recall": _recall(pairs, lambda g: g.suspicious, lambda o: o.suspicious.flag),
        "reply_flag_accuracy": sum(g.requires_reply is o.requires_reply for g, o in pairs) / n,
        # the two errors the owner feels: a draft for mail that needs none (noise), a reply he never hears about
        "needless_draft_rate": 1 - _recall(pairs, lambda g: not g.requires_reply, lambda o: not o.requires_reply),
        "missed_reply_rate": 1 - _recall(pairs, lambda g: g.requires_reply, lambda o: o.requires_reply),
        # labels come after intent: a role is judged only where one is expected, and noise must never get one
        "sender_role_accuracy": _role_accuracy(pairs),
        "needs_research_accuracy": _research_accuracy(pairs),
        "role_on_noise_rate": 1 - _recall(pairs, _is_unlabelled_noise, lambda o: o.sender_role is None),
    }


class GoldenCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    category: Category
    summary: str


class GoldenLinkInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    category: Category
    candidates: list[GoldenCandidate]


class GoldenLinkLabel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expected: str | None  # candidate key, or None: a new topic, open a new case


def load_linking(path: Path = GOLDEN_DIR / "linking.yaml") -> Dataset[GoldenLinkInput, Any, GoldenLinkLabel]:
    return Dataset[GoldenLinkInput, Any, GoldenLinkLabel].from_file(path)


def score_linking(labels: Sequence[GoldenLinkLabel], chosen: Sequence[str | None]) -> dict[str, float]:
    """`wrong_link_rate` is the costly error: a message filed under another case. A missed link only opens a case."""
    pairs = list(zip(labels, chosen, strict=True))
    n = len(pairs) or 1
    should_link = [(g, c) for g, c in pairs if g.expected is not None]
    should_open = [c for g, c in pairs if g.expected is None]
    return {
        "accuracy": sum(g.expected == c for g, c in pairs) / n,
        "wrong_link_rate": sum(c is not None and c != g.expected for g, c in pairs) / n,
        "link_recall": sum(c == g.expected for g, c in should_link) / len(should_link) if should_link else 1.0,
        "new_case_recall": sum(c is None for c in should_open) / len(should_open) if should_open else 1.0,
    }
