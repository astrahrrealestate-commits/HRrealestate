# BRIXX directory: mapper, reconcile, GDPR purge, boundary — design

Status: **autonomous, not user-approved** (written by an unattended build session) · Date: 2026-11-03 ·
Derived from the mirror design `2026-10-31-brixx-data-mirror-design.md` (itself still "draft for approval", treated
here as the design), `docs/build-plan.md` M3, `docs/tech-stack.md`, the identity-first directory
(`app/directory/identity.py`) and the BRIXXonline API documentation (entity model pp. 11-12, ZOEKID p. 7, Z-history
tables p. 8). Covers Phase D mapper, the daily reconcile, the GDPR purge and the BRIXX import/log boundary.
Out of scope: Phase B codegen of `brixx.<table>`, documents (Phase C), the status API, the Super Agent lookup tool and
the analyst DB role.

## Mapper (raw mirror -> directory)

Module `app/directory/brixx/mapper.py` (+ `columns.py`, `people.py`, `units.py`, `leases.py`). Reads the mirror only
(never the API), scoped by `company_id`, rows with `_deleted_at` or `INDVERWIJDERD` set count as ended.

| Mirror | Domain | Key (`brixx_ref`) | Validity |
|---|---|---|---|
| `prg_relatie` | `people` (+ `channel_identities` for phone -> whatsapp, email -> gmail) | `prg_relatieid` | from `newdatetime` (else today); ended -> `valid_to` = today |
| `prg_vhe` (+ `prg_object` for address/label fallback) | `units` | `prg_vheid` | same |
| `prg_contractvhe` + `prg_contract` | `leases` + `lease_parties` (`tenant` = `prg_contract.prg_relatieid`) | `<contractid>:<contractvheid>` | start/end of the contract VHE, else of the contract; ended -> min(end, today) |

- Idempotent: partial unique indexes `(company_id, brixx_ref) WHERE brixx_ref IS NOT NULL` on people, units and
  leases (new migration); `lease_parties (lease_id, person_id, role)` already unique; identities are inserted with
  `ON CONFLICT DO NOTHING` on the current-identity partial index. A second run with unchanged mirror data writes
  nothing. A per-company transaction advisory lock serialises concurrent mapper runs.
- Identity-first upgrade: a relatie without a mapped person is matched to an existing person through a current
  channel identity (normalised with `normalise_identity`, region NL) whose person has no `brixx_ref`; that person is
  upgraded (brixx_ref, name, kind), never duplicated. An identity that already belongs to another BRIXX person is
  never moved.
- `kind`: `tenant` when the relatie is the tenant of any contract; otherwise an existing kind is kept, new people are
  `other`. Owner/contractor roles need the Phase B metadata (open item).
- Column names are not known until the Phase B metadata snapshot. `columns.py` declares candidate names per field
  (first present, non-empty value wins) so a mismatch degrades to fallbacks instead of failing. A missing mirror
  table maps nothing (the codegen migration creates them).
- Runs as DBOS workflow `brixx.map_directory`, id `brixxmap:{run_id}`, as a child of every incremental and reconcile
  run (after the tables finished). Three steps (people, units, leases), each one short transaction.
- `import_id` stays NULL for BRIXX rows (it references `directory_imports`, the retired export import).

## Reconcile

Daily cron `brixx.reconcile_all` (03:00 Europe/Amsterdam), run kind `reconcile`, one child `brixx.reconcile_table` per
table (`brixxrec:{run_id}:{table}`) on the `brixx` queue. Per table:
1. Keyset scan of primary keys only (`fields=<pk>`, filter `[<pk> > cursor]`, ordered by pk, always page 1), so a
   hard delete during the scan cannot shift pages. Each page is one step that stages the keys in
   `brixx_reconcile_seen` (unique per run/table/pk: replay-safe; nothing held in memory).
2. One apply step: rows synced before the run started and absent from the staged keys get `_deleted_at = now`
   (soft); soft-deleted rows BRIXX lists again get `_deleted_at = NULL`; `INDVERWIJDERD=1` rows are BRIXX's own soft
   delete and are left as they are. Keys BRIXX has but the mirror lacks reset the table watermark, so the next
   incremental run does a full fetch (backfill). The staged keys are then deleted.

## GDPR purge

`erase_person` (app/pipeline/gdpr.py) calls `app/db/brixx_erasure.py` when the person has a `brixx_ref`: insert the
tombstone `brixx_erased_refs (company_id, relatie_id)` (unique) and delete the relatie's rows from `brixx.prg_relatie`
and `brixx.zprg_relatie`. `upsert_page` drops incoming rows of those tables whose relatie id is tombstoned, and the
mapper skips tombstoned relaties, so a re-sync never resurrects an erased person. S3 documents of the relation are
Phase C (`brixx_documents` does not exist yet).

## Boundary and redaction

- import-linter: only `app.channels.registry`, `app.workflows.deps`, `app.workflows.brixx_*` and
  `app.directory.brixx.*` import `app.channels.brixx`.
- structlog processor `redact_event` (app/core/redaction.py): values under secret keys (`authorization`, `token`,
  ...), BRIXX personal columns (`zoekid`, names, contact data) and row payload keys (`row`, `rows`, `record`, ...)
  become `[redacted]`, recursively; `Bearer <token>` inside strings is masked.
- Sentry: `EventScrubber` with the same deny list (recursive) and `include_local_variables=False`, so page rows held
  in local variables never reach an event.

## Tests

Integration (Postgres + DBOS, FakeBrixxApi, throwaway mirror schema, invented names): mapper creates, upgrades and
is idempotent; reconcile soft-deletes, restores, keeps INDVERWIJDERD rows and resets the watermark; erasure removes
mirror rows and a re-sync does not resurrect them. Unit: column pickers, redaction, Sentry options, contract present.
