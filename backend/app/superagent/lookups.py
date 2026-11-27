"""The research loop's lookups: database, messages, documents and the web. Each returns the text the model sees and a
count for the step label; every row and page gets a short reference in the run's `SourceLog`. Read only, company-scoped,
and never a model call inside an open database session."""

import contextlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.channels.calendar import CalendarUnavailableError, get_calendar_client
from app.channels.registry import search_client
from app.context.budget import clip
from app.contracts import Category
from app.core.ids import case_ref
from app.core.localtime import to_local
from app.db.models import Case, Person, Unit
from app.db.models.calendar import CalendarEventRow
from app.llm.render import one_line
from app.pipeline.case_repo import OPEN_STATES
from app.pipeline.concierge_sanitize import redact_contact
from app.pipeline.document_search import DocFilter, metadata_hits
from app.pipeline.draft_research import FINANCE_DOMAINS, LEGAL_DOMAINS, MAINTENANCE_DOMAINS, MARKET_DOMAINS
from app.pipeline.rag import RERANK_TOP, retrieve_context
from app.superagent.research_base import LOOKUP_FAILED, MAX_HITS, SNIPPET_CHARS, SuperAgentDeps
from app.tools.message_rag.rerank import best_lines, best_part, rerank_hits
from app.tools.message_rag.search import search_messages
from app.tools.query_agent.agent import run_query_agent

MAX_WEB_PAGES = 5


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def database(deps: SuperAgentDeps, question: str) -> tuple[str, int]:
    result = run_query_agent(deps.engine, deps.settings, deps.company_id, question)
    if not result.ok:
        return LOOKUP_FAILED, 0
    display = getattr(result, "display_rows", None)
    if isinstance(display, list) and display:
        return json.dumps(display[:15], ensure_ascii=False), result.row_count
    return result.answer, result.row_count


def parse_iso_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None


def messages_filtered(
    deps: SuperAgentDeps,
    query: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    channel: str | None = None,
) -> tuple[str, int]:
    chan = channel.strip().lower() if isinstance(channel, str) and channel.strip() else None
    if chan not in ("gmail", "whatsapp"):
        chan = None
    df = parse_iso_date(date_from)
    dt = parse_iso_date(date_to)
    return message_lines(deps, query, "%Y-%m-%d %H:%M", channel=chan, date_from=df, date_to=dt)


def messages(deps: SuperAgentDeps, query: str) -> tuple[str, int]:
    return message_lines(deps, query, "%Y-%m-%d")


def snippet(text: str, query: str, embedder: Any = None) -> str:
    return clip(best_part(" ".join(text.split()), query, SNIPPET_CHARS, embedder=embedder), SNIPPET_CHARS)


def chunk(text: str, query: str, embedder: Any = None) -> str:
    return one_line(best_lines(text, query, SNIPPET_CHARS, embedder=embedder), SNIPPET_CHARS)


def browse(filters: dict[str, Any]) -> bool:
    return any(v is not None for v in filters.values())


def message_lines(deps: SuperAgentDeps, query: str, stamp: str, **filters: Any) -> tuple[str, int]:
    """Candidates first, then the reranker once the session is closed; a date-only search has no question to rank by."""
    limit = RERANK_TOP if query.strip() else MAX_HITS
    with Session(deps.engine) as session:
        hits = search_messages(session, deps.company_id, query, deps.embedder, limit=limit, **filters)
    if query.strip():
        helpful = rerank_hits(deps.engine, deps.settings, deps.company_id, query, hits, embedder=deps.embedder)
        # "new messages today" has no passage that answers it: a search with a date or channel lists what it found
        hits = (helpful or (hits if browse(filters) else []))[:MAX_HITS]
    lines = []
    for h in hits:
        who, when = h.person_name or "unknown", h.last_sent_at.strftime(stamp)
        ref = deps.sources.add("message", str(h.first_message_id), f"{who}, {h.channel}, {when[:10]}")
        lines.append(
            f"[{ref}] {when} {h.channel} | {who} | {h.unit_address or '-'}: {chunk(h.text, query, deps.embedder)}"
        )
    return "\n".join(lines), len(lines)


def documents(deps: SuperAgentDeps, query: str) -> tuple[str, int]:
    """The answering passages (plan, hybrid, rerank), then documents whose title or file name holds the query."""
    flt = DocFilter(readable_only=True)
    found = retrieve_context(deps.engine, deps.settings, deps.company_id, query, flt, deps.embedder, fact_first=False)
    rows = [(p.document_id, p.title, p.doc_type, snippet(p.text, query, deps.embedder)) for p in found.passages]
    if found.fact is not None:
        f = found.fact
        rows.append((f.document_id, f.title, f.doc_type, f"{f.label}: {f.value}"))
    with Session(deps.engine) as session:
        titled = metadata_hits(session, deps.company_id, query, flt, {r[0] for r in rows}, MAX_HITS)
    rows += [(h.document_id, h.title, h.doc_type, snippet(h.summary or "", query, deps.embedder)) for h in titled]
    lines = []
    for doc_id, title, kind, text in rows[:MAX_HITS]:
        ref = deps.sources.add("document", str(doc_id), f"{title} ({kind})")
        lines.append(f"[{ref}] {one_line(title)} ({kind}): {one_line(text, SNIPPET_CHARS)}")
    return "\n".join(lines), len(lines)


_TOPIC_DOMAINS: dict[str, tuple[str, ...]] = {
    "legal": LEGAL_DOMAINS,
    "finance": FINANCE_DOMAINS,
    "market": MARKET_DOMAINS,
    "maintenance": MAINTENANCE_DOMAINS,
}


def cases(
    deps: SuperAgentDeps,
    query: str = "",
    *,
    category: str | None = None,
    state: str | None = None,
) -> tuple[str, int]:
    """Search EstateOS cases across all 6 business categories, returning short source refs for `open_case`."""
    stmt = (
        select(Case, Person.display_name, Unit.address, Unit.label)
        .outerjoin(Person, (Person.id == Case.primary_person_id) & (Person.company_id == deps.company_id))
        .outerjoin(Unit, (Unit.id == Case.unit_id) & (Unit.company_id == deps.company_id))
        .where(Case.company_id == deps.company_id)
    )
    if category and category.strip():
        with contextlib.suppress(ValueError):
            stmt = stmt.where(Case.category == Category(category.strip().lower()))
    if state and state.strip().lower() == "open":
        stmt = stmt.where(Case.state.in_(OPEN_STATES))
    elif state and state.strip().lower() in ("closed", "resolved"):
        stmt = stmt.where(Case.state.notin_(OPEN_STATES))

    q_clean = query.strip()
    if q_clean:
        pat = f"%{q_clean}%"
        stmt = stmt.where(
            or_(
                Case.summary.ilike(pat),
                Case.brixx_ref.ilike(pat),
                Person.display_name.ilike(pat),
                Unit.address.ilike(pat),
                Unit.label.ilike(pat),
            )
        )
    with Session(deps.engine) as session:
        rows = session.execute(stmt.order_by(Case.opened_at.desc(), Case.id.desc()).limit(MAX_HITS)).all()
    lines: list[str] = []
    for c, person_name, unit_addr, unit_lbl in rows:
        who = one_line(redact_contact(person_name or "Unknown"), 40)
        where = one_line(unit_addr or unit_lbl or "General", 40)
        ref = deps.sources.add("data", str(c.id), f"Case #{case_ref(c.id)} · {c.category.value} · {who}")
        snippet_txt = one_line(redact_contact(c.summary or ""), 140)
        lines.append(
            f"[{ref}] #{case_ref(c.id)} {c.category.value} | {c.state.value} | "
            f"{c.urgency.value} | {who} | {where}: {snippet_txt}"
        )
    return "\n".join(lines), len(lines)


def calendar_events(deps: SuperAgentDeps, days_ahead: int = 14) -> tuple[str, int]:
    """Read upcoming events from EstateOS DB and live Google Calendar (plus pending invites)."""
    days = max(1, min(60, days_ahead))
    now = datetime.now(UTC)
    end = now + timedelta(days=days)
    lines: list[str] = []
    with Session(deps.engine) as session:
        db_rows = session.scalars(
            select(CalendarEventRow)
            .where(
                CalendarEventRow.company_id == deps.company_id,
                CalendarEventRow.status != "cancelled",
                CalendarEventRow.end_time >= now,
                CalendarEventRow.start_time <= end,
            )
            .order_by(CalendarEventRow.start_time.asc())
            .limit(15)
        ).all()
        for r in db_rows:
            when = to_local(r.start_time).strftime("%Y-%m-%d %H:%M")
            lines.append(f"EstateOS [{r.status}] {when} | {one_line(r.title, 60)} | {one_line(r.location or '-', 50)}")

    gcal_note = ""
    try:
        client = get_calendar_client()
        live = client.list_events(now, end)
        for ev in live[:15]:
            when = to_local(ev.start_time).strftime("%Y-%m-%d %H:%M")
            lines.append(f"Google [{ev.status}] {when} | {one_line(ev.title, 60)} | {one_line(ev.location or '-', 50)}")
        invites = client.list_pending_invites(now, end)
        for inv in invites[:5]:
            when = to_local(inv.start_time).strftime("%Y-%m-%d %H:%M")
            lines.append(f"Pending invite {when} | {one_line(inv.title, 60)} | {one_line(inv.location or '-', 50)}")
    except CalendarUnavailableError as exc:
        gcal_note = f"{exc} Google Calendar could not be read completely."
    except Exception:
        gcal_note = "Could not reach Google Calendar; showing EstateOS calendar rows only."

    found = len(lines)
    if gcal_note:
        lines.append(gcal_note)
    ref = deps.sources.add("data", f"calendar:{days}", f"Calendar (next {days} days)")
    text = f"[{ref}] " + ("\n".join(lines) if lines else f"No events in the next {days} days.")
    return text, found


def calendar_free_busy(deps: SuperAgentDeps, start_iso: str, end_iso: str) -> tuple[str, int]:
    """Check busy slots in Google Calendar for a requested ISO datetime window."""
    try:
        start_dt = datetime.fromisoformat(start_iso.strip())
        end_dt = datetime.fromisoformat(end_iso.strip())
    except ValueError:
        return "Invalid ISO datetime window. Provide start and end in ISO format.", 0
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=UTC)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=UTC)
    try:
        busy = get_calendar_client().check_free_busy(start_dt, end_dt)
    except CalendarUnavailableError as exc:
        return f"Live availability cannot be checked. {exc}", 0
    except Exception:
        return LOOKUP_FAILED, 0
    ref = deps.sources.add("data", f"freebusy:{start_iso}", "Calendar availability")
    if not busy:
        return f"[{ref}] Slot {to_local(start_dt):%Y-%m-%d %H:%M} - {to_local(end_dt):%H:%M} is FREE.", 1
    slots = [f"{to_local(s.start_time):%H:%M}-{to_local(s.end_time):%H:%M}" for s in busy[:5]]
    return f"[{ref}] BUSY slots in window: {', '.join(slots)}.", len(busy)


def web(deps: SuperAgentDeps, query: str, *, topic: str = "general") -> tuple[str, int]:
    """Public pages, each fetched and read by the adapter; untrusted text like mail. Every finding carries its URL."""
    domains = _TOPIC_DOMAINS.get(topic.strip().lower(), ())
    client = search_client(deps.settings, deps.engine, deps.company_id, domains)
    hits = client.search(redact_contact(query), region="nl", limit=MAX_WEB_PAGES)  # no personal data to Google
    lines = []
    for hit in hits[:MAX_WEB_PAGES]:
        host = urlsplit(hit.url).hostname or ""
        ref = deps.sources.add("web", hit.url, one_line(f"{hit.title or host} ({host})", 120))
        lines.append(f"[{ref}] {one_line(hit.title, 120)} ({hit.url}): {snippet(hit.text, query, deps.embedder)}")
    return "\n".join(lines), len(lines)
