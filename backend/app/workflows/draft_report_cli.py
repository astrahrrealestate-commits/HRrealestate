"""`python -m app.workflows.draft_report_cli --company-id ID --days N`: the draft report, counts only (M13 T16).

Read-only. It prints categories, prompt versions, counts, minutes and cost; never message text, so its output may go
to CloudWatch. Run it before the 90-day purge (which deletes the rows it counts) and after the new drafts ship.
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.outcomes.draft_report import draft_report, render_report


def report_text(engine: Engine, company_id: UUID, days: int, now: datetime) -> str:
    with Session(engine) as session:
        report = draft_report(session, company_id, since=now - timedelta(days=days), until=now)
    return f"draft report, last {days} days until {now:%Y-%m-%d %H:%M} UTC\n{render_report(report)}"


def main(argv: Sequence[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-id", required=True, type=UUID)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args(argv)
    if engine is None:
        from app.core.settings import get_settings
        from app.db.session import make_engine

        engine = make_engine(get_settings().sqlalchemy_url)
    sys.stdout.write(report_text(engine, args.company_id, args.days, datetime.now(UTC)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
