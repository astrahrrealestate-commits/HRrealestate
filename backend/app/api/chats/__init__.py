"""WhatsApp-style Chats API: one conversation per contact number, read-only for the owner dashboard."""

from app.api.chats.routes import router

__all__ = ["router"]
