"""Drive go-live check (#9): the drive.file token can create the EstateOS folder, upload, find by attachment id.

Writes one small file under EstateOS/_live-check and deletes it again (drive.file may delete files it created).
"""

from uuid import uuid4

import pytest

from app.core.settings import Settings
from app.storage.drive import GoogleDrive, build_drive_service


@pytest.mark.live("DRIVE_CREDENTIALS_FILE")
def test_drive_file_scope_uploads_and_finds_by_attachment(live_settings: Settings) -> None:
    assert live_settings.drive_credentials_file is not None
    service = build_drive_service(live_settings.drive_credentials_file)
    drive = GoogleDrive(service)
    attachment_id = uuid4()
    folder = drive.ensure_folder(("EstateOS", "_live-check"))
    file_id = drive.upload(
        drive.new_file_id(),
        folder,
        f"live-check-{attachment_id}.txt",
        "text/plain",
        b"EstateOS live-check",
        attachment_id,
    )
    try:
        assert drive.find_by_attachment(attachment_id) == file_id
        assert drive.upload(file_id, folder, "again.txt", "text/plain", b"x", attachment_id) == file_id  # 409 = done
    finally:
        service.files().delete(fileId=file_id).execute()
