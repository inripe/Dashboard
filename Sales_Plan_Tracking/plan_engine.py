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
