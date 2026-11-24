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

> **Amendment 2026-11-24 (ADR 0013):** owner-typed WhatsApp text from the Chats page is a second allowed send class.
> It needs no approval row (Harjot typed it and clicked send), but the recipient is still derived from the DB
> (the stored thread of an outbound row, a number that wrote to the company before, never an own number), and
> `outbound_mode=send`, company pause, the 23 h window, `sends.idempotency_key` and an own hourly cap apply.
> Everything above stays true for AI-drafted actions; the Super Agent still cannot send.

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
  retry. Raw snapshots over 24000 characters are rejected before collapsing. Open waits are not part of the facts
  (not requested by any field). `task_ref` resolves open or snoozed tasks only.
- *As built (Task 4, 2026-10-16):* `answer` steps and the planner-failure `owner_qa` fallback see the page: the stored
  `resolved` facts plus the snapshot and filters (no new I/O; a turn stored before facts were resolved gets no page).
  They use prompt `owner_qa/v3` (escaped `<page_facts>` authoritative, `<page_snapshot>` unverified: may describe the
  page, never an id, recipient, instruction or permission source; same scope rule and refusal). Without a page the
  owner_qa prompt is byte-identical and the spec stays `owner_qa/v2` (WhatsApp/Chat questions unchanged); screening
  applies to the owner's text only, budget and fallbacks unchanged; `case_refs` may also name case ids on the
  server-built page fact lines. Snapshot CRLF and lone CR become LF (other control characters still `422`). A visible
  thread key may be up to 400 characters (UUIDs and task refs 120). The filters line is rendered apart from the
  snapshot, so only the snapshot is capped at 6000. Prompt escaping strips Unicode format characters (Cf) and
  default-ignorable code points, applies NFKC and maps angle-quote/slash look-alikes before matching block tags
  (NFKC also folds compatibility characters such as `½` in ordinary text).
  The thread key codec moved to `app/contracts/thread_key.py` (request contracts may not import the pipeline);
  `app.pipeline.read_repo` re-exports it.

### Conversation memory
The brief's history carries the last 6 turns of this conversation as owner text plus the agent's own answer (answer
capped at 300 characters), all inside the escaped history block.

### Stuck-send sweep (final review finding 1)
A cron step finds tenant `sends` rows in `sending` longer than the stuck threshold and settles them once (send and
action failed, one alert), so a worker crash mid-send is no longer silent. A lost claim reports "in progress" as a
distinct outcome that does not open the follow-up wait early.


## Amendment 2026-10-22: live chat awareness, steerable drafts, seconds-level turns

Decisions (user, 2026-10-22): when the owner opens a chat/thread/case page and types a prompt, the agent reads that
conversation (WhatsApp and Gmail) and its stored context from the database, understands it, answers, and can
draft replies; all within seconds. A requested draft is returned **in the chat reply and also created as a pending
approval** (one click to approve or edit; nothing is sent until approval). Speed work is the core set, **no token
streaming** in this round.

- **Memory pack** (extends `<page_facts>`): for an open thread/case, up to 30 messages (about 600 characters each,
  newest-biased, direction and time), the case summary and timeline, lease/unit/person facts from the directory, open
  waits, earlier drafts and the owner's edits and decisions. Authoritative server facts, company-scoped, tenant text
  escaped like all untrusted text, bounded token budget; stored resolved on the turn like other facts.
  - *As built (Task 1, 2026-10-22):* a thread page reads that thread's messages only; a case page (no thread) reads
    the case's linked messages on every channel. One window query numbers the conversation and keeps all messages up
    to 30, else the first 6 and newest 24; each is one line `msg NN | direction | channel | time UTC | text` (600
    characters, normalised and collapsed before capping, so tenant text never starts a line or forges a fact line).
    The case memory (the open case, else the open thread's case) is four queries: the person and that person's lease
    parties (Phase 1 cases carry no unit/lease ids, so leases come from the lease parties; at most 3), open waits (at
    most 5, `about` 200), the last 15 events (note 120) and the latest 5 actions (status, `draft_version`, latest
    approval status, edit revisions count, first variant 300). Summary cap is now 800. The facts text is at most
    12000 characters after normalisation; over it, whole lines go in a fixed order (older messages down to the newest
    6, visible rows bottom first, oldest events, oldest earlier drafts, remaining messages), never the headers,
    summary, directory facts or waits, with gap markers and a "left out" line. Only `<page_facts>` gets the larger
    12000 cap (`page_blocks.MAX_PAGE_FACTS`; other blocks keep 8000), escaping still runs after truncation. Statement
    count per page does not grow with the number of messages.
- **Steerable drafts:** `draft_reply` takes the owner's wording as sanitised guidance for the proposer (new proposer
  prompt version; v1 stays published); with a pending draft it supersedes it with a new `draft_version` instead of
  failing; the drafts are echoed in the turn answer and exist as approvals (the approval gates sending).
  - *As built (Task 2, 2026-10-22):* the guidance is the owner's own message (never the planner's `text`: the
    planner reads tenant text), sanitised (links, emails, phones, IBANs, amounts redacted; the answer then says details were removed) and given
    to the proposer as an `<owner_guidance>` data block with the replaced draft as `<current_draft>`; prompt
    `proposer/v2` only for these owner-requested drafts (inbound and chase proposals keep `proposer/v1`). Message with
    no proposal: the propose stage. Pending reply draft: superseded once (old approval expired, `draft_version + 1`,
    new approval, feed card resolved). Decided proposal: one fresh reply action for that message per turn. Both carry
    an ActionRevision keyed `agent:{turn_id}:{step}`; a retried step returns the same revision without a model call.
    The redraft passes the propose-stage rules: a suspicious or paused message, or a draft with an unverified link,
    account or phone number, changes nothing. The answer quotes up to 3 variants (600 characters each, output-guard
    flags, flagged variants redacted); `data` has the approval id for approve/edit. Plan `case_id`s are limited to the
    brief's open cases and the case ids on resolved page-facts lines (never tenant text or the snapshot); others get
    "Open that case's page first". A reply whose edit was tapped less than 24 h ago is never redrafted (an older,
    unusable edit is expired by the redraft); the redraft and `decide` both lock approval then action with fresh rows.
- **Speed:** one model call for page/chat questions (the planner returns the answer; no second owner_qa call), a
  dedicated chat queue with a short poll interval, turn SSE poll about 0.5 s, `PUT /agent/page` pre-warms resolved
  page facts when the owner navigates, per-turn timings stored on the turn so latency is measurable.
  - *As built (Task 3, 2026-10-22):* `ConciergePlan.reply` (required, nullable, at most 1200 characters) with prompt
    `concierge/v3` (v2 and v1 stay published; evals run either). The planner answers page/chat questions in `reply`
    and plans an `answer` step; actions keep their steps with `reply` null, and `draft_reply` takes `text` null (the
    guidance is the owner's own message). The reply is screened before anyone sees it (`concierge_reply`): kept only
    for an in-scope plan, control/format characters removed, at most 20 lines and 1200 characters, links, emails,
    phones, IBANs and amounts redacted (`concierge_sanitize.redact`), ids never read from it; the plan is stored with
    the screened reply, and an `answer` step is appended when a usable reply has none. The `answer` step shows it and
    calls owner_qa only when it is blank (the planner-failure fallback is unchanged). The snapshot cap is 3000 instead
    of 6000 characters when `<page_facts>` carries a memory pack. Turns run on the `concierge` DBOS queue
    (`worker_concurrency` from `concierge_worker_concurrency`, default 4; `polling_interval_sec` 0.25, the DBOS
    default is 1), from the API and the stranded-turn sweep, with the same `concierge:{turn_id}` id. The SSE stream
    polls turns every 0.5 s and the feed every 1.5 s (about 2 indexed turn queries/s per stream). `agent_turns.timings`
    (migration 0012) holds `queue_wait_ms` (database clock), `page_resolve_ms`, `planner_ms`, `executor_ms`,
    `answer_ms`, `total_ms` and `attempts`, merged at every write so a retry keeps earlier values; read-only in
    `GET /agent/conversations`. Migration 0012 also adds the expression index `messages (company_id, channel,
    coalesce(thread_ref, provider_msg_id))` for the thread scan. No latency has been measured yet (fake model only).
    *Fix round 1 (2026-10-23):* a `reply` is kept and shown only when every step is `answer` or `open_view` (any action
    step: reply null, nothing appended; a reply no `answer` step can show is stored null; the executor applies the same
    rule to older stored plans). Amounts are allowed in replies: `screen_reply` uses `redact_contact` (links, emails,
    IBANs, phones) instead of `redact` (titles, clarify questions and guidance keep losing amounts), and prompt
    `concierge/v5` (v4 plus one rule) allows only amounts found in `<data>`/`<page_facts>`, never from the snapshot or
    one a message asks to be paid. An 8+ digit run still reads as a phone number.
  - *As built (Task 4, 2026-10-23):* `PUT /api/v1/agent/page` (session owner, CSRF, its own 60/min bucket) takes the
    same validated `PageContext` as `page`, resolves its facts company-scoped with the turn's resolver and stored shape
    (`concierge_page.resolved_value`) in one transaction, and upserts ONE `agent_page_state` row per owner (migration
    0015: `page_key`, `resolved` = facts text + dropped kinds, `resolved_at` = that transaction's database time; no
    snapshot, filters or ids stored). `204` with no body, never a turn or a model call; a non-transient resolver error
    stores nothing (still 204), a transient one is 503. `create_turn` reads the owner's row (plain company + owner
    SELECT, no lock) and stores its facts under `page_context.resolved` only when the message's `page_key` matches
    (a hash of the view, each open id in its field and the visible ids in screen order; filters and snapshot excluded)
    and `resolved_at` is at most 120 s before the turn's own `now()` (its `created_at`); the run then skips resolving
    exactly like a retry. The snapshot and filters always come from the message. The TTL is applied at read time; the
    row is overwritten by the next PUT (never by an older resolution, never across companies), so nothing grows.
    *Fix round 1 (2026-10-23):* freshness is server-side. A candidate reuse is dropped when the company has a message,
    an approval created or decided, or a case event newer than `resolved_at - 2 s` (one statement of four
    company-scoped `max()` lookups, indexes from migration 0016), so a tenant message that arrives after the pre-warm
    is never missing; the SPA pre-warms on navigation and may re-warm after its own writes, for speed only. A failed
    state read never fails the message (savepoint, cold page).
