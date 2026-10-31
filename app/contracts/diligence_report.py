"""Due Diligence Lite report: the typed result the engine builds from the documents' verified reads.

Stored as jsonb on `dd_reviews.report` and returned by the API. Not LLM-facing: the model never produces any of it.
"""

from datetime import date
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.contracts.common import Contract
from app.contracts.diligence import DDDocKind, DDField, DDPropertyKind

DISCLAIMER = "Screening aid built from the documents provided. It is not legal, technical or financial advice."


class DDSeverity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class DDVerdict(StrEnum):
    clear_to_review = "clear_to_review"
    needs_documents = "needs_documents"
    red_flags = "red_flags"


class RequirementSeverity(StrEnum):
    critical = "critical"
    important = "important"
    nice = "nice"


class ChecklistStatus(StrEnum):
    present = "present"
    missing = "missing"
    stale = "stale"  # a matching document exists but is out of date
    unclear = "unclear"  # a matching document exists but could not be read with confidence


class MismatchKind(StrEnum):
    marketing_vs_legal = "marketing_vs_legal"  # a brochure disagrees with an official or legal document
    inconsistent = "inconsistent"


class ChecklistItem(Contract):
    key: str
    label: str
    severity: RequirementSeverity
    status: ChecklistStatus
    why: str
    document_ids: list[UUID]
    note: str | None


class MismatchSide(Contract):
    document_id: UUID
    title: str
    doc_kind: DDDocKind
    value: str
    quote: str


class Mismatch(Contract):
    field: DDField
    kind: MismatchKind
    severity: DDSeverity
    reference: MismatchSide  # the more authoritative source: the one to trust
    other: MismatchSide
    difference: str


class DDRisk(Contract):
    code: str
    severity: DDSeverity
    summary: str
    document_ids: list[UUID]
    source: Literal["rule", "document"]  # `document`: the model surfaced it, quoted from the text
    quote: str | None


class DDDocSummary(Contract):
    document_id: UUID
    title: str
    doc_kind: DDDocKind | None  # None: the document could not be read
    readable: bool
    claims: int


class Coverage(Contract):
    present: int
    applicable: int


class DDReport(Contract):
    framework_version: str
    property_kind: DDPropertyKind
    as_of: date
    verdict: DDVerdict
    coverage: Coverage
    checklist: list[ChecklistItem]
    mismatches: list[Mismatch]
    risks: list[DDRisk]
    documents: list[DDDocSummary]
    unverified_claims: int = Field(ge=0)  # claims and flags dropped because their quote was not in the text
    disclaimer: str
