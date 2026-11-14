"""Request and response schemas of the finance routes (quotes, reviews, owner rate cards).

Money is a decimal string (never a float). The stored review `report` is served as it was stored (the same JSON the
`quote_review` feed card carries) after `clean_report`: every `sources` entry has a name, or it is dropped.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, field_validator, model_validator

from app.contracts.finance import SnapshotBasis, Verdict
from app.core.property_terms import ITEM_KEY_MAX, UNIT_MAX, normalise_item_key
from app.db.enums import QuoteStatus, RateSource
from app.db.models import QuoteLineRow, QuoteReview
from app.finance.repo_read import QuoteDetail, QuoteListRow

_ITEM_KEY = re.compile(rf"^[a-z0-9][a-z0-9_]{{0,{ITEM_KEY_MAX - 1}}}$")
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class VendorOut(BaseModel):
    id: UUID
    name: str


class LatestReviewOut(BaseModel):
    review_id: UUID
    verdict: Verdict
    late_days: int
    late_flag: bool
    overcharge_total: Decimal
    low_confidence: bool
    snapshot_basis: SnapshotBasis


class QuoteOut(BaseModel):
    id: UUID
    cursor: str  # `{created_at}|{id}`: pass the last item's value as `cursor` for the next page
    case_id: UUID | None
    vendor: VendorOut | None  # null: no contractor linked yet (such a quote cannot be rechecked)
    quote_date: date
    work_date: date | None
    currency: str
    total: Decimal | None
    status: QuoteStatus
    latest: LatestReviewOut | None
    created_at: AwareDatetime


class QuoteLineOut(BaseModel):
    position: int
    description: str  # plain text from the quote: render as text, never as HTML or Markdown
    item_key: str
    quantity: str
    unit: str
    unit_price: Decimal | None
    amount: Decimal
    vat_included: bool | None


class ReviewHistoryOut(BaseModel):
    id: UUID
    verdict: Verdict
    created_at: AwareDatetime


class QuoteDetailOut(QuoteOut):
    lines: list[QuoteLineOut]
    report: dict[str, Any] | None  # the latest review as stored (`quote_review` card payload); null: not reviewed yet
    history: list[ReviewHistoryOut]  # newest first


class RecheckOut(BaseModel):
    quote_id: UUID
    n: int  # the recheck's sequence number: one run per (quote, n), so a repeated click is one recheck


class RateIn(BaseModel):
    person_id: UUID
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    item_key: Annotated[str, StringConstraints(strip_whitespace=True, max_length=ITEM_KEY_MAX)] | None = None
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=UNIT_MAX)]
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    currency: Literal["EUR"] = "EUR"  # EUR only in v1: any other currency is 422
    valid_from: date | None = None  # default: today in the company timezone
    valid_to: date | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _window(self) -> "RateIn":
        if self.valid_from is not None and self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must be on or after valid_from")
        return self

    def resolved_item_key(self) -> str:
        """The given key when it is a valid key (lowercase letters, digits, underscore), else derived from the text."""
        given = (self.item_key or "").strip()
        return given if _ITEM_KEY.fullmatch(given) else normalise_item_key(self.description)


class RateOut(BaseModel):
    id: UUID
    person_id: UUID
    item_key: str
    description: str  # plain text
    unit: str
    amount: Decimal
    currency: str
    valid_from: date
    valid_to: date | None
    source: RateSource
    created_at: AwareDatetime


class RateRemovedOut(BaseModel):
    id: UUID
    action: Literal["deleted", "closed"]  # closed: a decision-day snapshot still points at it, so it only ended
    valid_to: date | None


def _named(entries: list[Any]) -> list[Any]:
    return [e for e in entries if isinstance(e, dict) and isinstance(e.get("name"), str) and e["name"].strip()]


def clean_report(value: Any) -> Any:
    """The stored report with every `sources` list reduced to entries that carry a name (nothing else is changed)."""
    if isinstance(value, dict):
        return {k: _named(v) if k == "sources" and isinstance(v, list) else clean_report(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_report(v) for v in value]
    return value


def _flag(report: dict[str, Any], key: str) -> bool:
    return report.get(key) is True


def latest_out(review: QuoteReview | None) -> LatestReviewOut | None:
    if review is None:
        return None
    return LatestReviewOut(
        review_id=review.id, verdict=review.verdict, late_days=review.late_days,
        late_flag=_flag(review.report, "late_flag"), overcharge_total=review.overcharge,
        low_confidence=_flag(review.report, "low_confidence"), snapshot_basis=review.snapshot_basis,
    )  # fmt: skip


def _vendor(row: QuoteListRow | QuoteDetail) -> VendorOut | None:
    q = row.quote
    return VendorOut(id=q.person_id, name=row.vendor_name or "") if q.person_id is not None else None


def quote_out(row: QuoteListRow | QuoteDetail) -> QuoteOut:
    q = row.quote
    return QuoteOut(
        id=q.id, cursor=f"{q.created_at.isoformat()}|{q.id}", case_id=q.case_id, vendor=_vendor(row),
        quote_date=q.quote_date, work_date=q.work_date, currency=q.currency, total=q.total, status=q.status,
        latest=latest_out(row.latest), created_at=q.created_at,
    )  # fmt: skip


def _line(line: QuoteLineRow) -> QuoteLineOut:
    return QuoteLineOut(
        position=line.position, description=line.description, item_key=line.item_key,
        quantity=f"{line.quantity.normalize():f}", unit=line.unit, unit_price=line.unit_price, amount=line.amount,
        vat_included=line.vat_included,
    )  # fmt: skip


def detail_out(d: QuoteDetail) -> QuoteDetailOut:
    return QuoteDetailOut(
        **quote_out(d).model_dump(),
        lines=[_line(line) for line in d.lines],
        report=clean_report(d.latest.report) if d.latest is not None else None,
        history=[ReviewHistoryOut(id=i, verdict=Verdict(v), created_at=at) for i, v, at in d.history],
    )  # fmt: skip
