import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.channels.gmail.inbound import to_message
from app.channels.gmail.mime import parse_email
from app.channels.gmail.models import GmailMessage, parse_api_message
from app.contracts import Channel, Direction
from app.core.errors import UnroutableMessageError

Load = Callable[[str, str], bytes]
MAILBOX = "hausverwaltung@example.test"
WHEN = datetime(2025, 10, 6, 8, 0, tzinfo=UTC)


def gm(recorded: Load, name: str) -> GmailMessage:
    return parse_api_message(json.loads(recorded("gmail", name)))


def norm(recorded: Load, name: str):  # type: ignore[no-untyped-def]
    return to_message(gm(recorded, name), company_id=uuid4(), raw_event_id=uuid4(), mailbox=MAILBOX)


def test_api_message_model(recorded: Load) -> None:
    m = gm(recorded, "plain")
    assert (m.id, m.thread_id, m.history_id) == ("18c0000000000001", "thread-0001", 1001)
    assert m.label_ids == ["INBOX", "UNREAD"]
    assert m.internal_date == WHEN
    assert b"\r\nSubject: Heizung kaputt\r\n" in m.raw


def test_plain(recorded: Load) -> None:
    msg, meta, atts = norm(recorded, "plain")
    assert msg.channel is Channel.gmail
    assert msg.direction is Direction.inbound
    assert msg.sender_identity == "tenant-001@example.test"
    assert msg.thread_ref == "thread-0001"
    assert msg.provider_msg_id == "18c0000000000001"
    assert msg.sent_at == WHEN
    assert msg.text.startswith("Hallo,\ndie Heizung in Whg 3 ist seit gestern kalt.")
    assert meta["subject"] == "Heizung kaputt"
    assert meta["message_id"] == "<msg-0001@example.test>"
    assert meta["from_name"] == "Tenant 001"
    assert atts == []


def test_html_only_becomes_readable_text(recorded: Load) -> None:
    msg, _, _ = norm(recorded, "html_only")
    assert "Wasser tropft von der Decke" in msg.text
    assert "<" not in msg.text


PDF = b"%PDF-1.4\n% fake Nebenkostenabrechnung\n%%EOF\n"


def test_multipart_prefers_plain_and_keeps_pdf(recorded: Load) -> None:
    msg, _, atts = norm(recorded, "multipart_alt_mixed")
    assert msg.text == "Bitte prüfen Sie die Abrechnung im Anhang."
    [pdf] = atts
    assert (pdf.filename, pdf.mime_type, pdf.inline) == ("abrechnung.pdf", "application/pdf", False)
    assert pdf.data == PDF
    assert pdf.sha256 == hashlib.sha256(PDF).hexdigest()


def test_latin1_quoted_printable(recorded: Load) -> None:
    msg, _, _ = norm(recorded, "latin1_qp")
    assert msg.text == "Der Schlüssel für die Garage fehlt. Grüße aus Köln"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("german_quote", "Der Handwerker war noch nicht da."), ("outlook_quote", "Danke, passt so.")],
)
def test_quotes_stripped(recorded: Load, name: str, expected: str) -> None:
    msg, meta, _ = norm(recorded, name)
    assert msg.text == expected
    assert meta["quote_stripped"] is True


def test_reply_headers_kept(recorded: Load) -> None:
    _, meta, _ = norm(recorded, "german_quote")
    assert meta["in_reply_to"] == "<msg-0099@example.test>"


def test_inline_image_is_an_inline_attachment(recorded: Load) -> None:
    msg, _, atts = norm(recorded, "inline_image")
    assert msg.text == "Siehe Foto unten."
    [img] = atts
    assert (img.mime_type, img.inline, img.content_id) == ("image/png", True, "img1@example.test")


def test_attachment_only_has_placeholder_text(recorded: Load) -> None:
    msg, _, atts = norm(recorded, "attachment_only")
    assert msg.text == "[no text — 1 attachment: kuendigung.pdf]"
    assert [a.filename for a in atts] == ["kuendigung.pdf"]


def test_sent_by_owner_is_outbound_threaded(recorded: Load) -> None:
    msg, meta, _ = norm(recorded, "sent_by_owner")
    assert msg.direction is Direction.outbound
    assert msg.sender_identity == MAILBOX
    assert msg.thread_ref == "thread-0001"
    assert meta["to"] == ["tenant-001@example.test"]


def test_forged_from_self_is_not_trusted_as_owner(recorded: Load) -> None:
    msg, meta, _ = norm(recorded, "forged_from_self")
    assert msg.direction is Direction.inbound
    assert msg.sender_identity == MAILBOX  # the claimed address, recorded as an inbound claim
    assert meta["from_self_unsent"] is True


def test_missing_from_is_unroutable(recorded: Load) -> None:
    with pytest.raises(UnroutableMessageError):
        norm(recorded, "missing_from")


def test_parse_email_never_raises_on_garbage() -> None:
    parsed = parse_email(b"\x00\xff garbage without headers")
    assert parsed.from_addr is None
    assert isinstance(parsed.text, str)


def test_html_script_and_style_removed() -> None:
    raw = (
        b"From: a@example.test\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        b"<style>p{color:red}</style><script>alert(1)</script><p>Hallo</p>"
    )
    assert parse_email(raw).text.strip() == "Hallo"


@pytest.mark.parametrize("bad", [{}, {"id": "1"}, {"id": "1", "threadId": "t", "raw": "!!!", "internalDate": "1"}])
def test_bad_api_json_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        parse_api_message(bad)


# ---- review round 1 ------------------------------------------------------------------------------------------------

import time  # noqa: E402
from email.message import EmailMessage  # noqa: E402
from pathlib import Path  # noqa: E402

from syrupy.assertion import SnapshotAssertion  # noqa: E402

from app.channels.gmail import mime  # noqa: E402
from app.core.errors import IgnoredMessageError  # noqa: E402

FIXTURES = sorted(p.stem for p in (Path(__file__).parents[3] / "fixtures/recorded/gmail").glob("*.json"))


REJECTED = {"draft": IgnoredMessageError, "spam": IgnoredMessageError, "missing_from": UnroutableMessageError}


@pytest.mark.parametrize("fixture", FIXTURES)
def test_fixture_snapshot(recorded: Load, fixture: str, snapshot: SnapshotAssertion) -> None:
    if fixture in REJECTED:
        with pytest.raises(REJECTED[fixture]):
            norm(recorded, fixture)
        return
    msg, meta, atts = norm(recorded, fixture)
    view = {
        "direction": msg.direction.value,
        "sender": msg.sender_identity,
        "text": msg.text,
        "meta": {k: v for k, v in meta.items() if k != "history_id"},
        "attachments": [(a.filename, a.mime_type, len(a.data), a.sha256[:12], a.inline) for a in atts],
    }
    assert view == snapshot


@pytest.mark.parametrize("name", ["draft", "spam"])
def test_draft_and_spam_are_ignored(recorded: Load, name: str) -> None:
    with pytest.raises(IgnoredMessageError):
        norm(recorded, name)


@pytest.mark.parametrize(
    ("name", "must_contain"),
    [("gmail_forward", "Ich widerspreche der Mieterhöhung."), ("german_forward", "Jeden Abend Musik bis 2 Uhr.")],
)
def test_forwards_keep_forwarded_content(recorded: Load, name: str, must_contain: str) -> None:
    msg, meta, _ = norm(recorded, name)
    assert must_contain in msg.text
    assert "quote_stripped" not in meta or meta["quote_stripped"] is False


def test_attached_email_becomes_eml_and_quoted_text(recorded: Load) -> None:
    msg, _, atts = norm(recorded, "rfc822_attachment")
    assert "Keller steht unter Wasser, komme morgen." in msg.text
    assert [a.filename for a in atts] == ["forwarded.eml"]  # its keller.jpg stays inside the .eml
    assert atts[0].mime_type == "message/rfc822"


def test_apple_split_layout_keeps_all_text_and_photo(recorded: Load) -> None:
    msg, _, atts = norm(recorded, "apple_split")
    assert "Das Fenster klemmt." in msg.text
    assert "Und bitte auch das Fenster im Bad reparieren!" in msg.text
    assert [(a.filename, a.inline) for a in atts] == [("IMG_0001.jpeg", False)]


def test_calendar_invite_kept_as_attachment(recorded: Load) -> None:
    msg, _, atts = norm(recorded, "calendar_invite")
    [ics] = atts
    assert ics.mime_type == "text/calendar"
    assert ics.filename is not None
    assert ics.filename.endswith(".ics")
    assert "attachment" in msg.text


def test_apple_inline_photo_is_a_real_attachment(recorded: Load) -> None:
    msg, _, atts = norm(recorded, "apple_inline_photo")
    assert msg.text == "Hier das Foto."
    assert [(a.filename, a.inline) for a in atts] == [("IMG_0002.jpeg", False)]


def test_non_reply_with_von_lines_is_not_cut(recorded: Load) -> None:
    msg, _, _ = norm(recorded, "non_reply_with_von")
    assert "Von: Montag bis Freitag geht es bei mir." in msg.text


def test_metadata_fields(recorded: Load) -> None:
    _, meta, _ = norm(recorded, "plain")
    assert meta["to"] == [MAILBOX]
    assert meta["labels"] == ["INBOX", "UNREAD"]
    assert meta["from"] == "tenant-001@example.test"
    assert meta["history_id"] == 1001


# ---- hostile input -------------------------------------------------------------------------------------------------


def _nested(levels: int) -> bytes:
    head = b"From: a@example.test\r\nContent-Type: multipart/mixed; boundary=b0\r\n\r\n"
    body = b"".join(
        f"--b{i}\r\nContent-Type: multipart/mixed; boundary=b{i + 1}\r\n\r\n".encode() for i in range(levels)
    )
    return head + body + b"--b%d\r\nContent-Type: text/plain\r\n\r\ndeep\r\n" % levels


def test_nesting_beyond_depth_is_bounded() -> None:
    parsed = parse_email(_nested(30))
    assert f"nesting beyond depth {mime.MAX_DEPTH}" in parsed.skipped
    assert parsed.parse_error is False


def test_pathological_nesting_degrades_but_keeps_sender() -> None:
    parsed = parse_email(_nested(1000))
    assert parsed.parse_error is True
    assert parsed.from_addr == "a@example.test"
    assert parsed.text == "[unparseable email]"


def test_nul_and_surrogates_are_postgres_safe() -> None:
    raw = b"From: J\xfcrgen <j@example.test>\r\nSubject: =?utf-8?b?QQBC?=\r\n\r\nHal\x00lo"
    parsed = parse_email(raw)
    for value in (parsed.text, parsed.subject, parsed.from_name or ""):
        assert "\x00" not in value
        value.encode("utf-8")  # no lone surrogates
    assert parsed.text == "Hallo"


def test_header_injection_collapsed() -> None:
    msg = EmailMessage()
    msg["From"] = "a@example.test"
    msg["Subject"] = "=?utf-8?b?SGkNCkJjYzogZXZpbEB4LmNvbQ==?="
    msg.set_content("x")
    msg.add_attachment(b"x", maintype="application", subtype="pdf", filename="../../a.pdf")
    parsed = parse_email(msg.as_bytes())
    assert "\n" not in parsed.subject
    assert "\r" not in parsed.subject
    assert parsed.attachments[0].filename == "a.pdf"


@pytest.mark.parametrize("flood", [" " * 50_000 + "Am", "On " * 21_000, "Am " * 21_000, ("On " * 60 + "\n") * 300])
def test_quote_stripping_is_bounded_in_time(flood: str) -> None:
    raw = ("From: a@example.test\r\nSubject: Re: x\r\nIn-Reply-To: <x@y>\r\n\r\nHi " + flood).encode()
    started = time.monotonic()
    parse_email(raw)
    assert time.monotonic() - started < 2.0


def test_attachment_count_is_capped() -> None:
    msg = EmailMessage()
    msg["From"] = "a@example.test"
    msg.set_content("many")
    for i in range(mime.MAX_ATTACHMENTS + 10):
        msg.add_attachment(b"x", maintype="application", subtype="octet-stream", filename=f"f{i}.bin")
    parsed = parse_email(msg.as_bytes())
    assert len(parsed.attachments) == mime.MAX_ATTACHMENTS
    assert len(parsed.skipped) == 10


@pytest.mark.parametrize("value", ["99999999999999999999", "-1", "abc", "0"])
def test_internal_date_bounds(value: str) -> None:
    with pytest.raises(ValueError):
        parse_api_message({"id": "1", "threadId": "t", "internalDate": value, "raw": "eA"})


def test_gmail_message_json_round_trip(recorded: Load) -> None:
    m = gm(recorded, "latin1_qp")
    assert GmailMessage.model_validate_json(m.model_dump_json(by_alias=True)) == m


@pytest.mark.parametrize(
    ("ctype", "expected"),
    [
        ("app/x\x00y", "application/octet-stream"),
        ("image/j\xffpeg", "application/octet-stream"),
        ("IMAGE/JPEG", "image/jpeg"),
    ],
)
def test_attachment_mime_type_cleaned(ctype: str, expected: str) -> None:
    raw = (
        b"From: a@example.test\r\nContent-Type: multipart/mixed; boundary=x\r\n\r\n--x\r\n"
        b"Content-Type: text/plain\r\n\r\nhi\r\n--x\r\nContent-Type: " + ctype.encode("latin-1") + b"; name=a.bin\r\n"
        b"Content-Disposition: attachment; filename=a.bin\r\n\r\ndata\r\n--x--\r\n"
    )
    [att] = parse_email(raw).attachments
    assert att.mime_type == expected


def test_long_references_chain_kept_whole() -> None:
    refs = " ".join(f"<id{i}@example.test>" for i in range(300))
    msg = EmailMessage()
    msg["From"] = "a@example.test"
    msg["References"] = refs
    msg.set_content("x")
    parsed = parse_email(msg.as_bytes())
    assert parsed.references is not None
    assert parsed.references.endswith("<id299@example.test>")


def test_empty_plain_falls_back_to_html() -> None:
    msg = EmailMessage()
    msg["From"] = "a@example.test"
    msg.set_content("   ")
    msg.add_alternative("<p>Echter Inhalt</p>", subtype="html")
    assert parse_email(msg.as_bytes()).text == "Echter Inhalt"
