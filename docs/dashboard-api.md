# Dashboard API (`/api/v1`)

For the SPA built elsewhere. Source of truth is the code in `app/api/v1/` and the OpenAPI snapshot
(`tests/unit/api/__snapshots__`); this guide adds what the schema does not say. Design:
[spec](superpowers/specs/2026-10-15-dashboard-super-agent-design.md), [ADR 0006](adr/0006-dashboard-owner-channel.md).
Status: unit-tested only. The integration tests, `make check`, `make smoke` and `make sim-demo` for this API have not
been run (Docker was unavailable); see [PROGRESS.md](PROGRESS.md).

## Auth

1. The SPA obtains a Google ID token (Google Identity Services) for the owner.
2. `POST /api/v1/auth/session` with `{"id_token": "..."}` and the header `X-EstateOS-Client: dashboard`.
   Success: `200 {"email", "company_id"}` and a `Set-Cookie: eo_session=...` (httpOnly, `SameSite=Strict`, `Secure`
   outside dev/test, lifetime `DASHBOARD_SESSION_TTL_MIN`, default 480 min).
3. Every later call sends the cookie (`credentials: "include"`). The company always comes from the cookie, never from
   the request.
4. Every write (POST, DELETE), **including login**, must carry `X-EstateOS-Client: dashboard`, else `403`.
5. `DELETE /api/v1/auth/session` clears the cookie (`204`). `GET /api/v1/me` returns `{email, company_id, owner_id}`.

6. Every authenticated request also re-reads the owner row: if the owner was removed or his email changed, the next
   call is `401` (the cookie alone does not keep a session alive).

### Deployment: same origin (CORS)

Serve the SPA from the **same origin** as the API, behind the reverse proxy (for example `https://app.example.com/`
for the SPA and `https://app.example.com/api/v1/...` proxied to the API). The cookie is `SameSite=Strict`, and the
`X-EstateOS-Client` header makes every write a non-simple request that a browser preflights, so a cross-origin SPA
does not work by default. Only if the SPA must live on another origin, set `DASHBOARD_CORS_ORIGINS` to its exact
origins, comma-separated (`https://dash.example.com,https://staging.example.com`); `*` is refused at startup. The API
then answers preflights for those origins with credentials allowed, methods GET/POST/DELETE and the headers
`X-EstateOS-Client` and `Content-Type`. Empty (the default) adds no CORS headers at all. Because the cookie is
`SameSite=Strict`, a cross-origin SPA must still be on the same site (for example `dash.example.com` calling
`api.example.com`); a different registrable domain is not supported. Prefer same-origin.

Login errors: `401 invalid id token`, `403 not an owner account` (also when the email matches several companies),
`503 identity provider unavailable` (retry), `429 rate_limited`. In dev, `DASHBOARD_AUTH_PROVIDER=fake` accepts the
token `test-owner-token` for `owner@example.test`; prod refuses the fake provider.

## Errors

| Status | Body | Meaning |
|---|---|---|
| 401 | `{"detail":"not authenticated"}` | missing, invalid or expired cookie: log in again |
| 403 | `{"detail":"missing client header"}` | write without `X-EstateOS-Client: dashboard` |
| 404 | `{"detail":"not found"}` | missing **or another company's** id (indistinguishable on purpose) |
| 409 | `{"detail":"confirm_suspicious_required"}` / `"approval_not_editable"` | see the routes below |
| 422 | FastAPI validation body, or `{"detail":"invalid cursor"}` | bad input, `limit` above 100, bad cursor |
| 429 | `{"detail":"rate_limited"}` + `Retry-After: <seconds>` | see Limits |
| 503 | `{"detail":"could not start the assistant; try again"}` (agent) or `identity provider unavailable` (login) | retry |

429 is not declared in the OpenAPI schema.

## Limits

- `limit` on list routes: 1 to 100; above 100 is `422` (not clamped). `GET /feed` takes `limit >= 1` and clamps to 100.
- Cursor paging: `before` (inbox) / `after` (feed, approvals, documents/review) take the `cursor` string of the last
  item you have; a malformed cursor is `422`.
- Rate limits (in-process token buckets, per API worker; limits reset on restart):

| Routes | Limit | Key |
|---|---|---|
| `POST /agent/messages` | 30 / min | owner |
| `POST /auth/session` | 10 / min | client IP (`X-Forwarded-For` ignored unless `DASHBOARD_TRUST_FORWARDED_FOR=true`; a request without a client address shares one `unknown` bucket) |
| approvals decide/edit, tasks done/snooze, documents file, company pause/resume | 120 / min | owner |

Behind a reverse proxy, without `DASHBOARD_TRUST_FORWARDED_FOR` every login shares the proxy's IP bucket (10/min for
all users together). Enable the flag only when the proxy overwrites `X-Forwarded-For` (the last entry is used), never when
the API is reachable directly. GETs and the SSE stream are not limited. On `429` wait `Retry-After` seconds.
- Agent text: 1 to the question limit (over it: `422` with a "too long" message); `\n`, `\t` and `\r\n` allowed; NUL and
  other control characters and whitespace-only text are `422`.

## Routes

Read (GET, cookie only):

| Route | Response |
|---|---|
| `/me` | `{email, company_id, owner_id}` |
| `/feed?after=&limit=` | `FeedItem[]` oldest first: `{id, kind, ref_id, payload, created_at, seen_at, resolved_at}`; kinds `approval`, `document_review`, `alert`, `briefing`, `task`, `agent_note`. `ref_id` is the approval id (`approval`) or the attachment id (`document_review`), else null. Approved contractor requests, escalations, owner notes and draft-mode WhatsApp replies arrive as `alert` items with the copy-ready text |
| `/events` | SSE, see below |
| `/inbox?before=&limit=` | `InboxItem[]`, newest thread first: `{thread_key, cursor, channel, last_at, last_text, sender, person_name, case_id, unread_pipeline, message_count}` |
| `/threads/{thread_key}` | `ThreadMessage[]`: `{id, direction, sent_at, sender, text, delivery_status, pipeline_status, suspicious, suspicious_reason, attachments[{id, filename, mime_type, size_bytes, url}]}`; `404` for a bad key or empty thread. Attachment `url` is a short-lived presigned link |
| `/cases?state=&limit=` | `CaseSummary[]`: `{id, state, category, urgency, summary, opened_at, resolved_at}` |
| `/cases/{case_id}` | `CaseSummary` + `timeline[]`, `message_ids[]`, `actions[{id, type, status, draft_version, rationale, payload, approval}]` |
| `/activity?limit=` | `{kind: case_event\|send\|outcome, id, at, case_id, action_id, label}[]` |
| `/approvals?after=&limit=` | pending approvals: `{id, cursor, action_id, action_type, case_id, case_label, drafts[], draft_version, suspicious, created_at}` |
| `/documents/review?after=&limit=` | documents waiting for a filing choice: `{attachment_id, cursor, filename, mime_type, case_id, suggested_type, created_at}` |
| `/documents?q=&match=all\|any&type=&status=&person_id=&unit_id=&lease_id=&case_id=&date_from=&date_to=&needs_link=&limit=` | document library (M10): `{id, attachment_id, title, doc_type, status, document_date, summary, snippet, rank, drive_url, suspicious, created_at}[]`. With `q`: full-text over what the documents say (Dutch stemming) plus title/summary/file name; `match=any` takes any word, for a question. `snippet` marks hits with `«…»` and is untrusted document text. Without `q`: newest first. `needs_link=true`: documents naming people or addresses that could not be placed |
| `/documents/{id}` | `DocumentOut` + `{file_name, facts{parties, unit_hint, start_date, end_date, key_facts[{label, value}]}, unresolved[], links[{kind: person\|unit\|lease\|case, ref_id, label, method}], chunk_count}`; `404` for foreign or unknown ids |
| `/documents/reorg` | the newest Drive reorganisation plan or `null`: `{id, status: proposed\|approved\|applied\|rejected, created_by: owner\|system, created_at, items[{id, document_id, title, from_folder, to_folder, from_name, to_name, reason, status: proposed\|approved\|moved\|rejected\|failed}]}` |
| `/tasks`, `/waits` | open tasks `{id, ref, title, assignee, due_at, priority, status, case_id}`; open waits `{id, case_id, about, expected_by, chase_count, last_chased_at}` |
| `/briefing` | `{kind, day_label, urgent[], approvals[], overdue_tasks[], overdue_waits[], exceptions[], stats}` |
| `/company` | `{name, paused, outbound_mode, timezone}` |
| `/agent/conversations/{id}` | `{id, turns[{id, text, status, plan, results, answer, created_at, updated_at}]}`; `404` if not yours |

Writes (POST, need the CSRF header; the decision writes share the 120/min limit):

| Route | Body | Success | Errors |
|---|---|---|---|
| `/approvals/{id}/decide` | `{choice: ok\|d1\|d2\|d3\|rej, confirm_suspicious?: bool}` | `200 {kind: execute\|rejected\|stale, stale, action_id, draft_version, variant}` | `422` for `choice=edit` (use `/edit`); `404`; `409 confirm_suspicious_required` when the source message was flagged suspicious: ask the owner, resend with `confirm_suspicious: true` |
| `/approvals/{id}/edit` | `{text}` (1 to 4000) | `200 {action_id, draft_version, approval_id}`: a new revision and a new approval card in the feed | `404`; `409 approval_not_editable` |
| `/tasks/{ref}/done` | none; `ref` is the 6 to 36 char short id | `204` (repeating it is also `204`) | `404`, `422` bad ref |
| `/tasks/{ref}/snooze` | `{duration}` like `30m`, `4h`, `2d`, `1w` (1 min to 8 weeks) | `204` | `404`, `422` |
| `/documents/{attachment_id}/file` | `{choice}`, one of the document choices below | `202` (filing runs in the background) | `404`, `422 unknown document choice` |
| `/documents/{id}/links` | `{kind: person\|unit\|lease\|case, ref_id}`: the owner confirms or adds a link (`method: owner`) | `204` | `404` (foreign document or target) |
| `DELETE /documents/{id}/links/{kind}/{ref_id}` | none: hides a link and stops automation from re-adding it | `204` | `404` |

Changing a document link may propose a one-item reorganisation plan (`created_by: system`). Nothing in Drive moves until a plan is approved.
| `/documents/reorg` | none: compares filed documents with layout v2 and records the differences | `200 {plan_id}`; `plan_id` is null when nothing differs or everything is already planned | none |
| `/documents/reorg/{plan_id}/decide` | `{approve, item_ids?}`: all items, only these (the rest are rejected), or none | `202 {status}`; an approved plan is applied in the background (`drive:reorg:{plan_id}`); a repeat keeps the first decision | `404` |
| `/company/pause`, `/company/resume` | none | `200 {paused}` | none; resume also re-runs approved but unexecuted actions |
| `/agent/messages` | `{text, conversation_id?}` | `202 {conversation_id, turn_id}`; answer arrives via SSE or by polling the conversation | `404` for a foreign conversation; `503` if the turn could not be started (it is marked failed; send the message again) |
| `/auth/session` | `{id_token}` | see Auth | see Auth |

Document choices (`DOC_CHOICES`): `lease`, `invoice`, `quote`, `id_document`, `insurance`, `certificate`, `correspondence`, `photo`, `other`, `skip`.

A decision on an old draft version returns `kind: "stale"` (nothing is sent): refetch `/approvals`.

### thread_key

Opaque. It is the URL-safe base64 (no padding) of `{channel}:{ref}`. Always take it from `/inbox`; never build it.
Pass it unchanged in the path.

## SSE: `GET /api/v1/events`

- Use `EventSource` with credentials (or `fetch` streaming). Frames:
  - `event: feed`, `id: <cursor>`, `data: <FeedItem JSON>`.
  - `event: turn`, `data: {id, conversation_id, status, answer, updated_at}`: the current state of one of your agent
    turns. Turn frames carry no `id:` line, so they do not move `Last-Event-ID`.
  - `event: ping` every 15 s of silence (keep-alive, ignore).
  - `event: error` once, then the stream ends: reconnect.
- The stream ends by itself after 15 minutes: reconnect (the cookie is checked again; a `401` means log in).
  There is no "reconnect now" frame.
- Resume: the browser sends `Last-Event-ID` automatically on reconnect and the stream continues right after that
  cursor. Without a valid one the stream starts 5 seconds before "now" to cover rows committed slightly late.
- Because of that lag and late commits, after every (re)connect call `GET /feed` once and **dedupe by `FeedItem.id`**
  (frames can repeat). A row that commits more than about 2 seconds after a later row can still be missed until the
  next reconnect or refetch.
- If a turn you started is still `pending` or `running` after about 30 s, call `GET /agent/conversations/{id}` and
  use that (Postgres is the truth; SSE only nudges).
- `plan`, `results` and `answer` can quote tenant text. Render them as **plain text, never HTML or markdown**.

## What approving does: `outbound_mode`

Per company (`GET /company`), default `draft`.

- `draft`: an approved reply becomes a Gmail draft (Gmail threads) or an owner-only message. Nothing reaches the
  tenant. The approval still completes.
- `send`: approving sends the reply to the tenant on the channel the tenant wrote on: a Gmail reply in the same thread,
  or a WhatsApp text. The recipient is taken from the database (the case's own contact), never from the request.
  Sending is re-checked at execution: approval status and draft version, company not paused, mode still `send`, the
  recipient, and an idempotency key (a repeated click never double-sends).

`decide` returns as soon as the approval is stored; the send happens in the background. Read the outcome from
`/activity` (`send` items), the case `actions`, or an `alert` feed item.

### Blocked sends (alert items in the feed)

The approval stays valid and nothing is sent. The alert text is `Reply not sent to the tenant: <reason>.`, or
`Reply may not have reached the tenant: <reason>.` when the provider may have accepted it. One alert per action
version, whatever path (decide, resume, retry) ran it. Reasons the SPA will see:

- `WhatsApp window closed: the tenant wrote more than 23 h ago; reply by email or wait` (window measured from the
  tenant's last inbound message).
- `hourly tenant send cap reached` (`TENANT_SENDS_PER_HOUR`, default 30 per company; drafts count too, see
  [go-live-channels.md](go-live-channels.md)).
- `Gmail sending is not configured: GMAIL_REPLY_SEND_CREDENTIALS_FILE (gmail.send) is missing`.
- `delivery status unknown: previous attempt never reported; check the thread before resending it yourself`: an
  attempt started more than 30 minutes ago and never finished (the worker died mid-call). The send and the action are
  marked failed once; `resume` will not run it again. The 5-minute sweep settles such a row even when no attempt
  re-runs it (a worker died mid-call), with the same single alert. There is no dashboard action to mark it sent (the
  owner checks the thread and resends by hand if needed). A send still in flight (under 30 minutes) produces no alert.
- `delivery status unknown: a previous attempt did not finish; ...` or `may have been delivered: ...`: the provider
  call failed in a way that may still have delivered the message.
- Others: company paused, mode back on `draft`, the recipient is no longer the case's own contact, the draft was
  edited after approval, body over WhatsApp's 4096 characters.

### Lost enqueues (commit-then-crash sweep)

Writes commit first and enqueue the background work second. If the API dies in between, the worker's
`sweep.stranded` cron (every 5 minutes) picks the work up: approved actions decided 5 minutes to 24 hours ago that are
still `approved` with no send recorded (company not paused; a paused company's actions wait for Resume), and agent
turns still `pending` after 5 minutes (up to 24 hours). They are enqueued under the same ids the API uses
(`exec:{action_id}:{draft_version}`, `concierge:{turn_id}`), so nothing runs twice; at most 200 per round (up to 1000
candidates are read and checked against DBOS first, so actions whose run already exists, such as blocked ones, cannot
crowd out newer stranded work). For the SPA this means a decision or an agent message can take up to about 5 minutes
longer after a crash, never that it is lost.

**Limit: anything stranded longer than 24 hours is not swept.** An approval decided, or a turn created, more than a day
before the worker came back stays as it is (`approved` / `pending`). That needs an operator: confirm DBOS has no run under its
workflow id (`make workflows`), decide whether it should still run, and if so enqueue it under that same id.

The same cron settles tenant sends stuck `sending` for 30 minutes or more (see the reasons above): one alert, the
send and the action failed, never re-sent. Paused companies are included (settling sends nothing).

## Running the simulator scenario

`make sim-demo` ends with a `dashboard` scenario that logs in through this API with the fake token, so the api
container needs `DASHBOARD_SESSION_SECRET` (at least 32 characters) and `DASHBOARD_AUTH_PROVIDER=fake`. `docker/compose.yml`
forwards both with a dev-only default secret. Without a secret the scenario is skipped with a
`sim.demo.dashboard_skipped` log line and the final line reads `dashboard=skipped`. It refuses to run unless the
WhatsApp, Gmail and Drive providers are all fake. While it runs the dev company is in `outbound_mode=send` and the dev
owner on the dashboard channel with email `owner@example.test`; both are restored afterwards, also on failure.
Not yet run: Docker was unavailable.
