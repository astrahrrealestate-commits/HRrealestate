"""`exec:{action_id}:{draft_version}`: deliver (sender) or apply (internal) one approved action, exactly once."""

from typing import Any
from uuid import UUID

from dbos import DBOS

from app.ingestion.process import is_transient
from app.pipeline import local_actions
from app.sender.execute import execute_action
from app.workflows.deps import get_engine, get_sender_deps

EXECUTE_ACTION = "actions.execute_action"


def _retryable(exc: BaseException) -> bool:
    return bool(getattr(exc, "retryable", False)) or is_transient(exc)


_RETRY: dict[str, Any] = {
    "retries_allowed": True,
    "max_attempts": 6,
    "interval_seconds": 5.0,
    "backoff_rate": 2.0,
    "should_retry": _retryable,
}


@DBOS.step(name="actions.apply_local", **_RETRY)
def apply_local_step(action_id: str, draft_version: int) -> str:
    return local_actions.apply_local(get_engine(), UUID(action_id), draft_version)


@DBOS.step(name="actions.send", **_RETRY)
def send_step(action_id: str, draft_version: int) -> str:
    return execute_action(get_sender_deps(), UUID(action_id), draft_version).status


@DBOS.workflow(name=EXECUTE_ACTION)
def execute_action_wf(action_id: str, draft_version: int, local: bool) -> str:
    return apply_local_step(action_id, draft_version) if local else send_step(action_id, draft_version)
