"""Routing targets filled in by later milestones (M4 pipeline, M7 owner commands). M2: record and log only."""

from dbos import DBOS

from app.core.logging import get_logger
from app.core.workflow_names import OWNER_REPLY, PIPELINE_ENTRY

log = get_logger(__name__)


@DBOS.workflow(name=OWNER_REPLY)
def owner_reply(message_id: str) -> str:
    log.info("owner.reply.stub", message_id=message_id)
    return "stub"


@DBOS.workflow(name=PIPELINE_ENTRY)
def pipeline_entry(message_id: str) -> str:
    log.info("pipeline.entry.stub", message_id=message_id)
    return "stub"
