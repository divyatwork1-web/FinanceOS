"""
core/insights.py  —  FinanceOS Financial Intelligence Engine
════════════════════════════════════════════════════════════════
Provides interpretation-based analysis (not just raw numbers).

Public API:
  generate_behavioral_analysis(df)   → list[dict]
  detect_financial_personality(df)   → dict
  generate_predictive_insights(df)   → list[dict]
  generate_financial_recommendations(df) → list[dict]
  build_budget_progress_html(budgets, cat_spent) → (list[str], str)
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd


# ─────────────────────────────────────────────────────────────────
#  INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────

def _debits(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["Transaction Type"] == "debit"]


def _credits(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["Transaction Type"] == "credit"]


def _monthly_expense(df: pd.DataFrame) -> pd.Series:
    """Return monthly expense totals indexed by Month Key (YYYY-MM)."""
    deb = _debits(df)
    if deb.empty or "Month Key" not in deb.columns:
        return pd.Series(dtype=float)
    return deb.groupby("Month Key")["Amount"].sum().sort_index()


def _monthly_income(df: pd.DataFrame) -> pd.Series:
    cred = _credits(df)
    if cred.empty or "Month Key" not in cred.columns:
        return pd.Series(dtype=float)
    return cred.groupby("Month Key")["Amount"].sum().sort_index()


def _savings_rate(df: pd.DataFrame) -> float:
    inc = _credits(df)["Amount"].sum() if not _credits(df).empty else 0.0
    exp = _debits(df)["Amount"].sum()  if not _debits(df).empty  else 0.0
    return ((inc - exp) / inc * 100) if inc > 0 else 0.0


def _weekend_vs_weekday_ratio(df: pd.DataFrame) -> float | None:
    """Return (weekend_avg / weekday_avg). >1 = spends more on weekends."""
    deb = _debits(df).copy()
    if deb.empty or "Date" not in deb.columns:
        return None
    try:
        deb["_dow"] = pd.to_datetime(deb["Date"]).dt.dayofweek  # 0=Mon … 6=Sun
        weekend = deb[deb["_dow"] >= 5]["Amount"].mean()
        weekday = deb[deb["_dow"] < 5]["Amount"].mean()
        if weekday and not math.isnan(weekday) and weekday > 0:
            return round(weekend / weekday, 2)
    except Exception:
        pass
    return None


def _spending_after_salary(df: pd.DataFrame) -> bool:
    """
    Heuristic: do expenses spike in the 5 days after any credit?
    Returns True if average daily expense in the 5 days after a credit
    is at least 1.5× the overall daily average.
    """
    try:
        deb = _debits(df).copy()
        cred = _credits(df).copy()
        if deb.empty or cred.empty:
            return False
        deb["_date"]  = pd.to_datetime(deb["Date"])
        cred["_date"] = pd.to_datetime(cred["Date"])
        credit_dates  = cred["_date"].tolist()
        post_salary_amounts = []
        for cd in credit_dates:
            mask = (deb["_date"] > cd) & (deb["_date"] <= cd + pd.Timedelta(days=5))
            post_salary_amounts.extend(deb[mask]["Amount"].tolist())
        if not post_salary_amounts:
            return False
        overall_avg = deb["Amount"].mean()
        post_avg    = sum(post_salary_amounts) / len(post_salary_amounts)
        return post_avg >= overall_avg * 1.5
    except Exception:
        return False


def _month_over_month_growth(series: pd.Series) -> float | None:
    """Average monthly growth rate (%) over last 3 months."""
    if len(series) < 2:
        return None
    last3 = series.iloc[-min(3, len(series)):]
    changes = []
    for i in range(1, len(last3)):
        prev = last3.iloc[i - 1]
        if prev > 0:
            changes.append((last3.iloc[i] - prev) / prev * 100)
    return round(sum(changes) / len(changes), 1) if changes else None


def _category_pct(df: pd.DataFrame) -> dict[str, float]:
    """Percentage of total expense per category."""
    deb = _debits(df)
    if deb.empty:
        return {}
    totals = deb.groupby("Category")["Amount"].sum()
    grand  = totals.sum()
    return {cat: round(amt / grand * 100, 1) for cat, amt in totals.items()} if grand else {}


def _savings_consistency(df: pd.DataFrame) -> float:
    """
    Returns fraction of months (0–1) where the user had a positive savings (income > expense).
    """
    inc = _monthly_income(df)
    exp = _monthly_expense(df)
    if inc.empty:
        return 0.0
    net = inc.subtract(exp, fill_value=0)
    positive = (net > 0).sum()
    return round(positive / len(net), 2) if len(net) > 0 else 0.0


# ─────────────────────────────────────────────────────────────────
#  1. BEHAVIORAL ANALYSIS
# ─────────────────────────────────────────────────────────────────

def generate_behavioral_analysis(df: pd.DataFrame) -> list[dict]:
    """
    Return a list of behavioral insight dicts:
      {icon, text, tag, type}   (type ∈ up | down | info | warn)

    Interprets *why* spending happened, not just how much.
    """
    insights: list[dict] = []
    if df.empty:
        return insights

    try:
        deb = _debits(df)
        cred = _credits(df)

        # ── 1. Weekend spending pattern ──────────────────────────
        ratio = _weekend_vs_weekday_ratio(df)
        if ratio is not None:
            if ratio >= 1.4:
                insights.append({
                    "icon": "🎉",
                    "text": f"You spend <b>{ratio:.1f}×</b> more on weekends than on weekdays. "
                            "Weekend leisure and social spending are noticeably driving up your totals.",
                    "tag": "WEEKEND SPENDER", "type": "warn"
                })
            elif ratio <= 0.7:
                insights.append({
                    "icon": "📅",
                    "text": "Your spending is concentrated on weekdays, suggesting mostly work-related or "
                            "commute/food expenses. Weekends show disciplined restraint.",
                    "tag": "WEEKDAY PATTERN", "type": "info"
                })

        # ── 2. Post-salary spending spike ────────────────────────
        if _spending_after_salary(df):
            insights.append({
                "icon": "💳",
                "text": "Shopping and discretionary spending tend to <b>spike in the 5 days after a salary credit</b>. "
                        "This is a common impulse-spending pattern — consider a 48-hour pause before large purchases.",
                "tag": "POST-SALARY SPIKE", "type": "warn"
            })

        # ── 3. Food spending trend ───────────────────────────────
        if "Month Key" in df.columns and not deb.empty:
            food_cats = [c for c in deb["Category"].unique()
                         if any(k in c.lower() for k in ["food", "dining", "restaurant", "grocery"])]
            if food_cats:
                food_monthly = (deb[deb["Category"].isin(food_cats)]
                                .groupby("Month Key")["Amount"].sum().sort_index())
                if len(food_monthly) >= 2:
                    prev_f, cur_f = food_monthly.iloc[-2], food_monthly.iloc[-1]
                    change_pct = ((cur_f - prev_f) / prev_f * 100) if prev_f > 0 else 0
                    if change_pct > 20:
                        insights.append({
                            "icon": "🍽️",
                            "text": f"Food & dining expenses <b>increased by {change_pct:.0f}%</b> compared to last month. "
                                    "This could indicate more eating out or rising grocery prices.",
                            "tag": f"FOOD +{change_pct:.0f}%", "type": "warn"
                        })
                    elif change_pct < -15:
                        insights.append({
                            "icon": "🥗",
                            "text": f"Food spending <b>dropped by {abs(change_pct):.0f}%</b> this month — great job "
                                    "cooking at home or meal planning!",
                            "tag": f"FOOD -{abs(change_pct):.0f}%", "type": "up"
                        })

        # ── 4. Entertainment spending flag ───────────────────────
        cat_pcts = _category_pct(df)
        ent_cats = [c for c in cat_pcts if any(k in c.lower()
                    for k in ["entertainment", "leisure", "fun", "movies", "gaming"])]
        for ec in ent_cats:
            if cat_pcts[ec] > 20:
                insights.append({
                    "icon": "🎬",
                    "text": f"<b>Entertainment spending</b> accounts for {cat_pcts[ec]:.1f}% of total expenses — "
                            "this is unusually high. Most financial plans recommend capping leisure at 10–15%.",
                    "tag": "ENTERTAINMENT HIGH", "type": "warn"
                })

        # ── 5. Shopping spikes ───────────────────────────────────
        shop_cats = [c for c in cat_pcts if any(k in c.lower()
                     for k in ["shopping", "retail", "fashion", "clothes", "amazon"])]
        for sc in shop_cats:
            if cat_pcts[sc] > 25:
                insights.append({
                    "icon": "🛍️",
                    "text": f"Shopping & retail makes up <b>{cat_pcts[sc]:.1f}%</b> of your expenses. "
                            "Unplanned purchases and online shopping often creep up unnoticed.",
                    "tag": "RETAIL HEAVY", "type": "warn"
                })

        # ── 6. Savings consistency ───────────────────────────────
        consistency = _savings_consistency(df)
        if consistency >= 0.8:
            insights.append({
                "icon": "📈",
                "text": f"You've maintained positive savings in <b>{int(consistency*100)}% of your tracked months</b>. "
                        "This kind of consistency is the foundation of long-term wealth.",
                "tag": "SAVINGS CONSISTENT", "type": "up"
            })
        elif consistency < 0.4 and consistency > 0:
            insights.append({
                "icon": "📉",
                "text": f"You saved money in only <b>{int(consistency*100)}% of tracked months</b>. "
                        "Irregular savings often indicate unplanned expense spikes or income volatility.",
                "tag": "INCONSISTENT SAVINGS", "type": "down"
            })

        # ── 7. Month-over-month expense growth ───────────────────
        monthly_exp = _monthly_expense(df)
        growth = _month_over_month_growth(monthly_exp)
        if growth is not None and abs(growth) > 8:
            direction = "accelerating" if growth > 0 else "decelerating"
            tag_type  = "down" if growth > 0 else "up"
            insights.append({
                "icon": "🚀" if growth > 0 else "🛑",
                "text": f"Your spending growth rate is <b>{direction}</b> — averaging "
                        f"<b>{'+'if growth>0 else ''}{growth:.1f}%</b> per month over the last 3 months.",
                "tag": f"GROWTH {'+' if growth>0 else ''}{growth:.0f}%/MO", "type": tag_type
            })

    except Exception:
        pass

    return insights


# ─────────────────────────────────────────────────────────────────
#  2. FINANCIAL PERSONALITY DETECTION
# ─────────────────────────────────────────────────────────────────

PERSONALITY_PROFILES = {
    "Aggressive Spender": {
        "emoji": "🔥",
        "color": "#ef4444",
        "border": "rgba(239,68,68,.5)",
        "bg": "rgba(239,68,68,.08)",
        "description": "You tend to spend at high velocity with limited savings buffer. "
                       "Your income often flows out as fast as it comes in.",
        "action": "Set hard monthly limits per category. Automate a savings transfer on salary day."
    },
    "Balanced Saver": {
        "emoji": "⚖️",
        "color": "#10b981",
        "border": "rgba(16,185,129,.5)",
        "bg": "rgba(16,185,129,.08)",
        "description": "You maintain a healthy equilibrium between spending and saving. "
                       "Income and expenses are roughly proportional month to month.",
        "action": "Maintain your discipline. Consider channeling surplus into investments."
    },
    "Conservative Saver": {
        "emoji": "🏦",
        "color": "#3b82f6",
        "border": "rgba(59,130,246,.5)",
        "bg": "rgba(59,130,246,.08)",
        "description": "You prioritize saving over spending, often keeping expenses well below income. "
                       "Low risk, high security mindset.",
        "action": "Excellent base. Ensure savings are working for you via investments, not just idle cash."
    },
    "Lifestyle Focused": {
        "emoji": "✨",
        "color": "#a855f7",
        "border": "rgba(168,85,247,.5)",
        "bg": "rgba(168,85,247,.08)",
        "description": "A significant portion of your budget goes toward lifestyle categories: "
                       "dining, entertainment, shopping, and experiences.",
        "action": "There's joy in living well — just ensure core savings targets are met first."
    },
    "High Risk Spender": {
        "emoji": "⚠️",
        "color": "#f59e0b",
        "border": "rgba(245,158,11,.5)",
        "bg": "rgba(245,158,11,.08)",
        "description": "Spending frequently exceeds or nearly matches income. "
                       "Savings are minimal or inconsistent, creating financial vulnerability.",
        "action": "Urgent: build a 3-month emergency fund. Cut the top 2 discretionary categories immediately."
    },
    "Stable Financial Planner": {
        "emoji": "🎯",
        "color": "#06b6d4",
        "border": "rgba(6,182,212,.5)",
        "bg": "rgba(6,182,212,.08)",
        "description": "Your finances show steady, predictable patterns with consistent savings "
                       "and controlled expense growth.",
        "action": "You're in great shape. Focus on optimizing returns — mutual funds, SIPs, or index funds."
    },
}


def detect_financial_personality(df: pd.DataFrame) -> dict:
    """
    Classify the user's financial personality based on transaction patterns.
    Returns the full personality profile dict.
    """
    if df.empty:
        return {"name": "Unknown", **PERSONALITY_PROFILES.get("Balanced Saver", {})}

    try:
        sav_rate    = _savings_rate(df)
        consistency = _savings_consistency(df)
        cat_pcts    = _category_pct(df)
        monthly_exp = _monthly_expense(df)
        growth      = _month_over_month_growth(monthly_exp) or 0.0

        lifestyle_pct = sum(
            v for k, v in cat_pcts.items()
            if any(kw in k.lower() for kw in
                   ["entertainment", "dining", "food", "shopping", "fashion", "travel", "leisure"])
        )

        # Scoring rules → pick best matching personality
        if sav_rate < 0 or (sav_rate < 5 and consistency < 0.3):
            name = "High Risk Spender"
        elif sav_rate < 10 and growth > 10:
            name = "Aggressive Spender"
        elif sav_rate >= 30 and consistency >= 0.75:
            name = "Conservative Saver"
        elif lifestyle_pct >= 50 and sav_rate < 20:
            name = "Lifestyle Focused"
        elif sav_rate >= 15 and consistency >= 0.6 and growth < 5:
            name = "Stable Financial Planner"
        else:
            name = "Balanced Saver"

        profile = PERSONALITY_PROFILES[name].copy()
        profile["name"] = name

        # Attach computed signals for transparency
        profile["signals"] = {
            "savings_rate":  round(sav_rate, 1),
            "consistency":   round(consistency * 100, 0),
            "lifestyle_pct": round(lifestyle_pct, 1),
            "growth_rate":   round(growth, 1),
        }
        return profile

    except Exception:
        profile = PERSONALITY_PROFILES["Balanced Saver"].copy()
        profile["name"] = "Balanced Saver"
        return profile


def render_personality_card(profile: dict) -> str:
    """Return HTML for a premium financial personality display card."""
    signals = profile.get("signals", {})
    sig_html = ""
    if signals:
        sig_items = [
            ("💰 Savings Rate",     f"{signals.get('savings_rate', 0):.1f}%"),
            ("📅 Consistency",      f"{signals.get('consistency', 0):.0f}% of months"),
            ("✨ Lifestyle Spend",  f"{signals.get('lifestyle_pct', 0):.1f}% of expenses"),
            ("📈 Growth Rate",      f"{signals.get('growth_rate', 0):+.1f}%/mo"),
        ]
        for label, val in sig_items:
            sig_html += f"""<div style="display:flex;justify-content:space-between;
                padding:7px 0;border-bottom:1px solid rgba(255,255,255,.06);
                font-size:.84rem;">
                <span style="color:#94a3b8;font-weight:600;">{label}</span>
                <span style="color:#e2e8f0;font-weight:800;">{val}</span>
            </div>"""

    return f"""
    <div style="background:linear-gradient(135deg,{profile['bg']},rgba(15,23,42,.95));
        border:2px solid {profile['border']};border-radius:22px;padding:28px 32px;
        box-shadow:0 12px 40px rgba(0,0,0,.35);margin-bottom:1.2rem;">
        <div style="display:flex;align-items:center;gap:16px;margin-bottom:18px;">
            <div style="font-size:3rem;filter:drop-shadow(0 0 8px {profile['color']});">
                {profile['emoji']}</div>
            <div>
                <div style="font-size:.72rem;font-weight:800;letter-spacing:.14em;
                    text-transform:uppercase;color:{profile['color']};margin-bottom:4px;">
                    YOUR FINANCIAL PERSONALITY</div>
                <div style="font-size:1.65rem;font-weight:900;color:#f0f9ff;
                    font-family:Inter,sans-serif;letter-spacing:-.02em;">
                    {profile['name']}</div>
            </div>
        </div>
        <div style="color:#cbd5e1;font-size:.94rem;font-weight:600;line-height:1.65;
            margin-bottom:18px;border-left:3px solid {profile['color']};padding-left:14px;">
            {profile['description']}</div>
        <div style="background:rgba(0,0,0,.2);border-radius:14px;padding:14px 16px;
            margin-bottom:14px;">
            {sig_html}
        </div>
        <div style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);
            border-radius:12px;padding:12px 16px;">
            <div style="font-size:.72rem;font-weight:900;letter-spacing:.1em;
                text-transform:uppercase;color:{profile['color']};margin-bottom:6px;">
                💡 ADVISOR RECOMMENDATION</div>
            <div style="color:#e2e8f0;font-size:.9rem;font-weight:700;line-height:1.6;">
                {profile['action']}</div>
        </div>
    </div>"""


# ─────────────────────────────────────────────────────────────────
#  3. PREDICTIVE INSIGHTS
# ─────────────────────────────────────────────────────────────────

def generate_predictive_insights(df: pd.DataFrame) -> list[dict]:
    """
    Return future-oriented commentary dicts:
      {icon, text, tag, type, confidence}
    """
    predictions: list[dict] = []
    if df.empty:
        return predictions

    try:
        monthly_exp = _monthly_expense(df)
        monthly_inc = _monthly_income(df)
        sav_rate    = _savings_rate(df)

        # ── Projection: month-end budget status ──────────────────
        if len(monthly_exp) >= 2:
            last_exp   = monthly_exp.iloc[-1]
            second_exp = monthly_exp.iloc[-2]
            avg_exp    = monthly_exp.mean()

            if last_exp > avg_exp * 1.25:
                predictions.append({
                    "icon": "🚨",
                    "text": f"At your current pace (<b>₹{last_exp:,.0f}</b> this month vs avg ₹{avg_exp:,.0f}), "
                            "you are on track to <b>exceed your typical monthly budget</b> significantly.",
                    "tag": "BUDGET RISK", "type": "down", "confidence": "High"
                })
            elif last_exp < avg_exp * 0.8:
                predictions.append({
                    "icon": "🟢",
                    "text": f"This month's spending (<b>₹{last_exp:,.0f}</b>) is tracking well "
                            f"<b>below average</b> (₹{avg_exp:,.0f}). You're projected for a strong savings month.",
                    "tag": "STRONG MONTH", "type": "up", "confidence": "High"
                })

        # ── Savings trajectory ────────────────────────────────────
        all_months = monthly_inc.index.union(monthly_exp.index)
        if len(all_months) >= 3:
            net_series = monthly_inc.subtract(monthly_exp, fill_value=0).sort_index()
            growth = _month_over_month_growth(net_series)
            if growth is not None:
                if growth > 5:
                    predictions.append({
                        "icon": "📈",
                        "text": f"Your net savings are growing at <b>+{growth:.1f}% per month</b>. "
                                "If this trend holds, you'll build a significantly stronger reserve over the next quarter.",
                        "tag": "SAVINGS TRENDING UP", "type": "up", "confidence": "Medium"
                    })
                elif growth < -10:
                    predictions.append({
                        "icon": "📉",
                        "text": f"Net savings are <b>declining at {growth:.1f}% per month</b>. "
                                "Without course correction, you may see a negative savings position within 2–3 months.",
                        "tag": "SAVINGS RISK", "type": "down", "confidence": "Medium"
                    })

        # ── Spending growth rate warning ──────────────────────────
        growth_exp = _month_over_month_growth(monthly_exp)
        if growth_exp is not None and growth_exp > 12:
            predictions.append({
                "icon": "⚡",
                "text": f"Your spending growth rate is <b>accelerating at +{growth_exp:.1f}%/month</b>. "
                        "At this pace, expenses could outpace income within the next few months.",
                "tag": "ACCELERATION ALERT", "type": "warn", "confidence": "Medium"
            })

        # ── Savings rate projection ───────────────────────────────
        if sav_rate > 0:
            annual_savings_projection = (_monthly_income(df).mean() - _monthly_expense(df).mean()) * 12
            if annual_savings_projection > 0:
                predictions.append({
                    "icon": "🎯",
                    "text": f"Based on current trends, you're projected to save approximately "
                            f"<b>₹{annual_savings_projection:,.0f}</b> over the next 12 months.",
                    "tag": "12-MONTH PROJECTION", "type": "info", "confidence": "Medium"
                })

        # ── Top category escalation risk ──────────────────────────
        deb = _debits(df)
        if not deb.empty and "Month Key" in deb.columns:
            cat_monthly = deb.groupby(["Month Key", "Category"])["Amount"].sum().unstack(fill_value=0)
            if len(cat_monthly) >= 2:
                last_row = cat_monthly.iloc[-1]
                prev_row = cat_monthly.iloc[-2]
                for cat in last_row.index:
                    if prev_row[cat] > 0:
                        cat_growth = (last_row[cat] - prev_row[cat]) / prev_row[cat] * 100
                        if cat_growth > 40:
                            predictions.append({
                                "icon": "🔔",
                                "text": f"<b>{cat}</b> spending surged <b>+{cat_growth:.0f}%</b> this month. "
                                        "If unchecked, this category could significantly impact next month's budget.",
                                "tag": f"{cat[:12].upper()} SPIKE", "type": "warn", "confidence": "High"
                            })
                            break  # only flag the biggest spike

    except Exception:
        pass

    return predictions


# ─────────────────────────────────────────────────────────────────
#  4. SMART RECOMMENDATIONS
# ─────────────────────────────────────────────────────────────────

def generate_financial_recommendations(df: pd.DataFrame) -> list[dict]:
    """
    Return coaching-style recommendation dicts:
      {icon, title, body, priority}   priority ∈ high | medium | low
    """
    recs: list[dict] = []
    if df.empty:
        return recs

    try:
        sav_rate  = _savings_rate(df)
        cat_pcts  = _category_pct(df)
        deb       = _debits(df)
        monthly_exp = _monthly_expense(df)
        avg_monthly = monthly_exp.mean() if not monthly_exp.empty else 0

        # ── 1. Savings rate below benchmark ──────────────────────
        if sav_rate < 20:
            gap = 20 - sav_rate
            inc = _credits(df)["Amount"].mean() if not _credits(df).empty else 0
            monthly_savings_needed = inc * gap / 100 if inc > 0 else 0
            recs.append({
                "icon": "💡",
                "title": "Boost Your Savings Rate",
                "body": f"Your savings rate is <b>{sav_rate:.1f}%</b> — below the recommended 20%. "
                        f"Redirecting an extra <b>₹{monthly_savings_needed:,.0f}/month</b> into savings "
                        "would bring you in line with the 20% benchmark.",
                "priority": "high"
            })

        # ── 2. Top-category reduction opportunity ─────────────────
        if cat_pcts:
            top_cat, top_pct = max(cat_pcts.items(), key=lambda x: x[1])
            if top_pct > 30:
                potential_saving = avg_monthly * top_pct / 100 * 0.15
                recs.append({
                    "icon": "✂️",
                    "title": f"Trim {top_cat} Spending",
                    "body": f"<b>{top_cat}</b> accounts for {top_pct:.1f}% of your total expenses. "
                            f"A modest <b>15% reduction</b> in this category alone could save you "
                            f"<b>₹{potential_saving:,.0f}/month</b>.",
                    "priority": "high"
                })

        # ── 3. Transport above average ────────────────────────────
        transport_cats = [c for c in cat_pcts if any(k in c.lower()
                          for k in ["transport", "travel", "uber", "cab", "fuel", "petrol", "commute"])]
        for tc in transport_cats:
            if cat_pcts[tc] > 15:
                recs.append({
                    "icon": "🚗",
                    "title": "Transport Expenses Are Above Average",
                    "body": f"<b>{tc}</b> is using {cat_pcts[tc]:.1f}% of your budget — higher than typical. "
                            "Consider carpooling, public transit, or consolidating trips to reduce this.",
                    "priority": "medium"
                })

        # ── 4. Entertainment capping ──────────────────────────────
        ent_total = sum(v for k, v in cat_pcts.items()
                        if any(kw in k.lower() for kw in ["entertainment", "leisure", "movies", "gaming"]))
        if ent_total > 15:
            recs.append({
                "icon": "🎬",
                "title": "Cap Entertainment Spending",
                "body": f"Entertainment categories total <b>{ent_total:.1f}%</b> of expenses. "
                        "A soft cap of 10% is a common financial planning guideline. "
                        "Consider choosing 1–2 paid subscriptions and cancelling the rest.",
                "priority": "medium"
            })

        # ── 5. Emergency fund recommendation ─────────────────────
        if sav_rate < 5:
            recs.append({
                "icon": "🛡️",
                "title": "Build an Emergency Fund First",
                "body": "With a very low savings rate, your first priority should be building a "
                        "<b>3-month emergency fund</b>. This provides a safety net before any "
                        "investment goals.",
                "priority": "high"
            })

        # ── 6. SIP / investment suggestion for good savers ────────
        if sav_rate >= 25:
            monthly_surplus = (_monthly_income(df).mean() - _monthly_expense(df).mean())
            sip_amount = round(monthly_surplus * 0.5 / 1000) * 1000
            recs.append({
                "icon": "📊",
                "title": "Consider Investing Your Surplus",
                "body": f"Your strong savings rate of <b>{sav_rate:.1f}%</b> means you have room to invest. "
                        f"Starting a SIP of <b>₹{sip_amount:,.0f}/month</b> in an index fund could "
                        "significantly grow your wealth over 5–10 years.",
                "priority": "low"
            })

        # ── 7. Savings allocation reminder ────────────────────────
        if 10 <= sav_rate < 20:
            recs.append({
                "icon": "💰",
                "title": "Increase Savings Allocation",
                "body": "You're saving, which is great — but there's room to improve. "
                        "Try the <b>50/30/20 rule</b>: 50% needs, 30% wants, 20% savings. "
                        "Even a 5% increase in savings rate makes a major long-term difference.",
                "priority": "medium"
            })

    except Exception:
        pass

    return recs


def render_recommendation_card(rec: dict) -> str:
    """Return HTML for a premium coaching recommendation card."""
    priority_styles = {
        "high":   ("rgba(239,68,68,.12)",  "rgba(239,68,68,.5)",  "#ef4444", "🔴 HIGH PRIORITY"),
        "medium": ("rgba(245,158,11,.10)", "rgba(245,158,11,.4)", "#f59e0b", "🟡 MEDIUM PRIORITY"),
        "low":    ("rgba(16,185,129,.10)", "rgba(16,185,129,.4)", "#10b981", "🟢 OPPORTUNITY"),
    }
    bg, border, color, badge = priority_styles.get(rec["priority"], priority_styles["medium"])
    return f"""
    <div style="background:linear-gradient(135deg,{bg},rgba(15,23,42,.9));
        border:1.5px solid {border};border-radius:18px;padding:22px 26px;
        margin-bottom:14px;box-shadow:0 6px 24px rgba(0,0,0,.25);">
        <div style="display:flex;align-items:flex-start;gap:14px;">
            <div style="font-size:1.8rem;flex-shrink:0;filter:drop-shadow(0 0 6px {color});">
                {rec['icon']}</div>
            <div style="flex:1;">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
                    <div style="font-size:1rem;font-weight:900;color:#f0f9ff;
                        font-family:Inter,sans-serif;">{rec['title']}</div>
                    <span style="font-size:.65rem;font-weight:800;letter-spacing:.08em;
                        background:{bg};border:1px solid {border};color:{color};
                        border-radius:20px;padding:2px 8px;">{badge}</span>
                </div>
                <div style="color:#cbd5e1;font-size:.9rem;font-weight:600;line-height:1.65;">
                    {rec['body']}</div>
            </div>
        </div>
    </div>"""


# ─────────────────────────────────────────────────────────────────
#  5. BUDGET PROGRESS (kept from original, enhanced)
# ─────────────────────────────────────────────────────────────────

def build_budget_progress_html(
    budgets: pd.DataFrame,
    cat_spent: pd.Series,
) -> tuple[list[str], str]:
    """
    Build budget progress cards for the Tracker overview.
    Returns (list_of_card_html_strings, summary_html_string).
    (Preserved from original — Tracker only.)
    """
    cards: list[str] = []
    total_budget = 0.0
    total_spent  = 0.0

    for _, row in budgets.iterrows():
        cat     = row["category"]
        budget  = float(row["budget_amount"])
        spent   = float(cat_spent.get(cat, 0))
        pct     = min((spent / budget * 100) if budget > 0 else 0, 100)
        rem     = budget - spent
        over    = spent > budget

        if over:
            bar_color, status_icon = "#ef4444", "🔴"
        elif pct >= 80:
            bar_color, status_icon = "#f59e0b", "🟡"
        else:
            bar_color, status_icon = "#10b981", "🟢"

        cards.append(f"""
        <div style="background:linear-gradient(135deg,#FFFFFF,#FFF9FF);
            border:2px solid {'#FECACA' if over else '#F9A8D4'};
            border-radius:16px;padding:14px 18px;margin-bottom:10px;
            box-shadow:0 4px 16px rgba(249,168,212,.15);">
            <div style="display:flex;justify-content:space-between;align-items:center;
                margin-bottom:6px;">
                <div style="font-weight:800;color:#1A1A2E;font-size:.93rem;">{status_icon} {cat}</div>
                <div style="font-size:.82rem;font-weight:800;
                    color:{'#dc2626' if over else '#9d174d'};">
                    ₹{spent:,.0f} / ₹{budget:,.0f}</div>
            </div>
            <div style="background:#F3F4F6;border-radius:8px;height:8px;overflow:hidden;">
                <div style="width:{pct:.1f}%;height:100%;background:{bar_color};
                    border-radius:8px;transition:width .4s;"></div>
            </div>
            <div style="margin-top:5px;font-size:.76rem;font-weight:700;
                color:{'#dc2626' if over else '#6b7280'};">
                {'⚠️ Over by ₹' + f'{abs(rem):,.0f}' if over else f'₹{rem:,.0f} remaining'}
            </div>
        </div>""")

        total_budget += budget
        total_spent  += spent

    over_total = total_spent > total_budget
    pct_total  = min((total_spent / total_budget * 100) if total_budget > 0 else 0, 100)

    summary_html = f"""
    <div style="background:linear-gradient(135deg,{'#FEF2F2' if over_total else '#F0FDF4'},
        {'#FECACA' if over_total else '#DCFCE7'});
        border:2px solid {'#FECACA' if over_total else '#6EE7B7'};
        border-radius:14px;padding:12px 18px;margin-top:8px;text-align:center;">
        <div style="font-weight:900;font-size:.88rem;color:{'#dc2626' if over_total else '#065f46'};">
            {'⚠️ OVER BUDGET' if over_total else '✅ WITHIN BUDGET'} — 
            ₹{total_spent:,.0f} of ₹{total_budget:,.0f} ({pct_total:.1f}%)
        </div>
    </div>"""

    return cards, summary_html


# ─────────────────────────────────────────────────────────────────
#  LEGACY COMPATIBILITY LAYER
#  These functions are called by analyzer_engine.py and charts.py.
#  Do NOT remove — they keep the existing engine working.
# ─────────────────────────────────────────────────────────────────

def build_pie_data(cat_df: pd.DataFrame) -> pd.DataFrame:
    """
    Called by analyzer_engine.build_analytics_payload().
    Converts a category-aggregated DataFrame into a pie-ready DataFrame.
    Returns a DataFrame with the same structure as the input (passthrough),
    since analyzer_engine.py checks .empty and iterates rows itself.
    """
    try:
        if cat_df is None or cat_df.empty:
            return pd.DataFrame()
        return cat_df.copy()
    except Exception:
        return pd.DataFrame()


def build_budget_chart_data(
    budgets: pd.DataFrame,
    cat_spent: pd.Series,
) -> list[dict]:
    """
    Called by the Tracker budgets page to feed bar_budget_vs_actual().
    Returns a list of {category, budget, spent} dicts.
    """
    result = []
    try:
        for _, row in budgets.iterrows():
            cat    = row["category"]
            budget = float(row["budget_amount"])
            spent  = float(cat_spent.get(cat, 0))
            result.append({"category": cat, "budget": budget, "spent": spent})
    except Exception:
        pass
    return result