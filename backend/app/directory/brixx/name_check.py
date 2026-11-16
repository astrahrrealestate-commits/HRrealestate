"""Compare the names the code reads (`names.READS`) with the live `brixx` mirror schema.

A table or column group BRIXX no longer sends would not raise: the readers find nothing and a screen shows a dash. The
mapping workflow runs this after every run and logs each gap as `brixx.name_gap` (names only, no row data).
"""

from collections.abc import Mapping

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.directory.brixx.names import READS


def compare(actual: Mapping[str, set[str]]) -> list[str]:
    """One line per table the code reads that is missing, and per column group of which no candidate exists."""
    gaps: list[str] = []
    for table, groups in sorted(READS.items()):
        columns = actual.get(table)
        if columns is None:
            gaps.append(f"{table}: table missing")
            continue
        gaps.extend(f"{table}: none of {', '.join(group)}" for group in groups if not columns & set(group))
    return gaps


def live_columns(session: Session) -> dict[str, set[str]]:
    rows = session.execute(
        sa.text("select table_name, column_name from information_schema.columns where table_schema = 'brixx'")
    )
    found: dict[str, set[str]] = {}
    for table, column in rows:
        found.setdefault(str(table), set()).add(str(column))
    return found


def name_gaps(session: Session) -> list[str]:
    return compare(live_columns(session))
