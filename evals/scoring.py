"""Golden set types (pydantic-evals Dataset: inputs + label metadata) and the understanding metrics."""

from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from pydantic_evals import Dataset

from app.contracts import Category, Channel, Understanding, Urgency

GOLDEN_DIR = Path(__file__).parent / "golden"


class GoldenInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    channel: Channel


class GoldenLabels(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category: Category
    urgency: Urgency
    suspicious: bool


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
    }
