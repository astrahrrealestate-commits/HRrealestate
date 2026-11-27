"""The owner's writing persona: a markdown file the proposer drafts in (one per company, editable from the dashboard).

The text is owner-authored but uploadable, so it reaches the model only inside a `<persona>` data block and can never
change the proposer's rules, recipients or approval step. A company with no persona gets the bundled mock, which is
stored on first use so its version is stable. Every edit bumps `version`; drafts record the version they used.
"""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contracts import ReplyDraftPayload, RequestContractorPayload
from app.core.errors import EstateOSError
from app.core.ids import new_id
from app.db.models import ActionRow, OwnerPersona
from app.llm.agents.proposer import MAX_PERSONA_CHARS, Persona

DEFAULT_PATH = Path(__file__).parent / "default_persona.md"
DEFAULT_NAME = "Harjot Singh"
CUSTOM_NAME = "Harjot (custom)"


class InvalidPersonaError(EstateOSError):
    """The uploaded or edited persona is empty or too long."""


def _default_content() -> str:
    return DEFAULT_PATH.read_text(encoding="utf-8")


def _row(session: Session, company_id: UUID, *, lock: bool = False) -> OwnerPersona:
    """The company's row; created from the bundled mock on first use (a concurrent first use inserts once)."""
    session.execute(
        insert(OwnerPersona)
        .values(
            id=new_id(),
            company_id=company_id,
            name=DEFAULT_NAME,
            filename=DEFAULT_PATH.name,
            content=_default_content(),
            is_default=True,
        )
        .on_conflict_do_nothing(index_elements=["company_id"])
    )
    query = select(OwnerPersona).where(OwnerPersona.company_id == company_id)
    return session.execute(query.with_for_update() if lock else query).scalar_one()


def get_persona_row(session: Session, company_id: UUID) -> OwnerPersona:
    """The company's persona row, created from the bundled mock on first use."""
    return _row(session, company_id)


def save_persona(
    session: Session, company_id: UUID, content: str, name: str | None = None, filename: str | None = None
) -> OwnerPersona:
    text = content.replace("\x00", "").strip()
    if not text:
        raise InvalidPersonaError("persona must not be empty")
    if len(text) > MAX_PERSONA_CHARS:
        raise InvalidPersonaError(f"persona must be at most {MAX_PERSONA_CHARS} characters")
    row = _row(session, company_id, lock=True)
    row.name = (name or "").strip()[:120] or (CUSTOM_NAME if row.is_default else row.name)
    row.content = text
    row.filename = (filename or "").strip()[:255] or row.filename
    row.is_default = False
    row.version += 1
    row.updated_at = datetime.now(UTC)
    session.flush()
    return row


def reset_persona(session: Session, company_id: UUID) -> OwnerPersona:
    row = _row(session, company_id, lock=True)
    row.content, row.name, row.filename = _default_content(), DEFAULT_NAME, DEFAULT_PATH.name
    row.is_default = True
    row.version += 1
    row.updated_at = datetime.now(UTC)
    session.flush()
    return row


def load_persona(engine: Engine, company_id: UUID) -> Persona:
    with Session(engine) as session, session.begin():
        row = _row(session, company_id)
        return Persona(row.name, row.version, row.content)


def stamp_persona(row: ActionRow, payload: object, persona: Persona | None) -> None:
    """Record the persona a tenant- or contractor-facing draft was written in (the dashboard shows it on the card)."""
    if persona is not None and isinstance(payload, ReplyDraftPayload | RequestContractorPayload):
        row.persona_name, row.persona_version = persona.name, persona.version
