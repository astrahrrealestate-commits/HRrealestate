"""BRIXX mirror operator CLI (Phase B): record metadata, generate the mirror migration, run a first load.

    python -m app.dev.brixx discover [--out tests/fixtures/brixx/metadata] [--force]

`discover` calls only the BRIXX metadata endpoints (never row data) through the same adapter the worker uses
(`registry.brixx_api(Settings())`) and writes the snapshot. Output names tables and counts only: never the token or
a row value. Every failure is one line on stderr and exit code 1, never a traceback.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from app.channels import registry
from app.channels.brixx.ports import BrixxApi
from app.channels.brixx.snapshot import record_snapshot, write_snapshot
from app.core.errors import BrixxAuthError, BrixxError, UnsafeConfigurationError
from app.core.settings import Settings

DEFAULT_SNAPSHOT = Path("tests/fixtures/brixx/metadata")
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_settings()
    api = live_api(settings)
    if api is None:
        return 1
    return discover(api, settings, args.out, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
