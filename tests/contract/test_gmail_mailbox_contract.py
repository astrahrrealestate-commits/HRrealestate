"""GmailMailbox contract: FakeMailbox (paged) and GoogleMailbox (googleapiclient over a recording HTTP mock)."""

import base64
import json
import threading
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence

from app.channels.gmail.fake import DirMailboxStore, FakeMailbox, MemoryMailboxStore
from app.channels.gmail.google import GmailApiError, GoogleMailbox
from app.channels.gmail.ports import GmailMailbox, HistoryExpiredError
from app.core.errors import NotFoundError, UnsafeConfigurationError

ADDRESS = "hausverwaltung@example.test"


def _raw(subject: str) -> bytes:
    m = EmailMessage()
    m["From"] = "tenant-001@example.test"
    m["To"] = ADDRESS
    m["Subject"] = subject
    m.set_content("body")
    return m.as_bytes()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class RecordingHttp(HttpMockSequence):  # type: ignore[misc]
    def __init__(self, responses: list[tuple[dict[str, str], str]]) -> None:
        super().__init__(responses)
        self.calls: list[tuple[str, str, dict[str, list[str]], Any]] = []

    def request(self, uri: str, method: str = "GET", body: Any = None, headers: Any = None, **kw: Any) -> Any:
        parts = urlsplit(uri)
        self.calls.append((method, parts.path, parse_qs(parts.query), json.loads(body) if body else None))
        return super().request(uri, method, body, headers, **kw)


def _ok(body: dict[str, Any]) -> tuple[dict[str, str], str]:
    return {"status": "200"}, json.dumps(body)


def _added(*ids: str) -> list[dict[str, Any]]:
    return [{"id": f"h{i}", "messagesAdded": [{"message": {"id": i, "threadId": "t"}}]} for i in ids]


def _api_message(message_id: str, subject: str) -> dict[str, Any]:
    return {
        "id": message_id,
        "threadId": "t",
        "labelIds": ["INBOX"],
        "historyId": "3",
        "internalDate": "1759737600000",
        "raw": _b64(_raw(subject)),
    }


GOOGLE_RESPONSES = [
    _ok({"history": _added("m2"), "historyId": "3", "nextPageToken": "p2"}),
    _ok({"history": [*_added("m3"), {"id": "h9", "labelsAdded": [{"message": {"id": "m2"}}]}], "historyId": "3"}),
    _ok({"historyId": "3"}),
    ({"status": "404"}, json.dumps({"error": {"code": 404, "message": "Requested entity was not found."}})),
    _ok(_api_message("m2", "two")),
    ({"status": "404"}, json.dumps({"error": {"code": 404, "message": "Not Found"}})),
    _ok({"historyId": "3", "expiration": "1760342400000"}),
    _ok({"emailAddress": ADDRESS, "historyId": "3"}),
    _ok({"messages": [{"id": "m1", "threadId": "t"}, {"id": "m2", "threadId": "t"}, {"id": "m3", "threadId": "t"}]}),
]


def fake_mailbox() -> FakeMailbox:
    box = FakeMailbox(ADDRESS, MemoryMailboxStore(), page_size=1)  # forces paging through the contract
    for subject in ("one", "two", "three"):
        box.add_message(_raw(subject), labels=["INBOX"])
    box.expire_history_before(1)
    return box


def google_mailbox() -> tuple[GmailMailbox, RecordingHttp]:
    http = RecordingHttp(list(GOOGLE_RESPONSES))
    return GoogleMailbox(build("gmail", "v1", http=http, static_discovery=True), ADDRESS), http


@pytest.fixture(params=["fake", "google"])
def mailbox(request: pytest.FixtureRequest) -> GmailMailbox:
    return fake_mailbox() if request.param == "fake" else google_mailbox()[0]


def _all_since(box: GmailMailbox, start: int) -> tuple[list[str], int, int]:
    ids: list[str] = []
    token: str | None = None
    latest, pages = start, 0
    while True:
        page = box.history_since(start, page_token=token)
        pages += 1
        ids += page.message_ids
        latest = page.history_id
        if not page.next_page_token:
            return ids, latest, pages
        token = page.next_page_token


def test_contract_sequence(mailbox: GmailMailbox) -> None:
    ids, latest, pages = _all_since(mailbox, 1)
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert latest == 3
    assert pages == 2
    assert mailbox.history_since(3).message_ids == []
    with pytest.raises(HistoryExpiredError):
        mailbox.history_since(0)
    m = mailbox.get_message(ids[0])
    assert m.id == ids[0]
    assert b"Subject: two" in m.raw
    with pytest.raises(NotFoundError):
        mailbox.get_message("missing")
    watch = mailbox.watch("projects/p/topics/gmail")
    assert watch.history_id == 3
    assert watch.expiration > datetime(2025, 1, 1, tzinfo=UTC)
    assert mailbox.current_history_id() == 3
    assert len(mailbox.message_ids_since(datetime(2025, 10, 1, tzinfo=UTC))) == 3


def test_google_requests_carry_the_contract_parameters() -> None:
    box, http = google_mailbox()
    _all_since(box, 1)
    box.history_since(3)
    with pytest.raises(HistoryExpiredError):
        box.history_since(0)
    box.get_message("m2")
    with pytest.raises(NotFoundError):
        box.get_message("missing")
    box.watch("projects/p/topics/gmail")
    box.current_history_id()
    box.message_ids_since(datetime(2025, 10, 1, tzinfo=UTC))
    history = [c for c in http.calls if c[1].endswith("/history")]
    assert history[0][2]["startHistoryId"] == ["1"]
    assert history[0][2]["historyTypes"] == ["messageAdded"]
    assert "pageToken" not in history[0][2]
    assert history[1][2]["pageToken"] == ["p2"]
    get = next(c for c in http.calls if c[1].endswith("/messages/m2"))
    assert get[2]["format"] == ["raw"]
    watch = next(c for c in http.calls if c[1].endswith("/watch"))
    assert watch[0] == "POST"
    assert watch[3] == {
        "topicName": "projects/p/topics/gmail",
        "labelIds": ["INBOX", "SENT"],
        "labelFilterBehavior": "include",
    }
    listing = next(c for c in http.calls if c[1].endswith("/messages") and c[0] == "GET")
    assert listing[2]["q"] == [f"after:{int(datetime(2025, 10, 1, tzinfo=UTC).timestamp())}"]


def test_google_credentials_must_belong_to_the_mailbox() -> None:
    http = RecordingHttp([_ok({"emailAddress": "someone-else@example.test", "historyId": "1"})])
    with pytest.raises(UnsafeConfigurationError, match="someone-else"):
        GoogleMailbox(build("gmail", "v1", http=http, static_discovery=True), ADDRESS).verify_address()
    ok = RecordingHttp([_ok({"emailAddress": ADDRESS.upper(), "historyId": "1"})])
    GoogleMailbox(build("gmail", "v1", http=ok, static_discovery=True), ADDRESS).verify_address()


@pytest.mark.parametrize(
    ("status", "body", "retryable"),
    [(400, "{}", False), (403, '{"error":{"errors":[{"reason":"userRateLimitExceeded"}]}}', True)],
)
def test_google_errors_are_typed(status: int, body: str, retryable: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    import googleapiclient.http

    monkeypatch.setattr(googleapiclient.http.time, "sleep", lambda _s: None)  # library backoff between retries
    http = RecordingHttp([({"status": str(status)}, body)] * 4)
    box = GoogleMailbox(build("gmail", "v1", http=http, static_discovery=True), ADDRESS)
    with pytest.raises(GmailApiError) as exc:
        box.current_history_id()
    assert exc.value.retryable is retryable
    assert len(http.calls) == (4 if retryable else 1)  # rate limits are retried by the library first


def test_fake_store_is_shared_between_instances(tmp_path: Path) -> None:
    writer = FakeMailbox(ADDRESS, DirMailboxStore(tmp_path))
    reader = FakeMailbox(ADDRESS, DirMailboxStore(tmp_path))  # e.g. simulator writes, worker reads
    mid = writer.add_message(_raw("shared"), labels=["INBOX"])
    assert reader.history_since(0).message_ids == [mid]
    assert b"Subject: shared" in reader.get_message(mid).raw


def test_reader_never_sees_a_history_id_without_its_message(tmp_path: Path) -> None:
    writer = FakeMailbox(ADDRESS, DirMailboxStore(tmp_path))
    reader = FakeMailbox(ADDRESS, DirMailboxStore(tmp_path), page_size=10_000)
    done = threading.Event()

    def write() -> None:
        for i in range(60):
            writer.add_message(_raw(f"m{i}"), labels=["INBOX"])
        done.set()

    thread = threading.Thread(target=write)
    thread.start()
    while not done.is_set():
        page = reader.history_since(0)
        assert len(page.message_ids) >= page.history_id  # every published history id has its message stored
    thread.join()


def test_fake_draft_appears_in_history_with_draft_label() -> None:
    box = FakeMailbox(ADDRESS, MemoryMailboxStore())
    mid = box.add_message(_raw("draft"), labels=["DRAFT"], thread_id="thread-9")
    m = box.get_message(mid)
    assert m.label_ids == ["DRAFT"]
    assert m.thread_id == "thread-9"
