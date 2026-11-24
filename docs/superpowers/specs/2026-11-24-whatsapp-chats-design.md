# WhatsApp Chats: a WhatsApp-style workspace in the dashboard

Date: 2026-11-24 · Status: draft, awaiting owner approval · Related: [dashboard spec](2026-10-15-dashboard-super-agent-design.md),
[ADR 0006](../../adr/0006-dashboard-owner-channel.md), [security standard](../../standards/security.md)

## 1. Intent

The client will run **all of his WhatsApp through EstateOS**. He must be able to read every conversation, scroll its
history, and reply by typing and pressing send, as in the WhatsApp app, without ever opening WhatsApp.

Today the inbox is built around cases and approvals (WhatsApp and Gmail mixed in one list, about 1,100 lines of page
plus 1,100 of composer) and the composer sends him out to WhatsApp Web. There is no chat view, no unread state, and
direct sending is refused on purpose (`POST /api/contacts/{id}/whatsapp/send` returns 501).

Why it matters: if the chat view is slow, confusing or lossy, he goes back to the phone app, and the AI loses sight
of half the conversation.

## 2. Goals, non-goals, anti-goals

**Goals**
- A `/chats` page that looks and behaves like WhatsApp Web: chat list, bubbles, day separators, ticks, unread badges,
  search, attachments, voice-note playback, live updates.
- He types and sends directly. AI draft suggestions appear above the composer as one-tap, editable suggestions.
- Every chat links to its case, tenant or contractor profile, and shows the 24-hour window state.
- Everything he sends is recorded exactly once, visible in the thread, and traceable (`sends` row).

**Non-goals (this design)**
- WhatsApp **group** chats (Cloud API does not offer them).
- **History from before go-live** (he has none, and the Cloud API cannot export it). Meta coexistence and history sync are dropped.
- **Templates and first-contact outreach**: outside the 24-hour window the composer is disabled with a clear reason.
  Templates are a separate, later design.
- Sending voice notes, stickers, locations, contacts, polls. Calls.
- Replacing the Inbox page: the Inbox stays the case and approval workspace. Gmail is not touched.

**Anti-goals** (a failure even if it "works")
- A message sent twice, to the wrong number, or recorded as sent when it was not.
- A path that lets message text, model output or a client-supplied number decide the recipient.
- Hiding a message the pipeline held or flagged `suspicious`.
- The AI sending anything. It suggests; only his send click sends.

## 3. Constraints

- **Invariant 5 changes.** Today: "tenant sends happen only after the owner's approve click". New: an **owner-typed
  message sent by his own click** is a second allowed send class. AI-drafted actions still need approval; the Super
  Agent still cannot send. Needs **ADR 0013**, and edits to CLAUDE.md invariant 5, dashboard spec §5, `security.md`,
  and the 501 route text.
- Only `backend/app/sender/` may import `SenderSettings` or `app.channels.*.outbound` (import-linter + hook). The new
  send lives there.
- WhatsApp rules: free-form text only within 24 h of the contact's last inbound message; the Cloud API has no
  idempotency key, so an ambiguous failure must never be auto-retried (already handled by `WhatsAppSendError.maybe_sent`).
- **Plain WhatsApp Cloud API number, no phone app (decided 2026-11-24).** The client has no message history to keep
  and cannot run two WhatsApp apps on his phone, so he does not use Meta coexistence. The dashboard is the only place he
  reads and writes WhatsApp. Consequences: no phone-sent messages (echoes) and no history sync are needed, and the
  parser's existing `smb_message_echoes` handling stays untouched. Chats start empty at go-live and fill from the first
  inbound message. Meta's Cloud API limits still apply: no groups, template-only outside the 24-hour window.
- Tenant scoping (`company_id` everywhere), Postgres before work, deterministic idempotency keys, mypy strict,
  functions under 40 lines, modules under 300 lines.
- Respect `companies.outbound_mode`: in `draft` mode nothing leaves.

## 4. Approaches considered

| | Approach | Verdict |
|---|---|---|
| **A** | New `/chats` page and new chat endpoints beside the existing Inbox | **Chosen (owner, 2026-11-24)** |
| B | Rework the existing Inbox into a chat UI | Rejected: 2,200 lines built around cases and Gmail, high regression risk, Gmail does not fit a chat layout |
| C | Embed WhatsApp Web | Rejected: blocked by WhatsApp, and bypasses the sender |

Within A, one sub-choice I made: **a chat is keyed by the contact's WhatsApp number (E.164), not by case.** One
person with three open cases is one chat, as in WhatsApp. Cases appear as links in the side panel.

## 5. Design

### 5.1 What he sees

```
┌ Chats ───────────────┬ Mrs. de Vries · Tenant · Unit 4B     [case ▸] [profile ▸] ┐
│ 🔍 search            │ ── Mon 23 Nov ──                                          │
│ [All][Unread][Tenants│  Pump is leaking again               09:12               │
│  ][Contractors]      │              Ok, plumber comes tomorrow 10:00  ✓✓ (read)  │
│ ● de Vries   2m   2  │  [photo]                              09:15              │
│   Jansen BV  1h      │ ⓘ Reply window open 21h 40m                               │
│   Plumber Ali  Mon   │ ┌ Suggested: "Dank u, morgen om 10:00…"  [Use] [Other ▾] ┐ │
│                      │ [ 😊  type a message…                   📎   ➤ ]          │
└──────────────────────┴────────────────────────────────────────────────────────────┘
```

- **List:** newest activity first. Name (Person) or the raw number for unknown senders, last-message preview with a
  tick for outbound, time, unread count, role tag. Filters: All, Unread, Tenants, Contractors. Search over names,
  numbers and message text.
- **Thread:** bubbles (inbound left, outbound right), day separators, quoted replies, ticks (sent / delivered /
  read / failed), failed sends with a **Retry** that is a fresh send with a new client id only after he confirms.
  Images inline, documents as file chips, voice notes with an audio player and transcript when one exists.
  Messages held or flagged `suspicious` are shown with that state.
- **Composer states:** window open (normal), window closed ("Free-form replies closed since <time>; templates are
  not available yet"), `draft` mode ("Sending is switched off for this company"), no recipient rule match (cannot
  reply). Disabled composer still shows suggestions as copyable text.
- **Mobile:** single pane with back navigation (he may use it on a phone browser).

### 5.2 Backend API (`backend/app/api/v1/chats.py`, section access reuses `inbox`)

| Route | Purpose |
|---|---|
| `GET /chats?before=&limit=&filter=&q=` | chat list page (cursor like `/inbox`, limit ≤ 100) |
| `GET /chats/{chat_key}/messages?before=&limit=` | messages, oldest-first page, with attachments (presigned, short TTL) and quote info |
| `POST /chats/{chat_key}/read` | mark read up to now |
| `POST /chats/{chat_key}/messages` | owner-typed send. Body: `client_msg_id` (UUID from the browser), `text` (1–4096). Returns the stored message |
| `GET /chats/{chat_key}/suggestions` | pending reply drafts for the newest inbound message (reuses existing `reply_draft` actions) |

`chat_key` is the canonical E.164 number. Malformed, unknown and foreign keys all return the same 404 (as
`/threads/{key}`). Live updates reuse the existing SSE nudge in `api/v1/events.py` with a `chat` event, and the page
polls every 8 s as a fallback (as the Inbox does).

### 5.3 Owner-typed send (`backend/app/sender/owner_chat.py`)

One locked transaction, then the provider call after commit, mirroring `execute.py`:

1. **Recipient** derived from the DB only: the stored outbound row's `thread_ref` (canonical E.164; the request carries
   a `chat_key`, never a free-form `to`) must be the `sender_identity` of an inbound WhatsApp message of this company,
   must not be one of the company's own addresses (`own_addresses`, promoted from the private `_own_addresses`) or an
   owner number or email.
2. **Window:** the newest inbound from that number must be inside the 23 h window (`wa_window.window_open`, exactly at
   the boundary is closed), else refuse with the reason.
3. **Mode and pause:** company not paused, `outbound_mode == send`, else refuse.
4. **Caps:** a separate per-company hourly cap for owner-typed sends (`owner_chat_sends_per_hour`, default 200/h), a
   per-contact cap (`owner_chat_sends_per_number_per_hour`, default 20/h), plus the existing 120/min decision-write
   rate limit. The AI-draft cap stays untouched, and chat sends do not count against it.
5. **Idempotency:** key `chat:{company_id}:{client_msg_id}`; `client_msg_id` must match `[A-Za-z0-9_-]{1,64}` and is
   unique per company among outbound WhatsApp rows (migration 0050). A double click, retry or two tabs produce one send.
6. Built flow: the API (Task 7) stores the outbound `messages` row first (`direction=outbound`, `delivery_status`
   NULL = pending, placeholder provider id) and enqueues. The sender claims the `sends` row (existing `claim`) in one
   transaction under the company lock, calls the provider after commit, then writes the wamid into
   `provider_msg_id` and `delivery_status = sent`. A refusal or a provider failure writes `delivery_status = failed`
   and `meta.send_error` (a short reason, no text). Ambiguous failures record "unknown" and are never auto-retried;
   the UI shows "may not have been delivered". A send whose worker died is settled as failed by the stuck sweep.
7. Delivery/read ticks arrive through the existing status webhook handling
   (`ingestion/repository.py` rank-based status update). The pipeline skips outbound rows (`process.py`).
8. If the text came from a suggestion, the request carries `suggestion_action_id`; the action is closed as handled
   by hand so no stale approval stays pending and outcome capture compares sent text with the draft.

Owner typed text is not model output and is not guarded by the draft output guard. It is still never logged at
info level.

### 5.4 Data

- New table `chat_reads(company_id, chat_key, last_read_at)`, unique on `(company_id, chat_key)`. Unread count =
  inbound messages with `sent_at > last_read_at`. New Alembic migration (see `/new-migration`).
- Chat list is a query over `messages` (channel `whatsapp`) grouped by canonical number, joined to
  `channel_identities` → `people` for names, with a covering index if the explain plan needs one (builder decides).
  No other new storage.

### 5.5 Frontend

- New `frontend/src/app/chats/page.tsx` plus `frontend/src/components/chats/` (`ChatList`, `ChatThread`,
  `MessageBubble`, `ChatComposer`, `SuggestionBar`, `ChatHeader`). Small files; no reuse of the 1,100-line
  Inbox composer.
- Sidebar entry "Chats" with total unread badge. Existing inbox links ("open chat") deep-link to `/chats?chat=<key>`.
- English UI for him; message bodies stay Dutch. Reuse the existing translate toggle on a bubble.
- Optimistic send: bubble appears with a clock tick, reconciles on the response using `client_msg_id`.

## 6. Delivery slices

1. **Read-only chats:** list, thread, unread, search, media display, live updates. No send. (Safe to ship first.)
2. **Send text:** ADR 0013, `owner_chat.py`, composer, window and mode states, suggestions.
3. **Send images and documents:** upload to storage, provider media send, same guards.
4. **Polish:** quoted-reply sending, reactions display, mobile pass.

## 7. Testing (per [dev-pipeline](../../dev-pipeline.md))

- Unit: recipient derivation (own number, owner number, roommate, foreign company, unknown number), window boundary,
  idempotency, cap, mode gating, chat grouping and unread maths.
- Integration (testcontainers): double-submit sends once; ambiguous failure never retries; cross-company chat key 404;
  status webhook updates ticks on the stored outbound row; pipeline does not process the outbound row.
- Security (`estateos-security` pass): send isolation import-linter contract still green, no recipient from request,
  cross-tenant tests, no message text in info logs, presigned URL TTLs.
- Frontend: component tests for composer states; browser check of the full flow with `make sim-demo`.
- OpenAPI snapshot updated.

## 8. Left to the builder

Exact SQL and indexes for the chat list, SSE event payload shape, bubble styling details, the handling of the closed
suggestion action's status, and the media upload size limits (follow WhatsApp's: 5 MB image, 100 MB document).

## 9. My calls (change any of them)

- Chat key is the number, not the case.
- Closed window or `draft` mode disables the composer (no queueing, no template fallback).
- Owner-typed sends get their own hourly cap (200/h default), separate from the AI-draft cap.
- Section access reuses `inbox`; no new access section.
- Groups, templates, history import and sending voice notes are out of scope.
