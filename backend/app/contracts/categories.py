"""Display names and order of the six business categories, and the map from the eight categories before M13."""

from types import MappingProxyType

from app.contracts.understanding import Category

SHOWN_CATEGORIES: tuple[Category, ...] = (
    Category.maintenance,
    Category.finance,
    Category.legal,
    Category.business,
    Category.administration,
    Category.new_projects,
)

CATEGORY_LABELS: MappingProxyType[Category, str] = MappingProxyType(
    {
        Category.maintenance: "Maintenance",
        Category.finance: "Finance",
        Category.legal: "Legal",
        Category.business: "Business",
        Category.administration: "Administration",
        Category.new_projects: "New projects",
        Category.spam: "Spam",
    }
)

# Values stored before M13 (migration 0054 rewrites them; an old worker may still write one during a deploy).
LEGACY_CATEGORIES: MappingProxyType[str, str] = MappingProxyType(
    {
        "contractor_update": Category.maintenance.value,
        "complaint": Category.maintenance.value,
        "payment": Category.finance.value,
        "lease": Category.legal.value,
        "admin": Category.administration.value,
        "other": Category.administration.value,
    }
)


def current_category(value: str) -> Category:
    """A stored category value as one of today's categories."""
    return Category(LEGACY_CATEGORIES.get(value, value))
