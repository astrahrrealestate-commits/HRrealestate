"""Custom Query Agent: Translates natural language into safe, validated SQL and executes it."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from app.core.logging import get_logger
from app.core.settings import Settings
from app.tools.query_agent.executor import QueryExecutionResult, execute_readonly_query
from app.tools.query_agent.prompt import QUERY_AGENT_SYSTEM_PROMPT
from app.tools.query_agent.validator import SQLSecurityError, validate_and_wrap_sql

log = get_logger(__name__)


class SQLQueryProposal(BaseModel):
    sql: str = Field(description="Single PostgreSQL SELECT query over curated views or base tables")
    rationale: str = Field(description="Explanation of what the query calculates")


@dataclass(frozen=True)
class QueryAgentResponse:
    ok: bool
    answer: str
    sql: str | None
    rows: list[dict[str, Any]]
    row_count: int
    duration_ms: float
    error: str | None = None


def _call_groq_or_gemini(
    prompt: str,
    settings: Settings,
    system_instruction: str = QUERY_AGENT_SYSTEM_PROMPT,
) -> str | None:
    """Calls Groq API with structured JSON output instructions."""
    api_key = settings.groq_api_key.get_secret_value() if settings.groq_api_key else None
    if not api_key:
        return None

    for model in ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]:
        try:
            resp = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.0,
                    "max_tokens": 500,
                },
                timeout=12.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                return str(data["choices"][0]["message"]["content"])
            log.warning("query_agent.groq_status_not_200", model=model, status=resp.status_code, body=resp.text[:200])
        except Exception as exc:
            log.warning("query_agent.llm_call_failed", model=model, error=str(exc))
    return None


def propose_sql(
    question: str,
    settings: Settings,
    history: Sequence[str] | None = None,
    feedback_error: str | None = None,
) -> SQLQueryProposal | None:
    """Generates an SQL proposal from natural language, with optional error-feedback correction."""
    user_prompt = f"User Question: {question}"
    if history:
        recent_turns = "\n".join(history[-4:])
        user_prompt = f"Recent Chat Context:\n{recent_turns}\n\n{user_prompt}"

    if feedback_error:
        user_prompt += (
            f"\n\nCRITICAL: The previous SQL query failed with error:\n{feedback_error}\n"
            "Please fix this error and generate a corrected, valid PostgreSQL SELECT query referencing the database schema. "
            "Output your answer as a JSON object with keys 'sql' and 'rationale'."
        )
    else:
        user_prompt += "\n\nRespond with a valid JSON object with keys 'sql' and 'rationale'."

    raw_output = _call_groq_or_gemini(user_prompt, settings)
    if not raw_output:
        return None

    try:
        data = json.loads(raw_output)
        return SQLQueryProposal(
            sql=data.get("sql", "").strip().strip("`").rstrip(";"),
            rationale=data.get("rationale", ""),
        )
    except Exception as exc:
        log.warning("query_agent.parse_failed", error=str(exc), raw=raw_output)
        return None


def format_answer(question: str, rows: list[dict[str, Any]], row_count: int) -> str:
    """Formulates a factual, grounded summary directly from returned rows."""
    if row_count == 0:
        return f'I queried your portfolio records for *"{question}"*, but found 0 matching entries.'

    if row_count == 1:
        row = rows[0]
        # Check for simple aggregate counts
        if len(row) == 1:
            col_name, val = next(iter(row.items()))
            clean_label = col_name.replace("_", " ").title()
            return f"**Result:** **{val}** ({clean_label})"

    # Multiple records: format as readable bullet points
    lines = [f'Found **{row_count}** matching records for *"{question}"*:\n']
    for r in rows[:10]:
        parts = [
            f"**{k.replace('_', ' ').capitalize()}**: {v}" for k, v in r.items() if v is not None and k != "company_id"
        ]
        lines.append("• " + " | ".join(parts))

    if row_count > 10:
        lines.append(f"\n*(Showing top 10 of {row_count} total records)*")

    return "\n".join(lines)


def run_query_agent(
    engine: Engine,
    settings: Settings,
    company_id: UUID,
    question: str,
    history: Sequence[str] | None = None,
    max_retries: int = 3,
) -> QueryAgentResponse:
    """End-to-end execution of the Custom Query Agent:
    1. Proposes SQL from natural language question.
    2. Runs AST validation & limit wrapping (read-only enforcement).
    3. Retries on security or SQL execution errors with feedback loop (up to max_retries).
    4. Executes with RLS company context.
    5. Formulates factual, grounded response.
    """
    last_error: str | None = None
    last_sql: str | None = None

    for attempt in range(max_retries + 1):
        proposal = propose_sql(question, settings, history=history, feedback_error=last_error)
        if not proposal or not proposal.sql:
            last_error = "Could not generate SQL proposal"
            continue

        last_sql = proposal.sql
        try:
            wrapped_sql = validate_and_wrap_sql(proposal.sql, max_limit=50)
        except SQLSecurityError as sec_err:
            last_error = str(sec_err)
            log.warning("query_agent.security_rejected", attempt=attempt, error=last_error, sql=last_sql)
            continue

        # Execute safe query inside read-only company RLS transaction
        exec_res: QueryExecutionResult = execute_readonly_query(engine, company_id, wrapped_sql)
        if not exec_res.ok:
            last_error = exec_res.error
            log.warning("query_agent.db_execution_error", attempt=attempt, error=last_error, sql=wrapped_sql)
            continue

        # Format grounded natural language answer
        answer = format_answer(question, exec_res.rows, exec_res.row_count)
        return QueryAgentResponse(
            ok=True,
            answer=answer,
            sql=wrapped_sql,
            rows=exec_res.rows,
            row_count=exec_res.row_count,
            duration_ms=exec_res.duration_ms,
            error=None,
        )

    return QueryAgentResponse(
        ok=False,
        answer=f"Could not execute query safely: {last_error or 'Validation failed'}",
        sql=last_sql,
        rows=[],
        row_count=0,
        duration_ms=0.0,
        error=last_error,
    )
