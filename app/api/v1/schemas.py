"""Response schemas for the dashboard API."""

from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.db.enums import FeedKind


class FeedItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: FeedKind
    ref_id: UUID | None
    payload: dict[str, Any]
    created_at: AwareDatetime
    seen_at: AwareDatetime | None
    resolved_at: AwareDatetime | None
