"""Quote review (spec 2026-10-31, "contractor message/attachment with a quote"): the quote_reader agent reads the
message into typed lines, code stores the quote, compares it with the case's decision-day snapshot (or an estimate
from current prices, labelled) and appends a `quote_reviews` row plus a `quote_review` owner-feed card.

The company comes from the message (or quote) row, never from input. The vendor is the message's resolved sender if it
is one of the company's contractors, never anything the model returns; no contractor or no case → the quote is stored
`unlinked` with no review and no card. Replay-safe: a stored quote is checked BEFORE the model call (its first review
is returned, nothing new is written), and the quote insert is ON CONFLICT DO NOTHING. No session is held across the
model call or the price lookups; quote, lines, review, card and the `reviewed` status commit in one transaction.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.channels.dashboard import feed
from app.channels.prices.ports import PriceSource
from app.contracts.finance import ExtractedQuote
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import FeedKind, PersonKind, QuoteSource, QuoteStatus
from app.db.models import AttachmentRow, CaseLink, Company, MessageRow, Person, QuoteLineRow, QuoteReview, QuoteRow
from app.finance import repo
from app.finance.config import thresholds_from_settings
from app.finance.quote_lines import QuoteFacts, ReviewOutcome, quote_currency, run_review, stored_lines
from app.finance.references import Fresh, ReferencePlan, fresh_from, plan_lines, plan_lump_sum
from app.finance.repo_quotes import NewQuoteLine
from app.finance.report import build_report
from app.finance.review_types import REFERENCE_CURRENCY
from app.finance.sources import build_price_source
from app.llm.agents.quote_reader import QUOTE_READER, quote_reader_prompt
from app.llm.calls import CallContext, run_agent

log = get_logger(__name__)
PURPOSE = "finance_quote_reader"
FEED_KEY_PREFIX = "quote_review:"
MAX_FRESH_KEYS = 10  # fresh (drift/estimate) lookups per quote (R19: not counted in the daily snapshot cap)


@dataclass(frozen=True)
class _Incoming:
    company_id: UUID
    case_id: UUID | None
    vendor: tuple[UUID, str] | None
    received_on: date
    subject: str | None
    text: str
    attachments: list[str]


def _contractor(session: Session, company_id: UUID, person_id: UUID | None) -> tuple[UUID, str] | None:
    """(id, name) of the company's contractor `person_id`; None for no person or anyone who is not a contractor."""
    if person_id is None:
        return None
    row = session.execute(
        select(Person.id, Person.display_name).where(
            Person.company_id == company_id, Person.id == person_id, Person.kind == PersonKind.contractor
        )
    ).first()
    return (row.id, row.display_name) if row is not None else None


def _load_incoming(session: Session, message_id: UUID) -> _Incoming | None:
    msg = session.scalar(select(MessageRow).where(MessageRow.id == message_id))  # our own id: it gives the company
    if msg is None:
        return None
    cid = msg.company_id
    tz = session.scalar(select(Company.timezone).where(Company.id == cid)) or "Europe/Amsterdam"
    case_id = session.scalar(select(CaseLink.case_id).where(CaseLink.company_id == cid, CaseLink.message_id == msg.id))
    texts = session.scalars(
        select(AttachmentRow.extracted_text)
        .where(AttachmentRow.company_id == cid, AttachmentRow.message_id == msg.id)
        .where(AttachmentRow.extracted_text.is_not(None))
        .order_by(AttachmentRow.created_at, AttachmentRow.id)
    ).all()
    subject = msg.meta.get("subject") if msg.meta else None
    return _Incoming(
        company_id=cid, case_id=case_id, vendor=_contractor(session, cid, msg.person_id),
        received_on=msg.sent_at.astimezone(ZoneInfo(tz)).date(), subject=subject if isinstance(subject, str) else None,
        text=msg.text, attachments=[t for t in texts if t],
    )  # fmt: skip


def _stored(session: Session, company_id: UUID, message_id: UUID) -> tuple[bool, UUID | None]:
    """(the message's quote is stored, its first review id)."""
    quote_id = session.scalar(
        select(QuoteRow.id).where(
            QuoteRow.company_id == company_id, QuoteRow.source == QuoteSource.message, QuoteRow.source_id == message_id
        )
    )
    if quote_id is None:
        return False, None
    first = session.scalar(
        select(QuoteReview.id)
        .where(QuoteReview.company_id == company_id, QuoteReview.quote_id == quote_id)
        .order_by(QuoteReview.created_at, QuoteReview.id)
        .limit(1)
    )
    return True, first


def _facts(inc: _Incoming, quote: ExtractedQuote) -> QuoteFacts:
    vendor_id, vendor_name = inc.vendor if inc.vendor is not None else (None, None)
    return QuoteFacts(
        company_id=inc.company_id, case_id=inc.case_id, vendor_id=vendor_id, vendor_name=vendor_name,
        currency=quote_currency(quote), total=quote.total.amount if quote.total is not None else None,
        quote_date=inc.received_on, work_date=quote.work_date, lines=tuple(stored_lines(quote)),
    )  # fmt: skip


def _units(lines: Sequence[NewQuoteLine]) -> dict[str, str]:
    units: dict[str, str] = {}
    for line in lines:
        units.setdefault(line.item_key, line.unit)
    return units


def _gather(
    engine: Engine, settings: Settings, source: PriceSource, facts: QuoteFacts, case_id: UUID, vendor_id: UUID,
    today: date,
) -> ReferencePlan:  # fmt: skip
    """Snapshots and rate cards from the DB (session closed), then at most MAX_FRESH_KEYS fresh lookups."""
    cid, on, min_samples = facts.company_id, facts.quote_date, settings.finance_min_samples
    units = _units(facts.lines)
    with Session(engine) as session:
        if facts.lump_sum:
            case_snaps = repo.snapshots_for_case(session, cid, case_id, on)
            return plan_lump_sum(case_snaps, quote_date=on, min_samples=min_samples)
        snaps = {k: s for k in units if (s := repo.snapshot_for(session, cid, case_id, k, on)) is not None}
        cards = {k: repo.current_rate(session, cid, vendor_id, k, u, on) for k, u in units.items() if k not in snaps}
        amounts = {k: c.amount for k, c in cards.items() if c is not None and c.currency.upper() == REFERENCE_CURRENCY}
    looked = {k: snaps[k].unit if k in snaps else u for k, u in list(units.items())[:MAX_FRESH_KEYS]}
    fresh: dict[str, Fresh] = {
        k: fresh_from(source.lookup(k, u, today), u, vat_rate=settings.finance_vat_rate, min_samples=min_samples)
        for k, u in looked.items()
    }
    return plan_lines(units, snaps, amounts, fresh, quote_date=on, min_samples=min_samples)


def _write_quote(session: Session, facts: QuoteFacts, message_id: UUID, status: QuoteStatus) -> UUID | None:
    quote_id = repo.insert_quote(
        session, facts.company_id, source=QuoteSource.message, source_id=message_id, quote_date=facts.quote_date,
        currency=facts.currency, case_id=facts.case_id, person_id=facts.vendor_id, work_date=facts.work_date,
        total=facts.total, status=status,
    )  # fmt: skip
    if quote_id is not None:
        repo.insert_quote_lines(session, facts.company_id, quote_id=quote_id, lines=facts.lines)
    return quote_id


def _append_review(
    session: Session, facts: QuoteFacts, quote_id: UUID, plan: ReferencePlan, outcome: ReviewOutcome
) -> UUID:
    """The review row, its feed card (key `quote_review:{review_id}`) and the `reviewed` status, in the caller's
    transaction."""
    review_id, result = new_id(), outcome.result
    report = build_report(quote_id=quote_id, review_id=review_id, facts=facts, outcome=outcome, plan=plan)
    repo.insert_review(
        session, facts.company_id, quote_id=quote_id, snapshot_basis=plan.basis, verdict=result.verdict,
        overcharge=result.overcharge_total, late_days=result.late_days, report=report, review_id=review_id,
    )  # fmt: skip
    key = f"{FEED_KEY_PREFIX}{review_id}"
    feed.deliver_payload(session, facts.company_id, key, FeedKind.quote_review, quote_id, report)
    session.execute(
        update(QuoteRow)
        .where(QuoteRow.company_id == facts.company_id, QuoteRow.id == quote_id)
        .values(status=QuoteStatus.reviewed)
    )
    log.info("finance.quote.reviewed", quote_id=str(quote_id), review_id=str(review_id), verdict=result.verdict.value)
    return review_id


def _review(
    engine: Engine, settings: Settings, source: PriceSource | None, facts: QuoteFacts, today: date
) -> tuple[ReferencePlan, ReviewOutcome] | None:
    """References and the review of a linked quote (case and contractor known); None for an unlinked one."""
    if facts.case_id is None or facts.vendor_id is None:
        return None
    if source is None:
        source = build_price_source(settings, sessionmaker(engine), facts.company_id, facts.vendor_id)
    plan = _gather(engine, settings, source, facts, facts.case_id, facts.vendor_id, today)
    return plan, run_review(facts, plan, thresholds_from_settings(settings))


def review_message(
    engine: Engine, settings: Settings, message_id: UUID, *, today: date, source: PriceSource | None = None
) -> UUID | None:
    """Review the quote in `message_id`; the new (or, on replay, the first) review id. None: no such message, no
    quote in it (nothing stored), or an unlinked quote. `source` None = the configured sources minus the vendor."""
    with Session(engine) as session:
        inc = _load_incoming(session, message_id)
        stored, first = _stored(session, inc.company_id, message_id) if inc is not None else (False, None)
    if inc is None or stored:
        if stored:
            log.info("finance.quote.replay", message_id=str(message_id), review_id=str(first))
        return first
    prompt = quote_reader_prompt(inc.subject, inc.text, inc.attachments, inc.received_on)
    quote = run_agent(engine, settings, QUOTE_READER, prompt, CallContext(inc.company_id, PURPOSE)).output
    if not quote.is_quote:
        log.info("finance.quote.not_a_quote", message_id=str(message_id))
        return None
    facts = _facts(inc, quote)
    reviewed = _review(engine, settings, source, facts, today)
    with Session(engine) as session, session.begin():
        status = QuoteStatus.received if reviewed is not None else QuoteStatus.unlinked
        quote_id = _write_quote(session, facts, message_id, status)
        if quote_id is None:  # a concurrent run stored it first
            return _stored(session, facts.company_id, message_id)[1]
        if reviewed is None:
            log.info("finance.quote.unlinked", message_id=str(message_id), quote_id=str(quote_id))
            return None
        return _append_review(session, facts, quote_id, *reviewed)


def _new_line(row: QuoteLineRow) -> NewQuoteLine:
    return NewQuoteLine(
        position=row.position, description=row.description, item_key=row.item_key, quantity=row.quantity,
        unit=row.unit, amount=row.amount, unit_price=row.unit_price, vat_included=row.vat_included,
    )  # fmt: skip


def _load_quote(session: Session, quote_id: UUID) -> QuoteFacts | None:
    row = session.scalar(select(QuoteRow).where(QuoteRow.id == quote_id))  # our own id: it gives the company
    if row is None or row.status is QuoteStatus.unlinked or row.case_id is None:
        return None
    vendor = _contractor(session, row.company_id, row.person_id)
    if vendor is None:
        return None
    lines = session.scalars(
        select(QuoteLineRow)
        .where(QuoteLineRow.company_id == row.company_id, QuoteLineRow.quote_id == row.id)
        .order_by(QuoteLineRow.position, QuoteLineRow.id)
    ).all()
    return QuoteFacts(
        company_id=row.company_id, case_id=row.case_id, vendor_id=vendor[0], vendor_name=vendor[1],
        currency=row.currency, total=row.total, quote_date=row.quote_date, work_date=row.work_date,
        lines=tuple(_new_line(line) for line in lines),
    )  # fmt: skip


def recheck_quote(
    engine: Engine, settings: Settings, source: PriceSource | None, quote_id: UUID, *, today: date
) -> UUID | None:
    """Review a stored quote again from its stored lines (no model call; fresh lookups for drift and estimates);
    appends a review and a card. None if the quote is unknown or unlinked."""
    with Session(engine) as session:
        facts = _load_quote(session, quote_id)
    reviewed = _review(engine, settings, source, facts, today) if facts is not None else None
    if facts is None or reviewed is None:
        return None
    with Session(engine) as session, session.begin():
        return _append_review(session, facts, quote_id, *reviewed)
