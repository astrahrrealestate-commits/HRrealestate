"""BRIXX data-query syntax: `[col op value]` filters joined with `and`; dates as yyyy-MM-dd; `fields` joined by `+`."""

from collections.abc import Sequence
from datetime import date, datetime

FilterValue = str | int | datetime | date
Condition = tuple[str, str, FilterValue]


def _render_value(value: FilterValue) -> str:
    if isinstance(value, date):  # datetime is a date subclass
        return value.strftime("%Y-%m-%d")
    return str(value)


def build_filter(*conditions: Condition) -> str:
    return " and ".join(f"[{column} {op} {_render_value(value)}]" for column, op, value in conditions)


def data_query_params(
    page: int, filters: str | None, order_by: str | None, fields: Sequence[str] | None = None
) -> dict[str, str]:
    """Query string for a data page. `fields` projects columns (only for key scans: upserts need whole rows)."""
    params = {"page": str(page)}
    if filters:
        params["filters"] = filters
    if order_by:
        params["orderby"] = order_by
    if fields:
        params["fields"] = "+".join(fields)
    return params
