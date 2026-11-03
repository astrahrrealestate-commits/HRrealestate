---
description: autoship phase 4 - one full verification iteration per pass (max 8), then the final review. Only run from /autoship.
---

# verify (one iteration per pass, at most 8)

Guard: run only when /autoship selected this phase. Otherwise stop.

Increment `verify_iterations:` in BUILD_STATUS.md. Above 8: record what still fails, then run release.md's fallback.

## Run (through test-runner, quoting each result line)
`make setup` · `make quick` · `make check` · `make harness-test` · `make audit` ·
`cd frontend && npm ci && npm run build` · `make smoke` · `make sim-demo`.
Commands longer than 10 minutes: run them in the background and wait for the completion notification.
A check that could not run is a failure.

## Prove, quoting evidence
- **Agent memory survives a restart**: after `make sim-demo`, count rows in the memory tables named in
  `docs/superpowers/specs/2026-10-23-agent-memory-context-design.md`
  (`docker compose -f docker/compose.yml exec -T postgres psql -U estateos -c "select count(*) from ..."`), then
  `make down && make up`, count again: same counts, and a memory API read returns them.
- **Each Phase 1 agent (#1-#9)** returns a contract-valid proposal on simulated input: run its test/eval with the
  offline fake model and validate the output against `app/contracts/*`. Real-model runs need credentials ->
  Deferred, named.
- **Dashboard API returns real rows** from the simulated data: `curl -sf http://localhost:8000/api/v1/...` with a
  dev session, quote row counts.
- **BRIXX import loads a sample export**: run the import against the redacted fixture, quote per-table counts.

Fix root causes only (builders for larger fixes). Record each iteration's result lines in the phase log.

## Review
After the first fully green iteration: launch the `reviewer` agent. Fix every BLOCKING item, then re-run the reviewer
on the fix commits to confirm each is closed. Then one more fully green iteration is required.

## Gate
A fully green iteration after the review, with zero BLOCKING items. Not reached after 8 iterations: record what fails
and run release.md's fallback.
