"""Structured retrieval plan for instruction-aware draft enhancement."""

from typing import Annotated

from pydantic import Field

from app.contracts.common import Contract, NonBlankStr, max_len

ShortQuery = Annotated[NonBlankStr, max_len(200)]


class EnhancePlan(Contract):
    """Extra lookups required before redrafting; all empty when the instruction is purely style/tone/wording."""

    rag_queries: Annotated[list[ShortQuery], Field(max_length=3)] = Field(default_factory=list)
    mail_queries: Annotated[list[ShortQuery], Field(max_length=3)] = Field(default_factory=list)
    web_questions: Annotated[list[Annotated[NonBlankStr, max_len(300)]], Field(max_length=2)] = Field(
        default_factory=list
    )
    db_question: Annotated[NonBlankStr, max_len(300)] | None = None
