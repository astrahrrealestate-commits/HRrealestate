"""`Proposal`: the proposer agent's output (1–4 actions). Code overwrites `case_id` and `draft_version`."""

from typing import Annotated

from pydantic import Field

from app.contracts.action import Action
from app.contracts.common import Contract


class Proposal(Contract):
    actions: Annotated[list[Action], Field(min_length=1, max_length=4)]
