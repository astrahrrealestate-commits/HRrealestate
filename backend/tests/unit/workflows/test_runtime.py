from app.core.settings import Settings
from app.workflows import brixx_documents, runtime
from app.workflows.runtime import SCHEDULES, dbos_config


def test_dbos_config_does_not_pin_application_version() -> None:
    cfg = dbos_config(Settings(database_url="postgresql+psycopg://u:p@h:5433/db", _env_file=None))  # type: ignore[call-arg]
    assert "application_version" not in cfg  # DBOS hashes workflow source instead (ADR 0001)
    assert cfg["system_database_url"] == "postgresql://u:p@h:5433/db"


def test_schedule_names_unique() -> None:
    names = [s["schedule_name"] for s in SCHEDULES]
    assert len(names) == len(set(names))


def test_document_download_workflows_are_registered_at_launch() -> None:
    assert brixx_documents in runtime._REGISTERED
