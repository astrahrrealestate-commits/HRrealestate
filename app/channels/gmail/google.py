"""Gmail API adapter (google-api-python-client). Read-only scope; drafts live in app.channels.gmail.drafts."""

from datetime import UTC, datetime
from typing import Any

from googleapiclient.errors import HttpError

from app.channels.gmail.models import GmailMessage, parse_api_message
from app.channels.gmail.ports import HistoryExpiredError, HistoryPage, WatchResult
from app.core.errors import EstateOSError, NotFoundError, UnsafeConfigurationError

READ_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
NUM_RETRIES = 3  # googleapiclient's built-in exponential backoff for 429/5xx on idempotent reads
WATCH_LABELS = ["INBOX", "SENT"]
LIST_PAGE_SIZE = 500


def _status(exc: HttpError) -> int:
    return int(getattr(exc.resp, "status", 0) or 0)


class GmailApiError(EstateOSError):
    def __init__(self, message: str, *, status: int, retryable: bool) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def is_rate_limited(exc: HttpError) -> bool:
    return _status(exc) == 429 or (_status(exc) == 403 and b"ateLimitExceeded" in (exc.content or b""))


def _typed(exc: HttpError, what: str) -> GmailApiError:
    status = _status(exc)
    retryable = status >= 500 or is_rate_limited(exc)
    return GmailApiError(f"{what}: HTTP {status}", status=status, retryable=retryable)


class GoogleMailbox:
    def __init__(self, service: Any, address: str) -> None:
        self._users = service.users()
        self.address = address.lower()

    def verify_address(self) -> None:
        """The credentials must belong to this mailbox: `userId="me"` would otherwise read someone else's mail."""
        actual = str(self._users.getProfile(userId="me").execute(num_retries=NUM_RETRIES)["emailAddress"]).lower()
        if actual != self.address:
            raise UnsafeConfigurationError(f"gmail credentials are for {actual}, not {self.address}")

    def history_since(self, start_history_id: int, page_token: str | None = None) -> HistoryPage:
        try:
            response = (
                self._users.history()
                .list(
                    userId="me",
                    startHistoryId=str(start_history_id),
                    historyTypes=["messageAdded"],
                    pageToken=page_token,
                )
                .execute(num_retries=NUM_RETRIES)
            )
        except HttpError as exc:
            if _status(exc) == 404:
                raise HistoryExpiredError(f"history {start_history_id} expired") from exc
            raise _typed(exc, "history.list") from exc
        ids: list[str] = []
        for item in response.get("history", []):
            for added in item.get("messagesAdded", []):
                message_id = added.get("message", {}).get("id")
                if message_id and message_id not in ids:
                    ids.append(message_id)
        return HistoryPage(ids, int(response["historyId"]), response.get("nextPageToken"))

    def get_message(self, message_id: str) -> GmailMessage:
        try:
            response = (
                self._users.messages().get(userId="me", id=message_id, format="raw").execute(num_retries=NUM_RETRIES)
            )
        except HttpError as exc:
            if _status(exc) == 404:
                raise NotFoundError(f"gmail message {message_id}") from exc
            raise _typed(exc, "messages.get") from exc
        return parse_api_message(response)

    def watch(self, topic: str) -> WatchResult:
        body = {"topicName": topic, "labelIds": WATCH_LABELS, "labelFilterBehavior": "include"}
        try:
            response = self._users.watch(userId="me", body=body).execute(num_retries=NUM_RETRIES)
        except HttpError as exc:
            raise _typed(exc, "watch") from exc
        expiration = datetime.fromtimestamp(int(response["expiration"]) / 1000, UTC)
        return WatchResult(history_id=int(response["historyId"]), expiration=expiration)

    def current_history_id(self) -> int:
        try:
            return int(self._users.getProfile(userId="me").execute(num_retries=NUM_RETRIES)["historyId"])
        except HttpError as exc:
            raise _typed(exc, "getProfile") from exc

    def message_ids_since(self, after: datetime) -> list[str]:
        ids: list[str] = []
        token: str | None = None
        while True:
            try:
                response = (
                    self._users.messages()
                    .list(userId="me", q=f"after:{int(after.timestamp())}", maxResults=LIST_PAGE_SIZE, pageToken=token)
                    .execute(num_retries=NUM_RETRIES)
                )
            except HttpError as exc:
                raise _typed(exc, "messages.list") from exc
            ids += [m["id"] for m in response.get("messages", [])]
            token = response.get("nextPageToken")
            if not token:
                return ids
