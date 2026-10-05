# EstateOS progress

Tick an item only with `/check` evidence. Milestone definitions: [build-plan.md](build-plan.md).

## M0 Prerequisites (owner: user + Harjot)
- [ ] Google Cloud project inside Harjot's Workspace, OAuth app Internal
- [ ] WhatsApp test number
- [ ] Coexistence route confirmed (Meta direct or partner)
- [ ] OpenAI org with EU data processing agreement
- [ ] BRIXX export received
- [ ] Labeller named for first 100 emails

## M1 Skeleton + contracts + first migration
Spec: [2026-10-05-estateos-m1-foundation-design.md](superpowers/specs/2026-10-05-estateos-m1-foundation-design.md)
- [x] Claude harness (CLAUDE.md, hooks, agents, skills, Makefile)
- [ ] Implementation plan written (`docs/superpowers/plans/`)
- [ ] pyproject + uv lock + ruff/mypy/pytest config
- [ ] core: config, logging, ids, errors
- [ ] six contracts + unit tests
- [ ] SQLAlchemy models (22 tables) + first Alembic migration + roundtrip/drift tests
- [ ] FastAPI app + health endpoints
- [ ] Celery app + Beat `timers.sweep` no-op
- [ ] Dockerfile + compose (postgres, redis, migrate, api, worker, beat)
- [ ] send-isolation architecture test
- [ ] GitHub Actions CI
- [ ] `make smoke` green + reviewer `ship`

## M2 Ingestion
## M3 Directory
## M4 Understanding + call log
## M5 Case engine
## M6 Proposals + rules
## M7 Owner channel + sender
## M8 Outcomes + hardening
