"""What EstateOS remembers about one person (M13): output of the person_memory agent, stored on the profile."""

from typing import Annotated

from pydantic import Field

from app.contracts.common import Contract, NonBlankStr, max_len

MemoryLine = Annotated[NonBlankStr, max_len(200)]
MemoryLines = Annotated[tuple[MemoryLine, ...], Field(max_length=10)]


class PersonMemory(Contract):
    summary: Annotated[NonBlankStr, max_len(800)]
    commitments: MemoryLines  # what Harjot or his team promised this person
    preferences: MemoryLines
    open_issues: MemoryLines
