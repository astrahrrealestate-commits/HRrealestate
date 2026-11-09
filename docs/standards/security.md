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
Closed on 2026-11-09 (audit of `app/api`, regression guard `tests/unit/api/test_route_auth_guard.py`): every dashboard
router (`agent`, `calendar`, `contacts`, `dashboard`, `inbox`, `maintenance`, `properties`, `tenants`) now depends on
`require_session` (session cookie, plus the client header on state-changing methods); the Gmail connect flow is bound to
the owner by a signed, expiring `state`; the dev bypass needs `env=dev` **and** the fake identity provider; production
refuses `localhost` or plain-http public URLs. The guard test fails the build if any route answers an anonymous caller
without being listed as public.

Still open (each is a finding of the audit; fix in this order):
- **Handlers still read across companies.** The routers above authenticate, but `dashboard`, `inbox`, `maintenance`,
  `contacts` and `calendar` queries do not yet filter by `principal.company_id`, and `agent/routes.py` still resolves
  the company with `select(Company).limit(1)`. Harmless with one company; a blocker before a second tenant. Includes
  `inbox/decide.py` resolving "latest" across all companies and `maintenance._find_case` matching an id *prefix*.
- **Owner login can take over another owner.** `auth/login_routes.py` ignores `AllowedUser.company_id`, takes the first
  company's first owner and rewrites that owner's email; it also never verifies its OAuth `state` or `email_verified`.
- **Google Chat webhook** accepts unsigned tokens while `google_chat_provider=fake` (the default) and production does not
  refuse that setting.
- **Attachments** are served `inline` with the stored mime type (stored XSS on the API origin) and without a company
  check; the filename is not escaped in the header.
- **Fake data and fake sends.** `properties` and `tenants` return hard-coded demo records (including lockbox PINs);
  `contacts` "send" routes write `Send(status=sent)` rows for messages that were never sent (invariant 5).
- **Calendar approve** pushes events (with attendee emails) to the owner's Google Calendar without being idempotent or
  going through `app/sender/`.
- **Personal data in logs:** login and Google flows log email addresses and OAuth response text.
- The owner's Google OAuth credentials live in one plaintext file for the whole installation, not per company.
