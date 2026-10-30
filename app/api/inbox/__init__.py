"""Inbox & Triage API Package.

Provides communication triage threads, AI draft proposals, and 1-click approval actions.
"""

from app.api.inbox.routes import router

__all__ = ["router"]
