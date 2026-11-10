"""BRIXX mirror sync status for the dashboard: read-only, company-scoped through the session principal.

Reads the sync state tables only; BRIXX itself is called by the sync workflows alone, never on a request path.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_engine, get_settings_dep
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_principal
from app.contracts.brixx import BrixxStatus
from app.core.settings import Settings
from app.directory.brixx.status import load_status

router = APIRouter(prefix="/brixx", tags=["brixx"], dependencies=[Depends(require_section("settings"))])
Owner = Annotated[Principal, Depends(require_principal)]
Engine_ = Annotated[Engine, Depends(get_engine)]
Settings_ = Annotated[Settings, Depends(get_settings_dep)]


@router.get("/status")
def sync_status(who: Owner, engine: Engine_, settings: Settings_) -> BrixxStatus:
    with Session(engine) as session:
        return load_status(
            session, who.company_id, now=datetime.now(UTC), interval_minutes=settings.brixx_sync_interval_minutes
        )
