"""Owner morning email digest: collects reply proposals, decisions, tasks, waits, and exceptions.

Timer briefing.daily (07:30 company tz) sends one email to owner_accounts.email in addition to the
interactive channel's short briefing. Weekly (Friday 16:00) likewise.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
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
    _urgency_order = {Urgency.emergency: 0, Urgency.high: 1, Urgency.normal: 2, Urgency.low: 3}
    replies.sort(key=lambda r: _urgency_order.get(r.urgency, 99))

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
        "body { margin: 0; padding: 24px 12px; background-color: #f1f5f9; "
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; "
        "color: #1e293b; line-height: 1.5; -webkit-font-smoothing: antialiased; }\n"
        ".wrapper { max-width: 620px; margin: 0 auto; }\n"
        ".header { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px 12px 0 0; "
        "padding: 24px 28px 20px; border-bottom: 2px solid #2563eb; }\n"
        ".brand { display: inline-block; font-size: 11px; font-weight: 700; text-transform: uppercase; "
        "letter-spacing: 0.08em; color: #2563eb; background: #eff6ff; padding: 3px 8px; border-radius: 4px; "
        "margin-bottom: 8px; }\n"
        ".title { font-size: 22px; font-weight: 800; color: #0f172a; margin: 0 0 4px; letter-spacing: -0.02em; }\n"
        ".subtitle { font-size: 13px; color: #64748b; margin: 0; }\n"
        ".kpi-bar { display: table; width: 100%; background: #ffffff; border-left: 1px solid #e2e8f0; "
        "border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0; box-sizing: border-box; }\n"
        ".kpi-cell { display: table-cell; padding: 12px 8px; text-align: center; border-right: 1px solid #f1f5f9; }\n"
        ".kpi-cell:last-child { border-right: none; }\n"
        ".kpi-num { font-size: 18px; font-weight: 700; }\n"
        ".kpi-label { font-size: 11px; color: #64748b; font-weight: 500; text-transform: uppercase; }\n"
        ".content { background: #ffffff; border: 1px solid #e2e8f0; border-top: none; "
        "border-radius: 0 0 12px 12px; padding: 24px 28px; }\n"
        ".section-title { font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; "
        "color: #475569; margin: 28px 0 14px; padding-bottom: 6px; border-bottom: 1px solid #e2e8f0; }\n"
        ".section-title:first-child { margin-top: 4px; }\n"
        ".case-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px; "
        "margin-bottom: 18px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }\n"
        ".case-header { margin-bottom: 10px; font-size: 14px; color: #0f172a; }\n"
        ".badge { display: inline-block; padding: 2px 8px; border-radius: 9999px; font-size: 10px; "
        "font-weight: 700; letter-spacing: 0.04em; vertical-align: middle; margin-right: 6px; }\n"
        ".badge-emergency { background: #fee2e2; color: #991b1b; }\n"
        ".badge-high { background: #fef3c7; color: #92400e; }\n"
        ".badge-normal { background: #e0f2fe; color: #0369a1; }\n"
        ".badge-low { background: #f1f5f9; color: #475569; }\n"
        ".tag { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 11px; "
        "background: #f1f5f9; color: #475569; margin-left: 6px; }\n"
        ".situation-callout { background: #f8fafc; border-left: 3px solid #94a3b8; padding: 8px 12px; "
        "border-radius: 0 4px 4px 0; font-size: 13px; color: #334155; margin: 10px 0; }\n"
        ".draft-primary { background: #ffffff; border: 1px solid #bfdbfe; border-left: 4px solid #2563eb; "
        "border-radius: 0 6px 6px 0; padding: 12px 14px; margin: 12px 0; }\n"
        ".draft-tag { font-size: 11px; font-weight: 700; color: #2563eb; text-transform: uppercase; "
        "letter-spacing: 0.04em; margin-bottom: 6px; }\n"
        ".draft-body { font-size: 13px; color: #1e293b; line-height: 1.55; white-space: pre-wrap; "
        "font-family: inherit; }\n"
        ".alt-drafts { margin: 10px 0 6px; font-size: 12px; }\n"
        ".alt-summary { cursor: pointer; color: #2563eb; font-weight: 600; padding: 4px 0; user-select: none; }\n"
        ".alt-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; padding: 10px 12px; "
        "margin-top: 6px; font-size: 13px; color: #475569; white-space: pre-wrap; line-height: 1.5; }\n"
        ".action-row { margin-top: 14px; padding-top: 10px; border-top: 1px solid #f1f5f9; }\n"
        ".btn-action { display: inline-block; background-color: #2563eb; color: #ffffff !important; "
        "font-size: 12px; font-weight: 600; padding: 8px 16px; border-radius: 6px; text-decoration: none; }\n"
        ".item-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px 14px; "
        "margin-bottom: 8px; font-size: 13px; color: #334155; }\n"
        ".item-card.exception { background: #fffbeb; border-color: #fde68a; color: #92400e; }\n"
        ".ignored-footer { margin-top: 28px; padding: 14px; background: #f8fafc; border: 1px dashed #cbd5e1; "
        "border-radius: 6px; font-size: 12px; color: #64748b; text-align: center; }\n"
        ".footer-brand { margin-top: 18px; font-size: 11px; color: #94a3b8; text-align: center; }\n"
    )

    num_replies = len(data.replies)
    num_decisions = len(data.decisions)
    num_tasks = len(data.tasks_due)

    # HTML version
    html_parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        f"<style>{css}</style></head><body>",
        "<div class='wrapper'>",
        "<div class='header'>",
        "<div class='brand'>EstateOS</div>",
        f"<div class='title'>{kind_title}</div>",
        f"<div class='subtitle'>{data.date_label} · {data.company_name}</div>",
        "</div>",
        "<div class='kpi-bar'>",
        f"<div class='kpi-cell'><div class='kpi-num' style='color:#ef4444;'>{num_replies}</div>"
        f"<div class='kpi-label'>Replies</div></div>",
        f"<div class='kpi-cell'><div class='kpi-num' style='color:#f59e0b;'>{num_decisions}</div>"
        f"<div class='kpi-label'>Decisions</div></div>",
        f"<div class='kpi-cell'><div class='kpi-num' style='color:#3b82f6;'>{num_tasks}</div>"
        f"<div class='kpi-label'>Tasks</div></div>",
        f"<div class='kpi-cell'><div class='kpi-num' style='color:#64748b;'>{data.ignored_count}</div>"
        f"<div class='kpi-label'>Filtered</div></div>",
        "</div>",
        "<div class='content'>",
    ]

    if data.replies:
        html_parts.append("<div class='section-title'>📬 Needs Your Reply</div>")
        for r in data.replies:
            badge_cls = f"badge-{r.urgency.value}"
            link_html = (
                f"<div class='action-row'><a class='btn-action' href='{r.gmail_url}'>Open thread in Gmail →</a></div>"
                if r.gmail_url
                else ""
            )

            html_parts.append(
                f"<div class='case-card'>"
                f"<div class='case-header'>"
                f"<span class='badge {badge_cls}'>{r.urgency.value.upper()}</span>"
                f"<strong>{r.who}</strong>"
                f"<span class='tag'>{r.category}</span>"
                f"</div>"
                f"<div class='situation-callout'><strong>Situation:</strong> {r.situation}</div>"
            )

            if r.drafts:
                # Primary / recommended draft
                d1 = r.drafts[0].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_parts.append(
                    f"<div class='draft-primary'>"
                    f"<div class='draft-tag'>Draft 1 (Recommended)</div>"
                    f"<div class='draft-body'>{d1}</div>"
                    f"</div>"
                )

                # Alternative drafts enclosed in collapsible details if present
                if len(r.drafts) > 1:
                    alt_count = len(r.drafts) - 1
                    html_parts.append(
                        f"<details class='alt-drafts'>"
                        f"<summary class='alt-summary'>▶ View {alt_count} alternative draft(s)</summary>"
                    )
                    for idx, alt_d in enumerate(r.drafts[1:], start=2):
                        alt_esc = alt_d.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        html_parts.append(f"<div class='alt-card'><strong>Draft {idx}:</strong><br>{alt_esc}</div>")
                    html_parts.append("</details>")

            if link_html:
                html_parts.append(link_html)
            html_parts.append("</div>")

    if data.decisions:
        html_parts.append("<div class='section-title'>⚖️ Decisions Waiting</div>")
        for d in data.decisions:
            html_parts.append(f"<div class='item-card'>• {d}</div>")

    if data.tasks_due:
        html_parts.append("<div class='section-title'>⏱️ Tasks Due Today</div>")
        for t in data.tasks_due:
            html_parts.append(f"<div class='item-card'>📋 {t}</div>")

    if data.waiting_on_others:
        html_parts.append("<div class='section-title'>⏳ Waiting On Others</div>")
        for w in data.waiting_on_others:
            html_parts.append(f"<div class='item-card'>⏳ {w}</div>")

    if data.exceptions:
        html_parts.append("<div class='section-title'>⚠️ Exceptions (Needs Eyes)</div>")
        for e in data.exceptions:
            html_parts.append(f"<div class='item-card exception'>⚠️ {e}</div>")

    if data.ignored_count > 0:
        html_parts.append(
            f"<div class='ignored-footer'>"
            f"🛡️ <strong>{data.ignored_count} message(s) ignored</strong> "
            f"(newsletters, receipts, automated updates left alone)."
            f"</div>"
        )

    html_parts.append("<div class='footer-brand'>EstateOS Automated Briefing</div></div></div></body></html>")
    html_body = "".join(html_parts)

    return subject, text_body, html_body


def render_digest_chat(data: DigestData) -> dict[str, Any]:
    """Renders DigestData into an interactive Google Chat cardsV2 message."""
    kind_title = "Daily Briefing" if data.kind == "daily" else "Weekly Summary"
    sections: list[dict[str, Any]] = []

    # KPI summary bar
    num_replies = len(data.replies)
    num_decisions = len(data.decisions)
    num_tasks = len(data.tasks_due)
    kpi_text = (
        f"<b>📊 At a glance:</b>\n"
        f"• {num_replies} replies needed\n"
        f"• {num_decisions} decisions waiting\n"
        f"• {num_tasks} tasks due today\n"
        f"• {data.ignored_count} ignored (spam/receipts)"
    )
    sections.append(
        {
            "header": "Summary",
            "widgets": [{"textParagraph": {"text": kpi_text}}],
        }
    )

    # Cases needing reply
    for r in data.replies:
        widgets: list[dict[str, Any]] = []
        info = f"<b>[{r.urgency.value.upper()}] {r.who}</b> · {r.category}\n<i>Situation:</i> {r.situation}"
        widgets.append({"textParagraph": {"text": info}})

        if r.drafts:
            draft_1 = r.drafts[0]
            widgets.append({"textParagraph": {"text": f"<b>Draft 1 (Recommended):</b>\n{draft_1}"}})

        buttons: list[dict[str, Any]] = [
            {
                "text": "Send draft 1",
                "onClick": {
                    "action": {
                        "function": "owner_action",
                        "parameters": [{"key": "button_id", "value": f"apr:{r.approval_id}:d1"}],
                    }
                },
            },
            {
                "text": "Edit",
                "onClick": {
                    "action": {
                        "function": "owner_action",
                        "parameters": [{"key": "button_id", "value": f"apr:{r.approval_id}:edit"}],
                    }
                },
            },
            {
                "text": "Reject",
                "onClick": {
                    "action": {
                        "function": "owner_action",
                        "parameters": [{"key": "button_id", "value": f"apr:{r.approval_id}:rej"}],
                    }
                },
            },
        ]
        if r.gmail_url:
            buttons.append(
                {
                    "text": "Open in Gmail →",
                    "onClick": {"openLink": {"url": r.gmail_url}},
                }
            )
        widgets.append({"buttonList": {"buttons": buttons}})
        sections.append(
            {
                "header": f"Needs Reply: {r.who}",
                "widgets": widgets,
            }
        )

    # Decisions
    if data.decisions:
        dec_text = "\n".join(f"• {d}" for d in data.decisions)
        sections.append(
            {
                "header": "Decisions Waiting",
                "widgets": [{"textParagraph": {"text": dec_text}}],
            }
        )

    # Tasks
    if data.tasks_due:
        task_text = "\n".join(f"📋 {t}" for t in data.tasks_due)
        sections.append(
            {
                "header": "Tasks Due Today",
                "widgets": [{"textParagraph": {"text": task_text}}],
            }
        )

    if data.ignored_count > 0:
        sections.append(
            {
                "widgets": [
                    {
                        "textParagraph": {
                            "text": f"<i>🛡️ {data.ignored_count} messages ignored (newsletters, receipts, spam).</i>"
                        }
                    }
                ]
            }
        )

    card: dict[str, Any] = {
        "header": {
            "title": f"EstateOS {kind_title}",
            "subtitle": f"{data.date_label} · {data.company_name}",
        },
        "sections": sections,
    }
    return {
        "cardsV2": [
            {
                "cardId": "estateos_digest_briefing",
                "card": card,
            }
        ]
    }
