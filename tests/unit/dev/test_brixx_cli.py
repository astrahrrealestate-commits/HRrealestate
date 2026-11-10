"""`python -m app.dev.brixx`: discover writes a metadata snapshot; failures are one clear line, never a traceback."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.channels.brixx.fake import FakeBrixxApi, FakeTable
from app.channels.brixx.models import BrixxField, BrixxPage, BrixxTable
from app.channels.brixx.snapshot import read_snapshot
from app.core.errors import BrixxAuthError, BrixxError
from app.core.settings import Settings
from app.dev import brixx as cli

TOKEN = "tok-secret-987"
DB = "postgresql+psycopg://u:p@localhost/db"


def _info(name: str) -> BrixxTable:
    return BrixxTable(name, "ID", (BrixxField(1, "ID", "NUMBER", True, None, None),))


class RejectingApi:
    """What the HTTP adapter raises when the IP is not whitelisted or the token is wrong."""

    def list_tables(self) -> list[tuple[str, str]]:
        raise BrixxAuthError("BRIXX rejected the token (HTTP 401)")

    def describe_table(self, name: str) -> BrixxTable:
        raise AssertionError("not reached")

    def fetch_page(
        self, table: str, *, page: int, filters: str | None = None, order_by: str | None = None
    ) -> BrixxPage:
        raise AssertionError("never fetches rows")

    def download_document(self, document_id: int) -> bytes:
        raise AssertionError("never downloads")


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": DB,
        "brixx_provider": "api",
        "brixx_token": SecretStr(TOKEN),
        "brixx_environment": "hrrealestate",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_discover_writes_the_snapshot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeBrixxApi({"PRG_B": FakeTable(_info("PRG_B"), [{"ID": 1}]), "PRG_A": FakeTable(_info("PRG_A"), [])})
    out = tmp_path / "metadata"
    assert cli.discover(api, _settings(), out, force=False) == 0
    assert [t.name for t in read_snapshot(out)] == ["PRG_A", "PRG_B"]
    printed = capsys.readouterr().out
    assert "2 tables" in printed
    assert TOKEN not in printed
    assert api.fetch_log == []


def test_discover_auth_failure_names_token_and_ip_whitelist(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.discover(RejectingApi(), _settings(), tmp_path / "m", force=False) == 1
    captured = capsys.readouterr()
    for cause in ("IP whitelist", "BRIXX_TOKEN"):
        assert cause in captured.err
    assert "Traceback" not in captured.err
    assert TOKEN not in captured.err + captured.out
    assert not (tmp_path / "m").exists()


def test_discover_refuses_an_empty_listing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.discover(FakeBrixxApi({}), _settings(), tmp_path / "m", force=False) == 1
    assert "no tables" in capsys.readouterr().err
    assert not (tmp_path / "m").exists()


def test_main_refuses_the_fake_provider(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(brixx_provider="fake", brixx_token=None))
    assert cli.main(["discover", "--out", "unused"]) == 1
    assert "BRIXX_PROVIDER=api" in capsys.readouterr().err


def test_main_reports_a_missing_token(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(brixx_token=None))
    assert cli.main(["discover", "--out", "unused"]) == 1
    assert "brixx_token" in capsys.readouterr().err


def test_main_turns_brixx_errors_into_one_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Broken(RejectingApi):
        def list_tables(self) -> list[tuple[str, str]]:
            raise BrixxError("BRIXX request failed (ConnectTimeout)")

    monkeypatch.setattr(cli, "load_settings", _settings)
    monkeypatch.setattr(cli.registry, "brixx_api", lambda _s: Broken())
    assert cli.main(["discover", "--out", str(tmp_path / "m")]) == 1
    err = capsys.readouterr().err
    assert "ConnectTimeout" in err
    assert "Traceback" not in err


EXAMPLE = Path(__file__).parents[2] / "fixtures" / "brixx" / "metadata_example"
WHEN = datetime(2026, 11, 3, 9, 30, tzinfo=UTC)


def _alembic_dir(root: Path) -> Path:
    versions = root / "alembic" / "versions"
    versions.mkdir(parents=True)
    for rev, down in (("0001", None), ("0002", "0001")):
        (versions / f"{rev}_x.py").write_text(f"revision = {rev!r}\ndown_revision = {down!r}\n", encoding="utf-8")
    return root / "alembic"


def test_codegen_writes_the_next_revision_then_reports_up_to_date(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    alembic = _alembic_dir(tmp_path)
    assert cli.codegen(EXAMPLE, alembic, now=WHEN) == 0
    written = alembic / "versions" / "0003_brixx_mirror.py"
    source = written.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "0002"' in source
    assert "op.create_table('prg_relatie'" in source
    assert str(written) in capsys.readouterr().out

    assert cli.codegen(EXAMPLE, alembic, now=WHEN) == 0  # same snapshot again: nothing new, no duplicate tables
    assert "already match" in capsys.readouterr().out
    assert sorted(p.name for p in (alembic / "versions").glob("*.py")) == ["0001_x.py", "0002_x.py", written.name]


def test_codegen_refuses_two_heads(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    alembic = _alembic_dir(tmp_path)
    (alembic / "versions" / "0003_y.py").write_text("revision = '0003'\ndown_revision = '0001'\n", encoding="utf-8")
    assert cli.codegen(EXAMPLE, alembic, now=WHEN) == 1
    assert "head" in capsys.readouterr().err
    assert not list((alembic / "versions").glob("*brixx*"))


def test_codegen_without_a_snapshot_says_to_discover_first(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.codegen(tmp_path / "none", _alembic_dir(tmp_path), now=WHEN) == 1
    assert "discover" in capsys.readouterr().err
