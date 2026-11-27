"""Shared contract primitives.

LLM-facing contracts (`Understanding`, `Action`) must produce OpenAI strict-mode JSON schemas: every field required
(no defaults), no `oneOf`/discriminator, no string length keywords, no regex lookarounds. Length and blank checks
therefore live in `AfterValidator`s, which validate without appearing in the schema.
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, AliasChoices, BaseModel, ConfigDict, Field, StringConstraints, WithJsonSchema


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
    google_chat = "google_chat"
    dashboard = "dashboard"


class InteractiveChannel(StrEnum):
    whatsapp = "whatsapp"
    google_chat = "google_chat"
    dashboard = "dashboard"


class OutboundMode(StrEnum):
    draft = "draft"
    send = "send"


class Direction(StrEnum):
    inbound = "inbound"
    outbound = "outbound"


class Money(Contract):
    """Parsing tolerates stray keys from a model (`extra="ignore"`), but the published schema stays strict-mode
    (`additionalProperties: false`), which the OpenAI structured-output API requires on every object."""

    model_config = ConfigDict(
        frozen=True, extra="ignore", populate_by_name=True, json_schema_extra={"additionalProperties": False}
    )

    amount: Annotated[
        Decimal,
        Field(validation_alias=AliasChoices("amount", "value", "total"), max_digits=12, decimal_places=2),
        WithJsonSchema({"type": "string", "pattern": r"^-?[0-9]{1,10}(\.[0-9]{1,2})?$"}),
    ]
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


@dataclass(frozen=True)
class MailAttachment:
    filename: str
    mime_type: str
    content: bytes


@dataclass(frozen=True)
class DraftRequest:
    idempotency_key: str
    thread_id: str
    to: str
    subject: str
    body: str
    in_reply_to: str | None = None
    references: str | None = None
    attachments: tuple[MailAttachment, ...] = ()

    @property
    def key_token(self) -> str:
        """Carried in `X-EstateOS-Key`. Gmail rewrites a draft's Message-ID, but keeps custom headers."""
        return hashlib.sha256(self.idempotency_key.encode()).hexdigest()[:32]

    @property
    def rfc822_id(self) -> str:
        digest = hashlib.sha256(self.idempotency_key.encode()).hexdigest()[:32]
        return f"<draft-{digest}@estateos.invalid>"


@dataclass(frozen=True)
class EmailRequest:
    idempotency_key: str
    to: str
    subject: str
    body_text: str
    body_html: str | None = None

    @property
    def key_token(self) -> str:
        return hashlib.sha256(self.idempotency_key.encode()).hexdigest()[:32]

    @property
    def rfc822_id(self) -> str:
        return f"<owner-{self.key_token}@estateos.invalid>"
