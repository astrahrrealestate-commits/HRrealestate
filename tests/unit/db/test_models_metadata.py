from sqlalchemy import Index, Table, UniqueConstraint

import app.db.models  # noqa: F401  (registers tables)
from app.db.base import Base

SPEC_TABLES = {
    "companies", "channel_accounts", "owner_accounts", "gmail_sync_state", "directory_imports", "people",
    "channel_identities", "units", "leases", "lease_parties", "raw_events", "messages", "attachments",
    "understandings", "cases", "case_links", "case_events", "actions", "action_revisions", "approvals", "sends",
    "timers", "outcomes", "model_calls",
    # phase 1 agents (spec 2026-10-07)
    "tasks", "waits", "documents", "metric_snapshots", "owner_outbox",
    # dashboard (spec 2026-10-15)
    "owner_feed", "agent_conversations", "agent_turns",
    # live chat awareness (amendment 2026-10-22, Task 4: page pre-warm, one row per owner)
    "agent_page_state",
    # document intelligence (spec 2026-10-21)
    "document_chunks", "document_links", "drive_reorg_plans", "drive_reorg_items",
    # memory workspace (spec 2026-10-23)
    "person_profiles", "memory_items",
    # calendar scheduling agent (PR #15; migration 0021_calendar_events)
    "calendar_events",
    # quote checker (spec 2026-10-31)
    "vendor_rates", "price_snapshots", "quotes", "quote_lines", "quote_reviews",
    # due diligence lite (spec 2026-10-31)
    "dd_reviews", "dd_review_documents", "dd_document_reads",
}  # fmt: skip


def _uniques(table: Table) -> set[tuple[str, ...]]:
    out = {tuple(c.name for c in u.columns) for u in table.constraints if isinstance(u, UniqueConstraint)}
    out |= {tuple(c.name for c in i.columns) for i in table.indexes if i.unique}
    return out


def test_exact_table_set() -> None:
    assert set(Base.metadata.tables) == SPEC_TABLES


def test_every_table_has_uuid_pk_and_created_at_and_domain_tables_are_company_scoped() -> None:
    for name, table in Base.metadata.tables.items():
        assert [c.name for c in table.primary_key.columns] == ["id"], name
        assert "created_at" in table.c, name
        if name != "companies":
            assert "company_id" in table.c, name
            assert not table.c.company_id.nullable, name
            assert any(fk.column.table.name == "companies" for fk in table.c.company_id.foreign_keys), name


def test_critical_unique_constraints_present() -> None:
    t = Base.metadata.tables
    assert ("company_id", "provider", "provider_msg_id") in _uniques(t["raw_events"])
    assert ("company_id", "channel", "provider_msg_id") in _uniques(t["messages"])
    assert ("idempotency_key",) in _uniques(t["sends"])
    assert ("company_id", "dedupe_key") in _uniques(t["timers"])
    assert ("action_id", "draft_version") in _uniques(t["approvals"])
    assert ("company_id", "channel", "identity") in _uniques(t["channel_identities"])
    assert ("message_id",) in _uniques(t["case_links"])
    assert ("message_id",) in _uniques(t["understandings"])
    assert ("action_id", "draft_version") in _uniques(t["action_revisions"])
    assert ("owner_id",) in _uniques(t["agent_page_state"])  # one pre-warmed page per owner (upsert target)


def test_current_identity_unique_is_partial() -> None:
    idx = next(i for i in Base.metadata.tables["channel_identities"].indexes if i.unique)
    where = idx.dialect_options["postgresql"]["where"]
    assert "valid_to IS NULL" in str(where)


def test_all_timestamps_timezone_aware() -> None:
    from sqlalchemy import DateTime

    for table in Base.metadata.tables.values():
        for col in table.c:
            if isinstance(col.type, DateTime):
                assert col.type.timezone, f"{table.name}.{col.name}"


def test_enum_checks_named_by_column() -> None:
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        for col in table.c:
            if isinstance(col.type, sa.Enum):
                assert f"CONSTRAINT ck_{table.name}_{col.name} CHECK" in ddl, f"{table.name}.{col.name}"


def test_company_id_indexed_exactly_once_as_leading_column() -> None:
    for name, table in Base.metadata.tables.items():
        if name == "companies":
            continue
        leading = [i for i in table.indexes if i.columns.keys()[0] == "company_id"]
        leading += [
            u for u in table.constraints if isinstance(u, UniqueConstraint) and u.columns.keys()[0] == "company_id"
        ]
        usable = [i for i in leading if not isinstance(i, Index) or i.dialect_options["postgresql"]["where"] is None]
        assert len(usable) >= 1, f"{name}: company_id not leading any full index"
        single = [i for i in table.indexes if i.columns.keys() == ["company_id"]]
        assert not (single and len(usable) > 1), f"{name}: redundant single-column company_id index"
