"""What a message adds to its chunk: an email's new part once, and a reply of Harjot's that only exists as a quote in a
later mail, marked as such. WhatsApp and forwarded mail are indexed as they are."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.models import Company, MessageChunk, MessageRow, OwnerAccount, RawEvent
from app.tools.message_rag.indexer import index_message
from app.tools.message_rag.lines import QUOTED_OWNER

pytestmark = pytest.mark.integration
START = datetime(2026, 9, 1, 9, tzinfo=UTC)
HARJOT = "harjot@hr.example"
QUOTE = "\n\nOp 1 sep. 2026 om 10:00 schreef Harjot <harjot@hr.example>:\n> Ik stuur morgen de loodgieter.\n"


@pytest.fixture
def settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"llm_model": "fake", "embedding_model": "fake"})


@pytest.fixture
def owner(migrated_engine: Engine, committed_company: Company) -> None:
    with Session(migrated_engine) as s, s.begin():
        s.add(
            OwnerAccount(
                company_id=committed_company.id, email=HARJOT, display_name="Harjot", whatsapp_e164="+31600000000"
            )
        )


def _mail(engine: Engine, cid: UUID, text: str, *, hours: int = 0, channel: Channel = Channel.gmail) -> UUID:
    with Session(engine) as s, s.begin():
        raw = RawEvent(company_id=cid, provider=channel, provider_msg_id=str(new_id()), payload={})
        s.add(raw)
        s.flush()
        msg = MessageRow(
            company_id=cid, raw_event_id=raw.id, channel=channel, provider_msg_id=raw.provider_msg_id,
            thread_ref="t1", sender_identity="anna@x.test", direction=Direction.inbound,
            sent_at=START + timedelta(hours=hours), text=text, meta={},
        )  # fmt: skip
        s.add(msg)
        s.flush()
        return msg.id


def _text(engine: Engine, cid: UUID) -> str:
    with Session(engine) as s:
        return "\n".join(c.text for c in s.scalars(select(MessageChunk).where(MessageChunk.company_id == cid)))


def test_email_chunk_holds_the_new_part_only(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid = committed_company.id
    text = "Het lekt nog steeds.\n\nOp 1 sep. 2026 om 09:00 schreef Anna <anna@x.test>:\n> Er lekt water."
    index_message(migrated_engine, settings, _mail(migrated_engine, cid, text))
    chunk = _text(migrated_engine, cid)
    assert "Het lekt nog steeds." in chunk
    assert "Er lekt water." not in chunk


def test_quoted_harjot_reply_is_indexed_once_and_marked(
    migrated_engine: Engine, settings: Settings, committed_company: Company, owner: None
) -> None:
    cid = committed_company.id
    for i, new in enumerate(["Dank u.", "Hij is niet gekomen."]):
        index_message(migrated_engine, settings, _mail(migrated_engine, cid, new + QUOTE, hours=i))
    chunk = _text(migrated_engine, cid)
    assert chunk.count("Ik stuur morgen de loodgieter.") == 1
    line = next(x for x in chunk.splitlines() if "loodgieter" in x)
    assert QUOTED_OWNER in line
    assert "| inbound]" not in line


def test_a_quote_of_someone_else_is_not_indexed(
    migrated_engine: Engine, settings: Settings, committed_company: Company, owner: None
) -> None:
    cid = committed_company.id
    text = "Ja.\n\nOp 1 sep. 2026 om 10:00 schreef Bram <bram@x.test>:\n> Geheim van Bram."
    index_message(migrated_engine, settings, _mail(migrated_engine, cid, text))
    assert "Geheim van Bram" not in _text(migrated_engine, cid)


def test_whatsapp_chunks_are_unchanged(
    migrated_engine: Engine, settings: Settings, committed_company: Company, owner: None
) -> None:
    cid = committed_company.id
    text = "Op 1 sep. 2026 om 10:00 schreef Harjot <harjot@hr.example>:\nzie hieronder"
    index_message(migrated_engine, settings, _mail(migrated_engine, cid, text, channel=Channel.whatsapp))
    assert "schreef Harjot" in _text(migrated_engine, cid)


def test_a_forwarded_mail_is_indexed_whole(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid = committed_company.id
    text = "---------- Forwarded message ---------\nVan: Bakker\nOnderwerp: Offerte\n\nKitrand vervangen: 480 euro."
    index_message(migrated_engine, settings, _mail(migrated_engine, cid, text))
    assert "480 euro" in _text(migrated_engine, cid)


def test_a_mail_that_is_only_a_quote_keeps_its_text(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid = committed_company.id
    text = "Op 1 sep. 2026 om 09:00 schreef Anna <anna@x.test>:\n> Er lekt water."
    index_message(migrated_engine, settings, _mail(migrated_engine, cid, text))
    assert "Er lekt water." in _text(migrated_engine, cid)
