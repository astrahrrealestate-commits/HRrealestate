"""Page fetch (M13 T8): redirects followed by hand, every hop checked, so a search result never reaches our network."""

import gzip
from collections.abc import Callable

import httpx
import pytest

from app.channels.prices import page_fetch
from app.channels.prices.page_fetch import HttpPageFetcher, PageFetchError

PUBLIC = "93.184.215.14"
HTML = "<html><head><title>Uurtarief loodgieter</title></head><body><p>Vanaf € 55 per uur.</p></body></html>"


def _html(body: str = HTML, **headers: str) -> httpx.Response:
    full = {"content-type": "text/html; charset=utf-8", **headers}
    return httpx.Response(200, headers=full, stream=httpx.ByteStream(body.encode()))  # unread, as from a network


def _fetcher(
    handler: Callable[[httpx.Request], httpx.Response], addresses: dict[str, list[str]] | None = None
) -> HttpPageFetcher:
    known = addresses or {}
    return HttpPageFetcher(resolve=lambda host: known.get(host, [PUBLIC]), transport=httpx.MockTransport(handler))


def _redirects(chain: dict[str, str], body: str = HTML) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        target = chain.get(request.headers["host"])
        return httpx.Response(302, headers={"location": target}) if target else _html(body)

    return handler


def test_a_page_comes_back_as_text_with_its_final_url() -> None:
    chain = {"vertexaisearch.cloud.google.com": "https://klussen.example/tarief"}
    page = _fetcher(_redirects(chain)).fetch("https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc")
    assert page.url == "https://klussen.example/tarief"
    assert page.title == "Uurtarief loodgieter"
    assert "Vanaf € 55 per uur." in page.text


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.8", "172.16.3.4", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1",  # noqa: S104
     "::1", "fe80::1", "fd00:ec2::254", "::ffff:169.254.169.254", "64:ff9b::a9fe:a9fe", "2002:7f00:1::"],
)  # fmt: skip
def test_page_fetch_refuses_private_addresses_on_every_redirect(address: str) -> None:
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.headers["host"])
        return httpx.Response(302, headers={"location": "https://inside.example/latest/meta-data"})

    fetcher = _fetcher(handler, {"inside.example": [address]})
    with pytest.raises(PageFetchError, match="address"):
        fetcher.fetch("https://outside.example/")
    with pytest.raises(PageFetchError, match="address"):
        fetcher.fetch("https://inside.example/")
    assert asked == ["outside.example"]  # the internal host was never contacted


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://[::1]/", "http://2130706433/", "http://0x7f000001/"])
def test_an_address_written_in_the_url_is_checked_too(url: str) -> None:
    fetcher = HttpPageFetcher(transport=httpx.MockTransport(lambda _r: _html()))
    with pytest.raises(PageFetchError):
        fetcher.fetch(url)


def test_one_private_address_among_public_ones_is_enough_to_refuse() -> None:
    fetcher = _fetcher(lambda _r: _html(), {"mixed.example": [PUBLIC, "10.0.0.1"]})
    with pytest.raises(PageFetchError, match="address"):
        fetcher.fetch("https://mixed.example/")


def test_the_connection_goes_to_the_address_that_was_checked() -> None:
    """A second DNS answer between the check and the connection (rebinding) changes nothing."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _html()

    _fetcher(handler).fetch("https://klussen.example/tarief?x=1")
    [request] = seen
    assert request.url.host == PUBLIC
    assert request.url.raw_path == b"/tarief?x=1"
    assert request.headers["host"] == "klussen.example"
    assert request.extensions["sni_hostname"] == "klussen.example"


@pytest.mark.parametrize(
    "url",
    ["ftp://a.example/x", "file:///etc/passwd", "gopher://a.example", "https://user:pw@a.example/", "https:///x",
     "https://a.example:8080/", "javascript:alert(1)"],
)  # fmt: skip
def test_only_plain_http_and_https_urls_are_fetched(url: str) -> None:
    with pytest.raises(PageFetchError):
        _fetcher(lambda _r: _html()).fetch(url)


def test_more_than_five_redirects_are_not_followed() -> None:
    hops = {f"h{i}.example": f"https://h{i + 1}.example/" for i in range(6)}
    with pytest.raises(PageFetchError, match="redirects"):
        _fetcher(_redirects(hops)).fetch("https://h0.example/")
    assert _fetcher(_redirects(hops)).fetch("https://h1.example/").url == "https://h6.example/"


def test_a_page_over_the_size_limit_is_dropped() -> None:
    with pytest.raises(PageFetchError, match="large"):
        _fetcher(lambda _r: _html("x" * (page_fetch.MAX_BYTES + 1))).fetch("https://big.example/")


def test_a_compressed_page_is_read_and_a_compression_bomb_dropped() -> None:
    def gzipped(body: bytes) -> Callable[[httpx.Request], httpx.Response]:
        headers = {"content-type": "text/html", "content-encoding": "gzip"}
        return lambda _r: httpx.Response(200, headers=headers, stream=httpx.ByteStream(gzip.compress(body)))

    assert "€ 55" in _fetcher(gzipped(HTML.encode())).fetch("https://zip.example/").text
    with pytest.raises(PageFetchError, match="large"):
        _fetcher(gzipped(b"0" * (page_fetch.MAX_BYTES * 20))).fetch("https://bomb.example/")


@pytest.mark.parametrize("content_type", ["application/zip", "image/png", "application/octet-stream", ""])
def test_only_text_html_and_pdf_are_read(content_type: str) -> None:
    with pytest.raises(PageFetchError, match="type"):
        _fetcher(lambda _r: httpx.Response(200, headers={"content-type": content_type}, content=b"x")).fetch(
            "https://a.example/"
        )


def test_an_error_page_is_dropped() -> None:
    with pytest.raises(PageFetchError, match="404"):
        _fetcher(lambda _r: httpx.Response(404, headers={"content-type": "text/html"}, text=HTML)).fetch(
            "https://a.example/"
        )


def test_a_network_failure_is_a_page_fetch_error() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(PageFetchError):
        _fetcher(broken).fetch("https://slow.example/")


def test_a_slow_page_stops_at_the_time_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter([0.0, 0.0, *[page_fetch.TIMEOUT_SEC + 1.0] * 50])
    monkeypatch.setattr(page_fetch, "_now", lambda: next(clock))
    with pytest.raises(PageFetchError, match="long"):
        _fetcher(lambda _r: _html()).fetch("https://drip.example/")


def test_the_final_page_must_be_on_an_allowed_domain() -> None:
    chain = {"vertexaisearch.cloud.google.com": "https://blog.example/wet"}
    start = "https://vertexaisearch.cloud.google.com/r/1"
    with pytest.raises(PageFetchError, match="domain"):
        _fetcher(_redirects(chain)).fetch(start, allowed_domains=("wetten.overheid.nl",))
    chain["vertexaisearch.cloud.google.com"] = "https://wetten.overheid.nl/BWBR0005290"
    assert (
        _fetcher(_redirects(chain))
        .fetch(start, allowed_domains=("wetten.overheid.nl",))
        .url.startswith("https://wetten.overheid.nl/")
    )


def test_a_page_that_breaks_the_parser_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(_html: str) -> str:
        raise RecursionError

    monkeypatch.setattr(page_fetch, "html_to_clean_text", explode)
    with pytest.raises(PageFetchError, match="unreadable"):
        _fetcher(lambda _r: _html()).fetch("https://deep.example/")
