# EstateOS M1 foundation: design

Date: 2026-10-05 · Status: approved in chat (§1–§3); §1 revised for tool-first stack (see `docs/tech-stack.md`, ADR 0001–0004) · Scope: M1 skeleton + six contracts + first Alembic migration.
Parent docs: [build-plan.md](../../build-plan.md), [architecture.md](../../architecture.md).

## Goal

A repo where `docker compose up` runs Postgres, migrate, API and DBOS worker; the first migration creates every
Phase 1 table; the six contracts exist as Pydantic models; CI runs ruff, mypy and pytest. No pipeline logic.
Everything after M1 builds on these shapes, so they are locked here.

## Decisions

| Topic | Decision |
|---|---|
| Scope | M1 + contracts + migration only. Agents (M4–M6) come later on top of the locked shapes. |
| Tenancy | `company_id` on every domain row. Isolation enforced in the repository layer; Postgres RLS deferred until a second customer. |
| Package manager | `uv`, Python 3.12, `pyproject.toml`; ruff + mypy `strict`. |
| IDs | UUIDv7 (`core/ids.new_id()`), time-sortable. |
| Time | `timestamptz`, UTC in storage. Company local timezone on `companies.timezone` (default `Europe/Berlin`). |
| Money | `numeric(12,2)` + ISO currency code. Contract type `Money{amount: Decimal, currency: str}`. |
| DB driver | SQLAlchemy 2 typed declarative, psycopg 3 **sync**. FastAPI uses sync sessions via threadpool dependency. |
| Workflows | DBOS Transact (no Redis/Celery/Beat). API enqueues via `DBOSClient`; `worker` process executes. |
| Boundaries | import-linter contracts in `pyproject.toml` (ADR 0004). |
| Repo | Own git repo at `EstateOS/` (parent home-dir repo must never receive commits). |

## §1 Repo and runtime

- **Layout** as in build-plan. Unused packages in M1 are empty `__init__.py` — no fake stubs.
- **`core/config.py`**: pydantic-settings `Settings` (DB URL, `ENV`, S3, Langfuse, Sentry DSN, OpenAI). No secrets in
  code. `SenderSettings` (WhatsApp token, Gmail send scopes) lives in `app/sender/settings.py` and is importable only
  from `app/sender/`.
- **`core/logging.py`**: structlog JSON; contextvars bind `request_id` / `raw_event_id` / `company_id`.
- **`core/ids.py`**: `new_id() -> UUID` (v7).
- **`core/errors.py`**: base `EstateOSError`, `IllegalTransition`, `NotFound`, `TenantMismatch`.
- **DBOS** (`app/workflows/dbos_app.py`): DBOS config from settings (same DATABASE_URL, system schema `dbos`).
  `app/worker.py` launches DBOS as executor; `--selfcheck` flag runs a trivial workflow and exits 0.
  One cron `@DBOS.scheduled("* * * * *")` → `timer_sweep` (no-op in M1). Queue `pipeline` (concurrency from settings).
- **`core/telemetry.py`**: Sentry init + OTel exporter to Langfuse (no-op when keys absent).
- **API**: `/health/live` (process up), `/health/ready` (DB `SELECT 1` + DBOS system tables reachable).
- **Compose** (`docker/compose.yml`): `postgres:16` (host port 5433), `migrate` (one-shot `alembic upgrade head`),
  `api`, `worker`; api/worker depend on `migrate` completing successfully. One image for all roles.
- **CI** (`.github/workflows/ci.yml`): `uv sync --frozen` → `make quick` → `make test-int` (testcontainers needs
  Docker, available on ubuntu runners) → `make audit` → docker build. Never SQLite.
- **Tooling config in `pyproject.toml`**: ruff (rules E,F,I,B,UP,S,DTZ,T20,PGH,SIM,RUF,ASYNC), mypy strict + pydantic
  plugin, pytest (`--disable-socket --allow-hosts=127.0.0.1,localhost,::1`, markers), coverage floors, import-linter
  contracts.
- **Test infra** (`tests/conftest.py`): session-scoped testcontainers Postgres 16, alembic upgrade once, per-test
  transaction rollback; DBOS test fixture (launch against the container, reset between tests); `recorded()` fixture
  loader; polyfactory factories.
- **Network isolation in tests**: `pytest-socket` with `--disable-socket --allow-hosts=127.0.0.1,localhost,::1`.
- **Architecture contracts** (import-linter, ADR 0004): layers, send isolation, pure rules engine. Run in `make quick`.

## §2 Contracts (`app/contracts/`)

All Pydantic v2, `model_config = ConfigDict(frozen=True, extra="forbid")`. Enums are `StrEnum`, so DB and JSON share
string values.

### 1. `Message` (`contracts/message.py`)
```
channel: Channel                  # whatsapp | gmail
provider_msg_id: str              # WA wamid / Gmail message id
thread_ref: str | None            # WA: counterpart phone; Gmail: threadId
sender_identity: str              # E.164 phone or lowercased email (validator normalises)
direction: Direction              # inbound | outbound
sent_at: AwareDatetime
text: str                         # plain text; HTML stripped, quoted reply trimmed
attachments: list[Attachment]     # {s3_key, mime_type, filename, size_bytes, sha256}
raw_event_id: UUID
company_id: UUID
```

### 2. `Understanding` (`contracts/understanding.py`)
```
category: Category                # maintenance | payment | lease | complaint | contractor_update | admin | spam | other
intent: str                       # ≤200 chars
urgency: Urgency                  # emergency | high | normal | low
entities: Entities{people: list[str], unit_refs: list[str], dates: list[date | str], amounts: list[Money]}
suspicious: Suspicious{flag: bool, reason: str | None}   # validator: reason required iff flag
confidence: float                 # 0..1
prompt_version: str               # e.g. "understanding/v1"
```
The same model is the OpenAI structured-output schema; there is no second definition.

### 3. `Action` (`contracts/action.py`)
```
type: ActionType                  # reply_draft | notify_owner | create_reminder | update_case_state | request_contractor | escalate
case_id: UUID
payload: ActionPayload            # discriminated union on `kind` == type
rationale: str
context_ref: list[UUID]           # message ids
draft_version: int                # ≥1, bumped on every edit
```
Payloads: `ReplyDraftPayload{kind, channel, to, subject: str | None, body_variants: list[str] (2..3)}`,
`NotifyOwnerPayload{kind, text}`, `CreateReminderPayload{kind, due_at, note}`,
`UpdateCaseStatePayload{kind, new_state}`, `RequestContractorPayload{kind, contractor_person_id, body_variants}`,
`EscalatePayload{kind, reason}`. Validator: `payload.kind == type`.

### 4. `CaseState` (`contracts/case_state.py`)
```
open → waiting_on_owner | waiting_on_third_party | resolved | closed
waiting_* → open | resolved | closed
resolved → open | closed
closed → (terminal)
```
`assert_transition(old, new)` raises `IllegalTransition`. Self-transitions are illegal.

### 5. `ButtonId` (`contracts/button_id.py`)
`apr:<approval_id>:<choice>`, `choice ∈ {ok, edit, rej, d1, d2, d3}`. `ButtonId.parse(s)` / `.render()`.
Render length ≤ 256 (WhatsApp reply-button id limit). Titles (≤20 chars) are checked in `owner/`, not here.

### 6. `PromptRef` (`contracts/prompt_ref.py`)
`{name, version}`. Loader `app/llm/prompts.load(ref) -> RenderedPrompt{text, sha256}` reads
`app/llm/prompts/<version>/<name>.md`. Every `model_calls` row stores name, version and sha256 of the template.
Published prompt files are immutable; a change means a new version directory.

### Contract tests
Round-trip JSON for every model; full 5×5 state-transition matrix; ButtonId parse/render + hypothesis fuzz of garbage
input; `Understanding` suspicious validator; `Action` payload/type mismatch rejected.

## §3 Tables (single first migration)

Every table: `id uuid pk` (v7), `created_at timestamptz default now()`. Domain tables: `company_id uuid not null fk`.
Directory tables: `valid_from date`, `valid_to date null`.

| Table | Key columns | Constraints / indexes |
|---|---|---|
| `companies` | name, timezone, paused bool | — (no company_id) |
| `channel_accounts` | channel, address, is_owner_channel | unique(channel, address) |
| `owner_accounts` | display_name, whatsapp_e164, email | unique(company_id, whatsapp_e164) |
| `gmail_sync_state` | channel_account_id, history_id, watch_expires_at | unique(channel_account_id) |
| `directory_imports` | source_filename, s3_key, status, counts jsonb, error | — |
| `people` | kind (tenant/contractor/owner/other), display_name, trade, brixx_ref, import_id | idx(company_id, brixx_ref) |
| `channel_identities` | person_id, channel, identity, valid_from, valid_to | partial unique(company_id, channel, identity) where valid_to is null |
| `units` | label, address, brixx_ref, import_id | idx(company_id, brixx_ref) |
| `leases` | unit_id, valid_from, valid_to, brixx_ref, import_id | idx(unit_id) |
| `lease_parties` | lease_id, person_id, role | unique(lease_id, person_id, role) |
| `raw_events` | provider, provider_msg_id, payload jsonb, status, attempts, last_error, received_at | **unique(provider, provider_msg_id)**; idx(status) |
| `messages` | Message fields + person_id null | **unique(channel, provider_msg_id)**; idx(company_id, thread_ref) |
| `attachments` | message_id, s3_key, mime_type, filename, size_bytes, sha256, extracted_text | idx(message_id) |
| `understandings` | message_id, model_call_id, category, urgency, body jsonb, prompt_version | unique(message_id); idx(category), idx(urgency) |
| `cases` | unit_id, lease_id, primary_person_id, state, category, urgency, summary, summary_version, opened_at, resolved_at | idx(company_id, state) |
| `case_links` | case_id, message_id, method (thread/open_case/model), confidence | unique(message_id) |
| `case_events` | case_id, kind, from_state, to_state, note, actor | append-only; idx(case_id) |
| `actions` | Action fields, status | idx(case_id), idx(status) |
| `action_revisions` | action_id, draft_version, payload jsonb, edited_by | unique(action_id, draft_version) |
| `approvals` | action_id, draft_version, status, owner_wa_message_id, choice, decided_at | idx(action_id), idx(status) |
| `sends` | action_id null, idempotency_key, channel, target, provider_ref, status, error, attempted_at | **unique(idempotency_key)** |
| `timers` | kind, due_at, payload jsonb, status, attempts, locked_until, dedupe_key | **unique(dedupe_key)**; idx(status, due_at) |
| `outcomes` | action_id, draft_version, final_text, label, similarity, source | idx(action_id) |
| `model_calls` | purpose, prompt_name, prompt_version, prompt_sha256, model, input jsonb, output jsonb, tokens_in, tokens_out, cost_usd numeric(10,6), latency_ms, langfuse_trace_id, error | idx(company_id, created_at) |

`raw_events.company_id` is resolved from `channel_accounts` before insert.

**Gmail dedupe nuance:** a Pub/Sub push carries only `historyId`. The push handler enqueues a history sync; the sync
writes one `raw_event` per Gmail message id. Dedupe is therefore uniform across channels.

**Timer sweep:** `SELECT … WHERE status='pending' AND due_at<=now() FOR UPDATE SKIP LOCKED LIMIT n` — concurrent cron
ticks never double-fire.

**Sender guard (M7, schema ready now):** before any send, `approvals.draft_version == actions.draft_version` and
`approvals.status='approved'`; `sends.idempotency_key` unique makes retries no-ops.

### Migration tests (`tests/integration/test_migrations.py`)
`roundtrip`: upgrade head → downgrade base → upgrade head on testcontainers Postgres; `drift`: `alembic check` reports
no drift between models and migration; insert-twice tests on every unique constraint listed in bold.

## Out of scope for M1

Webhook handlers, Gmail sync, BRIXX import, LLM calls, case linking, owner messaging, sending. Tables exist; logic does
not.

## Error handling

Domain errors subclass `EstateOSError`. API returns 503 from `/health/ready` on dependency failure. DBOS steps raise for retry
(`retries_allowed`, backoff); idempotency comes from workflow ids + DB constraints, not bookkeeping.
