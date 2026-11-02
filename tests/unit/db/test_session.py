"""Engine settings that protect tenant data."""

from app.db.session import make_engine


def test_engine_hides_statement_parameters() -> None:
    """DBAPIError text would otherwise include `[parameters: ...]` with row values; DBOS and Sentry persist it."""
    engine = make_engine("postgresql+psycopg://u:p@localhost:1/db")
    assert engine.hide_parameters is True
