"""What runs before a draft (M13 T8; lane A built the reading and the quote review, lane B adds research).

`prepare_for_draft` reads the message's attachments and reviews a contractor's quote, so the first draft sees the
attachment text and the review. Every part is idempotent and none ever fails the draft: the pipeline's later filing
and the asynchronous quote hook still run and catch up whatever this could not do.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import MessageRow
from app.finance.quotes import review_message
from app.finance.triggers import is_quote_candidate
from app.pipeline.draft_reading import read_attachments
from app.pipeline.draft_research import research_for
from app.workflows.deps import get_deps, get_extractor

log = get_logger(__name__)


def _review_quote(engine: Engine, settings: Settings, message_id: UUID) -> None:
    with Session(engine) as session:
        if not is_quote_candidate(session, message_id):
            return
    review_message(engine, settings, message_id, today=datetime.now(UTC).date())


def _research(engine: Engine, settings: Settings, message_id: UUID) -> None:
    with Session(engine) as session:
        msg = session.get(MessageRow, message_id)
        company_id = msg.company_id if msg is not None else None
    if company_id is not None:
        research_for(engine, settings, company_id, message_id)


def prepare_for_draft(engine: Engine, settings: Settings, message_id: UUID, *, research: bool = True) -> None:
    """Read attachments, review any quote, and optionally research web/reference sources before drafting."""
    try:
        read_attachments(engine, settings, get_deps().storage, get_extractor(), message_id)
    except Exception as exc:
        log.warning("prepare.read_failed", message_id=str(message_id), error_type=type(exc).__name__)
    try:
        _review_quote(engine, settings, message_id)
    except Exception as exc:
        log.warning("prepare.quote_failed", message_id=str(message_id), error_type=type(exc).__name__)
    if research:
        try:
            _research(engine, settings, message_id)
        except Exception as exc:
            log.warning("prepare.research_failed", message_id=str(message_id), error_type=type(exc).__name__)
