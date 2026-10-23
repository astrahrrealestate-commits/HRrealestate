# ADR 0007: Reading document contents (pypdf, stdlib, model vision)

Status: accepted (2026-10-21), amends ADR 0005 and the 2026-10-07 "attachment contents are not read" decision.

## Context
M9 files attachments from metadata only, so nothing can answer "what does the lease say about the deposit?" or find
a quote by its words. The owner asked (2026-10-21) for agents that read, understand, link and search documents.

## Decision
- **Text PDFs: `pypdf`** (pure Python, no native deps), behind the `TextExtractor` port (`app/storage/extract.py`)
  with a `FakeExtractor` for tests and the simulator. `.docx` is read with the standard library (`zipfile` + the
  `w:t` runs); `.txt`, `.csv` and `.eml` are decoded. Spreadsheets stay metadata-only.
- **Scanned PDFs and photos: model vision through Pydantic AI** (`doc_ocr` agent), not an OCR engine. No new
  dependency and no native binary; the extractor reports `needs_ocr` and the pipeline calls the agent under the
  per-company LLM budget.
- **Docling is not adopted now** (heavy, model downloads). Revisit if scanned-document quality is poor on real files.
- **Limits**: 15 MB, 40 pages, 200 k characters. Over a limit = metadata-only with a note, never a failure.
- **ID documents are never read.** A cheap metadata pass (`doc_classifier`) and a file-name guard run first; only a
  document that is not an `id_document` is extracted and sent to the reader.
- Extracted text is **untrusted data**: injection-scanned, only inside data delimiters, never in info logs.

## Consequences
- One new runtime dependency (`pypdf`). Vision calls cost tokens; scans are the only path that uses them.
- A malformed or encrypted PDF is `extraction_status=failed|skipped`, and the document is still filed from metadata.
- Pairs with Postgres full-text search for retrieval (no pgvector, no new service).
