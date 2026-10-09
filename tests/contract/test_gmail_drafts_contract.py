import json
import re
from email import message_from_bytes, policy
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence

from app.channels.gmail.drafts import DraftRequest, FakeDrafts, GmailDraftError, GoogleDrafts, build_mime
from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.channels.gmail.inbound import to_message
from app.core.errors import IgnoredMessageError

ADDRESS = "hausverwaltung@example.test"
REQ = DraftRequest(
    idempotency_key="exec:action-1:1",
    thread_id="thread-0001",
    to="Tenant Müller <tenant-001@example.test>",
    subject="Re: Heizung – Grüße\r\nBcc: evil@example.test",
    body="Sehr geehrte Frau Müller,\nwir schicken morgen einen Handwerker.\nViele Grüße",
    in_reply_to="<msg-0001@example.test>",
    references="<root@example.test> <msg-0001@example.test>",
)


def parsed(raw: bytes) -> Any:
    return message_from_bytes(raw, policy=policy.default)


def test_mime_is_safe_threaded_and_utf8() -> None:
    m = parsed(build_mime(ADDRESS, REQ))
    assert m["Subject"] == "Re: Heizung – Grüße Bcc: evil@example.test"
    assert m["Bcc"] is None
    assert m["In-Reply-To"] == "<msg-0001@example.test>"
    assert m["References"] == "<root@example.test> <msg-0001@example.test>"
    assert m["From"] == ADDRESS
    assert m["To"].addresses[0].addr_spec == "tenant-001@example.test"
    assert m["Message-ID"] == REQ.rfc822_id
    assert "Frau Müller" in m.get_content()
    assert m.get_content_charset() == "utf-8"


def test_message_id_is_deterministic_per_idempotency_key() -> None:
    other = DraftRequest(**{**REQ.__dict__, "idempotency_key": "exec:action-1:2"})
    assert REQ.rfc822_id == DraftRequest(**REQ.__dict__).rfc822_id
    assert REQ.rfc822_id != other.rfc822_id


@pytest.mark.parametrize("to", ["", "a@example.test, b@example.test", "not-an-address", "a@b@c"])
def test_exactly_one_valid_recipient(to: str) -> None:
    with pytest.raises(GmailDraftError) as exc:
        build_mime(ADDRESS, DraftRequest(**{**REQ.__dict__, "to": to}))
    assert exc.value.retryable is False


def test_long_references_keep_root_and_parent_whole() -> None:
    ids = [f"<{'x' * 60}{i}@example.test>" for i in range(400)]
    m = parsed(build_mime(ADDRESS, DraftRequest(**{**REQ.__dict__, "references": " ".join(ids)})))
    kept = re.findall(r"<[^<>]+>", m["References"])  # folding may drop the space between ids (RFC 5322 allows it)
    assert kept[0] == ids[0]
    assert kept[-1] == ids[-1]
    assert all(r.startswith("<") and r.endswith(">") for r in kept)


class RecordingHttp(HttpMockSequence):  # type: ignore[misc]
    def __init__(self, responses: list[tuple[dict[str, str], str]]) -> None:
        super().__init__(responses)
        self.calls: list[tuple[str, str, dict[str, list[str]]]] = []

    def request(self, uri: str, method: str = "GET", body: Any = None, headers: Any = None, **kw: Any) -> Any:
        parts = urlsplit(uri)
        self.calls.append((method, parts.path, parse_qs(parts.query)))
        return super().request(uri, method, body, headers, **kw)


def test_google_drafts_create_is_idempotent_and_errors_typed() -> None:
    """Gmail rewrites a draft's Message-ID: the lookup is by our `X-EstateOS-Key` header among the thread's drafts."""
    mine = {"id": "r-123", "message": {"id": "m", "threadId": "thread-0001"}}
    other = {"id": "r-999", "message": {"id": "o", "threadId": "thread-0001"}}
    elsewhere = {"id": "r-555", "message": {"id": "e", "threadId": "thread-0002"}}

    def headers(value: str) -> str:
        return json.dumps({"message": {"payload": {"headers": [{"name": "X-EstateOS-Key", "value": value}]}}})

    http = RecordingHttp(
        [
            ({"status": "200"}, json.dumps({})),  # lookup: no drafts yet
            ({"status": "200"}, json.dumps({"id": "r-123", "message": {"id": "m", "threadId": "thread-0001"}})),
            ({"status": "200"}, json.dumps({"drafts": [elsewhere, other, mine]})),  # retry: scan the thread's drafts
            ({"status": "200"}, headers("someone-else")),
            ({"status": "200"}, headers(REQ.key_token)),
            ({"status": "200"}, json.dumps({})),
            ({"status": "400"}, json.dumps({"error": {"code": 400}})),
        ]
    )
    drafts = GoogleDrafts(build("gmail", "v1", http=http, static_discovery=True), ADDRESS)
    assert drafts.create_draft(REQ) == "r-123"
    assert drafts.create_draft(REQ) == "r-123"  # found by header: no second drafts.create
    assert [c[0] for c in http.calls] == ["GET", "POST", "GET", "GET", "GET"]  # other threads' drafts are not fetched
    assert http.calls[0][2]["q"] == ["in:drafts"]
    with pytest.raises(GmailDraftError) as permanent:
        drafts.create_draft(REQ)
    assert permanent.value.retryable is False


def test_mime_carries_the_idempotency_header_that_survives_gmail() -> None:
    assert parsed(build_mime(ADDRESS, REQ))["X-EstateOS-Key"] == REQ.key_token


def test_fake_drafts_idempotent_land_in_thread_and_are_never_read_back_as_sent() -> None:
    box = FakeMailbox(ADDRESS, MemoryMailboxStore())
    drafts = FakeDrafts(box)
    first = drafts.create_draft(REQ)
    assert drafts.create_draft(REQ) == first
    [mid] = box.history_since(0).message_ids
    gm = box.get_message(mid)
    assert gm.label_ids == ["DRAFT"]
    assert gm.thread_id == "thread-0001"
    with pytest.raises(IgnoredMessageError):
        to_message(gm, company_id=uuid4(), raw_event_id=uuid4(), mailbox=ADDRESS)
