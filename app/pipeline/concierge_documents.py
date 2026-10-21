"""Document intents of the concierge plan (M10): find documents, answer from them. Read-only, company-scoped.

Titles, snippets and quotes come from documents written by tenants and contractors: they are shown as data, with
links, e-mail addresses and IBANs removed, and never become instructions.
"""

from sqlalchemy.orm import Session

from app.contracts import PlanStep
from app.core.errors import BudgetExceededError
from app.pipeline.concierge_base import NEED_DETAIL, Ctx, StepResult, failed
from app.pipeline.concierge_sanitize import normalise_query, sanitize
from app.pipeline.document_qa import answer_from_documents, case_scope, strip_risky
from app.pipeline.document_search import DocFilter, search_documents
from app.pipeline.owner_commands import LIMIT_ANSWER

MAX_DOCS = 8
SNIPPET = 200


def find_document(ctx: Ctx, step: PlanStep) -> StepResult:
    query = normalise_query(step.text or "")
    if not query:
        return failed(step, NEED_DETAIL)
    with Session(ctx.engine) as session:
        scope = case_scope(session, ctx.company_id, step.case_id) if step.case_id else ()
        hits = search_documents(session, ctx.company_id, query, DocFilter(any_link=scope), MAX_DOCS, match="any")
    rows = [
        {
            "document_id": str(h.document_id),
            "title": sanitize(h.title),
            "doc_type": h.doc_type,
            "document_date": h.document_date.isoformat() if h.document_date else None,
            "status": h.status.value,
            "snippet": strip_risky(" ".join((h.snippet or "").split()))[:SNIPPET] or None,
            "drive_url": h.drive_url,
            "suspicious": h.suspicious,
        }
        for h in hits
    ]
    if not rows:
        return StepResult(step.intent, True, "No documents match that.", {"documents": []}, None)
    listing = "; ".join(f"{r['title']} ({r['doc_type']}, {r['document_date'] or 'undated'})" for r in rows)
    return StepResult(step.intent, True, f"Found {len(rows)} document(s): {listing}.", {"documents": rows}, None)


def read_document(ctx: Ctx, step: PlanStep) -> StepResult:
    """The owner's own message is the question (never the model's `text`); the answer is built from verified quotes."""
    try:
        result = answer_from_documents(ctx.engine, ctx.settings, ctx.company_id, ctx.question, step.case_id)
    except BudgetExceededError:
        return StepResult(step.intent, False, LIMIT_ANSWER, None, None)
    data = {"found": result.found, "quotes": [{"document_id": str(q.document_id), "title": sanitize(q.title),
                                               "text": strip_risky(q.text)} for q in result.quotes]}  # fmt: skip
    return StepResult(step.intent, result.found, result.text, data, None)
