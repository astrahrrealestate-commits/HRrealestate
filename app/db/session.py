"""Engine and session factories. Sessions are short-lived; callers commit explicitly."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

CONNECT_TIMEOUT_SEC = 3  # psycopg default is ~130s: readiness probes must answer, not hang
POOL_TIMEOUT_SEC = 5


def make_engine(url: str) -> Engine:
    return create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,  # DBAPIError text would otherwise carry tenant row values into DBOS and Sentry
        pool_timeout=POOL_TIMEOUT_SEC,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SEC},
    )


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
