# EstateOS developer entry points. Every gate Claude, pre-commit or CI runs goes through here.
# Pipeline: docs/dev-pipeline.md  ·  G1 = quick  ·  G2 = check  ·  G5 = smoke
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

COMPOSE := docker compose -f docker/compose.yml $(if $(wildcard .env),--env-file .env)  # agent settings reach the containers
UV      := uv run --frozen
NEXT_REV = $(shell printf '%04d' $$(( $$(ls app/db/alembic/versions/[0-9]*.py 2>/dev/null | wc -l) + 1 )))

.PHONY: help setup gmail-consent up up-db down logs ps migrate migration migrate-roundtrip alembic-check \
        fmt lint type boundaries test-unit test-int test cov quick check smoke audit eval \
        workflows harness-test clean sim-demo rag-eval live-check gmail-pull pending approve context-report

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

# ---- environment -------------------------------------------------------------
setup: ## install deps, pre-commit hooks, .env
	uv sync --frozen
	$(UV) pre-commit install
	@[ -f .env ] || { cp .env.example .env && echo "created .env from .env.example — fill secrets"; }

up: ## dev stack: postgres, migrate, api, worker
	$(COMPOSE) up -d --build --wait

up-db: ## only postgres (for alembic / manual runs; tests use testcontainers)
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

check: quick test-int ## G2: G1 + integration (incl. migration roundtrip + drift)

smoke: up ## G5: stack up, api ready, worker executing, logs clean
	@curl -sf http://localhost:$${API_PORT:-8000}/health/ready >/dev/null && echo "api ready: ok"
	@$(COMPOSE) exec -T worker python -m app.worker --selfcheck && echo "worker: ok"
	@! $(COMPOSE) logs --no-color 2>&1 | grep -E 'Traceback|CRITICAL' && echo "logs: clean"

sim-demo: up ## G5: simulate WhatsApp + Gmail through the stack, assert rows; then a dashboard scenario (needs DASHBOARD_SESSION_SECRET, compose has a dev default; skipped if unset; temporarily sets outbound_mode=send + dashboard owner, restored after)
	$(COMPOSE) exec -T api python -m app.dev.simulate demo

gmail-pull: ## real Gmail test: sync NEW mail now, no Pub/Sub (backfill=1 also reads the last day): make gmail-pull mailbox=you@gmail.com
	$(COMPOSE) exec -T api python -m app.dev.simulate gmail-pull --mailbox "$(mailbox)" $(if $(backfill),--backfill)

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
	uv export --frozen --no-hashes --format requirements-txt > .claude/.cache/req.txt
	$(UV) pip-audit -r .claude/.cache/req.txt --strict

rag-eval: up-db ## ADR 0008: document RAG quality on the synthetic corpus, M10 baseline vs hybrid (scratch company in the dev DB; real models via EMBEDDING_MODEL/LLM_MODEL)
	$(UV) alembic upgrade head
	$(UV) python -m evals.rag_eval

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
	rm -rf .mypy_cache .ruff_cache .pytest_cache .claude/.cache .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
