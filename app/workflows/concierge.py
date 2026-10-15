"""Super Agent turn workflow (`concierge:{turn_id}`): one step does the turn's I/O; the body stays deterministic.

The API commits the `pending` turn before enqueueing (invariant 1). A replayed workflow id is deduped by DBOS, and a
re-run step skips a turn that is already done, so a turn never plans or executes twice once finished.
"""

from uuid import UUID

from dbos import DBOS, SetWorkflowID

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.workflow_names import CONCIERGE_TURN
from app.pipeline import concierge_turns
from app.pipeline.concierge import is_transient
from app.workflows import queues
from app.workflows.actions import execute_action_wf
from app.workflows.deps import get_engine
from app.workflows.owner_reply import approved_unexecuted_step
from app.workflows.retry import STEP_RETRY, retryable

log = get_logger(__name__)


def turn_retryable(exc: BaseException) -> bool:
    """The global policy plus what the concierge executor treats as transient (pool timeouts, invalidated
    connections, OSError): run_turn re-raises exactly those, so the step must retry them."""
    return retryable(exc) or is_transient(exc)


TURN_RETRY = {**STEP_RETRY, "should_retry": turn_retryable}


@DBOS.step(name="concierge.run_turn", **TURN_RETRY)
def run_turn_step(turn_id: str) -> None:
    concierge_turns.run_turn(get_engine(), get_settings(), UUID(turn_id))


@DBOS.step(name="concierge.fail_turn", **STEP_RETRY)
def fail_turn_step(turn_id: str, error: str) -> None:
    concierge_turns.fail_turn(get_engine(), UUID(turn_id), error)


@DBOS.step(name="concierge.turn_state", **STEP_RETRY)
def turn_state_step(turn_id: str) -> dict[str, str | bool]:
    return concierge_turns.turn_state(get_engine(), UUID(turn_id))


@DBOS.workflow(name=CONCIERGE_TURN)
def concierge_turn(turn_id: str) -> str:
    try:
        run_turn_step(turn_id)
    except Exception as exc:  # retries exhausted: the owner sees a failed turn, never one stuck `running`
        log.error("concierge.turn_gave_up", turn_id=turn_id, error=type(exc).__name__)
        fail_turn_step(turn_id, type(exc).__name__)
    state = turn_state_step(turn_id)
    if state["resume"]:  # the `resume` command re-runs approved actions, as on WhatsApp
        for action_id, version, local in approved_unexecuted_step(str(state["company_id"])):
            with SetWorkflowID(f"exec:{action_id}:{version}:resume:concierge:{turn_id}"):
                queues.pipeline_queue().enqueue(execute_action_wf, action_id, version, local)
    return str(state["status"])
