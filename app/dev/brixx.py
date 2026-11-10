"""BRIXX mirror operator CLI (Phase B): record metadata, generate the mirror migration, run a first load.

    python -m app.dev.brixx discover [--out tests/fixtures/brixx/metadata] [--force]
    python -m app.dev.brixx codegen [--snapshot tests/fixtures/brixx/metadata] [--alembic app/db/alembic]

`discover` calls only the BRIXX metadata endpoints (never row data) through the same adapter the worker uses
(`registry.brixx_api(Settings())`) and writes the snapshot. `codegen` turns the snapshot into the next Alembic revision
(only what earlier generated revisions lack; `app/dev/brixx_codegen.py`). Output names tables and counts only: never
the token or a row value. Every failure is one line on stderr and exit code 1, never a traceback.
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from alembic.script import ScriptDirectory
from alembic.util import CommandError
from pydantic import ValidationError

from app.channels import registry
from app.channels.brixx.ports import BrixxApi
from app.channels.brixx.snapshot import read_snapshot, record_snapshot, write_snapshot
from app.core.errors import BrixxAuthError, BrixxError, UnsafeConfigurationError
from app.core.settings import Settings
from app.dev.brixx_codegen import existing_mirror, plan_delta, render_migration

DEFAULT_SNAPSHOT = Path("tests/fixtures/brixx/metadata")
DEFAULT_ALEMBIC = Path("app/db/alembic")
AUTH_HINT = (
    "BRIXX rejected the request (HTTP 401/403). Likely causes: this machine's public IP is not on the BRIXX IP "
    "whitelist (an unlisted IP also returns 401), or BRIXX_TOKEN / BRIXX_AUTH_SCHEME (raw|bearer) is wrong."
)


def load_settings() -> Settings:
    """Settings from the environment and .env. Metadata commands need no database, so a missing URL is tolerated."""
    try:
        return Settings()
    except ValidationError:
        return Settings(database_url="postgresql+psycopg://unused@localhost/unused")  # type: ignore[arg-type]


def fail(message: str) -> int:
    sys.stderr.write(f"brixx: {message}\n")
    return 1


def discover(api: BrixxApi, settings: Settings, out: Path, *, force: bool) -> int:
    try:
        tables = record_snapshot(api)
        if not tables:
            return fail("BRIXX listed no tables for this token; nothing recorded")
        write_snapshot(out, tables, environment=settings.brixx_environment, force=force)
    except BrixxAuthError:
        return fail(AUTH_HINT)
    except BrixxError as exc:
        return fail(str(exc))
    fields = sum(len(t.fields) for t in tables)
    sys.stdout.write(f"recorded {len(tables)} tables ({fields} fields) into {out}\n")
    return 0


def _next_revision(script: ScriptDirectory) -> tuple[str, str]:
    """(new revision id, current head): ids are zero-padded numbers, so the next one is the highest plus one."""
    heads = script.get_heads()
    if len(heads) != 1:
        raise BrixxError(f"expected one Alembic head, found {len(heads)}: merge the branches first")
    numbers = [int(r.revision) for r in script.walk_revisions() if r.revision.isdigit()]
    return f"{max(numbers, default=0) + 1:04d}", heads[0]


def codegen(snapshot: Path, alembic: Path, *, now: datetime) -> int:
    try:
        tables = read_snapshot(snapshot)
        script = ScriptDirectory(str(alembic))
        revision, head = _next_revision(script)
        versions = sorted((alembic / "versions").glob("*.py"))
        delta = plan_delta(tables, existing_mirror(p.read_text(encoding="utf-8") for p in versions))
        if delta.empty:
            sys.stdout.write("the mirror migrations already match the snapshot: nothing generated\n")
            return 0
        source = render_migration(delta, revision=revision, down_revision=head, create_date=now)
        target = alembic / "versions" / f"{revision}_brixx_mirror{'' if delta.first else '_delta'}.py"
        with target.open("x", encoding="utf-8") as fh:  # never overwrites a committed revision
            fh.write(source)
    except (BrixxError, CommandError, FileExistsError) as exc:
        return fail(str(exc))
    columns = sum(len(c) for _t, c in delta.new_columns)
    sys.stdout.write(f"wrote {target}: {len(delta.new_tables)} new tables, {columns} new columns\n")
    return 0


def live_api(settings: Settings) -> BrixxApi | None:
    """The real adapter, or None (after explaining why) when settings cannot reach BRIXX."""
    if settings.brixx_provider == "fake":
        fail("BRIXX_PROVIDER is 'fake'; set BRIXX_PROVIDER=api and BRIXX_TOKEN in .env to reach BRIXX")
        return None
    try:
        return registry.brixx_api(settings)
    except (UnsafeConfigurationError, BrixxError) as exc:
        fail(str(exc))
        return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.dev.brixx", description="BRIXX mirror operator commands")
    commands = parser.add_subparsers(dest="command", required=True)
    found = commands.add_parser("discover", help="record BRIXX table metadata (no row data) as a snapshot")
    found.add_argument("--out", type=Path, default=DEFAULT_SNAPSHOT)
    found.add_argument("--force", action="store_true", help="replace an existing snapshot")
    gen = commands.add_parser("codegen", help="write the Alembic revision for the snapshot's mirror tables")
    gen.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    gen.add_argument("--alembic", type=Path, default=DEFAULT_ALEMBIC, help="Alembic script directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "codegen":
        return codegen(args.snapshot, args.alembic, now=datetime.now(UTC))
    settings = load_settings()
    api = live_api(settings)
    if api is None:
        return 1
    return discover(api, settings, args.out, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
