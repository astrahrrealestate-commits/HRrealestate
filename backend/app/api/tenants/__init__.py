"""Tenants API Package.

Provides active tenant directory, rent payment tracking, and individual tenant contact profiles.
"""

from app.api.tenants.documents import router as documents_router
from app.api.tenants.routes import router

__all__ = ["documents_router", "router"]
