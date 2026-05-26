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


def _is_datetime_like(series: pd.Series) -> bool:
    """Detect date columns even when they arrive as strings."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if series.dtype == object:
        sample = series.dropna().head(20)
        if sample.empty:
            return False
        try:
            pd.to_datetime(sample, errors="raise")
            return True
        except Exception:
            return False
    return False


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
    if date_col and numeric_cols:
        try:
            df_plot[date_col] = pd.to_datetime(df_plot[date_col])
            df_plot = df_plot.sort_values(date_col)
        except Exception:
            pass
        y_col = numeric_cols[0]
        fig = px.line(df_plot, x=date_col, y=y_col, markers=True,
                      title=f"{y_col} over {date_col}")
        fig.update_layout(template="plotly_white", height=400,
                          margin=dict(l=20, r=20, t=50, b=20))
        return fig

    # --- Case 2: categorical × numeric → bar chart ---
    if non_numeric_cols and numeric_cols:
        x_col = non_numeric_cols[0]
        y_col = numeric_cols[0]
        # Sort by value descending for visual impact
        df_plot = df_plot.sort_values(y_col, ascending=False)
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
