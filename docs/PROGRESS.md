# EstateOS progress

Tick an item only with `/check` evidence. Milestone definitions: [build-plan.md](build-plan.md).

## M0 Prerequisites (owner: user + Harjot)
- [ ] Google Cloud project inside Harjot's Workspace, OAuth app Internal
- [ ] WhatsApp test number
- [ ] Coexistence route confirmed (Meta direct or partner) — open, see tech-stack.md "Open decisions"
- [ ] Hosting provider (EU) chosen — open
- [ ] LLM provider confirmed (OpenAI EU default) — open
- [ ] OpenAI org with EU data processing agreement
- [ ] BRIXX Data API access (replaces the export, ADR 0010): token in `.env`, IP whitelist for the dev machine and a fixed production egress IP (see the BRIXX data mirror section)
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

## M10 Document intelligence — spec [2026-10-21-document-intelligence-design.md](superpowers/specs/2026-10-21-document-intelligence-design.md) · plan [2026-10-21-m10-document-intelligence.md](superpowers/plans/2026-10-21-m10-document-intelligence.md) · branch `m10-document-intelligence` (worktree `../EstateOS-m10`)
Evidence: G1 `make quick` "1444 passed" · integration "523 passed" with 2 failures that also fail on the untouched `d-dashboard` base (`test_send_to_owner_dashboard_writes_feed_only`, `test_blocked_approval_tells_harjot_and_resume_runs_it`); `test_pipeline_propose::test_reply_and_escalation_await_approval_with_tasks` failed once in a full run and passed 3 of 3 alone (disk was nearly full) · migration round-trip and drift pass.
**Not run:** `make smoke`, `make sim-demo` (disk too full to build the stack), `make live-check k=drive` (no credentials; the new relocate/annotate check is written in tests/live/test_live_drive.py), a real-model `make eval agent=doc_reader version=v1`.
- [x] spec + plan (no brainstorm: user said "just start"); spec lists 3 open decisions for the user
- [x] 1 migration 0013 (was 0011 before the merge; tables: document_chunks with generated tsvector, document_links, drive_reorg_plans/items; attachment extraction and document facts columns).
- [x] 2 text extraction (pypdf, docx, plain; scans to vision; ID documents never read), ADR 0007
- [x] 3 `DocumentFacts` + `doc_reader`/`doc_ocr` agents, multimodal `run_agent`
- [x] 4 read, chunk, store in `file_document` with metadata fallback; injection-like content goes to review
- [x] 5 linking to person/unit/lease/case; ambiguous matches link nothing; owner links and removals are never overwritten
- [x] 6 search + library API (`/documents`, `/documents/{id}`, links)
- [x] 7 Super Agent `find_document`/`read_document` (concierge prompt v2), `doc_qa` with verified quotes
- [x] 8 proposer v2 cites the case's own documents only, rationale names them
- [x] 9 Drive layout v2 (`EstateOS/<unit>/<kind>/<year>`), tenant in the name, Drive description and properties; `relocate`/`annotate`
- [x] 10 owner-approved reorg plans + `drive:reorg:{plan_id}` workflow
- [x] 11 backfill workflow (`POST /documents/backfill`), `doc_reader` golden set (`make eval agent=doc_reader version=v1`; on the fake it only measures the fake)
- [x] G3 review (estateos-reviewer, 2026-10-22): verdict was fix-first. Fixed: ID text no longer kept in `model_calls` (OCR output never recorded, reader call blanked for ID documents); proposer/Q&A scope is the case, its lease and its main person, not the unit (earlier tenants' papers); `id_document` file names parse and rename correctly; backfill keeps documents unread on a budget stop and marks poison documents; model sentences with figures absent from the verified quotes are not shown; API title/summary/snippet/party names/unit hints stripped of links, emails, IBANs; unknown case never widens a search; reorg builds take an advisory lock
- [ ] known gaps from the review, not fixed: a scanned ID image is still sent to the model provider once before the reader recognises it (a cheap vision pre-check would close it); pypdf has no parse-time bound (run extraction with a timeout); link and reorg dates use UTC, filing uses the company timezone; `drive_reorg_items.document_id` has no index
- [x] **Advanced RAG (ADR 0008)**, same branch: migration 0014 (was 0012; pgvector, chunk context/page/heading/embedding, document vector, `index_version`; Postgres image becomes `pgvector/pgvector:pg16`); embedder port (fake hashing embedder + OpenAI/Gemini through Pydantic AI) and a Dutch/English term list; heading- and page-aware chunks with overlap and a deterministic contextual header; embed step (last in the filing workflow) and backfill that rebuilds stale chunks and refills vectors; hybrid retrieval (words + chunk vectors + document vectors, Reciprocal Rank Fusion); query planner (keyword variants, HyDE passage, fact label), fact-first route from stored facts, listwise reranker with a relevance floor, neighbour widening with pages; hybrid library search (`mode=hybrid` default) and cheap hybrid excerpts for reply drafts; Dutch injection scan widened (`voorgaande`, `bovenstaande`)
- [x] RAG quality gate `tests/integration/test_rag_quality.py` on a synthetic Dutch/English corpus (`evals/rag_corpus.py`, `evals/rag_eval.py`, `make rag-eval`). Offline models, quoted from the run: hybrid context_hit 1.00, doc_hit 1.00, mrr 0.92, fact_accuracy 1.00, abstain_accuracy 1.00, isolation_violations 0; the M10 full-text baseline on the same questions: context_hit 0.60, doc_hit 0.60, mrr 0.52, fact_accuracy 0.00, isolation_violations 1. **These numbers measure the mechanics only:** the offline embedder and reranker share the glossary the corpus was written with. Two `semantic` questions ("May I keep a dog?") are scored but not asserted offline and need a real embedding model
- [x] G3 review of the RAG work (2026-10-23, verdict fix-first). Fixed: passage refs hash the whole document id (UUIDv7 prefixes collided for documents created together); any embedder failure degrades to words and never raises, embeddings have a deadline and are computed before a session is held; the embed step no longer fails the filing workflow; fact answers come from leases only and match whole label words; reindex never touches ID documents and settles empty ones; changing a link marks a document for reindexing and a stale document vector is never written back; company filters added to three defence-in-depth queries; API embedder cached; pgvector pinned to 0.8.2
- [x] merged into `d-dashboard` (2026-10-23): migrations renumbered to 0013/0014 after its 0011/0012 (single head 0014); concierge prompt `v4` = their v3 plus `find_document`/`read_document`; proposer `v3` = v1 plus documents (v1 stays byte-identical when no documents are in view, their `v2` stays the owner-guided prompt); their `v2`/`v3` prompt files untouched
- [ ] real-model run of `make rag-eval` (needs EMBEDDING_MODEL, LLM_MODEL and keys), tune `KEEP_RELEVANCE`/`RRF` weights on it; recreate the dev Postgres volume (the image changed from alpine to Debian); a retrieval eval on Harjot's own documents
- [ ] sim-demo "lease question" scenario, live Drive check, real-model eval

## M12 Due diligence lite (agent) — spec [2026-10-31-due-diligence-lite-design.md](superpowers/specs/2026-10-31-due-diligence-lite-design.md) · branch `m12-due-diligence-lite`
Written without a brainstorm (user: "build the agent"); every call in the spec is marked **(my call)**. The client's own framework was not supplied: the default checklist `nl-residential-v1` is replaceable data (`dd_framework_path`).
Evidence: G1 `make quick` "2225 passed", "Contracts: 8 kept, 0 broken.", "Success: no issues found in 336 source files" · G2 `make check` "675 passed" with 1 failure, `test_maintenance_ticket_full_history` (frontend mock-data endpoint, no diligence code; not run on the base commit) · migration 0023 round trip and drift pass (`test_migration_0023.py`, `test_migrations.py`) · `LLM_MODEL=fake make eval agent=dd_reader version=v1`: kind_accuracy 1.00, claim_recall 1.00, quote_precision 1.00, clean_rate 1.00 (**measures the deterministic fake, not a real model**) · G3 `estateos-reviewer`: 13 findings, all but #13 (noise) addressed in the follow-up commit.
- [x] contracts `app/contracts/diligence.py`, `diligence_report.py`; pure engine `app/diligence/` (framework, checklist, compare, risks, verify, engine) behind an import-linter purity contract
- [x] `dd_reader` agent (prompt `v1/dd_reader.md`, fake, golden set `evals/golden/dd_reader.yaml`), quote + value verification, kind keyword check
- [x] migration 0027 (`dd_reviews`, `dd_review_documents`, `dd_document_reads`, feed kind `dd_report`), repo, service, DBOS workflow `dd:{review_id}:{run_no}` on the documents queue
- [x] API `POST/GET /diligence/reviews`, `POST /diligence/reviews/{id}/rerun`, feed card; documented in `docs/dashboard-api.md`
- [ ] real-model run of the dd_reader eval (needs LLM_MODEL and a key); tune the prompt and `KIND_KEYWORDS` on real Dutch documents (the keyword check may be too strict for unusual wording)
- [ ] the client's own framework JSON (`dd_framework_path`); a fifth property kind for tenanted houses if wanted
- [ ] Super Agent read intents (needs a concierge prompt version); dashboard UI for the report
- [ ] follow-ups from review: medium document flags do not change the verdict (shown in `risks`); `compare` checks each claim against the reference only (non-transitive tolerance); no index on `dd_reviews.unit_id`
- [ ] not run: `make smoke`, `make sim-demo` (no simulator scenario written for this agent), `make harness-test` fails on `test_allows_git_write_in_own_linked_worktree` (worktree guard, unrelated to this change)

## BRIXX data mirror — spec [2026-10-31-brixx-data-mirror-design.md](superpowers/specs/2026-10-31-brixx-data-mirror-design.md) · plan [Phase A](superpowers/plans/2026-10-31-brixx-data-mirror-phase-a.md) · ADR 0010 · branches `m-brixx-mirror` (PR 20), `m-brixx-status`
Replaces the deferred M3 CSV/XLSX export import: every BRIXX table mirrored into typed Postgres tables (schema `brixx`) by DBOS workflows; BRIXX is never called on a request path.
- [x] Phase A Tasks 1–8 (PR 20): settings + prod guard, models/port/filter builder/`{}`→NULL normaliser, httpx adapter + fake, mirror table builder and type map, sync state tables (migration 0028), idempotent page upsert, resumable table sync with drift detection, `brixx.sync_all` cron + `brixx.sync_table` children on the `brixx` queue. G1 on Windows at the PR 20 merge: "Contracts: 8 kept, 0 broken", unit+contract "2508 passed" with the 10 failed + 8 errors that are Windows-only (perms, symlinks, CRLF, timeouts), mypy only the 2 Windows `fcntl` errors in `app/channels/gmail/fake.py`
- [x] Phase A Task 9: `GET /api/v1/brixx/status` (state tables only, company-scoped, session auth; `stale` = no succeeded run within 3 x `brixx_sync_interval_minutes`), contracts `app/contracts/brixx.py` (run enums now defined there, re-exported by `app/db/enums.py`), read model `app/directory/brixx/status.py`, OpenAPI snapshot, `docs/dashboard-api.md`. G1 on Windows: "2654 passed", "32 snapshots passed", "Contracts: 8 kept, 0 broken", the same 10 failed + 8 errors and 2 mypy errors as the clean-tree baseline, nothing new
- [x] Phase A Task 10: ADR 0010, `docs/tech-stack.md`, `docs/hld.md`, `docs/go-live-channels.md` (BRIXX section)
- [ ] `make check` (G2) for Phase A: integration tests `test_brixx_schema.py`, `test_brixx_state_models.py`, `test_brixx_upsert.py`, `test_brixx_sync.py`, `test_brixx_workflows.py`, `test_brixx_status_api.py` are written; the status API tests were **not run** (no Docker on the Windows dev machine), and neither were the 0028 round-trip and drift there
- [ ] Phase B (discovery, `make brixx-codegen`, migration for all tables, first load, `make live-check k=brixx`) and Phase C (documents to S3): in progress on `m-brixx-discover` / `m-brixx-documents`. **Blocked for any live call on:** the BRIXX token in `.env`; the IP whitelist for the dev machine's public IP `122.161.68.101` (2026-11-03; the spec's `115.246.217.246` is stale); a fixed production egress IP, also whitelisted
- [ ] open: which `Authorization` form BRIXX expects (`BRIXX_AUTH_SCHEME` bearer or raw, unconfirmed); whether the token has the personal-data permission (documents, `ZOEKID`); rotate the token after go-live (exposed in a chat on 2026-10-31)
- [ ] follow-up (status API): the state row has no per-table success timestamp, so `last_success_at` is derived (start of the run that last completed the table, else the `UPDDATETIME` watermark; null for tables without `UPDDATETIME` while a run is mid-table or failing), and `row_count` counts rows written by the latest run, not the mirror size. A `last_success_at` column set by `mark_success` and a per-table mirror row count (Phase B, once the `brixx` tables exist) would make both exact
- [ ] Phase D: mapper to `people`/`units`/leases, Super Agent BRIXX lookup tool, GDPR purge of mirror rows and documents (failing test first) with an erased-refs tombstone

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
- [ ] (carried from M1) image CVE scan in CI (Docker Scout reports 3 high Debian CVEs in python:3.12-slim) — Trivy step committed in the ci.yml `image` job (fails on fixable HIGH/CRITICAL); first GitHub Actions run pending

## D Dashboard + Super Agent (#10) — spec [2026-10-15-dashboard-super-agent-design.md](superpowers/specs/2026-10-15-dashboard-super-agent-design.md) · branch `d-dashboard` · API guide [dashboard-api.md](dashboard-api.md)
Ticks below carry a quoted line from the build ledger (per-task `make quick` reports and reviews) or from a run on 2026-10-15.
**Not run anywhere in D (Docker down, no credentials):** every integration test, `make check`, `make cov`, `make smoke`,
`make sim-demo` (incl. the new `dashboard` scenario), `make live-check k=outbound`. Items that depend on them are unticked or say "written, not run".
- [x] spec + ADR 0006 written (user decisions 2026-10-15: dashboard-only owner, real sends on approve, backend API only); ADR 0006 now `accepted`
- [ ] spec review by user (the build proceeded on the user's "start"; spec amended with "Deviations from the first draft")
- [x] D1 foundation (migration 0009, auth, `/api/v1` skeleton, SSE feed): ledger "Task 3: complete (commits bf44484..f70017d, review clean)"; `make quick` 801 passed (task 1), 842 (after auth review fixes), 881 (task 4)
- [x] D2 read API (inbox, cases, tasks, waits, briefing, activity, approvals, documents/review): ledger "Task 5: complete (commits 3707141..094d2c6, review clean)"; `make quick` 923 passed after task 6
- [x] D3 decision routes, dashboard owner channel, sender `send` mode: ledger "Task 9: complete ... review clean; G2 must pass before merge"; `make quick` `1045 passed, 4 warnings`, `Contracts: 5 kept, 0 broken.`
- [ ] D3 live-check outbound (`make live-check k=outbound`): written, not run (no credentials); ledger "Task 10: complete (commits d492af4..ff2fa0d, review clean)" covers the code review only
- [ ] **G2 for D1-D3:** integration tests (342 collected, mypy clean) and the migration round-trip have NOT been run. `make check` must pass once Docker is back, before send mode is trusted
- [x] D4 Super Agent (ConciergePlan, executor, workflow, chat endpoints): ledger "Task 13: complete (commits 27a8169..d698b38, review clean)"
- [x] D5 concierge golden set and injection suite (unit part): ledger "Task 14: complete (commits d698b38..db24230, review clean)"; `LLM_MODEL=fake make eval agent=concierge version=v1` on 2026-10-15: `intent_sequence_match: 1.00`, `scope_accuracy: 1.00`, `forbidden_intent_rate: 0.00`, `invariant_pass_rate: 1.00`, `misses: 0` (fake model, not a real one). The injection integration tests are written, not run
- [x] D5 rate limits (30/min agent, 10/min login per IP, 120/min decisions; `app/api/v1/ratelimit.py`) with unit tests in `tests/unit/api/test_ratelimit.py`; CRLF now allowed in agent text
- [ ] D5 simulator `dashboard` scenario (`app/dev/demo_dashboard.py`, runs inside `make sim-demo`, ends with `dashboard=ok`; compose now forwards the dashboard settings, skip without a secret, provider guard, state restored): written, not run; only its pure helpers are unit-tested
- [x] D5 docs: dashboard-api.md, ADR 0006 accepted, tech-stack, spec deviations, go-live nits
- [x] G1 on 2026-10-15 (after task 15): `make quick` -> `1246 passed, 652 warnings`, import-linter contracts kept
- [x] `make audit` 2026-10-15: `No known vulnerabilities found`
- [x] `make harness-test` 2026-10-15: `Ran 16 tests ... OK`
- [ ] `make cov`: needs Docker (runs integration tests): not run
- [x] whole-branch final review (opus, 60e2afb..76e4003): verdict "merge after fixes" (I1-I8, M1-M8); one fix wave below
- [x] **Final review fix wave** (unit-tested; integration tests written, mypy-clean and collected, NOT run):
  - I1 document-review cards (`docreview:{attachment_id}`, now `app.owner.cards.document_review_key`) land as `document_review` with `ref_id`
  - I2 approved contractor requests, escalations, owner notes and draft-mode WhatsApp replies reach a `dashboard` owner as one feed row (`exec:` key, committed with the `sends` row marked sent); allowlist branch for the company's own owner feed; WhatsApp/Chat owners unchanged
  - I3 ruling: code default stays `whatsapp`; deviation recorded in the spec; switch runbook in go-live-channels.md
  - I4 the planner brief lists open tasks as `#<ref> <title>`
  - I5 `resume` skips actions whose exec send is `sending`/`sent`/`failed`; a lost claim on a tenant send `sending` < 30 min is "in progress" (no alert); `tell_blocked_step` keys alerts by `blocked:exec:{a}:{v}`
  - I6 a send `sending` 30+ min is marked failed once (send + action), one alert, never re-run by `resume`
  - I7 `sweep.stranded` cron every 5 min re-enqueues approved actions and pending turns stranded between commit and enqueue (same ids, 200 per round)
  - I8 same-origin deployment documented; optional `DASHBOARD_CORS_ORIGINS` allowlist (`*` refused)
  - M1 sessions re-read the owner row per request; M2 import-linter contract `app.api` never imports `app.workflows`/`app.sender` (`Contracts: 6 kept, 0 broken.`); M3 stale docs fixed/annotated; M5 compose and `.env.example` wiring (unit-tested); M8 go-live note on draft mode for a dashboard-only owner
  - G1 after the wave: `make quick` -> `1322 passed, 654 warnings`; integration suite `401 tests collected`, not run
- [ ] G5 `make smoke`, `make sim-demo`: not run

### Dashboard follow-ups / parked (from the ledger)
- Fixed in the final wave (were parked): N1 resume vs in-flight send (I5), stuck `STATUS_UNKNOWN` sends repeating (I6: failed once after 30 min), turns/actions stranded between commit and enqueue (I7 sweep). Their integration tests are written, not run.
- No owner mark-sent/cancel route for a send whose status is unknown (ruling: the owner checks the thread and resends by hand); owner re-target is refused on a number change.
- M4: outcome capture labels send-mode sends `unchanged` (the sender delivered the approved text itself); label them apart (follow-up).
- The owner channel default is still `whatsapp` in code (spec says `dashboard`): needs the user's decision on existing rows.
- SSE: a row that commits later than about 2 s after a later one can be missed until reconnect; no reconnect frame at lifetime end; generic error frame.
- Sanitiser gaps in concierge answers: dotted-time hold such as `06.12 34 56 78`, bare domains.
- `draft_reply` cannot re-draft after a decision.
- `normalise_identity` has no NL region default (separate change).
- `handle_wait_due` is about 55 lines and `followups.py` 297 lines (over the style limits).
- Inbox correlated subqueries per row (EXPLAIN later, index on coalesce); `owner_id` FK on conversations unindexed.
- Minor ledger items: `fail_turn` raising inside the enqueue-failure path leaves a turn pending; a transient error mid `run_plan` re-executes the stored plan's steps (relies on step idempotency); `pending_step_approval` may match a same-plan `draft_reply`; the live outbound test checks the read-token mailbox, not the reply-send token identity; `test_migration_0009` covers only 2 CHECKs and there is no 0010-specific test; the concierge fake's injection pattern diverged from `_SUSPICIOUS`; `StepResult.data["summary"]` can carry the raw case summary (capped at 400 chars; the SPA must render plain text).
- Stuck-send sweep: `stuck_query` should join `actions` and require `ActionRow.type == reply_draft` (draft-mode drafts and re-targeted owner rows currently get the tenant wording); owner-directed exec sends stuck in `sending` are never settled (no alert, `resume` skips them); `write_alert` runs inside the give-up transaction, so a persistent feed error rolls back the settle; `mark()` writes Send before Action (rare deadlock, resolved by the step retry).
- Task 2 minors: `NO_INFORMATION` matches fixed answers exactly only; no cursor tie-break test with equal `created_at`.
- Task 3 M7: a turn planned under `concierge/v1` and finished by a retry after the deploy is labelled `concierge/v2` (cosmetic).
- `MAX_THREAD_KEY` (400) assumes an ASCII ref: a 255-character non-ASCII ref encodes longer and its key is `422` as `thread_key`/visible id.
- Prompt escaping side effects (accepted): NFKC folds compatibility characters in ordinary text (`m²` -> `m2`, `½` -> `1/2`, ligatures), and stripping default-ignorable code points drops ZWJ/ZWNJ and variation selectors (emoji sequences split).
- Others minor: `_RE_PREFIX` strips only `Re:` (not `Antw:`/`AW:`); a roommate-only thread has no tenant recipient; ApprovalOut may be stale after an edit before the v2 approval row exists; `/feed` clamps `limit` while `/inbox` returns 422; multi-instance rate limits need Postgres counters (ADR 0006).

- [x] Final re-review finding 1 (was "BLOCKS `outbound_mode=send`"): a tenant send left `sending` by a worker that died mid-call is settled by the 5-minute `sweep.stranded` cron once it is 30 min old (`app/sender/stuck.py`: send + action failed, one alert under `blocked:exec:{a}:{v}`, conditional update so one winner, company-scoped, 200 per round, paused companies included). A lost claim on a fresh row is `in_progress` (no `after_execute_step`, no alert). Lows: `tell_blocked_step` uses `tenant_gate.alert_text` for tenant replies; `feed_claimed`/`give_up_stuck` lock Action before Send; the stranded scan reads up to 1000 candidates before the DBOS known-id filter (24 h limit documented in dashboard-api.md). Evidence: unit-tested, `make quick` -> `1357 passed, 654 warnings`; integration tests (`tests/integration/test_stuck_sends.py`, updated replay/execute tests) written, mypy-clean and collected (`409 tests collected`), **not run** (Docker down). Send mode still needs G2 below.
- [x] Page-aware Super Agent (amendment 2026-10-16, Task 3): optional `page` on `POST /agent/messages` (`app/contracts/page_context.py`: view, open entity ids, filters, at most 50 visible ids, snapshot at most 6000 chars after collapsing; 422 over limits or on control characters); migration 0011 `agent_turns.page_context` jsonb; `app/pipeline/page_facts.py` + `page_visible.py` resolve company-scoped facts and drop foreign ids by kind only; prompt `concierge/v2` (v1 kept) with escaped `<page_facts>`/`<page_snapshot>` blocks; facts resolved once and stored under `page_context.resolved` before the model call (`app/pipeline/concierge_page.py`), reused by a retry; fake resolves "this/it/him" from the facts block only; 13 page golden cases. Evidence: `make quick` -> `1445 passed, 654 warnings`, `Contracts: 6 kept, 0 broken.`; `LLM_MODEL=fake make eval agent=concierge version=v2` -> `intent_sequence_match: 1.00`, `forbidden_intent_rate: 0.00`, `invariant_pass_rate: 1.00`, `misses: 0`. Integration tests (`test_page_facts.py`, `test_concierge_page.py`, `test_migration_0011.py`) written, mypy-clean and collected (`416 tests collected`), **not run** (Docker down); migration 0011 round-trip and drift not run.
- [x] Page-aware answers and snapshot hardening (Task 4): `answer` steps and the planner-failure fallback pass the stored page facts, snapshot and filters to `owner_qa` (prompt `owner_qa/v3`, only when a page is present; page-less prompt byte-identical, spec `owner_qa/v2`); prompt escaping strips Unicode Cf and applies NFKC + angle-quote look-alikes; snapshot CRLF/CR become LF; visible thread keys up to 400 chars; filters no longer cut the snapshot's end; concierge fake: pronoun required, "the first one" is the first row of any kind; 6 owner_qa page golden cases, concierge `page-14`. Evidence: `make quick` -> `1541 passed`; `LLM_MODEL=fake make eval` owner_qa v3 and v2 -> `scope_accuracy: 1.00`, `refusal_recall: 1.00`, `false_refusal_rate: 0.00`, `page_use: 1.00`, `forbidden_rate: 0.00`, misses 0 (page cases run for v3 only; the fake now refuses prompt/rules requests); concierge v2 -> `intent_sequence_match: 1.00`, `forbidden_intent_rate: 0.00`, misses 0. Integration tests (`test_concierge_page.py`: answer step with a page uses `owner_qa/v3`, page-less keeps `v2`) written, mypy-clean and collected (`418 tests collected`), **not run** (Docker down).
- [x] Live chat awareness Task 1 (amendment 2026-10-22): memory pack for an open thread or case in `<page_facts>` (`app/pipeline/page_memory.py` queries, `page_memory_lines.py` lines, `page_text.py` one-line values + 12000-char budget with a fixed drop order): that thread's messages only (else the case's linked messages), all up to 30 else first 6 + newest 24, one anchored line each (600 chars); summary 800; person + lease parties; open waits; last 15 events (note 120); latest 5 actions with the owner's decision and edit count; one window query for messages, four for the case memory, company_id on every query and join. Only `<page_facts>` gets the 12000 cap (`MAX_PAGE_FACTS`), others keep 8000, escaping after truncation; worst-case concierge/owner_qa prompts bounded and tag-safe (unit). Evidence: `make quick` -> `1566 passed, 653 warnings`, `Contracts: 6 kept, 0 broken.`; `LLM_MODEL=fake make eval agent=concierge version=v2` -> `intent_sequence_match: 1.00`, `forbidden_intent_rate: 0.00`, misses 0; `agent=owner_qa version=v3` -> `scope_accuracy: 1.00`, `page_use: 1.00`, `forbidden_rate: 0.00`, misses 0. Integration tests (`tests/integration/test_page_memory.py`: window, thread isolation, company scoping, statement count independent of message count) written, mypy-clean and collected (`422 tests collected`), **not run** (Docker down).
- [x] Live chat awareness Task 2 (steerable drafts): `draft_reply` passes the owner's own message (never the planner's `text`, since the fix rounds) through the concierge sanitiser to the proposer as an `<owner_guidance>` block (prompt `proposer/v2`, used only for owner-requested drafts; inbound-message and chase proposals keep `proposer/v1` and a byte-identical prompt). On a turn, a pending reply draft is superseded once (`supersede.supersede_draft`, originally in `approvals`: old approval expired, `draft_version + 1`, new approval) and a decided one gets one fresh reply action (`app/pipeline/redraft.py`); both are keyed `agent:{turn_id}:{step}` in `action_revisions.edited_by`, so a retry (or a second step of the same turn) returns the same revision without a model call. Held messages (suspicious, paused) are never redrafted; new approvals keep `context_ref = [message_id]`. The chat answer quotes up to 3 variants (600 chars each, output-guard flags, flagged ones redacted) and `data` carries the approval id, version, drafts and `details_removed`. Plan case ids are limited to the brief's and the resolved page lines' (`known_case_ids`); memory pack: lease versions labelled and ordered with id tiebreaks, `(none) -> open`, edit count = owner edits only. Proposer eval (`evals/proposer_eval.py`, 9 golden cases, 1 real-only). Evidence: `make quick` -> `1602 passed, 654 warnings`, `Contracts: 6 kept, 0 broken.`; `LLM_MODEL=fake make eval agent=proposer version=v2` -> `reply_rate: 1.00`, `guidance_follow: 1.00`, `language_ok: 1.00`, `forbidden_rate: 0.00`, misses 0; `agent=concierge version=v2` -> `intent_sequence_match: 1.00`, `forbidden_intent_rate: 0.00`, misses 0; `agent=owner_qa version=v3` -> `page_use: 1.00`, `forbidden_rate: 0.00`, misses 0 (fake model only, no real model run). Integration tests (`test_concierge_redraft.py`: supersede once under retry, fresh draft once per turn, guidance never in a payload/recipient and no Send rows, suspicious stays gated; `test_concierge_page.py`: case id copied from tenant text is not found; updated `test_concierge_proposals.py`, `test_page_memory.py`) written, mypy-clean and collected (`427 tests collected`), **not run** (Docker down).
- [x] Task 2 fix round 1: `supersede_draft` locks the approval, then the action (the order `decide`/`edit_approval` use) and re-reads the approval's status after both locks, so a decision that committed meanwhile is never overwritten; draft guidance comes from the owner's own message (sanitised, 400 chars; a planner-text subset rule added here was dropped in fix round 2); redraft states `busy` (reply awaiting approval without a live pending approval, e.g. an edit tap's 24 h window: never redrafted) and `no_reply` (only other actions: a first reply, not "already decided"); `fresh` re-reads the state under the message lock and supersedes a reply another turn just proposed; a case id outside the brief/page now answers "Open that case's page first, then ask again."; a live non-reply approval is never reported as a waiting reply. Evidence: see the fix report in `.superpowers/sdd/2026-10-22-live-chat-awareness/task-2-report.md`. Integration tests written, not run (Docker down).
- [x] Note for Task 3: guidance is the owner's own message on purpose. `concierge/v3` must NOT rely on the planner's `text` to carry drafting wording: the planner reads tenant text, and its `text` is never used as guidance. Done in Task 3: `concierge/v3` says `text` null for `draft_reply` and never mentions guidance or wording (unit-tested).
- [x] Task 2 fix round 2: draft guidance is always the owner's own sanitised message (the planner-text subset refinement was dropped: negations, spelled-out and look-alike words passed it); `approvals.decide` re-reads the approval `FOR UPDATE` with `populate_existing` and then locks the action the same way (approval, then action, like the redraft), so a decision on an approval a redraft expired is `stale` and changes nothing; the redraft code moved to `app/pipeline/supersede.py`; an edit tap older than the 24 h edit window no longer blocks the case: it counts as supersedable and the redraft expires it atomically under the locks (inside the window the draft stays `busy`). Integration tests written, not run (Docker down).
- [ ] Task 2 follow-ups (deferred by the coordinator):
  - (5) When the first-draft path yields no reply action (for example an escalation only), nothing is keyed, so a second `draft_reply` step in the same turn or a retry takes the fresh path and calls the model again (results can disagree; no duplicates).
  - (7) `Loaded.source` omits the current draft: if the owner edited the draft to include his own phone number or IBAN, a "make it shorter" redraft keeping it is flagged by the output guard and nothing changes (consider counting owner-authored revision text as verified).
  - (8) No index on `action_revisions.edited_by`: the turn-replay `LIKE 'agent:{turn}:%'` and `replayed_edit` lookups need `(company_id, edited_by text_pattern_ops)` at scale.
  - Re-review minors: `redraft.classify` returns `pending` before `held` (a held non-reply action does not stop superseding a live reply; the rules still re-check the redraft); the plan text for Task 2 described the planner's `text` as the guidance (now marked superseded in the plan).
- [x] Live chat awareness Task 3 (fast turns): single-call answers (`ConciergePlan.reply`, required nullable, at most 1200 chars; prompt `concierge/v3`, v2/v1 stay published): a page/chat question is answered by the planner's own `reply`, screened in `app/pipeline/concierge_reply.py` (in-scope plans only, control/format characters out, 20 lines / 1200 chars, links, emails, phones and IBANs redacted (amounts too until fix round 1), ids never read, an `answer` step appended when missing) and stored screened; the `answer` step calls owner_qa only when the reply is blank. Snapshot cap 3000 (not 6000) when `<page_facts>` carries a memory pack. Dedicated `concierge` DBOS queue (`worker_concurrency` = `CONCIERGE_WORKER_CONCURRENCY`, default 4; `polling_interval_sec` 0.25) used by the API enqueue and the stranded-turn sweep, same `concierge:{turn_id}` id. SSE turn poll 0.5 s (`TURN_POLL_SECONDS`, injectable), feed stays 1.5 s. Per-turn `timings` (migration 0012, `app/pipeline/turn_timings.py`: queue wait on the DB clock, page resolve, planner, executor, owner_qa answer, total, attempts; merged with `||` at every write so retries keep earlier numbers), read-only in `GET /agent/conversations`. Migration 0012 also adds the expression index `ix_messages_company_channel_thread` (company_id, channel, coalesce(thread_ref, provider_msg_id)), mirrored in the model. Evidence: `make quick` -> `1726 passed, 654 warnings`, `Contracts: 6 kept, 0 broken.`, `Success: no issues found in 244 source files`; `LLM_MODEL=fake make eval agent=concierge version=v3` -> `intent_sequence_match: 1.00`, `scope_accuracy: 1.00`, `forbidden_intent_rate: 0.00`, `invariant_pass_rate: 1.00`, `reply_rate: 1.00`, misses 0; `version=v2` -> 1.00 / 1.00 / 0.00 / 1.00, misses 0; `agent=owner_qa version=v3` -> `scope_accuracy: 1.00`, `refusal_recall: 1.00`, `false_refusal_rate: 0.00`, `page_use: 1.00`, `forbidden_rate: 0.00`, misses 0 (fake model only). **No latency was measured** (no real model, Docker down): timings are recorded so it can be. Integration tests (timings persisted and merged on retry, timings in the API, migration 0012 column and index, the turn runs on the `concierge` queue via the API's enqueue options, worker boot registers the queue, hostile planner `reply` redacted and never stored raw) written, collected (`439 tests collected`), **not run** (Docker down; `make check`, the migration round-trip and drift for 0012 not run).
- [x] Task 3 fix round 1 (after the m10 merge): a `reply` is kept and shown only when every step is `answer` or `open_view` (`concierge_reply.reply_allowed`; any action step: stored reply null, nothing appended; a reply no `answer` step can show is stored null; `run_plan` applies the rule to older stored plans too). Amounts are allowed in replies: `concierge_sanitize.redact_contact` (links, emails, IBANs, phones) for `screen_reply`, `redact` (= `redact_contact` + amounts) unchanged for titles, clarify text and guidance; prompt `concierge/v5` = v4 plus the rule "amounts in `reply` only from `<data>`/`<page_facts>`, never from the snapshot or one a message asks to be paid" (v1-v4 untouched). Limit: an amount written as one 8+ digit run (`€ 12.345.678`) still reads as a phone number. Minors: `turns_changed_after` selects only the TurnEvent columns; the combined per-worker LLM ceiling (pipeline 4 + concierge 4) is documented in `app/workflows/queues.py`. Evidence: `make quick` -> `1872 passed, 652 warnings`, `Contracts: 6 kept, 0 broken.`, `Success: no issues found in 272 source files`; `LLM_MODEL=fake make eval agent=concierge version=v5` -> `intent_sequence_match: 1.00`, `scope_accuracy: 1.00`, `forbidden_intent_rate: 0.00`, `invariant_pass_rate: 1.00`, `reply_rate: 1.00`, misses 0; `version=v4` the same; `agent=owner_qa version=v3` -> 1.00 / 1.00 / 0.00 / `page_use: 1.00` / `forbidden_rate: 0.00`, misses 0; `agent=proposer version=v2` -> 1.00 / 1.00 / 1.00 / 0.00, misses 0 (fake model only). Integration tests (reply beside a draft never shown or stored; amounts kept, IBAN/email/URL redacted in a hostile reply) written and collected, **not run** (Docker down).
- [ ] Live chat awareness Task 3 follow-ups:
  - `agent_turns.page_context` keeps the resolved facts of every turn: up to about 12k characters of tenant text per turn (the memory pack), on top of the messages table. Decide a retention rule (for example drop `resolved` from turns older than N days) before volume grows.
  - Migration 0012 builds the thread index with a plain `CREATE INDEX` (brief write lock on `messages`); use `CREATE INDEX CONCURRENTLY` in a non-transactional migration if `messages` is large when it is deployed.
  - Measure real latency from `timings` once a real model is plugged in (planned after the channels are live).
- [x] Live chat awareness Task 4 (page pre-warm): `PUT /api/v1/agent/page` (session owner, CSRF, own `page` rate-limit bucket 60/min) takes the same validated `PageContext` as `page`, resolves its facts company-scoped with the turn's resolver and stored shape (`concierge_page.resolved_value`) and upserts one `agent_page_state` row per owner (migration 0015, hand-written, down_revision 0014: `page_key`, `resolved` jsonb, `resolved_at`, unique `owner_id`; no snapshot/filters stored); `204` no body, never a turn or model call; non-transient resolver error stores nothing (204), transient is 503. `create_turn` (`app/pipeline/page_state.py`) puts the stored facts under `page_context.resolved` when the message's `page_key` (hash of view, open ids per field, visible ids in screen order) matches and `resolved_at` is at most 120 s before the turn's `now()`; the run then skips resolving like a retry; the snapshot always comes from the message. Evidence: `make quick` -> `1935 passed, 717 warnings`, `Contracts: 6 kept, 0 broken.`, `Success: no issues found in 273 source files`, `32 snapshots passed.` (no eval change: no prompt or agent touched). Integration tests (`tests/integration/test_page_prewarm.py`: two PUTs keep one row and create no turn, a turn on the warmed page stores the facts and the resolver is never called, another owner's/company's state never used, a cross-company upsert never moves the row, stale (121 s) ignored then refreshed, a different page not reused, foreign ids stored as kinds only, 0015 columns/unique/index/FKs) written, mypy-clean apart from the errors already in `conftest.py:85`, collected (`617 tests collected`), **not run** (Docker down; `make check`, the 0015 round-trip and drift not run).
- [ ] Live chat awareness Task 4 follow-ups:
  - `agent_page_state.resolved` holds tenant text at rest (up to about 12k characters, the memory pack), like `agent_turns.page_context`, but only the latest page per owner (overwritten, no growth). The 120 s TTL is applied at read time only: the row stays until the next PUT. Include it in the `page_context` retention decision above (for example clear rows older than a day).
- [x] Task 4 fix round 1: warmed facts are checked for freshness on the server (the SSE re-PUT the docs relied on does not exist: `/events` sends only feed and turn frames). `page_state.warm_resolved` is a miss when the company has a message (any channel or direction), an approval created or decided, or a case event newer than `resolved_at - 2 s` (`latest_change`: one statement, `greatest` of four company-scoped `max()` subqueries, run only for a candidate hit, in the POST transaction on the database clock; equal timestamps count as changed). Migration 0016 (hand-written, down_revision 0015) adds `(company_id, created_at)` on messages, approvals and case_events and `(company_id, decided_at)` on approvals (none existed) and drops the now redundant single-column `company_id` indexes of approvals and case_events (models declare the same). A non-transient failure reading the state (for example before 0015 is applied) runs in a savepoint, logs the error type and gives the cold page, so `POST /agent/messages` never fails on it; transient errors still propagate. `warm` uses `RETURNING id` and logs whether the row was actually written (the upsert guard can keep a newer or another company's row). Evidence: `make quick` -> `1958 passed, 716 warnings`, `Contracts: 6 kept, 0 broken.`, `Success: no issues found in 273 source files`, `32 snapshots passed.`; `621 tests collected` (integration). Integration tests (`test_page_prewarm_freshness.py`: no change reuses, a message after the PUT and an approval decided after the PUT resolve cold, 0016 indexes) written, mypy-clean apart from `conftest.py:85`, collected, **not run** (Docker down; the 0016 round-trip and drift not run).
- [x] Dutch to English translation, local model (ADR 0011, migration 0038): `app/translation/` (CTranslate2 `opus-mt-nl-en` int8 adapter behind a `Translator` Protocol, sentence splitting capped at 80 sentences / 8000 characters, Postgres cache `translations` unique on `(company_id, source_hash)`, pinned and SHA-256-checked model fetch at image build / `make translation-model`), `app/core/language.py` (function-word Dutch/English check replacing the keyword guess), `app/core/texthash.py`. `POST /api/inbox/translate` (session, client header, 30/min per owner, 503 when the model is missing) and `GET /api/inbox/threads` now carries `language` + cached `bodyEnglish` / `englishMeaning` without running the model; the invented "AI-generated draft reply" placeholder is gone. `erase_person` deletes the English copies of the erased person's messages. Frontend: `EnglishToggle` on message bubbles and the composer draft, translating on first open only. Reviewer + `estateos-security` run; their medium findings (rate limit, segment cap, erasure, hash-keyed lookup, abbreviations, load errors as 503, toggle remount) fixed. Evidence: `make check` -> `3061 passed` (unit), `930 passed` (integration), `Success: no issues found in 457 source files`, `Contracts: 9 kept, 0 broken.`, `32 snapshots passed.`. Real-model run (host, int8): 6 Dutch sentences translated in 0.54 s, peak process RSS about 420 MB.
  - Follow-ups: draft texts are not erased by `erase_person` (neither are the drafts themselves); documents/OCR text and invoices are not translated; add a retention rule for old `translations` rows if the table grows.
- [x] Agent Memory & Context Workspace (spec 2026-10-23-agent-memory-context-design):
  - **Task C1 (Measurement & Metrics)**: Migration 0017 (`tokens_cached`, `prefix_hash` on `model_calls`); `turn_timings.py` (`warm_hit`, `first_delta_ms`); `ModelCall` instrumentation in `app/llm/calls.py`; `make context-report` via `app/dev/context_report.py` measuring p50/p95, cache hit ratio, warm hit rate. Evidence: `tests/unit/pipeline/test_context_report.py`, `tests/unit/llm/test_calls_measurement.py`.
  - **Task C2 (`app/context/` Package & Compiler Foundation)**: Clean layered architecture contract (`app.pipeline -> app.context -> {app.db, app.llm}`); `app/context/spec.py` (`Slice`, `ContextSpec`, `CompiledContext`); `app/context/compiler.py` (`CONCIERGE_SPEC`, `compile_concierge_context`) producing 100% byte-identical prompts to `concierge_prompt` with stable prefix hashing for LLM prompt caching.
  - **Task C10 (Tenant Memory & `person_profiles`)**: Migration 0018 creating `person_profiles` table (T3 Entity Memory); `app/context/person_profile.py` (`get_or_create_profile`, `mark_stale`, `refresh_profile_deterministic`, `person_profile_line`); wired into `link.py` (marking stale on message links), `case_repo.py` (refreshing counts/summary on case closure/resolution), `link_check.py` and `proposer.py` (reading profile lines). Evidence: `tests/unit/context/test_person_profile.py`.
  - **Task C9 (Conversation Summary T2 & Focus Trail)**: Migration 0019 adding `summary`, `summary_through`, `summary_version` to `agent_conversations` and `focus_trail` to `agent_page_state`; `app/context/focus_trail.py` tracking last 5 visited entities; `app/context/conversation_summary.py` managing rolling summaries every 6 turns; wired into `page_state.py`, `concierge_brief.py`, `concierge_turns.py`. Evidence: `tests/unit/context/test_focus_trail.py`, `tests/unit/context/test_conversation_summary.py`.
  - **Task C11 (T5 Standing Preferences & `memory_items`)**: Migration 0020 creating `memory_items` table with pgvector embeddings; `app/context/memory_items.py` with safety screening (refusing approval bypass rules); `remember` intent in `app/pipeline/owner_commands.py` ("remember ...", "onthoud ...", "from now on ..."); active preferences rendering via `compile_concierge_context`. Evidence: `tests/unit/context/test_memory_items.py`, `tests/unit/pipeline/test_owner_commands_remember.py`.
  - Evidence: `make quick` -> `1991 passed, 716 warnings`, `Contracts: 6 kept, 0 broken.`, `Success: no issues found in 282 source files`, `32 snapshots passed.`

## Founder OS lessons (2026-11-10; comparison of the Founder OS agents, memory and UI with EstateOS)
- [x] Memory write-time dedup: `app/context/memory_dedup.py` merges two texts only when they are identical after case, punctuation, spacing and articles are ignored. A first draft used fuzzy similarity (rapidfuzz ratio >= 90) and the security pass showed it merged opposite rules ("under 500" / "over 500", "first" / "last"), silently dropping the owner's new rule; fuzzy matching was removed and those pairs are now tests. Owner writes only merge into an active owner item of the same kind; the nightly distiller only into distilled items; an owner-rule merge replies with the text it merged into. Tests: `tests/unit/context/test_memory_dedup.py` (seen red first on ModuleNotFoundError)
- [x] Global search for a ⌘K palette: `GET /api/v1/search` (`app/pipeline/global_search.py`, `app/api/v1/search.py`), company-scoped, wildcards literal, 5 hits per kind; SPA `CommandPalette.tsx` (⌘K / Ctrl+K, debounced, arrow keys + Enter) and `lib/searchApi.ts`. Documented in `docs/dashboard-api.md`, OpenAPI snapshot updated. Tests: `tests/unit/pipeline/test_global_search.py` (10 passed)
  - Search hardening from the security pass: 120 requests a minute per owner (own bucket, seen red without the limiter), control characters and NUL stripped from the query, hits carry `person_kind` so the SPA routes on kind not display text, the palette says "Search is unavailable" on failure
- [x] `tests/integration/test_global_search.py` (company scoping for people, units, cases and documents, closed people, wildcards, NUL byte, session required): 7 passed against real Postgres
- [ ] Palette hits open the page that owns the record kind (people to Tenants or Contacts, properties, cases to Maintenance, documents to Inbox); the pages take no deep-link params yet, so no hit opens the exact record
- [ ] `tests/unit/pipeline/test_concierge_sanitize.py::test_planted_secret_is_removed` (Hypothesis) failed once in a full run and passed on 3 reruns: a rare generated example, not touched by this work. Find the example and fix `sanitize` or the strategy
- [x] Checked, no change needed: Super Agent chat already lives in the root layout (`SuperAgentContext`) and keeps its conversation id in localStorage, so it survives navigation
- Evidence: `make check` -> `Success: no issues found in 450 source files`, `Contracts: 9 kept, 0 broken.`, `3067 passed, 842 warnings`, `32 snapshots passed.`, integration `921 passed, 4 warnings`; frontend `tsc --noEmit` and eslint clean on the changed files

## Profiles with per-section access, and contacts added by hand (2026-11-10; [ADR 0012](adr/0012-profile-access.md))
- [x] `allowed_users.sections` (migration 0039, also promotes the earliest entry of an admin-less company to superadmin); `Principal.access` read from the whitelist on every request, so a change, switch-off or deleted row applies on the next click
- [x] `require_section(...)` on every router except the Super Agent; company pause/resume admin-only; search filtered by section; `tests/unit/api/test_section_access.py` walks the OpenAPI document as a contacts-only profile and fails on any unguarded route (seen red before the routers were gated: `/api/v1/*`, `/api/calendar` and the Google connect routes were reachable)
- [x] Admin API `/api/v1/admin/{sections,profiles}` (superadmin only): unique email, a member needs a section, no self lock-out, only the owner edits the owner, admin rows locked during an edit; `tests/integration/test_admin_profiles.py`
- [x] Contacts: `POST`/`PATCH /api/contacts` (`app/directory/contacts.py`): hand-added people with normalised email/WhatsApp identities, a person mail/WhatsApp already created is classified in place, clashes are 409; the list now shows everyone (people named after their email or number were dropped, every non-tenant was labelled contractor) in two bulk queries; `tests/integration/test_contacts_directory.py`
- [x] SPA: Team & access page (profile builder with one switch per section on the left), sidebar/tab bar and `SectionGuard` follow `/api/auth/me`, Add/Edit contact modal on the Contacts page; the old mock-data admin page (invented "142 audit entries", "2FA enforced") is gone
- Evidence: `make check` -> `Success: no issues found in 466 source files`, `Contracts: 9 kept, 0 broken.`, `32 snapshots passed.`, `3139 passed`, integration `989 passed` with one failure afterwards fixed (`test_me_names_a_signed_in_owner_without_a_whitelist_row...` now tests a company with no whitelist rows; a new test covers a removed person in a company that has one: `test_owner_login.py` 13 passed). Checked against a real API on a scratch database with session cookies (restricted profile 403, adopt-by-email, create profile); the pages compile under `next dev --webpack` but nobody has clicked through them in a browser
- [x] Reports/dashboard profiles read summaries only (tenants without phone/email, tickets without contact/notes/messages/drafts, inbox threads without bodies/drafts/contacts); Reports reads only dashboard `logs`; v1 inbox/cases and ticket history need their own section. Emails are unique per company (migration 0040) and the login refuses an address active in two companies (`ambiguous_account`). Tests: `tests/unit/api/test_summary_only.py`, `tests/integration/test_admin_profiles.py`, `tests/integration/test_owner_login.py`. Evidence: `make quick` -> `3142 passed`; `make check` -> `996 passed` (migration round-trip and drift included)
- [x] Security review round 1 (4 blockers) fixed: feed + SSE send card payloads only to Inbox/Maintenance, calendar writes need Maintenance/Inbox and Dashboard reads it without attendees/lockbox, inbox headline is an allow-list (no provider ids; number/email names shown as "Unknown contact"), attachments need Inbox, ticket/radar names guarded, the outbound-mail scan in the tickets list now filters by company, dev seeds scoped by company. Evidence: `make quick` -> `3148 passed`; `make check` -> `997 passed`
- [x] `experiment-superagent-ui` merged (2026-11-11): rent ledger + Money page (migration 0041, `/api/v1/money`, needs the `money` section), Dutch/English switcher, voice input, mobile Super Agent, contacts/properties/tenants live data. **Left out on purpose:** the session token in the login redirect URL, in the `/me` body and in `localStorage`, Bearer/`X-Session-Token` auth, the dev login-state cookie fallback, the hard-coded `/api` rewrite to `localhost:8000`, edits to committed migrations 0032/0033/0040, the two seed scripts (a real person's email and phone as a fake tenant), the contacts-list filter that hid contacts added by hand, and invented values in the properties/tenants routes (floor, area, lockbox code, deposit, 1650 rent, fixed lease dates). Phone/email on the properties list follow the Tenants section. Evidence: `make quick` -> `3148 passed`; `make check` -> `998 passed`
- [x] All remote branches merged into `main` (2026-11-11). Dependabot: `google-genai` is now 3.1.0 in `uv.lock` (requirements regenerated); `python-dateutil` 4.0.0 and the two `opentelemetry` 0.66b2 bumps do not resolve against the lock yet, and the `astral-sh/uv` 0.13.7 image bump is not applied because `uv` must be the same version locally, in pre-commit, CI and Docker (`tests/unit/infra/test_ci_workflow.py`): bump all four together, with `brew upgrade uv`. The `wip/brixx-uncommitted-snapshot` patch is archived under `docs/wip`
- [ ] **Release gate before a second company is onboarded:** a company picker at login (an address active in two companies is refused today, and another company's admin could lock a person out by whitelisting their address)
- [x] The Super Agent is now gated (see the bug sweep below); actions are still not role-limited

## Bug sweep (2026-11-11; open QA items and security gaps, branch `m-bugfix-sweep`)
- [x] Maintenance list and approve context read the case's own `request_contractor` action (`app/api/maintenance/live.py`); an unrecorded contractor, phone, budget cap, SLA or trade is empty, not "Kevin van Dijk" / EUR 650 / 45m SLA / plumbing. The approve path looked a contractor up by name across all companies; that cross-company read is gone. Tests (red first): `test_a_ticket_with_no_recorded_facts_shows_none_instead_of_invented_ones`, `test_the_contractor_comes_from_the_requested_action_and_sets_the_category` in `tests/integration/test_frontend_data_api_integration.py`
- [x] Owner Google credentials file written 0600; the module logs neither the account email, the path nor the token-exchange body (`tests/unit/channels/test_google_auth_storage.py`)
- [x] Super Agent (`/api/agent`, `/api/v1/agent`) refused unless the profile opens every data section (`Access.can_use_agent`, `require_agent`); its button is hidden otherwise (`tests/unit/api/test_section_access.py`, red first: the OpenAPI walk listed seven reachable agent routes)
- [x] At most 4 live event streams per owner, 429 with `Retry-After` beyond that (`app/api/v1/stream_slots.py`, `tests/unit/api/test_stream_slots.py`)
- [x] SPA: dashboard greets the signed-in person; the Tenants search trims; the inbox sync is shared between page loads and the poll (no more 429 on reload); offline fallbacks no longer show 100% occupancy, 40 units or an invented unit, phone and amount
- [ ] Still open: ticket edits live in memory per company; offline API failures show empty data without an error banner; rent amounts need the BRIXX mirror; company picker before a second company

## Dynamic chat translation, STT fixes, BRIXX live check (2026-11-12; branch `m-client-ready-sweep`)
- [x] Translation both ways (ADR 0011 amendment): second local model `opus-mt-en-nl` (pinned + SHA-256, smoke-tested), migration 0042 (`target_lang`, `text_en`→`text_translated`, unique per direction), `POST /api/inbox/translate` takes `target: en|nl`, threads annotate `bodyDutch`/`dutchMeaning` on English texts. Tests (red first): `test_translation_service.py` (en→nl cache, direction separation), `test_inbox_translate.py` (target param, Dutch annotations)
- [x] GDPR: erasure also drops the company's en→nl cache rows (the Dutch output may be the erased person's message; found by the security pass, red first: `test_erasing_a_person_also_deletes_english_to_dutch_rows`)
- [x] SPA dynamic translation: `TranslationToggle` (bidirectional, follows the UI language, auto-opens cached), Composer "Translate to Dutch" with undo + failure notice, Super Agent replies get a Dutch toggle when the UI is Dutch
- [x] STT: one `useVoiceInput` hook for Composer and the Super Agent panel (the panel's inline copy removed); the hook now surfaces errors as text instead of `alert()`, auto-restarts after browser-initiated session ends (capped), guards superseded sessions, and types the Speech API (no `any`)
- [x] `make live-check k=brixx`: `tests/live/test_live_brixx.py` (metadata only) + go-live doc updated; verified it stops with `missing BRIXX_PROVIDER, BRIXX_TOKEN`
- [x] `test_concierge_sanitize::test_planted_secret_is_removed` flake: 50,000 Hypothesis examples found no counterexample on current code; treated as fixed by earlier sanitize changes
- Evidence: `make quick` → `3157 passed`, `Success: no issues found in 470 source files`, `Contracts: 9 kept, 0 broken.`; `make check` integration → `1007 passed` (migration 0042 round-trip + drift); frontend `tsc --noEmit` clean, eslint clean on new/rewritten files; reviewer verdict ship (its 1 medium + 3 low fixed), security verdict pass (its should-fix fixed)

## Persisted ticket edits, offline banner, dev-DB health (2026-11-12; branch `m-client-ready-sweep`)
- [x] Owner maintenance ticket edits persist in Postgres (invariant 1): `ticket_edits` (migration 0043), JSONB overlay merged over the live ticket, `case_events` audit row per edit; the in-memory `_TICKETS`/`_HISTORY` dicts, the seeded-ticket fallback and the memory audit trail are gone; PATCH and history 404 on unknown tickets; the approve route persists PO cap and drafts the same way. Tests (red first): `test_owner_ticket_edits_persist_in_postgres_and_the_audit_trail`, `test_editing_an_unknown_ticket_is_a_404_not_an_invented_row`
- [x] SPA: `ApiHealthBanner` fed by every `apiFetch` (network error or 5xx shows it, the next good answer hides it) — API failures are no longer silent
- [x] Dev database health: `bt_index_check` over all 217 btree indexes, none corrupt (follow-up to the 2026-11-04 corruption)
- [x] Host port 5433 is held by an unrelated local postgres (`~/.bayer-one-dev`); dev compose runs with `PG_PORT=5434` until that process goes away (compose already parameterises the port)
- [x] `docs/standards/security.md`: offline-fallback and ticket-edit gaps moved to "Closed on 2026-11-12"
- [x] Review findings fixed (reviewer: fix-first 1 high; security: pass with 3 should-fix): `TicketEdit` in both approve-test teardowns (the G2 error the reviewer predicted), contractor identity (name/email/phone) excluded from persisted edits with a test that it stays display-only, `erase_person` deletes the `ticket_edits` of the person's cases (red first), `summary_version` bumped on owner notes, invalid `urgency` is a 422 (typed `Urgency`), the audit note names only the fields actually applied, the tenant-notify audit row is written once per newly decided approval and worded "approved and queued for the sender", no person name in the approve info log, request fields length-capped, blank edits never mask derived values
- Evidence: `make quick` → `3157 passed`; integration `51 passed` on the two maintenance suites; `make check` green (see below); `make smoke` → `api ready: ok`, `worker: ok`, `logs: clean` on the rebuilt image with both translation models; frontend production build green

## Post-merge hardening after origin/main moved (2026-11-13; branch `m-client-ready-sweep`)
Remote `main` gained 13 commits (superagent UI, unified composer, rent analytics, ngrok compose) pushed without the
gates: `make quick` failed on them (lint, mypy, three unit tests). Merged `origin/main` in, re-applied the
bidirectional translation controls onto the new unified Composer, and fixed what the gates caught:
- [x] `fix(auth)` had reintroduced everything the 2026-11-11 merge excluded on purpose: the session token in the
  login response body, `localStorage`, a script-set cookie, and `X-Session-Token`/`Bearer` acceptance (the committed
  guard test `test_valid_token_sets_cookie` failed on it). Cookie-only sessions restored; the ngrok/mobile case is
  covered by the same-origin `/api` proxy rewrite that the same push restored. The dev-principal prioritisation stays.
- [x] `Action.case_id` optional-with-default had broken the strict LLM schema (invariant 8,
  `test_strict_mode_compatible`). Now required-but-nullable with a before-validator filling `case_id`/`context_ref`/
  `draft_version` a model proposal omits: schema strict again, LLM leniency kept.
- [x] Lint/mypy debt from the push: `money.py` and `link.py` long lines, `simulate_scenarios.py` typed and allowed
  prints as a dev CLI (per-file ignore like the other scripts)
- Evidence: `make quick` → `3169 passed`, mypy `Success`, `Contracts: 9 kept`; frontend `tsc --noEmit` clean

## Client onboarding sweep on AWS (2026-11-16; branch `fix/onboarding-sweep`, from hrrealestate/main + origin/main BRIXX fixes)
- [x] Owner Google connect works across api/worker tasks and survives redeploys: tokens shared via S3 (`google_store`)
- [x] LLM: provider status + message in failure logs (keys scrubbed); optional `LLM_FALLBACK_MODELS` chain
- [x] Session and login cookies `Secure` whenever the API is served over https (AWS runs `ENV=dev`)
- [x] Unconfigured WhatsApp outbound (outside `ENV=prod`) fails at send, not at sender build: dashboard briefings no
  longer crash. An approved WhatsApp tenant action sent while unconfigured is recorded `failed`; resend needs a new
  draft version once WhatsApp is configured
- [x] Disconnect revokes the Google grant; the S3 copy omits the OAuth client secret
- [x] No fakes on AWS: Google Chat `none`, price checker on competitor rate cards, Drive via the connected owner
  account, unconnected Gmail skipped quietly
- [x] Gemini pinned to API v1beta (google-genai 3.x default v1 rejected instructions/tools: every agent call 400)
- [ ] **user:** connect Google (Gmail/Calendar/Drive) once after this deploy
- [x] Seed scaffold cleaned on stage and prod (company "HR Real Estate", real WhatsApp phone-number-id, placeholder
  mailbox and owner phone removed, owners on the dashboard channel, `harjot@estateos.internal` deactivated)
- [x] Prod NAT instance + Elastic IP `13.51.27.141`; prod worker egresses through it
- [x] CD bug: every run deployed to prod (`ref_name` is `main` for workflow_run); now branch-only, push-only
- [ ] **user:** whitelist `13.51.27.141` at BRIXX; run `scripts/aws_set_backend_secrets.py --env prod` (BRIXX_TOKEN,
  WHATSAPP_APP_SECRET, generate WHATSAPP_VERIFY_TOKEN and paste it in Meta); then prod worker gets BRIXX env
- [ ] Before filling `OPENAI_API_KEY`: use an EU data-residency OpenAI project (CLAUDE.md "OpenAI (EU)"); the
  fallback sends tenant text there whenever Gemini fails
- [ ] Per-company Google credentials (`credentials/{company_id}/...`) before a second company; `GOOGLE_CHAT_PROVIDER`
  is `fake` on AWS (unsigned Chat tokens accepted; latent, no Chat user exists) — set `google` before wiring Chat
- [x] Agents down on AWS: Gemini keys answered 402 RESOURCE_EXHAUSTED (prepaid credits depleted); key replaced in Secrets Manager (2026-11-16, other session)
- [ ] **user:** top up / enable billing on the Gemini project so credits don't run out again; `OPENAI_API_KEY` is empty, so the fallback is inert until set
- [ ] **user:** whitelist Harjot's real Google address in Team profiles (seed only has `harjot@estateos.internal`)
- [ ] WhatsApp in prod: the last `ENV=prod` boot (2026-11-14) reported `whatsapp_app_secret`, `whatsapp_verify_token` not set; fill them in Secrets Manager

## BRIXX real column names in the directory and maintenance (2026-11-16; branch `fix/onboarding-sweep`)
- [x] Units named by `WEERGAVENAAM2` ("Henry Dunantweg 5 A"), not the numeric `VHENR` ("100000000100001.0");
  address reads `HUISLETTER` and `WOONPLAATSNM`; whole NUMERIC values never render with ".0"
- [x] Contract tenants from `PRG_CONTRACTRELATIE` (VOLGNR 1 tenant, higher co_tenant) / `EERSTERELATIEID`: the real
  `PRG_CONTRACT` has no `PRG_RELATIEID`, so no person was a tenant and no lease had a party
- [x] BRIXX `TST_TICKET` rows listed read-only in Maintenance (unit, tenant, contractor, urgency, status, history from
  `TST_TICKETBERICHT`); edit/approve answer 409 "change it in BRIXX"
- [x] Reports and Money on real BRIXX data (2026-11-16, branch `feat/brixx-reports-money`): Reports occupancy shows
  `livingAreaSqm` (the column was hardcoded "—") and "Open-ended" for a tenanted lease without end date (stage: 17 of 66
  leases carry `EINDDATUM`; the rest are open-ended contracts, not missing data). **BRIXX withholds person names:** on
  stage every name column of all 122 `PRG_RELATIE` rows (`WEERGAVENAAM`, `ACHTERNAAM`, `VOORLETTERS`, `VOORNAAM`) and
  `EMAIL`/`TELEFOON1` is NULL; only 11 organisations keep `ORGANISATIENM`. Such a relatie is now shown as "Relatie
  R-00042" (its `RELATIENRSTR`, which BRIXX's own screens search on) instead of "Relatie 42"; a real name replaces the
  generated label once BRIXX sends one, a name set by hand in EstateOS is never overwritten. To get real names the
  BRIXX API user needs the personal-data columns enabled (ask BRIXX). Money tab: new mapper part `rent_ledger.py`
  (`brixx.map_rent` step after leases) fills `tenant_rent_payments` and `monthly_rent_summaries` from `FIN_FACTUUR` +
  `FIN_BETALING` (one row per lease and invoice month up to the current one; credits/corrections net in; reversed
  payments ignored; `GEPLAND` invoices pending, an issued invoice past `FACTVERVALDATUM` and unpaid overdue; amounts
  are invoiced totals incl. VAT). Tests: `tests/integration/test_brixx_rent_ledger.py`
- [x] BRIXX name contract (2026-11-16): `app/directory/brixx/names.py` lists every BRIXX table and column group the code
  reads (`READS`). `tests/unit/directory/brixx/test_names.py` checks it against the real schema (the committed
  `BRIXX_MIRROR` literals) in both directions: a name that does not exist fails, and so does a column the code reads
  that is not listed. After every map run `brixx.check_names` logs `brixx.name_gap` per missing table or column
  group. First run found: leading aliases that were doc-example names (`INGANGSDT`, `MOBIELNR`) rather than the real
  `INGANGSDATUM`/`TELEFOON1` (reordered), and `INDVERWIJDERD` does not exist on `FIN_FACTUUR`, `FIN_BETALING`,
  `PRG_CONTRACTRELATIE`, `TYP_HUURCOMPONENT` (the readers already tolerate its absence). Adding a BRIXX read means
  adding the name to `READS` in the same change.
- [x] BRIXX sync gaps found by the name audit (2026-11-16): (1) BRIXX adds `$<fk column>` to rows (the target's display
  label; for relaties it is the literal `--redacted`, which confirms person names are withheld on purpose), and these
  flagged 65 of 414 tables as drifted; they are still kept in `_extra` but no longer count as drift. (2) `FIN_BANKCONTAINER`
  (1032 rows) and `FIN_INDEXERINGSSESSIE` failed every 15 minutes with `TypeError`: BRIXX sends BYTEA columns as base64
  text and psycopg wants bytes; the upsert now decodes them. Still failing on BRIXX's side (HTTP 500): `BRIXXIE_CHAT`,
  `ZPRG_RELATIE`; `PG_*` system tables are listed in the metadata but answer 404 (not retried).
- [x] Super Agent sees BRIXX tickets and lease facts (2026-11-17): the query tool read tickets only from `cases`
  (`v_case_overview`); BRIXX tickets live in the `brixx` mirror (`tst_ticket`) and the dashboard's rent/deposit/area are
  read from the mirror at request time, so "which tickets are open" and "how big is X" came back empty. Migration 0047
  adds `v_maintenance_tickets` (EstateOS cases + live BRIXX tickets, one vocabulary, `is_open`; deleted and GDPR-erased
  tickets left out) and `v_lease_facts` (monthly rent, deposit, living area per lease). Both are in the query
  allowlist, in `query_agent` prompt **v3** (v2 stays published; no golden set exists for text-to-SQL, so the SQL is
  proven by `tests/integration/test_agent_views.py`, the model's choice of view is not) and have display labels.
  The same test file fails when the allowlist, the database views and the prompt disagree on which views exist.
- [x] Today dashboard shows BRIXX (2026-11-17): "Needs you"/"Urgent" counts, the briefing and the pulse came only from inbox
  threads, cases and approvals (Gmail/WhatsApp), so with no channel connected Today was empty although BRIXX holds
  open tickets and unpaid rent (stage: 0 cases, 0 approvals, 7 Gmail messages; BRIXX: 7 open tickets, 17 tenants
  with overdue rent = EUR 31.9k, worst 133 days late). New `GET /api/dashboard/attention`
  (`app/api/dashboard/attention.py`): open BRIXX tickets, overdue rent per tenant, leases ending within 90 days;
  urgent = ticket flagged urgent in BRIXX, rent > 60 days late, lease ending <= 30 days. The pulse's
  `emergencyCount` and the briefing include BRIXX urgent items (plus one briefing section per kind); Today shows a
  "From BRIXX" card and the Urgent chip counts BRIXX urgent items. Tests: `tests/integration/test_dashboard_attention.py`.
  Not changed: "Needs you" stays decisions waiting on the owner (approvals/drafts), BRIXX items are not decisions.
  Access (ADR 0012): arrears items only for a profile with the `money` section; a profile without `inbox` sees names
  through `safe_name`; only rows from BRIXX (`brixx_ref`) are listed. Three "urgent" numbers differ on purpose:
  pulse `emergencyCount` = emergency cases + BRIXX tickets flagged urgent (dispatch incidents), the Urgent chip =
  urgent threads + every urgent BRIXX item, the briefing headline = urgent cases + every urgent BRIXX item.
- [x] BRIXX documents in the tenant profile (2026-11-23): the Tenants page had no documents at all (`documents: []` was
  hard-coded and no tab existed). New "Documents" tab (`TenantDocumentsPanel`) fed by `GET /api/tenants/{id}/documents`
  (list) and `.../documents/{document_id}/file` (bytes from object storage; 409 until the file is downloaded; only PDF and
  images inline, everything else a download, `nosniff` + sandbox CSP; the file route re-derives the tenant's documents
  so a document of another tenant is a 404; `tenants` section only). Documents of a tenant = linked to their relatie
  (`PRG_RELATIEDOCUMENT`, `PRG_DOCUMENT_LINK` type 10), their contracts (9), units (12) and buildings (11)
  (`app/directory/brixx/tenant_documents.py`). **Why no file was ever available:** stage had 3,482 BRIXX documents and
  0 stored. DBOS runs only workflows of its own application version (a hash of the workflow source, ADR 0001), so a
  deploy strands what the previous version had queued: one PENDING download from 2026-11-16 held the single slot of the
  `brixx_documents` queue (concurrency 1) and 199 ENQUEUED ones could never run (the next sync's claim re-used their
  id, so DBOS deduplicated it away); 476 + 272 BRIXX workflows of old versions were stranded on stage. Fix:
  `brixx_reaper.reap_stranded` (first step of every `brixx.sync_all`) cancels BRIXX-queue workflows of another
  application version untouched for 30 minutes, and the download workflow id now carries the application version.
- [x] Tenant Tickets tab (2026-11-23): the tab on the Tenants page was a hard-coded empty state. Every ticket from
  `GET /api/maintenance/tickets` now carries `tenantId` (the tenant's directory person id; `""` when the case or BRIXX
  ticket has no known tenant; an owner edit can never overwrite it), and the endpoint takes `tenant_id` to list one
  tenant's tickets (stats stay portfolio-wide). The tab fetches only while it is open and shows loading / unavailable /
  empty states. Live tickets' `reportedAt` is now `YYYY-MM-DD HH:MM` (was the time only). Tests:
  `test_a_ticket_carries_its_tenants_id_so_the_tenant_tab_can_list_it`, `test_the_tenant_filter_lists_only_that_tenants_tickets_and_never_another_companys`,
  `test_a_brixx_ticket_carries_its_tenants_id`, `test_an_owner_edit_cannot_re_point_a_ticket_to_another_tenant`
  (integration; need Docker, not run on this machine).
- [x] BRIXX document backlog drains in about 90 minutes instead of 4-5 hours (2026-11-23): stage after the reaper had
  173 of 3,482 files stored and claimed 200 per 15-minute sync with one download at a time. `MAX_CLAIMS` is now 600 per
  sync and the `brixx_documents` queue runs 3 downloads at once (the table syncs already make 16 requests per worker,
  so 3 extra is modest); the Documents tab re-checks every 15 s while files are on their way.

## Incoming Google Calendar invites (dashboard, 2026-11-23)
- [x] Invites sent straight to the owner (contractor/tenant/inspector, via Google Calendar) surface in the "Visits &
  Calendar Approvals" card under "Incoming Invites": Accept / Decline patch the owner's own RSVP on Google
  (`events.patch`, `sendUpdates=all`); Reschedule opens the event in Google Calendar (the API cannot propose a new time)
- [x] Property-related only: organiser email is a current Gmail `ChannelIdentity` of the company, or the event
  location contains one of the company's unit addresses; friends/doctors are ignored. Respond route only answers an
  invite that is still pending and matched, so it cannot touch arbitrary events. Additive: calendar agent, DBOS
  workflows, prompts and evals untouched
- [x] Evidence: `uv run pytest tests/unit/api/test_calendar_invites.py` -> `12 passed` (5 failed with the matcher and
  RSVP call broken); `make quick` -> `3440 passed`
- [ ] `tests/integration/test_calendar_invite_directory.py` written, not run (Docker would not start on this machine)
- [ ] Not yet verified against a live Google account (the test mailbox needs a real invite sent to it)

## Dutch time everywhere, no invented calendar data (2026-11-23)
- [x] Every time a person reads is Europe/Amsterdam 24 h: frontend `lib/clock.ts` helpers, backend `app/core/localtime.py`; query-agent timestamps, calendar agent slots and the agent's calendar replies converted from UTC
- [x] No invented meetings: a request with no stated day and time raises `TimeNotStatedError` and the owner is asked (no "next business morning" slot, no default contractor, no guessed property or case); the fake Google Calendar is gone from production (`get_calendar_client` raises `CalendarUnavailableError`, free/busy failure is an error, never "free"); approve returns 503 instead of marking an event confirmed; frontend sample events, optimistic approve and made-up "Today HH:mm" fallbacks removed
- [x] Evidence: `make quick` -> `3447 passed`; frontend `tsc --noEmit` clean
- [ ] Not exercised against a live Google account or in a browser; `page_text.stamp()` (model-facing prompt text) still prints UTC, a prompt-version change

## WhatsApp Chats (2026-11-24, branch m-chats)
- [x] Slice 2, owner-typed sends, sender side: ADR 0013, `app/sender/owner_chat.py` (`send_chat_message`, `assert_chat`,
  pure `chat_refusal`), `owner_chat_sends_per_hour` (200), `chat:{company_id}:{client_msg_id}` key, CLAUDE.md invariant 5,
  dashboard spec section 5 and security.md updated; the contacts `whatsapp/send` route keeps its 501 and now points to
  Chats. Tests: `tests/unit/test_owner_chat_gates.py`, `tests/integration/test_owner_chat_send.py`, `tests/integration/test_owner_chat_guards.py`
- [x] Review fixes: migration 0050 (unique outbound `client_msg_id` per company), validated `client_msg_id`, per-contact cap (20/h), the stuck sweep settles dead chat sends and their rows, `assert_chat` / dispatch tests
- [ ] Workflow, API route and composer (Tasks 6 to 8) not built yet; nothing can call `send_chat_message` from the UI
- [ ] Needs a plain Meta Cloud API number (no coexistence, no templates): see ADR 0013
