"""Gmail drafts (Phase 1's only email output). Imported ONLY by app.sender (import-linter + edit guard)."""

import base64
import hashlib
import re
from dataclasses import dataclass, field
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import getaddresses
from typing import Any, Protocol

from googleapiclient.errors import HttpError

from app.channels.gmail.fake import FakeMailbox
from app.channels.gmail.google import is_rate_limited
from app.channels.gmail.text_clean import clean_header
from app.core.errors import EstateOSError

COMPOSE_SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


class GmailDraftError(EstateOSError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class DraftRequest:
    idempotency_key: str  # e.g. exec:{action_id}:{draft_version} — becomes a deterministic Message-ID
    thread_id: str
    to: str
    subject: str
    body: str
    in_reply_to: str | None = None
    references: str | None = None

    @property
    def rfc822_id(self) -> str:
        digest = hashlib.sha256(self.idempotency_key.encode()).hexdigest()[:32]
        return f"<draft-{digest}@estateos.invalid>"


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


def build_mime(sender: str, request: DraftRequest) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = _single_recipient(clean_header(request.to) or "")
    msg["Subject"] = clean_header(request.subject) or ""
    msg["Message-ID"] = request.rfc822_id
    if request.in_reply_to:
        msg["In-Reply-To"] = clean_header(request.in_reply_to, 1_000) or ""
    if request.references:
        msg["References"] = _trim_references(clean_header(request.references, 64_000) or "")
    msg.set_content(request.body, charset="utf-8")
    return msg.as_bytes()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class GoogleDrafts:
    def __init__(self, service: Any, address: str) -> None:
        self._drafts = service.users().drafts()
        self._address = address

    def create_draft(self, request: DraftRequest) -> str:
        """Idempotent: a retry after an ambiguous failure finds the existing draft by its Message-ID."""
        raw = _b64(build_mime(self._address, request))
        try:
            existing = self._drafts.list(userId="me", q=f"rfc822msgid:{request.rfc822_id}").execute(num_retries=3)
            if existing.get("drafts"):
                found: str = existing["drafts"][0]["id"]
                return found
            body = {"message": {"raw": raw, "threadId": request.thread_id}}
            response = self._drafts.create(userId="me", body=body).execute()
        except HttpError as exc:
            status = int(getattr(exc.resp, "status", 0) or 0)
            retryable = status >= 500 or is_rate_limited(exc)  # safe: the lookup above makes retries idempotent
            raise GmailDraftError(f"drafts failed: HTTP {status}", retryable=retryable) from exc
        draft_id: str = response["id"]
        return draft_id


@dataclass
class FakeDrafts:
    mailbox: FakeMailbox
    created: list[DraftRequest] = field(default_factory=list)

    def create_draft(self, request: DraftRequest) -> str:
        existing = self.mailbox.find_by_rfc822_id(request.rfc822_id, "DRAFT")
        if existing:
            return f"r-{existing}"
        message_id = self.mailbox.add_message(
            build_mime(self.mailbox.address, request), labels=["DRAFT"], thread_id=request.thread_id
        )
        self.created.append(request)
        return f"r-{message_id}"
