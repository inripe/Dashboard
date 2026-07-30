"""Plan engine — Inripe sales plan.

Reads the Plan sheet and turns a monthly plan into a daily spine, so plan
and actual can be compared on any date without re-deriving anything.

Rules enforced here:
  * Revenue, COGS and CM are recomputed from units, price and unit cost.
    The workbook's formulas are never trusted as input.
  * Weighted averages are always total ÷ total. Never the mean of a ratio.
    wavg_price = revenue / units, at every level of aggregation.
  * Paced plan = month plan x days elapsed / days in month. Pacing uses
    sellable days when the availability layer supplies them, calendar days
    otherwise.
  * Missing is not zero. A product with no plan row for a month is absent,
    not planned at zero.
  * Local currency is the source of truth. AED is derived via the FX sheet
    and is always labelled as such.

Pure pandas. No Streamlit, no file paths, no network.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_NO = {m: i + 1 for i, m in enumerate(MONTHS)}
MARKETS = ["UAE", "QA", "KSA", "EG"]
CURRENCY = {"UAE": "AED", "QA": "QAR", "KSA": "SAR", "EG": "EGP"}

REQUIRED = [
    "product_id", "category", "product", "market", "currency", "month",
    "plan_units", "plan_price_lc", "plan_cogs_unit_lc",
]

# Aggregations are always additive. Ratios are derived from these at the end,
# never averaged, which is what keeps weighted averages correct at any level.
ADDITIVE = ["plan_units", "plan_revenue_lc", "plan_cogs_lc", "plan_cm_lc"]


class PlanError(ValueError):
    """Raised when the plan sheet cannot be interpreted."""


@dataclass(frozen=True)
class Pace:
    """How far through a month a given date sits."""

    month: str
    days_total: int
    days_elapsed: int

    @property
    def fraction(self) -> float:
        return 0.0 if self.days_total == 0 else self.days_elapsed / self.days_total


# ------------------------------------------------------------------ loading


def normalise(plan: pd.DataFrame) -> pd.DataFrame:
    """Trim, validate, coerce types. Raises rather than guessing.

    The sheet may name products in two columns: store_product_name, which is
    what Shopify calls it and is the join key, and inhouse_product_name,
    which is the label the business uses. Older single-column sheets still
    work unchanged.
    """
    import variance_engine as _ve

    df = _ve.apply_naming(plan)
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise PlanError(f"missing columns: {missing}")

    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: v.strip() if isinstance(v, str) else v)

    df = df[df["plan_units"].notna()].copy()
    if df.empty:
        raise PlanError("no rows carry a plan")

    for c in ("plan_units", "plan_price_lc", "plan_cogs_unit_lc"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    blank = df[df[["plan_units", "plan_price_lc", "plan_cogs_unit_lc"]].isna().any(axis=1)]
    if len(blank):
        rows = blank[["product", "market", "month"]].to_dict("records")
        raise PlanError(f"rows with a unit count but no price or cost: {rows[:5]}")

    bad_month = sorted(set(df["month"]) - set(MONTHS))
    if bad_month:
        raise PlanError(f"unknown months: {bad_month}")
    bad_market = sorted(set(df["market"]) - set(MARKETS))
    if bad_market:
        raise PlanError(f"unknown markets: {bad_market}")

    df["currency"] = df["market"].map(CURRENCY)
    df["month_no"] = df["month"].map(MONTH_NO)

    dupe = df.duplicated(["product", "market", "month"]).sum()
    if dupe:
        raise PlanError(f"{dupe} duplicate product x market x month rows")

    return df.reset_index(drop=True)


def derive(plan: pd.DataFrame) -> pd.DataFrame:
    """Recompute money columns from units, price and unit cost.

    Any revenue or CM already in the sheet is discarded. One calculation
    path, owned here.
    """
    df = normalise(plan)
    df["plan_revenue_lc"] = df["plan_units"] * df["plan_price_lc"]
    df["plan_cogs_lc"] = df["plan_units"] * df["plan_cogs_unit_lc"]
    df["plan_cm_lc"] = df["plan_revenue_lc"] - df["plan_cogs_lc"]
    return df


def attach_fx(plan: pd.DataFrame, fx: pd.DataFrame) -> pd.DataFrame:
    """Add fx_to_aed and the three AED columns.

    fx is the FX sheet: a month column plus one column per currency,
    each holding the rate to AED.
    """
    f = fx.copy()
    f.columns = [str(c).strip() for c in f.columns]
    if "month" not in f.columns:
        raise PlanError("FX sheet has no month column")
    long = f.melt(id_vars="month", var_name="currency", value_name="fx_to_aed")
    long["month"] = long["month"].map(lambda v: str(v).strip())
    long = long[long["fx_to_aed"].notna()]

    out = plan.merge(long, on=["month", "currency"], how="left")
    miss = out[out["fx_to_aed"].isna()]
    if len(miss):
        pairs = sorted({(m, c) for m, c in zip(miss["month"], miss["currency"])})
        raise PlanError(f"no FX rate for: {pairs[:5]}")

    for lc, aed in (("plan_revenue_lc", "plan_revenue_aed"),
                    ("plan_cogs_lc", "plan_cogs_aed"),
                    ("plan_cm_lc", "plan_cm_aed")):
        out[aed] = out[lc] * out["fx_to_aed"]
    return out


# ------------------------------------------------------------------ pacing


def days_in_month(year: int, month: str) -> int:
    return calendar.monthrange(year, MONTH_NO[month])[1]


def pace_on(year: int, month: str, as_of: date,
            sellable: pd.DataFrame | None = None,
            product: str | None = None, market: str | None = None) -> Pace:
    """How much of a month's plan should have landed by as_of.

    When a sellable-days table is supplied, pacing runs on sellable days,
    so a product that opens on the 20th is judged on its own window rather
    than the whole month. Otherwise it falls back to calendar days.
    """
    n = MONTH_NO[month]
    total = days_in_month(year, month)

    if sellable is not None and product is not None and market is not None:
        s = sellable[(sellable["product"] == product)
                     & (sellable["market"] == market)
                     & (sellable["month"] == month)]
        if len(s):
            days = pd.to_datetime(s["date"]).dt.date
            total = int(days.nunique())
            elapsed = int((days <= as_of).sum())
            return Pace(month, total, elapsed)

    if as_of.year > year or (as_of.year == year and as_of.month > n):
        return Pace(month, total, total)
    if as_of.year < year or (as_of.year == year and as_of.month < n):
        return Pace(month, total, 0)
    return Pace(month, total, min(as_of.day, total))


def paced(plan: pd.DataFrame, year: int, as_of: date,
          sellable: pd.DataFrame | None = None) -> pd.DataFrame:
    """Add a paced_* column for every additive measure.

    Paced plan is what the plan says should have been achieved by as_of.
    It is the only fair comparison against a part-finished month.
    """
    df = plan.copy()
    fracs, totals, elapsed = [], [], []
    for r in df.itertuples():
        p = pace_on(year, r.month, as_of, sellable,
                    getattr(r, "product", None), getattr(r, "market", None))
        fracs.append(p.fraction)
        totals.append(p.days_total)
        elapsed.append(p.days_elapsed)
    df["pace_days_total"] = totals
    df["pace_days_elapsed"] = elapsed
    df["pace_fraction"] = fracs
    for c in ADDITIVE:
        if c in df.columns:
            df["paced_" + c.replace("plan_", "")] = df[c] * df["pace_fraction"]
    for c in ("plan_revenue_aed", "plan_cm_aed"):
        if c in df.columns:
            df["paced_" + c.replace("plan_", "")] = df[c] * df["pace_fraction"]
    return df


# ----------------------------------------------------------------- rollups


def _ratios(df: pd.DataFrame) -> pd.DataFrame:
    """Derive every ratio from summed numerators and denominators.

    This is the rule that keeps a weighted average correct: divide totals,
    never average the row-level ratios.
    """
    out = df.copy()
    u, r, c, m = (out.get(k) for k in ADDITIVE)
    out["plan_cm_pct"] = (m / r).where(r.ne(0))
    out["wavg_price_lc"] = (r / u).where(u.ne(0))
    out["wavg_cogs_lc"] = (c / u).where(u.ne(0))
    return out


def rollup(plan: pd.DataFrame, by: Iterable[str], **filters) -> pd.DataFrame:
    """Aggregate to any level. Ratios are always recomputed after summing."""
    df = plan
    for col, val in filters.items():
        if val is None:
            continue
        wanted = [val] if isinstance(val, str) else list(val)
        if not wanted:
            continue
        df = df[df[col].isin(wanted)]

    by = list(by)
    if df.empty:
        return pd.DataFrame(columns=by + ADDITIVE +
                            ["plan_cm_pct", "wavg_price_lc", "wavg_cogs_lc"])

    cols = [c for c in ADDITIVE if c in df.columns]
    extra = [c for c in df.columns
             if c.startswith("paced_") or c.endswith("_aed")]
    g = df.groupby(by, observed=True)[cols + extra].sum().reset_index()

    if "month" in by:
        g["month"] = pd.Categorical(g["month"], categories=MONTHS, ordered=True)
        g = g.sort_values(by)
    return _ratios(g).reset_index(drop=True)


def market_month(plan: pd.DataFrame, **filters) -> pd.DataFrame:
    """The management view: one row per market per month."""
    return rollup(plan, ["market", "currency", "month"], **filters)


def by_product(plan: pd.DataFrame, **filters) -> pd.DataFrame:
    """One row per product per market, full year."""
    return rollup(plan, ["market", "category", "product"], **filters)


def by_category(plan: pd.DataFrame, **filters) -> pd.DataFrame:
    return rollup(plan, ["market", "category"], **filters)


def totals(plan: pd.DataFrame, **filters) -> dict:
    """Whole-plan totals in AED. Only meaningful once FX is attached."""
    if "plan_revenue_aed" not in plan.columns:
        raise PlanError("attach_fx has not been run, AED totals unavailable")
    df = plan
    for col, val in filters.items():
        if val is None:
            continue
        wanted = [val] if isinstance(val, str) else list(val)
        df = df[df[col].isin(wanted)] if wanted else df
    rev = df["plan_revenue_aed"].sum()
    cm = df["plan_cm_aed"].sum()
    return {
        "units": int(df["plan_units"].sum()),
        "revenue_aed": rev,
        "cogs_aed": df["plan_cogs_aed"].sum(),
        "cm_aed": cm,
        "cm_pct": None if rev == 0 else cm / rev,
        "products": df["product"].nunique(),
        "rows": len(df),
    }


def coverage(plan: pd.DataFrame) -> pd.DataFrame:
    """Which market-months carry a plan at all.

    Blank is not zero: a market-month with no rows is absent here, and any
    view built on this should show n/a rather than 0%.
    """
    have = (plan.groupby(["market", "month"], observed=True)
            .agg(rows=("product", "size"), units=("plan_units", "sum"))
            .reset_index())
    full = pd.MultiIndex.from_product([MARKETS, MONTHS],
                                      names=["market", "month"]).to_frame(index=False)
    out = full.merge(have, on=["market", "month"], how="left")
    out["planned"] = out["rows"].notna()
    out["month"] = pd.Categorical(out["month"], categories=MONTHS, ordered=True)
    return out.sort_values(["market", "month"]).reset_index(drop=True)


# ------------------------------------------------- plan review and changes


def shape(plan: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Plan totals at any grain, with every ratio derived after summing."""
    cols = [c for c in ("plan_units", "plan_revenue_lc", "plan_cogs_lc",
                        "plan_cm_lc", "plan_revenue_aed", "plan_cogs_aed",
                        "plan_cm_aed") if c in plan.columns]
    g = plan.groupby(list(by), observed=True)[cols].sum().reset_index()
    if "plan_revenue_lc" in g:
        g["cm_pct"] = (g["plan_cm_lc"] / g["plan_revenue_lc"]).where(
            g["plan_revenue_lc"].ne(0))
        g["wavg_price"] = (g["plan_revenue_lc"] / g["plan_units"]).where(
            g["plan_units"].ne(0))
        g["wavg_cost"] = (g["plan_cogs_lc"] / g["plan_units"]).where(
            g["plan_units"].ne(0))
    if "plan_revenue_aed" in g:
        g["cm_pct_aed"] = (g["plan_cm_aed"] / g["plan_revenue_aed"]).where(
            g["plan_revenue_aed"].ne(0))
    if "month" in by:
        g["month"] = pd.Categorical(g["month"], categories=MONTHS, ordered=True)
        g = g.sort_values(list(by))
    return g.reset_index(drop=True)


def plan_concentration(plan: pd.DataFrame, by: str = "product",
                       measure: str = "plan_revenue_aed") -> pd.DataFrame:
    """How much of the plan rests on how few things.

    A plan can be perfectly achievable and still fragile. This is the shape
    of that fragility, per market: how much of the year depends on the
    largest product, the largest three, and the largest month.
    """
    if measure not in plan.columns:
        measure = "plan_revenue_lc"
    rows = []
    for mkt, grp in plan.groupby("market", observed=True):
        tot = grp[measure].sum()
        if not tot:
            continue
        s = grp.groupby(by, observed=True)[measure].sum().sort_values(
            ascending=False)
        m = grp.groupby("month", observed=True)[measure].sum().sort_values(
            ascending=False)
        rows.append({
            "market": mkt, "total": tot, "items": int((s > 0).sum()),
            "largest": s.index[0], "top1_share": s.iloc[0] / tot,
            "top3_share": s.head(3).sum() / tot,
            "top5_share": s.head(5).sum() / tot,
            "peak_month": str(m.index[0]), "peak_month_share": m.iloc[0] / tot,
            # How many items it takes to reach half the plan. A small number
            # is a concentrated plan however flat the top share looks.
            "items_to_half": int((s.cumsum() / tot <= 0.5).sum() + 1),
        })
    return pd.DataFrame(rows)


def plan_margin_quality(plan: pd.DataFrame) -> dict:
    """Where the plan is thin or loss-making, before anything is sold.

    Every one of these is knowable in advance. A row planned below cost is a
    decision, not an accident, and it should be a visible one.
    """
    d = plan[plan["plan_units"] > 0].copy()
    if d.empty:
        return {}
    d["cm_pct"] = (d["plan_cm_lc"] / d["plan_revenue_lc"]).where(
        d["plan_revenue_lc"].ne(0))
    below = d[d["plan_cogs_unit_lc"] >= d["plan_price_lc"]]
    thin = d[(d["cm_pct"] > 0) & (d["cm_pct"] < 0.15)]
    rev = d["plan_revenue_lc"].sum()
    return {
        "rows": len(d),
        "below_cost_rows": len(below),
        "below_cost_units": float(below["plan_units"].sum()),
        "below_cost_cm": float(below["plan_cm_lc"].sum()),
        "below_cost_detail": below[["market", "month", "product", "plan_units",
                                    "plan_price_lc", "plan_cogs_unit_lc",
                                    "plan_cm_lc"]],
        "thin_rows": len(thin),
        "thin_revenue_share": float(thin["plan_revenue_lc"].sum() / rev)
        if rev else None,
        "thin_detail": thin[["market", "month", "product", "plan_units",
                             "plan_revenue_lc", "cm_pct"]].sort_values("cm_pct"),
        "cm_pct_min": float(d["cm_pct"].min()),
        "cm_pct_median": float(d["cm_pct"].median()),
        "cm_pct_max": float(d["cm_pct"].max()),
    }


def diff_plans(current: pd.DataFrame, previous: pd.DataFrame) -> dict:
    """What changed between two versions of the plan, and what it cost.

    Matched on product, market and month, so a row that moved month reads as
    one removal and one addition rather than a silent edit. Money impact is
    reported on the same basis for both sides.
    """
    import variance_engine as _ve

    def prep(df):
        d = _ve.apply_naming(df)
        keep = ["product", "market", "month", "plan_units", "plan_price_lc",
                "plan_cogs_unit_lc"]
        d = d[[c for c in keep if c in d.columns]].copy()
        for c in ("plan_units", "plan_price_lc", "plan_cogs_unit_lc"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d[d["plan_units"].notna()]
        d["revenue"] = d["plan_units"] * d["plan_price_lc"]
        d["cm"] = d["plan_units"] * (d["plan_price_lc"] - d["plan_cogs_unit_lc"])
        return d

    cur, prv = prep(current), prep(previous)
    keys = ["product", "market", "month"]
    m = cur.merge(prv, on=keys, how="outer", suffixes=("_now", "_was"),
                  indicator=True)

    added = m[m["_merge"] == "left_only"].copy()
    removed = m[m["_merge"] == "right_only"].copy()
    both = m[m["_merge"] == "both"].copy()

    changed = both[
        (both["plan_units_now"] - both["plan_units_was"]).abs().gt(0.01)
        | (both["plan_price_lc_now"] - both["plan_price_lc_was"]).abs().gt(0.005)
        | (both["plan_cogs_unit_lc_now"]
           - both["plan_cogs_unit_lc_was"]).abs().gt(0.005)].copy()

    for df, a, b in ((changed, "_now", "_was"),):
        df["units_delta"] = df[f"plan_units{a}"] - df[f"plan_units{b}"]
        df["price_delta"] = df[f"plan_price_lc{a}"] - df[f"plan_price_lc{b}"]
        df["cost_delta"] = (df[f"plan_cogs_unit_lc{a}"]
                            - df[f"plan_cogs_unit_lc{b}"])
        df["revenue_delta"] = df[f"revenue{a}"] - df[f"revenue{b}"]
        df["cm_delta"] = df[f"cm{a}"] - df[f"cm{b}"]
        df["what"] = [
            ", ".join(filter(None, [
                "units" if abs(u) > 0.01 else "",
                "price" if abs(p) > 0.005 else "",
                "cost" if abs(c) > 0.005 else ""]))
            for u, p, c in zip(df["units_delta"], df["price_delta"],
                               df["cost_delta"])]

    rev_delta = (added["revenue_now"].sum() - removed["revenue_was"].sum()
                 + changed["revenue_delta"].sum())
    cm_delta = (added["cm_now"].sum() - removed["cm_was"].sum()
                + changed["cm_delta"].sum())

    # A change that pushes a row to or below cost matters more than its size.
    broke = changed[(changed["plan_price_lc_now"]
                     <= changed["plan_cogs_unit_lc_now"])
                    & (changed["plan_price_lc_was"]
                       > changed["plan_cogs_unit_lc_was"])]

    return {
        "added": added, "removed": removed, "changed": changed,
        "n_added": len(added), "n_removed": len(removed),
        "n_changed": len(changed),
        "units_delta": float(added["plan_units_now"].sum()
                             - removed["plan_units_was"].sum()
                             + changed["units_delta"].sum()),
        "revenue_delta": float(rev_delta),
        "cm_delta": float(cm_delta),
        "units_before": float(prv["plan_units"].sum()),
        "units_after": float(cur["plan_units"].sum()),
        "revenue_before": float(prv["revenue"].sum()),
        "revenue_after": float(cur["revenue"].sum()),
        "cm_before": float(prv["cm"].sum()),
        "cm_after": float(cur["cm"].sum()),
        "newly_below_cost": broke,
    }
