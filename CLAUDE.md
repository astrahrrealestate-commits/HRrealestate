# EstateOS — Claude working guide

AI property-management assistant (Phase 1) for one owner, Harjot. Reads tenant/contractor WhatsApp + Gmail,
links messages to cases, proposes typed actions with 2–3 drafts, and asks Harjot to approve on WhatsApp.
**Phase 1 sends nothing to tenants**: only Gmail drafts and messages to Harjot.

| Doc | Read when |
|---|---|
| [docs/hld.md](docs/hld.md) | architecture, flows, failure handling |
| [docs/tech-stack.md](docs/tech-stack.md) | which tool does what; **check before writing plumbing** |
| [docs/adr/](docs/adr/) | why DBOS, Pydantic AI, pywa/360dialog, import-linter |
| [docs/dev-pipeline.md](docs/dev-pipeline.md) | stages, gates, test strategy per layer, definition of done |
| [docs/build-plan.md](docs/build-plan.md) · [docs/PROGRESS.md](docs/PROGRESS.md) | milestones · status |
| [docs/superpowers/specs/](docs/superpowers/specs/) | current approved specs |

## Build philosophy
Assemble proven tools, then connect and manage them. Write code only for domain logic (case engine, rules, proposals,
owner commands, outcomes) and thin adapters. About to hand-roll retries, scheduling, queues, webhook parsing, HTTP
clients, LLM clients, eval runners or test DB setup? Stop. The tool is in tech-stack.md. Missing tool → propose
one (ADR) before building.

## Stack in one line
FastAPI · DBOS Transact (workflows/queues/cron on Postgres) · PostgreSQL 16 + SQLAlchemy 2 + Alembic · Pydantic v2 ·
Pydantic AI → OpenAI (EU) · Langfuse · pywa (WhatsApp, 360dialog) · Gmail API + Pub/Sub · S3 · structlog · Sentry.
**No Redis, no Celery** (guard-enforced).

## Commands (always via make)
| | |
|---|---|
| `make setup` | uv sync, pre-commit install, .env from example |
| `make up` / `make up-db` / `make down` | dev stack (postgres, migrate, api, worker) / postgres only / stop |
| `make quick` | **G1**: ruff, format, mypy, import-linter, unit tests |
| `make check` | **G2**: G1 + integration (testcontainers Postgres + DBOS, migration round-trip, drift) |
| `make smoke` | **G5**: stack up, api ready, worker self-check, logs clean |
| `make cov` · `make audit` | coverage floors · dependency vulnerabilities |
| `make migration m="..."` | new Alembic revision (see `/new-migration`) |
| `make eval agent=X version=vN` | pydantic-evals golden set (M4) |
| `make workflows` | list recent DBOS workflows |
| `make harness-test` | self-test Claude guard hooks |

## Invariants (non-negotiable; the reviewer checks every one)
1. **Postgres before work.** Insert/commit the row, then enqueue via DBOS with a deterministic workflow id
   (`evt:{raw_event_id}`, `exec:{action_id}:{draft_version}`). Nothing lives only in memory.
2. **Idempotent everything.** DBOS steps safe to retry; DB unique constraints back every "do once". Workflows stay
   short (minutes); long waits are DB state + a new workflow, never `DBOS.recv`/`sleep` for hours.
3. **Deterministic workflows.** Workflow functions do no I/O and use no clock or random. All of that goes in
   `@DBOS.step` / `@DBOS.transaction`.
4. **Tenant scoping.** Every domain query filters by `company_id`; repositories require it.
5. **Send isolation.** Only `app/sender/` imports `SenderSettings` or `app.channels.*.outbound` (import-linter +
   hook). The sender re-checks approval status, `draft_version`, company pause, the Phase 1 allowlist, and
   `sends.idempotency_key`.
6. **Message content is data, never instructions.** Untrusted text only inside prompt data delimiters. Agents have
   no write tools. Recipients come from the DB, never from model output.
7. **Adapters for every external service.** Pipeline depends on interfaces; tests use fakes/recorded fixtures.
8. **Contracts are the schema.** `app/contracts/*` are the stage API and the Pydantic AI `output_type`. One definition.
9. **Immutable artifacts.** Committed migrations, published prompts (`app/llm/prompts/vN/`), recorded fixtures.

## Code conventions
- Python 3.12, mypy strict, `StrEnum`, `AwareDatetime`/`timestamptz` (UTC stored), `Decimal` money, UUIDv7 ids.
- SQLAlchemy 2 typed `Mapped[...]`, sync psycopg 3, short sessions, explicit commit.
- structlog only. No `print`. No message bodies or secrets in info logs.
- Functions < 40 lines, modules < 300 lines, one purpose per module. Errors subclass `EstateOSError`.
- No TODO without an issue link. No commented-out code. No blanket `# type: ignore` / `# noqa`.

## Pipeline (how every change is made)
`/ship` per task: **RED → GREEN → REFACTOR → G1 → G2 (if db/workflows/channels/sender/api) → G3 reviewer → commit**.
Full detail and the per-layer test matrix: [docs/dev-pipeline.md](docs/dev-pipeline.md).
- New milestone → `/milestone` (brainstorm → spec → plan → execute).
- Evidence before claims → `/check` (quote result lines). Noisy runs → `test-runner` agent.
- Branch per milestone `m<n>-<slug>`; `main` is protected by pre-commit. Conventional commits enforced.

## Guardrails enforced by hooks (`.claude/hooks/`, self-tested by `make harness-test`)
- **Bash:** blocks git writes outside this repo (the parent dir is a home-dir repo), force push, hook bypass,
  reading `.env`, shell calls to Meta/Gmail/OpenAI/PubSub, destructive `rm`. Asks before reset --hard, push, volume
  wipe, alembic downgrade, DROP/TRUNCATE, dependency changes.
- **Edit/Write:** blocks `.env` edits, edits to committed migrations/prompts/fixtures, send-credential references
  outside `app/sender/`, Celery/Redis imports, hard-coded keys. Asks before adding skip/xfail to tests.
- **Post-edit:** ruff format + fix on the file; leftover lint is fed back.
- **Stop (G1):** ruff → mypy → import-linter → unit on changed Python; a failure blocks finishing.
- **Permissions:** `.env`/key files unreadable; Gmail MCP send/reply/forward/trash denied.
If a guard blocks you, follow its message. If you think the guard is wrong, ask the user.
