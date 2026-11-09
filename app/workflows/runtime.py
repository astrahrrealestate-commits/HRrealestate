"""DBOS runtime: configuration, launch and schedules. Only the worker process launches DBOS; the API uses DBOSClient.

`application_version` is deliberately NOT set: DBOS then derives it from a hash of the workflow source, so a deploy
that changes workflow code never resumes old in-flight workflows on new code (ADR 0001). Workflows are kept short so
little is in flight at deploy time; stranded ones are forked manually (`make workflows`, `dbos workflow fork`).
"""

from dbos import DBOS, DBOSConfig, ScheduleInput

from app.core.settings import Settings
from app.workflows import (
    actions,
    briefings,
    brixx_sync,
    concierge,
    diligence,
    distiller,
    document_backfill,
    documents,
    drive_reorg,
    finance,
    followups,
    ingest,
    maintenance,
    owner_notify,
    owner_reply,
    pipeline,
    quality,
    queues,
    sweeps,
    system,
    timer_dispatch,
)

# Importing registers the workflow functions before launch
_REGISTERED = (
    actions,
    briefings,
    brixx_sync,
    concierge,
    diligence,
    distiller,
    document_backfill,
    documents,
    drive_reorg,
    finance,
    followups,
    ingest,
    owner_notify,
    owner_reply,
    pipeline,
    quality,
    sweeps,
    timer_dispatch,
)

SCHEDULES: list[ScheduleInput] = [
    {"schedule_name": "system.timer_sweep", "workflow_fn": system.timer_sweep, "schedule": "* * * * *"},
    {
        "schedule_name": "gmail.watch_renew",
        "workflow_fn": ingest.gmail_watch_renew,
        "schedule": "0 3 * * *",
        "cron_timezone": "Europe/Amsterdam",
    },
    {"schedule_name": "gmail.poll", "workflow_fn": ingest.gmail_poll, "schedule": "* * * * *"},
    {"schedule_name": "gmail.backfill", "workflow_fn": ingest.gmail_backfill, "schedule": "17 * * * *"},
    {"schedule_name": "ingest.requeue", "workflow_fn": ingest.requeue_failed, "schedule": "41 * * * *"},
    {"schedule_name": "pipeline.requeue", "workflow_fn": pipeline.requeue_failed, "schedule": "47 * * * *"},
    {"schedule_name": "sweep.stranded", "workflow_fn": sweeps.sweep_stranded, "schedule": "*/5 * * * *"},
    {"schedule_name": "briefing.ensure", "workflow_fn": briefings.ensure_briefings, "schedule": "5 * * * *"},
    {"schedule_name": "brixx.sync_all", "workflow_fn": brixx_sync.sync_all, "schedule": "*/15 * * * *"},
    {"schedule_name": "outcomes.capture", "workflow_fn": quality.capture_cron, "schedule": "*/15 * * * *"},
    {"schedule_name": "drift.daily", "workflow_fn": quality.drift_cron, "schedule": "30 4 * * *"},
    {
        "schedule_name": "distiller.nightly",
        "workflow_fn": distiller.distiller_cron,
        "schedule": "0 2 * * *",
        "cron_timezone": "Europe/Amsterdam",
    },
    {
        "schedule_name": "maintenance.dbos_retention",
        "workflow_fn": maintenance.dbos_retention,
        "schedule": "50 3 * * *",
        "cron_timezone": "Europe/Amsterdam",
    },
]


def dbos_config(settings: Settings) -> DBOSConfig:
    return {"name": "estateos", "system_database_url": settings.dbos_database_url}


def launch(settings: Settings, *, reset_for_tests: bool = False, schedules: bool = True) -> None:
    """Configure and launch DBOS in this process, then register queues and (re)apply schedules (both idempotent).

    Tests pass `schedules=False` so real crons never fire inside a test executor.
    """
    DBOS(config=dbos_config(settings))
    if reset_for_tests:
        DBOS.reset_system_database(truncate=True)
    DBOS.launch()
    queues.register_queues(settings)
    if schedules:
        DBOS.apply_schedules(SCHEDULES)
