from datetime import UTC, datetime
from email import message_from_bytes, policy

from app.dev import mock_content as mc
from app.dev.real_mail import MAILS, _header_id, _raw


def test_every_mock_mail_has_a_distinct_key_and_replies_point_backwards() -> None:
    keys = [m.key for m in MAILS]
    assert len(set(keys)) == len(keys)
    for n, mail in enumerate(MAILS):
        assert mail.reply_to is None or mail.reply_to in keys[:n]


def test_mock_attachments_exist_and_known_senders_match_the_directory() -> None:
    known = {p.email for p in mc.PEOPLE if p.email}
    for mail in MAILS:
        assert mail.attachment is None or mail.attachment in mc.DOCUMENTS
    assert {"sanne.devries@example.test", "info@bakker-loodgieters.example.test"} <= {m.sender for m in MAILS} & known


def test_raw_mail_is_threaded_by_header_and_carries_the_pdf() -> None:
    reply = next(m for m in MAILS if m.reply_to)
    parsed = message_from_bytes(_raw(reply, "owner@gmail.test", datetime.now(UTC)), policy=policy.default)
    assert parsed["In-Reply-To"] == _header_id(reply.reply_to or "")
    quote = next(m for m in MAILS if m.attachment)
    with_pdf = message_from_bytes(_raw(quote, "owner@gmail.test", datetime.now(UTC)), policy=policy.default)
    assert [p.get_filename() for p in with_pdf.iter_attachments()] == [quote.attachment]
