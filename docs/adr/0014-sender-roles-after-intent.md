# ADR 0014: Sender roles are a display label decided after intent, not new categories

Date: 2026-11-24 · Status: accepted (requested by the user on 2026-11-24)

## Context
The inbox labelled every sender who was not a contractor as "Tenant" with "Unassigned Unit". Lawyers, the VvE, banks
and vendors landed in the tenant flow, and the understanding and proposer prompts only knew tenants and contractors.
Two fixes were on the table: add categories or sender personas to the pipeline contracts, or add a label next to the
existing intent. `Category` is a VARCHAR plus CHECK on `understandings` and `cases` and is read by `link`, `propose`,
the digest, the evals and the API schema.

## Decision
- **Intent first.** `category`, `urgency` and `requires_reply` stay the only inputs to the case flow. Mail that is not
  about the managed portfolio is `spam` or `other` with `requires_reply=false`, which already opens no case and no
  draft. `understanding` v3 only sharpens that scope.
- **Label second.** A sender role is computed after intent, from the directory first (`Person.kind`, `LeaseParty`),
  then from an optional `Understanding.sender_role` hint, else `Contact`. Computed on read, never stored on the case.
- **No new `Category`, no migration.** `sender_role` is an optional field in the JSONB `understandings.body`,
  defaulting to `None`; noise forbids a role.
- **The model never decides who gets a message.** The role is display and drafting-register only; recipients and
  person kind come from the DB (invariants 5 and 6).
- **Order of work:** resolver and UI first (no model change), then `understanding` v3, then `proposer` v5.

## Consequences
- No contract break for existing consumers; old rows read as before and show `Contact` instead of `Tenant` when the
  directory cannot tell.
- A wrong model role changes a label and a draft's tone, never a recipient or a case.
- Rolling back v3 or v5 is a one-line `AgentSpec` change.
- New role kinds later (notary, bailiff) are enum values in a JSON field, not migrations.
- Rejected: new `Category` values (migration plus six branching code paths) and a separate sender-classification
  agent (a second model call per message for a label).
