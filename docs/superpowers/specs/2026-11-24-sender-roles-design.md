# Sender roles: label who wrote, after the intent is known

Date: 2026-11-24 · Status: draft, approved in conversation by the owner's developer · Related:
[ADR 0014](../../adr/0014-sender-roles-after-intent.md), [HLD](../../hld.md), [security standard](../../standards/security.md)

## 1. Problem

The inbox thinks every sender is either a contractor or a tenant.

- `api/inbox/routes.py` sets the role with one line: a sender who is not a contractor is `"Tenant"`. Lawyers (PACT
  Advocaten), the VvE, the bank, the tax office, cleaners and software vendors all show as Tenant.
- Any thread without a unit shows `"Unassigned Unit"` and, if the text names a unit with a lease, the yellow
  "Unregistered Sender / Link to Tenant" banner. Non-tenants have no lease, so this is always wrong for them.
- The contractor test is partly hard-coded (`chahalbouw.nl`, `contractor`, `loodgieter` in the sender address).
- `understanding` v2 says "classify messages from tenants and contractors", and `proposer` writes "tenant replies in
  Dutch" for everyone.

## 2. Goals and non-goals

**Goals**
- Only mail about the portfolio (maintenance, tenancy, contractors, legal or VvE matters about our properties) creates
  work. Everything else stays out of the case flow, exactly as `spam` and `requires_reply=false` do today.
- A sender is labelled **after** the intent is decided, never before and never instead of it.
- Tenants keep their unit and the "Link to Tenant" warning. Everyone else gets a role and an organisation or
  property, never "Unassigned Unit".
- Drafts match the recipient: friendly Dutch for tenants, formal B2B for lawyers, VvE and business.
- Nothing in the pipeline breaks: no change to `Category`, to the cases/messages/understandings tables, or to
  who a message can be sent to.

**Non-goals**
- New `Category` values (a CHECK constraint on two tables, and six code paths branch on them).
- Letting the model choose a recipient, a person kind or a lease link.
- Re-running understanding over old messages.

## 3. Design

Two stages, in this order.

**Stage 1, intent (exists today).** `understanding` returns `category`, `urgency`, `requires_reply`. `link.py` opens
no case for `spam` and only joins a thread when `requires_reply` is false; `propose.py` drafts nothing for those.
v3 of the prompt only sharpens the scope: mail that is not about the managed portfolio is `other` or `spam` with
`requires_reply=false`.

**Stage 2, label (new).** Only for mail that passed stage 1.

| Step | Source | Decides |
|---|---|---|
| 1 | Directory (DB): `Person.kind`, `LeaseParty` | tenant or contractor. Always wins. |
| 2 | `Understanding.sender_role` (v3, optional) | legal, vve, business, prospect, only when step 1 has no answer |
| 3 | nothing matched | neutral `Contact` |

`sender_role` is `None` whenever the message is noise (validator: spam implies `None`). It lives in the existing
JSONB `understandings.body`; old rows validate through the default `None`. It is a display hint only. Recipients,
person kind and lease links never read it (invariants 5 and 6).

The label is computed when the inbox is read, from stored facts. Nothing is written back, so there is no backfill and
a wrong label is fixed by fixing the rule.

**Display rules** (`app/api/inbox/sender_label.py`, pure, unit tested)
- Tenant: unit from the case, else the unit named in the thread, else `Unassigned Unit` (a tenant with no unit
  really is a gap). Unregistered-sender banner as today.
- Anyone else: the property named in the thread if exactly one matches, else the sender's organisation (email
  domain; a free-mail domain shows `Unlisted contact`). No banner.
- Audience: `tenants`, `contractors`, or `others`.

## 4. Build order (each step ships alone)

1. **Resolver plus UI fix (no model change).** `sender_label.py`, wired into `routes.py`; frontend maps the new
   role and stops forcing `tenant`. Fixes "Tenant" and "Unassigned Unit" for everyone the directory can tell apart.
2. **`understanding` v3 + `sender_role`.** New prompt, optional contract field, fake model, golden cases, eval gate
   (no drop in category or `requires_reply` accuracy against v2). Resolver step 2 and banner suppression.
3. **`proposer` v5.** Receives the resolved role as prompt data; formal register for legal, VvE and business. Still
   approval-gated. Legal drafts carry a "needs owner review" flag.

## 5. Safety

- Role from the model is display only. A message saying "I am a lawyer" gets a label, nothing else.
- The sender re-checks the recipient against the case's own identity in the DB, unchanged.
- Untrusted text stays inside prompt data blocks; no new write tools.
- Rollback of steps 2 and 3 is pointing the `AgentSpec` back at the old prompt version.

## 6. Tests

- Step 1: unit tests for the resolver (precedence, free-mail domains, property-or-organisation), plus an inbox API
  test with a lawyer, a bank and a tenant thread. Seen red first.
- Step 2: contract tests (old body validates, noise forbids a role), fake model, ~12 new golden cases (advocate,
  VvE, bank, tax, vendor, prospect, "I am a lawyer" injection), `make eval agent=understanding version=v3`.
- Step 3: proposer eval cases per role.
- Always: `make check`, OpenAPI snapshot update, frontend `tsc` and lint.
