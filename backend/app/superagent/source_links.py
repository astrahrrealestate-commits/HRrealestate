"""Where an Astra source chip opens (M13 T15). Built by the server from its own rows after the answer is screened: a
message opens its case thread in the inbox, a filed document its Drive file, a web page its own https URL. The model
never names a link, and a row of another company, or one with nowhere to go, gets none."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts.sourced_answer import Source
from app.db.models import CaseLink, DocumentRow
from app.pipeline.document_search import DRIVE_URL


def _ids(sources: Sequence[Source], kind: str) -> list[UUID]:
    out: list[UUID] = []
    for source in sources:
        if source.kind == kind:
            try:
                out.append(UUID(source.ref))
            except ValueError:
                continue
    return out


def _hrefs(session: Session, company_id: UUID, sources: Sequence[Source]) -> dict[str, str]:
    threads = session.execute(
        select(CaseLink.message_id, CaseLink.case_id).where(
            CaseLink.company_id == company_id, CaseLink.message_id.in_(_ids(sources, "message"))
        )
    ).all()
    files = session.execute(
        select(DocumentRow.id, DocumentRow.drive_file_id).where(
            DocumentRow.company_id == company_id,
            DocumentRow.id.in_(_ids(sources, "document")),
            DocumentRow.drive_file_id.is_not(None),
        )
    ).all()
    links = {f"message:{m}": f"/inbox?thread={c}" for m, c in threads}
    links |= {f"document:{d}": DRIVE_URL.format(f) for d, f in files}
    return links


def with_links(engine: Engine, company_id: UUID, sources: Sequence[Source]) -> tuple[Source, ...]:
    """The sources with `href` set where the server knows a place to open them."""
    if not sources:
        return ()
    with Session(engine) as session:
        links = _hrefs(session, company_id, sources)
    out = []
    for source in sources:
        href = source.ref if source.kind == "web" and source.ref.startswith("https://") else None
        out.append(source.model_copy(update={"href": links.get(f"{source.kind}:{source.ref}", href)}))
    return tuple(out)
