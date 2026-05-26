"""
sql_tools.py — SQL safety, schema introspection, and execution.

This module is the security boundary between the LLM agent and the database.
The agent can only run queries that pass safety checks here.

Northwind-specific notes:
  - The 'Order Details' table has a space — must be quoted in SQL
  - 'Employees.Photo' and 'Categories.Picture' are BLOBs (binary image data)
    that we hide from the agent's schema view to avoid token blowup
  - Two demographic tables are empty — also hidden
"""

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import sqlparse

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "northwind.db"

# Hard block — any query containing these keywords is rejected outright
BLOCKED_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "REPLACE", "ATTACH", "DETACH", "PRAGMA", "VACUUM",
}

# Columns hidden from the agent because they hold binary image data
HIDDEN_COLUMNS = {
    ("Employees", "Photo"),
    ("Categories", "Picture"),
}

# Tables hidden from the agent because they're empty in this dataset
HIDDEN_TABLES = {"CustomerCustomerDemo", "CustomerDemographics"}

MAX_ROWS_RETURNED = 100  # cap result size to prevent token blowup


def _quote_identifier(name: str) -> str:
    """SQLite identifier quoting — handles names with spaces like 'Order Details'."""
    return '"' + name.replace('"', '""') + '"'


def get_schema() -> str:
    """
    Return human-readable schema for all relevant tables.
    Injected into the agent's system prompt so it knows what to query.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    table_names = [r[0] for r in cursor.fetchall() if r[0] not in HIDDEN_TABLES]

    schema_parts: list[str] = []
    for tname in table_names:
        # PRAGMA needs the bare name (not quoted)
        cols = cursor.execute(f"PRAGMA table_info({_quote_identifier(tname)})").fetchall()
        # Drop hidden BLOB columns
        col_lines = [
            f"  {c[1]} {c[2]}"
            for c in cols
            if (tname, c[1]) not in HIDDEN_COLUMNS
        ]
        # Note tables that need quoting because they contain a space
        note = "  -- use double quotes: \"Order Details\"" if " " in tname else ""
        schema_parts.append(
            f"TABLE {_quote_identifier(tname)} ({note}\n" + ",\n".join(col_lines) + "\n);"
        )

    conn.close()
    return "\n\n".join(schema_parts)


def validate_sql(query: str) -> tuple[bool, str]:
    """
    Returns (is_safe, reason).
    Rejects anything that isn't a single SELECT statement.
    """
    if not query or not query.strip():
        return False, "Empty query."

    parsed = sqlparse.parse(query.strip().rstrip(";"))

    # Must be exactly one statement (no stacked queries)
    if len(parsed) != 1:
        return False, "Only a single statement is allowed."

    statement = parsed[0]
    stmt_type = statement.get_type()
    if stmt_type != "SELECT":
        return False, f"Only SELECT statements are allowed. Got: {stmt_type or 'UNKNOWN'}"

    # Token-level scan for blocked keywords (catches them even inside subqueries)
    upper_query = query.upper()
    for kw in BLOCKED_KEYWORDS:
        # Word-boundary check so e.g. "CREATED_AT" doesn't trigger CREATE
        if f" {kw} " in f" {upper_query} " or upper_query.startswith(kw + " "):
            return False, f"Blocked keyword detected: {kw}"

    return True, "OK"


def run_sql_safe(query: str) -> dict[str, Any]:
    """
    Validate + execute a query. Always returns a dict (never raises).
    The agent receives this dict as its tool_result and can react to errors.
    """
    is_safe, reason = validate_sql(query)
    if not is_safe:
        return {"error": reason, "query": query}

    if not DB_PATH.exists():
        return {
            "error": f"Database file not found at {DB_PATH}. "
                     f"Run: python scripts/init_db.py",
            "query": query,
        }

    try:
        # Read-only connection (uri mode + mode=ro)
        uri = f"file:{DB_PATH}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        df = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as exc:
        return {"error": f"SQL execution failed: {exc}", "query": query}

    # Drop any BLOB columns that might have slipped through (e.g. SELECT *)
    for col in list(df.columns):
        if df[col].dtype == object and len(df) > 0:
            first_val = df[col].iloc[0]
            if isinstance(first_val, bytes):
                df = df.drop(columns=[col])

    truncated = len(df) > MAX_ROWS_RETURNED
    return {
        "columns": df.columns.tolist(),
        "rows": df.head(MAX_ROWS_RETURNED).to_dict(orient="records"),
        "row_count": len(df),
        "truncated": truncated,
        "query": query,
    }


def run_sql_to_df(query: str) -> tuple[pd.DataFrame | None, str | None]:
    """Returns (DataFrame, error_message). One of them is always None."""
    result = run_sql_safe(query)
    if "error" in result:
        return None, result["error"]
    return pd.DataFrame(result["rows"]), None
