# EstateOS M2 channels: design

Date: 2026-10-06 · Status: approved in chat · Scope: M2 ingestion (WhatsApp + Gmail) **plus the channel side of M7**
(outbound adapters), built fake-first so real providers plug in at go-live with credentials + config only.
Parents: [build-plan.md](../../build-plan.md) M2/M7, [hld.md](../../hld.md) §4, [ADR 0003](../../adr/0003-whatsapp-pywa-360dialog.md).

## Goal

1. Both channels run the **real code paths end to end** today — webhook verification, raw-event dedupe, durable
   processing, normalisation to `Message`, media/attachments to storage, routing — with fake providers at the edge.
2. Going live = set credentials + `WHATSAPP_PROVIDER` / `GMAIL_PROVIDER`; `make live-check` proves the real adapters
   satisfy the same contract tests as the fakes.
3. WhatsApp and Gmail behave **in sync**: same contract, same dedupe/idempotency, same workflow shape; a parity suite
   pins it.

## Constraints

- No real WhatsApp Business or Gmail access during M2. Nothing may require it to pass G1/G2/G5.
- Payload formats follow the providers' documented shapes (Meta Cloud API webhooks; Gmail API v1 JSON; Pub/Sub push
  envelope). Fixtures are built from documented examples and redacted (`/record-fixture`).
- Production must refuse to start with any fake provider.
- Phase 1 send rules unchanged: outbound adapters exist, but only `app/sender` (M7) may call them.

## §1 Ports (Protocols) and adapters

All ports live in `app/channels/<channel>/ports.py`; fakes in `app/channels/<channel>/fake.py`; real adapters in
`app/channels/<channel>/{cloud_api,google}.py`. Selection: `app/channels/registry.py` from settings.

| Port | Methods (sync) | Real | Fake |
|---|---|---|---|
| `WhatsAppWebhook` | `verify_handshake(mode, token, challenge) -> str`, `verify_signature(body: bytes, header: str) -> None`, `parse(body: bytes) -> list[WaEvent]` | pywa types + HMAC-SHA256 (`X-Hub-Signature-256`) | same code; app secret from test settings |
| `WhatsAppMedia` | `download(media_id) -> MediaBlob` | pywa `get_media_url` + download | serves fixture bytes by id |
| `WhatsAppOutbound` *(sender-only)* | `send_text`, `send_buttons(≤3, title ≤20)`, `send_list`, `send_template` → `provider_msg_id` | pywa client (Cloud API or 360dialog base URL) | records to fake outbox (in-memory + optional DB-less JSON log) |
| `GmailPushVerifier` | `verify(authorization_header, body) -> PushNotice` (OIDC JWT: issuer, audience, email) | google-auth `id_token.verify_oauth2_token` against Google certs | same verification against a local test RSA key + local certs |
| `GmailMailbox` | `history_since(history_id) -> HistoryPage`, `get_message(id) -> GmailMessage`, `watch(topic) -> WatchResult`, `profile() -> history_id` | google-api-python-client | in-memory mailbox emitting real Gmail API JSON (ids, threadIds, historyIds, labelIds, MIME payload) |
| `GmailDrafts` *(sender-only)* | `create_draft(thread_id, to, subject, body) -> draft_id` | `users.drafts.create` | appends to fake mailbox DRAFT label |
| `ObjectStorage` | `put(key, bytes, content_type) -> StoredObject`, `get(key) -> bytes` | boto3 S3 (EU) | local directory (dev) / memory (tests) |

`WaEvent` = typed union of `WaInbound` (text, image, document, audio, video, interactive button/list reply,
location, unsupported), `WaStatus` (sent/delivered/read/failed), `WaEcho` (Coexistence `smb_message_echoes`).
`GmailMessage` keeps id, threadId, historyId, labelIds, internalDate, headers, MIME parts.

**Import-linter additions:** `app.channels.*.outbound` / `GmailDrafts` implementations importable only by
`app.sender` (existing contract, extended to `app.channels.gmail.drafts`); `app.dev` (simulator) importable by nothing
in `app` except itself.

## §2 Inbound flows (shared shape)

```
webhook ─verify─▶ resolve channel_account → company ─▶ INSERT raw_events ON CONFLICT DO NOTHING
                                                        + DBOSClient.enqueue_in_transaction(process_event, id, wf_id="evt:{raw_event_id}")
                                                        (one transaction) ─▶ 200
worker: process_event(raw_event_id)
  step normalise   → Message (+ attachments: download → sha256 → storage)   [channel-specific normaliser]
  txn  persist     → messages / attachments rows (unique channel+provider_msg_id), raw_event.status=processed
  step route       → owner identity? enqueue owner_reply(message_id) : enqueue pipeline_entry(message_id)
```

- **WhatsApp:** one webhook POST may carry many entries/changes/messages → one `raw_event` per WhatsApp message id
  (`provider_msg_id = wamid`). Statuses update an outbound `messages` row's delivery state (no new raw_event workflow;
  stored as `raw_events` with provider id `status:{wamid}:{status}` for audit). Echoes → `direction=outbound` message.
- **Gmail:** push (OIDC-verified) is a notification, not a message, so it writes no `raw_event`; it enqueues
  `gmail_sync(channel_account_id)` with wf id `gsync:{account}:{historyId}`. `gmail_sync` reads `gmail_sync_state`,
  walks `history_since`, writes one `raw_event` per new message id (dedupe), enqueues `process_event` for each, then
  advances `history_id` (in the same transaction as the raw_event inserts). `SENT`-labelled → `direction=outbound`.
  Expired history id (404) → full resync from `profile()` (bounded window) — tested with the fake.
- **Normalisation:** Gmail body = `text/plain` part if present else HTML→text (inscriptis); quoted reply and signature
  stripped (mail-parser-reply, languages `de`,`en`); attachments stored. WhatsApp text/caption; interactive replies
  keep the button id in `Message.text` metadata for the owner handler (parsed by `ButtonId`).
- `pipeline_entry` and `owner_reply` are **stubs** in M2 (record + log); M4/M7 fill them.

## §3 Scheduled work

`gmail_watch_renew` — daily DBOS schedule: for each Gmail channel account, `watch()` and store `watch_expires_at`.
Fake returns expiry now+7d. Also `gmail_backfill` hourly safety net: `history_since(last)` even without a push
(covers lost pushes).

## §4 Configuration and safety

`Settings` additions: `whatsapp_provider: Literal["fake","cloud_api","360dialog"] = "fake"`,
`gmail_provider: Literal["fake","google"] = "fake"`, `whatsapp_app_secret`, `whatsapp_verify_token`,
`gmail_pubsub_audience`, `gmail_pubsub_service_account`, `storage_backend: Literal["local","s3"] = "local"`,
`storage_local_dir`. Startup check: `env == "prod"` and any fake/local → refuse to start (API and worker).
Outbound credentials stay in `SenderSettings`.

## §5 Simulator (dev only, `app/dev/`)

`python -m app.dev.simulate wa --from <e164> --text <t> [--image path] [--button apr:<id>:ok]`
→ builds a Cloud API webhook body, signs it with the dev app secret, POSTs to `/webhooks/whatsapp`.
`python -m app.dev.simulate gmail --from <email> --subject <s> --body <b> [--attach path] [--reply-to <thread>]`
→ appends a MIME message to the fake mailbox store (JSON files under `storage_local_dir/fake_gmail/`, shared by
API and worker; tests use an in-memory store) and POSTs a signed Pub/Sub push.
`make sim-demo` runs a scripted conversation across both channels against `make up` and asserts rows.

## §6 Testing

- **Unit:** each parser/normaliser over every recorded fixture (syrupy snapshots of resulting `Message`); HMAC and JWT
  verification (valid, wrong secret, tampered body, expired, wrong audience); MIME edge cases (HTML-only, nested
  multipart, base64url, charset latin-1, German quotes "Am … schrieb …", attachments, inline images).
- **Integration:** webhook → raw_event → workflow → messages rows (dedupe on duplicate delivery; multi-message
  webhook; status updates; echoes), Gmail push → sync → rows (duplicate push, out-of-order history, expired history
  id), storage of attachments, owner routing, prod-refuses-fake.
- **Parity suite:** same scenario (tenant reports broken heating, sends photo, owner replies) via WA and via Gmail →
  equivalent `Message` rows, one raw_event per provider message, one workflow per raw_event.
- **Port contract tests:** `tests/contract/` run each port's behavioural contract against the fake always and the
  real adapter when marked `live` (`make live-check`, needs credentials; deselected by default).
- **G5:** `make sim-demo` against the compose stack.

## Data changes

Migration `0002`: `messages.delivery_status` (nullable enum sent/delivered/read/failed) +
`messages.metadata jsonb default '{}'` (interactive reply ids, Gmail labelIds/headers subset). No other schema change
(`gmail_sync_state`, `channel_accounts`, `raw_events` exist from M1).

## Out of scope

BRIXX directory/identity resolution (M3 — M2 sets `person_id = NULL`), AI (M4+), sender approval logic (M7), outcome
labelling (M8). Live provider onboarding (M0).
