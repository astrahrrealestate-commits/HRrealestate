"""Owner morning email digest: collects reply proposals, decisions, tasks, waits, and exceptions.

Timer briefing.daily (07:30 company tz) sends one email to owner_accounts.email in addition to the
interactive channel's short briefing. Weekly (Friday 16:00) likewise.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.contracts import ActionType, Channel, Urgency
from app.core.logging import get_logger
from app.db.enums import ActionStatus, ApprovalStatus, PipelineStatus, TaskStatus, WaitStatus
from app.db.models import (
    ActionRow,
    Approval,
    Case,
    CaseLink,
    Company,
    MessageRow,
    Person,
    TaskRow,
    UnderstandingRow,
    WaitRow,
)
from app.llm.agents.briefing import Kind
from app.owner.card_data import case_label

log = get_logger(__name__)


@dataclass(frozen=True)
class DigestCaseReply:
    case_id: UUID
    approval_id: UUID
    action_id: UUID
    who: str
    category: str
    urgency: Urgency
    situation: str
    drafts: tuple[str, ...]
    thread_id: str | None = None

    @property
    def gmail_url(self) -> str | None:
        return f"https://mail.google.com/mail/u/0/#inbox/{self.thread_id}" if self.thread_id else None


@dataclass(frozen=True)
class DigestData:
    company_id: UUID
    company_name: str
    date_label: str
    kind: Kind
    replies: tuple[DigestCaseReply, ...] = ()
    decisions: tuple[str, ...] = ()  # non-reply pending approvals
    tasks_due: tuple[str, ...] = ()
    waiting_on_others: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    ignored_count: int = 0
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def has_items(self) -> bool:
        return bool(self.replies or self.decisions or self.tasks_due or self.waiting_on_others or self.exceptions)


def _latest_gmail_thread(session: Session, case_id: UUID) -> str | None:
    msg = session.scalar(
        select(MessageRow)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(CaseLink.case_id == case_id, MessageRow.channel == Channel.gmail)
        .order_by(MessageRow.sent_at.desc())
    )
    return msg.thread_ref if msg else None


def count_ignored_messages(session: Session, company_id: UUID, since: datetime) -> int:
    """Messages triaged with requires_reply=False and not suspicious in the time window."""
    rows = session.scalars(
        select(UnderstandingRow.body)
        .join(MessageRow, MessageRow.id == UnderstandingRow.message_id)
        .where(
            UnderstandingRow.company_id == company_id,
            MessageRow.created_at >= since,
            MessageRow.pipeline_status == PipelineStatus.done,
        )
    ).all()
    ignored = 0
    for b in rows:
        if not b.get("requires_reply", True) and not (b.get("suspicious") or {}).get("flag", False):
            ignored += 1
    return ignored


def collect_digest_data(session: Session, company_id: UUID, kind: Kind, now: datetime) -> DigestData:
    company = session.get(Company, company_id)
    if company is None:
        raise ValueError(f"company {company_id} not found")
    tz = ZoneInfo(company.timezone)
    since = now - timedelta(days=7 if kind == "weekly" else 1)

    # 1. Replies needing owner approval
    reply_rows = session.execute(
        select(Approval, ActionRow, Case)
        .join(ActionRow, ActionRow.id == Approval.action_id)
        .join(Case, Case.id == ActionRow.case_id)
        .where(
            Approval.company_id == company_id,
            Approval.status == ApprovalStatus.pending,
            ActionRow.type == ActionType.reply_draft,
        )
        .order_by(Approval.created_at)
    ).all()

    replies: list[DigestCaseReply] = []
    for appr, act, case in reply_rows:
        who = (
            session.scalar(
                select(Person.display_name).where(Person.company_id == company_id, Person.id == case.primary_person_id)
            )
            or "Unknown sender"
        )
        situation = act.rationale or (case.summary.splitlines()[0] if case.summary else "Inbound inquiry")
        variants = tuple(act.payload.get("body_variants") or ())
        thread_id = _latest_gmail_thread(session, case.id)
        replies.append(
            DigestCaseReply(
                case_id=case.id,
                approval_id=appr.id,
                action_id=act.id,
                who=who,
                category=case.category.value,
                urgency=case.urgency,
                situation=situation,
                drafts=variants,
                thread_id=thread_id,
            )
        )

    # 2. Other decisions waiting (non-reply approvals)
    decision_rows = session.execute(
        select(ActionRow, Case)
        .join(Approval, Approval.action_id == ActionRow.id)
        .join(Case, Case.id == ActionRow.case_id)
        .where(
            Approval.company_id == company_id,
            Approval.status == ApprovalStatus.pending,
            ActionRow.type != ActionType.reply_draft,
        )
        .order_by(Approval.created_at)
    ).all()
    decisions = tuple(f"{a.type.value.replace('_', ' ')}: {case_label(session, c)}" for a, c in decision_rows)

    # 3. Tasks due
    tasks_visible = TaskRow.status == TaskStatus.open
    if now is not None:
        tasks_visible = or_(tasks_visible, (TaskRow.status == TaskStatus.snoozed) & (TaskRow.snoozed_until <= now))
    open_task_rows = list(
        session.scalars(
            select(TaskRow)
            .where(TaskRow.company_id == company_id, tasks_visible)
            .order_by(TaskRow.priority, TaskRow.due_at.nulls_last(), TaskRow.created_at)
        ).all()
    )
    overdue_tasks = [t for t in open_task_rows if t.due_at and t.due_at < now]
    tasks_due = tuple(f"{t.title} (due {t.due_at.astimezone(tz):%a %H:%M})" for t in overdue_tasks if t.due_at)

    # 4. Waiting on others
    overdue_wait_rows = list(
        session.scalars(
            select(WaitRow)
            .where(WaitRow.company_id == company_id, WaitRow.status == WaitStatus.waiting, WaitRow.expected_by < now)
            .order_by(WaitRow.expected_by)
        ).all()
    )
    waiting_on_others = tuple(f"{w.about} ({w.chase_count} reminders sent)" for w in overdue_wait_rows)

    # 5. Exceptions
    exception_rows = session.scalars(
        select(ActionRow.rationale).where(
            ActionRow.company_id == company_id,
            ActionRow.status == ActionStatus.exception,
            ActionRow.created_at >= since,
        )
    ).all()
    exceptions = tuple(str(e) for e in exception_rows)

    ignored_count = count_ignored_messages(session, company_id, since)

    return DigestData(
        company_id=company_id,
        company_name=company.name,
        date_label=f"{now.astimezone(tz):%A, %d %B %Y}",
        kind=kind,
        replies=tuple(replies),
        decisions=decisions,
        tasks_due=tasks_due,
        waiting_on_others=waiting_on_others,
        exceptions=exceptions,
        ignored_count=ignored_count,
    )


def render_digest_email(data: DigestData) -> tuple[str, str, str]:
    """Returns (subject, text_body, html_body)."""
    kind_title = "Daily Briefing" if data.kind == "daily" else "Weekly Summary"
    subject = f"EstateOS {kind_title} – {data.date_label}"

    # Plain text version
    text_lines = [
        f"EstateOS {kind_title}",
        data.date_label,
        "=" * 40,
        "",
    ]

    if data.replies:
        text_lines.append("## Needs your reply")
        for r in data.replies:
            text_lines.append(f"\n• [{r.urgency.value.upper()}] {r.who} · {r.category}")
            text_lines.append(f"  Situation: {r.situation}")
            if r.gmail_url:
                text_lines.append(f"  Thread: {r.gmail_url}")
            for i, d in enumerate(r.drafts, start=1):
                text_lines.append(f"  Draft {i}:\n    " + d.replace("\n", "\n    "))
        text_lines.append("")

    if data.decisions:
        text_lines.append("## Decisions waiting")
        for d in data.decisions:
            text_lines.append(f"• {d}")
        text_lines.append("")

    if data.tasks_due:
        text_lines.append("## Tasks due")
        for t in data.tasks_due:
            text_lines.append(f"• {t}")
        text_lines.append("")

    if data.waiting_on_others:
        text_lines.append("## Waiting on others / chasers")
        for w in data.waiting_on_others:
            text_lines.append(f"• {w}")
        text_lines.append("")

    if data.exceptions:
        text_lines.append("## Exceptions (needs your eyes)")
        for e in data.exceptions:
            text_lines.append(f"• {e}")
        text_lines.append("")

    if data.ignored_count > 0:
        text_lines.append(f"ℹ️ {data.ignored_count} message(s) ignored (newsletters, receipts, spam).")

    text_body = "\n".join(text_lines)

    css = (
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.5; color: #1f2937; margin: 0; padding: 24px; background-color: #f9fafb; }\n"
        ".container { max-width: 680px; margin: 0 auto; background: #ffffff; border-radius: 8px; "
        "border: 1px solid #e5e7eb; padding: 32px; }\n"
        "h1 { font-size: 20px; font-weight: 700; color: #111827; margin: 0 0 4px 0; }\n"
        ".date { font-size: 14px; color: #6b7280; margin-bottom: 24px; }\n"
        "h2 { font-size: 16px; font-weight: 600; color: #374151; border-bottom: 1px solid #e5e7eb; "
        "padding-bottom: 8px; margin-top: 28px; }\n"
        ".card { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 16px; "
        "margin-bottom: 16px; }\n"
        ".badge-emergency { background: #fee2e2; color: #991b1b; padding: 2px 6px; border-radius: 4px; "
        "font-size: 11px; font-weight: bold; }\n"
        ".badge-high { background: #fef3c7; color: #92400e; padding: 2px 6px; border-radius: 4px; "
        "font-size: 11px; font-weight: bold; }\n"
        ".badge-normal { background: #e0f2fe; color: #075985; padding: 2px 6px; border-radius: 4px; "
        "font-size: 11px; font-weight: bold; }\n"
        ".badge-low { background: #f3f4f6; color: #4b5563; padding: 2px 6px; border-radius: 4px; "
        "font-size: 11px; font-weight: bold; }\n"
        ".draft { background: #ffffff; border-left: 3px solid #3b82f6; padding: 8px 12px; margin: 8px 0; "
        "font-size: 13px; color: #374151; white-space: pre-wrap; }\n"
        ".btn-link { display: inline-block; font-size: 12px; font-weight: 600; color: #2563eb; "
        "text-decoration: none; margin-top: 6px; }\n"
        "ul { padding-left: 20px; margin: 8px 0; }\n"
        "li { margin-bottom: 6px; font-size: 14px; }\n"
        ".ignored { font-size: 13px; color: #6b7280; font-style: italic; margin-top: 24px; padding-top: 12px; "
        "border-top: 1px solid #e5e7eb; }\n"
    )

    # HTML version
    html_parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        f"<style>{css}</style></head><body>",
        "<div class='container'>",
        f"<h1>EstateOS {kind_title}</h1>",
        f"<div class='date'>{data.date_label}</div>",
    ]

    if data.replies:
        html_parts.append("<h2>Needs your reply</h2>")
        for r in data.replies:
            badge_cls = f"badge-{r.urgency.value}"
            link_html = f"<a class='btn-link' href='{r.gmail_url}'>Open thread in Gmail →</a>" if r.gmail_url else ""
            html_parts.append(
                f"<div class='card'>"
                f"<div><span class='{badge_cls}'>{r.urgency.value.upper()}</span> "
                f"<strong>{r.who}</strong> · {r.category}</div>"
                f"<div style='font-size: 14px; margin: 6px 0; color: #4b5563;'>{r.situation}</div>"
            )
            for i, d in enumerate(r.drafts, start=1):
                escaped = d.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_parts.append(f"<div class='draft'><strong>Draft {i}:</strong><br>{escaped}</div>")
            if link_html:
                html_parts.append(link_html)
            html_parts.append("</div>")

    if data.decisions:
        html_parts.append("<h2>Decisions waiting</h2><ul>")
        for d in data.decisions:
            html_parts.append(f"<li>{d}</li>")
        html_parts.append("</ul>")

    if data.tasks_due:
        html_parts.append("<h2>Tasks due</h2><ul>")
        for t in data.tasks_due:
            html_parts.append(f"<li>{t}</li>")
        html_parts.append("</ul>")

    if data.waiting_on_others:
        html_parts.append("<h2>Waiting on others</h2><ul>")
        for w in data.waiting_on_others:
            html_parts.append(f"<li>{w}</li>")
        html_parts.append("</ul>")

    if data.exceptions:
        html_parts.append("<h2>Exceptions</h2><ul>")
        for e in data.exceptions:
            html_parts.append(f"<li>{e}</li>")
        html_parts.append("</ul>")

    if data.ignored_count > 0:
        html_parts.append(
            f"<div class='ignored'>ℹ️ {data.ignored_count} message(s) ignored (newsletters, receipts, spam).</div>"
        )

    html_parts.append("</div></body></html>")
    html_body = "".join(html_parts)

    return subject, text_body, html_body
