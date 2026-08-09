"""Metrics engine — Inripe sales performance.

One place where every headline figure is defined. The dashboard reads from
here and computes nothing of its own, so a number cannot mean two things on
two screens.

The definitions, agreed and fixed:

  Order state      delivered              fulfilment status is delivered
                   open                   created, shipped, out for delivery,
                                          on hold — not yet delivered
                   lost                   cancelled, refunded, voided

  Revenue          delivered + open. Lost is excluded entirely, never
                   counted as zero, because it was never earned.

  Cash certainty   collected              delivered and paid
                   owed                   delivered, not paid
                   at risk                not delivered, not paid
                   prepaid                paid, not delivered

  Cost             matched to the order date, not the delivery date.
                   Revenue is recognised when the order is placed, so cost
                   is matched to the same moment. Matching to delivery would
                   let a later cost change land on a sale already priced.

  Cost movement    against plan cost on the management cards — is the year
                   still worth what we said. Against the previous cost entry
                   in the drill-downs — what just moved.

  Pace             plan x days elapsed / days in the month.

  Margin           at dated cost where the cost log covers the period,
                   at plan cost otherwise, and it always says which.

Pure pandas. No Streamlit, no I/O, no network.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MARKETS = ["UAE", "QA", "KSA", "EG"]

DELIVERED = {"FULFILLED"}
LOST_FINANCIAL = {"REFUNDED", "VOIDED", "EXPIRED"}
PAID = {"PAID"}
NOT_PRODUCTS = {"Gift Wrapping", "Gift wrapping", "Tip", "Shipping",
                "WooCommerce Order", "Woocommerce Order"}

# Shown in the footer of every page so a figure and its definition are never
# more than a glance apart.
DEFINITIONS = [
    ("Revenue", "delivered plus open orders. Cancelled, refunded and voided "
                "are excluded entirely, not counted as zero."),
    ("Order state", "delivered · open is created, shipped, out for delivery "
                    "or on hold · lost is cancelled, refunded or voided."),
    ("Cash", "collected is delivered and paid · owed is delivered, not paid · "
             "at risk is neither."),
    ("Cost", "matched to the order date, so cost and revenue are recognised "
             "at the same moment."),
    ("Cost movement", "against plan cost on the cards, against the previous "
                      "cost entry in the drill-downs."),
    ("Margin", "at dated cost where the cost log covers the period, at plan "
               "cost otherwise. The card says which."),
    ("Pace", "plan x days elapsed / days in the month."),
]


class MetricError(ValueError):
    """Raised when a metric cannot be computed honestly."""


@dataclass
class Scope:
    """What the page is showing. Everything downstream reads this.

    A date range filters both sides. Filtering actuals without filtering the
    plan — or the reverse — makes every comparison wrong, which is what the
    old as_of control did: it moved the pace without moving the orders, so
    a full month of sales was measured against a third of a month of plan.
    """

    year: int = 2026
    market: str | None = None
    month: str | None = None
    categories: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    start: date | None = None
    end: date | None = None

    def __post_init__(self):
        # A month selection is a date range. Holding one idea rather than two
        # stops the two drifting apart.
        if self.month and (self.start is None or self.end is None):
            n = MONTHS.index(self.month) + 1
            last = calendar.monthrange(self.year, n)[1]
            self.start = self.start or date(self.year, n, 1)
            self.end = self.end or date(self.year, n, last)
        if self.start is None:
            self.start = date(self.year, 1, 1)
        if self.end is None:
            self.end = date(self.year, 12, 31)
        if self.end < self.start:
            self.start, self.end = self.end, self.start

    @property
    def consolidated(self) -> bool:
        return self.market is None

    @property
    def full_year(self) -> bool:
        return self.month is None

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def label(self) -> str:
        if self.month and self.start.day == 1:
            n = MONTHS.index(self.month) + 1
            if self.end.day == calendar.monthrange(self.year, n)[1]:
                return self.month
        if self.start == date(self.year, 1, 1) and \
                self.end == date(self.year, 12, 31):
            return str(self.year)
        return f"{self.start:%d %b} – {self.end:%d %b}"

    def plan_fraction(self, month: str) -> float:
        """How much of a month's plan falls inside the range.

        Plan is monthly, so a partial range takes a pro-rated share by days.
        Crude, but it is the honest comparison — the alternative is measuring
        half a month of sales against a whole month of plan.
        """
        n = MONTHS.index(month) + 1
        last = calendar.monthrange(self.year, n)[1]
        m_start, m_end = date(self.year, n, 1), date(self.year, n, last)
        lo, hi = max(self.start, m_start), min(self.end, m_end)
        if hi < lo:
            return 0.0
        return ((hi - lo).days + 1) / last


# ---------------------------------------------------------------- shaping


def prepare(lines: pd.DataFrame, scope: Scope) -> pd.DataFrame:
    """Every line in scope, classified once.

    Classification happens here and nowhere else. A page that needed to know
    whether an order was lost would otherwise re-derive it, and two
    derivations drift.
    """
    d = lines.copy()
    # Pinned to nanoseconds. Pandas can return microsecond precision here
    # depending on the input, and a merge against the cost log then fails on
    # a dtype mismatch that has nothing to do with the data.
    d["ts"] = (pd.to_datetime(d["processed_at"], utc=True, format="mixed")
               .dt.tz_localize(None).astype("datetime64[ns]"))
    d["date"] = d["ts"].dt.normalize()
    # One filter, applied to actuals and plan alike.
    d = d[(d["date"].dt.date >= scope.start) & (d["date"].dt.date <= scope.end)]
    d = d[~d["product"].isin(NOT_PRODUCTS)]

    if scope.market:
        d = d[d["market"] == scope.market]
    if scope.products:
        d = d[d["product"].isin(scope.products)]
    if d.empty:
        return d

    d["month"] = d["date"].dt.month.map(lambda n: MONTHS[n - 1])

    lost = d["cancelled"] | d["financial_status"].isin(LOST_FINANCIAL)
    delivered = d["fulfillment_status"].isin(DELIVERED) & ~lost
    d["state"] = np.where(lost, "lost",
                          np.where(delivered, "delivered", "open"))

    paid = d["financial_status"].isin(PAID)
    d["cash"] = np.select(
        [lost,
         delivered & paid,
         delivered & ~paid,
         ~delivered & paid],
        ["lost", "collected", "owed", "prepaid"],
        default="at risk")

    # Money on a lost line is not revenue, so it is zeroed rather than
    # carried and filtered later — a filter that someone forgets is a bug,
    # a zero is not.
    ratio = (d["qty_current"] / d["qty_ordered"]).where(
        d["qty_ordered"].ne(0), 1.0).clip(upper=1.0)
    live = d["state"].ne("lost")
    d["units"] = np.where(live, d["qty_current"], 0.0)
    d["gross"] = np.where(live, d["gross_lc"] * ratio, 0.0)
    d["revenue"] = np.where(live, d["net_line_lc"] * ratio, 0.0)
    d["discount"] = (d["gross"] - d["revenue"]).clip(lower=0)

    # What was ordered and then died, kept separately so the cost of losing
    # it can be stated rather than merely implied by absence.
    d["lost_units"] = np.where(~live, d["qty_ordered"], 0.0)
    d["lost_revenue"] = np.where(~live, d["gross_lc"], 0.0)
    return d


def attach_cost(d: pd.DataFrame, cost_log: pd.DataFrame | None,
                plan: pd.DataFrame | None) -> pd.DataFrame:
    """Unit cost per line, matched to the order date.

    Falls back to plan cost where the log does not reach, and records which
    basis was used so the page can say so instead of implying a precision it
    does not have.
    """
    import variance_engine as ve

    if d.empty:
        return d
    out = d.copy()
    out["unit_cost"] = np.nan
    out["cost_basis"] = "none"

    if cost_log is not None and len(cost_log):
        cl = ve.normalise_cost_log(cost_log)
        if len(cl):
            parts = []
            for (prod, mkt), grp in cl.groupby(["product", "market"],
                                               sort=False):
                sub = out[(out["product"] == prod) & (out["market"] == mkt)]
                if sub.empty:
                    continue
                s = sub.sort_values("ts")
                merged = pd.merge_asof(
                    s, grp.sort_values("valid_from")[
                        ["valid_from", "cogs_unit_lc"]],
                    left_on="ts", right_on="valid_from", direction="backward")
                merged.index = s.index
                parts.append(merged["cogs_unit_lc"])
            if parts:
                found = pd.concat(parts).reindex(out.index)
                out["unit_cost"] = found
                out.loc[found.notna(), "cost_basis"] = "dated"

    missing = out["unit_cost"].isna()
    if plan is not None and missing.any():
        pc = (plan.drop_duplicates(["product", "market", "month"])
              .set_index(["product", "market", "month"])["plan_cogs_unit_lc"])
        idx = pd.MultiIndex.from_arrays(
            [out["product"], out["market"], out["month"]])
        fb = pd.Series(pc.reindex(idx).to_numpy(), index=out.index)
        out.loc[missing, "unit_cost"] = fb[missing]
        out.loc[missing & fb.notna(), "cost_basis"] = "plan"

    out["unit_cost"] = out["unit_cost"].fillna(0.0)
    out["cogs"] = out["units"] * out["unit_cost"]
    out["cm"] = out["revenue"] - out["cogs"]
    out["lost_cogs"] = out["lost_units"] * out["unit_cost"]
    return out


def plan_scope(plan: pd.DataFrame, scope: Scope) -> pd.DataFrame:
    """Plan rows for the same range, pro-rated where a month is partial."""
    p = plan[plan["plan_units"] > 0].copy()
    if scope.market:
        p = p[p["market"] == scope.market]
    if scope.categories:
        p = p[p["category"].isin(scope.categories)]
    if scope.products:
        p = p[p["product"].isin(scope.products)]
    if p.empty:
        return p

    frac = p["month"].map(scope.plan_fraction)
    p = p[frac > 0].copy()
    frac = frac[frac > 0]
    for c in ("plan_units", "plan_revenue_lc", "plan_cogs_lc", "plan_cm_lc",
              "plan_revenue_aed", "plan_cogs_aed", "plan_cm_aed"):
        if c in p.columns:
            p[c] = p[c] * frac
    return p


# ------------------------------------------------------------------ pace


def pace_fraction(scope: Scope, today: date | None = None
                  ) -> tuple[float, int, int]:
    """How much of the selected range has elapsed.

    The plan is already pro-rated to the range, so pace only asks how far
    through that range we are. A range that ended in the past is complete,
    and its plan is the whole of the pro-rated figure.
    """
    today = today or date.today()
    total = scope.days
    if today >= scope.end:
        return 1.0, total, total
    if today < scope.start:
        return 0.0, 0, total
    elapsed = (today - scope.start).days + 1
    return elapsed / total, elapsed, total


# --------------------------------------------------------------- the cards


def cards(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
          cost_log: pd.DataFrame | None = None) -> dict:
    """Every management figure, computed once.

    The chain is deliberately consistent: orders x basket = units, and
    units x price = revenue. `check_chain` asserts it holds rather than
    trusting that it must.
    """
    d = attach_cost(prepare(lines, scope), cost_log, plan)
    p = plan_scope(plan, scope)
    frac, elapsed, total = pace_fraction(scope)

    plan_units = float(p["plan_units"].sum())
    plan_rev = float(p["plan_revenue_lc"].sum())
    plan_cogs = float(p["plan_cogs_lc"].sum())
    plan_cm = plan_rev - plan_cogs

    if d.empty:
        return {"empty": True, "pace_fraction": frac,
                "days_elapsed": elapsed, "days_total": total,
                "plan": {"units": plan_units, "revenue": plan_rev,
                         "cm": plan_cm}}

    live = d[d["state"].ne("lost")]
    by_state = d.groupby("state", observed=True)
    by_cash = d.groupby("cash", observed=True)

    def state_orders(s):
        return int(d[d["state"] == s]["order"].nunique())

    def cash_money(c):
        return float(d[d["cash"] == c]["revenue"].sum())

    # Orders that can still become revenue. A lost order is not a smaller
    # sale, it is no sale, so it does not belong in a headline that units,
    # revenue and margin all exclude it from. Counting it here also
    # understated AOV and basket size, because their numerators came from
    # surviving orders while the denominator counted every order placed.
    orders_placed = int(d["order"].nunique())
    orders_total = int(d[d["state"].ne("lost")]["order"].nunique())
    units = float(live["units"].sum())
    revenue = float(live["revenue"].sum())
    cogs = float(live["cogs"].sum())
    cm = revenue - cogs

    # Cost movement: what the same boxes would have cost at plan cost. The
    # difference is cost, everything else is commercial.
    pc = (plan.drop_duplicates(["product", "market", "month"])
          .set_index(["product", "market", "month"])["plan_cogs_unit_lc"])
    idx = pd.MultiIndex.from_arrays(
        [live["product"], live["market"], live["month"]])
    plan_unit_cost = pd.Series(pc.reindex(idx).to_numpy(), index=live.index)
    cogs_at_plan = float((live["units"] * plan_unit_cost.fillna(0)).sum())
    cm_at_plan = revenue - cogs_at_plan
    cost_effect = cm - cm_at_plan

    paced_units = plan_units * frac
    paced_rev = plan_rev * frac
    paced_cm = plan_cm * frac
    paced_orders = (plan_units / (units / orders_total) * frac
                    if orders_total and units else 0.0)

    basis = ("dated" if (d["cost_basis"] == "dated").any() else "plan")
    dated_share = float((d["cost_basis"] == "dated").mean())

    return {
        "empty": False,
        "pace_fraction": frac, "days_elapsed": elapsed, "days_total": total,
        "cost_basis": basis, "dated_share": dated_share,

        "orders": {
            "total": orders_total,
            "placed": orders_placed,
            "delivered": state_orders("delivered"),
            "open": state_orders("open"),
            "lost": state_orders("lost"),
            "cancel_rate": (state_orders("lost") / orders_placed
                            if orders_placed else None),
            "paced": paced_orders,
            "plan_full": (plan_units / (units / orders_total)
                          if orders_total and units else None),
            "aov": revenue / orders_total if orders_total else None,
        },
        "units": {
            "total": units,
            "delivered": float(d[d["state"] == "delivered"]["units"].sum()),
            "open": float(d[d["state"] == "open"]["units"].sum()),
            "lost": float(d["lost_units"].sum()),
            "paced": paced_units, "plan_full": plan_units,
            "per_order": units / orders_total if orders_total else None,
        },
        "revenue": {
            "total": revenue,
            "collected": cash_money("collected"),
            "owed": cash_money("owed"),
            "prepaid": cash_money("prepaid"),
            "at_risk": cash_money("at risk"),
            "lost": float(d["lost_revenue"].sum()),
            "discount": float(live["discount"].sum()),
            "paced": paced_rev, "plan_full": plan_rev,
        },
        "margin": {
            "cm": cm, "cm_pct": cm / revenue if revenue else None,
            "cm_at_plan_cost": cm_at_plan,
            "commercial_effect": cm_at_plan - paced_cm,
            "cost_effect": cost_effect,
            "paced": paced_cm, "plan_full": plan_cm,
            "plan_pct": plan_cm / plan_rev if plan_rev else None,
            "per_box": cm / units if units else None,
            "plan_per_box": plan_cm / plan_units if plan_units else None,
            "lost_cm": float(d["lost_revenue"].sum() - d["lost_cogs"].sum()),
            "price_index": (revenue / units) / (plan_rev / plan_units)
            if units and plan_units and plan_rev else None,
            "cost_index": (cogs / units) / (plan_cogs / plan_units)
            if units and plan_units and plan_cogs else None,
        },
    }


def projection(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
               cost_log: pd.DataFrame | None = None,
               today: date | None = None) -> dict:
    """Where the period lands, on three bases with different assumptions.

    Not a forecast. Each figure is arithmetic from a stated assumption, and
    the spread between them is the honest measure of how uncertain the
    period is. A single projected number would hide which assumption it
    rested on.

      run rate    the last seven days repeat to the end
      attainment  the rest runs at the rate achieved so far
      plan        the remaining days run exactly to plan

    A statistical model was built and tested against this data and lost to a
    trailing mean, so it is deliberately not used here.
    """
    today = today or date.today()
    if today >= scope.end:
        return {}

    d = attach_cost(prepare(lines, scope), cost_log, plan)
    if d.empty:
        return {}
    live = d[d["state"].ne("lost")]

    elapsed = max(1, (min(today, scope.end) - scope.start).days + 1)
    remaining = (scope.end - min(today, scope.end)).days
    if remaining <= 0:
        return {}

    p_scope = plan_scope(plan, scope)
    out = {"elapsed": elapsed, "remaining": remaining, "days": scope.days,
           "bases": {}}

    week_start = pd.Timestamp(today) - pd.Timedelta(days=7)
    recent = live[live["ts"] > week_start]

    for name, actual_col, plan_col in (
            ("revenue", "revenue", "plan_revenue_lc"),
            ("units", "units", "plan_units"),
            ("cm", "cm", None)):
        banked = float(live[actual_col].sum())
        if plan_col:
            plan_total = float(p_scope[plan_col].sum())
        else:
            plan_total = float((p_scope["plan_revenue_lc"]
                                - p_scope["plan_cogs_lc"]).sum())

        per_day_recent = (float(recent[actual_col].sum()) / 7
                          if len(recent) else banked / elapsed)
        per_day_so_far = banked / elapsed
        plan_per_day = plan_total / scope.days if scope.days else 0.0

        out["bases"][name] = {
            "banked": banked,
            "plan": plan_total,
            "run_rate": banked + per_day_recent * remaining,
            "attainment": banked + per_day_so_far * remaining,
            "at_plan": banked + plan_per_day * remaining,
        }
        for k in ("run_rate", "attainment", "at_plan"):
            out["bases"][name][k + "_pct"] = (
                out["bases"][name][k] / plan_total if plan_total else None)
    return out


def forecast(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
             cost_log: pd.DataFrame | None = None,
             today: date | None = None, window: int = 7) -> dict:
    """Where the period lands, demand first and financials derived from it.

    Orders and basket are forecast separately because they fail for
    different reasons and have different owners. Boxes are then orders times
    basket, revenue is boxes times achieved price, and margin is revenue
    less boxes times current cost.

    Forecasting revenue independently of the orders that produce it is the
    common mistake: the two then disagree and nobody can say which is right.
    Here they cannot disagree, because only the drivers are forecast.

    Three bases, each a stated assumption rather than a prediction:
      run rate    the last `window` days repeat
      attainment  the rate achieved so far continues
      plan        the remaining days run exactly to plan
    """
    today = today or date.today()
    if today >= scope.end:
        return {}

    d = attach_cost(prepare(lines, scope), cost_log, plan)
    if d.empty:
        return {}
    live = d[d["state"].ne("lost")]
    if live.empty:
        return {}

    elapsed = max(1, (min(today, scope.end) - scope.start).days + 1)
    remaining = (scope.end - min(today, scope.end)).days
    if remaining <= 0:
        return {}

    p_scope = plan_scope(plan, scope)
    plan_orders = None
    plan_units = float(p_scope["plan_units"].sum())
    plan_rev = float(p_scope["plan_revenue_lc"].sum())
    plan_cogs = float(p_scope["plan_cogs_lc"].sum())

    orders_so_far = int(live["order"].nunique())
    units_so_far = float(live["units"].sum())
    rev_so_far = float(live["revenue"].sum())
    cogs_so_far = float(live["cogs"].sum())

    cut = pd.Timestamp(today) - pd.Timedelta(days=window)
    recent = live[live["ts"] > cut]
    recent_orders = int(recent["order"].nunique()) if len(recent) else 0

    basket_now = (float(recent["units"].sum()) / recent_orders
                  if recent_orders else units_so_far / max(1, orders_so_far))
    basket_all = units_so_far / max(1, orders_so_far)
    # plan_units / (plan_units / basket_all) is just basket_all, and it
    # divides by zero the moment a month has no sales yet. Stated directly.
    plan_basket = basket_all if basket_all else None

    price_now = (float(recent["revenue"].sum()) / float(recent["units"].sum())
                 if len(recent) and recent["units"].sum()
                 else rev_so_far / max(1e-9, units_so_far))
    cost_now = (float(recent["cogs"].sum()) / float(recent["units"].sum())
                if len(recent) and recent["units"].sum()
                else cogs_so_far / max(1e-9, units_so_far))
    plan_price = plan_rev / plan_units if plan_units else None
    plan_cost = plan_cogs / plan_units if plan_units else None

    # Orders per day on each basis. Everything else is derived from these.
    per_day = {
        "run_rate": recent_orders / window if recent_orders else
        orders_so_far / elapsed,
        "attainment": orders_so_far / elapsed,
        "at_plan": ((plan_units / basket_all) / scope.days
                    if basket_all and scope.days else 0.0),
    }
    plan_orders = plan_units / basket_all if basket_all else None

    bases = {}
    for name, rate in per_day.items():
        orders = orders_so_far + rate * remaining
        basket = plan_basket if name == "at_plan" and plan_basket else basket_now
        units = units_so_far + (orders - orders_so_far) * basket
        price = plan_price if name == "at_plan" and plan_price else price_now
        cost = plan_cost if name == "at_plan" and plan_cost else cost_now
        revenue = rev_so_far + (units - units_so_far) * price
        cogs = cogs_so_far + (units - units_so_far) * cost
        bases[name] = {
            "orders": orders, "basket": basket, "units": units,
            "price": price, "revenue": revenue,
            "cost_per_box": cost, "cogs": cogs,
            "cm": revenue - cogs,
            "cm_pct": (revenue - cogs) / revenue if revenue else None,
            "orders_pct": (orders / plan_orders
                           if plan_orders else None),
            "units_pct": units / plan_units if plan_units else None,
            "revenue_pct": revenue / plan_rev if plan_rev else None,
            "cm_pct_of_plan": ((revenue - cogs) / (plan_rev - plan_cogs)
                               if (plan_rev - plan_cogs) else None),
        }

    # Split the projected margin shortfall on the working basis, so the
    # conversation it starts is the right one.
    base = bases["run_rate"]
    plan_cm = plan_rev - plan_cogs
    vol_effect = ((base["units"] - plan_units) * (plan_price - plan_cost)
                  if plan_price and plan_cost else 0.0)
    cost_effect = (base["units"] * (plan_cost - base["cost_per_box"])
                   if plan_cost else 0.0)
    price_effect = base["cm"] - plan_cm - vol_effect - cost_effect

    return {
        "elapsed": elapsed, "remaining": remaining, "days": scope.days,
        "bases": bases,
        "so_far": {"orders": orders_so_far, "units": units_so_far,
                   "revenue": rev_so_far, "cogs": cogs_so_far,
                   "cm": rev_so_far - cogs_so_far},
        "plan": {"units": plan_units, "revenue": plan_rev, "cogs": plan_cogs,
                 "cm": plan_cm, "price": plan_price, "cost": plan_cost,
                 "basket": basket_all, "orders": plan_orders},
        "basket_now": basket_now, "price_now": price_now,
        "cost_now": cost_now, "window": window,
        "margin_split": {"volume": vol_effect, "cost": cost_effect,
                         "price": price_effect},
        "cost_basis": ("dated" if (d["cost_basis"] == "dated").any()
                       else "plan"),
        "daily": (live.groupby("date", observed=True)["revenue"]
                  .sum().cumsum().reset_index()),
    }


def cost_log_status(cost_log: pd.DataFrame | None) -> dict:
    """When costs were last updated, and how many products they cover.

    A cost log that stopped being maintained looks identical to one that is
    current, unless the header says otherwise — so it says otherwise.
    """
    import variance_engine as ve

    if cost_log is None or not len(cost_log):
        return {}
    try:
        cl = ve.normalise_cost_log(cost_log)
    except Exception:
        return {}
    if cl.empty:
        return {}
    latest = cl["valid_from"].max()
    return {
        "entries": int(len(cl)),
        "products": int(cl.groupby(["product", "market"]).ngroups),
        "latest": latest.date() if pd.notna(latest) else None,
        "days_old": ((date.today() - latest.date()).days
                     if pd.notna(latest) else None),
    }


def momentum(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
             field: str = "revenue", window: int = 7,
             cost_log: pd.DataFrame | None = None) -> dict:
    """Daily activity against its own recent average.

    A cumulative line always rises, so it cannot say whether a number is
    accelerating. This can: bars above the average mean momentum is
    building, below means it is fading.

    The calendar is filled, so a silent day pulls the average down rather
    than being skipped.
    """
    d = prepare(lines, scope)
    if d.empty:
        return {}
    if field == "cm":
        d = attach_cost(d, cost_log, plan)
    live = d[d["state"].ne("lost")]
    if live.empty:
        return {}

    if field == "orders":
        daily = live.groupby("date", observed=True)["order"].nunique()
    else:
        col = {"units": "units", "revenue": "revenue", "cm": "cm"}.get(field)
        if col is None or col not in live.columns:
            return {}
        daily = live.groupby("date", observed=True)[col].sum()

    last = min(pd.Timestamp(date.today()), pd.Timestamp(scope.end))
    cal = pd.date_range(pd.Timestamp(scope.start),
                        max(last, daily.index.max()), freq="D")
    daily = daily.reindex(cal, fill_value=0)
    tail = daily.tail(window * 2)
    if len(tail) < 3:
        return {}

    avg = float(tail.mean())
    recent = float(tail.tail(min(3, len(tail))).mean())
    peak_i = int(daily.to_numpy().argmax())

    return {
        "values": [float(v) for v in tail],
        "average": avg,
        "change": (recent / avg - 1) if avg else None,
        "peak_value": float(daily.iloc[peak_i]),
        "peak_date": cal[peak_i].date(),
        "days": len(tail),
    }


def basis_accuracy(lines: pd.DataFrame, plan: pd.DataFrame,
                   scope: Scope, cost_log: pd.DataFrame | None = None,
                   at_day: int = 12) -> pd.DataFrame:
    """Which forecast basis was closest, tested on completed months.

    Each finished month is replayed: all three bases are computed as they
    would have been on day `at_day`, then compared to what the month
    actually did. Without this the choice of basis is a preference; with it
    it is evidence.
    """
    rows = []
    today = date.today()
    for month in MONTHS:
        n = MONTHS.index(month) + 1
        last = calendar.monthrange(scope.year, n)[1]
        m_end = date(scope.year, n, last)
        if m_end >= today:
            continue

        s_full = Scope(scope.year, scope.market, month,
                       categories=scope.categories, products=scope.products)
        actual = cards(lines, plan, s_full, cost_log)
        if actual.get("empty") or not actual["revenue"]["total"]:
            continue

        cut = date(scope.year, n, min(at_day, last))
        fc = forecast(lines, plan, s_full, cost_log, today=cut)
        if not fc:
            continue

        truth = actual["revenue"]["total"]
        for name, b in fc["bases"].items():
            rows.append({"month": month, "basis": name,
                         "projected": b["revenue"], "actual": truth,
                         "error": (b["revenue"] - truth) / truth
                         if truth else None})

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    g = df.groupby("basis", observed=True).agg(
        months=("month", "nunique"),
        avg_error=("error", lambda s: s.abs().mean()),
        bias=("error", "mean")).reset_index()
    label = {"run_rate": "Run rate", "attainment": "Attainment",
             "at_plan": "Plan"}
    g["basis"] = g["basis"].map(label).fillna(g["basis"])
    g["at_day"] = at_day
    return g.sort_values("avg_error").reset_index(drop=True)


def confidence(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
               cost_log: pd.DataFrame | None = None,
               today: date | None = None, metric: str = "revenue") -> dict:
    """How much to trust the projection, measured rather than asserted.

    The interval comes from how far the same method missed on completed
    months, not from a distribution assumed in advance. Fresh produce demand
    is spiky and skewed, so a normal interval would be too narrow exactly
    when it matters.

    Confidence rises with two things and both are checkable: days elapsed,
    because a projection on day 25 has less left to guess, and months of
    history, because the interval itself is better calibrated. The to-do
    list states what each would buy.
    """
    today = today or date.today()
    fc = forecast(lines, plan, scope, cost_log, today=today)
    if not fc:
        return {}

    elapsed, days = fc["elapsed"], fc["days"]
    share_done = elapsed / days if days else 0.0

    # Each metric is calibrated on its own history. Orders are steadier than
    # margin, so borrowing revenue's interval would understate the one and
    # overstate the other.
    key = {"revenue": "revenue", "orders": "orders",
           "units": "units", "margin": "cm"}.get(metric, "revenue")

    def truth_of(c):
        if key == "orders":
            return c["orders"]["total"]
        if key == "units":
            return c["units"]["total"]
        if key == "cm":
            return c["margin"]["cm"]
        return c["revenue"]["total"]

    # How far each basis missed on completed months, at a comparable point.
    errors, by_day = [], {}
    for month in MONTHS:
        n = MONTHS.index(month) + 1
        last = calendar.monthrange(scope.year, n)[1]
        if date(scope.year, n, last) >= today:
            continue
        s_full = Scope(scope.year, scope.market, month,
                       categories=scope.categories, products=scope.products)
        actual = cards(lines, plan, s_full, cost_log)
        if actual.get("empty") or not truth_of(actual):
            continue
        truth = truth_of(actual)
        for at in (5, 10, 15, 20, 25):
            if at > last:
                continue
            past = forecast(lines, plan, s_full, cost_log,
                            today=date(scope.year, n, at))
            if not past:
                continue
            e = (past["bases"]["run_rate"][key] - truth) / truth
            by_day.setdefault(at, []).append(e)
            if abs(at - elapsed) <= 3:
                errors.append(e)

    months = len({m for m in MONTHS
                  if date(scope.year, MONTHS.index(m) + 1,
                          calendar.monthrange(scope.year,
                                              MONTHS.index(m) + 1)[1]) < today})

    if errors:
        arr = np.array(errors)
        spread = float(np.quantile(np.abs(arr), 0.8))
        basis = "measured"
        tested = len(errors)
    elif by_day:
        arr = np.concatenate([np.array(v) for v in by_day.values()])
        spread = float(np.quantile(np.abs(arr), 0.8))
        basis = "measured at other points in the month"
        tested = len(arr)
    else:
        # Nothing to measure against. A deliberately wide default, so an
        # uncalibrated projection is not mistaken for a confident one.
        spread = 0.45
        basis = "no completed months to test against"
        tested = 0

    # Confidence is the share of the period already banked, tightened by how
    # consistent past months were. Both are facts, not judgements.
    level = share_done * 0.55 + max(0.0, 1 - min(spread, 1.0)) * 0.45
    level = float(np.clip(level, 0.15, 0.95))

    point = fc["bases"]["run_rate"][key]
    remaining_share = 1 - share_done
    band = spread * remaining_share

    todo = []
    if elapsed < days:
        for at in (10, 15, 20, 25):
            if at <= elapsed or at > days:
                continue
            got = by_day.get(at)
            if got:
                s_at = float(np.quantile(np.abs(np.array(got)), 0.8))
                lvl = float(np.clip((at / days) * 0.55
                                    + max(0.0, 1 - min(s_at, 1.0)) * 0.45,
                                    0.15, 0.95))
            else:
                lvl = float(np.clip((at / days) * 0.55
                                    + max(0.0, 1 - min(spread, 1.0)) * 0.45,
                                    0.15, 0.95))
            todo.append({
                "done": False,
                "what": f"Wait until day {at}",
                "gives": f"confidence about {lvl:.0%}",
                "in_days": at - elapsed})
            break

    todo.append({
        "done": months >= 6,
        "what": f"Six completed months to calibrate against",
        "gives": f"a measured interval instead of a default"
                 + (f" · have {months}" if months < 6 else ""),
        "in_days": None})
    todo.append({
        "done": bool(cost_log is not None and len(cost_log)),
        "what": "Cost log covering the period",
        "gives": "margin projected at real cost, not plan cost",
        "in_days": None})
    todo.append({
        "done": False,
        "what": "Two full seasons of history",
        "gives": "a seasonal model, so a season launch can be projected "
                 "before it has happened",
        "in_days": None})

    plan_target = {"revenue": fc["plan"]["revenue"],
                   "units": fc["plan"]["units"],
                   "cm": fc["plan"]["cm"],
                   "orders": fc["plan"].get("orders")}.get(key)

    return {
        "metric": metric, "plan": plan_target,
        "level": level, "spread": spread, "basis": basis, "tested": tested,
        "months": months, "elapsed": elapsed, "days": days,
        "point": point, "low": point * (1 - band), "high": point * (1 + band),
        "band_pct": band,
        "todo": [t for t in todo if not t["done"]],
        "done": [t for t in todo if t["done"]],
    }


def progress(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
             field: str = "revenue",
             cost_log: pd.DataFrame | None = None) -> dict:
    """Cumulative progress against the plan line, plus the peak day.

    Daily bars show activity; they do not show whether the gap is opening or
    closing. Four days into a month, four bars say almost nothing — a line
    climbing from zero against a straight plan line says everything.

    The calendar is filled so a silent day flattens the line rather than
    being skipped, which would flatter the shape.
    """
    d = prepare(lines, scope)
    if d.empty:
        return {}
    if field == "cm":
        d = attach_cost(d, cost_log, plan)
    live = d[d["state"].ne("lost")]
    if live.empty:
        return {}

    if field == "orders":
        daily = live.groupby("date", observed=True)["order"].nunique()
    else:
        col = {"units": "units", "revenue": "revenue", "cm": "cm"}.get(field)
        if col is None or col not in live.columns:
            return {}
        daily = live.groupby("date", observed=True)[col].sum()

    start = pd.Timestamp(scope.start)
    last = min(pd.Timestamp(date.today()), pd.Timestamp(scope.end))
    cal = pd.date_range(start, max(last, daily.index.max()), freq="D")
    daily = daily.reindex(cal, fill_value=0)

    p_scope = plan_scope(plan, scope)
    if field == "orders":
        units = float(live["units"].sum())
        orders = int(live["order"].nunique())
        basket = units / orders if orders else None
        target = (float(p_scope["plan_units"].sum()) / basket
                  if basket else 0.0)
    elif field == "units":
        target = float(p_scope["plan_units"].sum())
    elif field == "cm":
        target = float((p_scope["plan_revenue_lc"]
                        - p_scope["plan_cogs_lc"]).sum())
    else:
        target = float(p_scope["plan_revenue_lc"].sum())

    n = len(cal)
    per_day = target / scope.days if scope.days else 0.0
    peak_i = int(daily.to_numpy().argmax()) if n else 0

    return {
        "actual": [float(v) for v in daily.cumsum()],
        "plan": [per_day * (i + 1) for i in range(n)],
        "dates": [d_.date() for d_ in cal],
        "peak_value": float(daily.iloc[peak_i]) if n else 0.0,
        "peak_date": cal[peak_i].date() if n else None,
        "days": n,
    }


def sparkline(lines: pd.DataFrame, scope: Scope, field: str = "revenue",
              plan: pd.DataFrame | None = None,
              cost_log: pd.DataFrame | None = None) -> list[float]:
    """A short daily series, kept for callers that want raw activity."""
    d = prepare(lines, scope)
    if d.empty:
        return []
    if field == "cm":
        d = attach_cost(d, cost_log, plan)
    live = d[d["state"].ne("lost")]
    if live.empty:
        return []
    if field == "orders":
        g = live.groupby("date", observed=True)["order"].nunique()
    else:
        col = {"units": "units", "revenue": "revenue", "cm": "cm"}.get(field)
        if col is None or col not in live.columns:
            return []
        g = live.groupby("date", observed=True)[col].sum()
    full = pd.date_range(g.index.min(), g.index.max(), freq="D")
    return [float(v) for v in g.reindex(full, fill_value=0).tail(21)]


def week_move(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
              cost_log: pd.DataFrame | None = None,
              today: date | None = None) -> dict:
    """Last seven days against the seven before, on the rate measures.

    Rates do not accumulate, so a sparkline says little about them. What
    matters is whether the rate moved, and by how much.
    """
    d = attach_cost(prepare(lines, scope), cost_log, plan)
    if d.empty:
        return {}
    ref = pd.Timestamp(min(today or date.today(), scope.end))
    a, b = ref - pd.Timedelta(days=7), ref - pd.Timedelta(days=14)
    now, prev = d[d["ts"] > a], d[(d["ts"] > b) & (d["ts"] <= a)]
    if now.empty or prev.empty:
        return {}

    def rates(x):
        live = x[x["state"].ne("lost")]
        rev = float(live["revenue"].sum())
        cm = rev - float(live["cogs"].sum())
        placed = int(x["order"].nunique())
        lost = int(x[x["state"] == "lost"]["order"].nunique())
        return {"cm_pct": cm / rev if rev else None,
                "lost_rate": lost / placed if placed else None}

    n_, p_ = rates(now), rates(prev)
    out = {}
    for k in ("cm_pct", "lost_rate"):
        if n_[k] is not None and p_[k] is not None:
            out[k] = (n_[k] - p_[k]) * 100
    return out


def check_chain(c: dict, tolerance: float = 0.01) -> list[str]:
    """The chain must multiply. If it does not, the cards contradict.

    orders x basket = units, units x price = revenue. Cheap to assert and
    the only guard against three cards that each look right and cannot all
    be true at once.
    """
    if c.get("empty"):
        return []
    problems = []
    o, u, r = c["orders"], c["units"], c["revenue"]

    if o["total"] and u["per_order"]:
        implied = o["total"] * u["per_order"]
        if abs(implied - u["total"]) > max(tolerance, u["total"] * tolerance):
            problems.append(
                f"orders x basket = {implied:,.1f}, units = {u['total']:,.1f}")

    if u["total"] and r["total"]:
        price = r["total"] / u["total"]
        implied = u["total"] * price
        if abs(implied - r["total"]) > max(tolerance, r["total"] * tolerance):
            problems.append(
                f"units x price = {implied:,.1f}, revenue = {r['total']:,.1f}")

    # The headline counts surviving orders only; lost sits alongside it.
    if abs((o["delivered"] + o["open"]) - o["total"]) > 0:
        problems.append(
            f"delivered plus open is {o['delivered'] + o['open']}, "
            f"orders is {o['total']}")
    if abs((o["total"] + o["lost"]) - o["placed"]) > 0:
        problems.append(
            f"orders plus lost is {o['total'] + o['lost']}, "
            f"placed is {o['placed']}")

    # AOV and basket must divide by the same order count the numerator came
    # from. Getting this wrong is invisible to the chain check, because both
    # errors cancel — which is exactly why it is asserted separately.
    if o["total"] and u["total"] and o.get("aov"):
        if abs(o["aov"] * o["total"] - r["total"]) > max(1.0, r["total"] * tolerance):
            problems.append(
                f"AOV x orders = {o['aov'] * o['total']:,.0f}, "
                f"revenue = {r['total']:,.0f}")
        if abs(u["per_order"] * o["total"] - u["total"]) > max(
                tolerance, u["total"] * tolerance):
            problems.append(
                f"basket x orders = {u['per_order'] * o['total']:,.1f}, "
                f"units = {u['total']:,.1f}")

    cash = (r["collected"] + r["owed"] + r["prepaid"] + r["at_risk"])
    if abs(cash - r["total"]) > max(1.0, r["total"] * tolerance):
        problems.append(
            f"cash buckets sum to {cash:,.0f}, revenue is {r['total']:,.0f}")

    return problems


# ------------------------------------------------------------- drill-downs


def gap_decomposition(c: dict, metric: str) -> list[dict]:
    """The bar that opens every drill-down: plan to actual, in named steps."""
    if c.get("empty"):
        return []

    if metric == "orders":
        o = c["orders"]
        paced = o["paced"]
        lost = o["lost"]
        # The headline counts surviving orders, so the walk has to reach the
        # same figure. Cancelled comes off first, then whatever is still
        # missing is demand that never arrived. Subtracting cancelled from a
        # total that already excludes it would double count it.
        shortfall = paced - lost - o["total"]
        return [
            {"label": "plan to date", "value": paced, "kind": "start"},
            {"label": "cancelled", "value": -lost, "kind": "down"},
            {"label": "demand shortfall", "value": -shortfall,
             "kind": "down" if shortfall >= 0 else "up"},
            {"label": "actual", "value": o["total"], "kind": "end"},
        ]

    if metric == "units":
        u, o = c["units"], c["orders"]
        paced = u["paced"]
        lost = u["lost"]

        # Cancelled boxes come off first, so the remaining gap is about
        # surviving demand rather than a mixture of demand and loss.
        after_loss = paced - lost

        # Of the orders that survived, what they should have carried at the
        # planned basket. The basket term is then the remainder, which forces
        # the three parts to sum to actual instead of leaving a residual to
        # bury. Computing both from the plan basket independently is what
        # broke the reconciliation.
        plan_basket = (u["plan_full"] / o["plan_full"]
                       if o.get("plan_full") else None)
        live_orders = o["total"] - o["lost"]
        if plan_basket and o["paced"]:
            surviving_at_plan = live_orders * plan_basket
            order_effect = surviving_at_plan - after_loss
            basket_effect = u["total"] - surviving_at_plan
        else:
            order_effect = u["total"] - after_loss
            basket_effect = 0.0

        return [
            {"label": "plan to date", "value": paced, "kind": "start"},
            {"label": "cancelled", "value": -lost, "kind": "down"},
            {"label": "fewer orders", "value": order_effect,
             "kind": "up" if order_effect >= 0 else "down"},
            {"label": "basket size", "value": basket_effect,
             "kind": "up" if basket_effect >= 0 else "down"},
            {"label": "actual", "value": u["total"], "kind": "end"},
        ]

    if metric == "revenue":
        r, u = c["revenue"], c["units"]
        paced = r["paced"]
        plan_price = (r["plan_full"] / u["plan_full"]
                      if u.get("plan_full") else None)
        volume = ((u["total"] - u["paced"]) * plan_price) if plan_price else 0.0
        price = (r["total"] + r["discount"]
                 - u["total"] * plan_price) if plan_price else 0.0
        return [
            {"label": "plan to date", "value": paced, "kind": "start"},
            {"label": "volume", "value": volume, "kind": "down"},
            {"label": "price", "value": price,
             "kind": "up" if price >= 0 else "down"},
            {"label": "discount", "value": -r["discount"], "kind": "down"},
            {"label": "actual", "value": r["total"], "kind": "end"},
        ]

    if metric == "margin":
        m = c["margin"]
        return [
            {"label": "plan to date", "value": m["paced"], "kind": "start"},
            {"label": "commercial", "value": m["commercial_effect"],
             "kind": "up" if m["commercial_effect"] >= 0 else "down"},
            {"label": "cost", "value": m["cost_effect"],
             "kind": "up" if m["cost_effect"] >= 0 else "down"},
            {"label": "actual", "value": m["cm"], "kind": "end"},
        ]

    raise MetricError(f"unknown metric {metric!r}")


def state_payment_grid(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
                       measure: str = "orders",
                       cost_log: pd.DataFrame | None = None) -> pd.DataFrame:
    """Order state against payment state. Counts or money."""
    d = attach_cost(prepare(lines, scope), cost_log, plan)
    if d.empty:
        return pd.DataFrame()
    d = d[d["state"].ne("lost")]
    d["paid"] = np.where(d["financial_status"].isin(PAID), "Paid", "Not paid")
    if measure == "orders":
        g = (d.groupby(["state", "paid"], observed=True)["order"]
             .nunique().reset_index(name="value"))
    else:
        g = (d.groupby(["state", "paid"], observed=True)["revenue"]
             .sum().reset_index(name="value"))
    return g.pivot(index="state", columns="paid", values="value").fillna(0)


def by_dimension(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
                 dims=("channel", "city", "customer_type"),
                 cost_log: pd.DataFrame | None = None) -> pd.DataFrame:
    """One table, several dimensions stacked, same measures throughout."""
    d = attach_cost(prepare(lines, scope), cost_log, plan)
    if d.empty:
        return pd.DataFrame()

    frames = []
    for dim in dims:
        if dim not in d.columns:
            continue
        live = d[d["state"].ne("lost")]
        g = live.groupby(dim, observed=True).agg(
            orders=("order", "nunique"), units=("units", "sum"),
            revenue=("revenue", "sum"), cm=("cm", "sum"),
            discount=("discount", "sum")).reset_index()
        lost = (d[d["state"] == "lost"].groupby(dim, observed=True)["order"]
                .nunique().rename("lost_orders").reset_index())
        all_o = (d.groupby(dim, observed=True)["order"]
                 .nunique().rename("all_orders").reset_index())
        g = g.merge(lost, on=dim, how="left").merge(all_o, on=dim, how="left")
        g["lost_orders"] = g["lost_orders"].fillna(0)
        g["dimension"] = dim.replace("_", " ").title()
        g = g.rename(columns={dim: "value"})
        frames.append(g)

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["share"] = out.groupby("dimension")["revenue"].transform(
        lambda s: s / s.sum() if s.sum() else np.nan)
    out["aov"] = (out["revenue"] / out["orders"]).where(out["orders"].ne(0))
    out["boxes_per_order"] = (out["units"] / out["orders"]).where(
        out["orders"].ne(0))
    out["cancel_rate"] = (out["lost_orders"] / out["all_orders"]).where(
        out["all_orders"].ne(0))
    out["cm_pct"] = (out["cm"] / out["revenue"]).where(out["revenue"].ne(0))
    out["cm_per_box"] = (out["cm"] / out["units"]).where(out["units"].ne(0))
    out["discount_rate"] = (out["discount"] / (out["revenue"] + out["discount"])
                            ).where(out["revenue"].ne(0))
    return out


def order_concentration(lines: pd.DataFrame, plan: pd.DataFrame,
                        scope: Scope) -> pd.DataFrame:
    """Share of orders containing each product, nested under its category.

    Deliberately not a share of units. When a product that appears in half
    the orders ends, those orders do not shrink — they disappear, taking
    everything else in the basket with them.
    """
    d = prepare(lines, scope)
    if d.empty:
        return pd.DataFrame()
    d = d[d["state"].ne("lost")]
    total = d["order"].nunique()
    if not total:
        return pd.DataFrame()

    cat = (plan.drop_duplicates("product").set_index("product")["category"]
           if "category" in plan.columns else pd.Series(dtype=object))
    d["category"] = d["product"].map(cat).fillna("(unassigned)")

    sku = (d.groupby(["category", "product"], observed=True)["order"]
           .nunique().reset_index(name="orders"))
    sku["share"] = sku["orders"] / total
    sku["level"] = "product"

    grp = (d.groupby("category", observed=True)["order"]
           .nunique().reset_index(name="orders"))
    grp["product"] = grp["category"]
    grp["share"] = grp["orders"] / total
    grp["level"] = "category"

    out = pd.concat([grp, sku], ignore_index=True)
    out["total_orders"] = total
    return out.sort_values(["orders"], ascending=False).reset_index(drop=True)


def basket_composition(lines: pd.DataFrame, scope: Scope) -> pd.DataFrame:
    """How many distinct products an order holds, and what each is worth."""
    d = prepare(lines, scope)
    if d.empty:
        return pd.DataFrame()
    d = d[d["state"].ne("lost")]
    per_order = d.groupby("order", observed=True).agg(
        products=("product", "nunique"), revenue=("revenue", "sum"),
        units=("units", "sum"))
    per_order["band"] = per_order["products"].clip(upper=5).map(
        lambda n: "5+" if n >= 5 else str(int(n)))
    g = per_order.groupby("band", observed=True).agg(
        orders=("revenue", "size"), revenue=("revenue", "sum"),
        avg_order=("revenue", "mean"), avg_units=("units", "mean")).reset_index()
    g["share"] = g["orders"] / g["orders"].sum()
    order = {"1": 0, "2": 1, "3": 2, "4": 3, "5+": 4}
    return g.sort_values("band", key=lambda s: s.map(order)).reset_index(drop=True)


def product_performance(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
                        cost_log: pd.DataFrame | None = None) -> pd.DataFrame:
    """Every product: plan against actual on units, price and margin."""
    d = attach_cost(prepare(lines, scope), cost_log, plan)
    if d.empty:
        return pd.DataFrame()
    live = d[d["state"].ne("lost")]

    g = live.groupby("product", observed=True).agg(
        units=("units", "sum"), revenue=("revenue", "sum"),
        cm=("cm", "sum"), cogs=("cogs", "sum"),
        orders=("order", "nunique")).reset_index()

    frac, _, _ = pace_fraction(scope)
    p = plan_scope(plan, scope)
    pg = p.groupby("product", observed=True).agg(
        plan_units=("plan_units", "sum"),
        plan_revenue=("plan_revenue_lc", "sum"),
        plan_cogs=("plan_cogs_lc", "sum")).reset_index()
    for c in ("plan_units", "plan_revenue", "plan_cogs"):
        pg[c] = pg[c] * frac

    out = g.merge(pg, on="product", how="outer").fillna(0)
    out["price"] = (out["revenue"] / out["units"]).where(out["units"].ne(0))
    out["plan_price"] = (out["plan_revenue"] / out["plan_units"]).where(
        out["plan_units"].ne(0))
    out["price_index"] = (out["price"] / out["plan_price"]).where(
        out["plan_price"].ne(0))
    out["unit_cost"] = (out["cogs"] / out["units"]).where(out["units"].ne(0))
    out["plan_unit_cost"] = (out["plan_cogs"] / out["plan_units"]).where(
        out["plan_units"].ne(0))
    out["cost_index"] = (out["unit_cost"] / out["plan_unit_cost"]).where(
        out["plan_unit_cost"].ne(0))
    out["cm_pct"] = (out["cm"] / out["revenue"]).where(out["revenue"].ne(0))
    out["cm_per_box"] = (out["cm"] / out["units"]).where(out["units"].ne(0))
    out["cm_share"] = out["cm"] / out["cm"].sum() if out["cm"].sum() else np.nan
    out["unit_attainment"] = (out["units"] / out["plan_units"]).where(
        out["plan_units"].ne(0))
    return out.sort_values("revenue", ascending=False).reset_index(drop=True)


def cost_changes(cost_log: pd.DataFrame | None, plan: pd.DataFrame,
                 scope: Scope) -> pd.DataFrame:
    """Cost movement per product, against plan and against the previous entry.

    Two baselines because they answer different questions. Against plan is
    cumulative and belongs on the cards. Against the previous entry is the
    alert, and belongs here.
    """
    import variance_engine as ve

    if cost_log is None or not len(cost_log):
        return pd.DataFrame()
    cl = ve.normalise_cost_log(cost_log)
    if not len(cl):
        return pd.DataFrame()
    if scope.market:
        cl = cl[cl["market"] == scope.market]
    if cl.empty:
        return pd.DataFrame()

    cl = cl.sort_values(["product", "market", "valid_from"])
    cl["previous"] = cl.groupby(["product", "market"])["cogs_unit_lc"].shift()
    latest = cl.groupby(["product", "market"], as_index=False).last()

    p = plan_scope(plan, scope)
    pc = (p.groupby(["product", "market"], observed=True)
          .apply(lambda x: (x["plan_cogs_lc"].sum() / x["plan_units"].sum())
                 if x["plan_units"].sum() else np.nan,
                 include_groups=False).rename("plan_cost").reset_index())

    out = latest.merge(pc, on=["product", "market"], how="left")
    out["vs_plan"] = out["cogs_unit_lc"] - out["plan_cost"]
    out["vs_plan_pct"] = (out["vs_plan"] / out["plan_cost"]).where(
        out["plan_cost"].notna() & out["plan_cost"].ne(0))
    out["vs_previous"] = out["cogs_unit_lc"] - out["previous"]
    out["vs_previous_pct"] = (out["vs_previous"] / out["previous"]).where(
        out["previous"].notna() & out["previous"].ne(0))
    out["changes"] = out["product"].map(
        cl.groupby("product").size().to_dict())
    return out.sort_values("vs_plan_pct", ascending=False).reset_index(drop=True)


def _median_lag(d: pd.DataFrame) -> float | None:
    """Median days from delivery to payment on settled orders only.

    An unpaid order has no lag yet, so including it would make the figure
    move because a delivery happened rather than because collection changed.
    """
    if d.empty or "fulfilled_at" not in d.columns or "paid_at" not in d.columns:
        return None
    paid = d[d["cash"] == "collected"]
    if paid.empty:
        return None
    ff = pd.to_datetime(paid["fulfilled_at"], utc=True, errors="coerce",
                        format="mixed").dt.tz_localize(None)
    pp = pd.to_datetime(paid["paid_at"], utc=True, errors="coerce",
                        format="mixed").dt.tz_localize(None)
    lag = (pp - ff).dt.days
    lag = lag[lag.notna() & lag.ge(0)]
    return float(lag.median()) if len(lag) else None


def payment(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
            cost_log: pd.DataFrame | None = None,
            stuck_after: int = 21) -> dict:
    """Everything the payment section shows, including the week-on-week move.

    The trend compares the last seven days against the seven before, not this
    month against last. Reconciliation speed should not depend on which fruit
    is in season, and month comparisons here would be comparing mango against
    strawberry.
    """
    d = attach_cost(prepare(lines, scope), cost_log, plan)
    if d.empty:
        return {}

    delivered = d[d["state"] == "delivered"]
    if delivered.empty:
        return {"delivered_value": 0.0, "delivered_orders": 0,
                "outstanding": 0.0, "orders": 0}

    owed = d[d["cash"] == "owed"]
    ff = (pd.to_datetime(owed["fulfilled_at"], utc=True, errors="coerce",
                         format="mixed").dt.tz_localize(None)
          if "fulfilled_at" in owed.columns
          else pd.Series(pd.NaT, index=owed.index))
    since = ff.fillna(owed["ts"]) if len(owed) else pd.Series(dtype="datetime64[ns]")
    ref = pd.Timestamp(min(date.today(), scope.end))

    if len(owed):
        age = (ref.normalize() - since.dt.normalize()).dt.days.clip(lower=0)
        o = owed.assign(age=age,
                        basis=np.where(ff.notna(), "delivery", "order date")
                        ).groupby("order", observed=True).agg(
            outstanding=("revenue", "sum"), boxes=("units", "sum"),
            age=("age", "max"), basis=("basis", "first"),
            channel=("channel", "first"),
            delivered_on=("ts", "min"))
        bands = [(0, 7, "0–7"), (8, 14, "8–14"), (15, 21, "15–21"),
                 (22, 30, "22–30"), (31, 10_000, "30+")]
        o["band"] = o["age"].map(
            lambda n: next(l for lo, hi, l in bands if lo <= n <= hi))
        by_band = (o.groupby("band", observed=True)
                   .agg(orders=("outstanding", "size"),
                        outstanding=("outstanding", "sum"))
                   .reindex([l for _, _, l in bands]).fillna(0).reset_index())
        stuck = o[o["age"] > stuck_after]
    else:
        o = pd.DataFrame()
        by_band = pd.DataFrame(columns=["band", "orders", "outstanding"])
        stuck = pd.DataFrame()

    # Week on week. The comparison window is the seven days before the
    # reference date against the seven before that.
    cut_a = ref - pd.Timedelta(days=7)
    cut_b = ref - pd.Timedelta(days=14)
    now = d[d["ts"] > cut_a]
    prev = d[(d["ts"] > cut_b) & (d["ts"] <= cut_a)]

    def move(a, b):
        if b in (None, 0) or a is None:
            return None
        return a / b - 1

    lag_now, lag_prev = _median_lag(now), _median_lag(prev)
    out_now = float(now[now["cash"] == "owed"]["revenue"].sum())
    out_prev = float(prev[prev["cash"] == "owed"]["revenue"].sum())

    by_product = (delivered.groupby("product", observed=True)
                  .agg(boxes=("units", "sum"), orders=("order", "nunique"),
                       value=("revenue", "sum")).reset_index()
                  .sort_values("value", ascending=False))

    return {
        "delivered_value": float(delivered["revenue"].sum()),
        "delivered_orders": int(delivered["order"].nunique()),
        "delivered_boxes": float(delivered["units"].sum()),
        "outstanding": float(o["outstanding"].sum()) if len(o) else 0.0,
        "orders": int(len(o)),
        "median_lag": _median_lag(d),
        "lag_change": (lag_now - lag_prev
                       if lag_now is not None and lag_prev is not None else None),
        "lag_prev": lag_prev,
        "outstanding_change": move(out_now, out_prev),
        "stuck_value": float(stuck["outstanding"].sum()) if len(stuck) else 0.0,
        "stuck_orders": int(len(stuck)),
        "stuck_after": stuck_after,
        "oldest": int(o["age"].max()) if len(o) else 0,
        "by_band": by_band,
        "orders_table": (o.reset_index()
                         .rename(columns={"age": "days_since_delivery"})
                         .sort_values("days_since_delivery", ascending=False)
                         if len(o) else pd.DataFrame()),
        "stuck_table": (stuck.reset_index()
                        .rename(columns={"age": "days_since_delivery"})
                        .sort_values("days_since_delivery", ascending=False)
                        if len(stuck) else pd.DataFrame()),
        "by_product": by_product,
        "no_delivery_date": int((o["basis"] == "order date").sum()) if len(o) else 0,
    }


def collection_lag(lines: pd.DataFrame, scope: Scope) -> float | None:
    """Median days from delivery to payment, on orders already settled.

    Measured only on orders that have been paid, because an unpaid order has
    no lag yet — including them would make the figure move simply because a
    delivery happened, not because collection changed.
    """
    d = prepare(lines, scope)
    if d.empty or "fulfilled_at" not in d.columns or "paid_at" not in d.columns:
        return None
    paid = d[d["cash"] == "collected"]
    if paid.empty:
        return None
    ff = pd.to_datetime(paid["fulfilled_at"], utc=True, errors="coerce",
                        format="mixed").dt.tz_localize(None)
    pp = pd.to_datetime(paid["paid_at"], utc=True, errors="coerce",
                        format="mixed").dt.tz_localize(None)
    lag = (pp - ff).dt.days
    lag = lag[lag.notna() & lag.ge(0)]
    return float(lag.median()) if len(lag) else None


def receivables_aged(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
                     cost_log: pd.DataFrame | None = None) -> dict:
    """Delivered and unpaid, aged from the delivery date."""
    d = attach_cost(prepare(lines, scope), cost_log, plan)
    if d.empty:
        return {}
    owed = d[d["cash"] == "owed"]
    if owed.empty:
        return {"orders": 0, "outstanding": 0.0}

    ff = (pd.to_datetime(owed["fulfilled_at"], utc=True, errors="coerce",
                         format="mixed").dt.tz_localize(None)
          if "fulfilled_at" in owed.columns else pd.Series(pd.NaT,
                                                           index=owed.index))
    basis = np.where(ff.notna(), "delivery", "order date")
    since = ff.fillna(owed["ts"])
    ref = pd.Timestamp(min(date.today(), scope.end))
    age = (ref.normalize() - since.dt.normalize()).dt.days.clip(lower=0)

    o = owed.assign(age=age, basis=basis).groupby("order", observed=True).agg(
        outstanding=("revenue", "sum"), age=("age", "max"),
        basis=("basis", "first"), city=("city", "first"),
        channel=("channel", "first"))

    bands = [(0, 3, "0–3"), (4, 7, "4–7"), (8, 14, "8–14"),
             (15, 30, "15–30"), (31, 10_000, "30+")]
    o["band"] = o["age"].map(
        lambda n: next(l for lo, hi, l in bands if lo <= n <= hi))
    by_band = (o.groupby("band", observed=True)
               .agg(orders=("outstanding", "size"),
                    outstanding=("outstanding", "sum"))
               .reindex([l for _, _, l in bands]).fillna(0).reset_index())

    total = float(o["outstanding"].sum())
    revenue = float(d[d["state"].ne("lost")]["revenue"].sum())
    return {
        "orders": int(len(o)), "outstanding": total,
        "over_14": float(o[o["age"] > 14]["outstanding"].sum()),
        "oldest": int(o["age"].max()), "avg_age": float(o["age"].mean()),
        "share_of_revenue": total / revenue if revenue else None,
        "by_band": by_band,
        "by_city": (o.groupby("city", observed=True)
                    .agg(outstanding=("outstanding", "sum"),
                         avg_age=("age", "mean")).reset_index()
                    .sort_values("outstanding", ascending=False)),
        "by_channel": (o.groupby("channel", observed=True)
                       .agg(outstanding=("outstanding", "sum"),
                            avg_age=("age", "mean")).reset_index()
                       .sort_values("outstanding", ascending=False)),
        "no_delivery_date": int((o["basis"] == "order date").sum()),
        # The order-level rows, so the outstanding can be taken away and
        # worked on rather than only looked at.
        "orders_table": (o.reset_index()
                         .rename(columns={"order": "order",
                                          "age": "days_since_delivery"})
                         .sort_values("days_since_delivery", ascending=False)),
    }


def exceptions(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
               cost_log: pd.DataFrame | None = None) -> list[dict]:
    """Everything making the numbers wrong, ranked by what it is worth."""
    d = attach_cost(prepare(lines, scope), cost_log, plan)
    p = plan_scope(plan, scope)
    out = []

    if not d.empty:
        live = d[d["state"].ne("lost")]
        planned = set(p["product"]) if len(p) else set()
        unplanned = live[~live["product"].isin(planned)]
        if len(unplanned):
            g = (unplanned.groupby("product", observed=True)["revenue"]
                 .sum().sort_values(ascending=False))
            out.append({
                "severity": "high", "value": float(g.sum()),
                "title": f"{len(g)} products sold with no plan row",
                "detail": ", ".join(g.head(5).index),
                "why": "Revenue is counted but attainment cannot be.",
            })

        sold = set(live["product"])
        dead = p[~p["product"].isin(sold)]
        if len(dead):
            g = (dead.groupby("product", observed=True)["plan_revenue_lc"]
                 .sum().sort_values(ascending=False))
            out.append({
                "severity": "medium", "value": float(g.sum()),
                "title": f"{len(g)} products planned, nothing sold",
                "detail": ", ".join(g.head(5).index),
                "why": "Delisted, out of stock, or never launched.",
            })

        pp = product_performance(lines, plan, scope, cost_log)
        if len(pp):
            below = pp[(pp["units"] > 0) & (pp["cm"] < 0)]
            if len(below):
                out.append({
                    "severity": "high", "value": float(below["cm"].sum()),
                    "title": f"{len(below)} products selling below cost",
                    "detail": ", ".join(below["product"].head(5)),
                    "why": "Every box sold loses money.",
                })

        plan_basis = float((d["cost_basis"] == "plan").mean())
        if plan_basis > 0.05:
            out.append({
                "severity": "low", "value": 0.0,
                "title": f"{plan_basis:.0%} of lines have no dated cost",
                "detail": "Margin for those falls back to plan cost.",
                "why": "Cost movement is invisible where the log does not reach.",
            })

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda x: (order[x["severity"]], -abs(x["value"])))


# ------------------------------------------------------------- portfolio


TOLERANCE = {"None": 0.0, "Some": 0.05, "High": 0.12}


def portfolio(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
              cost_log: pd.DataFrame | None = None) -> dict:
    """Where a margin gap can be recovered, or a surplus spent.

    Margin is a weighted average across a mix, so a cost rise on one product
    does not have to be recovered on that product. It has to be recovered
    somewhere, and the right somewhere is wherever demand can absorb it.

    The tool computes what each product would need to close the gap alone —
    a feasibility test, not a proposal — and then lets the business apply
    moves within a tolerance it sets itself. That tolerance is deliberately
    an input rather than an estimate: price and season moved together all
    year in this data, so any elasticity derived from it would be seasonal
    demand wearing a price label.
    """
    d = attach_cost(prepare(lines, scope), cost_log, plan)
    if d.empty:
        return {}
    live = d[d["state"].ne("lost")]
    if live.empty:
        return {}

    p_scope = plan_scope(plan, scope)
    plan_rev = float(p_scope["plan_revenue_lc"].sum())
    plan_cm = float((p_scope["plan_revenue_lc"] - p_scope["plan_cogs_lc"]).sum())
    plan_pct = plan_cm / plan_rev if plan_rev else None

    revenue = float(live["revenue"].sum())
    cogs = float(live["cogs"].sum())
    cm = revenue - cogs
    pct = cm / revenue if revenue else None

    # The gap at the volume actually sold. Comparing against the full plan
    # margin would mix a volume shortfall into a pricing question.
    target_cm = revenue * plan_pct if plan_pct else cm
    gap = cm - target_cm

    g = live.groupby("product", observed=True).agg(
        units=("units", "sum"), revenue=("revenue", "sum"),
        cogs=("cogs", "sum")).reset_index()
    g["price"] = (g["revenue"] / g["units"]).where(g["units"].ne(0))
    g["cost"] = (g["cogs"] / g["units"]).where(g["units"].ne(0))
    g["cm"] = g["revenue"] - g["cogs"]
    g["cm_pct"] = (g["cm"] / g["revenue"]).where(g["revenue"].ne(0))
    g["cm_per_box"] = (g["cm"] / g["units"]).where(g["units"].ne(0))
    g["share"] = g["revenue"] / revenue if revenue else np.nan

    pp = (p_scope.groupby("product", observed=True)
          .apply(lambda x: (x["plan_revenue_lc"].sum() / x["plan_units"].sum())
                 if x["plan_units"].sum() else np.nan,
                 include_groups=False).rename("plan_price").reset_index())
    g = g.merge(pp, on="product", how="left")
    g["price_index"] = (g["price"] / g["plan_price"]).where(
        g["plan_price"].notna() & g["plan_price"].ne(0))

    # What this product alone would need. A price move changes margin by the
    # move times that product's revenue, so the required move is simply the
    # gap over its revenue.
    g["alone_pct"] = (-gap / g["revenue"]).where(g["revenue"].ne(0))
    g["feasible"] = g["alone_pct"].abs() <= 0.10

    return {
        "revenue": revenue, "cm": cm, "cm_pct": pct,
        "plan_cm_pct": plan_pct, "target_cm": target_cm, "gap": gap,
        "direction": "recover" if gap < 0 else "spend",
        "points": (pct - plan_pct) * 100 if pct and plan_pct else None,
        "cost_basis": ("dated" if (d["cost_basis"] == "dated").any()
                       else "plan"),
        "products": g.sort_values("revenue", ascending=False).reset_index(drop=True),
    }


def apply_moves(pf: dict, moves: dict) -> dict:
    """What a set of price moves does to the mix.

    Volume is held flat on purpose. The point is not to predict what happens
    to demand — it is to state the break-even, so the person who knows the
    market can judge whether the trade is worth taking.
    """
    if not pf:
        return {}
    g = pf["products"].copy()
    g["move"] = g["product"].map(moves).fillna(0.0) / 100.0
    g["new_price"] = g["price"] * (1 + g["move"])
    g["new_revenue"] = g["units"] * g["new_price"]
    g["new_cm"] = g["new_revenue"] - g["cogs"]
    g["new_cm_pct"] = (g["new_cm"] / g["new_revenue"]).where(
        g["new_revenue"].ne(0))
    g["cm_change"] = g["new_cm"] - g["cm"]

    new_rev = float(g["new_revenue"].sum())
    new_cm = float(g["new_cm"].sum())
    recovered = new_cm - pf["cm"]

    # How much volume the move can cost before it is worse than doing
    # nothing. Margin per box rises, so fewer boxes can carry the same total.
    breakeven = None
    if new_cm > 0 and pf["cm"] > 0:
        breakeven = pf["cm"] / new_cm - 1

    below = g[g["new_cm"] < 0]
    return {
        "table": g, "new_revenue": new_rev, "new_cm": new_cm,
        "new_cm_pct": new_cm / new_rev if new_rev else None,
        "recovered": recovered,
        "gap_after": new_cm - pf["target_cm"],
        "closed_share": (recovered / -pf["gap"]
                         if pf["gap"] and pf["gap"] < 0 else None),
        "breakeven_volume": breakeven,
        "below_cost": below["product"].tolist(),
        "moved": int((g["move"].abs() > 0).sum()),
    }


# --------------------------------------------------------- data quality


def data_quality(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
                 cost_log: pd.DataFrame | None = None,
                 fx: pd.DataFrame | None = None,
                 raw_plan: pd.DataFrame | None = None) -> dict:
    """Everything wrong with the inputs, grouped by where it must be fixed.

    Grouped by source rather than by severity, because that is what decides
    who fixes it. A name mismatch is a Shopify job, a missing plan row is a
    workbook job, and a reconciliation failure is a code job. Ranking them
    together by money would mix three different queues.

    Every finding carries a count, what it is worth, and what to do — a
    warning without an action is only an apology.
    """
    out = {"sheet": [], "shopify": [], "consistency": []}

    d = attach_cost(prepare(lines, scope), cost_log, plan)
    p_all = plan[plan["plan_units"] > 0]
    p = plan_scope(plan, scope)

    # ---- the workbook
    if len(p_all):
        below = p_all[p_all["plan_cogs_unit_lc"] >= p_all["plan_price_lc"]]
        if len(below):
            out["sheet"].append({
                "severity": "high",
                "title": f"{len(below)} plan rows priced at or below cost",
                "value": float((below["plan_cogs_lc"]
                                - below["plan_revenue_lc"]).sum()),
                "detail": ", ".join(below["product"].unique()[:5]),
                "action": "Correct the price or the cost in the Plan sheet."})

        cm_pct = (p_all["plan_cm_lc"] / p_all["plan_revenue_lc"]).where(
            p_all["plan_revenue_lc"].ne(0))
        thin = p_all[(cm_pct > 0) & (cm_pct < 0.10)]
        if len(thin):
            out["sheet"].append({
                "severity": "medium",
                "title": f"{len(thin)} plan rows below 10% margin",
                "value": float(thin["plan_revenue_lc"].sum()),
                "detail": ", ".join(thin["product"].unique()[:5]),
                "action": "Deliberate, or a pricing error worth checking."})

        dupes = plan.duplicated(["product", "market", "month"]).sum()
        if dupes:
            out["sheet"].append({
                "severity": "high",
                "title": f"{dupes} duplicate product, market and month rows",
                "value": 0.0, "detail": "The same cell planned twice.",
                "action": "Remove the duplicates — totals are being "
                          "double counted."})

        gaps = []
        for mk in MARKETS:
            have = set(p_all[p_all["market"] == mk]["month"])
            missing = [m for m in MONTHS if m not in have]
            if missing and len(missing) < 12:
                gaps.append(f"{mk}: {', '.join(missing[:4])}"
                            + ("…" if len(missing) > 4 else ""))
        if gaps:
            out["sheet"].append({
                "severity": "low",
                "title": f"{len(gaps)} markets have months with no plan",
                "value": 0.0, "detail": " · ".join(gaps),
                "action": "Blank is treated as absent, not zero. Add rows "
                          "only if those months were meant to sell."})

    # ---- FX
    if fx is not None and len(fx):
        placeholders = {"SAR": 0.98, "QAR": 1.008, "EGP": 0.076}
        flagged = [c for c, v in placeholders.items()
                   if c in fx.columns
                   and bool(np.isclose(fx[c].dropna(), v, atol=1e-6).any())]
        if flagged:
            out["sheet"].append({
                "severity": "high",
                "title": f"{len(flagged)} FX rates look like placeholders",
                "value": 0.0, "detail": ", ".join(flagged),
                "action": "Every consolidated AED figure moves when these "
                          "are corrected."})
        if "EGP" in fx.columns:
            egp = fx["EGP"].dropna()
            if len(egp) and (egp.max() > 0.5 or egp.min() < 0.001):
                out["sheet"].append({
                    "severity": "high",
                    "title": "The EGP rate is outside a plausible range",
                    "value": 0.0,
                    "detail": f"between {egp.min():.4f} and {egp.max():.4f}",
                    "action": "A factor of ten here silently multiplies or "
                              "divides Egypt by ten in every AED view."})

    # ---- cost log
    cls = cost_log_status(cost_log)
    if not cls:
        out["sheet"].append({
            "severity": "high", "title": "No cost log",
            "value": 0.0,
            "detail": "Margin is calculated at plan cost everywhere.",
            "action": "Add a Cost_Log sheet so cost movement becomes visible."})
    else:
        if (cls.get("days_old") or 0) > 30:
            out["sheet"].append({
                "severity": "medium",
                "title": f"Cost log last updated {cls['days_old']} days ago",
                "value": 0.0,
                "detail": f"latest entry {cls['latest']:%d %b %Y}",
                "action": "Margin uses the last entered cost, which may no "
                          "longer be what you pay."})
        if not d.empty:
            share = float((d["cost_basis"] == "plan").mean())
            if share > 0.05:
                out["sheet"].append({
                    "severity": "medium",
                    "title": f"{share:.0%} of lines have no dated cost",
                    "value": 0.0,
                    "detail": "Those fall back to plan cost.",
                    "action": "Cost movement is invisible where the log does "
                              "not reach."})

    # ---- Shopify
    if not d.empty:
        live = d[d["state"].ne("lost")]
        planned = set(p_all["product"])
        unmatched = live[~live["product"].isin(planned)]
        if len(unmatched):
            g = (unmatched.groupby("product", observed=True)["revenue"]
                 .sum().sort_values(ascending=False))
            out["shopify"].append({
                "severity": "high",
                "title": f"{len(g)} store product names never reach a plan row",
                "value": float(g.sum()),
                "detail": ", ".join(g.head(6).index),
                "action": "Rename in Shopify to match the plan, or add an "
                          "Aliases row. Until then this revenue counts but "
                          "cannot be measured against plan.",
                "table": g.reset_index().rename(
                    columns={"revenue": "revenue"})})

        delivered = d[d["state"] == "delivered"]
        if len(delivered) and "fulfilled_at" in delivered.columns:
            no_date = delivered["fulfilled_at"].isna().sum()
            if no_date:
                out["shopify"].append({
                    "severity": "medium",
                    "title": f"{no_date:,} delivered lines have no delivery date",
                    "value": 0.0,
                    "detail": "Ageing falls back to the order date.",
                    "action": "Payment ageing understates how long cash has "
                              "been out."})

        if "paid_at" in d.columns:
            paid = d[d["cash"] == "collected"]
            if len(paid):
                missing = paid["paid_at"].isna().sum()
                if missing > len(paid) * 0.1:
                    out["shopify"].append({
                        "severity": "medium",
                        "title": f"{missing:,} paid lines have no payment date",
                        "value": 0.0,
                        "detail": f"of {len(paid):,} paid lines",
                        "action": "Days to reconcile is measured on the rest "
                                  "only."})

        if "order_subtotal" in d.columns:
            per_order = live.groupby("order", observed=True).agg(
                lines_net=("revenue", "sum"),
                shopify=("order_subtotal", "first"))
            per_order = per_order[per_order["shopify"] > 0]
            if len(per_order):
                gap = (per_order["lines_net"] - per_order["shopify"]).abs()
                off = (gap / per_order["shopify"] > 0.02).sum()
                drift = float(gap.sum() / per_order["shopify"].sum())
                if drift > 0.01:
                    out["shopify"].append({
                        "severity": "high",
                        "title": f"Line items differ from Shopify's own "
                                 f"subtotals by {drift:.1%}",
                        "value": float(gap.sum()),
                        "detail": f"{off:,} of {len(per_order):,} orders "
                                  f"differ by more than 2%",
                        "action": "Usually order-level discounts. If it grows, "
                                  "the revenue read is drifting."})

        dead = p[~p["product"].isin(set(live["product"]))] if len(p) else p
        if len(dead):
            g = (dead.groupby("product", observed=True)["plan_revenue_lc"]
                 .sum().sort_values(ascending=False))
            out["shopify"].append({
                "severity": "low",
                "title": f"{len(g)} planned products sold nothing",
                "value": float(g.sum()),
                "detail": ", ".join(g.head(5).index),
                "action": "Delisted, out of stock, or never launched."})

    # ---- consistency
    c = cards(lines, plan, scope, cost_log)
    if not c.get("empty"):
        problems = check_chain(c)
        if problems:
            out["consistency"].append({
                "severity": "high", "title": "The cards do not reconcile",
                "value": 0.0, "detail": " · ".join(problems),
                "action": "Do not act on these figures until it is fixed."})
        bad = []
        for m in ("orders", "units", "revenue", "margin"):
            steps = gap_decomposition(c, m)
            if not steps:
                continue
            tot = steps[0]["value"] + sum(x["value"] for x in steps[1:-1])
            if abs(tot - steps[-1]["value"]) > max(1.0,
                                                   abs(steps[-1]["value"]) * .01):
                bad.append(m)
        if bad:
            out["consistency"].append({
                "severity": "high",
                "title": f"{len(bad)} gap decompositions do not reconcile",
                "value": 0.0, "detail": ", ".join(bad),
                "action": "A bridge that does not add up is worse than none."})

    order = {"high": 0, "medium": 1, "low": 2}
    for k in out:
        out[k] = sorted(out[k], key=lambda x: (order[x["severity"]],
                                               -abs(x.get("value") or 0)))
    out["total"] = sum(len(v) for v in
                       (out["sheet"], out["shopify"], out["consistency"]))
    out["high"] = sum(1 for v in (out["sheet"] + out["shopify"]
                                  + out["consistency"])
                      if v["severity"] == "high")
    out["at_stake"] = sum(abs(x.get("value") or 0)
                          for x in out["sheet"] + out["shopify"])
    return out


# --------------------------------------------------------- monthly close


def closeout(lines: pd.DataFrame, plan: pd.DataFrame, scope: Scope,
             cost_log: pd.DataFrame | None = None) -> dict:
    """The month as accounting closes it, in money and in boxes.

    Two movement schedules that must each tie, and must tie to each other:
    a delivery adds to the receivable and removes from the order book in the
    same event.

    The dates are the point. Revenue is recognised when the goods are
    delivered, so an order placed in June and delivered in July is July
    revenue. Cash is dated by the payment stamp, because reconciling with
    the delivery company catches up after the fact — of what is collected in
    July, some will be for June deliveries, and the schedule follows that
    rather than tidying it away.

    Opening balances carry everything outstanding from all prior periods,
    not merely the previous month.

    Refunded and cancelled orders never enter revenue at all, so there is no
    credit note line to reverse them out of.
    """
    # The whole year in scope, so opening balances can be built from every
    # prior period rather than only the month being closed.
    full = Scope(scope.year, scope.market, None,
                 categories=scope.categories, products=scope.products)
    d = attach_cost(prepare(lines, full), cost_log, plan)
    if d.empty:
        return {}

    start = pd.Timestamp(scope.start)
    end = pd.Timestamp(scope.end) + pd.Timedelta(days=1)

    def stamp(col):
        if col not in d.columns:
            return pd.Series(pd.NaT, index=d.index)
        return (pd.to_datetime(d[col], utc=True, errors="coerce",
                               format="mixed").dt.tz_localize(None)
                .astype("datetime64[ns]"))

    delivered_at = stamp("fulfilled_at")
    paid_at = stamp("paid_at")

    # A delivered line with no delivery stamp still has to fall somewhere, so
    # it uses the order date and the count of those is reported. Dropping it
    # would silently shrink revenue; guessing a date would silently move it.
    is_delivered = d["state"].eq("delivered")
    deliv_date = delivered_at.where(delivered_at.notna(), d["ts"])
    no_deliv_stamp = int((is_delivered & delivered_at.isna()).sum())

    is_paid = d["cash"].eq("collected")

    # Most cash-on-delivery orders are marked paid by hand and carry no
    # transaction record, so Shopify does not know when they were paid. The
    # schedule therefore dates collection by delivery: an order is treated as
    # collected in the period it was delivered, once it is marked paid.
    #
    # The consequence is stated on the page rather than hidden: opening and
    # closing show delivered-but-unpaid status, not the timing of cash. Using
    # the sparse payment stamps instead would have covered under a fifth of
    # the business and left the rest silently mis-dated.
    #
    # Where a real payment stamp exists it is still used, but never earlier
    # than the delivery — a receivable cannot be settled before it exists.
    pay_date = paid_at.where(paid_at.notna(), deliv_date)
    pay_date = pay_date.where(pay_date >= deliv_date, deliv_date)
    no_pay_stamp = int((is_paid & paid_at.isna()).sum())
    has_pay_stamp = int((is_paid & paid_at.notna()).sum())
    early_pay = int((is_paid & paid_at.notna() & (paid_at < deliv_date)).sum())

    lost = d["state"].eq("lost")
    live = ~lost

    # ---- money
    del_before = is_delivered & (deliv_date < start)
    del_in = is_delivered & (deliv_date >= start) & (deliv_date < end)
    paid_before = is_paid & (pay_date < start)
    paid_in = is_paid & (pay_date >= start) & (pay_date < end)

    opening_money = float(d.loc[del_before, "revenue"].sum()
                          - d.loc[paid_before, "revenue"].sum())
    delivered_money = float(d.loc[del_in, "revenue"].sum())
    collected_money = float(d.loc[paid_in, "revenue"].sum())
    closing_money = opening_money + delivered_money - collected_money

    # Of what was collected this period, how much related to deliveries made
    # earlier. The two do not sit in the same month and saying so is the
    # point of dating them separately.
    collected_prior = float(d.loc[paid_in & del_before, "revenue"].sum())

    # ---- boxes
    ord_before = live & (d["ts"] < start)
    ord_in = live & (d["ts"] >= start) & (d["ts"] < end)
    lost_in = lost & (d["ts"] >= start) & (d["ts"] < end)
    lost_before = lost & (d["ts"] < start)

    opening_boxes = float(d.loc[ord_before, "units"].sum()
                          - d.loc[del_before, "units"].sum())
    ordered_boxes = float(d.loc[ord_in, "units"].sum())
    delivered_boxes = float(d.loc[del_in, "units"].sum())
    cancelled_boxes = float(d.loc[lost_in, "lost_units"].sum())
    closing_boxes = (opening_boxes + ordered_boxes - delivered_boxes)

    # ---- per SKU, the same movement
    def by_sku(mask, col):
        return (d.loc[mask].groupby("product", observed=True)[col]
                .sum().rename(col))

    sku = pd.concat([
        (d.loc[ord_before, "units"].groupby(d.loc[ord_before, "product"]).sum()
         - d.loc[del_before, "units"].groupby(
             d.loc[del_before, "product"]).sum().reindex(
             d.loc[ord_before, "product"].unique()).fillna(0)
         ).rename("opening"),
        by_sku(ord_in, "units").rename("ordered"),
        by_sku(del_in, "units").rename("delivered"),
        by_sku(lost_in, "lost_units").rename("cancelled"),
    ], axis=1).fillna(0.0)
    sku["closing"] = sku["opening"] + sku["ordered"] - sku["delivered"]

    # Oldest open commitment per product, which is where a book turns into a
    # loss on something perishable.
    open_lines = d[live & (d["ts"] < end) & (~del_in) & (~del_before)]
    if len(open_lines):
        age = (pd.Timestamp(min(date.today(), scope.end))
               - open_lines["ts"].dt.normalize()).dt.days.clip(lower=0)
        oldest = age.groupby(open_lines["product"]).max().rename("oldest_days")
        sku = sku.join(oldest)
    sku["oldest_days"] = sku.get("oldest_days", pd.Series(dtype=float))
    sku = sku.reset_index().rename(columns={"index": "product"})
    sku = sku.sort_values("closing", ascending=False).reset_index(drop=True)

    # ---- ageing of the closing receivable
    #
    # Exactly the population behind the closing balance: delivered on or
    # before the period end, and not yet collected by then. Computing it any
    # other way would let the ageing and the schedule disagree, which is the
    # one thing a reconciliation cannot survive.
    owed_mask = (is_delivered & (deliv_date < end)
                 & ~(is_paid & (pay_date < end)))
    still_owed = d[owed_mask]
    ageing = pd.DataFrame(columns=["band", "amount"])
    by_month = pd.DataFrame(columns=["delivered", "amount"])
    if len(still_owed):
        ref = pd.Timestamp(min(date.today(), scope.end))
        sub_age = (ref - deliv_date[still_owed.index].dt.normalize()
                   ).dt.days.clip(lower=0)
        bands = [(0, 7, "0–7"), (8, 14, "8–14"), (15, 30, "15–30"),
                 (31, 60, "31–60"), (61, 10_000, "60+")]
        band = sub_age.map(
            lambda x: next(l for lo, hi, l in bands if lo <= x <= hi))
        ageing = (still_owed.assign(band=band)
                  .groupby("band", observed=True)["revenue"].sum()
                  .reindex([l for _, _, l in bands]).fillna(0)
                  .reset_index(name="amount"))
        mon = deliv_date[still_owed.index].dt.month.map(
            lambda m: MONTHS[m - 1])
        by_month = (still_owed.assign(delivered=mon)
                    .groupby("delivered", observed=True)["revenue"].sum()
                    .reset_index(name="amount")
                    .sort_values("amount", ascending=False))

    # ---- open items, for reconciliation
    open_receivable = pd.DataFrame()
    if len(still_owed):
        ref = pd.Timestamp(min(date.today(), scope.end))
        open_receivable = (still_owed.assign(
            delivered_on=deliv_date[still_owed.index].dt.date,
            days=(ref - deliv_date[still_owed.index].dt.normalize()).dt.days)
            .groupby("order", observed=True)
            .agg(market=("market", "first"),
                 delivered_on=("delivered_on", "min"),
                 days=("days", "max"), amount=("revenue", "sum"),
                 boxes=("units", "sum"), channel=("channel", "first"))
            .reset_index().sort_values("days", ascending=False))

    return {
        "money": {
            "opening": opening_money, "delivered": delivered_money,
            "collected": collected_money, "closing": closing_money,
            "collected_prior": collected_prior,
            "collected_current": collected_money - collected_prior,
        },
        "boxes": {
            "opening": opening_boxes, "ordered": ordered_boxes,
            "delivered": delivered_boxes, "cancelled": cancelled_boxes,
            "closing": closing_boxes,
        },
        "orders_delivered": int(d.loc[del_in, "order"].nunique()),
        "orders_delivered_prior_month": int(
            d.loc[del_in & (d["ts"] < start), "order"].nunique()),
        "sku": sku, "ageing": ageing, "by_delivery_month": by_month,
        "open_receivable": open_receivable,
        "no_delivery_stamp": no_deliv_stamp,
        "no_payment_stamp": no_pay_stamp,
        "has_payment_stamp": has_pay_stamp,
        "payment_stamp_share": (has_pay_stamp / (has_pay_stamp + no_pay_stamp)
                                if (has_pay_stamp + no_pay_stamp) else None),
        "paid_before_delivery": early_pay,
        "period": scope.label,
    }


def check_closeout(co: dict, tolerance: float = 0.01) -> list[str]:
    """Both schedules must tie, and the delivery must agree across them.

    A movement schedule that does not add up is not a schedule, and the two
    only mean anything together if the same delivery appears in both.
    """
    if not co:
        return []
    problems = []
    m, b = co["money"], co["boxes"]

    calc = m["opening"] + m["delivered"] - m["collected"]
    if abs(calc - m["closing"]) > max(1.0, abs(m["closing"]) * tolerance):
        problems.append(
            f"receivable does not tie: {calc:,.2f} against {m['closing']:,.2f}")

    calc_b = b["opening"] + b["ordered"] - b["delivered"]
    if abs(calc_b - b["closing"]) > max(0.5, abs(b["closing"]) * tolerance):
        problems.append(
            f"order book does not tie: {calc_b:,.1f} against {b['closing']:,.1f}")

    if abs(m["collected_prior"] + m["collected_current"]
           - m["collected"]) > max(1.0, m["collected"] * tolerance):
        problems.append("the split of collected does not sum to collected")

    sku = co.get("sku")
    if sku is not None and len(sku):
        for col, total in (("opening", b["opening"]), ("ordered", b["ordered"]),
                           ("delivered", b["delivered"]),
                           ("closing", b["closing"])):
            s = float(sku[col].sum())
            if abs(s - total) > max(0.5, abs(total) * tolerance):
                problems.append(
                    f"SKU {col} sums to {s:,.1f}, schedule says {total:,.1f}")

    if m["closing"] < -1:
        problems.append(f"closing receivable is negative: {m['closing']:,.2f}")
    if b["closing"] < -1:
        problems.append(f"closing order book is negative: {b['closing']:,.1f}")

    return problems
