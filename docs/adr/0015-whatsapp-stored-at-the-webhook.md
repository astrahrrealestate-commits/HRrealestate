# ADR 0015: WhatsApp is stored at the webhook and kept apart from the case pipeline

Date: 2026-11-25 · Status: accepted (requested by the user on 2026-11-25: every WhatsApp message must be in the Chats
UI; WhatsApp must not be handled like mail that is selected before it is shown; WhatsApp chats that are not tenant or
property business must not mix into the case context)

## Context
Email is filtered on purpose: Harjot sees what the pipeline decides matters. WhatsApp is the opposite. The Chats page is
his WhatsApp, so it must show every message, in every chat, the moment it arrives. Two things stood in the way.

1. **Late storage.** The webhook stored only a `raw_events` row; the `process_event` workflow wrote the `messages` row.
   That workflow runs on the shared `pipeline` queue (4 slots per worker), behind the AI case pipeline and mail, and a
   message with an image did not exist until its media download succeeded (retries, then an hourly requeue).
2. **One context for everything.** Every WhatsApp message went through understand, link-to-case and propose, and into
   inbox threads, page memory and message search. His own phone chat app also carries personal and unrelated chats; those
   would open cases, get proposals and pollute the context the Super Agent reads.

## Decision
**Store at the webhook.** The webhook writes the `messages` row for an inbound message in the same transaction as its
`raw_events` row (`app/ingestion/early_store.py`): no network, no model call, one idempotent insert from the same cleaned
payload the worker re-parses. `process_event` keeps its shape (normalise, media, route); its `save_message` completes the
row (adds the attachment, or `meta.media_error`) instead of inserting a second one. The raw event stays `pending` until
the worker finishes, so the requeue sweep and the media retry budget are unchanged.

**Only known contacts reach the pipeline.** A WhatsApp message goes to the case pipeline only when the sender is the
owner's own number (his commands) or a contact the directory really knows (`app/db/known_contacts.py`): a current
identity of a tenant, contractor or owner, a BRIXX person, a person with a trade (utility, municipal), a lease party, or a
person with a case the pipeline already opened. A number whose conversation a case already contains also stays known (a
third party Harjot approved a message to). An ended person is still known (a tenant whose lease just ended may write about
the deposit). A person auto-created on first contact (`kind = other`, none of the above) is not known; a contact added by
hand as plain "other" is indistinguishable from it, so give such a contact a real category or trade.
Everyone else is **chat only**: the row gets `pipeline_status = skipped` (migration 0051 widens the CHECK without a long
table lock), decided once at the webhook (the worker honours it, and decides itself for a row it created). Harjot's own
messages in a chat-only chat are marked `skipped` too: the reply he types in Chats, and the echo of one he types on his
phone (the worker marks it when it stores the echo).

**Readers.** The same table, separated by rule. `not_chat_only()` (`app/db/models/ingestion.py`) is applied by every
reader that scans WhatsApp by thread, channel or text outside a case: the inbox thread list and thread view, the legacy
inbox thread builder (so a stranger's old chat is never linked into a case), page memory and page visibility, the Super
Agent's text search and contact conversation history, and the message-search window and timeline helpers. Message search
never indexes a `skipped` row (`should_index_message`). The Super Agent's read-only SQL role (`estateos_readonly`) cannot
see `skipped` rows at all: a restrictive row-level-security policy on `messages` (migration 0052) covers the base table and
`v_message_stats`. GDPR erasure of a person also redacts their chat-only rows, found by the person's WhatsApp numbers.
Readers that start from a case or a message id the pipeline handed them are unaffected. Only the Chats page, the sender
and the window rule read `skipped` rows.

## Consequences
- A message is in Chats as soon as the provider is answered, whatever state the queue, worker or model is in.
- A stranger's first message does **not** open a case, send an alert or create a person. If a new tenant writes before
  being in the directory, Harjot sees it in Chats; it enters the AI world once the directory knows the number. A
  per-chat "hand this to the AI" action is a follow-up, not built.
- Deploy order: run the migrations and replace the workers before the API goes live. An old worker ignores `skipped`
  and would route such a row to the pipeline. Rolling the migration back turns `skipped` into `done`, which makes those
  chats visible to the case world again.
- Old rows keep their status; contacts the pipeline auto-created earlier and that have no case now count as unknown for
  new messages.
- Not covered, listed in PROGRESS: a sender with no phone number (username-only WhatsApp users) and an item the parser
  cannot read stay raw events and do not appear in Chats.
