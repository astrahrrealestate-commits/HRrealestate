"""Process-wide ingestion dependencies for workflow steps: built from settings once, overridable in tests."""

from functools import lru_cache

from dbos import DBOSClient

from app.channels import registry
from app.core.settings import get_settings
from app.db.session import make_engine
from app.ingestion.process import IngestDeps
from app.storage.factory import build_storage

DEV_TOPIC = "projects/estateos-dev/topics/gmail"
_override: IngestDeps | None = None


@lru_cache(maxsize=1)
def _default() -> IngestDeps:
    settings = get_settings()
    return IngestDeps(
        engine=make_engine(settings.sqlalchemy_url),
        storage=build_storage(settings),
        enqueuer=DBOSClient(system_database_url=settings.dbos_database_url, lazy=True),
        gmail_mailbox=lambda address: registry.gmail_mailbox(settings, address),
        whatsapp_media=lambda pnid: registry.whatsapp_media(settings, pnid),
        gmail_topic=settings.gmail_pubsub_topic or DEV_TOPIC,
    )


def get_deps() -> IngestDeps:
    return _override or _default()


def set_deps(deps: IngestDeps | None) -> None:
    """Tests inject fakes here (None restores the settings-built default)."""
    global _override
    _override = deps
