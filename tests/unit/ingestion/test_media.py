from uuid import UUID

from app.ingestion.media import store_attachment
from app.storage.memory import MemoryStorage

COMPANY = UUID("01900000-0000-7000-8000-000000000001")


def test_attachment_metadata_fits_its_columns_and_is_clean() -> None:
    """Provider-supplied names and types go into String(255) columns: oversize or hostile values must never fail the
    insert (a DataError would cost the whole message)."""
    att = store_attachment(MemoryStorage(), COMPANY, b"%PDF", "application/pdf\x00; x=" + "y" * 400, "a/" + "b" * 400)
    assert att.mime_type == "application/octet-stream"
    assert att.filename is not None
    assert len(att.filename) <= 255
    assert "/" not in att.filename


def test_mime_parameters_are_dropped_not_the_type() -> None:
    att = store_attachment(MemoryStorage(), COMPANY, b"OggS", "Audio/OGG; codecs=opus", "voice.ogg")
    assert att.mime_type == "audio/ogg"
