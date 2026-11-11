# ADR 0012: Team profiles with per-section access, and contacts added by hand

Date: 2026-11-10 · Status: accepted (requested by the user on 2026-11-10)

## Context
Until now everyone on the whitelist (`allowed_users`) had the same full access, and `role` was stored but never read
(security.md, "Role is not enforced"). The owner wants a superadmin to create several named profiles and choose, with
one switch per dashboard section, what each person sees. Separately, the contacts page only listed people that mail or
WhatsApp had created (and hid those named after their email address); there was no way to add a contractor, tenant or
maintenance person before they write, or to name and classify one that already did.

## Decision
- **A profile is a whitelist row.** `allowed_users` gains `sections text[] NULL` (migration 0039). `NULL` means every
  section, so existing rows keep today's access. The roles `owner` and `superadmin` always see everything and are the
  only ones who manage profiles; any other role (`member`, legacy `manager`) sees its `sections`.
- **Sections** (`app/api/v1/sections.py`, one list, exposed at `GET /api/v1/admin/sections`): dashboard, inbox,
  properties, tenants, contacts, maintenance, money, reports, settings. Team management is not a section; it is the
  admin role.
- **Enforced on the server, not only hidden.** `require_principal` reads the whitelist row on every request (it already
  re-reads the owner row) and puts `Principal.access` on the principal; nothing about access is in the cookie. So a
  change, switching a profile off, or deleting its row applies on the person's next request. A company with no
  whitelist rows at all keeps full access (an owner who signs in with a Google ID token); once it has any row, a
  session without one is refused. `require_section(section, also=..., also_read=...)` guards every router:
  dashboard (`/api/dashboard`, `/api/v1/work`, the SSE feed: any section), inbox (`/api/inbox`, `/api/v1/inbox`,
  `cases`, `decisions`, `reviews`, `documents`; maintenance may also use the workflow ones), properties
  (`/api/properties`, `diligence`), tenants, contacts, maintenance (`/api/maintenance`, `/api/calendar`), money
  (`/api/v1/finance*`), settings (`memory`, `persona`, `channels`, `brixx`, the Google connect routes). Company
  pause/resume need the admin role. Search returns only the kinds of record the profile could open.
  `tests/unit/api/test_section_access.py` walks the whole OpenAPI document as a contacts-only profile and fails if a
  route outside the shared list is not refused (403), so a new router cannot ship unguarded.
  The Reports and Dashboard pages are assembled from the properties, tenants, maintenance and inbox endpoints, so
  `reports` and `dashboard` may also **read** (GET) those, as a summary: a profile that reads a list through another
  section's pages gets it without what was said or how to reach anyone. Tenants lose `phone` and `email`; tickets lose
  the phone numbers, contractor email, notes, original message and both drafts; inbox threads keep title, summary, unit,
  urgency and status but lose message bodies, drafts, attachments, provider ids (a WhatsApp thread id is the
  customer's number), snippet and the sender's contact; the thread is an allow-list, so a field added later stays
  hidden until listed (`app/api/inbox/summary.py`). A contact named after their email or number shows as "Unknown
  contact". The owner feed (`/api/v1/feed`, the SSE stream) sends card payloads (draft text, choices) only to Inbox
  and Maintenance; others get the cards with an empty payload. The calendar is readable by Dashboard without
  attendees and lockbox codes, and writable only by Maintenance or Inbox; attachments need Inbox. Holding the section
  itself (`tenants`, `maintenance`, `inbox`) returns everything.
  **This is a view limit, not a wall, while the Super Agent is ungated** (below): any profile can ask it for the same
  data in words.
  Reports may read only the dashboard `logs`; ticket history, the v1 inbox/cases/activity and the other dashboard
  routes need their own section. The Dashboard page's "needs you" cards therefore show the headline; opening a thread
  to read or answer it needs Inbox.
- **Admin API** (`/api/v1/admin/*`, superadmin only): list, create and edit profiles. Rules: unique email (across
  companies, as the table already is), at least one section for a member, unknown sections refused, nobody can switch
  off or demote their own profile, only the `owner` role can change the owner's row, at least one active admin must
  remain (the admin rows are locked while an edit runs, so two superadmins cannot demote each other at once), edits are scoped to the caller's company
  (another company's id is a 404).
- **Contacts** (`app/directory/contacts.py`, `POST` and `PATCH /api/contacts`): a hand-added contact is a `Person` plus
  email and WhatsApp `ChannelIdentity` rows, normalised with the same `normalise_identity` the ingest path uses, so
  the sender's earlier messages already match. If the email or number belongs to a person mail/WhatsApp created
  (kind `other`, no BRIXX reference, no trade) that person is classified in place instead of duplicated; any other
  clash is a 409 that names the contact. BRIXX-managed people cannot be edited here. Categories reuse `PersonKind`
  (`tenant|contractor|owner|other`); utility and municipality are `other` with a fixed trade, a maintenance person is a
  contractor with a trade, so no enum change was needed.
- **Bootstrap.** Migration 0039 promotes the earliest active whitelist entry of a company that has no `owner` or
  `superadmin` to `superadmin`; the seeded rows are already `owner`.
- **The contacts list** now returns everyone in the company, including people named after their email or number
  (previously dropped), with the real category (previously every non-tenant was labelled "contractor"), in two bulk
  queries instead of two per person.

## Consequences
- **The Super Agent is not section-gated** (`/api/agent`, `/api/v1/agent`). It answers from the whole portfolio, so a
  member with only `contacts` can still ask it about rent or maintenance. The admin page says so. Gating it needs its
  own design (per-section tool scopes); recorded in security.md.
- Approving and sending are allowed for anyone who holds the section that offers them (inbox, or maintenance for the
  workflow routes); pausing the company is admin-only.
- An email is unique **within a company** (migration 0040: `(company_id, lower(email))`), so a 409 on create says
  nothing about other companies. The Google login looks a person up by address alone, so an address whitelisted
  (and active) in more than one company is refused with `error=ambiguous_account` and no session; the login never
  guesses a company. The cost: an admin who whitelists a stranger's address in their own company can stop that person
  from signing in until the extra row is removed. Phase 1 has one company; revisit with a company picker at login
  before a second company is onboarded.
- One extra indexed lookup per authenticated request.
- Alternative rejected: role-based presets (admin/manager/viewer) with fixed permissions: the request was explicit
  about per-section switches, and a preset table would have to be edited for every new combination.
