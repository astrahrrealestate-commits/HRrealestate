"""Process-wide ingestion dependencies for workflow steps: built from settings once, overridable in tests."""

from functools import lru_cache

from dbos import DBOSClient
from sqlalchemy import Engine

from app.channels import google_store, registry
from app.channels.brixx.ports import BrixxApi
from app.core.errors import UnsafeConfigurationError
from app.core.settings import get_settings
from app.db.session import make_engine
from app.ingestion.process import IngestDeps
from app.llm.embeddings import TextEmbedder, build_embedder
from app.sender.execute import SenderDeps
from app.storage.drive import DriveStore, GoogleDrive, MemoryDrive, build_drive_service
from app.storage.extract import LocalExtractor, TextExtractor
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


_sender_override: SenderDeps | None = None


def get_sender_deps() -> SenderDeps:
    if _sender_override is not None:
        return _sender_override
    return _default_sender()


@lru_cache(maxsize=1)
def _default_sender() -> SenderDeps:
    from app.sender.deps import build_sender_deps

    return build_sender_deps(get_settings(), get_engine())


def set_sender_deps(deps: SenderDeps | None) -> None:
    """Tests inject fake outbound adapters here (None restores the settings-built default)."""
    global _sender_override
    _sender_override = deps


_engine_override: Engine | None = None


def get_engine() -> Engine:
    """The domain database for workflow steps (tests inject theirs with `set_engine`)."""
    return _engine_override if _engine_override is not None else get_deps().engine


def set_engine(engine: Engine | None) -> None:
    global _engine_override
    _engine_override = engine


_drive_override: DriveStore | None = None


@lru_cache(maxsize=1)
def _default_drive() -> DriveStore:
    settings = get_settings()
    if settings.drive_provider == "fake":
        return MemoryDrive()  # dev/sim: filing works end to end, nothing leaves the process
    if settings.drive_credentials_file is not None:
        return GoogleDrive(build_drive_service(settings.drive_credentials_file))
    owner = google_store.refresh(settings)  # the account connected in the Connections modal (drive.file scope)
    if not owner.exists():
        raise UnsafeConfigurationError("drive_provider 'google' needs drive_credentials_file or a connected Google")
    return GoogleDrive(build_drive_service(owner, scopes=None))


def get_drive() -> DriveStore:
    return _drive_override if _drive_override is not None else _default_drive()


def set_drive(drive: DriveStore | None) -> None:
    global _drive_override
    _drive_override = drive


_extractor_override: TextExtractor | None = None


def get_extractor() -> TextExtractor:
    return _extractor_override if _extractor_override is not None else LocalExtractor()


def set_extractor(extractor: TextExtractor | None) -> None:
    global _extractor_override
    _extractor_override = extractor


_embedder_override: TextEmbedder | None = None


@lru_cache(maxsize=1)
def _default_embedder() -> TextEmbedder:
    return build_embedder(get_settings())


def get_embedder() -> TextEmbedder:
    return _embedder_override if _embedder_override is not None else _default_embedder()


def set_embedder(embedder: TextEmbedder | None) -> None:
    global _embedder_override
    _embedder_override = embedder


_brixx_override: BrixxApi | None = None


@lru_cache(maxsize=1)
def _default_brixx() -> BrixxApi:
    return registry.brixx_api(get_settings())


def brixx_api() -> BrixxApi:
    """The BRIXX read API for workflow steps (fake unless `brixx_provider=api`)."""
    return _brixx_override if _brixx_override is not None else _default_brixx()


def set_brixx_api(api: BrixxApi | None) -> None:
    global _brixx_override
    _brixx_override = api
