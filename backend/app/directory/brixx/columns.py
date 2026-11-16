"""Mirror column vocabulary for the directory mapper, and tolerant readers for mirror rows.

The exact BRIXX column names are known only from the Phase B metadata snapshot (spec 2026-10-31, open item 3). Each
mapped field therefore lists candidate names; the first present, non-empty value wins, and a field none of them
matches falls back (a generated label, today's date) instead of failing the run. Table and key names come from the
API documentation (`PRG_RELATIE.PRG_RELATIEID`, `ZOEKID`, `INDVERWIJDERD`; the `<TABLE>ID` primary key convention).
"""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import psycopg.errors
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.db.brixx_erasure import mirror_table

Row = Mapping[str, object]

RELATIE, RELATIE_PK = "prg_relatie", "prg_relatieid"
OBJECT, OBJECT_PK = "prg_object", "prg_objectid"
# BRIXX's own API docs and the PDF spec call this entity "VHE" (verhuurbare eenheid, rentable unit), but the real
# hrrealestate environment names the table PRG_SUBOBJECT -- no PRG_VHE table exists anywhere in the live metadata
# (confirmed against the full 491-table real snapshot). PRG_CONTRACTVHE's own FK column to it is PRG_SUBOBJECTID,
# not PRG_VHEID, consistently. Kept the VHE_* constant names since the rest of the mapper (units.py, leases.py)
# and the domain model (Unit) use "VHE"/"unit" as the conceptual name regardless of BRIXX's table name for it.
VHE, VHE_PK = "prg_subobject", "prg_subobjectid"
CONTRACT, CONTRACT_PK = "prg_contract", "prg_contractid"
CONTRACTVHE, CONTRACTVHE_PK = "prg_contractvhe", "prg_contractvheid"
# The real PRG_CONTRACT has no PRG_RELATIEID: its relaties are PRG_CONTRACTRELATIE rows (VOLGNR 1 = the tenant,
# higher = co-tenants) and EERSTERELATIEID repeats the first one. PRG_RELATIEID stays last for the doc examples.
CONTRACTRELATIE = "prg_contractrelatie"
CONTRACT_TENANT = ("eersterelatieid", "prg_relatieid")
ORDER = ("volgnr",)

RELATIE_NUMBER = ("relatienrstr", "relatienr")
NAME = ("weergavenaam", "weergavenaam2", "naam", "organisatienm")
EMAIL = ("email", "emailadres", "e_mail")
PHONE = ("mobielnr", "mobiel", "telefoon1", "telefoon2", "telefoonnr", "telefoon", "telefoonnr1", "telefoonnr2")
# Display names first: the real VHENR/OBJECTNR are internal numbers (e.g. 100000000100001), WEERGAVENAAM2 is
# "Henry Dunantweg 5 A" and WEERGAVENAAM the same with the BRIXX number in front ("00001/001 Henry ...").
OBJECT_LABEL = ("weergavenaam2", "weergavenaam", "objectnm", "objectnr", "omschrijving", "naam")
VHE_LABEL = ("weergavenaam2", "weergavenaam", "subobjectnm", "vhenr", "omschrijving", "naam")
STREET = ("straatnm", "straat", "straatnaam")
HOUSE_NUMBER = ("huisnr", "huisnummer")
HOUSE_LETTER = ("huisletter",)
HOUSE_SUFFIX = ("huisnummertoev", "huisnrtoev", "huisnrtoevoeging", "toevoeging")
POSTCODE = ("postcode",)
CITY = ("woonplaatsnm", "plaatsnm", "plaats", "woonplaats")
START = ("ingangsdt", "ingangsdatum", "begindt", "startdatum")
END = ("einddt", "einddatum")
CREATED = ("newdatetime",)
DELETED_FLAG = "indverwijderd"
REDACTED = "--redacted"  # what BRIXX sends for personal data the API token may not read
_TRUE_FLAGS = frozenset({"1", "j", "y", "true", "ja", "yes"})


def read_mirror(session: Session, table: str, company_id: UUID) -> list[dict[str, object]] | None:
    """Every mirror row of `brixx.<table>` for the company, keyed by lower-case column; None if the table is missing."""
    mirror = mirror_table(table)
    query = sa.select(sa.text("*")).select_from(mirror).where(mirror.c.company_id == company_id)
    try:
        with session.begin_nested():
            found = session.execute(query).mappings().all()
    except ProgrammingError as exc:
        if isinstance(exc.orig, psycopg.errors.UndefinedTable | psycopg.errors.InvalidSchemaName):
            return None
        raise
    return [{str(k).lower(): v for k, v in row.items()} for row in found]


def pick(row: Row | None, candidates: tuple[str, ...]) -> object | None:
    """The first candidate column with a non-empty value."""
    if row is None:
        return None
    for name in candidates:
        value = row.get(name)
        if isinstance(value, str):
            value = value.strip() or None
            if value is not None and value.lower() == REDACTED:  # BRIXX withholds it from this API token
                value = None
        if value is not None:
            return value
    return None


def pick_text(row: Row | None, candidates: tuple[str, ...], limit: int) -> str | None:
    """As text; a whole number stored as NUMERIC reads "100000000100001", never "100000000100001.0"."""
    value = pick(row, candidates)
    if isinstance(value, float | Decimal) and value == int(value):
        value = int(value)
    return None if value is None else str(value)[:limit]


def as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float | Decimal) and value != int(value):
        return None
    try:
        return int(value) if isinstance(value, int | float | Decimal) else int(str(value).strip())
    except ValueError:
        return None


def pick_int(row: Row | None, candidates: tuple[str, ...]) -> int | None:
    return as_int(pick(row, candidates))


def pick_date(row: Row | None, candidates: tuple[str, ...]) -> date | None:
    value = pick(row, candidates)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


def is_ended(row: Row | None) -> bool:
    """Soft-deleted by the reconcile (`_deleted_at`) or by BRIXX itself (`INDVERWIJDERD`)."""
    if row is None:
        return False
    if row.get("_deleted_at") is not None:
        return True
    return is_flagged(row, DELETED_FLAG)


def is_flagged(row: Row, column: str) -> bool:
    """A BRIXX yes/no column (`0`/`1`, `J`/`N`, bool) that says yes."""
    flag = row.get(column)
    if isinstance(flag, bool):
        return flag
    return flag is not None and str(flag).strip().lower() in _TRUE_FLAGS | {"1.0"}


def address(row: Row | None, limit: int) -> str | None:
    """`<street> <number><suffix>, <postcode> <city>` from whatever parts are present."""
    street = " ".join(str(p) for p in (pick(row, STREET), pick(row, HOUSE_NUMBER)) if p is not None)
    letter, suffix = pick(row, HOUSE_LETTER), pick(row, HOUSE_SUFFIX)
    if street and letter is not None:  # "5A"; a toevoeging after a letter gets a dash ("5A-2")
        street = f"{street}{letter}"
    if street and suffix is not None:
        street = f"{street}-{suffix}" if letter is not None else f"{street}{suffix}"
    line = street
    place = " ".join(str(p) for p in (pick(row, POSTCODE), pick(row, CITY)) if p is not None)
    text = ", ".join(part for part in (line, place) if part)
    return text[:limit] or None
