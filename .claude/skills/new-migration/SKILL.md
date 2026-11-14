---
name: new-migration
description: Create and validate an EstateOS Alembic migration after changing SQLAlchemy models. Use whenever backend/app/db/models changes, a table/column/index/constraint is added, or the user says "migration".
---

# /new-migration

Committed migrations are immutable (hook-enforced). Every schema change = a new revision.

1. Change models in `backend/app/db/models/`. Every domain table: `company_id` FK + index; UUIDv7 `id`; `created_at`.
2. Stack DB up: `make up-db`.
3. Generate: `make migration m="<imperative summary>"` (autogenerate; revision ids are sequential `0002`, `0003`, …).
4. **Read the generated file fully.** Autogenerate misses or mangles:
   - partial unique indexes (`postgresql_where=`), server defaults, renames (shows as drop+add — rewrite as `alter_column`/`op.rename_table`), CHECK constraints.
   - downgrade must exactly reverse upgrade.
   - **Enum columns (VARCHAR + CHECK):** handled automatically by `backend/app/db/alembic_hooks.py` (renders `sa.String` +
     one `op.create_check_constraint(op.f("ck_<table>_<column>"), ...)`). **Adding a value to an existing StrEnum**
     is NOT detected by autogenerate: write `op.drop_constraint` + `op.create_check_constraint` by hand.
     `test_every_enum_column_check_matches_model_values` fails until you do.
5. Data-touching migrations: batch large updates, never load whole tables into Python.
6. Validate: `make migrate-roundtrip` (upgrade head → downgrade base → upgrade head) and `make alembic-check` (no drift).
7. Add/extend an integration test for each new unique constraint (insert twice → `IntegrityError`).
8. `/check` full tier.
