"""Read intents of the concierge plan: answers and listings from existing company-scoped reads. No state changes."""

from dataclasses import asdict
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import PlanStep
from app.db.models import MessageRow
from app.llm.agents.briefing import fallback_briefing, render_text
from app.llm.agents.owner_qa import FALLBACK_ANSWER
from app.pipeline import briefing, case_repo, owner_commands, read_approvals, read_work, work_repo
from app.pipeline.concierge_base import NEED_DETAIL, Ctx, StepResult, failed, log
from app.pipeline.concierge_reply import screen_reply
from app.pipeline.concierge_sanitize import normalise_query, safe_question
from app.pipeline.read_repo import encode_thread_key

MAX_LISTED = 10
MAX_HITS = 10
SNIPPET = 120
MAX_REVIEW = 20
MAX_SUMMARY = 400


def answer(ctx: Ctx, step: PlanStep) -> StepResult:
    """The plan's own screened `reply` when it has one (one model call for the turn; the plan was in scope, or the
    executor would not run). Otherwise the owner's own question goes to `owner_qa` (scope guard, refusal and budget
    fallbacks included) with the turn's stored page facts and snapshot. At most once per plan: a later `answer` step
    reuses the first result."""
    if "answer" not in ctx.memo:
        reply = screen_reply(ctx.reply)
        if reply is not None:
            log.info("concierge.direct_reply", company_id=str(ctx.company_id))
            ctx.memo["answer"] = StepResult(step.intent, True, reply, None, None)
        else:
            ctx.memo["answer"] = _owner_qa_answer(ctx, step)
    return ctx.memo["answer"]


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
        waits = read_work.open_waits(session, ctx.company_id)
        rows = [
            {
                "id": str(w.id),
                "case_id": str(w.case_id),
                "about": w.about,
                "expected_by": w.expected_by.isoformat(),
                "chase_count": w.chase_count,
            }
            for w in waits
        ]
    lines = [f"{i}. {w.about}, {w.chase_count} reminders sent" for i, w in enumerate(waits[:MAX_LISTED], 1)]
    summary = "Waiting on:\n" + "\n".join(lines) if lines else "Not waiting on anyone."
    return StepResult(step.intent, True, summary, {"waits": rows}, "waiting")


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


def search_inbox(ctx: Ctx, step: PlanStep) -> StepResult:
    """Company-scoped, case-insensitive substring match over message text (the query is a bound parameter with LIKE
    wildcards escaped), newest 10: thread keys and short snippets only, never full bodies."""
    query = normalise_query(step.text or "")
    if not query:
        return failed(step, NEED_DETAIL)
    with Session(ctx.engine) as session:
        hits = session.execute(
            select(MessageRow.id, MessageRow.channel, MessageRow.thread_ref, MessageRow.provider_msg_id,
                   MessageRow.sent_at, MessageRow.text)
            .where(MessageRow.company_id == ctx.company_id, MessageRow.text.icontains(query, autoescape=True))
            .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
            .limit(MAX_HITS)
        ).all()  # fmt: skip
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
