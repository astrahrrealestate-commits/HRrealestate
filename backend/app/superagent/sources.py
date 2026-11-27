"""The sources one research run found. Each gets a short reference (`m1`, `d2`, `w1`, `q1`) that the model uses to open
or cite it. A reference this run never handed out resolves to nothing: the model cannot name a row or a URL itself."""

import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.contracts.sourced_answer import Source, SourcedAnswer, SourceKind
from app.pipeline.concierge_sanitize import plain_line, redact_contact

_PREFIX: dict[SourceKind, str] = {"message": "m", "document": "d", "web": "w", "data": "q"}
MAX_LABEL = 120
NOT_FOUND = "I could not find that in your mail, documents or data."


@dataclass
class SourceLog:
    _by_alias: dict[str, Source] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, kind: SourceKind, ref: str, label: str) -> str:
        with self._lock:  # tools of one model response run in parallel
            for alias, known in self._by_alias.items():
                if (known.kind, known.ref) == (kind, ref):
                    return alias
            alias = f"{_PREFIX[kind]}{sum(s.kind == kind for s in self._by_alias.values()) + 1}"
            clean = redact_contact(plain_line(label))[:MAX_LABEL]
            self._by_alias[alias] = Source(kind=kind, ref=ref, label=clean)
            return alias

    def get(self, alias: str) -> Source | None:
        return self._by_alias.get(alias.strip().lower())

    def _id(self, alias: str, kind: SourceKind) -> UUID | None:
        source = self.get(alias)
        return UUID(source.ref) if source is not None and source.kind == kind else None

    def message_id(self, alias: str) -> UUID | None:
        return self._id(alias, "message")

    def document_id(self, alias: str) -> UUID | None:
        return self._id(alias, "document")

    def case_id(self, alias: str) -> UUID | None:
        source = self.get(alias)
        if source is None or source.kind != "data":
            return None
        try:
            return UUID(source.ref)
        except ValueError:
            return None


@dataclass(frozen=True)
class ScreenedAnswer:
    answer: str
    sources: tuple[Source, ...]


def screen(output: SourcedAnswer, log: SourceLog, steps: Sequence[str] = ()) -> ScreenedAnswer:
    """The answer with the sources that exist. A run that looked things up but cites nothing real has no ground for its
    claims, so they are replaced by what was searched; small talk (no lookups) and an honest "not found" stand."""
    cited = [s for s in (log.get(alias) for alias in output.sources) if s is not None]
    sources = tuple(dict.fromkeys(cited))
    if (sources and output.found) or not steps:
        return ScreenedAnswer(output.answer.strip(), sources)
    return ScreenedAnswer(f"{NOT_FOUND} {'; '.join(steps)}.", ())
