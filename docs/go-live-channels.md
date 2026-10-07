# Going live with WhatsApp, Gmail and S3

EstateOS runs on fake providers until go-live. Going live changes **configuration only**: credentials and provider
switches in the environment. Code, database and workflows stay the same. `make live-check` proves each real adapter
works before traffic is switched over. Prod startup refuses fake providers, local storage and missing secrets
(`app/core/startup.py`), so a half-configured deploy fails at boot instead of silently dropping mail.

## Order of operations

Providers can only deliver to a running API (Meta verifies the webhook with a live handshake; Pub/Sub pushes to the
endpoint), so the API is deployed **before** deliveries are connected.

1. **Rows.** Create the company, its channel accounts and the owner ([Onboarding rows](#onboarding-rows)).
   Deliveries for unknown numbers or mailboxes are acknowledged and logged, but create no work.
2. **Credentials and settings** for [S3](#s3), [Gmail](#gmail) steps 1–5 and [WhatsApp](#whatsapp) (tokens, secrets),
   without connecting any delivery yet.
3. **Checks that need no inbound traffic:**
   `make live-check k="storage or mailbox or certs or draft or text_to_owner"`.
4. **Deploy** with `ENV=prod`. Startup refuses to boot while any required setting is missing or still fake.
5. **Connect deliveries:** the WhatsApp webhook (Meta dashboard / 360dialog API) and the Gmail push subscription
   (Gmail step 6). Then register the Gmail watch: `make live-check k=watch` calls `users.watch`; the worker's daily
   `gmail.watch_renew` (03:00 Europe/Berlin) also does, and records the cursor. Until a cursor is recorded, the
   first sync reads the last day of mail (duplicates are ignored).
6. **Checks that need inbound traffic:** send a WhatsApp image and an email to the business number and mailbox.
   Each must produce a `raw_events` row and an `evt:` workflow (`make workflows`). Take the image's
   `<phone_number_id>:<media id>` from its `raw_events.payload` and run `make live-check k=media`.

`make live-check` without the needed settings stops before any provider call and lists them, for example
`live-check: missing GMAIL_CREDENTIALS_FILE, S3_BUCKET (see docs/go-live-channels.md)`. Settings may come from
the environment or `.env`; the `LIVE_*` variables exist only for the check and must be exported in the shell.

## S3

| Variable | Value |
|---|---|
| `STORAGE_BACKEND` | `s3` |
| `S3_BUCKET` | bucket in an EU region; private, versioning on, SSE on |
| `S3_REGION` | e.g. `eu-central-1` |
| `S3_ENDPOINT_URL` | empty for AWS; set for S3-compatible providers |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | key limited to `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on this bucket; empty when an instance role provides credentials |

The live check writes and reads `live-check/probe.txt` (overwritten each run).

## Gmail

Harjot's mailbox is read through a Google Workspace **internal** OAuth app (no Google verification needed for
internal apps). Two separate credential files keep reading and drafting apart.

1. In Harjot's Workspace, create a Google Cloud project. Enable the **Gmail API** and **Cloud Pub/Sub API**.
2. OAuth consent screen: user type **Internal**. Create an OAuth client of type **Desktop app** and download
   `client.json`.
3. Create the two authorized-user files (OAuth refresh tokens), signed in as the mailbox owner: one with scope
   `gmail.readonly`, one with `gmail.compose`. Store both on the server outside the repository, readable only by
   the app user.

   > **Open decision (scope width):** `gcloud auth application-default login --scopes=…` also requires the
   > `cloud-platform` scope, so files made that way can act on Harjot's whole Google Cloud account if stolen. A
   > minimal-scope alternative is a ten-line consent script using `google-auth-oauthlib` (`InstalledAppFlow`) —
   > a new dev dependency that needs approval. Until decided, do not create these files with `gcloud`.
4. Pub/Sub topic, e.g. `projects/<project>/topics/gmail-estateos`. Grant
   `gmail-api-push@system.gserviceaccount.com` the **Pub/Sub Publisher** role on the topic.
5. Create a service account for push authentication (no keys needed), e.g. `gmail-push@<project>.iam.gserviceaccount.com`.
6. Push subscription on the topic:
   - endpoint `https://<api host>/webhooks/gmail/push`
   - **Enable authentication** with the service account from step 5
   - audience: set it explicitly (for example the endpoint URL) and use the same value below
   - acknowledgement deadline 60 s; retry policy exponential backoff

| Variable | Value |
|---|---|
| `GMAIL_PROVIDER` | `google` |
| `GMAIL_CREDENTIALS_FILE` | path to the `gmail.readonly` authorized-user file (step 3) |
| `GMAIL_SEND_CREDENTIALS_FILE` | path to the `gmail.compose` authorized-user file (read only by `app/sender`) |
| `GMAIL_PUBSUB_TOPIC` | `projects/<project>/topics/gmail-estateos` |
| `GMAIL_PUBSUB_AUDIENCE` | the audience configured on the push subscription |
| `GMAIL_PUBSUB_SERVICE_ACCOUNT` | the push service account email (step 5) |
| `LIVE_GMAIL_MAILBOX` *(check only)* | Harjot's mailbox address |

The live checks: read history and recent mail with the read-only credentials (and confirm they belong to that
mailbox), register the watch on the topic, fetch Google's push signing certs, and create **one** draft addressed to
the mailbox itself as a reply in the newest thread (Re: subject, In-Reply-To, References — exactly like production
drafts; reruns reuse it, delete it any time).

Behaviour to know: the watch expires after 7 days and is renewed daily; an hourly backfill catches pushes that
never arrived; if the mailbox history cursor expires (long outage), the next sync re-reads the last 7 days and
duplicates are ignored.

## WhatsApp

The provider decision is still open (Meta Cloud API directly, or 360dialog). Both are supported; set one.

### Meta Cloud API (`WHATSAPP_PROVIDER=cloud_api`)

1. Meta Business app with the WhatsApp product; a registered business phone number.
2. System user with `whatsapp_business_messaging` permission; generate a permanent token.
3. App → WhatsApp → Configuration → Webhook: callback `https://<api host>/webhooks/whatsapp`, verify token = the
   value of `WHATSAPP_VERIFY_TOKEN`. Subscribe to the `messages` field, and to `smb_message_echoes` when the number
   runs in Coexistence (Harjot's replies from the WhatsApp Business app arrive as echoes).
4. Subscribe the app to the WhatsApp Business Account, otherwise a production WABA delivers no webhooks:
   `POST https://graph.facebook.com/<version>/<WABA_ID>/subscribed_apps` with the system user token.

| Variable | Value |
|---|---|
| `WHATSAPP_PROVIDER` | `cloud_api` |
| `WHATSAPP_API_BASE_URL` | `https://graph.facebook.com/v21.0` (or the current Graph version) |
| `WHATSAPP_APP_SECRET` | the Meta app secret (verifies `X-Hub-Signature-256`) |
| `WHATSAPP_VERIFY_TOKEN` | any long random string, also entered in the Meta dashboard |
| `WHATSAPP_MEDIA_TOKENS` | `{"<phone_number_id>": "<system user token>"}` (inbound media download) |
| `WHATSAPP_ACCESS_TOKEN` | system user token for sending (read only by `app/sender`) |
| `WHATSAPP_PHONE_NUMBER_ID` | the business number's phone_number_id |

### 360dialog (`WHATSAPP_PROVIDER=360dialog`)

| Variable | Value |
|---|---|
| `WHATSAPP_PROVIDER` | `360dialog` |
| `WHATSAPP_API_BASE_URL` | `https://waba-v2.360dialog.io` |
| `WHATSAPP_APP_SECRET` | the 360dialog **partner platform secret** (verifies `x-360dialog-signature`) |
| `WHATSAPP_VERIFY_TOKEN` | any long random string. 360dialog has no handshake, but prod startup requires it for every provider |
| `WHATSAPP_MEDIA_TOKENS` | `{"<phone_number_id>": "<D360-API-KEY>"}` |
| `WHATSAPP_ACCESS_TOKEN` | the number's `D360-API-KEY` (read only by `app/sender`) |

Set the webhook URL `https://<api host>/webhooks/whatsapp` through 360dialog's webhook configuration API.

> **Open decision:** 360dialog signs messaging webhooks only with a partner **platform secret**. A direct 360dialog
> customer without one receives unsigned webhooks, and EstateOS rejects every unsigned delivery (401) by design.
> Going live on 360dialog therefore needs either the platform secret, or a decision to accept 360dialog's
> custom-header authentication instead (not implemented). Meta Cloud API has no such gap.

### Owner template (both providers)

WhatsApp only allows free-form messages to Harjot within 24 hours of his last message. Outside that window EstateOS
holds owner messages (approval cards, briefings, alerts) in `owner_outbox` and sends **one** template instead; his
next message (any text or tap) delivers everything that waited, oldest first.

1. Create and get approval for a **utility** template named `estateos_pending`, language `en`, body
   `You have {{1}} items waiting in EstateOS. Reply to see them.` (one body parameter: the number of items).
2. Different name or language → set `OWNER_TEMPLATE_NAME` / `OWNER_TEMPLATE_LANGUAGE`.
3. Until the template is approved, owner messages outside the window are not delivered (the provider rejects the
   template); they stay queued and flush on Harjot's next message.

## LLM

Agents run on deterministic offline models until `LLM_MODEL` is set (default `fake`; prod refuses it).

| Variable | Value |
|---|---|
| `LLM_MODEL` | Pydantic AI model string, e.g. `openai:gpt-4.1-mini` (OpenAI project with EU data residency) |
| `OPENAI_API_KEY` | required for `openai:*` models |
| `LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | optional: every agent run traced to Langfuse (EU) |

After switching, run `make eval agent=understanding version=v1` and compare with the fake-model report.

### Live checks

| Variable *(check only)* | Value |
|---|---|
| `LIVE_WHATSAPP_OWNER` | Harjot's number in E.164 (`+49…`). Must be the owner of the company that owns the sending number, read from the database at `DATABASE_URL` — point it at **prod** for this check; any other number is refused. Then the check sends him one text, "EstateOS live-check ✓". For `cloud_api`, `WHATSAPP_PHONE_NUMBER_ID` is also required. |
| `LIVE_WHATSAPP_MEDIA` | `<phone_number_id>:<media_id>` of an image sent to the business number after go-live (from `raw_events.payload`; media ids expire after about 30 days) |

Free-form text needs an open 24-hour service window: Harjot messages the business number first. Phase 1 never
messages tenants; the live check messages only the owner.

## Onboarding rows

Until an admin command exists (M3), create the rows once with `psql`. Ids follow the UUIDv7 convention: generate
one per row with `uv run python -c "from app.core.ids import new_id; print(new_id())"`.

```sql
INSERT INTO companies (id, name) VALUES ('<id 1>', 'Hausverwaltung …');
INSERT INTO channel_accounts (id, company_id, channel, address, is_owner_channel) VALUES
  ('<id 2>', '<id 1>', 'whatsapp', '<phone_number_id>', false),
  ('<id 3>', '<id 1>', 'gmail', '<mailbox address, lower case>', false);
INSERT INTO owner_accounts (id, company_id, display_name, whatsapp_e164, email) VALUES
  ('<id 4>', '<id 1>', 'Harjot', '+49…', '<owner email>');
```

## Rollback

Stop each provider from delivering, then redeploy the previous configuration:

- **WhatsApp:** remove the webhook URL in the Meta / 360dialog dashboard.
- **Gmail:** delete the push subscription. The hourly backfill and the daily watch renewal keep running (they only
  read mail and re-register the watch). To stop them in a way that survives restarts, revoke EstateOS's access in
  Harjot's Google account (Security → third-party access) or remove the credential files: both jobs then fail for
  that mailbox, are logged, and affect nothing else. Pausing their DBOS schedules works only until the next worker
  start, because the worker re-applies all schedules at launch.

Prod refuses fake providers, so a full return to fakes means leaving prod (`ENV=dev`, `*_PROVIDER=fake`) on that
host. Deliveries already received stay in `raw_events` / `messages`.

## Recovering failed events

Processing retries for about 10 minutes inside one run, then the hourly requeue reruns the event up to 5 more
times (about 5 hours). A WhatsApp media outage that outlasts this costs only the photo: the last rerun stores the
message with `meta.media_error`. Other failures that outlast it (for example Gmail unreachable for hours) leave the
raw event `failed` and log `ingest.requeue_exhausted` at error level (alert on it). After fixing the cause, reset
those events and the next hourly sweep (minute 41) reruns them:

```sql
UPDATE raw_events SET attempts = 0
 WHERE status = 'failed' AND last_error LIKE 'requeue:%' AND attempts >= 5
   AND received_at > now() - interval '7 days';
```

Failures without the `requeue:` prefix are data problems (unroutable sender, unreadable payload) and are final.
Events stuck in `pending` for over an hour (for example a deploy during an outage) are rerun by the same sweep.
