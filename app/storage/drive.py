"""Google Drive filing port (#9, ADR 0005): a `DriveStore` Protocol, an in-memory fake and the Drive v3 adapter.

Scope `drive.file`: the app sees only files and folders it created, so lookups by name or app property never touch
Harjot's own Drive content. Uploads are idempotent by id: the caller reserves an id (`new_file_id`, Drive
`generateIds`), stores it in Postgres, and creates the file with that id. A repeated create of the same id gets 409
from Drive, which counts as "already uploaded", so a retry or a concurrent caller can never make a second copy.
Creates are sent once (`num_retries=0`): the DBOS step owns retries.
"""

import json
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

import httplib2  # type: ignore[import-untyped]  # no stubs published; only its error base class is used
from google.auth.exceptions import TransportError as AuthTransportError
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaInMemoryUpload

from app.core.errors import EstateOSError

DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive.file",)
FOLDER_MIME = "application/vnd.google-apps.folder"
APP_PROPERTY = "estateos_attachment_id"
RESUMABLE_ABOVE = 5 * 1024 * 1024  # Drive: multipart uploads are for files up to 5 MB
CHUNK_SIZE = 8 * 1024 * 1024
_RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "sharingRateLimitExceeded"})


class DriveApiError(EstateOSError):
    def __init__(self, message: str, *, status: int, retryable: bool) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def is_transient(exc: BaseException) -> bool:
    """For DBOS `should_retry`: Drive rate limits, 5xx and transport failures are retried; the rest fail the step."""
    return isinstance(exc, DriveApiError) and exc.retryable


class DriveStore(Protocol):
    def new_file_id(self) -> str: ...

    def find_by_attachment(self, attachment_id: UUID) -> str | None: ...

    def ensure_folder(self, path: tuple[str, ...]) -> str: ...

    def upload(
        self, file_id: str, folder_id: str, name: str, mime_type: str, content: bytes, attachment_id: UUID
    ) -> str: ...


class MemoryDrive:
    """Fake for tests and `make sim-demo`: folders by path, files by id with their attachment id."""

    def __init__(self) -> None:
        self.folders: dict[tuple[str, ...], str] = {}
        self.files: dict[str, tuple[str, str, UUID]] = {}  # file id → (folder id, name, attachment id)

    def new_file_id(self) -> str:
        return f"file-{uuid4()}"

    def find_by_attachment(self, attachment_id: UUID) -> str | None:
        return next((fid for fid, (_, _, att) in self.files.items() if att == attachment_id), None)

    def ensure_folder(self, path: tuple[str, ...]) -> str:
        if not path:
            raise ValueError("folder path must not be empty")
        return self.folders.setdefault(path, f"folder-{uuid4()}")

    def upload(
        self, file_id: str, folder_id: str, name: str, mime_type: str, content: bytes, attachment_id: UUID
    ) -> str:
        self.files.setdefault(file_id, (folder_id, name, attachment_id))  # same id twice = Drive's 409
        return file_id


def _quote(value: str) -> str:
    """Drive query string literal: backslash and single quote escaped."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _reasons(exc: HttpError) -> set[str]:
    try:
        errors = json.loads(exc.content).get("error", {}).get("errors", [])
    except (ValueError, AttributeError, TypeError):
        return set()
    return {str(e.get("reason")) for e in errors if isinstance(e, dict)}


def _typed(exc: HttpError, what: str) -> DriveApiError:
    status = int(getattr(exc.resp, "status", 0) or 0)
    retryable = status == 429 or status >= 500 or (status == 403 and bool(_reasons(exc) & _RATE_LIMIT_REASONS))
    return DriveApiError(f"drive {what} failed ({status})", status=status, retryable=retryable)


def _call(request: Any, what: str, *, retries: int = 3) -> Any:
    try:
        return request.execute(num_retries=retries)
    except HttpError as exc:
        raise _typed(exc, what) from exc
    except (OSError, httplib2.HttpLib2Error, AuthTransportError) as exc:  # network, DNS, TLS, token refresh
        raise DriveApiError(f"drive {what} failed ({type(exc).__name__})", status=0, retryable=True) from exc


class GoogleDrive:
    """Drive v3 over a googleapiclient service built with `drive.file` credentials (`build_drive_service`)."""

    def __init__(self, service: Any) -> None:
        self._files = service.files()

    def _first_id(self, query: str, what: str) -> str | None:
        request = self._files.list(q=query, spaces="drive", fields="files(id)", orderBy="createdTime", pageSize=1)
        files = _call(request, what).get("files") or []
        return str(files[0]["id"]) if files else None

    def new_file_id(self) -> str:
        return str(_call(self._files.generateIds(count=1, space="drive"), "generate id")["ids"][0])

    def find_by_attachment(self, attachment_id: UUID) -> str | None:
        prop = f"appProperties has {{ key={_quote(APP_PROPERTY)} and value={_quote(str(attachment_id))} }}"
        return self._first_id(f"{prop} and trashed = false", "lookup")

    def ensure_folder(self, path: tuple[str, ...]) -> str:
        """Find-or-create each level. The oldest duplicate wins, so concurrent first filings converge on one folder."""
        if not path:
            raise ValueError("folder path must not be empty")
        parent = "root"
        for name in path:
            query = f"mimeType = {_quote(FOLDER_MIME)} and name = {_quote(name)} and {_quote(parent)} in parents"
            found = self._first_id(f"{query} and trashed = false", "folder lookup")
            if found is None:
                body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent]}
                found = str(_call(self._files.create(body=body, fields="id"), "mkdir")["id"])
            parent = found
        return parent

    def upload(
        self, file_id: str, folder_id: str, name: str, mime_type: str, content: bytes, attachment_id: UUID
    ) -> str:
        body = {
            "id": file_id,
            "name": name,
            "parents": [folder_id],
            "appProperties": {APP_PROPERTY: str(attachment_id)},
        }
        resumable = len(content) > RESUMABLE_ABOVE
        media = MediaInMemoryUpload(content, mimetype=mime_type, resumable=resumable, chunksize=CHUNK_SIZE)
        try:
            _call(self._files.create(body=body, media_body=media, fields="id"), "upload", retries=0)
        except DriveApiError as exc:
            if exc.status != 409:  # 409: a file with this reserved id exists, i.e. an earlier attempt succeeded
                raise
        return file_id


def build_drive_service(credentials_file: Path) -> Any:
    """Drive v3 service from an authorized-user file created with the `drive.file` scope only."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(credentials_file), list(DRIVE_SCOPES))
    return build("drive", "v3", credentials=creds, cache_discovery=False)
