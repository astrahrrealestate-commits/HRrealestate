"""WhatsApp outbound transport. Imported ONLY by app.sender (import-linter contract + edit guard).

One HTTP transport serves Meta Cloud API and 360dialog: both accept the same Cloud API message JSON and differ only in
base URL, messages path and auth header. Message bodies come from `app.channels.whatsapp.payloads`.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.errors import EstateOSError

TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Rejected by the provider before sending (rate limits / throughput): safe to retry later.
_THROTTLE_CODES = frozenset({4, 80007, 130429, 131048, 131056})
# Transient platform failures after the request was accepted for processing: the message MAY have been sent.
_AMBIGUOUS_CODES = frozenset({1, 2, 131000, 131016, 133004})
# Transport failures where the request never reached the provider.
_NOT_SENT_TRANSPORT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


class WhatsAppSendError(EstateOSError):
    """A failed send. `maybe_sent` means the provider may have delivered it: the sender must record the send as
    unknown and never retry automatically (Cloud API /messages has no idempotency key). `retryable` is only ever
    True when the message was definitely not sent."""

    def __init__(
        self, message: str, *, code: int | None, http_status: int | None, retryable: bool, maybe_sent: bool
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.retryable = retryable and not maybe_sent
        self.maybe_sent = maybe_sent


class WhatsAppOutbound(Protocol):
    def send(self, payload: dict[str, Any]) -> str:
        """Send a payload built by `payloads`; returns the provider message id (wamid)."""
        ...


def _require_built(payload: dict[str, Any]) -> None:
    if payload.get("messaging_product") != "whatsapp" or "to" not in payload or "type" not in payload:
        raise ValueError("payload must be built with app.channels.whatsapp.payloads")


class HttpWhatsAppOutbound:
    def __init__(self, messages_url: str, headers: dict[str, str], client: httpx.Client | None = None) -> None:
        self._url = messages_url
        self._headers = {**headers, "Content-Type": "application/json"}
        self._client = client or httpx.Client(timeout=TIMEOUT)

    @classmethod
    def cloud_api(
        cls, base_url: str, phone_number_id: str, token: str, client: httpx.Client | None = None
    ) -> "HttpWhatsAppOutbound":
        return cls(f"{base_url.rstrip('/')}/{phone_number_id}/messages", {"Authorization": f"Bearer {token}"}, client)

    @classmethod
    def dialog360(cls, base_url: str, api_key: str, client: httpx.Client | None = None) -> "HttpWhatsAppOutbound":
        return cls(f"{base_url.rstrip('/')}/messages", {"D360-API-KEY": api_key}, client)

    def send(self, payload: dict[str, Any]) -> str:
        _require_built(payload)
        try:
            response = self._client.post(self._url, json=payload, headers=self._headers)
        except _NOT_SENT_TRANSPORT as exc:
            raise WhatsAppSendError(
                f"connect failed: {type(exc).__name__}", code=None, http_status=None, retryable=True, maybe_sent=False
            ) from exc
        except httpx.TransportError as exc:  # the request may have reached the provider (read timeout, reset)
            raise WhatsAppSendError(
                f"transport error after send: {type(exc).__name__}",
                code=None,
                http_status=None,
                retryable=False,
                maybe_sent=True,
            ) from exc
        if response.status_code >= 400:
            raise _error_from(response)
        return _wamid_from(response)


def _json_dict(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _wamid_from(response: httpx.Response) -> str:
    messages = _json_dict(response).get("messages")
    first = messages[0] if isinstance(messages, list) and messages else None
    wamid = first.get("id") if isinstance(first, dict) else None
    if not isinstance(wamid, str) or not wamid:
        # 2xx: the provider accepted the request, so the message may well be on its way.
        raise WhatsAppSendError(
            "2xx response without a message id",
            code=None,
            http_status=response.status_code,
            retryable=False,
            maybe_sent=True,
        )
    return wamid


def _error_from(response: httpx.Response) -> WhatsAppSendError:
    error = _json_dict(response).get("error")
    error = error if isinstance(error, dict) else {}
    code = error.get("code") if isinstance(error.get("code"), int) else None
    status = response.status_code
    throttled = status == 429 or code in _THROTTLE_CODES
    maybe_sent = not throttled and (status >= 500 or code in _AMBIGUOUS_CODES)
    message = str(error.get("message") or f"HTTP {status}")[:200]
    return WhatsAppSendError(message, code=code, http_status=status, retryable=throttled, maybe_sent=maybe_sent)


@dataclass(frozen=True)
class SentWhatsApp:
    wamid: str
    payload: dict[str, Any]


@dataclass
class FakeWhatsAppOutbound:
    """Records sends instead of calling a provider (dev, tests, simulator)."""

    sent: list[SentWhatsApp] = field(default_factory=list)

    def send(self, payload: dict[str, Any]) -> str:
        _require_built(payload)
        wamid = f"wamid.FAKE{len(self.sent) + 1:06d}"
        self.sent.append(SentWhatsApp(wamid=wamid, payload=payload))
        return wamid
