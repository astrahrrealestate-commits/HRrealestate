---
name: check
description: Tiered EstateOS verification — run before claiming any task, fix or milestone is done. Tiers quick (lint+types+unit), full (+integration+migrations), stack (+docker compose up and health smoke). Use when the user says "verify", "check", "does it work", "is it green", or before committing.
---

# /check — evidence before claims

Pick the lowest tier that covers what changed. A tier passes only when the tool output shows it passing.
Report the exact command and its result line. Never write "should pass".

| Tier | Command | Covers | When |
|---|---|---|---|
| quick | `make quick` | ruff, mypy, `tests/unit` | any code change (stop hook runs this too) |
| full | `make check` | quick + `tests/integration` (real Postgres/Redis) + migration round-trip + `alembic check` drift | DB models, migrations, tasks, repositories, API |
| stack | `make smoke` | compose up → `/health/ready` 200 → worker + beat alive → compose logs scanned for tracebacks | Docker/compose/config/Celery wiring, milestone end |
| harness | `make harness-test` | guard hook self-tests | after editing `.claude/hooks/` |

## Procedure
1. `git status --short` — know what changed.
2. Run the tier. For full/stack, delegate to the `test-runner` agent if output may be long.
3. On failure: invoke `superpowers:systematic-debugging`. Fix root cause. Re-run the same tier.
4. Infra failures (Docker unresponsive, port in use, stale container): fix infra, don't touch code.
   Docker Desktop wedged → see user memory "Docker Desktop zombie backend".
5. Report: tier · command · result line (e.g. `142 passed in 8.31s`) · anything skipped and why.

## Milestone end
Run `stack`, then dispatch `estateos-reviewer`. Both must be clean before ticking the milestone in
`docs/PROGRESS.md`.
