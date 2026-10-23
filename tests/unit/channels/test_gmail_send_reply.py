"""`send_reply`: one message in the tenant's thread, idempotent via `X-EstateOS-Key`, never re-sent blindly."""

import base64
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from googleapiclient.errors import HttpError

from app.channels.gmail.drafts import FakeDrafts, GmailDraftError, GoogleDrafts
from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.contracts import DraftRequest

MAILBOX = "beheer@example.test"
REQ = DraftRequest("exec:a:1", "thr-1", "sanne@example.test", "Re: Lekkage", "Beste Sanne", "<m1@x>", "<m0@x> <m1@x>")


def _http(status: int, content: bytes = b"{}") -> HttpError:
    return HttpError(SimpleNamespace(status=status, reason="error"), content)


@dataclass
class _Call:
    result: Any = None
    error: BaseException | None = None

    def execute(self, num_retries: int = 0) -> Any:
        if self.error is not None:
            raise self.error
        return self.result


@dataclass
class _Service:
    """The subset of the Gmail client `send_reply` uses: `threads().get` and `messages().send`."""

    thread: dict[str, Any] = field(default_factory=lambda: {"messages": []})
    lookup_error: BaseException | None = None
    send_error: BaseException | None = None
    sends: list[dict[str, Any]] = field(default_factory=list)
    lookups: list[dict[str, Any]] = field(default_factory=list)

    def users(self) -> "_Service":
        return self

    def drafts(self) -> "_Service":
        return self

    def threads(self) -> "_Service":
        return self

    def messages(self) -> "_Service":
        return self

    def get(self, **kw: Any) -> _Call:
        self.lookups.append(kw)
        return _Call(self.thread, self.lookup_error)

    def send(self, **kw: Any) -> _Call:
        self.sends.append(kw)
        return _Call({"id": "msg-new"}, self.send_error)


def _with_key(message_id: str, token: str, labels: list[str]) -> dict[str, Any]:
    return {"id": message_id, "labelIds": labels, "payload": {"headers": [{"name": "X-EstateOS-Key", "value": token}]}}


def test_sends_in_the_thread_with_reply_headers_and_key() -> None:
    service = _Service()
    assert GoogleDrafts(service, MAILBOX).send_reply(REQ) == "msg-new"
    assert service.lookups == [
        {"userId": "me", "id": "thr-1", "format": "metadata", "metadataHeaders": ["X-EstateOS-Key"]}
    ]
    [call] = service.sends
    assert call["userId"] == "me"
    assert call["body"]["threadId"] == "thr-1"
    raw = base64.urlsafe_b64decode(call["body"]["raw"] + "==").decode()
    for header in ("To: sanne@example.test", "In-Reply-To: <m1@x>", "References: <m0@x> <m1@x>"):
        assert header in raw
    assert f"X-EstateOS-Key: {REQ.key_token}" in raw


def test_an_already_sent_message_with_our_key_is_returned_without_sending() -> None:
    service = _Service(thread={"messages": [_with_key("old-1", REQ.key_token, ["SENT"])]})
    assert GoogleDrafts(service, MAILBOX).send_reply(REQ) == "old-1"
    assert service.sends == []


def test_a_draft_carrying_our_key_is_not_a_sent_message() -> None:
    service = _Service(thread={"messages": [_with_key("draft-1", REQ.key_token, ["DRAFT"])]})
    assert GoogleDrafts(service, MAILBOX).send_reply(REQ) == "msg-new"
    assert len(service.sends) == 1


def test_another_key_in_the_thread_does_not_count() -> None:
    service = _Service(thread={"messages": [_with_key("other", "f" * 32, ["SENT"])]})
    assert GoogleDrafts(service, MAILBOX).send_reply(REQ) == "msg-new"


@pytest.mark.parametrize("error", [_http(429), _http(403, b'{"reason": "rateLimitExceeded"}')])
def test_rate_limited_is_retryable_and_not_maybe_sent(error: HttpError) -> None:
    with pytest.raises(GmailDraftError) as exc:
        GoogleDrafts(_Service(send_error=error), MAILBOX).send_reply(REQ)
    assert (exc.value.retryable, exc.value.maybe_sent) == (True, False)


@pytest.mark.parametrize("status", [400, 403, 404])
def test_a_4xx_rejection_is_permanent_and_nothing_was_sent(status: int) -> None:
    with pytest.raises(GmailDraftError) as exc:
        GoogleDrafts(_Service(send_error=_http(status)), MAILBOX).send_reply(REQ)
    assert (exc.value.retryable, exc.value.maybe_sent) == (False, False)


@pytest.mark.parametrize("error", [_http(500), _http(503), TimeoutError("read timed out"), OSError("reset")])
def test_5xx_and_transport_errors_after_the_request_are_ambiguous(error: BaseException) -> None:
    with pytest.raises(GmailDraftError) as exc:
        GoogleDrafts(_Service(send_error=error), MAILBOX).send_reply(REQ)
    assert (exc.value.retryable, exc.value.maybe_sent) == (False, True)


@pytest.mark.parametrize(("error", "retryable"), [(_http(503), True), (_http(429), True), (_http(404), False),
                                                  (TimeoutError("t"), True)])  # fmt: skip
def test_a_failed_lookup_sends_nothing(error: BaseException, retryable: bool) -> None:
    service = _Service(lookup_error=error)
    with pytest.raises(GmailDraftError) as exc:
        GoogleDrafts(service, MAILBOX).send_reply(REQ)
    assert (exc.value.retryable, exc.value.maybe_sent) == (retryable, False)
    assert service.sends == []


def test_draft_errors_default_to_not_maybe_sent() -> None:
    assert GmailDraftError("x", retryable=False).maybe_sent is False


def test_fake_send_reply_stores_one_sent_message_in_the_thread() -> None:
    mailbox = FakeMailbox(MAILBOX, MemoryMailboxStore())
    fake = FakeDrafts(mailbox)
    first, second = fake.send_reply(REQ), fake.send_reply(REQ)
    assert first == second
    assert fake.replies == [REQ]
    stored = mailbox.get_message(first)
    assert stored.thread_id == "thr-1"
    assert "SENT" in stored.label_ids
    assert mailbox.find_by_header("X-EstateOS-Key", REQ.key_token, "DRAFT") is None


def test_fake_send_reply_ignores_a_draft_with_the_same_key() -> None:
    mailbox = FakeMailbox(MAILBOX, MemoryMailboxStore())
    fake = FakeDrafts(mailbox)
    fake.create_draft(REQ)
    fake.send_reply(REQ)
    assert fake.replies == [REQ]
