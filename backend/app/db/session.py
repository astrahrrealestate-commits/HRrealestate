"""Engine and session factories. Sessions are short-lived; callers commit explicitly."""

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

CONNECT_TIMEOUT_SEC = 3  # psycopg default is ~130s: readiness probes must answer, not hang
POOL_TIMEOUT_SEC = 15
POOL_SIZE = 8
MAX_OVERFLOW = 12
POOL_RECYCLE_SEC = 1800


def make_engine(
    url: str,
    *,
    pool_size: int | None = None,
    max_overflow: int | None = None,
    pool_timeout: int | None = None,
) -> Engine:
    resolved_pool = pool_size if pool_size is not None else int(os.environ.get("DB_POOL_SIZE", POOL_SIZE))
    resolved_overflow = (
        max_overflow if max_overflow is not None else int(os.environ.get("DB_MAX_OVERFLOW", MAX_OVERFLOW))
    )
    resolved_timeout = (
        pool_timeout if pool_timeout is not None else int(os.environ.get("DB_POOL_TIMEOUT_SEC", POOL_TIMEOUT_SEC))
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,  # DBAPIError text would otherwise carry tenant row values into DBOS and Sentry
        pool_size=resolved_pool,
        max_overflow=resolved_overflow,
        pool_timeout=resolved_timeout,
        pool_recycle=POOL_RECYCLE_SEC,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SEC},
    )


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
