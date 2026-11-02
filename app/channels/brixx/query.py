"""BRIXX data-query syntax: `[col op value]` filters joined with `and`; dates as yyyy-MM-dd."""

from datetime import date, datetime

FilterValue = str | int | datetime | date
Condition = tuple[str, str, FilterValue]


def _render_value(value: FilterValue) -> str:
    if isinstance(value, date):  # datetime is a date subclass
        return value.strftime("%Y-%m-%d")
    return str(value)


def build_filter(*conditions: Condition) -> str:
    return " and ".join(f"[{column} {op} {_render_value(value)}]" for column, op, value in conditions)


def data_query_params(page: int, filters: str | None, order_by: str | None) -> dict[str, str]:
    params = {"page": str(page)}
    if filters:
        params["filters"] = filters
    if order_by:
        params["orderby"] = order_by
    return params
