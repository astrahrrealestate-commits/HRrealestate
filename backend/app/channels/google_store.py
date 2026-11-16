"""The owner's Google tokens (Gmail, Calendar, Drive), shared by every process.

ECS runs the API and the worker as separate tasks on throwaway disks: a file the API's connect callback writes is
invisible to the worker that polls Gmail, and every redeploy (or the nightly stage stop) deletes it. With
`storage_backend == "s3"` the bucket holds the one shared copy and each process keeps the local file as a cache,
refreshed at most every `REFRESH_S` seconds. Any other backend keeps the local file alone (local development).

The shared copy never holds the app's own OAuth client id and secret (they stay in Secrets Manager); `refresh` puts
them back into the local cache from Settings, so `Credentials.from_authorized_user_file` keeps working.

A thin adapter of its own because `app.channels` and `app.storage` are independent layers (import-linter); it stores
exactly one object, under a key no content-addressed upload can produce.
"""

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.logging import get_logger
from app.core.settings import Settings

log = get_logger(__name__)

LOCAL_FILE = Path(".data/credentials/google_owner.json")
SHARED_KEY = "credentials/google_owner.json"
REFRESH_S = 30.0
CLIENT_FIELDS = ("client_id", "client_secret")
_CONFIG = Config(retries={"mode": "standard", "max_attempts": 3}, connect_timeout=5, read_timeout=10)
_MISSING = {"NoSuchKey", "404"}

# `_lock` guards the local file, `_synced_at` and `_generation`; it is never held across a network call. Every local
# change bumps `_generation`, so a refresh whose S3 read started before a connect/disconnect cannot overwrite it.
_lock = threading.Lock()
_synced_at: float | None = None
_generation = 0
_clients: dict[tuple[str | None, str | None], Any] = {}


def _shared(settings: Settings) -> bool:
    return settings.storage_backend == "s3" and bool(settings.s3_bucket)


def _client(settings: Settings) -> Any:
    key = (settings.s3_region, settings.s3_endpoint_url)
    with _lock:  # boto3 client creation from the default session is not thread-safe
        if key not in _clients:
            secret = settings.s3_secret_access_key.get_secret_value() if settings.s3_secret_access_key else None
            _clients[key] = boto3.client(
                "s3",
                region_name=settings.s3_region,
                config=_CONFIG,
                endpoint_url=settings.s3_endpoint_url,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=secret,
            )
        return _clients[key]


def forget_clients() -> None:
    _clients.clear()


def forget_sync() -> None:
    """The next `refresh` reads the shared copy whatever its age (tests; a fresh process starts like this)."""
    global _synced_at
    _synced_at = None


def write_local(data: bytes) -> Path:
    """Atomic and owner-only: a reader never sees a half-written file, nobody else reads the tokens."""
    LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=LOCAL_FILE.parent, prefix=".google_owner.")  # created 0600
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, LOCAL_FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return LOCAL_FILE


def _changed_locally() -> None:
    """Under `_lock`: the local file now holds the newest state."""
    global _synced_at, _generation
    _generation += 1
    _synced_at = time.monotonic()


def publish(settings: Settings, credentials: dict[str, Any]) -> Path:
    """Write the tokens to the shared copy (S3, without the client secret) and locally. A failed upload raises before
    anything is written: a connect the worker would never see must not look successful."""
    if _shared(settings):
        shared = {k: v for k, v in credentials.items() if k not in CLIENT_FIELDS}
        _client(settings).put_object(
            Bucket=settings.s3_bucket, Key=SHARED_KEY, Body=json.dumps(shared).encode(), ContentType="application/json"
        )
    with _lock:
        path = write_local(json.dumps(credentials, indent=2).encode())
        _changed_locally()
    return path


def withdraw(settings: Settings) -> None:
    if _shared(settings):
        _client(settings).delete_object(Bucket=settings.s3_bucket, Key=SHARED_KEY)
    with _lock:
        LOCAL_FILE.unlink(missing_ok=True)
        _changed_locally()


def _with_client_fields(settings: Settings, body: bytes) -> bytes:
    data = json.loads(body)
    secret = settings.google_oauth_client_secret
    data.setdefault("client_id", settings.google_oauth_client_id)
    data.setdefault("client_secret", secret.get_secret_value() if secret else None)
    return json.dumps(data, indent=2).encode()


def _read_shared(settings: Settings) -> tuple[bool, bytes | None]:
    """(read ok, body or None when no account is connected)."""
    try:
        body: bytes = _client(settings).get_object(Bucket=settings.s3_bucket, Key=SHARED_KEY)["Body"].read()
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in _MISSING:
            return True, None
        log.warning("google_store.refresh_failed", error=type(exc).__name__)
        return False, None
    except BotoCoreError as exc:
        log.warning("google_store.refresh_failed", error=type(exc).__name__)
        return False, None
    return True, body


def refresh(settings: Settings) -> Path:
    """The local cache path, first brought up to date with the shared copy when that is due. A storage outage keeps
    the last good cache (and waits `REFRESH_S` before trying again) rather than signing the mailbox out."""
    global _synced_at
    if not _shared(settings):
        return LOCAL_FILE
    with _lock:
        if _synced_at is not None and time.monotonic() - _synced_at < REFRESH_S:
            return LOCAL_FILE
        generation = _generation
    ok, body = _read_shared(settings)
    with _lock:
        if generation != _generation:  # a connect/disconnect in this process is newer than what we read
            return LOCAL_FILE
        if ok and body is None:
            LOCAL_FILE.unlink(missing_ok=True)
        elif ok and body is not None:
            write_local(_with_client_fields(settings, body))
        _synced_at = time.monotonic()
    return LOCAL_FILE
