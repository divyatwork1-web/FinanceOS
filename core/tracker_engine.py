"""
core/tracker_engine.py
══════════════════════════════════════════════════════════════════
Tracker-side logic layer.
Handles DataFrame enrichment (adding derived columns), session-level
caching via st.session_state, and any tracker-specific helpers.

Rule: nothing in this file directly renders Streamlit UI.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.db import db_get_txns

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

CATS = [
    "Food & Dining", "Shopping", "Transport", "Entertainment",
    "Utilities", "Healthcare", "Education", "Rent",
    "Salary", "Investments", "Freelance", "Other",
]


# ── DataFrame preparation ─────────────────────────────────────────

def enrich_df(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the raw DataFrame from db_get_txns and adds derived columns:
      - Transaction Type  → normalised to lowercase str
      - Date              → datetime, rows with unparseable dates dropped
      - Month Name        → e.g. "January"
      - Month Key         → e.g. "2024-01"
      - Year              → str
      - Amount            → numeric, NaN → 0
    """
    if raw.empty:
        return pd.DataFrame()
    df = raw.copy()
    df["Transaction Type"] = df["Transaction Type"].str.strip().str.lower()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    df["Month Name"] = df["Date"].dt.month_name()
    df["Month Key"]  = df["Date"].dt.to_period("M").astype(str)
    df["Year"]       = df["Date"].dt.year.astype(str)
    df["Amount"]     = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
    return df


@st.cache_data(ttl=30, show_spinner=False)
def get_enriched_df(username: str) -> pd.DataFrame:
    """
    Cached version: fetches raw transactions for *username* from SQLite,
    then enriches them. Cache TTL is 30 seconds so edits propagate quickly.
    Call st.cache_data.clear() after any write operation to invalidate.
    """
    raw = db_get_txns(username)
    return enrich_df(raw)


def get_df() -> pd.DataFrame:
    """
    Convenience wrapper used by page functions.
    Reads the username from st.session_state automatically.
    """
    uid = st.session_state.get("username", "")
    if not uid:
        return pd.DataFrame()
    return get_enriched_df(uid)


def invalidate_cache() -> None:
    """Call after any write (add / update / delete / import) to bust the cache."""
    get_enriched_df.clear()


# ── Filter helpers ────────────────────────────────────────────────

def filter_df(
    df: pd.DataFrame,
    txn_type: str = "All",
    category: str = "All",
    account: str = "",
    year: str = "All",
) -> pd.DataFrame:
    """Apply the edit-page filter controls to a DataFrame."""
    fdf = df.copy()
    if txn_type != "All":
        fdf = fdf[fdf["Transaction Type"] == txn_type]
    if category != "All":
        fdf = fdf[fdf["Category"] == category]
    if account.strip():
        fdf = fdf[
            fdf["Account Name"].str.contains(account.strip(), case=False, na=False)
        ]
    if year != "All":
        fdf = fdf[fdf["Date"].astype(str).str.startswith(year)]
    return fdf
