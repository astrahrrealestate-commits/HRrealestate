"""FastAPI dependencies shared by routers (everything hangs off app.state, set by the app factory)."""

from typing import Any, Protocol, cast

from fastapi import Request
from sqlalchemy import Engine

from app.channels import registry
from app.core.settings import Settings
from app.ingestion.process import IngestDeps
from app.llm.embeddings import TextEmbedder, build_embedder
from app.storage.factory import build_storage
from app.storage.ports import ObjectStorage
from app.translation.ports import Translator


class WorkflowClient(Protocol):
    """The slice of `dbos.DBOSClient` the API uses (narrow, so tests can pass a fake)."""

    def enqueue(self, options: Any, *args: Any) -> Any: ...

    def enqueue_in_transaction(self, conn_or_session: Any, options: Any, *args: Any) -> Any: ...


def get_engine(request: Request) -> Engine:
    return cast(Engine, request.app.state.engine)


def get_settings_dep(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_workflow_client(request: Request) -> WorkflowClient:
    return cast(WorkflowClient, request.app.state.workflow_client)


def storage_for(state: Any) -> ObjectStorage:
    """Built on first use (not at startup): an s3 client resolves credentials when created, which must not
    block apps that never serve attachments."""
    if state.storage is None:
        state.storage = build_storage(state.settings)
    return cast(ObjectStorage, state.storage)


def get_storage(request: Request) -> ObjectStorage:
    return storage_for(request.app.state)


def get_translator(request: Request) -> Translator:
    return cast(Translator, request.app.state.translator)


def ingest_deps_for(state: Any) -> IngestDeps:
    """The API's own ingestion deps (on-demand Gmail sync), built once from app.state: the API never imports
    app.workflows. Raw events are enqueued by name through the API's DBOS client, like every other API write."""
    if getattr(state, "ingest_deps", None) is None:
        settings = cast(Settings, state.settings)
        state.ingest_deps = IngestDeps(
            engine=cast(Engine, state.engine),
            storage=storage_for(state),
            enqueuer=cast(WorkflowClient, state.workflow_client),
            gmail_mailbox=lambda address: registry.gmail_mailbox(settings, address),
            whatsapp_media=lambda pnid: registry.whatsapp_media(settings, pnid),
            gmail_topic=settings.gmail_pubsub_topic or "",  # sync never renews the watch; the worker does
        )
    return cast(IngestDeps, state.ingest_deps)


def get_ingest_deps(request: Request) -> IngestDeps:
    return ingest_deps_for(request.app.state)


def get_embedder_dep(request: Request) -> TextEmbedder:
    """Built on first use and kept: building a provider client per request is wasted work."""
    state = request.app.state
    if getattr(state, "embedder", None) is None:
        state.embedder = build_embedder(state.settings)
    return cast(TextEmbedder, state.embedder)
