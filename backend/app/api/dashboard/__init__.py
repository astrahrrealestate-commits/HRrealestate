"""Dashboard API Package.

Provides executive pulse metrics, unresponsive radar stalled cases, prospective tenant leads,
and autonomous operation logs for the Today Dashboard.
"""

from app.api.dashboard.routes import router

__all__ = ["router"]
