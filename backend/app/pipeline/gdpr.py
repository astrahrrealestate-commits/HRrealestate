"""GDPR Tenant Erasure cascade (spec §6.3, §8, Task C12).

Cascades tenant erasure across:
1. `person_profiles` (deleted).
2. `memory_items` referencing person_id or their message ids via `source_refs` (retired).
3. `messages` (text and sender_identity redacted).
4. `channel_identities` (identity scrubbed, valid_to set).
5. `people` (display_name set to [Erased Person], valid_to set).
6. `translations` (the English copies of the person's message texts, found by text hash, plus every
   English-to-Dutch row of the company, deleted before the redaction).
7. `ticket_edits` of the person's cases (deleted: the owner's edits can quote the person's messages or drafts to them).
8. `chat_reads` of the person's WhatsApp chats (deleted, found by their WhatsApp identities).
11. BRIXX library documents linked to the person (`gdpr_documents`; chunks and links cascade).
12. What was derived from their messages (`gdpr_derived`): understandings' research and free text, attachment text and
    the documents read from it, and Astra's turns citing one of their messages.
10. `model_calls` whose prompt or output carried the person's words (input, output and error blanked; gdpr_calls).
9. BRIXX mirror: a person with a numeric `brixx_ref` gets a `brixx_erased_refs` tombstone and their mirror rows
   (`brixx.prg_relatie`, `brixx.zprg_relatie`) are deleted, so a re-sync never resurrects them.
Strictly company-scoped (invariant 4).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, Text, and_, cast, delete, or_, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.core.logging import get_logger
from app.core.texthash import source_hash
from app.db.brixx_erasure import purge_brixx_relatie, relatie_id
from app.db.enums import MemoryScope, MemoryStatus, PipelineStatus
from app.db.models import (
    Case,
    ChannelIdentity,
    ChatRead,
    MemoryItem,
    MessageChunk,
    MessageIndexState,
    MessageRow,
    Person,
    PersonProfile,
    TicketEdit,
    Translation,
)
from app.pipeline.gdpr_calls import erase_model_calls
from app.pipeline.gdpr_derived import erase_derived
from app.pipeline.gdpr_documents import erase_brixx_documents

log = get_logger(__name__)


@dataclass(frozen=True)
class ErasureReport:
    person_id: UUID
    company_id: UUID
    profile_deleted: bool
    memories_retired: int
    messages_redacted: int
    identities_cleared: int
    person_anonymized: bool
    brixx_rows_purged: int
    calls_blanked: int = 0
    turns_blanked: int = 0


def _delete_translations(session: Session, company_id: UUID, msg_ids: list[UUID]) -> None:
    """Dutch-to-English rows are keyed by the person's own message text, so the hash finds them. An
    English-to-Dutch row is keyed by the owner's English source while its Dutch output may be the message that was
    sent to the person, so the whole en->nl cache goes with every erasure (it refills on the next translate)."""
    texts = session.execute(
        select(MessageRow.text).where(MessageRow.company_id == company_id, MessageRow.id.in_(msg_ids))
    ).scalars()
    hashes = {source_hash(t) for t in texts if t and t.strip()}
    clauses = [Translation.target_lang == "nl"]
    if hashes:
        clauses.append(Translation.source_hash.in_(hashes))
    session.execute(delete(Translation).where(Translation.company_id == company_id, or_(*clauses)))


def _delete_ticket_edits(session: Session, company_id: UUID, person_id: UUID) -> None:
    case_ids = select(Case.id).where(Case.company_id == company_id, Case.primary_person_id == person_id)
    session.execute(delete(TicketEdit).where(TicketEdit.company_id == company_id, TicketEdit.case_id.in_(case_ids)))


def _messages_of(company_id: UUID, person_id: UUID) -> ColumnElement[bool]:
    """The person's messages. Chats-only WhatsApp rows (ADR 0015) never got a person, so they are found by the
    person's WhatsApp numbers."""
    numbers = select(ChannelIdentity.identity).where(
        ChannelIdentity.company_id == company_id,
        ChannelIdentity.person_id == person_id,
        ChannelIdentity.channel == Channel.whatsapp,
    )
    chat_only = and_(
        MessageRow.channel == Channel.whatsapp,
        MessageRow.pipeline_status == PipelineStatus.skipped,
        MessageRow.thread_ref.in_(numbers),
    )
    return and_(MessageRow.company_id == company_id, or_(MessageRow.person_id == person_id, chat_only))


# Message metadata that copies the body or names its sender.
_COPIED_META = ("body_html", "full_text", "from", "from_name", "header_from", "forwarded_by", "reattributed_from")


def erase_person(
    session: Session,
    company_id: UUID,
    person_id: UUID,
) -> ErasureReport:
    """Cascade GDPR erasure for a person and all derived memory/message records."""
    # 1. Identify all messages associated with the person
    msg_ids = list(session.scalars(select(MessageRow.id).where(_messages_of(company_id, person_id))).all())
    msg_id_strs = {str(mid) for mid in msg_ids}

    _delete_ticket_edits(session, company_id, person_id)
    calls_blanked = erase_model_calls(session, company_id, person_id, msg_ids)  # needs the text: before redaction
    erase_brixx_documents(session, company_id, person_id)  # their BRIXX papers leave the document library (M13)
    turns_blanked = erase_derived(session, company_id, msg_ids)  # understandings, attachment text, Astra turns

    # 2. Redact message texts and identities (their cached English copies go first: they are found by the text)
    messages_redacted = 0
    if msg_ids:
        _delete_translations(session, company_id, msg_ids)
        res = session.execute(
            update(MessageRow)
            .where(_messages_of(company_id, person_id))
            .values(
                text="[Content erased per GDPR request]",
                sender_identity=f"erased-{person_id}@gdpr.estateos",
                meta=MessageRow.meta.op("-")(cast(list(_COPIED_META), ARRAY(Text))),
            )
        )
        messages_redacted = int(res.rowcount)  # type: ignore[attr-defined]

    # 3. Delete person profile
    prof = session.scalar(
        select(PersonProfile).where(
            PersonProfile.company_id == company_id,
            PersonProfile.person_id == person_id,
        )
    )
    profile_deleted = False
    if prof is not None:
        session.delete(prof)
        profile_deleted = True

    # 4. Retire memory items referencing person_id or their messages via source_refs
    mems = list(
        session.scalars(
            select(MemoryItem).where(
                MemoryItem.company_id == company_id,
                MemoryItem.status != MemoryStatus.retired,
            )
        ).all()
    )
    memories_retired = 0
    now = datetime.now(tz=UTC)
    for m in mems:
        should_retire = False
        if m.scope == MemoryScope.person and m.scope_id == person_id:
            should_retire = True
        elif m.source_refs:
            for ref in m.source_refs:
                if isinstance(ref, dict):
                    if ref.get("person_id") == str(person_id):
                        should_retire = True
                        break
                    if ref.get("message_id") in msg_id_strs:
                        should_retire = True
                        break
        if should_retire:
            m.status = MemoryStatus.retired
            m.updated_at = now
            memories_retired += 1

    # 5. Scrub channel identities
    cis = list(
        session.scalars(
            select(ChannelIdentity).where(
                ChannelIdentity.company_id == company_id,
                ChannelIdentity.person_id == person_id,
            )
        ).all()
    )
    today = datetime.now(tz=UTC).date()
    chat_keys = [ci.identity for ci in cis if ci.channel == Channel.whatsapp]
    for ci in cis:
        ci.identity = f"erased-{ci.id}@gdpr.local"
        ci.valid_to = today
    identities_cleared = len(cis)
    if chat_keys:  # the read markers are keyed by the number: with the number gone they would only keep a trace
        session.execute(delete(ChatRead).where(ChatRead.company_id == company_id, ChatRead.chat_key.in_(chat_keys)))

    # 5b. Remove message_chunks and indexing state for this person
    session.execute(
        delete(MessageChunk).where(
            MessageChunk.company_id == company_id,
            or_(
                MessageChunk.person_id == person_id,
                MessageChunk.participant_ids.contains([person_id]),
                MessageChunk.message_ids.overlap(msg_ids),  # a chunk filed under someone else can hold their words
            ),
        )
    )
    if msg_ids:
        session.execute(
            delete(MessageIndexState).where(
                MessageIndexState.company_id == company_id,
                MessageIndexState.message_id.in_(msg_ids),
            )
        )

    # 6. Anonymize person directory entry
    person = session.scalar(
        select(Person).where(
            Person.company_id == company_id,
            Person.id == person_id,
        )
    )
    person_anonymized = False
    brixx_rows_purged = 0
    if person is not None:
        relatie = relatie_id(person.brixx_ref)
        if relatie is not None:
            brixx_rows_purged = purge_brixx_relatie(session, company_id, relatie)
        person.display_name = "[Erased Person]"
        person.trade = None
        person.brixx_ref = None
        person.valid_to = today
        person_anonymized = True

    session.flush()

    report = ErasureReport(
        person_id=person_id,
        company_id=company_id,
        profile_deleted=profile_deleted,
        memories_retired=memories_retired,
        messages_redacted=messages_redacted,
        identities_cleared=identities_cleared,
        person_anonymized=person_anonymized,
        brixx_rows_purged=brixx_rows_purged,
        calls_blanked=calls_blanked,
        turns_blanked=turns_blanked,
    )
    log.info(
        "gdpr.person_erased",
        company_id=str(company_id),
        person_id=str(person_id),
        memories_retired=memories_retired,
        messages_redacted=messages_redacted,
        brixx_rows_purged=brixx_rows_purged,
        calls_blanked=calls_blanked,
        turns_blanked=turns_blanked,
    )
    return report
