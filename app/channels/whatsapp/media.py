"""WhatsApp media download (inbound images, documents, voice notes).

Two-step Cloud API flow: GET /<media_id> → {url, mime_type, sha256, file_size}, then GET <url> with the same auth.
360dialog proxies the second call: the lookaside host is replaced by the 360dialog base URL. The download streams
with a hard byte cap and an overall deadline; sha256 is checked before anything reaches storage. Every failure is a
typed error that says whether a retry can help.
"""

import base64
import binascii
import hashlib
import re
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.errors import EstateOSError, NotFoundError

MAX_MEDIA_BYTES = 100 * 1024 * 1024  # Cloud API document limit
DOWNLOAD_DEADLINE_SEC = 120.0
TIMEOUT = httpx.Timeout(30.0, connect=5.0)
META_DOWNLOAD_HOSTS = frozenset({"lookaside.fbsbx.com"})
_MEDIA_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


class WhatsAppMediaError(EstateOSError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class MediaBlob:
    data: bytes
    mime_type: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


class WhatsAppMedia(Protocol):
    def download(self, media_id: str) -> MediaBlob: ...


def _provider_sha_hex(value: object) -> str | None:
    """Providers report sha256 as hex or base64; normalise to lowercase hex (None when unparseable)."""
    if not isinstance(value, str) or not value:
        return None
    if re.fullmatch(r"[0-9a-fA-F]{64}", value):
        return value.lower()
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw.hex() if len(raw) == 32 else None


def _declared_size(value: object, media_id: str) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, int) or (isinstance(value, str) and value.isascii() and value.isdigit()):
        return int(value)
    raise WhatsAppMediaError(f"media {media_id}: malformed file_size {str(value)[:20]!r}", retryable=False)


def _check_status(response: httpx.Response, what: str) -> None:
    if 300 <= response.status_code < 400:
        raise WhatsAppMediaError(f"{what}: unexpected redirect HTTP {response.status_code}", retryable=False)
    if response.status_code == 404:
        raise NotFoundError(what)
    if response.status_code in (401, 403):
        raise WhatsAppMediaError(f"{what}: HTTP {response.status_code} (credentials)", retryable=False)
    if response.status_code >= 400:
        raise WhatsAppMediaError(f"{what}: HTTP {response.status_code}", retryable=response.status_code >= 429)


class HttpWhatsAppMedia:
    def __init__(
        self,
        base_url: str,
        headers: dict[str, str],
        *,
        proxy_base: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = headers
        self._proxy_base = proxy_base
        self._client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)

    @classmethod
    def cloud_api(cls, base_url: str, token: str, client: httpx.Client | None = None) -> "HttpWhatsAppMedia":
        return cls(base_url, {"Authorization": f"Bearer {token}"}, client=client)

    @classmethod
    def dialog360(cls, base_url: str, api_key: str, client: httpx.Client | None = None) -> "HttpWhatsAppMedia":
        return cls(base_url, {"D360-API-KEY": api_key}, proxy_base=base_url.rstrip("/"), client=client)

    def download(self, media_id: str) -> MediaBlob:
        if not _MEDIA_ID.fullmatch(media_id):
            raise WhatsAppMediaError(f"invalid media id {media_id[:40]!r}", retryable=False)
        try:
            info = self._client.get(f"{self._base}/{media_id}", headers=self._headers)
            _check_status(info, f"media {media_id}")
            body = info.json()
            meta = body if isinstance(body, dict) else {}
            if not isinstance(meta.get("url"), str):
                raise WhatsAppMediaError(f"media {media_id}: info response has no url", retryable=True)
            if _declared_size(meta.get("file_size"), media_id) > MAX_MEDIA_BYTES:
                raise WhatsAppMediaError(f"media {media_id} too large: {meta['file_size']} bytes", retryable=False)
            data = self._stream(self._download_url(meta["url"]), media_id)
        except httpx.TransportError as exc:
            raise WhatsAppMediaError(f"media {media_id}: {type(exc).__name__}", retryable=True) from exc
        except ValueError as exc:  # non-JSON info body
            raise WhatsAppMediaError(f"media {media_id}: malformed info response", retryable=True) from exc
        if not data:
            raise WhatsAppMediaError(f"media {media_id}: empty download", retryable=True)
        blob = MediaBlob(data, str(meta.get("mime_type") or "application/octet-stream"))
        expected = _provider_sha_hex(meta.get("sha256"))
        if expected is not None and expected != blob.sha256:
            raise WhatsAppMediaError(f"media {media_id} sha256 mismatch", retryable=False)
        return blob

    def _stream(self, url: str, media_id: str) -> bytes:
        deadline = time.monotonic() + DOWNLOAD_DEADLINE_SEC
        with self._client.stream("GET", url, headers=self._headers) as response:
            _check_status(response, f"media {media_id} download")
            if int(response.headers.get("content-length") or 0) > MAX_MEDIA_BYTES:
                raise WhatsAppMediaError(f"media {media_id} too large", retryable=False)
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_MEDIA_BYTES:
                    raise WhatsAppMediaError(f"media {media_id} too large", retryable=False)
                if time.monotonic() > deadline:
                    raise WhatsAppMediaError(f"media {media_id} download exceeded deadline", retryable=True)
                chunks.append(chunk)
        return b"".join(chunks)

    def _download_url(self, url: str) -> str:
        original = urlsplit(url)
        if self._proxy_base:
            proxy = urlsplit(self._proxy_base)
            return urlunsplit((proxy.scheme, proxy.netloc, original.path, original.query, ""))
        allowed = META_DOWNLOAD_HOSTS | {urlsplit(self._base).hostname}
        if original.scheme != "https" or original.hostname not in allowed:
            raise WhatsAppMediaError(f"refusing to send credentials to {original.hostname!r}", retryable=False)
        return url


class FakeWhatsAppMedia:
    def __init__(self, blobs: dict[str, MediaBlob] | None = None) -> None:
        self.blobs = dict(blobs or {})

    def download(self, media_id: str) -> MediaBlob:
        try:
            return self.blobs[media_id]
        except KeyError as exc:
            raise NotFoundError(f"media {media_id}") from exc
