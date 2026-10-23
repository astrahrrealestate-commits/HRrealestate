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
_BRIEFING_PREFIXES = ("brief", "weekly")
_DOCUMENT_REVIEW_PREFIX = "docreview:"  # app.owner.cards.document_review_key (documents.review_card_step)


def kind_for_key(key: str) -> FeedKind:
    """approval:/apr: -> approval, docreview: -> document_review, brief/weekly -> briefing,
    blocked:/nudge:/alert -> alert, everything else -> alert."""
    if key.startswith(_APPROVAL_PREFIXES):
        return FeedKind.approval
    if key.startswith(_DOCUMENT_REVIEW_PREFIX):
        return FeedKind.document_review
    if key.startswith(_BRIEFING_PREFIXES):
        return FeedKind.briefing
    return FeedKind.alert


def ref_for_key(key: str, kind: FeedKind) -> UUID | None:
    """The approval or attachment id carried in `approval:{uuid}:n` / `apr:{uuid}:c` / `docreview:{uuid}`."""
    if kind not in (FeedKind.approval, FeedKind.document_review):
        return None
    _, _, rest = key.partition(":")
    try:
        return UUID(rest.split(":", 1)[0])
    except ValueError:
        return None


KEY_MAX = 255  # owner_feed.idempotency_key is String(255)


def stored_key(company_id: UUID, key: str) -> str:
    """The column is globally unique, so the key is namespaced by company (`{company_id}:{key}`). A too-long caller
    key is truncated, never the prefix."""
    prefix = f"{company_id}:"
    return prefix + key[: KEY_MAX - len(prefix)]


def existing(session: Session, company_id: UUID, key: str) -> UUID | None:
    """The feed row already delivered under `key`, so a replay can skip building the message at all."""
    return session.scalar(
        select(OwnerFeed.id).where(
            OwnerFeed.company_id == company_id, OwnerFeed.idempotency_key == stored_key(company_id, key)
        )
    )


def deliver(
    session: Session, company_id: UUID, key: str, kind: FeedKind, ref_id: UUID | None, message: OwnerMessage
) -> UUID:
    """Idempotent on (company, `key`): a replay inserts nothing and returns the existing row id."""
    stored = stored_key(company_id, key)
    session.execute(
        insert(OwnerFeed)
        .values(company_id=company_id, idempotency_key=stored, kind=kind, ref_id=ref_id, payload=to_payload(message))
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    return session.execute(
        select(OwnerFeed.id).where(OwnerFeed.company_id == company_id, OwnerFeed.idempotency_key == stored)
    ).scalar_one()
