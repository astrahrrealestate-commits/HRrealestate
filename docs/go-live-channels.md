# Going live with WhatsApp, Gmail and S3

EstateOS runs on fake providers until go-live. Going live changes **configuration only**: credentials and provider
switches in the environment. Code, database and workflows stay the same. `make live-check` proves each real adapter
works before traffic is switched over. Prod startup refuses fake providers, local storage and missing secrets
(`backend/app/core/startup.py`), so a half-configured deploy fails at boot instead of silently dropping mail.

## Order of operations

Providers can only deliver to a running API (Meta verifies the webhook with a live handshake; Pub/Sub pushes to the
endpoint), so the API is deployed **before** deliveries are connected.

1. **Rows.** Create the company, its channel accounts and the owner ([Onboarding rows](#onboarding-rows)).
   Deliveries for unknown numbers or mailboxes are acknowledged and logged, but create no work.
2. **Credentials and settings** for [S3](#s3), [Gmail](#gmail) steps 1–5, [WhatsApp](#whatsapp) (tokens, secrets),
   [Drive](#drive-document-filing), the [LLM](#llm) and [BRIXX](#brixx-data-mirror) (its IP whitelist takes the
   longest: ask early), without connecting any delivery yet.
3. **Checks that need no inbound traffic:**
   `make live-check k="storage or mailbox or certs or draft or text_to_owner or drive or llm"`.
4. **Deploy** with `ENV=prod`. Startup refuses to boot while any required setting is missing or still fake.
5. **Connect deliveries:** the WhatsApp webhook (Meta dashboard / 360dialog API) and the Gmail push subscription
   (Gmail step 6). Then register the Gmail watch: `make live-check k=watch` calls `users.watch`; the worker's daily
   `gmail.watch_renew` (03:00 Europe/Amsterdam) also does, and records the cursor. Until a cursor is recorded, the
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
3. Create the two authorized-user files (OAuth refresh tokens), signed in as the mailbox owner:

   ```
   make gmail-consent client=~/.estateos/client.json mailbox=<mailbox> out=~/.estateos
   ```

   Two browser consents follow: the first writes `gmail-read.json` (`gmail.readonly`), the second
   `gmail-compose.json` (`gmail.compose`). Grant every requested permission and nothing else. The tool refuses to
   write when the account is not `<mailbox>`, when the granted scopes differ from the requested ones, or when the
   output directory is inside the repository. Files are 0600. On a server, copy them outside the repository,
   readable only by the app user. Do not use `gcloud auth application-default login` for this: it forces the
   `cloud-platform` scope, so a stolen file could act on the whole Google Cloud account.

   An External app in **Testing** status (consumer Gmail test mailbox) issues refresh tokens that expire after
   7 days: rerun the command weekly. Internal Workspace apps have no such expiry.
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
| `GMAIL_CREDENTIALS_FILE` | path to the `gmail.readonly` authorized-user file (step 3: `gmail-read.json`) |
| `GMAIL_SEND_CREDENTIALS_FILE` | path to the `gmail.compose` authorized-user file (`gmail-compose.json`; read only by `backend/app/sender`) |
| `GMAIL_REPLY_SEND_CREDENTIALS_FILE` | send mode only: path to the `gmail.send` + `gmail.metadata` authorized-user file (`gmail-reply-send.json`, created with `reply_send=1`; read only by `backend/app/sender`; separate from the compose token) |
| `TENANT_SENDS_PER_HOUR` | send mode only: tenant sends per company and hour (default 30); beyond it approvals are blocked |
| `GMAIL_PUBSUB_TOPIC` | `projects/<project>/topics/gmail-estateos` |
| `GMAIL_PUBSUB_AUDIENCE` | the audience configured on the push subscription |
| `GMAIL_PUBSUB_SERVICE_ACCOUNT` | the push service account email (step 5) |
| `LIVE_GMAIL_MAILBOX` *(check only)* | Harjot's mailbox address |
| `LIVE_WHATSAPP_TEST_TO` *(check only)* | optional: the owner's number (must equal `LIVE_WHATSAPP_OWNER`); lets the outbound check send one WhatsApp text |

The live checks: read history and recent mail with the read-only credentials (and confirm they belong to that
mailbox), register the watch on the topic, fetch Google's push signing certs, and create **one** draft addressed to
the mailbox itself as a reply in the newest thread (Re: subject, In-Reply-To, References — exactly like production
drafts; reruns reuse it, delete it any time).

Behaviour to know: the watch expires after 7 days and is renewed daily; an hourly backfill catches pushes that
never arrived; if the mailbox history cursor expires (long outage), the next sync re-reads the last 7 days and
duplicates are ignored.

### Quick local test with a real mailbox (no Pub/Sub, no public endpoint)

The worker pulls the mailbox the way the hourly backfill does; WhatsApp stays simulated, so Harjot's taps are faked
and nothing is ever sent. Approved replies become **real Gmail drafts** in the mailbox.

1. Steps 1–3 above (an External app in Testing works for a personal Gmail; add yourself as a test user), with
   `out=~/.estateos` (the stack mounts that directory read-only at `/secrets`; other directory: `ESTATEOS_SECRETS_DIR`).
2. `.env`: `GMAIL_PROVIDER=google`, `GMAIL_CREDENTIALS_FILE=~/.estateos/gmail-read.json`,
   `GMAIL_SEND_CREDENTIALS_FILE=~/.estateos/gmail-compose.json` (keep `WHATSAPP_PROVIDER` fake). Then `make up`.
3. `LIVE_GMAIL_MAILBOX=<mailbox> make live-check k="mailbox or draft"`: read access and one self-addressed draft.
4. Send the mailbox a test mail from another address (e.g. "Er lekt water uit de kraan in de keuken").
5. `make gmail-pull mailbox=<mailbox>`: registers the mailbox on the dev company and syncs **new mail only** (the
   first pull starts from now, so a real inbox's past is not ingested; `backfill=1` also reads the last day). Send
   the test mail first, then pull; run it again after each further test mail.
6. `make pending`: lists the proposals waiting for approval. `make approve n=1 choice=d1`: taps draft 1 as Harjot.
7. Open Gmail → Drafts: the reply sits in the tenant's thread. Nothing was sent; delete the draft any time.

## Switching the owner to the dashboard

`owner_accounts.interactive_channel` still defaults to `whatsapp` in code (the spec's `dashboard` default was not
applied to existing rows; it waits for the user's decision). For a dashboard-only owner, switch his row once:

```sql
update owner_accounts set interactive_channel='dashboard' where company_id=<company>;
```

Since the final review fix wave this is complete: approval cards, alerts, briefings and the results of approved
contractor requests, escalations and owner notes land in his dashboard feed (no WhatsApp message). Rollback: set it
back to `whatsapp`.

**Draft mode is of little use to a dashboard-only owner:** an approved Gmail reply becomes a Gmail draft in a mailbox
he never opens, and a WhatsApp reply becomes copy-ready text in his feed that he must paste himself. Plan the switch to
`send` (below) together with the dashboard switch.

## Switching a company to send

Until this step every approved reply stays a Gmail draft or an owner-only message: `companies.outbound_mode` defaults
to `draft`. In `send` mode an approve click sends the reply to the tenant, on the channel the tenant wrote on
(Gmail reply in the same thread, or a WhatsApp text inside the 24 h window). The mode is per company.

**Prerequisites**
1. `make live-check k=outbound` is green. It lists the missing settings and exits 2 before any provider call when
   any of `GMAIL_CREDENTIALS_FILE`, `GMAIL_REPLY_SEND_CREDENTIALS_FILE` or `LIVE_GMAIL_MAILBOX` is absent. When green it has sent one real reply **to the test mailbox itself**
   and proved that a repeated call returns the same message (no second email). With `LIVE_WHATSAPP_TEST_TO` set to the
   owner's number it also sends one WhatsApp text, and refuses any other number.
2. Harjot's written OK to send to tenants on his behalf.
3. The reply-send token: `make gmail-consent client=~/.estateos/client.json mailbox=<mailbox> out=~/.estateos reply_send=1`
   writes `gmail-reply-send.json` (scopes `gmail.send` + `gmail.metadata`, nothing else; the consent also rewrites the
   read and compose files). Set `GMAIL_REPLY_SEND_CREDENTIALS_FILE` to it and redeploy (compose maps it to
   `/secrets/gmail-reply-send.json`). Without it Gmail replies are blocked, never sent through the compose token.

**Switch** (one company):

```sql
update companies set outbound_mode='send' where id=<company>;
```

**Verify:** make a test tenant (your own address or number) write in, approve the proposed reply in the dashboard and
confirm it arrives. Check the `sends` row is `sent`. Only then tell Harjot to approve real cases.

**Rollback** (takes effect for the next send; approvals already sent cannot be recalled):

```sql
update companies set outbound_mode='draft' where id=<company>;
```

**When a send is blocked** the approval stays valid, nothing is sent, and the dashboard feed shows why:
- *WhatsApp window closed: the tenant wrote more than 23 h ago* — reply by email or wait for the tenant's next message.
- *hourly tenant send cap reached* — `TENANT_SENDS_PER_HOUR` per company; retry later or raise the setting and restart.
  The count (`backend/app/sender/tenant_gate.tenant_sends_last_hour`) is every `sends` row of the company from the last hour
  on Gmail or WhatsApp with status pending, sending or sent whose target is not an owner address, and it does not
  look at the outbound mode. Draft-mode Gmail reply drafts are such rows (target: the tenant's address), so they count;
  owner-only messages (WhatsApp texts to Harjot, digests) do not. The first hour after switching can hit the cap early.
- *Gmail sending is not configured: GMAIL_REPLY_SEND_CREDENTIALS_FILE (gmail.send) is missing* — create the token (step 3).
- Others: company paused, mode back on `draft`, the recipient is no longer the case's own contact, the draft was edited
  after approval, a body over WhatsApp's 4096 characters.
A send that failed after the provider may have accepted it is reported as "Reply may not have reached the tenant:
... delivery status unknown": check the thread before resending. If the worker died during the provider call, DBOS
re-runs the same `exec:{action}:{version}` workflow; its attempt finds the dead attempt's `sends` row still `sending`
and, while that row is under 30 minutes old, ends as `in_progress`: no alert, no follow-up wait, nothing re-sent.
Once the row is 30 minutes old the 5-minute `sweep.stranded` cron (`backend/app/sender/stuck.py`) settles it exactly once:
the send and the action are marked failed ("delivery status unknown: previous attempt never reported; check the
thread before resending it yourself") and one alert is written under `blocked:exec:{action}:{version}` (the same
key every other path uses, so a WhatsApp/Chat owner also gets one message). The settle is a conditional update, so
concurrent sweeps or a late recovered run cannot alert twice. Fresh in-flight sends are left alone; `resume` skips
them. Owner-directed messages are never settled by this sweep. Check the thread, then resend by hand if needed.

**Gmail scope caveat.** `gmail.compose` (drafts, owner digest) can technically also call `messages.send`, so OAuth
scopes alone do not stop that token from sending. The separation is enforced in code: only `backend/app/sender` holds either
token, `send_message` is limited to the owner's own addresses, and tenant replies go only through `send_reply` on the
separate reply-send token.

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
| `WHATSAPP_ACCESS_TOKEN` | system user token for sending (read only by `backend/app/sender`) |
| `WHATSAPP_PHONE_NUMBER_ID` | the business number's phone_number_id |

### 360dialog (`WHATSAPP_PROVIDER=360dialog`)

| Variable | Value |
|---|---|
| `WHATSAPP_PROVIDER` | `360dialog` |
| `WHATSAPP_API_BASE_URL` | `https://waba-v2.360dialog.io` |
| `WHATSAPP_APP_SECRET` | the 360dialog **partner platform secret** (verifies `x-360dialog-signature`) |
| `WHATSAPP_VERIFY_TOKEN` | any long random string. 360dialog has no handshake, but prod startup requires it for every provider |
| `WHATSAPP_MEDIA_TOKENS` | `{"<phone_number_id>": "<D360-API-KEY>"}` |
| `WHATSAPP_ACCESS_TOKEN` | the number's `D360-API-KEY` (read only by `backend/app/sender`) |

Set the webhook URL `https://<api host>/webhooks/whatsapp` through 360dialog's webhook configuration API.

> **Open decision:** 360dialog signs messaging webhooks only with a partner **platform secret**. A direct 360dialog
> customer without one receives unsigned webhooks, and EstateOS rejects every unsigned delivery (401) by design.
> Going live on 360dialog therefore needs either the platform secret, or a decision to accept 360dialog's
> custom-header authentication instead (not implemented). Meta Cloud API has no such gap.

### SendZen & Hookdeck (`WHATSAPP_PROVIDER=sendzen`)

SendZen is an official Meta partner providing developer-first WhatsApp Business Cloud API access.

| Variable | Value |
|---|---|
| `WHATSAPP_PROVIDER` | `sendzen` |
| `WHATSAPP_API_BASE_URL` | `https://api.sendzen.io/v1` |
| `WHATSAPP_APP_SECRET` | the SendZen webhook secret (verifies `X-Hub-Signature-256`) |
| `WHATSAPP_VERIFY_TOKEN` | any string entered for handshake verification |
| `WHATSAPP_MEDIA_TOKENS` | `{"<phone_number_id>": "<sendzen_api_key>"}` |
| `WHATSAPP_ACCESS_TOKEN` | SendZen API key (`sz_live_...`; read only by `backend/app/sender`) |
| `WHATSAPP_PHONE_NUMBER_ID` | phone number id |

Hookdeck ingestion:
1. In SendZen Dashboard, set the Webhook URL to your Hookdeck ingestion endpoint (e.g. `https://hkdk.events/mb2f57may8q2ds`).
2. In Hookdeck Dashboard, route the destination to your EstateOS endpoint: `https://<api host>/webhooks/whatsapp`.
3. Hookdeck preserves and forwards the provider's `X-Hub-Signature-256` header unchanged, ensuring HMAC-SHA256 signature verification succeeds in EstateOS.

### Owner template (both providers)

WhatsApp only allows free-form messages to Harjot within 24 hours of his last message. Outside that window EstateOS
holds owner messages (approval cards, briefings, alerts) in `owner_outbox` and sends **one** template instead; his
next message (any text or tap) delivers everything that waited, oldest first.

1. Create and get approval for a **utility** template named `estateos_pending`, language `en`, body
   `You have {{1}} items waiting in EstateOS. Reply to see them.` (one body parameter: the number of items).
2. Different name or language → set `OWNER_TEMPLATE_NAME` / `OWNER_TEMPLATE_LANGUAGE`.
3. Until the template is approved, owner messages outside the window are not delivered (the provider rejects the
   template); they stay queued and flush on Harjot's next message.

## Drive (document filing)

Attachments are filed in Harjot's Google Drive under `EstateOS/<type>/<year>/` (ADR 0005). The scope is
`drive.file`: the app sees and changes only what it created, never his existing files.

1. Enable the **Google Drive API** in the same Google Cloud project as Gmail.
2. Create the token together with the Gmail ones: `make gmail-consent client=… mailbox=… out=~/.estateos drive=1`
   writes `drive-file.json` (exactly the `drive.file` scope, checked against the signed-in account).
3. Settings:

| Variable | Value |
|---|---|
| `DRIVE_PROVIDER` | `google` (prod refuses `fake`) |
| `DRIVE_CREDENTIALS_FILE` | path to `drive-file.json` (0600, outside the repository) |

`make live-check k=drive` creates `EstateOS/_live-check`, uploads one small file, finds it by its attachment id and
deletes it again.

## LLM

Agents run on deterministic offline models until `LLM_MODEL` is set (default `fake`; prod refuses it).

| Variable | Value |
|---|---|
| `LLM_MODEL` | Pydantic AI model string, e.g. `openai:gpt-4.1-mini` (OpenAI project with EU data residency) |
| `OPENAI_API_KEY` | required for `openai:*` models |
| `GEMINI_API_KEY` | required for `google-gla:*` models, e.g. `LLM_MODEL=google-gla:gemini-2.5-flash` (Google AI Studio; testing only: no EU data processing agreement, use synthetic or test data) |
| `LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | optional: every agent run traced to Langfuse (EU) |

After switching:
1. `make live-check k=llm` — one small call: the published understanding prompt on a synthetic Dutch emergency
   message must come back as valid `Understanding` (maintenance, emergency/high).
2. `make eval agent=understanding version=v1` and `make eval agent=linking version=v2`; compare with the
   fake-model reports in `backend/evals/reports/` (fake: understanding category 0.43, linking accuracy 0.83; Gemini 2.5
   Flash on 2026-10-08: category 0.90, urgency 0.70, emergency and suspicious recall 1.00, linking accuracy 1.00).
   On free-tier quotas set `EVAL_MAX_CONCURRENCY=1`.

### Live checks

| Variable *(check only)* | Value |
|---|---|
| `LIVE_WHATSAPP_OWNER` | Harjot's number in E.164 (`+49…`). Must be the owner of the company that owns the sending number, read from the database at `DATABASE_URL` — point it at **prod** for this check; any other number is refused. Then the check sends him one text, "EstateOS live-check ✓". For `cloud_api`, `WHATSAPP_PHONE_NUMBER_ID` is also required. |
| `LIVE_WHATSAPP_MEDIA` | `<phone_number_id>:<media_id>` of an image sent to the business number after go-live (from `raw_events.payload`; media ids expire after about 30 days) |

Free-form text needs an open 24-hour service window: Harjot messages the business number first. Phase 1 never
messages tenants; the live check messages only the owner.

## BRIXX (data mirror)

The BRIXX mirror (ADR 0010) copies every BRIXX table into Postgres (schema `brixx`) on a 15-minute DBOS schedule and
reads only from there. EstateOS never writes to BRIXX, and BRIXX is never called on a request path. Until switched it
runs on the in-memory fake; prod refuses `BRIXX_PROVIDER=fake` and a missing token.

1. **IP whitelist.** BRIXX accepts the token only from whitelisted source IPs; from any other IP every call answers
   `401` (seen on 2026-10-31 with both header forms). Ask BRIXX to whitelist:
   - the dev machine's public IP: `122.161.68.101` on 2026-11-03 (the `115.246.217.246` in the spec is stale; home
     and office IPs change, so re-check before asking);
   - the production egress IP. Production needs a **fixed** egress IP (for example an Elastic IP or a NAT gateway);
     without it the sync stops whenever the host's address changes.
2. **Settings** (private `.env` or the secret store only, never git):

| Variable | Value |
|---|---|
| `BRIXX_PROVIDER` | `api` (prod refuses `fake`) |
| `BRIXX_TOKEN` | the per-user Data API token (secret; never stored in the database, never logged) |
| `BRIXX_AUTH_SCHEME` | `bearer` (sends `Authorization: Bearer <token>`, the default) or `raw` (sends the bare token). **Unconfirmed** which one BRIXX expects: start with `bearer`; if a whitelisted IP still gets `401`, try `raw` |
| `BRIXX_BASE_URL` / `BRIXX_ENVIRONMENT` | defaults `https://mob.brixxonline.com/api/v1` / `hrrealestate` |
| `BRIXX_SYNC_INTERVAL_MINUTES` | default 15; only the staleness window of the status API uses it (stale after 3 intervals), the cron itself is fixed at every 15 minutes |
| `BRIXX_TIMEOUT_SEC` | default 60 |

3. **Check.** `make live-check k=brixx` (tests/live/test_live_brixx.py) calls the real Data API with the configured
   token: it lists the readable tables and describes one, metadata only, never row data. It stops and lists what is
   missing until `BRIXX_PROVIDER=api` and `BRIXX_TOKEN` are set. Then, after the worker runs, read
   `GET /api/v1/brixx/status` (dashboard session): `last_run.status` is `succeeded`, `stale` is
   false and no table has a `last_error`. A `BrixxAuthError` there means the token, the header form or the whitelist
   is wrong; it is not retried, and the other tables carry on.
4. **Rotate the token after go-live.** The current token was exposed in a chat transcript on 2026-10-31. Once the
   production sync works, ask BRIXX for a new token, replace `BRIXX_TOKEN`, restart the api and worker, and have the
   old one revoked. Use a separate token per environment (dev and prod).
5. **Documents** (mirror Phase C) also need the token's "personal data" permission; without it downloads are
   refused and shown as `forbidden`.

Rollback: removing the token or the whitelist entry makes every run fail with `BrixxAuthError`, which the status API
shows (`stale` after 45 minutes); mirror rows already synced stay readable.

## Onboarding rows

Until an admin command exists (M3), create the rows once with `psql`. Ids follow the UUIDv7 convention: generate
one per row with `uv run python -c "from app.core.ids import new_id; print(new_id())"`.

```sql
INSERT INTO companies (id, name) VALUES ('<id 1>', 'Hausverwaltung …');
INSERT INTO channel_accounts (id, company_id, channel, address, is_owner_channel) VALUES
  ('<id 2>', '<id 1>', 'whatsapp', '<phone_number_id>', false),
  ('<id 3>', '<id 1>', 'gmail', '<mailbox address, lower case>', false);
INSERT INTO owner_accounts (id, company_id, display_name, whatsapp_e164, email) VALUES
  ('<id 4>', '<id 1>', 'Harjot', '+31…', '<owner email>');
```

Company agent settings have Phase 1 defaults (change with `UPDATE companies SET … WHERE id = '<id 1>'`):
`timezone` Europe/Amsterdam · `briefing_time` 07:30 · `weekly_weekday` 4 (Friday) / `weekly_time` 16:00 ·
`chase_after_days` 3 business days · `escalate_after_chases` 2 · `drift_thresholds` `{}` (per-metric overrides,
e.g. `{"llm_cost_usd": 3.0}`) · `paused` false (Harjot can also send `pause` / `resume`). The first briefing timers
are scheduled within the hour by the `briefing.ensure` cron.

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
