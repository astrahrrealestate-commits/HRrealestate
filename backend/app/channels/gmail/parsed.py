"""Result types of email parsing."""

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedAttachment:
    filename: str | None
    mime_type: str
    data: bytes
    inline: bool = False
    content_id: str | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class ParsedEmail:
    from_addr: str | None
    from_name: str | None
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    subject: str = ""
    message_id: str | None = None
    in_reply_to: str | None = None
    references: str | None = None
    text: str = ""
    full_text: str = ""
    html: str | None = None
    quote_stripped: bool = False
    attachments: list[ParsedAttachment] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    parse_error: bool = False
    reply_to: list[tuple[str, str | None]] = field(default_factory=list)  # (address, display name)
    forwarded_from: str | None = None  # original sender when this mail is a forward
    forwarded_from_name: str | None = None
