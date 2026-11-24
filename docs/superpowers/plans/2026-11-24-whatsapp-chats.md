# WhatsApp Chats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A WhatsApp-style `/chats` page where Harjot reads every WhatsApp conversation and replies by typing and pressing send; the AI only suggests text.

**Architecture:** Chats are a read model over `messages` (channel `whatsapp`) grouped by `thread_ref` (the contact's E.164 number), plus a `chat_reads` table for unread state. Sending follows invariant 1 and the layer contract: the API (which may not import `app.sender` or `app.workflows`) inserts a pending outbound `messages` row, then enqueues the DBOS workflow `chat.send_message` by name; a step calls the new `app/sender/owner_chat.py`, which re-derives the recipient from the DB and re-checks window, mode, pause and cap before one provider call. Delivery ticks come from the existing status webhook.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, DBOS, Postgres 16 (testcontainers), Next.js 16 (read `frontend/node_modules/next/dist/docs/` before writing frontend code: see `frontend/AGENTS.md`), React 19, Tailwind.

**Spec:** [docs/superpowers/specs/2026-11-24-whatsapp-chats-design.md](../specs/2026-11-24-whatsapp-chats-design.md). This plan covers design slices 1 and 2 (read-only chats, then send text). Slices 3 (send images/documents) and 4 (polish) get their own plan after these ship.

## Plan amendments to the spec (found while reading the code)

- **API location:** the dashboard frontend talks to cookie-session routers under `/api/...` (`app/api/inbox`, `app/api/contacts`: `require_session`, `get_engine`), not `/api/v1`. Chats follow that: package `backend/app/api/chats/`, paths `/api/chats/...`, access `require_section("inbox")`.
- **Send path:** the layer contract forbids `app.api` importing `app.sender` or `app.workflows`, so the send is API insert + enqueue by name + workflow step, not one synchronous locked transaction.
- **Live updates:** polling every 8 s like the Inbox. No new SSE event (YAGNI; can follow).
- **Shared window rule:** `pipeline` and `sender` are sibling layers and may not import each other, so the 23 h window rule moves to `app/core/wa_window.py`.

## Global Constraints

- Every query filters by `company_id`; repositories require it (invariant 4).
- Only `backend/app/sender/` imports `SenderSettings` or `app.channels.*.outbound` (invariant 5, import-linter).
- Recipient comes from the DB only: the chat's number must be the `sender_identity` of an inbound WhatsApp message of this company and not an own or owner address. Never from request body or model output (invariant 6).
- Workflow functions do no I/O; all I/O in `@DBOS.step`. Workflow id `chat:{company_id}:{client_msg_id}` (invariants 1-3).
- Window rule: free-form text only within 23 h of the contact's last inbound (`WINDOW = timedelta(hours=23)`). Closed window or `outbound_mode != send` or company paused: refuse, no queueing, no template.
- Owner-typed sends have their own cap: setting `owner_chat_sends_per_hour`, default `200`, counted from `sends` rows with key prefix `chat:`.
- Text length 1-4096 characters after strip; exactly as typed, never trimmed or edited by code.
- Chat key = canonical E.164 string; malformed, unknown and foreign keys return one identical 404 body `"chat not found"`.
- Python 3.12, mypy strict, `StrEnum`, UUIDv7 ids (`app.core.ids.new_id`), functions < 40 lines, modules < 300 lines, structlog only, no message bodies in info logs.
- Migrations and prompts, once committed, are immutable. One new migration `0049`.
- Tests: RED first (see it fail), GREEN, then `make quick`; `make check` for db/workflows/sender/api tasks. Always via `make` from the repo root; single tests via `make test-int` / `make test-unit` cannot take a path, so run `cd backend && uv run pytest <path> -q` only for the red/green loop, and finish each task with the make target.
- Frontend has no test runner. Verification there is `cd frontend && npx tsc --noEmit`, `npm run lint`, `make frontend-build`, plus the browser check in Task 4 and Task 8. Adding vitest is a dependency change and needs the owner's OK (open question at the end of this plan).
- UI language English for Harjot; message bodies are shown as stored (Dutch).
- Commit per task, conventional commits, branch `m-chats` from `dev` (never commit on `main`). Do not push (standing rule: push only when asked, only `hrrealestate dev`).

## Review Focus

Failure modes the spec implies but no single task's happy path covers. Each has a test in the task named in brackets.

1. Double click or two tabs send the same `client_msg_id`: one row, one workflow id, one provider call. [Task 7, Task 5]
2. A voice note, photo or document with empty `text`: list preview shows "Voice message" / "Photo" / "Document", never blank. [Task 2]
3. An unknown number (no `Person`): chat shows the number and can be answered inside the window. [Task 2, Task 5]
4. The worker is down or the provider call is ambiguous: the outbound bubble must show "Sending..." then "May not have been delivered", never a silent success; an ambiguous failure is never auto-retried. [Task 5, Task 8]
5. A `delivered` status webhook arrives before the new `wamid` is stored on our outbound row: the tick must not be lost. [Task 6]
6. Message text containing HTML or a `javascript:` link renders as plain text. [Task 4]
7. Own number, owner number, a roommate who is not the contact, or another company's number as `chat_key` on send: refused. [Task 5, Task 7]
8. Messages the pipeline held or flagged `suspicious` appear with their state and are not hidden. [Task 3, Task 4]

---

## File Structure

Backend (new unless marked):
- `backend/app/core/wa_window.py`: the 23 h window rule, one definition.
- `backend/app/db/models/chat.py` + `backend/app/db/alembic/versions/0049_chat_reads.py`: `ChatRead`.
- `backend/app/pipeline/chat_repo.py`: chat list, messages page, unread, mark-read, suggestions. Pure queries.
- `backend/app/api/chats/{__init__,routes,schemas}.py`: `/api/chats` routes.
- `backend/app/sender/owner_chat.py`: recipient rule, gates, `send_chat_message`.
- `backend/app/workflows/chat_send.py`: `chat.send_message` workflow.
- Modified: `app/sender/owner_window.py`, `app/sender/recipient.py`, `app/sender/targets.py`, `app/sender/plan.py`, `app/sender/deps.py`, `app/sender/delivery.py` (SenderDeps field), `app/core/settings.py`, `app/core/workflow_names.py`, `app/api/v1/enqueue.py`, `app/main.py`, `app/db/models/__init__.py`, `app/api/contacts/routes.py` (501 text), worker workflow registration.

Frontend (new unless marked):
- `frontend/src/app/chats/page.tsx`
- `frontend/src/components/chats/{ChatList,ChatThread,MessageBubble,ChatHeader,ChatComposer,SuggestionBar}.tsx`
- `frontend/src/lib/chatsApi.ts`, `frontend/src/lib/chats.ts` (pure helpers), `frontend/src/types/chats.ts`
- Modified: `frontend/src/components/layout/Sidebar.tsx`, `frontend/src/lib/sections.ts`.

---

### Task 1: Window rule in core and the `chat_reads` table

**Files:**
- Create: `backend/app/core/wa_window.py`, `backend/app/db/models/chat.py`, `backend/app/db/alembic/versions/0049_chat_reads.py`
- Modify: `backend/app/sender/owner_window.py` (import `WINDOW` from core, keep the name exported), `backend/app/sender/recipient.py:111-114` (`whatsapp_window_open` delegates), `backend/app/db/models/__init__.py` (export `ChatRead`)
- Test: `backend/tests/unit/test_wa_window.py`, `backend/tests/integration/test_chat_reads.py`

**Interfaces:**
- Produces: `app.core.wa_window.WINDOW: timedelta` (23 h), `window_open(received_at: datetime, now: datetime) -> bool`, `window_closes_at(received_at: datetime) -> datetime`.
- Produces: `ChatRead(Base, CompanyScoped)` with `chat_key: str` (String 32), `last_read_at: datetime`; unique on `(company_id, chat_key)`, `__company_id_leading_index__ = True`.

- [ ] **Step 1: Write failing unit tests** in `test_wa_window.py`: `test_window_open_just_inside` (received = now - 23h + 1s -> True), `test_window_closed_exactly_at_boundary` (received = now - 23h -> False, matches the existing "exactly at the boundary is closed" rule), `test_window_closes_at_adds_window`, and `test_existing_sender_rule_unchanged` calling `recipient.whatsapp_window_open` with a `MessageRow` whose `sent_at` is newer than `created_at` (the older clock is the anchor).
- [ ] **Step 2: Run to see RED:** `cd backend && uv run pytest tests/unit/test_wa_window.py -q` -> FAIL (module missing).
- [ ] **Step 3: Implement** `wa_window.py` per the Interfaces block; make `owner_window.py` do `from app.core.wa_window import WINDOW as WINDOW`; make `recipient.whatsapp_window_open` return `window_open(min(msg.sent_at, msg.created_at), now)`.
- [ ] **Step 4: Run** the new test plus `tests/unit -k window` -> PASS (existing window tests unchanged).
- [ ] **Step 5: Write failing integration test** `test_chat_reads.py`: inserting two `ChatRead` rows with the same `(company_id, chat_key)` raises `IntegrityError`; two companies may share a `chat_key`.
- [ ] **Step 6: Add model and migration.** Use `make migration m="chat reads"` (see `/new-migration`), then hand-check that revision is `0049`, `down_revision = "0048"`, creates `chat_reads` with the unique constraint and FK to `companies`. Run `make migrate-roundtrip` and `make alembic-check` -> both green.
- [ ] **Step 7: Run** `make quick` then `make check`. Expected: all green.
- [ ] **Step 8: Commit** `feat(chats): shared WhatsApp window rule and chat_reads table`.

---

### Task 2: Chat read queries (`chat_repo`)

**Files:**
- Create: `backend/app/pipeline/chat_repo.py`
- Test: `backend/tests/integration/test_chat_repo.py`

**Interfaces:**
- Consumes: `read_repo.Cursor`, `read_repo.parse_cursor`, `read_repo.MAX_PAGE`, `ChatRead`, `MessageRow`, `ChannelIdentity`, `Person`, `CaseLink`, `ActionRow`.
- Produces:
  - `class BadChatKeyError(EstateOSError)`
  - `parse_chat_key(raw: str) -> str`: canonical E.164 via `normalise_identity`; must start with `+` and be digits after it; else `BadChatKeyError`.
  - `@dataclass(frozen=True) class ChatSummary`: `chat_key: str`, `name: str | None`, `person_kind: PersonKind | None`, `last_message_id: UUID`, `last_at: datetime`, `last_text: str`, `last_kind: str | None` (message `meta["type"]`), `last_direction: Direction`, `last_delivery: DeliveryStatus | None`, `unread: int`.
  - `chat_list(session, company_id, *, before: Cursor | None, limit: int, filter: Literal["all","unread","tenants","contractors"] = "all", q: str | None = None) -> list[ChatSummary]`: WhatsApp messages grouped by `thread_ref`, newest activity first, cursor `(last_at, last_message_id)`.
  - `chat_messages(session, company_id, chat_key: str, *, before: Cursor | None, limit: int) -> list[MessageRow]`: newest `limit` before the cursor, returned oldest-first; empty for unknown or foreign key.
  - `mark_read(session, company_id, chat_key: str, now: datetime) -> None`: upsert `ChatRead.last_read_at = now` (never moves backwards).
  - `latest_inbound(session, company_id, chat_key: str) -> MessageRow | None`
  - `latest_case_id(session, company_id, chat_key: str) -> UUID | None`: newest case linked to any message of the chat.
  - `suggestions(session, company_id, chat_key: str) -> tuple[UUID | None, list[str]]`: id and `payload["body_variants"]` (max 3, non-empty strings) of the newest `reply_draft` action whose `context_ref` contains the latest inbound message id and whose status is still open (read `ActionStatus` for the pending member names); `(None, [])` if none.

Rules: `unread` counts inbound rows with `created_at` greater than the chat's `last_read_at` (all inbound if no `ChatRead`); outbound rows (ours, echoes) never count. `name` and `person_kind` come from the current (`valid_to IS NULL`) WhatsApp `ChannelIdentity` -> `Person`; unknown number gives `None`. `q` matches name, number, or message text, `ILIKE` with `%`/`_` escaped. `last_kind` for empty `text` lets the UI show "Voice message" etc.

- [ ] **Step 1: Write failing integration tests** (fixture style: `tests/integration/test_dashboard_inbox.py`, helper `_msg`; WhatsApp rows use `thread_ref=<E.164>`, `sender_identity=<E.164>` for inbound):
  `test_chat_list_groups_by_number_newest_first`, `test_unread_counts_only_inbound_after_last_read`, `test_outbound_and_echo_never_unread`, `test_name_from_current_identity_unknown_number_is_none`, `test_filter_tenants_and_contractors_and_unread`, `test_search_matches_name_number_and_text_and_escapes_wildcards` (query `"%"` matches only a literal percent), `test_empty_text_voice_note_keeps_kind` (meta `{"type": "audio"}` -> `last_kind == "audio"`), `test_other_company_never_listed_and_messages_empty`, `test_chat_messages_pages_oldest_first`, `test_mark_read_never_moves_backwards`, `test_parse_chat_key_rejects_email_and_garbage`, `test_suggestions_returns_open_reply_draft_variants`.
- [ ] **Step 2: Run to see RED:** `cd backend && uv run pytest tests/integration/test_chat_repo.py -q` -> FAIL (module missing).
- [ ] **Step 3: Implement** the signatures above in `chat_repo.py`. Use one ranked subquery for the last row per `thread_ref` (pattern of `read_repo._ranked`) and a correlated count for unread; keep every function < 40 lines by splitting helpers (`_unread_count`, `_name_of`, `_apply_filter`).
- [ ] **Step 4: Run** the file -> all PASS.
- [ ] **Step 5: Look at the query plan** for `chat_list` on a few thousand rows with `EXPLAIN` in a scratch test; if it seq-scans past `ix_messages_company_channel_thread`, add an index in a follow-up migration revision `0050` (do not edit `0049` once committed). Record the decision in the commit message.
- [ ] **Step 6: Run** `make quick` then `make check` -> green.
- [ ] **Step 7: Commit** `feat(chats): chat list, messages page, unread and suggestions queries`.

---

### Task 3: Read API (`/api/chats`)

**Files:**
- Create: `backend/app/api/chats/__init__.py` (exports `router`, like `app/api/inbox/__init__.py`), `routes.py`, `schemas.py`
- Modify: `backend/app/main.py` (import `chats` from `app.api` and `api.include_router(chats.router)` after `inbox`), `backend/app/api/__init__.py` if it lists submodules
- Test: `backend/tests/integration/test_chats_api.py`

**Interfaces:**
- Consumes: Task 2 functions; `Principal`, `require_session`, `require_section("inbox")`, `get_engine`, `get_storage`; `read_repo.attachments_for`, `suspicious_flags`; `MAX_PRESIGN_TTL_S`.
- Produces (pydantic models in `schemas.py`):
  - `ChatItem`: the `ChatSummary` fields plus `cursor: str` (`"{last_at.isoformat()}|{last_message_id}"`).
  - `ChatMessage`: `id: UUID`, `direction: Direction`, `sent_at: datetime`, `text: str`, `kind: str | None`, `delivery_status: DeliveryStatus | None`, `error: str | None` (message `meta["send_error"]`), `suspicious: bool`, `suspicious_reason: str | None`, `reply_to: ChatQuote | None` (`id`, `text`: the quoted message's text, looked up by `provider_msg_id = meta["reply_to"]` in the same company), `attachments: list[AttachmentOut]` (reuse `app.api.v1.schemas.AttachmentOut`, presigned with `MAX_PRESIGN_TTL_S`), `pending: bool` (outbound row with no `delivery_status` and not failed).
  - `ChatThread`: `chat_key: str`, `name: str | None`, `person_kind: PersonKind | None`, `case_id: UUID | None`, `messages: list[ChatMessage]`.
- Routes (all `dependencies=[Depends(require_section("inbox"))]`, DB work in `run_in_threadpool`):
  - `GET /api/chats?before=&limit=&filter=&q=` -> `list[ChatItem]`; `limit` is `Query(ge=1, le=100)` default 50; bad cursor -> 422 `"invalid cursor"`; `q` max 100 chars.
  - `GET /api/chats/{chat_key}/messages?before=&limit=` -> `ChatThread`; `limit` `ge=1, le=200` default 100; `BadChatKeyError` or no messages -> 404 `"chat not found"` (same body for all three cases).
  - `POST /api/chats/{chat_key}/read` -> 204, same 404.

- [ ] **Step 1: Write failing integration tests** (fixture pattern from `test_dashboard_inbox.py::world`, cookie session via `issue_session`, `MemoryStorage`; two companies A and B each with WhatsApp chats):
  `test_list_is_company_scoped_and_newest_first`, `test_limit_above_100_is_422`, `test_bad_cursor_is_422`, `test_unknown_malformed_and_foreign_chat_key_give_identical_404` (compare full response bodies of the three), `test_messages_include_attachment_presigned_url_with_ttl`, `test_suspicious_and_held_messages_are_returned_with_state` (Review Focus 8), `test_quote_resolves_text_from_same_company_only`, `test_read_clears_unread_in_list`, `test_profile_without_inbox_section_is_403`, `test_messages_do_not_leak_other_company_attachments`.
- [ ] **Step 2: Run to see RED:** `cd backend && uv run pytest tests/integration/test_chats_api.py -q` -> FAIL (404 on route).
- [ ] **Step 3: Implement** schemas and routes; keep each route function < 40 lines by moving row-to-model mapping into `_to_message(row, atts, flag, quote)` helpers in `routes.py`. Log counts only, never message text.
- [ ] **Step 4: Run** the file -> PASS.
- [ ] **Step 5: Update the OpenAPI snapshot** the way the existing API snapshot test says in its failure message (search `tests` for the openapi snapshot test; run `make quick` and follow it), then re-run `make quick`.
- [ ] **Step 6: Run** `make check` -> green.
- [ ] **Step 7: Commit** `feat(chats): read API for chat list, messages and read state`.

---

### Task 4: Frontend, read-only Chats page (slice 1)

Read `frontend/AGENTS.md` and the relevant guide under `frontend/node_modules/next/dist/docs/` first. Follow the page shell of `frontend/src/app/contacts/page.tsx` (page renders `Sidebar`, `TopCommandBar`, `MobileTabBar` itself) and the fetch pattern of `frontend/src/lib/api.ts` (`apiFetch`, `BACKEND_BASE_URL`; a bare `fetch` sends no cookie).

**Files:**
- Create: `frontend/src/types/chats.ts`, `frontend/src/lib/chatsApi.ts`, `frontend/src/lib/chats.ts`, `frontend/src/app/chats/page.tsx`, `frontend/src/components/chats/{ChatList,ChatThread,MessageBubble,ChatHeader}.tsx`
- Modify: `frontend/src/lib/sections.ts` (add `["/chats", "inbox"]` to `SECTION_ROUTES`), `frontend/src/components/layout/Sidebar.tsx` (nav item `section: "inbox"`, `href: "/chats"`, `MessageCircle` icon, label `t("nav.chats")`, badge = total unread), `frontend/src/locales/common.ts` (`"nav.chats": { en: "Chats", nl: "Chats" }`)

**Interfaces:**
- Produces in `types/chats.ts`: types mirroring Task 3 schemas (`ChatItem`, `ChatMessage`, `ChatThread`, `ChatFilter = "all" | "unread" | "tenants" | "contractors"`).
- Produces in `chatsApi.ts`: `getChats(params: { filter?: ChatFilter; q?: string; before?: string; limit?: number }): Promise<ChatItem[] | null>`, `getChatMessages(chatKey: string, before?: string): Promise<ChatThread | null>`, `markChatRead(chatKey: string): Promise<boolean>`. `null`/`false` on network failure (same convention as `api.ts`); the page shows an error state, never fake data.
- Produces in `lib/chats.ts` (pure, no React): `chatPreview(item: ChatItem): string` (text, or "Voice message" / "Photo" / "Document" / "Message" by `last_kind` when text is empty, prefixed with "You: " for outbound), `groupByDay(messages: ChatMessage[], tz: string): Array<{ day: string; messages: ChatMessage[] }>` (day label in `Europe/Amsterdam`), `tickFor(m: ChatMessage): "pending" | "sent" | "delivered" | "read" | "failed"`, `totalUnread(items: ChatItem[]): number`.

- [ ] **Step 1: Types, API client and pure helpers** with the signatures above. Message bodies are rendered as React text children only: never `dangerouslySetInnerHTML`, never auto-linked (Review Focus 6).
- [ ] **Step 2: Components.** `ChatList`: search box, filter tabs (All / Unread / Tenants / Contractors), rows with name or number, `chatPreview`, time, unread badge. `ChatThread`: day separators, bubbles (inbound left, outbound right), ticks via `tickFor`, quoted reply block, image inline, document chip, `<audio controls>` for audio with transcript text if present, `suspicious` banner with reason, scroll to newest, "Load older" using the `before` cursor. `ChatHeader`: name or number, role tag, link to `/inbox?thread=...` when `case_id` is set (look up how the existing inbox links a case in `app/inbox/page.tsx`).
- [ ] **Step 3: Page.** Two panes on desktop, single pane with back button below `md`. Selected chat in the URL (`/chats?chat=<chat_key>`, URL-encode `+`). Poll the list and the open thread every 8 s (same as `app/inbox/page.tsx`), pause when `document.hidden`. Opening a chat calls `markChatRead` and refreshes the list.
- [ ] **Step 4: Verify types and lint:** `cd frontend && npx tsc --noEmit && npm run lint` -> no errors.
- [ ] **Step 5: Verify build:** `make frontend-build` -> success.
- [ ] **Step 6: Browser check** with `make up seed` then `make sim-demo` (simulates WhatsApp inbound) and `make frontend`: open `http://localhost:3000/chats`; expected: simulated chats listed, unread badge in sidebar, opening a chat clears the badge, an HTML-looking message (`<b>x</b>`, add via the simulator or a direct DB insert in a scratch company) shows literally. Use the `run` skill or ego-browser; take a screenshot as evidence.
- [ ] **Step 7: Commit** `feat(chats): read-only WhatsApp-style chats page`.

**Slice 1 checkpoint:** run the G3 reviewer (`estateos-reviewer`) and `estateos-security` (new API reading message content and presigned URLs) on the branch diff before starting Task 5. Fix blockers first.

---

### Task 5: ADR, docs and the owner-chat sender

**Files:**
- Create: `docs/adr/0013-owner-typed-whatsapp-sends.md`, `backend/app/sender/owner_chat.py`
- Modify: `CLAUDE.md` (invariant 5 wording), `docs/superpowers/specs/2026-10-15-dashboard-super-agent-design.md` (§5 amendment note), `docs/standards/security.md`, `docs/PROGRESS.md`, `backend/app/api/contacts/routes.py` (501 text now points to Chats), `backend/app/core/workflow_names.py` (`CHAT_SEND = "chat.send_message"`, `chat_workflow_id(company_id: object, client_msg_id: object) -> str`), `backend/app/core/settings.py` (`owner_chat_sends_per_hour: int = 200`), `backend/app/sender/delivery.py` (`SenderDeps.owner_chat_sends_per_hour: int = 200`), `backend/app/sender/deps.py` (pass the setting), `backend/app/sender/plan.py` (`chat_message_id: UUID | None = None`), `backend/app/sender/targets.py` (`assert_allowed` dispatches `plan.chat_message_id is not None` to `owner_chat.assert_chat`)
- Test: `backend/tests/integration/test_owner_chat_send.py`, `backend/tests/unit/test_owner_chat_gates.py`

**Interfaces:**
- Consumes: `recipient._own_addresses`, `recipient.canonical`, `tenant_gate.owner_targets`, `wa_window.window_open`, `delivery.claim`, `delivery.send_claimed`, `payloads.text`, `Company.outbound_mode`, `Company.paused`.
- Produces in `owner_chat.py`:
  - The idempotency key is `chat_workflow_id(company_id, client_msg_id)` from `app.core.workflow_names` (added in this task; core is below both sender and workflows): returns `f"chat:{company_id}:{client_msg_id}"`. It is both the `sends.idempotency_key` and the DBOS workflow id (Task 6).
  - `send_chat_message(deps: SenderDeps, company_id: UUID, message_id: UUID) -> ExecOutcome`: loads the pending outbound row (must be `direction=outbound`, channel `whatsapp`, `company_id` match, `delivery_status IS NULL`), derives the recipient from `row.thread_ref`, runs every gate, claims `sends` under key `chat:{company_id}:{row.meta["client_msg_id"]}`, calls the provider once, then writes `provider_msg_id = wamid` and `delivery_status = sent` on the row; on a refusal or failure writes `delivery_status = failed` and `meta["send_error"] = <short reason>` (no text body in the reason).
  - `assert_chat(session: Session, company_id: UUID, plan: Plan) -> None`: re-derives and re-checks right before the claim (mirrors `tenant_plans.assert_tenant`); raises `SendBlockedError`.
- Gate order and exact refusal texts (constants in `owner_chat.py`): `"company paused"`; `"sending is switched off for this company"` (`outbound_mode != send`); `"no inbound message from this number"`; `"this number belongs to the company"` (own or owner address); `"WhatsApp window closed: the contact wrote more than 23 h ago"`; `"hourly send cap reached"`; `"message is empty"`; `"message is too long"` (> `payloads.TEXT_BODY_MAX`).

- [ ] **Step 1: Write the ADR** `0013`: context (client uses only the dashboard; 501 on `/whatsapp/send` was deliberate), decision (owner-typed send is a second allowed send class: his own click, recipient from DB, window, mode, pause, own cap, idempotency, `sends` row; AI-drafted actions still need approval; Super Agent still cannot send), consequences (invariant 5 wording, security.md entry, no templates yet, Meta plain Cloud API number without coexistence). Edit `CLAUDE.md` invariant 5, the dashboard spec §5, `security.md` and `PROGRESS.md` accordingly; change the `NO_DIRECT_SEND` text in `contacts/routes.py` to say messages are sent from the Chats page. Keep the 501.
- [ ] **Step 2: Write failing unit tests** `test_owner_chat_gates.py` (pure gate function `chat_refusal(...)` extracted for testability: inputs are plain values, returns reason or `None`): paused, draft mode, no inbound, own number, owner number, window boundary (exactly 23 h -> closed), cap at 200 refuses and 199 passes, empty/whitespace text, 4097-character text.
- [ ] **Step 3: Write failing integration tests** `test_owner_chat_send.py` using `tests/integration/send_mode_support.py` (send-mode company, `FakeWhatsAppOutbound`): `test_sends_once_and_marks_row_sent_with_wamid`, `test_replay_same_message_sends_once` (call twice -> one fake provider call, Review Focus 1), `test_recipient_is_thread_ref_never_payload`, `test_unknown_number_inside_window_can_be_answered` (Review Focus 3), `test_roommate_number_without_inbound_refused`, `test_company_a_cannot_send_to_company_b_number` (Review Focus 7), `test_ambiguous_failure_marks_failed_and_is_not_retried` (provider raises `WhatsAppSendError(maybe_sent=True)`; row `failed`, `send_error` starts with "may have been delivered", second call makes no provider call; Review Focus 4), `test_definitely_not_sent_error_is_retryable` (returns pending, re-raises), `test_owner_chat_cap_is_separate_from_tenant_cap` (30 tenant sends do not block a chat send).
- [ ] **Step 4: Run to see RED:** `cd backend && uv run pytest tests/unit/test_owner_chat_gates.py tests/integration/test_owner_chat_send.py -q` -> FAIL.
- [ ] **Step 5: Implement** `owner_chat.py` (reuse `recipient` helpers; if a helper is private, promote it by dropping the underscore in `recipient.py` rather than copying it), the settings field, the `SenderDeps` field, `Plan.chat_message_id`, and the `assert_allowed` dispatch. Cap counts `Send` rows with `idempotency_key LIKE 'chat:%'` in the last hour, status in pending/sending/sent.
- [ ] **Step 6: Run** the two test files -> PASS; then `make boundaries` -> the send-isolation contract stays green (no new importer of `SenderSettings` or `channels.whatsapp.outbound` outside `app.sender`).
- [ ] **Step 7: Run** `make quick` then `make check` -> green.
- [ ] **Step 8: Commit** `feat(sender): owner-typed WhatsApp chat sends (ADR 0013)`.

---

### Task 6: `chat.send_message` workflow

Follow `backend/app/workflows/actions.py` (steps with `_RETRY`, thin workflow, no I/O in the workflow body) and find where `execute_action_wf` is registered for the worker (`app/workflows/runtime.py` or the module that imports it) and where `CONCIERGE_QUEUE` is declared in `app/workflows/queues.py`.

**Files:**
- Create: `backend/app/workflows/chat_send.py`
- Modify: `backend/app/core/workflow_names.py` (`CHAT_QUEUE = "chat"`), `backend/app/workflows/queues.py` (declare the chat queue with a short poll interval like the concierge queue: a person is waiting on a click), worker registration (import the new module where the others are), `backend/app/api/v1/enqueue.py`, `backend/app/ingestion/repository.py` (promote `_replay_statuses` to public `replay_statuses`, update its callers)
- Test: `backend/tests/integration/test_chat_send_workflow.py`

**Interfaces:**
- Consumes: `send_chat_message` (Task 5), `chat_workflow_id`, `get_sender_deps`, `get_engine`.
- Produces: `chat_send_wf(company_id: str, message_id: str) -> str` (returns the outcome status); `enqueue_chat_send(client: WorkflowClient, company_id: UUID, client_msg_id: UUID, message_id: UUID) -> None` (options: `queue_name=CHAT_QUEUE`, `workflow_name=CHAT_SEND`, `workflow_id=chat_workflow_id(company_id, client_msg_id)`; args `str(company_id)`, `str(message_id)`).
- Steps: `chat.send` (calls `send_chat_message`; retry policy as `actions._RETRY`), `chat.replay_statuses` (after a `sent` outcome, call `repository.replay_statuses(session, company_id, wamid)` so a `delivered` or `read` status that arrived before the `wamid` was stored is applied; Review Focus 5), `chat.close_suggestion` (when `meta["suggestion_action_id"]` is set and the send succeeded, move that action out of the open state so no stale approval stays pending).

- [ ] **Step 1: Write failing integration tests** (follow `tests/integration/test_concierge_workflow.py` for the DBOS fixture; `FakeWhatsAppOutbound`, send-mode company from `send_mode_support.py`): `test_workflow_sends_and_row_gets_wamid_and_sent`, `test_same_workflow_id_runs_once` (enqueue twice -> one provider call), `test_blocked_send_marks_row_failed_with_reason_and_does_not_retry`, `test_status_before_wamid_is_applied` (insert a stored `delivered` status raw event for the fake wamid first; after the workflow the row is `delivered`), `test_suggestion_action_is_closed_after_send` (the action no longer appears in `chat_repo.suggestions`; read `ActionStatus` and the approvals code to choose the existing terminal status that means "handled by hand"; if none fits, stop and ask the owner before adding an enum value and migration).
- [ ] **Step 2: Run to see RED:** `cd backend && uv run pytest tests/integration/test_chat_send_workflow.py -q` -> FAIL.
- [ ] **Step 3: Implement** the module, names, queue, enqueue function and the `replay_statuses` promotion.
- [ ] **Step 4: Run** the file -> PASS; `make boundaries` -> the "API enqueues by name only" contract stays green.
- [ ] **Step 5: Run** `make check` -> green.
- [ ] **Step 6: Commit** `feat(chats): chat.send_message workflow`.

---

### Task 7: Send and suggestions API, composer state

**Files:**
- Modify: `backend/app/api/chats/routes.py`, `backend/app/api/chats/schemas.py`
- Test: `backend/tests/integration/test_chats_send_api.py`

**Interfaces:**
- Consumes: `chat_repo.latest_inbound`, `chat_repo.suggestions`, `enqueue_chat_send`, `wa_window`, `Company`, `decide_limit` (the 120/min decision-write limiter in `app/api/v1/session_limits.py`), `get_workflow_client`.
- Produces in `schemas.py`:
  - `SendChatMessageRequest`: `client_msg_id: UUID`, `text: str` (validated: length 1-4096 after strip; the stored and sent text is exactly what was typed, unstripped), `suggestion_action_id: UUID | None`.
  - `ComposerState`: `state: Literal["open","window_closed","draft_mode","paused","no_recipient"]`, `window_closes_at: datetime | None`.
  - `ChatThread.composer: ComposerState`; `ChatMessage.client_msg_id: str | None` (from message `meta["client_msg_id"]`).
  - `SuggestionsOut`: `action_id: UUID | None`, `variants: list[str]`.
- Routes: `POST /api/chats/{chat_key}/messages` -> 202 with `ChatMessage` (pending); `GET /api/chats/{chat_key}/suggestions` -> `SuggestionsOut`.
- Send route behaviour, in one transaction: parse key (404 `"chat not found"`), require a prior inbound message for that number in this company (else the same 404), upsert the outbound row (`RawEvent` done with payload `{"kind": "dashboard_send"}` and `provider_msg_id = f"dash:{client_msg_id}"`; `MessageRow` `direction=outbound`, `channel=whatsapp`, `thread_ref=chat_key`, `sender_identity="dashboard"`, `sent_at=now`, `pipeline_status=done`, `delivery_status=None`, `meta={"client_msg_id", "type": "text", "dashboard": True, "suggestion_action_id"?}`), `ON CONFLICT DO NOTHING` on the existing `(company_id, channel, provider_msg_id)` unique so a replay returns the existing row; commit; then `enqueue_chat_send` (idempotent). Verify `suggestion_action_id` belongs to this company and is a `reply_draft`, else 422. Check `process.py` and `message_rag/indexer.py` for how outbound rows are treated and confirm the pipeline does not run on this row (spec §5.3 point 7).

- [ ] **Step 1: Write failing integration tests** (client fixture as Task 3; `workflow_client=MagicMock()` to assert enqueue options): `test_send_inserts_pending_row_then_enqueues_with_workflow_id` (assert `workflow_id == f"chat:{company}:{client_msg_id}"`, row text equals typed text exactly), `test_double_post_same_client_msg_id_one_row_one_enqueue_id` (Review Focus 1), `test_whitespace_only_and_4097_chars_are_422`, `test_unknown_foreign_and_malformed_chat_key_are_identical_404_and_never_enqueue` (Review Focus 7), `test_request_cannot_choose_recipient` (extra field `to` ignored/forbidden: `model_config = ConfigDict(extra="forbid")` -> 422), `test_suggestion_action_of_other_company_is_422`, `test_composer_state_open_window_closed_draft_mode_paused_no_recipient` (five cases against thread GET), `test_send_is_rate_limited`, `test_pipeline_does_not_process_dashboard_row` (row `pipeline_status` stays `done`, no `UnderstandingRow`), `test_suggestions_endpoint_returns_variants_and_none_when_absent`.
- [ ] **Step 2: Run to see RED:** `cd backend && uv run pytest tests/integration/test_chats_send_api.py -q` -> FAIL.
- [ ] **Step 3: Implement** routes and schemas; the composer state is computed in a `_composer_state(company, latest_inbound, now)` helper using `wa_window` and `Company.outbound_mode`, `Company.paused`.
- [ ] **Step 4: Run** the file -> PASS. Update the OpenAPI snapshot as in Task 3 step 5.
- [ ] **Step 5: Run** `make check` -> green.
- [ ] **Step 6: Commit** `feat(chats): owner-typed send, suggestions and composer state API`.

---

### Task 8: Frontend composer (slice 2)

**Files:**
- Create: `frontend/src/components/chats/ChatComposer.tsx`, `frontend/src/components/chats/SuggestionBar.tsx`
- Modify: `frontend/src/lib/chatsApi.ts`, `frontend/src/lib/chats.ts`, `frontend/src/types/chats.ts`, `frontend/src/components/chats/ChatThread.tsx`, `frontend/src/components/chats/MessageBubble.tsx`, `frontend/src/app/chats/page.tsx`

**Interfaces:**
- Produces in `chatsApi.ts`: `sendChatMessage(chatKey: string, body: { clientMsgId: string; text: string; suggestionActionId?: string }): Promise<{ ok: true; message: ChatMessage } | { ok: false; kind: "rejected" | "unknown"; reason: string }>` (`unknown` = network error or timeout: the request may have reached the server); `getChatSuggestions(chatKey: string): Promise<{ actionId: string | null; variants: string[] } | null>`.
- Produces in `chats.ts`: `newClientMsgId(): string` (`crypto.randomUUID()`), `mergeOptimistic(server: ChatMessage[], pending: ChatMessage[]): ChatMessage[]` (drops an optimistic bubble once a server message with the same `client_msg_id` exists; keeps the rest in order), `composerNotice(c: ComposerState): string | null` (the exact user-facing sentences: window closed -> `"Free-form replies closed: this contact last wrote more than 23 hours ago. Templates are not available yet."`; draft mode -> `"Sending is switched off for this company."`; paused -> `"This company is paused."`; no recipient -> `"There is no incoming message from this number to reply to."`), `pendingTooLong(m: ChatMessage, nowMs: number): boolean` (outbound, still pending, older than 5 minutes -> bubble says "May not have been sent. Check before sending again.").

- [ ] **Step 1: Types, API client, helpers** per the Interfaces block. Use `apiFetch` (adds the CSRF header for POST).
- [ ] **Step 2: Composer.** Multi-line textarea, Enter sends, Shift+Enter newline, 4096-character counter, disabled with `composerNotice` text when `composer.state !== "open"`. On send: add an optimistic outbound bubble (clock tick) with a fresh `clientMsgId`, clear the box, call `sendChatMessage`. `ok:false, kind:"rejected"` marks the bubble failed with the reason and a Retry button that asks for confirmation then sends again with a **new** `clientMsgId`. `kind:"unknown"` keeps the bubble pending (polling reconciles it by `client_msg_id`; never mark it failed, never resend automatically).
- [ ] **Step 3: Suggestions.** `SuggestionBar` above the composer shows up to 3 variants as chips; clicking one fills the textarea (editable) and remembers `suggestionActionId` for the send. Shown, as copyable text, even when the composer is disabled. Nothing is ever sent by clicking a suggestion alone.
- [ ] **Step 4: Bubble states:** clock (pending), one tick (sent), two ticks (delivered), blue two ticks (read), red "Not sent: <error>" (failed), "May not have been delivered" for an error starting with `may have been delivered` (Review Focus 4).
- [ ] **Step 5: Verify:** `cd frontend && npx tsc --noEmit && npm run lint` -> clean; `make frontend-build` -> success.
- [ ] **Step 6: Browser check** (`make up seed`, set the dev company to `outbound_mode=send` as `make sim-demo` does, `make frontend`): simulate an inbound, open the chat, type and send, see the bubble go clock -> sent; a second inbound older than 23 h (insert via the simulator with an old `sent_at`) shows the closed-window notice and a disabled composer; double-clicking send creates one bubble. Screenshot evidence.
- [ ] **Step 7: Commit** `feat(chats): WhatsApp-style composer, suggestions and send states`.

---

### Task 9: Simulator scenario, go-live docs, gates and retro

**Files:**
- Modify: `backend/app/dev/simulate.py` (dashboard-send scenario for `make sim-demo`), `docs/go-live-channels.md` (Chats go-live steps), `docs/PROGRESS.md`, `docs/build-plan.md` if it lists milestones
- Create: `reports/2026-11-24-whatsapp-chats-retro.md`

- [ ] **Step 1: Extend `make sim-demo`:** after the existing WhatsApp inbound, post a chat send through the API in send mode and assert one outbound `messages` row (`delivery_status=sent`, `provider_msg_id` set), one `sends` row with key prefix `chat:`, and no pipeline row for it.
- [ ] **Step 2: Docs for go-live (ops, no code):** in `docs/go-live-channels.md` add: register the client's number on the Cloud API as a plain number (no coexistence, no phone app after registration); Meta business verification and display-name approval first; subscribe the webhook to `messages` (statuses included); run `make live-check k=outbound`; only then set `outbound_mode=send`; confirm the chat webhook shows delivered/read ticks in the dashboard.
- [ ] **Step 3: Run the gates from the repo root:** `make check` -> all green; `make cov` -> coverage floors hold; `make audit` -> no new advisory; `make smoke` -> stack up, logs clean; `make sim-demo` -> assertions pass. Quote the result lines in the final report.
- [ ] **Step 4: G3:** run `estateos-reviewer` and `estateos-security` on the whole branch diff (security is mandatory: api, sender, external input). Fix blockers; list non-blockers in the PR description.
- [ ] **Step 5: `/retro`:** write `reports/2026-11-24-whatsapp-chats-retro.md` (what slowed us down, missing knowledge, repeats, what a hook or test should have caught) and land each answer as an artifact in the same change.
- [ ] **Step 6: Commit** `docs(chats): go-live steps, simulator scenario and retro`. Do not push; the owner decides.

---

## Open questions for the owner

1. **Frontend tests:** the dashboard has no test runner, so chat UI logic is verified by `tsc`, lint, build and a browser check. Adding `vitest` (dev dependency; the repo's hook asks before dependency changes) would let `lib/chats.ts` helpers get real tests. Recommended: yes, in Task 4 step 1.
2. **Branch:** plan assumes a new branch `m-chats` from `dev`. Say if you prefer another name.
