# EstateOS Phase 1: high-level design

> **2026-10-15:** the owner interface is now a dashboard (`/api/v1` + SSE) with one Super Agent; tenant sends happen after
> the owner's approve click (since 2026-11-24 he can also type and send WhatsApp messages himself on the Chats page, see
> [ADR 0013](adr/0013-owner-typed-whatsapp-sends.md)). Sections below that mention WhatsApp/Chat owner cards or "drafts only" are superseded by
> [the dashboard spec](superpowers/specs/2026-10-15-dashboard-super-agent-design.md) and [ADR 0006](adr/0006-dashboard-owner-channel.md).

Tools: [tech-stack.md](tech-stack.md) · Decisions: [adr/](adr/) · Milestones: [build-plan.md](build-plan.md)

## 1. Context

```
 Tenants / contractors                         Harjot (owner)
   │ WhatsApp (existing biz number)              ▲ WhatsApp (agent's own number)
   │ Email (Workspace mailbox)                   │ approve / edit / reject, briefing, alerts
   ▼                                             │
 360dialog ──webhook──┐   Gmail ──Pub/Sub push──┐│
                      ▼                         ▼│
               ┌───────────────── EstateOS ──────┴───────────┐
               │ FastAPI (api)   DBOS workers   Postgres     │──► OpenAI (EU) via Pydantic AI
               │                                S3 (EU)      │──► Langfuse EU, Sentry
               └─────────────────────────────────────────────┘
 Phase 1 outbound: Gmail DRAFTS in the thread + WhatsApp messages to Harjot ONLY.
```
*(Since the dashboard work: owner messages go to the dashboard feed for a `dashboard` owner, and in
`outbound_mode=send` an approved reply is sent to the tenant through the guarded sender; see §4.4.)*

## 2. Containers

| Container | Tech | Responsibility |
|---|---|---|
| `api` | FastAPI webhook routes + DBOSClient | verify signature/OIDC → insert `raw_events` (unique) → enqueue `process_event(raw_event_id)` with workflow id = raw_event id → 200 |
| `worker` | DBOS executor | runs all workflows, queues and cron schedules |
| `postgres` | PG 16 | domain tables + DBOS system tables (`dbos` schema) |
| `s3` | EU bucket | media, attachments, BRIXX documents (mirror Phase C) |
| `caddy` | reverse proxy | TLS for webhooks |

## 3. Components (in-process modules)

```
app/
  api/          FastAPI routers: whatsapp (Cloud API webhook), gmail (Pub/Sub), health
  channels/     inbound normalisers → Message contract; outbound adapters (imported ONLY by sender)
    whatsapp/   inbound.py + normalise.py (webhook models → Message), outbound.py (httpx transport, sender-only)
    gmail/      inbound.py (history sync → Message), outbound.py (drafts.create)
  ingestion/    raw_event insert/dedupe, media → S3, Message persistence
  workflows/    DBOS workflows: process_event, owner_reply, execute_action, briefing, gmail_watch_renew, timer_sweep
  pipeline/     understanding (agent), case_engine, proposals (agent), rules (pure)
  owner/        command handler, message builders (≤20-char buttons), briefing composer
  sender/       the only module with send credentials; guards + idempotent sends
  translation/  local Dutch to English (CTranslate2 adapter, sentence splitting, Postgres cache; ADR 0011)
  directory/    identity lookup; brixx/ = BRIXX mirror schema builder, page upsert, resumable sync, status read model (ADR 0010)
  outcomes/     sent-folder / echo capture, rapidfuzz labelling
  llm/          Pydantic AI agents, prompt loader (prompts/vN/*.md), model_calls recorder
  storage/      S3 adapter
  db/           SQLAlchemy models, repositories (company-scoped), alembic/
  contracts/    the six contracts
  core/         settings, logging, ids, errors, telemetry
```

**Dependency rule (import-linter):** `api → workflows → {pipeline, owner, ingestion, directory, outcomes} → {db, llm,
contracts, core}`. Only `sender` imports `channels.*.outbound`. `contracts` and `core` import nothing internal except
`core` used by `contracts`. Lower layers never import upper ones.

## 4. Key flows

### 4.1 Inbound tenant message (WhatsApp)
1. `POST /webhooks/whatsapp`. HMAC-SHA256 body signature verified per provider (`X-Hub-Signature-256` for Meta, `x-360dialog-signature` for 360dialog).
2. Resolve `channel_accounts` → company. `INSERT raw_events … ON CONFLICT DO NOTHING`, and for an inbound message
   also its `messages` row (text and metadata, no media yet; [ADR 0015](adr/0015-whatsapp-stored-at-the-webhook.md)).
   Commit. Chats read that row, so every message shows at once, whatever the queue or the pipeline is doing. A sender
   the directory does not know (and who is not the owner) gets `pipeline_status = skipped`: Chats only, never routed.
3. `DBOSClient.enqueue(process_event, raw_event_id, workflow_id=f"evt:{raw_event_id}")`. Return 200.
   A duplicate webhook means the same workflow id, so DBOS runs it once.
4. Worker `process_event` workflow; each step is checkpointed:
   1. `normalise` → `Message` + attachments to S3 (step; completes the row the webhook already stored)
   2. route: sender is an owner number → `owner_reply` workflow; sender not a known contact → stop (Chats only); else continue
   3. `understand` → Pydantic AI agent → `Understanding` over the 6 business categories (+ internal `spam`)
   4. `link_case` → identity → person → unit → lease → existing open case or new (transaction)
   5. `prepare` (`app/workflows/prepare.py`): read attachments (purging ID-document text), review vendor/contractor quotes against catalog and market references, and — in live mode (`history=False`) — run quality-tier draft research for open questions
   6. `propose` (`history=False` only; `history=True` stops before proposing) → dossier-backed `proposer/v14` (answers from the dossier before it asks, closes settled cases, negotiates only on money, never names a price, rule or date the data does not hold, ends a closing reply with what happens next) → `Action`s with drafts and extracted `commitments`
   7. `apply_rules` → pure function → `pending_approval` | `exception` (suspicious) | `paused` (company paused)
   8. `notify_owner` → enqueue `execute_action(notify_owner …)` (sender path)

### 4.2 Inbound email
Pub/Sub push → verify OIDC JWT (google-auth) → enqueue `gmail_sync(mailbox, history_id)` with workflow id
`gmail:{mailbox}:{history_id}` → `history.list` → one `raw_events` row per new message id → enqueue `process_event`
for each. The rest is identical to 4.1.

### 4.3 Owner approval
Harjot taps a button. The webhook from the owner number arrives with button id `apr:<approval_id>:<choice>`.
`owner_reply` workflow:
- parse `ButtonId` → lock the approval row → record the decision (transaction)
- `ok` / `d1..d3` → enqueue `execute_action(action_id, draft_version)` with workflow id
  `exec:{action_id}:{draft_version}`
- `edit` → ask for the new text; the next owner message becomes a new revision (draft_version + 1) and a new approval
- free-text question → read-only answer agent (no tools that write)

**Long waits are DB state, not sleeping workflows.** No workflow blocks for hours on an approval. This keeps workflows
short, so deploys never strand in-flight code versions.

### 4.4 Sender (`execute_action`)
In one transaction: `approval.status=='approved'` and `approval.draft_version == action.draft_version` and the company
is not paused, else abort. `INSERT sends(idempotency_key=exec:{action_id}:{draft_version})`; on conflict, already done.
Then call the adapter (Gmail `drafts.create` in the thread, or a WhatsApp message to the owner number), store
`provider_ref`, and mark the action executed. Phase 1 allowlist: the recipient must be an `owner_accounts` number, or
the action must be a Gmail draft. Anything else raises.

*Dashboard update (ADR 0006):* the allowlist also accepts the company's own dashboard owner feed (an `owner_feed` row
for approved owner-directed actions of a `dashboard` owner) and, only in `outbound_mode=send`, the case's own contact
on the thread's channel, re-derived from the database at execution (spec §5). The company row is locked for the claim,
the hourly tenant cap is checked, and a tenant send that is blocked or fails leaves one dashboard alert. A send still
`sending` after 30 minutes is marked failed once (status unknown: check the thread), by a re-run attempt or by the
5-minute sweep; a younger one is `in_progress` (no alert, no follow-up wait). The same sweep re-enqueues approved
actions and Super Agent turns stranded by a crash between commit and enqueue (24 h lookback).

### 4.5 Time-based work
| Job | Mechanism |
|---|---|
| Timer sweep (re-checks, overdue flags) | DBOS cron `* * * * *` → `SELECT … FOR UPDATE SKIP LOCKED` on `timers` |
| 07:30 briefing (company tz) | rows in the same `timers` table, rescheduled after each run, so timezone and DST are handled in our code |
| Gmail watch renewal | DBOS cron daily |
| Outcome capture | DBOS cron every 15 min: Sent-folder diff + echo matching |

### 4.6 Search, Astra and Today Category Desk (M13)
- **Message search** fuses all-words, any-words (with a Dutch/English glossary excluding header words) and vector similarity (`gemini-embedding-001` query vs document task types), then reranks matching chunks for Astra with redaction (`model_calls` stores sizes only).
- **Astra turn** (`app/super_agent/`): resolves portfolio entities (`rapidfuzz`), loads the last 12 turns + conversation summary block, runs read-only research tools (`open_message`, `open_thread`, `open_document`, `open_person`, `search_web` with guarded page fetch) within `SUPER_AGENT_DEADLINE_SEC` (35 s), and emits answers backed strictly by returned short references (`m1`, `d2`, `w1`, `q1`, `p1`).
- **Today Category Desk** (`GET /api/dashboard/categories`, `/{cat}`): ranks pending approvals, flagged quotes, overdue waits, awaiting replies, document reviews and BRIXX attention items across the 6 business categories; the frontend renders server order without inline approvals or demo fallbacks.

## 5. Data
Schema per M1 spec (24 domain tables). DBOS keeps its own tables in schema `dbos` in the same database, so one backup
covers everything. All domain rows carry `company_id`; repositories take `company_id` as a required argument.

## 6. AI design
- **Agents** (one Pydantic AI `Agent(output_type=Contract)` each, no tools): `understanding` (triage #2),
  `link_check` + `case_summary` (context linking #3), `proposer` (reply drafting #4 and chasers #5), `owner_qa`
  (read-only answers, preview of #10), `briefing` (#7), `doc_classifier` (#9). The orchestrator (#1), follow-up ladder
  (#5), task manager (#6) and quality monitor (#8) are plain code. Map: specs/2026-10-07-estateos-phase1-agents-design.md.
- **Offline by default:** `LLM_MODEL=fake` runs deterministic per-agent `FunctionModel`s (`backend/app/llm/fakes.py`); prod
  refuses it. Attachment contents are never sent to a model in Phase 1 (metadata only).
- **Prompt files** in `backend/app/llm/prompts/vN/<agent>.md`, loaded and hashed. Version and sha256 go on every `model_calls`
  row and Langfuse trace.
- **Injection defence:** untrusted text only inside `<message>…</message>` data blocks. Agents have **no write tools**.
  Output is validated by the contract and then by the pure-Python rules engine. Model output never picks a recipient:
  recipients come from the DB (case → person → identity).
- **Evals:** pydantic-evals datasets in `backend/evals/golden/` (labelled emails/WA messages). CI runs on prompt or contract
  change. Reports go to `backend/evals/reports/`.

## 7. Security and compliance
EU-only data processing (OpenAI EU residency + DPA, Langfuse EU, EU S3/DB). Webhook auth: Meta HMAC, Pub/Sub OIDC.
Secrets only in env. Least privilege: Gmail scopes `gmail.readonly` + `gmail.compose` (drafts); `gmail.send` only in a
separate token for send mode (`GMAIL_REPLY_SEND_CREDENTIALS_FILE`, ADR 0006). PII not logged at info level. Retention policy is decided at M0 with Harjot.

## 8. Failure handling
| Failure | Behaviour |
|---|---|
| Worker crash mid-workflow | DBOS resumes from the last completed step |
| OpenAI / Gmail / Meta 5xx or timeout | step retries with backoff (`retries_allowed`, `max_attempts`), then workflow ERROR → Sentry alert → fix → `fork_workflow` from the failed step |
| Duplicate webhook | `raw_events` unique + same workflow id = no-op |
| Duplicate send attempt | `sends.idempotency_key` unique = no-op |
| Edited draft after approval | version mismatch → sender aborts → owner re-asked |
| Company paused | rules return `paused`; sender re-checks too |

## 9. Deployment
Dev: `docker compose` (postgres, api, worker) + cloudflared for webhooks. Prod Phase 1: one EU VM (Caddy, api, worker,
migrate) + managed Postgres + S3. CI builds one image; the deploy job pulls it and restarts. Zero external infra beyond
Postgres and S3.
