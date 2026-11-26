"""What one quote review compares with, read for the QUOTING vendor (rulings R19, R21, R22): the case's snapshots and
the vendor's own cards from the DB (session closed before any lookup), then at most `MAX_FRESH_KEYS` fresh lookups
(drift for snapshot items, the market for the others; not counted in the daily snapshot cap). Every query filters by
the quote's company.
"""

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.channels.prices.ports import PriceSource
from app.core.settings import Settings
from app.db.models import PriceSnapshot, VendorRate
from app.finance import repo
from app.finance.quote_lines import QuoteFacts
from app.finance.references import Fresh, ReferencePlan, fresh_from, plan_lines, plan_lump_sum
from app.finance.repo_quotes import NewQuoteLine
from app.finance.review_types import REFERENCE_CURRENCY

MAX_FRESH_KEYS = 10


def units_of(lines: Sequence[NewQuoteLine]) -> dict[str, str]:
    units: dict[str, str] = {}
    for line in lines:
        units.setdefault(line.item_key, line.unit)
    return units


def _vendor_cards(
    session: Session, company_id: UUID, vendor_id: UUID | None, wanted: dict[str, str],
    snaps: dict[str, PriceSnapshot], on: date,
) -> dict[str, Decimal | None]:  # fmt: skip
    """The QUOTING vendor's EUR card per item: the snapshot's (immutable) card when it is that vendor's own, else the
    vendor's card valid on `on` (the decision date), else None. `wanted` = item key → unit."""
    if vendor_id is None:
        return {}
    ids = [s.rate_card_id for s in snaps.values() if s.rate_card_id is not None]
    own = set(
        session.scalars(
            select(VendorRate.id).where(
                VendorRate.company_id == company_id, VendorRate.person_id == vendor_id, VendorRate.id.in_(ids)
            )
        )
    )
    cards: dict[str, Decimal | None] = {}
    for key, unit in wanted.items():
        snap = snaps.get(key)
        if snap is not None and snap.rate_card_id in own:
            cards[key] = snap.rate_card_amount
            continue
        card = repo.current_rate(session, company_id, vendor_id, key, unit, on)
        cards[key] = card.amount if card is not None and card.currency.upper() == REFERENCE_CURRENCY else None
    return cards


def gather_references(
    engine: Engine, settings: Settings, source: PriceSource, facts: QuoteFacts, case_id: UUID,
    vendor_id: UUID | None, today: date,
) -> ReferencePlan:  # fmt: skip
    """Snapshots and the vendor's cards from the DB (session closed), then at most MAX_FRESH_KEYS fresh lookups."""
    cid, on, min_samples = facts.company_id, facts.quote_date, settings.finance_min_samples
    units = units_of(facts.lines)
    with Session(engine) as session:
        if facts.lump_sum:
            case_snaps = {s.item_key: s for s in repo.snapshots_for_case(session, cid, case_id, on)}
            decided = min((s.as_of for s in case_snaps.values()), default=on)
            wanted = {k: s.unit for k, s in case_snaps.items()}
            cards = _vendor_cards(session, cid, vendor_id, wanted, case_snaps, decided)
            return plan_lump_sum(list(case_snaps.values()), cards, quote_date=on, min_samples=min_samples)
        snaps = {k: s for k in units if (s := repo.snapshot_for(session, cid, case_id, k, on)) is not None}
        wanted = {k: snaps[k].unit if k in snaps else u for k, u in units.items()}
        decided = min((s.as_of for s in snaps.values()), default=on)
        cards = _vendor_cards(session, cid, vendor_id, wanted, snaps, decided)
    looked = dict(list(wanted.items())[:MAX_FRESH_KEYS])
    if len(looked) <= 1:
        fresh: dict[str, Fresh] = {
            k: fresh_from(source.lookup(k, u, today), u, vat_rate=settings.finance_vat_rate, min_samples=min_samples)
            for k, u in looked.items()
        }
    else:
        with ThreadPoolExecutor(max_workers=min(3, len(looked))) as pool:
            items = list(looked.items())
            results = list(pool.map(lambda kv: source.lookup(kv[0], kv[1], today), items))
        fresh = {
            k: fresh_from(obs, u, vat_rate=settings.finance_vat_rate, min_samples=min_samples)
            for (k, u), obs in zip(items, results, strict=True)
        }
    return plan_lines(units, snaps, cards, fresh, quote_date=on, min_samples=min_samples)
