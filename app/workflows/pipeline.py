"""Pipeline entry DBOS workflow: triage inbound messages, link cases, propose actions."""

from typing import Any
from uuid import UUID

from dbos import DBOS
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.workflow_names import PIPELINE_ENTRY
from app.db.models import MessageRow
from app.directory.identity import resolve_message_sender
from app.ingestion.process import is_transient
from app.llm.calls import is_transient as llm_transient
from app.pipeline.link import link_message
from app.pipeline.propose import propose_for_message
from app.pipeline.understand import mark_pipeline_done, understand_message
from app.workflows.deps import get_engine
from app.workflows.owner_notify import alert_exceptions_step, send_card_step

log = get_logger(__name__)


def _retryable(exc: BaseException) -> bool:
    return bool(getattr(exc, "retryable", False)) or is_transient(exc) or llm_transient(exc)


_RETRY: dict[str, Any] = {
    "retries_allowed": True,
    "max_attempts": 5,
    "interval_seconds": 2.0,
    "backoff_rate": 2.0,
    "should_retry": _retryable,
}


@DBOS.step(name="pipeline.understand", **_RETRY)
def understand_step(message_id: str) -> str:
    engine = get_engine()
    settings = get_settings()
    res = understand_message(engine, settings, UUID(message_id))
    return "understood" if res is not None else "failed"


@DBOS.step(name="pipeline.resolve_sender", **_RETRY)
def resolve_step(message_id: str) -> None:
    resolve_message_sender(get_engine(), UUID(message_id))


@DBOS.step(name="pipeline.link", **_RETRY)
def link_step(message_id: str) -> str | None:
    result = link_message(get_engine(), get_settings(), UUID(message_id))
    return str(result.case_id) if result else None


@DBOS.step(name="pipeline.propose", **_RETRY)
def propose_step(message_id: str) -> dict[str, Any]:
    result = propose_for_message(get_engine(), get_settings(), UUID(message_id))
    return {"approval_ids": [str(a) for a in result.approval_ids], "exceptions": result.exceptions}


@DBOS.step(name="pipeline.company")
def company_step(message_id: str) -> str | None:
    with Session(get_engine()) as session:
        msg = session.get(MessageRow, UUID(message_id))
        return str(msg.company_id) if msg else None


@DBOS.step(name="pipeline.done")
def done_step(message_id: str) -> None:
    mark_pipeline_done(get_engine(), UUID(message_id))


@DBOS.workflow(name=PIPELINE_ENTRY)
def pipeline_entry(message_id: str) -> str:
    """Orchestrator (#1): understand → resolve sender → link → propose + rules → ask owner. One step per stage."""
    status = understand_step(message_id)
    resolve_step(message_id)
    case_id = link_step(message_id)
    company_id = company_step(message_id)
    if case_id is not None and company_id is not None:
        proposed = propose_step(message_id)
        for approval_id in proposed["approval_ids"]:
            send_card_step(company_id, approval_id)
        if proposed["exceptions"]:
            alert_exceptions_step(company_id, message_id)
    done_step(message_id)
    log.info("pipeline.entry.done", message_id=message_id, status=status, linked=case_id is not None)
    return status
