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

Messages already stored are not re-attributed, and `backend/scripts/` history imports still read `From`.

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
