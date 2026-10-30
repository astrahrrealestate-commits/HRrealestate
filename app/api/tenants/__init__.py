"""Tenants API Package.

Provides active tenant directory, rent payment tracking, and individual tenant contact profiles.
"""

from app.api.tenants.routes import router

__all__ = ["router"]
