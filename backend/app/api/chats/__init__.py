"""WhatsApp-style Chats API: one conversation per contact number; the owner reads and types his own replies."""

from app.api.chats.routes import router
from app.api.chats.send import send_router

router.include_router(send_router)  # same prefix and `inbox` section guard as the read routes

__all__ = ["router"]
