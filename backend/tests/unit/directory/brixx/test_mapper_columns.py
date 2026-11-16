"""Pure pieces of the BRIXX directory mapper: column pickers, end flags, addresses, identities, lease periods."""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.contracts import Channel
from app.directory.brixx import columns as col
from app.directory.brixx.leases import lease_period, lease_ref
from app.directory.brixx.map_common import changed, ended_on
from app.directory.brixx.people import contact_identities
from app.directory.brixx.units import unit_values

TODAY = date(2026, 11, 3)


def test_pick_takes_the_first_non_empty_candidate() -> None:
    row = {"weergavenaam": "  ", "weergavenaam2": "Invented Name", "naam": "Other"}
    assert col.pick(row, col.NAME) == "Invented Name"
    assert col.pick(row, ("missing",)) is None
    assert col.pick(None, col.NAME) is None
    assert col.pick_text({"naam": "x" * 300}, col.NAME, 200) == "x" * 200


def test_ints_and_dates_are_read_tolerantly() -> None:
    assert [col.as_int(v) for v in (7, "7", Decimal("7"), 7.0, 7.5, True, None, "x")] == [
        7,
        7,
        7,
        7,
        None,
        None,
        None,
        None,
    ]
    assert col.pick_date({"ingangsdt": "2026-02-01"}, col.START) == date(2026, 2, 1)
    assert col.pick_date({"ingangsdt": datetime(2026, 2, 1, 9, tzinfo=UTC)}, col.START) == date(2026, 2, 1)
    assert col.pick_date({"ingangsdt": "not a date"}, col.START) is None


def test_ended_means_reconcile_soft_delete_or_brixx_flag() -> None:
    assert col.is_ended({"_deleted_at": datetime(2026, 11, 1, tzinfo=UTC)})
    assert col.is_ended({"indverwijderd": 1})
    assert col.is_ended({"indverwijderd": Decimal("1")})
    assert col.is_ended({"indverwijderd": "J"})
    assert not col.is_ended({"indverwijderd": 0})
    assert not col.is_ended({"indverwijderd": None})
    assert not col.is_ended(None)


def test_address_joins_present_parts() -> None:
    row = {
        "straatnm": "Teststraat",
        "huisnr": "5",
        "huisnrtoev": "a",
        "postcode": "1000 AA",
        "plaatsnm": "Voorbeeldstad",
    }
    assert col.address(row, 300) == "Teststraat 5a, 1000 AA Voorbeeldstad"
    assert col.address({"plaatsnm": "Voorbeeldstad"}, 300) == "Voorbeeldstad"
    assert col.address({}, 300) is None


def test_contact_identities_are_normalised_and_invalid_ones_dropped() -> None:
    row = {"mobielnr": "06-12345678", "telefoonnr": "not a number", "email": "Someone@Example.TEST"}
    assert contact_identities(row) == [(Channel.whatsapp, "+31612345678"), (Channel.gmail, "someone@example.test")]
    assert contact_identities({"mobielnr": "06 12345678", "telefoonnr": "+31 6 12345678"}) == [
        (Channel.whatsapp, "+31612345678")
    ]


def test_unit_values_fall_back_to_the_object_then_a_generated_label() -> None:
    building = {"objectnr": "OBJ-1", "straatnm": "Teststraat", "huisnr": "1"}
    assert unit_values({"vhenr": "A"}, building, 9) == {"label": "A", "address": "Teststraat 1"}
    assert unit_values({}, building, 9) == {"label": "OBJ-1", "address": "Teststraat 1"}
    assert unit_values({}, None, 9) == {"label": "VHE 9", "address": None}


def test_lease_period_prefers_the_link_and_ends_ended_rows_by_today() -> None:
    contract = {"ingangsdt": "2026-01-01", "einddt": "2027-12-31"}
    assert lease_period({"ingangsdt": "2026-03-01"}, contract, TODAY) == (date(2026, 3, 1), date(2027, 12, 31))
    assert lease_period({}, contract | {"indverwijderd": 1}, TODAY) == (date(2026, 1, 1), TODAY)
    assert lease_period({}, {}, TODAY) == (TODAY, None)
    assert lease_ref(500, 900) == "500:900"


def test_ended_on_and_changed() -> None:
    assert ended_on(None, ended=False, today=TODAY) is None
    assert ended_on(date(2026, 1, 1), ended=True, today=TODAY) == date(2026, 1, 1)
    assert ended_on(date(2027, 1, 1), ended=True, today=TODAY) == TODAY

    class Target:
        label = "A"

    target = Target()
    assert not changed(target, label="A")
    assert changed(target, label="B")
    assert target.label == "B"


def test_address_reads_the_real_letter_toevoeging_and_city_columns() -> None:
    row = {"straatnm": "Teststraat", "huisnr": 5, "huisletter": "A", "huisnummertoev": "2", "postcode": "1000AA",
           "woonplaatsnm": "VOORBEELDSTAD"}  # fmt: skip
    assert col.address(row, 300) == "Teststraat 5A-2, 1000AA VOORBEELDSTAD"
    assert col.address({**row, "huisletter": None}, 300) == "Teststraat 52, 1000AA VOORBEELDSTAD"
    assert col.pick_text({"vhenr": Decimal("100000000100001.0")}, col.VHE_LABEL, 100) == "100000000100001"
