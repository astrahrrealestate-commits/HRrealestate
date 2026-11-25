# 0016. Reply-To names the sender of an inbound email

Date: 2026-11-25 · Status: accepted (owner decision)

## Context
Mail reaches the EstateOS mailbox through a Google Apps Script in the owner's own Google account (as described by the
user on 2026-11-25; the script is not in this repository). The owner labels a mail, and the script forwards it to the
EstateOS mailbox with the original sender in `Reply-To` and both the original sender and the owner in `From`.
Attributing by `From` can file that mail under the wrong contact.

The script makes `Reply-To` correct for the mail it forwards. The code cannot tell that mail from mail sent straight
to the EstateOS mailbox, so the risk under Consequences applies to anyone who knows that address.

## Decision
For **inbound** Gmail, `sender_identity`, `meta.from` and `meta.from_name` come from, in order:

1. the first `Reply-To` address that is a valid email and is neither a team address (owner account, whitelisted users,
   `owner_email`) nor one of the company's connected mailboxes, comparing without any `+tag`. Aliases and groups that
   are not connected as mailboxes cannot be recognised;
2. for a mail forwarded by the team, the original sender quoted in the forward;
3. `From`.

This applies to every inbound mail, not only mail from the team. The display name is the `Reply-To` name; the `From`
name is used only when both headers carry the same address. Mail with Gmail's `SENT` label stays outbound, attributed
to the mailbox. `From` is still required. When `Reply-To` replaces it, the `From` address is kept as `meta.header_from`.

Messages already stored change only when the repair below is run, and `backend/scripts/` history imports still read
`From`.

**Repair of stored mail** (`python -m app.workflows.reattribute_cli --mailbox <address>`, preview by default; apply
with `--apply --worker-stopped` after a database snapshot). Candidates are Gmail rows filed under a team address or
company mailbox. Each original is read again from Gmail (an IMAP import's `X-GM-MSGID` is the API id in decimal) and
passed through the ingestion rule. Only the message changes: sender, name, direction and contact, with the old values
kept in `meta.reattributed_from`. Mail Gmail marks as sent, and mail naming nobody else, is left alone, as is a row
stored as sent where only quoted text names someone else. Hashed history rows cannot be read again. An outage or lost
login stops the run before any write; applying is refused when no original at all can be read.

**Cases and flats are not changed** (decided 2026-11-25). Moving and splitting cases was built and dropped before use:
review showed it could hand one tenant's cases or messages to another and could not be undone. The report lists every
case holding repaired mail, so a thread may show several senders until a person sorts it. Unsent reply drafts on those
cases are cancelled, approved ones included, because a send takes its recipient from the case at send time; each
cancellation and the previous statuses are written to the case history. A send being delivered stops the run. Cases sharing a repaired message's thread count too. On a case holding repaired mail, a Gmail draft is
created only for the person the reply answers (a chaser needs a case with one sender); otherwise it is blocked until
the case is sorted. Do not draft from the dashboard during a run. Search
chunks, understandings, summaries, tasks of other kinds, documents and memories are not rebuilt.

Undo restores from the snapshot. `meta.reattributed_from` and the case notes record what changed.

**Label pass** (added 2026-11-25). A separate step (`--label`), run once the worker is back. It asks the pinned
understanding prompt once for each case's shown mail (latest incoming) whose sender the directory cannot place as
tenant or contractor, across the company, and stores only `sender_role` in `messages.meta.sender_role_pass`. It skips
mail flagged suspicious or spam (a later flag also overrides a stored label), and mail given a role at ingestion unless
its sender was repaired. No full pipeline, and no understanding, case or state is written. It uses the configured
model under the triage budget limits, which new mail shares, so one run makes at most 200 calls (`--max-calls`); it
also stops after 5 failures in a row or at a limit, and a repeat run asks only what is left. A preview counts the calls
and makes none. A model role never makes anyone a tenant.

**Running it** on a deployed environment: `scripts/repair_mail.sh <stage|prod> <preview|apply|label> [mailbox]`.
`apply` stops the worker, waits for its tasks to exit, snapshots the database, repairs, restores the worker, then
labels. On any early exit it stops its own repair task before restoring the worker, and leaves the worker stopped if
it cannot confirm that. It refuses to apply when the worker is already at 0.

**Labels and flats follow the sender shown.** The inbox derives a thread's role label from the writer of its latest
incoming mail; a writer the directory does not know stays a contact, and only a thread nobody has written in takes the
case contact's label. A writer's leased flat fills only a case that has no flat of its own; no case is changed. A
non-tenant with no flat shows their organisation, or nothing (the "Unlisted contact" text is gone). The inbox's count
badges still count by case contact.

**Link to Tenant** names the mail it acts on (`message_id`) and is refused if that is no longer the latest incoming
one. It moves only that mail's writer, never a fallback, and only an unclassified contact with no lease or BRIXX record
who holds none of our addresses, to a tenant or leaseholder.

**On screen** (`app/context/shown_sender.py`), each mail is named from its own row: the name in its headers, or its
address when `Reply-To` gave no name. The saved contact name is used only for a mail with neither. This holds for the
inbox thread (its latest inbound mail) and each message in it, a contact's mails, and the lines of newly indexed
search chunks (the label on a search result stays the saved name). The frontend shows that name unchanged; the reply
side of a Today card names the latest sender, not the ticket's tenant. WhatsApp and Google Chat have no `Reply-To` and keep the saved contact name. The thread's
role label, unit and reply recipient still come from the case's records.

## Consequences
- The risks below, and those in `security.md`, were accepted on 2026-11-25 with the advice to keep send mode off.
- The person, the lease and unit of a new case, and the reply recipient all follow the `Reply-To` address.
- **`Reply-To` is not authenticated.** SPF, DKIM and DMARC alignment protect the `From` domain only, so any outside
  sender can set `Reply-To` to a tenant's address and have the mail filed as that tenant's. A reply goes to the named
  address. Owner approval still gates every send, but it does not cover case changes made when the mail arrives, and
  the owner is not shown the `From` address. Full list and fix options: `docs/standards/security.md`.
- Mailing lists, ticket systems and automated notices that set `Reply-To` are attributed to that address, so checks
  that look for markers such as `noreply` in the sender can miss them.
- Rejected: applying `Reply-To` only when `From` is a team address. It is narrower and harder to abuse, but does not
  cover relays outside the team.
