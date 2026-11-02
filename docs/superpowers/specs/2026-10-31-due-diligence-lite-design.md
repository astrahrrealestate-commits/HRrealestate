# Due Diligence Lite (agent, Phase 1) — design

Status: written without a brainstorm (user: "build the agent", 2026-10-31). Every call marked **(my call)** is open to
override. The client's own framework was not supplied: the default checklist below is a Dutch residential
property screening framework and is **replaceable data** (`dd_framework_path`, see Framework).

## Why
Before Harjot commits to a property he gets a pile of documents: a brochure, deed drafts, VvE papers, an energy label.
Two things are easy to miss: a document that is **not there**, and a brochure that **says something different** from the
legal papers (area, year built, ownership, price). The agent screens the pile and answers three questions:
what is missing, what disagrees, what is risky.

## Goals
1. **Missing documents.** Compare the documents of a review with a checklist for the property kind; each item is
   `present`, `missing`, `stale` (present but out of date) or `unclear` (a matching document was found but read with low confidence; a document that could not be read at all
satisfies nothing and raises one `unreadable_documents` risk).
2. **Mismatches.** Same fact, different value across documents (area, plot, year built, energy label, ownership type,
   ground-lease end, ground-lease fee, VvE contribution, price, address). A mismatch between a **brochure** (marketing)
   and a **legal** document is labelled `marketing_vs_legal` and ranked higher; the legal document is the reference.
3. **Key risks.** Rule-based risks from the extracted facts (leasehold ending, energy label E-G, asbestos, old
   building without survey, expired documents, expiring tenancy) plus document-quoted red flags the model surfaces.
4. **One verdict**: `clear_to_review`, `needs_documents` or `red_flags`, with coverage (present of applicable items).
5. Light by design: screening, not legal advice. Every report carries that disclaimer.

## Non-goals
Legal or technical opinion, valuation, mortgage advice, Kadaster or municipal lookups, contacting sellers or agents,
sending anything, editing documents. The Super Agent integration (read intents) is deferred: it needs a concierge
prompt version. Auto-triggering from incoming mail is out; a review starts when the owner starts it.

## Anti-goals (a failure even if tests pass)
- A claim without a verbatim quote from the document. Code checks every quote against the document text; a claim or
  flag whose quote is not found is dropped and counted (`unverified_claims`), never shown.
- The model deciding a verdict, a severity above `medium`, or a mismatch. The model only reads text into typed claims
  and quoted flags. Code compares, ranks, and rates.
- A silent gap: a document that could not be read shows as `unclear`, never as `present`.
- Treating text inside a document as instructions (invariant 6).

## Inputs and trigger
The owner picks documents already in the library (M10, `documents` with extracted text) and a property kind
(`apartment`, `house`, `tenanted_investment`) **(my call)**, plus a title and an optional unit. `POST` creates the
row, then enqueues `dd:{review_id}:{run_no}`. Rerun (after adding documents) bumps `run_no`.

## Flow
```
POST /diligence/reviews ─► dd_reviews row (pending) + dd_review_documents ─► workflow dd:{review_id}:{run_no}
   per document: dd_reader agent (cached per document + reader version) ─► typed claims + quoted flags
   quotes verified against the text ─► dd_document_reads
   pure engine: checklist ─ mismatches ─ risks ─ verdict ─► report jsonb on dd_reviews (done)
   ─► owner_feed row kind dd_report
```
Documents with no extracted text (scan not read, over the caps), ID documents (ADR 0007) and documents the injection
scan flagged as suspicious are never sent to the model; they appear as unreadable.

## Framework (the checklist is data) **(my call)**
`app/diligence/framework.py`: `Framework(version, requirements, field_rules, authority)`. Default `nl-residential-v1`.
Requirements per property kind, each with `key`, `label`, accepted `DDDocKind`s, `severity`
(`critical`|`important`|`nice`), `why`, optional `max_age_days`, optional condition (`ownership_type` contains
`leasehold` ⇒ ground-lease papers required). Overridable with `dd_framework_path` (JSON, validated by the same model);
the report records `framework_version`.

Default checklist (apartment): deed of title / purchase agreement (critical), Kadaster extract (critical), VvE
splitsingsakte + rules (critical), VvE annual budget/accounts (important), VvE meeting minutes <18 months
(important), VvE multi-year maintenance plan (important), energy label <10 years (important), buyer's survey
(nice), asbestos report if built before 1994 (important), ground-lease papers if leasehold (critical), brochure (nice).
House: same minus the VvE items, plus building survey (important) and permits (nice). Tenanted investment: the
apartment checklist plus lease agreements (critical) and rent roll (important) **(my call: a tenanted house is
screened as `house` and the leases are added by hand until the owner asks for a fifth kind)**.

## Rules (code, defaults in the framework) **(my call)**
- Field tolerance: areas 2 %, ground-lease fee 1 %, VvE contribution 5 %, rent 2 %, price 0 %; year, label, ownership,
  ground-lease end and address exact (address compared after normalising case/whitespace/punctuation).
- Source authority: brochure 1, advisory (survey, valuation, energy label, VvE minutes/budget/plan, insurance, rent
  roll) 2, legal (deed, purchase agreement, Kadaster, VvE rules, ground lease, permit, lease agreement) 3. Every
  `DDDocKind` must have an authority (validated). A brochure disagreeing with a more authoritative document is
  `marketing_vs_legal`: high (price: medium, as asking differs from agreed). Two non-brochure sources disagreeing is
  `inconsistent`: medium, **high** for ground-lease end, ownership type, asbestos and energy label.
- Rules and conditions read **every claim at the highest authority that states the fact** and take the worst case, so
  the order of equally authoritative documents never hides a risk.
- Risks: ground lease ending in under 15 years high, under 30 medium; label F/G high, E medium; asbestos reported
  present high; built before 1945 without survey medium; expired document medium; tenancy ending within 12 months
  medium (tenanted investment only); a document-quoted flag medium; unreadable documents and documents longer than the
  reader's window (24 000 characters) medium.
- Age limits: a requirement with an age limit is `stale` when the newest document is older or expired, and `unclear`
  when the document carries no date at all (a silent pass would hide the gap).
- Verification (`app/diligence/verify.py`): a claim is kept only when its quote (at least 4 characters) is in the text
  **and supports the value** (the number's digits, the date's year, the label letter, the stated words); a flag when its
  quote is in the text. A kind none of whose Dutch/English words appear in the text is capped at confidence 0.4
  (`unclear`). Dropped items are counted in `unverified_claims`.
- Verdict: any `high` risk or mismatch is `red_flags`; else no readable document, any unverified claim, any unreadable
  or truncated document, or a missing/stale/unclear `critical` or `important` item is `needs_documents`; else
  `clear_to_review`.
- One document the model cannot read (`AgentFailedError`) is reported as unreadable; a spent LLM budget fails the
  whole review (a partial report would mislead). A failed review stores only the exception type.
- A rerun is allowed in any state: the run number makes an in-flight run stale, so a stuck review can always be rerun.
  A rerun clears the previous report and verdict.

## Data (migration 0023)
- `dd_reviews`: company, title, property_kind, unit_id (nullable), status (`pending|running|done|failed`), run_no,
  framework_version, verdict, report jsonb, error, completed_at.
- `dd_review_documents`: review_id, document_id; unique pair.
- `dd_document_reads`: company, document_id, reader_version, read jsonb (the verified `DDDocRead`); unique
  (company, document, reader_version).
- `owner_feed.kind` check gains `dd_report`.

## API (owner session, CSRF on writes; documented in `docs/dashboard-api.md`)
`POST /api/v1/diligence/reviews`, `GET /api/v1/diligence/reviews`, `GET /api/v1/diligence/reviews/{id}`,
`POST /api/v1/diligence/reviews/{id}/rerun` (optional new document set). Foreign or missing ids answer the same 404.

## Invariants this keeps (CLAUDE.md)
Postgres row before enqueue; deterministic id `dd:{review_id}:{run_no}`; workflow body does no I/O (steps do);
every query takes `company_id`; no send path touched; document text only in data blocks; the agent has no tools;
contracts in `app/contracts/diligence.py` are the agent `output_type`; new prompt `app/llm/prompts/v1/dd_reader.md`
is immutable once published; `app.diligence.engine` imports no I/O layer (import-linter).
