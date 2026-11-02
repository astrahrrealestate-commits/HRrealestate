"""Decision-day price snapshot (spec 2026-10-31, "approval of request_contractor"): what the job is (job_items agent
on the case summary and its recent messages), the market price of each item on the decision day, and the vendor's
rate card then; one immutable `price_snapshots` row per item (estimates are never stored, R4).

The company comes from the action row, never from input. No session is held across the model call or the lookups.
Replay-safe: an action that already has snapshot rows is not looked at again (no model call, no lookups), and rows
are written in one transaction with ON CONFLICT DO NOTHING. Daily cap (R19): the company's snapshot rows dated today
count as lookups; items past the cap are skipped and counted, as are items with no observations (no row).
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.channels.prices.ports import URL_OPTIONAL_PREFIX, PriceObservation, PriceSource
from app.contracts import ActionType
from app.contracts.finance import JobItem, PriceBasis
from app.core.errors import NotFoundError, SnapshotNotApplicableError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.property_terms import normalise_item_key, normalise_unit
from app.core.settings import Settings
from app.db.models import ActionRow, Case, CaseLink, MessageRow, PriceSnapshot
from app.finance import repo
from app.finance.review import to_excl_vat
from app.finance.review_types import REFERENCE_CURRENCY
from app.finance.stats import MarketStats, aggregate
from app.llm.agents.job_items import JOB_ITEMS, MAX_MESSAGES, job_items_prompt
from app.llm.calls import CallContext, run_agent

log = get_logger(__name__)
PURPOSE = "finance_job_items"
CENT = Decimal("0.01")
_BASIS_PREFERENCE = (PriceBasis.web, PriceBasis.competitor, PriceBasis.owner, PriceBasis.fake)  # tie order


@dataclass(frozen=True)
class SnapshotOutcome:
    written: list[UUID]
    skipped_cap: int
    skipped_no_data: int


@dataclass(frozen=True)
class SnapshotRequest:
    company_id: UUID
    case_id: UUID
    action_id: UUID
    vendor_id: UUID


@dataclass(frozen=True)
class _Priced:
    item_key: str
    unit: str
    stats: MarketStats
    basis: PriceBasis
    sources: list[dict[str, str]]


def load_request(session: Session, action_id: UUID) -> SnapshotRequest:
    """The action's company, case and contractor (all from the DB); raises unless it is a request_contractor."""
    act = session.scalar(select(ActionRow).where(ActionRow.id == action_id))  # our own id: it gives the company
    if act is None:
        raise NotFoundError(f"action {action_id} not found")
    if act.type is not ActionType.request_contractor:
        raise SnapshotNotApplicableError(f"action {action_id} is {act.type.value}, not request_contractor")
    try:
        vendor = UUID(str(act.payload["contractor_person_id"]))
    except (KeyError, ValueError) as exc:
        raise SnapshotNotApplicableError(f"action {action_id} names no contractor") from exc
    return SnapshotRequest(company_id=act.company_id, case_id=act.case_id, action_id=act.id, vendor_id=vendor)


def _already_taken(session: Session, req: SnapshotRequest) -> bool:
    q = select(PriceSnapshot.id).where(
        PriceSnapshot.company_id == req.company_id, PriceSnapshot.action_id == req.action_id
    )
    return session.scalar(q.limit(1)) is not None


def _case_text(session: Session, req: SnapshotRequest) -> tuple[str, list[str]]:
    """The case summary and its latest messages (oldest first, at most the agent's message window)."""
    summary = session.scalar(select(Case.summary).where(Case.company_id == req.company_id, Case.id == req.case_id))
    texts = session.scalars(
        select(MessageRow.text)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(
            CaseLink.company_id == req.company_id,
            CaseLink.case_id == req.case_id,
            MessageRow.company_id == req.company_id,
        )
        .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
        .limit(MAX_MESSAGES)
    ).all()
    return summary or "", list(reversed(texts))


def job_keys(items: Sequence[JobItem]) -> list[tuple[str, str]]:
    """(item_key, canonical unit) per job item, the first item of each key only (one snapshot row per key)."""
    keys: dict[str, str] = {}
    for item in items:
        keys.setdefault(normalise_item_key(item.description), normalise_unit(item.unit))
    return list(keys.items())


def excl_vat_prices(
    observations: Sequence[PriceObservation], unit: str, vat_rate: Decimal
) -> list[tuple[PriceObservation, Decimal]]:
    """Observations in `unit` (compared normalised) with their price excl. VAT. All observations are EUR (the port
    carries no currency), so there is no currency to filter."""
    wanted = normalise_unit(unit)
    out: list[tuple[PriceObservation, Decimal]] = []
    for obs in observations:
        price = to_excl_vat(obs.amount, obs.vat_included, vat_rate)
        if normalise_unit(obs.unit) == wanted and price is not None and price > 0:
            out.append((obs, price))
    return out


def _kind(obs: PriceObservation) -> PriceBasis:
    if obs.source == PriceBasis.fake.value:
        return PriceBasis.fake
    if obs.source.startswith(URL_OPTIONAL_PREFIX):
        return PriceBasis.competitor
    if obs.source == PriceBasis.owner.value:
        return PriceBasis.owner
    return PriceBasis.web  # any other source must carry a URL (PriceObservation enforces it)


def basis_of(observations: Sequence[PriceObservation]) -> PriceBasis:
    """The dominant kind of source; ties prefer web, then competitor, owner, fake."""
    counts = Counter(_kind(obs) for obs in observations)
    return max(_BASIS_PREFERENCE, key=lambda b: (counts[b], -_BASIS_PREFERENCE.index(b)))


def source_entries(priced: Sequence[tuple[PriceObservation, Decimal]]) -> list[dict[str, str]]:
    """What each number traces to: name, URL (when there is one), price excl. VAT and observed date, strings only."""
    entries: list[dict[str, str]] = []
    for obs, price in priced:
        entry = {"name": obs.source, "price": str(price.quantize(CENT)), "observed_on": obs.observed_on.isoformat()}
        if obs.url is not None:
            entry["url"] = obs.url
        entries.append(entry)
    return entries


def _price_item(source: PriceSource, settings: Settings, key: str, unit: str, today: date) -> _Priced | None:
    found = excl_vat_prices(source.lookup(key, unit, today), unit, settings.finance_vat_rate)
    stats = aggregate([price for _, price in found], settings.finance_min_samples)
    if stats is None:
        return None
    return _Priced(key, unit, stats, basis_of([obs for obs, _ in found]), source_entries(found))


def _store(engine: Engine, req: SnapshotRequest, priced: Sequence[_Priced], today: date) -> list[UUID]:
    written: list[UUID] = []
    with Session(engine) as session, session.begin():
        for p in priced:
            card = repo.current_rate(session, req.company_id, req.vendor_id, p.item_key, p.unit, today)
            if card is not None and card.currency.strip().upper() != REFERENCE_CURRENCY:
                card = None  # a rate card in another currency is no reference
            sid = new_id()
            if repo.insert_snapshot(
                session, req.company_id, action_id=req.action_id, item_key=p.item_key, unit=p.unit, as_of=today,
                stats=p.stats, basis=p.basis, sources=p.sources, rate_card=card, snapshot_id=sid,
            ):  # fmt: skip
                written.append(sid)
    return written


def take_snapshot(
    engine: Engine, settings: Settings, source: PriceSource, action_id: UUID, *, today: date
) -> SnapshotOutcome:
    """Snapshot market prices for the approved request_contractor `action_id` as of `today`. `source` is built by
    the caller with the action's contractor excluded (`build_price_source(..., exclude_person_id=vendor)`)."""
    with Session(engine) as session:
        req = load_request(session, action_id)
        if _already_taken(session, req):
            log.info("finance.snapshot.replay", action_id=str(action_id))
            return SnapshotOutcome(written=[], skipped_cap=0, skipped_no_data=0)
        summary, texts = _case_text(session, req)
        used = repo.lookups_today(session, req.company_id, today)
    ctx = CallContext(company_id=req.company_id, purpose=PURPOSE)
    keys = job_keys(run_agent(engine, settings, JOB_ITEMS, job_items_prompt(summary, texts), ctx).output.items)
    looked = keys[: max(0, settings.finance_daily_lookup_cap - used)]
    skipped_cap = len(keys) - len(looked)
    if skipped_cap:
        log.warning("finance.snapshot.cap_reached", company_id=str(req.company_id), skipped=skipped_cap)
    priced = [p for key, unit in looked if (p := _price_item(source, settings, key, unit, today)) is not None]
    written = _store(engine, req, priced, today)
    outcome = SnapshotOutcome(written=written, skipped_cap=skipped_cap, skipped_no_data=len(looked) - len(priced))
    log.info(
        "finance.snapshot.saved", action_id=str(action_id), written=len(written), skipped_cap=skipped_cap,
        skipped_no_data=outcome.skipped_no_data,
    )  # fmt: skip
    return outcome
