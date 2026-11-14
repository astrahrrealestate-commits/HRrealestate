"""WhatsAppOutbound / WhatsAppMedia contracts: fake and HTTP adapters (Meta + 360dialog via respx) behave alike."""

import base64
import hashlib
from collections.abc import Iterator

import httpx
import pytest
import respx

from app.channels.whatsapp import payloads
from app.channels.whatsapp.media import (
    FakeWhatsAppMedia,
    HttpWhatsAppMedia,
    MediaBlob,
    WhatsAppMedia,
    WhatsAppMediaError,
)
from app.channels.whatsapp.outbound import (
    FakeWhatsAppOutbound,
    HttpWhatsAppOutbound,
    WhatsAppOutbound,
    WhatsAppSendError,
)
from app.core.errors import NotFoundError

META = "https://graph.facebook.com/v21.0"
D360 = "https://waba-v2.360dialog.io"
OWNER = "+4915550000100"
OK_BODY = {
    "messaging_product": "whatsapp",
    "contacts": [{"wa_id": "4915550000100"}],
    "messages": [{"id": "wamid.SENT1"}],
}


@pytest.fixture(params=["fake", "meta", "360dialog"])
def outbound(request: pytest.FixtureRequest) -> Iterator[WhatsAppOutbound]:
    if request.param == "fake":
        yield FakeWhatsAppOutbound()
        return
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{META}/100000000000001/messages").mock(return_value=httpx.Response(200, json=OK_BODY))
        router.post(f"{D360}/messages").mock(return_value=httpx.Response(200, json=OK_BODY))
        if request.param == "meta":
            yield HttpWhatsAppOutbound.cloud_api(META, "100000000000001", "tok")
        else:
            yield HttpWhatsAppOutbound.dialog360(D360, "d360key")


def test_send_returns_provider_message_id(outbound: WhatsAppOutbound) -> None:
    assert outbound.send(payloads.text(OWNER, "Briefing")).startswith("wamid.")


def test_send_rejects_unbuilt_payload(outbound: WhatsAppOutbound) -> None:
    with pytest.raises(ValueError):
        outbound.send({"to": "4915550000100", "text": {"body": "x"}})


def test_fake_records_payloads_in_order() -> None:
    fake = FakeWhatsAppOutbound()
    first = fake.send(payloads.text(OWNER, "a"))
    second = fake.send(payloads.buttons(OWNER, "b", [payloads.Button("apr:1:ok", "OK")]))
    assert [s.wamid for s in fake.sent] == [first, second]
    assert first != second
    assert fake.sent[1].payload["interactive"]["type"] == "button"


@respx.mock
def test_http_sends_exact_json_and_auth_per_provider() -> None:
    meta = respx.post(f"{META}/100000000000001/messages").mock(return_value=httpx.Response(200, json=OK_BODY))
    d360 = respx.post(f"{D360}/messages").mock(return_value=httpx.Response(200, json=OK_BODY))
    body = payloads.text(OWNER, "Hallo")
    HttpWhatsAppOutbound.cloud_api(META, "100000000000001", "tok").send(body)
    HttpWhatsAppOutbound.dialog360(D360, "d360key").send(body)
    assert meta.calls.last.request.headers["Authorization"] == "Bearer tok"
    assert d360.calls.last.request.headers["D360-API-KEY"] == "d360key"
    assert "Authorization" not in d360.calls.last.request.headers
    assert meta.calls.last.request.read() == d360.calls.last.request.read()


@pytest.mark.parametrize(
    ("status", "content", "retryable", "maybe_sent", "code"),
    [
        (429, {"error": {"code": 130429, "message": "Rate limit hit"}}, True, False, 130429),
        (400, {"error": {"code": 131048, "message": "Spam rate limit hit"}}, True, False, 131048),
        (500, {"error": {"code": 1, "message": "Unknown"}}, False, True, 1),
        (503, None, False, True, None),
        (400, {"error": {"code": 131026, "message": "Message undeliverable"}}, False, False, 131026),
        (400, {"error": {"code": 131047, "message": "Re-engagement message"}}, False, False, 131047),
        (401, {"error": {"code": 190, "message": "Invalid OAuth access token"}}, False, False, 190),
        (401, {"error": "Unauthorized"}, False, False, None),
        (502, ["not", "an", "object"], False, True, None),
        (400, "plain text body", False, False, None),
    ],
)
@respx.mock
def test_http_error_mapping(status: int, content: object, retryable: bool, maybe_sent: bool, code: int | None) -> None:
    response = (
        httpx.Response(status, text=content) if isinstance(content, str) else httpx.Response(status, json=content)
    )
    respx.post(f"{META}/1/messages").mock(return_value=response)
    with pytest.raises(WhatsAppSendError) as exc:
        HttpWhatsAppOutbound.cloud_api(META, "1", "tok").send(payloads.text(OWNER, "x"))
    assert (exc.value.retryable, exc.value.maybe_sent, exc.value.code, exc.value.http_status) == (
        retryable,
        maybe_sent,
        code,
        status,
    )


@pytest.mark.parametrize(
    ("side_effect", "retryable", "maybe_sent"),
    [
        (httpx.ConnectError("refused"), True, False),
        (httpx.ConnectTimeout("slow connect"), True, False),
        (httpx.ReadTimeout("slow read"), False, True),
        (httpx.RemoteProtocolError("reset"), False, True),
    ],
)
@respx.mock
def test_transport_errors_split_not_sent_vs_maybe_sent(
    side_effect: Exception, retryable: bool, maybe_sent: bool
) -> None:
    respx.post(f"{META}/1/messages").mock(side_effect=side_effect)
    with pytest.raises(WhatsAppSendError) as exc:
        HttpWhatsAppOutbound.cloud_api(META, "1", "tok").send(payloads.text(OWNER, "x"))
    assert (exc.value.retryable, exc.value.maybe_sent) == (retryable, maybe_sent)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"messages": []}),
        httpx.Response(200, text="<html>ok</html>"),
        httpx.Response(200, json=["x"]),
        httpx.Response(200, json={"messages": [{"id": 5}]}),
    ],
)
@respx.mock
def test_malformed_2xx_is_maybe_sent_never_retryable(response: httpx.Response) -> None:
    respx.post(f"{META}/1/messages").mock(return_value=response)
    with pytest.raises(WhatsAppSendError) as exc:
        HttpWhatsAppOutbound.cloud_api(META, "1", "tok").send(payloads.text(OWNER, "x"))
    assert (exc.value.retryable, exc.value.maybe_sent) == (False, True)


# ---- media -------------------------------------------------------------------------------------------------------

JPEG = b"\xff\xd8\xff\xe0 fake jpeg"
SHA = hashlib.sha256(JPEG).hexdigest()
LOOKASIDE = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=MEDIA0002"


@pytest.fixture(params=["fake", "meta", "360dialog"])
def media(request: pytest.FixtureRequest) -> Iterator[WhatsAppMedia]:
    if request.param == "fake":
        yield FakeWhatsAppMedia({"MEDIA0002": MediaBlob(JPEG, "image/jpeg")})
        return
    with respx.mock(assert_all_called=False) as router:
        info = {"url": LOOKASIDE, "mime_type": "image/jpeg", "sha256": SHA, "file_size": len(JPEG), "id": "MEDIA0002"}
        base = META if request.param == "meta" else D360
        router.get(f"{base}/MEDIA0002").mock(return_value=httpx.Response(200, json=info))
        router.get(f"{base}/MISSING").mock(return_value=httpx.Response(404, json={"error": {"code": 100}}))
        if request.param == "meta":
            router.get(LOOKASIDE).mock(return_value=httpx.Response(200, content=JPEG))
        else:  # lookaside deliberately unmocked: the rewrite to the 360dialog host must happen
            router.get(f"{D360}/whatsapp_business/attachments/", params={"mid": "MEDIA0002"}).mock(
                return_value=httpx.Response(200, content=JPEG)
            )
        if request.param == "meta":
            yield HttpWhatsAppMedia.cloud_api(META, "tok")
        else:
            yield HttpWhatsAppMedia.dialog360(D360, "d360key")


def test_media_download(media: WhatsAppMedia) -> None:
    blob = media.download("MEDIA0002")
    assert (blob.data, blob.mime_type, blob.sha256) == (JPEG, "image/jpeg", SHA)


def test_media_missing(media: WhatsAppMedia) -> None:
    with pytest.raises(NotFoundError):
        media.download("MISSING")


@respx.mock
def test_360dialog_rewrites_host_keeps_query_and_uses_api_key() -> None:
    info = {"url": LOOKASIDE, "mime_type": "image/jpeg", "sha256": SHA}
    respx.get(f"{D360}/MEDIA0002").mock(return_value=httpx.Response(200, json=info))
    route = respx.get(f"{D360}/whatsapp_business/attachments/").mock(return_value=httpx.Response(200, content=JPEG))
    HttpWhatsAppMedia.dialog360(D360, "d360key").download("MEDIA0002")
    request = route.calls.last.request
    assert request.url.params["mid"] == "MEDIA0002"
    assert request.headers["D360-API-KEY"] == "d360key"
    assert all("fbsbx" not in str(c.request.url) for c in respx.calls)


@respx.mock
def test_media_integrity_size_and_host_checks() -> None:
    url = "https://lookaside.fbsbx.com/x"
    cases = {
        "BAD": {"url": url, "mime_type": "image/jpeg", "sha256": "0" * 64},
        "HUGE": {"url": url, "mime_type": "video/mp4", "file_size": 10**10},
        "EVIL": {"url": "https://attacker.example/x", "mime_type": "image/jpeg"},
        "B64": {
            "url": url,
            "mime_type": "image/jpeg",
            "sha256": base64.b64encode(hashlib.sha256(JPEG).digest()).decode(),
        },
        "UPPER": {"url": url, "mime_type": "image/jpeg", "sha256": SHA.upper()},
    }
    for media_id, info in cases.items():
        respx.get(f"{META}/{media_id}").mock(return_value=httpx.Response(200, json=info))
    respx.get(url).mock(return_value=httpx.Response(200, content=JPEG))
    adapter = HttpWhatsAppMedia.cloud_api(META, "tok")
    for media_id, fragment in [("BAD", "sha256"), ("HUGE", "too large"), ("EVIL", "refusing")]:
        with pytest.raises(WhatsAppMediaError, match=fragment) as exc:
            adapter.download(media_id)
        assert exc.value.retryable is False
    assert adapter.download("B64").data == JPEG
    assert adapter.download("UPPER").data == JPEG
    with pytest.raises(WhatsAppMediaError):
        adapter.download("../../etc")


@respx.mock
def test_media_body_cap_without_file_size_and_transient_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.channels.whatsapp.media as media_module

    monkeypatch.setattr(media_module, "MAX_MEDIA_BYTES", 8)
    url = "https://lookaside.fbsbx.com/big"
    respx.get(f"{META}/NOSIZE").mock(return_value=httpx.Response(200, json={"url": url, "mime_type": "image/jpeg"}))
    respx.get(url).mock(return_value=httpx.Response(200, content=b"0123456789"))
    respx.get(f"{META}/DOWN").mock(return_value=httpx.Response(503))
    adapter = HttpWhatsAppMedia.cloud_api(META, "tok")
    with pytest.raises(WhatsAppMediaError, match="too large"):
        adapter.download("NOSIZE")
    with pytest.raises(WhatsAppMediaError) as exc:
        adapter.download("DOWN")
    assert exc.value.retryable is True


@respx.mock
def test_media_redirect_empty_and_bad_size_are_typed() -> None:
    url = "https://lookaside.fbsbx.com/r"
    respx.get(f"{META}/REDIR").mock(return_value=httpx.Response(200, json={"url": url, "mime_type": "image/jpeg"}))
    respx.get(url).mock(return_value=httpx.Response(302, headers={"location": "https://elsewhere.example/x"}))
    respx.get(f"{META}/SIZE").mock(return_value=httpx.Response(200, json={"url": url, "file_size": "lots"}))
    empty = "https://lookaside.fbsbx.com/empty"
    respx.get(f"{META}/EMPTY").mock(return_value=httpx.Response(200, json={"url": empty, "mime_type": "image/jpeg"}))
    respx.get(empty).mock(return_value=httpx.Response(200, content=b""))
    adapter = HttpWhatsAppMedia.cloud_api(META, "tok")
    for media_id, retryable in [("REDIR", False), ("SIZE", False), ("EMPTY", True)]:
        with pytest.raises(WhatsAppMediaError) as exc:
            adapter.download(media_id)
        assert exc.value.retryable is retryable, media_id
