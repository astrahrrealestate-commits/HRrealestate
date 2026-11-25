"""Migration 0054 (M13 T4): eight old categories map onto the six, on cases, understandings and the stored body."""

import json
from collections.abc import Iterator
from uuid import UUID

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, make_url, text

import app.db.models  # noqa: F401  (registers tables)
from app.contracts.understanding import Understanding
from app.core.ids import new_id
from app.pipeline.propose import _with_defaults
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration
OLD_TO_NEW = {
    "maintenance": "maintenance",
    "contractor_update": "maintenance",
    "complaint": "maintenance",
    "payment": "finance",
    "lease": "legal",
    "admin": "administration",
    "other": "administration",
    "spam": "spam",
}


@pytest.fixture
def scratch_db_url(pg_url: str) -> Iterator[str]:
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS roundtrip_0054"))
        conn.execute(text("CREATE DATABASE roundtrip_0054"))
    yield make_url(pg_url).set(database="roundtrip_0054").render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS roundtrip_0054 WITH (FORCE)"))
    admin.dispose()


def _body(category: str) -> dict[str, object]:
    return {
        "category": category,
        "intent": "Vraag",
        "urgency": "normal",
        "requires_reply": True,
        "entities": {"people": [], "unit_refs": [], "dates": [], "amounts": []},
        "suspicious": {"flag": False, "reason": None},
        "confidence": 0.8,
        "sender_role": None,
        "prompt_version": "understanding/v3",
    }


def _seed(engine: Engine, category: str) -> tuple[UUID, UUID]:
    """One case and one understanding (with its message) stored under an old category, written as 0053 would."""
    cid, raw, msg, case, und = new_id(), new_id(), new_id(), new_id(), new_id()
    with engine.begin() as c:
        c.execute(text("INSERT INTO companies (id, name) VALUES (:id, 'Old')"), {"id": cid})
        c.execute(
            text(
                "INSERT INTO raw_events (id, company_id, provider, provider_msg_id, payload) "
                "VALUES (:id, :c, 'gmail', :p, '{}')"
            ),
            {"id": raw, "c": cid, "p": str(raw)},
        )
        c.execute(
            text(
                "INSERT INTO messages (id, company_id, raw_event_id, channel, provider_msg_id, sender_identity, "
                "direction, sent_at, text) VALUES (:id, :c, :r, 'gmail', :p, 'a@b.nl', 'inbound', now(), 'x')"
            ),
            {"id": msg, "c": cid, "r": raw, "p": str(raw)},
        )
        c.execute(
            text("INSERT INTO cases (id, company_id, category, urgency) VALUES (:id, :c, :cat, 'normal')"),
            {"id": case, "c": cid, "cat": category},
        )
        c.execute(
            text(
                "INSERT INTO understandings (id, company_id, message_id, category, urgency, body, prompt_version) "
                "VALUES (:id, :c, :m, :cat, 'normal', CAST(:b AS jsonb), 'understanding/v3')"
            ),
            {"id": und, "c": cid, "m": msg, "cat": category, "b": json.dumps(_body(category))},
        )
    return case, und


def _stored(engine: Engine, case: UUID, und: UUID) -> tuple[str, str, dict[str, object]]:
    with engine.connect() as c:
        case_cat = c.execute(text("SELECT category FROM cases WHERE id = :i"), {"i": case}).scalar_one()
        und_cat, body = c.execute(text("SELECT category, body FROM understandings WHERE id = :i"), {"i": und}).one()
    return case_cat, und_cat, body


def test_old_values_map_on_migration(scratch_db_url: str) -> None:
    cfg = alembic_config(scratch_db_url)
    engine = create_engine(scratch_db_url)
    try:
        command.upgrade(cfg, "0053")
        seeded = {old: _seed(engine, old) for old in OLD_TO_NEW}
        command.upgrade(cfg, "0054")
        for old, (case, und) in seeded.items():
            case_cat, und_cat, body = _stored(engine, case, und)
            assert (case_cat, und_cat, body["category"]) == (OLD_TO_NEW[old],) * 3, old
        command.downgrade(cfg, "0053")
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()


def test_stored_old_understanding_still_proposes_after_migration(scratch_db_url: str) -> None:
    cfg = alembic_config(scratch_db_url)
    engine = create_engine(scratch_db_url)
    try:
        command.upgrade(cfg, "0053")
        case, und = _seed(engine, "payment")
        command.upgrade(cfg, "head")
        _case, _cat, body = _stored(engine, case, und)
        assert Understanding.model_validate(_with_defaults(body)).category.value == "finance"
    finally:
        engine.dispose()


def test_a_body_written_by_old_code_after_the_migration_still_validates() -> None:
    """During a rolling deploy an old worker can still write `payment`; the proposer reads it as finance."""
    assert Understanding.model_validate(_with_defaults(_body("contractor_update"))).category.value == "maintenance"
