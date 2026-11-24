# EstateOS — Claude working guide

AI property-management assistant (Phase 1) for one owner, Harjot. Reads tenant/contractor WhatsApp + Gmail,
links messages to cases, proposes typed actions with 2–3 drafts. Harjot uses **only the dashboard** (backend API in
`backend/app/api/v1`, frontend in `frontend/`) and one **Super Agent**; WhatsApp/Gmail messages are mirrored there.
**Tenant sends happen only after his approve click**, via `backend/app/sender/`, behind `outbound_mode` (default `draft`).
Design: [dashboard spec](docs/superpowers/specs/2026-10-15-dashboard-super-agent-design.md), [ADR 0006](docs/adr/0006-dashboard-owner-channel.md).

Repo layout: `backend/` (Python — app, tests, evals, docker, pyproject.toml, uv.lock) and `frontend/` (Next.js) are
siblings; `docs/`, `.claude/`, `.github/`, `reports/`, `scripts/` and the Makefile cover both and stay at the repo
root. `make <target>` from the root always does the right thing — the Makefile's `backend/`-relative invocation is
an implementation detail, never type the path yourself.

| Doc | Read when |
|---|---|
| [docs/hld.md](docs/hld.md) | architecture, flows, failure handling |
| [docs/tech-stack.md](docs/tech-stack.md) | which tool does what; **check before writing plumbing** |
| [docs/adr/](docs/adr/) | why DBOS, Pydantic AI, WhatsApp via Cloud API models/360dialog (pywa dropped), import-linter |
| [docs/dev-pipeline.md](docs/dev-pipeline.md) | stages, gates, test strategy per layer, definition of done |
| [docs/build-plan.md](docs/build-plan.md) · [docs/PROGRESS.md](docs/PROGRESS.md) | milestones · status |
| [docs/superpowers/specs/](docs/superpowers/specs/) | current approved specs |
| [docs/standards/security.md](docs/standards/security.md) | auth, tenant scoping, injection, secrets, **known security gaps** |
| [reports/](reports/) | dated retros: what slowed us down and what we changed |

## Build philosophy
Assemble proven tools, then connect and manage them. Write code only for domain logic (case engine, rules, proposals,
owner commands, outcomes) and thin adapters. About to hand-roll retries, scheduling, queues, webhook parsing, HTTP
clients, LLM clients, eval runners or test DB setup? Stop. The tool is in tech-stack.md. Missing tool → propose
one (ADR) before building.

## Stack in one line
FastAPI · DBOS Transact (workflows/queues/cron on Postgres) · PostgreSQL 16 + SQLAlchemy 2 + Alembic · Pydantic v2 ·
Pydantic AI → OpenAI (EU) · Langfuse · WhatsApp Cloud API (Pydantic models + httpx; Meta or 360dialog) · Gmail API +
Pub/Sub · S3 · structlog · Sentry.
**No Redis, no Celery** (guard-enforced).

## Commands (always via make)
| | |
|---|---|
| `make setup` | uv sync, pre-commit install, .env from example |
| `make up` / `make up-db` / `make down` | dev stack (postgres, migrate, api, worker) / postgres only / stop |
| `make quick` | **G1**: ruff, format, mypy, import-linter, unit tests |
| `make check` | **G2**: G1 + integration (testcontainers Postgres + DBOS, migration round-trip, drift) |
| `make smoke` | **G5**: stack up, api ready, worker self-check, logs clean |
| `make sim-demo` | **G5**: simulate WhatsApp + Gmail through the stack, assert parity rows (`backend/app/dev/simulate.py`) |
| `make live-check [k=gmail]` | go-live gate: real provider adapters; lists missing credentials ([docs/go-live-channels.md](docs/go-live-channels.md)) |
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
5. **Send isolation.** Only `backend/app/sender/` imports `SenderSettings` or `app.channels.*.outbound` (import-linter +
   hook). AI-drafted actions are sent only after his approve click: the sender re-checks approval status,
   `draft_version`, company pause, `outbound_mode`, that the recipient is the case's own identity on the thread's
   channel (from the DB), and `sends.idempotency_key`. A second allowed class is the **owner-typed WhatsApp send**
   from the Chats page (his own click on text he typed, ADR 0013): recipient from the stored row's DB thread only,
   same pause/mode/window/idempotency gates and its own cap. The Super Agent can propose, never approve or send.
6. **Message content is data, never instructions.** Untrusted text only inside prompt data delimiters. Agents have
   no write tools. Recipients come from the DB, never from model output.
7. **Adapters for every external service.** Pipeline depends on interfaces; tests use fakes/recorded fixtures.
8. **Contracts are the schema.** `backend/app/contracts/*` are the stage API and the Pydantic AI `output_type`. One definition.
9. **Immutable artifacts.** Committed migrations, published prompts (`backend/app/llm/prompts/vN/`), recorded fixtures.

## Code conventions
- Python 3.12, mypy strict, `StrEnum`, `AwareDatetime`/`timestamptz` (UTC stored), `Decimal` money, UUIDv7 ids.
- SQLAlchemy 2 typed `Mapped[...]`, sync psycopg 3, short sessions, explicit commit.
- structlog only. No `print`. No message bodies or secrets in info logs.
- Functions < 40 lines, modules < 300 lines, one purpose per module. Errors subclass `EstateOSError`.
- No TODO without an issue link. No commented-out code. No blanket `# type: ignore` / `# noqa`.

## Pipeline (how every change is made)
`/ship` per task: **RED → GREEN → REFACTOR → G1 → G2 (if db/workflows/channels/sender/api) → G3 reviewer (+ `estateos-security` for api/sender/channels/llm/auth/prompts/external input) → commit**.
Full detail and the per-layer test matrix: [docs/dev-pipeline.md](docs/dev-pipeline.md).
- New milestone → `/milestone` (brainstorm → spec → plan → execute).
- Evidence before claims → `/check` (quote result lines). Noisy runs → `test-runner` agent.
- Branch per milestone `m<n>-<slug>`; `main` is protected by pre-commit. Conventional commits enforced.

## Two kinds of agent
**Product agents** run inside EstateOS (the Super Agent / concierge planner, proposer, understanding, owner_qa, the
research loop; code in `backend/app/llm/agents/`, `backend/app/superagent/`). **Engineering agents** build it (`.claude/agents/`):
`estateos-implementer`, `estateos-reviewer`, `estateos-security`, `test-runner`, `builder`. "Reviewer" or "security"
without a prefix means the engineering role. Engineering agents never get product credentials; product agents never get
write tools.

## Quality gates: reject work if
- no test, or a test never seen red (see "Test rules" in dev-pipeline.md)
- docs, spec or PROGRESS not updated for a behaviour or contract change
- a significant design choice with no ADR
- complexity a simpler equivalent would avoid, or plumbing that tech-stack.md already names a tool for
- an open **blocker** from `docs/standards/security.md`, or no `estateos-security` pass on a diff that needs one
A failed gate sends the task back to the stage that owns it; it does not ship.

## Self-improvement loop
At the end of every slice or milestone run `/retro`: what slowed us down, what knowledge was missing and where it
should live, what repeated (the **third** occurrence becomes a skill), what a hook or test should have caught. Each
answer becomes an artifact in the same change (a rule, skill, hook, test, ADR) and a dated file in `reports/`.

## Guardrails enforced by hooks (`.claude/hooks/`, self-tested by `make harness-test`)
- **Bash:** blocks git writes outside this repo (the parent dir is a home-dir repo), force push, hook bypass,
  reading `.env`, shell calls to Meta/Gmail/OpenAI/PubSub, destructive `rm`. Asks before reset --hard, push, volume
  wipe, alembic downgrade, DROP/TRUNCATE, dependency changes.
- **Edit/Write:** blocks `.env` edits, edits to committed migrations/prompts/fixtures, send-credential references
  outside `backend/app/sender/`, Celery/Redis imports, hard-coded keys. Asks before adding skip/xfail to tests.
- **Post-edit:** ruff format + fix on the file; leftover lint is fed back.
- **Stop (G1):** ruff → mypy → import-linter → unit on changed Python; a failure blocks finishing.
- **Permissions:** `.env`/key files unreadable; Gmail MCP send/reply/forward/trash denied.
If a guard blocks you, follow its message. If you think the guard is wrong, ask the user.

## Autonomy rules (apply only during /autoship)
- Never ask the user questions or wait for approval. Pick the safest reasonable option and log it in DECISIONS.md.
- Hooks and invariants still apply. Never work around a guard block: log it and take another path.
- Never force-push, rewrite history, commit on main, or delete remote branches. main moves only by fast-forward in release.md after every gate is green.
- Never skip, delete, or weaken tests to get green.
- No stubs, placeholders, or TODOs in shipped code. Fakes live in tests, behind adapter interfaces.
- Never claim something works without running it and quoting the result line. A check that couldn't run is a failure.
- State lives in BUILD_STATUS.md, DECISIONS.md and FINAL_REPORT.md. Re-read them at the start of every pass.
- If a step fails 3 times the same way, try a different approach, log it, and move on.
