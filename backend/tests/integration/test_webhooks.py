import json
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest
from dbos import DBOSClient
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app.api.webhooks.gmail import gmail_sync_workflow_id
from app.channels.gmail.push import DEV_AUDIENCE, DEV_SERVICE_ACCOUNT, local_push_verifier
from app.channels.whatsapp.webhook_auth import DEV_APP_SECRET, sign_body
from app.contracts import Channel
from app.core.settings import Settings
from app.core.workflow_names import PROCESS_EVENT, event_workflow_id
from app.db.enums import PersonKind, PipelineStatus, RawEventStatus
from app.db.models import (
    AttachmentRow,
    ChannelAccount,
    ChannelIdentity,
    Company,
    MessageRow,
    OwnerAccount,
    Person,
    RawEvent,
)
from app.dev.keys import ensure_dev_keys, sign_push_token
from app.main import create_app
from app.pipeline.chat_repo import chat_list, chat_messages
from tests.unit.channels.gmail.test_push import envelope

pytestmark = pytest.mark.integration
Load = Callable[[str, str], bytes]
PNID, MAILBOX = "100000000000001", "hausverwaltung@example.test"


@pytest.fixture
def accounts(committed_company: Company, migrated_engine: Engine) -> Company:
    with Session(migrated_engine) as s:
        s.add_all(
            [
                ChannelAccount(company_id=committed_company.id, channel=Channel.whatsapp, address=PNID),
                ChannelAccount(company_id=committed_company.id, channel=Channel.gmail, address=MAILBOX),
            ]
        )
        s.commit()
    return committed_company


@pytest.fixture
def api(
    dbos_client: DBOSClient, test_settings: Settings, migrated_engine: Engine, tmp_path: Path
) -> Iterator[tuple[TestClient, str]]:
    private, _ = ensure_dev_keys(tmp_path)
    verifier = local_push_verifier(tmp_path, DEV_AUDIENCE, DEV_SERVICE_ACCOUNT)
    app = create_app(test_settings, engine=migrated_engine, workflow_client=dbos_client, gmail_push_verifier=verifier)
    with TestClient(app) as client:
        yield client, private


def _post(client: TestClient, body: bytes) -> int:
    return client.post(
        "/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sign_body(DEV_APP_SECRET, body)}
    ).status_code


def _raw(engine: Engine, company: Company) -> list[RawEvent]:
    with Session(engine) as s:
        return list(s.scalars(select(RawEvent).where(RawEvent.company_id == company.id).order_by(RawEvent.received_at)))


def test_whatsapp_message_recorded_once_and_enqueued(
    api: tuple[TestClient, str], accounts: Company, migrated_engine: Engine, recorded: Load, dbos_client: DBOSClient
) -> None:
    client, _ = api
    body = recorded("whatsapp", "text")
    assert _post(client, body) == 200
    assert _post(client, body) == 200  # Meta redelivery
    [raw] = _raw(migrated_engine, accounts)
    assert (raw.provider_msg_id, raw.status) == ("wamid.TEST0001", RawEventStatus.pending)
    assert raw.payload["kind"] == "message"
    [wf] = dbos_client.list_workflows(workflow_ids=[event_workflow_id(raw.id)])
    assert (wf.name, wf.status) == (PROCESS_EVENT, "ENQUEUED")


def test_multi_message_batch_and_statuses(
    api: tuple[TestClient, str], accounts: Company, migrated_engine: Engine, recorded: Load, dbos_client: DBOSClient
) -> None:
    client, _ = api
    assert _post(client, recorded("whatsapp", "multi_message")) == 200
    rows = _raw(migrated_engine, accounts)
    message_rows = [r for r in rows if not r.provider_msg_id.startswith("status:")]
    queued = dbos_client.list_workflows(workflow_ids=[event_workflow_id(r.id) for r in message_rows])
    assert len(queued) == 3
    messages = sorted(r.provider_msg_id for r in rows if not r.provider_msg_id.startswith("status:"))
    statuses = sorted(r.provider_msg_id for r in rows if r.provider_msg_id.startswith("status:"))
    assert messages == ["wamid.TEST0008", "wamid.TEST0009", "wamid.TEST0010"]
    assert statuses == ["status:wamid.OUT0004:read", "status:wamid.OUT0004:sent"]
    assert {r.status for r in rows if r.provider_msg_id.startswith("status:")} == {RawEventStatus.ignored}


def test_unknown_number_acked_and_ignored(
    api: tuple[TestClient, str],
    committed_company: Company,
    migrated_engine: Engine,
    recorded: Load,
    dbos_client: DBOSClient,
) -> None:
    client, _ = api
    before = len(dbos_client.list_workflows())
    assert _post(client, recorded("whatsapp", "text")) == 200
    with Session(migrated_engine) as s:
        assert s.scalars(select(RawEvent).where(RawEvent.provider_msg_id == "wamid.TEST0001")).all() == []
    assert len(dbos_client.list_workflows()) == before


def test_gmail_push_enqueues_idempotent_sync(
    api: tuple[TestClient, str], accounts: Company, migrated_engine: Engine, dbos_client: DBOSClient
) -> None:
    client, private = api
    headers = {"authorization": f"Bearer {sign_push_token(private)}"}
    for _ in range(2):  # Pub/Sub at-least-once delivery
        assert (
            client.post(
                "/webhooks/gmail/push", content=envelope(email=MAILBOX, history="777"), headers=headers
            ).status_code
            == 204
        )
    with Session(migrated_engine) as s:
        account = s.scalar(
            select(ChannelAccount).where(
                ChannelAccount.company_id == accounts.id, ChannelAccount.channel == Channel.gmail
            )
        )
    assert account is not None
    workflows = dbos_client.list_workflows(workflow_ids=[gmail_sync_workflow_id(account.id, 777)])
    assert [w.status for w in workflows] == ["ENQUEUED"]


def test_gmail_push_for_unknown_mailbox_acked_without_work(
    api: tuple[TestClient, str], accounts: Company, dbos_client: DBOSClient
) -> None:
    client, private = api
    headers = {"authorization": f"Bearer {sign_push_token(private)}"}
    before = len(dbos_client.list_workflows())
    r = client.post("/webhooks/gmail/push", content=envelope(email="stranger@example.test"), headers=headers)
    assert r.status_code == 204
    assert len(dbos_client.list_workflows()) == before


def test_echo_through_route(
    api: tuple[TestClient, str], accounts: Company, migrated_engine: Engine, recorded: Load
) -> None:
    client, _ = api
    assert _post(client, recorded("whatsapp", "echo")) == 200
    [raw] = _raw(migrated_engine, accounts)
    assert (raw.provider_msg_id, raw.payload["kind"]) == ("wamid.ECHO0001", "echo")


def test_dropped_items_are_stored_failed_next_to_good_ones(
    api: tuple[TestClient, str], accounts: Company, migrated_engine: Engine
) -> None:
    client, _ = api
    good = {
        "from": "4915550000001",
        "id": "wamid.GOOD",
        "timestamp": "1759737600",
        "type": "text",
        "text": {"body": "ok"},
    }
    bad = {**good, "id": "wamid.BAD", "timestamp": "not-a-time"}
    value = {"metadata": {"display_phone_number": "1", "phone_number_id": PNID}, "messages": [bad, good]}
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"id": "1", "changes": [{"field": "messages", "value": value}]}],
        }
    ).encode()
    assert _post(client, body) == 200
    rows = {
        r.provider_msg_id.split(":")[0] if r.provider_msg_id.startswith("unparsed:") else r.provider_msg_id: r
        for r in _raw(migrated_engine, accounts)
    }
    assert rows["wamid.GOOD"].status is RawEventStatus.pending
    assert rows["unparsed"].status is RawEventStatus.failed
    assert rows["unparsed"].payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"] == "wamid.BAD"


def test_db_error_on_one_event_skips_only_that_event(
    api: tuple[TestClient, str],
    accounts: Company,
    migrated_engine: Engine,
    recorded: Load,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import DataError

    import app.api.webhooks.whatsapp as route

    real = route.record_event

    def flaky(session, client, account, provider_msg_id, payload, **kw):  # type: ignore[no-untyped-def]
        if provider_msg_id == "wamid.TEST0009":
            raise DataError("INSERT", {}, Exception("value too long"))
        return real(session, client, account, provider_msg_id, payload, **kw)

    monkeypatch.setattr(route, "record_event", flaky)
    client, _ = api
    assert _post(client, recorded("whatsapp", "multi_message")) == 200
    ids = {r.provider_msg_id for r in _raw(migrated_engine, accounts)}
    assert {"wamid.TEST0008", "wamid.TEST0010"} <= ids
    assert "wamid.TEST0009" not in ids


def test_signed_but_malformed_push_is_acked(
    api: tuple[TestClient, str], accounts: Company, dbos_client: DBOSClient
) -> None:
    client, private = api
    before = len(dbos_client.list_workflows())
    r = client.post(
        "/webhooks/gmail/push",
        content=b'{"message": {}}',
        headers={"authorization": f"Bearer {sign_push_token(private)}"},
    )
    assert r.status_code == 204
    assert len(dbos_client.list_workflows()) == before


def test_mixed_case_mailbox_resolves(
    api: tuple[TestClient, str], committed_company: Company, migrated_engine: Engine, dbos_client: DBOSClient
) -> None:
    with Session(migrated_engine) as s:
        s.add(ChannelAccount(company_id=committed_company.id, channel=Channel.gmail, address="Mixed.Case@Example.test"))
        s.commit()
    client, private = api
    headers = {"authorization": f"Bearer {sign_push_token(private)}"}
    assert (
        client.post(
            "/webhooks/gmail/push", content=envelope(email="mixed.case@example.test", history="5"), headers=headers
        ).status_code
        == 204
    )
    with Session(migrated_engine) as s:
        account = s.scalar(select(ChannelAccount).where(ChannelAccount.company_id == committed_company.id))
    assert account is not None
    assert dbos_client.list_workflows(workflow_ids=[gmail_sync_workflow_id(account.id, 5)])


def test_unsafe_strings_and_dropped_items_in_one_body_are_all_stored(
    api: tuple[TestClient, str], accounts: Company, migrated_engine: Engine
) -> None:
    """NUL / lone surrogates must neither drop the message nor turn the unparsed-item record into a 500 (which makes
    Meta redeliver the whole batch for days)."""
    client, _ = api
    good = {
        "from": "4915550000001",
        "id": "wamid.NUL",
        "timestamp": "1759737600",
        "type": "text",
        "text": {"body": "Heiz\u0000ung \ud800kalt"},
    }
    bad = {**good, "id": "wamid.BAD2", "timestamp": "not-a-time"}
    value = {"metadata": {"display_phone_number": "1", "phone_number_id": PNID}, "messages": [bad, good]}
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"id": "1", "changes": [{"field": "messages", "value": value}]}],
        }
    ).encode()
    assert _post(client, body) == 200
    rows = {r.provider_msg_id.split(":")[0]: r for r in _raw(migrated_engine, accounts)}
    assert rows["wamid.NUL"].payload["item"]["text"]["body"] == "Heizung \ufffdkalt"
    assert rows["unparsed"].status is RawEventStatus.failed


def test_unparsed_items_are_never_stored_across_companies(
    api: tuple[TestClient, str], accounts: Company, migrated_engine: Engine
) -> None:
    """One Meta POST can carry several WABAs: an unparsed body must not land in another tenant's raw_events."""
    other = Company(name="Other GmbH")
    with Session(migrated_engine, expire_on_commit=False) as s:
        s.add(other)
        s.flush()
        s.add(ChannelAccount(company_id=other.id, channel=Channel.whatsapp, address="100000000000077"))
        s.commit()
    client, _ = api
    try:
        bad = {"from": "4915550000001", "id": "wamid.X", "timestamp": "nope", "type": "text", "text": {"body": "x"}}
        entries = [
            {
                "id": str(i),
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"display_phone_number": "1", "phone_number_id": pnid},
                            "messages": [bad],
                        },
                    }
                ],
            }
            for i, pnid in enumerate((PNID, "100000000000077"))
        ]
        body = json.dumps({"object": "whatsapp_business_account", "entry": entries}).encode()
        assert _post(client, body) == 200
        assert [r for r in _raw(migrated_engine, accounts) if r.provider_msg_id.startswith("unparsed:")] == []
    finally:
        from tests.integration.conftest import purge_company

        purge_company(migrated_engine, other.id)


def _text_body(message: dict[str, object]) -> bytes:
    value = {"metadata": {"display_phone_number": "1", "phone_number_id": PNID}, "messages": [message]}
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"id": "1", "changes": [{"field": "messages", "value": value}]}],
        }
    ).encode()


def test_whatsapp_message_is_stored_and_in_the_chat_list_before_any_worker_runs(
    api: tuple[TestClient, str], accounts: Company, migrated_engine: Engine, recorded: Load
) -> None:
    """Chats show every message the moment the webhook returns: storage never waits for a queue slot or the pipeline."""
    client, _ = api
    body = recorded("whatsapp", "text")
    assert _post(client, body) == 200
    assert _post(client, body) == 200  # Meta redelivery
    with Session(migrated_engine) as s:
        [row] = s.scalars(select(MessageRow).where(MessageRow.company_id == accounts.id)).all()
        assert (row.provider_msg_id, row.thread_ref, row.sender_identity) == (
            "wamid.TEST0001",
            "+4915550000001",
            "+4915550000001",
        )
        assert row.text.startswith("Hallo, die Heizung")
        [chat] = chat_list(s, accounts.id, before=None, limit=10)
        assert (chat.chat_key, chat.unread) == ("+4915550000001", 1)
        assert [m.id for m in chat_messages(s, accounts.id, "+4915550000001", before=None, limit=10)] == [row.id]
    [raw] = _raw(migrated_engine, accounts)
    assert raw.status is RawEventStatus.pending  # the worker still normalises, downloads media and routes it


def test_every_message_kind_is_stored_on_arrival(
    api: tuple[TestClient, str], accounts: Company, migrated_engine: Engine, recorded: Load
) -> None:
    client, _ = api
    kinds = (
        "image_caption",
        "document",
        "reaction",
        "unsupported",
        "button_reply",
        "list_reply",
        "system_number_change",
    )
    for name in kinds:
        assert _post(client, recorded("whatsapp", name)) == 200
    with Session(migrated_engine) as s:
        stored = {r.meta["type"] for r in s.scalars(select(MessageRow).where(MessageRow.company_id == accounts.id))}
        attachments = s.scalars(select(AttachmentRow).where(AttachmentRow.company_id == accounts.id)).all()
    assert {"image", "document", "reaction", "unsupported", "interactive", "system"} <= stored
    assert attachments == []  # media is downloaded later by the worker; the row is already visible


def test_sender_without_a_phone_number_keeps_only_the_raw_event(
    api: tuple[TestClient, str], accounts: Company, migrated_engine: Engine
) -> None:
    client, _ = api
    body = _text_body({"id": "wamid.NOPHONE", "timestamp": "1759737600", "type": "text", "text": {"body": "hi"}})
    assert _post(client, body) == 200
    [raw] = _raw(migrated_engine, accounts)
    assert (raw.provider_msg_id, raw.status) == ("wamid.NOPHONE", RawEventStatus.pending)
    with Session(migrated_engine) as s:
        assert s.scalars(select(MessageRow).where(MessageRow.company_id == accounts.id)).all() == []


@pytest.mark.parametrize("error", [DataError("INSERT", {}, Exception("value too long")), KeyError("surprise")])
def test_a_message_the_early_store_cannot_save_does_not_lose_its_raw_event(
    api: tuple[TestClient, str],
    accounts: Company,
    migrated_engine: Engine,
    recorded: Load,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    import app.api.webhooks.whatsapp as route

    def reject(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(route, "store_inbound", reject)
    client, _ = api
    assert _post(client, recorded("whatsapp", "text")) == 200
    [raw] = _raw(migrated_engine, accounts)
    assert (raw.provider_msg_id, raw.status) == ("wamid.TEST0001", RawEventStatus.pending)  # the worker stores it


SENDER = "+4915550000001"  # the recorded `text` fixture's sender


def _directory(engine: Engine, company: Company, kind: PersonKind, *, brixx_ref: str | None = None) -> None:
    with Session(engine) as s, s.begin():
        person = Person(
            company_id=company.id, kind=kind, display_name="Sender", brixx_ref=brixx_ref, valid_from=date(2026, 1, 1)
        )
        s.add(person)
        s.flush()
        s.add(
            ChannelIdentity(
                company_id=company.id,
                person_id=person.id,
                channel=Channel.whatsapp,
                identity=SENDER,
                valid_from=date(2026, 1, 1),
            )
        )


def _stored_status(engine: Engine, company: Company) -> PipelineStatus:
    with Session(engine) as s:
        row = s.scalars(select(MessageRow).where(MessageRow.company_id == company.id)).one()
        return row.pipeline_status


def test_a_number_the_directory_does_not_know_is_stored_for_chats_only(
    api: tuple[TestClient, str], accounts: Company, migrated_engine: Engine, recorded: Load
) -> None:
    client, _ = api
    assert _post(client, recorded("whatsapp", "text")) == 200
    assert _stored_status(migrated_engine, accounts) is PipelineStatus.skipped


@pytest.mark.parametrize(
    ("kind", "brixx_ref", "expected"),
    [
        (PersonKind.tenant, None, PipelineStatus.pending),
        (PersonKind.contractor, None, PipelineStatus.pending),
        (PersonKind.other, "BX-1", PipelineStatus.pending),  # a BRIXX relatie is the directory's own record
        (PersonKind.other, None, PipelineStatus.skipped),  # only auto-created on a past first contact: not known
    ],
)
def test_only_a_contact_the_directory_knows_feeds_the_pipeline(
    api: tuple[TestClient, str],
    accounts: Company,
    migrated_engine: Engine,
    recorded: Load,
    kind: PersonKind,
    brixx_ref: str | None,
    expected: PipelineStatus,
) -> None:
    _directory(migrated_engine, accounts, kind, brixx_ref=brixx_ref)
    client, _ = api
    assert _post(client, recorded("whatsapp", "text")) == 200
    assert _stored_status(migrated_engine, accounts) is expected


def test_a_person_with_a_case_the_pipeline_already_opened_keeps_flowing(
    api: tuple[TestClient, str], accounts: Company, migrated_engine: Engine, recorded: Load
) -> None:
    from app.contracts import CaseState, Category, Urgency
    from app.db.models import Case

    _directory(migrated_engine, accounts, PersonKind.other)
    with Session(migrated_engine) as s, s.begin():
        person_id = s.scalars(select(Person.id).where(Person.company_id == accounts.id)).one()
        s.add(
            Case(
                company_id=accounts.id,
                category=Category.other,
                urgency=Urgency.normal,
                state=CaseState.open,
                primary_person_id=person_id,
            )
        )
    client, _ = api
    assert _post(client, recorded("whatsapp", "text")) == 200
    assert _stored_status(migrated_engine, accounts) is PipelineStatus.pending
    with Session(migrated_engine) as s, s.begin():
        s.query(Case).filter(Case.company_id == accounts.id).delete()


def test_the_owners_own_number_is_not_chat_only(
    api: tuple[TestClient, str], accounts: Company, migrated_engine: Engine, recorded: Load
) -> None:
    """His commands are routed by the owner handler exactly as before."""
    with Session(migrated_engine) as s, s.begin():
        s.add(OwnerAccount(company_id=accounts.id, display_name="H", whatsapp_e164=SENDER, email="h@example.test"))
    client, _ = api
    assert _post(client, recorded("whatsapp", "text")) == 200
    assert _stored_status(migrated_engine, accounts) is PipelineStatus.pending
    with Session(migrated_engine) as s, s.begin():
        s.query(OwnerAccount).filter(OwnerAccount.company_id == accounts.id).delete()
