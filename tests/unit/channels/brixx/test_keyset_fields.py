"""Primary-key-only keyset scans (reconcile): `fields` projection and `[pk > cursor]` on the fake, query and HTTP."""

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.channels.brixx.fake import FakeBrixxApi, FakeTable
from app.channels.brixx.http import HttpBrixxApi
from app.channels.brixx.models import BrixxField, BrixxTable
from app.channels.brixx.query import data_query_params
from app.core.errors import BrixxError

BASE = "https://brixx.test/api/v1"
INFO = BrixxTable(
    "PRG_OBJECT",
    "PRG_OBJECTID",
    (
        BrixxField(1, "PRG_OBJECTID", "NUMBER", True, None, None),
        BrixxField(2, "NAAM", "VARCHAR(20)", False, None, None),
    ),
)


def _fake() -> FakeBrixxApi:
    rows: list[dict[str, object]] = [{"PRG_OBJECTID": i, "NAAM": f"o{i}"} for i in (5, 1, 9, 3)]
    return FakeBrixxApi({"PRG_OBJECT": FakeTable(INFO, rows)}, page_size=2)


def test_params_carry_fields_joined_with_plus() -> None:
    assert data_query_params(1, None, "id", fields=("PRG_OBJECTID", "NAAM")) == {
        "page": "1",
        "orderby": "id",
        "fields": "PRG_OBJECTID+NAAM",
    }


def test_fake_projects_fields_and_pages_by_keyset() -> None:
    api = _fake()
    first = api.fetch_page("PRG_OBJECT", page=1, order_by="prg_objectid", fields=("prg_objectid",))
    assert first.rows == [{"PRG_OBJECTID": 1}, {"PRG_OBJECTID": 3}]
    assert first.has_next
    after = api.fetch_page(
        "PRG_OBJECT", page=1, filters="[prg_objectid > 3]", order_by="prg_objectid", fields=("prg_objectid",)
    )
    assert after.rows == [{"PRG_OBJECTID": 5}, {"PRG_OBJECTID": 9}]
    assert not after.has_next


def test_fake_rejects_unknown_projection_column() -> None:
    with pytest.raises(BrixxError):
        _fake().fetch_page("PRG_OBJECT", page=1, fields=("nope",))


@respx.mock
def test_http_sends_fields_param() -> None:
    route = respx.get(f"{BASE}/bigdata/hrrealestate/table/prg_object").respond(
        200, json={"meta": {"currentPage": 1, "perPage": 2}, "links": {}, "data": [{"PRG_OBJECTID": 1}]}
    )
    api = HttpBrixxApi(BASE, "hrrealestate", SecretStr("t"), "bearer", 5.0, client=httpx.Client())
    page = api.fetch_page("PRG_OBJECT", page=1, filters="[prg_objectid > 0]", fields=("PRG_OBJECTID",))
    assert page.rows == [{"PRG_OBJECTID": 1}]
    params = route.calls.last.request.url.params
    assert params["fields"] == "PRG_OBJECTID"
    assert params["filters"] == "[prg_objectid > 0]"
