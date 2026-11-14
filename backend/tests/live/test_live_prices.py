"""Web price go-live check (ADR 0009): the connected search provider returns pages the extractor can read.

Needs a real `PRICE_SEARCH_PROVIDER` (not `none` or `fake`) and a real `LLM_MODEL`: until they are set,
`make live-check k=prices` stops before any call and lists what is missing. Costs one search and one small model
call per page. The extractor runs the published prompt directly (no database, like the LLM live check).
"""

from datetime import UTC, datetime

import pytest
from pydantic_ai import Agent

from app.channels.prices.search import SearchHit
from app.channels.prices.web import WebPriceSource
from app.channels.registry import search_client
from app.contracts import ExtractedPrices
from app.core.settings import Settings
from app.llm.agents.price_extractor import PRICE_EXTRACTOR, price_extractor_prompt
from app.llm.prompts import load_prompt
from app.llm.runtime import build_model


@pytest.mark.live("PRICE_SEARCH_PROVIDER", "LLM_MODEL")
def test_prices_real_provider_returns_checkable_boiler_service_prices(live_settings: Settings) -> None:
    agent = Agent(
        build_model(live_settings, PRICE_EXTRACTOR.name),
        output_type=ExtractedPrices,
        instructions=load_prompt(PRICE_EXTRACTOR.prompt).text,
        retries=2,
    )

    def extract(hit: SearchHit, item_key: str, unit: str) -> ExtractedPrices:
        return agent.run_sync(price_extractor_prompt(item_key, unit, hit.title, hit.text)).output

    source = WebPriceSource(search_client(live_settings), extract, allowed_domains=live_settings.price_allowed_domains)
    found = source.lookup("boiler_service", "job", datetime.now(UTC).date())
    assert found, "no observation: check the provider key, region and PRICE_ALLOWED_DOMAINS"
    assert all(o.url and o.url.startswith("http") and o.amount > 0 and o.source for o in found)
