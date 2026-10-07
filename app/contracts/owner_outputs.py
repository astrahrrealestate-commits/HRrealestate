"""LLM outputs addressed to Harjot: owner Q&A answers and briefings (English)."""

from typing import Annotated
from uuid import UUID

from app.contracts.common import Contract, NonBlankStr, max_len


class OwnerAnswer(Contract):
    answer: Annotated[NonBlankStr, max_len(1500)]
    case_refs: list[UUID]
