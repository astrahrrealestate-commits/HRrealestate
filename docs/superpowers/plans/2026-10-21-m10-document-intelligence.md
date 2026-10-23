# M10 Document Intelligence: plan

Spec: [2026-10-21-document-intelligence-design.md](../specs/2026-10-21-document-intelligence-design.md). Branch
`m10-document-intelligence`. Each task is `/ship`: RED, GREEN, REFACTOR, G1, G2 where db/workflows/api are touched,
reviewer, commit. Docker is down on this machine, so G2 runs are written but unrun until the stack is up; say so in
PROGRESS.

Dependency changes (pypdf) need ADR 0007 and user OK (hook asks) before Task 2.

| # | Task | Files | Failing test first | Acceptance |
|---|---|---|---|---|
| 1 | Migration 0013 (written as 0011, renumbered at the merge): `attachments` extraction columns; `documents` summary/facts/reader_version/document_date; `document_chunks` (+GIN tsv); `document_links`; `drive_reorg_plans` | `app/db/models/{ingestion,work,documents}.py`, migration | migration round-trip + drift | `make check` migration tests |
| 2 | `TextExtractor` port, `FakeExtractor`, pypdf adapter, caps, id_document exclusion, ADR 0007 | `app/storage/extract.py`, `docs/adr/0007-*.md` | caps, id doc skipped, scanned falls to vision | `make quick` |
| 3 | `DocumentFacts` contract, `doc_reader/v1` prompt, agent spec, fake model, injection scan hook | `app/contracts/document.py`, `app/llm/agents/doc_reader.py`, `app/llm/prompts/v1/` | contract strictness, prompt render snapshot | `make quick` |
| 4 | Pipeline: extract, read, chunk, store; fallback to classifier; gate unchanged | `app/pipeline/documents.py`, `document_chunks.py` | extract fail falls back; replay safe; budget path | unit + integration |
| 5 | Linking: person/unit/lease/case scoring, `link_review` | `app/pipeline/document_links.py` | exact, fuzzy, ambiguous, none | unit |
| 6 | Search + read models + API routes | `app/pipeline/document_search.py`, `app/api/v1/documents.py` | FTS rank/filters, company scoping | integration |
| 7 | Super Agent: intents, concierge/v2, `doc_qa` agent + quote verification, executors | `app/contracts/concierge.py`, `app/llm/agents/doc_qa.py`, `concierge_reads.py` | quote not in chunks is refused | unit + golden |
| 8 | Proposer v2: scoped `<documents>` block, card shows source | `app/pipeline/propose.py`, `app/llm/prompts/v2/` | two-tenant isolation | integration |
| 9 | `DriveStore` move/rename/set_properties/list_owned; layout v2; name rule v2 | `app/storage/drive.py`, `app/pipeline/drive_layout.py` | memory drive moves, idempotent | unit |
| 10 | Reorg plan + approval route + DBOS workflow `drive:reorg:{plan_id}` | `app/workflows/drive_reorg.py`, `app/api/v1/documents.py` | plan diff, approve, replay | integration |
| 11 | Backfill workflow, sim-demo "lease question", live-check drive, golden sets, docs + PROGRESS | `app/dev/*`, `evals/golden/` | `make sim-demo` | quoted output |

Order: 1, 2, 3, 4, 5, 6, then 7, 8 (need 6), 9, 10, 11.
