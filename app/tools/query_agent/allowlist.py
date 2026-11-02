"""Allowlists and security constraints for the Custom Query Agent."""

ALLOWED_VIEWS = frozenset({
    "v_active_leases",
    "v_case_overview",
    "v_task_overview",
    "v_scheduled_visits",
    "v_message_stats",
})

# Business tables allowed if explicit join with views is needed
ALLOWED_BASE_TABLES = frozenset({
    "cases",
    "units",
    "people",
    "leases",
    "lease_parties",
    "tasks",
    "calendar_events",
    "messages",
})

ALL_ALLOWED_RELATIONS = ALLOWED_VIEWS | ALLOWED_BASE_TABLES

# Strictly allowlisted safe analytical functions (case-insensitive)
ALLOWED_FUNCTIONS = frozenset({
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
    "concat",
})

# Explicitly banned functions (redundant belt-and-suspenders check)
BANNED_FUNCTIONS = frozenset({
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
})

# Explicitly forbidden secrets & system tables
BLOCKED_RELATIONS = frozenset({
    "owner_accounts",
    "channel_accounts",
    "gmail_sync_state",
    "alembic_version",
    "dbos_sys",
    "dbos_workflow_status",
    "raw_events",
})
