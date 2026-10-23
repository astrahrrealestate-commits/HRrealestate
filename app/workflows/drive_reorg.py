"""Drive reorganisation wiring (M10): `drive:reorg:{plan_id}` applies an approved plan.

Runs on the `documents` queue, partitioned by company with concurrency 1, like filing, so folder creation never races.
The plan is already in Postgres and approved; the step is safe to retry (see `app.pipeline.drive_reorg`).
"""

from uuid import UUID

from dbos import DBOS

from app.core.workflow_names import REORG_PLAN
from app.pipeline.drive_reorg import apply_plan
from app.workflows.deps import get_drive, get_engine
from app.workflows.documents import DRIVE_STEP_RETRY


@DBOS.step(name="documents.reorg_apply", **DRIVE_STEP_RETRY)
def apply_step(company_id: str, plan_id: str) -> dict[str, int]:
    return apply_plan(get_engine(), get_drive(), UUID(company_id), UUID(plan_id))


@DBOS.workflow(name=REORG_PLAN)
def reorg_plan_wf(company_id: str, plan_id: str) -> dict[str, int]:
    return apply_step(company_id, plan_id)
