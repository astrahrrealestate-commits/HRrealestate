# EstateOS developer entry points. Every check Claude or CI runs goes through here.
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

COMPOSE := docker compose -f docker/compose.yml
UV      := uv run --frozen
PY_DIRS := app workers evals tests

.PHONY: help setup up up-db down logs ps migrate migration migrate-roundtrip alembic-check \
        fmt lint type test-unit test-int test quick check smoke eval harness-test clean

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

# ---- environment -------------------------------------------------------------
setup: ## install deps (uv), git hooks, .env
	uv sync --frozen
	git config core.hooksPath .githooks
	@[ -f .env ] || { cp .env.example .env && echo "created .env from .env.example — fill secrets"; }

up: ## start full stack (postgres, redis, migrate, api, worker, beat)
	$(COMPOSE) up -d --build --wait

up-db: ## start only postgres + redis
	$(COMPOSE) up -d --wait postgres redis

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
	$(UV) alembic revision --autogenerate -m "$(m)"

migrate-roundtrip: up-db ## upgrade head -> downgrade base -> upgrade head
	$(UV) alembic upgrade head
	$(UV) alembic downgrade base
	$(UV) alembic upgrade head

alembic-check: up-db ## fail if models drift from migrations
	$(UV) alembic upgrade head
	$(UV) alembic check

# ---- quality -----------------------------------------------------------------
fmt: ## format + autofix
	$(UV) ruff format .
	$(UV) ruff check --fix .

lint:
	$(UV) ruff check .
	$(UV) ruff format --check .

type:
	$(UV) mypy app workers evals

test-unit:
	$(UV) pytest tests/unit -q

test-int: up-db ## integration tests against real postgres/redis
	$(UV) pytest tests/integration -q

test: test-unit test-int

quick: lint type test-unit ## fast tier: lint + types + unit  (stop hook equivalent)

check: quick migrate-roundtrip alembic-check test-int ## full tier

smoke: up ## stack tier: health + workers alive + no tracebacks
	@curl -sf http://localhost:$${API_PORT:-8000}/health/ready >/dev/null && echo "api ready: ok"
	@$(COMPOSE) exec -T worker celery -A workers.celery_app inspect ping --timeout 10 | grep -q pong && echo "worker: ok"
	@$(COMPOSE) ps beat --format '{{.State}}' | grep -q running && echo "beat: ok"
	@! $(COMPOSE) logs --no-color 2>&1 | grep -E 'Traceback|CRITICAL' && echo "logs: clean"

eval: ## golden-set eval: make eval prompt=understanding version=v1
	$(UV) python -m evals.run_eval --prompt $(prompt) --version $(version)

# ---- harness -----------------------------------------------------------------
harness-test: ## self-test Claude guard hooks (stdlib only)
	python3 -m unittest discover -s .claude/hooks/tests

clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache .claude/.cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
