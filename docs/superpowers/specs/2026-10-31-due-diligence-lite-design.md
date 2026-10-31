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
   `present`, `missing`, `stale` (present but out of date) or `unclear` (present, could not be read).
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
Documents with no extracted text (scan not read, ID documents, over the caps) are `unclear`; ID documents are never
sent to the model (ADR 0007).

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
House: same minus the VvE items, plus building survey (important). Tenanted investment: adds lease agreements (critical)
and rent roll (important).

## Rules (code, defaults in the framework) **(my call)**
- Field tolerance: areas 2 %, ground-lease fee 1 %, VvE contribution 5 %, price 0 %; year, label, ownership, ground-lease
  end and address exact (address compared after normalising case/whitespace/punctuation).
- Source authority: brochure 1, advisory (survey, valuation, energy label) 2, legal (deed, purchase agreement, Kadaster,
  VvE rules, ground lease, permit) 3. Mismatch severity: `marketing_vs_legal` high (price: medium, as asking differs from
  agreed), other `inconsistent` medium.
- Risks: ground lease ending in under 15 years high, under 30 medium; label F/G high, E medium; asbestos reported
  present high; built before 1945 without survey medium; built before 1994 without asbestos report (already a
  checklist item, no extra risk); expired document medium; tenancy ending within 12 months medium; model flag medium.
- Verdict: any `high` risk or mismatch ⇒ `red_flags`; else any missing/stale/unclear `critical` or `important` item ⇒
  `needs_documents`; else `clear_to_review`. No readable document ⇒ `needs_documents`.

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
