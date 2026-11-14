"""Gmail consent tool: one minimal-scope token file per purpose, only for the expected mailbox, never in the repo."""

import json
import stat
from pathlib import Path

import pytest
from google.oauth2.credentials import Credentials

from app.channels.gmail.drafts import COMPOSE_SCOPES
from app.channels.gmail.google import READ_SCOPES
from app.core.errors import UnsafeConfigurationError
from app.dev import gmail_consent as gc

MAILBOX = "Owner@Example.com"


def _creds(scopes: list[str]) -> Credentials:
    return Credentials(
        token="t",
        refresh_token="r",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="cid",
        client_secret="secret",
        scopes=scopes,
        granted_scopes=scopes,
    )


def _consent(granted: list[str] | None = None, mailbox: str = "owner@example.com") -> gc.Consent:
    return gc.Consent(
        authorize=lambda scopes: _creds(granted if granted is not None else scopes),
        profile_email=lambda _creds: mailbox,
    )


def test_scopes_match_the_adapters() -> None:
    assert gc.PURPOSES == {"read": READ_SCOPES, "compose": COMPOSE_SCOPES}


def test_writes_one_private_token_file_per_purpose(tmp_path: Path) -> None:
    written = gc.create_token_files(_consent(), MAILBOX, tmp_path)

    assert [p.name for p in written] == ["gmail-read.json", "gmail-compose.json"]
    for path, scopes in zip(written, (READ_SCOPES, COMPOSE_SCOPES), strict=True):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        data = json.loads(path.read_text())
        assert data["refresh_token"] == "r"
        assert data["scopes"] == scopes
        assert Credentials.from_authorized_user_file(str(path), scopes).refresh_token == "r"


def test_wrong_mailbox_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(UnsafeConfigurationError, match=r"someone@else\.com"):
        gc.create_token_files(_consent(mailbox="someone@else.com"), MAILBOX, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_extra_or_missing_scope_writes_nothing(tmp_path: Path) -> None:
    both = READ_SCOPES + COMPOSE_SCOPES
    with pytest.raises(UnsafeConfigurationError, match="scopes"):
        gc.create_token_files(_consent(granted=both), MAILBOX, tmp_path)
    with pytest.raises(UnsafeConfigurationError, match="scopes"):
        gc.create_token_files(_consent(granted=[]), MAILBOX, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_missing_refresh_token_writes_nothing(tmp_path: Path) -> None:
    no_refresh = Credentials(token="t", scopes=READ_SCOPES, granted_scopes=READ_SCOPES)
    consent = gc.Consent(authorize=lambda _scopes: no_refresh, profile_email=lambda _creds: MAILBOX)
    with pytest.raises(UnsafeConfigurationError, match="refresh token"):
        gc.create_token_files(consent, MAILBOX, tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("sub", ["secrets", "SECRETS/deeper"])
def test_refuses_output_inside_the_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sub: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(gc, "REPO_ROOT", repo)
    via_link = tmp_path / "link"
    via_link.symlink_to(repo)
    for out in (repo / sub, via_link / sub):
        with pytest.raises(UnsafeConfigurationError, match="outside the repository"):
            gc.create_token_files(_consent(), MAILBOX, out)
    assert list(repo.iterdir()) == []


def test_existing_loose_file_is_tightened_and_symlinks_refused(tmp_path: Path) -> None:
    loose = tmp_path / "gmail-read.json"
    loose.write_text("old")
    loose.chmod(0o644)
    assert stat.S_IMODE(gc.create_token_files(_consent(), MAILBOX, tmp_path)[0].stat().st_mode) == 0o600

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "target.json").write_text("keep")
    (elsewhere / "gmail-read.json").symlink_to(elsewhere / "target.json")
    with pytest.raises(OSError):
        gc.create_token_files(_consent(), MAILBOX, elsewhere)
    assert (elsewhere / "target.json").read_text() == "keep"


def test_cli_rejects_a_missing_mailbox_before_any_consent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gc, "google_consent", lambda _client: pytest.fail("consent must not start"))
    with pytest.raises(SystemExit):
        gc.main(["--client", "c.json", "--mailbox", "", "--out-dir", str(tmp_path)])


def test_drive_token_is_opt_in_and_has_only_the_drive_file_scope(tmp_path: Path) -> None:
    from app.storage.drive import DRIVE_SCOPES

    written = gc.create_token_files(_consent(), MAILBOX, tmp_path, drive=True)
    assert [p.name for p in written] == ["gmail-read.json", "gmail-compose.json", "drive-file.json"]
    assert json.loads(written[-1].read_text())["scopes"] == list(DRIVE_SCOPES)
    assert [p.name for p in gc.create_token_files(_consent(), MAILBOX, tmp_path / "plain")] == [
        "gmail-read.json",
        "gmail-compose.json",
    ]


def test_reply_send_scopes_match_the_adapter() -> None:
    from app.channels.gmail.drafts import SEND_SCOPES

    assert gc.REPLY_SEND_PURPOSE == ("reply-send", SEND_SCOPES)


def test_reply_send_token_is_opt_in_and_has_exactly_the_send_scopes(tmp_path: Path) -> None:
    from app.channels.gmail.drafts import SEND_SCOPES

    written = gc.create_token_files(_consent(), MAILBOX, tmp_path, reply_send=True)
    assert [p.name for p in written] == ["gmail-read.json", "gmail-compose.json", "gmail-reply-send.json"]
    assert json.loads(written[-1].read_text())["scopes"] == SEND_SCOPES
    assert stat.S_IMODE(written[-1].stat().st_mode) == 0o600
    plain = gc.create_token_files(_consent(), MAILBOX, tmp_path / "plain")
    assert "gmail-reply-send.json" not in [p.name for p in plain]


def test_reply_send_refuses_extra_scopes_and_wrong_mailbox_writing_nothing(tmp_path: Path) -> None:
    from app.channels.gmail.drafts import SEND_SCOPES

    def authorize(scopes: list[str]) -> Credentials:
        granted = [*scopes, "https://www.googleapis.com/auth/gmail.readonly"] if scopes == SEND_SCOPES else scopes
        return _creds(granted)

    greedy = gc.Consent(authorize=authorize, profile_email=lambda _c: "owner@example.com")
    with pytest.raises(UnsafeConfigurationError, match="scopes"):
        gc.create_token_files(greedy, MAILBOX, tmp_path, reply_send=True)
    with pytest.raises(UnsafeConfigurationError, match=r"someone@else\.com"):
        gc.create_token_files(_consent(mailbox="someone@else.com"), MAILBOX, tmp_path, reply_send=True)
    assert list(tmp_path.iterdir()) == []


def test_cli_passes_reply_send_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def fake_create(
        _c: gc.Consent, _m: str, _o: Path, *, drive: bool = False, reply_send: bool = False, calendar: bool = False
    ) -> list[Path]:
        seen.append(reply_send)
        return []

    monkeypatch.setattr(gc, "google_consent", lambda _client: _consent())
    monkeypatch.setattr(gc, "create_token_files", fake_create)
    gc.main(["--client", "c.json", "--mailbox", "a@b.c", "--out-dir", str(tmp_path), "--reply-send"])
    assert seen == [True]
