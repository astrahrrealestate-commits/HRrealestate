# M10 Document Intelligence: read, link, find and organise documents

Status: draft, written without a brainstorm (user: "just start", 2026-10-21). Every call below is marked **[call]**
and is open to override. Extends M9 ([ADR 0005](../../adr/0005-google-drive-filing.md)); supersedes the
"metadata only" decision of 2026-10-07 for document attachments.

## Why
M9 files attachments by name, type and size, and nothing reads them back. Harjot's real moments are: a tenant asks
"what does my lease say about the deposit?", a contractor asks "did you approve my quote?", Harjot asks "show me the
insurance for Unit 3". Today the agent cannot answer, and the Drive is a write-only dump he must browse by hand.

## Goals
1. **Read**: extract text from PDFs, Office files and photos/scans; understand what the document is and its key facts.
2. **Link**: tie each document to the real tenant(s), unit, lease, case and (when relevant) maintenance issue.
3. **Find**: search by words, tenant, unit, type, date, status; open the source file in Drive.
4. **Answer**: the Super Agent answers questions from a document (lease clauses, quote amounts) with a citation, and
   the proposer sees the relevant excerpts when drafting a reply to a tenant query.
5. **Organise**: Drive layout is by property, then document kind, with searchable names and metadata; existing
   filed documents are re-organised through an owner-approved plan.

## Non-goals / anti-goals
- No auto-send of anything. Documents inform drafts; sends stay behind approve + `app/sender/` (invariant 5).
- No agent write tools. Drive moves run in code after Harjot approves a plan; the Super Agent can only propose.
- No cross-tenant leakage: a draft to tenant A never contains text from tenant B's documents (see Privacy).
- Not reorganising Harjot's pre-existing Drive: `drive.file` cannot see it (ADR 0005). Changing that needs the full
  `drive` scope: **a decision for the user**, not made here.
- No OCR engine of our own, no vector DB, no Redis.

## Constraints
Invariants 1-9 of CLAUDE.md. Document text is **untrusted data** (invariant 6): it goes only inside data delimiters
and passes the injection scanner. Immutable prompts: new agents/prompts are new `vN` directories. Contracts are the
schema. Every query filters by `company_id`.

## Design

### 1. Reading (`TextExtractor` port, `app/storage/extract.py`)
- Port + `FakeExtractor` for tests. Real adapter: **pypdf** for text PDFs and **python-docx/openpyxl** only if needed
  later **[call]**; scanned PDFs and photos go through **model vision via Pydantic AI** (already in the stack; no
  OCR dependency). Docling stays deferred (heavy).
- Output stored in the existing `attachments.extracted_text` (+ `extraction_status`, `page_count`, `extractor`).
- Caps **[call]**: 40 pages, 200 k characters, 15 MB; over the cap = metadata-only + note, never a failure.
- `id_document` (passport, ID card): **never extracted**; classified from metadata and filename only **[call]**.
  Privacy over convenience; revisit if Harjot wants it.
- Extraction is a DBOS step (retryable), runs before classification in the `documents` queue.

### 2. Understanding (`doc_reader` agent, replaces `doc_classifier` input)
- New contract `DocumentFacts` (OpenAI-strict): `doc_type`, `title`, `document_date`, `summary` (≤400 chars),
  `parties[]` (name, role), `unit_hint` (address/label text), `key_facts` (typed per kind: lease start/end/rent/
  deposit/notice; invoice amount/due/vendor; quote amount/valid-until; insurance policy/expiry), `confidence`.
  `Decimal` money, `AwareDatetime`/`date` dates.
- `doc_reader/v1` prompt sees the extracted text (truncated, in a data block), metadata, sender and case summary.
  `doc_classifier` stays for the metadata-only fallback (budget exhausted, extraction failed, id documents).
- Same confidence gate (0.80 files, below goes to the review card). Facts land in `documents` (`summary`,
  `facts` jsonb, `document_date`, `reader_version`).

### 3. Linking (`document_links`, `app/pipeline/document_links.py`)
- Table `document_links(document_id, kind person|unit|lease|case|maintenance_case, ref_id, method, score)`,
  unique on `(document_id, kind, ref_id)`.
- Deterministic first: the message's case and person (already known); then `rapidfuzz` of `parties[]` against
  `people.display_name` and of `unit_hint` against `units.label/address`, thresholds in settings; the lease comes from
  unit + parties + dates (Validity ranges). A maintenance link is the case when its type is maintenance.
- One match above threshold = link. Several or none above a lower threshold = a `link_review` item on the dashboard
  (same card mechanism as filing review). Never guess a tenant silently.

### 4. Finding (`app/pipeline/document_search.py`)
- Postgres full-text: table `document_chunks(document_id, ord, text, tsv)` (≈800-token chunks, GIN on `tsv`),
  `dutch` and `simple` configs **[call]** because tenants write Dutch and docs are mixed. Filters: `doc_type`,
  `unit`, `person`, `case`, date range, `status`. Ranked with `ts_rank`, snippets with `ts_headline`.
- **pgvector is not added now [call].** FTS plus structured filters covers "lease of Unit 3", "invoice from
  Loodgieter X". If recall proves poor on real documents, propose an ADR for hybrid search then (tech-stack rule).
- Read models and routes in `app/api/v1/documents.py`: `GET /documents`, `GET /documents/search`,
  `GET /documents/{id}` (facts, links, Drive URL, snippets), `POST /documents/{id}/links` (owner fixes a link).

### 5. Answering (Super Agent + proposer)
- New intents `find_document`, `read_document` (answer a question from one document) and `unit_documents`. Concierge
  prompt **v2** (v1 untouched). Executors in `concierge_reads.py`; retrieval is code, never a model tool.
- `doc_qa` agent: question + top chunks as data blocks, returns `DocAnswer(answer, quotes[], document_ids[],
  confidence)`. Quotes must appear verbatim in the supplied chunks (checked in code; failing = "I could not find
  that in the document"). The answer always names the document and links it.
- Proposer **v2**: for a tenant message, retrieve the case's lease and the top relevant chunks **only from documents
  linked to that tenant's lease/case** and add them as an `<documents>` data block; the draft may cite a clause, and
  the approval card shows which document supplied it.

### 6. Organising Drive (`app/storage/drive.py`, `app/pipeline/drive_layout.py`)
- Layout v2 **[call]**: `EstateOS/<Unit label>/<Kind>/<YYYY>/` (Kind = Leases, Invoices, Quotes, Insurance,
  Certificates, Correspondence, Photos, Other), `EstateOS/_Unsorted/` for unlinked documents. Name rule v2:
  `YYYY-MM-DD_<kind>_<tenant>_<title>.<ext>` unchanged in spirit, now with the linked tenant, not the sender.
- Every file gets Drive `description` (summary) and `appProperties` (`doc_type`, `unit`, `tenant`, `date`, `case`),
  so Drive's own search finds it. No shortcuts in v1.
- `DriveStore` gains `move`, `rename`, `set_properties`, `list_owned` (all within `drive.file`).
- **Reorganise = plan then approve**: `drive_layout.plan()` diffs current vs target paths for owned files and
  writes a `drive_reorg_plans` row (items: file, from, to, reason). Harjot approves the whole plan or items on the
  dashboard; DBOS workflow `drive:reorg:{plan_id}` applies idempotently (move is a no-op if already there).
  A document whose link changes later produces a one-item plan, never a silent move.

### 7. Privacy and safety
- Retrieval for tenant-facing drafts is scoped by the case's lease/person links, tested with a two-tenant fixture.
- Extracted text and facts are never in info logs. Injection scan on extracted text; a hit marks the document
  `suspicious`, keeps it searchable for Harjot, and excludes it from draft context.
- `id_document` not extracted; chunks are not created for it.

### 8. Cost
`doc_reader` and `doc_qa` use the existing per-company LLM budget; vision only for scans/photos; extraction is
skipped for files that `should_skip` already drops.

## Failure handling
Extraction failure or budget exhaustion = fall back to the M9 metadata path (`doc_classifier`), document still
filed or sent to review. Reader invalid answer = `failed` with the error, owner can pick the type as today.
Re-reading is idempotent: `documents.reader_version` + `attachment sha256` key the result.

## Backfill
`documents:backfill` workflow (one per company, resumable): extract + read + link already-filed documents, then
produce one reorganisation plan. Runs in small batches on the `documents` queue.

## Testing
Unit: extraction caps, chunker, link scoring, layout/name rules v2, quote verification. Integration (testcontainers):
FTS ranking and filters, company scoping, two-tenant draft isolation, reorg plan idempotence. Golden set
`evals/golden/doc_reader.yaml` (Dutch lease, invoice, quote, scanned insurance, injection attempt) + `doc_qa`.
Simulator: `make sim-demo` gains a "lease question" scenario (tenant asks about the deposit, the draft cites the
lease). `make live-check k=drive` gains move/rename/properties.

## Decisions for the user (not made here)
1. Allow the full `drive` scope so the whole existing Drive can be searched and organised? (Default: no.)
2. OK to read ID documents' contents? (Default: never.)
3. pypdf + vision acceptable as the reader, or do you want Docling now? (Default: pypdf + vision.)

## Out of scope for M10
Dashboard UI (backend API only, per ADR 0006); e-signature; renewals/expiry reminders from `key_facts` (follow-up
once facts exist: a cron over lease end and insurance expiry creating tasks).

## Amendments made while building (2026-10-21)
- **Classifier first.** `doc_classifier` (metadata only) still runs before reading: it decides whether a document may be
  read at all (ID documents never are), and is the fallback when reading fails. `doc_reader` then refines the type.
- **Link kinds** are person, unit, lease and case (a maintenance issue is a case). Owner removals are kept as
  `method="removed"` rows so automation cannot re-add them.
- **Unresolved names** the reader found but the directory could not place are kept in `documents.facts.unresolved`
  (filter `needs_link=true`), not as a separate review card.
- **Answers are assembled from verified quotes** (found word for word in the retrieved passage, links/e-mails/IBANs
  removed); the model's own sentence is shown only when it carries none of those. Suspicious documents are never context.
- **Search**: `match=all` for typed queries, `match=any` (stop words dropped, best overlap first) for questions.
- **Layout v2** shipped with filing itself; the reorg plan moves v1 files. Backfill: `POST /documents/backfill`.
- **Proposer excerpts** carry no links/e-mails/IBANs and are not added to the draft guard's source text, so a draft that
  repeats such a value is still flagged.
