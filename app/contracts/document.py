"""`DocumentClassification`: output of the doc_classifier agent (#9 Document Filing). OpenAI-strict.

`DocType` values are stored in `documents.doc_type` and name the Drive folders, so they never change.
"""

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import Field

from app.contracts.common import Contract, NonBlankStr, max_len


class DocType(StrEnum):
    lease = "lease"
    invoice = "invoice"
    quote = "quote"
    id_document = "id_document"
    insurance = "insurance"
    certificate = "certificate"
    correspondence = "correspondence"
    photo = "photo"
    other = "other"


class DocumentClassification(Contract):
    doc_type: DocType
    title: Annotated[NonBlankStr, max_len(80)]
    document_date: date | None
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]


class PartyRole(StrEnum):
    landlord = "landlord"
    tenant = "tenant"
    contractor = "contractor"
    insurer = "insurer"
    other = "other"


class DocParty(Contract):
    name: Annotated[NonBlankStr, max_len(120)]
    role: PartyRole


class KeyFact(Contract):
    """One labelled fact: ("monthly_rent", "EUR 1150.00"), ("deposit", "2 months rent"), ("due_date", "2026-11-01")."""

    label: Annotated[NonBlankStr, max_len(40)]
    value: Annotated[NonBlankStr, max_len(160)]


class DocumentFacts(Contract):
    """Output of the doc_reader agent (M10): what the document is and what it says. OpenAI-strict (no defaults)."""

    doc_type: DocType
    title: Annotated[NonBlankStr, max_len(80)]
    document_date: date | None
    summary: Annotated[NonBlankStr, max_len(400)]
    parties: Annotated[list[DocParty], Field(max_length=6)]
    unit_hint: Annotated[str, max_len(200)] | None  # the address or unit label as written in the document
    start_date: date | None  # lease start, insurance period start, work start
    end_date: date | None  # lease end, policy expiry, quote validity
    key_facts: Annotated[list[KeyFact], Field(max_length=10)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]

    def as_classification(self) -> DocumentClassification:
        return DocumentClassification(
            doc_type=self.doc_type, title=self.title, document_date=self.document_date, confidence=self.confidence
        )


class ExtractedText(Contract):
    """Output of the doc_ocr agent: the text read off a scan or photo, verbatim."""

    text: Annotated[str, max_len(30_000)]
