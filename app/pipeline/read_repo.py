"""Read-side queries for the dashboard API. Every function requires `company_id` (CLAUDE.md invariant 4)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.core.errors import EstateOSError
from app.db.models.dashboard import OwnerFeed

MAX_PAGE = 100
Cursor = tuple[datetime, UUID]


class BadCursorError(EstateOSError):
    """A feed cursor that is not `{created_at_iso}|{id}` with a timezone-aware timestamp."""


def parse_cursor(raw: str) -> Cursor:
    stamp, sep, ident = raw.partition("|")
    try:
        if not sep:
            raise ValueError("missing separator")
        created_at = datetime.fromisoformat(stamp.replace(" ", "+"))  # a raw "+" in a query string decodes to " "
        if created_at.tzinfo is None:
            raise ValueError("naive timestamp")
        return created_at, UUID(ident)
    except ValueError:
        raise BadCursorError("invalid cursor") from None


def feed_page(session: Session, company_id: UUID, after: Cursor | None, limit: int) -> list[OwnerFeed]:
    q = select(OwnerFeed).where(OwnerFeed.company_id == company_id)
    if after is not None:
        q = q.where(tuple_(OwnerFeed.created_at, OwnerFeed.id) > tuple_(*after))
    capped = max(1, min(limit, MAX_PAGE))
    return list(session.scalars(q.order_by(OwnerFeed.created_at, OwnerFeed.id).limit(capped)))
