"""Small builders for engine tests: a document read with claims, as the dd_reader would return it."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from app.contracts.diligence import DDClaim, DDDocKind, DDDocRead, DDField, DDFlag, DDFlagCategory
from app.diligence.inputs import DocInput

TODAY = date(2026, 10, 31)


def num(field: DDField, value: str, quote: str | None = None) -> DDClaim:
    return DDClaim(field=field, number=Decimal(value), text=None, day=None, quote=quote or f"{field.value} {value}")


def txt(field: DDField, value: str, quote: str | None = None) -> DDClaim:
    return DDClaim(field=field, number=None, text=value, day=None, quote=quote or f"{field.value} {value}")


def day(field: DDField, value: date, quote: str | None = None) -> DDClaim:
    return DDClaim(field=field, number=None, text=None, day=value, quote=quote or f"{field.value} {value}")


def doc(
    kind: DDDocKind,
    *claims: DDClaim,
    title: str | None = None,
    document_date: date | None = None,
    valid_until: date | None = None,
    flags: tuple[DDFlag, ...] = (),
    confidence: float = 0.9,
    document_id: UUID | None = None,
) -> DocInput:
    read = DDDocRead(
        doc_kind=kind, title=title or kind.value, document_date=document_date, valid_until=valid_until,
        claims=list(claims), flags=list(flags), confidence=confidence,
    )  # fmt: skip
    return DocInput(document_id=document_id or uuid4(), title=read.title, read=read)


def unreadable(title: str = "scan.pdf") -> DocInput:
    return DocInput(document_id=uuid4(), title=title, read=None)


def flag(summary: str = "Pending dispute with the VvE", quote: str = "geschil met de VvE") -> DDFlag:
    return DDFlag(category=DDFlagCategory.legal, summary=summary, quote=quote)
