# 0011 — Dutch to English translation with a local model

Status: accepted (2026-11-10)

## Context
Tenants and contractors write Dutch; Harjot reads English. The inbox UI had "Show English translation" slots
(`bodyEnglish`, `translatedSnippet`, `draftTranslation`) that nothing filled, and the only language check was a keyword
count. Calling an LLM per message and per draft view is slow and costs money on every open.

## Decision
- **Engine:** Helsinki-NLP `opus-mt-nl-en` (Marian, CC-BY-4.0) converted for **CTranslate2**, run int8 on CPU inside
  the api container (`app/translation/ct2.py`). Behind a `Translator` Protocol, so DeepL or an LLM can replace it
  without touching callers. Model files come from a pinned Hugging Face revision (a third-party converter repo; the
  hashes were taken from a one-time download and review of the files) with SHA-256 checks
  (`app/translation/fetch.py`), downloaded at image build (`TRANSLATION_MODEL_DIR`) or by `make translation-model`.
  No torch, no GPU.
- **Language check:** a function-word count (`app/core/language.py`), not lingua (its wheel is 170 MB and loads many
  language models for a two-way decision). Words common to both languages count for neither.
- **Lazy and cached:** nothing translates on arrival. `POST /api/inbox/translate` (session auth) runs the model for one
  text; `GET /api/inbox/threads` only reads the cache (`bodyEnglish` on messages, `englishMeaning` on drafts, plus a
  `language` flag on both so the UI knows when to offer the button). Table `translations` (migration 0038) is unique on
  `(company_id, source_hash)`, where the hash is the sha256 of the NFC-normalised, stripped text
  (`app/core/texthash.py`). A message, a draft and a repeated quote therefore share one row, and the source text is not
  stored. The English copy is personal text: `erase_person` deletes the rows of the erased person's messages (found by
  hash) before it redacts them. Draft texts are not covered, as drafts themselves are not erased there either.
- **Sentence by sentence:** the model drops everything after the first sentence of a long input, so
  `app/translation/text.py` splits into sentences (long ones at spaces), translates one batch, and rebuilds lines.
  Segments without letters (phone numbers, amounts) pass through, and Dutch abbreviations ("Dhr.", "bijv.", "nr.") do not
  end a sentence. Work is bounded: the request accepts 20000 characters, 8000 are translated, at most 80 sentences,
  batches of 32, output length proportional to the input. The route is limited to 30 per minute per owner.
- **Synchronous, not a workflow:** a translation is 0.1–0.5 s and idempotent (insert is `ON CONFLICT DO NOTHING`), runs
  in the threadpool outside any transaction, and has no side effect on a case, so it is not DBOS work (invariant 1
  concerns durable pipeline work). The model loads on first use under a lock; the API starts without it.
- **Only Dutch:** text the language check does not call Dutch (English, unknown, other languages) is not translated,
  and a model that cannot load is a 503 "not available", never a 500.
- **Safety:** the model is a seq2seq translator, not an instruction follower, so message text cannot steer it
  (invariant 6). Translations are display-only: no sender, rule or agent reads them.

## Consequences
- No per-call cost and no tenant text leaves the machine. Needs roughly 0.5–1 GB of extra RAM while loaded
  (measured peak process RSS about 420 MB in a one-off run) and about 200 MB of image size.
- Quality is good for ordinary Dutch and weaker for slang or mixed Dutch/English; the original is always shown.
- A model change should bump `engine` so old rows stay attributable; stale rows can be deleted safely (they refill).
- Not covered yet: documents/OCR text, invoices, and owner-side Super Agent text (already English).
