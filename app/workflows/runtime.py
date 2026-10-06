"""DBOS runtime: configuration, launch and schedules. Only the worker process launches DBOS; the API uses DBOSClient.

`application_version` is deliberately NOT set: DBOS then derives it from a hash of the workflow source, so a deploy
that changes workflow code never resumes old in-flight workflows on new code (ADR 0001). Workflows are kept short so
little is in flight at deploy time; stranded ones are forked manually (`make workflows`, `dbos workflow fork`).
"""

from dbos import DBOS, DBOSConfig, ScheduleInput

from app.core.settings import Settings
from app.workflows import queues, system

SCHEDULES: list[ScheduleInput] = [
    {"schedule_name": "system.timer_sweep", "workflow_fn": system.timer_sweep, "schedule": "* * * * *"},
]


def dbos_config(settings: Settings) -> DBOSConfig:
    return {"name": "estateos", "system_database_url": settings.dbos_database_url}


def launch(settings: Settings, *, reset_for_tests: bool = False) -> None:
    """Configure and launch DBOS in this process, then register queues and (re)apply schedules (both idempotent)."""
    DBOS(config=dbos_config(settings))
    if reset_for_tests:
        DBOS.reset_system_database(truncate=True)
    DBOS.launch()
    queues.register_queues()
    DBOS.apply_schedules(SCHEDULES)
