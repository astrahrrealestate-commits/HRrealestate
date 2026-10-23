"""Contracts of the retrieval agents (ADR 0008). OpenAI-strict: every field required, no defaults."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from app.contracts.common import Contract, NonBlankStr, max_len
from app.contracts.document import DocType


class FactKind(StrEnum):
    """A single fact a landlord asks for, answerable from a document's stored facts without generation."""

    monthly_rent = "monthly_rent"
    deposit = "deposit"
    notice_period = "notice_period"
    lease_start = "lease_start"
    lease_end = "lease_end"


class QueryPlan(Contract):
    """How to search for one question: other words for it, a passage that would answer it, and its fact if any."""

    keywords: Annotated[list[Annotated[NonBlankStr, max_len(60)]], Field(max_length=8)]  # Dutch and English variants
    hypothetical_answer: Annotated[
        str, max_len(500)
    ]  # a short Dutch passage as a document would say it (HyDE); may be empty
    fact: FactKind | None  # set only when the question asks for exactly one of these facts
    doc_types: Annotated[
        list[DocType], Field(max_length=3)
    ]  # kinds of document likely to hold the answer; may be empty


class PassageScore(Contract):
    ref: Annotated[int, Field(ge=1, le=40)]  # the number of the passage in the prompt
    relevance: Annotated[int, Field(ge=0, le=3)]  # 0 unrelated · 1 mentions the topic · 2 helps · 3 answers it


class RerankResult(Contract):
    scores: Annotated[list[PassageScore], Field(max_length=40)]
