"""Fetch one web page a search named: its text and the address it really came from.

The address comes from a model or a search index, so it is untrusted, and so is the page. Redirects are followed by
hand. At every hop the scheme must be http(s) on its usual port, and every address the host resolves to must be public;
the request then goes to the address that was checked (the host name only appears in `Host` and TLS), so a second DNS
answer cannot lead it into our own network. At most five redirects, 2 MB (after decompression), 10 seconds, HTML, plain
text or PDF. Anything else is a `PageFetchError`: the caller drops the source.
"""

import ipaddress
import re
import socket
import time
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html import unescape
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from app.channels.gmail.html_sanitize import html_to_clean_text
from app.channels.text_clean import clean_header, clean_text
from app.core.errors import EstateOSError
from app.core.logging import get_logger
from app.storage.extract import LocalExtractor

log = get_logger(__name__)

MAX_REDIRECTS = 5
MAX_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 60_000
TIMEOUT_SEC = 10.0
_PORTS = {"http": 80, "https": 443}
_HTML = ("text/html", "application/xhtml+xml")
_PDF = "application/pdf"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; page-reader/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9",
    "Accept-Language": "nl,en;q=0.8",
    "Accept-Encoding": "gzip, identity",
}
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_NAT64 = ipaddress.ip_network("64:ff9b::/96")  # public on paper, but it carries any IPv4 address, private ones too

Resolver = Callable[[str], list[str]]


class PageFetchError(EstateOSError):
    """A page that cannot be read safely (address, size, type, time, status). The source is dropped, never retried."""


@dataclass(frozen=True)
class Page:
    """The final address (after redirects) and the page text. Untrusted data, never instructions."""

    url: str
    title: str
    text: str


class PageFetcher(Protocol):
    def fetch(self, url: str, *, allowed_domains: Sequence[str] = ()) -> Page: ...


def _now() -> float:
    return time.monotonic()


def _resolve(host: str) -> list[str]:
    try:
        found = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise PageFetchError("host does not resolve to an address") from exc
    return [str(entry[4][0]).partition("%")[0] for entry in found]


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return _is_public(str(ip.ipv4_mapped))
        if ip.sixtofour is not None or ip.teredo is not None or ip in _NAT64:
            return False
    return ip.is_global and not ip.is_multicast


def host_allowed(host: str, allowed_domains: Sequence[str]) -> bool:
    return not allowed_domains or any(host == d or host.endswith("." + d) for d in allowed_domains)


@dataclass(frozen=True)
class _Target:
    """One checked hop: the URL as asked, its host, and the public address to connect to."""

    url: str
    host: str
    pinned: httpx.URL


def _inflate(raw: bytes, encoding: str) -> bytes:
    if encoding in ("", "identity"):
        return raw
    if encoding not in ("gzip", "x-gzip", "deflate"):
        raise PageFetchError(f"unsupported content encoding {encoding[:20]!r}")
    try:
        out = zlib.decompressobj(wbits=47).decompress(raw, MAX_BYTES + 1)
    except zlib.error as exc:
        raise PageFetchError("unreadable compressed page") from exc
    if len(out) > MAX_BYTES:
        raise PageFetchError("page too large")
    return out


def _page(url: str, content_type: str, charset: str | None, body: bytes) -> Page:
    if content_type == _PDF:
        text = (LocalExtractor().extract(body, _PDF, None).text or "").replace("\f", "\n")
        return Page(url, "", clean_text(text)[:MAX_TEXT_CHARS])
    try:
        raw = body.decode(charset or "utf-8", errors="replace")
    except LookupError:  # a charset Python does not know
        raw = body.decode("utf-8", errors="replace")
    if content_type not in _HTML:
        return Page(url, "", clean_text(raw)[:MAX_TEXT_CHARS])
    title = _TITLE.search(raw)
    name = clean_header(unescape(title.group(1)), 200) if title else None
    return Page(url, name or "", html_to_clean_text(raw)[:MAX_TEXT_CHARS])


def _read(url: str, content_type: str, charset: str | None, body: bytes) -> Page:
    try:
        return _page(url, content_type, charset, body)
    except Exception as exc:  # hostile markup can break any parser: the source is dropped, the search goes on
        raise PageFetchError(f"unreadable page: {type(exc).__name__}") from exc


class HttpPageFetcher:
    def __init__(self, *, resolve: Resolver = _resolve, transport: httpx.BaseTransport | None = None) -> None:
        self._resolve = resolve
        self._transport = transport

    def fetch(self, url: str, *, allowed_domains: Sequence[str] = ()) -> Page:
        deadline = _now() + TIMEOUT_SEC
        # trust_env off: a proxy from the environment would resolve the host again, past the check
        with httpx.Client(transport=self._transport, trust_env=False, follow_redirects=False) as client:
            for _hop in range(MAX_REDIRECTS + 1):
                target = self._check(url)
                try:
                    found = self._get(client, target, deadline, allowed_domains)
                except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
                    raise PageFetchError(f"page not readable: {type(exc).__name__}") from exc
                if isinstance(found, Page):
                    return found
                url = found
        raise PageFetchError(f"more than {MAX_REDIRECTS} redirects")

    def _check(self, url: str) -> _Target:
        try:
            parts = urlsplit(url.strip())
            host, port = (parts.hostname or "").lower().rstrip("."), parts.port
        except ValueError as exc:
            raise PageFetchError("not a web address") from exc
        if parts.scheme not in _PORTS or not host or parts.username is not None or parts.password is not None:
            raise PageFetchError("not a plain http(s) address")
        if port not in (None, _PORTS[parts.scheme]):
            raise PageFetchError("only the usual web ports are fetched")
        addresses = self._resolve(host)
        if not addresses or not all(_is_public(a) for a in addresses):
            log.warning("prices.page_fetch.address_refused")
            raise PageFetchError("the host is not at a public address")
        connect_to = next((a for a in addresses if ":" not in a), addresses[0])  # our network has no IPv6 route out
        try:
            return _Target(url.strip(), host, httpx.URL(url.strip()).copy_with(host=connect_to))
        except httpx.InvalidURL as exc:
            raise PageFetchError("not a web address") from exc

    def _get(
        self, client: httpx.Client, target: _Target, deadline: float, allowed_domains: Sequence[str]
    ) -> Page | str:
        """The page, or the address it redirects to."""
        request = client.build_request(
            "GET", target.pinned, headers={**_HEADERS, "Host": target.host},
            timeout=self._left(deadline), extensions={"sni_hostname": target.host},
        )  # fmt: skip
        response = client.send(request, stream=True)
        try:
            if response.is_redirect:
                return urljoin(target.url, str(response.headers.get("location", "")))
            if response.status_code != httpx.codes.OK:
                raise PageFetchError(f"page answered {response.status_code}")
            if not host_allowed(target.host, allowed_domains):
                raise PageFetchError("the page is not on an allowed domain")
            content_type = response.headers.get("content-type", "").partition(";")[0].strip().lower()
            if content_type not in (*_HTML, _PDF, "text/plain"):
                raise PageFetchError(f"unsupported content type {content_type[:40]!r}")
            body = self._body(response, deadline)
            return _read(target.url, content_type, response.charset_encoding, body)
        finally:
            response.close()

    def _body(self, response: httpx.Response, deadline: float) -> bytes:
        raw = bytearray()
        for chunk in response.iter_raw():
            raw += chunk
            if len(raw) > MAX_BYTES:
                raise PageFetchError("page too large")
            self._left(deadline)
        return _inflate(bytes(raw), response.headers.get("content-encoding", "").strip().lower())

    @staticmethod
    def _left(deadline: float) -> float:
        left = deadline - _now()
        if left <= 0:
            raise PageFetchError("page took too long")
        return left
