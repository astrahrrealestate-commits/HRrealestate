"""Gmail inbound ports: mailbox history/fetch/watch and the Pub/Sub push notice."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.channels.gmail.models import GmailMessage
from app.core.errors import EstateOSError


class HistoryExpiredError(EstateOSError):
    """startHistoryId is older than Gmail keeps (HTTP 404): resync from `message_ids_since`."""


@dataclass(frozen=True)
class HistoryPage:
    message_ids: list[str]  # messagesAdded only, deduplicated, in history order
    history_id: int  # mailbox history id at the time of the call
    next_page_token: str | None = None


@dataclass(frozen=True)
class WatchResult:
    history_id: int
    expiration: datetime


@dataclass(frozen=True)
class PushNotice:
    email: str
    history_id: int
    message_id: str | None = None  # Pub/Sub message id (dedupe/audit)
    extra: dict[str, str] = field(default_factory=dict)


class GmailMailbox(Protocol):
    def history_since(self, start_history_id: int, page_token: str | None = None) -> HistoryPage: ...

    def get_message(self, message_id: str) -> GmailMessage: ...

    def watch(self, topic: str) -> WatchResult: ...

    def current_history_id(self) -> int: ...

    def message_ids_since(self, after: datetime) -> list[str]: ...
