"""Aggregates every dashboard sub-router under /api/v1."""

from fastapi import APIRouter

from app.api.v1 import auth, events, inbox

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth.router)
api_v1_router.include_router(events.router)
api_v1_router.include_router(inbox.router)
