"""WhatsApp reply-button ids: `apr:<approval_id>:<choice>` maps a tap to exactly one approval."""

import re
from enum import StrEnum
from typing import Self
from uuid import UUID

from app.contracts.common import Contract
from app.core.errors import InvalidButtonIdError

MAX_BUTTON_ID_LEN = 256  # WhatsApp interactive reply-button id limit


class ButtonChoice(StrEnum):
    ok = "ok"
    edit = "edit"
    rej = "rej"
    d1 = "d1"
    d2 = "d2"
    d3 = "d3"


_PATTERN = re.compile(
    r"apr:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):("
    + "|".join(c.value for c in ButtonChoice)
    + ")"
)


class ButtonId(Contract):
    approval_id: UUID
    choice: ButtonChoice

    @classmethod
    def parse(cls, raw: object) -> Self:
        if not isinstance(raw, str):
            raise InvalidButtonIdError(f"button id must be a string, got {type(raw).__name__}")
        match = _PATTERN.fullmatch(raw)
        if match is None:
            raise InvalidButtonIdError(f"not a button id: {raw[:64]!r}")
        return cls(approval_id=UUID(match.group(1)), choice=ButtonChoice(match.group(2)))

    def render(self) -> str:
        return f"apr:{self.approval_id}:{self.choice.value}"
