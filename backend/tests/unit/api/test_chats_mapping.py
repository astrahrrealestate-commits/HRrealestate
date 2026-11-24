"""How a stored message and attachment become the Chats API shapes: safe download types, send state, error cap."""

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest

from app.api.chats.routes import _attachment, _to_message
from app.contracts import Channel, Direction
from app.db.enums import DeliveryStatus
from app.db.models.ingestion import AttachmentRow, MessageRow
from app.storage.memory import MemoryStorage


def _att(mime: str, name: str | None = "f.bin") -> AttachmentRow:
    return AttachmentRow(
        id=uuid4(), company_id=uuid4(), message_id=uuid4(), s3_key="media/a/ab/abc", mime_type=mime, filename=name,
        size_bytes=3, sha256="ab" * 32,
    )  # fmt: skip


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


@pytest.mark.parametrize("mime", ["text/html", "image/svg+xml", "application/xml", "application/x-unknown"])
def test_unsafe_attachment_types_are_forced_to_a_download(mime: str) -> None:
    query = _query(_attachment(_att(mime, "evil.html"), MemoryStorage()).url)
    assert query["response-content-type"] == ["application/octet-stream"]
    assert query["response-content-disposition"][0].startswith("attachment;")
    assert "evil.html" in query["response-content-disposition"][0]


@pytest.mark.parametrize("mime", ["image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"])
def test_safe_attachment_types_stay_inline(mime: str) -> None:
    query = _query(_attachment(_att(mime), MemoryStorage()).url)
    assert query["response-content-type"] == [mime]
    assert query["response-content-disposition"][0].startswith("inline;")


def test_mime_parameters_and_case_do_not_defeat_the_allowlist() -> None:
    assert _query(_attachment(_att("IMAGE/PNG; charset=x"), MemoryStorage()).url)["response-content-type"] == [
        "image/png"
    ]
    assert _query(_attachment(_att("text/html; charset=utf-8"), MemoryStorage()).url)["response-content-type"] == [
        "application/octet-stream"
    ]


def _row(**kw: Any) -> MessageRow:
    fields: dict[str, Any] = {
        "id": uuid4(), "company_id": uuid4(), "raw_event_id": uuid4(), "channel": Channel.whatsapp,
        "provider_msg_id": "p", "thread_ref": "+31612345678", "sender_identity": "+31612345678",
        "direction": Direction.outbound, "sent_at": datetime(2026, 11, 1, tzinfo=UTC), "text": "hi",
        "delivery_status": None, "meta": {},
    }  # fmt: skip
    fields.update(kw)
    return MessageRow(**fields)


def _out(row: MessageRow) -> Any:
    return _to_message(row, [], (False, None), None)


def test_pending_only_for_a_row_our_send_path_created() -> None:
    assert _out(_row(meta={"client_msg_id": "c1"})).pending is True


def test_business_app_echo_and_legacy_outbound_rows_are_not_pending() -> None:
    assert _out(_row(meta={"echo": True})).pending is False
    assert _out(_row(meta={})).pending is False


def test_inbound_and_statused_or_failed_rows_are_never_pending() -> None:
    assert _out(_row(direction=Direction.inbound, meta={"client_msg_id": "c1"})).pending is False
    assert _out(_row(delivery_status=DeliveryStatus.sent, meta={"client_msg_id": "c1"})).pending is False
    assert _out(_row(meta={"client_msg_id": "c1", "send_error": "window closed"})).pending is False


def test_send_error_is_capped_at_200_characters() -> None:
    message = _out(_row(delivery_status=DeliveryStatus.failed, meta={"send_error": "e" * 500}))
    assert message.error == "e" * 200
    assert _out(_row(meta={"send_error": "short"})).error == "short"
