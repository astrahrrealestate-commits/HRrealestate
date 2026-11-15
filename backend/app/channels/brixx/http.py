"""BRIXX HTTP adapter (httpx). Read-only; no retries here (DBOS steps retry); the token never leaves the header."""

import logging
import re
from typing import Literal, cast
from urllib.parse import urlparse

import httpx
from pydantic import SecretStr

from app.channels.brixx.models import BrixxField, BrixxPage, BrixxTable
from app.channels.brixx.normalise import normalise_row
from app.channels.brixx.query import data_query_params
from app.core.errors import BrixxAuthError, BrixxError, BrixxNotFoundError

_TABLE_NAME = re.compile(r"[A-Za-z0-9_]+")
Json = dict[str, object]
_QUIET_LOGGERS = ("httpx", "httpcore")


def _as_dict(value: object, what: str) -> Json:
    if not isinstance(value, dict):
        raise BrixxError(f"BRIXX returned an unexpected {what}")
    return cast(Json, value)


def _as_list(value: object, what: str) -> list[object]:
    if not isinstance(value, list):
        raise BrixxError(f"BRIXX returned an unexpected {what}")
    return value


def _parse_field(raw: object) -> BrixxField:
    data = _as_dict(raw, "field")
    refs = data.get("references")
    ref = _as_dict(refs, "field reference") if refs else {}
    fk_table, fk_field = ref.get("foreignKeyTable"), ref.get("foreignKeyField")
    try:
        return BrixxField(
            id=int(str(data["id"])),
            name=str(data["name"]),
            type=str(data.get("type", "")),
            required=bool(data.get("required", False)),
            fk_table=str(fk_table) if fk_table else None,
            fk_field=str(fk_field) if fk_field else None,
        )
    except (KeyError, ValueError) as exc:
        raise BrixxError("BRIXX returned a malformed field") from exc


class HttpBrixxApi:
    def __init__(
        self,
        base_url: str,
        environment: str,
        token: SecretStr,
        auth_scheme: Literal["raw", "bearer"],
        timeout_sec: float,
        client: httpx.Client | None = None,
    ) -> None:
        if client is None and urlparse(base_url).scheme != "https":
            raise BrixxError("brixx_base_url must be https (the token travels in a header)")
        for name in _QUIET_LOGGERS:  # their INFO request line carries the full URL incl. filter values (PII)
            logging.getLogger(name).setLevel(logging.WARNING)
        self._base = base_url.rstrip("/")
        self._env = environment
        self._token = token
        self._scheme = auth_scheme
        self._client = client or httpx.Client(timeout=timeout_sec)

    def __repr__(self) -> str:
        return f"HttpBrixxApi(base={self._base!r}, environment={self._env!r})"

    def _headers(self) -> dict[str, str]:
        secret = self._token.get_secret_value()
        return {"Authorization": f"Bearer {secret}" if self._scheme == "bearer" else secret}

    def _get(self, path: str, params: dict[str, str] | None = None) -> httpx.Response:
        url = f"{self._base}/{path}"
        try:
            response = self._client.get(url, params=params, headers=self._headers())
        except httpx.HTTPError as exc:  # message may carry URL/headers: keep the class name only
            raise BrixxError(f"BRIXX request failed ({type(exc).__name__})") from None
        status = response.status_code
        if status in (401, 403):
            raise BrixxAuthError(f"BRIXX rejected the token (HTTP {status})")
        if status == 404:  # never transient: the resource at this URL does not exist, retrying cannot help
            raise BrixxNotFoundError(f"BRIXX request failed (HTTP {status})")
        if status >= 300:
            raise BrixxError(f"BRIXX request failed (HTTP {status})")
        return response

    def _json(self, path: str, params: dict[str, str] | None = None) -> object:
        try:
            return self._get(path, params).json()
        except ValueError:
            raise BrixxError("BRIXX returned a non-JSON body") from None

    @staticmethod
    def _segment(name: str) -> str:
        if not _TABLE_NAME.fullmatch(name):
            raise BrixxError("invalid BRIXX table name")
        return name.lower()

    def list_tables(self) -> list[tuple[str, str]]:
        body = _as_list(self._json(f"metadata/{self._env}/tables"), "table list")
        out: list[tuple[str, str]] = []
        for item in body:
            row = _as_dict(item, "table entry")
            if "name" not in row or "primaryKeyField" not in row:
                raise BrixxError("BRIXX table entry lacks name or primaryKeyField")
            out.append((str(row["name"]), str(row["primaryKeyField"])))
        return out

    def describe_table(self, name: str) -> BrixxTable:
        body = _as_dict(self._json(f"metadata/{self._env}/tables/{self._segment(name)}"), "table description")
        fields = tuple(_parse_field(f) for f in _as_list(body.get("fields", []), "field list"))
        if "primaryKeyField" not in body:
            raise BrixxError("BRIXX table description lacks primaryKeyField")
        return BrixxTable(str(body.get("name", name)), str(body["primaryKeyField"]), fields)

    def fetch_page(
        self,
        table: str,
        *,
        page: int,
        filters: str | None = None,
        order_by: str | None = None,
        fields: tuple[str, ...] | None = None,
    ) -> BrixxPage:
        params = data_query_params(page, filters, order_by, fields)
        body = _as_dict(self._json(f"bigdata/{self._env}/table/{self._segment(table)}", params), "data page")
        if "data" not in body:
            raise BrixxError("BRIXX data page has no data list")
        rows = [normalise_row(_as_dict(r, "row")) for r in _as_list(body["data"], "row list")]
        meta = _as_dict(body.get("meta") or {}, "page meta")
        links = _as_dict(body.get("links") or {}, "page links")
        return BrixxPage(
            rows=rows,
            page=int(str(meta.get("currentPage", page))),
            per_page=int(str(meta.get("perPage", len(rows)))),
            has_next=bool(links.get("next")),
        )

    def download_document(self, document_id: int) -> bytes:
        return self._get(f"bigdata/{self._env}/document/{int(document_id)}").content
