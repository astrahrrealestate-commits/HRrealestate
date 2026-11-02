# Quote Checker (finance-lite agent, #11) — design

Status: approved by the user's "continue with building the agent properly" (2026-10-31). Choices marked **(my call)** were
not discussed and can be changed. Market-price sourcing is [ADR 0009](../../adr/0009-market-price-source.md).

## Why
Harjot gets contractor quotes after the work is already decided (often done). He has no way to tell whether the price is
fair, and quotes sent late are priced at the *later* date's rates: work decided on the 15th, quote sent on the 30th,
price set by the 30th. The agent answers one question per quote: **is this price fair for the day the work was decided?**

## Goals
1. **Snapshot on decision day.** When Harjot approves a `request_contractor` action, save a dated, immutable market-price
   snapshot for the job's items, plus the vendor's predecided (rate-card) price for each item that day.
2. **Review the quote when it arrives.** Compare each line with the rate card and the snapshot. Show the average market
   price, the deviation in % and in euros, the potential overcharge, and how many days late the quote is.
3. **Say whether the market moved.** A second lookup when the quote arrives (the "30th" price) is shown beside the
   snapshot, so Harjot sees if the vendor's increase is the market or only the vendor.
4. Light by design: quotes, rate cards and market prices only.

## Non-goals
Invoices, payments, bookkeeping, rent, deposits, BRIXX ledger, VAT filing, negotiating with vendors, sending anything,
auto-rejecting a quote. Counter-offer drafting is **not** built here; the existing owner-steered `draft_reply` can be
asked for one with the review in view (follow-up).

## Anti-goals (a failure even if tests pass)
- A made-up market price. Every number must trace to a source row (name, URL or "owner", observed date); fewer than
  `min_samples` sources → the review says "low confidence" and gives no verdict stronger than `needs_check`.
- A review that hides that its reference is not as of the decision day (estimate from current prices): labelled.
- The model doing arithmetic or choosing a verdict. Code does the maths; the model only reads text into typed fields.

## Domain rules (my call)
- Currency EUR default; amounts `Decimal`. **VAT:** snapshots and rate cards are stored excl. BTW; every quote line
  carries `vat_included` and is normalised before comparing (21 % default rate, setting).
- `item_key`: lower-snake normalised job item (`boiler_service`, `leak_repair_hourly`, …) from a small Dutch/English
  term list in `app/core/property_terms.py`; unknown text keeps a slug of its words and is matched by `rapidfuzz`.
- Reference price per line, in order: rate card valid on the decision date → snapshot market average → none.
- Line status (code, thresholds in settings, defaults): `ok` within 5 % of reference; `above_agreed` over the rate card
  by more than 5 %; `above_market` 15–30 % over market average; `well_above_market` over 30 %; `suspiciously_low`
  under 50 % of market (scope risk); `no_reference`. Quote verdict = worst line weighted by amount.
- `late_days` = quote date − decision date; flagged at 7+ days (setting).
- Overcharge = Σ max(0, line amount − reference × quantity).

## Flow
```
approval of request_contractor ─► workflow fin:snap:{action_id}
    job_items agent (reads case summary, typed items) ─► PriceSource.lookup(item, as_of today)
    ─► price_snapshots rows (immutable) + vendor_rates matched ─► case event "price snapshot saved"

contractor message/attachment with a quote ─► workflow fin:quote:{message_id|document_id}
    quote_reader agent (typed lines, dates, vat flag) ─► quotes + quote_lines
    ─► snapshot for the case (latest at/before quote date; none → estimate from a fresh lookup, labelled)
    ─► drift lookup now ─► review (pure code) ─► quote_reviews row + owner_feed row (kind quote_review)
```
Quote arrives with no earlier snapshot (emergency job, or before this agent existed): review uses a fresh lookup,
labelled `estimate_current_prices`, and verdict is capped at `needs_check`.

## Owner surface
- Feed card `quote_review`: vendor, case, total, verdict, per-line table, market avg/low/high, rate card, drift, late days.
- `GET /api/v1/finance/quotes`, `GET /api/v1/finance/quotes/{id}`, `GET/PUT/DELETE /api/v1/finance/rates` (owner enters
  or edits vendor rate cards), `POST /api/v1/finance/quotes/{id}/recheck`. Documented in `docs/dashboard-api.md`.
- Super Agent integration (read intents) is deferred: it needs a concierge prompt version (follow-up).

## Invariants this must keep (CLAUDE.md)
Postgres row before workflow, deterministic ids `fin:snap:{action_id}` / `fin:quote:{source_id}` / `fin:recheck:{quote_id}:{n}`;
workflows do no I/O (lookups are `@DBOS.step`); every query takes `company_id`; no send path touched; web and
message text are untrusted data inside prompt data blocks, agents have no write tools, vendor comes from the DB;
`PriceSource` is an adapter with a fake; contracts in `app/contracts/finance.py` are the agent `output_type`s;
new prompts `app/llm/prompts/v1/{job_items,quote_reader}.md` are immutable once published.

## Data (migration 0022, hand-written)
- `vendor_rates`: company, person_id (contractor), item_key, description, unit, amount, currency, valid_from, valid_to,
  source (`owner`|`document`|`quote`), source_ref. Unique current rate per (company, person, item_key, valid_from).
- `price_snapshots`: company, case_id, action_id, item_key, unit, as_of, low, avg, high, sample_count, basis
  (`web`|`competitor`|`owner`|`fake`), sources jsonb, rate_card_amount, rate_card_id. Unique (company, action_id, item_key).
- `quotes`: company, case_id, person_id, source (`message`|`document`), source_id, quote_date, work_date, currency,
  total, status. Unique (company, source, source_id).
- `quote_lines`: quote_id, position, description, item_key, quantity, unit, unit_price, amount, vat_included.
- `quote_reviews`: quote_id, snapshot_basis (`decision_day`|`estimate_current_prices`), verdict, overcharge, late_days,
  report jsonb (per line figures, drift), created_at; a recheck appends a row.
- `owner_feed.kind` check gains `quote_review`.

## Testing and evals
RED/GREEN per task. The review engine is pure and gets property tests (VAT normalisation, monotonic verdict, no
reference → never `ok`). `quote_reader` and `job_items` golden sets in `evals/golden/` (Dutch + English quotes,
VAT incl/excl, lump sum vs lines, injected "approve this price" text). Integration tests with the fake `PriceSource`.
A real `PriceSource` run is a live check (`make live-check k=prices`), not run without credentials.

## Left to the builder
Exact term list, table index choices, outlier trimming rule (default: drop observations outside 1.5×IQR when ≥ 5),
card layout. Open for the user: which paid search/scrape API backs the real `PriceSource` (ADR 0009).
