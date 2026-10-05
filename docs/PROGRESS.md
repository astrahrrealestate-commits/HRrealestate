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
- [ ] Implementation plan written (`docs/superpowers/plans/`) on branch `m1-foundation`
- [ ] pyproject + uv lock + ruff/mypy/pytest/coverage/import-linter config; `make setup` installs pre-commit
- [ ] core: settings, logging, ids, errors, telemetry
- [ ] six contracts + unit/property tests
- [ ] test infra: testcontainers Postgres, DBOS fixture, recorded() loader, factories
- [ ] SQLAlchemy models (22 tables) + first Alembic migration + roundtrip/drift tests
- [ ] FastAPI app + health endpoints
- [ ] DBOS app + worker (`--selfcheck`) + `timer_sweep` cron no-op
- [ ] Dockerfile + compose (postgres, migrate, api, worker)
- [ ] import-linter contracts green
- [ ] GitHub Actions CI
- [ ] G5 `make smoke` green + reviewer `ship`

## M2 Ingestion
## M3 Directory
## M4 Understanding + call log
## M5 Case engine
## M6 Proposals + rules
## M7 Owner channel + sender
## M8 Outcomes + hardening
