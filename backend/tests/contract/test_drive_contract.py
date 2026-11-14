"""DriveStore contract: MemoryDrive and GoogleDrive (googleapiclient over a recording HTTP mock)."""

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import googleapiclient.http
import pytest
from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence

from app.storage import drive as drive_module
from app.storage.drive import APP_PROPERTY, FOLDER_MIME, DriveApiError, GoogleDrive, MemoryDrive, is_transient

ATTACHMENT = uuid4()
PDF = "application/pdf"


class RecordingHttp(HttpMockSequence):  # type: ignore[misc]
    def __init__(self, responses: list[tuple[dict[str, str], str]]) -> None:
        super().__init__(responses)
        self.calls: list[tuple[str, str, dict[str, list[str]], str]] = []

    def request(self, uri: str, method: str = "GET", body: Any = None, headers: Any = None, **kw: Any) -> Any:
        parts = urlsplit(uri)
        raw = body.decode("utf-8", "replace") if isinstance(body, bytes) else (body or "")
        self.calls.append((method, parts.path, parse_qs(parts.query), raw))
        return super().request(uri, method, body, headers, **kw)


def _ok(body: dict[str, Any]) -> tuple[dict[str, str], str]:
    return {"status": "200"}, json.dumps(body)


def _err(status: int, reason: str = "x") -> tuple[dict[str, str], str]:
    body = {"error": {"code": status, "message": "nope", "errors": [{"reason": reason}]}}
    return {"status": str(status)}, json.dumps(body)


def _google(responses: list[tuple[dict[str, str], str]]) -> tuple[GoogleDrive, RecordingHttp]:
    http = RecordingHttp(responses)
    return GoogleDrive(build("drive", "v3", http=http, static_discovery=True)), http


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(googleapiclient.http.time, "sleep", lambda _s: None)  # library backoff between retries


def test_memory_drive_contract() -> None:
    drive = MemoryDrive()
    folder = drive.ensure_folder(("EstateOS", "invoice", "2026"))
    assert drive.ensure_folder(("EstateOS", "invoice", "2026")) == folder
    assert drive.find_by_attachment(ATTACHMENT) is None
    file_id = drive.new_file_id()
    assert drive.upload(file_id, folder, "a.pdf", PDF, b"%PDF", ATTACHMENT) == file_id
    assert drive.upload(file_id, folder, "a.pdf", PDF, b"%PDF", ATTACHMENT) == file_id  # same id twice: one file
    assert len(drive.files) == 1
    assert drive.find_by_attachment(ATTACHMENT) == file_id
    with pytest.raises(ValueError, match="empty"):
        drive.ensure_folder(())


def test_google_new_file_id() -> None:
    drive, http = _google([_ok({"ids": ["reserved-1"], "space": "drive", "kind": "drive#generatedIds"})])
    assert drive.new_file_id() == "reserved-1"
    assert http.calls[0][1] == "/drive/v3/files/generateIds"


def test_google_ensure_folder_reuses_oldest_and_creates() -> None:
    drive, http = _google([_ok({"files": [{"id": "root-estateos"}]}), _ok({"files": []}), _ok({"id": "new-invoice"})])
    assert drive.ensure_folder(("EstateOS", "invoice")) == "new-invoice"
    (m1, p1, q1, _), (_, _, q2, _), (m3, p3, _, b3) = http.calls
    assert (m1, p1) == ("GET", "/drive/v3/files")
    assert q1["q"] == [f"mimeType = '{FOLDER_MIME}' and name = 'EstateOS' and 'root' in parents and trashed = false"]
    assert q1["orderBy"] == ["createdTime"]
    assert "'root-estateos' in parents" in q2["q"][0]
    assert (m3, p3) == ("POST", "/drive/v3/files")
    assert json.loads(b3) == {"name": "invoice", "mimeType": FOLDER_MIME, "parents": ["root-estateos"]}


def test_google_query_escapes_quotes() -> None:
    drive, http = _google([_ok({"files": [{"id": "f"}]})])
    drive.ensure_folder(("O'Brien \\ Co",))
    assert "name = 'O\\'Brien \\\\ Co'" in http.calls[0][2]["q"][0]


def test_google_upload_uses_reserved_id_and_tags_attachment() -> None:
    drive, http = _google([_ok({"id": "reserved-1"}), _ok({"files": [{"id": "reserved-1"}]})])
    name = "2026-10-07_invoice_jan_factuur.pdf"
    assert drive.upload("reserved-1", "folder-1", name, PDF, b"%PDF-1.4", ATTACHMENT) == "reserved-1"
    method, path, query, body = http.calls[0]
    assert (method, path, query["uploadType"]) == ("POST", "/upload/drive/v3/files", ["multipart"])
    assert '"id": "reserved-1"' in body
    assert f'"{APP_PROPERTY}": "{ATTACHMENT}"' in body
    assert '"parents": ["folder-1"]' in body
    assert "%PDF-1.4" in body
    assert drive.find_by_attachment(ATTACHMENT) == "reserved-1"
    lookup = http.calls[1][2]["q"][0]
    assert lookup == f"appProperties has {{ key='{APP_PROPERTY}' and value='{ATTACHMENT}' }} and trashed = false"


def test_google_upload_conflict_means_already_uploaded_and_is_sent_once() -> None:
    drive, http = _google([_err(409, "duplicate")])
    assert drive.upload("reserved-1", "folder-1", "a.pdf", PDF, b"%PDF", ATTACHMENT) == "reserved-1"
    drive, http = _google([_err(503)] * 4)
    with pytest.raises(DriveApiError) as exc:
        drive.upload("reserved-1", "folder-1", "a.pdf", PDF, b"%PDF", ATTACHMENT)
    assert exc.value.retryable
    assert len(http.calls) == 1  # no library re-POST: the DBOS step retries with the same reserved id


def test_google_large_files_upload_resumably(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []
    real = drive_module.MediaInMemoryUpload

    def spy(content: bytes, *, mimetype: str, resumable: bool, chunksize: int) -> Any:
        seen.append(resumable)
        return real(content, mimetype=mimetype, resumable=False, chunksize=chunksize)

    monkeypatch.setattr(drive_module, "MediaInMemoryUpload", spy)
    drive, _ = _google([_ok({"id": "a"}), _ok({"id": "b"})])
    drive.upload("a", "f", "small.pdf", PDF, b"x" * 1024, ATTACHMENT)
    drive.upload("b", "f", "big.pdf", PDF, b"x" * (drive_module.RESUMABLE_ABOVE + 1), ATTACHMENT)
    assert seen == [False, True]


@pytest.mark.parametrize(
    ("status", "reason", "retryable"),
    [(429, "x", True), (503, "x", True), (403, "userRateLimitExceeded", True), (403, "forbidden", False),
     (404, "notFound", False)],
)  # fmt: skip
def test_google_errors_are_typed(status: int, reason: str, retryable: bool) -> None:
    drive, _ = _google([_err(status, reason)] * 4)
    with pytest.raises(DriveApiError) as exc:
        drive.find_by_attachment(ATTACHMENT)
    assert (exc.value.status, exc.value.retryable, is_transient(exc.value)) == (status, retryable, retryable)


def test_google_transport_errors_are_retryable() -> None:
    class Broken:
        def execute(self, num_retries: int = 0) -> Any:
            raise TimeoutError("read timed out")

    class Files:
        def list(self, **_kw: Any) -> Broken:
            return Broken()

    class Service:
        def files(self) -> Files:
            return Files()

    with pytest.raises(DriveApiError) as exc:
        GoogleDrive(Service()).find_by_attachment(ATTACHMENT)
    assert is_transient(exc.value)


def test_memory_drive_relocate_annotate_and_missing_files() -> None:
    drive = MemoryDrive()
    old, new = drive.ensure_folder(("EstateOS", "invoice")), drive.ensure_folder(("EstateOS", "Unit 1", "Invoices"))
    file_id = drive.new_file_id()
    drive.upload(file_id, old, "a.pdf", PDF, b"%PDF", ATTACHMENT, description="Invoice", properties={"unit": "Unit 1"})
    assert drive.properties[file_id] == {APP_PROPERTY: str(ATTACHMENT), "unit": "Unit 1"}
    drive.relocate(file_id, new, "b.pdf")
    drive.relocate(file_id, new, "b.pdf")  # a repeat changes nothing
    assert drive.files[file_id][:2] == (new, "b.pdf")
    assert drive.path_of(file_id) == ("EstateOS", "Unit 1", "Invoices")
    drive.annotate(file_id, "New summary", {"date": "2026-10-07"})
    assert drive.description[file_id] == "New summary"
    assert drive.properties[file_id]["unit"] == "Unit 1"
    assert drive.properties[file_id]["date"] == "2026-10-07"
    for call in (lambda: drive.relocate("gone", new, "x"), lambda: drive.annotate("gone", None, {})):
        with pytest.raises(DriveApiError) as caught:
            call()
        assert caught.value.status == 404
        assert not is_transient(caught.value)


def test_google_upload_carries_description_and_properties() -> None:
    drive, http = _google([_ok({"id": "f1"})])
    drive.upload("f1", "folder", "a.pdf", PDF, b"%PDF", ATTACHMENT, description="Lease", properties={"unit": "U1"})
    body = next(c[3] for c in http.calls if "metadata" in c[3] or "estateos" in c[3])
    assert '"description": "Lease"' in body
    assert '"unit": "U1"' in body
    assert APP_PROPERTY in body


def test_google_relocate_moves_and_renames_once() -> None:
    drive, http = _google([_ok({"parents": ["old-folder"], "name": "a.pdf"}), _ok({"id": "f1"})])
    drive.relocate("f1", "new-folder", "b.pdf")
    (m1, p1, q1, _), (m2, p2, q2, b2) = http.calls
    assert (m1, p1) == ("GET", "/drive/v3/files/f1")
    assert q1["fields"] == ["parents,name"]
    assert (m2, p2) == ("PATCH", "/drive/v3/files/f1")
    assert (q2["addParents"], q2["removeParents"]) == (["new-folder"], ["old-folder"])
    assert json.loads(b2) == {"name": "b.pdf"}


def test_google_relocate_is_a_no_op_when_already_there() -> None:
    drive, http = _google([_ok({"parents": ["new-folder"], "name": "b.pdf"})])
    drive.relocate("f1", "new-folder", "b.pdf")
    assert len(http.calls) == 1  # only the lookup


def test_google_relocate_rename_only_does_not_send_remove_parents() -> None:
    drive, http = _google([_ok({"parents": ["new-folder"], "name": "a.pdf"}), _ok({"id": "f1"})])
    drive.relocate("f1", "new-folder", "b.pdf")
    assert "removeParents" not in http.calls[1][2]


def test_google_annotate_patches_description_and_properties() -> None:
    drive, http = _google([_ok({"id": "f1"})])
    drive.annotate("f1", "Summary", {"unit": "U1"})
    method, path, _, body = http.calls[0]
    assert (method, path) == ("PATCH", "/drive/v3/files/f1")
    assert json.loads(body) == {"appProperties": {"unit": "U1"}, "description": "Summary"}


def test_google_missing_file_is_a_permanent_404() -> None:
    drive, _ = _google([_err(404, "notFound")])
    with pytest.raises(DriveApiError) as caught:
        drive.relocate("gone", "folder", "a.pdf")
    assert caught.value.status == 404
    assert not is_transient(caught.value)
