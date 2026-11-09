"""Synthetic BRIXX directory tables (relatie, object, VHE, contract) for mapper, reconcile and erasure tests.

Column names follow the API doc examples (`PRG_RELATIEID`, `ZOEKID`, `WEERGAVENAAM`, `INDVERWIJDERD`); the rest are
the mapper's first candidate names. Every value is invented: no real names, numbers or ZOEKIDs.
"""

from typing import Any

from app.channels.brixx.models import BrixxField, BrixxTable


def _info(name: str, pk: str, columns: list[tuple[str, str]], fks: dict[str, str] | None = None) -> BrixxTable:
    fields = [BrixxField(1, pk, "NUMBER", True, None, None)]
    for index, (column, kind) in enumerate(columns, start=2):
        target = (fks or {}).get(column)
        fields.append(BrixxField(index, column, kind, False, target, column if target else None))
    return BrixxTable(name, pk, tuple(fields))


_AUDIT = [("VERSIENR", "NUMBER"), ("NEWDATETIME", "TIMESTAMP(6)"), ("UPDDATETIME", "TIMESTAMP(6)")]
_RELATIE_COLUMNS = [
    ("WEERGAVENAAM", "VARCHAR(200)"),
    ("ZOEKID", "VARCHAR(12)"),
    ("EMAIL", "VARCHAR(200)"),
    ("MOBIELNR", "VARCHAR(30)"),
    ("INDVERWIJDERD", "NUMBER"),
    *_AUDIT,
]
_ADDRESS = [
    ("STRAATNM", "VARCHAR(100)"),
    ("HUISNR", "VARCHAR(10)"),
    ("POSTCODE", "VARCHAR(10)"),
    ("PLAATSNM", "VARCHAR(60)"),
]
_PERIOD = [("INGANGSDT", "DATE"), ("EINDDT", "DATE")]

RELATIE = _info("PRG_RELATIE", "PRG_RELATIEID", _RELATIE_COLUMNS)
ZRELATIE = _info(
    "ZPRG_RELATIE", "ZPRG_RELATIEID", [("PRG_RELATIEID", "NUMBER"), *_RELATIE_COLUMNS], {"PRG_RELATIEID": "PRG_RELATIE"}
)
OBJECT = _info(
    "PRG_OBJECT", "PRG_OBJECTID", [("OBJECTNR", "VARCHAR(30)"), *_ADDRESS, ("INDVERWIJDERD", "NUMBER"), *_AUDIT]
)
VHE = _info(
    "PRG_VHE",
    "PRG_VHEID",
    [("PRG_OBJECTID", "NUMBER"), ("VHENR", "VARCHAR(30)"), *_ADDRESS, ("INDVERWIJDERD", "NUMBER"), *_AUDIT],
    {"PRG_OBJECTID": "PRG_OBJECT"},
)
CONTRACT = _info(
    "PRG_CONTRACT",
    "PRG_CONTRACTID",
    [("PRG_RELATIEID", "NUMBER"), ("CONTRACTNR", "VARCHAR(30)"), *_PERIOD, ("INDVERWIJDERD", "NUMBER"), *_AUDIT],
    {"PRG_RELATIEID": "PRG_RELATIE"},
)
CONTRACTVHE = _info(
    "PRG_CONTRACTVHE",
    "PRG_CONTRACTVHEID",
    [("PRG_CONTRACTID", "NUMBER"), ("PRG_VHEID", "NUMBER"), *_PERIOD, ("INDVERWIJDERD", "NUMBER"), *_AUDIT],
    {"PRG_CONTRACTID": "PRG_CONTRACT", "PRG_VHEID": "PRG_VHE"},
)
DIRECTORY_TABLES = (RELATIE, ZRELATIE, OBJECT, VHE, CONTRACT, CONTRACTVHE)


def _audit(version: int) -> dict[str, object]:
    return {
        "INDVERWIJDERD": 0,
        "VERSIENR": version,
        "NEWDATETIME": "2026-01-05T10:00:00",
        "UPDDATETIME": f"2026-10-{min(version, 28):02d}T10:00:00",
    }


def _upper(extra: dict[str, object]) -> dict[str, object]:
    return {key.upper(): value for key, value in extra.items()}


def relatie(pk: int, name: str, *, version: int = 1, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "PRG_RELATIEID": pk,
        "WEERGAVENAAM": name,
        "ZOEKID": "000000000000",
        "EMAIL": None,
        "MOBIELNR": None,
        **_audit(version),
    }
    return {**row, **_upper(extra)}


def history(pk: int, relatie_id: int, name: str) -> dict[str, object]:
    return {"ZPRG_RELATIEID": pk, **relatie(relatie_id, name)}


def obj(pk: int, number: str, *, version: int = 1, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "PRG_OBJECTID": pk,
        "OBJECTNR": number,
        "STRAATNM": "Teststraat",
        "HUISNR": str(pk),
        "POSTCODE": "1000 AA",
        "PLAATSNM": "Voorbeeldstad",
        **_audit(version),
    }
    return {**row, **_upper(extra)}


def vhe(pk: int, object_id: int, number: str, *, version: int = 1, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "PRG_VHEID": pk,
        "PRG_OBJECTID": object_id,
        "VHENR": number,
        "STRAATNM": None,
        "HUISNR": None,
        "POSTCODE": None,
        "PLAATSNM": None,
        **_audit(version),
    }
    return {**row, **_upper(extra)}


def contract(pk: int, relatie_id: int, start: str, end: str | None = None, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "PRG_CONTRACTID": pk,
        "PRG_RELATIEID": relatie_id,
        "CONTRACTNR": f"C-{pk}",
        "INGANGSDT": start,
        "EINDDT": end,
        **_audit(1),
    }
    return {**row, **_upper(extra)}


def contract_vhe(pk: int, contract_id: int, vhe_id: int, start: str | None = None, **extra: object) -> dict[str, Any]:
    row: dict[str, object] = {
        "PRG_CONTRACTVHEID": pk,
        "PRG_CONTRACTID": contract_id,
        "PRG_VHEID": vhe_id,
        "INGANGSDT": start,
        "EINDDT": None,
        **_audit(1),
    }
    return {**row, **_upper(extra)}
