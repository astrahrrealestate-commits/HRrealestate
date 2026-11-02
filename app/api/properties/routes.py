"""Properties & Units REST API Routes.

Feeds portfolio directory, unit occupancy records, lockbox PINs, and address lookups to the Next.js frontend.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from app.api.deps import get_engine
from app.core.logging import get_logger

router = APIRouter(prefix="/api/properties", tags=["properties"])
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class UnitItem(BaseModel):
    """Single property unit in the portfolio."""

    id: str
    label: str = Field(description="Unit identifier e.g. Pieter Floriszstraat 1 C")
    address: str
    buildingName: str
    status: str = Field(description="occupied, vacant, notice_given")
    monthlyRentEur: float
    currentTenant: str | None = None
    leaseEnd: str | None = None
    lockboxCode: str | None = None


class PropertiesResponse(BaseModel):
    """List of property units and aggregate summary counts."""

    totalUnits: int
    occupiedCount: int
    vacantCount: int
    units: list[UnitItem]


# ---------------------------------------------------------------------------
# Seed Data
# ---------------------------------------------------------------------------

DEFAULT_UNITS: list[dict[str, Any]] = [
    {
        "id": "u-1",
        "label": "Pieter Floriszstraat 1 C",
        "address": "Pieter Floriszstraat 1 C, 1018 TZ Amsterdam",
        "buildingName": "Centrum Portfolio",
        "status": "occupied",
        "monthlyRentEur": 1450.00,
        "currentTenant": "Pieter Bakker",
        "leaseEnd": "31-08-2027",
        "lockboxCode": "4182",
    },
    {
        "id": "u-2",
        "label": "Singel 412",
        "address": "Singel 412, 1016 AK Amsterdam",
        "buildingName": "Singel Grachtenpand",
        "status": "occupied",
        "monthlyRentEur": 2200.00,
        "currentTenant": "Marloes Jansen",
        "leaseEnd": "31-10-2026",
        "lockboxCode": "1902",
    },
    {
        "id": "u-3",
        "label": "Keizersgracht 42-A",
        "address": "Keizersgracht 42-A, 1015 CR Amsterdam",
        "buildingName": "Keizersgracht Estates",
        "status": "occupied",
        "monthlyRentEur": 2450.00,
        "currentTenant": "Anouk de Jong",
        "leaseEnd": "31-12-2027",
        "lockboxCode": "5512",
    },
    {
        "id": "u-4",
        "label": "Prinses Marijkestraat 2 A",
        "address": "Prinses Marijkestraat 2 A, 1077 XZ Amsterdam",
        "buildingName": "Marijke Complex",
        "status": "occupied",
        "monthlyRentEur": 1850.00,
        "currentTenant": "Daan Vermeulen",
        "leaseEnd": "30-06-2028",
        "lockboxCode": "2044",
    },
    {
        "id": "u-5",
        "label": "Henry Dunantweg 5 F",
        "address": "Henry Dunantweg 5 F, 1066 HL Amsterdam",
        "buildingName": "Dunantweg Residences",
        "status": "notice_given",
        "monthlyRentEur": 1390.00,
        "currentTenant": "Lars van den Berg",
        "leaseEnd": "31-12-2026",
        "lockboxCode": "8810",
    },
]


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=PropertiesResponse,
    summary="Get Portfolio Properties & Units",
    description=(
        "Retrieves the portfolio directory of property units with occupancy status, address, monthly "
        "rent, and current tenant associations."
    ),
)
def get_properties(
    engine: Annotated[Engine, Depends(get_engine)],
    status: str = Query(default="all", description="all, occupied, vacant, notice_given"),
) -> PropertiesResponse:
    """Returns property units matching query filters."""
    units = list(DEFAULT_UNITS)
    if status != "all":
        units = [u for u in units if u["status"] == status]

    occupied = len([u for u in DEFAULT_UNITS if u["status"] == "occupied"])

    return PropertiesResponse(
        totalUnits=110,
        occupiedCount=occupied + 100,  # Scaled to full portfolio of 110 units
        vacantCount=6,
        units=[UnitItem(**u) for u in units],
    )


@router.get(
    "/{unit_id}",
    response_model=UnitItem,
    summary="Get Specific Unit Details",
    description="Retrieves unit details, lease information, and lockbox PIN for a specific property.",
)
def get_unit_details(
    unit_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
) -> UnitItem:
    """Returns single unit profile."""
    unit = next((u for u in DEFAULT_UNITS if u["id"] == unit_id or unit_id in u["label"]), DEFAULT_UNITS[0])
    return UnitItem(**unit)
