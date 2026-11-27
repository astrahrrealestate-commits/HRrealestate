"""`Understanding`: structured output of the understanding agent (also its LLM output schema).

`prompt_version` is part of the schema for storage, but the model's value is never trusted: the agent wrapper
overwrites it with the `PromptRef.key` actually used (M4).
"""

from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import Field, StringConstraints, model_validator

from app.contracts.common import Contract, Money, NonBlankStr, max_len


class Category(StrEnum):
    """The six business areas Harjot works by (M13), plus internal `spam`, which is never shown."""

    maintenance = "maintenance"
    finance = "finance"
    legal = "legal"
    business = "business"
    administration = "administration"
    new_projects = "new_projects"
    spam = "spam"


class SenderRole(StrEnum):
    """Who the model thinks wrote a property-related message. A display and drafting-register hint only: the directory
    decides who a person is, and recipients never come from this (ADR 0014)."""

    tenant = "tenant"
    contractor = "contractor"
    legal = "legal"  # advocate, notary, bailiff
    vve = "vve"  # homeowners' association or building admin
    business = "business"  # bank, tax office, utility, software or other vendor
    prospect = "prospect"  # someone asking to view or rent


class Urgency(StrEnum):
    emergency = "emergency"
    high = "high"
    normal = "normal"
    low = "low"


class WaitingSide(StrEnum):
    """Who owes the next message or promised deliverable after this message."""

    owner = "owner"
    third_party = "third_party"
    none = "none"


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
    sender_role: SenderRole | None  # None when the sender is unclear or the mail is not about the portfolio
    needs_research: bool  # a quote, legal or works question, or anything our data cannot answer (M13)
    research_questions: Annotated[list[Annotated[NonBlankStr, max_len(300)]], Field(max_length=3)]
    waiting_side: WaitingSide
    open_obligation: Annotated[NonBlankStr, max_len(200)] | None
    expected_days: Annotated[int, Field(ge=1, le=60)] | None
    expected_date: date | None
    prompt_version: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*/v[0-9]+$")]

    @model_validator(mode="before")
    @classmethod
    def _research_defaults_for_stored_bodies(cls, data: Any) -> Any:
        """Bodies stored before understanding/v4 (research) and v6 (waiting) lack newer fields: defaulted here
        while keeping the strict JSON output schema complete."""
        if not isinstance(data, dict):
            return data
        out = {"needs_research": False, "research_questions": [], **data}
        if "waiting_side" not in out:
            req_reply = out.get("requires_reply", True)
            cat = out.get("category")
            ws = (
                WaitingSide.none.value
                if (cat in (Category.spam, Category.spam.value) or req_reply is False)
                else WaitingSide.owner.value
            )
            out["waiting_side"] = ws
        out.setdefault("open_obligation", None)
        out.setdefault("expected_days", None)
        out.setdefault("expected_date", None)
        return out

    @model_validator(mode="before")
    @classmethod
    def _no_role_for_noise_or_suspicious(cls, data: Any) -> Any:
        """Spam and suspicious mail get no label: a phishing mail claiming to be a lawyer must not look like one."""
        if not isinstance(data, dict) or data.get("sender_role") is None:
            return data
        suspicious = data.get("suspicious")
        if isinstance(suspicious, Suspicious):
            flagged = suspicious.flag
        else:
            flagged = isinstance(suspicious, dict) and bool(suspicious.get("flag"))
        if flagged or data.get("category") in (Category.spam, Category.spam.value):
            return {**data, "sender_role": None}
        return data
