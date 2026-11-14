"""BRIXX go-live check (ADR 0010): the real Data API answers with this token from this machine's IP.

Needs `BRIXX_PROVIDER=api` and a real `BRIXX_TOKEN`: until they are set, `make live-check k=brixx` stops before any
call and lists what is missing. Reads metadata only (table list and one table's description), never row data, so it
is safe against the production BRIXX environment. A 401 here means the token, the header form (BRIXX_AUTH_SCHEME
raw|bearer) or the IP whitelist — see docs/go-live-channels.md.
"""

import pytest

from app.channels.registry import brixx_api
from app.core.settings import Settings


@pytest.mark.live("BRIXX_PROVIDER", "BRIXX_TOKEN")
def test_brixx_real_api_lists_tables_and_describes_one(live_settings: Settings) -> None:
    api = brixx_api(live_settings)
    tables = api.list_tables()
    assert tables, "BRIXX returned no readable tables: check the token's permissions"
    name, primary_key = tables[0]
    assert name
    assert primary_key
    described = api.describe_table(name)
    assert described.fields, f"BRIXX described {name} without fields"
