"""FastAPI dependencies shared by routers (everything hangs off app.state, set by the app factory)."""

from typing import Any, Protocol, cast

from fastapi import Request
from sqlalchemy import Engine

from app.core.settings import Settings
from app.storage.factory import build_storage
from app.storage.ports import ObjectStorage


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


def get_storage(request: Request) -> ObjectStorage:
    """Built on first use (not at startup): an s3 client resolves credentials when created, which must not
    block apps that never serve attachments."""
    state = request.app.state
    if state.storage is None:
        state.storage = build_storage(state.settings)
    return cast(ObjectStorage, state.storage)
