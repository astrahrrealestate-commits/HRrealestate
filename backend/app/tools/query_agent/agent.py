"""Custom Query Agent: Translates natural language into safe, validated SQL and executes it."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import Engine, text

from app.contracts import PromptRef
from app.core.errors import AgentFailedError
from app.core.ids import case_ref
from app.core.localtime import to_local
from app.core.logging import get_logger
from app.core.settings import Settings
from app.llm.calls import AgentSpec, CallContext, run_agent
from app.llm.render import data_block
from app.tools.query_agent.executor import QueryExecutionResult, execute_readonly_query
from app.tools.query_agent.prompt import QUERY_AGENT_SYSTEM_PROMPT
from app.tools.query_agent.validator import SQLSecurityError, validate_and_wrap_sql

log = get_logger(__name__)

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_ISO_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_HIDDEN_ID_COLS = frozenset(
    {
        "company_id",
        "id",
        "lease_id",
        "unit_id",
        "person_id",
        "primary_person_id",
        "tenant_id",
        "action_id",
        "message_id",
        "document_id",
        "event_id",
        "raw_event_id",
        "import_id",
        "source_id",
        "quote_id",
        "rent_payment_id",
        "wait_id",
        "party_person_id",
        "source_action_id",
        "attachment_id",
        "model_call_id",
        "dd_review_id",
        "rate_card_id",
        "approval_id",
        "linked_ref_id",
    }
)
_TICKET_REF_COLS = frozenset({"case_id", "task_id"})
_ENUM_STYLE_COLS = frozenset(
    {
        "state",
        "status",
        "urgency",
        "category",
        "event_type",
        "priority",
        "verdict",
        "doc_type",
        "action_type",
        "choice",
    }
)

_COLUMN_LABELS: dict[str, str] = {
    "case_id": "Ticket",
    "ticket_ref": "Ticket",
    "source": "Source",
    "title": "Title",
    "closed_at": "Closed",
    "is_open": "Open",
    "monthly_rent_eur": "Monthly Rent (€)",
    "deposit_eur": "Deposit (€)",
    "living_area_sqm": "Area (m²)",
    "task_id": "Task",
    "unit_address": "Property",
    "unit_label": "Unit",
    "tenant_name": "Tenant",
    "contractor_name": "Contractor",
    "party_name": "Counterparty",
    "display_name": "Name",
    "valid_from": "Lease Start",
    "valid_to": "Lease End",
    "is_active": "Status",
    "opened_at": "Opened",
    "resolved_at": "Resolved",
    "due_at": "Due",
    "due_date": "Due Date",
    "paid_at": "Paid At",
    "decided_at": "Decided At",
    "attempted_at": "Attempted At",
    "billing_month": "Billing Month",
    "invoice_number": "Invoice Number",
    "contract_rent_eur": "Contract Rent (€)",
    "amount_paid_eur": "Paid (€)",
    "scheduled_rent_eur": "Scheduled Rent (€)",
    "collected_rent_eur": "Collected Rent (€)",
    "scheduled_eur": "Scheduled (€)",
    "collected_eur": "Collected (€)",
    "overdue_eur": "Overdue (€)",
    "overdue_rent_eur": "Overdue Rent (€)",
    "maintenance_cost_eur": "Maintenance Cost (€)",
    "net_profit_eur": "Net Profit (€)",
    "margin_pct": "Margin (%)",
    "collection_rate_pct": "Collection Rate (%)",
    "overdue_days": "Overdue Days",
    "payment_method": "Payment Method",
    "expected_by": "Expected By",
    "last_chased_at": "Last Chased",
    "chase_count": "Chase Count",
    "doc_type": "Doc Type",
    "file_name": "File Name",
    "document_date": "Document Date",
    "start_time": "Starts",
    "end_time": "Ends",
    "has_lockbox": "Lockbox",
    "event_type": "Type",
    "quote_date": "Quote Date",
    "work_date": "Work Date",
    "late_days": "Late Days",
}

_SUMMARY_SYNTHESIS_PROMPT = (
    "You are Astra, the executive estate-intelligence copilot for Harjot (property owner).\n"
    "Turn the verified query results inside <data> into a crisp, human-readable executive answer as JSON:\n"
    '{"answer": "..."}\n'
    "Rules:\n"
    "- Language Matching: Answer in the same language as the user's question (if asked in Dutch, reply in\n"
    "  natural, fluent Dutch; if in English, reply in English).\n"
    "- Be concise (1-3 short sentences, or a brief headline + up to 4 clean '- ' bullets highlighting key items).\n"
    "- A structured data table card is shown directly below your answer whenever multiple records exist, so give the\n"
    "  key takeaway (counts, urgent issues, dates, names) rather than repeating every column of every row.\n"
    "- NEVER include 36-character UUIDs, pipe separators ('|'), raw column names like 'unit_address', or ISO\n"
    "  microsecond timestamps.\n"
    "- Refer to tickets as '#<6 chars>' or by tenant and property.\n"
    "- Base every fact strictly on <data>. Never invent numbers, names, properties, or dates."
)


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
    columns: list[str] = field(default_factory=list)
    display_rows: list[dict[str, Any]] = field(default_factory=list)


def _call_gemini(
    prompt: str,
    settings: Settings,
    system_instruction: str = QUERY_AGENT_SYSTEM_PROMPT,
) -> str | None:
    """Calls Google Gemini API with structured JSON output instructions."""
    gemini_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
    if not gemini_key:
        return None
    for model in ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash"]:
        try:
            resp = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}",
                json={
                    "systemInstruction": {"parts": [{"text": system_instruction}]},
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.0,
                    },
                },
                timeout=15.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates") or []
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts") or []
                    if parts and "text" in parts[0]:
                        return str(parts[0]["text"])
            log.warning("query_agent.gemini_status_not_200", model=model, status=resp.status_code, body=resp.text[:200])
        except Exception as exc:
            log.warning("query_agent.gemini_call_failed", model=model, error=str(exc))
    return None


QUERY_AGENT = AgentSpec(
    name="query_agent",
    prompt=PromptRef(name="query_agent", version="v4"),
    output_type=SQLQueryProposal,
    finalize=lambda output, _loaded: output,
    gemini_prompted=True,
)


def _propose_with_configured_llm(
    user_prompt: str, engine: Engine, settings: Settings, company_id: UUID
) -> SQLQueryProposal | None:
    """The project's own LLM layer (configured model, versioned prompt, one `model_calls` row per call)."""
    try:
        ctx = CallContext(company_id=company_id, purpose="query_agent")
        return run_agent(engine, settings, QUERY_AGENT, user_prompt, ctx).output
    except AgentFailedError as exc:
        log.warning("query_agent.llm_failed", error=str(exc))
        return None


def propose_sql(
    question: str,
    settings: Settings,
    history: Sequence[str] | None = None,
    feedback_error: str | None = None,
    *,
    engine: Engine | None = None,
    company_id: UUID | None = None,
) -> SQLQueryProposal | None:
    """Generates an SQL proposal from natural language, with optional error-feedback correction.

    Groq answers when a key is configured; otherwise (or when it fails) the configured LLM does."""
    user_prompt = f"User Question: {question}"
    if history:
        recent_turns = "\n".join(history[-4:])
        user_prompt = f"Recent Chat Context:\n{recent_turns}\n\n{user_prompt}"

    if feedback_error:
        user_prompt += (
            f"\n\nCRITICAL: The previous SQL query failed with error:\n{feedback_error}\n"
            "Please fix this error and generate a corrected, valid PostgreSQL SELECT query referencing the database "
            "schema. "
            "Output your answer as a JSON object with keys 'sql' and 'rationale'."
        )
    else:
        user_prompt += "\n\nRespond with a valid JSON object with keys 'sql' and 'rationale'."

    raw_output = _call_gemini(user_prompt, settings)
    if not raw_output:
        if engine is None or company_id is None or settings.llm_model == "fake":
            return None
        proposal = _propose_with_configured_llm(user_prompt, engine, settings, company_id)
        if proposal is None:
            return None
        return SQLQueryProposal(sql=proposal.sql.strip().strip("`").rstrip(";"), rationale=proposal.rationale)

    try:
        data = json.loads(raw_output)
        return SQLQueryProposal(
            sql=data.get("sql", "").strip().strip("`").rstrip(";"),
            rationale=data.get("rationale", ""),
        )
    except Exception as exc:
        log.warning("query_agent.parse_failed", error=str(exc), raw=raw_output)
        return None


def _human_col_label(col: str) -> str:
    if col in _COLUMN_LABELS:
        return _COLUMN_LABELS[col]
    return col.replace("_", " ").strip().title()


def _amsterdam_stamp(dt: datetime) -> str:
    return to_local(dt).strftime("%d %b %Y, %H:%M")


def _format_cell_value(col: str, val: Any, *, clip_summary: bool = True) -> str:
    if val is None:
        return "—"
    if isinstance(val, bool):
        if col == "is_active":
            return "Active" if val else "Ended"
        return "Yes" if val else "No"
    if isinstance(val, datetime):
        return _amsterdam_stamp(val)
    if isinstance(val, date):
        return val.strftime("%d %b %Y")
    if isinstance(val, Decimal):
        if val == val.to_integral_value():
            return str(int(val))
        return f"{float(val):.2f}".rstrip("0").rstrip(".")
    if isinstance(val, float):
        if val.is_integer():
            return str(int(val))
        return f"{val:.2f}".rstrip("0").rstrip(".")
    if isinstance(val, int):
        return str(val)
    if isinstance(val, UUID):
        return f"#{case_ref(val)}"

    s = str(val).strip()
    if not s:
        return "—"
    if _UUID_RE.match(s):
        return f"#{case_ref(s)}"
    if _ISO_DT_RE.match(s):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return _amsterdam_stamp(dt)
        except ValueError:
            pass
    if _ISO_DATE_RE.match(s):
        try:
            return date.fromisoformat(s).strftime("%d %b %Y")
        except ValueError:
            pass
    if col in _ENUM_STYLE_COLS:
        pretty = s.replace("_", " ").strip()
        if col == "priority" and len(pretty) <= 3:
            return pretty.upper()
        return pretty.capitalize()

    clean_s = " ".join(s.split())
    if clip_summary and col == "summary" and len(clean_s) > 140:
        return clean_s[:137].rstrip() + "..."
    return clean_s


def sanitize_rows_for_display(rows: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    """Strip internal IDs and redundant columns, format dates/enums cleanly, and map to human labels."""
    if not rows:
        return [], []

    raw_cols = list(dict.fromkeys(k for r in rows for k in r))
    kept_cols = [c for c in raw_cols if c not in _HIDDEN_ID_COLS]
    if "unit_label" in kept_cols and "unit_address" in kept_cols:
        all_redundant = all(
            not r.get("unit_label")
            or str(r.get("unit_label")).strip().lower() in str(r.get("unit_address") or "").lower()
            for r in rows
        )
        if all_redundant:
            kept_cols = [c for c in kept_cols if c != "unit_label"]
    if not kept_cols:
        kept_cols = raw_cols[:]

    col_pairs: list[tuple[str, str]] = []
    used_labels: set[str] = set()
    for raw_col in kept_cols:
        lbl = _human_col_label(raw_col)
        if lbl in used_labels:
            lbl = raw_col.replace("_", " ").strip().title()
        used_labels.add(lbl)
        col_pairs.append((raw_col, lbl))

    seen: set[tuple[str, ...]] = set()
    display_rows: list[dict[str, Any]] = []
    for r in rows:
        formatted = {lbl: _format_cell_value(raw_col, r.get(raw_col)) for raw_col, lbl in col_pairs}
        sig = tuple(formatted.values())
        if sig in seen:
            continue
        seen.add(sig)
        display_rows.append(formatted)

    return [lbl for _, lbl in col_pairs], display_rows


def synthesize_query_answer(
    question: str,
    display_rows: list[dict[str, Any]],
    row_count: int,
    settings: Settings,
) -> str | None:
    """Turn sanitized query rows into an executive prose/bullet answer via Gemini or Groq.

    Returns None to use the fallback.
    """
    if (
        settings.env == "test"
        or settings.llm_model == "fake"
        or not settings.gemini_api_key
        or row_count == 0
        or not display_rows
    ):
        return None
    if row_count == 1 and len(display_rows[0]) <= 1:
        return None

    payload = {
        "question": question,
        "total_matching_rows": row_count,
        "rows_shown": display_rows[:15],
    }
    prompt = (
        f"Owner Question: {question}\n\n"
        f"Verified Portfolio Query Results:\n{data_block('data', json.dumps(payload, ensure_ascii=False))}\n\n"
        'Respond ONLY with JSON: {"answer": "..."}'
    )
    raw = _call_gemini(prompt, settings, system_instruction=_SUMMARY_SYNTHESIS_PROMPT)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        answer = str(parsed.get("answer") or "").strip()
        return answer or None
    except Exception as exc:
        log.warning("query_agent.synthesis_parse_failed", error=type(exc).__name__)
        return None


def _synthesize_occupancy_breakdown(
    engine: Engine | None,
    company_id: UUID | None,
    question: str,
    col_name: str,
    val: Any,
) -> str | None:
    """Provides a clear, contextual breakdown for occupancy queries (avoiding confusing bare isolated numbers)."""
    if engine is None or company_id is None:
        return None

    q_low = question.lower()
    col_low = col_name.lower()

    is_tenant_q = (
        bool(re.search(r"\b(tenant|tenants|tenat|tenats|tenaant|tenaants|huurder|huurders)\b", q_low))
        or "tenant" in col_low
    )
    is_vacant_q = bool(re.search(r"\b(vacant|vacancy|leegstand|leegstaand)\b", q_low)) or "vacan" in col_low
    is_occupied_q = bool(re.search(r"\b(occupied|bezet|verhuurd)\b", q_low)) or "occup" in col_low
    is_prop_q = (
        bool(re.search(r"\b(property|properties|unit|units|portfolio|pand|panden)\b", q_low))
        or "propert" in col_low
        or "unit" in col_low
    )

    if not (is_tenant_q or is_vacant_q or is_occupied_q or is_prop_q):
        return None

    try:
        with engine.connect() as conn:
            conn.execute(text(f"SET LOCAL app.current_company_id = '{company_id}';"))
            row = (
                conn.execute(
                    text("""
                    SELECT
                        (SELECT count(*) FROM units WHERE valid_to IS NULL) AS total_units,
                        (SELECT count(DISTINCT unit_id) FROM leases
                         WHERE (valid_to IS NULL OR valid_to > CURRENT_DATE)) AS occupied_units,
                        (SELECT count(DISTINCT lp.person_id) FROM lease_parties lp
                         JOIN leases l ON lp.lease_id = l.id
                         WHERE (l.valid_to IS NULL OR l.valid_to > CURRENT_DATE)) AS active_tenants;
                """)
                )
                .mappings()
                .first()
            )
            if not row:
                return None

            total = int(row["total_units"] or 0)
            occupied = int(row["occupied_units"] or 0)
            vacant = max(0, total - occupied)
            tenants = int(row["active_tenants"] or 0)

            if is_vacant_q:
                return (
                    f"You have **{vacant} vacant properties** out of **{total} total properties**. "
                    f"The remaining **{occupied} occupied properties** house **{tenants} active tenants** "
                    "(due to joint co-tenants)."
                )
            if is_tenant_q:
                return (
                    f"You have **{tenants} active tenants** residing across **{occupied} occupied properties** "
                    f"(several leases have co-tenants/partners). **{vacant} properties** are currently vacant, "
                    f"for a total of **{total} properties**."
                )
            if is_occupied_q:
                return (
                    f"You have **{occupied} occupied properties** out of **{total} total properties**, "
                    f"housing **{tenants} active tenants**. The remaining **{vacant} properties** are currently vacant."
                )
            if is_prop_q:
                return (
                    f"You have **{total} total properties** in your portfolio "
                    f"(**{occupied} currently occupied** by {tenants} active tenants, and **{vacant} vacant**)."
                )
    except Exception as exc:
        log.warning("query_agent.occupancy_breakdown_failed", error=str(exc))
        return None

    return None


def format_answer(
    question: str,
    rows: list[dict[str, Any]],
    row_count: int,
    *,
    engine: Engine | None = None,
    company_id: UUID | None = None,
) -> str:
    """Formulates a factual, executive summary directly from sanitized rows."""
    if row_count == 0 or not rows:
        return f'I queried your portfolio records for *"{question}"*, but found 0 matching entries.'

    if row_count == 1 and len(rows[0]) == 1:
        col_name, val = next(iter(rows[0].items()))
        if engine is not None and company_id is not None:
            breakdown = _synthesize_occupancy_breakdown(engine, company_id, question, col_name, val)
            if breakdown:
                return breakdown
        clean_label = _human_col_label(col_name)
        formatted_val = _format_cell_value(col_name, val, clip_summary=False)
        return f"**Result:** **{formatted_val}** ({clean_label})"

    _cols, display_rows = sanitize_rows_for_display(rows)
    if len(display_rows) == 1:
        lines = ["Found **1** matching record:\n"]
        for k, v in display_rows[0].items():
            if v and v != "—":
                lines.append(f"- **{k}:** {v}")
        return "\n".join(lines) if len(lines) > 1 else "Found **1** matching record."

    lines = [f"Found **{row_count}** matching records:\n"]
    lead_keys = {"Ticket", "Task", "Tenant", "Contractor", "Name", "Title", "Property", "Unit"}
    for dr in display_rows[:5]:
        lead_parts: list[str] = []
        meta_parts: list[str] = []

        ticket_ref = dr.get("Ticket") or dr.get("Task")
        primary = dr.get("Tenant") or dr.get("Contractor") or dr.get("Name") or dr.get("Title")
        prop = dr.get("Property") or dr.get("Unit")

        if ticket_ref and ticket_ref != "—":
            lead_parts.append(f"**{ticket_ref}**")
        if primary and primary != "—":
            lead_parts.append(f"**{primary}**" if not lead_parts else primary)
        if prop and prop != "—":
            lead_parts.append(f"({prop})" if lead_parts else f"**{prop}**")

        for k, v in dr.items():
            if k in lead_keys or k in ("Lease Start", "Lease End") or not v or v == "—":
                continue
            if k == "Summary":
                meta_parts.append(str(v))
            else:
                meta_parts.append(f"{k}: {v}")

        l_start = dr.get("Lease Start")
        l_end = dr.get("Lease End")
        has_start = bool(l_start and l_start != "—")
        has_end = bool(l_end and l_end != "—")
        if has_start and has_end:
            meta_parts.append(f"Lease {l_start} to {l_end}")
        elif has_start:
            meta_parts.append(f"From {l_start}")
        elif has_end:
            meta_parts.append(f"Until {l_end}")

        if lead_parts:
            bullet = "- " + " ".join(lead_parts)
            if meta_parts:
                bullet += " — " + ", ".join(meta_parts)
        else:
            non_empty = [f"**{k}:** {v}" for k, v in dr.items() if v and v != "—"]
            bullet = "- " + ", ".join(non_empty) if non_empty else "- Record"
        lines.append(bullet)

    if row_count > 5:
        lines.append(f"\nShowing top 5 highlights above; all {row_count} records are in the table below.")

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
    5. Sanitizes rows and formulates a crisp executive response.
    """
    last_error: str | None = None
    last_sql: str | None = None

    for attempt in range(max_retries + 1):
        proposal = propose_sql(
            question, settings, history=history, feedback_error=last_error, engine=engine, company_id=company_id
        )
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

        cols, display_rows = sanitize_rows_for_display(exec_res.rows)
        answer = synthesize_query_answer(question, display_rows, exec_res.row_count, settings) or format_answer(
            question, exec_res.rows, exec_res.row_count, engine=engine, company_id=company_id
        )
        return QueryAgentResponse(
            ok=True,
            answer=answer,
            sql=wrapped_sql,
            rows=exec_res.rows,
            row_count=exec_res.row_count,
            duration_ms=exec_res.duration_ms,
            error=None,
            columns=cols,
            display_rows=display_rows,
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
