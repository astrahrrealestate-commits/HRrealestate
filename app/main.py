"""ASGI app factory. Run: `uvicorn app.main:create_app --factory`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

import app
from app.api import health
from app.channels.registry import assert_channels_ready
from app.core.logging import configure_logging
from app.core.settings import Settings, get_settings
from app.core.startup import assert_production_safe
from app.core.telemetry import init_telemetry
from app.db.session import make_engine


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or get_settings()
    assert_production_safe(settings)
    assert_channels_ready(settings)
    configure_logging(settings.env)
    init_telemetry(settings)  # before routes are built: Sentry patches FastAPI request handlers at init
    owns_engine = engine is None
    resolved_engine = engine or make_engine(settings.sqlalchemy_url)

    @asynccontextmanager
    async def lifespan(api: FastAPI) -> AsyncIterator[None]:
        api.state.engine = resolved_engine
        yield
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
    api.include_router(health.router)
    return api
