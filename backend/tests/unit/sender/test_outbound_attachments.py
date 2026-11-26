"""Unit tests for outbound Gmail MIME & WhatsApp media attachments (1 upload -> 3 places)."""

from email import message_from_bytes, policy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.channels.gmail.drafts import build_mime
from app.channels.whatsapp import payloads as wa_payloads
from app.contracts import Channel, DraftRequest, MailAttachment
from app.sender import delivery
from app.sender.plan import Plan


def test_build_mime_attaches_mail_attachments() -> None:
    req = DraftRequest(
        idempotency_key="idem-1",
        thread_id="thread-1",
        to="tenant@example.com",
        subject="Rental contract",
        body="See attached contract.",
        attachments=(
            MailAttachment(filename="lease.pdf", mime_type="application/pdf", content=b"%PDF-1.4\ntest"),
            MailAttachment(filename="photo.png", mime_type="image/png", content=b"\x89PNG\r\n\x1a\n"),
        ),
    )
    raw = build_mime("harjot@example.com", req)
    msg = message_from_bytes(raw, policy=policy.default)
    attachments = list(msg.iter_attachments())
    assert len(attachments) == 2
    assert attachments[0].get_filename() == "lease.pdf"
    assert attachments[0].get_content_type() == "application/pdf"
    assert attachments[0].get_payload(decode=True) == b"%PDF-1.4\ntest"
    assert attachments[1].get_filename() == "photo.png"
    assert attachments[1].get_content_type() == "image/png"


def test_whatsapp_media_payload_validation() -> None:
    doc = wa_payloads.media(
        "+31612345678",
        kind="document",
        link="https://s3.example.com/file.pdf?sig=1",
        filename="contract.pdf",
    )
    assert doc["type"] == "document"
    assert doc["document"]["link"] == "https://s3.example.com/file.pdf?sig=1"
    assert doc["document"]["filename"] == "contract.pdf"

    img = wa_payloads.media("+31612345678", kind="image", link="https://s3.example.com/photo.jpg")
    assert img["type"] == "image"
    assert img["image"] == {"link": "https://s3.example.com/photo.jpg"}

    with pytest.raises(ValueError, match="https://"):
        wa_payloads.media("+31612345678", kind="document", link="http://insecure.local/file.pdf")


class _FakeStorage:
    def __init__(self, objects: dict[str, bytes], urls: dict[str, str]) -> None:
        self.objects = objects
        self.urls = urls

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def presigned_url(
        self, key: str, ttl_seconds: int = 300, *, content_type: str | None = None, disposition: str | None = None
    ) -> str:
        return self.urls[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class _FakeGmailAdapter:
    def __init__(self) -> None:
        self.sent: list[DraftRequest] = []
        self.drafted: list[DraftRequest] = []

    def send_reply(self, req: DraftRequest) -> str:
        self.sent.append(req)
        return "gmail-sent-1"

    def create_draft(self, req: DraftRequest) -> str:
        self.drafted.append(req)
        return "gmail-draft-1"


class _FakeWhatsApp:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def send(self, payload: dict) -> str:
        self.payloads.append(payload)
        return f"wa-msg-{len(self.payloads)}"


def test_deliver_attaches_bytes_to_gmail_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    company_id = uuid4()
    att_id = uuid4()
    row = SimpleNamespace(
        id=att_id,
        company_id=company_id,
        s3_key="attachments/doc.pdf",
        filename="doc.pdf",
        mime_type="application/pdf",
        size_bytes=12,
    )
    monkeypatch.setattr(delivery, "_load_attachments", lambda deps, plan: [row])

    storage = _FakeStorage({"attachments/doc.pdf": b"hello-attach"}, {})
    gmail = _FakeGmailAdapter()
    deps = delivery.SenderDeps(
        engine=None,  # type: ignore[arg-type]
        whatsapp=_FakeWhatsApp(),  # type: ignore[arg-type]
        gmail_drafts=lambda _m: gmail,  # type: ignore[arg-type,return-value]
        gmail_sender=lambda _m: gmail,  # type: ignore[arg-type,return-value]
        storage=storage,  # type: ignore[arg-type]
    )
    plan = Plan(
        channel=Channel.gmail,
        target="tenant@example.com",
        mailbox="harjot@example.com",
        tenant_send=True,
        company_id=company_id,
        attachment_ids=(att_id,),
        draft=DraftRequest(
            idempotency_key="idem-2",
            thread_id="thread-2",
            to="tenant@example.com",
            subject="Re: Hi",
            body="Attached.",
        ),
    )
    ref = delivery.deliver(deps, plan)
    assert ref == "gmail-sent-1"
    assert len(gmail.sent) == 1
    assert gmail.sent[0].attachments == (
        MailAttachment(filename="doc.pdf", mime_type="application/pdf", content=b"hello-attach"),
    )


def test_deliver_sends_whatsapp_media_after_text(monkeypatch: pytest.MonkeyPatch) -> None:
    company_id = uuid4()
    att_doc = uuid4()
    att_big_img = uuid4()
    att_http_doc = uuid4()
    rows = [
        SimpleNamespace(
            id=att_doc,
            company_id=company_id,
            s3_key="k/doc.pdf",
            filename="doc.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
        ),
        SimpleNamespace(
            id=att_big_img,
            company_id=company_id,
            s3_key="k/big.png",
            filename="big.png",
            mime_type="image/png",
            size_bytes=17 * 1024 * 1024,  # exceeds 16 MB WhatsApp image limit -> skipped
        ),
        SimpleNamespace(
            id=att_http_doc,
            company_id=company_id,
            s3_key="k/local.pdf",
            filename="local.pdf",
            mime_type="application/pdf",
            size_bytes=512,  # http:// URL -> skipped
        ),
    ]
    monkeypatch.setattr(delivery, "_load_attachments", lambda deps, plan: rows)

    storage = _FakeStorage(
        {},
        {
            "k/doc.pdf": "https://files.example.com/doc.pdf",
            "k/big.png": "https://files.example.com/big.png",
            "k/local.pdf": "http://localhost:9000/local.pdf",
        },
    )
    wa = _FakeWhatsApp()
    deps = delivery.SenderDeps(
        engine=None,  # type: ignore[arg-type]
        whatsapp=wa,  # type: ignore[arg-type]
        gmail_drafts=lambda _m: _FakeGmailAdapter(),  # type: ignore[arg-type,return-value]
        storage=storage,  # type: ignore[arg-type]
    )
    text_payload = wa_payloads.text("+31612345678", "Zie bijlage.")
    plan = Plan(
        channel=Channel.whatsapp,
        target="+31612345678",
        tenant_send=True,
        company_id=company_id,
        attachment_ids=(att_doc, att_big_img, att_http_doc),
        whatsapp=text_payload,
    )
    ref = delivery.deliver(deps, plan)
    assert ref == "wa-msg-1"
    assert len(wa.payloads) == 2
    assert wa.payloads[0] == text_payload
    assert wa.payloads[1]["type"] == "document"
    assert wa.payloads[1]["document"]["link"] == "https://files.example.com/doc.pdf"
    assert wa.payloads[1]["document"]["filename"] == "doc.pdf"
