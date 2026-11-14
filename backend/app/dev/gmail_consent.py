"""Gmail consent: create the authorized-user token files with minimal scopes (docs/go-live-channels.md, Gmail 3).

One browser consent per file, so the read token cannot draft and the compose token cannot read. A file is written only
when the signed-in account is the expected mailbox and the granted scopes are exactly the requested ones. Output must
live outside the repository (tokens never get committed); files are 0600.

    uv run python -m app.dev.gmail_consent --client ~/.estateos/client.json --mailbox you@example.com \
        --out-dir ~/.estateos
"""

import argparse
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.core.errors import UnsafeConfigurationError
from app.core.logging import get_logger
from app.storage.drive import DRIVE_SCOPES

log = get_logger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[3]
# Same values as the adapters' READ_SCOPES / COMPOSE_SCOPES (tested); the compose module is sender-only (import-linter).
PURPOSES: dict[str, list[str]] = {
    "read": ["https://www.googleapis.com/auth/gmail.readonly"],
    "compose": ["https://www.googleapis.com/auth/gmail.compose"],
}
# Document filing (#9, ADR 0005): app-created files only. Opt-in (`--drive`), written as drive-file.json.
DRIVE_PURPOSE: tuple[str, list[str]] = ("file", list(DRIVE_SCOPES))
# Tenant replies in send mode: its own token, never the compose one. Same values as the sender's SEND_SCOPES (tested);
# gmail.metadata lets the idempotency lookup (threads.get) run. Opt-in (`--reply-send`): gmail-reply-send.json.
REPLY_SEND_PURPOSE: tuple[str, list[str]] = (
    "reply-send",
    ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.metadata"],
)
CALENDAR_PURPOSE: tuple[str, list[str]] = (
    "calendar",
    ["https://www.googleapis.com/auth/calendar"],
)


@dataclass(frozen=True)
class Consent:
    authorize: Callable[[list[str]], Credentials]  # browser consent for exactly these scopes
    profile_email: Callable[[Credentials], str]  # the signed-in mailbox address


def create_token_files(
    consent: Consent,
    mailbox: str,
    out_dir: Path,
    *,
    drive: bool = False,
    reply_send: bool = False,
    calendar: bool = False,
) -> list[Path]:
    """Consent once per purpose; write `gmail-<purpose>.json` (and `drive-file.json`) only after every check passed."""
    out_dir = out_dir.expanduser().resolve()
    if _inside(out_dir, REPO_ROOT):
        raise UnsafeConfigurationError(f"token files must live outside the repository, not in {out_dir}")
    if calendar and not (drive or reply_send):
        wanted = {"calendar": CALENDAR_PURPOSE[1]}
    else:
        wanted = {f"gmail-{purpose}": scopes for purpose, scopes in PURPOSES.items()}
        if drive:
            wanted[f"drive-{DRIVE_PURPOSE[0]}"] = DRIVE_PURPOSE[1]
        if reply_send:
            wanted[f"gmail-{REPLY_SEND_PURPOSE[0]}"] = REPLY_SEND_PURPOSE[1]
        if calendar:
            wanted["calendar"] = CALENDAR_PURPOSE[1]
    tokens = {name: _checked(consent, scopes, mailbox) for name, scopes in wanted.items()}
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return [_write_private(out_dir / f"{name}.json", creds.to_json()) for name, creds in tokens.items()]


def _inside(path: Path, root: Path) -> bool:
    """Case-insensitive on macOS/Windows filesystems too (`resolve` keeps the typed case of missing parts)."""
    return Path(os.path.normcase(path)).is_relative_to(Path(os.path.normcase(root.resolve())))


def _checked(consent: Consent, scopes: list[str], mailbox: str) -> Credentials:
    creds = consent.authorize(scopes)
    granted = set(creds.granted_scopes or [])
    if granted != set(scopes):  # exactly the purpose's scopes: a broader token must never be written
        raise UnsafeConfigurationError(f"granted scopes {sorted(granted)} differ from requested {scopes}")
    if not creds.refresh_token:
        raise UnsafeConfigurationError(
            "no refresh token returned; revoke the app's access in the Google account, rerun"
        )
    actual = consent.profile_email(creds).lower()
    if actual != mailbox.lower():  # an unreadable profile ("") is refused too
        raise UnsafeConfigurationError(f"signed in as {actual}, expected {mailbox.lower()}")
    return creds


def _write_private(path: Path, text: str) -> Path:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)  # never write through a symlink where supported
    if hasattr(os, "fchmod"):
        os.fchmod(fd, 0o600)  # before any byte: O_CREAT's mode does not apply to an existing file
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    return path


def google_consent(client_file: Path) -> Consent:
    def authorize(scopes: list[str]) -> Credentials:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scopes=scopes)
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
        if not isinstance(creds, Credentials):
            raise UnsafeConfigurationError(f"unexpected credential type {type(creds).__name__}")
        return creds

    def profile_email(creds: Credentials) -> str:
        if any("calendar" in scope for scope in creds.granted_scopes or []):
            try:
                cal = build("calendar", "v3", credentials=creds, cache_discovery=False).calendars()
                res = cal.get(calendarId="primary").execute()
                return str(res.get("id") or res.get("summary") or "")
            except Exception:
                try:
                    clist = build("calendar", "v3", credentials=creds, cache_discovery=False).calendarList()
                    return str(clist.get(calendarId="primary").execute().get("id") or "")
                except Exception:
                    return ""
        if any("drive" in scope for scope in creds.granted_scopes or []):  # a Drive-only token cannot read Gmail
            about = build("drive", "v3", credentials=creds, cache_discovery=False).about()
            return str(about.get(fields="user(emailAddress)").execute()["user"]["emailAddress"])
        users = build("gmail", "v1", credentials=creds, cache_discovery=False).users()
        return str(users.getProfile(userId="me").execute()["emailAddress"])

    return Consent(authorize=authorize, profile_email=profile_email)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.dev.gmail_consent", description="Create Gmail token files.")
    parser.add_argument("--client", type=Path, required=True, help="OAuth Desktop client JSON")
    parser.add_argument("--mailbox", required=True, help="the mailbox address the tokens must belong to")
    parser.add_argument("--out-dir", type=Path, required=True, help="directory outside the repository")
    parser.add_argument("--drive", action="store_true", help="also create drive-file.json (document filing, #9)")
    parser.add_argument(
        "--reply-send",
        action="store_true",
        help=(
            "also create gmail-reply-send.json (tenant replies, send mode); "
            "re-consents three tokens: read, compose, reply-send"
        ),
    )
    parser.add_argument("--calendar", action="store_true", help="also create calendar.json (Google Calendar events)")
    args = parser.parse_args(argv)
    if "@" not in args.mailbox:  # fail before two browser consents, not after
        parser.error(f"--mailbox must be an email address, got {args.mailbox!r}")
    consent = google_consent(args.client.expanduser())
    for path in create_token_files(
        consent, args.mailbox, args.out_dir, drive=args.drive, reply_send=args.reply_send, calendar=args.calendar
    ):
        log.info("gmail.consent.written", path=str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
