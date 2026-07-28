"""
INRIPE DM TRACKING — CALCULATION ENGINE v6
Pure Python/pandas. No streamlit, no plotly. Importable and testable standalone.

Every number rendered by app.py is produced here, so the numbers can be verified
without running the UI. app.py contains presentation only.

Design rules enforced in this module
------------------------------------
R1  Missing is not zero.        -> None propagates; never scored as 0%.
R2  One basis per number.       -> every ratio carries an explicit `basis` label.
R3  Polarity is declared.       -> inverse metrics never green-flag an overrun.
R4  Totals are reconciled.      -> every headline figure is recomputed a second way.
R5  Coverage gates scoring.     -> thin data greys out, it does not turn red.
"""

from __future__ import annotations

import calendar
import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────────
# SCHEMA CONSTANTS — the vocabulary gap between T2 and T3 lives here only
# ─────────────────────────────────────────────────────────────────────

ACTUAL_PLATFORMS = ["API", "Meta API", "Meta Ecom"]

# actual platform -> the platform label targets use
PLATFORM_TO_TARGET = {"API": "API", "Meta API": "Meta", "Meta Ecom": "Meta"}

# Targets are set at Meta level, so the two Meta platforms must roll up before
# any plan comparison. Consolidated is the default; split is a drill-down.
CHANNEL_GROUPS = {
    "API": ["API"],
    "Meta": ["Meta API", "Meta Ecom"],
}
CHANNEL_ORDER = ["API", "Meta"]
# TikTok carries targets in T3 but has never reported an actual. It is excluded
# from channel views on purpose; planned_only_channels() reports it so a planned
# channel with no delivery is visible rather than silently missing.


def planned_only_channels(t3, market, month, year) -> list:
    """Channels that have a plan but no way to report actuals."""
    d = _scope(t3, None if market in (None, "All") else market, month, year)
    planned = set(d[d["Metric"] == TGT_ORDERS]["Platform"].unique())
    return sorted(planned - set(CHANNEL_GROUPS) - {"Total"})

# orders are named differently per platform in T2
ORDER_METRIC = {"API": "Total Orders", "Meta API": "Orders", "Meta Ecom": "Orders"}
ORDER_METRICS_ALL = ["Total Orders", "Orders"]

REVENUE = "Revenue (AED)"
SPEND = "Budget Spent"
UNITS = "Units"
MSG_CUST = "Messages to Customers"
MSG_LEAD = "Messages to Leads"
MSG_RECV = "Messages Received"

TGT_ORDERS = "Target Orders"
TGT_REVENUE = "Target Revenue"
TGT_API_REVENUE = "API Revenue (AED)"
TGT_UNITS = "Target Units"
TGT_BUDGET = "Budget"
TGT_MESSAGES = "Messages Required"
TGT_CR = "CR%"

# RAG thresholds. (green_at, amber_at) as fractions of the comparison basis.
TH_UP = (0.90, 0.70)        # higher is better: >=90% green, >=70% amber
TH_DOWN = (1.05, 1.20)      # lower is better:  <=105% green, <=120% amber
TH_SPEND = (0.90, 1.05, 0.70, 1.15)   # (lo_green, hi_green, lo_amber, hi_amber)

COVERAGE_MIN = 0.90         # below this share of elapsed days, scoring is greyed
AOV_TOLERANCE = 0.10        # price divergence beyond this trips the integrity flag
CORR_WEAK, CORR_STRONG = 0.30, 0.60

GREEN, AMBER, RED, GREY, BLUE = "#1A6B4A", "#854F0B", "#A32D2D", "#8A8A8A", "#1B4F8A"


# ─────────────────────────────────────────────────────────────────────
# FORMATTING — R1: None and 0 are different things
# ─────────────────────────────────────────────────────────────────────

def fmt(n, prefix: str = "", suffix: str = "", dec: int = 0) -> str:
    """Format a number. None -> 'n/a'. Zero -> '0', never 'n/a'.

    Uses one decimal on K/M so 2,918 and 3,345 do not both render '3K'.
    """
    if n is None or (isinstance(n, float) and np.isnan(n)):
        return "n/a"
    if abs(n) >= 1_000_000:
        return f"{prefix}{n / 1_000_000:.2f}M{suffix}"
    if abs(n) >= 10_000:
        return f"{prefix}{n / 1_000:.1f}K{suffix}"
    if abs(n) >= 1_000:
        return f"{prefix}{n:,.0f}{suffix}"
    return f"{prefix}{n:,.{dec}f}{suffix}"


def pct(a, b) -> Optional[float]:
    """a as a percentage of b. None if either side is unusable."""
    if a is None or b in (None, 0) or (isinstance(b, float) and np.isnan(b)):
        return None
    return a / b * 100.0


def fmt_pct(a, b, dec: int = 0) -> str:
    v = pct(a, b)
    return "n/a" if v is None else f"{v:.{dec}f}%"


def delta_pct(a, b) -> Optional[float]:
    """True delta: (a-b)/b. Identical inputs give 0.0, not 100."""
    if a is None or b in (None, 0):
        return None
    return (a - b) / b * 100.0


def safe_div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


# ─────────────────────────────────────────────────────────────────────
# RAG — R3: polarity is declared, never inferred
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Verdict:
    label: str
    color: str
    ratio: Optional[float]
    basis: str
    scored: bool = True
    note: str = ""


def rag(actual, basis_value, direction: str = "up", basis: str = "",
        gated: bool = False, gate_note: str = "") -> Verdict:
    """Score `actual` against `basis_value`.

    direction:
        'up'    higher is better (orders, revenue, ROAS, CR%, basket)
        'down'  lower is better  (CAC)
        'spend' band around 100% (budget spent, burn%) - overrun is never green,
                and heavy underspend is flagged too
    gated: coverage too thin to score -> grey, no colour verdict (R5)
    """
    if gated:
        return Verdict("n/a", GREY, None, basis, scored=False, note=gate_note)
    r = pct(actual, basis_value)
    if r is None:
        return Verdict("n/a", GREY, None, basis, scored=False, note="no basis")

    if direction == "up":
        g, a = TH_UP[0] * 100, TH_UP[1] * 100
        if r >= g:
            return Verdict(f"{r:.0f}% OK", GREEN, r, basis)
        if r >= a:
            return Verdict(f"{r:.0f}% WATCH", AMBER, r, basis)
        return Verdict(f"{r:.0f}% MISS", RED, r, basis)

    if direction == "down":
        g, a = TH_DOWN[0] * 100, TH_DOWN[1] * 100
        if r <= g:
            return Verdict(f"{r:.0f}% OK", GREEN, r, basis)
        if r <= a:
            return Verdict(f"{r:.0f}% WATCH", AMBER, r, basis)
        return Verdict(f"{r:.0f}% OVER", RED, r, basis)

    if direction == "neutral":
        # Spend, burn and message volume are inputs, not outcomes. Spending more
        # is neither good nor bad on its own - CAC and ROAS judge whether it
        # bought anything. These report magnitude and never a verdict.
        return Verdict(f"{r:.0f}% of {basis or 'plan'}", GREY, r, basis, scored=False)

    if direction == "spend":
        lo_g, hi_g, lo_a, hi_a = (TH_SPEND[0] * 100, TH_SPEND[1] * 100,
                                  TH_SPEND[2] * 100, TH_SPEND[3] * 100)
        if lo_g <= r <= hi_g:
            return Verdict(f"{r:.0f}% OK", GREEN, r, basis)
        if r > hi_a:
            return Verdict(f"{r:.0f}% OVER", RED, r, basis)
        if r < lo_a:
            return Verdict(f"{r:.0f}% UNDER", RED, r, basis)
        if r > hi_g:
            return Verdict(f"{r:.0f}% OVER", AMBER, r, basis)
        return Verdict(f"{r:.0f}% UNDER", AMBER, r, basis)

    raise ValueError(f"unknown direction {direction!r}")


# A ratio beyond this cannot be a real result - it is a data entry fault.
IMPLAUSIBLE_RATIO = 300.0


def plausible(actual, ratio, key) -> tuple[bool, str]:
    """Catch data-entry faults before they are rendered as a verdict.

    An extra zero or a value typed into the wrong column is the most common real
    error in a hand-maintained workbook, and without this it renders green.
    """
    if ratio is not None and ratio > IMPLAUSIBLE_RATIO:
        return False, f"{ratio:,.0f}% of plan is not a real result"
    if key in ("cac",) and actual is not None and actual <= 0:
        return False, "acquisition cost cannot be zero"
    if key in ("cr_api", "cr_meta") and actual is not None and actual > 100:
        return False, "conversion rate cannot exceed 100%"
    if key in ("roas",) and actual is not None and actual > 500:
        return False, f"{actual:,.0f}x return is not a real result"
    return True, ""


def corr_band(r: Optional[float]) -> str:
    """R2: one definition of weak/moderate/strong, used everywhere."""
    if r is None or (isinstance(r, float) and np.isnan(r)):
        return "insufficient data"
    a = abs(r)
    if a < CORR_WEAK:
        return "weak"
    if a < CORR_STRONG:
        return "moderate"
    return "strong"


# ─────────────────────────────────────────────────────────────────────
# LOAD
# ─────────────────────────────────────────────────────────────────────

def load_data(path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read T2. Actuals and T3. Targets. Header sits on sheet row 2."""
    t2 = pd.read_excel(path, sheet_name="T2. Actuals", skiprows=1)
    t2 = t2[["Date", "Market", "Platform", "Metric", "Value"]].copy()
    t2["Date"] = pd.to_datetime(t2["Date"], errors="coerce")
    t2["Value"] = pd.to_numeric(t2["Value"], errors="coerce")
    t2 = t2.dropna(subset=["Date", "Market", "Platform", "Metric"])
    # R1: a blank Value is missing, not zero -> drop the row, do not coerce to 0
    t2 = t2.dropna(subset=["Value"])
    t2["Market"] = t2["Market"].astype(str)
    t2["Platform"] = t2["Platform"].astype(str)
    t2["Metric"] = t2["Metric"].astype(str)
    t2["Month"] = t2["Date"].dt.month
    t2["Year"] = t2["Date"].dt.year
    t2["Day"] = t2["Date"].dt.date

    t3 = pd.read_excel(path, sheet_name="T3. Targets", skiprows=1)
    t3 = t3[["Market", "Month", "Platform", "Metric", "Target Value"]].copy()
    t3.columns = ["Market", "Month", "Platform", "Metric", "Value"]
    t3["Month"] = pd.to_datetime(t3["Month"], errors="coerce")
    t3["Value"] = pd.to_numeric(t3["Value"], errors="coerce")
    t3 = t3.dropna(subset=["Month", "Market", "Platform", "Metric"])
    t3 = t3.dropna(subset=["Value"])
    for c in ("Market", "Platform", "Metric"):
        t3[c] = t3[c].astype(str)
    t3["MonthNum"] = t3["Month"].dt.month
    t3["Year"] = t3["Month"].dt.year
    return t2, t3


# ─────────────────────────────────────────────────────────────────────
# SCOPED ACCESSORS
# ─────────────────────────────────────────────────────────────────────

def _scope(df, market=None, month=None, year=None, platform=None):
    d = df
    if market and market != "All":
        d = d[d["Market"] == market]
    if month is not None:
        col = "Month" if "Day" in df.columns else "MonthNum"
        d = d[d[col] == month]
    if year is not None:
        d = d[d["Year"] == year]
    if platform:
        d = d[d["Platform"] == platform]
    return d


def actual(t2, metric, market=None, month=None, year=None, platform=None,
           date_range=None) -> Optional[float]:
    """Sum an actual metric. Returns None when no rows exist (R1)."""
    d = _scope(t2, market, month, year, platform)
    if date_range:
        d = d[(d["Date"] >= pd.Timestamp(date_range[0])) &
              (d["Date"] <= pd.Timestamp(date_range[1]))]
    d = d[d["Metric"] == metric] if isinstance(metric, str) else d[d["Metric"].isin(metric)]
    return None if d.empty else float(d["Value"].sum())


def target(t3, metric, market=None, month=None, year=None, platform=None) -> Optional[float]:
    d = _scope(t3, market, month, year, platform)
    d = d[d["Metric"] == metric]
    return None if d.empty else float(d["Value"].sum())


def total_orders(t2, **kw) -> Optional[float]:
    """Orders across all platforms. 'Total Orders' is the API platform's own
    label, not a grand total - summing both names is correct, not double counting."""
    return actual(t2, ORDER_METRICS_ALL, **kw)


def daily_orders_series(t2, market=None, month=None, year=None) -> pd.Series:
    d = _scope(t2, market, month, year)
    d = d[d["Metric"].isin(ORDER_METRICS_ALL)]
    if d.empty:
        return pd.Series(dtype=float)
    return d.groupby("Date")["Value"].sum().sort_index()


def daily_metric_series(t2, metric, market=None, month=None, year=None) -> pd.Series:
    d = _scope(t2, market, month, year)
    d = d[d["Metric"] == metric]
    if d.empty:
        return pd.Series(dtype=float)
    return d.groupby("Date")["Value"].sum().sort_index()


# ─────────────────────────────────────────────────────────────────────
# COVERAGE — R5
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Coverage:
    days_in_month: int
    days_elapsed: int              # distinct calendar dates carrying any entry
    days_remaining: int
    per_market: dict = field(default_factory=dict)   # market -> (entries, active)

    def gate(self, market: Optional[str]) -> tuple[bool, str]:
        """True when this market's data is too thin to score."""
        if not market or market == "All":
            return False, ""
        entries, _active = self.per_market.get(market, (0, 0))
        if self.days_elapsed == 0:
            return True, "no data"
        share = entries / self.days_elapsed
        if share < COVERAGE_MIN:
            return True, f"only {entries}/{self.days_elapsed} days reported"
        return False, ""


def build_coverage(t2, month, year) -> Coverage:
    d = _scope(t2, None, month, year)
    dim = calendar.monthrange(year, month)[1]
    elapsed = int(d["Day"].nunique()) if not d.empty else 0
    per = {}
    for m in sorted(d["Market"].unique()):
        dm = d[d["Market"] == m]
        entries = int(dm["Day"].nunique())
        od = dm[dm["Metric"].isin(ORDER_METRICS_ALL)].groupby("Day")["Value"].sum()
        active = int((od > 0).sum())
        per[m] = (entries, active)
    return Coverage(dim, elapsed, max(dim - elapsed, 0), per)


# ─────────────────────────────────────────────────────────────────────
# TREND / MOMENTUM — R2: one window definition, shared by every panel
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Momentum:
    recent: Optional[float]
    prior: Optional[float]
    window: int
    label: str          # 'accelerating' | 'slowing' | 'steady' | 'insufficient'
    arrow: str          # up / down / flat


def momentum(series: pd.Series, window: int = 7) -> Momentum:
    """Last `window` days vs the `window` days before them.

    Deliberately not first-half vs second-half: on a 27-day month that compares
    a 13-day-old average against a 14-day-old one and reports the state of the
    month a fortnight ago as if it were current.
    """
    v = [x for x in series.values]
    if len(v) < 4:
        return Momentum(None, None, window, "insufficient", "flat")
    w = min(window, len(v) // 2)
    recent = float(np.mean(v[-w:]))
    prior = float(np.mean(v[-2 * w:-w]))
    if prior == 0:
        return Momentum(recent, prior, w, "insufficient", "flat")
    if recent > prior * 1.05:
        return Momentum(recent, prior, w, "accelerating", "up")
    if recent < prior * 0.95:
        return Momentum(recent, prior, w, "slowing", "down")
    return Momentum(recent, prior, w, "steady", "flat")


# ─────────────────────────────────────────────────────────────────────
# THE SNAPSHOT
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Line:
    """One metric row. Carries its own basis and polarity so no consumer
    has to guess which comparison produced the verdict (R2/R3)."""
    key: str
    label: str
    actual: Optional[float]
    plan: Optional[float]
    paced: Optional[float]
    eom: Optional[float]
    direction: str
    basis: str              # 'paced' | 'plan'
    prefix: str = ""
    suffix: str = ""
    dec: int = 0
    verdict: Optional[Verdict] = None
    eom_vs_plan: Optional[float] = None
    trend: str = "flat"


@dataclass
class Snapshot:
    market: str
    month: int
    year: int
    month_name: str
    coverage: Coverage
    lines: list
    momentum: Momentum
    integrity: list
    raw: dict

    def line(self, key) -> Optional[Line]:
        return next((l for l in self.lines if l.key == key), None)


def _pace(plan, cov: Coverage):
    if plan is None or cov.days_in_month == 0:
        return None
    return plan * cov.days_elapsed / cov.days_in_month


def _eom(act, cov: Coverage):
    if act is None or cov.days_elapsed == 0:
        return None
    return act / cov.days_elapsed * cov.days_in_month


def build_snapshot(t2, t3, market, month, year) -> Snapshot:
    mkt = None if market in (None, "All") else market
    cov = build_coverage(t2, month, year)
    gated, gate_note = cov.gate(mkt)

    A = lambda metric, **kw: actual(t2, metric, market=mkt, month=month, year=year, **kw)
    T = lambda metric, plat: target(t3, metric, market=mkt, month=month, year=year, platform=plat)

    # ── actuals ──────────────────────────────────────────────────────
    ord_api = A(ORDER_METRIC["API"], platform="API")
    ord_meta_api = A(ORDER_METRIC["Meta API"], platform="Meta API")
    ord_meta_ecom = A(ORDER_METRIC["Meta Ecom"], platform="Meta Ecom")
    ord_tot = total_orders(t2, market=mkt, month=month, year=year)
    ord_meta = _nsum(ord_meta_api, ord_meta_ecom)

    units = A(UNITS)
    rev = A(REVENUE)
    spend = A(SPEND)
    rev_api = A(REVENUE, platform="API")
    spend_api = A(SPEND, platform="API")

    msg_cust = A(MSG_CUST, platform="API")
    msg_lead = A(MSG_LEAD, platform="API")
    msg_api = _nsum(msg_cust, msg_lead)
    msg_recv = A(MSG_RECV, platform="Meta API")

    roas = safe_div(rev, spend)
    cac = safe_div(spend, ord_tot)
    basket = safe_div(units, ord_tot)
    cr_api = pct(ord_api, msg_api)
    cr_meta = pct(ord_meta_api, msg_recv)
    aov = safe_div(rev, ord_tot)
    price_per_unit = safe_div(rev, units)

    # ── targets ──────────────────────────────────────────────────────
    plan_ord = T(TGT_ORDERS, "Total")
    plan_units = T(TGT_UNITS, "Total")
    plan_rev = T(TGT_REVENUE, "Total")
    plan_bud = T(TGT_BUDGET, "Total")
    plan_ord_api = T(TGT_ORDERS, "API")
    plan_bud_api = T(TGT_BUDGET, "API")
    plan_msg_api = T(TGT_MESSAGES, "API")
    plan_ord_meta = T(TGT_ORDERS, "Meta")
    plan_bud_meta = T(TGT_BUDGET, "Meta")
    plan_rev_api = T(TGT_API_REVENUE, "API")

    plan_roas = safe_div(plan_rev, plan_bud)
    plan_cac = safe_div(plan_bud, plan_ord)
    plan_basket = safe_div(plan_units, plan_ord)
    plan_price = safe_div(plan_rev, plan_units)
    plan_aov = safe_div(plan_rev, plan_ord)
    plan_cr_api = pct(plan_ord_api, plan_msg_api)

    burn = pct(spend, plan_bud)
    burn_expected = pct(cov.days_elapsed, cov.days_in_month)

    daily_series = daily_orders_series(t2, mkt, month, year)
    mom = momentum(daily_series)
    daily_actual = safe_div(ord_tot, cov.days_elapsed)
    daily_target = safe_div(plan_ord, cov.days_in_month)
    gap = None if (plan_ord is None or ord_tot is None) else plan_ord - ord_tot
    need_daily = safe_div(gap, cov.days_remaining) if cov.days_remaining > 0 else None

    def mk(key, label, act, plan, direction, basis, prefix="", suffix="", dec=0,
           paced_override="auto", eom_override="auto"):
        paced = _pace(plan, cov) if paced_override == "auto" else paced_override
        em = _eom(act, cov) if eom_override == "auto" else eom_override
        basis_val = paced if basis == "paced" else plan
        v = rag(act, basis_val, direction, basis, gated, gate_note)
        ok, why = plausible(act, v.ratio, key)
        if not ok:
            v = Verdict("CHECK DATA", RED, v.ratio, basis, scored=False, note=why)
        ln = Line(key, label, act, plan, paced, em, direction, basis,
                  prefix, suffix, dec, v, pct(em, plan))
        ln.trend = _trend_for(t2, key, mkt, month, year)
        return ln

    lines = [
        mk("orders", "Orders", ord_tot, plan_ord, "up", "paced"),
        mk("units", "Units", units, plan_units, "up", "paced"),
        mk("revenue", "Revenue", rev, plan_rev, "up", "paced", prefix="AED "),
        mk("spend", "Budget spent", spend, plan_bud, "neutral", "paced", prefix="AED "),
        # ratios have no meaningful pace or EOM run-rate: compared to plan directly
        mk("roas", "ROAS", roas, plan_roas, "up", "plan", suffix="x", dec=1,
           paced_override=None, eom_override=None),
        mk("cac", "CAC", cac, plan_cac, "down", "plan", prefix="AED ", dec=1,
           paced_override=None, eom_override=None),
        mk("cr_api", "CR% API", cr_api, plan_cr_api, "up", "plan", suffix="%", dec=2,
           paced_override=None, eom_override=None),
        mk("cr_meta", "CR% Meta API", cr_meta, None, "up", "plan", suffix="%", dec=2,
           paced_override=None, eom_override=None),
        mk("burn", "Budget burn%", burn, burn_expected, "neutral", "plan", suffix="%", dec=0,
           paced_override=None, eom_override=None),
        mk("daily_orders", "Daily orders", daily_actual, daily_target, "up", "plan", dec=0,
           paced_override=None, eom_override=None),
    ]

    raw = dict(
        ord_api=ord_api, ord_meta_api=ord_meta_api, ord_meta_ecom=ord_meta_ecom,
        ord_meta=ord_meta, ord_tot=ord_tot, units=units, rev=rev, spend=spend,
        rev_api=rev_api, spend_api=spend_api,
        msg_cust=msg_cust, msg_lead=msg_lead, msg_api=msg_api, msg_recv=msg_recv,
        roas=roas, cac=cac, basket=basket, aov=aov, price_per_unit=price_per_unit,
        cr_api=cr_api, cr_meta=cr_meta,
        plan_ord=plan_ord, plan_units=plan_units, plan_rev=plan_rev, plan_bud=plan_bud,
        plan_ord_api=plan_ord_api, plan_bud_api=plan_bud_api, plan_msg_api=plan_msg_api,
        plan_ord_meta=plan_ord_meta, plan_bud_meta=plan_bud_meta, plan_rev_api=plan_rev_api,
        plan_roas=plan_roas, plan_cac=plan_cac, plan_basket=plan_basket,
        plan_price=plan_price, plan_aov=plan_aov, plan_cr_api=plan_cr_api,
        burn=burn, burn_expected=burn_expected,
        daily_actual=daily_actual, daily_target=daily_target,
        need_daily=need_daily, gap=gap,
        roas_api=safe_div(rev_api, spend_api),
        daily_series=daily_series,
        gated=gated, gate_note=gate_note,
    )

    integ = run_integrity(t2, t3, mkt, month, year, raw, cov)

    return Snapshot(market or "All", month, year, calendar.month_abbr[month],
                    cov, lines, mom, integ, raw)


def _nsum(*vals):
    """Sum that keeps None when every input is missing."""
    present = [v for v in vals if v is not None]
    return None if not present else float(sum(present))


_TREND_METRIC = {
    "orders": ORDER_METRICS_ALL, "revenue": REVENUE, "spend": SPEND,
    "units": UNITS, "daily_orders": ORDER_METRICS_ALL,
}


def _trend_for(t2, key, market, month, year) -> str:
    """R2: every trend arrow in the app comes from this one function, so the
    snapshot and the scorecard cannot disagree about which way a metric moved."""
    met = _TREND_METRIC.get(key)
    if met is None:
        return "flat"
    d = _scope(t2, market, month, year)
    d = d[d["Metric"].isin(met)] if isinstance(met, list) else d[d["Metric"] == met]
    if d.empty:
        return "flat"
    s = d.groupby("Date")["Value"].sum().sort_index()
    return momentum(s).arrow


# ─────────────────────────────────────────────────────────────────────
# INTEGRITY CHECKS — R4
# ─────────────────────────────────────────────────────────────────────

def run_integrity(t2, t3, market, month, year, raw, cov: Coverage) -> list:
    """Self-audit. Every headline figure is recomputed a second, independent way.

    Deliberately contains no price or AOV test. P1 of the workbook records that the
    AOV concept was removed from this model: Target Units and Target Revenue are
    independent entries in P4 with no link between them, so their attainment
    percentages are not comparable and a divergence between them is not an error."""
    out = []

    def add(cid, name, ok, detail, severity="high"):
        out.append({"id": cid, "check": name, "pass": bool(ok),
                    "detail": detail, "severity": severity})

    # 1. Orders reconcile: platform sum vs daily-series sum
    ps = _nsum(raw["ord_api"], raw["ord_meta_api"], raw["ord_meta_ecom"])
    ds = float(raw["daily_series"].sum()) if len(raw["daily_series"]) else None
    ok = ps is not None and ds is not None and abs(ps - ds) < 0.5
    add("ORD_RECON", "Orders reconcile (platform sum = daily sum)", ok,
        f"platform {fmt(ps)} vs daily {fmt(ds)}")

    # 2. Revenue by market sums to total
    d = _scope(t2, market, month, year)
    rev_by_mkt = d[d["Metric"] == REVENUE]["Value"].sum()
    ok = raw["rev"] is not None and abs(rev_by_mkt - raw["rev"]) < 0.5
    add("REV_RECON", "Revenue reconciles across markets", ok,
        f"{fmt(rev_by_mkt, 'AED ')} vs {fmt(raw['rev'], 'AED ')}")

    # 3. Coverage
    ok = cov.days_elapsed <= cov.days_in_month and cov.days_elapsed > 0
    add("COVERAGE", "Elapsed days within month", ok,
        f"day {cov.days_elapsed} of {cov.days_in_month}")

    # 4. Per-market reporting completeness
    thin = [f"{m} {e}/{cov.days_elapsed}d"
            for m, (e, _a) in cov.per_market.items()
            if cov.days_elapsed and e / cov.days_elapsed < COVERAGE_MIN]
    add("MKT_COVERAGE", "All markets reporting full period", not thin,
        "all markets complete" if not thin else "thin: " + ", ".join(thin),
        severity="medium")

    # 5. Basket size sanity
    if None not in (raw["basket"], raw["plan_basket"]):
        ok = abs(raw["basket"] / raw["plan_basket"] - 1) <= 0.15
        add("BASKET", "Basket size near plan", ok,
            f"{raw['basket']:.2f} vs plan {raw['plan_basket']:.2f}", severity="medium")

    # 6. Targets exist for every market carrying actuals
    act_mkts = set(_scope(t2, None, month, year)["Market"].unique())
    tgt_mkts = set(_scope(t3, None, month, year)[
        lambda x: x["Metric"] == TGT_ORDERS]["Market"].unique())
    missing = sorted(act_mkts - tgt_mkts)
    add("TARGETS", "Targets present for all active markets", not missing,
        "complete" if not missing else "missing: " + ", ".join(missing))

    # 7. Plan internal consistency: channel targets should roll up to Total
    for m in sorted(act_mkts):
        tot = target(t3, TGT_ORDERS, m, month, year, "Total")
        parts = _nsum(*[target(t3, TGT_ORDERS, m, month, year, p)
                        for p in ("API", "Meta", "TikTok")])
        if tot and parts:
            ok = abs(tot - parts) / tot < 0.02
            add(f"ROLLUP_{m}", f"{m} channel targets roll up to Total", ok,
                f"channels {fmt(parts)} vs Total {fmt(tot)}", severity="medium")

    return out


# ─────────────────────────────────────────────────────────────────────
# COMMENTARY — every figure below is read from the snapshot, none retyped
# ─────────────────────────────────────────────────────────────────────

def build_commentary(s: Snapshot, gap: Optional[pd.DataFrame] = None) -> list:
    """Returns [(severity, text)] where severity is good|warn|risk|info."""
    r = s.raw
    cov = s.coverage
    out = []

    o = s.line("orders")
    vs_paced = pct(r["ord_tot"], o.paced)
    if vs_paced is None:
        out.append(("info", f"{s.market}: no order plan for {s.month_name}."))
    else:
        head = (f"Day {cov.days_elapsed} of {cov.days_in_month}: "
                f"{fmt(r['ord_tot'])} orders, {vs_paced:.0f}% of paced plan. "
                f"EOM run rate {fmt(o.eom)} = {fmt_pct(o.eom, o.plan)} of plan.")
        sev = "good" if vs_paced >= 90 else "warn" if vs_paced >= 70 else "risk"
        plural = s.market == "All"
        name = "All markets" if plural else s.market
        verb = "are" if plural else "is"
        state = ("on track" if sev == "good"
                 else "behind pace" if sev == "warn" else "significantly behind")
        out.append((sev, f"{name} {verb} {state} in {s.month_name}. {head}"))

        if r["need_daily"] and r["daily_target"]:
            above = (r["need_daily"] / r["daily_target"] - 1) * 100   # ABOVE, not "of"
            out.append(("risk" if above > 50 else "warn",
                        f"Closing the gap needs {r['need_daily']:.0f} orders/day for the "
                        f"remaining {cov.days_remaining} days, {above:.0f}% above the "
                        f"{r['daily_target']:.0f}/day plan rate."))

    m = s.momentum
    if m.label == "accelerating":
        out.append(("good", f"Momentum improving: last {m.window} days average "
                            f"{m.recent:.0f}/day vs {m.prior:.0f}/day in the {m.window} before."))
    elif m.label == "slowing":
        out.append(("warn", f"Momentum slowing: last {m.window} days average "
                            f"{m.recent:.0f}/day vs {m.prior:.0f}/day in the {m.window} before."))

    # channels
    if r["ord_api"] is not None and r["plan_ord_api"]:
        v = pct(r["ord_api"], _pace(r["plan_ord_api"], cov))
        sev = "good" if v >= 90 else "warn" if v >= 70 else "risk"
        extra = f" ROAS {r['roas_api']:.1f}x." if r["roas_api"] else ""
        out.append((sev, f"API {fmt(r['ord_api'])} orders, {v:.0f}% of paced plan.{extra}"))
    if r["ord_meta"] is not None and r["plan_ord_meta"]:
        v = pct(r["ord_meta"], _pace(r["plan_ord_meta"], cov))
        sev = "good" if v >= 90 else "warn" if v >= 70 else "risk"
        out.append((sev, f"Meta {fmt(r['ord_meta'])} orders, {v:.0f}% of paced plan."))

    # budget - never phrased as a win when overspending
    b = s.line("burn")
    if b.verdict and b.verdict.ratio is not None:
        if b.verdict.ratio > 115:
            out.append(("risk", f"Budget burn {r['burn']:.0f}% of plan at day "
                                f"{cov.days_elapsed}, ahead of the {r['burn_expected']:.0f}% "
                                f"expected. Overspending against plan."))
        elif b.verdict.ratio < 70:
            out.append(("warn", f"Budget under-deployed: {r['burn']:.0f}% spent vs "
                                f"{r['burn_expected']:.0f}% expected by day {cov.days_elapsed}."))

    # where the miss actually sits - the first question anyone asks
    if gap is not None and len(gap):
        behind = gap[gap["Gap (orders)"] > 0]
        if len(behind):
            tot = behind["Gap (orders)"].sum()
            top = behind.iloc[0]
            share = top["Gap (orders)"] / tot * 100 if tot > 0 else 0
            if share > 20:
                out.append(("risk",
                            f"Largest single gap is {top['Market']} {top['Channel']}: "
                            f"{top['Actual']:,} orders against {top['Paced plan']:,} paced, "
                            f"{share:.0f}% of the shortfall in this selection."))

    # integrity gets the last word, and it is loud
    for f in s.integrity:
        if not f["pass"] and f["severity"] == "high":
            out.append(("risk", f"Data integrity: {f['check']} FAILED - {f['detail']}. "
                                f"Treat affected figures as unverified."))
    return out


# ─────────────────────────────────────────────────────────────────────
# BREAKDOWN / COMPARISON HELPERS
# ─────────────────────────────────────────────────────────────────────

def market_channel_breakdown(t2, t3, month, year, cov: Coverage) -> pd.DataFrame:
    rows = []
    mkts = sorted(_scope(t2, None, month, year)["Market"].unique())
    for m in mkts:
        entries, _ = cov.per_market.get(m, (0, 0))
        gated = cov.days_elapsed and entries / cov.days_elapsed < COVERAGE_MIN
        for ch in ACTUAL_PLATFORMS + ["Total"]:
            if ch == "Total":
                o = total_orders(t2, market=m, month=month, year=year)
                rev = actual(t2, REVENUE, market=m, month=month, year=year)
                sp = actual(t2, SPEND, market=m, month=month, year=year)
                po = target(t3, TGT_ORDERS, m, month, year, "Total")
                pb = target(t3, TGT_BUDGET, m, month, year, "Total")
                cr = None
            else:
                o = actual(t2, ORDER_METRIC[ch], market=m, month=month, year=year, platform=ch)
                rev = actual(t2, REVENUE, market=m, month=month, year=year, platform=ch)
                sp = actual(t2, SPEND, market=m, month=month, year=year, platform=ch)
                tp = PLATFORM_TO_TARGET[ch]
                po = target(t3, TGT_ORDERS, m, month, year, tp)
                pb = target(t3, TGT_BUDGET, m, month, year, tp)
                if ch == "API":
                    msgs = _nsum(actual(t2, MSG_CUST, market=m, month=month, year=year, platform=ch),
                                 actual(t2, MSG_LEAD, market=m, month=month, year=year, platform=ch))
                    cr = pct(o, msgs)
                elif ch == "Meta API":
                    cr = pct(o, actual(t2, MSG_RECV, market=m, month=month, year=year, platform=ch))
                else:
                    cr = None
                # Meta targets cover both Meta platforms; do not compare one against both
                if ch in ("Meta API", "Meta Ecom"):
                    po = None
                    pb = None
            if o is None and sp is None:
                continue
            paced_o = _pace(po, cov)
            eom_o = _eom(o, cov)
            v = rag(o, paced_o, "up", "paced", gated,
                    f"{entries}/{cov.days_elapsed} days")
            rows.append({
                "Market": m, "Channel": ch,
                "Orders": None if o is None else int(o),
                "vs Paced": fmt_pct(o, paced_o),
                "EOM": None if eom_o is None else int(eom_o),
                "EOM vs Plan": fmt_pct(eom_o, po),
                "CR%": "n/a" if cr is None else f"{cr:.2f}%",
                "Revenue": None if rev is None else int(rev),
                "Spend": None if sp is None else int(sp),
                "Burn% (vs paced)": fmt_pct(sp, _pace(pb, cov)),
                "ROAS": "n/a" if safe_div(rev, sp) is None else f"{rev/sp:.1f}x",
                "CAC": "n/a" if safe_div(sp, o) is None else f"{sp/o:.1f}",
                "Coverage": f"{entries}/{cov.days_elapsed}d",
                "Orders RAG": v.label,
                "Spend RAG": rag(sp, _pace(pb, cov), "spend", "paced", gated,
                                 f"{entries}/{cov.days_elapsed} days").label,
            })
    return pd.DataFrame(rows)


def period_compare(t2, market, a_start, a_end, b_start, b_end) -> pd.DataFrame:
    mkt = None if market in (None, "All") else market

    def agg(metric, s, e, platform=None):
        return actual(t2, metric, market=mkt, platform=platform, date_range=(s, e))

    def block(s, e):
        o = agg(ORDER_METRICS_ALL, s, e)
        rev = agg(REVENUE, s, e)
        sp = agg(SPEND, s, e)
        msgs = _nsum(agg(MSG_CUST, s, e, "API"), agg(MSG_LEAD, s, e, "API"))
        oa = agg(ORDER_METRIC["API"], s, e, "API")
        days = max((e - s).days + 1, 1)
        return dict(orders=o, revenue=rev, spend=sp,
                    roas=safe_div(rev, sp), cac=safe_div(sp, o),
                    cr=pct(oa, msgs), daily=safe_div(o, days), days=days)

    A, B = block(a_start, a_end), block(b_start, b_end)
    spec = [("Orders", "orders", "up", "", 0), ("Revenue", "revenue", "up", "AED ", 0),
            ("Budget spent", "spend", "spend", "AED ", 0), ("ROAS", "roas", "up", "", 1),
            ("CAC", "cac", "down", "AED ", 1), ("API CR%", "cr", "up", "", 2),
            ("Orders/day", "daily", "up", "", 1)]
    rows = []
    for label, k, direction, pfx, dec in spec:
        d = delta_pct(A[k], B[k])
        if d is None:
            arrow = "n/a"
        elif abs(d) < 3:
            arrow = "flat"
        elif (d > 0) == (direction != "down"):
            arrow = "better"
        else:
            arrow = "worse"
        rows.append({"Metric": label,
                     "Period A": fmt(A[k], pfx, dec=dec),
                     "Period B": fmt(B[k], pfx, dec=dec),
                     "Δ% (A vs B)": "n/a" if d is None else f"{d:+.1f}%",
                     "Direction": arrow})
    return pd.DataFrame(rows)


def default_compare_periods(dates: list) -> tuple:
    """Period A = latest 7 days, Period B = the 7 before. A comparison that
    defaults both sides to the same range renders the section inert."""
    if not dates:
        return None, None, None, None
    ds = sorted(dates)
    a_end = ds[-1]
    a_start = ds[max(len(ds) - 7, 0)]
    b_end = a_start - _dt.timedelta(days=1)
    b_start = b_end - _dt.timedelta(days=6)
    if b_start < ds[0]:
        b_start = ds[0]
    return a_start, a_end, b_start, b_end


def daily_frame(t2, market, month, year) -> pd.DataFrame:
    """Per-day frame used by the correlation panels."""
    mkt = None if market in (None, "All") else market
    d = _scope(t2, mkt, month, year)
    if d.empty:
        return pd.DataFrame()
    rows = []
    for day, g in d.groupby("Day"):
        o = g[g["Metric"].isin(ORDER_METRICS_ALL)]["Value"].sum()
        oa = g[(g["Platform"] == "API") & (g["Metric"] == ORDER_METRIC["API"])]["Value"].sum()
        rev = g[g["Metric"] == REVENUE]["Value"].sum()
        sp = g[g["Metric"] == SPEND]["Value"].sum()
        msg = g[g["Metric"].isin([MSG_CUST, MSG_LEAD])]["Value"].sum()
        rows.append(dict(day=day, day_num=day.day, orders=o, api_orders=oa,
                         revenue=rev, spend=sp, messages=msg,
                         cac=safe_div(sp, o), roas=safe_div(rev, sp)))
    return pd.DataFrame(rows).sort_values("day_num")


def efficiency_points(t2, t3, month, year, market="All") -> list:
    """S8 bubble data. CR% here is API orders over API messages - the same
    definition the scorecard uses. Dividing all-channel orders by API-only
    messages inflates the rate and is why this panel used to disagree with S1."""
    mkts = sorted(_scope(t2, None, month, year)["Market"].unique())
    if market != "All":
        mkts = [market]
    out = []
    for m in mkts:
        o = total_orders(t2, market=m, month=month, year=year)
        oa = actual(t2, ORDER_METRIC["API"], market=m, month=month, year=year, platform="API")
        rev = actual(t2, REVENUE, market=m, month=month, year=year)
        sp = actual(t2, SPEND, market=m, month=month, year=year)
        msgs = _nsum(actual(t2, MSG_CUST, market=m, month=month, year=year, platform="API"),
                     actual(t2, MSG_LEAD, market=m, month=month, year=year, platform="API"))
        if not sp:
            continue
        out.append(dict(market=m, budget=sp, roas=safe_div(rev, sp),
                        cr_api=pct(oa, msgs), orders=o))
    return out


# ─────────────────────────────────────────────────────────────────────
# v7 — CHANNEL HIERARCHY, GAP ATTRIBUTION, GENERIC CHANNEL DRILL-DOWN
# ─────────────────────────────────────────────────────────────────────

def _chan_orders(t2, market, channel, month, year):
    """Orders for a channel group, summing its constituent platforms."""
    return _nsum(*[actual(t2, ORDER_METRIC[p], market=market, month=month,
                          year=year, platform=p)
                   for p in CHANNEL_GROUPS[channel]])


def _chan_metric(t2, metric, market, channel, month, year):
    return _nsum(*[actual(t2, metric, market=market, month=month, year=year,
                          platform=p) for p in CHANNEL_GROUPS[channel]])


def gap_contribution(t2, t3, month, year, cov: Coverage) -> pd.DataFrame:
    """Rank market x channel by how much of the shortfall each one owns.

    The scorecard says the month is behind. This says where, in orders and in
    AED, so the conversation starts at the cause rather than the symptom.
    """
    rows = []
    markets = sorted(_scope(t2, None, month, year)["Market"].unique())
    for m in markets:
        for ch in CHANNEL_ORDER:
            act = _chan_orders(t2, m, ch, month, year)
            plan = target(t3, TGT_ORDERS, m, month, year, ch)
            if plan is None:
                continue
            paced = _pace(plan, cov)
            act = act or 0.0
            gap = (paced or 0) - act
            spend = _chan_metric(t2, SPEND, m, ch, month, year) or 0.0
            rev = _chan_metric(t2, REVENUE, m, ch, month, year) or 0.0
            aov = safe_div(rev, act) if act else None
            rows.append({
                "Market": m, "Channel": ch,
                "Actual": int(act), "Paced plan": int(paced or 0),
                "Gap (orders)": int(round(gap)),
                "Gap (AED rev)": int(round(gap * aov)) if aov else None,
                "vs paced": pct(act, paced),
                "Spend": int(spend),
                "_gap": gap,
            })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    behind = df[df["_gap"] > 0]["_gap"].sum()
    df["Share of shortfall"] = df["_gap"].apply(
        lambda g: (g / behind * 100) if behind > 0 and g > 0 else 0.0)
    df = df.sort_values("_gap", ascending=False).drop(columns=["_gap"])
    return df


def channel_detail(t2, t3, channel, market, month, year, cov: Coverage) -> pd.DataFrame:
    """Metric detail for any channel. Replaces the hardcoded API section.

    Rows adapt to the channel: messaging metrics only appear where that channel
    reports them, rather than showing empty rows for channels that never had them.
    """
    mkt = None if market in (None, "All") else market
    plats = CHANNEL_GROUPS[channel]

    orders = _chan_orders(t2, mkt, channel, month, year)
    rev = _chan_metric(t2, REVENUE, mkt, channel, month, year)
    spend = _chan_metric(t2, SPEND, mkt, channel, month, year)
    plan_ord = target(t3, TGT_ORDERS, mkt, month, year, channel)
    plan_bud = target(t3, TGT_BUDGET, mkt, month, year, channel)
    plan_msg = target(t3, TGT_MESSAGES, mkt, month, year, channel)
    plan_rev = (target(t3, TGT_API_REVENUE, mkt, month, year, "API")
                if channel == "API" else None)

    if channel == "API":
        msg_out = _nsum(actual(t2, MSG_CUST, market=mkt, month=month, year=year, platform="API"),
                        actual(t2, MSG_LEAD, market=mkt, month=month, year=year, platform="API"))
        msg_label = "Messages sent"
    else:
        msg_out = actual(t2, MSG_RECV, market=mkt, month=month, year=year, platform="Meta API")
        msg_label = "Messages received"

    cr = pct(orders, msg_out)
    plan_cr = pct(plan_ord, plan_msg)

    def row(label, act, plan, direction, pfx="", sfx="", dec=0, paced=True, key=""):
        p = _pace(plan, cov) if (paced and plan is not None) else None
        basis = p if p is not None else plan
        v = rag(act, basis, direction, "paced" if p is not None else "plan")
        ok, why = plausible(act, v.ratio, key)
        if not ok:
            v = Verdict("CHECK DATA", RED, v.ratio, "", scored=False, note=why)
        return {"Metric": label,
                "Actual MTD": fmt(act, pfx, sfx, dec),
                "Plan (month)": fmt(plan, pfx, sfx, dec),
                f"Paced to D{cov.days_elapsed}": fmt(p, pfx, sfx, dec) if p is not None else "n/a",
                "vs paced": fmt_pct(act, p) if p is not None else "n/a",
                "vs full-month plan": fmt_pct(act, plan),
                "Status": v.label}

    rows = [
        row("Orders", orders, plan_ord, "up"),
        row(msg_label, msg_out, plan_msg, "neutral"),
        row("Conversion rate %", cr, plan_cr, "up", sfx="%", dec=2, paced=False,
            key="cr_api"),
        row("Revenue", rev, plan_rev, "up", pfx="AED "),
        row("Spend", spend, plan_bud, "neutral", pfx="AED "),
    ]
    roas = safe_div(rev, spend)
    cac = safe_div(spend, orders)
    for label, val, pfx, sfx, dec in [("ROAS", roas, "", "x", 1),
                                      ("CAC", cac, "AED ", "", 1)]:
        rows.append({"Metric": label, "Actual MTD": fmt(val, pfx, sfx, dec),
                     "Plan (month)": "not planned by channel",
                     f"Paced to D{cov.days_elapsed}": "n/a",
                     "vs paced": "n/a", "vs full-month plan": "n/a",
                     "Status": "reference only"})

    if channel == "Meta":
        for p in plats:
            po = actual(t2, ORDER_METRIC[p], market=mkt, month=month, year=year, platform=p)
            ps = actual(t2, SPEND, market=mkt, month=month, year=year, platform=p)
            pr = actual(t2, REVENUE, market=mkt, month=month, year=year, platform=p)
            rows.append({
                "Metric": f"  · {p}",
                "Actual MTD": f"{fmt(po)} orders",
                "Plan (month)": "no separate target",
                f"Paced to D{cov.days_elapsed}": "n/a",
                "vs paced": "n/a",
                "vs full-month plan": "n/a",
                "Status": (f"ROAS {pr/ps:.1f}x" if ps else "no spend")})
    return pd.DataFrame(rows)


def channel_summary(t2, t3, market, month, year, cov: Coverage,
                    split_meta: bool = False) -> pd.DataFrame:
    """One row per channel. Meta consolidated by default, split on request."""
    mkt = None if market in (None, "All") else market
    rows = []
    units = CHANNEL_ORDER if not split_meta else ["API", "Meta API", "Meta Ecom"]
    for ch in units:
        if ch in CHANNEL_GROUPS:
            o = _chan_orders(t2, mkt, ch, month, year)
            rev = _chan_metric(t2, REVENUE, mkt, ch, month, year)
            sp = _chan_metric(t2, SPEND, mkt, ch, month, year)
            plan = target(t3, TGT_ORDERS, mkt, month, year, ch)
            pbud = target(t3, TGT_BUDGET, mkt, month, year, ch)
        else:
            o = actual(t2, ORDER_METRIC[ch], market=mkt, month=month, year=year, platform=ch)
            rev = actual(t2, REVENUE, market=mkt, month=month, year=year, platform=ch)
            sp = actual(t2, SPEND, market=mkt, month=month, year=year, platform=ch)
            plan = pbud = None
        if o is None and sp is None:
            continue
        paced = _pace(plan, cov)
        v = rag(o, paced, "up", "paced")
        rows.append({
            "Channel": ch,
            "Orders": int(o or 0),
            "Paced plan": int(paced) if paced else None,
            "vs paced": fmt_pct(o, paced),
            "EOM": int(_eom(o, cov)) if o else None,
            "Revenue": int(rev or 0),
            "Spend": int(sp or 0),
            "Spend vs paced": fmt_pct(sp, _pace(pbud, cov)),
            "ROAS": f"{rev/sp:.1f}x" if sp else "n/a",
            "CAC": f"{sp/o:.1f}" if o else "n/a",
            "Share of orders": None,
            "Status": v.label,
        })
    if rows:
        tot = sum(r["Orders"] for r in rows) or 1
        for r in rows:
            r["Share of orders"] = f"{r['Orders']/tot*100:.0f}%"
    return pd.DataFrame(rows)


def financial_summary(t2, t3, market, month, year, cov: Coverage) -> pd.DataFrame:
    """Money only. Kept apart from volume so the two are never scored alike."""
    mkt = None if market in (None, "All") else market
    rev = actual(t2, REVENUE, market=mkt, month=month, year=year)
    sp = actual(t2, SPEND, market=mkt, month=month, year=year)
    prev = target(t3, TGT_REVENUE, mkt, month, year, "Total")
    pbud = target(t3, TGT_BUDGET, mkt, month, year, "Total")
    rows = [
        ("Revenue", rev, prev, "up", "AED ", 0),
        ("Budget spent", sp, pbud, "neutral", "AED ", 0),
        ("Revenue after marketing spend", 
         (rev - sp) if None not in (rev, sp) else None,
         (prev - pbud) if None not in (prev, pbud) else None, "up", "AED ", 0),
        ("ROAS", safe_div(rev, sp), safe_div(prev, pbud), "up", "", 1),
        ("Spend per order",
         safe_div(sp, total_orders(t2, market=mkt, month=month, year=year)),
         safe_div(pbud, target(t3, TGT_ORDERS, mkt, month, year, "Total")),
         "down", "AED ", 1),
    ]
    out = []
    for label, act, plan, direction, pfx, dec in rows:
        paced = _pace(plan, cov) if direction != "down" and label not in ("ROAS",) else None
        basis = paced if paced is not None else plan
        v = rag(act, basis, direction, "paced" if paced is not None else "plan")
        out.append({"Metric": label,
                    "Actual MTD": fmt(act, pfx, dec=dec),
                    "Plan (month)": fmt(plan, pfx, dec=dec),
                    f"Paced to D{cov.days_elapsed}": fmt(paced, pfx, dec=dec) if paced else "n/a",
                    "vs plan": fmt_pct(act, plan),
                    "Status": v.label})
    return pd.DataFrame(out)
