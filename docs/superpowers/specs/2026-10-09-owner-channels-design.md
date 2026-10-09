# Owner channels: morning email + Google Chat bot (alongside WhatsApp)

Date: 2026-10-09 · Status: **implemented** · Decision (user, 2026-10-09): morning digest email in
Gmail **plus** an interactive Google Chat bot. WhatsApp stays supported. Parent: [phase-1 agents design](2026-10-07-estateos-phase1-agents-design.md).

## Goal

Harjot works from Gmail and Google Chat instead of (or besides) WhatsApp: one morning email with everything that needs
him, an interactive Chat bot for approvals and commands, and the useless mail left alone. Phase 1 still sends nothing
to tenants: only Gmail drafts, and messages to Harjot.

## What exists vs. what changes

Today the owner channel is WhatsApp-shaped: `app/owner/cards.py` builds WhatsApp JSON, `app/sender/execute.py`
`send_to_owner` takes a WhatsApp payload builder and applies the 24 h window, `owner_reply` reads WhatsApp button ids.
The pipeline, approvals, rules, tasks, waits, briefing facts and commands are channel-free already.

| Piece | Change |
|---|---|
| **OwnerMessage** (new, `app/owner/model.py`) | Channel-neutral message: `text` blocks + `choices[(button_id, label)]` + optional `kind`. Button ids stay `ButtonId` (`apr:<id>:<choice>`, `doc:<id>:<choice>`). `cards.py` builds `OwnerMessage`, not WhatsApp JSON. |
| **Renderers** | `whatsapp` (today's payloads, unchanged output; snapshot-tested), `google_chat` (cardsV2 with buttons), `email` (HTML + plain text). |
| **OwnerChannel port** (new, `app/sender/owner_channels.py`) | `deliver(OwnerMessage, owner) -> provider_ref`, per-channel window rules (WhatsApp: 24 h outbox; Chat/email: none). `send_to_owner(deps, company, key, OwnerMessage)` picks the interactive channel(s) from the owner's settings. Idempotency (`sends.idempotency_key`) and the allowlist stay in `app/sender`. |
| **Owner settings** | `owner_accounts` gains `chat_user` (Google Chat user resource, for DMs) and `interactive_channel` (`whatsapp` \| `google_chat`, default whatsapp). `email` already exists and is the digest address. Migration 0008. |
| **Channel enum** | `Channel` gains `google_chat` (inbound Chat events are stored as `raw_events`/`messages`, routed to `owner_reply` exactly like a WhatsApp tap). CHECK constraints widened in the same migration. |

## Morning email (digest)

- Timer `briefing.daily` (07:30 company tz) sends **one email to `owner_accounts.email`** in addition to the interactive
  channel's short briefing. Weekly (Friday 16:00) likewise.
- Content (from the existing briefing facts + proposals): **Needs your reply** (per case: who, one-line situation,
  urgency, the 2–3 Dutch reply drafts, "open thread" link), **Decisions waiting** (non-reply approvals), **Tasks due**,
  **Waiting on others / chasers due**, **Exceptions**. Mail triaged as spam/other/low-value with no action is **left
  out**; one line says "N messages ignored" and lists nothing else.
- If the owner has no interactive channel configured, the first draft of each reply is created in the Gmail thread
  (as today after approval) so he can edit and send from Gmail; the email links to it.
- Sending: a new `Plan` kind "email to the owner" in `app/sender`; the allowlist accepts only `owner_accounts.email`.
  The Gmail `compose` token already allows sending. Replies to the digest are **not** read as commands (the From
  header is spoofable; see `process._route`).

## Google Chat bot

- **Outbound:** Chat API `spaces.messages.create` as the Chat app (service-account auth, scope `chat.bot`), DM space
  per owner. Cards: draft text sections + buttons (`Send draft 1/2/3`, `Edit`, `Reject`), document-review menu.
- **Inbound:** `POST /webhooks/googlechat`. Every request is verified (Google-signed JWT: issuer
  `chat@system.gserviceaccount.com`, audience = the Chat app's project number; same pattern as the Pub/Sub push
  verifier). Event types: `MESSAGE` (text → command/question/edit text), `CARD_CLICKED` (button parameter = `ButtonId`).
  Unknown sender (not an `owner_accounts.chat_user`) is ignored and logged. Record the event first, enqueue
  `process_event` (Postgres before work), answer 200 fast.
- **Edit flow, commands, Q&A, tasks:** unchanged; they run in `owner_reply` on the stored message.
- **Setup:** Chat API enabled in Harjot's Workspace project, a Chat app configured with the HTTPS endpoint, installed
  for Harjot (DM). Needs a public HTTPS endpoint, so full end-to-end testing waits for deployment (or a tunnel);
  everything before that is tested with recorded Chat events and fakes.
- A personal Gmail account cannot host a custom Chat app (to be verified at setup); the test mailbox covers the email
  digest, Harjot's Workspace covers Chat.

## Build order (each step shippable, TDD, G1/G2)

1. `OwnerMessage` + WhatsApp renderer; move cards/briefing/commands replies onto it. **No behaviour change**: the
   WhatsApp payload snapshots stay identical.
2. Owner settings + migration 0008 (`chat_user`, `interactive_channel`, `Channel.google_chat`).
3. Email renderer + owner-email send path + the digest (daily + weekly), idempotent per day; "ignored" counting;
   Gmail draft for the no-interactive-channel case. Testable live on the personal mailbox.
4. Google Chat adapter: renderer, outbound client (port + fake), inbound webhook + verifier + event parsing, owner
   routing, contract tests with recorded payloads.
5. Docs: go-live Chat section (project, app config, scopes, endpoint), env settings, live checks.

## Testing

Unit: renderers (snapshots), event parsing, verifier (valid/expired/wrong audience/wrong issuer), digest content
rules (what is left out). Integration: digest end to end with fakes (one email per day; replay sends once; owner-only
allowlist; a tenant address is refused), Chat tap → single Gmail draft, Chat message → command reply, unknown Chat
sender ignored. Live: `make live-check k=digest` (sends the digest to the mailbox itself), `k=chat` (one DM).

## Out of scope

Replacing WhatsApp (it stays selectable), replying to the digest email as a command channel, Chat spaces with several
people, reading attachment contents, any message to a tenant.

## Open points & Resolution

1. **Workspace policy**: Harjot/admin enables custom Google Chat bot in Workspace. Webhook is `POST /webhooks/googlechat`.
2. **Digest language**: English for the digest framing, Dutch for reply drafts and tenant-facing content.
3. **Empty days**: Digest email is sent ONLY when there is at least one item requiring attention (`replies`, `decisions`, `tasks`, `waiting`, or `exceptions`).

## Implemented Architecture

1. **Triage Filter (`app/pipeline/understand.py`, `app/pipeline/propose.py`)**:
   - `requires_reply: bool` field added to understanding contract and prompt.
   - Proposer skips generating actions/drafts if `not requires_reply and not suspicious`.
2. **Channel-Neutral Message Model (`app/contracts/owner.py`)**:
   - `OwnerMessage`, `OwnerChoice` contracts.
   - Renderers: `render_whatsapp` (WhatsApp list/button format, byte-identical to previous snapshots), `render_google_chat` (cardsV2 format with button actions).
3. **Database Migration (`0008_owner_channels_chat_and_email.py`)**:
   - Added `chat_user: str | None`, `interactive_channel: InteractiveChannel` (`whatsapp` | `google_chat`) to `owner_accounts`.
   - Widened `Channel` enum check constraints to permit `google_chat`.
4. **Morning Email Digest (`app/owner/digest.py`, `app/workflows/briefings.py`)**:
   - Morning digest (07:30 company tz) and Friday summary (16:00).
   - Collects reply proposals, non-reply approvals, due tasks, open waits, and exceptions.
   - Displays "N messages ignored" for triaged mail requiring no response.
   - If no interactive channel is configured, automatically drafts the first Dutch reply in the Gmail thread.
   - Delivered to `owner_accounts.email` via Gmail drafts/send pipeline with allowlist enforcement.
5. **Google Chat Bot (`app/channels/google_chat/`, `app/api/webhooks/google_chat.py`)**:
   - Endpoint: `POST /webhooks/googlechat` verifying Bearer JWT from `chat@system.gserviceaccount.com`.
   - Message and card click events parsed into standard `RawEvent` / `MessageRow` records.
   - Sender routing in `app/ingestion/process.py` directs events from `OwnerAccount.chat_user` to `"owner"`, triggering `owner_reply` workflow.
   - Interactive buttons (`Send draft 1/2/3`, `Edit`, `Reject`, document review) trigger workflow execution and Gmail draft creation.
