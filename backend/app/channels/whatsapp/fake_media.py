"""Fake WhatsApp media shared through a directory: the simulator puts blobs, the worker downloads them.

Media ids come from webhook payloads, so they are validated before they become file names.
"""

import json
import os
import re
import tempfile
from pathlib import Path

from app.channels.whatsapp.media import MediaBlob
from app.core.errors import NotFoundError

_MEDIA_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


class DirWhatsAppMedia:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def put(self, media_id: str, blob: MediaBlob) -> None:
        if not _MEDIA_ID.fullmatch(media_id):
            raise ValueError(f"invalid media id {media_id[:40]!r}")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._write(self._dir / f"{media_id}.bin", blob.data)
        self._write(self._dir / f"{media_id}.json", json.dumps({"mime_type": blob.mime_type}).encode())  # publish

    def download(self, media_id: str) -> MediaBlob:
        meta = self._dir / f"{media_id}.json"
        if not _MEDIA_ID.fullmatch(media_id) or not meta.exists():
            raise NotFoundError(f"media {media_id[:40]}")
        mime_type = str(json.loads(meta.read_text())["mime_type"])
        return MediaBlob((self._dir / f"{media_id}.bin").read_bytes(), mime_type)

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        fd, tmp = tempfile.mkstemp(dir=path.parent)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        Path(tmp).replace(path)
