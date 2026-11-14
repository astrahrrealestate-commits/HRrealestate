"""WebPriceSource over a recorded SearchClient: R27 (URL from the hit, evidence in the page, EUR, unit, one per URL),
R28 (VAT unknown means included), page-level failure isolation, domain allow-list, hit budget."""

import json
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.channels.prices.search import FakeSearchClient, SearchClient, SearchHit, UnconfiguredSearchClient
from app.channels.prices.web import WebPriceSource
from app.contracts import ExtractedPrice, ExtractedPrices
from app.core.errors import PriceSourceNotConfiguredError

AS_OF = date(2026, 11, 2)
FIXTURE = Path(__file__).parents[2] / "fixtures" / "prices" / "search_hits.json"
BOILER = "https://www.cvketel-service.example/tarieven"
PAGE = "Het onderhoud van uw ketel kost € 89,00 per beurt inclusief BTW. Bel ons voor een afspraak."


def _price(
    amount: str = "89.00",
    *,
    unit: str = "job",
    currency: str = "EUR",
    vat: bool | None = True,
    evidence: str = "kost € 89,00 per beurt",
) -> ExtractedPrice:
    return ExtractedPrice.model_validate(
        {"amount": {"amount": amount, "currency": currency}, "unit": unit, "vat_included": vat, "evidence": evidence}
    )


def _hit(url: str = BOILER, text: str = PAGE) -> SearchHit:
    return SearchHit(url=url, title="Tarieven", text=text)


class Pages:
    """A search client serving fixed hits for every query, recording each call."""

    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, str, int]] = []

    def search(self, query: str, *, region: str, limit: int) -> list[SearchHit]:
        self.calls.append((query, region, limit))
        return self.hits[:limit]


def _extract(by_url: dict[str, list[ExtractedPrice]]) -> Callable[[SearchHit, str, str], ExtractedPrices]:
    def run(hit: SearchHit, item_key: str, unit: str) -> ExtractedPrices:
        return ExtractedPrices(prices=by_url.get(hit.url, []))

    return run


def _source(
    hits: list[SearchHit],
    extract: Callable[[SearchHit, str, str], ExtractedPrices],
    allowed_domains: Sequence[str] = (),
) -> WebPriceSource:
    search: SearchClient = Pages(hits)
    return WebPriceSource(search, extract, allowed_domains=allowed_domains)


def test_web_source_returns_observation_per_url_with_source_name_and_url() -> None:
    other = "https://shop.bouwmaterialen.example/diensten/ketel"
    source = _source(
        [_hit(), _hit(other)],
        _extract({BOILER: [_price()], other: [_price()]}),
    )
    got = source.lookup("boiler_service", "job", AS_OF)
    assert [(o.url, o.source) for o in got] == [
        (BOILER, "cvketel-service.example"),
        (other, "shop.bouwmaterialen.example"),
    ]
    assert [o.amount for o in got] == [Decimal("89.00")] * 2
    assert all(o.observed_on == AS_OF and o.unit == "job" for o in got)


def test_observation_uses_the_search_hit_url_never_one_from_the_model() -> None:
    forged = _price(evidence="kost € 89,00 per beurt")
    got = _source([_hit()], _extract({BOILER: [forged]})).lookup("boiler_service", "job", AS_OF)
    assert [o.url for o in got] == [BOILER]


@pytest.mark.parametrize("url", ["", "ftp://x.example/p", "javascript:alert(1)", "www.example/p", "https:///nohost"])
def test_page_without_https_url_is_dropped(url: str) -> None:
    got = _source([_hit(url)], _extract({url: [_price()]})).lookup("boiler_service", "job", AS_OF)
    assert got == []


def test_http_url_is_kept() -> None:
    url = "http://old-shop.example/p"
    got = _source([_hit(url)], _extract({url: [_price()]})).lookup("boiler_service", "job", AS_OF)
    assert [o.url for o in got] == [url]


def test_evidence_not_in_the_page_is_dropped() -> None:
    made_up = _price(evidence="de prijs is € 89,00 voor iedereen")
    assert _source([_hit()], _extract({BOILER: [made_up]})).lookup("boiler_service", "job", AS_OF) == []


def test_evidence_matches_after_whitespace_and_case_normalisation() -> None:
    evidence = "KOST  € 89,00\nper   BEURT"
    got = _source([_hit()], _extract({BOILER: [_price(evidence=evidence)]})).lookup("boiler_service", "job", AS_OF)
    assert len(got) == 1


def test_evidence_must_carry_the_amount() -> None:
    wrong_amount = _price("1.00", evidence="kost € 89,00 per beurt")
    assert _source([_hit()], _extract({BOILER: [wrong_amount]})).lookup("boiler_service", "job", AS_OF) == []


def test_evidence_amount_with_thousands_separator_matches() -> None:
    text = "Een complete renovatie kost € 1.250,00 per project."
    price = _price("1250.00", evidence="kost € 1.250,00 per project")
    got = _source([_hit(text=text)], _extract({BOILER: [price]})).lookup("boiler_service", "job", AS_OF)
    assert [o.amount for o in got] == [Decimal("1250.00")]


def test_non_eur_amounts_are_dropped() -> None:
    usd = _price(currency="USD")
    assert _source([_hit()], _extract({BOILER: [usd]})).lookup("boiler_service", "job", AS_OF) == []


def test_unit_mismatch_is_dropped_and_equivalent_units_match() -> None:
    per_m2 = _price(unit="m²")
    assert _source([_hit()], _extract({BOILER: [per_m2]})).lookup("painting", "hour", AS_OF) == []
    dutch_hour = _price(unit="per uur")
    got = _source([_hit()], _extract({BOILER: [dutch_hour]})).lookup("plumbing", "hour", AS_OF)
    assert len(got) == 1
    assert got[0].unit == "hour"


def test_first_valid_price_per_url_wins_and_invalid_ones_are_skipped() -> None:
    prices = [_price(currency="USD"), _price("89.00"), _price("90.00", evidence="kost € 89,00 per beurt")]
    got = _source([_hit()], _extract({BOILER: prices})).lookup("boiler_service", "job", AS_OF)
    assert [o.amount for o in got] == [Decimal("89.00")]


def test_unknown_vat_is_treated_as_included() -> None:
    cases = {True: True, False: False, None: True}
    for given, expected in cases.items():
        got = _source([_hit()], _extract({BOILER: [_price(vat=given)]})).lookup("boiler_service", "job", AS_OF)
        assert got[0].vat_included is expected


def test_one_failing_page_skips_only_that_page() -> None:
    other = "https://second.example/p"

    def run(hit: SearchHit, item_key: str, unit: str) -> ExtractedPrices:
        if hit.url == BOILER:
            raise RuntimeError("model said: SECRET PAGE TEXT")
        return ExtractedPrices(prices=[_price()])

    got = _source([_hit(), _hit(other)], run).lookup("boiler_service", "job", AS_OF)
    assert [o.url for o in got] == [other]


def test_extractor_failure_is_logged_by_type_without_page_text(capsys: pytest.CaptureFixture[str]) -> None:
    def run(hit: SearchHit, item_key: str, unit: str) -> ExtractedPrices:
        raise ValueError("SECRET PAGE TEXT")

    _source([_hit(text="SECRET PAGE TEXT")], run).lookup("boiler_service", "job", AS_OF)
    out = capsys.readouterr()
    assert "ValueError" in out.out + out.err
    assert "SECRET PAGE TEXT" not in out.out + out.err


def test_allowed_domains_filter_skips_other_hosts_without_calling_the_extractor() -> None:
    other = "https://not-allowed.example/p"
    sub = "https://shop.cvketel-service.example/p"
    seen: list[str] = []

    def run(hit: SearchHit, item_key: str, unit: str) -> ExtractedPrices:
        seen.append(hit.url)
        return ExtractedPrices(prices=[_price()])

    source = _source([_hit(), _hit(other), _hit(sub)], run, allowed_domains=["CVKetel-Service.example"])
    got = source.lookup("boiler_service", "job", AS_OF)
    assert seen == [BOILER, sub]
    assert [o.url for o in got] == [BOILER, sub]


def test_empty_allowed_domains_allows_every_host() -> None:
    got = _source([_hit()], _extract({BOILER: [_price()]}), allowed_domains=[]).lookup("boiler_service", "job", AS_OF)
    assert len(got) == 1


def test_max_hits_bounds_pages_across_both_queries() -> None:
    hits = [_hit(f"https://site{i}.example/p") for i in range(20)]
    search = Pages(hits)
    seen: list[str] = []

    def run(hit: SearchHit, item_key: str, unit: str) -> ExtractedPrices:
        seen.append(hit.url)
        return ExtractedPrices(prices=[])

    WebPriceSource(search, run, max_hits=5).lookup("boiler_service", "job", AS_OF)
    assert len(seen) == len(set(seen)) <= 5
    assert sum(limit for _q, _r, limit in search.calls) <= 5 + 1  # first query takes the larger half


def test_queries_are_dutch_and_english_from_the_humanised_item_key() -> None:
    search = Pages([])
    WebPriceSource(search, _extract({})).lookup("boiler_service", "job", AS_OF)
    assert [q for q, _r, _l in search.calls] == ["boiler service prijs Nederland", "boiler service price Netherlands"]
    assert {r for _q, r, _l in search.calls} == {"NL"}


def test_the_same_page_from_both_queries_is_read_once() -> None:
    calls: list[str] = []

    def run(hit: SearchHit, item_key: str, unit: str) -> ExtractedPrices:
        calls.append(hit.url)
        return ExtractedPrices(prices=[_price()])

    got = _source([_hit()], run).lookup("boiler_service", "job", AS_OF)
    assert calls == [BOILER]
    assert len(got) == 1


def test_unconfigured_client_raises_clear_error() -> None:
    source = WebPriceSource(UnconfiguredSearchClient(), _extract({}))
    with pytest.raises(PriceSourceNotConfiguredError, match="PRICE_SEARCH_PROVIDER"):
        source.lookup("boiler_service", "job", AS_OF)


def test_fake_search_client_serves_the_recorded_fixture_by_default() -> None:
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    hits = FakeSearchClient().search("anything", region="NL", limit=50)
    assert [{"url": h.url, "title": h.title, "text": h.text} for h in hits] == recorded
    assert len(FakeSearchClient().search("anything", region="NL", limit=2)) == 2


def test_fake_search_client_takes_explicit_pages() -> None:
    page = _hit()
    assert FakeSearchClient([page]).search("q", region="NL", limit=8) == [page]
