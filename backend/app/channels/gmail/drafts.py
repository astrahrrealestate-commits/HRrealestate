"""Gmail drafts (Phase 1's only email output). Imported ONLY by app.sender (import-linter + edit guard)."""

import base64
import re
from dataclasses import dataclass, field
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import getaddresses
from typing import Any, Protocol

from googleapiclient.errors import HttpError

from app.channels.gmail.fake import FakeMailbox
from app.channels.gmail.google import is_rate_limited
from app.channels.text_clean import clean_header
from app.contracts import DraftRequest, EmailRequest
from app.core.errors import EstateOSError

COMPOSE_SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
# Tenant replies (send mode): `gmail.send` to send, `gmail.metadata` to find an earlier attempt's message by header.
SEND_SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.metadata"]
KEY_HEADER = "X-EstateOS-Key"


class GmailDraftError(EstateOSError):
    """`retryable` only when nothing was sent; `maybe_sent` when the provider may have delivered it (never retried)."""

    def __init__(self, message: str, *, retryable: bool, maybe_sent: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable and not maybe_sent
        self.maybe_sent = maybe_sent


MAX_REFERENCES = 8_000


def _single_recipient(to: str) -> str:
    parsed = [addr for _, addr in getaddresses([to]) if addr]
    if len(parsed) != 1 or parsed[0].count("@") != 1:
        raise GmailDraftError("a draft needs exactly one recipient address", retryable=False)
    try:
        return str(Address(addr_spec=parsed[0]))
    except Exception as exc:  # stdlib raises HeaderParseError/ValueError/IndexError for malformed specs
        raise GmailDraftError(f"invalid recipient {to[:60]!r}", retryable=False) from exc


def _trim_references(references: str) -> str:
    """Keep whole ids; when too long drop the middle, keeping the root and the newest (the parent)."""
    ids = re.findall(r"<[^<>\s]+>", references)
    while len(" ".join(ids)) > MAX_REFERENCES and len(ids) > 2:
        del ids[1]
    return " ".join(ids)


class GmailDrafts(Protocol):
    def create_draft(self, request: DraftRequest) -> str:
        """Create a draft in the thread; returns the provider draft id."""
        ...

    def send_message(self, request: EmailRequest) -> str:
        """Send an email (used for owner digest); returns provider message id."""
        ...

    def send_reply(self, request: DraftRequest) -> str:
        """Send the reply in `thread_id` (idempotent through `X-EstateOS-Key`); returns the provider message id."""
        ...

    def send_draft(self, draft_id: str) -> str:
        """Send an existing draft; returns provider message id."""
        ...


def build_mime(sender: str, request: DraftRequest) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = _single_recipient(clean_header(request.to) or "")
    msg["Subject"] = clean_header(request.subject) or ""
    msg["Message-ID"] = request.rfc822_id
    msg["X-EstateOS-Key"] = request.key_token
    if request.in_reply_to:
        msg["In-Reply-To"] = clean_header(request.in_reply_to, 1_000) or ""
    if request.references:
        msg["References"] = _trim_references(clean_header(request.references, 64_000) or "")
    msg.set_content(request.body, charset="utf-8")
    for att in request.attachments:
        maintype, _, subtype = (att.mime_type or "application/octet-stream").partition("/")
        msg.add_attachment(
            att.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=clean_header(att.filename, 255) or "attachment",
        )
    return msg.as_bytes()


def build_owner_email_mime(sender: str, request: EmailRequest) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = _single_recipient(clean_header(request.to) or "")
    msg["Subject"] = clean_header(request.subject) or ""
    msg["Message-ID"] = request.rfc822_id
    msg["X-EstateOS-Key"] = request.key_token
    msg.set_content(request.body_text, charset="utf-8")
    if request.body_html:
        msg.add_alternative(request.body_html, subtype="html")
    return msg.as_bytes()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _has_key(message: dict[str, Any], token: str) -> bool:
    headers = message.get("payload", {}).get("headers", [])
    return any(h.get("name", "").lower() == KEY_HEADER.lower() and h.get("value") == token for h in headers)


def _lookup_error(exc: Exception) -> GmailDraftError:
    """The pre-send lookup failed: nothing was sent, so transient failures may be retried."""
    if isinstance(exc, HttpError):
        status = int(getattr(exc.resp, "status", 0) or 0)
        retryable = status >= 500 or is_rate_limited(exc)
        return GmailDraftError(f"reply lookup failed: HTTP {status}", retryable=retryable)
    return GmailDraftError(f"reply lookup failed: {type(exc).__name__}", retryable=True)


def _send_error(exc: Exception) -> GmailDraftError:
    """429 → nothing sent, retry; other 4xx → rejected, nothing sent; 5xx/transport after the request → ambiguous."""
    if isinstance(exc, HttpError):
        status = int(getattr(exc.resp, "status", 0) or 0)
        if is_rate_limited(exc):
            return GmailDraftError(f"sending reply rate-limited: HTTP {status}", retryable=True)
        if 400 <= status < 500:
            return GmailDraftError(f"sending reply rejected: HTTP {status}", retryable=False)
        return GmailDraftError(f"sending reply failed: HTTP {status}", retryable=False, maybe_sent=True)
    return GmailDraftError(f"sending reply failed: {type(exc).__name__}", retryable=False, maybe_sent=True)


class GoogleDrafts:
    def __init__(self, service: Any, address: str) -> None:
        self._service = service
        self._drafts = service.users().drafts()
        self._address = address

    def _find(self, request: DraftRequest) -> str | None:
        """An earlier attempt's draft: scan this thread's drafts for our header (Gmail's search cannot see it)."""
        listed = self._drafts.list(userId="me", q="in:drafts", maxResults=100).execute(num_retries=3)
        for draft in listed.get("drafts", []):
            if draft.get("message", {}).get("threadId") != request.thread_id:
                continue
            full = self._drafts.get(userId="me", id=draft["id"], format="metadata").execute(num_retries=3)
            headers = full.get("message", {}).get("payload", {}).get("headers", [])
            if any(
                h.get("name", "").lower() == "x-estateos-key" and h.get("value") == request.key_token for h in headers
            ):
                found: str = draft["id"]
                return found
        return None

    def create_draft(self, request: DraftRequest) -> str:
        """Idempotent: a retry after an ambiguous failure finds the earlier draft by its `X-EstateOS-Key` header."""
        raw = _b64(build_mime(self._address, request))
        try:
            existing = self._find(request)
            if existing is not None:
                return existing
            body = {"message": {"raw": raw, "threadId": request.thread_id}}
            response = self._drafts.create(userId="me", body=body).execute()
        except HttpError as exc:
            status = int(getattr(exc.resp, "status", 0) or 0)
            retryable = status >= 500 or is_rate_limited(exc)  # safe: the lookup above makes retries idempotent
            raise GmailDraftError(f"drafts failed: HTTP {status}", retryable=retryable) from exc
        draft_id: str = response["id"]
        return draft_id

    def send_draft(self, draft_id: str) -> str:
        """Send an existing draft; returns provider message id."""
        try:
            response = self._drafts.send(userId="me", body={"id": draft_id}).execute()
            message_id: str = response.get("id", draft_id)
            return message_id
        except HttpError as exc:
            raise _send_error(exc) from exc

    def send_message(self, request: EmailRequest) -> str:
        raw = _b64(build_owner_email_mime(self._address, request))
        try:
            response = self._service.users().messages().send(userId="me", body={"raw": raw}).execute()
        except HttpError as exc:
            status = int(getattr(exc.resp, "status", 0) or 0)
            retryable = status >= 500 or is_rate_limited(exc)
            raise GmailDraftError(f"sending email failed: HTTP {status}", retryable=retryable) from exc
        message_id: str = response["id"]
        return message_id

    def _sent_in_thread(self, request: DraftRequest) -> str | None:
        """An earlier attempt's sent message in this thread, found by our header (drafts do not count)."""
        thread = (
            self._service.users()
            .threads()
            .get(userId="me", id=request.thread_id, format="metadata", metadataHeaders=[KEY_HEADER])
            .execute(num_retries=3)
        )
        for message in thread.get("messages", []):
            if "DRAFT" not in message.get("labelIds", []) and _has_key(message, request.key_token):
                found: str = message["id"]
                return found
        return None

    def send_reply(self, request: DraftRequest) -> str:
        """Idempotent: a retry finds the earlier message by `X-EstateOS-Key`. The send itself is never retried here."""
        raw = _b64(build_mime(self._address, request))
        try:
            existing = self._sent_in_thread(request)
        except Exception as exc:
            raise _lookup_error(exc) from exc
        if existing is not None:
            return existing
        body = {"raw": raw, "threadId": request.thread_id}
        try:
            response = self._service.users().messages().send(userId="me", body=body).execute()
        except Exception as exc:
            raise _send_error(exc) from exc
        message_id: str = response["id"]
        return message_id


@dataclass
class FakeDrafts:
    mailbox: FakeMailbox
    created: list[DraftRequest] = field(default_factory=list)
    sent: list[EmailRequest] = field(default_factory=list)
    replies: list[DraftRequest] = field(default_factory=list)

    def create_draft(self, request: DraftRequest) -> str:
        existing = self.mailbox.find_by_header("X-EstateOS-Key", request.key_token, "DRAFT")
        if existing:
            return f"r-{existing}"
        message_id = self.mailbox.add_message(
            build_mime(self.mailbox.address, request), labels=["DRAFT"], thread_id=request.thread_id
        )
        self.created.append(request)
        return f"r-{message_id}"

    def send_message(self, request: EmailRequest) -> str:
        existing = self.mailbox.find_by_header("X-EstateOS-Key", request.key_token, "SENT")
        if existing:
            return f"r-{existing}"
        raw = build_owner_email_mime(self.mailbox.address, request)
        message_id = self.mailbox.add_message(raw, labels=["SENT"])
        self.sent.append(request)
        return f"r-{message_id}"

    def send_reply(self, request: DraftRequest) -> str:
        existing = self.mailbox.find_by_header(KEY_HEADER, request.key_token, "SENT")
        if existing:
            return existing
        raw = build_mime(self.mailbox.address, request)
        message_id = self.mailbox.add_message(raw, labels=["SENT"], thread_id=request.thread_id)
        self.replies.append(request)
        return message_id

    def send_draft(self, draft_id: str) -> str:
        return f"sent-{draft_id}"
