from pathlib import Path

import pytest

from app.channels.whatsapp.fake_media import DirWhatsAppMedia
from app.channels.whatsapp.media import MediaBlob
from app.core.errors import NotFoundError


def test_blob_written_by_one_instance_is_downloaded_by_another(tmp_path: Path) -> None:
    DirWhatsAppMedia(tmp_path).put("MEDIA_1", MediaBlob(b"\xff\xd8jpeg", "image/jpeg"))  # simulator
    blob = DirWhatsAppMedia(tmp_path).download("MEDIA_1")  # worker
    assert (blob.data, blob.mime_type) == (b"\xff\xd8jpeg", "image/jpeg")


def test_unknown_media_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        DirWhatsAppMedia(tmp_path).download("MEDIA_404")


@pytest.mark.parametrize("media_id", ["../etc/passwd", ".hidden", "", "a/b", "x" * 200])
def test_media_ids_never_become_paths(tmp_path: Path, media_id: str) -> None:
    media = DirWhatsAppMedia(tmp_path / "media")
    with pytest.raises(NotFoundError):
        media.download(media_id)
    with pytest.raises(ValueError, match="media id"):
        media.put(media_id, MediaBlob(b"x", "image/jpeg"))
    assert not (tmp_path / "etc").exists()


def test_download_never_reads_outside_its_directory(tmp_path: Path) -> None:
    (tmp_path / "secret.json").write_text('{"mime_type": "text/plain"}')
    (tmp_path / "secret.bin").write_bytes(b"not yours")
    with pytest.raises(NotFoundError):
        DirWhatsAppMedia(tmp_path / "media").download("../secret")
