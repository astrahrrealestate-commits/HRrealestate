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

## Known gaps (2026-11-09; remove an item when it is fixed)
Closed on 2026-11-09 after an audit of `app/api` (regression guard: `tests/unit/api/test_route_auth_guard.py`, which fails
the build when a route answers an anonymous caller without being listed as public):
- every dashboard router (`agent`, `calendar`, `contacts`, `dashboard`, `inbox`, `maintenance`, `properties`, `tenants`)
  requires a session, and state-changing calls also the client header; their queries filter by `principal.company_id`
  and (for conversations) the owner; cross-company isolation is tested per router against a real database
- approving or deciding something names what it decides: no "latest case" guess, no id-prefix scan, 404 when nothing
  of the caller's matches (it used to report an authorization)
- the Gmail connect flow is bound to the owner by a signed `state`; the owner login binds its `state` to the browser,
  requires a verified email, enters the company of the whitelist row, and never rewrites another owner
- attachments are scoped, and only pdf and common images render inline (nosniff always)
- the contacts "send" routes no longer record sends that never happened; properties, tenants, the dashboard pulse and
  briefing, and contact facts come from the database instead of fabricated demo values
- the Super Agent, inbox sync, translate and the approve/decide routes are rate limited per owner (`api/v1/session_limits.py`);
- local translation (ADR 0011): `POST /api/inbox/translate` is session + client-header guarded and limited to 30/min per
  owner; work per request is bounded (20000 characters accepted, 8000 translated, at most 80 sentences, batches of 32);
  the model files are pinned to a commit and SHA-256 checked at build; translations are tenant-scoped, display-only,
  and deleted by `erase_person` together with the messages they copy
- calendar approve is idempotent; the dev bypass needs `env=dev` and the fake identity provider; production refuses
  localhost and plain-http public URLs and the fake Google Chat verifier

Still open (fix in this order):
- **Role is not enforced.** `allowed_users.role` is stored, but every whitelisted person can approve and send as an
  owner. Decide which roles may approve before inviting anyone who is not the owner.
- **The owner's Google OAuth credentials** live in one plaintext file for the whole installation
  (`channels/google_auth.py`), not per company, and that module logs the account email and the file path.
- **The SPA falls back to bundled mock data** (`frontend/src/data/mockData`) when an API call fails, so an outage or a
  401 looks like an empty or demo dashboard instead of an error.
- **Demo defaults remain in the maintenance list and approve context** (a default contractor and phone number), and the
  owner's ticket edits are kept in memory per company rather than as case events. The "AI draft" options in contacts
  are fixed templates.
- **Rent is unknown.** Amounts and arrears are reported as 0 / `unknown` until the BRIXX rent mirror exists.
- The SSE endpoint has no per-owner connection cap, and v1 rate limits are per process.
