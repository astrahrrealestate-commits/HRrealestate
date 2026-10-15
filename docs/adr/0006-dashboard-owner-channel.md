# ADR 0006: Dashboard as the owner channel; real sends after owner approval

Date: 2026-10-15 · Status: proposed (user decided the direction on 2026-10-15; auth tool pending confirmation)

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

## Consequences
- Invariant 5 changes from "nothing leaves to tenants" to the guarded-send rule in the dashboard spec §5. CLAUDE.md,
  hld.md and the sender allowlist are updated with it.
- WhatsApp/Chat/email owner channels stay in code, unmaintained beyond keeping tests green.
- Needs a `gmail.send` token and the owner's explicit go-live sign-off for `outbound_mode=send`.
