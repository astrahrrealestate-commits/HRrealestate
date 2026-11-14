"""Structured output of the link_check agent."""

from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.contracts.common import Contract, NonBlankStr, max_len


class LinkDecision(Contract):
    case_id: UUID | None
    reason: Annotated[NonBlankStr, max_len(300)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
