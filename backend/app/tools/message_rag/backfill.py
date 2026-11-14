"""Backfill script to index existing messages into Message RAG."""

from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.db.models import MessageRow
from app.tools.message_rag.indexer import index_message

log = get_logger(__name__)


def backfill_messages(
    engine: Engine,
    settings: Settings,
    company_id: UUID | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Runs through all existing messages and indexes them into Message RAG."""
    with Session(engine) as session:
        stmt = select(MessageRow.id).order_by(MessageRow.sent_at.asc())
        if company_id is not None:
            stmt = stmt.where(MessageRow.company_id == company_id)
        if limit is not None:
            stmt = stmt.limit(limit)
        msg_ids = list(session.scalars(stmt).all())

    stats = {"indexed": 0, "skipped": 0, "failed": 0, "total": len(msg_ids)}
    log.info("message_rag.backfill.start", total=len(msg_ids))

    for mid in msg_ids:
        try:
            status = index_message(engine, settings, mid)
            stats[status] = stats.get(status, 0) + 1
        except Exception as exc:
            log.error("message_rag.backfill.error", message_id=str(mid), error=str(exc))
            stats["failed"] += 1

    log.info("message_rag.backfill.done", **stats)
    return stats


if __name__ == "__main__":
    from app.db.session import make_engine

    settings = get_settings()
    engine = make_engine(str(settings.database_url))
    backfill_messages(engine, settings)
