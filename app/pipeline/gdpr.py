"""GDPR Tenant Erasure cascade (spec §6.3, §8, Task C12).

Cascades tenant erasure across:
1. `person_profiles` (deleted).
2. `memory_items` referencing person_id or their message ids via `source_refs` (retired).
3. `messages` (text and sender_identity redacted).
4. `channel_identities` (identity scrubbed, valid_to set).
5. `people` (display_name set to [Erased Person], valid_to set).
6. `translations` (English copies of the person's message texts, found by text hash, deleted before the redaction).
7. BRIXX mirror: a person with a numeric `brixx_ref` gets a `brixx_erased_refs` tombstone and their mirror rows
   (`brixx.prg_relatie`, `brixx.zprg_relatie`) are deleted, so a re-sync never resurrects them.
Strictly company-scoped (invariant 4).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.texthash import source_hash
from app.db.brixx_erasure import purge_brixx_relatie, relatie_id
from app.db.enums import MemoryScope, MemoryStatus
from app.db.models import (
    ChannelIdentity,
    MemoryItem,
    MessageChunk,
    MessageIndexState,
    MessageRow,
    Person,
    PersonProfile,
    Translation,
)

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


def _delete_translations(session: Session, company_id: UUID, msg_ids: list[UUID]) -> None:
    texts = session.execute(
        select(MessageRow.text).where(MessageRow.company_id == company_id, MessageRow.id.in_(msg_ids))
    ).scalars()
    hashes = {source_hash(t) for t in texts if t and t.strip()}
    if hashes:
        session.execute(
            delete(Translation).where(Translation.company_id == company_id, Translation.source_hash.in_(hashes))
        )


def erase_person(
    session: Session,
    company_id: UUID,
    person_id: UUID,
) -> ErasureReport:
    """Cascade GDPR erasure for a person and all derived memory/message records."""
    # 1. Identify all messages associated with the person
    msg_ids = list(
        session.scalars(
            select(MessageRow.id).where(
                MessageRow.company_id == company_id,
                MessageRow.person_id == person_id,
            )
        ).all()
    )
    msg_id_strs = {str(mid) for mid in msg_ids}

    # 2. Redact message texts and identities (their cached English copies go first: they are found by the text)
    messages_redacted = 0
    if msg_ids:
        _delete_translations(session, company_id, msg_ids)
        res = session.execute(
            update(MessageRow)
            .where(
                MessageRow.company_id == company_id,
                MessageRow.person_id == person_id,
            )
            .values(
                text="[Content erased per GDPR request]",
                sender_identity=f"erased-{person_id}@gdpr.estateos",
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
    for ci in cis:
        ci.identity = f"erased-{ci.id}@gdpr.local"
        ci.valid_to = today
    identities_cleared = len(cis)

    # 5b. Remove message_chunks and indexing state for this person
    session.execute(
        delete(MessageChunk).where(
            MessageChunk.company_id == company_id,
            or_(
                MessageChunk.person_id == person_id,
                MessageChunk.participant_ids.contains([person_id]),
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
    )
    log.info(
        "gdpr.person_erased",
        company_id=str(company_id),
        person_id=str(person_id),
        memories_retired=memories_retired,
        messages_redacted=messages_redacted,
        brixx_rows_purged=brixx_rows_purged,
    )
    return report
