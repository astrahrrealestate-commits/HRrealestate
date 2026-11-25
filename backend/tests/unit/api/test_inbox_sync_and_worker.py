"""Regression tests for Gmail sync isolation from the API server into the worker."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pydantic import SecretStr

import app.main as main_mod
import app.worker as worker_mod
from app.api.inbox import routes as inbox_routes
from app.core.errors import GmailNotConnectedError
from app.core.settings import Settings
from app.workflows import queues


def _test_settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@localhost:1/db",  # type: ignore[arg-type]
        env="test",
        dashboard_session_secret=SecretStr("x" * 32),
        _env_file=None,
    )


def test_api_process_has_no_inline_auto_sync_loop() -> None:
    assert not hasattr(main_mod, "_auto_sync_loop")


def test_sync_gmail_accounts_skips_when_lock_held() -> None:
    deps = MagicMock()
    assert inbox_routes._SYNC_LOCK.acquire(blocking=False)
    try:
        assert inbox_routes.sync_gmail_accounts(deps) == 0
        deps.gmail_mailbox.assert_not_called()
    finally:
        inbox_routes._SYNC_LOCK.release()


def test_sync_gmail_accounts_closes_db_session_before_gmail_rpc() -> None:
    events: list[str] = []
    acct_id = uuid4()
    fake_acct = SimpleNamespace(id=acct_id, address="owner@example.test")

    class FakeSession:
        def __init__(self, _engine: object) -> None:
            events.append("session.init")

        def __enter__(self) -> "FakeSession":
            events.append("session.enter")
            return self

        def __exit__(self, *_args: object) -> None:
            events.append("session.exit")

        def scalars(self, _query: object) -> SimpleNamespace:
            return SimpleNamespace(all=lambda: [fake_acct], first=lambda: None)

    class FakeMailbox:
        def current_history_id(self) -> int:
            events.append("gmail.history")
            return 42

    deps = SimpleNamespace(engine=object(), gmail_mailbox=lambda _addr: FakeMailbox())

    def fake_sync_mailbox(_deps: object, _acct_id: object, history: int) -> int:
        events.append(f"sync_mailbox:{history}")
        return 3

    with (
        patch.object(inbox_routes, "Session", FakeSession),
        patch.object(inbox_routes, "sync_mailbox", fake_sync_mailbox),
    ):
        count = inbox_routes.sync_gmail_accounts(deps)  # type: ignore[arg-type]

    assert count == 3
    assert events == [
        "session.init",
        "session.enter",
        "session.exit",
        "gmail.history",
        "sync_mailbox:42",
    ]


def test_worker_poll_gmail_once_enqueues_per_connected_account() -> None:
    acct_disconnected = uuid4()
    acct_connected = uuid4()
    company_id = uuid4()
    enqueued: list[tuple[str | None, tuple[object, ...]]] = []

    class FakeQueue:
        def enqueue(self, fn: object, *args: object) -> None:
            enqueued.append((getattr(fn, "__name__", None), args))

    def fake_mailbox(address: str) -> SimpleNamespace:
        if address == "disconnected@example.test":
            raise GmailNotConnectedError("not connected")
        return SimpleNamespace(current_history_id=lambda: 9001)

    deps = SimpleNamespace(gmail_mailbox=fake_mailbox)

    @contextmanager
    def fake_set_wf_id(wf_id: str) -> Iterator[str]:
        yield wf_id

    with (
        patch.object(worker_mod, "get_deps", return_value=deps),
        patch.object(
            worker_mod,
            "gmail_accounts",
            return_value=[
                (acct_disconnected, "disconnected@example.test", company_id),
                (acct_connected, "connected@example.test", company_id),
            ],
        ),
        patch.object(queues, "gmail_sync_queue", return_value=FakeQueue()),
        patch.object(worker_mod, "SetWorkflowID", fake_set_wf_id),
    ):
        worker_mod._poll_gmail_once()

    assert enqueued == [("gmail_sync", (str(acct_connected), 9001))]


def test_worker_poll_thread_skips_when_gmail_provider_not_google() -> None:
    import threading

    stop = threading.Event()
    settings = _test_settings()
    settings.gmail_provider = "fake"
    assert worker_mod._start_gmail_poll_thread(settings, stop) is None
