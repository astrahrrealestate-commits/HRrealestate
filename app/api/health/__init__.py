"""Health & Readiness API Package.

Provides liveness and readiness probe routes for orchestrators and uptime checks.
"""

from app.api.health.routes import router

__all__ = ["router"]
