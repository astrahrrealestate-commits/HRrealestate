"""A research answer with the sources it rests on. The model cites the short references a tool handed it (`m1`, `d2`);
the server turns those into `Source` rows, so an id or a URL never comes from the model."""

from typing import Annotated, Literal

from pydantic import Field

from app.contracts.common import Contract

SourceKind = Literal["message", "document", "web", "data"]
MAX_SOURCES = 12


class Source(Contract):
    kind: SourceKind
    ref: str  # a row id, or the URL of a fetched page
    label: str
    href: str | None = None  # where the chip opens, built by the server (`superagent.source_links`), never the model


class SourcedAnswer(Contract):
    """The research agent's output."""

    answer: str
    sources: Annotated[list[str], Field(max_length=MAX_SOURCES)]  # references from tool results, best first
    found: bool = True  # False: the tools were used and nothing answers the question
