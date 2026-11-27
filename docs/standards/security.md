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
- Nothing AI-drafted reaches a tenant, contractor or third party without Harjot's approve click (invariant 5); text he
  types himself in Chats is his own click (ADR 0013, next bullet). Only `app/sender/`
  imports send settings or outbound adapters; the sender re-checks approval status, `draft_version`, company pause,
  `outbound_mode`, the recipient (from the DB) and `sends.idempotency_key`.
- A second send class exists since ADR 0013: an **owner-typed WhatsApp message** from the Chats page (his own click on
  text he typed). It needs no approval row, so its safety is the recipient and the gates, all in
  `app/sender/owner_chat.py`: recipient from the stored row's `thread_ref` (never a request or payload value), the
  number must have written to this company, must not be an owner or company number, `outbound_mode=send`, company not
  paused, 23 h window, own hourly caps (`owner_chat_sends_per_hour` per company, `owner_chat_sends_per_number_per_hour`
  per contact), claimed `sends` key `chat:{company_id}:{client_msg_id}` (`client_msg_id` is a short `[A-Za-z0-9_-]`
  token, unique per company through a partial index on `messages`), and a failed or ambiguous provider call is never
  retried automatically. A send whose worker died mid-call is settled as failed by the 5-minute stuck sweep
  (`app.sender.stuck`) once it is older than `STUCK_AFTER`, so a bubble never stays "sending" for ever. The API must
  verify the chat key belongs to the session's company before it stores the row; the sender re-checks it anyway.
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
- M13 lane B (2026-11-26, needs a decision): a mailbox purge deletes the actions, approvals and revisions of replies
  that were already sent; `sends` stay with `action_id` NULL, so what Harjot approved, and when, is then only in the
  RDS snapshot taken before the purge. Keep that snapshot, or archive sent actions' approvals first (a migration).
- M13 lane B (2026-11-26, open): `understandings.research` (migration 0060) holds questions and answers taken from a
  person's mail, and `erase_person` clears neither it nor `attachments.extracted_text`.
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

Closed on 2026-11-12:
- the SPA shows one fixed banner while the API is unreachable or answering 5xx (`ApiHealthBanner`, fed by every
  `apiFetch`), instead of quietly showing empty fallbacks
- the owner's maintenance ticket edits are persisted (`ticket_edits`, migration 0043, merged over the live ticket)
  with a `case_events` audit row; the PATCH and history routes no longer keep anything in process memory, and an
  unknown ticket is a 404, never an invented row. The contractor's identity (name, email, phone) is never persisted
  as an edit — the dashboard can only name the recipient the dispatch actually goes to — request fields are
  length-capped, and `erase_person` deletes the `ticket_edits` of the erased person's cases
- translation now runs both ways (ADR 0011 amendment): the en→nl model is pinned and SHA-256 checked like the nl→en
  one, the cache is unique per (company, source hash, target), and `erase_person` also drops the company's en→nl rows
  because their Dutch output may be a message sent to the erased person

Closed on 2026-11-26 (M13):
- `erase_person` blanks the model-call log too (`pipeline/gdpr_calls.py`): input, output and error of every call
  tagged with one of the person's messages (`model_calls.message_ids`, migration 0057; set by triage, link check,
  case summary, person memory and the proposer), and of untagged calls whose text holds one of the person's
  addresses or numbers, their full name, or a line of one of their messages. Before M13 every prompt, now a whole
  dossier, stayed in `model_calls.input` after erasure. Limits: a one-word name and lines under 24 characters are not
  searched (they match strangers); outbound mail to the person is not counted as theirs, as in the message redaction.
  Tagged calls are judged by their tags only; sign-off and footer lines are never search terms; other people's person
  memory that names the erased person is cleared and rebuilt on its next refresh.
- Dossier and person memory (M13 review): an allowlist decides what reaches a draft. Own words always; anything sent
  to the person or an allowed person; the case's other mail only for its main person or a directory contractor,
  never mail involving another tenant. Harjot's forwarded copies count only where the forwarded header names an
  allowed addressee. A contractor sees the tenant's photos, never their papers. Inbound authors are the directory
  name or the address, never a header display name; a message's own line breaks render as `    | `, so text cannot
  forge a "Harjot (sent)" line. Person memory (`person_memory/v2`) takes commitments only from Harjot's sent mail;
  quoted or copied promises are marked "(unverified)". The quote splitter's patterns are bounded and scan at most
  50,000 characters. A reply is never addressed to Harjot's own copy (`sender/recipient.latest_inbound`).
- BRIXX documents in the library (M13, ADR 0017 §17): only the newest stored version is read; identity, income, bank
  and health papers (by BRIXX label or title) and text that reads like an identity document are never read; a
  document of a relatie erased under GDPR is never read; links follow BRIXX's own links (relatie, contract and its
  lease parties, unit, building), so a tenant's dossier sees their own papers and contract through the existing case
  scope and never another tenant's; `erase_person` deletes the person's BRIXX library documents. Scans are not read
  (no OCR on this path).
- Accepted (M13): a forged `From: <owner address>` mail linked to a case shows in that case's dossier as "Harjot (copy
  in the mailbox, not verified)"; it can never approve, send or become a stored commitment. `POST
  /api/v1/documents/{document_id}/reference` (T12) is the sole writer of `documents.is_reference`, gated by an admin
  profile (`require_admin`), CSRF header, decision rate limit, and company-scoped 404 — ingestion, filing and model
  output can never promote a document into the reference library. Every dossier reads the library, so a document
  linked to a person, unit, lease or case, or an `id_document`/`correspondence`, is refused with 409
  (`document_links.set_reference`; `test_a_tenants_own_papers_never_become_reference_documents`).

- Reload, ID purge and Category Desk (M13 lane B): `mail_purge` and `mail_reload_cli` log record counts only
  (`messages`, `cases`, `released`, `drafted`, `skipped`), never message bodies, sender names or email addresses; purge
  requires `--worker-stopped --confirm "purge <mailbox>"` (enforced by `scripts/mail_reload.sh` with a snapshot first).
  Identity documents are refused by name (`looks_like_id`) and by text (`looks_like_id_text`: a passport
  machine-readable line, a BSN, or a document word with an identity field) before any text is stored, so a passport
  sent as `IMG_2041.jpg` never reaches the dossier, person memory or search chunks; when filing classifies one later,
  `purge_text` blanks its text, the call that found it, every call tagged with its mail (OCR, proposer, memory) and the
  sender's memory. `GET /api/dashboard/categories` and `/{cat}` filter all queries by
  `company_id` and redact contact names (`safe_name`) and summaries for profiles lacking `inbox` or `money` sections.

- Search and Astra (M13 lane C review): message search, the reranker and Astra's tools only ever return rows of the
  caller's company and filters; the reranker sees the matching stretch of a chunk under that line's real
  `[time | sender | direction]` head, bodies cannot write a head, entries cannot forge or crowd out other entries, and
  reranker calls keep only sizes in `model_calls`. Astra opens and cites by short references the server handed out in
  that run (never ids or URLs from the model); opened mail and threads use the dossier's line rules, so a stranger's
  mail or a forged line never reads as "Harjot (sent)"; quoted or copied Harjot text is "not verified" and the
  research rules say it is a claim, never his word. The conversation reaches research only as a data block. Web pages
  come only from grounding metadata through the guarded page fetch, are data, and web queries are stripped of contact
  details. Dashboard research and chat answers are screened like a reply. Name resolution is company-scoped, marks an
  unknown sender "unverified sender" and ranks the directory first; the live v9 planner gets no names until v10 is
  pinned.

Still open (fix in this order):
- **Astra sources outlive erasure** (M13 lane C): each dashboard turn stores its sources in `agent_turns.results`, and a
  message source's label is "name, channel, date"; `erase_person` does not touch `agent_turns`, and turns have no
  retention purge. Fix: blank the labels (and answers that name the person) of turns citing one of their messages.
- **Reranker and web search calls are not tagged with message ids** (M13 lane C): erasure finds a rerank call only
  through its stored size (no text is kept) and a grounding call by text match of its model-written query.
- **Owner-typed inbox replies** (`POST /api/inbox/threads/{case_id}/reply`, from dev 6ac612c; no ADR yet; not accepted).
  Fixed on merge: Approve never falls back to it, held or refused drafts are not offered, it needs the suspicious
  confirmation, and it records only a quoted mail. **Keep send mode off until these are fixed:** no client idempotency
  key (a retry sends again) and an older pending draft stays approvable after a typed reply; the request names no
  recipient, so in send mode it goes to the case contact even when the card shows someone else. Also open: it calls
  `record_dispatch`, which writes "Contractor dispatch approved & dispatched" into the case summary for any reply and
  moves the case to waiting; its message says "queued for sending" in draft mode; a draft blocked by the shared-case
  guard is not reported to the owner in draft mode; the emergency fallback can drop a model's fourth action; dev edited
  the published `proposer/v4` (active) and `v5` prompts in place, which invariant 9 forbids.
- **The mail repair report holds personal data** (not yet accepted): names, addresses and possibly numbers go to the
  worker's CloudWatch log group, which `erase_person` cannot reach. Limit who reads it; its snapshot is a full copy of
  tenant data, to be deleted once the repair is accepted.
- **Email HTML view** (merged 2026-11-25). A sanitizer bypass through `<style>` content was fixed and stored HTML is
  cleaned again on read; the frame also allows no script. Still open: remote `https` images load on open (tracking);
  the owner sees the HTML part while the model reads `text/plain`, and a mismatch is not flagged; the hand-written
  sanitizer should be replaced by a maintained one (some `HTMLParser` versions are quadratic on hostile input). The
  frame keeps `allow-same-origin`: never add `allow-scripts` to it.
- **Shared cases after the forwarded-mail repair** (ADR 0016): drafts and sends are blocked when they answer someone
  other than the addressee, but a permitted draft can still draw on a case summary and waits built from every sender.
- **A sender chooses the name shown for their mail** (not yet accepted). The screen names each mail from its headers, so
  any outsider, with or without `Reply-To`, can appear as "Harjot Singh", a saved tenant or a contractor. The thread
  list, mobile header and quoted-reply line show only the name; each incoming bubble shows the address beside it.
  Invisible and direction characters are removed, names are cut at 80 characters, and search chunk lines strip their own
  delimiters and always carry the address. Fix: warn when a header name matches the team or a saved contact who does not
  hold that address. Related: `actions.payload.reply_to.sender` now stores a name or address, which `erase_person` does
  not scrub; message search results still label a hit with the saved name while its lines carry header names, and chunks
  indexed before this change keep their old names until rebuilt.
- **The email sender is taken from `Reply-To`** (ADR 0016), which SPF, DKIM and DMARC alignment do not authenticate.
  **Accepted on 2026-11-25** by the user who requested the change, who chose to keep it for all inbound mail after the
  effects below were put to them, with the advice to keep send mode off. An outside sender can name a tenant, a contractor or any third party in `Reply-To`:
  - before any approval, the mail joins that person's only open case, can close their awaited answer (cancelling the
    chasers), reopen the case and raise its urgency; its text enters the case summary and message search under their
    name, its attachments are queued for filing, and as a "contractor" it can be stored as that contractor's quote
  - an approved reply goes to the named address; in `outbound_mode=send` it passes the case-contact check and uses the
    outsider's subject and thread (fix this before relying on send mode). Rejecting a draft undoes none of the above
  - the dashboard shows the `Reply-To` name or address and never `meta.header_from`, so nothing marks the mismatch
  - a card that names a tenant this way also shows their directory label and, on a case with no flat, their real flat
  - the inbox's substring filter for automated mail (`noreply`, `alert`, `update` and others) tests only the new sender
  Fix: a server-side "unverified sender" flag when `Reply-To` replaced a `From` that is not a team address or a known
  identity of the same person, honoured by case waits and state, filing, quotes and the sender, and shown to the
  owner. Narrower alternative: honour `Reply-To` only from team addresses and known relays. Related: `erase_person`
  does not scrub `meta.from`, `from_name` or `header_from`.
- **Profiles limit sections, not actions** (ADR 0012). A member sees only the sections a superadmin switched on; every
  router is guarded per request and a test walks the OpenAPI document to keep it so. Anyone who holds a section that
  offers approve/send can approve and send; a profile with the `inbox` section (which the Chats page uses) can also type
  and send WhatsApp messages to contacts (ADR 0013); `reports`/`dashboard` profiles read the lists their pages summarise
  without message bodies, drafts, phone numbers or emails (the feed, calendar and attachments follow the same rule).
  The Super Agent (`/api/agent`, `/api/v1/agent`) answers from the whole portfolio, so it is refused (403, and its
  button is hidden) unless the profile opens every data section (`Access.can_use_agent`); scoping its tools per
  section would lift that. An address whitelisted in two companies cannot sign in (`ambiguous_account`): an admin who
  whitelists a stranger's address can lock that person out until the row is removed; add a company picker before a
  second company exists.
- **The owner's Google OAuth credentials** are one object for the whole installation, not per company
  (`channels/google_store.py`): with S3 storage, plaintext JSON at `credentials/google_owner.json` in the
  environment's (versioned, SSE-S3) media bucket, plus a 0600 local cache per process; otherwise the local file
  only. The shared copy holds the tokens but not the app's OAuth client secret (re-added from Settings into the local
  cache). Disconnect revokes the grant at Google (best effort, logged on failure), which voids the token versions the
  bucket keeps; it does not purge those versions. Any member with the `settings` section of any company can see,
  connect or disconnect it, and the calendar client takes no `company_id`, so this must become
  `credentials/{company_id}/...` before a second company exists. The task role that signs media links can also read
  the object (no path reaches it: every presigned key comes from `content_key`). The module does not log the account
  email, the file path or the token-exchange response body.
- **Calendar invites (RSVP) are an owner-click write outside `sender/`.** `POST /api/calendar/invites/{id}/respond`
  patches the owner's own RSVP with `sendUpdates=all`, so Google tells the organiser (a tenant or contractor). It is
  deliberate: an RSVP is that notice, it needs an owner click, and it is not a message the product composes, so
  `outbound_mode` and company pause do not gate it. Only a pending invite that matches the company's directory can be
  answered. A match is by organiser email (a known person; the address is shown beside the name) or by unit address in
  the location (whole address, 8+ characters, flagged "unknown sender" in the UI); a forged organiser or location can
  still make a stranger's invite appear, which is why the owner sees the sender's address and decides. Known gaps:
  the calendar client is the installation's one Google account (see the credentials note above), so with a second
  company this must be bound per company first; GET has no cache or rate limit beyond the global one.
- The "AI draft" options in contacts are fixed templates.
- **Rent is unknown.** Amounts and arrears are reported as 0 / `unknown` until the BRIXX rent mirror exists.
- v1 rate limits and the per-owner cap of 4 live event streams (`stream_slots.py`) are per process.
