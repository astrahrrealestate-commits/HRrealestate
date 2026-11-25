"""Person memory (M13 T7): refresh what EstateOS remembers about one person from their own mail, only when stale."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Engine, select, tuple_
from sqlalchemy.orm import Session

from app.context.message_origin import is_history, is_owner_authored
from app.context.person_profile import get_or_create_profile
from app.contracts import Direction
from app.contracts.person_memory import PersonMemory
from app.core.errors import EstateOSError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import Case, ChannelIdentity, MessageRow, PersonProfile
from app.db.models.ingestion import not_chat_only
from app.llm.agents.person_memory import PERSON_MEMORY, person_memory_prompt
from app.llm.calls import CallContext, run_agent
from app.pipeline.conversation import line_of, load_people, other_tenants, quoted_lines

log = get_logger(__name__)
WINDOW = timedelta(days=90)
MAX_MESSAGES = 40
MAX_CASES = 10


def _profile(session: Session, company_id: UUID, person_id: UUID) -> PersonProfile | None:
    return session.scalar(
        select(PersonProfile).where(PersonProfile.company_id == company_id, PersonProfile.person_id == person_id)
    )


def stored_memory(session: Session, company_id: UUID, person_id: UUID) -> PersonMemory | None:
    profile = _profile(session, company_id, person_id)
    if profile is None or profile.memory is None:
        return None
    try:
        return PersonMemory.model_validate(profile.memory)
    except ValidationError:  # written by another version of the contract: the next refresh replaces it
        return None


def _rows(session: Session, company_id: UUID, person_id: UUID, since: datetime) -> list[MessageRow]:
    """The person's mail and what was sent in those threads, newest first; nothing from or to another tenant."""
    base = (MessageRow.company_id == company_id, MessageRow.sent_at >= since, not_chat_only())
    newest = MessageRow.sent_at.desc()
    own = list(
        session.scalars(
            select(MessageRow).where(*base, MessageRow.person_id == person_id).order_by(newest).limit(MAX_MESSAGES)
        )
    )
    threads = {(r.channel, r.thread_ref) for r in own if r.thread_ref}
    sent = list(
        session.scalars(
            select(MessageRow)
            .where(
                *base,
                MessageRow.direction == Direction.outbound,
                tuple_(MessageRow.channel, MessageRow.thread_ref).in_(threads),
            )
            .order_by(newest)
            .limit(MAX_MESSAGES)
        )
    ) if threads else []  # fmt: skip
    return sorted([*own, *sent], key=lambda r: r.sent_at, reverse=True)[:MAX_MESSAGES]


def _prompt(session: Session, company_id: UUID, person_id: UUID, now: datetime) -> tuple[str, tuple[UUID, ...]] | None:
    rows = _rows(session, company_id, person_id, now - WINDOW)
    if not rows:
        return None
    people = load_people(session, company_id, rows)
    identities = frozenset(
        i.lower()
        for i in session.scalars(
            select(ChannelIdentity.identity).where(
                ChannelIdentity.company_id == company_id, ChannelIdentity.person_id == person_id
            )
        )
    )
    allowed = frozenset({person_id})
    kept = [r for r in rows if not other_tenants(r, people, allowed, identities)]
    lines = [line_of(r, people) for r in kept]
    own = [r for r in kept if r.person_id == person_id and not is_owner_authored(r)]
    lines += quoted_lines(own, people, frozenset(), [line.text for line in lines])
    lines.sort(key=lambda line: line.sent_at, reverse=True)
    cases = session.scalars(
        select(Case)
        .where(Case.company_id == company_id, Case.primary_person_id == person_id, Case.summary != "")
        .order_by(Case.opened_at.desc())
        .limit(MAX_CASES)
    ).all()
    prompt = person_memory_prompt(
        [line.render() for line in lines], [f"{c.category.value}, {c.state.value}: {c.summary}" for c in cases]
    )
    return prompt, tuple(r.id for r in kept)


def refresh_person_memory(
    engine: Engine, settings: Settings, company_id: UUID, person_id: UUID, now: datetime | None = None
) -> PersonMemory | None:
    """The person's memory, rewritten first when they have mail newer than it was written from."""
    with Session(engine) as session:
        profile = _profile(session, company_id, person_id)
        source = profile.source_max_message_at if profile else None
        if profile is None or source is None:
            return None
        if profile.memory_at is not None and profile.memory_at >= source:
            return stored_memory(session, company_id, person_id)
        built = _prompt(session, company_id, person_id, now or datetime.now(UTC))
    if built is None:
        return None
    ctx = CallContext(company_id, "person_memory", message_ids=built[1])
    memory = run_agent(engine, settings, PERSON_MEMORY, built[0], ctx).output
    with Session(engine) as session, session.begin():
        fresh = get_or_create_profile(session, company_id, person_id)
        fresh.memory, fresh.memory_at = memory.model_dump(mode="json"), source
    return memory


def refresh_for_message(engine: Engine, settings: Settings, message_id: UUID) -> None:
    """Pipeline step, live mail only. Memory helps a draft but never blocks one: any failure keeps the old memory."""
    with Session(engine) as session:
        msg = session.get(MessageRow, message_id)
        if msg is None or msg.person_id is None or is_history(msg) or is_owner_authored(msg):
            return
        company_id, person_id = msg.company_id, msg.person_id
    try:
        refresh_person_memory(engine, settings, company_id, person_id)
    except EstateOSError as exc:  # model refused, invalid output, budget stop
        log.warning("person_memory.refresh_failed", message_id=str(message_id), error_type=type(exc).__name__)
