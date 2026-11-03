"""A quote as stored (its lines, currency, lump sum) and its review from those stored lines. Pure.

The first review and every recheck run on the same stored representation, so they agree. Lines keep what the quote
states; a line without a VAT flag takes the quote's (stored on the line, since `quotes` has no VAT column). A quote
with a total and no lines is a lump sum: one synthetic `job` line (R17/R18). The `quotes` row has one currency: a quote
mixing currencies takes its first non-EUR one, so it is never compared as EUR. A stored line the review cannot read
(quantity, unit price or amount not positive) is skipped and counted; any skip holds the verdict at `needs_check`.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.contracts.common import Money
from app.contracts.finance import ExtractedQuote, Verdict
from app.core.property_terms import normalise_item_key, normalise_unit
from app.finance.references import LUMP_SUM_KEY, LUMP_SUM_UNIT, ReferencePlan
from app.finance.repo_quotes import NewQuoteLine
from app.finance.review import review_quote
from app.finance.review_types import REFERENCE_CURRENCY, ReviewInput, ReviewLine, ReviewResult, Thresholds

LUMP_SUM_DESCRIPTION = "lump sum"
NO_READABLE_LINES = "no readable quote lines"


@dataclass(frozen=True)
class QuoteFacts:
    """Everything a review needs about one quote; vendor and case come from our DB, never from the model."""

    company_id: UUID
    case_id: UUID | None
    vendor_id: UUID | None
    vendor_name: str | None
    currency: str
    total: Decimal | None
    quote_date: date
    lines: tuple[NewQuoteLine, ...]
    work_date: date | None = None

    @property
    def lump_sum(self) -> bool:
        return len(self.lines) == 1 and self.lines[0].item_key == LUMP_SUM_KEY


@dataclass(frozen=True)
class ReviewOutcome:
    """`reviewed` lines line up with `result.lines`; `skipped` could not be read."""

    review_input: ReviewInput
    result: ReviewResult
    reviewed: tuple[NewQuoteLine, ...]
    skipped: tuple[NewQuoteLine, ...]
    reason: str | None


def _money(quote: ExtractedQuote) -> Iterator[Money]:
    if quote.total is not None:
        yield quote.total
    for line in quote.lines:
        yield line.amount
        if line.unit_price is not None:
            yield line.unit_price


def quote_currency(quote: ExtractedQuote) -> str:
    found = [m.currency.strip().upper() for m in _money(quote)]
    return next((c for c in found if c != REFERENCE_CURRENCY), REFERENCE_CURRENCY)


def stored_lines(quote: ExtractedQuote) -> list[NewQuoteLine]:
    if not quote.lines and quote.total is not None:
        return [
            NewQuoteLine(
                position=1, description=LUMP_SUM_DESCRIPTION, item_key=LUMP_SUM_KEY, quantity=Decimal(1),
                unit=LUMP_SUM_UNIT, amount=quote.total.amount, vat_included=quote.vat_included,
            )
        ]  # fmt: skip
    return [
        NewQuoteLine(
            position=position, description=line.description, item_key=normalise_item_key(line.description),
            quantity=line.quantity, unit=normalise_unit(line.unit), amount=line.amount.amount,
            unit_price=line.unit_price.amount if line.unit_price is not None else None,
            vat_included=line.vat_included if line.vat_included is not None else quote.vat_included,
        )
        for position, line in enumerate(quote.lines, start=1)
    ]  # fmt: skip


def _review_line(line: NewQuoteLine) -> ReviewLine | None:
    try:
        if not line.amount > 0:
            return None
        return ReviewLine(
            description=line.description, quantity=line.quantity, unit=line.unit, amount=line.amount,
            unit_price=line.unit_price, vat_included=line.vat_included, item_key=line.item_key,
        )  # fmt: skip
    except (ValueError, ArithmeticError):  # decimal.InvalidOperation (NaN) is an ArithmeticError
        return None


def _readable(lines: Sequence[NewQuoteLine]) -> tuple[list[tuple[NewQuoteLine, ReviewLine]], list[NewQuoteLine]]:
    kept: list[tuple[NewQuoteLine, ReviewLine]] = []
    skipped: list[NewQuoteLine] = []
    for line in lines:
        review_line = _review_line(line)
        if review_line is None:
            skipped.append(line)
        else:
            kept.append((line, review_line))
    return kept, skipped


def run_review(facts: QuoteFacts, plan: ReferencePlan, thresholds: Thresholds) -> ReviewOutcome:
    kept, skipped = _readable(facts.lines)
    review_input = ReviewInput(
        lines=tuple(rl for _, rl in kept), currency=facts.currency, quote_date=facts.quote_date,
        decision_date=plan.decision_date, references=plan.references, snapshot_basis=plan.basis,
        lump_sum=facts.lump_sum,
    )  # fmt: skip
    result = review_quote(review_input, thresholds)
    reason = None
    if not kept:
        reason = NO_READABLE_LINES
    elif skipped:
        reason = f"{len(skipped)} unreadable line(s) skipped"
    if reason is not None:
        result = replace(result, verdict=Verdict.needs_check, low_confidence=True)
    return ReviewOutcome(review_input, result, tuple(ln for ln, _ in kept), tuple(skipped), reason)
