"""Channel setup status for the Connections panel: read-only, from server configuration.

WhatsApp is configured on the server (provider and credentials in settings), not connected by a click in the
dashboard, so the panel only reports what the server is set up to do. Nothing here reads or returns a secret.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_settings_dep
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_principal
from app.core.settings import Settings

router = APIRouter(prefix="/channels", tags=["channels"], dependencies=[Depends(require_section("settings"))])
Owner = Annotated[Principal, Depends(require_principal)]
Settings_ = Annotated[Settings, Depends(get_settings_dep)]


class WhatsAppStatus(BaseModel):
    """`configured` is false for the built-in fake provider: no real WhatsApp account is attached."""

    configured: bool
    provider: Literal["fake", "cloud_api", "360dialog"]


@router.get("/whatsapp/status")
def whatsapp_status(who: Owner, settings: Settings_) -> WhatsAppStatus:
    return WhatsAppStatus(configured=settings.whatsapp_provider != "fake", provider=settings.whatsapp_provider)
