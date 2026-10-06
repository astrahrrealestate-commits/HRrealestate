from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts import Attachment, Channel, Direction, Message, normalise_identity

BASE: dict[str, Any] = {
    "channel": Channel.whatsapp,
    "provider_msg_id": "wamid.TEST1",
    "thread_ref": None,
    "direction": Direction.inbound,
    "sent_at": datetime(2026, 1, 1, tzinfo=UTC),
    "text": "Heizung kaputt",
    "raw_event_id": uuid4(),
    "company_id": uuid4(),
}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0151 2345 6789", "+4915123456789"),
        ("+49 (151) 2345-6789", "+4915123456789"),
        ("  Tenant@Example.DE ", "tenant@example.de"),
        ("4915123456789", "+4915123456789"),  # WhatsApp wa_id form: digits, no "+"
        ("447911123456", "+447911123456"),
        ("905321234567", "+905321234567"),
        ("０１５１２３４５６７８９", "+4915123456789"),  # full-width digits are not a bare WhatsApp id
    ],
)
def test_identity_normalised(raw: str, expected: str) -> None:
    assert normalise_identity(raw) == expected
    assert Message(**BASE, sender_identity=raw).sender_identity == expected


@pytest.mark.parametrize("raw", ["hello", "+49 1", "", "a@", "@b.de"])
def test_identity_rejected(raw: str) -> None:
    with pytest.raises(ValidationError):
        Message(**BASE, sender_identity=raw)


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValidationError):
        Message(**{**BASE, "sent_at": datetime(2026, 1, 1)}, sender_identity="+4915123456789")  # noqa: DTZ001


def test_round_trip_and_frozen() -> None:
    att = Attachment(s3_key="k", mime_type="application/pdf", filename="a.pdf", size_bytes=10, sha256="a" * 64)
    m = Message(**BASE, sender_identity="+4915123456789", attachments=[att])
    assert Message.model_validate_json(m.model_dump_json()) == m
    with pytest.raises(ValidationError):
        m.text = "x"  # type: ignore[misc]


@pytest.mark.parametrize("kw", [{"size_bytes": -1}, {"sha256": "XYZ"}, {"sha256": "a" * 63}])
def test_attachment_bounds(kw: dict[str, Any]) -> None:
    base: dict[str, Any] = {
        "s3_key": "k",
        "mime_type": "image/jpeg",
        "filename": None,
        "size_bytes": 1,
        "sha256": "a" * 64,
    }
    with pytest.raises(ValidationError):
        Attachment(**{**base, **kw})


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        Message(**BASE, sender_identity="+4915123456789", surprise=1)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+4919912345678", "+4919912345678"),
        ("4919912345678", "+4919912345678"),
        ("+49 199 1234-5678", "+4919912345678"),
    ],
)
def test_unknown_range_in_known_country_accepted(raw: str, expected: str) -> None:
    assert normalise_identity(raw) == expected


@pytest.mark.parametrize("raw", ["1234567", "+1234567", "+999123456789", "+4901511234567", "+49123"])
def test_implausible_international_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalise_identity(raw)
