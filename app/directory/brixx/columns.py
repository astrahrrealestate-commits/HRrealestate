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
VHE, VHE_PK = "prg_vhe", "prg_vheid"
CONTRACT, CONTRACT_PK = "prg_contract", "prg_contractid"
CONTRACTVHE, CONTRACTVHE_PK = "prg_contractvhe", "prg_contractvheid"

NAME = ("weergavenaam", "weergavenaam2", "naam", "organisatienm", "achternaam")
EMAIL = ("email", "emailadres", "e_mail")
PHONE = ("mobielnr", "mobiel", "telefoonnr", "telefoon", "telefoonnr1", "telefoonnr2")
OBJECT_LABEL = ("objectnr", "omschrijving", "naam")
VHE_LABEL = ("vhenr", "omschrijving", "naam")
STREET = ("straatnm", "straat", "straatnaam")
HOUSE_NUMBER = ("huisnr", "huisnummer")
HOUSE_SUFFIX = ("huisnrtoev", "huisnrtoevoeging", "toevoeging")
POSTCODE = ("postcode",)
CITY = ("plaatsnm", "plaats", "woonplaats")
START = ("ingangsdt", "ingangsdatum", "begindt", "startdatum")
END = ("einddt", "einddatum")
CREATED = ("newdatetime",)
DELETED_FLAG = "indverwijderd"
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
        if value is not None:
            return value
    return None


def pick_text(row: Row | None, candidates: tuple[str, ...], limit: int) -> str | None:
    value = pick(row, candidates)
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
    flag = row.get(DELETED_FLAG)
    if isinstance(flag, bool):
        return flag
    return flag is not None and str(flag).strip().lower() in _TRUE_FLAGS | {"1.0"}


def address(row: Row | None, limit: int) -> str | None:
    """`<street> <number><suffix>, <postcode> <city>` from whatever parts are present."""
    street = " ".join(str(p) for p in (pick(row, STREET), pick(row, HOUSE_NUMBER)) if p is not None)
    suffix = pick(row, HOUSE_SUFFIX)
    line = f"{street}{suffix}" if street and suffix is not None else street
    place = " ".join(str(p) for p in (pick(row, POSTCODE), pick(row, CITY)) if p is not None)
    text = ", ".join(part for part in (line, place) if part)
    return text[:limit] or None
