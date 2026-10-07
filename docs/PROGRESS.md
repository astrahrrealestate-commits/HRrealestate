# EstateOS progress

Tick an item only with `/check` evidence. Milestone definitions: [build-plan.md](build-plan.md).

## M0 Prerequisites (owner: user + Harjot)
- [ ] Google Cloud project inside Harjot's Workspace, OAuth app Internal
- [ ] WhatsApp test number
- [ ] Coexistence route confirmed (Meta direct or partner) — open, see tech-stack.md "Open decisions"
- [ ] Hosting provider (EU) chosen — open
- [ ] LLM provider confirmed (OpenAI EU default) — open
- [ ] OpenAI org with EU data processing agreement
- [ ] BRIXX export received
- [ ] Labeller named for first 100 emails

## M1 Skeleton + contracts + first migration
Spec: [2026-10-05-estateos-m1-foundation-design.md](superpowers/specs/2026-10-05-estateos-m1-foundation-design.md)
- [x] Claude harness v1 (CLAUDE.md, hooks, agents, skills, Makefile)
- [x] HLD, tech stack, ADR 0001–0004, dev pipeline, harness v2 (/ship, pre-commit, practice guards)
- [x] Implementation plan written — `docs/superpowers/plans/2026-10-05-m1-foundation.md`
- [x] pyproject + uv lock + tooling config; pre-commit installed — G1: "Contracts: 3 kept, 0 broken", "1 passed"; pre-commit 17/17 passed
- [x] core: settings, logging, ids, errors, telemetry — G1 "10 passed", contracts 3 kept
- [x] six contracts + unit/property tests — G1 "104 passed", LLM strict-schema test; reviewer VERDICT: ship
- [x] test infra: testcontainers Postgres, DBOS fixture, recorded() loader — factories deferred to M2 (deviation recorded in spec §1)
- [x] SQLAlchemy models (24 tables) + first Alembic migration + roundtrip/drift/CHECK-value tests — G2 "114 passed" + "13 passed"; reviewer VERDICT: ship
- [x] FastAPI app + health endpoints — G2 "124 passed" + "21 passed"; reviewer VERDICT: ship
- [x] DBOS app + worker (`--selfcheck`) + `timer_sweep` cron — G2 "116 passed" + "20 passed", cov 95.67%; reviewer VERDICT: ship
- [x] Dockerfile + compose (postgres, migrate, api, worker) — `make smoke`: "api ready: ok", "worker: ok", "logs: clean"
- [ ] **decision for user:** add dev dep `httpx2` (starlette TestClient successor; blocked by permission classifier in Task 7) — then drop the filterwarnings ignore
- [x] import-linter contracts green — "Contracts: 3 kept, 0 broken" (app.main + app.worker required)
- [ ] GitHub Actions CI — workflow committed; **first green run pending: no git remote yet (user to add + push)**
- [x] G5 `make smoke` green + whole-branch reviewer `ship`; `make cov` 145 passed / 96.06%; `make audit` no known vulnerabilities

## M2 Ingestion (branch m2-channels; plan docs/superpowers/plans/2026-10-06-m2-channels.md)
- [x] T1 settings + prod safety; T2 storage port; T3 WhatsApp inbound; T4 WhatsApp outbound + media; T5 Gmail normalisation; T6 Gmail mailbox + push + drafts; T7 migration 0002 + ingestion repository; T8 webhook routes — reviewer fixes applied
- [ ] (carried from M1) polyfactory factories in `tests/factories.py`
- [x] (carried from M1 review) company_id required on every ingestion read/write; cross-tenant integration tests (T7)
- [x] (from T6 review) push route: resolve channel account by notice.email; unknown mailbox → 2xx, log, enqueue nothing (T8)
- [x] (from T8 review, Task 9) gmail_sync serialised (dedicated `gmail_sync` queue, concurrency 1; cursor compare-and-swap, no lock across Gmail calls); notice.history_id ≤ stored → no-op
- [x] T9 ingestion workflows (process_event, gmail_sync/backfill/watch_renew, hourly requeue of retryable failures + stranded `pending`) — reviewer fixes applied
- [x] T10 simulator (`python -m app.dev.simulate seed|wa|wa-button|gmail|demo`) + parity suite + `make sim-demo` — G5 "sim.demo.ok gmail=2 owner_buttons=1 whatsapp=2"; reviewer VERDICT: ship (mediums fixed)
- [x] T11 live harness: `make live-check [k=…]` (tests/live, `@pytest.mark.live(*settings)`, deselected by default, exits 2 listing missing names before any provider call), docs/go-live-channels.md; 360dialog webhook signature (`x-360dialog-signature`) supported — G2 green, no live run (no credentials)
- [ ] (T11 deviation, recorded) live checks are standalone smoke tests per real adapter, not `live` params of the tests/contract suites; real-adapter edge cases (NotFound, HistoryExpired) stay covered by recorded-HTTP contract tests only
- [ ] **decision for user:** 360dialog without a partner platform secret sends unsigned webhooks (rejected by design) — Meta Cloud API, get the platform secret, or approve custom-header auth
- [ ] **decision for user:** Gmail OAuth consent: `gcloud` forces the `cloud-platform` scope; minimal-scope consent script needs dev dep `google-auth-oauthlib`
- [ ] (from T9 review, before a 2nd company) `gmail_sync` queue: `partition_concurrency=1` + partition key = account id, so one slow mailbox never delays other tenants
- [x] (carried from M1 review) raw_event insert + DBOS enqueue in one transaction (T7, commit/rollback test)
## M3 Directory
## M4 Understanding + call log
## M5 Case engine
## M6 Proposals + rules
## M7 Owner channel + sender
## M8 Outcomes + hardening
- [ ] (carried from M1) DBOS system-table retention/GC (minute cron writes ~1,440 workflow rows/day)
- [ ] (carried from M1) image CVE scan in CI (Docker Scout reports 3 high Debian CVEs in python:3.12-slim)
