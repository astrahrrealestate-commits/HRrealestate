# ADR 0006: Dashboard as the owner channel; real sends after owner approval

Date: 2026-10-15 · Status: accepted (direction decided by the user on 2026-10-15; the `itsdangerous` choice is flagged below for the user's veto)

## Context
Harjot will not use WhatsApp, Gmail or Google Chat. A dashboard (built elsewhere) is his only interface, with one Super
Agent in front of the other agents. Tenant messages are mirrored in the dashboard, and approving a reply sends it.

## Decision
- The dashboard is a new owner channel (`dashboard`; intended default, but the code default stayed `whatsapp`, see
  the amendments). The backend exposes `/api/v1` (REST + SSE). Postgres
  stays the source of truth; SSE only nudges the client.
- The Super Agent runs inside the existing DBOS pipeline as a workflow step, not as a separate service, so budgets,
  guardrails, idempotency and tenant scoping apply unchanged. It has no write tools and emits a typed plan that code
  validates and executes through the same services as the REST routes.
- Tenant sends are allowed only through `app/sender/`, only after the owner's approve click, only to the case's own
  identity on the thread's channel, behind `outbound_mode` (default `draft`).
- Auth: verify the Google ID token with `google-auth` (already a dependency) and issue a signed short-lived session
  cookie; no new auth framework. Alternative: an OIDC library (authlib), rejected for now as extra surface.
- Rate limits are in-process token buckets (`app/api/v1/ratelimit.py`, injectable clock): agent messages 30/min per
  owner, login 10/min per client IP, decision writes 120/min per owner. State is per process, which is correct for the
  single API worker of Phase 1. **Running several API instances needs Postgres-backed counters** (a table with an
  atomic upsert, or advisory locks); Redis is not an option (invariant: no Redis). `X-Forwarded-For` is ignored unless
  `DASHBOARD_TRUST_FORWARDED_FOR=true`.

## Consequences
- Invariant 5 changes from "nothing leaves to tenants" to the guarded-send rule in the dashboard spec §5. CLAUDE.md,
  hld.md and the sender allowlist are updated with it.
- WhatsApp/Chat/email owner channels stay in code, unmaintained beyond keeping tests green.
- Needs a `gmail.send` token and the owner's explicit go-live sign-off for `outbound_mode=send`.

## Amendments (2026-10-15, end of the dashboard build)
- New dependency: **`itsdangerous`** signs and time-checks the session cookie (small, maintained, already the Flask/
  Starlette session primitive). Chosen by the build when the user said "start" without picking an auth
  library; the user has not explicitly confirmed it (ledger ruling). Swap it if vetoed: only `app/api/v1/auth.py`
  uses it.
- The Super Agent's **second "phrasing" model call was dropped**. Version 1 assembles answers deterministically from
  the executed steps. A turn makes the planner call plus at most one `owner_qa` call (an `answer` step, or the
  fallback when the planner fails), and no model call on the fast path (`tasks`, `?`, ...).
  Step results can hold untrusted tenant text; if a phrasing model is added later that text must sit inside the data
  delimiters (invariant 6).
- Tenant replies in send mode use a separate Gmail token (`GMAIL_REPLY_SEND_CREDENTIALS_FILE`), not the compose token.
- Gate status: the integration tests, `make check`, `make smoke`, `make sim-demo` and `make live-check k=outbound`
  for this work were written but not run (Docker and credentials unavailable). Accepted here means the design is
  accepted, not that send mode is verified: run those gates before `outbound_mode=send` on a real company.

## Amendments (2026-10-15, final review fix wave)
- **Owner default not flipped.** `owner_accounts.interactive_channel` still defaults to `whatsapp` in code: changing
  existing rows needs the user's decision. A dashboard owner is switched by SQL (go-live runbook in
  [go-live-channels.md](../go-live-channels.md)).
- **Approved owner-directed actions follow the owner's channel.** For a `dashboard` owner, approved
  `request_contractor`, `escalate`, `notify_owner` and draft-mode WhatsApp replies are one `owner_feed` row under the
  `exec:{action}:{version}` key, written in the same transaction that marks the `sends` row (channel `dashboard`,
  target `owner:{owner_id}`) sent. The sender allowlist accepts such a plan only for the company's own dashboard owner.
- **Commit-then-crash sweep.** The API commits, then enqueues; a crash in between used to strand the work. A DBOS
  cron (`sweep.stranded`, every 5 minutes) re-enqueues approved actions (decided 5 min to 24 h ago, still `approved`,
  no exec `sends` row, company not paused) and `pending` turns (5 min to 24 h old) under the same deterministic ids,
  200 per round. DBOS dedupes anything that already started.
- **In-flight and stuck sends.** `resume` skips actions whose exec send is `sending`/`sent`/`failed`. An attempt that
  loses the claim to a tenant send still `sending` for under 30 minutes reports "in progress" (no failure, no alert).
  An older one never reported: the send and the action are marked failed once, with one alert (key
  `blocked:exec:{action}:{version}`, shared by every path) telling Harjot to check the thread before resending by hand.
  There is still no dashboard route to mark such an item sent.
- **Deployment.** Serve the SPA same-origin behind the reverse proxy. `DASHBOARD_CORS_ORIGINS` is an optional exact
  allowlist for a SPA on another origin (never `*`). Each request re-reads the owner row, so removing an owner or
  changing the email ends the session at once.

## Amendment (2026-10-16, page-aware Super Agent)
- **Page context.** `POST /agent/messages` takes an optional `page` (open entity ids, visible row ids, filters and a
  text snapshot of the page, at most 6000 characters). Ids are resolved company-scoped into server facts
  (`<page_facts>`); the snapshot is unverified display text in an escaped `<page_snapshot>` block, never an id,
  recipient or permission source. Stored on the turn (`agent_turns.page_context`, migration 0011) with the facts
  resolved once, so a retry reuses them. Prompt `concierge/v2`.
- **Page-aware answers (Task 4).** The `answer` step and the planner-failure fallback pass the stored page facts and
  snapshot to `owner_qa`, which uses prompt `owner_qa/v3` only when a page is present (`owner_qa/v2` and a
  byte-identical prompt otherwise). Still at most one `owner_qa` call per turn, under the same `owner_qa` budget.

## Amendment (2026-10-22, steerable drafts)
- The Super Agent's `draft_reply` steers the proposer with the owner's sanitised wording (prompt `proposer/v2`) and,
  on a turn, supersedes a pending reply draft (new `draft_version`, old approval expired) or redrafts a decided one,
  once per turn. The draft is quoted in the chat answer and exists as a pending approval; only the approve click can
  lead to a send, recipients still come from the DB, and suspicious or paused messages are never redrafted.
