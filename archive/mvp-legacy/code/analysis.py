from __future__ import annotations

import pandas as pd


def allocation_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "total": 0,
            "avg": 0,
            "median": 0,
            "by_category": pd.Series(dtype=float),
            "top_companies": pd.Series(dtype=float),
        }

    return {
        "total": int(df["amount_isk"].sum()),
        "avg": float(df["amount_isk"].mean()),
        "median": float(df["amount_isk"].median()),
        "by_category": df.groupby("grant_category_raw")["amount_isk"].sum().sort_values(ascending=False),
        "top_companies": df.groupby("company_name")["amount_isk"].sum().sort_values(ascending=False).head(5),
    }
