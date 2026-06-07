"""
core/metrics.py
══════════════════════════════════════════════════════════════════
Pure, reusable financial calculation functions.
Every function accepts a DataFrame and returns a plain Python dict
(or scalar), making them trivially testable and cache-friendly.

These are the single source of truth for every numeric KPI used
across Tracker Overview, Analyzer pages, Reports, and Profile.
"""
from __future__ import annotations

import pandas as pd


# ── Low-level helpers ─────────────────────────────────────────────

def _income(df: pd.DataFrame) -> float:
    """Sum of all credit transactions."""
    if df.empty:
        return 0.0
    return float(df[df["Transaction Type"] == "credit"]["Amount"].sum())


def _expenses(df: pd.DataFrame) -> float:
    """Sum of all debit transactions."""
    if df.empty:
        return 0.0
    return float(df[df["Transaction Type"] == "debit"]["Amount"].sum())


# ── Public API ────────────────────────────────────────────────────

def calculate_savings_rate(df: pd.DataFrame) -> dict:
    """
    Returns:
        income      – total credit amount
        expenses    – total debit amount
        net         – income - expenses
        savings_pct – net / income * 100  (0 if no income)
        direction   – "▲" | "▼"
        direction_color – hex colour string
    """
    inc = _income(df)
    exp = _expenses(df)
    net = inc - exp
    pct = (net / inc * 100) if inc > 0 else 0.0
    return {
        "income": inc,
        "expenses": exp,
        "net": net,
        "savings_pct": pct,
        "direction": "▲" if net >= 0 else "▼",
        "direction_color": "#15803d" if net >= 0 else "#b91c1c",
    }


def calculate_financial_health(df: pd.DataFrame) -> dict:
    """
    Derives a qualitative health score from the savings rate.

    Returns:
        savings_pct  – float
        label        – human-readable health label
        color        – hex colour for the label
        gauge_value  – same as savings_pct (for the Plotly gauge)
        tip          – actionable smart tip string
    """
    sr = calculate_savings_rate(df)
    pct = sr["savings_pct"]

    if pct >= 50:
        label, color = "Excellent 🌟", "#15803d"
        tip = "🌟 Exceptional! Consider index funds or FDs for your surplus."
    elif pct >= 30:
        label, color = "Good 👍", "#065f46"
        tip = "👍 Great! Try automating savings to grow faster."
    elif pct >= 10:
        label, color = "Average ⚠️", "#b45309"
        tip = "⚠️ Review your top spending category for easy cuts."
    else:
        label, color = "Needs Attention 🔴", "#b91c1c"
        tip = "🔴 Expenses exceed income. Time for a strict monthly budget."

    return {
        "savings_pct": pct,
        "income": sr["income"],
        "expenses": sr["expenses"],
        "net": sr["net"],
        "label": label,
        "color": color,
        "gauge_value": pct,
        "tip": tip,
    }


def analyze_category_trends(df: pd.DataFrame) -> dict:
    """
    Computes per-category spend aggregates for expense transactions.

    Returns:
        breakdown   – DataFrame with Category, Total (₹), Transactions, Avg (₹)
        top_category – name of the highest-spend category (str | "N/A")
    """
    if df.empty:
        return {
            "breakdown": pd.DataFrame(
                columns=["Category", "Total (₹)", "Transactions", "Avg (₹)"]
            ),
            "top_category": "N/A",
        }
    deb = df[df["Transaction Type"] == "debit"]
    if deb.empty:
        return {
            "breakdown": pd.DataFrame(
                columns=["Category", "Total (₹)", "Transactions", "Avg (₹)"]
            ),
            "top_category": "N/A",
        }

    bd = (
        deb.groupby("Category")["Amount"]
        .agg(["sum", "count", "mean"])
        .reset_index()
        .rename(
            columns={"sum": "Total (₹)", "count": "Transactions", "mean": "Avg (₹)"}
        )
    )
    bd[["Total (₹)", "Avg (₹)"]] = bd[["Total (₹)", "Avg (₹)"]].round(2)
    bd = bd.sort_values("Total (₹)", ascending=False)
    top = str(bd.iloc[0]["Category"]) if not bd.empty else "N/A"
    return {"breakdown": bd, "top_category": top}


def generate_spending_insights(df: pd.DataFrame) -> dict:
    """
    High-level summary facts used by the Insights page.

    Returns:
        top_category     – highest-spend expense category
        most_used_account – account with highest total transactions
        best_savings_month – month name with highest net savings
        total_transactions – int
        savings_pct      – float
        tip              – smart tip string
    """
    if df.empty:
        return {
            "top_category": "N/A",
            "most_used_account": "N/A",
            "best_savings_month": "N/A",
            "total_transactions": 0,
            "savings_pct": 0.0,
            "tip": "Add transactions to see insights.",
        }

    cat_data = analyze_category_trends(df)
    top_c = cat_data["top_category"]

    top_a = "N/A"
    if "Account Name" in df.columns and not df.empty:
        top_a = str(df.groupby("Account Name")["Amount"].sum().idxmax())

    inc_m = df[df["Transaction Type"] == "credit"].groupby("Month Name")["Amount"].sum()
    exp_m = df[df["Transaction Type"] == "debit"].groupby("Month Name")["Amount"].sum()
    try:
        best = str((inc_m - exp_m).idxmax())
    except Exception:
        best = "N/A"

    health = calculate_financial_health(df)

    return {
        "top_category": top_c,
        "most_used_account": top_a,
        "best_savings_month": best,
        "total_transactions": len(df),
        "savings_pct": health["savings_pct"],
        "tip": health["tip"],
    }


def monthly_income_expense(df: pd.DataFrame, month_order: list[str]) -> pd.DataFrame:
    """
    Returns a DataFrame with columns: Month Name, Income, Expense
    sorted by calendar month order.
    """
    if df.empty:
        return pd.DataFrame(columns=["Month Name", "Income", "Expense"])
    inc_m = df[df["Transaction Type"] == "credit"].groupby("Month Name")["Amount"].sum()
    exp_m = df[df["Transaction Type"] == "debit"].groupby("Month Name")["Amount"].sum()
    comp = pd.DataFrame({"Income": inc_m, "Expense": exp_m}).reset_index()
    comp["Month Name"] = pd.Categorical(
        comp["Month Name"], categories=month_order, ordered=True
    )
    return comp.sort_values("Month Name")


def monthly_savings(df: pd.DataFrame, month_order: list[str]) -> pd.DataFrame:
    """
    Returns a DataFrame with columns: Month Name, Savings
    sorted by calendar month order.
    """
    comp = monthly_income_expense(df, month_order)
    if comp.empty:
        return pd.DataFrame(columns=["Month Name", "Savings"])
    sav = comp.copy()
    sav["Savings"] = sav["Income"].fillna(0) - sav["Expense"].fillna(0)
    return sav[["Month Name", "Savings"]]


def top_expense_categories(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Returns top-N expense categories by total amount."""
    if df.empty:
        return pd.DataFrame(columns=["Category", "Amount"])
    deb = df[df["Transaction Type"] == "debit"]
    if deb.empty:
        return pd.DataFrame(columns=["Category", "Amount"])
    return (
        deb.groupby("Category")["Amount"]
        .sum()
        .sort_values(ascending=False)
        .head(n)
        .reset_index()
    )


def expense_by_account(df: pd.DataFrame) -> pd.DataFrame:
    """Returns per-account total expense."""
    if df.empty or "Account Name" not in df.columns:
        return pd.DataFrame(columns=["Account Name", "Amount"])
    deb = df[df["Transaction Type"] == "debit"]
    if deb.empty:
        return pd.DataFrame(columns=["Account Name", "Amount"])
    return deb.groupby("Account Name")["Amount"].sum().reset_index()


def category_by_month(df: pd.DataFrame, month_order: list[str]) -> pd.DataFrame:
    """Returns per-month per-category expense totals."""
    if df.empty:
        return pd.DataFrame(columns=["Month Name", "Category", "Amount"])
    deb = df[df["Transaction Type"] == "debit"]
    cats = deb.groupby(["Month Name", "Category"])["Amount"].sum().reset_index()
    cats["Month Name"] = pd.Categorical(
        cats["Month Name"], categories=month_order, ordered=True
    )
    return cats.sort_values("Month Name")


def monthly_expense_trend(df: pd.DataFrame, month_order: list[str]) -> pd.DataFrame:
    """Returns monthly debit totals sorted by calendar order."""
    if df.empty:
        return pd.DataFrame(columns=["Month Name", "Amount"])
    m_exp = (
        df[df["Transaction Type"] == "debit"]
        .groupby("Month Name")["Amount"]
        .sum()
        .reset_index()
    )
    m_exp["Month Name"] = pd.Categorical(
        m_exp["Month Name"], categories=month_order, ordered=True
    )
    return m_exp.sort_values("Month Name")


def summary_stats(df: pd.DataFrame) -> dict:
    """
    Flat summary used for Excel export and profile page.
    Returns income, expenses, net, savings_pct, total_transactions.
    """
    sr = calculate_savings_rate(df)
    return {
        "income": round(sr["income"], 2),
        "expenses": round(sr["expenses"], 2),
        "net": round(sr["net"], 2),
        "savings_pct": round(sr["savings_pct"], 2),
        "total_transactions": len(df),
    }
