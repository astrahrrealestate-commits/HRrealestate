"""Aggregates every dashboard sub-router under /api/v1."""

from fastapi import APIRouter

from app.api.v1 import agent, auth, cases, decisions, diligence, documents, events, inbox, memory, reviews, work

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth.router)
api_v1_router.include_router(events.router)
api_v1_router.include_router(inbox.router)
api_v1_router.include_router(cases.router)
api_v1_router.include_router(work.router)
api_v1_router.include_router(decisions.router)
api_v1_router.include_router(reviews.router)
api_v1_router.include_router(documents.router)  # after reviews: /documents/review must win over /documents/{id}
api_v1_router.include_router(agent.router)
api_v1_router.include_router(memory.router)
api_v1_router.include_router(diligence.router)
