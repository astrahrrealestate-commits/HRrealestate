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


_JUST_UNDER_CAP = ("On " * 60 + "\n") * (mime.QUOTE_STRIP_MAX_CHARS // 181 - 1)  # worst case the parser still sees


@pytest.mark.parametrize("flood", [" " * 50_000 + "Am", "On " * 21_000, "Am " * 21_000, _JUST_UNDER_CAP])
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


def test_meta_records_the_receiving_mailbox_lowercased(recorded: Load) -> None:
    _, meta, _ = to_message(gm(recorded, "plain"), company_id=uuid4(), raw_event_id=uuid4(), mailbox=MAILBOX.upper())
    assert meta["mailbox"] == MAILBOX


# ---- forwards from the owner's own address ------------------------------------------------------------------------

OWNER = "harjot.owner@example.test"
INLINE_FWD = (
    f"From: Harjot <{OWNER}>\r\nTo: {MAILBOX}\r\nSubject: Fwd: Heizung kaputt\r\n\r\n"
    "Zie hieronder.\r\n\r\n---------- Forwarded message ---------\r\n"
    "From: Tenant 001 <tenant-001@example.test>\r\nDate: Mon, 6 Oct 2025 at 08:00\r\n"
    "Subject: Heizung kaputt\r\nTo: <harjot.owner@example.test>\r\n\r\nDie Heizung ist kalt.\r\n"
).encode()
DUTCH_FWD = INLINE_FWD.replace(b"Forwarded message", b"Doorgestuurd bericht").replace(b"From: Tenant", b"Van: Tenant")


def forwarded(  # type: ignore[no-untyped-def]
    raw: bytes,
    forwarders: frozenset[str] = frozenset({OWNER}),
    labels: tuple[str, ...] = ("INBOX",),
    own_addresses: frozenset[str] = frozenset(),
):
    api = {"id": "f1", "threadId": "t1", "internalDate": str(int(WHEN.timestamp() * 1000)), "labelIds": list(labels)}
    import base64

    api["raw"] = base64.urlsafe_b64encode(raw).decode()
    extra = {"own_addresses": own_addresses} if own_addresses else {}
    return to_message(
        parse_api_message(api),
        company_id=uuid4(),
        raw_event_id=uuid4(),
        mailbox=MAILBOX,
        forwarders=forwarders,
        **extra,
    )


@pytest.mark.parametrize("raw", [INLINE_FWD, DUTCH_FWD])
def test_owner_forward_is_attributed_to_the_original_sender(raw: bytes) -> None:
    msg, meta, _ = forwarded(raw)
    assert msg.sender_identity == "tenant-001@example.test"
    assert meta["from"] == "tenant-001@example.test"
    assert meta["from_name"] == "Tenant 001"
    assert meta["forwarded_by"] == OWNER
    assert "Die Heizung ist kalt." in msg.text


def test_forward_from_a_stranger_keeps_the_forwarder() -> None:
    msg, meta, _ = forwarded(INLINE_FWD, forwarders=frozenset())
    assert msg.sender_identity == OWNER
    assert "forwarded_by" not in meta


def test_owner_mail_without_a_forward_stays_the_owner() -> None:
    msg, _, _ = forwarded(f"From: {OWNER}\r\nSubject: hi\r\n\r\nNiets doorgestuurd.\r\n".encode())
    assert msg.sender_identity == OWNER


def test_forward_of_another_owner_address_is_not_remapped() -> None:
    raw = INLINE_FWD.replace(b"tenant-001@example.test", OWNER.encode())
    msg, _, _ = forwarded(raw)
    assert msg.sender_identity == OWNER


# ---- Reply-To names the real sender -------------------------------------------------------------------------------

JAN = "jan@example.test"


def replied(  # type: ignore[no-untyped-def]
    reply_to: str,
    *,
    sender: str = f"Harjot <{OWNER}>",
    labels: tuple[str, ...] = ("INBOX",),
    body: str = "Hoi",
    own_addresses: frozenset[str] = frozenset(),
):
    raw = f"From: {sender}\r\nReply-To: {reply_to}\r\nTo: {MAILBOX}\r\nSubject: Lekkage\r\n\r\n{body}\r\n".encode()
    return forwarded(raw, labels=labels, own_addresses=own_addresses)


@pytest.mark.parametrize("sender", [f"Harjot <{OWNER}>", "Contact Form <noreply@forms.example.test>"])
def test_reply_to_is_the_sender_whoever_the_from_is(sender: str) -> None:
    msg, meta, _ = replied(f"Jan de Vries <{JAN.title()}>", sender=sender)
    assert msg.sender_identity == JAN
    assert (meta["from"], meta["from_name"]) == (JAN, "Jan de Vries")
    assert meta["header_from"] == sender.split("<")[1].rstrip(">")


def test_reply_to_without_a_name_never_borrows_the_from_name() -> None:
    _, meta, _ = replied(JAN)
    assert meta["from"] == JAN
    assert "from_name" not in meta


def test_reply_to_equal_to_from_keeps_the_from_name() -> None:
    msg, meta, _ = replied(JAN, sender=f"Jan de Vries <{JAN}>")
    assert (msg.sender_identity, meta["from_name"]) == (JAN, "Jan de Vries")
    assert "header_from" not in meta


@pytest.mark.parametrize("reply_to", [OWNER, MAILBOX, "not-an-address", "broken@nodot", "undisclosed-recipients:;"])
def test_unusable_reply_to_falls_back_to_from(reply_to: str) -> None:
    msg, meta, _ = replied(reply_to, sender=f"Piet <{JAN}>")
    assert (msg.sender_identity, meta["from_name"]) == (JAN, "Piet")
    assert "header_from" not in meta


def test_first_reply_to_outside_the_team_wins() -> None:
    msg, _, _ = replied(f"{OWNER}, {MAILBOX}, Jan <{JAN}>, other@example.test")
    assert msg.sender_identity == JAN


def test_reply_to_beats_the_forwarded_block() -> None:
    quoted = "---------- Forwarded message ---------\r\nFrom: Other <other@example.test>\r\n\r\nx"
    msg, meta, _ = replied(JAN, body=quoted)
    assert msg.sender_identity == JAN
    assert "forwarded_by" not in meta


def test_sent_mail_ignores_reply_to() -> None:
    msg, meta, _ = replied(JAN, sender=MAILBOX, labels=("SENT",))
    assert (msg.direction, msg.sender_identity) == (Direction.outbound, MAILBOX)
    assert meta["from"] == MAILBOX
    assert "header_from" not in meta


def test_forged_from_self_stays_flagged_with_a_reply_to() -> None:
    _, meta, _ = replied(JAN, sender=MAILBOX)
    assert meta["from_self_unsent"] is True


def test_unparseable_body_still_honours_reply_to(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(raw: bytes) -> None:
        raise RecursionError

    monkeypatch.setattr(mime, "_parse", boom)
    msg, meta, _ = replied(f"Jan <{JAN}>", sender="Form <noreply@forms.example.test>")
    assert (msg.sender_identity, meta["from_name"], meta["parse_error"]) == (JAN, "Jan", True)


@pytest.mark.parametrize(
    "reply_to",
    ["onderhoud@company.example.test", "hausverwaltung+web@example.test", "harjot.owner+x@example.test"],
)
def test_other_company_addresses_and_plus_aliases_are_not_the_sender(reply_to: str) -> None:
    msg, _, _ = replied(reply_to, sender=f"Piet <{JAN}>", own_addresses=frozenset({"onderhoud@company.example.test"}))
    assert msg.sender_identity == JAN


def test_a_chat_style_reply_to_is_not_an_email_sender() -> None:
    msg, _, _ = replied("users/abc@nodot", sender=f"Piet <{JAN}>")
    assert msg.sender_identity == JAN


def test_sent_forward_stays_attributed_to_from() -> None:
    quoted = "---------- Forwarded message ---------\r\nFrom: Other <other@example.test>\r\n\r\nx"
    _, meta, _ = replied(JAN, labels=("SENT",), body=quoted)
    assert meta["from"] == OWNER
    assert "forwarded_by" not in meta
