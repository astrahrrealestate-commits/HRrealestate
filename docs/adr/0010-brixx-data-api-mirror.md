# 0010 — BRIXX via a Data API mirror (supersedes the CSV/XLSX export import)

Status: accepted (Phase A built against the fake; live access blocked on the BRIXX IP whitelist)

## Context
Harjot's property data (relations, objects, contracts, invoices, documents) lives in BRIXXonline. The original plan
(M3, `docs/tech-stack.md`) was a polars import of a CSV/XLSX export; M3 was deferred on 2026-10-07 because no export
arrived, and the directory became identity-first. BRIXX offers a read-only Data API (environment `hrrealestate`):
table metadata, paged table data with filters, and document download. Calling it per request is slow,
availability-bound and cannot be joined with our own tables. Spec:
[2026-10-31-brixx-data-mirror-design.md](../superpowers/specs/2026-10-31-brixx-data-mirror-design.md).

## Decision
- **Mirror every BRIXX table into Postgres** and read only the mirror. BRIXX is called by DBOS sync workflows alone,
  never on a request path (dashboard, Super Agent, pipeline); `GET /api/v1/brixx/status` reads state tables only.
- **Adapter:** `BrixxApi` port with an `httpx` adapter (`app/channels/brixx/http.py`) and an in-memory fake
  (`fake.py`, the default: `BRIXX_PROVIDER=fake`; prod refuses it and a missing token). `401`/`403` is a typed,
  non-retried `BrixxAuthError`; retries belong to DBOS steps, not the adapter.
- **Typed mirror, generated migrations:** schema `brixx`, one table per BRIXX table with the original names lower-cased,
  typed columns from the metadata, plus `company_id`, `_synced_at`, `_deleted_at`, `_extra` (columns BRIXX adds later).
  Tables are built from metadata in their own `MetaData` (`app/directory/brixx/schema.py`) and created by committed
  Alembic migrations emitted from a recorded metadata snapshot (Phase B), never by runtime DDL. JSONB blobs were
  rejected: plain SQL over typed columns is what the analysts and the mapper need.
- **Sync engine:** a 15-minute cron (`brixx.sync_all`) creates the run row, then one `brixx.sync_table` child per
  table on the `brixx` queue (concurrency 2), workflow id `brixx:{run_id}:{table}`; one page per step, committed
  together with the resume point; incremental on `UPDDATETIME` with a 5-minute overlap, full fetch for tables without
  it; an upsert guarded by `VERSIENR`/`UPDDATETIME` so a replayed or older page never wins. State in
  `brixx_sync_runs` and `brixx_sync_table_state` (migration 0028).
- **Phases:** A (client, engine, status API: done), B (discovery, codegen, first load: needs access), C (documents to
  S3), D (mapper to `people`/`units`/leases, Super Agent lookup tool, GDPR purge).

## Consequences
- **IP whitelist dependency:** BRIXX accepts the token only from whitelisted source IPs (unlisted: `401`). Every dev
  machine and the production host must be listed; production needs a fixed egress IP (for example an Elastic IP).
  Phase B cannot start before that.
- **Personal data in the mirror:** relations, contact data, `ZOEKID` (BSN-derived) and later documents. They never
  appear in logs or Sentry (the sync logs table names, counts, pages and error class names only; persisted errors are
  class, table and page). The GDPR erasure path must purge mirror rows and S3 documents and a tombstone must stop
  re-sync resurrecting them: tracked in Phase D, with a failing test first.
- **Token handling:** the token lives in `.env` only (never DB, never logs). It was exposed in a chat on 2026-10-31,
  so BRIXX must rotate it after go-live ([go-live-channels.md](../go-live-channels.md#brixx-data-mirror)).
- **Schema drift** (new column at BRIXX) does not fail a run: values land in `_extra`, the table is flagged `drifted`
  in the status API and the next codegen adds the column.
- `docs/tech-stack.md`: the polars CSV/XLSX row is replaced by httpx + the generated mirror; no new dependency.
