"""Identity of a text for caches: sha256 of its NFC-normalised, stripped form (surrounding space is not new text)."""

import hashlib
import unicodedata


def normalise(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip()


def source_hash(text: str) -> str:
    return hashlib.sha256(normalise(text).encode()).hexdigest()
