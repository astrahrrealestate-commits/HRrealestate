"""GDPR erasure also removes the English copies of the erased person's messages (ADR 0011)."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.db.enums import PersonKind
from app.db.models import Company, MessageRow, Person, RawEvent
from app.db.models.translation import Translation
from app.pipeline.gdpr import erase_person
from app.translation.service import translate_cached

pytestmark = pytest.mark.integration

ERASED_TEXT = "Goedemorgen, mijn naam is Jan en ik woon op de tweede verdieping."
KEPT_TEXT = "Bedankt voor het snelle antwoord over de huur."


class Echo:
    engine = "fake"

    def translate(self, segments: list[str]) -> list[str]:
        return [f"EN({s})" for s in segments]


@pytest.fixture
def company(migrated_engine: Engine) -> Iterator[UUID]:
    with Session(migrated_engine) as s:
        c = Company(name="Erasure")
        s.add(c)
        s.commit()
        cid = c.id
    yield cid
    with Session(migrated_engine) as s:
        for model in (Translation, MessageRow, RawEvent, Person):
            s.query(model).filter(model.company_id == cid).delete(synchronize_session=False)
        s.query(Company).filter(Company.id == cid).delete()
        s.commit()


def test_erasing_a_person_deletes_the_translations_of_their_messages_only(
    migrated_engine: Engine, company: UUID
) -> None:
    with Session(migrated_engine) as s:
        person = Person(company_id=company, kind=PersonKind.tenant, display_name="Jan", valid_from=date(2026, 1, 1))
        s.add(person)
        s.flush()
        for n, (text, owner) in enumerate([(ERASED_TEXT, person.id), (KEPT_TEXT, None)]):
            raw = RawEvent(company_id=company, provider=Channel.gmail, provider_msg_id=f"p{n}", payload={})
            s.add(raw)
            s.flush()
            s.add(MessageRow(company_id=company, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id=f"p{n}",
                             thread_ref="t", sender_identity="x@y.test", direction=Direction.inbound,
                             sent_at=datetime(2026, 1, 1, tzinfo=UTC), text=text, person_id=owner))  # fmt: skip
        s.commit()
        person_id = person.id
    for text in (ERASED_TEXT, KEPT_TEXT):
        translate_cached(migrated_engine, Echo(), company, text)

    with Session(migrated_engine) as s, s.begin():
        erase_person(s, company, person_id)

    with Session(migrated_engine) as s:
        remaining = s.scalars(select(Translation.text_translated).where(Translation.company_id == company)).all()
    assert remaining == [f"EN({KEPT_TEXT})"]


def test_erasing_a_person_also_deletes_english_to_dutch_rows(migrated_engine: Engine, company: UUID) -> None:
    """An en->nl row is keyed by the English source, but its Dutch output may be the message sent to the erased
    person, so erasure drops the whole en->nl cache for the company (it refills on the next translate)."""
    with Session(migrated_engine) as s:
        person = Person(company_id=company, kind=PersonKind.tenant, display_name="Jan", valid_from=date(2026, 1, 1))
        s.add(person)
        s.flush()
        raw = RawEvent(company_id=company, provider=Channel.gmail, provider_msg_id="pd", payload={})
        s.add(raw)
        s.flush()
        s.add(MessageRow(company_id=company, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id="pd",
                         thread_ref="t", sender_identity="x@y.test", direction=Direction.outbound,
                         sent_at=datetime(2026, 1, 1, tzinfo=UTC), text="EN(We will send the plumber today.)",
                         person_id=person.id))  # fmt: skip
        s.commit()
        person_id = person.id
    translate_cached(migrated_engine, Echo(), company, "We will send the plumber today.", target="nl")
    translate_cached(migrated_engine, Echo(), company, KEPT_TEXT)

    with Session(migrated_engine) as s, s.begin():
        erase_person(s, company, person_id)

    with Session(migrated_engine) as s:
        remaining = s.scalars(select(Translation.text_translated).where(Translation.company_id == company)).all()
    assert remaining == [f"EN({KEPT_TEXT})"]
