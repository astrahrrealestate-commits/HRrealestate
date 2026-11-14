"""The opaque dashboard thread key: `{channel}:{ref}` urlsafe-base64 encoded. Pure, so request contracts validate it.

`app.pipeline.read_repo` re-exports these names; this module is the one definition.
"""

import base64
import binascii

from app.contracts.common import Channel
from app.core.errors import EstateOSError

MAX_REF_LEN = 255  # messages.thread_ref / provider_msg_id are String(255)
# Base64 of `{channel}:{ref}` for an ASCII ref of MAX_REF_LEN characters is at most 348 characters. The limit assumes
# ASCII refs (Message-IDs, WhatsApp ids): a long non-ASCII ref (up to 4 UTF-8 bytes per character) encodes longer and
# its key is refused (422) as `thread_key` or visible id.
MAX_THREAD_KEY = 400


class BadThreadKeyError(EstateOSError):
    """A thread key that does not decode to `{channel}:{ref}`."""


def encode_thread_key(channel: Channel, ref: str) -> str:
    """Opaque, path-safe key: refs may hold `<`, `@`, `/`, `%` (Message-IDs), so the pair is urlsafe-base64 encoded."""
    raw = f"{channel.value}:{ref}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_thread_key(key: str) -> tuple[Channel, str]:
    try:
        raw = base64.b64decode(key.replace("-", "+").replace("_", "/") + "=" * (-len(key) % 4), validate=True).decode()
        channel, sep, ref = raw.partition(":")
        if not sep or not ref or len(ref) > MAX_REF_LEN or any(ord(c) < 0x20 or c == "\x7f" for c in ref):
            raise ValueError("bad ref")
        return Channel(channel), ref
    except (binascii.Error, ValueError):  # UnicodeDecodeError is a ValueError
        raise BadThreadKeyError("invalid thread key") from None
