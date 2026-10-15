# ADR 0006: Dashboard as the owner channel; real sends after owner approval

Date: 2026-10-15 · Status: accepted (direction decided by the user on 2026-10-15; the `itsdangerous` choice is flagged below for the user's veto)

## Context
Harjot will not use WhatsApp, Gmail or Google Chat. A dashboard (built elsewhere) is his only interface, with one Super
Agent in front of the other agents. Tenant messages are mirrored in the dashboard, and approving a reply sends it.

## Decision
- The dashboard is a new owner channel (`dashboard`, default). The backend exposes `/api/v1` (REST + SSE). Postgres
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
  the executed steps, so one model call (the planner) per turn at most, and none on the fast path (`tasks`, `?`, ...).
  Step results can hold untrusted tenant text; if a phrasing model is added later that text must sit inside the data
  delimiters (invariant 6).
- Tenant replies in send mode use a separate Gmail token (`GMAIL_REPLY_SEND_CREDENTIALS_FILE`), not the compose token.
- Gate status: the integration tests, `make check`, `make smoke`, `make sim-demo` and `make live-check k=outbound`
  for this work were written but not run (Docker and credentials unavailable). Accepted here means the design is
  accepted, not that send mode is verified: run those gates before `outbound_mode=send` on a real company.
