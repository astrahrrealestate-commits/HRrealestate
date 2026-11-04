"""What the agent tour left behind: model calls per agent and the rows each agent produces, since the tour began."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db.base import CompanyScoped
from app.db.models import (
    ActionRow,
    Case,
    DDReview,
    DocumentRow,
    ModelCall,
    QuoteLineRow,
    QuoteReview,
    QuoteRow,
    TaskRow,
    UnderstandingRow,
)
from app.db.models.calendar import CalendarEventRow

# agent purpose -> what shows it working. Some only run when the model chose to (an unambiguous follow-up needs no
# link_check), so a missing one is reported, not failed.
AGENTS = {
    "triage": "every message is understood",
    "link_check": "an ambiguous follow-up is matched to one of several open cases",
    "case_summary": "each case gets a summary",
    "proposer": "reply and contractor actions with drafts",
    "doc_classifier": "attachments are typed and filed",
    "doc_reader": "document facts are read from the text",
    "finance_quote_reader": "a contractor quote is read and checked",
    "dd_reader": "due-diligence documents are read",
    "concierge": "Super Agent answers",
    "owner_qa": "Super Agent answers a question about the portfolio",
    "doc_qa": "an answer from document text",
    "briefing_daily": "the daily briefing",
}


@dataclass(frozen=True)
class Calls:
    purpose: str
    calls: int
    errors: int


def model_calls(engine: Engine, company_id: UUID, since: datetime) -> dict[str, Calls]:
    query = (
        select(ModelCall.purpose, func.count(), func.count(ModelCall.error))
        .where(ModelCall.company_id == company_id, ModelCall.created_at >= since)
        .group_by(ModelCall.purpose)
    )
    with Session(engine) as session:
        return {p: Calls(p, n, e) for p, n, e in session.execute(query)}


def row_counts(engine: Engine, company_id: UUID, since: datetime) -> dict[str, int]:
    tables: dict[str, type[CompanyScoped]] = {
        "cases": Case,
        "understandings": UnderstandingRow,
        "actions (proposals)": ActionRow,
        "tasks": TaskRow,
        "documents": DocumentRow,
        "quotes": QuoteRow,
        "quote lines": QuoteLineRow,
        "quote reviews": QuoteReview,
        "due-diligence reviews": DDReview,
        "calendar events": CalendarEventRow,
    }
    with Session(engine) as session:
        return {
            name: session.scalar(
                select(func.count()).select_from(model).where(model.company_id == company_id, model.created_at >= since)
            )
            or 0
            for name, model in tables.items()
        }


def render(calls: dict[str, Calls], counts: dict[str, int]) -> str:
    lines = ["", "AGENT                  CALLS  ERRORS  WHAT IT DOES"]
    for purpose, meaning in AGENTS.items():
        seen = calls.get(purpose)
        lines.append(f"{purpose:<22} {seen.calls if seen else 0:>5}  {seen.errors if seen else 0:>6}  {meaning}")
    other = sorted(set(calls) - set(AGENTS))
    lines += [f"{p:<22} {calls[p].calls:>5}  {calls[p].errors:>6}  (other)" for p in other]
    lines += ["", "ROWS CREATED"] + [f"{name:<24} {n:>5}" for name, n in counts.items()]
    return "\n".join(lines) + "\n"
