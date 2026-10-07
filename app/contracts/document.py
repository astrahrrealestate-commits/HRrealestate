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
