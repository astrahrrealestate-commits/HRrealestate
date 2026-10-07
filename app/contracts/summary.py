"""Structured output of the case_summary agent."""

from typing import Annotated

from app.contracts.common import Contract, NonBlankStr, max_len


class CaseSummary(Contract):
    summary: Annotated[NonBlankStr, max_len(1200)]
    next_step: Annotated[NonBlankStr, max_len(200)]
