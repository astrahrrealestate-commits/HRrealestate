# EstateOS developer entry points. Every gate Claude, pre-commit or CI runs goes through here.
# Pipeline: docs/dev-pipeline.md  ·  G1 = quick  ·  G2 = check  ·  G5 = smoke
# Layout: backend/ (Python: app, tests, evals, docker, pyproject.toml, uv.lock) and frontend/ (Next.js), siblings.
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

COMPOSE = docker compose -f backend/docker/compose.yml $$([ -f backend/.env ] && echo --env-file backend/.env)  # agent settings reach the containers; checked when the recipe runs, so a .env made by `make env` counts
# --directory backend: the tool's cwd, so its own relative paths (tests/unit, app, .) mean backend/tests/unit etc.
UV       := uv run --frozen --directory backend
# --project backend: resolves backend's environment/lockfile without moving cwd, for commands whose paths (output
# files, recipe-root-relative reads) must stay resolved against the repo root instead.
UV_HERE  := uv run --frozen --project backend
NEXT_REV = $(shell printf '%04d' $$(( $$(ls backend/app/db/alembic/versions/[0-9]*.py 2>/dev/null | wc -l) + 1 )))

.PHONY: help all start doctor env seed stop reset requirements frontend frontend-install frontend-build frontend-test \
        setup gmail-consent translation-model up up-db down logs ps migrate migration migrate-roundtrip alembic-check \
        fmt lint type boundaries test-unit test-int test cov quick check smoke audit eval \
        workflows harness-test clean sim-demo sim-agents mock-mail rag-eval draft-report live-check gmail-pull pending approve context-report

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

# ---- run it (fresh clone) ----------------------------------------------------
# Needs only Docker, make, curl and Node 20.9+. uv is for contributors (setup, tests, lint).
all: doctor env up seed frontend-install ## fresh clone: check tools, create config, start backend, seed owner, install dashboard deps
	@echo
	@echo "Backend is up: http://localhost:$${API_PORT:-8000}. Now run: make frontend   (dashboard on http://localhost:3000)"

start: ## backend + seed + dashboard in one go (same as ./start.sh)
	./start.sh

doctor: ## check required tools, versions, free ports and disk
	./scripts/doctor.sh

env: ## create backend/.env and frontend/.env.local from the examples if missing
	@[ -f backend/.env ] || { cp backend/.env.example backend/.env && echo "created backend/.env from backend/.env.example (fake LLM and channels: runs offline)"; }
	@[ -f frontend/.env.local ] || { cp frontend/.env.example frontend/.env.local && echo "created frontend/.env.local"; }
	@mkdir -p "$${ESTATEOS_SECRETS_DIR:-$${HOME}/.estateos}"

seed: ## create the dev company, channel accounts and owner (idempotent; the dashboard logs in as this owner)
	$(COMPOSE) exec -T api python -m app.dev.simulate seed

stop: down ## stop the backend stack (data kept)

reset: ## DESTROY local database and app data: make reset CONFIRM=yes
	@[ "$(CONFIRM)" = "yes" ] || { echo 'this deletes the Postgres volume and local storage. Re-run: make reset CONFIRM=yes'; exit 2; }
	$(COMPOSE) down -v

frontend/node_modules/.package-lock.json: frontend/package-lock.json
	cd frontend && npm ci --no-audit --no-fund

frontend-install: frontend/node_modules/.package-lock.json ## install dashboard deps (only when package-lock.json changed)

frontend: env frontend-install ## dashboard dev server on http://localhost:3000 (needs the backend: make up seed)
	cd frontend && npm run dev -- --port 3000

frontend-build: frontend-install ## production build of the dashboard (type-check included)
	cd frontend && npm run build

frontend-test: frontend-install ## dashboard unit tests (vitest)
	cd frontend && npm test

translation-model: ## download the local translation models into backend/.data/models (the Docker image bakes its own)
	$(UV) python -m app.translation.fetch .data/models/opus-mt-nl-en nl-en
	$(UV) python -m app.translation.fetch .data/models/opus-mt-en-nl en-nl

requirements: ## regenerate backend/requirements*.txt for pip users from uv.lock (uv.lock stays the source of truth)
	cd backend && uv export --frozen --no-hashes --no-dev --no-emit-project -o requirements.txt
	cd backend && uv export --frozen --no-hashes --only-dev --no-emit-project -o requirements-dev.txt

# ---- contributor setup -------------------------------------------------------
setup: env ## contributors: python env (uv sync), pre-commit hooks, .env
	cd backend && uv sync --frozen
	$(UV_HERE) pre-commit install

up: env ## dev stack: postgres, migrate, api, worker
	$(COMPOSE) up -d --build --wait

up-db: env ## only postgres (for alembic / manual runs; tests use testcontainers)
	$(COMPOSE) up -d --wait postgres

down: ## stop stack (keeps volumes)
	$(COMPOSE) down

logs: ## tail stack logs
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

# ---- database ----------------------------------------------------------------
migrate: up-db ## alembic upgrade head
	$(UV) alembic upgrade head

migration: up-db ## new autogenerate revision: make migration m="add x"
	@[ -n "$(m)" ] || { echo 'usage: make migration m="message"'; exit 2; }
	$(UV) alembic upgrade head
	$(UV) alembic revision --autogenerate --rev-id $(NEXT_REV) -m "$(m)"

migrate-roundtrip: ## upgrade head -> downgrade base -> upgrade head (testcontainers)
	$(UV) pytest tests/integration/test_migrations.py -q -k roundtrip

alembic-check: ## fail if models drift from migrations (testcontainers)
	$(UV) pytest tests/integration/test_migrations.py -q -k drift

# ---- quality gates -----------------------------------------------------------
fmt: ## format + autofix
	$(UV) ruff format .
	$(UV) ruff check --fix .

lint:
	$(UV) ruff check .
	$(UV) ruff format --check .

type:
	$(UV) mypy app evals

boundaries: ## import-linter architecture contracts
	$(UV) lint-imports

test-unit: ## unit + adapter contract tests (fakes; no Docker)
	$(UV) pytest tests/unit tests/contract -q -n auto

test-int: ## integration: testcontainers Postgres + DBOS (needs Docker)
	$(UV) pytest tests/integration -q

test: test-unit test-int

cov: ## full suite with coverage floors (pyproject [tool.coverage])
	$(UV) pytest tests -q -n auto --cov=app --cov-branch --cov-report=term-missing:skip-covered

quick: lint type boundaries test-unit ## G1: lint, types, boundaries, unit

check: quick test-int frontend-test ## G2: G1 + integration (incl. migration roundtrip + drift)

smoke: up ## G5: stack up, api ready, worker executing, logs clean
	@curl -sf http://localhost:$${API_PORT:-8000}/health/ready >/dev/null && echo "api ready: ok"
	@$(COMPOSE) exec -T worker python -m app.worker --selfcheck && echo "worker: ok"
	@! $(COMPOSE) logs --no-color 2>&1 | grep -E 'Traceback|CRITICAL' && echo "logs: clean"

sim-demo: up ## G5: simulate WhatsApp + Gmail through the stack, assert rows; then a dashboard scenario (needs DASHBOARD_SESSION_SECRET, compose has a dev default; skipped if unset; temporarily sets outbound_mode=send + dashboard owner, restored after)
	$(COMPOSE) exec -T api python -m app.dev.simulate demo

sim-agents: up ## mock portfolio + one scripted day: every agent runs, dashboard fills; prints calls per agent (drafts only, nothing leaves the machine)
	$(COMPOSE) exec -T api python -m app.dev.simulate tour

gmail-pull: ## real Gmail test: sync NEW mail now, no Pub/Sub (backfill=1 also reads the last day): make gmail-pull mailbox=you@gmail.com
	$(COMPOSE) exec -T api python -m app.dev.simulate gmail-pull --mailbox "$(mailbox)" $(if $(backfill),--backfill)

mock-mail: ## mock tenant/contractor mail into the REAL connected Gmail, synced and processed (Google must be connected)
	$(COMPOSE) exec -T api python -m app.dev.simulate mock-mail

pending: ## pending approvals (dev company) with the tap to approve each
	$(COMPOSE) exec -T api python -m app.dev.simulate pending

approve: ## tap a pending approval as Harjot: make approve n=1 choice=d1
	$(COMPOSE) exec -T api python -m app.dev.simulate approve --n "$(or $(n),1)" --choice "$(or $(choice),d1)"

live-check: ## go-live gate: real WhatsApp/Gmail/S3/price-search adapters (credentials: docs/go-live-channels.md); subset: k=gmail or k=prices
	$(UV) pytest tests/live --live -v $(if $(k),-k "$(k)")

gmail-consent: ## Google token files (read + compose, drive=1 adds Drive, reply_send=1 adds the tenant-reply send token; every consent run re-consents the read and compose tokens too, so reply_send=1 is three tokens): make gmail-consent client=… mailbox=you@x out=~/.estateos
	$(UV) python -m app.dev.gmail_consent --client "$(client)" --mailbox "$(mailbox)" --out-dir "$(out)" $(if $(drive),--drive) $(if $(reply_send),--reply-send)

audit: ## dependency vulnerability audit
	mkdir -p .claude/.cache
	cd backend && uv export --frozen --no-hashes --format requirements-txt > ../.claude/.cache/req.txt
	$(UV_HERE) pip-audit -r .claude/.cache/req.txt --strict

rag-eval: up-db ## ADR 0008: document and message RAG quality on the synthetic corpora; reports in backend/evals/reports (scratch company in the dev DB; real models via EMBEDDING_MODEL/LLM_MODEL)
	$(UV) alembic upgrade head
	$(UV) python -m evals.rag_eval
	$(UV) python -m evals.message_rag_eval

draft-report: ## (M13 T16) draft acceptance per category and prompt version, counts only: make draft-report company=<uuid> days=30
	$(UV) python -m app.workflows.draft_report_cli --company-id $(company) --days $(or $(days),30)

eval: ## (M4) golden-set eval: make eval agent=understanding|linking|owner_qa|concierge|proposer|doc_reader|quote_reader|job_items|dd_reader version=v2
	$(UV) python -m evals.run --agent $(agent) --version $(version)

context-report: up-db ## (C1) context report: p50/p95 per stage, warm hit rate, cache hit ratio and tokens per turn
	$(UV) python -m app.dev.context_report $(if $(turns),--turns $(turns))

workflows: up-db ## list recent DBOS workflows (ops)
	$(UV) dbos workflow list --limit 20 --sys-db-url "$${DBOS_SYSTEM_DATABASE_URL:-postgresql://estateos:estateos@localhost:5433/estateos}"

# ---- harness -----------------------------------------------------------------
harness-test: ## self-test Claude guard hooks (stdlib only)
	python3 -m unittest discover -s .claude/hooks/tests

clean:
	rm -rf backend/.mypy_cache backend/.ruff_cache backend/.pytest_cache .claude/.cache backend/.coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
