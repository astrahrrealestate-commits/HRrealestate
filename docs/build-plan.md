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
| Queue and timers | Redis 7 + Celery 5 for the work queue; timers stored in a Postgres table, checked every minute by Celery Beat |
| Schemas and config | Pydantic v2, pydantic-settings |
| AI | OpenAI SDK with structured outputs, behind our own `llm/` interface (provider can be swapped) |
| WhatsApp | Meta Cloud API via httpx, or a partner adapter if Coexistence requires one |
| Gmail | google-api-python-client, google-auth, Pub/Sub push |
| Attachments | Docling for PDFs; the model's vision for photos and scans |
| File storage | S3-compatible storage, EU region (boto3) |
| Observability | Langfuse (EU cloud), Sentry, structlog with JSON logs |
| Quality | ruff, mypy, pytest + pytest-asyncio, recorded webhook payloads, golden-set eval runner |
| CI | GitHub Actions |
| Deployment | Docker; docker compose for development; Phase 1 production = one EU VM running API, worker, Beat and Redis, plus managed Postgres |

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
    timers/         timers table, sweep, handlers
    directory/      BRIXX export import, contacts, channel identities
    outcomes/       Sent folder / echo capture → unchanged / edited / rewritten
    llm/            client interface, prompts/v1/*.md, output schemas
    db/             models, session, alembic/
    core/           config, logging, errors, ids
  workers/          celery_app.py, tasks.py, beat schedule
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
| **M1** | Skeleton | `docker compose up` runs API, worker, Beat, Postgres and Redis; first migration creates **every** table; CI runs ruff, mypy and pytest |
| **M2** | Ingestion | WhatsApp: verification handshake, signature check (`X-Hub-Signature-256`), insert raw event, acknowledge, enqueue. Gmail: Pub/Sub endpoint, history sync, watch renewed **daily** by timer. Media saved to S3. **Test:** feeding the same recorded payload in twice gives exactly one message row |
| **M3** | Directory | BRIXX export imported as a batch (people, units, leases, contractors, channel identities, with valid-from and valid-to dates); a phone number or email address looks up to a person, unit and lease |
| **M4** | Understanding + call log | `llm/` interface, prompt v1, typed output; every call written to `model_calls` and Langfuse; `run_eval.py` reports accuracy on the golden set |
| **M5** | Case engine | Identity → person → unit → lease; linking (same thread → same person with an open case → model check for borderline cases); rolling case summary. Linking accuracy measured |
| **M6** | Proposals + rules | `Action` objects and 2–3 drafts for decisions; Phase 1 rules: everything external needs approval, suspicious messages become exceptions, pause switch per company |
| **M7** | Owner channel + sender | Interactive WhatsApp messages to Harjot (reply buttons, list menu); owner command handler; Gmail drafts in the thread; 07:30 briefing via template plus timer; immediate urgent alerts. The sender uses an idempotency key and re-checks the approval and draft version |
| **M8** | Outcomes + hardening | Sent folder and echo capture labels every draft; Sentry alerts; a test proving no code path sends to a tenant; database backups; one day of shadow running on live mail |

**Order:** M1 → M2 → M3, with M4 running in parallel once M1 is done (it only needs fixtures). Then M5 → M6 → M7 → M8. With two engineers:
- **Engineer A:** M1, M2, M3, and the channel side of M7.
- **Engineer B:** M4, M5, M6, the owner logic in M7, and M8.

## Rules that apply from the first commit

- Postgres before the queue. Redis never holds the only copy of anything.
- No delayed Celery tasks longer than a few minutes; anything later goes in the `timers` table. Every task must be safe to run twice.
- Only `sender/` imports send credentials. In Phase 1 it can create Gmail drafts and message Harjot, and nothing else.
- Message content is never treated as instructions. It goes into prompts as clearly marked data.
- Every external call goes through an adapter, so Meta, the WhatsApp partner, Gmail or OpenAI can each be swapped without touching the pipeline.

**First coding session:** M1, plus the six contracts above as Pydantic models and the first Alembic migration. Everything after depends on those shapes.
