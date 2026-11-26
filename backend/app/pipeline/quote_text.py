"""The stored quote review of a message, as the dossier shows it (M13): lines, unit prices, the market, the verdict."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import QuoteSource
from app.db.models import QuoteReview, QuoteRow

MAX_LINES = 20


def _line(ln: dict[str, Any]) -> str:
    price = ln.get("unit_price_excl_vat") or ln.get("unit_price")
    parts = [f"{ln.get('position')}. {ln.get('description')}: {ln.get('quantity')} {ln.get('unit')} at {price}",
             f"amount {ln.get('amount')}", f"status {ln.get('status')}"]  # fmt: skip
    if ln.get("reference") is not None:
        parts.append(f"reference {ln['reference']}")
    if ln.get("vs_market_pct") is not None:
        parts.append(f"{ln['vs_market_pct']}% vs market")
    if ln.get("rate_card") is not None:
        parts.append(f"rate card {ln['rate_card']}")
    return ", ".join(parts)


def render_review(report: dict[str, Any]) -> str:
    vendor = (report.get("vendor") or {}).get("name") or "vendor"
    head = (
        f"Quote by {vendor}: total {report.get('total')} {report.get('currency')}, verdict {report.get('verdict')}, "
        f"overcharge {report.get('overcharge_total')}"
    )
    lines = [_line(ln) for ln in (report.get("lines") or [])[:MAX_LINES] if isinstance(ln, dict)]
    skipped = report.get("skipped") or []
    tail = [f"Not judged: {len(skipped)} line(s) without a reference"] if skipped else []
    return "\n".join([head, *lines, *tail])


def quote_review_text(session: Session, company_id: UUID, message_ids: Sequence[UUID]) -> str | None:
    """The newest review of a quote taken from one of these messages; None when there is none."""
    if not message_ids:
        return None
    report = session.scalar(
        select(QuoteReview.report)
        .join(QuoteRow, QuoteRow.id == QuoteReview.quote_id)
        .where(
            QuoteRow.company_id == company_id,
            QuoteReview.company_id == company_id,
            QuoteRow.source == QuoteSource.message,
            QuoteRow.source_id.in_(list(message_ids)),
        )
        .order_by(QuoteReview.created_at.desc())
        .limit(1)
    )
    return render_review(report) if isinstance(report, dict) else None
