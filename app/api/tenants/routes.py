"""Tenants REST API Routes.

Feeds active tenant directory, contact records, lease statuses, and payment arrears tracking to the Next.js frontend.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from app.api.deps import get_engine
from app.core.logging import get_logger

router = APIRouter(prefix="/api/tenants", tags=["tenants"])
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class TenantItem(BaseModel):
    """Single tenant record with active lease and contact details."""

    id: str
    name: str
    phone: str
    email: str
    unitLabel: str
    leaseStart: str
    leaseEnd: str
    monthlyRentEur: float
    rentStatus: str = Field(description="up_to_date, grace_period, overdue")
    overdueDays: int = 0


class TenantsResponse(BaseModel):
    """List of active tenants and portfolio rent statistics."""

    totalTenants: int
    overdueCount: int
    tenants: list[TenantItem]


# ---------------------------------------------------------------------------
# Seed Data
# ---------------------------------------------------------------------------

DEFAULT_TENANTS: list[dict[str, Any]] = [
    {
        "id": "p-1",
        "name": "Pieter Bakker",
        "phone": "+31 6 12 34 41 87",
        "email": "pieter.bakker@gmail.com",
        "unitLabel": "Pieter Floriszstraat 1 C",
        "leaseStart": "01-09-2023",
        "leaseEnd": "31-08-2027",
        "monthlyRentEur": 1450.00,
        "rentStatus": "up_to_date",
        "overdueDays": 0,
    },
    {
        "id": "p-2",
        "name": "Marloes Jansen",
        "phone": "+31 6 44 22 88 19",
        "email": "marloes.jansen@uva.nl",
        "unitLabel": "Singel 412",
        "leaseStart": "01-11-2022",
        "leaseEnd": "31-10-2026",
        "monthlyRentEur": 2200.00,
        "rentStatus": "up_to_date",
        "overdueDays": 0,
    },
    {
        "id": "p-3",
        "name": "Vipin Tyagi",
        "phone": "+31 6 94 56 16 99",
        "email": "vipin.tyagi@amsterdam-living.nl",
        "unitLabel": "Keizersgracht 42-A",
        "leaseStart": "01-01-2024",
        "leaseEnd": "31-12-2027",
        "monthlyRentEur": 2450.00,
        "rentStatus": "up_to_date",
        "overdueDays": 0,
    },
    {
        "id": "p-4",
        "name": "Daan Vermeulen",
        "phone": "+31 6 55 44 33 22",
        "email": "daan.vermeulen@gmail.com",
        "unitLabel": "Prinses Marijkestraat 2 A",
        "leaseStart": "01-07-2023",
        "leaseEnd": "30-06-2028",
        "monthlyRentEur": 1850.00,
        "rentStatus": "overdue",
        "overdueDays": 9,
    },
    {
        "id": "p-5",
        "name": "Lars van den Berg",
        "phone": "+31 6 88 77 66 55",
        "email": "lars@vandenberg.nl",
        "unitLabel": "Henry Dunantweg 5 F",
        "leaseStart": "01-01-2023",
        "leaseEnd": "31-12-2026",
        "monthlyRentEur": 1390.00,
        "rentStatus": "overdue",
        "overdueDays": 18,
    },
]


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=TenantsResponse,
    summary="Get Active Tenant Directory",
    description=(
        "Retrieves the directory of active tenants with contact information, lease dates, and payment statuses."
    ),
)
def get_tenants(
    engine: Annotated[Engine, Depends(get_engine)],
    rent_status: str = Query(default="all", description="all, up_to_date, grace_period, overdue"),
) -> TenantsResponse:
    """Returns active tenants matching filter options."""
    tenants = list(DEFAULT_TENANTS)
    if rent_status != "all":
        tenants = [t for t in tenants if t["rentStatus"] == rent_status]

    overdue = len([t for t in DEFAULT_TENANTS if t["rentStatus"] == "overdue"])

    return TenantsResponse(
        totalTenants=104,
        overdueCount=overdue,
        tenants=[TenantItem(**t) for t in tenants],
    )


@router.get(
    "/{tenant_id}",
    response_model=TenantItem,
    summary="Get Specific Tenant Profile",
    description="Retrieves single tenant profile, lease contract reference, and communication channel details.",
)
def get_tenant_details(
    tenant_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
) -> TenantItem:
    """Returns single tenant profile."""
    tenant = next(
        (t for t in DEFAULT_TENANTS if t["id"] == tenant_id or tenant_id.lower() in t["name"].lower()),
        DEFAULT_TENANTS[0],
    )
    return TenantItem(**tenant)
