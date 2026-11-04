"""Unit and red-team security tests for the Custom Query Agent."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.settings import Settings
from app.tools.query_agent.agent import SQLQueryProposal, format_answer, run_query_agent
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
