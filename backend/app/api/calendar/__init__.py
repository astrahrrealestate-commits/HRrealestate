"""Calendar API router."""

from fastapi import APIRouter

from app.api.calendar import invites, routes

router = APIRouter()
router.include_router(routes.router)
router.include_router(invites.router)

__all__ = ["router"]
