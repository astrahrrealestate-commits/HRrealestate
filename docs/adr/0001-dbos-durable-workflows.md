# ADR 0001: DBOS Transact instead of Celery + Redis + Beat

Status: accepted (2026-10-05)

## Context
The pipeline is multi-step (normalise → understand → link → propose → rules → notify), calls flaky external APIs,
must be idempotent, and needs cron jobs (briefing, watch renewal, sweeps). The build plan used Celery + Redis + Beat
plus a hand-rolled `timers` table and idempotency bookkeeping.

## Decision
Use **DBOS Transact** (library, MIT). Workflows and steps are checkpointed in our existing Postgres. Queues replace
Celery, `@DBOS.scheduled` replaces Beat, and the workflow id (`evt:{raw_event_id}`) gives exactly-once processing.
The API enqueues with `DBOSClient`; a separate `worker` process executes.

## Consequences
- No Redis or Celery to run. Postgres-first holds by construction, and one backup covers workflow state.
- Steps must be idempotent or transactional, and workflow code deterministic (inputs come from step results only).
- **Versioning:** a workflow resumes only on the same application version. Mitigation: workflows stay short (minutes).
  Human waits are DB state plus a new workflow per owner reply, never `recv()` for days.
- Ops via the `dbos` CLI / DBOSClient (list, cancel, fork from a step).
- **Application version** is not pinned: DBOS hashes the workflow source, so new code never resumes old in-flight
  workflows. Deploys drain (worker `stop_grace_period: 40s`, `DBOS.destroy(workflow_completion_timeout_sec=20)`);
  anything stranded is forked manually.
- **Exactly one worker in Phase 1.** DBOS recovers PENDING workflows by executor id (`DBOS__VMID`, default `local`);
  two workers sharing an id would each recover the other's in-flight work. Scaling out requires a stable, unique
  `DBOS__VMID` per replica (`worker-0`, `worker-1`, …).
- dbos 3.x specifics: queues via `DBOS.register_queue` after launch; cron via `DBOS.apply_schedules` (create-or-
  replace, preserves pause state); removing a schedule needs an explicit `DBOS.delete_schedule`.
- Fallback if DBOS disappoints: Temporal (same workflow/step shape, heavier infra).
