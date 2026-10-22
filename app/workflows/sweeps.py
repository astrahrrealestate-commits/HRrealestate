"""`sweep.stranded` (every 5 minutes): re-enqueue approved actions and Super Agent turns stranded by a crash between
the API's commit and its enqueue (selection and bounds: `app.pipeline.sweeps`). Same workflow ids as the API, so DBOS
dedupes anything that did start; ids DBOS already knows are skipped before enqueueing.

Third kind: tenant sends stuck `sending` past `STUCK_AFTER` (a worker died mid provider call; `app.sender.stuck`) are
settled once each (send and action failed, one alert), then Harjot's owner channel is told under the same stable key
`blocked:exec:{a}:{v}` as `execute_action_wf`. Queries and settling run inside steps; logs carry counts only.
"""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from dbos import DBOS, SetWorkflowID

from app.core.logging import get_logger
from app.pipeline import sweeps
from app.sender import stuck
from app.sender.delivery import STUCK
from app.workflows import queues
from app.workflows.actions import execute_action_wf, tell_blocked_step
from app.workflows.concierge import concierge_turn
from app.workflows.deps import get_engine
from app.workflows.retry import STEP_RETRY

log = get_logger(__name__)


def _known(workflow_ids: list[str]) -> set[str]:
    if not workflow_ids:
        return set()
    found = DBOS.list_workflows(workflow_ids=workflow_ids, load_input=False, load_output=False)
    return {w.workflow_id for w in found}


@DBOS.step(name="sweep.stranded_candidates", **STEP_RETRY)
def candidates_step(now_iso: str) -> list[dict[str, Any]]:
    """Up to `SCAN` raw candidates, minus runs DBOS knows, then the `BATCH` cut (known runs cannot starve the rest)."""
    actions, turns = sweeps.stranded(get_engine(), datetime.fromisoformat(now_iso), limit=sweeps.SCAN)
    every = sweeps.plan_sweep(actions, turns, known=(), limit=sweeps.SCAN)
    items = sweeps.plan_sweep(actions, turns, known=_known([i.workflow_id for i in every]), limit=sweeps.BATCH)
    log.info("sweep.stranded", actions=len(actions), turns=len(turns), enqueued=len(items))
    return [asdict(item) for item in items]


def _item_data(item: stuck.StuckSend) -> dict[str, Any]:
    data = asdict(item)
    return {**data, "company_id": str(item.company_id), "action_id": str(item.action_id)}


@DBOS.step(name="sweep.stuck_sends", **STEP_RETRY)
def stuck_sends_step(now_iso: str) -> list[dict[str, Any]]:
    found = stuck.stuck_sends(get_engine(), datetime.fromisoformat(now_iso))
    log.info("sweep.stuck_sends", found=len(found))
    return [_item_data(item) for item in found]


@DBOS.step(name="sweep.settle_stuck", **STEP_RETRY)
def settle_stuck_step(item: dict[str, Any], now_iso: str) -> bool:
    send = stuck.StuckSend(UUID(item["company_id"]), item["key"], UUID(item["action_id"]), item["draft_version"])
    return stuck.settle(get_engine(), send, datetime.fromisoformat(now_iso))


@DBOS.workflow(name="sweep.stranded")
def sweep_stranded(scheduled_time: datetime, context: Any) -> None:
    """The window comes from the scheduled time (an input), so the workflow stays deterministic."""
    now_iso = scheduled_time.astimezone(UTC).isoformat()
    for item in candidates_step(now_iso):
        with SetWorkflowID(item["workflow_id"]):
            if item["kind"] == "exec":
                queues.pipeline_queue().enqueue(execute_action_wf, *item["args"])
            else:  # the chat queue, as the API enqueues turns
                queues.concierge_queue().enqueue(concierge_turn, *item["args"])
    for send in stuck_sends_step(now_iso):
        if settle_stuck_step(send, now_iso):  # the alert row is already written with the settle
            tell_blocked_step(send["action_id"], send["draft_version"], STUCK)
