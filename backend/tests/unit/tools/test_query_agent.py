"""Unit and red-team security tests for the Custom Query Agent."""

from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.core.settings import Settings
from app.tools.query_agent.agent import SQLQueryProposal, format_answer, run_query_agent, sanitize_rows_for_display
from app.tools.query_agent.executor import execute_readonly_query
from app.tools.query_agent.validator import SQLSecurityError, validate_and_wrap_sql

SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@localhost:1/db",
    env="test",
    _env_file=None,
)


# ==============================================================================
# 1. AST VALIDATOR TESTS (VALID QUERIES)
# ==============================================================================


def test_valid_select_query_is_wrapped():
    sql = "SELECT unit_address, urgency FROM v_case_overview WHERE state = 'open'"
    wrapped = validate_and_wrap_sql(sql, max_limit=50)
    assert wrapped.startswith(
        "SELECT * FROM (SELECT unit_address, urgency FROM v_case_overview WHERE state = 'open') AS q LIMIT 50"
    )


def test_valid_aggregate_functions_allowed():
    sql = (
        "SELECT count(*), lower(category), date_trunc('month', opened_at) FROM v_case_overview "
        "GROUP BY category, date_trunc('month', opened_at)"
    )
    wrapped = validate_and_wrap_sql(sql)
    assert "COUNT(*)" in wrapped
    assert "LOWER(category)" in wrapped
    assert "DATE_TRUNC" in wrapped


def test_valid_cte_with_internal_alias_allowed():
    sql = "WITH active_cases AS (SELECT * FROM v_case_overview WHERE state = 'open') SELECT * FROM active_cases"
    wrapped = validate_and_wrap_sql(sql)
    assert "active_cases" in wrapped
    assert "LIMIT 50" in wrapped


def test_query_strips_comments_and_normalizes():
    sql = "/* malicious trailing attempt */ SELECT unit_address FROM v_case_overview -- trailing comment"
    wrapped = validate_and_wrap_sql(sql)
    assert "/*" not in wrapped
    assert "--" not in wrapped
    assert "SELECT unit_address FROM v_case_overview" in wrapped


# ==============================================================================
# 2. RED-TEAM SECURITY ATTACKS (MUST RAISE SQLSecurityError)
# ==============================================================================


def test_reject_a_schema_qualified_mirror_table():
    with pytest.raises(SQLSecurityError, match="Schema"):
        validate_and_wrap_sql("SELECT * FROM brixx.v_lease_facts")
    assert "v_lease_facts" in validate_and_wrap_sql("SELECT * FROM public.v_lease_facts")


def test_reject_insert_mutation():
    with pytest.raises(SQLSecurityError):
        validate_and_wrap_sql("INSERT INTO v_case_overview (summary) VALUES ('fake')")


def test_reject_update_mutation():
    with pytest.raises(SQLSecurityError):
        validate_and_wrap_sql("UPDATE v_case_overview SET summary = 'hacked'")


def test_reject_delete_mutation():
    with pytest.raises(SQLSecurityError):
        validate_and_wrap_sql("DELETE FROM v_case_overview WHERE 1=1")


def test_reject_drop_mutation():
    with pytest.raises(SQLSecurityError):
        validate_and_wrap_sql("DROP TABLE units CASCADE")


def test_reject_data_modifying_cte():
    sql = "WITH deleted AS (DELETE FROM cases WHERE 1=1 RETURNING *) SELECT * FROM deleted"
    with pytest.raises(SQLSecurityError, match="Prohibited SQL operation"):
        validate_and_wrap_sql(sql)


def test_reject_stacked_queries():
    sql = "SELECT * FROM v_case_overview; DROP TABLE units;"
    with pytest.raises(SQLSecurityError, match="Query must contain exactly one statement"):
        validate_and_wrap_sql(sql)


def test_reject_for_update_locking():
    sql = "SELECT * FROM v_case_overview FOR UPDATE"
    with pytest.raises(SQLSecurityError, match="Prohibited SQL operation"):
        validate_and_wrap_sql(sql)


def test_reject_select_into_table():
    sql = "SELECT * INTO stolen_cases FROM v_case_overview"
    with pytest.raises(SQLSecurityError, match="Prohibited SQL operation"):
        validate_and_wrap_sql(sql)


def test_reject_forbidden_secrets_tables():
    with pytest.raises(SQLSecurityError, match="Access to sensitive table"):
        validate_and_wrap_sql("SELECT * FROM owner_accounts")

    with pytest.raises(SQLSecurityError, match="Access to sensitive table"):
        validate_and_wrap_sql("SELECT * FROM gmail_sync_state")


def test_reject_non_allowlisted_tables():
    with pytest.raises(SQLSecurityError, match="not in the allowed relations list"):
        validate_and_wrap_sql("SELECT * FROM pg_catalog.pg_tables")

    with pytest.raises(SQLSecurityError, match="not in the allowed relations list"):
        validate_and_wrap_sql("SELECT * FROM information_schema.tables")


def test_reject_banned_dangerous_functions():
    with pytest.raises(SQLSecurityError, match="explicitly forbidden"):
        validate_and_wrap_sql("SELECT pg_sleep(5)")

    with pytest.raises(SQLSecurityError, match="explicitly forbidden"):
        validate_and_wrap_sql("SELECT pg_read_file('/etc/passwd')")

    with pytest.raises(SQLSecurityError, match="explicitly forbidden"):
        validate_and_wrap_sql("SELECT dblink('host=evil', 'SELECT 1')")

    with pytest.raises(SQLSecurityError, match="explicitly forbidden"):
        validate_and_wrap_sql("SELECT query_to_xml('SELECT 1', true, true, '')")


# ==============================================================================
# 3. EXECUTOR & RLS TESTS
# ==============================================================================


def test_executor_sets_parameterized_rls_config():
    mock_engine = MagicMock()
    mock_session = MagicMock()
    mock_session.__enter__.return_value = mock_session
    mock_cursor = MagicMock()
    mock_cursor.keys.return_value = ["count"]
    mock_cursor.fetchall.return_value = [(3,)]
    mock_session.execute.return_value = mock_cursor

    company_id = uuid4()
    with patch("app.tools.query_agent.executor.Session", return_value=mock_session):
        res = execute_readonly_query(mock_engine, company_id, "SELECT * FROM v_case_overview LIMIT 50")
        assert res.ok is True
        assert res.row_count == 1
        assert res.rows == [{"count": 3}]

        # Verify set_config was executed with company_id
        first_call = mock_session.execute.call_args_list[0]
        sql_text = str(first_call.args[0])
        params = first_call.args[1]
        assert "set_config" in sql_text
        assert params == {"cid": str(company_id)}


# ==============================================================================
# 4. AGENT RETRY & FORMATTING TESTS
# ==============================================================================


def test_format_answer_empty_rows():
    ans = format_answer("Show arrears", [], 0)
    assert "found 0 matching entries" in ans


def test_format_answer_single_scalar():
    ans = format_answer("How many urgent tickets?", [{"urgent_count": 5}], 1)
    assert "**Result:** **5**" in ans


def test_run_query_agent_retries_on_security_error_and_succeeds():
    mock_engine = MagicMock()
    company_id = uuid4()

    # First attempt generates forbidden table, second attempt generates valid view
    bad_proposal = SQLQueryProposal(sql="SELECT * FROM owner_accounts", rationale="Bad attempt")
    good_proposal = SQLQueryProposal(sql="SELECT * FROM v_case_overview", rationale="Good attempt")

    mock_exec_res = MagicMock()
    mock_exec_res.ok = True
    mock_exec_res.rows = [{"summary": "Leak"}]
    mock_exec_res.row_count = 1
    mock_exec_res.duration_ms = 15.0

    with (
        patch("app.tools.query_agent.agent.propose_sql", side_effect=[bad_proposal, good_proposal]),
        patch("app.tools.query_agent.agent.execute_readonly_query", return_value=mock_exec_res) as mock_exec,
    ):
        resp = run_query_agent(mock_engine, SETTINGS, company_id, "List cases")
        assert resp.ok is True
        assert resp.row_count == 1
        assert "Leak" in resp.answer
        mock_exec.assert_called_once()


def test_propose_sql_uses_the_configured_llm_when_groq_has_no_key():
    from app.llm.calls import CallResult
    from app.tools.query_agent.agent import propose_sql

    settings = SETTINGS.model_copy(update={"llm_model": "google-gla:gemini-2.5-flash", "groq_api_key": None})
    proposal = SQLQueryProposal(sql="SELECT * FROM v_active_leases;", rationale="leases")
    with patch("app.tools.query_agent.agent.run_agent", return_value=CallResult(proposal, uuid4())) as run:
        got = propose_sql("List active leases", settings, engine=MagicMock(), company_id=uuid4())
    assert got is not None
    assert got.sql == "SELECT * FROM v_active_leases"
    assert run.call_args.args[2].prompt.name == "query_agent"


def test_propose_sql_without_groq_or_engine_returns_none():
    from app.tools.query_agent.agent import propose_sql

    assert propose_sql("List active leases", SETTINGS) is None


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM v_active_leases WHERE is_active = TRUE AND end_date < '2028-01-01'",
        "SELECT a FROM v_active_leases WHERE x = 1 OR y = 2",
        "SELECT CASE WHEN a > 1 THEN 'x' ELSE 'y' END FROM v_case_overview",
        "SELECT a FROM v_case_overview WHERE created_at > CURRENT_DATE - INTERVAL '30 days'",
        "SELECT a FROM v_case_overview WHERE created_at > NOW() - INTERVAL '30 days'",
        "SELECT EXTRACT(YEAR FROM end_date) FROM v_active_leases",
    ],
)
def test_common_operators_and_keywords_are_not_rejected_as_functions(sql: str):
    assert "LIMIT 50" in validate_and_wrap_sql(sql, max_limit=50)


@pytest.mark.parametrize(
    "sql",
    ["SELECT pg_sleep(5) FROM v_case_overview", "SELECT a FROM v_case_overview WHERE x = 1 AND pg_sleep(1) IS NULL"],
)
def test_banned_functions_stay_rejected_inside_an_and(sql: str):
    with pytest.raises(SQLSecurityError):
        validate_and_wrap_sql(sql, max_limit=50)


def test_sanitize_rows_for_display_strips_internal_ids_and_formats_values():
    case_uuid = UUID("01a1ca59-c6cb-7e02-bd67-f86ff1b72267")
    raw_row = {
        "lease_id": "01a19be8-29ae-7cf0-b698-4b5dbbdea65e",
        "unit_id": "01a19be8-0000-0000-0000-000000000001",
        "case_id": case_uuid,
        "unit_address": "Keizersgracht 42-A, 1015 CR Amsterdam",
        "unit_label": "Keizersgracht 42-A",
        "tenant_name": "Vipin Tyagi",
        "valid_from": "2026-11-02",
        "opened_at": "2026-11-11 11:24:03.646025+00:00",
        "is_active": True,
    }
    cols, display_rows = sanitize_rows_for_display([raw_row, dict(raw_row)])

    assert cols == ["Ticket", "Property", "Tenant", "Lease Start", "Opened", "Status"]
    assert len(display_rows) == 1
    row = display_rows[0]
    assert row["Ticket"] == "#b72267"
    assert row["Property"] == "Keizersgracht 42-A, 1015 CR Amsterdam"
    assert row["Tenant"] == "Vipin Tyagi"
    assert row["Lease Start"] == "02 Nov 2026"
    assert row["Opened"] == "11 Nov 2026, 12:24"
    assert row["Status"] == "Active"


def test_format_answer_renders_clean_bullets_without_pipes_or_uuids():
    rows = [
        {
            "case_id": "01a1ca59-c6cb-7e02-bd67-f86ff1b72267",
            "unit_address": "Keizersgracht 42-B, 1015 CS Amsterdam",
            "tenant_name": "Anouk de Jong",
            "urgency": "emergency",
            "opened_at": "2026-11-11 11:24:03.646025+00:00",
            "summary": "Water leaking from upstairs ceiling.",
        },
        {
            "case_id": "01a1af60-2b7b-78f0-9bf0-22a937afccdb",
            "unit_address": "Keizersgracht 42-A, 1015 CR Amsterdam",
            "tenant_name": "Vipin Tyagi",
            "urgency": "high",
            "opened_at": "2026-11-10 09:15:00+00:00",
            "summary": "Heating stopped working.",
        },
    ]
    ans = format_answer("show open tickets", rows, 2)
    assert " | " not in ans
    assert "01a1ca59-c6cb-7e02-bd67-f86ff1b72267" not in ans
    assert "#b72267" in ans
    assert "11 Nov 2026, 12:24" in ans
    assert "Anouk de Jong" in ans


@pytest.mark.parametrize(
    "sql",
    [
        (
            "SELECT unit_address, collected_rent_eur, maintenance_cost_eur, net_profit_eur "
            "FROM v_unit_profitability ORDER BY net_profit_eur DESC"
        ),
        "SELECT tenant_name, unit_address, overdue_eur, overdue_days FROM v_rent_ledger WHERE overdue_eur > 0",
        "SELECT billing_month, scheduled_eur, collected_eur, collection_rate_pct FROM v_monthly_rent_summary",
        "SELECT unit_address, party_name, about, expected_by FROM v_waiting_radar WHERE status = 'waiting'",
        "SELECT contractor_name, trade, item_key, amount, currency FROM v_vendor_rates",
        "SELECT title, doc_type, status, document_date FROM v_documents_overview",
        "SELECT action_type, status, count(*) FROM v_approval_audit GROUP BY action_type, status",
        "SELECT channel, status, count(*) FROM v_send_stats GROUP BY channel, status",
        "SELECT scope, kind, text FROM memory_items WHERE status = 'active'",
    ],
)
def test_new_financial_and_operational_relations_allowed(sql: str):
    wrapped = validate_and_wrap_sql(sql, max_limit=50)
    assert "LIMIT 50" in wrapped


@pytest.mark.parametrize(
    "forbidden_table",
    [
        "allowed_users",
        "companies",
        "owner_personas",
        "owner_outbox",
        "sends",
        "channel_identities",
        "approvals",
        "model_calls",
        "translations",
        "brixx_documents",
        "agent_conversations",
        "agent_turns",
    ],
)
def test_reject_newly_blocked_sensitive_tables(forbidden_table: str):
    with pytest.raises(SQLSecurityError, match="Access to sensitive table"):
        validate_and_wrap_sql(f"SELECT * FROM {forbidden_table}")  # noqa: S608


def test_executor_enforces_postgres_read_only_and_timeout():
    mock_engine = MagicMock()
    mock_engine.dialect.name = "postgresql"
    mock_session = MagicMock()
    mock_session.__enter__.return_value = mock_session
    mock_cursor = MagicMock()
    mock_cursor.keys.return_value = ["net_profit_eur"]
    mock_cursor.fetchall.return_value = [(1850.50,)]
    mock_session.execute.return_value = mock_cursor

    company_id = uuid4()
    with patch("app.tools.query_agent.executor.Session", return_value=mock_session):
        res = execute_readonly_query(
            mock_engine,
            company_id,
            "SELECT net_profit_eur FROM v_unit_profitability LIMIT 50",
        )

    assert res.ok is True
    executed_sqls = [str(c.args[0]) for c in mock_session.execute.call_args_list]
    assert "set_config('app.company_id'" in executed_sqls[0]
    assert "SET LOCAL TRANSACTION READ ONLY" in executed_sqls[1]
    assert "SET LOCAL statement_timeout = '4000'" in executed_sqls[2]
    assert "v_unit_profitability" in executed_sqls[3]


def test_sanitize_rows_formats_financial_labels_and_hides_ids():
    rows = [
        {
            "rent_payment_id": "01a1ca59-c6cb-7e02-bd67-f86ff1b72267",
            "unit_id": "01a1ca59-0000-0000-0000-000000000001",
            "unit_address": "Dorpsstraat 54 E",
            "collected_rent_eur": 2400.00,
            "maintenance_cost_eur": 350.00,
            "net_profit_eur": 2050.00,
        }
    ]
    cols, display_rows = sanitize_rows_for_display(rows)
    assert cols == ["Property", "Collected Rent (€)", "Maintenance Cost (€)", "Net Profit (€)"]
    assert display_rows == [
        {
            "Property": "Dorpsstraat 54 E",
            "Collected Rent (€)": "2400",
            "Maintenance Cost (€)": "350",
            "Net Profit (€)": "2050",
        }
    ]


def test_query_agent_prompts_are_in_sync():
    from app.contracts import PromptRef
    from app.llm.prompts import load_prompt
    from app.tools.query_agent.prompt import QUERY_AGENT_SYSTEM_PROMPT

    published = load_prompt(PromptRef(name="query_agent", version="v4")).text
    assert QUERY_AGENT_SYSTEM_PROMPT.strip() == published.strip()


def test_sanitize_rows_labels_brixx_tickets_and_lease_facts():
    rows = [
        {
            "source": "brixx",
            "ticket_ref": "BRIXX-41",
            "unit_address": "Teststraat 5A",
            "title": "Lekkage",
            "is_open": True,
            "monthly_rent_eur": 1500.0,
            "living_area_sqm": 62,
        }
    ]
    cols, _ = sanitize_rows_for_display(rows)
    assert cols == ["Source", "Ticket", "Property", "Title", "Open", "Monthly Rent (€)", "Area (m²)"]


def test_gemini_is_never_asked_for_a_retired_model():
    """gemini-2.0-flash answers 404 now; trying it only costs a round trip before the configured LLM takes over."""
    from pydantic import SecretStr

    from app.tools.query_agent.agent import _call_gemini

    settings = SETTINGS.model_copy(update={"gemini_api_key": SecretStr("k")})
    with patch("app.tools.query_agent.agent.httpx.post", return_value=MagicMock(status_code=503, text="")) as post:
        assert _call_gemini("q", settings) is None
    asked = [call.args[0] for call in post.call_args_list]
    assert asked
    assert not any("gemini-2.0" in url for url in asked)


def test_gemini_prefers_configured_google_model_before_fallback():
    from pydantic import SecretStr

    from app.tools.query_agent.agent import _call_gemini

    settings = SETTINGS.model_copy(
        update={"gemini_api_key": SecretStr("k"), "llm_model": "google-gla:gemini-2.5-flash"}
    )
    with patch("app.tools.query_agent.agent.httpx.post", return_value=MagicMock(status_code=503, text="")) as post:
        assert _call_gemini("q", settings) is None
    assert "gemini-2.5-flash" in post.call_args_list[0].args[0]
