"""`Understanding`: structured output of the understanding agent (also its LLM output schema).

`prompt_version` is part of the schema for storage, but the model's value is never trusted: the agent wrapper
overwrites it with the `PromptRef.key` actually used (M4).
"""

from datetime import date
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from app.contracts.common import Contract, Money, NonBlankStr, max_len


class Category(StrEnum):
    maintenance = "maintenance"
    payment = "payment"
    lease = "lease"
    complaint = "complaint"
    contractor_update = "contractor_update"
    admin = "admin"
    spam = "spam"
    other = "other"


class Urgency(StrEnum):
    emergency = "emergency"
    high = "high"
    normal = "normal"
    low = "low"


class Entities(Contract):
    people: list[str]
    unit_refs: list[str]
    dates: list[str]
    amounts: list[Money]

    @classmethod
    def none(cls) -> "Entities":
        return cls(people=[], unit_refs=[], dates=[], amounts=[])


class Suspicious(Contract):
    flag: bool
    reason: str | None

    @model_validator(mode="after")
    def _reason_iff_flag(self) -> Self:
        if self.flag and not (self.reason and self.reason.strip()):
            raise ValueError("suspicious messages need a reason")
        if not self.flag and self.reason is not None:
            raise ValueError("reason given for a non-suspicious message")
        return self


class Understanding(Contract):
    category: Category
    intent: Annotated[NonBlankStr, max_len(200)]
    urgency: Urgency
    requires_reply: bool  # the owner must answer this person; False for FYI, newsletters, receipts, thank-yous
    entities: Entities
    suspicious: Suspicious
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    prompt_version: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*/v[0-9]+$")]
