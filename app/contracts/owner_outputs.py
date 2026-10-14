"""LLM outputs addressed to Harjot: owner Q&A answers and briefings (English)."""

from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.contracts.common import Contract, NonBlankStr, max_len


class OwnerAnswer(Contract):
    in_scope: bool  # False: not about Harjot's cases, tasks, people, properties or this app
    refusal_reason: Annotated[str, max_len(200)] | None  # why it is out of scope; None when in scope
    answer: Annotated[NonBlankStr, max_len(1500)]
    case_refs: list[UUID]


class BriefingSection(Contract):
    title: Annotated[NonBlankStr, max_len(40)]
    items: Annotated[list[Annotated[NonBlankStr, max_len(240)]], Field(max_length=8)]


class Briefing(Contract):
    headline: Annotated[NonBlankStr, max_len(160)]
    sections: Annotated[list[BriefingSection], Field(max_length=6)]
