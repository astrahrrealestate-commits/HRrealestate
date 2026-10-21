# Dashboard as the owner interface + Super Agent (#10)

Date: 2026-10-15 · Status: **draft, awaiting review** · Supersedes the owner-channel parts of
[owner-channels design](2026-10-09-owner-channels-design.md) and the "Phase 1 sends nothing to tenants" rule.
Parent: [phase-1 agents design](2026-10-07-estateos-phase1-agents-design.md) · ADR: [0006](../../adr/0006-dashboard-owner-channel.md)

## Decisions (user, 2026-10-15)

1. Harjot no longer uses WhatsApp, Gmail or Google Chat. A **dashboard** is his only interface. WhatsApp and Gmail
   tenant/contractor messages are **mirrored into the dashboard inbox**; he never opens those apps.
2. One **Super Agent** is the only agent he talks to. It routes work to the other agents and to the backend.
3. **Approving a reply in the dashboard sends it for real** (Gmail send, WhatsApp text) to the tenant.
4. This repo builds the **backend API only**. The dashboard frontend is built elsewhere against the documented contract.

## What changes

| Area | Before | After |
|---|---|---|
| Owner interface | WhatsApp / Google Chat cards + morning email | Dashboard: inbox, cases, approvals, tasks, chat with Super Agent, live feed |
| Inbound tenant mail | Pipeline only; owner saw cards | Same pipeline; every message also visible in the inbox (read-only mirror) |
| Approval | Button tap in a chat app | `POST /approvals/{id}/decide` from the dashboard |
| Outbound to tenants | Gmail draft only | Company `outbound_mode`: `draft` (today) or `send` (Gmail send in thread / WhatsApp text) |
| Owner free text | regex commands + `owner_qa` | Super Agent (`concierge`) with typed plans; `owner_qa` becomes its answer skill |
| Owner channels | WhatsApp, Google Chat, email | `dashboard` (default). Others stay in code behind `interactive_channel`, no new work |

Unchanged: ingestion, DBOS workflows, understanding, linking, proposer, rules, tasks, waits, filing, outcomes,
guardrails, budgets, the approval/version/idempotency model.

## Architecture

```
 Dashboard (external SPA) ──HTTPS──► FastAPI /api/v1  ──► services ──► repositories ──► Postgres
        ▲   SSE /api/v1/events            │                  │
        │                                 │                  └─► DBOS enqueue (pipeline, exec, concierge turn)
        └─────────────────────────────────┘
 WhatsApp / Gmail inbound ─► raw_events ─► process_event ─► messages, cases, proposals  (unchanged)
 Owner-facing output ─► owner_feed rows (+ SSE)      Tenant-facing output ─► sender (guards) ─► Gmail / WhatsApp
```

**Integrated, not separate.** The Super Agent is a step inside a DBOS workflow (`concierge_turn`), reusing budgets,
guardrails, `model_calls` and idempotency. The REST routes and the agent's executor call the **same service
functions**, so the dashboard buttons and the agent can never diverge in rules.

### 1. Dashboard channel and owner feed
- `Channel.dashboard` and `InteractiveChannel.dashboard` (default). Migration 0009 widens the CHECKs.
- `owner_feed` table: `id, company_id, kind (approval|document_review|alert|briefing|task|agent_note), ref_id,
  payload jsonb (OwnerMessage-shaped), created_at, seen_at, resolved_at`. `send_to_owner` for the dashboard channel
  inserts a feed row (idempotent on its key) and publishes an SSE event. No 24 h window, no outbox.
- `OwnerMessage`/`OwnerChoice` stay the channel-neutral model. A `dashboard` renderer emits JSON the SPA draws.

### 2. Auth
- Owners sign in with Google (Workspace OIDC). The SPA sends the Google ID token once; the backend verifies it with
  `google-auth` (already a dependency), checks `email` against `owner_accounts.email`, and returns a short-lived
  signed session token (httpOnly cookie, CSRF header on writes). Tool choice and details are in ADR 0006.
- The principal carries `company_id` and `owner_id`; **no endpoint takes `company_id` from the client** (invariant 4).
- Unknown email → 403, logged. Rate limit per principal.

### 3. API (`/api/v1`, JSON, cursor pagination, OpenAPI published)
| Route | Purpose |
|---|---|
| `GET /inbox`, `GET /threads/{id}` | Unified WhatsApp + Gmail messages, grouped by thread/case, sender, linked case, attachments (presigned S3 URL, short TTL) |
| `GET /cases`, `GET /cases/{id}` | State, urgency, summary, timeline, linked messages, actions, waits |
| `GET /approvals`, `POST /approvals/{id}/decide`, `POST /approvals/{id}/edit` | Draft choice (`d1..d3`/`ok`), reject, edit → new `draft_version` |
| `GET /tasks`, `POST /tasks/{id}/done`, `POST /tasks/{id}/snooze`, `GET /waits` | Task manager and waits |
| `GET /documents/review`, `POST /documents/{id}/file` | Filing review and decision |
| `GET /briefing`, `GET /activity`, `GET /company`, `POST /company/pause`, `POST /company/resume` | Briefing, audit trail, controls |
| `POST /agent/messages` | Send text to the Super Agent; returns `{conversation_id, turn_id}` (202), workflow-backed |
| `GET /agent/conversations/{id}` | Turns with plan, step results, answer |
| `GET /events` | SSE: new messages, feed rows, turn progress/answers. `Last-Event-ID` resume from `owner_feed`/turn rows (Postgres is the source, SSE is only a nudge) |

Writes return the new state. Every write goes through the same services and guards as today's `owner_reply` path.

### 4. Super Agent (#10)
- **Fast path, no model:** the dashboard's own buttons hit REST routes. Exact commands typed in chat (`tasks`, `done #ref`,
  `pause`, …) are parsed by `owner_commands` first, so they work when the LLM budget is spent.
- **Everything else:** `concierge` Pydantic AI agent, `output_type=ConciergePlan`, **no write tools**, message and
  recent turns inside data blocks (invariant 6). It sees a compact brief: open cases, tasks, waits, pending approvals.
- `ConciergePlan` = ordered `steps[]`, each `{intent, args}`:
  `answer` · `list_tasks|list_waiting|case_status|search_inbox` · `briefing_now` ·
  `task_done|task_snooze|pause|resume` · `draft_reply|chase_now|file_document|create_task` · `open_view` (tells the SPA
  what to show) · `clarify`.
- **Executor (code):** validates every ref against the DB (company-scoped), then dispatches through a table to existing
  services. Read intents return data into the answer. State-changing intents that are reversible (`task_*`,
  `create_task`) run directly and are logged. Intents that could lead to a tenant message (`draft_reply`, `chase_now`)
  only **create a proposal**: it appears as an approval in the dashboard, and **only the owner's explicit approve
  click sends**. The agent can never approve on his behalf and never chooses a recipient.
- Specialists are existing code and agents called in a fixed order. No agent-to-agent LLM loops; every turn is bounded
  (max steps, one model call to plan, one optional call to phrase the answer).
  *Deviation (v1, Task 13):* the phrasing call is dropped. The answer is the step summaries, one per line in plan
  order, assembled in code; step results never go back to a model. This keeps turns bounded and cheap.
- `agent_conversations(id, company_id, owner_id)` and `agent_turns(id, conversation_id, text, plan jsonb, results jsonb,
  answer, status, prompt_ref, created_at)`; workflow id `concierge:{turn_id}`; per-company turn and token caps reuse the
  M4 budget. Failure falls back to `owner_qa`, then to a fixed message. Migration 0009.
- `owner_qa` stays as the read-only answer skill (scope guard, refusal text) and is called by the `answer` step.

### 5. Real sending (changes invariant 5 and the Phase 1 rule)
- `companies.outbound_mode`: `draft` (default; today's behaviour) or `send`. Switching to `send` is an owner-controlled
  setting that requires `make live-check k=outbound` green. Rollout is per company.
- New sender plans, still only in `app/sender/`:
  - **Gmail send** in the thread's own mailbox (`gmail.send` scope, new token file), reply headers from the stored thread.
  - **WhatsApp text to the tenant**, only inside the 24 h customer-service window of that tenant's last inbound
    message. Outside the window: blocked with a clear reason shown in the dashboard (template sending is out of scope).
- **Recipient rule:** target = the case's linked person identity on the **same channel as the thread being replied to**,
  read from the DB. No first-contact sends, no new recipients, no recipient from model output or from owner text.
- The sender keeps every existing re-check (approval status, `draft_version`, company pause, `sends.idempotency_key`,
  atomic claim) and adds: `outbound_mode == send`, recipient on the case, window open (WhatsApp), per-company hourly
  send cap, and `suspicious` actions need an explicit `confirm_suspicious` flag in the decide call.
- Output guard (links, accounts, phone numbers in drafts) stays; a flagged draft shows the warning in the approval.
- Outcome capture (sent-folder/echo) keeps working: it now compares sent text with the approved draft.
- Import-linter and the edit hook keep `SenderSettings` and `channels.*.outbound` private to `app/sender/`; the new
  `app/api/v1` and `app/services` may not import them. Test: no outbound call exists outside an approved `sends` row.

### 6. Ingestion visibility
The inbox is a query over `messages` + `threads` + `message_attachments`. Nothing new is stored. Outbound messages we
send appear in the same thread (direction `outbound`) with delivery status (`sent/delivered/read/failed`).
Messages held by the budget or flagged `suspicious` are shown with that state, never hidden.

## Build order (each step TDD, G1/G2, reviewer)

1. **D1 Foundation:** migration 0009 (`dashboard` enums, `owner_feed`, `agent_*`, `outbound_mode`), settings, auth
   (ID-token verify, session, principal dependency), `/api/v1` skeleton, OpenAPI export test, SSE feed.
2. **D2 Read API:** inbox/threads, cases, tasks, waits, briefing, activity. Company scoping and cross-tenant tests.
3. **D3 Decisions + sending:** approvals decide/edit, tasks done/snooze, documents, pause/resume via services; dashboard
   owner channel (`send_to_owner` → feed); sender `send` mode (Gmail, WhatsApp), guards, live-check `outbound`.
4. **D4 Super Agent:** `ConciergePlan` contract, `concierge/v1` prompt, executor + dispatch table, workflow, fallback to
   `owner_qa`, chat endpoints, SSE turn events.
5. **D5 Hardening:** concierge golden set (`make eval agent=concierge`), injection tests on inbox text reaching the
   agent, rate limits, docs (API contract, go-live, runbook), `make sim-demo` extended to drive the dashboard API.

## Testing

Unit: plan validation, dispatch table, recipient resolution, window rule, auth verification (valid, expired, wrong
audience, unknown email). Integration (testcontainers): cross-tenant isolation on every route, approve → exactly one
send (replay safe), edit after approval blocks the send, `draft` vs `send` mode, agent cannot approve or send, budget
exhausted still serves fast-path commands, SSE resume. Contract: OpenAPI snapshot. Eval: routing accuracy and
refusal of out-of-scope or injected requests.

## Risks

- **Real sending is the largest risk change.** Mitigations above: default `draft`, owner-only approve click, DB-derived
  recipient on the same channel, caps, suspicious confirm, idempotent claim. Needs Harjot's explicit sign-off before
  `outbound_mode=send` is enabled in production.
- WhatsApp window rule will block some replies; Gmail covers email threads.
- Frontend and backend ship separately: the OpenAPI snapshot test is the contract guard.

## Out of scope

The frontend itself, WhatsApp templates and first-contact outreach, multi-owner roles, push notifications outside the
dashboard (email/SMS alerts can be added later), attachment content analysis.

## Open points

1. Auth tool (Google ID-token verify plus own session, or an OIDC library): ADR 0006 proposes the former; confirm.
2. Does the SPA need websockets instead of SSE? SSE chosen (one-way push, simple, proxy-friendly).
3. Retention of mirrored attachments in S3 and presigned URL TTL (proposed 5 min).

## Deviations from the first draft (recorded at the end of the build)

- **No phrasing model call.** Answers are assembled deterministically from the executed steps (spec §4 had a second
  call). A turn makes the planner call plus at most one `owner_qa` call (an `answer` step, or the fallback when the
  planner fails); none on the fast path.
- **Separate reply-send token.** Tenant replies use `GMAIL_REPLY_SEND_CREDENTIALS_FILE` (`gmail.send` +
  `gmail.metadata`), not the compose token; `make gmail-consent reply_send=1` creates it.
- **Decide gate source.** The suspicious-message gate on `decide` reads the understandings listed in the action's
  `context_ref`, not the latest understanding of the thread.
- **Recipient.** The tenant recipient is the newest inbound message on the channel whose canonical sender identity is
  one of the case's primary person's current identities (from the DB). A thread with only a roommate's messages has no
  recipient and the send is blocked. Draft mode still addresses the raw sender (a draft only).
- **Tenant subject** of a Gmail reply is taken from the thread, not from model output.
- **Inbox `limit` above 100 is `422`** (advertised as `le=100`), not clamped; `/feed` still clamps.
- **Edit card** is delivered from the API through the DB-only feed (`approval:{id}:{n}` keys), not through the old
  owner-reply path.
- **`resume`**: the concierge does not execute a planned `resume`; the chat message `resume` (owner command) and
  `POST /company/resume` re-run approved, unexecuted actions.
- **Migrations**: `0009` (dashboard tables, owner `interactive_channel`, company `outbound_mode`) and `0010` (index
  `agent_turns (company_id, updated_at, id)` for the SSE turn cursor).
- **Auth/rate limits**: `itsdangerous` session cookie; in-process rate limits (ADR 0006).
- **Owner channel default stays `whatsapp`** (this spec, §1 and §2, says `dashboard` by default). The model and
  migration default of `owner_accounts.interactive_channel` remained `whatsapp`, pending the user's decision on
  existing rows; a dashboard owner is switched by SQL (runbook: `docs/go-live-channels.md`, "Switching the owner to the
  dashboard"). Approved owner-directed actions (contractor requests, escalations, owner notes, draft-mode WhatsApp
  replies) follow the owner's channel, so a switched owner gets them in the feed.
- **Final review fix wave**: in-flight tenant sends are skipped by `resume` and reported "in progress"; a send
  `sending` for 30+ minutes is marked failed once with one alert (no mark-sent route); a 5-minute sweep re-enqueues
  approved actions and pending turns stranded between commit and enqueue; optional `DASHBOARD_CORS_ORIGINS`; sessions
  re-read the owner row per request.


## Amendment 2026-10-16: page-aware Super Agent, conversation memory, stuck-send sweep

Decisions (user, 2026-10-16): the agent must know what the page it was opened on shows; the SPA sends a **text
snapshot** of the page (user's choice over IDs only), plus the open entity IDs; conversation memory and the stuck-send
sweep are included.

### Page context (`page` on `POST /agent/messages`, optional)
- `PageContext` = `view` (enum: inbox, thread, case, approvals, tasks, waiting, documents, briefing, other),
  `case_id|thread_key|approval_id|task_ref|attachment_id` (optional, open entity), `filters` (short key/value
  strings), `visible_ids` (at most 50 ids of rows on screen), `snapshot` (what the page displays as text, at most
  6000 characters, collapsed whitespace, control characters rejected).
- **The snapshot is client-supplied and therefore unverified.** It goes into the planner prompt only inside a
  `<page_snapshot>` data block labelled as unverified UI text, with tags escaped like every untrusted block
  (invariant 6). It can answer "what does this page say", explain what the owner sees, and resolve "this/it/the
  first one". It can never be an ID source, a recipient, or a permission: any case/task/approval the planner names is
  still resolved company-scoped by the executor, and ids named only in the snapshot text are not trusted.
- **Server facts:** every id in the structured fields is validated company-scoped and, when valid, replaced by facts
  loaded from the DB (case state/urgency/summary capped, last thread messages capped, approval drafts and suspicious
  flag, open waits). These go in a separate `<page_facts>` block and are authoritative; the snapshot is not. A foreign
  or unknown id is dropped and reported as "that page item no longer exists".
- Stored on the turn (`agent_turns.page_context` jsonb, migration 0011) so a retried turn reuses the same context.
- Prompt `concierge/v2` (v1 stays published): adds the page blocks, "this/it/them resolve to the page entity" and that
  the snapshot is unverified display text.
- *As built (Task 3, 2026-10-16):* the first run resolves the facts once and stores them in the same jsonb under
  `page_context.resolved` (`{facts, dropped}`) before the model call; a retry reuses them and never re-resolves. A
  resolver bug stores empty facts (`error` = exception type) and the turn goes on without them; transient errors
  retry. Raw snapshots over 24000 characters are rejected before collapsing; `\r` is a rejected control character.
  Open waits are not part of the facts (not requested by any field). `task_ref` resolves open or snoozed tasks only.
  `answer` steps still go to `owner_qa` with the owner's question only: it does not see the page facts or snapshot
  (follow-up), so "what does this page say" is answered from the open cases, not the snapshot.
  The thread key codec moved to `app/contracts/thread_key.py` (request contracts may not import the pipeline);
  `app.pipeline.read_repo` re-exports it.

### Conversation memory
The brief's history carries the last 6 turns of this conversation as owner text plus the agent's own answer (answer
capped at 300 characters), all inside the escaped history block.

### Stuck-send sweep (final review finding 1)
A cron step finds tenant `sends` rows in `sending` longer than the stuck threshold and settles them once (send and
action failed, one alert), so a worker crash mid-send is no longer silent. A lost claim reports "in progress" as a
distinct outcome that does not open the follow-up wait early.
