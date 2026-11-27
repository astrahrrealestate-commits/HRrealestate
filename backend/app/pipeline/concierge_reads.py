"""Read intents of the concierge plan: answers and listings from existing company-scoped reads. No state changes."""

import re
from dataclasses import asdict
from datetime import UTC, date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Channel, PlanStep
from app.core import rent_data
from app.db.enums import TaskStatus, WaitStatus
from app.db.models import MessageRow, TaskRow, WaitRow
from app.db.models.ingestion import not_chat_only
from app.llm.agents.briefing import fallback_briefing, render_text
from app.llm.agents.owner_qa import FALLBACK_ANSWER
from app.pipeline import briefing, case_repo, chasing, owner_commands, read_approvals, read_work, work_repo
from app.pipeline.concierge_base import NEED_DETAIL, Ctx, StepResult, failed, log
from app.pipeline.concierge_reply import screen_reply
from app.pipeline.concierge_sanitize import normalise_query, safe_question
from app.pipeline.read_repo import encode_thread_key
from app.pipeline.turn_timings import ANSWER

MAX_LISTED = 10
MAX_HITS = 10
SNIPPET = 120
MAX_REVIEW = 20
MAX_SUMMARY = 400

# Fixed answers of the concierge/v8 guard intents, defined once here (the API's rent guard re-exports the rent one).
NO_RENT_DATA_ANSWER = (
    "Rent invoices are generated in BRIXX, but bank payment reconciliation is handled externally in Exact Online "
    "(not connected yet). Because bank settlements are not mirrored in BRIXX, I cannot confirm which tenants have paid "
    "or who is actually overdue."
)
CALENDAR_POINTER = "I can't book or look up visits from here yet. Open the Calendar page to book, move or check one."


def answer(ctx: Ctx, step: PlanStep) -> StepResult:
    """The plan's own screened `reply` when it has one (one model call for the turn; the plan was in scope, or the
    executor would not run). Next, when the plan asked for research (concierge/v7), the read-only research loop; its
    text is screened like a reply. Otherwise the owner's own question goes to `owner_qa` (scope guard, refusal and
    budget fallbacks included) with the turn's stored page facts and snapshot. At most once per plan: a later
    `answer` step reuses the first result."""
    if "answer" not in ctx.memo:
        reply = screen_reply(ctx.reply)
        if reply is not None:
            log.info("concierge.direct_reply", company_id=str(ctx.company_id))
            ctx.memo["answer"] = StepResult(step.intent, True, reply, None, None)
        else:
            with ctx.timer.measure(ANSWER):
                ctx.memo["answer"] = _researched_answer(ctx, step) or _owner_qa_answer(ctx, step)
    return ctx.memo["answer"]


def _researched_answer(ctx: Ctx, step: PlanStep) -> StepResult | None:
    if not ctx.needs_research or ctx.research is None:
        return None
    found = ctx.research(ctx.company_id, ctx.question, ctx.page, ctx.history)
    text = screen_reply(found.answer) if found is not None else None
    if found is None or text is None:
        return None
    log.info("concierge.researched_reply", company_id=str(ctx.company_id), steps=len(found.steps))
    data: dict[str, Any] = {"steps": list(found.steps)} if found.steps else {}
    if found.sources:
        data["sources"] = [s.model_dump() for s in found.sources]
    return StepResult(step.intent, True, text, data or None, None)


def _owner_qa_answer(ctx: Ctx, step: PlanStep) -> StepResult:
    cmd = owner_commands.Command(owner_commands.CommandKind.question, text=ctx.question)
    text = owner_commands.run_command(ctx.engine, ctx.settings, ctx.company_id, cmd, now=ctx.now, page=ctx.page)
    ok = text not in (FALLBACK_ANSWER, owner_commands.LIMIT_ANSWER)
    return StepResult(step.intent, ok, text, None, None)


def list_tasks(ctx: Ctx, step: PlanStep) -> StepResult:
    with Session(ctx.engine) as session:
        tz = ZoneInfo(read_work.get_company(session, ctx.company_id).timezone)
        tasks = work_repo.open_tasks(session, ctx.company_id, now=ctx.now)
        rows = [
            {
                "id": str(t.id),
                "ref": work_repo.short_ref(t.id),
                "title": t.title,
                "priority": t.priority.value,
                "due_at": t.due_at.isoformat() if t.due_at else None,
                "case_id": str(t.case_id) if t.case_id else None,
            }
            for t in tasks
        ]
    lines = [
        f"{i}. [{t.priority.value}] {t.title}"
        f"{f' (due {t.due_at.astimezone(tz):%a %d %b %H:%M})' if t.due_at else ''} #{work_repo.short_ref(t.id)}"
        for i, t in enumerate(tasks[:MAX_LISTED], 1)
    ]
    summary = "Open tasks:\n" + "\n".join(lines) if lines else "No open tasks."
    return StepResult(step.intent, True, summary, {"tasks": rows}, "tasks")


def list_waiting(ctx: Ctx, step: PlanStep) -> StepResult:
    with Session(ctx.engine) as session:
        tz = read_work.get_company(session, ctx.company_id).timezone
        waits = list(
            session.scalars(
                select(WaitRow)
                .where(
                    WaitRow.company_id == ctx.company_id,
                    WaitRow.status.in_([WaitStatus.waiting, WaitStatus.escalated]),
                )
                .order_by(WaitRow.expected_by, WaitRow.id)
                .limit(read_work.MAX_WAITS)
            ).all()
        )
        promises = list(
            session.scalars(
                select(TaskRow)
                .where(
                    TaskRow.company_id == ctx.company_id,
                    TaskRow.assignee == "owner",
                    TaskRow.source.in_(["promise", "reminder"]),
                    TaskRow.status.in_([TaskStatus.open, TaskStatus.snoozed]),
                )
                .order_by(TaskRow.due_at.nulls_last(), TaskRow.id)
                .limit(MAX_LISTED)
            ).all()
        )
        rows = [
            {
                "id": str(w.id),
                "case_id": str(w.case_id),
                "about": w.about,
                "status": w.status.value,
                "expected_by": w.expected_by.isoformat(),
                "overdue_days": chasing.overdue_days_from(
                    w.expected_by if w.expected_by.tzinfo else w.expected_by.replace(tzinfo=UTC), ctx.now, tz
                ),
                "chase_count": w.chase_count,
            }
            for w in waits
        ]
        promise_rows = [
            {
                "id": str(p.id),
                "case_id": str(p.case_id) if p.case_id else None,
                "title": p.title,
                "due_at": p.due_at.isoformat() if p.due_at else None,
                "overdue_days": (
                    chasing.overdue_days_from(
                        p.due_at if p.due_at.tzinfo else p.due_at.replace(tzinfo=UTC), ctx.now, tz
                    )
                    if p.due_at
                    else 0
                ),
            }
            for p in promises
        ]

    wait_lines: list[str] = []
    for i, (w, r) in enumerate(zip(waits[:MAX_LISTED], rows[:MAX_LISTED], strict=True), 1):
        tags: list[str] = []
        od = int(str(r["overdue_days"]))
        if w.status is WaitStatus.escalated:
            tags.append("ESCALATED")
        if od > 0:
            tags.append(f"{od}d overdue")
        tags.append(f"{w.chase_count} reminders sent")
        wait_lines.append(f"{i}. {w.about} ({', '.join(tags)})")

    promise_lines: list[str] = []
    for i, (p, pr) in enumerate(zip(promises[:MAX_LISTED], promise_rows[:MAX_LISTED], strict=True), 1):
        od = int(str(pr["overdue_days"]))
        tag = f"{od}d overdue" if od > 0 else "open promise"
        promise_lines.append(f"{i}. {p.title} ({tag})")

    parts: list[str] = []
    if wait_lines:
        parts.append("Owed by Others (waiting):\n" + "\n".join(wait_lines))
    if promise_lines:
        parts.append("Owed by Us (promises):\n" + "\n".join(promise_lines))
    summary = "\n\n".join(parts) if parts else "Not waiting on anyone."
    return StepResult(step.intent, True, summary, {"waits": rows, "promises": promise_rows}, "waiting")


def case_status(ctx: Ctx, step: PlanStep) -> StepResult:
    """`data["summary"]` is the model-written case summary: untrusted, tenant-derived text. It is the owner's own
    company data (also served by GET /cases/{id}), so it is returned, capped at 400 chars; the SPA must render it
    as plain text."""
    if step.case_id is None:  # the executor validates first; kept for type narrowing
        return failed(step, NEED_DETAIL)
    with Session(ctx.engine) as session:
        case = case_repo.get_case(session, ctx.company_id, step.case_id)
        label = owner_commands.case_label(session, case)
        data = {
            "case_id": str(case.id),
            "state": case.state.value,
            "urgency": case.urgency.value,
            "category": case.category.value,
            "summary": case.summary[:MAX_SUMMARY],
        }
    summary = f"{label}: {case.state.value.replace('_', ' ')}, urgency {case.urgency.value}."
    return StepResult(step.intent, True, summary, data, "cases")


_DATE_TOKEN_RE = re.compile(r"\b(from|to):(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)
_CHAN_TOKEN_RE = re.compile(r"\bchannel:(gmail|whatsapp)\b", re.IGNORECASE)


def _extract_inbox_search_filters(raw_query: str) -> tuple[str, date | None, date | None, str | None]:
    date_from: date | None = None
    date_to: date | None = None
    channel: str | None = None

    def _collect_date(m: re.Match[str]) -> str:
        nonlocal date_from, date_to
        try:
            parsed = date.fromisoformat(m.group(2))
        except ValueError:
            return m.group(0)
        if m.group(1).lower() == "from":
            date_from = parsed
        else:
            date_to = parsed
        return ""

    cleaned = _DATE_TOKEN_RE.sub(_collect_date, raw_query)

    def _collect_chan(m: re.Match[str]) -> str:
        nonlocal channel
        channel = m.group(1).lower()
        return ""

    cleaned = _CHAN_TOKEN_RE.sub(_collect_chan, cleaned)
    return normalise_query(cleaned), date_from, date_to, channel


def search_inbox(ctx: Ctx, step: PlanStep) -> StepResult:
    """Hybrid RAG and substring match over message text and conversation chunks, with optional date/channel filters."""
    query, date_from, date_to, channel = _extract_inbox_search_filters(step.text or "")
    if not query and date_from is None and date_to is None and channel is None:
        return failed(step, NEED_DETAIL)

    from app.llm.embeddings import build_embedder
    from app.tools.message_rag import search_messages

    embedder = build_embedder(ctx.settings) if query else None
    with Session(ctx.engine) as session:
        chunk_hits = search_messages(
            session,
            ctx.company_id,
            query=query,
            embedder=embedder,
            case_id=step.case_id,
            channel=channel,
            date_from=date_from,
            date_to=date_to,
            limit=MAX_HITS,
        )
        if chunk_hits:
            rows = [
                {
                    "message_id": str(h.first_message_id),
                    "chunk_id": str(h.chunk_id),
                    "thread_key": encode_thread_key(Channel(h.channel), h.thread_ref),
                    "sent_at": h.last_sent_at.isoformat(),
                    "sender": h.person_name or "Contact",
                    "property": h.unit_address or "",
                    "snippet": " ".join(h.text.split())[:240],
                    "score": round(h.score, 4),
                }
                for h in chunk_hits
            ]
            summary = f"Found {len(rows)} matching conversation(s)."
            return StepResult(step.intent, True, summary, {"messages": rows, "chunks": rows}, "inbox")

        msg_stmt = select(
            MessageRow.id,
            MessageRow.channel,
            MessageRow.thread_ref,
            MessageRow.provider_msg_id,
            MessageRow.sent_at,
            MessageRow.text,
        ).where(MessageRow.company_id == ctx.company_id, not_chat_only())
        if query:
            msg_stmt = msg_stmt.where(MessageRow.text.icontains(query, autoescape=True))
        if channel is not None:
            msg_stmt = msg_stmt.where(MessageRow.channel == Channel(channel))
        if date_from is not None:
            msg_stmt = msg_stmt.where(MessageRow.sent_at >= date_from)
        if date_to is not None:
            msg_stmt = msg_stmt.where(MessageRow.sent_at < date_to + timedelta(days=1))
        hits = session.execute(msg_stmt.order_by(MessageRow.sent_at.desc(), MessageRow.id.desc()).limit(MAX_HITS)).all()
        rows = [
            {
                "message_id": str(mid),
                "thread_key": encode_thread_key(channel, thread_ref or provider_msg_id),
                "sent_at": sent_at.isoformat(),
                "snippet": " ".join(text.split())[:SNIPPET],
            }
            for mid, channel, thread_ref, provider_msg_id, sent_at, text in hits
        ]
        summary = f"Found {len(rows)} matching message(s)." if rows else "No messages match that search."
        return StepResult(step.intent, True, summary, {"messages": rows}, "inbox")


def briefing_now(ctx: Ctx, step: PlanStep) -> StepResult:
    """Read-only: the briefing facts with the template write-up. No model call, no timer, no send."""
    facts = briefing.collect(ctx.engine, ctx.company_id, "daily", ctx.now)
    text = render_text(facts, fallback_briefing(facts))
    return StepResult(step.intent, True, text, {"briefing": asdict(facts)}, None)


def file_document(ctx: Ctx, step: PlanStep) -> StepResult:
    """Lists documents waiting for the owner's filing choice; filing itself stays an explicit owner action."""
    with Session(ctx.engine) as session:
        docs = read_approvals.review_documents(session, ctx.company_id, None, MAX_REVIEW)
    rows = [
        {
            "attachment_id": str(d.attachment_id),
            "filename": d.filename,
            "case_id": str(d.case_id) if d.case_id else None,
            "suggested_type": d.suggested_type,
        }
        for d in docs
    ]
    if not rows:
        return StepResult(step.intent, True, "No documents are waiting for a filing choice.", {"documents": []}, None)
    summary = f"{len(rows)} document(s) wait for your filing choice. Choose the type for each in the dashboard."
    return StepResult(step.intent, True, summary, {"documents": rows}, None)


def open_view(ctx: Ctx, step: PlanStep) -> StepResult:
    if step.view is None:
        return failed(step, NEED_DETAIL)
    data = {"case_id": str(step.case_id)} if step.case_id else None
    return StepResult(step.intent, True, f"Opening {step.view}.", data, step.view)


def clarify(ctx: Ctx, step: PlanStep) -> StepResult:
    return StepResult(step.intent, True, safe_question(step.text or ""), None, None)


def calendar(ctx: Ctx, step: PlanStep) -> StepResult:
    """The calendar helpers live in the API layer, which the pipeline may not import: a fixed pointer to the Calendar
    page. The step's text is model output and is never echoed."""
    return StepResult(step.intent, True, CALENDAR_POINTER, None, None)


def rent_status(ctx: Ctx, step: PlanStep) -> StepResult:
    """Who owes or paid rent. While no rent data is mirrored (`app.core.rent_data`) the honest answer, never a figure
    counted from tables that hold none; once it is, the query agent answers the owner's question."""
    if not rent_data.RENT_DATA_AVAILABLE:
        return StepResult(step.intent, True, NO_RENT_DATA_ANSWER, None, None)
    return query_data(ctx, step)


def query_data(ctx: Ctx, step: PlanStep) -> StepResult:
    """Executes a natural language analytical/reporting query using the Custom Query Agent."""
    query = (step.text or ctx.question or "").strip()
    if not query:
        return failed(step, NEED_DETAIL)

    from app.tools.query_agent.agent import run_query_agent

    response = run_query_agent(
        engine=ctx.engine,
        settings=ctx.settings,
        company_id=ctx.company_id,
        question=query,
    )

    data = {
        "sql": response.sql,
        "rows": response.rows,
        "columns": response.columns,
        "display_rows": response.display_rows,
        "row_count": response.row_count,
        "duration_ms": response.duration_ms,
        "question": query,
    }
    return StepResult(step.intent, response.ok, response.answer, data, None)
