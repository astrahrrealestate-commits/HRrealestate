"""What the draft research agent answers (M13 T8): claims that point at a numbered source and quote it.

The model never gives a URL. Code turns a claim into a `Finding` only when its source exists, belongs to its question
and contains the quoted evidence word for word.
"""

from typing import Annotated

from pydantic import Field

from app.contracts.common import Contract, NonBlankStr, max_len

MAX_CLAIMS = 9


class ResearchClaim(Contract):
    question: Annotated[int, Field(ge=1, le=3)]
    source: Annotated[int, Field(ge=1, le=50)]
    answer: Annotated[NonBlankStr, max_len(1500)]
    evidence: Annotated[NonBlankStr, max_len(300)]


class ResearchAnswers(Contract):
    claims: Annotated[list[ResearchClaim], Field(max_length=MAX_CLAIMS)]
