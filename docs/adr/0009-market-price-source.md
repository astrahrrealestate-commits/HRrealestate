# 0009 — Market price source for the Quote Checker

Status: proposed (needs the user's pick of a provider before a real run; the build uses the fake)

## Context
The Quote Checker needs market prices for maintenance items (Dutch and English), with a source per number. Web pages
only show today's prices, so history comes from our own dated snapshots (spec 2026-10-31), not from the source.

## Decision
- A `PriceSource` port (`app/finance/ports.py`): `lookup(item, region, as_of) -> list[PriceObservation]` where an
  observation is amount, unit, vat flag, source name, URL, observed date. No observation without a URL or the
  value `owner`.
- Adapters: `FakePriceSource` (deterministic, tests, default while `PRICE_SOURCE=fake`), `ManualPriceSource`
  (competitor quotes Harjot enters, always usable), and one web adapter chosen below.
- Web adapter, default proposal: a search/scrape API behind `httpx` with a Pydantic AI extraction step that turns page
  text into `PriceObservation` (page text is untrusted data; the extractor has no tools). Candidates: Firecrawl search
  (already used in this workspace), Tavily, Brave Search API. Provider is a setting; **user to pick and supply a key**.
- Prod boot refuses `PRICE_SOURCE=fake`, like the LLM and Drive settings.

## Consequences
- No scraping code of our own beyond the adapter; retries and scheduling stay in DBOS.
- Cost per snapshot = items × one lookup; bounded by a per-company daily lookup cap (setting, default 40).
- Numbers are only as good as sources: `min_samples` (3) and outlier trimming guard it, low confidence is shown.

## Implementation status (M11)
Built and tested offline: the `SearchClient` port (`app/channels/prices/search.py`, with `FakeSearchClient` over
recorded pages and `UnconfiguredSearchClient`), `WebPriceSource` (`app/channels/prices/web.py`: URL from the search
hit, evidence must occur in the page, EUR only, unit must match, one observation per URL, domain allow-list) and the
`price_extractor` agent (prompt `v1`, page text only as escaped data). Settings: `PRICE_SEARCH_PROVIDER` (`none` |
`fake`) and `PRICE_ALLOWED_DOMAINS`; prod refuses `PRICE_SOURCE=web` while the provider is `none` or `fake`.
Only a `SearchClient` implementation and its API key remain (Firecrawl, Tavily or Brave Search): one new class, one
new `price_search_provider` literal and its case in `app/channels/registry.py:search_client`, then
`make live-check k=prices`. Status stays `proposed` until the provider is picked.
