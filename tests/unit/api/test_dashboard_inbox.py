import base64
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.contracts import Channel, Direction
from app.core.settings import Settings
from app.db.enums import PipelineStatus
from app.main import create_app
from app.pipeline.read_repo import BadThreadKeyError, ThreadRow, decode_thread_key, encode_thread_key
from app.storage.memory import MemoryStorage

SETTINGS = Settings(  # type: ignore[call-arg]
    database_url="postgresql+psycopg://u:p@localhost:1/db",
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)
PRINCIPAL = Principal(company_id=uuid4(), owner_id=uuid4(), email="h@example.test")
T0 = datetime(2026, 1, 1, tzinfo=UTC)
HOSTILE = ["<CAF=abc+d@mail.gmail.com>", "a/b/../c", "100%25 ?x=1#f", "naïve ✉ \u0000 ref", "a:b:c", " "]


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock(), storage=MemoryStorage())
    with TestClient(app) as c:
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        yield c


@pytest.mark.parametrize("ref", HOSTILE)
@pytest.mark.parametrize("channel", list(Channel))
def test_thread_key_roundtrip_and_path_safe(channel: Channel, ref: str) -> None:
    key = encode_thread_key(channel, ref)
    assert all(c.isalnum() or c in "-_" for c in key)
    assert decode_thread_key(key) == (channel, ref)


@pytest.mark.parametrize(
    "key",
    [
        "",
        "!!!",
        "bm9jb2xvbg",
        base64.urlsafe_b64encode(b"fax:x").decode(),
        base64.urlsafe_b64encode(b"gmail:").decode(),
        base64.urlsafe_b64encode(b"\xff\xfe").decode(),
    ],
)
def test_undecodable_key_rejected(key: str) -> None:
    with pytest.raises(BadThreadKeyError):
        decode_thread_key(key)


def test_thread_route_malformed_and_unknown_share_one_404(client: TestClient) -> None:
    malformed = client.get("/api/v1/threads/!!!")
    with patch("app.api.v1.inbox.thread_messages", return_value=[]):
        unknown = client.get(f"/api/v1/threads/{encode_thread_key(Channel.gmail, 'x')}")
    assert malformed.status_code == unknown.status_code == 404
    assert malformed.json() == unknown.json()


def test_inbox_bad_cursor_422(client: TestClient) -> None:
    assert client.get("/api/v1/inbox", params={"before": "junk"}).status_code == 422


def test_inbox_requires_auth() -> None:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock(), storage=MemoryStorage())
    with TestClient(app) as c:
        assert c.get("/api/v1/inbox").status_code == 401
        assert c.get("/api/v1/threads/abc").status_code == 401


def test_inbox_passes_company_and_serialises(client: TestClient) -> None:
    row = ThreadRow(
        thread_key="k", channel=Channel.gmail, last_at=T0, last_message_id=UUID(int=7), last_text="hi", sender="a@b",
        person_name=None, case_id=None, unread_pipeline=PipelineStatus.pending, message_count=2,
    )  # fmt: skip
    seen: dict[str, Any] = {}

    def fake(_s: Any, company_id: UUID, *, before: Any, limit: int) -> list[ThreadRow]:
        seen.update(company_id=company_id, before=before, limit=limit)
        return [row]

    with patch("app.api.v1.inbox.inbox_page", fake), patch("app.api.v1.inbox.Session", MagicMock()):
        body = client.get("/api/v1/inbox", params={"limit": 1000}).json()
    assert seen == {"company_id": PRINCIPAL.company_id, "before": None, "limit": 1000}  # clamped in the repo
    assert body[0]["cursor"] == f"{T0.isoformat()}|{UUID(int=7)}"
    assert body[0]["unread_pipeline"] == "pending"


def test_thread_attachment_url_ttl_and_flags(client: TestClient) -> None:
    mid = uuid4()
    msg = SimpleNamespace(
        id=mid, direction=Direction.inbound, sent_at=T0, sender_identity="+31", text="<script>", delivery_status=None,
        pipeline_status=PipelineStatus.pending, meta={"suspicious": True},
    )  # fmt: skip
    att = SimpleNamespace(
        id=uuid4(), message_id=mid, filename="f.pdf", mime_type="application/pdf", size_bytes=3, s3_key="media/c/ab/abc"
    )
    with (
        patch("app.api.v1.inbox.thread_messages", return_value=[msg]),
        patch("app.api.v1.inbox.attachments_for", return_value=[att]),
        patch("app.api.v1.inbox.Session", MagicMock()),
    ):
        body = client.get(f"/api/v1/threads/{encode_thread_key(Channel.whatsapp, '+31')}").json()
    assert body[0]["suspicious"] is True
    assert body[0]["pipeline_status"] == "pending"
    assert body[0]["text"] == "<script>"
    url = body[0]["attachments"][0]["url"]
    assert int(parse_qs(urlparse(url).query)["expires_in"][0]) <= 300
