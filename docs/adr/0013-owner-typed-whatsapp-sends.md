# ADR 0013: Owner-typed WhatsApp sends from the Chats page

Date: 2026-11-24 · Status: accepted (requested by the user on 2026-11-24; spec
[2026-11-24-whatsapp-chats-design.md](../superpowers/specs/2026-11-24-whatsapp-chats-design.md))

## Context
The client uses only the dashboard. Until now a WhatsApp message to a tenant could leave EstateOS in one way: an
AI-proposed `reply_draft` that Harjot approved, through `backend/app/sender/` (ADR 0006, invariant 5). The contacts
route `POST /contacts/{id}/whatsapp/send` answers 501 on purpose, because the old frontend recorded sends that never
happened. The new Chats page (WhatsApp Web style) needs Harjot to type his own message to a contact and send it, or he
goes back to his phone and the AI loses sight of half the conversation.

## Decision
Owner-typed send is a **second allowed send class**, in `backend/app/sender/owner_chat.py`:
- It is Harjot's own click on text he typed. No AI draft is involved, so no approval row exists; the click is the
  approval. The Super Agent still cannot send, approve or type on his behalf.
- AI-drafted actions are unchanged: they still need his approve click, `draft_version`, and the full tenant gate.
- The recipient comes from the DB only: the `thread_ref` of the stored outbound `messages` row. The request names a
  chat, never a free-form number. The number must have written to this company before (an unknown number with no
  `Person` can be answered; a roommate who never wrote cannot be written to first), must not be the owner's or any
  company-account number, and its newest inbound message must be inside the 23 h window.
- Same gates as every send: company not paused, `outbound_mode = send`, `sends.idempotency_key`
  (`chat:{company_id}:{client_msg_id}`, also the DBOS workflow id), a `sends` row claimed before the provider call,
  and an ambiguous provider failure is recorded as failed and never retried automatically.
- Its own cap: `owner_chat_sends_per_hour` (default 200 per company). It neither consumes nor is blocked by the
  AI-draft cap (`tenant_sends_per_hour`).
- The API stores the outbound row (Postgres first) and enqueues; the sender trusts nothing but that row, and re-derives
  the recipient and re-checks the gates right before the claim (`assert_chat`, as `assert_tenant`).

## Consequences
- CLAUDE.md invariant 5, the dashboard spec section 5, `docs/standards/security.md` and `docs/PROGRESS.md` say there
  are two send classes. Only `app/sender/` is still allowed to import send credentials or `app.channels.*.outbound`.
- No templates yet: outside the 23 h window the composer is refused with the reason; starting a conversation with a
  number that never wrote is not possible. Template sends need an ADR of their own.
- The WhatsApp number must be a plain Meta Cloud API number (Meta direct or 360dialog). With **no coexistence** the
  number cannot also run in the WhatsApp Business app, so Harjot's replies from the phone do not exist; every outbound
  message is one of ours, and the Chats page is where he sees the whole conversation. If coexistence is chosen later,
  business-app echoes arrive as outbound rows and must not be confused with our pending rows (they carry no
  `client_msg_id`).
- A worker that dies mid-call leaves a `sending` row; the next attempt settles it as failed after 30 minutes and the
  bubble shows it did not confirm. Harjot checks the chat before resending by hand.
- Typed text is not run through the AI output guard (it is his own text); the Cloud API's own 4,096-character limit
  is enforced and the text is never trimmed.
