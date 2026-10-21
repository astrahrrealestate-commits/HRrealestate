"""Enqueue worker workflows from the API process by name (DBOSClient: no DBOS runtime, no app.workflows import)."""

from uuid import UUID

from app.api.deps import WorkflowClient
from app.core.workflow_names import (
    CONCIERGE_TURN,
    DOCUMENTS_QUEUE,
    EXECUTE_ACTION,
    FILE_DOCUMENT,
    PIPELINE_QUEUE,
    REORG_PLAN,
    concierge_workflow_id,
    exec_workflow_id,
    reorg_workflow_id,
)


def enqueue_execute(
    client: WorkflowClient, action_id: UUID, version: int, local: bool, *, suffix: str | None = None
) -> None:
    """`exec:{action_id}:{version}` (resume adds `:resume:<request>`): DBOS dedupes a repeated id."""
    workflow_id = exec_workflow_id(action_id, version) + (f":{suffix}" if suffix else "")
    options = {"queue_name": PIPELINE_QUEUE, "workflow_name": EXECUTE_ACTION, "workflow_id": workflow_id}
    client.enqueue(options, str(action_id), version, local)


def enqueue_filing(client: WorkflowClient, company_id: UUID, attachment_id: UUID, choice: str) -> None:
    options = {
        "queue_name": DOCUMENTS_QUEUE,
        "workflow_name": FILE_DOCUMENT,
        "workflow_id": f"doc:{attachment_id}:owner:{choice}",
        "queue_partition_key": str(company_id),
    }
    client.enqueue(options, str(company_id), str(attachment_id), choice)


def enqueue_reorg(client: WorkflowClient, company_id: UUID, plan_id: UUID) -> None:
    """Apply an approved Drive plan on the documents queue (per company, one at a time: folders never race)."""
    options = {
        "queue_name": DOCUMENTS_QUEUE,
        "workflow_name": REORG_PLAN,
        "workflow_id": reorg_workflow_id(plan_id),
        "queue_partition_key": str(company_id),
    }
    client.enqueue(options, str(company_id), str(plan_id))


def enqueue_turn(client: WorkflowClient, turn_id: UUID) -> None:
    """`concierge:{turn_id}` on the pipeline queue, after the turn row committed."""
    options = {
        "queue_name": PIPELINE_QUEUE,
        "workflow_name": CONCIERGE_TURN,
        "workflow_id": concierge_workflow_id(turn_id),
    }
    client.enqueue(options, str(turn_id))
