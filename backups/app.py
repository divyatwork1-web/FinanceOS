"""
app.py  —  FinanceOS  💸
══════════════════════════════════════════════════════════════════
Entry point.  Contains:
  • Page config + global CSS
  • Session-state defaults
  • Navigation helpers (go / nav / switch_mode)
  • Auth page
  • Onboarding pages
  • Sidebar + Topbar renderers
  • Tracker pages   (mode == "tracker" only)
  • Analyzer pages  (both modes)
  • Reports page
  • Profile page
  • Main router

All heavy calculations are delegated to core/:
  core/db.py              – SQLite CRUD
  core/tracker_engine.py  – DataFrame enrichment + caching
  core/analyzer_engine.py – read-only payload builders
  core/metrics.py         – reusable KPI functions
  core/insights.py        – HTML card builders
  core/charts.py          – Plotly figure factories
"""

import io
from datetime import date, datetime

import pandas as pd
import streamlit as st

from core.tracker_engine import (
    CATS,
    MONTHS,
    filter_df,
)
from core import analyzer_engine, insights
from core.insights import (
    generate_behavioral_analysis,
    detect_financial_personality,
    generate_predictive_insights,
    generate_financial_recommendations,
    render_personality_card,
    render_recommendation_card,
    PERSONALITY_PROFILES,
)

# ── Direct session-state get_df (no DB patching needed) ───────────
# tracker_engine's get_df is bypassed entirely.
# We define get_df and invalidate_cache here, reading straight from
# st.session_state["transactions"] which _launch_platform populates.

def get_df() -> pd.DataFrame:
    """Return enriched transactions DataFrame from session state."""
    rows = st.session_state.get("transactions", [])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"])
        if "Month Name" not in df.columns:
            df["Month Name"] = df["Date"].dt.month_name()
        if "Month Key" not in df.columns:
            df["Month Key"] = df["Date"].dt.to_period("M").astype(str)
        if "Year" not in df.columns:
            df["Year"] = df["Date"].dt.year.astype(str)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    if "Amount" in df.columns:
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
    if "Transaction Type" in df.columns:
        df["Transaction Type"] = df["Transaction Type"].astype(str).str.strip().str.lower()
    return df

def invalidate_cache():
    """No-op — session state is always fresh, no cache to clear."""
    pass

# ══════════════════════════════════════════════════════════════════
#  PAGE CONFIG
# ══════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="FinanceOS",
    layout="wide",
    page_icon="💸",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════════════════
#  SESSION STATE
# ══════════════════════════════════════════════════════════════════
DEFAULTS = {
    "app_page":     "upload",     # upload | platform
    "mode":         None,         # "tracker" | "analyzer"
    "nav_section":  "tracker",
    "nav_page":     "overview",
    "edit_txn_id":  None,
    # Session-only data (no DB)
    "transactions": [],           # list of dicts — cleared on every new session
    "budgets":      {},           # {month: {category: amount}}
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Session-state DB shims ────────────────────────────────────────
# All functions below replace the SQLite db_* calls with pure
# session_state equivalents so the rest of the app is unchanged.

import uuid as _uuid

def _next_id() -> int:
    rows = st.session_state.get("transactions", [])
    return max((r["id"] for r in rows), default=0) + 1

def db_get_txns(_uid=None) -> pd.DataFrame:
    rows = st.session_state.get("transactions", [])
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)

def db_has_transactions(_uid=None) -> bool:
    return bool(st.session_state.get("transactions"))

def db_import_txns(_uid, df: pd.DataFrame) -> int:
    rows = st.session_state.setdefault("transactions", [])
    for _, r in df.iterrows():
        rows.append({
            "id":               _next_id(),
            "Date":             str(r.get("Date", ""))[:10],
            "Transaction Type": str(r.get("Transaction Type", "")).strip().lower(),
            "Category":         str(r.get("Category", "")),
            "Amount":           float(r.get("Amount", 0)),
            "Account Name":     str(r.get("Account Name", "")),
            "Note":             str(r.get("Note", "")),
        })
    return len(df)

def db_add_txn(_uid, txn_date, txn_type, txn_cat, txn_amt, txn_acct, txn_note=""):
    rows = st.session_state.setdefault("transactions", [])
    rows.append({
        "id":               _next_id(),
        "Date":             str(txn_date),
        "Transaction Type": txn_type,
        "Category":         txn_cat,
        "Amount":           float(txn_amt),
        "Account Name":     txn_acct,
        "Note":             txn_note,
    })

def db_update_txn(row_id, e_date, e_type, e_cat, e_amt, e_acct, e_note=""):
    for r in st.session_state.get("transactions", []):
        if r["id"] == row_id:
            r.update({
                "Date":             str(e_date),
                "Transaction Type": e_type,
                "Category":         e_cat,
                "Amount":           float(e_amt),
                "Account Name":     e_acct,
                "Note":             e_note,
            })
            break

def db_delete_txn(row_id):
    rows = st.session_state.get("transactions", [])
    st.session_state["transactions"] = [r for r in rows if r["id"] != row_id]

def db_clear_txns(_uid=None):
    st.session_state["transactions"] = []

def db_get_budgets(_uid, month: str) -> pd.DataFrame:
    budgets = st.session_state.get("budgets", {})
    month_data = budgets.get(month, {})
    if not month_data:
        return pd.DataFrame()
    rows = [{"category": cat, "amount": amt} for cat, amt in month_data.items()]
    return pd.DataFrame(rows)

def db_set_budget(_uid, month: str, category: str, amount: float):
    budgets = st.session_state.setdefault("budgets", {})
    budgets.setdefault(month, {})[category] = amount

def db_delete_budget(_uid, month: str, category: str):
    budgets = st.session_state.get("budgets", {})
    if month in budgets and category in budgets[month]:
        del budgets[month][category]


# ══════════════════════════════════════════════════════════════════
#  NAVIGATION HELPERS
# ══════════════════════════════════════════════════════════════════
def go(page: str, **kwargs) -> None:
    st.session_state.app_page = page
    for k, v in kwargs.items():
        st.session_state[k] = v
    st.rerun()


def nav(section: str, page: str) -> None:
    st.session_state.nav_section = section
    st.session_state.nav_page    = page
    st.rerun()


def switch_mode(new_mode: str) -> None:
    """Switch between tracker and analyzer modes — fully resets navigation."""
    st.session_state.mode = new_mode
    if new_mode == "tracker":
        st.session_state.nav_section = "tracker"
        st.session_state.nav_page    = "overview"
    elif new_mode == "analyzer":
        st.session_state.nav_section = "analyzer"
        st.session_state.nav_page    = "insights"
    st.rerun()


# ══════════════════════════════════════════════════════════════════
#  GLOBAL BASE CSS  —  Dual Identity System
# ══════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    /* ── Tracker palette (pink/purple workspace) ── */
    --tr-primary:   #be185d;
    --tr-secondary: #9d174d;
    --tr-accent:    #f472b6;
    --tr-purple:    #7c3aed;
    --tr-border:    #F9A8D4;
    --tr-bg:        #FFF0F9;
    --tr-card:      #FFFFFF;
    --tr-grad:      linear-gradient(90deg,#f472b6,#a78bfa);
    --tr-page-bg:   linear-gradient(150deg,#FFF0F9 0%,#EFF6FF 40%,#F0FDF4 100%);
    --tr-topbar-bg: rgba(255,240,249,.88);
    --tr-topbar-bd: rgba(249,168,212,.5);
    --tr-topbar-sh: rgba(249,168,212,.22);

    /* ── Analyzer palette (blue/purple intelligence) ── */
    --az-primary:   #1e40af;
    --az-secondary: #3b82f6;
    --az-accent:    #6366f1;
    --az-purple:    #7c3aed;
    --az-border:    #6366f1;
    --az-bg:        #0f172a;
    --az-card:      rgba(30,41,59,.85);
    --az-grad:      linear-gradient(90deg,#3b82f6,#6366f1,#8b5cf6);
    --az-page-bg:   linear-gradient(150deg,#0f172a 0%,#1e1b4b 50%,#0f172a 100%);
    --az-topbar-bg: rgba(15,23,42,.88);
    --az-topbar-bd: rgba(99,102,241,.35);
    --az-topbar-sh: rgba(99,102,241,.18);
}

*, *::before, *::after { box-sizing: border-box; }

html, body, [data-testid="stAppViewContainer"],
[data-testid="stAppViewBlockContainer"], .main, .stApp {
    font-family: 'Nunito', sans-serif !important;
    color: #1A1A2E !important;
}
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stSidebar"] { display: none !important; }

/* ── Alerts ── */
[data-testid="stAlert"] p, [data-testid="stAlert"] div {
    color:#1A1A2E!important; font-weight:800!important; font-size:1rem!important; }

/* ── Table / DataFrame ── */
[data-testid="stDataFrame"] { border-radius:14px; overflow:hidden; border:2px solid #A5F3FC; }

/* ── File uploader ── */
[data-testid="stFileUploader"] { background:#FFF0F9; border-radius:18px;
    border:2.5px dashed #F9A8D4; padding:1rem; }

/* ── Inputs ── */
input[type="text"],input[type="password"],input[type="number"],
[data-testid="stTextInput"] input,[data-testid="stNumberInput"] input {
    border:2px solid #F9A8D4!important; border-radius:12px!important;
    font-family:'Nunito',sans-serif!important; font-weight:700!important;
    color:#1A1A2E!important; background:#FFFBFB!important; }

hr  { border-color:#F9A8D4; opacity:.5; }
.block-container { padding-top:0!important; padding-bottom:2rem; max-width:100%!important; }

/* ══════════════════════════════════════════════════
   TRACKER IDENTITY — pink/purple workspace
   ══════════════════════════════════════════════════ */

/* Tracker buttons */
.tracker-mode [data-testid="baseButton-secondary"],
.tracker-mode [data-testid="baseButton-primary"],
.tracker-mode [data-testid="stDownloadButton"] button,
.tracker-mode [data-testid="stFileUploader"] button,
[data-testid="baseButton-secondary"],[data-testid="baseButton-primary"],
[data-testid="stDownloadButton"] button,[data-testid="stFileUploader"] button,
button[kind="secondary"],button[kind="primary"] {
    background: linear-gradient(90deg,#f472b6,#a78bfa)!important;
    color:#FFFFFF!important; -webkit-text-fill-color:#FFFFFF!important;
    border-radius:14px!important; border:none!important;
    font-weight:900!important; font-size:1rem!important; padding:.6rem 1.4rem!important; }
[data-testid="baseButton-secondary"]:hover,
[data-testid="stDownloadButton"] button:hover {
    background:linear-gradient(90deg,#ec4899,#8b5cf6)!important; }

/* Tracker sidebar */
.tracker-mode [data-testid="stSidebar"] > div:first-child,
.tracker-sidebar [data-testid="stSidebar"] > div:first-child {
    background: linear-gradient(180deg,#FFF0F9 0%,#fce7f3 50%,#ede9fe 100%) !important;
    border-right: 2.5px solid #F9A8D4 !important; }

/* Tracker h2 section headers */
.tracker-h2 { color:#9d174d!important; font-weight:900!important; font-size:1.4rem!important;
    border-left:5px solid #f472b6; padding-left:10px; margin-top:.4rem; }

/* Tracker metrics */
.tracker-mode div[data-testid="metric-container"] {
    background:#FFFFFF!important; border:3px solid #F9A8D4!important;
    border-radius:20px!important; padding:20px 22px!important;
    box-shadow:0 6px 24px rgba(249,168,212,.25)!important; }

/* ══════════════════════════════════════════════════
   ANALYZER IDENTITY — dark blue/purple intelligence
   ══════════════════════════════════════════════════ */

/* Analyzer page background */
.analyzer-page-bg {
    background: linear-gradient(150deg,#0f172a 0%,#1e1b4b 50%,#0f172a 100%); }

/* Analyzer buttons */
.analyzer-mode [data-testid="baseButton-primary"] {
    background: linear-gradient(90deg,#3b82f6,#6366f1)!important;
    box-shadow: 0 4px 16px rgba(99,102,241,.4)!important; }
.analyzer-mode [data-testid="baseButton-secondary"] {
    background: rgba(30,41,59,.7)!important;
    color: #a5b4fc!important; -webkit-text-fill-color:#a5b4fc!important;
    border: 1.5px solid rgba(99,102,241,.4)!important; }

/* Analyzer sidebar */
.analyzer-sidebar [data-testid="stSidebar"] > div:first-child {
    background: linear-gradient(180deg,#0f172a 0%,#1e1b4b 100%) !important;
    border-right: 1.5px solid rgba(99,102,241,.3) !important; }

/* ── Shared nav structure ──────────────────────────────── */
.nav-section-label {
    font-size:.63rem; font-weight:900; letter-spacing:.14em; text-transform:uppercase;
    color:#be185d; padding:10px 10px 3px; margin-top:.6rem; }
.nav-section-label.az {
    color:#a5b4fc; }
.nav-item {
    display:flex; align-items:center; gap:10px; padding:9px 14px;
    border-radius:12px; cursor:pointer; font-weight:700; font-size:.91rem;
    color:#374151; margin:2px 0; transition:all .15s; border:none;
    background:transparent; width:100%; text-align:left; }
.nav-item:hover { background:rgba(249,168,212,.25); color:#be185d; }
.nav-item.active {
    background:linear-gradient(90deg,rgba(244,114,182,.18),rgba(167,139,250,.18));
    color:#be185d; border-left:3px solid #f472b6; padding-left:11px; font-weight:900; }
.nav-item.az-active {
    background: linear-gradient(90deg,rgba(59,130,246,.2),rgba(99,102,241,.2));
    color:#93c5fd; border-left:3px solid #6366f1; padding-left:11px; font-weight:900; }

/* ── Tracker KPI cards ──────────────────────────────────── */
.kpi-card { background:#FFFFFF; border-radius:20px; padding:20px 22px;
    box-shadow:0 6px 24px rgba(0,0,0,.06); }
.kpi-label { font-size:.72rem; font-weight:900; letter-spacing:.09em;
    text-transform:uppercase; color:#9d174d; margin-bottom:6px; }
.kpi-value { font-size:1.7rem; font-weight:900; color:#1A1A2E; }

/* ── Analyzer KPI cards (larger, premium) ──────────────── */
.az-kpi-card {
    background: linear-gradient(135deg,rgba(30,41,59,.9),rgba(15,23,42,.95));
    border: 1.5px solid rgba(99,102,241,.35);
    border-radius: 20px; padding: 26px 28px;
    box-shadow: 0 8px 32px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.06);
}
.az-kpi-label {
    font-size:.72rem; font-weight:800; letter-spacing:.12em;
    text-transform:uppercase; color:#a5b4fc; margin-bottom:10px;
    font-family:'Inter',sans-serif;
}
.az-kpi-value {
    font-size:2.1rem; font-weight:900; color:#f0f9ff;
    font-family:'Inter',sans-serif; letter-spacing:-.02em;
}
.az-kpi-sub { font-size:.78rem; color:#64748b; font-weight:600; margin-top:4px; }

/* ── Analyzer insight commentary cards ─────────────────── */
.az-insight-card {
    background: linear-gradient(135deg,rgba(30,41,59,.88),rgba(30,27,75,.88));
    border: 1.5px solid rgba(99,102,241,.3);
    border-radius: 18px; padding: 20px 24px; margin-bottom: 12px;
    box-shadow: 0 6px 24px rgba(0,0,0,.25);
    display: flex; align-items: flex-start; gap: 14px;
}
.az-insight-icon {
    font-size: 1.6rem; flex-shrink: 0; margin-top: 2px;
}
.az-insight-text {
    font-size: .95rem; font-weight: 700; color: #e2e8f0; line-height: 1.55;
}
.az-insight-tag {
    display: inline-block; font-size: .7rem; font-weight: 800;
    letter-spacing: .08em; text-transform: uppercase;
    padding: 2px 8px; border-radius: 20px; margin-top: 6px;
}
.az-insight-tag.up   { background:rgba(34,197,94,.15); color:#4ade80; border:1px solid rgba(74,222,128,.25); }
.az-insight-tag.down { background:rgba(239,68,68,.15);  color:#f87171; border:1px solid rgba(248,113,113,.25); }
.az-insight-tag.info { background:rgba(99,102,241,.15); color:#a5b4fc; border:1px solid rgba(165,180,252,.25); }
.az-insight-tag.warn { background:rgba(245,158,11,.15); color:#fbbf24; border:1px solid rgba(251,191,36,.25); }

/* ── Analyzer section header ───────────────────────────── */
.az-section-header {
    font-size: 1.1rem; font-weight: 800; color: #a5b4fc;
    letter-spacing: .06em; text-transform: uppercase;
    padding-bottom: 10px; margin-bottom: 1rem;
    border-bottom: 1px solid rgba(99,102,241,.25);
    font-family: 'Inter', sans-serif;
}

/* ── Tracker page topbar ────────────────────────────────── */
.page-topbar {
    display:flex; align-items:center; justify-content:space-between;
    margin-bottom:1.5rem; padding-bottom:1rem; border-bottom:2px solid #F9A8D4; }
.page-title  { font-size:1.9rem; font-weight:900; color:#be185d; margin:0; }
.page-breadcrumb { font-size:.82rem; font-weight:700; color:#9d174d; opacity:.7; }

/* ── Analyzer page topbar ───────────────────────────────── */
.az-page-topbar {
    display:flex; align-items:center; justify-content:space-between;
    margin-bottom:1.8rem; padding-bottom:1.1rem;
    border-bottom: 1px solid rgba(99,102,241,.3); }
.az-page-title  { font-size:1.7rem; font-weight:800; color:#e2e8f0; margin:0;
    font-family:'Inter',sans-serif; letter-spacing:-.02em; }
.az-page-breadcrumb { font-size:.78rem; font-weight:600; color:#6366f1;
    text-transform:uppercase; letter-spacing:.08em; }

/* ── Auth page ──────────────────────────────────────────── */
.auth-viewport {
    position: fixed; top:0; left:0; right:0; bottom:0;
    display:flex; flex-direction:column;
    align-items:center; justify-content:center;
    background:linear-gradient(150deg,#FFF0F9 0%,#EFF6FF 50%,#F0FDF4 100%);
    overflow-y: auto; padding: 1rem;
}

/* ── Onboarding ─────────────────────────────────────────── */
.onboard-viewport {
    min-height: 100vh;
    background: linear-gradient(135deg,#EDE9FE 0%,#FFF0F9 45%,#ECFDF5 100%);
}

/* ── TRACKER Topbar ─────────────────────────────────────── */
.finance-topbar {
    position: sticky; top: 0; z-index: 999;
    display: flex; align-items: center; justify-content: space-between;
    padding: .75rem 2rem;
    background: linear-gradient(90deg,rgba(255,240,249,.92),rgba(237,233,254,.92));
    backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border-bottom: 2px solid rgba(249,168,212,.5);
    box-shadow: 0 4px 28px rgba(249,168,212,.22);
    border-radius: 0 0 20px 20px;
    margin-bottom: 1.4rem;
}
.topbar-logo {
    font-size: 1.22rem; font-weight: 900; color: #be185d;
    letter-spacing: -.02em; display: flex; align-items: center; gap: 6px;
}
.topbar-center { display: flex; align-items: center; gap: 10px; }
.topbar-right  { display: flex; align-items: center; gap: 12px; }

/* ── ANALYZER Topbar ────────────────────────────────────── */
.analyzer-topbar {
    position: sticky; top: 0; z-index: 999;
    display: flex; align-items: center; justify-content: space-between;
    padding: .75rem 2rem;
    background: linear-gradient(90deg,rgba(15,23,42,.92),rgba(30,27,75,.92));
    backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
    border-bottom: 1.5px solid rgba(99,102,241,.3);
    box-shadow: 0 4px 32px rgba(0,0,0,.4), 0 0 0 1px rgba(99,102,241,.1);
    border-radius: 0 0 20px 20px;
    margin-bottom: 1.4rem;
}
.analyzer-topbar-logo {
    font-size: 1.22rem; font-weight: 900; color: #a5b4fc;
    letter-spacing: -.02em; display: flex; align-items: center; gap: 8px;
    font-family: 'Inter', sans-serif;
}
.analyzer-topbar-logo span.name { color: #6366f1; }
.analyzer-topbar-logo span.page {
    color: #64748b; font-size: .93rem; font-weight: 600;
    margin-left: 14px; padding-left: 14px;
    border-left: 1px solid rgba(99,102,241,.3);
}

/* mode badges */
.mode-badge {
    display: inline-flex; align-items: center;
    background: rgba(255,255,255,.75);
    border: 2px solid rgba(249,168,212,.5);
    border-radius: 50px; padding: 4px 14px;
    font-size: .78rem; font-weight: 900; color: #9d174d;
    box-shadow: 0 2px 10px rgba(249,168,212,.2);
}
.az-mode-badge {
    display: inline-flex; align-items: center; gap: 6px;
    background: linear-gradient(90deg,rgba(99,102,241,.15),rgba(139,92,246,.15));
    border: 1.5px solid rgba(99,102,241,.4);
    border-radius: 50px; padding: 5px 16px;
    font-size: .78rem; font-weight: 800; color: #a5b4fc;
    font-family: 'Inter', sans-serif; letter-spacing: .04em;
}
.az-mode-badge::before { content:'●'; color:#6366f1; font-size:.6rem; }

/* profile chips */
.profile-chip {
    display: flex; align-items: center; gap: 7px; cursor: pointer;
    background: rgba(255,255,255,.7);
    border: 2px solid rgba(249,168,212,.4);
    border-radius: 50px; padding: 5px 14px 5px 6px;
    font-weight: 800; font-size: .88rem; color: #9d174d;
}
.az-profile-chip {
    display: flex; align-items: center; gap: 7px; cursor: pointer;
    background: rgba(30,41,59,.7);
    border: 1.5px solid rgba(99,102,241,.35);
    border-radius: 50px; padding: 5px 14px 5px 6px;
    font-weight: 700; font-size: .88rem; color: #a5b4fc;
    font-family: 'Inter', sans-serif;
}
.profile-avatar {
    width: 30px; height: 30px; border-radius: 50%;
    background: linear-gradient(135deg,#f472b6,#a78bfa);
    color: #fff; font-weight: 900; font-size: .88rem;
    display: flex; align-items: center; justify-content: center;
}
.az-profile-avatar {
    width: 30px; height: 30px; border-radius: 50%;
    background: linear-gradient(135deg,#3b82f6,#6366f1);
    color: #fff; font-weight: 800; font-size: .88rem;
    display: flex; align-items: center; justify-content: center;
    font-family: 'Inter', sans-serif;
}

/* topbar page title */
.topbar-page-title { font-size: 1rem; font-weight: 800; color: #7c3aed; }

/* ── Tracker stat cards ─────────────────────────────────── */
.tr-stat-card {
    background: #FFFFFF; border: 2.5px solid #F9A8D4;
    border-radius: 18px; padding: 18px 20px;
    box-shadow: 0 4px 20px rgba(249,168,212,.2);
}
.tr-stat-label {
    font-size: .7rem; font-weight: 900; letter-spacing: .1em;
    text-transform: uppercase; color: #9d174d; margin-bottom: 6px;
}
.tr-stat-value { font-size: 1.65rem; font-weight: 900; color: #1A1A2E; }
.tr-stat-sub   { font-size: .78rem; color: #9d174d; font-weight: 700; margin-top: 4px; }

/* ── Tracker activity feed ──────────────────────────────── */
.tr-activity-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 16px; border-radius: 12px; margin-bottom: 6px;
    background: #FFFBFB; border: 1.5px solid rgba(249,168,212,.3);
}
.tr-activity-cat { font-weight: 800; color: #be185d; font-size: .9rem; }
.tr-activity-date { font-size: .78rem; color: #9d174d; font-weight: 600; }
.tr-activity-amt-d { font-weight: 900; color: #dc2626; font-size: 1rem; }
.tr-activity-amt-c { font-weight: 900; color: #059669; font-size: 1rem; }

/* ── Tracker budget summary ─────────────────────────────── */
.tr-budget-panel {
    background: linear-gradient(135deg,#FFF0F9,#ede9fe);
    border: 2.5px solid #c4b5fd; border-radius: 20px; padding: 20px 24px;
    box-shadow: 0 4px 20px rgba(196,181,253,.2);
}

/* ── Animations ─────────────────────────────────────────── */
@keyframes fadeInUp {
    from { opacity:0; transform:translateY(18px); }
    to   { opacity:1; transform:translateY(0); }
}
@keyframes fadeIn {
    from { opacity:0; } to { opacity:1; }
}
.fade-in { animation: fadeIn .4s ease; }
.fade-up  { animation: fadeInUp .45s ease; }
</style>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
#  UI HELPERS  (HTML card factories — mode-aware)
# ══════════════════════════════════════════════════════════════════

def _is_analyzer() -> bool:
    return st.session_state.get("mode", "tracker") == "analyzer"


# ── Tracker KPI card ──────────────────────────────────────────────
def kpi(label, value, border="#F9A8D4", shadow="rgba(249,168,212,.3)"):
    return f"""<div style="background:#FFFFFF;border:3px solid {border};border-radius:20px;
        padding:20px 22px;box-shadow:0 6px 24px {shadow};">
        <div style="color:#9d174d;font-weight:900;font-size:.72rem;letter-spacing:.09em;
            text-transform:uppercase;margin-bottom:6px;">{label}</div>
        <div style="color:#1A1A2E;font-weight:900;font-size:1.7rem;font-family:Nunito,sans-serif;">{value}</div>
    </div>"""


# ── Analyzer premium KPI card ─────────────────────────────────────
def az_kpi(label, value, sub="", accent="#6366f1"):
    return f"""<div class="az-kpi-card fade-up">
        <div class="az-kpi-label">{label}</div>
        <div class="az-kpi-value">{value}</div>
        {f'<div class="az-kpi-sub">{sub}</div>' if sub else ''}
    </div>"""


# ── Analyzer insight commentary card ─────────────────────────────
def az_insight(icon, text, tag_text, tag_type="info"):
    return f"""<div class="az-insight-card fade-in">
        <div class="az-insight-icon">{icon}</div>
        <div>
            <div class="az-insight-text">{text}</div>
            <span class="az-insight-tag {tag_type}">{tag_text}</span>
        </div>
    </div>"""


def info_card(label, value, border="#6EE7B7", shadow="rgba(110,231,183,.25)"):
    if _is_analyzer():
        return az_kpi(label, value)
    return f"""<div style="background:#FFFFFF;border:3px solid {border};border-radius:20px;
        padding:18px 22px;box-shadow:0 6px 24px {shadow};">
        <div style="color:#9d174d;font-weight:900;font-size:.72rem;text-transform:uppercase;margin-bottom:6px;">{label}</div>
        <div style="color:#1A1A2E;font-weight:900;font-size:1.35rem;">{value}</div>
    </div>"""


def empty_state(icon, title, subtitle):
    if _is_analyzer():
        st.markdown(f"""<div style="background:rgba(30,41,59,.7);border:1.5px dashed rgba(99,102,241,.4);
            border-radius:22px;padding:60px;text-align:center;margin:2rem 0;">
            <div style="font-size:3.5rem;">{icon}</div>
            <div style="font-size:1.2rem;font-weight:800;color:#a5b4fc;margin-top:1rem;
                font-family:Inter,sans-serif;">{title}</div>
            <div style="color:#475569;font-weight:600;margin-top:.6rem;">{subtitle}</div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""<div style="background:#FFFFFF;border:3px dashed #F9A8D4;border-radius:22px;
            padding:50px;text-align:center;margin:2rem 0;">
            <div style="font-size:3rem;">{icon}</div>
            <div style="font-size:1.2rem;font-weight:900;color:#9d174d;margin-top:1rem;">{title}</div>
            <div style="color:#6b7280;font-weight:700;margin-top:.5rem;">{subtitle}</div>
        </div>""", unsafe_allow_html=True)


def page_header(title, breadcrumb=""):
    """Mode-aware page header."""
    if _is_analyzer():
        st.markdown(f"""<div class="az-page-topbar fade-in">
            <div>
                <div class="az-page-breadcrumb">{breadcrumb}</div>
                <div class="az-page-title">{title}</div>
            </div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""<div class="page-topbar">
            <div>
                <div class="page-breadcrumb">{breadcrumb}</div>
                <div class="page-title">{title}</div>
            </div>
        </div>""", unsafe_allow_html=True)


def az_section(label: str):
    """Analyzer section divider."""
    st.markdown(f'<div class="az-section-header">{label}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
#  TOPBAR
# ══════════════════════════════════════════════════════════════════

def _current_page_title() -> str:
    PAGE_TITLES = {
        "analytics":  "📈 Analytics",
        "insights":   "💡 Insights",
        "health":     "🏥 Financial Health",
        "charts":     "📊 Charts",
        "savings":    "💚 Savings Trends",
        "categories": "🏷️ Category Analysis",
        "overview":   "🏠 Overview",
        "add":        "➕ Add Transaction",
        "edit":       "✏️ Edit / Delete",
        "budgets":    "💰 Budgets",
        "history":    "📋 History",
        "download":   "📥 Download Report",
    }
    return PAGE_TITLES.get(st.session_state.get("nav_page", "analytics"), "📈 Analytics")


def render_topbar():
    mode       = st.session_state.get("mode", "tracker")
    page_title = _current_page_title()

    if mode == "analyzer":
        # ── ANALYZER: dark blue/purple glassmorphism topbar ────────
        st.markdown(f"""
        <div class="analyzer-topbar fade-in">
            <div class="analyzer-topbar-logo">
                📊 <span class="name">FinanceOS</span>
                <span class="page">{page_title}</span>
            </div>
            <div class="topbar-center">
                <span class="az-mode-badge">INTELLIGENCE MODE</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        _, tcol2, tcol3, tcol4 = st.columns([2, 1.2, 1.2, 1.4])
        with tcol2:
            if st.button(
                "📝 Tracker ✓" if mode == "tracker" else "📝 Tracker",
                key="topbar_mode_tracker",
                use_container_width=True,
                type="primary" if mode == "tracker" else "secondary",
            ):
                if mode != "tracker":
                    switch_mode("tracker")
        with tcol3:
            if st.button(
                "📊 Analyzer ✓" if mode == "analyzer" else "📊 Analyzer",
                key="topbar_mode_analyzer",
                use_container_width=True,
                type="primary" if mode == "analyzer" else "secondary",
            ):
                if mode != "analyzer":
                    switch_mode("analyzer")
        with tcol4:
            if st.button("📂 Upload New File", key="topbar_upload_new_az", use_container_width=True):
                for k in list(DEFAULTS.keys()):
                    st.session_state[k] = DEFAULTS[k]
                st.rerun()

    else:
        # ── TRACKER: pink/purple gradient topbar ───────────────────
        st.markdown(f"""
        <div class="finance-topbar">
            <div class="topbar-logo">
                💸 <span style="color:#7c3aed;">FinanceOS</span>
                <span class="topbar-page-title" style="margin-left:14px;padding-left:14px;
                    border-left:2px solid rgba(249,168,212,.4);">{page_title}</span>
            </div>
            <div class="topbar-center">
                <span style="font-size:.74rem;font-weight:900;color:#9d174d;
                    letter-spacing:.08em;text-transform:uppercase;margin-right:2px;">WORKSPACE MODE</span>
            </div>
            <div class="topbar-right">
                <span class="mode-badge">📝 Finance Workspace</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        _, tcol2, tcol3, tcol4 = st.columns([2, 1.2, 1.2, 1.4])
        with tcol2:
            if st.button(
                "📝 Tracker ✓" if mode == "tracker" else "📝 Tracker",
                key="topbar_mode_tracker",
                use_container_width=True,
                type="primary" if mode == "tracker" else "secondary",
            ):
                if mode != "tracker":
                    switch_mode("tracker")
        with tcol3:
            if st.button(
                "📊 Analyzer ✓" if mode == "analyzer" else "📊 Analyzer",
                key="topbar_mode_analyzer",
                use_container_width=True,
                type="primary" if mode == "analyzer" else "secondary",
            ):
                if mode != "analyzer":
                    switch_mode("analyzer")
        with tcol4:
            if st.button("📂 Upload New File", key="topbar_upload_new_tr", use_container_width=True):
                for k in list(DEFAULTS.keys()):
                    st.session_state[k] = DEFAULTS[k]
                st.rerun()


# ══════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════

def render_sidebar():
    mode = st.session_state.get("mode", "tracker")
    cur_page = st.session_state.get("nav_page", "analytics")

    if mode == "analyzer":
        # ── ANALYZER: dark sidebar ─────────────────────────────────
        st.markdown("""<style>
        [data-testid="stSidebar"] { display:flex!important; }
        [data-testid="stSidebar"] > div:first-child {
            background:linear-gradient(180deg,#0f172a 0%,#1e1b4b 60%,#0f172a 100%) !important;
            border-right:1.5px solid rgba(99,102,241,.25) !important;
            padding:1rem .7rem; }
        [data-testid="stSidebar"] * { color:#a5b4fc !important; }
        [data-testid="stSidebar"] [data-testid="baseButton-secondary"] {
            background:transparent !important;
            color:#64748b !important; -webkit-text-fill-color:#64748b !important;
            border:none !important; text-align:left !important;
            font-weight:600 !important; border-radius:10px !important; }
        [data-testid="stSidebar"] [data-testid="baseButton-secondary"]:hover {
            background:rgba(99,102,241,.15) !important;
            color:#a5b4fc !important; -webkit-text-fill-color:#a5b4fc !important; }
        </style>""", unsafe_allow_html=True)

        with st.sidebar:
            st.markdown("""<div style="font-size:1.25rem;font-weight:800;color:#a5b4fc;
                padding:6px 0 14px;border-bottom:1px solid rgba(99,102,241,.25);margin-bottom:.6rem;
                letter-spacing:-.02em;font-family:Inter,sans-serif;">
                📊 <span style="color:#6366f1;">FinanceOS</span>
                <div style="font-size:.65rem;color:#475569;font-weight:600;letter-spacing:.12em;
                    text-transform:uppercase;margin-top:4px;">Intelligence Dashboard</div>
            </div>""", unsafe_allow_html=True)

            st.markdown('<div class="nav-section-label az">🔀 Mode</div>', unsafe_allow_html=True)
            if st.button("📊 Analyzer Only ✓", key="sb_az_mode_analyzer", use_container_width=True,
                         disabled=True):
                pass
            if st.button("📝 Switch to Tracker + Analyzer", key="sb_az_mode_tracker",
                         use_container_width=True):
                switch_mode("tracker")

            st.markdown('<div class="nav-section-label az">📊 Analyzer</div>', unsafe_allow_html=True)
            for label, pg in [
                ("📈 Analytics",        "analytics"),
                ("💡 Insights",         "insights"),
                ("🏥 Financial Health", "health"),
                ("📊 Charts",           "charts"),
                ("💚 Savings Trends",   "savings"),
                ("🏷️ Category Analysis","categories"),
            ]:
                if st.button(label, key=f"nav_a_{pg}", use_container_width=True):
                    nav("analyzer", pg)

            st.markdown('<div class="nav-section-label az">📥 Reports</div>', unsafe_allow_html=True)
            if st.button("📥 Download Report", key="nav_r_download_az", use_container_width=True):
                nav("reports", "download")
                for k in list(DEFAULTS.keys()):
                    st.session_state[k] = DEFAULTS[k]
                st.rerun()

    else:
        # ── TRACKER: pink/purple workspace sidebar ─────────────────
        st.markdown("""<style>
        [data-testid="stSidebar"] { display:flex!important; }
        [data-testid="stSidebar"] > div:first-child {
            background:linear-gradient(180deg,#FFF0F9 0%,#fce7f3 50%,#ede9fe 100%);
            border-right:2.5px solid #F9A8D4; padding:1rem .7rem; }
        </style>""", unsafe_allow_html=True)

        with st.sidebar:
            st.markdown("""<div style="font-size:1.35rem;font-weight:900;color:#be185d;
                padding:6px 0 14px;border-bottom:2px solid #F9A8D4;margin-bottom:.6rem;
                letter-spacing:-.02em;">💸 FinanceOS
                <div style="font-size:.62rem;color:#9d174d;font-weight:700;letter-spacing:.12em;
                    text-transform:uppercase;margin-top:4px;">Finance Workspace</div>
            </div>""", unsafe_allow_html=True)

            st.markdown('<div class="nav-section-label">🔀 Mode</div>', unsafe_allow_html=True)
            if st.button("📝 Tracker + Analyzer ✓", key="sb_tr_mode_tracker", use_container_width=True,
                         disabled=True):
                pass
            if st.button("📊 Switch to Analyzer Only", key="sb_tr_mode_analyzer",
                         use_container_width=True):
                switch_mode("analyzer")

            st.markdown('<div class="nav-section-label">📝 Tracker</div>', unsafe_allow_html=True)
            for label, pg in [
                ("🏠 Overview",        "overview"),
                ("➕ Add Transaction", "add"),
                ("✏️ Edit / Delete",    "edit"),
                ("💰 Monthly Budgets", "budgets"),
                ("📋 History",         "history"),
            ]:
                if st.button(label, key=f"nav_t_{pg}", use_container_width=True):
                    nav("tracker", pg)

            st.markdown('<div class="nav-section-label">📥 Reports</div>', unsafe_allow_html=True)
            if st.button("📥 Download Report", key="nav_r_download_tr", use_container_width=True):
                nav("reports", "download")
            for label, pg in [
                ("📈 Analytics",        "analytics"),
                ("💡 Insights",         "insights"),
                ("🏥 Financial Health", "health"),
                ("📊 Charts",           "charts"),
                ("💚 Savings Trends",   "savings"),
                ("🏷️ Category Analysis","categories"),
            ]:
                if st.button(label, key=f"nav_ta_{pg}", use_container_width=True):
                    nav("analyzer", pg)

            st.markdown("---")
            if st.button("📂 Upload New File", use_container_width=True, key="sidebar_upload_new_tr"):
                for k in list(DEFAULTS.keys()):
                    st.session_state[k] = DEFAULTS[k]
                st.rerun()


# ══════════════════════════════════════════════════════════════════
#  UPLOAD PAGE  (replaces Auth + Onboarding — mandatory every session)
# ══════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════
#  DATASET DETECTION ENGINE  (inline — no separate import needed)
# ══════════════════════════════════════════════════════════════════

import re as _re
from dataclasses import dataclass as _dataclass, field as _field

_DATE_KW    = ["date","time","dt","day","posted","transaction date","value date","txn date"]
_DESC_KW    = ["description","narration","particulars","details","remarks","narrative",
               "merchant","payee","memo","note","notes","reference","ref","name"]
_AMT_KW     = ["amount","amt","sum","value","total"]
_DEBIT_KW   = ["debit","withdrawal","withdraw","dr","expense","paid","outflow","out"]
_CREDIT_KW  = ["credit","deposit","cr","income","received","inflow","in"]
_CAT_KW     = ["category","cat","type","tag","group","classification","head","sub"]
_TXNTYPE_KW = ["transaction type","txn type","trans type","type","kind","mode"]
_BAL_KW     = ["balance","bal","closing","running balance","available"]
_ACCT_KW    = ["account","acct","account name","acc","bank","wallet"]
_BUDGET_KW  = ["rent","groceries","food","transport","travel","utilities","electricity",
               "water","internet","phone","mobile","entertainment","healthcare","medical",
               "insurance","education","shopping","clothing","dining","restaurants",
               "subscriptions","savings","investments","misc","miscellaneous","other",
               "fuel","petrol","emi","loan","mortgage"]
_INCOME_KW  = ["income","salary","wages","revenue","earnings","pay","net pay"]

_DS_BANK    = "Bank Statement"
_DS_LEDGER  = "Transaction Ledger"
_DS_BUDGET  = "Budget / Spending Dataset"
_DS_UNKNOWN = "Unknown Dataset"
_CAP_TRACKER  = "tracker_capable"
_CAP_ANALYZER = "analyzer_only"
_CAP_UNKNOWN  = "unknown"


def _dd_norm(s):
    return _re.sub(r"\s+", " ", str(s).lower().strip())

def _dd_best(candidates, keywords):
    nc = {c: _dd_norm(c) for c in candidates}
    for kw in keywords:
        for orig, norm in nc.items():
            if kw in norm:
                return orig
    return None

def _dd_is_numeric(series):
    try:
        pd.to_numeric(series.dropna(), errors="raise")
        return True
    except:
        return False

def _dd_numeric_cols(df):
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) or _dd_is_numeric(df[c])]

def _dd_is_date(series):
    try:
        pd.to_datetime(series.dropna().iloc[:20], infer_datetime_format=True, errors="raise")
        return True
    except:
        return False


def _detect_dataset(df: pd.DataFrame) -> dict:
    """
    Returns a dict with keys:
      dataset_type, capability, confidence, detected_fields, warnings,
      needs_mapping, mapping (dict of field→col)
    """
    cols      = list(df.columns)
    warnings  = []
    detected  = []
    mapping   = {k: None for k in ["date","description","amount","debit","credit",
                                    "category","txn_type","account","balance"]}
    mapping["budget_cols"] = {}

    mapping["date"]        = _dd_best(cols, _DATE_KW)
    mapping["description"] = _dd_best(cols, _DESC_KW)
    mapping["amount"]      = _dd_best(cols, _AMT_KW)
    mapping["debit"]       = _dd_best(cols, _DEBIT_KW)
    mapping["credit"]      = _dd_best(cols, _CREDIT_KW)
    mapping["category"]    = _dd_best(cols, _CAT_KW)
    mapping["txn_type"]    = _dd_best(cols, _TXNTYPE_KW)
    mapping["account"]     = _dd_best(cols, _ACCT_KW)
    mapping["balance"]     = _dd_best(cols, _BAL_KW)

    if mapping["txn_type"] and mapping["category"] and mapping["txn_type"] == mapping["category"]:
        mapping["txn_type"] = None
    if mapping["amount"] and (mapping["amount"] == mapping["debit"] or mapping["amount"] == mapping["credit"]):
        mapping["amount"] = None

    budget_hits = {}
    income_col  = _dd_best(cols, _INCOME_KW)
    for col in cols:
        nc = _dd_norm(col)
        for bkw in _BUDGET_KW:
            if bkw == nc or nc.startswith(bkw):
                budget_hits[bkw] = col
                break

    has_date     = mapping["date"]     is not None
    has_desc     = mapping["description"] is not None
    has_amount   = mapping["amount"]   is not None
    has_debit    = mapping["debit"]    is not None
    has_credit   = mapping["credit"]   is not None
    has_category = mapping["category"] is not None
    has_txntype  = mapping["txn_type"] is not None
    has_balance  = mapping["balance"]  is not None
    has_budget   = len(budget_hits) >= 2

    native_cols = {"Date", "Transaction Type", "Category", "Amount"}
    is_native   = native_cols.issubset(set(cols))

    confidence    = 0.0
    dataset_type  = _DS_UNKNOWN
    capability    = _CAP_UNKNOWN
    needs_mapping = True

    if is_native:
        dataset_type  = _DS_LEDGER
        capability    = _CAP_TRACKER
        confidence    = 1.0
        needs_mapping = False
        detected = ["Date ✓", "Transaction Type ✓", "Category ✓", "Amount ✓",
                    "Account Name" + (" ✓" if "Account Name" in cols else " (auto-filled)")]
        mapping.update({"date": "Date", "txn_type": "Transaction Type",
                        "category": "Category", "amount": "Amount",
                        "account": "Account Name" if "Account Name" in cols else None})

    elif has_date and (has_debit or has_credit) and has_balance:
        dataset_type  = _DS_BANK
        capability    = _CAP_TRACKER
        confidence    = 0.9 if has_desc else 0.75
        needs_mapping = False
        if has_date:    detected.append(f"Date → {mapping['date']}")
        if has_desc:    detected.append(f"Description → {mapping['description']}")
        if has_debit:   detected.append(f"Debit → {mapping['debit']}")
        if has_credit:  detected.append(f"Credit → {mapping['credit']}")
        if has_balance: detected.append(f"Balance → {mapping['balance']}")
        if not has_category:
            warnings.append("No Category column — will be set to 'Uncategorised'.")

    elif has_date and has_amount and (has_txntype or has_category or has_desc):
        dataset_type  = _DS_LEDGER
        capability    = _CAP_TRACKER
        score = sum([has_date, has_amount, has_desc, has_category, has_txntype])
        confidence    = min(0.5 + score * 0.1, 0.95)
        needs_mapping = confidence < 0.8
        if has_date:     detected.append(f"Date → {mapping['date']}")
        if has_desc:     detected.append(f"Description → {mapping['description']}")
        if has_amount:   detected.append(f"Amount → {mapping['amount']}")
        if has_category: detected.append(f"Category → {mapping['category']}")
        if has_txntype:  detected.append(f"Transaction Type → {mapping['txn_type']}")

    elif has_budget or (income_col and len(_dd_numeric_cols(df)) >= 3):
        dataset_type  = _DS_BUDGET
        capability    = _CAP_ANALYZER
        confidence    = 0.85 if has_budget else 0.65
        needs_mapping = False
        mapping["budget_cols"] = budget_hits
        if income_col:
            detected.append(f"Income → {income_col}")
            mapping["credit"] = income_col
        for bk, bc in budget_hits.items():
            detected.append(f"Spending ({bk}) → {bc}")
    else:
        dataset_type  = _DS_UNKNOWN
        capability    = _CAP_UNKNOWN
        confidence    = 0.0
        needs_mapping = True
        detected = [f"{c} ({df[c].dtype})" for c in cols[:12]]

    return dict(dataset_type=dataset_type, capability=capability, confidence=confidence,
                detected_fields=detected, warnings=warnings, needs_mapping=needs_mapping,
                mapping=mapping, income_col=income_col)


def _clean_amount(val) -> float:
    """
    Robustly parse any financial amount value.
    Handles: commas, currency symbols (₹$€£), spaces, dashes, parentheses,
    mixed strings like "₹ 1,23,456.78" or "(500.00)" (negative notation).
    Returns 0.0 if unparseable.
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return abs(float(val)) if not (val != val) else 0.0  # handle NaN
    s = str(val).strip()
    if not s or s in ("-", "--", "N/A", "n/a", "nil", "NIL", ""):
        return 0.0
    # Strip currency symbols and spaces
    s = s.replace("₹", "").replace("$", "").replace("€", "").replace("£", "")
    s = s.replace(",", "").replace(" ", "").strip()
    # Handle parentheses as negative e.g. (500.00) → treat as positive amount
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    # Strip leading minus — we determine sign from column context
    s = s.lstrip("-").strip()
    if not s:
        return 0.0
    try:
        return abs(float(s))
    except (ValueError, TypeError):
        return 0.0


def _standardise_df(df: pd.DataFrame, mapping: dict, dataset_type: str) -> pd.DataFrame:
    """Convert any detected format into the internal FinanceOS format."""
    if dataset_type == _DS_BUDGET:
        return _standardise_budget_df(df, mapping)

    rows = []
    for _, r in df.iterrows():
        raw_date = r.get(mapping["date"], "") if mapping["date"] else ""
        try:
            parsed_date = str(pd.to_datetime(raw_date).date())
        except:
            parsed_date = str(raw_date)[:10]

        note     = str(r.get(mapping["description"], "")) if mapping["description"] else ""
        category = str(r.get(mapping["category"], "Uncategorised")) if mapping["category"] else "Uncategorised"
        if not category or category.lower() in ("nan", "none", ""):
            category = "Uncategorised"
        account  = str(r.get(mapping["account"], "Uploaded")) if mapping["account"] else "Uploaded"

        if mapping["debit"] and mapping["credit"]:
            dv = _clean_amount(r.get(mapping["debit"],  None))
            cv = _clean_amount(r.get(mapping["credit"], None))
            if dv > 0 and cv > 0:
                # Both filled — treat debit as expense, credit as income (two rows)
                rows.append({"Date": parsed_date, "Transaction Type": "debit",
                             "Category": category, "Amount": round(dv, 2),
                             "Account Name": account, "Note": note})
                rows.append({"Date": parsed_date, "Transaction Type": "credit",
                             "Category": category, "Amount": round(cv, 2),
                             "Account Name": account, "Note": note})
                continue
            elif dv > 0:
                txn_type, amount = "debit", dv
            elif cv > 0:
                txn_type, amount = "credit", cv
            else:
                continue  # both zero — skip (blank row)
        elif mapping["amount"]:
            amount = _clean_amount(r.get(mapping["amount"], 0))
            if amount == 0.0:
                continue
            if mapping["txn_type"]:
                rt = str(r.get(mapping["txn_type"], "")).lower().strip()
                if any(k in rt for k in ["credit","cr","income","deposit","received","in"]):
                    txn_type = "credit"
                elif any(k in rt for k in ["debit","dr","expense","withdrawal","paid","out"]):
                    txn_type = "debit"
                else:
                    raw_raw = r.get(mapping["amount"], 0)
                    try:
                        txn_type = "debit" if float(str(raw_raw).replace(",","").replace("₹","").strip()) < 0 else "credit"
                    except:
                        txn_type = "credit"
            else:
                # No txn_type column — use sign of original value
                raw_raw = r.get(mapping["amount"], 0)
                try:
                    orig = float(str(raw_raw).replace(",","").replace("₹","").replace("$","").replace("€","").replace("£","").strip())
                    txn_type = "debit" if orig < 0 else "credit"
                except:
                    txn_type = "credit"
        else:
            continue

        rows.append({"Date": parsed_date, "Transaction Type": txn_type,
                     "Category": category, "Amount": round(amount, 2),
                     "Account Name": account, "Note": note})
    return pd.DataFrame(rows)


def _standardise_budget_df(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    rows = []
    income_col = mapping.get("credit")
    period_col = None
    for c in df.columns:
        nc = _dd_norm(c)
        if any(k in nc for k in ["month","period","year","quarter","date"]):
            period_col = c
            break
    for idx, r in df.iterrows():
        period = str(r.get(period_col, f"Period {idx+1}")) if period_col else f"Period {idx+1}"
        try:
            parsed_date = str(pd.to_datetime(period, infer_datetime_format=True).date())
        except:
            parsed_date = "2024-01-01"
        if income_col:
            try:
                inc = float(r.get(income_col, 0) or 0)
                if inc > 0:
                    rows.append({"Date": parsed_date, "Transaction Type": "credit",
                                 "Category": "Income", "Amount": round(inc, 2),
                                 "Account Name": "Budget Sheet", "Note": f"Income — {period}"})
            except: pass
        for cat_name, col_name in mapping.get("budget_cols", {}).items():
            try:
                amt = float(r.get(col_name, 0) or 0)
                if amt > 0:
                    rows.append({"Date": parsed_date, "Transaction Type": "debit",
                                 "Category": cat_name.title(), "Amount": round(amt, 2),
                                 "Account Name": "Budget Sheet", "Note": f"{col_name} — {period}"})
            except: pass
    return pd.DataFrame(rows)


def _launch_platform(std_df: pd.DataFrame, filename: str, mode: str):
    """Clear old data, import standardised df, navigate to platform."""
    # Enrich before import so Month Name / Month Key / Year are present
    # from the first get_df() call
    if not std_df.empty:
        std_df = std_df.copy()
        std_df["Transaction Type"] = std_df["Transaction Type"].astype(str).str.strip().str.lower()
        try:
            std_df["Date"] = pd.to_datetime(std_df["Date"], errors="coerce")
            std_df = std_df.dropna(subset=["Date"])
            std_df["Month Name"] = std_df["Date"].dt.month_name()
            std_df["Month Key"]  = std_df["Date"].dt.to_period("M").astype(str)
            std_df["Year"]       = std_df["Date"].dt.year.astype(str)
            std_df["Date"]       = std_df["Date"].dt.strftime("%Y-%m-%d")
            std_df["Amount"]     = pd.to_numeric(std_df["Amount"], errors="coerce").fillna(0)
        except Exception:
            pass
    db_clear_txns()
    invalidate_cache()
    db_import_txns(None, std_df)
    st.session_state["uploaded_filename"]  = filename
    st.session_state["uploaded_row_count"] = len(std_df)
    nav_section = "tracker" if mode == "tracker" else "analyzer"
    nav_pg      = "overview" if mode == "tracker" else "insights"
    st.session_state.mode = mode
    go("platform", nav_section=nav_section, nav_page=nav_pg)


# ── Confidence badge helper ───────────────────────────────────────
def _confidence_badge(pct: float) -> str:
    if pct >= 0.85:
        color, label = "#065f46", "HIGH"
        bg = "#F0FDF4"; border = "#6EE7B7"
    elif pct >= 0.65:
        color, label = "#92400e", "MEDIUM"
        bg = "#FFFBEB"; border = "#FCD34D"
    else:
        color, label = "#991b1b", "LOW"
        bg = "#FEF2F2"; border = "#FCA5A5"
    return (f'<span style="background:{bg};border:2px solid {border};border-radius:20px;'
            f'padding:2px 10px;font-size:.72rem;font-weight:900;color:{color};">'
            f'{label} ({pct*100:.0f}%)</span>')


# ── Dataset type badge ────────────────────────────────────────────
def _type_badge(ds_type: str) -> str:
    icons = {
        _DS_BANK:    ("🏦", "#1d4ed8", "#EFF6FF", "#93C5FD"),
        _DS_LEDGER:  ("📒", "#065f46", "#F0FDF4", "#6EE7B7"),
        _DS_BUDGET:  ("📊", "#7c3aed", "#F5F3FF", "#C4B5FD"),
        _DS_UNKNOWN: ("❓", "#6b7280", "#F9FAFB", "#D1D5DB"),
    }
    icon, color, bg, border = icons.get(ds_type, icons[_DS_UNKNOWN])
    return (f'<span style="background:{bg};border:2px solid {border};border-radius:20px;'
            f'padding:4px 14px;font-size:.85rem;font-weight:900;color:{color};">'
            f'{icon} {ds_type}</span>')


def page_upload():
    """Upload gate with automatic dataset detection, classification, mapping, and standardization."""
    st.markdown("""<style>
    html, body, .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stAppViewBlockContainer"], .main {
        background: linear-gradient(150deg,#FFF0F9 0%,#EFF6FF 50%,#F0FDF4 100%) !important;
    }
    .block-container {
        padding: 2rem 1rem !important; max-width: 820px !important;
        margin: 0 auto !important;
    }
    [data-testid="stSidebar"] { display: none !important; }
    @keyframes fadeInUp {
        from { opacity:0; transform:translateY(20px); }
        to   { opacity:1; transform:translateY(0); }
    }
    /* ── Dark labels for ALL widgets on upload page ── */
    .stSelectbox > label,
    .stSelectbox > label > div,
    .stSelectbox > label > div > p,
    .stFileUploader > label,
    .stFileUploader > label > div,
    .stFileUploader > label > div > p,
    div[data-testid="stSelectbox"] > label,
    div[data-testid="stSelectbox"] > label > div,
    div[data-testid="stSelectbox"] > label > div > p,
    div[data-testid="stWidgetLabel"],
    div[data-testid="stWidgetLabel"] p,
    div[data-testid="stWidgetLabel"] span {
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        font-weight: 800 !important;
        font-size: .88rem !important;
        opacity: 1 !important;
        visibility: visible !important;
    }
    </style>""", unsafe_allow_html=True)

    # ── Logo / Hero ───────────────────────────────────────────────
    st.markdown("""
    <div style="text-align:center;margin-bottom:2rem;animation:fadeInUp .5s ease;">
        <div style="font-size:3.5rem;line-height:1;">💸</div>
        <div style="font-size:2.6rem;font-weight:900;line-height:1.1;
            background:linear-gradient(90deg,#be185d,#7c3aed);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
            FinanceOS</div>
        <div style="color:#9d174d;font-weight:700;font-size:.88rem;margin-top:6px;
            letter-spacing:.1em;">TRACK · ANALYSE · GROW</div>
        <div style="color:#6b7280;font-size:.82rem;font-weight:600;margin-top:.4rem;">
            Upload any financial file — FinanceOS will detect and adapt to your data automatically.</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Upload card ───────────────────────────────────────────────
    st.markdown("""
    <div style="background:#FFFFFF;border:3px solid #93C5FD;border-radius:28px;
        padding:28px 36px 20px;box-shadow:0 24px 64px rgba(147,197,253,.22);
        animation:fadeInUp .5s ease .1s both;margin-bottom:1.2rem;">
        <div style="text-align:center;margin-bottom:1rem;">
            <div style="font-size:2.2rem;line-height:1;">📊</div>
            <div style="font-size:1.35rem;font-weight:900;color:#1d4ed8;margin-top:.5rem;">
                Import Your Finance Data</div>
            <div style="color:#6b7280;font-weight:700;font-size:.85rem;margin-top:.3rem;">
                Supports: Bank Statements · Transaction Ledgers · Budget Sheets · Any Excel format
            </div>
        </div>
        <div style="background:#EFF6FF;border:2px dashed #93C5FD;border-radius:12px;
            padding:10px 16px;font-weight:700;color:#1e40af;font-size:.82rem;">
            🔒 Your data is never stored — full privacy, every time.
        </div>
    </div>
    """, unsafe_allow_html=True)

    upload_file = st.file_uploader(
        "Upload Excel file (.xlsx)", type=["xlsx"], key="session_upload_file"
    )

    if not upload_file:
        st.markdown("""
        <div style="background:#FFF0F9;border:2.5px dashed #F9A8D4;border-radius:16px;
            padding:28px;text-align:center;margin-top:.5rem;">
            <div style="font-size:2.2rem;">📂</div>
            <div style="font-weight:800;color:#9d174d;margin-top:.5rem;font-size:.95rem;">
                No file uploaded yet</div>
            <div style="color:#6b7280;font-weight:700;font-size:.82rem;margin-top:.3rem;">
                Upload any Excel file — FinanceOS will automatically detect its format.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    # ── Read file ─────────────────────────────────────────────────
    try:
        raw_df = pd.read_excel(upload_file)
        raw_df.columns = raw_df.columns.str.strip()
    except Exception as e:
        st.error(f"❌ Could not read file: {e}")
        return

    if raw_df.empty:
        st.error("❌ The uploaded file is empty.")
        return

    # ── Auto-detect bad header row ─────────────────────────────
    # If >40% of columns are "Unnamed: N", the real headers are
    # likely in row 1 (0-indexed). Re-read with header=1.
    skipped_header = False
    unnamed_count = sum(1 for c in raw_df.columns if str(c).startswith("Unnamed:"))
    if unnamed_count / max(len(raw_df.columns), 1) > 0.4:
        try:
            upload_file.seek(0)
            raw_df2 = pd.read_excel(upload_file, header=1)
            raw_df2.columns = raw_df2.columns.str.strip()
            # Only use it if we got fewer Unnamed cols
            unnamed2 = sum(1 for c in raw_df2.columns if str(c).startswith("Unnamed:"))
            if unnamed2 < unnamed_count:
                raw_df = raw_df2
                skipped_header = True
        except Exception:
            pass  # fall back to original read

    if skipped_header:
        st.info("ℹ️ Detected a merged/title header row — automatically skipped to row 2 for column names.")

    # ══════════════════════════════════════════════════════════════
    #  STEP 1 — DATASET DETECTION
    # ══════════════════════════════════════════════════════════════
    result = _detect_dataset(raw_df)
    ds_type    = result["dataset_type"]
    capability = result["capability"]
    confidence = result["confidence"]
    detected   = result["detected_fields"]
    warnings   = result["warnings"]
    mapping    = result["mapping"]
    needs_map  = result["needs_mapping"]

    # ── Dataset Summary card ──────────────────────────────────────
    num_cols = len(raw_df.columns)
    num_rows = len(raw_df)
    cols_preview = " · ".join(str(c) for c in raw_df.columns[:8])
    if len(raw_df.columns) > 8:
        cols_preview += f" … +{len(raw_df.columns)-8} more"

    st.markdown(f"""
    <div style="background:#FFFFFF;border:3px solid #C4B5FD;border-radius:22px;
        padding:22px 28px;margin-bottom:1rem;box-shadow:0 8px 28px rgba(196,181,253,.18);">
        <div style="font-weight:900;color:#7c3aed;font-size:1rem;margin-bottom:14px;
            letter-spacing:.06em;text-transform:uppercase;">📋 Dataset Summary</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px;">
            <div style="background:#F5F3FF;border:2px solid #C4B5FD;border-radius:12px;
                padding:12px 16px;">
                <div style="font-size:.68rem;font-weight:800;color:#7c3aed;text-transform:uppercase;
                    letter-spacing:.08em;margin-bottom:4px;">Rows</div>
                <div style="font-size:1.5rem;font-weight:900;color:#4c1d95;">{num_rows:,}</div>
            </div>
            <div style="background:#F5F3FF;border:2px solid #C4B5FD;border-radius:12px;
                padding:12px 16px;">
                <div style="font-size:.68rem;font-weight:800;color:#7c3aed;text-transform:uppercase;
                    letter-spacing:.08em;margin-bottom:4px;">Columns</div>
                <div style="font-size:1.5rem;font-weight:900;color:#4c1d95;">{num_cols}</div>
            </div>
        </div>
        <div style="background:#F9FAFB;border:1.5px solid #E5E7EB;border-radius:10px;
            padding:10px 14px;font-size:.8rem;font-weight:700;color:#374151;margin-bottom:12px;">
            <b style="color:#6b7280;">Columns detected:</b> {cols_preview}
        </div>
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
            <span style="font-size:.8rem;font-weight:700;color:#6b7280;">Dataset Type:</span>
            {_type_badge(ds_type)}
            <span style="font-size:.8rem;font-weight:700;color:#6b7280;margin-left:6px;">Detection Confidence:</span>
            {_confidence_badge(confidence)}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════
    #  STEP 2 — CLASSIFICATION RESULT
    # ══════════════════════════════════════════════════════════════
    if ds_type == _DS_BANK:
        st.markdown("""
        <div style="background:#EFF6FF;border:2.5px solid #93C5FD;border-radius:16px;
            padding:16px 20px;margin-bottom:1rem;">
            <div style="font-weight:900;color:#1d4ed8;font-size:.95rem;margin-bottom:6px;">
                🏦 Bank Statement Detected</div>
            <div style="font-size:.85rem;color:#1e40af;font-weight:700;">
                Found separate Debit / Credit / Balance columns. FinanceOS will auto-map this format.</div>
        </div>""", unsafe_allow_html=True)

    elif ds_type == _DS_LEDGER:
        st.markdown("""
        <div style="background:#F0FDF4;border:2.5px solid #6EE7B7;border-radius:16px;
            padding:16px 20px;margin-bottom:1rem;">
            <div style="font-weight:900;color:#065f46;font-size:.95rem;margin-bottom:6px;">
                📒 Transaction Ledger Detected</div>
            <div style="font-size:.85rem;color:#047857;font-weight:700;">
                Found Date, Amount, and transaction detail columns. Compatible with Tracker + Analyzer.</div>
        </div>""", unsafe_allow_html=True)

    elif ds_type == _DS_BUDGET:
        st.markdown("""
        <div style="background:#F5F3FF;border:2.5px solid #C4B5FD;border-radius:16px;
            padding:16px 20px;margin-bottom:1rem;">
            <div style="font-weight:900;color:#5b21b6;font-size:.95rem;margin-bottom:6px;">
                📊 Budget / Spending Dataset Detected</div>
            <div style="font-size:.85rem;color:#6d28d9;font-weight:700;">
                This dataset is suitable for financial analysis but not transaction tracking.</div>
            <div style="margin-top:8px;background:#EDE9FE;border-radius:8px;padding:8px 12px;
                font-size:.8rem;font-weight:700;color:#7c3aed;">
                ℹ️ Tracker mode will be disabled. Only Analyzer mode is available for this dataset.</div>
        </div>""", unsafe_allow_html=True)

    elif ds_type == _DS_UNKNOWN:
        st.markdown("""
        <div style="background:#FEF2F2;border:2.5px solid #FCA5A5;border-radius:16px;
            padding:16px 20px;margin-bottom:1rem;">
            <div style="font-weight:900;color:#991b1b;font-size:.95rem;margin-bottom:6px;">
                ❓ Dataset Structure Not Recognized</div>
            <div style="font-size:.85rem;color:#b91c1c;font-weight:700;">
                FinanceOS could not automatically classify this dataset. Please map columns manually below.</div>
        </div>""", unsafe_allow_html=True)

    # Detected fields
    if detected:
        fields_html = "".join(
            f'<span style="background:#F0FDF4;border:1.5px solid #6EE7B7;border-radius:20px;'
            f'padding:3px 10px;font-size:.75rem;font-weight:800;color:#065f46;'
            f'margin:2px 3px 2px 0;display:inline-block;">{f}</span>'
            for f in detected
        )
        st.markdown(f"""
        <div style="background:#FFFFFF;border:2px solid #E5E7EB;border-radius:14px;
            padding:14px 18px;margin-bottom:1rem;">
            <div style="font-size:.75rem;font-weight:900;color:#6b7280;text-transform:uppercase;
                letter-spacing:.08em;margin-bottom:8px;">Detected Fields</div>
            <div style="display:flex;flex-wrap:wrap;">{fields_html}</div>
        </div>
        """, unsafe_allow_html=True)

    # Warnings
    for w in warnings:
        st.warning(f"⚠️ {w}")

    # Preview
    with st.expander("👀 Preview uploaded data (first 8 rows)", expanded=False):
        st.dataframe(raw_df.head(8), use_container_width=True)

    # ══════════════════════════════════════════════════════════════
    #  STEP 3 — COLUMN MAPPING (only if needed)
    # ══════════════════════════════════════════════════════════════
    col_options = ["(none)"] + list(raw_df.columns)

    if needs_map or ds_type == _DS_UNKNOWN:
        st.markdown("""
        <div style="background:#FFFBEB;border:2.5px solid #FCD34D;border-radius:16px;
            padding:16px 20px;margin-bottom:1rem;">
            <div style="font-weight:900;color:#92400e;font-size:.95rem;margin-bottom:4px;">
                🗺️ Column Mapping Required</div>
            <div style="font-size:.84rem;color:#78350f;font-weight:700;">
                Help FinanceOS understand your data by mapping columns below.
                Fields left as (none) will be skipped or filled with defaults.</div>
        </div>""", unsafe_allow_html=True)

        def _col_idx(detected_col):
            if detected_col and detected_col in raw_df.columns:
                return col_options.index(detected_col)
            return 0

        # Force-inject label colour right before the dropdowns
        st.markdown("""<style>
        div[data-testid="stWidgetLabel"] p,
        div[data-testid="stWidgetLabel"] span,
        div[data-testid="stWidgetLabel"],
        .stSelectbox label p,
        .stSelectbox label span,
        .stSelectbox label {
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            font-weight: 800 !important;
            opacity: 1 !important;
        }
        </style>""", unsafe_allow_html=True)
        mc1, mc2 = st.columns(2)
        with mc1:
            m_date  = st.selectbox("📅 Date Column",        col_options, index=_col_idx(mapping["date"]),        key="map_date")
            m_desc  = st.selectbox("📝 Description Column", col_options, index=_col_idx(mapping["description"]), key="map_desc")
            m_amt   = st.selectbox("💰 Amount Column",       col_options, index=_col_idx(mapping["amount"]),      key="map_amt")
            m_inc   = st.selectbox("💚 Income Column",       col_options, index=_col_idx(mapping["credit"]),      key="map_inc")
        with mc2:
            m_debit = st.selectbox("📤 Debit Column",        col_options, index=_col_idx(mapping["debit"]),       key="map_debit")
            m_cred  = st.selectbox("📥 Credit Column",       col_options, index=_col_idx(mapping["credit"]),      key="map_cred")
            m_cat   = st.selectbox("🏷️ Category Column",     col_options, index=_col_idx(mapping["category"]),    key="map_cat")
            m_txntp = st.selectbox("🔄 Transaction Type Col",col_options, index=_col_idx(mapping["txn_type"]),    key="map_txntp")

        # Apply manual mapping overrides
        def _none(v): return None if v == "(none)" else v
        mapping["date"]        = _none(m_date)
        mapping["description"] = _none(m_desc)
        mapping["amount"]      = _none(m_amt)
        mapping["debit"]       = _none(m_debit)
        mapping["credit"]      = _none(m_cred) or _none(m_inc)
        mapping["category"]    = _none(m_cat)
        mapping["txn_type"]    = _none(m_txntp)

    # ══════════════════════════════════════════════════════════════
    #  STEP 4 — MODE SELECTION + LAUNCH
    # ══════════════════════════════════════════════════════════════
    st.markdown("<hr style='border-color:#E5E7EB;margin:1.2rem 0;'>", unsafe_allow_html=True)
    st.markdown("**How would you like to use FinanceOS this session?**")

    is_analyzer_only = (capability == _CAP_ANALYZER)

    if is_analyzer_only:
        st.info("📊 This dataset supports **Analyzer Only** mode — transaction tracking is not available.")
        if st.button("📊 Launch Analyzer", use_container_width=True, type="primary", key="upload_analyzer_only"):
            try:
                std_df = _standardise_df(raw_df, mapping, ds_type)
                if std_df.empty:
                    st.error("❌ Standardisation produced 0 rows. Check column mapping above.")
                else:
                    _launch_platform(std_df, upload_file.name, "analyzer")
            except Exception as e:
                st.error(f"❌ Error during standardisation: {e}")
                st.exception(e)

    else:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("📝 Tracker + Analyzer", use_container_width=True,
                         type="primary", key="upload_tracker"):
                try:
                    std_df = _standardise_df(raw_df, mapping, ds_type)
                    if std_df.empty:
                        st.error("❌ Standardisation produced 0 rows. Check column mapping above.")
                    else:
                        _launch_platform(std_df, upload_file.name, "tracker")
                except Exception as e:
                    st.error(f"❌ Error during standardisation: {e}")
                    st.exception(e)
        with c2:
            if st.button("📊 Analyzer Only", use_container_width=True, key="upload_analyzer"):
                try:
                    std_df = _standardise_df(raw_df, mapping, ds_type)
                    if std_df.empty:
                        st.error("❌ Standardisation produced 0 rows. Check column mapping above.")
                    else:
                        _launch_platform(std_df, upload_file.name, "analyzer")
                except Exception as e:
                    st.error(f"❌ Error during standardisation: {e}")
                    st.exception(e)



# ══════════════════════════════════════════════════════════════════
#  ANALYZER PAGES  (Analyzer mode only — strictly guarded by router)
# ══════════════════════════════════════════════════════════════════

def _build_commentary(df) -> list:
    """Generate smart financial insight commentary from transaction data."""
    commentary = []
    if df.empty:
        return commentary

    try:
        debits = df[df["Transaction Type"] == "debit"]
        credits = df[df["Transaction Type"] == "credit"]

        # Top spending category
        if not debits.empty:
            top_cat = debits.groupby("Category")["Amount"].sum().idxmax()
            top_amt = debits.groupby("Category")["Amount"].sum().max()
            commentary.append({
                "icon": "🛍️",
                "text": f"<b>{top_cat}</b> is your highest expense category, accounting for ₹{top_amt:,.0f} in total spending.",
                "tag": "TOP CATEGORY", "type": "warn"
            })

        # Monthly spending trend (last 2 months)
        if "Month Name" in df.columns and "Month Key" in df.columns:
            monthly = debits.groupby("Month Key")["Amount"].sum().sort_index()
            if len(monthly) >= 2:
                last_two = monthly.iloc[-2:]
                prev_amt, cur_amt = last_two.iloc[0], last_two.iloc[1]
                if prev_amt > 0:
                    pct_change = ((cur_amt - prev_amt) / prev_amt) * 100
                    if abs(pct_change) > 5:
                        direction = "increased" if pct_change > 0 else "decreased"
                        tag_type  = "down" if pct_change > 0 else "up"
                        tag_label = f"↑ {abs(pct_change):.0f}%" if pct_change > 0 else f"↓ {abs(pct_change):.0f}%"
                        commentary.append({
                            "icon": "📈" if pct_change > 0 else "📉",
                            "text": f"Your spending <b>{direction} by {abs(pct_change):.0f}%</b> compared to the previous month.",
                            "tag": tag_label, "type": tag_type
                        })

        # Savings comparison
        if "Month Key" in df.columns:
            monthly_inc  = credits.groupby("Month Key")["Amount"].sum()
            monthly_exp  = debits.groupby("Month Key")["Amount"].sum()
            monthly_net  = monthly_inc.subtract(monthly_exp, fill_value=0).sort_index()
            if len(monthly_net) >= 2:
                prev_sav, cur_sav = monthly_net.iloc[-2], monthly_net.iloc[-1]
                diff = cur_sav - prev_sav
                if diff > 0:
                    commentary.append({
                        "icon": "💚",
                        "text": f"You saved <b>₹{diff:,.0f} more</b> than the previous month. Great financial discipline!",
                        "tag": "SAVINGS UP", "type": "up"
                    })
                elif diff < 0:
                    commentary.append({
                        "icon": "⚠️",
                        "text": f"Your savings <b>dropped by ₹{abs(diff):,.0f}</b> compared to last month. Consider reviewing discretionary spending.",
                        "tag": "SAVINGS DOWN", "type": "down"
                    })

        # Savings rate assessment
        total_inc = credits["Amount"].sum() if not credits.empty else 0
        total_exp = debits["Amount"].sum()  if not debits.empty  else 0
        if total_inc > 0:
            sav_rate = ((total_inc - total_exp) / total_inc) * 100
            if sav_rate >= 20:
                commentary.append({
                    "icon": "🏆",
                    "text": f"Your overall savings rate is <b>{sav_rate:.1f}%</b> — above the recommended 20% threshold. Excellent!",
                    "tag": "HEALTHY RATE", "type": "up"
                })
            elif sav_rate < 10:
                commentary.append({
                    "icon": "🔔",
                    "text": f"Your savings rate is <b>{sav_rate:.1f}%</b>. Financial experts recommend saving at least 20% of your income.",
                    "tag": "LOW SAVINGS", "type": "warn"
                })

        # Account diversity
        if "Account Name" in df.columns:
            acct_count = df["Account Name"].nunique()
            if acct_count >= 3:
                commentary.append({
                    "icon": "🏦",
                    "text": f"You're managing transactions across <b>{acct_count} accounts</b>. Consolidated tracking gives you full visibility.",
                    "tag": "MULTI-ACCOUNT", "type": "info"
                })

    except Exception:
        pass
    return commentary


def pf_analytics():
    page_header("📈 Analytics", "Analyzer › Analytics")
    df = get_df()
    if df.empty:
        empty_state("📊", "No data to analyse",
                    "Upload a file to get started, or add transactions from Tracker.")
        return

    c1, c2 = st.columns(2)
    with c1:
        view = st.selectbox("View By", ["Monthly", "Yearly"], key="an_view")
    with c2:
        if view == "Monthly":
            months = sorted(df["Month Name"].dropna().unique().tolist())
            sel = st.selectbox("Select Month", ["All"] + months, key="an_month")
            cdf = df if sel == "All" else df[df["Month Name"] == sel]
        else:
            years = sorted(df["Year"].dropna().unique().tolist())
            # Normalise years to strings for display; compare as same type
            years_str = [str(y) for y in years]
            sel = st.selectbox("Select Year", ["All"] + years_str, key="an_year")
            if sel == "All":
                cdf = df
            else:
                # Match regardless of whether Year col is int or str
                cdf = df[df["Year"].astype(str) == sel]

    # Normalise Transaction Type for ALL downstream calls
    if not df.empty and "Transaction Type" in df.columns:
        df = df.copy()
        df["Transaction Type"] = df["Transaction Type"].astype(str).str.strip().str.lower()
    if not cdf.empty and "Transaction Type" in cdf.columns:
        cdf = cdf.copy()
        cdf["Transaction Type"] = cdf["Transaction Type"].astype(str).str.strip().str.lower()
    else:
        cdf = df.copy() if sel == "All" else cdf

    payload = analyzer_engine.build_analytics_payload(cdf)
    sr = payload["kpis"]

    # ── LEAD with behavioral intelligence, not raw numbers ────────
    behavioral = generate_behavioral_analysis(df)
    commentary = _build_commentary(df)
    all_insights = behavioral + [c for c in commentary if c not in behavioral]
    if all_insights:
        az_section("🧠 What Your Data Is Telling You")
        cards_html = "".join(
            az_insight(c["icon"], c["text"], c["tag"], c["type"])
            for c in all_insights[:5]
        )
        st.markdown(cards_html, unsafe_allow_html=True)
        st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)

    # ── Raw KPI numbers go BELOW interpretation ────────────────────
    az_section("📊 Period Breakdown")
    st.markdown(f"""<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:18px;margin:.8rem 0 1.5rem;">
        {az_kpi("💰 Total Income",  f"₹{sr['income']:,.0f}",  "Selected period")}
        {az_kpi("💸 Total Expense", f"₹{sr['expenses']:,.0f}", "Selected period")}
        {az_kpi("🏦 Net Savings",   f'₹{sr["net"]:,.0f}',     f'{sr["direction"]} vs average')}
        {az_kpi("📊 Savings Rate",  f"{sr['savings_pct']:.1f}%", "Income retained")}
    </div>""", unsafe_allow_html=True)

    # ── Charts ─────────────────────────────────────────────────────
    figs = payload["figures"]
    st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)
    az_section("🛍️ Top Expense Categories")
    if "bar_categories" in figs:
        st.plotly_chart(figs["bar_categories"], use_container_width=True,
                        config={"displayModeBar": False})
    if "pie_distribution" in figs:
        st.plotly_chart(figs["pie_distribution"], use_container_width=True,
                        config={"displayModeBar": False})

    az_section("📈 Monthly Expense Trend")
    if "line_trend" in figs:
        st.plotly_chart(figs["line_trend"], use_container_width=True,
                        config={"displayModeBar": False})


def pf_insights():
    """
    Financial Intelligence Engine — the core interpretation layer.
    Answers: What does it mean?  (not just: what happened?)
    """
    page_header("💡 Financial Intelligence", "Analyzer › Intelligence Engine")
    df = get_df()
    if df.empty:
        empty_state("💡", "No data yet", "Add transactions or import an Excel file.")
        return

    if "Transaction Type" in df.columns:
        df = df.copy()
        df["Transaction Type"] = df["Transaction Type"].astype(str).str.strip().str.lower()

    # ══ HERO BANNER ══════════════════════════════════════════════
    st.markdown("""
    <div style="background:linear-gradient(135deg,rgba(59,130,246,.15),rgba(99,102,241,.15),rgba(139,92,246,.1));
        border:1.5px solid rgba(99,102,241,.4);border-radius:20px;padding:20px 28px;
        margin-bottom:1.8rem;display:flex;align-items:center;gap:16px;">
        <div style="font-size:2.8rem;">🧠</div>
        <div>
            <div style="font-size:.72rem;font-weight:900;letter-spacing:.14em;text-transform:uppercase;
                color:#6366f1;margin-bottom:4px;">FINANCIAL INTELLIGENCE ENGINE</div>
            <div style="font-size:1.2rem;font-weight:800;color:#f0f9ff;font-family:Inter,sans-serif;">
                Interpreting your financial behavior — not just showing numbers</div>
            <div style="color:#64748b;font-size:.88rem;font-weight:600;margin-top:4px;">
                Behavioral patterns · Personality profile · Predictions · Coaching
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

    # ══ TAB LAYOUT ════════════════════════════════════════════════
    tab1, tab2, tab3, tab4 = st.tabs([
        "🧠 Behavioral Analysis",
        "🎭 Financial Personality",
        "🔮 Predictions",
        "💡 Recommendations",
    ])

    # ── TAB 1: BEHAVIORAL ANALYSIS ────────────────────────────────
    with tab1:
        az_section("🧠 Behavioral Pattern Analysis")
        st.markdown("""<div style="color:#64748b;font-size:.88rem;font-weight:600;
            margin-bottom:1.2rem;padding:10px 14px;background:rgba(99,102,241,.06);
            border-radius:10px;border-left:3px solid #6366f1;">
            Interpreting <i>why</i> and <i>when</i> you spend — not just how much.
        </div>""", unsafe_allow_html=True)

        behavioral = generate_behavioral_analysis(df)
        if behavioral:
            for b in behavioral:
                st.markdown(az_insight(b["icon"], b["text"], b["tag"], b["type"]),
                            unsafe_allow_html=True)
        else:
            st.markdown(az_insight(
                "💡",
                "Add more varied transactions across multiple months to unlock deep behavioral analysis.",
                "MORE DATA NEEDED", "info"
            ), unsafe_allow_html=True)

        # Supplement with the original commentary for extra coverage
        st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)
        az_section("📊 Additional Financial Observations")
        commentary = _build_commentary(df)
        if commentary:
            for c in commentary:
                st.markdown(az_insight(c["icon"], c["text"], c["tag"], c["type"]),
                            unsafe_allow_html=True)

    # ── TAB 2: FINANCIAL PERSONALITY ─────────────────────────────
    with tab2:
        az_section("🎭 Your Financial Personality")
        st.markdown("""<div style="color:#64748b;font-size:.88rem;font-weight:600;
            margin-bottom:1.2rem;padding:10px 14px;background:rgba(99,102,241,.06);
            border-radius:10px;border-left:3px solid #6366f1;">
            Dynamically classified from your transaction patterns, savings rate,
            and spending behavior — not a static quiz.
        </div>""", unsafe_allow_html=True)

        profile = detect_financial_personality(df)
        st.markdown(render_personality_card(profile), unsafe_allow_html=True)

        # Personality signal badges
        if "signals" in profile:
            sig = profile["signals"]
            st.markdown(f"""
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:1rem;">
                <div style="background:rgba(30,41,59,.8);border:1px solid rgba(99,102,241,.3);
                    border-radius:14px;padding:14px;text-align:center;">
                    <div style="font-size:.68rem;color:#64748b;font-weight:700;text-transform:uppercase;
                        letter-spacing:.08em;margin-bottom:6px;">Savings Rate</div>
                    <div style="font-size:1.5rem;font-weight:900;color:#a5b4fc;
                        font-family:Inter,sans-serif;">{sig['savings_rate']:.1f}%</div>
                </div>
                <div style="background:rgba(30,41,59,.8);border:1px solid rgba(99,102,241,.3);
                    border-radius:14px;padding:14px;text-align:center;">
                    <div style="font-size:.68rem;color:#64748b;font-weight:700;text-transform:uppercase;
                        letter-spacing:.08em;margin-bottom:6px;">Saving Months</div>
                    <div style="font-size:1.5rem;font-weight:900;color:#a5b4fc;
                        font-family:Inter,sans-serif;">{sig['consistency']:.0f}%</div>
                </div>
                <div style="background:rgba(30,41,59,.8);border:1px solid rgba(99,102,241,.3);
                    border-radius:14px;padding:14px;text-align:center;">
                    <div style="font-size:.68rem;color:#64748b;font-weight:700;text-transform:uppercase;
                        letter-spacing:.08em;margin-bottom:6px;">Lifestyle Spend</div>
                    <div style="font-size:1.5rem;font-weight:900;color:#a5b4fc;
                        font-family:Inter,sans-serif;">{sig['lifestyle_pct']:.1f}%</div>
                </div>
                <div style="background:rgba(30,41,59,.8);border:1px solid rgba(99,102,241,.3);
                    border-radius:14px;padding:14px;text-align:center;">
                    <div style="font-size:.68rem;color:#64748b;font-weight:700;text-transform:uppercase;
                        letter-spacing:.08em;margin-bottom:6px;">Monthly Growth</div>
                    <div style="font-size:1.5rem;font-weight:900;color:#a5b4fc;
                        font-family:Inter,sans-serif;">{sig['growth_rate']:+.1f}%</div>
                </div>
            </div>""", unsafe_allow_html=True)

        # All personality profiles reference (collapsed style)
        st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
        az_section("📖 All Financial Personality Types")
        cols = st.columns(3)
        for i, (pname, pdata) in enumerate(PERSONALITY_PROFILES.items()):
            is_current   = (pname == profile["name"])
            bg_style     = f"linear-gradient(135deg,{pdata['bg']},rgba(15,23,42,.9))" if is_current else "rgba(30,41,59,.5)"
            border_style = f"2px solid {pdata['border']}" if is_current else "1px solid rgba(99,102,241,.15)"
            shadow_style = f"box-shadow:0 0 20px {pdata['border']};" if is_current else ""
            name_color   = "#f0f9ff" if is_current else "#64748b"
            desc_color   = "#cbd5e1" if is_current else "#475569"
            you_badge    = (f'<span style="font-size:.62rem;background:{pdata["color"]};color:#fff;border-radius:20px;padding:1px 7px;font-weight:800;margin-left:4px;">YOU</span>') if is_current else ""
            desc_text    = pdata['description'][:80]
            emoji        = pdata['emoji']
            # Single-line HTML — no indented newlines that Markdown would treat as code blocks
            html = (
                f'<div style="background:{bg_style};border:{border_style};border-radius:14px;padding:14px 16px;margin-bottom:10px;{shadow_style}">'
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">'
                f'<span style="font-size:1.4rem;">{emoji}</span>'
                f'<div style="font-size:.85rem;font-weight:900;color:{name_color};font-family:Inter,sans-serif;">{pname}</div>'
                f'{you_badge}'
                f'</div>'
                f'<div style="font-size:.77rem;color:{desc_color};font-weight:600;line-height:1.5;">{desc_text}…</div>'
                f'</div>'
            )
            with cols[i % 3]:
                st.markdown(html, unsafe_allow_html=True)

    # ── TAB 3: PREDICTIONS ────────────────────────────────────────
    with tab3:
        az_section("🔮 Predictive Financial Intelligence")
        st.markdown("""<div style="color:#64748b;font-size:.88rem;font-weight:600;
            margin-bottom:1.2rem;padding:10px 14px;background:rgba(99,102,241,.06);
            border-radius:10px;border-left:3px solid #6366f1;">
            Forward-looking insights derived from your spending trajectory,
            growth rates, and monthly patterns.
        </div>""", unsafe_allow_html=True)

        predictions = generate_predictive_insights(df)
        if predictions:
            for p in predictions:
                confidence_badge = f"""<span style="font-size:.65rem;font-weight:800;
                    background:rgba(99,102,241,.15);color:#a5b4fc;border-radius:20px;
                    padding:2px 8px;margin-left:8px;border:1px solid rgba(165,180,252,.25);">
                    {p.get('confidence','Medium')} Confidence</span>"""
                full_text = p["text"] + confidence_badge
                st.markdown(az_insight(p["icon"], full_text, p["tag"], p["type"]),
                            unsafe_allow_html=True)
        else:
            st.markdown(az_insight(
                "🔮",
                "Predictive insights require at least 2–3 months of transaction data to identify trends.",
                "MORE DATA NEEDED", "info"
            ), unsafe_allow_html=True)

        # Prediction disclaimer
        st.markdown("""<div style="margin-top:1.5rem;background:rgba(15,23,42,.8);
            border:1px solid rgba(99,102,241,.15);border-radius:12px;
            padding:12px 16px;font-size:.78rem;color:#475569;font-weight:600;">
            ⚠️ <b style="color:#64748b;">Disclaimer:</b> Predictions are generated from historical patterns
            in your data. They are directional insights, not guarantees. Always consult a certified
            financial advisor for major financial decisions.
        </div>""", unsafe_allow_html=True)

    # ── TAB 4: RECOMMENDATIONS ────────────────────────────────────
    with tab4:
        az_section("💡 Smart Financial Coaching")
        st.markdown("""<div style="color:#64748b;font-size:.88rem;font-weight:600;
            margin-bottom:1.2rem;padding:10px 14px;background:rgba(99,102,241,.06);
            border-radius:10px;border-left:3px solid #6366f1;">
            Personalized coaching derived from your specific financial patterns —
            like a financial advisor who knows your data.
        </div>""", unsafe_allow_html=True)

        recs = generate_financial_recommendations(df)
        if recs:
            # Sort: high first
            priority_order = {"high": 0, "medium": 1, "low": 2}
            recs.sort(key=lambda r: priority_order.get(r["priority"], 1))
            for rec in recs:
                st.markdown(render_recommendation_card(rec), unsafe_allow_html=True)
        else:
            st.markdown(az_insight(
                "💡",
                "Add more data to generate personalized coaching recommendations.",
                "MORE DATA NEEDED", "info"
            ), unsafe_allow_html=True)


def pf_health():
    page_header("🏥 Financial Health", "Analyzer › Health Score")
    df = get_df()
    if df.empty:
        empty_state("🏥", "No data yet", "Add some transactions to see your health score.")
        return

    if not df.empty and "Transaction Type" in df.columns:
        df = df.copy()
        df["Transaction Type"] = df["Transaction Type"].astype(str).str.strip().str.lower()
    payload = analyzer_engine.build_health_payload(df)
    st.markdown(payload["status_html"], unsafe_allow_html=True)
    st.plotly_chart(payload["gauge_fig"], use_container_width=True,
                    config={"displayModeBar": False})

    sr = payload["kpis"]
    az_section("📊 Income vs Expense Breakdown")
    st.markdown(f"""<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin:1rem 0 1.5rem;">
        {az_kpi("💰 Total Income",  f"₹{sr['income']:,.0f}",  "All time")}
        {az_kpi("💸 Total Expense", f"₹{sr['expenses']:,.0f}", "All time")}
        {az_kpi("🏦 Net Savings",   f"₹{sr['net']:,.0f}",     "Retained")}
    </div>""", unsafe_allow_html=True)

    # Health insight commentary
    total_inc = sr.get("income", 0)
    total_exp = sr.get("expenses", 0)
    if total_inc > 0:
        sav_rate = ((total_inc - total_exp) / total_inc) * 100
        if sav_rate >= 20:
            st.markdown(az_insight("🏆", f"Your savings rate of <b>{sav_rate:.1f}%</b> is excellent. You're building a strong financial foundation.", "HEALTHY", "up"), unsafe_allow_html=True)
        elif sav_rate >= 10:
            st.markdown(az_insight("💡", f"Your savings rate is <b>{sav_rate:.1f}%</b>. Aim for 20%+ by reducing discretionary spending.", "IMPROVING", "info"), unsafe_allow_html=True)
        else:
            st.markdown(az_insight("⚠️", f"Your savings rate of <b>{sav_rate:.1f}%</b> is below the recommended minimum. Review your top spending categories.", "ACTION NEEDED", "warn"), unsafe_allow_html=True)

    # ── Financial Personality Badge ───────────────────────────────
    st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)
    az_section("🎭 Financial Personality at a Glance")
    profile = detect_financial_personality(df)
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{profile['bg']},rgba(15,23,42,.9));
        border:2px solid {profile['border']};border-radius:18px;padding:20px 26px;
        display:flex;align-items:center;gap:18px;margin-bottom:1rem;">
        <div style="font-size:2.8rem;filter:drop-shadow(0 0 8px {profile['color']});">
            {profile['emoji']}</div>
        <div style="flex:1;">
            <div style="font-size:.68rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;
                color:{profile['color']};margin-bottom:4px;">DETECTED FINANCIAL PERSONALITY</div>
            <div style="font-size:1.35rem;font-weight:900;color:#f0f9ff;font-family:Inter,sans-serif;">
                {profile['name']}</div>
            <div style="color:#94a3b8;font-size:.88rem;font-weight:600;margin-top:4px;">
                {profile['description']}</div>
        </div>
        <div style="background:rgba(0,0,0,.2);border-radius:12px;padding:12px 16px;
            font-size:.84rem;font-weight:700;color:#e2e8f0;max-width:220px;line-height:1.5;">
            💡 {profile['action']}
        </div>
    </div>""", unsafe_allow_html=True)
    st.caption("→ See the full personality analysis in the 💡 Financial Intelligence page.")


def pf_charts():
    page_header("📊 Charts", "Analyzer › Charts")
    df = get_df()
    if df.empty:
        empty_state("📊", "No data yet", "Start adding transactions to see charts.")
        return

    if not df.empty and "Transaction Type" in df.columns:
        df = df.copy()
        df["Transaction Type"] = df["Transaction Type"].astype(str).str.strip().str.lower()
    payload = analyzer_engine.build_charts_payload(df)
    figs    = payload["figures"]

    az_section("📊 Chart Explorer")
    tab1, tab2, tab3 = st.tabs(["Income vs Expense", "Account Breakdown", "Category Trends"])
    with tab1:
        if "inc_exp" in figs:
            st.plotly_chart(figs["inc_exp"], use_container_width=True,
                            config={"displayModeBar": False})
    with tab2:
        if "account" in figs:
            st.plotly_chart(figs["account"], use_container_width=True,
                            config={"displayModeBar": False})
    with tab3:
        if "cat_month" in figs:
            st.plotly_chart(figs["cat_month"], use_container_width=True,
                            config={"displayModeBar": False})


def pf_savings():
    page_header("💚 Savings Trends", "Analyzer › Savings Trends")
    df = get_df()
    if df.empty:
        empty_state("💚", "No data yet", "Add transactions to view savings trends.")
        return

    if not df.empty and "Transaction Type" in df.columns:
        df = df.copy()
        df["Transaction Type"] = df["Transaction Type"].astype(str).str.strip().str.lower()
    payload = analyzer_engine.build_savings_payload(df)
    figs    = payload["figures"]

    az_section("📈 Savings Trend Analysis")
    if "bar" in figs:
        st.plotly_chart(figs["bar"], use_container_width=True,
                        config={"displayModeBar": False})
    if "line" in figs:
        st.plotly_chart(figs["line"], use_container_width=True,
                        config={"displayModeBar": False})

    # Savings commentary
    if "Month Key" in df.columns and not df.empty:
        credits = df[df["Transaction Type"] == "credit"]
        debits  = df[df["Transaction Type"] == "debit"]
        monthly_net = (credits.groupby("Month Key")["Amount"].sum()
                      .subtract(debits.groupby("Month Key")["Amount"].sum(), fill_value=0)
                      .sort_index())
        if not monthly_net.empty:
            best_month = monthly_net.idxmax()
            best_val   = monthly_net.max()
            st.markdown(az_insight("🏆",
                f"Your strongest savings month was <b>{best_month}</b> with a surplus of <b>₹{best_val:,.0f}</b>. Use that month as your benchmark.",
                "BEST MONTH", "up"), unsafe_allow_html=True)


def pf_categories():
    page_header("🏷️ Category Analysis", "Analyzer › Category Analysis")
    df = get_df()
    if df.empty:
        empty_state("🏷️", "No data yet", "Add transactions to see category analysis.")
        return
    df_check = df.copy() if "Transaction Type" in df.columns else df
    if "Transaction Type" in df_check.columns:
        df_check["Transaction Type"] = df_check["Transaction Type"].astype(str).str.strip().str.lower()
    if df_check[df_check["Transaction Type"] == "debit"].empty if "Transaction Type" in df_check.columns else True:
        st.info("No expense transactions found.")
        return
    df = df_check

    if not df.empty and "Transaction Type" in df.columns:
        df = df.copy()
        df["Transaction Type"] = df["Transaction Type"].astype(str).str.strip().str.lower()
    payload = analyzer_engine.build_categories_payload(df)
    bd      = payload["breakdown_df"]

    az_section("🏷️ Category Intelligence")

    # Top-3 category insight cards
    debits = df[df["Transaction Type"] == "debit"]
    if not debits.empty and not bd.empty:
        cat_totals = debits.groupby("Category")["Amount"].sum().sort_values(ascending=False)
        total_exp  = cat_totals.sum()
        top3 = cat_totals.head(3)
        cards_html = ""
        for cat, amt in top3.items():
            pct = (amt / total_exp * 100) if total_exp > 0 else 0
            cards_html += az_insight("🏷️",
                f"<b>{cat}</b> accounts for {pct:.1f}% of total expenses — ₹{amt:,.0f} spent.",
                f"{pct:.0f}% OF EXPENSES",
                "warn" if pct > 30 else "info")
        st.markdown(cards_html, unsafe_allow_html=True)
        st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)

    az_section("📋 Full Category Breakdown")
    st.dataframe(bd, use_container_width=True)

    if payload["treemap_fig"]:
        az_section("🗺️ Category Treemap")
        st.plotly_chart(payload["treemap_fig"], use_container_width=True,
                        config={"displayModeBar": False})


# ══════════════════════════════════════════════════════════════════
#  TRACKER PAGES  (tracker mode only — write-enabled)
# ══════════════════════════════════════════════════════════════════

def pf_overview():
    page_header("🏠 Tracker Overview", "Tracker › Overview")
    df  = get_df()
    if df.empty:
        empty_state("📭", "No transactions yet!",
                    "Use ➕ Add Transaction in the Tracker menu to get started.")
        return

    # Normalise once for all downstream use
    if "Transaction Type" in df.columns:
        df = df.copy()
        df["Transaction Type"] = df["Transaction Type"].astype(str).str.strip().str.lower()

    from core.metrics import calculate_savings_rate
    sr    = calculate_savings_rate(df)
    s_col = sr["direction_color"]
    s_ico = sr["direction"]

    # ── Tracker Stat Cards ────────────────────────────────────────
    total_txns = len(df)
    recent_7   = df[df["Date"] >= (pd.Timestamp.today() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")] if "Date" in df.columns else pd.DataFrame()
    top_cat    = df[df["Transaction Type"] == "debit"].groupby("Category")["Amount"].sum().idxmax() if not df[df["Transaction Type"]=="debit"].empty else "—"

    st.markdown(f"""<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:1rem 0 1.5rem;">
        <div class="tr-stat-card">
            <div class="tr-stat-label">💰 Total Income</div>
            <div class="tr-stat-value">₹{sr['income']:,.0f}</div>
            <div class="tr-stat-sub">All time</div>
        </div>
        <div class="tr-stat-card">
            <div class="tr-stat-label">💸 Total Expense</div>
            <div class="tr-stat-value">₹{sr['expenses']:,.0f}</div>
            <div class="tr-stat-sub">All time</div>
        </div>
        <div class="tr-stat-card" style="border-color:#6EE7B7;">
            <div class="tr-stat-label">🏦 Net Savings</div>
            <div class="tr-stat-value" style="color:{s_col};">₹{sr['net']:,.0f} {s_ico}</div>
            <div class="tr-stat-sub">Savings rate: {sr['savings_pct']:.1f}%</div>
        </div>
        <div class="tr-stat-card" style="border-color:#C4B5FD;">
            <div class="tr-stat-label">📊 Transactions</div>
            <div class="tr-stat-value">{total_txns}</div>
            <div class="tr-stat-sub">Top category: {top_cat}</div>
        </div>
    </div>""", unsafe_allow_html=True)

    # ── Two-column layout: Activity + Budget ──────────────────────
    col_activity, col_budget = st.columns([1.4, 1])

    with col_activity:
        st.markdown('<div class="tracker-h2">📋 Recent Activity</div>', unsafe_allow_html=True)
        st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)
        show_cols = [c for c in ["Date","Category","Transaction Type","Amount","Account Name"] if c in df.columns]
        recent_df = df[show_cols].sort_values("Date", ascending=False).head(10)
        activity_html = ""
        for _, row in recent_df.iterrows():
            is_debit = str(row.get("Transaction Type","")).lower() == "debit"
            amt_cls  = "tr-activity-amt-d" if is_debit else "tr-activity-amt-c"
            amt_sign = "-" if is_debit else "+"
            activity_html += f"""<div class="tr-activity-row">
                <div>
                    <div class="tr-activity-cat">{row.get('Category','—')}</div>
                    <div class="tr-activity-date">{str(row.get('Date',''))[:10]} · {row.get('Account Name','')}</div>
                </div>
                <div class="{amt_cls}">{amt_sign}₹{float(row.get('Amount',0)):,.0f}</div>
            </div>"""
        st.markdown(activity_html, unsafe_allow_html=True)

    with col_budget:
        cur_month = date.today().strftime("%Y-%m")
        budgets   = db_get_budgets(None, cur_month)
        if not budgets.empty:
            st.markdown('<div class="tracker-h2">💰 This Month\'s Budgets</div>', unsafe_allow_html=True)
            st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)
            month_exp = df[(df["Transaction Type"] == "debit") & (df["Month Key"] == cur_month)] if "Month Key" in df.columns else pd.DataFrame()
            cat_spent = month_exp.groupby("Category")["Amount"].sum() if not month_exp.empty else pd.Series(dtype=float)
            cards, summary_html = insights.build_budget_progress_html(budgets, cat_spent)
            for card in cards:
                st.markdown(card, unsafe_allow_html=True)
            st.markdown(summary_html, unsafe_allow_html=True)
        else:
            st.markdown('<div class="tracker-h2">💰 Budget Panel</div>', unsafe_allow_html=True)
            st.markdown(f"""<div class="tr-budget-panel" style="text-align:center;padding:30px;">
                <div style="font-size:2rem;">💰</div>
                <div style="font-weight:800;color:#9d174d;margin-top:.6rem;">No budgets set</div>
                <div style="font-size:.85rem;color:#6b7280;font-weight:700;margin-top:.4rem;">
                    Set budgets for {date.today().strftime('%B %Y')} from the Budgets page.</div>
            </div>""", unsafe_allow_html=True)


def pf_add():
    page_header("➕ Add Transaction", "Tracker › Add Transaction")

    st.markdown("""<div style="background:linear-gradient(135deg,#FFFFFF,#FFF0F9);
        border:3px solid #F9A8D4;border-radius:22px;
        padding:28px 36px 20px;box-shadow:0 8px 32px rgba(249,168,212,.2);margin-bottom:2rem;">
        <div style="font-size:1rem;font-weight:800;color:#be185d;margin-bottom:1.2rem;
            letter-spacing:.06em;text-transform:uppercase;">📝 New Transaction</div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        txn_date = st.date_input("📅 Date", value=date.today())
        txn_type = st.selectbox("💳 Type", ["debit", "credit"])
        txn_cat  = st.selectbox("🏷️ Category", CATS)
    with c2:
        txn_amt  = st.number_input("💰 Amount (₹)", min_value=0.0, step=10.0, format="%.2f")
        txn_acct = st.text_input("🏦 Account Name", placeholder="e.g. HDFC Savings, GPay")
        txn_note = st.text_input("📝 Note (optional)")

    if st.button("✅ Save Transaction", use_container_width=True):
        if txn_amt <= 0:
            st.error("Amount must be greater than 0.")
        elif not txn_acct.strip():
            st.error("Account name is required.")
        else:
            db_add_txn(None, txn_date, txn_type, txn_cat, txn_amt,
                       txn_acct.strip(), txn_note.strip())
            invalidate_cache()
            st.success(f"✅ {txn_type.capitalize()} of ₹{txn_amt:,.2f} saved!")
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def pf_edit():
    page_header("✏️ Edit / Delete", "Tracker › Edit & Delete")
    db_df = db_get_txns(None)
    if db_df.empty:
        empty_state("🗂️", "No transactions yet", "Add some from ➕ Add Transaction first.")
        return

    st.subheader("🔍 Filter Transactions")
    f1, f2, f3, f4 = st.columns(4)
    with f1: f_type = st.selectbox("Type", ["All","credit","debit"], key="ef_type")
    with f2: f_cat  = st.selectbox("Category", ["All"] + CATS, key="ef_cat")
    with f3: f_acct = st.text_input("Account contains", key="ef_acct")
    with f4:
        years = sorted(db_df["Date"].str[:4].dropna().unique().tolist())
        f_yr  = st.selectbox("Year", ["All"] + years, key="ef_yr")

    fdf = filter_df(db_df, f_type, f_cat, f_acct, f_yr)
    st.markdown(f"**{len(fdf)} transaction(s) found**")
    show = [c for c in ["id","Date","Transaction Type","Category","Amount","Account Name","Note"]
            if c in fdf.columns]
    st.dataframe(fdf[show].head(50), use_container_width=True)

    st.markdown("---")
    tab_edit, tab_del = st.tabs(["✏️ Edit a Transaction", "🗑️ Delete"])

    with tab_edit:
        ids = fdf["id"].tolist() if "id" in fdf.columns else []
        if not ids:
            st.info("No transactions match the current filter.")
        else:
            sel_id = st.selectbox("Select transaction ID to edit", ids, key="edit_sel")
            row    = db_df[db_df["id"] == sel_id].iloc[0]
            st.markdown("""<div style="background:#FFFFFF;border:3px solid #C4B5FD;
                border-radius:20px;padding:20px 28px;
                box-shadow:0 6px 24px rgba(196,181,253,.2);margin-top:1rem;">
            """, unsafe_allow_html=True)
            ec1, ec2 = st.columns(2)
            with ec1:
                e_date = st.date_input("📅 Date",
                         value=pd.to_datetime(row["Date"]).date(), key="e_date")
                e_type = st.selectbox("💳 Type", ["debit","credit"],
                         index=0 if row["Transaction Type"]=="debit" else 1, key="e_type")
                e_cat  = st.selectbox("🏷️ Category", CATS,
                         index=CATS.index(row["Category"]) if row["Category"] in CATS else 0,
                         key="e_cat")
            with ec2:
                e_amt  = st.number_input("💰 Amount (₹)", value=float(row["Amount"]),
                         min_value=0.0, step=10.0, format="%.2f", key="e_amt")
                e_acct = st.text_input("🏦 Account Name",
                         value=str(row.get("Account Name","")), key="e_acct")
                e_note = st.text_input("📝 Note",
                         value=str(row.get("Note","")), key="e_note")
            if st.button("💾 Save Changes", use_container_width=True):
                if e_amt <= 0:
                    st.error("Amount must be > 0.")
                elif not e_acct.strip():
                    st.error("Account name required.")
                else:
                    db_update_txn(sel_id, e_date, e_type, e_cat, e_amt,
                                  e_acct.strip(), e_note.strip())
                    invalidate_cache()
                    st.success(f"✅ Transaction #{sel_id} updated!")
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    with tab_del:
        ids = fdf["id"].tolist() if "id" in fdf.columns else []
        if not ids:
            st.info("No transactions match.")
        else:
            d1, d2 = st.columns([2, 1])
            with d1:
                del_id = st.selectbox("Select ID to delete", ids, key="del_sel")
            with d2:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if st.button("🗑️ Delete This Row", use_container_width=True):
                    db_delete_txn(del_id)
                    invalidate_cache()
                    st.success(f"Deleted #{del_id}")
                    st.rerun()
        st.markdown("---")
        st.markdown("**⚠️ Danger zone**")
        if st.button("🗑️ Clear ALL My Transactions", type="primary"):
            db_clear_txns(None)
            invalidate_cache()
            st.success("All transactions cleared.")
            st.rerun()


def pf_budgets():
    page_header("💰 Monthly Budgets", "Tracker › Monthly Budgets")
    sel_month = st.selectbox(
        "📅 Select Month",
        [date(date.today().year, m, 1).strftime("%Y-%m") for m in range(1, 13)],
        index=date.today().month - 1,
        format_func=lambda x: datetime.strptime(x, "%Y-%m").strftime("%B %Y"),
    )

    st.markdown("---")
    st.subheader("➕ Set a Budget")
    b1, b2, b3 = st.columns([2, 1, 1])
    with b1: b_cat = st.selectbox("Category", CATS, key="b_cat")
    with b2: b_amt = st.number_input("Budget (₹)", min_value=0.0, step=100.0,
                                      format="%.2f", key="b_amt")
    with b3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("💾 Save Budget", use_container_width=True):
            if b_amt <= 0:
                st.error("Budget must be > 0.")
            else:
                db_set_budget(None, sel_month, b_cat, b_amt)
                st.success(f"✅ {b_cat} → ₹{b_amt:,.2f}")
                st.rerun()

    st.markdown("---")
    budgets   = db_get_budgets(None, sel_month)
    df        = get_df()
    month_exp = (df[(df["Transaction Type"] == "debit") & (df["Month Key"] == sel_month)]
                 if not df.empty and "Month Key" in df.columns else pd.DataFrame())
    cat_spent = (month_exp.groupby("Category")["Amount"].sum()
                 if not month_exp.empty else pd.Series(dtype=float))

    if budgets.empty:
        st.info(f"No budgets set for {datetime.strptime(sel_month,'%Y-%m').strftime('%B %Y')} yet.")
    else:
        st.subheader(f"📊 Budget vs Actual — {datetime.strptime(sel_month,'%Y-%m').strftime('%B %Y')}")
        cards, summary_html = insights.build_budget_progress_html(budgets, cat_spent)
        for card in cards:
            st.markdown(card, unsafe_allow_html=True)
        st.markdown(summary_html, unsafe_allow_html=True)

        chart_data = insights.build_budget_chart_data(budgets, cat_spent)
        if chart_data:
            from core.charts import bar_budget_vs_actual
            fig = bar_budget_vs_actual(chart_data)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        st.markdown("---")
        st.subheader("🗑️ Remove a Budget")
        del_cat = st.selectbox("Select category", budgets["category"].tolist(), key="del_bcat")
        if st.button("Remove Budget", key="del_budget_btn"):
            db_delete_budget(None, sel_month, del_cat)
            st.success(f"Removed {del_cat}.")
            st.rerun()


def pf_history():
    page_header("📋 Transaction History", "Tracker › History")
    db_df = db_get_txns(None)
    if db_df.empty:
        empty_state("📋", "No transactions yet", "Start adding transactions to see history.")
        return
    st.subheader(f"📦 {len(db_df)} total transactions")
    show = [c for c in ["Date","Transaction Type","Category","Amount","Account Name","Note"]
            if c in db_df.columns]
    st.dataframe(db_df[show], use_container_width=True)


# ══════════════════════════════════════════════════════════════════
#  REPORTS PAGE
# ══════════════════════════════════════════════════════════════════

def pf_download():
    page_header("📥 Download Report", "Reports › Download")
    df = get_df()
    if df.empty:
        empty_state("📥", "Nothing to export", "Add transactions first.")
        return

    summary = analyzer_engine.build_export_summary(df)
    cat_bd  = analyzer_engine.build_category_export(df)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        cols = [c for c in ["Date","Transaction Type","Category","Amount","Account Name","Note"]
                if c in df.columns]
        df[cols].to_excel(w, sheet_name="Transactions", index=False)
        pd.DataFrame({
            "Metric": ["Total Income","Total Expense","Net Savings","Savings Rate %","Total Transactions"],
            "Value":  [summary["income"], summary["expenses"], summary["net"],
                       summary["savings_pct"], summary["total_transactions"]],
        }).to_excel(w, sheet_name="Summary", index=False)
        if not cat_bd.empty:
            cat_bd.to_excel(w, sheet_name="Category Breakdown", index=False)
    buf.seek(0)

    fname = f"finance_report_{datetime.today().strftime('%Y%m%d')}.xlsx"
    st.download_button(
        "📥 Download Excel Report", data=buf, file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    st.markdown("---")
    st.subheader("Preview")
    prev_cols = [c for c in ["Date","Transaction Type","Category","Amount","Account Name"]
                 if c in df.columns]
    st.dataframe(df[prev_cols].head(30), use_container_width=True)


# ══════════════════════════════════════════════════════════════════
#  MODE SELECTION PAGE  (replaces Profile)
# ══════════════════════════════════════════════════════════════════

def pf_mode_select():
    page_header("🔀 Mode Selection", "Settings › Mode")
    df   = get_df()
    mode = st.session_state.get("mode", "tracker")

    from core.metrics import calculate_savings_rate
    sr = calculate_savings_rate(df)

    # ── Dataset summary card ──────────────────────────────────────
    filename  = st.session_state.get("uploaded_filename", "Uploaded Dataset")
    row_count = st.session_state.get("uploaded_row_count", len(df))

    st.markdown(f"""<div style="background:#FFFFFF;border:3px solid #93C5FD;border-radius:22px;
        padding:24px 32px;box-shadow:0 8px 28px rgba(147,197,253,.2);margin-bottom:1.5rem;">
        <div style="font-size:1rem;font-weight:900;color:#1d4ed8;margin-bottom:14px;
            letter-spacing:.06em;text-transform:uppercase;">📂 Current Dataset</div>
        <div style="color:#374151;font-weight:700;font-size:.95rem;margin-bottom:12px;">
            📄 {filename}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;">
            <div style="background:#F0FDF4;border:2px solid #6EE7B7;border-radius:12px;
                padding:12px;text-align:center;">
                <div style="font-weight:900;font-size:1.4rem;color:#065f46;">{row_count:,}</div>
                <div style="font-size:.78rem;font-weight:700;color:#6b7280;">Rows</div>
            </div>
            <div style="background:#FFF0F9;border:2px solid #F9A8D4;border-radius:12px;
                padding:12px;text-align:center;">
                <div style="font-weight:900;font-size:1.4rem;color:#be185d;">₹{sr['income']:,.0f}</div>
                <div style="font-size:.78rem;font-weight:700;color:#6b7280;">Total Income</div>
            </div>
            <div style="background:#EFF6FF;border:2px solid #93C5FD;border-radius:12px;
                padding:12px;text-align:center;">
                <div style="font-weight:900;font-size:1.4rem;color:#1d4ed8;">₹{sr['expenses']:,.0f}</div>
                <div style="font-size:.78rem;font-weight:700;color:#6b7280;">Total Expenses</div>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("🔀 Switch Mode")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""<div style="background:#FFF0F9;border:3px solid #F9A8D4;border-radius:18px;
            padding:20px;text-align:center;margin-bottom:1rem;">
            <div style="font-size:2rem;">📊📝</div>
            <div style="font-weight:900;color:#be185d;margin-top:.5rem;">Tracker + Analyzer</div>
            <div style="font-size:.82rem;color:#9d174d;font-weight:700;margin-top:.3rem;">
                Full write access — add, edit, budget, analyse</div>
        </div>""", unsafe_allow_html=True)
        if st.button("📝 Enable Tracker + Analyzer", use_container_width=True,
                     disabled=(mode == "tracker"), key="mode_sel_tracker"):
            switch_mode("tracker")
    with c2:
        st.markdown("""<div style="background:#EFF6FF;border:3px solid #93C5FD;border-radius:18px;
            padding:20px;text-align:center;margin-bottom:1rem;">
            <div style="font-size:2rem;">📊</div>
            <div style="font-weight:900;color:#1d4ed8;margin-top:.5rem;">Analyzer Only</div>
            <div style="font-size:.82rem;color:#1e40af;font-weight:700;margin-top:.3rem;">
                Read-only intelligence — insights, charts, trends</div>
        </div>""", unsafe_allow_html=True)
        if st.button("📊 Switch to Analyzer Only", use_container_width=True,
                     disabled=(mode == "analyzer"), key="mode_sel_analyzer"):
            switch_mode("analyzer")

    if mode == "tracker":
        st.success("✅ Current mode: Tracker + Analyzer")
    else:
        st.info("ℹ️ Current mode: Analyzer Only")

    st.markdown("---")
    st.subheader("📂 Upload New File")
    st.warning("This will clear the current session and return to the upload screen.")
    if st.button("📂 Upload New File", use_container_width=True, key="mode_page_upload_new"):
        for k in list(DEFAULTS.keys()):
            st.session_state[k] = DEFAULTS[k]
        st.rerun()

    st.markdown("---")
    st.subheader("📂 Merge Additional Data")
    st.info("Add more rows from a new Excel file into the current session.")
    reimport_file = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"], key="mode_reimport")
    if reimport_file:
        try:
            rdf = pd.read_excel(reimport_file)
            rdf.columns = rdf.columns.str.strip()
            unnamed_c = sum(1 for c in rdf.columns if str(c).startswith("Unnamed:"))
            if unnamed_c / max(len(rdf.columns), 1) > 0.4:
                try:
                    reimport_file.seek(0)
                    rdf2 = pd.read_excel(reimport_file, header=1)
                    rdf2.columns = rdf2.columns.str.strip()
                    unnamed2 = sum(1 for c in rdf2.columns if str(c).startswith("Unnamed:"))
                    if unnamed2 < unnamed_c:
                        rdf = rdf2
                except Exception:
                    pass
            reimport_result = _detect_dataset(rdf)
            reimport_mapping = reimport_result["mapping"]
            reimport_type    = reimport_result["dataset_type"]
            if reimport_result["capability"] == _CAP_UNKNOWN:
                st.error("❌ Could not detect dataset structure. Check that your file has Date and Amount columns.")
            else:
                try:
                    std_rdf = _standardise_df(rdf, reimport_mapping, reimport_type)
                    if std_rdf.empty:
                        st.error("❌ Standardisation produced 0 rows.")
                    else:
                        st.success(f"✅ Loaded {len(std_rdf)} standardised rows from {reimport_file.name}.")
                        st.dataframe(std_rdf.head(5), use_container_width=True)
                        if st.button("💾 Add to Existing Data", key="mode_do_reimport"):
                            count = db_import_txns(None, std_rdf)
                            invalidate_cache()
                            st.success(f"✅ {count} rows merged.")
                            st.rerun()
                except Exception as e:
                    st.error(f"Standardisation error: {e}")
        except Exception as e:
            st.error(f"Could not read file: {e}")


# ══════════════════════════════════════════════════════════════════
#  PLATFORM — sidebar + routing
# ══════════════════════════════════════════════════════════════════

def page_platform():
    mode = st.session_state.get("mode", "tracker")
    page = st.session_state.get("nav_page", "overview")

    ANALYZER_PAGES = {"analytics", "insights", "health", "charts", "savings", "categories"}
    on_analyzer_page = page in ANALYZER_PAGES

    if mode == "analyzer" or (mode == "tracker" and on_analyzer_page):
        # ── ANALYZER: dark blue/purple executive dashboard ──────────
        st.markdown("""<style>
        [data-testid="stSidebar"] { display:flex!important; }
        html,body,.stApp,[data-testid="stAppViewContainer"],
        [data-testid="stAppViewBlockContainer"],.main {
            background:linear-gradient(150deg,#0f172a 0%,#1e1b4b 50%,#0f172a 100%)!important; }
        .block-container { padding:0 2rem 3rem!important; max-width:1180px; }
        /* Override all text to light for dark bg */
        [data-testid="stAppViewBlockContainer"] p,
        [data-testid="stAppViewBlockContainer"] label,
        [data-testid="stAppViewBlockContainer"] span:not(.az-mode-badge):not(.name):not(.page) {
            color:#cbd5e1 !important; }
        /* Tabs in analyzer */
        [data-testid="stTabs"] [data-baseweb="tab-list"] {
            background: rgba(30,41,59,.6) !important;
            border-radius: 12px !important; border: 1px solid rgba(99,102,241,.2) !important; }
        [data-testid="stTabs"] [data-baseweb="tab"] {
            color: #64748b !important; font-weight: 700 !important; }
        [data-testid="stTabs"] [aria-selected="true"] {
            color: #a5b4fc !important;
            background: rgba(99,102,241,.2) !important; border-radius: 10px !important; }
        /* Selectboxes */
        [data-testid="stSelectbox"] > div > div {
            background: rgba(30,41,59,.8) !important;
            border: 1.5px solid rgba(99,102,241,.3) !important;
            border-radius: 12px !important; color: #e2e8f0 !important; }
        /* DataFrames in dark mode */
        [data-testid="stDataFrame"] {
            border: 1.5px solid rgba(99,102,241,.25) !important;
            border-radius: 14px !important; }
        /* Analyzer buttons */
        [data-testid="baseButton-primary"] {
            background: linear-gradient(90deg,#3b82f6,#6366f1)!important;
            box-shadow: 0 4px 16px rgba(99,102,241,.4)!important; }
        [data-testid="baseButton-secondary"] {
            background: rgba(30,41,59,.7)!important;
            color: #a5b4fc!important; -webkit-text-fill-color:#a5b4fc!important;
            border: 1.5px solid rgba(99,102,241,.4)!important; }
        hr { border-color: rgba(99,102,241,.2) !important; }
        </style>""", unsafe_allow_html=True)
    else:
        # ── TRACKER: pink/purple workspace ──────────────────────────
        st.markdown("""<style>
        [data-testid="stSidebar"] { display:flex!important; }
        html,body,.stApp,[data-testid="stAppViewContainer"],
        [data-testid="stAppViewBlockContainer"],.main {
            background:linear-gradient(150deg,#FFF0F9 0%,#EFF6FF 40%,#F0FDF4 100%)!important; }
        .block-container { padding:0 2rem 3rem!important; max-width:1100px; }
        [data-testid="baseButton-primary"] {
            background:linear-gradient(90deg,#f472b6,#a78bfa)!important;
            box-shadow:0 2px 14px rgba(244,114,182,.4)!important; }
        [data-testid="baseButton-secondary"] {
            background:rgba(255,255,255,.8)!important;
            color:#9d174d!important; -webkit-text-fill-color:#9d174d!important;
            border:2px solid rgba(249,168,212,.5)!important; }
        </style>""", unsafe_allow_html=True)

    render_topbar()
    render_sidebar()

    section = st.session_state.nav_section
    page    = st.session_state.nav_page
    mode    = st.session_state.get("mode", "tracker")

    # ── Route tables ──────────────────────────────────────────
    ANALYZER_ROUTES = {
        "analytics":  pf_analytics,
        "insights":   pf_insights,
        "health":     pf_health,
        "charts":     pf_charts,
        "savings":    pf_savings,
        "categories": pf_categories,
    }
    TRACKER_ROUTES = {
        "overview": pf_overview,
        "add":      pf_add,
        "edit":     pf_edit,
        "budgets":  pf_budgets,
        "history":  pf_history,
    }
    REPORTS_ROUTES = {"download": pf_download}
    MODE_ROUTES    = {"mode":     pf_mode_select}

    # ── Hard mode guards ──────────────────────────────────────
    if mode == "analyzer":
        # Analyzer Only: block tracker pages, allow analyzer + reports + mode
        if page in TRACKER_ROUTES:
            st.session_state.nav_section = "analyzer"
            st.session_state.nav_page    = "insights"
            st.rerun()
            return
        fn = {**ANALYZER_ROUTES, **REPORTS_ROUTES, **MODE_ROUTES}.get(page, pf_insights)
    else:
        # Tracker + Analyzer: allow ALL pages — tracker, analyzer, reports, mode
        fn = {**TRACKER_ROUTES, **ANALYZER_ROUTES, **REPORTS_ROUTES, **MODE_ROUTES}.get(page, pf_overview)

    fn()


# ══════════════════════════════════════════════════════════════════
#  MAIN ROUTER
# ══════════════════════════════════════════════════════════════════
APP_PAGE = st.session_state.app_page

if APP_PAGE == "platform":
    page_platform()
else:
    page_upload()