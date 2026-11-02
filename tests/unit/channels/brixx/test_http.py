import logging
from typing import Literal

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.channels.brixx.http import HttpBrixxApi
from app.core.errors import BrixxAuthError, BrixxError

BASE = "https://brixx.test/api/v1"
TOKEN = "s3cr3t-token-value"


def _api(scheme: Literal["raw", "bearer"] = "bearer") -> HttpBrixxApi:
    return HttpBrixxApi(BASE, "hrrealestate", SecretStr(TOKEN), scheme, 5.0, client=httpx.Client())


@respx.mock
def test_list_tables_parses_names_and_pk() -> None:
    route = respx.get(f"{BASE}/metadata/hrrealestate/tables").respond(
        200, json=[{"name": "PRG_RELATIE", "primaryKeyField": "PRG_RELATIEID"}]
    )
    assert _api().list_tables() == [("PRG_RELATIE", "PRG_RELATIEID")]
    assert route.call_count == 1


@respx.mock
def test_describe_table_parses_fields_and_fk() -> None:
    route = respx.get(f"{BASE}/metadata/hrrealestate/tables/prg_contract").respond(
        200,
        json={
            "name": "PRG_CONTRACT",
            "primaryKeyField": "PRG_CONTRACTID",
            "fields": [
                {"id": 1, "name": "PRG_CONTRACTID", "type": "NUMBER", "required": True},
                {
                    "id": 2,
                    "name": "RELATIEID",
                    "type": "NUMBER",
                    "required": False,
                    "references": {"foreignKeyTable": "PRG_RELATIE", "foreignKeyField": "PRG_RELATIEID"},
                },
            ],
        },
    )
    table = _api().describe_table("PRG_CONTRACT")
    assert route.call_count == 1
    assert table.name == "PRG_CONTRACT"
    assert table.primary_key == "PRG_CONTRACTID"
    pk, fk = table.fields
    assert (pk.id, pk.type, pk.required, pk.fk_table, pk.fk_field) == (1, "NUMBER", True, None, None)
    assert (fk.fk_table, fk.fk_field, fk.required) == ("PRG_RELATIE", "PRG_RELATIEID", False)


@respx.mock
def test_fetch_page_follows_has_next() -> None:
    route = respx.get(f"{BASE}/bigdata/hrrealestate/table/prg_relatie")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "meta": {"currentPage": 1, "perPage": 2},
                "links": {"next": "https://brixx.test/next"},
                "data": [{"PRG_RELATIEID": 1, "website": {}}, {"PRG_RELATIEID": 2, "website": "x"}],
            },
        ),
        httpx.Response(
            200, json={"meta": {"currentPage": 2, "perPage": 2}, "links": {}, "data": [{"PRG_RELATIEID": 3}]}
        ),
    ]
    api = _api()
    first = api.fetch_page("PRG_RELATIE", page=1, filters="[upddatetime >= 2024-01-01]", order_by="upddatetime")
    assert first.has_next is True
    assert (first.page, first.per_page) == (1, 2)
    assert first.rows[0] == {"PRG_RELATIEID": 1, "website": None}
    sent = route.calls[0].request.url.params
    assert sent["page"] == "1"
    assert sent["filters"] == "[upddatetime >= 2024-01-01]"
    assert sent["orderby"] == "upddatetime"
    last = api.fetch_page("PRG_RELATIE", page=2)
    assert last.has_next is False
    assert last.rows == [{"PRG_RELATIEID": 3}]


@respx.mock
@pytest.mark.parametrize(("scheme", "expected"), [("bearer", f"Bearer {TOKEN}"), ("raw", TOKEN)])
def test_auth_header_bearer_and_raw(scheme: Literal["raw", "bearer"], expected: str) -> None:
    route = respx.get(f"{BASE}/metadata/hrrealestate/tables").respond(200, json=[])
    _api(scheme).list_tables()
    assert route.calls[0].request.headers["Authorization"] == expected


@respx.mock
@pytest.mark.parametrize("status", [401, 403])
def test_401_raises_auth_error_without_retry(status: int) -> None:
    route = respx.get(f"{BASE}/metadata/hrrealestate/tables").respond(status, text=f"denied {TOKEN}")
    with pytest.raises(BrixxAuthError) as exc:
        _api().list_tables()
    assert route.call_count == 1
    assert TOKEN not in str(exc.value)
    assert TOKEN not in repr(exc.value)
    assert str(status) in str(exc.value)


@respx.mock
def test_5xx_raises_brixx_error() -> None:
    route = respx.get(f"{BASE}/bigdata/hrrealestate/table/prg_relatie").respond(503, text="secret body")
    with pytest.raises(BrixxError) as exc:
        _api().fetch_page("PRG_RELATIE", page=1, filters="[zoekid = 123]")
    assert not isinstance(exc.value, BrixxAuthError)
    assert route.call_count == 1
    assert "503" in str(exc.value)
    assert "secret body" not in str(exc.value)
    assert "zoekid" not in str(exc.value)


@respx.mock
def test_transport_error_and_bad_json_raise_brixx_error() -> None:
    route = respx.get(f"{BASE}/metadata/hrrealestate/tables")
    route.mock(side_effect=httpx.ConnectError("boom " + TOKEN))
    with pytest.raises(BrixxError) as exc:
        _api().list_tables()
    assert TOKEN not in str(exc.value)
    route.mock(return_value=httpx.Response(200, text="not json"))
    with pytest.raises(BrixxError):
        _api().list_tables()


@respx.mock
def test_download_document_returns_bytes() -> None:
    respx.get(f"{BASE}/bigdata/hrrealestate/document/42").respond(200, content=b"%PDF-1.7")
    assert _api().download_document(42) == b"%PDF-1.7"


def test_table_name_is_validated_for_the_path() -> None:
    with pytest.raises(BrixxError):
        _api().fetch_page("../../x", page=1)


def test_http_base_url_rejected_without_injected_client() -> None:
    with pytest.raises(BrixxError):
        HttpBrixxApi("http://brixx.test/api/v1", "hrrealestate", SecretStr(TOKEN), "bearer", 5.0)


def test_https_base_url_accepted_and_repr_hides_token() -> None:
    api = HttpBrixxApi(BASE, "hrrealestate", SecretStr(TOKEN), "bearer", 5.0)
    assert TOKEN not in repr(api)


@respx.mock
@pytest.mark.parametrize("body", [{}, {"error": "x"}, {"data": "nope"}])
def test_data_page_without_data_list_raises(body: dict[str, object]) -> None:
    respx.get(f"{BASE}/bigdata/hrrealestate/table/prg_relatie").respond(200, json=body)
    with pytest.raises(BrixxError):
        _api().fetch_page("PRG_RELATIE", page=1)


@respx.mock
def test_empty_data_list_is_a_legitimate_empty_page() -> None:
    respx.get(f"{BASE}/bigdata/hrrealestate/table/prg_relatie").respond(200, json={"data": []})
    page = _api().fetch_page("PRG_RELATIE", page=1)
    assert page.rows == []
    assert page.has_next is False


@respx.mock
def test_httpx_loggers_are_quiet_and_filter_values_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    api = HttpBrixxApi(BASE, "hrrealestate", SecretStr(TOKEN), "bearer", 5.0)
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
    respx.get(f"{BASE}/bigdata/hrrealestate/table/prg_relatie").respond(200, json={"data": []})
    api.fetch_page("PRG_RELATIE", page=1, filters="[zoekid = 123456789]")
    assert "123456789" not in caplog.text
