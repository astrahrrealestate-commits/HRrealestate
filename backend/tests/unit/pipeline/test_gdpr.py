"""Unit tests for GDPR tenant erasure cascade (Task C12)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.db.enums import MemoryKind, MemoryOrigin, MemoryScope, MemoryStatus
from app.db.models import ChannelIdentity, MemoryItem, Person, PersonProfile
from app.pipeline import gdpr
from app.pipeline.gdpr import erase_person

NOW = datetime(2026, 10, 23, 14, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_call_log_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests script each query of the cascade; the model-call step runs its own queries and is covered against
    Postgres in tests/integration/test_erasure_model_calls.py."""
    monkeypatch.setattr(gdpr, "erase_model_calls", lambda *_a, **_k: 0)


def test_erase_person_cascades_profile_memories_and_redacts_messages() -> None:
    session = MagicMock()
    company_id = uuid4()
    person_id = uuid4()
    msg_id1 = uuid4()
    msg_id2 = uuid4()

    # Messages
    session.scalars.side_effect = [
        # 1. MessageRow.id
        MagicMock(all=MagicMock(return_value=[msg_id1, msg_id2])),
        # 4. MemoryItem
        MagicMock(
            all=MagicMock(
                return_value=[
                    # Item 1: scoped to this person -> should retire
                    MemoryItem(
                        id=uuid4(),
                        company_id=company_id,
                        scope=MemoryScope.person,
                        scope_id=person_id,
                        kind=MemoryKind.fact,
                        text="Speaks English",
                        status=MemoryStatus.active,
                        origin=MemoryOrigin.distilled,
                    ),
                    # Item 2: company scope but references msg_id1 in source_refs -> should retire
                    MemoryItem(
                        id=uuid4(),
                        company_id=company_id,
                        scope=MemoryScope.company,
                        scope_id=None,
                        kind=MemoryKind.preference,
                        text="No evening visits",
                        status=MemoryStatus.proposed,
                        origin=MemoryOrigin.distilled,
                        source_refs=[{"message_id": str(msg_id1)}],
                    ),
                    # Item 3: unrelated memory -> remains active
                    MemoryItem(
                        id=uuid4(),
                        company_id=company_id,
                        scope=MemoryScope.company,
                        scope_id=None,
                        kind=MemoryKind.rule,
                        text="General rule",
                        status=MemoryStatus.active,
                        origin=MemoryOrigin.owner,
                        source_refs=[{"message_id": str(uuid4())}],
                    ),
                ]
            )
        ),
        # 5. ChannelIdentity
        MagicMock(
            all=MagicMock(
                return_value=[
                    ChannelIdentity(
                        id=uuid4(),
                        company_id=company_id,
                        person_id=person_id,
                        identity="+31612345678",
                    )
                ]
            )
        ),
    ]

    # PersonProfile
    profile = PersonProfile(id=uuid4(), company_id=company_id, person_id=person_id)
    # Person
    person = Person(id=person_id, company_id=company_id, display_name="Jan Jansen")

    session.scalar.side_effect = [
        profile,  # step 3: PersonProfile
        person,  # step 6: Person
    ]

    mock_execute_res = MagicMock()
    mock_execute_res.rowcount = 2
    session.execute.return_value = mock_execute_res

    report = erase_person(session, company_id, person_id)

    assert report.person_id == person_id
    assert report.company_id == company_id
    assert report.profile_deleted is True
    assert report.memories_retired == 2
    assert report.messages_redacted == 2
    assert report.identities_cleared == 1
    assert report.person_anonymized is True

    # Person was deleted/anonymized
    session.delete.assert_called_once_with(profile)
    assert person.display_name == "[Erased Person]"
    session.flush.assert_called_once()


def test_erase_person_purges_the_brixx_mirror_for_a_brixx_person(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.pipeline import gdpr

    session = MagicMock()
    company_id, person_id = uuid4(), uuid4()
    session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
    person = Person(id=person_id, company_id=company_id, display_name="Invented Name", brixx_ref="42")
    session.scalar.side_effect = [None, person]
    purged: list[tuple[object, int]] = []

    def fake_purge(_session: object, cid: object, ref: int) -> int:
        purged.append((cid, ref))
        return 2

    monkeypatch.setattr(gdpr, "purge_brixx_relatie", fake_purge)

    report = erase_person(session, company_id, person_id)

    assert purged == [(company_id, 42)]
    assert report.brixx_rows_purged == 2
    assert person.brixx_ref is None


def test_erase_person_skips_the_mirror_without_a_numeric_brixx_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.pipeline import gdpr

    session = MagicMock()
    session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
    person = Person(id=uuid4(), company_id=uuid4(), display_name="Invented Name", brixx_ref="not-a-number")
    session.scalar.side_effect = [None, person]

    def no_purge(*_args: object) -> int:
        raise AssertionError("no numeric BRIXX ref: nothing to purge")

    monkeypatch.setattr(gdpr, "purge_brixx_relatie", no_purge)

    assert erase_person(session, person.company_id, person.id).brixx_rows_purged == 0


def test_erase_person_deletes_the_read_markers_of_their_whatsapp_chats() -> None:
    from app.contracts import Channel

    session = MagicMock()
    company_id, person_id = uuid4(), uuid4()
    session.scalars.side_effect = [
        MagicMock(all=MagicMock(return_value=[])),  # messages
        MagicMock(all=MagicMock(return_value=[])),  # memories
        MagicMock(
            all=MagicMock(
                return_value=[
                    ChannelIdentity(
                        id=uuid4(), company_id=company_id, person_id=person_id, channel=Channel.whatsapp,
                        identity="+31612345678",
                    ),
                    ChannelIdentity(
                        id=uuid4(), company_id=company_id, person_id=person_id, channel=Channel.gmail,
                        identity="jan@example.test",
                    ),
                ]
            )
        ),
    ]  # fmt: skip
    session.scalar.side_effect = [None, Person(id=person_id, company_id=company_id, display_name="Jan")]

    erase_person(session, company_id, person_id)

    deletes = [
        str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        for call in session.execute.call_args_list
        if "DELETE FROM chat_reads" in str(call.args[0])
    ]
    assert len(deletes) == 1
    assert company_id.hex in deletes[0]  # scoped to the company
    assert "+31612345678" in deletes[0]
    assert "jan@example.test" not in deletes[0]  # only WhatsApp identities name a chat
