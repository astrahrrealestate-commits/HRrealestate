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
| `PUT /agent/page` | 60 / min | owner (its own bucket: pre-warms never use up the message limit) |
| `POST /auth/session` | 10 / min | client IP (`X-Forwarded-For` ignored unless `DASHBOARD_TRUST_FORWARDED_FOR=true`; a request without a client address shares one `unknown` bucket) |
| approvals decide/edit, tasks done/snooze, documents file, finance recheck / rate put / rate delete, company pause/resume | 120 / min | owner |

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
| `/feed?after=&limit=` | `FeedItem[]` oldest first: `{id, kind, ref_id, payload, created_at, seen_at, resolved_at}`; kinds `approval`, `document_review`, `alert`, `briefing`, `task`, `agent_note`, `quote_review`, `dd_report` (a finished due diligence screening: `ref_id` is the review id, payload `{review_id, title, verdict: clear_to_review\|needs_documents\|red_flags, coverage{present, applicable}, counts{mismatches, high_risks, risks}, missing[]}`). `ref_id` is the approval id (`approval`), the attachment id (`document_review`) the quote id (`quote_review`) or the review id (`dd_report`), else null. Approved contractor requests, escalations, owner notes and draft-mode WhatsApp replies arrive as `alert` items with the copy-ready text |
| `/events` | SSE, see below |
| `/inbox?before=&limit=` | `InboxItem[]`, newest thread first: `{thread_key, cursor, channel, last_at, last_text, sender, person_name, case_id, unread_pipeline, message_count}` |
| `/threads/{thread_key}` | `ThreadMessage[]`: `{id, direction, sent_at, sender, text, delivery_status, pipeline_status, suspicious, suspicious_reason, attachments[{id, filename, mime_type, size_bytes, url}]}`; `404` for a bad key or empty thread. Attachment `url` is a short-lived presigned link |
| `/cases?state=&limit=` | `CaseSummary[]`: `{id, state, category, urgency, summary, opened_at, resolved_at}` |
| `/cases/{case_id}` | `CaseSummary` + `timeline[]`, `message_ids[]`, `actions[{id, type, status, draft_version, rationale, payload, approval}]` |
| `/activity?limit=` | `{kind: case_event\|send\|outcome, id, at, case_id, action_id, label}[]` |
| `/approvals?after=&limit=` | pending approvals: `{id, cursor, action_id, action_type, case_id, case_label, drafts[], draft_version, suspicious, created_at}` |
| `/documents/review?after=&limit=` | documents waiting for a filing choice: `{attachment_id, cursor, filename, mime_type, case_id, suggested_type, created_at}` |
| `/documents?q=&mode=hybrid\|words&match=all\|any&type=&status=&person_id=&unit_id=&lease_id=&case_id=&date_from=&date_to=&needs_link=&limit=` | document library (M10): `{id, attachment_id, title, doc_type, status, document_date, summary, snippet, rank, drive_url, suspicious, created_at}[]`. With `q` (`mode=hybrid`, the default): words and meaning together (Dutch stemming, Dutch/English term list, vectors), so an English question finds a Dutch clause; documents ranked by their best passage, with `«…»` around matching words when the words side matched. `mode=words`: full-text only plus title/summary/file name; `match=any` takes any word, for a question (`match` is ignored in hybrid mode). `snippet` marks hits with `«…»` and is untrusted document text. Without `q`: newest first. `needs_link=true`: documents naming people or addresses that could not be placed |
| `/documents/{id}` | `DocumentOut` + `{file_name, facts{parties, unit_hint, start_date, end_date, key_facts[{label, value}]}, unresolved[], links[{kind: person\|unit\|lease\|case, ref_id, label, method}], chunk_count}`; `404` for foreign or unknown ids |
| `/documents/reorg` | the newest Drive reorganisation plan or `null`: `{id, status: proposed\|approved\|applied\|rejected, created_by: owner\|system, created_at, items[{id, document_id, title, from_folder, to_folder, from_name, to_name, reason, status: proposed\|approved\|moved\|rejected\|failed}]}` |
| `/diligence/reviews?limit=` | `ReviewOut[]` newest first: `{id, title, property_kind: apartment\|house\|tenanted_investment, unit_id, status: pending\|running\|done\|failed, run_no, verdict, framework_version, error, document_ids[], created_at, completed_at}` |
| `/diligence/reviews/{id}` | `ReviewOut` + `report` (null until `status` is `done`): `{framework_version, property_kind, as_of, verdict, coverage{present, applicable}, checklist[{key, label, severity: critical\|important\|nice, status: present\|missing\|stale\|unclear, why, document_ids[], note}], mismatches[{field, kind: marketing_vs_legal\|inconsistent, severity: low\|medium\|high, reference{document_id, title, doc_kind, value, quote}, other{...}, difference}], risks[{code, severity, summary, document_ids[], source: rule\|document, quote}], documents[{document_id, title, doc_kind, readable, claims}], unverified_claims, disclaimer}`. Links, e-mail addresses and IBANs are stripped from document-derived text; `404` if not yours |
| `/tasks`, `/waits` | open tasks `{id, ref, title, assignee, due_at, priority, status, case_id}`; open waits `{id, case_id, about, expected_by, chase_count, last_chased_at}` |
| `/briefing` | `{kind, day_label, urgent[], approvals[], overdue_tasks[], overdue_waits[], exceptions[], stats}` |
| `/company` | `{name, paused, outbound_mode, timezone}` |
| `/finance/quotes?case_id=&person_id=&cursor=&limit=` | quote checker (M11), newest first, `limit` 1 to 100: `{id, cursor, case_id, vendor{id, name}\|null, quote_date, work_date, currency, total, status: received\|reviewed\|unlinked, latest{review_id, verdict, late_days, late_flag, overcharge_total, low_confidence, snapshot_basis}\|null, created_at}[]`. `cursor` on an item is the value to send as `cursor` for the next page (empty page = end); a malformed cursor is `422`. Money (`total`, `overcharge_total`) is a decimal string. `vendor` is null while no contractor is linked |
| `/finance/quotes/{id}` | the list item + `{lines[{position, description, item_key, quantity, unit, unit_price, amount, vat_included}], report, history[{id, verdict, created_at}]}`. `report` is the latest review exactly as stored (the `quote_review` feed payload, below), null before the first review; `history` is newest first; `404` for foreign or unknown ids |
| `/finance/rates?person_id=&limit=` | the company's agreed rates (closed ones too), by contractor and item: `{id, person_id, item_key, description, unit, amount, currency, valid_from, valid_to, source: owner\|document\|quote, created_at}[]`, `limit` 1 to 500 (default 200) |
| `/brixx/status` | BRIXX mirror sync health, read from the sync state tables only (BRIXX is never called on a request): `{last_run{id, kind: incremental\|reconcile, status: running\|succeeded\|failed, started_at, finished_at, error}\|null, tables[{name, row_count, last_success_at, lag_seconds, drifted, last_error}], total_rows, stale}`. `last_run` is the newest run in any status. `stale` is true when no run succeeded within 3 x `brixx_sync_interval_minutes` (default 15, so 45 minutes) or none ever did. Tables are sorted by name; `row_count` (and `total_rows`, their sum) counts the rows written by each table's latest run, so an incremental run shows only changed rows, not the mirror size. `last_success_at`: every BRIXX change before it is mirrored (the start of the run that last completed the table; while a newer run is mid-table or the last attempt failed, the newest change applied); null before the first complete pass, and for tables without `UPDDATETIME` also while a run is mid-table or failing. `lag_seconds` is the age of `last_success_at`. `drifted`: BRIXX has columns the mirror lacks (their values are kept in `_extra`). `last_error` and `error` hold error class, table and page only (for example `BrixxAuthError table=PRG_RELATIE page=3`) |
| `/agent/conversations/{id}` | `{id, turns[{id, text, status, plan, results, answer, created_at, updated_at, timings}]}`; `404` if not yours. `timings`: see [Turn timings](#turn-timings) |

Writes (POST unless another method is shown, need the CSRF header; the decision writes share the 120/min limit):

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
| `/diligence/reviews` | `{title, property_kind, document_ids[1..200], unit_id?}`: screen these library documents against the checklist (at most `dd_max_documents`, default 30) | `202 {id, run_no}`; the row is saved first, then `dd:{id}:{run_no}` is queued; poll the review, or wait for the `dd_report` feed item | `404` (foreign or unknown document or unit), `422` (empty or too many) |
| `/diligence/reviews/{id}/rerun` | `{document_ids?}`: screen again, optionally with a different document set; documents already read are not read again | `202 {id, run_no}`; allowed in any state (an in-flight run becomes stale), clears the previous report | `404`, `422` |
| `/finance/quotes/{id}/recheck` | none: review the stored quote again with fresh prices | `202 {quote_id, n}`; the review and a new `quote_review` card arrive in the feed. `n` is the number of reviews stored so far and is part of the workflow id (`fin:recheck:{quote_id}:{n}`), so clicking again before the worker finishes is the same run | `404`; `409 quote_not_linked` (no contractor linked yet) |
| `PUT /finance/rates` | `{person_id, description, unit, amount, currency?, item_key?, valid_from?, valid_to?}`: `person_id` must be a contractor of your company; `amount` > 0 with at most 2 decimals; `currency` only `EUR` (default); `valid_from` defaults to today in the company timezone, `valid_to` must not be before it. `item_key` is used when it is lowercase letters, digits and `_` (at most 100), else derived from `description`; `unit` is stored normalised (`uur` becomes `hour`) | `200` the stored rate (`source: owner`). One row per (contractor, `item_key`, `valid_from`): setting it again updates that row | `404` (foreign, unknown or non-contractor `person_id`); `422` |
| `DELETE /finance/rates/{id}` | none | `200 {id, action: deleted\|closed, valid_to}` in both cases. `deleted`: no price snapshot referenced the rate and the row is gone. `closed`: a decision-day snapshot references it, so the row stays and `valid_to` is set to today (company timezone); repeating it keeps the first close date | `404` (foreign, unknown or already deleted id) |
| `/company/pause`, `/company/resume` | none | `200 {paused}` | none; resume also re-runs approved but unexecuted actions |
| `/agent/messages` | `{text, conversation_id?, page?}` (`page`: see [Page context](#page-context-page-on-post-agentmessages)) | `202 {conversation_id, turn_id}`; answer arrives via SSE or by polling the conversation | `404` for a foreign conversation; `422` for an invalid `page`; `503` if the turn could not be started (it is marked failed; send the message again) |
| `PUT /agent/page` | a page context, the same object as `page` above (not wrapped) | `204`, no body: the page facts are resolved for your next message (see [Page pre-warm](#page-pre-warm-put-agentpage)) | `422` for an invalid page (same rules as `page`); `503` when the facts could not be resolved right now (safe to ignore: the next message resolves them itself) |
| `/auth/session` | `{id_token}` | see Auth | see Auth |

Document choices (`DOC_CHOICES`): `lease`, `invoice`, `quote`, `id_document`, `insurance`, `certificate`, `correspondence`, `photo`, `other`, `skip`.

A decision on an old draft version returns `kind: "stale"` (nothing is sent): refetch `/approvals`.

### Quote checker (`/finance/*`, `quote_review` feed card)

A contractor's quote or invoice is read when it arrives and compared with the rates agreed with that contractor and with
market prices **of the day the owner decided** (`snapshot_basis: decision_day`); when no snapshot exists the review
uses current prices and says so (`snapshot_basis: estimate_current_prices`). Verdicts: `ok`, `needs_check`,
`above_market`, `above_agreed`, `well_above_market`. Nothing is sent to anyone: the card is for the owner.

**Render as plain text.** Line descriptions, `reason`, vendor names and every source name come from contractor messages
or web pages. Show them as text, never as HTML or Markdown, and never follow or auto-link a `url`. Every entry of every
`sources` list carries a `name` (entries without one are dropped by the API); `url` is optional and untrusted.
Raw message bodies are never part of any finance response.

`quote_review` feed item: `ref_id` is the quote id; `payload` is the same JSON as `report` on
`GET /finance/quotes/{id}`. Money is always a decimal string, dates are ISO (`YYYY-MM-DD`), ids are strings.

| Field | Meaning |
|---|---|
| `quote_id`, `review_id`, `case_id` | ids (`case_id` may be null) |
| `vendor{id, name}` | the contractor linked from the sender (`id`/`name` null when none) |
| `currency`, `total` | as quoted (`total` may be null) |
| `verdict` | the most severe line verdict |
| `snapshot_basis`, `decision_date` | `decision_day` or `estimate_current_prices` (an estimate: label it) and the day the reference prices are from |
| `quote_date`, `work_date` | dates on the quote |
| `late_days`, `late_flag` | days between decision and quote; `late_flag` when over the threshold |
| `overcharge_total` | summed overcharge over the reviewed lines (EUR, excl. VAT); `overcharge_assumes_vat_excl_for_unknown_vat_lines` says it assumed excl. VAT for lines whose VAT status was unknown |
| `low_confidence` | too few price samples for at least one figure: say "indicative" |
| `lump_sum`, `lump_sum_parts[{item_key, kind: rate_card\|market, amount}]` | one price for a whole job, compared with the sum of the case's item references |
| `skipped_lines`, `skipped[{position, description}]` | lines that could not be read or compared (not in the totals) |
| `reason` | short note when the review could not be complete (nullable) |
| `worst_line_index` | index into `lines` of the worst line (nullable) |
| `lines[]` | per line: `position, description, item_key, quantity, unit, unit_price, amount, vat_included, unit_price_excl_vat, status, reference{kind: rate_card\|market, amount, unit}\|null, rate_card, reference_as_of: decision_day\|estimate\|null, snapshot_as_of, vs_rate_card_pct, vs_market_pct, overcharge, vat_unknown, vs_reference_pct_if_vat_included, low_confidence, drift_pct, market{low, avg, high, n, low_confidence, sources[{name, url?, price?, observed_on?, item_key?}]}\|null, market_now{low, avg, high, n, low_confidence}\|null` |

Line `status`: `ok`, `above_agreed`, `above_market`, `well_above_market`, `suspiciously_low`, `no_reference`,
`currency_mismatch`. Percentages are decimal strings ("12.5" = 12.5 % over the reference).

Rate cards are EUR only. `valid_to` null means current. Deleting a rate that a snapshot still references only ends it
(see `DELETE /finance/rates/{id}`): snapshots are immutable facts of the decision day.

### Page context (`page` on `POST /agent/messages`)

Optional. Send it whenever the Super Agent is opened on a page, so "this", "it", "reply to him" or "the first one"
mean the item the owner is looking at. Leave it out (or `null`) when the agent is opened without a page.

| Field | Type and limit | What the server does with it |
|---|---|---|
| `view` | required: `inbox`, `thread`, `case`, `approvals`, `tasks`, `waiting`, `documents`, `briefing`, `other` | shown to the planner |
| `case_id`, `approval_id`, `attachment_id` | UUID, optional | looked up in your company; replaced by server facts (case state, urgency, summary capped at 800 chars, plus the memory pack below with the case's messages; approval type, status, drafts capped at 300 chars, suspicious flag; document file name and status) |
| `thread_key` | optional, as returned by `/inbox` (an invalid key is `422`) | the memory pack below with this thread's messages only, and the thread's case |
| `task_ref` | optional, 6 to 8 hex characters (`#` allowed) | the open task's title, due date and status (open or snoozed tasks only; a done task counts as no longer existing) |
| `filters` | object of strings, at most 10 pairs, key 1 to 40 chars, value at most 120, no control characters | passed as unverified text |
| `visible_ids` | at most 50 strings (51 or more is `422`), each a UUID or task ref of at most 120 chars, or a thread key of at most 400 chars (long Gmail Message-IDs) | ids that belong to your company get a short label in screen order ("the first one") |
| `snapshot` | string, at most 6000 characters after whitespace is collapsed (runs of spaces/tabs become one space, blank lines are dropped; raw input over 24000 characters is `422` before collapsing); `\n` and `\t` allowed, `\r\n` and a lone `\r` become `\n`, any other control character (NUL, ESC, ...) is `422`; blank means no snapshot | passed as unverified text |

How the SPA builds it:
- `snapshot`: the visible text of the main panel (for example `innerText` of the page body without the agent panel and
  navigation), cut to 6000 characters on the client (the server turns `\r\n` and `\r` into `\n`). Over-long text is
  rejected, never truncated by the server.
- Ids: the open entity's id in its field (`case_id` on a case page, `thread_key` on a thread, `approval_id` on an
  approval, `task_ref` on a task, `attachment_id` on a document) and the ids of the rows on screen, top to bottom, in
  `visible_ids`.

Trust: **the snapshot and filters are advisory and unverified.** They reach the model only as escaped display text and
are never a source of ids, recipients or permissions; an id that appears only in the snapshot is ignored. When the page
facts carry the memory pack below (an open thread or case), the model sees only the first 3000 characters of the
snapshot (the facts already hold the conversation); otherwise up to 6000. The ids in
the structured fields are what the server trusts, and only after checking that they belong to your company. A foreign,
unknown or stale id is dropped (reported to the planner as "no longer exists", without the id). The validated page is
stored on the turn, and its facts are resolved once, so a retried turn answers from the same context.

What the agent reads for an open thread or case (the memory pack, server facts in the same `<page_facts>` block):
- **Messages:** with `thread_key`, that thread's messages only (never another thread's, even of the same case);
  with only `case_id`, the messages linked to the case on any channel. Up to 30: all of them when there are 30 or
  fewer, else the first 6 and the newest 24. Each is one line `msg NN | direction | channel | time (UTC) | text`
  with the text's first 600 characters, whitespace collapsed (tenant text can never start a line of its own).
- **Case memory** (the open case, else the open thread's case): summary (800 chars), the person's name and kind, the
  person's lease parties (role, unit, the directory version's validity, `current` or `not current since <date>`,
  current versions first; at most 3), open waits (who, what in 200 chars, expected
  by; at most 5), the last 15 timeline events (kind, state change such as `open -> waiting` or `(none) -> open`,
  actor, note in 120 chars) and the case's latest 5
  actions (type, status, `draft_version`, the owner's latest decision, edit count, first draft variant in 300 chars).
- **Budget:** the whole facts text is at most 12000 characters. When it would be longer, whole lines are left out in
  this order: older messages (down to the newest 6), visible rows from the bottom, the oldest events, the oldest
  earlier drafts, then the remaining messages oldest first. The page item headers, the summary, directory facts and
  open waits are never left out; a `(N messages not shown)` marker sits where messages are missing and a last line
  says what was left out. Like all page facts, the pack is resolved once and stored on the turn, so a retried turn
  reads the same text.

Answers use the page too, in one model call: for a question about the page, the conversation, a case, a draft or
the tasks, the planner (prompt `concierge/v6`; v4 added the document steps, v6 the `query_data` step and `suggestions`) writes the answer itself in the plan's
`reply` and plans an `answer` step, which shows it. A `reply` is used only when every step of the plan is `answer` or
`open_view`: a plan with any action (a draft, a chase, a task change, pause/resume, a document step) shows no model
text, only each step's own summary, and its stored `reply` is null. Before the owner sees it, `reply` is screened:
only for an in-scope plan (an out-of-scope plan gets the fixed refusal and its `reply` is dropped), control
characters removed, at most 20 lines and 1200 characters, links, email addresses, phone numbers and IBANs replaced by
`[redacted]`; ids are never taken from it. Amounts are allowed (the prompt lets the planner state only amounts found
in the server facts, such as "Rent arrears: € 950", never one from the snapshot or one a message asks to be paid);
an amount written as one run of 8 or more digits (`€ 12.345.678`) still reads as a phone number and is redacted. The
stored `plan` (in `GET /agent/conversations`) carries the screened `reply`, never the raw one, and never a reply that
no `answer` step shows. Only when `reply` is empty (or the planner fails and the agent falls back to a plain answer)
is the question asked again of the answering model: from your open cases and tasks plus the page facts, with the
snapshot and filters as advisory display text (prompt `owner_qa/v3`). So "what does this page say?", "what did he ask
last?" or "how much does Piet owe?" is answered from the page, and "is this draft okay?" on an approval is answered
from the server's copy of the draft (with an `open_view` step for `approvals`; the agent never approves or sends).

Case ids in a plan: a step may only name a case the planner was shown as company data, that is one of the brief's
open cases or a case id on a server fact line of the page (`open case:`, `open thread: ... | case`, approval and
visible rows). Any other id (one that appears only in a tenant message, the snapshot or the history, or a foreign one)
gets "Open that case's page first, then ask again.", whether or not it exists.

Example ("is this draft okay?" on an open approval):

```json
{
  "text": "is this draft okay?",
  "conversation_id": null,
  "page": {
    "view": "approvals",
    "approval_id": "0192a7c4-5b1e-7c3d-9f00-1a2b3c4d5e6f",
    "case_id": "0192a7c4-5b1e-7c3d-9f00-6f5e4d3c2b1a",
    "filters": {"status": "pending"},
    "visible_ids": ["0192a7c4-5b1e-7c3d-9f00-1a2b3c4d5e6f"],
    "snapshot": "Approvals\nJoris · maintenance\nBeste Joris, we sturen morgen een glazenmaker."
  }
}
```

### Drafts from the Super Agent (`draft_reply`)

"Reply to this, keep it short", "tell him the plumber comes Tuesday" or "make it shorter" on a thread or case page
produce a reply draft for the case's latest inbound message:
- **Guidance.** The owner's own message is the guidance for the drafting model (never the planner's wording, which
  may echo a tenant message). Links, email addresses, phone numbers, IBANs and amounts are removed first (`[redacted]`); the answer then
  says so and `details_removed` is `true`. Tenant replies are Dutch unless the guidance asks otherwise; the draft never
  adds contact or bank details or links that are not already in the conversation.
- **No draft yet:** a new proposal, as for an incoming message, with the guidance.
- **A reply draft is waiting for approval:** it is replaced by a new `draft_version` with a new pending approval; the
  old approval becomes `expired` (deciding it returns `stale`) and its feed card is resolved. Re-run safe: a retried
  turn returns the same new draft, never a third one.
- **The earlier draft was approved or rejected** (or the message has only other proposals, such as an escalation):
  one new reply draft for the same message per turn, as a new pending approval.
- **A reply draft is being edited** (edit tapped less than 24 hours ago) or waits without a pending approval: nothing
  changes; the answer asks the owner to finish it in Approvals first. An edit tapped more than 24 hours ago can no
  longer be applied: the new draft replaces that one like a pending draft.
- **Held messages** (flagged suspicious, company paused) and a new draft that would add an unverified link, account
  or phone number change nothing: the answer says why. Approving a draft on a suspicious message still needs
  `confirm_suspicious: true`.

The turn's `answer` quotes up to 3 variants (each at most 600 characters, lines prefixed `> `; a variant with an
unverified link, account or phone number is shown redacted with a "held back" note). The `draft_reply` entry in
`results` has `data`:

```json
{"approval_ids": ["<approval id>"], "case_id": "<case id>", "draft_version": 2,
 "drafts": [{"text": "Beste,\nDe loodgieter komt dinsdag bij u langs.\nMet vriendelijke groet,\nHarjot", "flags": []}],
 "details_removed": false, "superseded_approval_id": "<the replaced approval id or null>"}
```

`flags` lists `account`, `link` or `phone`. Show approve/edit for `approval_ids[0]` (it is also in `/approvals`); refetch
`/approvals` when `superseded_approval_id` is set. Nothing is sent until the owner approves; the recipient is always
the case's own contact from the database, never anything in the guidance or the drafts.

### Turn timings

Each turn records how long its stages took, in whole milliseconds, as `timings` on the turn (read-only, for latency
diagnostics; `null` for turns from before it was recorded): `queue_wait_ms` (message stored to the run starting, both
on the database clock), `page_resolve_ms`, `planner_ms`, `executor_ms` (includes `answer_ms`), `answer_ms` (the extra
answering call, only when the plan had no usable `reply` or the planner failed), `first_delta_ms` (time to first visible text),
`total_ms` (the run), `attempts` (runs started; a retried run keeps the first run's `queue_wait_ms` and any stage it
did not repeat), and `warm_hit` (`none`, `facts` or `blocks`). A key is missing when its stage did not run (the `tasks` command,
for example, has no planner). Turns run on their own `concierge` queue, so they never wait behind message processing;
the worker picks a waiting turn up within about 0.25 s.

### Page pre-warm (`PUT /agent/page`)

Optional speed-up. The server resolves the page facts (the server facts and memory pack above) as soon as the owner
opens a page, so the next message on that page does not wait for them. Nothing else happens: no turn, no model call,
no answer.

When the SPA calls it:
- on navigation to a page, debounced about 300 ms (only the last page of a quick click-through is sent);
- again when the open entity changes (another thread, case, approval, task or document on the same view) or the rows
  on screen change (new `visible_ids` or a new order);
- optionally again after the SPA's own writes on that page (an approve, edit or task change), so the next message
  stays fast. This is only for speed; correctness does not depend on it (see below).

The body is the same object as `page` on `POST /agent/messages`, with the same limits and `422` rules. Answer `204`
with no body; `503` means try later or just ignore it. Foreign or unknown ids are dropped exactly as for a message.

When a message reuses the warmed facts: only for the same owner (the session's, never ids in the body), when the
message's `page` has the same `view`, the same open ids in the same fields and the same `visible_ids` in the same order,
and the facts were resolved at most 120 seconds before the message. `filters` and `snapshot` do not matter for
the match. The server also drops warmed facts as soon as your company has anything newer than them: a message (any
channel, inbound or outbound), an approval created or decided, or a case event (state change, note), counting
anything from 2 seconds before the pre-warm. So a tenant message that arrives after the pre-warm is never missing:
the message then resolves its facts itself, as it does without a pre-warm. There is no SSE event to re-warm on, and
none is needed.

Why the snapshot is not stored: the server keeps only the latest resolved facts per owner (one row, overwritten by
each call), never the client's `snapshot` or `filters`. A message always sends its own `page`, and its snapshot is the
one the agent reads, so a warmed page can never put an older screen in front of the model.

Example (owner opens a case; on a thread page send `view: "thread"` and the `thread_key` from `/inbox` the same way):

```json
{
  "view": "case",
  "case_id": "0192a7c4-5b1e-7c3d-9f00-6f5e4d3c2b1a",
  "visible_ids": [],
  "snapshot": "Sanne de Vries\nDe kraan in de keuken lekt nog steeds."
}
```

### thread_key

Opaque. It is the URL-safe base64 (no padding) of `{channel}:{ref}`. Always take it from `/inbox`; never build it.
Pass it unchanged in the path.

## SSE: `GET /api/v1/events`

- Use `EventSource` with credentials (or `fetch` streaming). Frames:
  - `event: feed`, `id: <cursor>`, `data: <FeedItem JSON>`.
  - `event: turn`, `data: {id, conversation_id, status, answer, updated_at}`: the current state of one of your agent
    turns. Turn frames carry no `id:` line, so they do not move `Last-Event-ID`. Turns are checked every 0.5 s (the
    feed every 1.5 s), so an answer appears about half a second after it is stored. That is about 2 small indexed
    queries per second per open stream (`agent_turns (company_id, updated_at, id)`); open one stream per tab.
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
(`exec:{action_id}:{draft_version}`, `concierge:{turn_id}`, turns on the `concierge` queue like the API), so nothing
runs twice; at most 200 per round (up to 1000
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
