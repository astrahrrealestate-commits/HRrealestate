"""The owner's Google tokens reach every process: on ECS the API (which runs the connect callback) and the worker (which
polls Gmail) are separate tasks on throwaway disks, so the S3 bucket holds the shared copy and the local file is only
each process's cache."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import httpx
import pytest
import respx
from botocore.exceptions import ClientError
from moto import mock_aws
from pydantic import SecretStr

from app.channels import google_auth, google_store, registry
from app.channels.google_auth import (
    disconnect_owner,
    get_connection_status,
    load_owner_credentials,
    save_owner_credentials,
)
from app.core.settings import Settings

BUCKET = "estateos-test-creds"
CREDS = {"token": "t", "refresh_token": "r", "email": "owner@example.test", "name": "Owner"}


BASE = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="test", _env_file=None)  # type: ignore[arg-type]
S3 = BASE.model_copy(update={"storage_backend": "s3", "s3_bucket": BUCKET, "s3_region": "eu-north-1"})
LOCAL = BASE.model_copy(update={"storage_backend": "local"})


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def google() -> Iterator[respx.MockRouter]:
    """Disconnect revokes at Google; unit tests never reach the network."""
    with respx.mock(assert_all_called=False) as router:
        router.post(google_auth.REVOKE_URL, name="revoke").mock(return_value=httpx.Response(200))
        yield router


@pytest.fixture
def bucket(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="eu-north-1")
        client.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "eu-north-1"})
        google_store.forget_clients()
        yield client
        google_store.forget_clients()


def _fresh_process() -> None:
    """What a new container (or the worker task) starts with: no local file, nothing synced yet."""
    google_store.LOCAL_FILE.unlink(missing_ok=True)
    google_store.forget_sync()


def test_connecting_in_the_api_stores_the_tokens_in_the_shared_bucket(bucket: Any) -> None:
    save_owner_credentials(S3, dict(CREDS))
    body = bucket.get_object(Bucket=BUCKET, Key=google_store.SHARED_KEY)["Body"].read()
    assert json.loads(body)["refresh_token"] == "r"


@pytest.mark.usefixtures("bucket")
def test_another_process_sees_the_connected_mailbox() -> None:
    save_owner_credentials(S3, dict(CREDS))
    _fresh_process()

    assert registry.owner_login_email(S3) == "owner@example.test"
    assert get_connection_status(S3).connected is True
    assert google_store.LOCAL_FILE.stat().st_mode & 0o777 == 0o600


@pytest.mark.usefixtures("bucket")
def test_disconnecting_reaches_the_other_processes_too() -> None:
    save_owner_credentials(S3, dict(CREDS))
    disconnect_owner(S3)
    google_store.write_local(json.dumps(CREDS).encode())  # the worker's stale cache
    google_store.forget_sync()

    assert load_owner_credentials(S3) is None
    assert not google_store.LOCAL_FILE.exists()


@pytest.mark.usefixtures("bucket")
def test_a_storage_outage_keeps_the_last_good_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    save_owner_credentials(S3, dict(CREDS))
    google_store.forget_sync()
    monkeypatch.setattr(google_store, "_client", lambda _settings: _Broken())

    assert registry.owner_login_email(S3) == "owner@example.test"


def test_without_s3_the_local_file_is_the_only_copy() -> None:
    save_owner_credentials(LOCAL, dict(CREDS))
    google_store.forget_sync()

    assert registry.owner_login_email(LOCAL) == "owner@example.test"
    disconnect_owner(LOCAL)
    assert registry.owner_login_email(LOCAL) is None


class _Broken:
    def get_object(self, **_kwargs: object) -> object:
        from botocore.exceptions import EndpointConnectionError

        raise EndpointConnectionError(endpoint_url="https://s3.eu-north-1.amazonaws.com")


def test_the_shared_copy_never_holds_the_oauth_client_secret(bucket: Any) -> None:
    """The bucket also holds tenant media; the app's own OAuth client secret stays in Secrets Manager only and is put
    back into each process's local cache from Settings."""
    settings = S3.model_copy(update={"google_oauth_client_id": "cid", "google_oauth_client_secret": SecretStr("cs")})
    save_owner_credentials(settings, {**CREDS, "client_id": "cid", "client_secret": "cs"})
    shared = json.loads(bucket.get_object(Bucket=BUCKET, Key=google_store.SHARED_KEY)["Body"].read())
    assert "client_secret" not in shared
    assert "client_id" not in shared

    _fresh_process()
    local = json.loads(google_store.refresh(settings).read_text())
    assert (local["client_id"], local["client_secret"], local["refresh_token"]) == ("cid", "cs", "r")


def test_disconnecting_revokes_the_grant_at_google(google: respx.MockRouter) -> None:
    """Old token versions survive in a versioned bucket; a revoked grant makes them worthless."""
    revoke = google.routes["revoke"]
    save_owner_credentials(LOCAL, dict(CREDS))
    assert disconnect_owner(LOCAL) is True
    assert revoke.called
    assert b"token=r" in revoke.calls.last.request.content


def test_a_failed_revoke_still_disconnects(google: respx.MockRouter) -> None:
    google.routes["revoke"].mock(side_effect=httpx.ConnectError("down"))
    save_owner_credentials(LOCAL, dict(CREDS))
    assert disconnect_owner(LOCAL) is True
    assert load_owner_credentials(LOCAL) is None


def test_a_failed_upload_fails_the_connect_and_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connect the worker would never see must not look successful in the API."""
    monkeypatch.setattr(google_store, "_client", lambda _settings: _Denied())
    with pytest.raises(ClientError):
        save_owner_credentials(S3, dict(CREDS))
    assert not google_store.LOCAL_FILE.exists()


def test_access_denied_on_refresh_keeps_the_last_good_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    google_store.write_local(json.dumps(CREDS).encode())
    google_store.forget_sync()
    monkeypatch.setattr(google_store, "_client", lambda _settings: _Denied())
    assert registry.owner_login_email(S3) == "owner@example.test"


class _Denied:
    def _deny(self, **_kwargs: object) -> object:
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "S3")

    put_object = get_object = _deny
