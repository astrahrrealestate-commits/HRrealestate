# EstateOS tech stack

Principle: **assemble proven tools; write code only for domain logic and the glue between tools.**
Every external tool sits behind an adapter interface so it can be swapped. Rationale for big choices: [adr/](adr/).

## Changes vs original build plan

| Was | Now | Why | ADR |
|---|---|---|---|
| Celery + Redis + Beat + custom timer sweep + custom idempotency | **DBOS Transact** (durable workflows/queues/cron in our Postgres) | Removes Redis, Celery, Beat and most retry and idempotency code. Workflow state lives in Postgres (Postgres-first by construction). | [0001](adr/0001-dbos-durable-workflows.md) |
| Custom `llm/` client over OpenAI SDK | **Pydantic AI** (typed agents, structured output, provider-agnostic) + **pydantic-evals** | Contracts *are* the output types; provider swap is a config string; test models built in. | [0002](adr/0002-pydantic-ai.md) |
| Hand-rolled WhatsApp client | **pywa** (typed Cloud API framework) via **360dialog** partner for Coexistence | Webhook parsing, signature check, buttons/lists/templates come for free. Coexistence requires a partner. | [0003](adr/0003-whatsapp-pywa-360dialog.md) |
| Custom AST send-isolation test | **import-linter** contracts | Declarative architecture rules, run in CI and pre-commit. | [0004](adr/0004-import-linter-boundaries.md) |
| Custom `.githooks` | **pre-commit** framework + **gitleaks** | Standard hook manager; secret scanning included. | — |

## Runtime

| Concern | Tool | We build |
|---|---|---|
| Language / packaging | Python 3.12, **uv** | — |
| HTTP API + webhooks | **FastAPI** + Uvicorn | route wiring only |
| Durable workflows, queues, cron, human-wait | **DBOS Transact** (`dbos`) | workflow definitions |
| Database | **PostgreSQL 16**, **SQLAlchemy 2** (typed), **Alembic**, psycopg 3 | models, repositories |
| Config | **pydantic-settings** | settings classes |
| Contracts / validation | **Pydantic v2** | the six contracts |
| LLM agents | **Pydantic AI** → OpenAI (EU data residency) | prompts, agent wiring |
| LLM observability + prompt eval | **Langfuse** (EU cloud, OTel) | — |
| Golden-set evals | **pydantic-evals** | datasets, custom evaluators |
| WhatsApp | **pywa** (Cloud API) + **360dialog** (Coexistence partner) | outbound adapter, owner message builders |
| Gmail | **google-api-python-client**, **google-auth** (OAuth + Pub/Sub OIDC verify) | history sync, draft adapter |
| Email body cleanup | **mail-parser-reply** (quote/signature strip, German aware), **inscriptis** (HTML→text) | — |
| PDFs | **Docling** | — |
| Photos / scans | model vision via Pydantic AI | — |
| Phone / email normalising | **phonenumbers**, **email-validator** | — |
| Fuzzy matching (linking, outcomes) | **rapidfuzz** | thresholds |
| BRIXX export import | **polars** (CSV/XLSX) + Pydantic row models | column mapping |
| Object storage | **boto3** → S3-compatible EU bucket | — |
| Logging | **structlog** (JSON) | — |
| Errors | **Sentry** SDK (FastAPI + DBOS) | — |
| Traces | **OpenTelemetry** (DBOS + Pydantic AI emit spans) → Langfuse | — |

**Built by us (no tool fits):** case engine (identity → person → unit → lease, linking), rules engine (small pure-function
policy set; OPA is overkill), proposal assembly, owner command handler, outcome labelling, BRIXX column mapping.

## Quality and testing

| Concern | Tool |
|---|---|
| Lint + format + security lint | **ruff** (incl. `S` bandit rules, `ASYNC`, `DTZ` timezone rules) |
| Types | **mypy** strict + pydantic plugin |
| Architecture boundaries | **import-linter** |
| Tests | **pytest**, **pytest-xdist** (parallel), **pytest-socket** (no network), **pytest-cov** |
| DB in tests | **testcontainers** (Postgres 16 per session; no manual stack needed) |
| Property tests | **hypothesis** |
| Test data | **polyfactory** (Pydantic + SQLAlchemy factories) |
| HTTP mocking | **respx** (httpx) |
| LLM in tests | Pydantic AI **TestModel / FunctionModel** (no network, deterministic) |
| Snapshots | **syrupy** (prompt renders, owner messages) |
| Secrets scan | **gitleaks** |
| Dependency audit | **pip-audit** (CI), **Dependabot** |
| Hook manager | **pre-commit** |
| CI | **GitHub Actions** |

## Infrastructure

| Concern | Choice |
|---|---|
| Region | EU only (Germany preferred: Harjot + BRIXX are German). Confirm the provider at M0. |
| Default provider | AWS `eu-central-1`: one EC2 VM, RDS Postgres 16, S3. Code is provider-neutral. |
| Containers | Docker. Compose for dev; compose on the VM for prod (Phase 1). |
| TLS / reverse proxy | **Caddy** (auto Let's Encrypt; webhooks need HTTPS) |
| Deploy | GitHub Actions → build image → GHCR → SSH `docker compose pull && up -d` |
| Secrets | GitHub Actions secrets → `.env` on VM (0600). No secrets in images. |
| Backups | RDS automated backups + PITR; S3 versioning |
| Workflow ops | `dbos` CLI / DBOSClient (list, fork, cancel workflows) |
| Dev tunnel for webhooks | **cloudflared** or ngrok |

## Processes (one image, three roles)

| Role | Command | Does |
|---|---|---|
| `api` | `uvicorn app.main:app` | webhooks, health. Enqueues via `DBOSClient` (never executes workflows). |
| `worker` | `python -m app.worker` | DBOS executor: runs queued workflows + cron schedules |
| `migrate` | `alembic upgrade head` | one-shot before api/worker |

No Redis, no Celery, no Beat.
