"""`sweep.stranded` (every 5 minutes): re-enqueue approved actions and Super Agent turns stranded by a crash between
the API's commit and its enqueue (selection and bounds: `app.pipeline.sweeps`). Same workflow ids as the API, so DBOS
dedupes anything that did start; ids DBOS already knows are skipped before enqueueing. Logs counts only.
"""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from dbos import DBOS, SetWorkflowID

from app.core.logging import get_logger
from app.pipeline import sweeps
from app.workflows import queues
from app.workflows.actions import execute_action_wf
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
    actions, turns = sweeps.stranded(get_engine(), datetime.fromisoformat(now_iso))
    every = sweeps.plan_sweep(actions, turns, known=(), limit=sweeps.BATCH)
    items = sweeps.plan_sweep(actions, turns, known=_known([i.workflow_id for i in every]), limit=sweeps.BATCH)
    log.info("sweep.stranded", actions=len(actions), turns=len(turns), enqueued=len(items))
    return [asdict(item) for item in items]


@DBOS.workflow(name="sweep.stranded")
def sweep_stranded(scheduled_time: datetime, context: Any) -> None:
    """The window comes from the scheduled time (an input), so the workflow stays deterministic."""
    items = candidates_step(scheduled_time.astimezone(UTC).isoformat())
    for item in items:
        with SetWorkflowID(item["workflow_id"]):
            if item["kind"] == "exec":
                queues.pipeline_queue().enqueue(execute_action_wf, *item["args"])
            else:
                queues.pipeline_queue().enqueue(concierge_turn, *item["args"])
