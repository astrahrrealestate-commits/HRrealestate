"""The dossier of one mail (M13 T6): everything a colleague would read before answering it.

Same person, same case, company documents marked as reference. Never another tenant's mail or papers: messages go
through `conversation.other_tenants`, documents through the case's own links. `quote` and `research` are filled by the
steps that run before the draft (T8).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.context.message_origin import full_text, is_owner_authored
from app.contracts import Direction
from app.contracts.person_memory import PersonMemory
from app.contracts.research import Finding
from app.core.errors import NotFoundError
from app.db.enums import DocLinkKind, ExtractionStatus, PersonKind
from app.db.models import AttachmentRow, Case, CaseLink, ChannelIdentity, MessageRow, Person, UnderstandingRow
from app.db.models.ingestion import not_chat_only
from app.llm.agents.doc_qa import Passage
from app.llm.embeddings import TextEmbedder
from app.pipeline import case_repo
from app.pipeline.conversation import (
    People,
    ThreadLine,
    line_of,
    load_people,
    new_part,
    other_tenants,
    quoted_lines,
    recipients,
)
from app.pipeline.document_policy import FileMeta, looks_like_id
from app.pipeline.document_qa import case_scope, strip_risky
from app.pipeline.document_search import DocFilter
from app.pipeline.dossier_facts import open_waits, owner_rules, unread_attachments
from app.pipeline.dossier_history import older_mail, similar_conversations
from app.pipeline.draft_research import stored_findings
from app.pipeline.injection_scan import scan
from app.pipeline.person_memory import stored_memory
from app.pipeline.quote_text import quote_review_text
from app.pipeline.rag import retrieve_cheap
from app.pipeline.tenancy import owns_tenancy, tenancy_facts

MAX_THREAD = 60
MAX_SENDER_HISTORY = 15
MAX_ATTACHMENTS = 12
MAX_PASSAGES = 4


@dataclass(frozen=True)
class AttachmentText:
    attachment_id: UUID
    filename: str
    text: str
    flagged: bool
    current: bool  # attached to the mail being answered


@dataclass(frozen=True)
class Dossier:
    current: ThreadLine  # the mail being answered, whole, quoted part included
    thread: tuple[ThreadLine, ...]  # case and thread, both directions, oldest first, each its new part only
    sender_history: tuple[ThreadLine, ...]  # same person, other cases, newest first
    attachments: tuple[AttachmentText, ...]  # the current mail's first
    documents: tuple[Passage, ...]
    references: tuple[Passage, ...]
    memory: PersonMemory | None
    owner_rules: tuple[str, ...]
    waiting: tuple[str, ...]
    quote: str | None = None
    research: tuple[Finding, ...] = ()
    tenancy: tuple[str, ...] = ()  # lease, rent, arrears, work order (directory and BRIXX ledger)
    older_mail: tuple[ThreadLine, ...] = ()  # the person's older mail that matches this one
    similar_conversations: tuple[ThreadLine, ...] = ()  # redacted outbound precedents from similar company cases
    extra_message_ids: tuple[UUID, ...] = ()  # messages behind `older_mail` (call log, erasure)
    unread_attachments: tuple[str, ...] = ()  # file names of the current mail's attachments that could not be read


@dataclass(frozen=True)
class _Scope:
    msg: MessageRow
    case: Case | None
    identities: frozenset[str]
    allowed: frozenset[UUID]  # tenants whose mail may be shown
    trusted: bool  # the case's main person or a directory contractor: sees the case's mail, not only their own
    allowed_identities: frozenset[str]  # addresses and numbers of the allowed people, lower-case
    contractor: bool


def _scope(session: Session, msg: MessageRow) -> _Scope:
    """A tenant sees their own mail. A contractor also sees the report of the case's main person, which is what they
    are asked to work on. Anyone else sees only their own words."""
    case_id = case_repo.case_of_message(session, msg.company_id, msg.id)
    case = case_repo.get_case(session, msg.company_id, case_id) if case_id else None
    person = session.get(Person, msg.person_id) if msg.person_id else None
    allowed = {msg.person_id} if msg.person_id else set()
    contractor = bool(person and person.company_id == msg.company_id and person.kind is PersonKind.contractor)
    if contractor and case:
        allowed |= {case.primary_person_id} if case.primary_person_id else set()
    main = case is not None and msg.person_id is not None and msg.person_id == case.primary_person_id
    own = frozenset({msg.sender_identity.lower()})
    known = session.scalars(
        select(ChannelIdentity.identity).where(
            ChannelIdentity.company_id == msg.company_id, ChannelIdentity.person_id.in_(allowed)
        )
    )
    reach = own | {i.strip().lower() for i in known}
    return _Scope(msg, case, own, frozenset(allowed), main or contractor, reach, contractor)


def _is_own(row: MessageRow, scope: _Scope) -> bool:
    if row.direction is not Direction.inbound or is_owner_authored(row):
        return False
    same_person = scope.msg.person_id is not None and row.person_id == scope.msg.person_id
    return same_person or row.sender_identity.lower() in scope.identities


def _conversation(session: Session, scope: _Scope) -> list[tuple[MessageRow, UUID | None]]:
    """Rows of this case, and unlinked rows of the same thread, newest first, with the case each is linked to."""
    msg, case_id = scope.msg, scope.case.id if scope.case else None
    link = and_(CaseLink.company_id == msg.company_id, CaseLink.message_id == MessageRow.id)
    same_thread = and_(MessageRow.channel == msg.channel, MessageRow.thread_ref == msg.thread_ref)
    if msg.thread_ref is None:
        same_thread = MessageRow.id == msg.id
    rows = session.execute(
        select(MessageRow, CaseLink.case_id)
        .outerjoin(CaseLink, link)
        .where(
            MessageRow.company_id == msg.company_id,
            MessageRow.id != msg.id,
            not_chat_only(),
            or_(CaseLink.case_id == case_id, same_thread) if case_id else same_thread,
        )
        .order_by(MessageRow.sent_at.desc())
        .limit(MAX_THREAD)
    ).all()
    return [(row, linked) for row, linked in rows]


def _ours(row: MessageRow) -> bool:
    return row.direction is Direction.outbound or is_owner_authored(row)


def _sent_to(row: MessageRow, identities: frozenset[str]) -> bool:
    return _ours(row) and bool(recipients(row) & identities)


def _keep(row: MessageRow, linked: UUID | None, scope: _Scope, people: People) -> bool:
    """Allowlist. Own words always; anything sent to the person or an allowed person; for the case's main person or
    a contractor also the case's other mail (Harjot's own forwarded copies only where they name an allowed addressee)
    unless it involves a tenant outside the case."""
    if _is_own(row, scope) or _sent_to(row, scope.allowed_identities):
        return True
    if not scope.trusted or is_owner_authored(row) or linked is None or linked != (scope.case and scope.case.id):
        return False
    return not other_tenants(row, people, scope.allowed, scope.identities)


def _thread_rows(session: Session, scope: _Scope) -> tuple[list[MessageRow], People]:
    found = list({row.id: (row, linked) for row, linked in _conversation(session, scope)}.values())
    people = load_people(session, scope.msg.company_id, [scope.msg, *(row for row, _ in found)])
    kept = [row for row, linked in found if _keep(row, linked, scope, people)]
    return sorted(kept, key=lambda r: r.sent_at), people


def _thread(rows: Sequence[MessageRow], people: People, scope: _Scope, current: str) -> tuple[ThreadLine, ...]:
    lines = [line_of(row, people) for row in rows]
    own = [row for row in rows if _is_own(row, scope)]
    lines += quoted_lines(own, people, scope.identities, [current, *(line.text for line in lines)])
    return tuple(sorted(lines, key=lambda line: line.sent_at))


def _sender_history(session: Session, scope: _Scope, people: People, shown: set[UUID]) -> tuple[ThreadLine, ...]:
    msg = scope.msg
    if msg.person_id is None:
        return ()
    rows = session.scalars(
        select(MessageRow)
        .where(
            MessageRow.company_id == msg.company_id,
            MessageRow.person_id == msg.person_id,
            MessageRow.direction == Direction.inbound,
            MessageRow.id.not_in({msg.id, *shown}),
            not_chat_only(),
        )
        .order_by(MessageRow.sent_at.desc())
        .limit(MAX_SENDER_HISTORY)
    ).all()
    return tuple(line_of(row, people) for row in rows if not is_owner_authored(row))


def _attachments(
    session: Session, msg: MessageRow, message_ids: Sequence[UUID], photos_only: Sequence[UUID] = ()
) -> tuple[AttachmentText, ...]:
    """Text of the case's attachments, the current mail's first. From `photos_only` messages only images: a contractor
    sees the photos of a defect, never the tenant's papers."""
    rows = session.execute(
        select(AttachmentRow, MessageRow.sent_at)
        .join(MessageRow, MessageRow.id == AttachmentRow.message_id)
        .where(
            AttachmentRow.company_id == msg.company_id,
            AttachmentRow.message_id.in_([msg.id, *message_ids]),
            AttachmentRow.extraction_status == ExtractionStatus.done,
            AttachmentRow.extracted_text.is_not(None),
        )
        .order_by((AttachmentRow.message_id == msg.id).desc(), MessageRow.sent_at.desc())
        .limit(MAX_ATTACHMENTS)
    ).all()
    return tuple(
        AttachmentText(a.id, a.filename or "unnamed", text, scan(text) is not None, a.message_id == msg.id)
        for a, _ in rows
        if (text := (a.extracted_text or "").strip())
        and not looks_like_id(FileMeta(a.filename, a.mime_type, a.size_bytes, msg.sent_at))
        and (a.message_id not in photos_only or a.mime_type.startswith("image/"))
    )


def _not_theirs(rows: Sequence[MessageRow], scope: _Scope) -> list[UUID]:
    """For a contractor: the case's messages that are neither theirs nor sent to them."""
    if not scope.contractor:
        return []
    return [r.id for r in rows if not _is_own(r, scope) and not _sent_to(r, scope.identities)]


def _case_ids(scope: _Scope) -> tuple[UUID | None, ...]:
    return (scope.case.id, scope.case.unit_id) if scope.case else ()


def _tenancy(session: Session, scope: _Scope) -> tuple[str, ...]:
    """Own lease and rent for the main person or a tenant on a lease; a contractor gets the case's address only."""
    if not scope.trusted:
        return ()
    cid, pid = scope.msg.company_id, scope.msg.person_id
    full = not scope.contractor and owns_tenancy(session, cid, pid, scope.case)
    return tenancy_facts(session, cid, pid, scope.case, full=full, today=scope.msg.sent_at.date())


def _document_links(session: Session, scope: _Scope) -> tuple[tuple[DocLinkKind, UUID], ...]:
    """The case's own links for its main person. Anyone else (a contractor, a co-tenant) gets only papers filed under
    their own name: the case and lease links hold the main person's papers."""
    msg, case = scope.msg, scope.case
    if case and case.primary_person_id is not None and msg.person_id == case.primary_person_id:
        return case_scope(session, msg.company_id, case.id)
    return ((DocLinkKind.person, msg.person_id),) if msg.person_id else ()


def _passages(
    session: Session, company_id: UUID, query: str, flt: DocFilter, embedder: TextEmbedder | None
) -> tuple[Passage, ...]:
    found = retrieve_cheap(session, company_id, query, replace(flt, readable_only=True), embedder, MAX_PASSAGES)
    return tuple(replace(p, text=strip_risky(p.text)) for p in found)


def _research(session: Session, company_id: UUID, message_id: UUID) -> tuple[Finding, ...]:
    """What draft research (T8) found for this mail, if it ran."""
    stored = session.scalar(
        select(UnderstandingRow.research).where(
            UnderstandingRow.company_id == company_id, UnderstandingRow.message_id == message_id
        )
    )
    return stored_findings(stored)


def build_dossier(session: Session, company_id: UUID, message_id: UUID, embedder: TextEmbedder | None) -> Dossier:
    msg = session.get(MessageRow, message_id)
    if msg is None or msg.company_id != company_id:
        raise NotFoundError(f"message {message_id} not found for company {company_id}")
    scope = _scope(session, msg)
    rows, people = _thread_rows(session, scope)
    current = line_of(msg, people, full_text(msg))
    shown = {row.id for row in rows}
    query = f"{(msg.meta or {}).get('subject') or ''}\n{new_part(msg)}".strip()
    links = _document_links(session, scope)
    older, older_ids = (
        older_mail(session, company_id, msg.person_id, query, embedder, {msg.id, *shown})
        if msg.person_id and embedder is not None else ((), ())
    )  # fmt: skip
    precedents = (
        similar_conversations(session, company_id, msg.person_id, query, embedder, {msg.id, *shown, *older_ids})
        if scope.trusted and embedder is not None else ()
    )  # fmt: skip
    return Dossier(
        current=current,
        thread=_thread(rows, people, scope, current.text),
        sender_history=_sender_history(session, scope, people, shown),
        attachments=_attachments(session, msg, [row.id for row in rows], _not_theirs(rows, scope)),
        documents=_passages(session, company_id, query, DocFilter(any_link=links), embedder) if links else (),
        references=_passages(session, company_id, query, DocFilter(reference_only=True), embedder),
        memory=stored_memory(session, company_id, msg.person_id) if msg.person_id else None,
        owner_rules=owner_rules(session, company_id, [msg.person_id, *_case_ids(scope)]),
        waiting=open_waits(session, company_id, scope.case.id if scope.case else None),
        quote=quote_review_text(session, company_id, [msg.id, *(row.id for row in rows if _is_own(row, scope))]),
        research=_research(session, company_id, msg.id),
        tenancy=_tenancy(session, scope),
        older_mail=older,
        similar_conversations=precedents,
        extra_message_ids=older_ids,
        unread_attachments=unread_attachments(session, msg),
    )  # fmt: skip
