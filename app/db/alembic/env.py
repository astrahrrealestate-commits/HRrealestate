"""Alembic environment.

Only the default (`public`) schema is managed. DBOS keeps its tables in schema `dbos`; autogenerate never sees them
because `include_schemas` is off (only the default schema is reflected).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import app.db.models  # noqa: F401  (registers tables)
from app.db.alembic_hooks import normalise_enum_checks
from app.db.base import Base

config = context.config
if config.config_file_name is not None and not config.attributes.get("database_url"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    url = config.attributes.get("database_url") or context.get_x_argument(as_dictionary=True).get("url")
    if url:
        return str(url)
    from app.core.settings import get_settings

    return get_settings().sqlalchemy_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=Base.metadata,
        literal_binds=True,
        compare_type=True,
        process_revision_directives=normalise_enum_checks,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_type=True,
            process_revision_directives=normalise_enum_checks,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
