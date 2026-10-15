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
- [x] (carried from M1) polyfactory factories in `tests/factories.py`
- [x] (carried from M1 review) company_id required on every ingestion read/write; cross-tenant integration tests (T7)
- [x] (from T6 review) push route: resolve channel account by notice.email; unknown mailbox → 2xx, log, enqueue nothing (T8)
- [x] (from T8 review, Task 9) gmail_sync serialised (dedicated `gmail_sync` queue, concurrency 1; cursor compare-and-swap, no lock across Gmail calls); notice.history_id ≤ stored → no-op
- [x] T9 ingestion workflows (process_event, gmail_sync/backfill/watch_renew, hourly requeue of retryable failures + stranded `pending`) — reviewer fixes applied
- [x] T10 simulator (`python -m app.dev.simulate seed|wa|wa-button|gmail|demo`) + parity suite + `make sim-demo` — G5 "sim.demo.ok gmail=2 owner_buttons=1 whatsapp=2"; reviewer VERDICT: ship (mediums fixed)
- [x] T11 live harness: `make live-check [k=…]` (tests/live, `@pytest.mark.live(*settings)`, deselected by default, exits 2 listing missing names before any provider call), docs/go-live-channels.md; 360dialog webhook signature (`x-360dialog-signature`) supported — G2 green, no live run (no credentials)
- [ ] (T11 deviation, recorded) live checks are standalone smoke tests per real adapter, not `live` params of the tests/contract suites; real-adapter edge cases (NotFound, HistoryExpired) stay covered by recorded-HTTP contract tests only
- [ ] **decision for user:** 360dialog without a partner platform secret sends unsigned webhooks (rejected by design) — Meta Cloud API, get the platform secret, or approve custom-header auth
- [x] **decided (2026-10-08):** Gmail OAuth consent via `make gmail-consent` (dev dep `google-auth-oauthlib`, two minimal-scope token files, mailbox + exact-scope checks, never inside the repo) — G1 "703 passed"; reviewer VERDICT: ship (lows fixed)
- [x] whole-branch review fixes: prod boot refuses empty settings / missing bucket / missing creds file; postgres-safe WhatsApp payloads + filenames; single-company unparsed records; media failure keeps the message; resync race; spam→inbox relabel ingested; hour-bucketed requeue ids + `ingest.requeue_exhausted` + runbook; Meta `subscribed_apps` + echo field in go-live doc; modules split under 300 lines
- [x] (from M2 branch review, low) cache one verified Gmail mailbox client per address per thread (`app/channels/registry.py`)
- [ ] (from M2 branch review, low) migration: gmail `channel_accounts.address` lower-case CHECK or unique `(channel, lower(address))` (lookups are case-insensitive, constraint is not)
- [ ] (from T9 review, before a 2nd company) `gmail_sync` queue: `partition_concurrency=1` + partition key = account id, so one slow mailbox never delays other tenants
- [x] (carried from M1 review) raw_event insert + DBOS enqueue in one transaction (T7, commit/rollback test)
- [x] **M2 closed** (2026-10-07): `make cov` 94.52% (601 passed), `make audit` "No known vulnerabilities found", `make harness-test` OK, `make smoke` "api ready: ok / worker: ok / logs: clean", `make sim-demo` "sim.demo.ok gmail=2 owner_buttons=1 whatsapp=2"; whole-branch reviewer VERDICT: ship (re-review after fixes). Live checks not yet run (no credentials). Merge: user decision.
## M3 Directory — deferred (user, 2026-10-07); identity-first directory instead (`app/directory/identity.py`)

Phase 1 agents spec: [2026-10-07-estateos-phase1-agents-design.md](superpowers/specs/2026-10-07-estateos-phase1-agents-design.md) · branch `m4-agents`

## M4 Understanding + call log
- [x] `llm_model` setting (default `fake`, prod refuses fake/test, openai needs key); deps pydantic-ai 2.54, pydantic-evals, genai-prices, OTLP exporter, rapidfuzz
- [x] llm core: prompt loader + sha256, data blocks (case/space-insensitive escaping), `run_agent` (model_calls row on success and failure, transient errors retried, timeout, cost, resolved model name), fake FunctionModels, Langfuse OTel
- [x] understanding agent (#2) + prompt v1; `pipeline.entry` orchestrator (#1); messages.pipeline_status + hourly requeue (max 3)
- [x] golden set + `make eval` (evals/golden/understanding.yaml, evals/run.py, make eval agent=understanding version=v1)
- [ ] agent guardrails: owner Q&A scope (`owner_qa/v2`), per-company LLM budget/call caps (disabled by default), injection scanner feeding `suspicious`, draft output guard, owner_qa scope golden set; spec [2026-10-12-agent-guardrails-design.md](superpowers/specs/2026-10-12-agent-guardrails-design.md). Integration tests for these tasks NOT run (Docker unavailable); `make check`/`make smoke` pending. G1 790 passed; G2/smoke pending (Docker unavailable)

## M5 Case engine + tasks + waits
- [x] migration 0003: tasks, waits, documents, metric_snapshots, pipeline status, Europe/Amsterdam default, chase/briefing settings
- [x] identity resolution, case repository, link stage (thread → only open case → `link_check` v2 → new), rolling `case_summary` v2, waits received reopen the case
- [x] timer dispatcher (SKIP LOCKED + lease, per-kind handlers, max 5 attempts); task + wait repositories
- [x] linking accuracy eval (evals/golden/linking.yaml, make eval agent=linking version=v2)

## M6 Proposals + rules + chasing
- [x] `Proposal` contract, proposer agent v1 (Dutch drafts, untrusted blocks), pure rules engine (100 % branch)
- [x] propose stage: actions/approvals/tasks, replay-safe, proposer-failure notice
- [x] follow-up (#5): waits after approved requests, business-day ladder (DST-safe), chaser drafts, escalation; reclaimed timers never chase twice

## M7 Owner channel + sender
- [x] sender `execute_action`: approval/version/pause/allowlist/idempotency re-checks; Gmail draft in thread; WhatsApp replies go to Harjot as copy-ready text
- [x] approval cards (list menu / buttons), owner reply (tap twice = one draft), edit → revision, unknown taps answered, local actions (reminder → task, case state)
- [x] owner commands (#6) + owner Q&A agent; WhatsApp 24 h window: owner_outbox + `estateos_pending` template, flush on Harjot's next message (migration 0004)
- [x] briefings (#7): 07:30 daily + Friday 16:00 weekly per company timezone, agent text with template fallback
- [x] G5: `make smoke` "api ready: ok", "worker: ok", "logs: clean"; `make sim-demo` "sim.demo.ok agents=ok documents=2 gmail=2 owner_buttons=1 whatsapp=2" (2026-10-08, dev DB at migration 0007, no errors in stack logs)

## M9 Document filing
- [x] classifier (metadata only) + Drive adapter + `file_document` (app/pipeline/documents.py, app/storage/drive.py, doc_classifier agent); workflow + review card

## Review rounds (whole branch, 2026-10-08)
- [x] round 1 (estateos-reviewer + peer): owner-step retries, pipeline failure handling (no silent drops, final failure → `other` case + alert), blocked approvals told + `resume` reruns, re-fired chase timers, blank/command edits, edit replay, task #refs, outbox per-item isolation + current owner number, payload recipient check, reply channel from the message, propose lock, timers queue, briefing lists stuck items, company_id scoping
- [x] round 2 (peer): atomic send claim `pending → sending` (no double delivery, migration 0007), permanent failures tell Harjot, stranded-`pending` sweep with hour ids, lease renewal at handler start, refs-only done/snooze, thread's own Gmail mailbox for drafts, review-card retry, `<mode>` escaped; migration 0006 indexes + NULLS NOT DISTINCT waits
- [x] G1 `make quick` "727 passed"; G2 integration "201 passed" (twice; flaky briefing-timer ordering fixed); test teardown waits for in-flight workflows

## Go-live readiness (owner: user) — docs/go-live-channels.md
- [x] `.env.example` lists every setting; prod boot refuses fakes / missing credentials (incl. LLM, Drive)
- [x] `make gmail-consent … drive=1` creates gmail-read, gmail-compose and drive-file tokens (minimal scopes, account-checked)
- [x] `make live-check` covers S3, Gmail (read, watch, push certs, draft), WhatsApp (text to owner, media), Drive, real LLM
- [ ] WhatsApp template `estateos_pending` approved (Meta / 360dialog)
- [ ] credentials + settings set, onboarding rows inserted, `make live-check` green
- [ ] real `LLM_MODEL` + `make eval` (understanding v1, linking v2) compared with the fake reports

## M8 Outcomes + drift + hardening
- [x] outcome capture (Sent folder + echo → unchanged/edited/rewritten, migration 0005 unique per draft), 15-min cron
- [x] drift (#8): daily snapshots vs 14-day median, per-company thresholds, owner + Sentry alert
- [x] test: no approved action of any type on any channel reaches a tenant
- [ ] one day of shadow running on live mail (needs live credentials, user)
- [x] (carried from M1) DBOS system-table retention/GC (daily DBOS system-table retention 30 days with DBOS GC)
- [ ] (carried from M1) image CVE scan in CI (Docker Scout reports 3 high Debian CVEs in python:3.12-slim)

## D Dashboard + Super Agent (#10) — spec [2026-10-15-dashboard-super-agent-design.md](superpowers/specs/2026-10-15-dashboard-super-agent-design.md)
- [x] spec + ADR 0006 written (user decisions 2026-10-15: dashboard-only owner, real sends on approve, backend API only)
- [ ] spec review by user → implementation plan
- [ ] D1 foundation: migration 0009, auth, /api/v1 skeleton, SSE feed
- [ ] D2 read API: inbox, cases, tasks, waits, briefing, activity
- [ ] D3 decisions + sending: approvals API, dashboard owner channel, sender `send` mode, live-check outbound
- [ ] D4 Super Agent: ConciergePlan, executor, workflow, chat endpoints
- [ ] D5 hardening: concierge golden set, injection tests, rate limits, docs, sim-demo via API
