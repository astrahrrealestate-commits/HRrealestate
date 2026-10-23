# ADR 0008: Advanced retrieval for documents (pgvector, embeddings, query rewriting, reranking)

Status: accepted (2026-10-22), builds on ADR 0007. Owner request: "the best RAG output possible".

## Context
M10 retrieval is Postgres full-text only: one best chunk per document, words must match. It cannot bridge Dutch and
English ("deposit" never finds "waarborgsom"), cannot find a passage that says the same thing in other words, cannot
cite a page, and has no measurement. Documents are few (a landlord's files, thousands of chunks), tenant-scoped, and
mostly Dutch, so the system should stay inside Postgres and add only what moves answer quality.

## Decision
Techniques, each with the reason it earns its place:
1. **Hybrid search**: dense vectors (`pgvector`, HNSW, cosine) plus the existing Dutch/simple full-text index, fused with
   Reciprocal Rank Fusion. Words catch exact terms (clause numbers, amounts, names); vectors catch meaning and language.
2. **Multilingual embeddings** through Pydantic AI's `Embedder` (`openai:text-embedding-3-small`, 1024 dimensions, EU
   endpoint like the other OpenAI calls). Fake deterministic embedder for tests and the simulator.
3. **Structure-aware chunking**: per page, heading-aware, about 1,500 characters with 200 overlap; each chunk keeps its
   page and nearest heading. Pages are joined with a form feed in `attachments.extracted_text`.
4. **Contextual chunks** (Anthropic's "contextual retrieval", deterministic variant): the indexed and embedded text of
   a chunk is prefixed with its document title, type, date, unit, parties and heading, so "the deposit" in a lease for
   unit X is distinguishable from the same words in another lease. No LLM call per chunk.
5. **Query understanding**: one small LLM call per question produces Dutch and English keyword variants, a
   hypothetical answer passage (HyDE) for the vector side, and a fact label when the question asks for a single fact.
   A property-term glossary (Dutch/English) is the offline fallback and also expands keyword queries.
6. **Fact-first routing**: questions about a stored fact (rent, deposit, notice period, term) are answered from the
   reader's `key_facts` and dates with no generation, and cite the document.
7. **Reranking**: a listwise LLM reranker scores the fused top 20 for relevance to the question; chunks below the
   relevance floor are dropped (corrective step: nothing relevant means "not found", no generation).
8. **Parent expansion**: the chosen chunks are widened with their neighbours (±1) before generation, at most three
   chunks per document, with page numbers in the citations.
9. **Document-level vectors** (title + summary + parties + unit) so "the lease for Kerkstraat 12" is found by what the
   document is, not only by what it says.
10. **Evaluation**: a synthetic Dutch/English corpus with questions that exercise cross-language, distractors from other
    tenants, facts, abstention and injection; recall@k, MRR, fact accuracy and abstention accuracy gate regressions.

Not adopted: a separate vector database (Postgres is enough at this size), a local cross-encoder model (heavy image,
no GPU; the LLM reranker is used instead), per-chunk LLM context generation (cost per chunk; the deterministic header
gets most of the benefit), GraphRAG (the directory already is the graph: documents link to people, units, leases and
cases).

## Consequences
- New dependency `pgvector` (and its `numpy`). Postgres image becomes `pgvector/pgvector:pg16` in compose and the test
  containers; production uses a managed Postgres 16 with the extension (RDS and others support it). The dev volume was
  created by the alpine image: recreate it (`make down`, wipe the volume) because the two images collate text
  differently.
- Embeddings are computed after filing in their own step; retrieval works without them (words only) until they exist.
- Cost per question: one embedding, one small rewrite call, one rerank call, one answer call; the fact route costs one
  embedding at most. Each LLM step has its own switch and falls back to the cheaper path on budget or error.
- Chunks written by M10 (v1) are re-chunked by the reindex workflow (`documents.index_version`).

## Operational requirements (from the review of 2026-10-23)
- **pgvector 0.8 or later.** Compose and the test containers pin `pgvector/pgvector:0.8.2-pg16`. Filtered vector search
  (company, case scope) relies on `hnsw.iterative_scan`, which older versions do not have; without it an HNSW scan
  post-filters a fixed number of candidates across every tenant and recall drops silently as the table grows.
  Production must run 0.8+ (check the managed Postgres offering before choosing).
- **`CREATE EXTENSION vector`** in migration 0014 needs a role that may create extensions; on a managed Postgres, enable
  the extension once as the admin role before the migration runs.
- **Failure policy.** Any embedding-provider failure (bad key, quota, timeout, outage) is logged at error level with its
  class and retrieval continues on words alone; embeddings have a deadline (`llm_timeout_sec`). The embed step in the
  filing workflow never fails the workflow: the backfill refills missing vectors.
- **Freshness.** Changing a document's link clears its `index_version`, so the next backfill rebuilds the chunk headers
  (unit, parties) and the document vector; a document vector is written only if the document was not re-indexed while it
  was being embedded.
- **Fact answers** are read only from leases, matched on whole words of the label, and shown with their source.
