"""Maintenance Hub API Package.

Provides work order queue, ticket lifecycle audit history, and dispatch approval endpoints.
"""

from app.api.maintenance.routes import router

__all__ = ["router"]
