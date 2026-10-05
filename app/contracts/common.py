"""Shared contract primitives.

LLM-facing contracts (`Understanding`, `Action`) must produce OpenAI strict-mode JSON schemas: every field required
(no defaults), no `oneOf`/discriminator, no string length keywords, no regex lookarounds. Length and blank checks
therefore live in `AfterValidator`s, which validate without appearing in the schema.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, WithJsonSchema


class Contract(BaseModel):
    """Base for every stage-to-stage contract: immutable, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def require_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def max_len(limit: int) -> AfterValidator:
    def check(value: str) -> str:
        if len(value) > limit:
            raise ValueError(f"must be at most {limit} characters")
        return value

    return AfterValidator(check)


NonBlankStr = Annotated[str, AfterValidator(require_non_blank)]


class Channel(StrEnum):
    whatsapp = "whatsapp"
    gmail = "gmail"


class Direction(StrEnum):
    inbound = "inbound"
    outbound = "outbound"


class Money(Contract):
    amount: Annotated[
        Decimal,
        Field(max_digits=12, decimal_places=2),
        WithJsonSchema({"type": "string", "pattern": r"^-?[0-9]{1,10}(\.[0-9]{1,2})?$"}),
    ]
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
