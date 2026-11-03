from datetime import UTC, datetime

import pytest

from app.channels.brixx.fake import FakeBrixxApi, FakeTable
from app.channels.brixx.models import BrixxField, BrixxTable
from app.core.errors import BrixxAuthError, BrixxError


def _info(name: str = "PRG_RELATIE") -> BrixxTable:
    field = BrixxField(1, f"{name}ID", "NUMBER", True, None, None)
    return BrixxTable(name, f"{name}ID", (field,))


def _rows(n: int) -> list[dict[str, object]]:
    return [
        {"PRG_RELATIEID": i, "UPDDATETIME": datetime(2024, 1, i, 12, tzinfo=UTC).isoformat()} for i in range(1, n + 1)
    ]


def _fake(n: int = 5, page_size: int = 2) -> FakeBrixxApi:
    return FakeBrixxApi({"PRG_RELATIE": FakeTable(_info(), _rows(n))}, page_size=page_size)


def test_fake_lists_and_describes() -> None:
    api = _fake()
    assert api.list_tables() == [("PRG_RELATIE", "PRG_RELATIEID")]
    assert api.describe_table("prg_relatie").primary_key == "PRG_RELATIEID"
    with pytest.raises(BrixxError):
        api.describe_table("NOPE")


def test_fake_paginates() -> None:
    api = _fake(5, 2)
    pages = [api.fetch_page("PRG_RELATIE", page=p) for p in (1, 2, 3)]
    assert [len(p.rows) for p in pages] == [2, 2, 1]
    assert [p.has_next for p in pages] == [True, True, False]
    assert [p.per_page for p in pages] == [2, 2, 2]
    assert api.fetch_log == [("PRG_RELATIE", 1, None), ("PRG_RELATIE", 2, None), ("PRG_RELATIE", 3, None)]


def test_fake_incremental_filter() -> None:
    api = _fake(5, 10)
    page = api.fetch_page("PRG_RELATIE", page=1, filters="[upddatetime >= 2024-01-03]")
    assert [r["PRG_RELATIEID"] for r in page.rows] == [3, 4, 5]
    assert api.fetch_log[-1] == ("PRG_RELATIE", 1, "[upddatetime >= 2024-01-03]")


def test_fake_scripted_failure_is_one_shot_by_default() -> None:
    api = _fake(5, 2)
    api.fail_on("PRG_RELATIE", 2, BrixxAuthError("denied"))
    api.fetch_page("PRG_RELATIE", page=1)
    with pytest.raises(BrixxAuthError):
        api.fetch_page("PRG_RELATIE", page=2)
    assert len(api.fetch_page("PRG_RELATIE", page=2).rows) == 2
    assert [p for _, p, _ in api.fetch_log] == [1, 2, 2]


def test_fake_scripted_failure_can_persist() -> None:
    api = _fake()
    api.fail_on("PRG_RELATIE", 1, BrixxError("down"), once=False)
    for _ in range(2):
        with pytest.raises(BrixxError):
            api.fetch_page("PRG_RELATIE", page=1)


def test_fake_download_document() -> None:
    api = FakeBrixxApi({}, documents={7: b"pdf"})
    assert api.download_document(7) == b"pdf"
    with pytest.raises(BrixxError):
        api.download_document(8)


def test_fake_normalises_null_cells() -> None:
    rows: list[dict[str, object]] = [{"PRG_RELATIEID": 1, "website": {}}]
    api = FakeBrixxApi({"PRG_RELATIE": FakeTable(_info(), rows)})
    assert api.fetch_page("PRG_RELATIE", page=1).rows == [{"PRG_RELATIEID": 1, "website": None}]


@pytest.mark.parametrize(
    "filters", ["[name = abc]", "[upddatetime < 2024-01-03]", "[upddatetime >= 2024-01-03] and [id = 1]"]
)
def test_fake_rejects_filter_it_cannot_evaluate(filters: str) -> None:
    with pytest.raises(BrixxError):
        _fake().fetch_page("PRG_RELATIE", page=1, filters=filters)


@pytest.mark.parametrize("page", [0, -1])
def test_fake_rejects_page_below_one(page: int) -> None:
    with pytest.raises(BrixxError):
        _fake().fetch_page("PRG_RELATIE", page=page)


def test_fake_orders_numerically_by_column_and_records_it() -> None:
    rows: list[dict[str, object]] = [{"PRG_RELATIEID": i} for i in (10, 9, 100, 2)]
    api = FakeBrixxApi({"PRG_RELATIE": FakeTable(_info(), rows)}, page_size=10)
    page = api.fetch_page("PRG_RELATIE", page=1, order_by="prg_relatieid")
    assert [r["PRG_RELATIEID"] for r in page.rows] == [2, 9, 10, 100]
    assert api.order_log == ["prg_relatieid"]


def test_fake_without_order_keeps_insertion_order() -> None:
    rows: list[dict[str, object]] = [{"PRG_RELATIEID": i} for i in (3, 1, 2)]
    api = FakeBrixxApi({"PRG_RELATIE": FakeTable(_info(), rows)}, page_size=10)
    assert [r["PRG_RELATIEID"] for r in api.fetch_page("PRG_RELATIE", page=1).rows] == [3, 1, 2]
    assert api.order_log == [None]


def test_fake_rejects_unknown_order_column() -> None:
    with pytest.raises(BrixxError):
        _fake().fetch_page("PRG_RELATIE", page=1, order_by="nope")
