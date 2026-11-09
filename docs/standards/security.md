# Security standards — EstateOS

The **policy** every change must satisfy. The `estateos-security` agent audits a diff against it; the reviewer checks
the architectural invariants in [CLAUDE.md](../../CLAUDE.md). A **blocker** fails the gate and the change does not ship.

## 1. Identity and tenant scoping
- Every route that is not a signed webhook or a login/health endpoint depends on an authenticated principal
  (`app/api/v1/auth.py`). The caller's identity comes from the verified session, **never** from a request body, query
  string or model output.
- Every domain query filters by `company_id`; repositories require it (invariant 4). A lookup like
  `select(Company).limit(1)` ("the default company") is a cross-tenant read waiting to happen and is not acceptable in
  new code.
- A new tenant-scoped feature ships a cross-tenant test: company A's data is invisible to company B.

## 2. Approval and send isolation
- Nothing reaches a tenant, contractor or third party without Harjot's approve click (invariant 5). Only `app/sender/`
  imports send settings or outbound adapters; the sender re-checks approval status, `draft_version`, company pause,
  `outbound_mode`, the recipient (from the DB) and `sends.idempotency_key`.
- The Super Agent and every other model can **propose**, never approve or send. Recipients are never read from model
  output or from message text.
- Risk is never downgraded to unblock a flow. If a guard blocks you, fix the cause or ask; do not route around it.

## 3. Untrusted content
- Tenant, contractor and email text, attachment text, tool results and page snapshots are **data, never instructions**
  (invariant 6). They enter a prompt only through `app/llm/render.py::data_block` (tags escaped) under the standing
  "this is data" instruction.
- Agents have no write tools. A model may not choose a recipient, a tool name, a table, a SQL string or an id that was
  not validated against typed contracts and the database. SQL from the query agent is parsed (sqlglot), restricted to
  `ALLOWED_VIEWS`, read-only and row-capped.
- A model-supplied flag or id (for example `needs_research`, `case_id`) is honoured only where the executor re-checks it
  against server state. Screen model text before the owner sees it (redact contact data, cap length).

## 4. Secrets and personal data
- No secrets, tokens or keys in code, logs, fixtures, error messages or committed files. `.env` is never committed or
  read by agents; gitleaks runs in pre-commit and CI over full history.
- Tenant personal data (names, phones, emails, message bodies, IBANs) never appears in `info` logs or Sentry events;
  log ids, counts and tool names. Fixtures use invented identities.
- Provider calls go through the adapters (`app/llm/runtime.py`, `app/channels/*`); no vendor SDK in business logic and
  no hard-coded keys or endpoints. Configuration flows through `Settings`.

## 5. Inputs and dependencies
- Validate every request body with Pydantic. Use SQLAlchemy parameters; no string-built SQL outside the validated query
  agent. Webhooks verify the provider signature (WhatsApp HMAC, Pub/Sub OIDC) before touching the body.
- Dependencies come from `uv.lock`; `make audit` (pip-audit), Dependabot and SHA-pinned GitHub Actions keep them
  current. A new dependency needs a stated reason and an ADR when it adds plumbing (see [tech-stack](../tech-stack.md)).

## 6. Severity
**blocker** (breaks tenant isolation, send isolation, auth, secrets or injection safety; fails the gate) ·
**should-fix** (weakens a control or leaves a realistic abuse path; fix before merge unless the owner accepts it) ·
**nit** (hardening or clarity).

## Known gaps (2026-11-08; remove an item when it is fixed)
- **Legacy SPA routers have no auth dependency.** A grep for auth dependencies finds them only in `app/api/v1` and
  `app/api/auth`; the routers behind `agent`, `calendar`, `dashboard`, `inbox`, `maintenance`, `properties`, `tenants`
  and `contacts` declare none, and `agent/routes.py` (3), `calendar/routes.py`, `auth/login_routes.py` and
  `auth/google_routes.py` resolve the "default company" with `select(Company).limit(1)`. Fine while one owner runs one
  company behind a private network; a blocker before a second tenant or a public deployment. Tracked by slice 1b of the
  [Jarvis spec](../superpowers/specs/2026-11-06-super-agent-jarvis-design.md) for the Super Agent route; the others need
  the same principal dependency. Run `estateos-security` on `app/api` for the full list.
