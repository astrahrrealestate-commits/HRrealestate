# BRIXX data mirror — design

Status: draft for approval · Date: 2026-10-31 · Replaces the deferred M3 "BRIXX export import" (CSV/XLSX) with the BRIXXonline Data API.

## Intent

Harjot's property data lives in BRIXXonline. EstateOS (dashboard, Super Agent, case linking, drafts) needs it constantly.
Calling the BRIXX API per question is slow, rate/availability-bound, and cannot be joined with our own tables.
So: **mirror all BRIXX data into our Postgres, keep it fresh incrementally, and read everything from the database.**
The BRIXX API is only ever called by the sync workflows, never on a request path.

## Goals

1. Every table the BRIXX API exposes for environment `hrrealestate` (current tables, `Z*` history tables, document metadata) lands in Postgres with typed columns and original BRIXX names, queryable with plain SQL.
2. Documents and photos (`PRG_DOCUMENT` files) are downloaded to S3 and linked to their rows.
3. Incremental sync (minutes-level freshness), a periodic full reconcile (detects hard deletes and missed updates), resumable after any crash.
4. A thin mapper fills the existing `people`, `units`, leases and `brixx_ref` columns from the mirror, so linking, cases and the Super Agent use BRIXX identities.
5. Sync status is visible (API + dashboard read model): last run, rows per table, errors, drift.

## Non-goals / anti-goals

- No writes to BRIXX. The API is read-only; we never try.
- No BRIXX API call on any request path (dashboard, Super Agent, pipeline). Failure of BRIXX must not break those.
- No hand-rolled scheduling, retry or queue code (DBOS), no new HTTP/SQL tooling beyond httpx, SQLAlchemy, Alembic.
- Not a replacement of domain tables: the mirror is a read-only copy; domain logic reads mapped tables, not raw BRIXX names.
- Failure even if technically working: silent partial syncs, token or personal data in logs, a mirror that is stale with no signal.

## Fixed by the user

- Pull everything, including personal data (`PRG_RELATIE.ZOEKID` = last 3 BSN digits + birth date + surname initial) and personal documents.
- Two layers: raw mirror, then mapping into existing directory tables.

## Facts from the API doc (page refs: BRIXXonline_API_Documentation_hrrealestate_EN.pdf)

- Base `https://mob.brixxonline.com/api/v1`; metadata at `/metadata/hrrealestate/tables` and `/tables/{name}`; data at `/bigdata/hrrealestate/table/{name}`; files at `/bigdata/hrrealestate/document/{id}`.
- Auth: access token in `Authorization` header **and** source-IP whitelist. Unlisted IP yields `401 Unauthorized` (observed 2026-10-31 from the dev machine, both raw and `Bearer` forms).
- Query: `fields` (`+`-separated), `fieldIds` (`1-10,15`), `filters` (`[col op value]`, operators `< <= > >= = <> LIKE`, `and`/`or`, parentheses, dates `yyyy-MM-dd`), `page`, `orderby`, `includeAttributes`. Page size depends on column count (example: 52).
- Response: `{meta:{currentPage,perPage}, links:{next}, data:[...]}`. Null values appear as `{}` (see `"website": {}`), not `null`.
- Common columns seen: `<TABLE>ID` (PK), `VERSIENR`, `NEWDATETIME`, `UPDDATETIME`, `NEWUSERNM`, `UPDUSERNM`, `INDVERWIJDERD` (soft delete flag).
- Metadata field types seen: `NUMBER`, `VARCHAR(n)`; foreign keys listed via `references.foreignKeyTable/Field`.
- History: `Z<TABLE>` has the same columns plus its own `Z<TABLE>ID` PK; the current table's PK repeats across versions.
- Documents: `PRG_DOCUMENT` (ids), `PRG_DOCUMENTLINK` (`sys_entiteittypeid` + `entiteitid`), download needs the "personal data" permission.
- Unknown until access works: full table list, exact types (dates, decimals), rate limits, max page size, which tables have `UPDDATETIME`.

## Architecture

```
BRIXX API ──httpx──▶ app/brixx/client.py (adapter, interface + fake)
                         │
        DBOS cron ──▶ app/workflows/brixx_sync.py ──▶ brixx.<table> (typed raw mirror, schema `brixx`)
                         │                               │
                         ├─ documents queue ──▶ S3       └─▶ app/brixx/mapper.py ──▶ people / units / leases
                         └─ brixx.sync_runs / sync_table_state (status, cursors)
```

Modules (each < 300 lines, one purpose): `app/brixx/{client,models_meta,schema_codegen,sync,reconcile,documents,mapper}.py`,
`app/workflows/brixx_sync.py`, `app/db/models/brixx.py` (state tables only), `app/api/v1/brixx.py` (status read model).
Import-linter: pipeline and agents may read the mirror and mapped tables; only `app/brixx/` may import the client.

### Storage: typed mirror via generated migrations

- Schema `brixx`. One table per BRIXX table, **same name lower-cased, same column names**, plus `company_id uuid NOT NULL`, `_synced_at timestamptz`, `_deleted_at timestamptz NULL`, `_extra jsonb` (columns BRIXX adds later that we have no column for yet, so nothing is dropped).
- PK: `(company_id, <pk column>)` for current tables; `(company_id, z<table>id)` for history tables. Upsert with `INSERT ... ON CONFLICT DO UPDATE` guarded by `VERSIENR`/`UPDDATETIME` so older pages never overwrite newer rows (idempotent).
- Type map from metadata: `NUMBER` on `*ID`/FK columns → `bigint`; other `NUMBER` → `numeric` (no precision, avoids truncation); `VARCHAR(n)` → `varchar(n)`; date/time types → `date` / `timestamptz` (Europe/Amsterdam source, stored UTC); unknown type → `text`. `{}` normalised to `NULL`.
- Foreign keys from metadata become real FKs only in a second, deferred step (mirror loads pages in arbitrary order). Until then, indexes on FK columns.
- **Tables are created by committed Alembic migrations, not at runtime** (invariant 9: migrations immutable; CLAUDE.md: Alembic owns schema). `make brixx-codegen` reads a recorded metadata snapshot (`tests/fixtures/brixx/metadata/*.json`) and emits a migration. Schema drift at sync time (new table, new column, type change) is detected by comparing live metadata to the snapshot: the run continues, new columns land in `_extra`, the table is flagged `drifted` in the status API, and the next codegen produces a new migration.
- State tables in `public`: `brixx_sync_runs` (run id, kind incremental|reconcile, status, started/finished, error), `brixx_sync_table_state` (company_id, table, last_success_upd, last_page, row_count, last_error, drifted), `brixx_documents` (document id, sha256, s3_key, size, status).

### Sync (DBOS)

- Cron workflow `brixx_incremental` (default every 15 min; setting `brixx_sync_interval_minutes`) enqueues one child workflow per table on a `brixx` queue (worker_concurrency 2, so BRIXX is not hammered). Workflow id `brixx:{run_id}:{table}`; deterministic, no I/O in workflow bodies.
- Per table: step loop over pages. Each page is one `@DBOS.step` (fetch, normalise, upsert in one short transaction, advance `last_page`). Retry with DBOS step retries; `401`/`403` is non-retryable and raises a typed `BrixxAuthError`.
- Incremental filter: `[upddatetime >= <last_success_upd - 5 min overlap>]`, ordered by `upddatetime`. Tables without `UPDDATETIME` always do a full fetch with hash compare (so unchanged rows are not rewritten).
- First run per table is a full load (no filter). A table is never marked successful until `links.next` is exhausted.
- Cron workflow `brixx_reconcile` (default daily 03:00 Europe/Amsterdam): full fetch of primary keys per table, rows missing from BRIXX get `_deleted_at` (soft). `INDVERWIJDERD=1` rows are kept as-is (BRIXX's own soft delete).
- History `Z*` tables: append-only fetch keyed by their own PK; incremental on `UPDDATETIME` where present.
- Documents: after `PRG_DOCUMENT`/`PRG_DOCUMENTLINK` sync, a `documents`-queue workflow per new/changed document id downloads the file with the S3 adapter, stores sha256 and key, idempotent via `brixx_documents` unique `(company_id, document_id, sha256)`. Needs the personal-data permission; if missing, status `forbidden` and surfaced.
- Single BRIXX environment per company in Phase 1: `company_id` from settings; env name `hrrealestate`, base URL and token from `Settings` (`.env`). Token never stored in DB, never logged; `structlog` redaction covers the `Authorization` header and row values.

### Mapper (raw → domain)

Idempotent, runs after each successful table sync (deterministic workflow id `brixxmap:{run_id}`):
`PRG_RELATIE` → `people` (+ contact data → `channel_identities` where phone/email exist; kind from role), `PRG_OBJECT`/VHE → `units` (address, label), `PRG_CONTRACT` + `PRG_CONTRACTVHE` → leases and lease parties (tenant, co_tenant, guarantor). `brixx_ref` = BRIXX primary key as string; `import_id` becomes nullable provenance (`brixx_sync_runs.id`). Exact column mapping fixed after the metadata snapshot exists (known gap, see Open items). Existing identity-first people created from messages are matched by phone/email and upgraded, never duplicated.

### Access paths

- Read-only `/api/v1/brixx/status` (runs, per-table counts, lag, drift, document backlog).
- Super Agent reads mapped domain tables as today; a read-only "BRIXX lookup" tool over curated mirror views (contracts, payment rules, invoices, arrears) comes after the mapper; it has no write tools and no free SQL.
- Developers and Harjot's analysts use SQL on schema `brixx` through a dedicated read-only DB role.

### GDPR and security

- Mirror holds BSN-derived `ZOEKID`, relations, contact data and documents. The existing erasure path (`app/pipeline/gdpr.py`) must also purge the person's mirror rows and S3 documents; add a failing test first. Re-sync must not resurrect an erased person: `brixx_erased_refs` tombstone table checked by the upsert.
- `ZOEKID`, names and document contents never appear in info logs or Sentry.
- Token: exposed in a chat transcript on 2026-10-31. Ask BRIXX to rotate it after go-live and use a token per environment. Dev machine and production host IPs must each be whitelisted; production needs a fixed egress IP (Elastic IP).
- Send isolation unaffected: mirror data supplies recipients only through the DB-resolved identity rules already in place.

## Phasing

| Phase | Needs access? | Delivers |
|---|---|---|
| A. Client + engine | no | `BrixxClient` interface, httpx adapter, fake, recorded-fixture format, page/filter builder, `{}`→NULL normaliser, upsert engine, sync state tables, DBOS workflows, tests against the fake and a Postgres testcontainer |
| B. Discovery + first load | **yes (IP whitelist)** | metadata snapshot fixtures, `make brixx-codegen`, migration for all tables, first full load, row counts vs BRIXX UI, `make live-check k=brixx` |
| C. Documents | yes | S3 download workflow, backlog metric |
| D. Mapper + lookup tool | yes | people/units/leases fill, Super Agent tool, GDPR purge test |

## Testing

Unit: filter/URL encoding, type map, `{}` normalisation, pagination via `links.next`, idempotent upsert (replay a page twice, older version never wins), drift detection. Integration (testcontainers Postgres + DBOS): crash mid-table then resume, reconcile marks deletes, document download idempotency, erasure removes mirror rows. Live: `make live-check k=brixx` counts every table against the live API (go-live gate).

## Decisions for the builder (my calls, marked)

- Typed tables via generated migrations rather than JSONB blobs or runtime DDL (my call: SQL ergonomics, matches the Alembic rule).
- 15 min incremental, daily reconcile, 5 min overlap, queue concurrency 2 (my call; no rate limit info yet).
- Soft-delete via `_deleted_at` on reconcile (my call).
- Needs ADR 0007 ("BRIXX via Data API mirror, supersedes CSV import") and `docs/tech-stack.md` update (polars/CSV row replaced by httpx + generated mirror).

## Open items

1. IP whitelist for the dev machine (`115.246.217.246` at time of writing) and later the production egress IP (owner: user with Harjot).
2. Whether the token has the personal-data permission (affects documents, `ZOEKID`).
3. Full table list, real column types, rate limits: known only after Phase B discovery. The column mapping in the mapper and any type-map corrections are finalised then.
4. How `PRG_RELATIE` stores phone/email for `channel_identities` (Phase D, from metadata).
