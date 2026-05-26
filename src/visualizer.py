"""
visualizer.py — Heuristic auto-chart selection.

Given any DataFrame returned by the agent, pick a sensible chart automatically.
Rules are deliberately simple — the goal is "always produce something useful,
never produce something embarrassing."
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


# Columns that look like identifiers and should NOT be used as a Y-axis metric.
# Matched case-insensitively as a suffix or whole word.
ID_COLUMN_PATTERNS = ("id", "_id", "uuid", "guid", "code", "number", "no", "key")

# Keywords that suggest a column is a "real" business metric (good Y-axis candidate).
METRIC_KEYWORDS = (
    "revenue", "sales", "total", "sum", "amount", "count",
    "qty", "quantity", "value", "price", "cost", "profit",
    "margin", "score", "rate", "pct", "percent", "avg", "mean",
)


def _is_datetime_like(series: pd.Series) -> bool:
    """
    Detect date/time columns even when they arrive as strings.

    Handles common SQL outputs:
      - Full timestamps: "2023-01-15 14:30:00"
      - ISO dates:       "2023-01-15"
      - Year-month:      "2023-01"   (e.g. from strftime('%Y-%m', ...))
      - Year-quarter:    "2023-Q1"
      - Year only:       "2023"
    """
    import re

    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    # Reject numeric columns — they shouldn't be treated as dates even if some
    # year-only values (e.g. 2023) could technically parse as such.
    if pd.api.types.is_numeric_dtype(series):
        return False

    sample = series.dropna().head(20)
    if sample.empty:
        return False

    # Try pandas' parser first (handles most cases incl. "2023-01-15")
    # Silence the "could not infer format" warning — we don't care about speed
    # here, we only need to know whether it parses at all.
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            pd.to_datetime(sample, errors="raise")
        return True
    except Exception:
        pass

    # Fallback: regex patterns for common partial-date formats that
    # pandas refuses to parse without a format hint.
    patterns = [
        r"^\d{4}-\d{2}$",                # 2023-01 (year-month)
        r"^\d{4}-Q[1-4]$",               # 2023-Q1 (year-quarter)
        r"^\d{4}-W\d{1,2}$",             # 2023-W05 (year-week)
        r"^\d{4}$",                      # 2023 (year only)
        r"^\d{4}/\d{2}$",                # 2023/01
    ]
    sample_strs = [str(v).strip() for v in sample]
    for pattern in patterns:
        if all(re.match(pattern, s) for s in sample_strs):
            return True

    return False


def _looks_like_id(col_name: str) -> bool:
    """Return True if a column name suggests it's an identifier, not a metric."""
    name_lower = col_name.lower()
    # Exact match (e.g. "id", "code")
    if name_lower in ID_COLUMN_PATTERNS:
        return True
    # Suffix match (e.g. "ProductID", "customer_id", "order_no")
    for pat in ID_COLUMN_PATTERNS:
        if name_lower.endswith(pat) and len(name_lower) > len(pat):
            # Make sure it's a real suffix boundary
            char_before = name_lower[-len(pat) - 1]
            if char_before in "_- " or char_before.isupper() or not char_before.isalpha():
                return True
            # Also catch CamelCase like "ProductID" where col_name has uppercase ID
            if pat == "id" and col_name.endswith("ID"):
                return True
    return False


def _looks_like_metric(col_name: str) -> bool:
    """Return True if a column name suggests it's a business metric."""
    name_lower = col_name.lower()
    return any(kw in name_lower for kw in METRIC_KEYWORDS)


def _choose_y_column(df: pd.DataFrame, numeric_cols: list[str]) -> str:
    """
    Pick the best numeric column to use as the Y-axis.

    Priority:
      1. Prefer a column whose name contains a metric keyword (revenue, total, ...)
         AND is not an ID-like column.
      2. Otherwise, prefer the last non-ID numeric column (aggregations usually
         end up last in SELECT lists).
      3. Last resort: prefer the numeric column with the largest range (metrics
         tend to have much wider ranges than IDs).
    """
    non_id_cols = [c for c in numeric_cols if not _looks_like_id(c)]

    # Rule 1: metric keyword in name
    metric_named = [c for c in non_id_cols if _looks_like_metric(c)]
    if metric_named:
        # If multiple, prefer the last one (latest aggregation in SELECT)
        return metric_named[-1]

    # Rule 2: last non-ID numeric column
    if non_id_cols:
        return non_id_cols[-1]

    # Rule 3: fallback — biggest-range numeric column
    # (If every column is ID-like, pick the most "metric-y" one by range.)
    ranges = {c: df[c].max() - df[c].min() for c in numeric_cols if df[c].notna().any()}
    if ranges:
        return max(ranges, key=ranges.get)

    return numeric_cols[0]


def _choose_x_column(df: pd.DataFrame, non_numeric_cols: list[str],
                     numeric_cols: list[str], y_col: str) -> str:
    """
    Pick the best column to use as the X-axis (category/label) for a bar chart.

    Prefers non-numeric columns. If none, falls back to a numeric ID-like column
    (treated as a discrete label).
    """
    if non_numeric_cols:
        # Pick the most "descriptive-looking" non-numeric — prefer ones that don't
        # look like IDs (e.g. "ProductName" over "ProductCode")
        non_id_text = [c for c in non_numeric_cols if not _looks_like_id(c)]
        if non_id_text:
            return non_id_text[0]
        return non_numeric_cols[0]

    # No text columns at all — use a numeric ID column as discrete labels
    id_cols = [c for c in numeric_cols if c != y_col and _looks_like_id(c)]
    if id_cols:
        return id_cols[0]

    # Last resort
    return [c for c in numeric_cols if c != y_col][0]


def auto_chart(df: pd.DataFrame) -> go.Figure | None:
    """
    Return a Plotly figure that makes sense for the given DataFrame,
    or None if no chart is appropriate (e.g. a single scalar result).
    """
    if df is None or df.empty or len(df.columns) < 2:
        return None

    # Limit to top 20 rows for readability
    df_plot = df.head(20).copy()

    numeric_cols = df_plot.select_dtypes(include="number").columns.tolist()
    non_numeric_cols = [c for c in df_plot.columns if c not in numeric_cols]

    if not numeric_cols:
        return None

    # --- Case 1: time series ---
    # If there's a datetime-like column and a numeric column → line chart
    date_col = next((c for c in df_plot.columns if _is_datetime_like(df_plot[c])), None)
    if date_col:
        try:
            # Handle YYYY-MM (no day) by appending -01 so pandas can parse it.
            # Also handle YYYY-Q1 (year-quarter) by converting to a real period.
            import re
            sample_val = str(df_plot[date_col].dropna().iloc[0]).strip()
            if re.match(r"^\d{4}-\d{2}$", sample_val):
                df_plot[date_col] = pd.to_datetime(df_plot[date_col] + "-01")
            elif re.match(r"^\d{4}$", sample_val):
                df_plot[date_col] = pd.to_datetime(df_plot[date_col] + "-01-01")
            elif re.match(r"^\d{4}-Q[1-4]$", sample_val):
                df_plot[date_col] = pd.PeriodIndex(df_plot[date_col], freq="Q").to_timestamp()
            else:
                df_plot[date_col] = pd.to_datetime(df_plot[date_col])
            df_plot = df_plot.sort_values(date_col)
        except Exception:
            pass
        # Exclude the date column from numeric candidates if it got picked up
        candidates = [c for c in numeric_cols if c != date_col]
        if candidates:
            y_col = _choose_y_column(df_plot, candidates)
            fig = px.line(df_plot, x=date_col, y=y_col, markers=True,
                          title=f"{y_col} over {date_col}")
            fig.update_layout(template="plotly_white", height=400,
                              margin=dict(l=20, r=20, t=50, b=20))
            return fig

    # --- Case 2: categorical × numeric → bar chart ---
    # (This includes the case where the "category" is a numeric ID column.)
    if numeric_cols:
        y_col = _choose_y_column(df_plot, numeric_cols)
        # Re-derive remaining numeric cols (those that could be the X)
        remaining_numeric = [c for c in numeric_cols if c != y_col]

        if non_numeric_cols or remaining_numeric:
            x_col = _choose_x_column(df_plot, non_numeric_cols, numeric_cols, y_col)
            # Make sure x and y are different
            if x_col == y_col and remaining_numeric:
                x_col = remaining_numeric[0]

            # Sort by Y descending for visual impact
            df_plot = df_plot.sort_values(y_col, ascending=False)
            # If X is numeric (an ID), cast to string so Plotly treats it as categorical
            if x_col in numeric_cols:
                df_plot[x_col] = df_plot[x_col].astype(str)
            fig = px.bar(df_plot, x=x_col, y=y_col,
                         title=f"{y_col} by {x_col}",
                         color=y_col, color_continuous_scale="Teal")
            fig.update_layout(template="plotly_white", height=400,
                              margin=dict(l=20, r=20, t=50, b=20),
                              coloraxis_showscale=False)
            fig.update_xaxes(tickangle=-30)
            return fig

    # --- Case 3: two numeric columns → scatter ---
    if len(numeric_cols) >= 2:
        x_col, y_col = numeric_cols[0], numeric_cols[1]
        fig = px.scatter(df_plot, x=x_col, y=y_col,
                         title=f"{y_col} vs {x_col}")
        fig.update_layout(template="plotly_white", height=400,
                          margin=dict(l=20, r=20, t=50, b=20))
        return fig

    return None
