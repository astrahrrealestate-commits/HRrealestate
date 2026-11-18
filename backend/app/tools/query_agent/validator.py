"""SQL AST validator using sqlglot for secure read-only execution."""

import sqlglot
from sqlglot import exp

from app.tools.query_agent.allowlist import (
    ALL_ALLOWED_RELATIONS,
    ALLOWED_FUNCTIONS,
    BANNED_FUNCTIONS,
    BLOCKED_RELATIONS,
)


class SQLSecurityError(ValueError):
    """Raised when a query fails AST security validation."""


def _get_function_name(func: exp.Func | exp.Anonymous) -> str:
    """Extracts normalized lowercase function name from sqlglot AST node."""
    if isinstance(func, exp.Anonymous):
        return str(func.this or func.name or "").lower()
    fname = (func.sql_name() or func.key or func.name or "").lower()
    if fname in ("timestamptrunc", "datetrunc"):
        return "date_trunc"
    return fname


def validate_and_wrap_sql(sql: str, max_limit: int = 50) -> str:
    """Validates that SQL is a single, pure, safe SELECT statement and wraps it in a subquery limit.

    Guarantees:
    1. Exactly one statement.
    2. Root expression is an exp.Select or exp.Union.
    3. No data mutation (INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE) even inside CTEs.
    4. No table locking (FOR UPDATE / FOR SHARE) or table creation (SELECT INTO).
    5. Only allowlisted business views/tables are referenced.
    6. Only allowlisted safe analytical functions are used.
    7. Clean SQL regenerated from AST without comments or trailing tricks.
    8. Wrapped in: SELECT * FROM (<clean_sql>) AS q LIMIT <max_limit>;
    """
    cleaned = (sql or "").strip()
    if not cleaned:
        raise SQLSecurityError("Query string cannot be empty.")

    try:
        statements = sqlglot.parse(cleaned, read="postgres")
    except Exception as e:
        raise SQLSecurityError(f"Failed to parse SQL query: {e}") from e

    if len(statements) != 1 or statements[0] is None:
        raise SQLSecurityError(f"Query must contain exactly one statement (found {len(statements)}).")

    tree = statements[0]

    # 1. Enforce root query type (must be Select or Union of Selects)
    if not isinstance(tree, exp.Select | exp.Union):
        raise SQLSecurityError(f"Only SELECT queries are allowed. Root expression was: {type(tree).__name__}")

    # 2. Ban data-modifying expressions across the entire syntax tree
    mutation_nodes = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Alter,
        exp.Command,
        exp.Into,
        exp.Lock,  # FOR UPDATE / FOR SHARE
    )
    for node in tree.find_all(*mutation_nodes):
        raise SQLSecurityError(f"Prohibited SQL operation detected: {type(node).__name__}")

    # 3. Check relations (Tables & Views)
    # Extract any defined CTE aliases so they are not rejected as missing base tables
    ctes = {cte.alias.lower() for cte in tree.find_all(exp.CTE) if cte.alias}

    for table in tree.find_all(exp.Table):
        tbl_name = table.name.lower()
        if not tbl_name:
            continue
        if tbl_name in ctes:
            continue
        if tbl_name in BLOCKED_RELATIONS:
            raise SQLSecurityError(f"Access to sensitive table '{table.name}' is strictly forbidden.")
        if tbl_name not in ALL_ALLOWED_RELATIONS:
            raise SQLSecurityError(
                f"Table or view '{table.name}' is not in the allowed relations list. "
                f"Allowed views: {sorted(ALL_ALLOWED_RELATIONS)}"
            )
        if table.db and table.db.lower() != "public":
            raise SQLSecurityError(f"Schema '{table.db}' is not allowed; use the curated views.")

    # 4. Check functions
    for func in tree.find_all(exp.Func, exp.Anonymous):
        fname = _get_function_name(func)
        if not fname:
            continue
        if fname in BANNED_FUNCTIONS:
            raise SQLSecurityError(f"Function '{fname}' is explicitly forbidden for security reasons.")
        if fname not in ALLOWED_FUNCTIONS:
            raise SQLSecurityError(f"Function '{fname}' is not permitted. Only safe analytical functions are allowed.")

    # 5. Regenerate clean, sanitized SQL from the verified AST (stripping comments)
    clean_sql = tree.sql(dialect="postgres", comments=False)

    # 6. Wrap in subquery limit to guarantee max row ceiling
    wrapped_sql = f"SELECT * FROM ({clean_sql}) AS q LIMIT {int(max_limit)};"  # noqa: S608 - AST-regenerated SQL
    return wrapped_sql
