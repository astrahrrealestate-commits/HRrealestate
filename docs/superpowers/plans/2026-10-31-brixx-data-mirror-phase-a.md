# BRIXX Data Mirror — Phase A (client + sync engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task follows the project pipeline (`/ship`: RED → GREEN → REFACTOR → `make quick` → `make check` if db/workflows/api → reviewer → commit).

**Goal:** A tested, fake-backed BRIXX client and sync engine that mirrors any BRIXX table into typed Postgres tables incrementally and resumably, with status visible over the API. No live access needed.

**Architecture:** The HTTP adapter and fake live in `app/channels/brixx/` (adapter layer). Schema building, upsert, sync loop and state live in `app/directory/brixx/` (above db and channels in the import-linter layers). DBOS workflows in `app/workflows/brixx_sync.py` run a 15-minute cron that fans out one child workflow per table on a new `brixx` queue; each page is one step. Mirror tables are SQLAlchemy `Table`s built from BRIXX metadata in their own `MetaData(schema="brixx")` (not `Base.metadata`, so the drift check ignores them); Phase B emits their Alembic migration from the same builder.

**Tech Stack:** httpx (+ respx in tests), SQLAlchemy 2 Core upserts (`postgresql.insert ... on_conflict_do_update`), DBOS Transact, Alembic, structlog, FastAPI. No new dependencies.

**Spec:** [docs/superpowers/specs/2026-10-31-brixx-data-mirror-design.md](../specs/2026-10-31-brixx-data-mirror-design.md)

## Global Constraints

- Python 3.12, mypy strict, functions < 40 lines, modules < 300 lines, errors subclass `EstateOSError`, structlog only, no `print`.
- BRIXX base `https://mob.brixxonline.com/api/v1`, environment `hrrealestate`; data at `/bigdata/{env}/table/{name}`, metadata at `/metadata/{env}/tables` and `/metadata/{env}/tables/{name}`.
- Auth: token in the `Authorization` header (raw vs `Bearer` form is unconfirmed: the adapter takes a `brixx_auth_scheme: Literal["raw","bearer"] = "bearer"` setting). `401`/`403` is non-retryable (`BrixxAuthError`).
- Filters: `[col op value]`, operators `< <= > >= = <> like`, dates `yyyy-MM-dd`, must be URL-encoded. Pagination via `links.next`; `meta.currentPage`, `meta.perPage`.
- BRIXX encodes null as `{}`; the normaliser converts `{}` to `None`.
- Mirror table rules: schema `brixx`, lower-cased BRIXX names, plus `company_id uuid NOT NULL`, `_synced_at timestamptz`, `_deleted_at timestamptz NULL`, `_extra jsonb`. PK `(company_id, <pk column>)`.
- Workflow ids deterministic: `brixx:{run_id}:{table}`; cron-triggered run id derived from the scheduled hour/minute bucket. Incremental overlap 5 minutes. Queue `brixx`, `worker_concurrency=2`. Default interval 15 min (`brixx_sync_interval_minutes`).
- Invariants 1–3, 7, 9 (CLAUDE.md): rows committed before work, idempotent steps, no I/O in workflow bodies, adapters behind interfaces, never edit committed migrations.
- Never log the token, `Authorization` header, row values or `ZOEKID`. Log table names, counts, page numbers, error class names only.
- `make migration` / `/new-migration` assigns the next revision number (parallel work on `app/contracts/finance.py` may also add one: rebase the revision chain, do not renumber committed files).
- `app/dev` must not be imported by production code; fakes live next to the adapter (`app/channels/brixx/fake.py`), like the Gmail fake.

## Review Focus

1. A page that is replayed or arrives out of order must never overwrite a newer row (older `VERSIENR`/`UPDDATETIME` loses).
2. Table with no `UPDDATETIME` column: must do a full fetch with hash compare, not crash on the filter.
3. BRIXX adds a column the mirror table lacks: row still loads, value lands in `_extra`, table flagged drifted, run not failed.
4. Crash after page N of M: the next attempt resumes at page N+1 and never marks the table successful early.
5. `401` mid-run (IP removed from whitelist): table state shows the auth error, other tables not retried pointlessly, no token in logs.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/channels/brixx/models.py` | `BrixxField`, `BrixxTable`, `BrixxPage` (frozen dataclasses) |
| `app/channels/brixx/ports.py` | `BrixxApi` Protocol, `BrixxError`, `BrixxAuthError` |
| `app/channels/brixx/query.py` | `build_filter`, `data_url_params` (pure) |
| `app/channels/brixx/normalise.py` | `normalise_row` (`{}` → `None`) |
| `app/channels/brixx/http.py` | `HttpBrixxApi` (httpx) |
| `app/channels/brixx/fake.py` | `FakeBrixxApi` (in-memory tables, pages, scripted failures) |
| `app/directory/brixx/schema.py` | type map, `MirrorSpec`, `build_table` |
| `app/directory/brixx/upsert.py` | `upsert_page` |
| `app/directory/brixx/state.py` | sync run/table state repository |
| `app/directory/brixx/sync.py` | `plan_table`, `sync_page`, drift detection |
| `app/db/models/brixx.py` | `BrixxSyncRun`, `BrixxSyncTableState` |
| `app/workflows/brixx_sync.py` | cron + per-table DBOS workflows |
| `app/api/v1/brixx.py` | `GET /api/v1/brixx/status` |

---

### Task 1: Settings, errors, production guard

**Files:**
- Modify: `app/core/settings.py`, `app/core/errors.py`, `app/core/startup.py`, `.env.example`
- Test: `tests/unit/core/test_startup_brixx.py`

**Interfaces:**
- Produces: `Settings.brixx_provider: Literal["fake","api"] = "fake"`, `brixx_base_url: str = "https://mob.brixxonline.com/api/v1"`, `brixx_environment: str = "hrrealestate"`, `brixx_token: SecretStr | None`, `brixx_auth_scheme: Literal["raw","bearer"] = "bearer"`, `brixx_sync_interval_minutes: PositiveInt = 15`, `brixx_timeout_sec: float = 60.0`. `BrixxError(EstateOSError)` and `BrixxAuthError(BrixxError)` in `app/core/errors.py` (so every layer can catch them).

- [ ] **Step 1: Write failing tests** in `test_startup_brixx.py`: `production_problems` with `env="prod"` and `brixx_provider="fake"` contains `"brixx_provider is 'fake'"`; with `brixx_provider="api"` and no token contains `"brixx_token is not set"`; with `env="dev"` and defaults there are no brixx problems. Use the helper that other `test_startup*` tests use to build prod-valid settings.
- [ ] **Step 2: Run** `uv run pytest tests/unit/core/test_startup_brixx.py -v`; expect FAIL (attributes missing).
- [ ] **Step 3: Add the settings fields, error classes and the two guard checks** in `production_problems` (follows the existing `whatsapp_provider` pattern); add commented placeholder lines for the new variables to `.env.example` (never a real token).
- [ ] **Step 4: Run** the test; expect PASS. Run `make quick`.
- [ ] **Step 5: Commit** `feat(brixx): settings, errors and production guard`.

### Task 2: Models, query builder, normaliser (pure)

**Files:**
- Create: `app/channels/brixx/__init__.py`, `models.py`, `ports.py`, `query.py`, `normalise.py`
- Test: `tests/unit/channels/brixx/test_query.py`, `test_normalise.py`

**Interfaces:**
- Produces (`models.py`): `BrixxField(id: int, name: str, type: str, required: bool, fk_table: str | None, fk_field: str | None)`; `BrixxTable(name: str, primary_key: str, fields: tuple[BrixxField, ...])`; `BrixxPage(rows: list[dict[str, object]], page: int, per_page: int, has_next: bool)`.
- Produces (`ports.py`): `class BrixxApi(Protocol)` with `list_tables() -> list[tuple[str, str]]` (name, primary key), `describe_table(name: str) -> BrixxTable`, `fetch_page(table: str, *, page: int, filters: str | None = None, order_by: str | None = None) -> BrixxPage`, `download_document(document_id: int) -> bytes` (used from Phase C; implemented now so the port is stable).
- Produces (`query.py`): `build_filter(*conditions: tuple[str, str, str | int | datetime | date]) -> str` joining `[col op value]` with ` and `, dates rendered `yyyy-MM-dd`; `data_query_params(page: int, filters: str | None, order_by: str | None) -> dict[str, str]` (httpx URL-encodes).
- Produces (`normalise.py`): `normalise_row(row: dict[str, object]) -> dict[str, object]` mapping `{}` (empty dict) to `None`, leaving other values untouched.

- [ ] **Step 1: Write failing tests.** `test_build_filter_single`: `build_filter(("upddatetime", ">=", date(2024,1,1))) == "[upddatetime >= 2024-01-01]"`. `test_build_filter_and`: two conditions joined with `" and "`. `test_params_page_default`: `data_query_params(1, None, None) == {"page": "1"}`. `test_params_filter_and_order`: includes `"filters"` and `"orderby"`. `test_normalise_null_object`: `normalise_row({"website": {}, "id": 1, "name": "x"}) == {"website": None, "id": 1, "name": "x"}`; a non-empty dict value stays as is.
- [ ] **Step 2: Run** `uv run pytest tests/unit/channels/brixx -v`; expect FAIL (import errors).
- [ ] **Step 3: Implement** the modules with the signatures above.
- [ ] **Step 4: Run** tests; expect PASS. `make quick`.
- [ ] **Step 5: Commit** `feat(brixx): models, port, filter builder and null normaliser`.

### Task 3: HTTP adapter and fake

**Files:**
- Create: `app/channels/brixx/http.py`, `app/channels/brixx/fake.py`
- Modify: `app/workflows/deps.py` (add `brixx_api()` built from settings, like `gmail_mailbox`)
- Test: `tests/unit/channels/brixx/test_http.py`, `test_fake.py`

**Interfaces:**
- Consumes: `BrixxApi`, models, `build_filter`, `data_query_params`, `normalise_row`, `BrixxAuthError`, `BrixxError`.
- Produces: `HttpBrixxApi(base_url: str, environment: str, token: SecretStr, auth_scheme: Literal["raw","bearer"], timeout_sec: float, client: httpx.Client | None = None)`; `FakeBrixxApi(tables: dict[str, FakeTable], page_size: int = 50)` with `FakeTable(info: BrixxTable, rows: list[dict[str, object]])`, plus `FakeBrixxApi.fail_on(table: str, page: int, error: BrixxError)` to script failures and `fetch_log: list[tuple[str, int, str | None]]` recording (table, page, filters). The fake applies a simple `[col >= value]` filter on `upddatetime` so incremental logic is testable.

- [ ] **Step 1: Write failing tests** (respx): `test_list_tables_parses_names_and_pk` (200 with `[{"name":"PRG_RELATIE","primaryKeyField":"PRG_RELATIEID"}]`); `test_describe_table_parses_fields_and_fk` (field with `references`); `test_fetch_page_follows_has_next` (`links.next` present means `has_next=True`, absent means False; rows normalised); `test_auth_header_bearer_and_raw`; `test_401_raises_auth_error_without_retry` (exactly one request made, message does not contain the token); `test_5xx_raises_brixx_error`. Fake: `test_fake_paginates`, `test_fake_incremental_filter`, `test_fake_scripted_failure`.
- [ ] **Step 2: Run** the tests; expect FAIL.
- [ ] **Step 3: Implement.** Adapter uses one `httpx.Client`, maps status codes to errors (401/403 → `BrixxAuthError`, other ≥400 → `BrixxError` with status code only). Retries belong to DBOS steps, not the adapter. Wire `deps.brixx_api()` to return the fake when `brixx_provider="fake"`.
- [ ] **Step 4: Run** tests; expect PASS. `make quick` (import-linter must pass: adapter imports only `app.core`, `app.channels.brixx`).
- [ ] **Step 5: Commit** `feat(brixx): httpx adapter and fake`.

### Task 4: Mirror schema builder

**Files:**
- Create: `app/directory/brixx/__init__.py`, `app/directory/brixx/schema.py`
- Test: `tests/unit/directory/brixx/test_schema.py`

**Interfaces:**
- Consumes: `BrixxTable`, `BrixxField`.
- Produces: `sql_type(brixx_type: str, *, is_key: bool) -> sa.types.TypeEngine` (map from spec: `NUMBER` on `*ID`/FK/PK columns → `BigInteger`, other `NUMBER` → `Numeric` without precision, `VARCHAR(n)` → `String(n)`, `DATE` → `Date`, `TIMESTAMP*`/`DATETIME` → `DateTime(timezone=True)`, unknown → `Text`); `MIRROR_SCHEMA = "brixx"`; `build_table(info: BrixxTable, metadata: sa.MetaData) -> sa.Table` adding the system columns and PK `(company_id, <pk lower>)`, indexes on FK columns and on `upddatetime` when present; `has_incremental_column(info: BrixxTable) -> bool` (field named `UPDDATETIME`, case-insensitive).

- [ ] **Step 1: Write failing tests.** `test_type_map` table-driven over the rules above, including `VARCHAR(132)` → length 132 and an unknown type → `Text`. `test_build_table_columns`: a `BrixxTable("PRG_RELATIE", "PRG_RELATIEID", ...)` yields table `brixx.prg_relatie` with columns `prg_relatieid`, original columns lower-cased, and `company_id`, `_synced_at`, `_deleted_at`, `_extra`; PK columns are `company_id, prg_relatieid`. `test_fk_column_indexed`. `test_has_incremental_column`. `test_not_in_base_metadata`: building a table does not add anything to `Base.metadata`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/directory/brixx -v`; expect FAIL.
- [ ] **Step 3: Implement** as specified. `company_id` is a plain `Uuid` column (no FK across schemas, spec: company consistency enforced in repository layer).
- [ ] **Step 4: Run** tests; expect PASS. `make quick`.
- [ ] **Step 5: Commit** `feat(brixx): mirror table builder and type map`.

### Task 5: Sync state tables and migration

**Files:**
- Create: `app/db/models/brixx.py`, new Alembic revision via `make migration m="brixx sync state"` (see `/new-migration`)
- Modify: `app/db/models/__init__.py` (register), `app/db/enums.py` (`BrixxRunKind`, `BrixxRunStatus`)
- Test: `tests/integration/test_brixx_state_models.py`

**Interfaces:**
- Produces: `BrixxSyncRun(CompanyScoped)`: `kind: BrixxRunKind` (`incremental|reconcile`), `status: BrixxRunStatus` (`running|succeeded|failed`), `started_at`, `finished_at`, `error: str | None`. `BrixxSyncTableState(CompanyScoped)`: `table_name: str`, `last_success_upd: datetime | None`, `last_page: int` (default 0), `row_count: int`, `last_error: str | None`, `drifted: bool`, `last_run_id: UUID | None`; unique `(company_id, table_name)`.

- [ ] **Step 1: Write failing test:** inserting two `BrixxSyncTableState` rows with the same `(company_id, table_name)` raises `IntegrityError`; a run row round-trips with enum values.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_brixx_state_models.py -v`; expect FAIL.
- [ ] **Step 3: Add models, enums and migration;** `make check` must pass migration round-trip and drift.
- [ ] **Step 4: Run** the test; expect PASS.
- [ ] **Step 5: Commit** `feat(brixx): sync run and table state tables`.

### Task 6: Upsert engine

**Files:**
- Create: `app/directory/brixx/upsert.py`
- Test: `tests/integration/test_brixx_upsert.py` (creates the mirror table with `build_table(...).metadata.create_all` in the `brixx` schema inside the test DB)

**Interfaces:**
- Consumes: `build_table`, `normalise_row`, `BrixxTable`.
- Produces: `upsert_page(session: Session, table: sa.Table, info: BrixxTable, company_id: UUID, rows: list[dict[str, object]], synced_at: datetime) -> UpsertResult` with `UpsertResult(written: int, skipped_older: int, extra_columns: frozenset[str])`. Row keys lower-cased; keys without a mirror column go into `_extra`; `_deleted_at` reset to NULL on write; a row is skipped when the stored `versienr` is greater than the incoming one, or equal `versienr` with stored `upddatetime` newer (tables lacking those columns always overwrite).

- [ ] **Step 1: Write failing tests:** `test_insert_then_update`; `test_replay_same_page_is_noop_count` (second write changes nothing but counts equal rows); `test_older_version_never_wins` (write versienr 2 then 1: row stays 2, `skipped_older == 1`); `test_unknown_column_goes_to_extra` (result lists the column); `test_null_object_stored_as_null`; `test_two_companies_isolated` (same PK, different `company_id`, two rows).
- [ ] **Step 2: Run;** expect FAIL.
- [ ] **Step 3: Implement** with `postgresql.insert(...).on_conflict_do_update(index_elements=[company_id, pk], set_=..., where=<newer-or-equal-version predicate>)`; one statement per page (executemany), short transaction, caller commits.
- [ ] **Step 4: Run;** expect PASS. `make check`.
- [ ] **Step 5: Commit** `feat(brixx): idempotent page upsert`.

### Task 7: Table sync loop and drift detection

**Files:**
- Create: `app/directory/brixx/state.py`, `app/directory/brixx/sync.py`
- Test: `tests/integration/test_brixx_sync.py`

**Interfaces:**
- Consumes: `BrixxApi`, `upsert_page`, `build_filter`, `has_incremental_column`, state models.
- Produces (`state.py`): `get_or_create_table_state(session, company_id, table) -> BrixxSyncTableState`; `record_page(session, state, page: int, written: int)`; `mark_success(session, state, upd: datetime | None, started_at: datetime)`; `mark_error(session, state, error: str)`.
- Produces (`sync.py`): `OVERLAP = timedelta(minutes=5)`; `sync_table_page(session: Session, api: BrixxApi, company_id: UUID, info: BrixxTable, table: sa.Table, *, page: int, since: datetime | None, now: datetime) -> PageResult` where `PageResult(has_next: bool, written: int, max_upd: datetime | None, extra_columns: frozenset[str])` (one page, one transaction, updates `last_page`); `incremental_filter(info: BrixxTable, since: datetime | None) -> str | None` (None when full fetch needed); `detect_drift(info: BrixxTable, table: sa.Table) -> bool` (BRIXX fields not present as mirror columns).

- [ ] **Step 1: Write failing tests** against `FakeBrixxApi` + testcontainers DB: `test_first_run_is_full_load` (no filter, all rows, `has_next` ends); `test_incremental_sends_filter_with_overlap` (filter is `[upddatetime >= since-5min]`, read from `fetch_log`); `test_no_upddatetime_table_full_fetch` (Review Focus 2: no filter sent, unchanged rows count as written 0 via hash compare is not required in Phase A: rewritten rows are fine, assert no crash and all rows present); `test_resume_after_crash` (Review Focus 4: fake fails page 3, call again from `last_page + 1`, no refetch of pages 1–2, success only after last page); `test_drift_flagged_not_failed` (Review Focus 3); `test_auth_error_recorded` (Review Focus 5: `mark_error` text contains class name only, not the token).
- [ ] **Step 2: Run;** expect FAIL.
- [ ] **Step 3: Implement.** `since` comes from `last_success_upd`; the overlap is subtracted inside `incremental_filter`. `max_upd` is the largest `upddatetime` seen across pages and is committed by `mark_success` only after `has_next` is False.
- [ ] **Step 4: Run;** expect PASS. `make check`.
- [ ] **Step 5: Commit** `feat(brixx): resumable table sync with drift detection`.

### Task 8: DBOS workflows and queue

**Files:**
- Create: `app/workflows/brixx_sync.py`
- Modify: `app/core/workflow_names.py` (`BRIXX_QUEUE = "brixx"`, `BRIXX_SYNC_ALL = "brixx.sync_all"`, `BRIXX_SYNC_TABLE = "brixx.sync_table"`, `brixx_run_workflow_id(run_id, table) -> str` returning `brixx:{run_id}:{table}`), `app/workflows/queues.py` (register `BRIXX_QUEUE`, `worker_concurrency=2`, accessor `brixx_queue()`), `app/workflows/runtime.py` (import the module so DBOS registers it)
- Test: `tests/integration/test_brixx_workflows.py`

**Interfaces:**
- Consumes: Task 7 functions, `deps.brixx_api()`, queue accessors.
- Produces: `@DBOS.scheduled("*/15 * * * *") @DBOS.workflow(name="brixx.sync_all")` `sync_all(scheduled_time: datetime, context: Any) -> None` (reads the interval from settings at registration; lists tables via a step, creates the `BrixxSyncRun` row in a step, enqueues one `brixx.sync_table` child per table with id `brixx_run_workflow_id(run_id, table)`); `@DBOS.workflow(name="brixx.sync_table")` `sync_table(run_id: str, table: str) -> None` looping page steps (`@DBOS.step(name="brixx.sync_page")` with retry, non-retryable on `BrixxAuthError`) until `has_next` is False, then `mark_success`. Workflow bodies do no I/O or clock reads.

- [ ] **Step 1: Write failing tests** with `dbos_runtime` and the fake: `test_sync_all_creates_run_and_children` (one run row, N table states succeed); `test_repeat_enqueue_same_run_does_not_duplicate` (same workflow id, rows unchanged); `test_one_table_auth_error_does_not_fail_others` (scripted `BrixxAuthError` on one table: that state has `last_error`, others succeed, run marked `failed`).
- [ ] **Step 2: Run;** expect FAIL.
- [ ] **Step 3: Implement** following `app/workflows/ingest.py` (`gmail_backfill`) for the scheduled-workflow and `SetWorkflowID` enqueue pattern. Only the metadata `list_tables` is fetched per run (describe results cached per run in the step return values).
- [ ] **Step 4: Run;** expect PASS. `make check`; then `make workflows` after `make up` shows `brixx.sync_all` (G5 `make smoke` stays green with `brixx_provider=fake`).
- [ ] **Step 5: Commit** `feat(brixx): sync workflows and queue`.

### Task 9: Status API

**Files:**
- Create: `app/api/v1/brixx.py`; Modify: router registration in `app/api/v1/__init__.py` (or wherever existing routers register), `docs/dashboard-api.md`
- Test: `tests/integration/test_brixx_status_api.py`

**Interfaces:**
- Produces: `GET /api/v1/brixx/status` (dashboard session auth like other routes) returning `BrixxStatus(last_run: RunOut | None, tables: list[TableStatusOut], total_rows: int, stale: bool)` with `TableStatusOut(name, row_count, last_success_at, lag_seconds, drifted, last_error)`; `stale` is true when no successful run in 3 × `brixx_sync_interval_minutes`. Contracts live in `app/contracts/` (invariant 8). Reads state tables only, scoped by `company_id`; never calls BRIXX.

- [ ] **Step 1: Write failing tests:** authenticated request returns seeded table states; other company's states never appear; unauthenticated gets 401; `stale` true when the last success is older than the window.
- [ ] **Step 2: Run;** expect FAIL.
- [ ] **Step 3: Implement** the router and contracts; API must not import `app.workflows` (import-linter).
- [ ] **Step 4: Run;** expect PASS. `make check`.
- [ ] **Step 5: Commit** `feat(brixx): sync status endpoint`.

### Task 10: ADR, docs, progress

**Files:**
- Create: `docs/adr/<next number>-brixx-data-api-mirror.md`
- Modify: `docs/tech-stack.md` (BRIXX row: httpx adapter + generated mirror, replacing polars CSV import), `docs/hld.md` §3 (`directory/` BRIXX line), `docs/PROGRESS.md` (BRIXX mirror Phase A done; Phase B blocked on IP whitelist `115.246.217.246` and production egress IP), `docs/go-live-channels.md` (BRIXX credentials, whitelist, token rotation)

- [ ] **Step 1: Write the ADR** (context: export import deferred; decision: Data API mirror with typed generated tables; consequences: IP whitelist dependency, personal data in mirror, GDPR purge tracked in Phase D).
- [ ] **Step 2: Update the other docs** as listed; `make quick` still green.
- [ ] **Step 3: Commit** `docs(brixx): ADR, tech stack and progress`.

---

## Self-Review

- **Spec coverage:** client adapter (T2–3), typed mirror and system columns (T4), state tables (T5), idempotent upsert and `_extra` (T6), incremental/full/resume/drift (T7), DBOS cron + queue (T8), status API (T9), ADR/docs (T10). Deferred by design to later plans: codegen and first load (Phase B), documents (C), reconcile deletes, mapper, GDPR purge, Super Agent tool (D). The reconcile workflow is Phase B because it needs real primary-key-only fetch behaviour.
- **Type consistency:** `BrixxApi`, `BrixxTable`, `BrixxPage`, `upsert_page`, `sync_table_page`, `brixx_run_workflow_id` are defined once and reused unchanged.
- **Review Focus** lines map to tests: 1 → T6 `test_older_version_never_wins`; 2 → T7 `test_no_upddatetime_table_full_fetch`; 3 → T6/T7 drift tests; 4 → T7 `test_resume_after_crash`; 5 → T3 `test_401_raises_auth_error_without_retry`, T7 `test_auth_error_recorded`, T8 `test_one_table_auth_error_does_not_fail_others`.
