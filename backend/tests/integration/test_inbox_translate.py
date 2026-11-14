"""POST /api/inbox/translate and the translations the inbox threads carry (ADR 0011): local model faked."""

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal
from app.core.errors import TranslationUnavailableError
from app.core.settings import Settings
from app.db.models import (
    ActionRevision,
    ActionRow,
    Approval,
    Case,
    CaseEvent,
    CaseLink,
    Company,
    MessageRow,
    OwnerFeed,
    RawEvent,
    Send,
    TaskRow,
    UnderstandingRow,
)  # fmt: skip
from app.db.models.translation import Translation
from app.main import create_app
from tests.api_auth import as_owner
from tests.integration.test_inbox_maintenance_approve import FakeClient, _seed

pytestmark = pytest.mark.integration

TENANT_NL = "Goedemorgen, er is een lekkage in de keuken. Kunt u iemand sturen?"
DRAFT_NL = "Beste Jan, bedankt voor uw bericht. Wij sturen vandaag een loodgieter."


class FakeTranslator:
    engine = "fake-nl-en"

    def __init__(self) -> None:
        self.segments: list[str] = []

    def translate(self, segments: list[str]) -> list[str]:
        self.segments.extend(segments)
        return [f"EN[{s}]" for s in segments]


class BrokenTranslator:
    engine = "broken"

    def translate(self, segments: list[str]) -> list[str]:
        raise TranslationUnavailableError("translation model not found")


@dataclass
class World:
    client: TestClient
    engine: Engine
    company_id: UUID
    translator: FakeTranslator


def _world(engine: Engine, pg_url: str, translator: FakeTranslator | BrokenTranslator) -> Iterator[World]:
    with Session(engine) as s:
        company = Company(name="Translate")
        s.add(company)
        s.flush()
        _, action_id, _ = _seed(s, company, suspicious=False)
        s.scalars(select(MessageRow).where(MessageRow.company_id == company.id)).one().text = TENANT_NL
        action = s.get(ActionRow, action_id)
        assert action is not None
        action.payload = {**action.payload, "body_variants": [DRAFT_NL, "Second draft"]}
        s.commit()
        settings = Settings(database_url=pg_url, env="test", _env_file=None)  # type: ignore[call-arg]
        owner = Principal(company_id=company.id, owner_id=uuid4(), email="harjot@example.test")
        app = create_app(
            settings, engine=engine, workflow_client=FakeClient(), translator=translator, translator_en_nl=translator
        )
        with TestClient(as_owner(app, owner)) as client:
            yield World(
                client, engine, company.id, translator if isinstance(translator, FakeTranslator) else FakeTranslator()
            )
        for model in (
            Translation, OwnerFeed, ActionRevision, UnderstandingRow, CaseLink, MessageRow, RawEvent, Approval, Send,
            TaskRow, ActionRow, CaseEvent, Case,
        ):  # fmt: skip
            s.query(model).filter(model.company_id == company.id).delete(synchronize_session=False)
        s.query(Company).filter(Company.id == company.id).delete()
        s.commit()


@pytest.fixture
def world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    yield from _world(migrated_engine, pg_url, FakeTranslator())


@pytest.fixture
def broken_world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    yield from _world(migrated_engine, pg_url, BrokenTranslator())


def test_translate_returns_english_then_serves_it_from_the_cache(world: World) -> None:
    first = world.client.post("/api/inbox/translate", json={"text": TENANT_NL}).json()
    assert first["language"] == "nl"
    assert first["cached"] is False
    assert first["text"].startswith("EN[Goedemorgen")
    again = world.client.post("/api/inbox/translate", json={"text": TENANT_NL}).json()
    assert again["cached"] is True
    assert again["text"] == first["text"]
    assert len(world.translator.segments) == 2  # two sentences, translated once


def test_english_text_comes_back_without_a_translation(world: World) -> None:
    body = world.client.post("/api/inbox/translate", json={"text": "Thanks, that works for me."}).json()
    assert body == {"language": "en", "target": "en", "text": None, "cached": False}
    assert world.translator.segments == []


def test_english_text_is_translated_to_dutch_when_target_is_nl(world: World) -> None:
    english = "Good morning, the plumber will come to the kitchen tomorrow."
    first = world.client.post("/api/inbox/translate", json={"text": english, "target": "nl"}).json()
    assert (first["language"], first["target"], first["cached"]) == ("en", "nl", False)
    assert first["text"].startswith("EN[Good morning")  # the fake echoes; the real model is opus-mt-en-nl
    again = world.client.post("/api/inbox/translate", json={"text": english, "target": "nl"}).json()
    assert again["cached"] is True


def test_dutch_text_with_target_nl_comes_back_without_a_translation(world: World) -> None:
    body = world.client.post("/api/inbox/translate", json={"text": TENANT_NL, "target": "nl"}).json()
    assert body == {"language": "nl", "target": "nl", "text": None, "cached": False}


def test_threads_carry_cached_dutch_on_english_messages(world: World) -> None:
    english = "Thanks for the message, we will send a plumber today to fix this."
    with Session(world.engine) as s:
        s.scalars(select(MessageRow).where(MessageRow.company_id == world.company_id)).one().text = english
        s.commit()
    world.client.post("/api/inbox/translate", json={"text": english, "target": "nl"})
    thread = _thread(world)
    [message] = thread["messages"]
    assert message["language"] == "en"
    assert message["bodyDutch"].startswith("EN[Thanks")
    assert "bodyEnglish" not in message


def test_blank_and_oversized_text_are_rejected(world: World) -> None:
    assert world.client.post("/api/inbox/translate", json={"text": ""}).status_code == 422
    assert world.client.post("/api/inbox/translate", json={"text": "a" * 20001}).status_code == 422


def test_missing_model_is_a_503_not_a_crash(broken_world: World) -> None:
    response = broken_world.client.post("/api/inbox/translate", json={"text": TENANT_NL})
    assert response.status_code == 503
    assert "translation" in response.json()["detail"].lower()


def _thread(world: World) -> dict:  # type: ignore[type-arg]
    [thread] = world.client.get("/api/inbox/threads").json()["threads"]
    return thread  # type: ignore[no-any-return]


def test_threads_flag_dutch_messages_and_drafts_without_running_the_model(world: World) -> None:
    thread = _thread(world)
    [message] = thread["messages"]
    assert message["language"] == "nl"
    assert message.get("bodyEnglish") is None
    assert [d["language"] for d in thread["gmailDrafts"]] == ["nl", "unknown"]
    assert world.translator.segments == []  # listing never translates


def test_threads_carry_cached_translations_on_messages_and_drafts(world: World) -> None:
    world.client.post("/api/inbox/translate", json={"text": TENANT_NL})
    world.client.post("/api/inbox/translate", json={"text": DRAFT_NL})
    thread = _thread(world)
    assert thread["messages"][0]["bodyEnglish"].startswith("EN[Goedemorgen")
    assert thread["gmailDrafts"][0]["englishMeaning"].startswith("EN[Beste Jan")
    assert "englishMeaning" not in thread["gmailDrafts"][1]  # no invented placeholder for an untranslated draft


def test_other_companys_cache_is_not_served(world: World, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        other = Company(name="Other")
        s.add(other)
        s.flush()
        from app.translation.service import source_hash

        s.add(Translation(company_id=other.id, source_hash=source_hash(TENANT_NL), source_lang="nl",
                          text_translated="LEAK", target_lang="en", engine="x"))  # fmt: skip
        s.commit()
        try:
            assert (
                "bodyEnglish" not in _thread(world)["messages"][0]
                or _thread(world)["messages"][0]["bodyEnglish"] is None
            )
        finally:
            s.query(Translation).filter(Translation.company_id == other.id).delete()
            s.query(Company).filter(Company.id == other.id).delete()
            s.commit()


def test_translate_is_rate_limited_per_owner(world: World) -> None:
    codes = [
        world.client.post(
            "/api/inbox/translate", json={"text": f"Goedemorgen nummer {n}, de verwarming werkt niet."}
        ).status_code
        for n in range(31)
    ]
    assert codes[:30] == [200] * 30
    assert codes[30] == 429
