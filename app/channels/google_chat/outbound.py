"""Outbound Google Chat adapter: sends messages/cards to Google Chat spaces."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.core.errors import EstateOSError

CHAT_SCOPES = ["https://www.googleapis.com/auth/chat.bot"]


class GoogleChatError(EstateOSError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class GoogleChatOutbound(Protocol):
    def send(self, space: str, payload: dict[str, Any]) -> str:
        """Post a message or card to the given space (e.g. 'spaces/AAAA...'). Returns message name."""
        ...


@dataclass
class FakeGoogleChatOutbound:
    sent: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def send(self, space: str, payload: dict[str, Any]) -> str:
        msg_id = f"{space}/messages/fake-{len(self.sent) + 1}"
        self.sent.append((space, payload))
        return msg_id


class GoogleChatClient:
    def __init__(self, service_account_file: Path | str | None = None) -> None:
        self._chat = None
        if service_account_file:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds = service_account.Credentials.from_service_account_file(str(service_account_file), scopes=CHAT_SCOPES)
            self._chat = build("chat", "v1", credentials=creds, cache_discovery=False)

    def send(self, space: str, payload: dict[str, Any]) -> str:
        if space.startswith("https://"):
            import httpx

            try:
                res = httpx.post(space, json=payload, timeout=10.0)
                if res.status_code >= 400:
                    raise GoogleChatError(f"chat webhook failed: HTTP {res.status_code} {res.text[:200]}")
                data = res.json()
                return str(data.get("name") or "webhook/message")
            except Exception as exc:
                if isinstance(exc, GoogleChatError):
                    raise
                raise GoogleChatError(f"chat webhook network error: {exc}") from exc

        if self._chat is None:
            raise GoogleChatError("chat service account credentials not configured")

        from googleapiclient.errors import HttpError

        try:
            res = self._chat.spaces().messages().create(parent=space, body=payload).execute()
            name: str = res.get("name") or f"{space}/messages/unknown"
            return name
        except HttpError as exc:
            status = int(getattr(exc.resp, "status", 0) or 0)
            retryable = status >= 500 or status == 429
            raise GoogleChatError(f"chat API failed: HTTP {status}", retryable=retryable) from exc
