from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.channels.whatsapp.inbound import WaEcho, WaInbound, WaStatus, parse_webhook, to_message
from app.channels.whatsapp.webhook_auth import sign_body, verify_handshake, verify_signature
from app.contracts import Direction
from app.core.errors import WebhookRejectedError

SECRET = "dev-app-secret"
Load = Callable[[str, str], bytes]
TS = datetime(2025, 10, 6, 8, 0, tzinfo=UTC)


def events(recorded: Load, name: str) -> list[WaInbound | WaStatus | WaEcho]:
    return parse_webhook(recorded("whatsapp", name))


# ---- signature + handshake ---------------------------------------------------------------------------------------


def test_signature_round_trip(recorded: Load) -> None:
    body = recorded("whatsapp", "text")
    verify_signature(body, sign_body(SECRET, body), SECRET)


@pytest.mark.parametrize("header", [None, "", "sha256=", "sha1=abc", "sha256=" + "0" * 64, "sha256=zz"])
def test_bad_signature_rejected(recorded: Load, header: str | None) -> None:
    with pytest.raises(WebhookRejectedError):
        verify_signature(recorded("whatsapp", "text"), header, SECRET)


def test_tampered_body_rejected(recorded: Load) -> None:
    body = recorded("whatsapp", "text")
    with pytest.raises(WebhookRejectedError):
        verify_signature(body.replace(b"kaputt", b"heile"), sign_body(SECRET, body), SECRET)


def test_handshake() -> None:
    assert verify_handshake("subscribe", "tok", "12345", expected_token="tok") == "12345"
    for mode, token in [("subscribe", "wrong"), ("unsubscribe", "tok"), (None, "tok"), ("subscribe", None)]:
        with pytest.raises(WebhookRejectedError):
            verify_handshake(mode, token, "12345", expected_token="tok")


# ---- parsing -----------------------------------------------------------------------------------------------------


def test_text(recorded: Load) -> None:
    [e] = events(recorded, "text")
    assert isinstance(e, WaInbound)
    assert (e.kind, e.wamid, e.sender, e.phone_number_id) == (
        "text",
        "wamid.TEST0001",
        "4915550000001",
        "100000000000001",
    )
    assert e.text == "Hallo, die Heizung in Whg 3 ist kaputt."
    assert e.contact_name == "Tenant 001"
    assert e.sent_at == TS


def test_image_and_document_media(recorded: Load) -> None:
    [img] = events(recorded, "image_caption")
    [doc] = events(recorded, "document")
    assert isinstance(img, WaInbound)
    assert isinstance(doc, WaInbound)
    assert img.media is not None
    assert img.media.id == "MEDIA0002"
    assert img.media.mime_type == "image/jpeg"
    assert img.text == "Wasserfleck Decke"
    assert doc.media is not None
    assert doc.media.filename == "abrechnung.pdf"


@pytest.mark.parametrize(("name", "reply_id"), [("button_reply", ":ok"), ("list_reply", ":d2")])
def test_interactive_replies_keep_id_and_context(recorded: Load, name: str, reply_id: str) -> None:
    [e] = events(recorded, name)
    assert isinstance(e, WaInbound)
    assert e.kind == "interactive"
    assert e.interactive_id is not None
    assert e.interactive_id.endswith(reply_id)
    assert e.reply_to is not None
    assert e.reply_to.startswith("wamid.OUT")


def test_statuses(recorded: Load) -> None:
    [ok] = events(recorded, "status_delivered")
    [bad] = events(recorded, "status_failed")
    assert isinstance(ok, WaStatus)
    assert (ok.wamid, ok.status) == ("wamid.OUT0001", "delivered")
    assert isinstance(bad, WaStatus)
    assert bad.status == "failed"
    assert bad.error_codes == [131026]


def test_echo(recorded: Load) -> None:
    [e] = events(recorded, "echo")
    assert isinstance(e, WaEcho)
    assert (e.wamid, e.recipient, e.text) == (
        "wamid.ECHO0001",
        "4915550000001",
        "Danke, ich schicke morgen einen Handwerker.",
    )


def test_reaction_location_unsupported_are_safe(recorded: Load) -> None:
    [r] = events(recorded, "reaction")
    [u] = events(recorded, "unsupported")
    assert isinstance(r, WaInbound)
    assert r.kind == "reaction"
    assert "\U0001f44d" in r.text
    assert isinstance(u, WaInbound)
    assert u.kind == "unsupported"
    assert u.text == "[unsupported message]"


def test_multi_message_keeps_order_and_statuses(recorded: Load) -> None:
    evs = events(recorded, "multi_message")
    assert [type(e).__name__ for e in evs] == ["WaInbound", "WaInbound", "WaInbound", "WaStatus", "WaStatus"]
    loc = evs[2]
    assert isinstance(loc, WaInbound)
    assert loc.kind == "location"
    assert "10115 Berlin" in loc.text


@pytest.mark.parametrize(
    "body", [b"", b"not json", b"[]", b'{"object": "page"}', b'{"object": "whatsapp_business_account"}']
)
def test_garbage_yields_no_events(body: bytes) -> None:
    assert parse_webhook(body) == []


def test_unknown_message_type_and_extra_fields_tolerated() -> None:
    body = (
        b'{"object":"whatsapp_business_account","entry":[{"id":"1","changes":[{"field":"messages","value":'
        b'{"messaging_product":"whatsapp","new_field":1,"metadata":{"display_phone_number":"1","phone_number_id":"2"},'
        b'"messages":[{"from":"4915550000001","id":"wamid.X","timestamp":"1759737600","type":"hologram","hologram":{}}]}}]}]}'
    )
    [e] = parse_webhook(body)
    assert isinstance(e, WaInbound)
    assert e.kind == "unsupported"


# ---- normalisation -----------------------------------------------------------------------------------------------


def test_to_message_inbound(recorded: Load) -> None:
    [e] = events(recorded, "text")
    assert isinstance(e, WaInbound)
    company, raw = uuid4(), uuid4()
    msg, meta = to_message(e, company_id=company, raw_event_id=raw)
    assert msg.sender_identity == "+4915550000001"
    assert msg.thread_ref == "+4915550000001"
    assert msg.direction is Direction.inbound
    assert msg.provider_msg_id == "wamid.TEST0001"
    assert (msg.company_id, msg.raw_event_id) == (company, raw)
    assert meta["type"] == "text"
    assert meta["contact_name"] == "Tenant 001"


def test_to_message_echo_is_outbound_threaded_on_customer(recorded: Load) -> None:
    [e] = events(recorded, "echo")
    assert isinstance(e, WaEcho)
    msg, meta = to_message(e, company_id=uuid4(), raw_event_id=uuid4())
    assert msg.direction is Direction.outbound
    assert msg.thread_ref == "+4915550000001"
    assert msg.sender_identity == "+4915550000999"
    assert meta["echo"] is True


def test_to_message_button_reply_metadata(recorded: Load) -> None:
    [e] = events(recorded, "button_reply")
    assert isinstance(e, WaInbound)
    _, meta = to_message(e, company_id=uuid4(), raw_event_id=uuid4())
    assert meta["interactive_id"].startswith("apr:")
    assert meta["reply_to"] == "wamid.OUT0001"


# ---- review round 1: robustness, legacy replies, fallbacks -------------------------------------------------------

import dataclasses  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

from syrupy.assertion import SnapshotAssertion  # noqa: E402

from app.channels.whatsapp.webhook_auth import MAX_WEBHOOK_BYTES  # noqa: E402
from app.core.errors import UnroutableMessageError  # noqa: E402

FIXTURES = sorted(p.stem for p in (Path(__file__).parents[3] / "fixtures/recorded/whatsapp").glob("*.json"))
GOOD = {"from": "4915550000001", "id": "wamid.GOOD", "timestamp": "1759737600", "type": "text", "text": {"body": "ok"}}


def _body(
    messages: list[object] | None = None, *, contacts: object = None, extra_changes: list[object] | None = None
) -> bytes:
    value: dict[str, object] = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "4915550000999", "phone_number_id": "100000000000001"},
        "messages": messages if messages is not None else [GOOD],
    }
    if contacts is not None:
        value["contacts"] = contacts
    changes = [*(extra_changes or []), {"field": "messages", "value": value}]
    return json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": changes}]}).encode()


def _ids(body: bytes) -> list[str]:
    return [e.wamid for e in parse_webhook(body)]


@pytest.mark.parametrize("fixture", FIXTURES)
def test_fixture_snapshot(recorded: Load, fixture: str, snapshot: SnapshotAssertion) -> None:
    assert [
        {k: v for k, v in dataclasses.asdict(e).items() if k != "raw"} for e in events(recorded, fixture)
    ] == snapshot


@pytest.mark.parametrize("ts", ["abc", "1759737600.5", "99999999999999999", "-1", "", None, "１７５９７３７６００"])
def test_bad_timestamp_skips_only_that_item(ts: object) -> None:
    bad = {**GOOD, "id": "wamid.BAD", "timestamp": ts}
    assert _ids(_body([bad, GOOD])) == ["wamid.GOOD"]


@pytest.mark.parametrize("item", [None, 1, "x", [], {"id": "no-type"}, {**GOOD, "id": None}])
def test_malformed_items_do_not_drop_neighbours(item: object) -> None:
    assert _ids(_body([item, GOOD])) == ["wamid.GOOD"]


def test_bad_contact_does_not_drop_messages() -> None:
    assert _ids(_body(contacts=[{"profile": {"name": "x"}}, "junk", {"wa_id": "4915550000001"}])) == ["wamid.GOOD"]


@pytest.mark.parametrize("sibling", [{"field": "messages"}, {"field": "messages", "value": "x"}, "junk", None])
def test_malformed_sibling_change_does_not_drop_good_change(sibling: object) -> None:
    assert _ids(_body(extra_changes=[sibling])) == ["wamid.GOOD"]


def test_other_fields_ignored() -> None:
    other = {
        "field": "account_update",
        "value": {"metadata": {"display_phone_number": "1", "phone_number_id": "2"}, "messages": [GOOD]},
    }
    body = json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [other]}]}).encode()
    assert parse_webhook(body) == []


def test_unknown_status_value_skipped() -> None:
    value = {
        "metadata": {"display_phone_number": "1", "phone_number_id": "2"},
        "statuses": [{"id": "wamid.S", "status": "warning", "timestamp": "1759737600"}],
    }
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"id": "1", "changes": [{"field": "messages", "value": value}]}],
        }
    )
    assert parse_webhook(body.encode()) == []


def test_deep_nesting_never_raises() -> None:
    assert parse_webhook(b"[" * 200_000) == []


def test_oversize_raises_typed_error_never_silent() -> None:
    from app.core.errors import WebhookTooLargeError

    assert MAX_WEBHOOK_BYTES >= 3 * 1024 * 1024  # Meta batches can reach ~3 MB
    with pytest.raises(WebhookTooLargeError):
        parse_webhook(b" " * (MAX_WEBHOOK_BYTES + 1))


def test_message_field_does_not_read_echo_list() -> None:
    value = {
        "metadata": {"display_phone_number": "1", "phone_number_id": "2"},
        "message_echoes": [{**GOOD, "to": "4915550000001"}],
    }
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"id": "1", "changes": [{"field": "messages", "value": value}]}],
        }
    )
    assert parse_webhook(body.encode()) == []


def test_failed_status_without_error_code_kept() -> None:
    value = {
        "metadata": {"display_phone_number": "1", "phone_number_id": "2"},
        "statuses": [
            {"id": "wamid.S", "status": "failed", "timestamp": "1759737600", "errors": [{"title": "no code"}]}
        ],
    }
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"id": "1", "changes": [{"field": "messages", "value": value}]}],
        }
    )
    [s] = parse_webhook(body.encode())
    assert isinstance(s, WaStatus)
    assert (s.status, s.error_codes) == ("failed", [])


@pytest.mark.parametrize("header", ["sha256=é", "éé"])
def test_non_ascii_signature_rejected_not_crash(recorded: Load, header: str) -> None:
    with pytest.raises(WebhookRejectedError):
        verify_signature(recorded("whatsapp", "text"), header, SECRET)


def test_empty_secret_and_token_fail_closed() -> None:
    with pytest.raises(WebhookRejectedError):
        verify_signature(b"{}", sign_body("", b"{}"), "")
    with pytest.raises(WebhookRejectedError):
        verify_handshake("subscribe", "", "1", expected_token="")


@pytest.mark.parametrize("challenge", ["é", "<script>", "", None, "12a"])
def test_handshake_rejects_non_numeric_challenge_and_non_ascii_token(challenge: str | None) -> None:
    with pytest.raises(WebhookRejectedError):
        verify_handshake("subscribe", "tok", challenge, expected_token="tok")
    with pytest.raises(WebhookRejectedError):
        verify_handshake("subscribe", "ték", "1", expected_token="tok")


def test_template_button_reply_is_the_owner_approval_path(recorded: Load) -> None:
    [e] = events(recorded, "template_button_reply")
    assert isinstance(e, WaInbound)
    assert e.kind == "button"
    assert e.interactive_id == "apr:01900000-0000-7000-8000-0000000000cc:ok"
    assert e.reply_to == "wamid.OUT0005"


def test_system_number_change_keeps_new_wa_id(recorded: Load) -> None:
    [e] = events(recorded, "system_number_change")
    assert isinstance(e, WaInbound)
    _, meta = to_message(e, company_id=uuid4(), raw_event_id=uuid4())
    assert (e.kind, meta["new_wa_id"]) == ("system", "4915550000002")


@pytest.mark.parametrize("message", [{**GOOD, "text": {}}, {**GOOD, "type": "image", "image": {"caption": "no id"}}])
def test_incomplete_payloads_become_unsupported(message: dict[str, object]) -> None:
    [e] = parse_webhook(_body([message]))
    assert isinstance(e, WaInbound)
    assert e.kind == "unsupported"


def test_identity_fallback_and_unroutable() -> None:
    no_meta = parse_webhook(_body([{**GOOD, "from": "4919912345678"}]))[0]
    assert isinstance(no_meta, WaInbound)
    msg, _ = to_message(no_meta, company_id=uuid4(), raw_event_id=uuid4())
    assert msg.sender_identity == "+4919912345678"
    [anon] = parse_webhook(_body([{k: v for k, v in GOOD.items() if k != "from"}]))
    assert isinstance(anon, WaInbound)
    with pytest.raises(UnroutableMessageError):
        to_message(anon, company_id=uuid4(), raw_event_id=uuid4())


def test_malformed_status_error_item_keeps_status() -> None:
    value = {
        "metadata": {"display_phone_number": "1", "phone_number_id": "2"},
        "statuses": [
            {"id": "wamid.S", "status": "failed", "timestamp": "1759737600", "errors": ["junk", {"code": 131026}]}
        ],
    }
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"id": "1", "changes": [{"field": "messages", "value": value}]}],
        }
    )
    [s] = parse_webhook(body.encode())
    assert isinstance(s, WaStatus)
    assert s.error_codes == [131026]


@pytest.mark.parametrize("fixture", ["text", "echo", "button_reply", "image_caption"])
def test_payload_round_trip(recorded: Load, fixture: str) -> None:
    from app.channels.whatsapp.inbound import event_from_payload, event_to_payload

    for event in events(recorded, fixture):
        if isinstance(event, WaStatus):
            continue
        payload = event_to_payload(event)
        assert json.loads(json.dumps(payload)) == payload
        assert event_from_payload(payload) == event


@pytest.mark.parametrize("payload", [{}, {"v": 2, "item": {}}, {"v": 1, "item": "x"}, {"v": 1, "item": {"id": "x"}}])
def test_bad_payloads_yield_none(payload: dict[str, object]) -> None:
    from app.channels.whatsapp.inbound import event_from_payload

    assert event_from_payload(payload) is None
