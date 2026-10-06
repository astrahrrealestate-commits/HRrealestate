"""Fake Gmail mailbox emitting real API shapes (raw format, monotonic history ids) for dev, tests and the simulator.

`DirMailboxStore` keeps state as JSON files with an flock, so the simulator (writer) and api/worker (readers) share
one mailbox across processes. `MemoryMailboxStore` is for tests.
"""

import base64
import fcntl
import json
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from app.channels.gmail.models import GmailMessage, parse_api_message
from app.channels.gmail.ports import HistoryExpiredError, HistoryPage, WatchResult
from app.core.errors import NotFoundError


class MailboxStore(Protocol):
    def append(self, build: Callable[[int], dict[str, Any]]) -> dict[str, Any]:
        """Atomically: allocate history N, persist the record, then publish N (readers never see N without it)."""
        ...

    def load(self, message_id: str) -> dict[str, Any] | None: ...

    def records(self) -> list[dict[str, Any]]: ...

    def state(self) -> dict[str, int]: ...

    def set_expired_before(self, history_id: int) -> None: ...


class MemoryMailboxStore:
    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._state = {"history": 0, "expired_before": 0}

    def append(self, build: Callable[[int], dict[str, Any]]) -> dict[str, Any]:
        record = build(self._state["history"] + 1)
        self._records[record["id"]] = record
        self._state["history"] += 1
        return record

    def load(self, message_id: str) -> dict[str, Any] | None:
        return self._records.get(message_id)

    def records(self) -> list[dict[str, Any]]:
        return sorted(self._records.values(), key=lambda r: int(r["historyId"]))

    def state(self) -> dict[str, int]:
        return dict(self._state)

    def set_expired_before(self, history_id: int) -> None:
        self._state["expired_before"] = history_id


class DirMailboxStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        (root / "messages").mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked_state(self) -> Iterator[dict[str, int]]:
        with (self._root / "state.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self._root / "state.json"
            state = json.loads(path.read_text()) if path.exists() else {"history": 0, "expired_before": 0}
            yield state
            self._write(path, json.dumps(state))

    @staticmethod
    def _write(path: Path, text: str) -> None:
        fd, tmp = tempfile.mkstemp(dir=path.parent)
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        Path(tmp).replace(path)

    def append(self, build: Callable[[int], dict[str, Any]]) -> dict[str, Any]:
        with self._locked_state() as state:
            record = build(state["history"] + 1)
            self._write(self._root / "messages" / f"{record['id']}.json", json.dumps(record))  # message first
            state["history"] += 1  # then publish the new history id (written when the lock is released)
            return record

    def load(self, message_id: str) -> dict[str, Any] | None:
        path = self._root / "messages" / f"{message_id}.json"
        if not message_id.isalnum() or not path.exists():
            return None
        record: dict[str, Any] = json.loads(path.read_text())
        return record

    def records(self) -> list[dict[str, Any]]:
        loaded = [json.loads(p.read_text()) for p in (self._root / "messages").glob("*.json")]
        return sorted(loaded, key=lambda r: int(r["historyId"]))

    def state(self) -> dict[str, int]:
        path = self._root / "state.json"
        return json.loads(path.read_text()) if path.exists() else {"history": 0, "expired_before": 0}

    def set_expired_before(self, history_id: int) -> None:
        with self._locked_state() as state:
            state["expired_before"] = history_id


class FakeMailbox:
    def __init__(self, address: str, store: MailboxStore, *, page_size: int = 100) -> None:
        self.address = address
        self._store = store
        self._page_size = page_size

    # -- test/simulator helpers ----------------------------------------------------------------------------------

    def add_message(self, raw: bytes, *, labels: list[str], thread_id: str | None = None) -> str:
        def build(history: int) -> dict[str, Any]:
            return {
                "id": f"{history:016x}",
                "threadId": thread_id or f"thread{history:011x}",
                "labelIds": labels,
                "historyId": str(history),
                "internalDate": str(int(datetime.now(UTC).timestamp() * 1000)),
                "sizeEstimate": len(raw),
                "raw": base64.urlsafe_b64encode(raw).decode().rstrip("="),
            }

        message_id: str = self._store.append(build)["id"]
        return message_id

    def find_by_rfc822_id(self, rfc822_id: str, label: str) -> str | None:
        needle = f"Message-ID: {rfc822_id}".encode()
        for record in self._store.records():
            if label in record["labelIds"] and needle in parse_api_message(record).raw:
                found: str = record["id"]
                return found
        return None

    def expire_history_before(self, history_id: int) -> None:
        self._store.set_expired_before(history_id)

    # -- GmailMailbox ----------------------------------------------------------------------------------------------

    def history_since(self, start_history_id: int, page_token: str | None = None) -> HistoryPage:
        state = self._store.state()
        if start_history_id < state["expired_before"]:
            raise HistoryExpiredError(f"history {start_history_id} expired")
        ids = [r["id"] for r in self._store.records() if int(r["historyId"]) > start_history_id]
        offset = int(page_token) if page_token and page_token.isdigit() else 0
        page = ids[offset : offset + self._page_size]
        more = offset + self._page_size < len(ids)
        return HistoryPage(
            message_ids=page,
            history_id=state["history"],
            next_page_token=str(offset + self._page_size) if more else None,
        )

    def get_message(self, message_id: str) -> GmailMessage:
        record = self._store.load(message_id)
        if record is None:
            raise NotFoundError(f"gmail message {message_id}")
        return parse_api_message(record)

    def watch(self, topic: str) -> WatchResult:
        return WatchResult(history_id=self.current_history_id(), expiration=datetime.now(UTC) + timedelta(days=7))

    def current_history_id(self) -> int:
        return self._store.state()["history"]

    def message_ids_since(self, after: datetime) -> list[str]:
        cutoff = int(after.timestamp() * 1000)
        return [r["id"] for r in self._store.records() if int(r["internalDate"]) >= cutoff]
