"""ASGI app factory. Run: `uvicorn app.main:create_app --factory`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dbos import DBOSClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

import app
from app.api import health
from app.api.deps import WorkflowClient
from app.api.v1 import auth as dashboard_auth
from app.api.v1.ratelimit import RateLimiter
from app.api.v1.router import api_v1_router
from app.api.webhooks import gmail as gmail_webhook
from app.api.webhooks import google_chat as google_chat_webhook
from app.api.webhooks import whatsapp as whatsapp_webhook
from app.channels import registry
from app.channels.gmail.push import PushVerifier
from app.channels.google_chat.verifier import ChatVerifier
from app.core.logging import configure_logging
from app.core.settings import Settings, get_settings
from app.core.startup import assert_production_safe
from app.core.telemetry import init_telemetry
from app.db.session import make_engine
from app.storage.ports import ObjectStorage


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    workflow_client: WorkflowClient | None = None,
    gmail_push_verifier: PushVerifier | None = None,
    google_chat_verifier: ChatVerifier | None = None,
    id_token_verifier: dashboard_auth.IdTokenVerifier | None = None,
    storage: ObjectStorage | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    assert_production_safe(settings)
    registry.assert_channels_ready(settings)
    configure_logging(settings.env)
    init_telemetry(settings)  # before routes are built: Sentry patches FastAPI request handlers at init
    owns_engine = engine is None
    resolved_engine = engine or make_engine(settings.sqlalchemy_url)

    @asynccontextmanager
    async def lifespan(api: FastAPI) -> AsyncIterator[None]:
        api.state.engine = resolved_engine
        api.state.settings = settings
        api.state.storage = storage
        api.state.workflow_client = workflow_client or DBOSClient(
            system_database_url=settings.dbos_database_url, lazy=True
        )
        api.state.gmail_push_verifier = gmail_push_verifier or registry.gmail_push_verifier(settings)
        api.state.google_chat_verifier = google_chat_verifier or registry.google_chat_verifier(settings)
        api.state.id_token_verifier = id_token_verifier or dashboard_auth.dashboard_verifier(settings)
        yield
        if workflow_client is None:
            api.state.workflow_client.destroy()
        if owns_engine:
            resolved_engine.dispose()

    api = FastAPI(
        title="EstateOS",
        version=app.__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.env != "prod" else None,
        openapi_url="/openapi.json" if settings.env != "prod" else None,
        redoc_url=None,
    )
    api.state.rate_limiter = RateLimiter()
    if settings.dashboard_cors_origins:  # default: none, the SPA is served same-origin behind the proxy
        api.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.dashboard_cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=[dashboard_auth.CSRF_HEADER, "Content-Type"],
        )
    api.include_router(health.router)
    api.include_router(api_v1_router)
    api.include_router(whatsapp_webhook.router)
    api.include_router(gmail_webhook.router)
    api.include_router(google_chat_webhook.router)
    return api
