# EstateOS Phase 1: build plan

> Source of truth for milestones and rules. Architecture diagram: [architecture.md](architecture.md).
> **Tooling superseded where noted in [tech-stack.md](tech-stack.md)** (DBOS replaces Celery/Redis/Beat; Pydantic AI; pywa). HLD: [hld.md](hld.md).
> Detailed M1 design: [superpowers/specs/2026-10-05-estateos-m1-foundation-design.md](superpowers/specs/2026-10-05-estateos-m1-foundation-design.md).

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| API | FastAPI + Uvicorn |
| Database | PostgreSQL 16 (managed, EU region), SQLAlchemy 2, Alembic, psycopg 3 |
| Queue and timers | DBOS Transact (durable workflows, queues, cron in Postgres); due work in the `timers` table, swept every minute by a DBOS cron (ADR 0001) |
| Schemas and config | Pydantic v2, pydantic-settings |
| AI | OpenAI SDK with structured outputs, behind our own `llm/` interface (provider can be swapped) |
| WhatsApp | Meta Cloud API via httpx, or a partner adapter if Coexistence requires one |
| Gmail | google-api-python-client, google-auth, Pub/Sub push |
| Attachments | Docling for PDFs; the model's vision for photos and scans |
| File storage | S3-compatible storage, EU region (boto3) |
| Observability | Langfuse (EU cloud), Sentry, structlog with JSON logs |
| Quality | ruff, mypy, pytest + pytest-asyncio, recorded webhook payloads, golden-set eval runner |
| CI | GitHub Actions |
| Deployment | Docker; docker compose for development; Phase 1 production = one EU VM running API and one DBOS worker, plus managed Postgres |

**One infrastructure fact:** Gmail push only works through a Google Cloud Pub/Sub topic, so a Google Cloud project is needed whatever you host on. Create it inside Harjot's Workspace, with the OAuth app set to Internal.

## Repository layout

```
estateos/
  app/
    api/            webhooks (whatsapp.py, gmail.py), health
    channels/       whatsapp/, gmail/: normalise inbound, send outbound
    ingestion/      raw_event insert, dedupe, enqueue, media → S3
    pipeline/       understanding.py, case_engine.py, proposals.py, rules.py
    owner/          command handler, briefing, message builders (buttons ≤20 chars)
    sender/         the only module with send credentials
    workflows/      DBOS workflows, queues, schedules (incl. timer sweep)
    directory/      BRIXX export import, contacts, channel identities
    outcomes/       Sent folder / echo capture → unchanged / edited / rewritten
    llm/            client interface, prompts/v1/*.md, output schemas
    db/             models, session, alembic/
    core/           config, logging, errors, ids
  evals/            golden/ (labelled cases), run_eval.py, reports/
  tests/            unit/, integration/, fixtures/ (recorded payloads)
  docker/           Dockerfile, compose.yml
```

## Contracts to lock on day 1, before any pipeline code

1. **`Message`**, the one normalised format for both channels: `channel, provider_msg_id, thread_ref, sender_identity, direction, sent_at, text, attachments[], raw_event_id`.
2. **`Understanding`**, the AI output: `category, intent, urgency, entities{people, unit_refs, dates, amounts}, suspicious{flag, reason}, confidence`.
3. **`Action`**, the proposal engine's output and the only thing the rules engine accepts: `type, case_id, payload, rationale, context_ref, draft_version`.
4. **Case states:** `open → waiting_on_owner | waiting_on_third_party → resolved | closed`.
5. **Button ID format:** `apr:<approval_id>:<choice>`, which lets the owner command handler match a tap to its approval without guessing.
6. **Prompt versioning:** files under `llm/prompts/v1/`; every model call records which version it used.

## Milestones

| # | Milestone | Done when |
|---|---|---|
| **M0** | Prerequisites (owner: you plus Harjot) | Google Cloud project inside his Workspace; WhatsApp test number; Coexistence route confirmed (Meta directly or a partner); OpenAI organisation with an EU data processing agreement; BRIXX export received; someone named to label the first 100 emails |
| **M1** | Skeleton | `docker compose up` runs Postgres, migrate, API and the DBOS worker (cron); first migration creates **every** table; CI runs ruff, mypy and pytest |
| **M2** | Ingestion | WhatsApp: verification handshake, signature check (`X-Hub-Signature-256`), insert raw event, acknowledge, enqueue. Gmail: Pub/Sub endpoint, history sync, watch renewed **daily** by timer. Media saved to S3. **Test:** feeding the same recorded payload in twice gives exactly one message row |
| **M3** | Directory (**deferred**, user 2026-10-07) | BRIXX export imported as a batch (people, units, leases, contractors, channel identities, with valid-from and valid-to dates). Until then the directory is identity-first: an unknown phone/email becomes a person on first contact |
| **M4** | Understanding + call log | `llm/` interface, prompt v1, typed output; every call written to `model_calls` and Langfuse; `make eval` reports accuracy on the golden set. Attachment **contents are not read** in Phase 1 (metadata only) |
| **M5** | Case engine + tasks + waits | Identity → person; linking (same thread → the person's only open case → `link_check` agent among several → new case); rolling case summary. Owner tasks (#6) and waiting-for items (#5) with timers |
| **M6** | Proposals + rules + chasing | `Action` objects and 2–3 drafts; Phase 1 rules: everything external needs approval, suspicious messages become exceptions, pause switch per company. Overdue waits produce chaser drafts, then an escalation |
| **M7** | Owner channel + sender | Approval cards (reply buttons, list menu); owner commands (`tasks`, `done`, `snooze`, `waiting`, `pause`, `resume`, `help`) and owner Q&A; Gmail drafts in the thread; 07:30 daily and Friday weekly briefing; WhatsApp 24 h window (outbox + template); the sender re-checks approval, draft version, pause, allowlist and idempotency key |
| **M9** | Document filing (#9) | Attachments classified from metadata, named and filed in Google Drive (`drive.file`); uncertain ones go to an owner review card |
| **M8** | Outcomes + drift + hardening | Sent folder and echo capture labels every draft; daily drift snapshots (autonomy, cost, performance) with owner/Sentry alerts; a test proving no code path sends to a tenant; database backups; one day of shadow running on live mail |

**D (Dashboard + Super Agent, branch `d-dashboard`):** the owner's interface is the dashboard API, with real tenant sends after the approve click. Plan, spec and status: [PROGRESS.md](PROGRESS.md) section D, [dashboard-api.md](dashboard-api.md), [ADR 0006](adr/0006-dashboard-owner-channel.md).

Agents per milestone: [specs/2026-10-07-estateos-phase1-agents-design.md](superpowers/specs/2026-10-07-estateos-phase1-agents-design.md).

**Order:** M1 → M2 → M4 → M5 → M6 → M7 → M9 → M8 (M3 deferred until the BRIXX export arrives). With two engineers:
- **Engineer A:** M1, M2, M3, and the channel side of M7.
- **Engineer B:** M4, M5, M6, the owner logic in M7, and M8.

## Rules that apply from the first commit

- Postgres before the queue. Nothing lives only in memory or in a queue.
- No long sleeps or waits inside workflows; anything later goes in the `timers` table. Every step must be safe to run twice.
- Only `sender/` imports send credentials. In Phase 1 it can create Gmail drafts and message Harjot, and nothing else.
- Message content is never treated as instructions. It goes into prompts as clearly marked data.
- Every external call goes through an adapter, so Meta, the WhatsApp partner, Gmail or OpenAI can each be swapped without touching the pipeline.

**First coding session:** M1, plus the six contracts above as Pydantic models and the first Alembic migration. Everything after depends on those shapes.
