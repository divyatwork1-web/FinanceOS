"""
core/charts.py
══════════════════════════════════════════════════════════════════
Plotly figure factories for FinanceOS.
Every function returns a go.Figure ready to pass to st.plotly_chart.
No Streamlit calls live here — pure data → figure transforms.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

PASTEL = [
    "#F9A8D4", "#93C5FD", "#6EE7B7", "#C4B5FD",
    "#FCA5A5", "#FCD34D", "#A5F3FC", "#FBCFE8",
]

# ── Shared layout factory ─────────────────────────────────────────

def _layout(**kw) -> dict:
    base = dict(
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Nunito", color="#1A1A2E"),
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#1A1A2E")),
        xaxis=dict(gridcolor="#F3E8FF", zerolinecolor="#F3E8FF"),
        yaxis=dict(gridcolor="#F3E8FF", zerolinecolor="#F3E8FF"),
    )
    base.update(kw)
    return base


# ── Bar charts ────────────────────────────────────────────────────

def bar_top_categories(cat_df: pd.DataFrame) -> go.Figure:
    """Horizontal bar of top expense categories."""
    fig = px.bar(
        cat_df,
        x="Category",
        y="Amount",
        text_auto=True,
        color="Category",
        color_discrete_sequence=PASTEL,
        title="Top 10 Expense Categories",
    )
    fig.update_layout(**_layout(xaxis_title="Category", yaxis_title="Amount (₹)"))
    fig.update_traces(
        textfont=dict(color="#1A1A2E", size=12), textposition="outside"
    )
    return fig


def bar_income_vs_expense(comp_df: pd.DataFrame) -> go.Figure:
    """Grouped bar: monthly income vs expense."""
    fig = px.bar(
        comp_df,
        x="Month Name",
        y=["Income", "Expense"],
        barmode="group",
        title="Monthly Income vs Expense",
        color_discrete_sequence=["#6EE7B7", "#FCA5A5"],
    )
    fig.update_layout(**_layout(xaxis_title="Month", yaxis_title="Amount (₹)"))
    return fig


def bar_savings(sav_df: pd.DataFrame) -> go.Figure:
    """Colour-scaled bar for monthly net savings."""
    fig = px.bar(
        sav_df,
        x="Month Name",
        y="Savings",
        title="Monthly Net Savings",
        color="Savings",
        color_continuous_scale=["#FCA5A5", "#FCD34D", "#6EE7B7"],
    )
    fig.update_layout(**_layout(xaxis_title="Month", yaxis_title="Savings (₹)"))
    return fig


def bar_stacked_category_month(cats_df: pd.DataFrame) -> go.Figure:
    """Stacked bar: category spending by month."""
    fig = px.bar(
        cats_df,
        x="Month Name",
        y="Amount",
        color="Category",
        barmode="stack",
        title="Category Spending by Month",
        color_discrete_sequence=PASTEL,
    )
    fig.update_layout(**_layout(xaxis_title="Month", yaxis_title="Amount (₹)"))
    return fig


def bar_budget_vs_actual(chart_data: list[dict]) -> go.Figure:
    """Grouped bar: budget vs actual per category."""
    bdf = pd.DataFrame(chart_data)
    fig = px.bar(
        bdf,
        x="Category",
        y="Amount",
        color="Type",
        barmode="group",
        title="Budget vs Actual Spending",
        color_discrete_map={"Budget": "#93C5FD", "Spent": "#FCA5A5"},
    )
    fig.update_layout(**_layout(xaxis_title="Category", yaxis_title="Amount (₹)"))
    return fig


# ── Line charts ───────────────────────────────────────────────────

def line_expense_trend(m_exp_df: pd.DataFrame) -> go.Figure:
    """Line chart of monthly expense trend."""
    fig = px.line(
        m_exp_df,
        x="Month Name",
        y="Amount",
        markers=True,
        title="Monthly Expense Trend",
        color_discrete_sequence=["#C4B5FD"],
    )
    fig.update_layout(**_layout(xaxis_title="Month", yaxis_title="Amount (₹)"))
    fig.update_traces(
        line=dict(width=3),
        marker=dict(size=10, color="#be185d", line=dict(color="#FFFFFF", width=2)),
    )
    return fig


def line_savings_trend(sav_df: pd.DataFrame) -> go.Figure:
    """Line chart of savings trend."""
    fig = px.line(
        sav_df,
        x="Month Name",
        y="Savings",
        markers=True,
        title="Savings Trend Line",
        color_discrete_sequence=["#818CF8"],
    )
    fig.update_layout(**_layout(xaxis_title="Month", yaxis_title="Savings (₹)"))
    fig.update_traces(
        line=dict(width=3),
        marker=dict(size=10, color="#be185d", line=dict(color="#FFFFFF", width=2)),
    )
    return fig


# ── Pie / donut charts ────────────────────────────────────────────

def pie_expense_distribution(pie_df: pd.DataFrame) -> go.Figure:
    """Donut pie: top-5 categories + Others."""
    fig = px.pie(
        pie_df,
        values="Amount",
        names="Category",
        title="🍩 Expense Distribution",
        hole=0.45,
        color_discrete_sequence=PASTEL,
    )
    fig.update_layout(**_layout())
    fig.update_traces(
        textfont=dict(color="#1A1A2E", size=13),
        pull=[0.03] * len(pie_df),
        marker=dict(line=dict(color="#FFFFFF", width=3)),
    )
    return fig


def pie_expense_by_account(acct_df: pd.DataFrame) -> go.Figure:
    """Donut pie: expense share per account."""
    fig = px.pie(
        acct_df,
        names="Account Name",
        values="Amount",
        hole=0.5,
        title="Expense by Account",
        color_discrete_sequence=PASTEL,
    )
    fig.update_layout(**_layout())
    fig.update_traces(
        textfont=dict(color="#1A1A2E", size=13),
        pull=[0.03] * len(acct_df),
        marker=dict(line=dict(color="#FFFFFF", width=3)),
    )
    return fig


# ── Gauge ─────────────────────────────────────────────────────────

def gauge_savings_rate(savings_pct: float, health_label: str) -> go.Figure:
    """Plotly gauge for savings rate / financial health."""
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=savings_pct,
            title={
                "text": f"Savings Rate — {health_label}",
                "font": {"color": "#be185d", "family": "Nunito", "size": 16},
            },
            number={"suffix": "%", "font": {"color": "#1A1A2E", "size": 36}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#1A1A2E"},
                "bar": {"color": "#818CF8"},
                "steps": [
                    {"range": [0, 10], "color": "#FCA5A5"},
                    {"range": [10, 30], "color": "#FCD34D"},
                    {"range": [30, 50], "color": "#6EE7B7"},
                    {"range": [50, 100], "color": "#A7F3D0"},
                ],
                "bordercolor": "#F9A8D4",
            },
        )
    )
    fig.update_layout(
        height=380,
        paper_bgcolor="#FFFFFF",
        font=dict(family="Nunito", color="#1A1A2E"),
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return fig


# ── Treemap ───────────────────────────────────────────────────────

def treemap_top_categories(bd: pd.DataFrame, n: int = 8) -> go.Figure:
    """Treemap of top-N expense categories."""
    top = bd.head(n)
    fig = px.treemap(
        top,
        path=["Category"],
        values="Total (₹)",
        title=f"Spending Treemap — Top {n} Categories",
        color="Total (₹)",
        color_continuous_scale=["#EDE9FE", "#be185d"],
    )
    fig.update_layout(
        height=420,
        paper_bgcolor="#FFFFFF",
        font=dict(family="Nunito", color="#1A1A2E"),
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig
