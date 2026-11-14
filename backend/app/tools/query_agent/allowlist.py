"""Allowlists and security constraints for the Custom Query Agent."""

ALLOWED_VIEWS = frozenset(
    {
        "v_active_leases",
        "v_case_overview",
        "v_task_overview",
        "v_scheduled_visits",
        "v_message_stats",
        "v_rent_ledger",
        "v_monthly_rent_summary",
        "v_unit_profitability",
        "v_waiting_radar",
        "v_vendor_rates",
        "v_documents_overview",
        "v_approval_audit",
        "v_send_stats",
    }
)

# Business tables allowed if explicit join with views is needed
ALLOWED_BASE_TABLES = frozenset(
    {
        "cases",
        "units",
        "people",
        "leases",
        "lease_parties",
        "actions",
        "case_links",
        "tasks",
        "calendar_events",
        "messages",
        "quotes",
        "quote_lines",
        "quote_reviews",
        "tenant_rent_payments",
        "monthly_rent_summaries",
        "vendor_rates",
        "price_snapshots",
        "waits",
        "documents",
        "document_links",
        "person_profiles",
        "understandings",
        "dd_reviews",
        "memory_items",
    }
)

ALL_ALLOWED_RELATIONS = ALLOWED_VIEWS | ALLOWED_BASE_TABLES

# Strictly allowlisted safe analytical functions (case-insensitive)
ALLOWED_FUNCTIONS = frozenset(
    {
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "coalesce",
        "date_trunc",
        "timestamp_trunc",
        "lower",
        "upper",
        "round",
        "now",
        "cast",
        "abs",
        "nullif",
        "greatest",
        "least",
        "concat",
        "length",
        "trim",
        "split_part",
        "substring",
        # sqlglot parses these operators and keywords as function nodes; they run nothing
        "and",
        "or",
        "case",
        "if",
        "extract",
        "current_date",
        "current_timestamp",
    }
)

# Explicitly banned functions (redundant belt-and-suspenders check)
BANNED_FUNCTIONS = frozenset(
    {
        "pg_sleep",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "query_to_xml",
        "dblink",
        "set_config",
        "current_setting",
        "lo_import",
        "lo_export",
        "pg_terminate_backend",
        "pg_cancel_backend",
    }
)

# Explicitly forbidden secrets, auth, PII-heavy audit targets & system tables
BLOCKED_RELATIONS = frozenset(
    {
        "owner_accounts",
        "allowed_users",
        "companies",
        "channel_accounts",
        "gmail_sync_state",
        "owner_personas",
        "owner_outbox",
        "sends",
        "channel_identities",
        "approvals",
        "alembic_version",
        "dbos_sys",
        "dbos_workflow_status",
        "raw_events",
        "model_calls",
        "translations",
        "brixx_sync_runs",
        "brixx_sync_table_state",
        "brixx_documents",
        "brixx_erased_refs",
        "brixx_reconcile_seen",
        "agent_conversations",
        "agent_turns",
        "agent_page_state",
    }
)
