"""Insert owner-feed rows. The dashboard feed is DB-only: no window, outbox, Send row or provider call."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.channels.dashboard.render import to_payload
from app.contracts import OwnerMessage
from app.db.enums import FeedKind
from app.db.models import OwnerFeed

_APPROVAL_PREFIXES = ("approval:", "apr:")
_ALERT_PREFIXES = ("blocked:", "nudge:", "alert")
_BRIEFING_PREFIXES = ("brief", "weekly")


def kind_for_key(key: str) -> FeedKind:
    """approval:/apr: -> approval, doc: -> document_review, brief/weekly -> briefing,
    blocked:/nudge:/alert -> alert, everything else -> alert."""
    if key.startswith(_APPROVAL_PREFIXES):
        return FeedKind.approval
    if key.startswith("doc:"):
        return FeedKind.document_review
    if key.startswith(_BRIEFING_PREFIXES):
        return FeedKind.briefing
    return FeedKind.alert


def ref_for_key(key: str, kind: FeedKind) -> UUID | None:
    """The approval or attachment id carried in `approval:{uuid}:n` / `apr:{uuid}:c` / `doc:{uuid}:c`."""
    if kind not in (FeedKind.approval, FeedKind.document_review):
        return None
    _, _, rest = key.partition(":")
    try:
        return UUID(rest.split(":", 1)[0])
    except ValueError:
        return None


def deliver(
    session: Session, company_id: UUID, key: str, kind: FeedKind, ref_id: UUID | None, message: OwnerMessage
) -> UUID:
    """Idempotent on `key`: a replay inserts nothing and returns the existing row id (company-scoped)."""
    session.execute(
        insert(OwnerFeed)
        .values(company_id=company_id, idempotency_key=key, kind=kind, ref_id=ref_id, payload=to_payload(message))
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    return session.execute(
        select(OwnerFeed.id).where(OwnerFeed.company_id == company_id, OwnerFeed.idempotency_key == key)
    ).scalar_one()
