"""
core/analyzer_engine.py
══════════════════════════════════════════════════════════════════
Analyzer-side orchestration layer.
Composes metrics + insights + charts into page-ready payloads.
All functions are read-only: they never write to the database.

Each `build_*_payload` function returns a single dict with
everything an analyzer page needs — reducing how much logic
lives inside page functions themselves.
"""
from __future__ import annotations

import pandas as pd

from core import charts, insights, metrics

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# ── Analytics page payload ────────────────────────────────────────

def build_analytics_payload(df: pd.DataFrame) -> dict:
    """
    Returns everything pf_analytics needs:
      kpis        – savings rate dict
      cat_df      – top-10 expense categories DataFrame
      pie_df      – 5+1 slice pie DataFrame
      m_exp_df    – monthly expense trend DataFrame
      figures     – dict of pre-built Plotly figures
    """
    sr = metrics.calculate_savings_rate(df)
    cat_df = metrics.top_expense_categories(df, n=10)
    pie_df = insights.build_pie_data(cat_df)
    m_exp_df = metrics.monthly_expense_trend(df, MONTHS)

    figs = {}
    if not cat_df.empty:
        figs["bar_categories"] = charts.bar_top_categories(cat_df)
    if not pie_df.empty:
        figs["pie_distribution"] = charts.pie_expense_distribution(pie_df)
    if not m_exp_df.empty:
        figs["line_trend"] = charts.line_expense_trend(m_exp_df)

    return {
        "kpis": sr,
        "cat_df": cat_df,
        "pie_df": pie_df,
        "m_exp_df": m_exp_df,
        "figures": figs,
    }


# ── Insights page payload ─────────────────────────────────────────

def build_insights_payload(df: pd.DataFrame) -> dict:
    """
    Returns everything pf_insights needs:
      insight_cards  – dict with top_category, most_used_account, etc.
      tip_html       – rendered HTML for the smart-tip card
      breakdown_df   – category breakdown DataFrame
    """
    ins = metrics.generate_spending_insights(df)
    tip_html = insights.build_smart_tip_html(ins["tip"])
    cat_data = metrics.analyze_category_trends(df)
    return {
        "insight_cards": ins,
        "tip_html": tip_html,
        "breakdown_df": cat_data["breakdown"],
    }


# ── Health page payload ───────────────────────────────────────────

def build_health_payload(df: pd.DataFrame) -> dict:
    """
    Returns everything pf_health needs:
      health         – health dict (label, color, savings_pct, net, tip)
      status_html    – rendered HTML banner
      gauge_fig      – Plotly gauge figure
      kpis           – savings rate dict for the income/expense/net row
    """
    health = metrics.calculate_financial_health(df)
    status_html = insights.build_health_status_html(health)
    gauge_fig = charts.gauge_savings_rate(health["gauge_value"], health["label"])
    kpis = metrics.calculate_savings_rate(df)
    return {
        "health": health,
        "status_html": status_html,
        "gauge_fig": gauge_fig,
        "kpis": kpis,
    }


# ── Charts page payload ───────────────────────────────────────────

def build_charts_payload(df: pd.DataFrame) -> dict:
    """
    Returns everything pf_charts needs:
      inc_exp_fig   – grouped bar income vs expense
      account_fig   – donut pie by account (None if no account data)
      cat_month_fig – stacked bar category x month
    """
    comp_df = metrics.monthly_income_expense(df, MONTHS)
    acct_df = metrics.expense_by_account(df)
    cats_df = metrics.category_by_month(df, MONTHS)

    figs = {}
    if not comp_df.empty:
        figs["inc_exp"] = charts.bar_income_vs_expense(comp_df)
    if not acct_df.empty:
        figs["account"] = charts.pie_expense_by_account(acct_df)
    if not cats_df.empty:
        figs["cat_month"] = charts.bar_stacked_category_month(cats_df)

    return {"figures": figs}


# ── Savings page payload ──────────────────────────────────────────

def build_savings_payload(df: pd.DataFrame) -> dict:
    """
    Returns everything pf_savings needs:
      sav_df      – monthly savings DataFrame
      bar_fig     – colour-scaled bar chart
      line_fig    – savings trend line chart
    """
    sav_df = metrics.monthly_savings(df, MONTHS)
    figs = {}
    if not sav_df.empty:
        figs["bar"] = charts.bar_savings(sav_df)
        figs["line"] = charts.line_savings_trend(sav_df)
    return {"sav_df": sav_df, "figures": figs}


# ── Category analysis page payload ───────────────────────────────

def build_categories_payload(df: pd.DataFrame) -> dict:
    """
    Returns everything pf_categories needs:
      breakdown_df  – full category breakdown DataFrame
      treemap_fig   – Plotly treemap figure (None if empty)
    """
    cat_data = metrics.analyze_category_trends(df)
    bd = cat_data["breakdown"]
    fig = charts.treemap_top_categories(bd) if not bd.empty else None
    return {"breakdown_df": bd, "treemap_fig": fig}


# ── Report export helper ──────────────────────────────────────────

def build_export_summary(df: pd.DataFrame) -> dict:
    """Summary dict used for the Excel report Summary sheet."""
    return metrics.summary_stats(df)


def build_category_export(df: pd.DataFrame) -> pd.DataFrame:
    """Category breakdown DataFrame for the Excel report."""
    cat_data = metrics.analyze_category_trends(df)
    return cat_data["breakdown"].rename(
        columns={"Total (₹)": "Total (₹)", "Transactions": "Transactions", "Avg (₹)": "Avg (₹)"}
    )
