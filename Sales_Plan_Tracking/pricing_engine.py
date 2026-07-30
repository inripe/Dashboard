"""Pricing engine — Inripe.

Two things live here, and both deliberately avoid predicting volume.

The simulator answers "what would have to be true". Cut a price ten percent
and it reports the extra volume needed to hold contribution margin. That is
exact arithmetic from price and cost, with nothing estimated. The judgement
of whether that volume is achievable stays with the person who knows the
market, which is not this file.

The alternative would be to estimate elasticity from seven months of data in
which price moved with the season. A regression would credit price for
seasonal demand and return a confident, wrong number. When the WooCommerce
migration brings 2024 and 2025, that becomes answerable. Until then, break
even volume is the honest form of the question.

The advisor is rules on margin arithmetic, not a model. Every recommendation
carries the money at stake and the assumption behind it, and none of them
name an optimal price.

Pure pandas. No Streamlit, no I/O, no network.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class PricingError(ValueError):
    """Raised when a simulation cannot be run honestly."""


# ------------------------------------------------------------- simulator


@dataclass
class Scenario:
    """One price move. Percentages are signed: -10 is a ten percent cut."""

    pct: float = 0.0
    market: str | None = None
    category: str | None = None
    product: str | None = None
    months: list[str] | None = None
    label: str = ""

    def mask(self, df: pd.DataFrame) -> pd.Series:
        m = pd.Series(True, index=df.index)
        if self.market:
            m &= df["market"].eq(self.market)
        if self.category:
            m &= df["category"].eq(self.category)
        if self.product:
            m &= df["product"].eq(self.product)
        if self.months:
            m &= df["month"].isin(self.months)
        return m


def _base(combined: pd.DataFrame, use_actual: bool) -> pd.DataFrame:
    """The rows a scenario acts on, with a price, a cost and a volume.

    Actual basis uses what was really sold and really achieved, so the
    starting point is reality rather than intention. Plan basis is there for
    months that have not happened yet.
    """
    d = combined.copy()
    if use_actual:
        d = d[d["act_units"] > 0].copy()
        d["units"] = d["act_units"]
        d["price"] = (d["act_net_lc"] / d["act_units"]).where(
            d["act_units"].ne(0))
        if "act_cm_dated_lc" in d.columns and d["act_cm_dated_lc"].notna().any():
            d["cost"] = ((d["act_net_lc"] - d["act_cm_dated_lc"])
                         / d["act_units"])
            d["cost_basis"] = "dated"
        else:
            d["cost"] = d["plan_cogs_unit_lc"]
            d["cost_basis"] = "plan"
    else:
        d = d[d["plan_units"] > 0].copy()
        d["units"] = d["plan_units"]
        d["price"] = d["plan_price_lc"]
        d["cost"] = d["plan_cogs_unit_lc"]
        d["cost_basis"] = "plan"

    d = d[d["price"].notna() & d["cost"].notna() & d["price"].gt(0)]
    d["revenue"] = d["units"] * d["price"]
    d["cm"] = d["units"] * (d["price"] - d["cost"])
    return d


def simulate(combined: pd.DataFrame, scenarios: list[Scenario],
             use_actual: bool = True) -> dict:
    """Apply price moves and report what they would require.

    Volume is deliberately held flat. The output is not a prediction that
    nothing changes; it is the baseline against which the break-even figure
    is read. Reporting a guessed volume response would bury the one number
    that can be stated exactly.
    """
    d = _base(combined, use_actual)
    if d.empty:
        raise PricingError("no rows with a usable price and cost in this scope")

    d["new_price"] = d["price"]
    touched = pd.Series(False, index=d.index)
    for s in scenarios:
        m = s.mask(d)
        d.loc[m, "new_price"] = d.loc[m, "new_price"] * (1 + s.pct / 100.0)
        touched |= m

    d["new_revenue"] = d["units"] * d["new_price"]
    d["new_cm"] = d["units"] * (d["new_price"] - d["cost"])

    base_rev, base_cm = d["revenue"].sum(), d["cm"].sum()
    new_rev, new_cm = d["new_revenue"].sum(), d["new_cm"].sum()

    aff = d[touched]
    unit_cm_before = ((aff["price"] - aff["cost"]) * aff["units"]).sum()
    unit_cm_after = ((aff["new_price"] - aff["cost"]) * aff["units"]).sum()

    # The number that decides it. If unit margin fell, how much more volume
    # would restore the old total; if it rose, how much can be given up.
    if unit_cm_after > 0 and unit_cm_before > 0:
        breakeven = unit_cm_before / unit_cm_after - 1.0
    else:
        breakeven = None

    below = aff[aff["new_price"] <= aff["cost"]]
    return {
        "rows": len(d), "rows_affected": int(touched.sum()),
        "base_units": float(d["units"].sum()),
        "base_revenue": float(base_rev), "base_cm": float(base_cm),
        "base_cm_pct": float(base_cm / base_rev) if base_rev else None,
        "new_revenue": float(new_rev), "new_cm": float(new_cm),
        "new_cm_pct": float(new_cm / new_rev) if new_rev else None,
        "revenue_change": float(new_rev - base_rev),
        "cm_change": float(new_cm - base_cm),
        "breakeven_volume_pct": (breakeven * 100.0
                                 if breakeven is not None else None),
        "rows_below_cost_after": len(below),
        "products_below_cost_after": sorted(below["product"].unique().tolist()),
        "basis": "actual" if use_actual else "plan",
        "cost_basis": (d["cost_basis"].mode().iloc[0]
                       if len(d) else "unknown"),
        "detail": d,
    }


def sensitivity(combined: pd.DataFrame, market: str | None = None,
                category: str | None = None, product: str | None = None,
                steps=(-20, -15, -10, -5, 0, 5, 10, 15, 20),
                use_actual: bool = True) -> pd.DataFrame:
    """The same move at a range of sizes, so the shape is visible.

    Break-even volume is not linear in the price change. A five percent cut
    on a thin margin can need far more than half the volume a ten percent cut
    needs, and a table makes that obvious where a single number does not.
    """
    rows = []
    for pct in steps:
        r = simulate(combined,
                     [Scenario(pct=pct, market=market, category=category,
                               product=product)],
                     use_actual=use_actual)
        rows.append({
            "price_change_pct": pct,
            "revenue": r["new_revenue"],
            "cm": r["new_cm"],
            "cm_pct": r["new_cm_pct"],
            "cm_change": r["cm_change"],
            "breakeven_volume_pct": r["breakeven_volume_pct"],
            "below_cost_rows": r["rows_below_cost_after"],
        })
    return pd.DataFrame(rows)


def breakeven_table(combined: pd.DataFrame, pct: float,
                    by: str = "product", market: str | None = None,
                    use_actual: bool = True) -> pd.DataFrame:
    """Break-even volume per product or category for one price move.

    A single blended figure hides that the same cut is trivial on a fifty
    percent margin and impossible on a ten percent one.
    """
    d = _base(combined, use_actual)
    if market:
        d = d[d["market"] == market]
    if d.empty:
        return pd.DataFrame()

    d["new_price"] = d["price"] * (1 + pct / 100.0)
    d["cm_before"] = (d["price"] - d["cost"]) * d["units"]
    d["cm_after"] = (d["new_price"] - d["cost"]) * d["units"]

    keys = ["market", by] if by != "market" else ["market"]
    g = d.groupby(keys, observed=True).agg(
        units=("units", "sum"), revenue=("revenue", "sum"),
        cm_before=("cm_before", "sum"), cm_after=("cm_after", "sum")).reset_index()
    g["cm_pct_before"] = g["cm_before"] / g["revenue"]
    g["breakeven_volume_pct"] = np.where(
        g["cm_after"] > 0, (g["cm_before"] / g["cm_after"] - 1) * 100, np.nan)
    g["verdict"] = np.where(
        g["cm_after"] <= 0, "below cost after the move",
        np.where(g["breakeven_volume_pct"].abs() < 10, "easy",
                 np.where(g["breakeven_volume_pct"].abs() < 30, "demanding",
                          "unlikely")))
    return g.sort_values("breakeven_volume_pct",
                         ascending=False).reset_index(drop=True)


# --------------------------------------------------------------- advisor


def advise(combined: pd.DataFrame, plan: pd.DataFrame,
           cost_log: pd.DataFrame | None = None,
           market: str | None = None, month: str | None = None,
           min_units: int = 20) -> pd.DataFrame:
    """Ranked pricing recommendations, each with the money at stake.

    Rules on margin arithmetic, not a model. Nothing here names an optimal
    price, because that needs an elasticity this data cannot yet identify.
    Every row states what is wrong, what it costs, and what would have to be
    true for a price move to fix it.
    """
    d = combined.copy()
    if market:
        d = d[d["market"] == market]
    if month:
        d = d[d["month"] == month]
    sold = d[d["act_units"] >= min_units].copy()
    if sold.empty:
        return pd.DataFrame(columns=["severity", "stake", "product", "market",
                                     "issue", "detail", "action"])

    sold["price"] = sold["act_net_lc"] / sold["act_units"]
    if ("act_cm_dated_lc" in sold.columns
            and sold["act_cm_dated_lc"].notna().any()):
        sold["cost"] = ((sold["act_net_lc"] - sold["act_cm_dated_lc"])
                        / sold["act_units"])
        basis = "dated cost"
    else:
        sold["cost"] = sold["plan_cogs_unit_lc"]
        basis = "plan cost"
    sold = sold[sold["cost"].notna()]
    sold["cm_unit"] = sold["price"] - sold["cost"]
    sold["cm_pct"] = (sold["cm_unit"] / sold["price"]).where(sold["price"].gt(0))
    sold["cm_total"] = sold["cm_unit"] * sold["act_units"]

    out = []

    # 1. Selling below cost. Every extra box loses money.
    loss = sold[sold["cm_unit"] < 0]
    for r in loss.itertuples():
        need = (-r.cm_unit / r.price) * 100
        out.append({
            "severity": "urgent", "stake": abs(r.cm_total),
            "product": r.product, "market": r.market, "month": str(r.month),
            "issue": "selling below cost",
            "detail": (f"{r.act_units:,.0f} boxes at {r.price:,.2f} against a "
                       f"{basis} of {r.cost:,.2f}. Losing "
                       f"{abs(r.cm_unit):,.2f} a box, {abs(r.cm_total):,.0f} "
                       f"in total."),
            "action": (f"Raise price {need:.0f}% to break even, or stop "
                       f"selling it."),
        })

    # 2. Achieved price below plan price. Discount or downtrading.
    gap = sold[(sold["plan_price_lc"] > 0)
               & (sold["price"] < sold["plan_price_lc"] * 0.90)]
    for r in gap.itertuples():
        lost = (r.plan_price_lc - r.price) * r.act_units
        out.append({
            "severity": "high" if lost > 5000 else "medium", "stake": lost,
            "product": r.product, "market": r.market, "month": str(r.month),
            "issue": "achieved price below plan",
            "detail": (f"Achieved {r.price:,.2f} against a plan of "
                       f"{r.plan_price_lc:,.2f}, "
                       f"{r.price / r.plan_price_lc - 1:+.0%}. "
                       f"{lost:,.0f} of revenue given away on "
                       f"{r.act_units:,.0f} boxes."),
            "action": ("Check whether this is discounting or a shift to "
                       "cheaper grades. The two need different fixes."),
        })

    # 3. Cost moved but price did not. Silent margin erosion.
    if cost_log is not None and len(cost_log):
        try:
            import variance_engine as ve
            cl = ve.normalise_cost_log(cost_log)
        except Exception:
            cl = pd.DataFrame()
        if len(cl):
            moves = (cl.sort_values("valid_from")
                     .groupby(["product", "market"], observed=True)
                     .agg(first_cost=("cogs_unit_lc", "first"),
                          last_cost=("cogs_unit_lc", "last"),
                          changes=("cogs_unit_lc", "size")).reset_index())
            moves = moves[moves["changes"] > 1]
            m = sold.merge(moves, on=["product", "market"], how="inner")
            for r in m.itertuples():
                rise = r.last_cost - r.first_cost
                if rise <= 0:
                    continue
                erosion = rise * r.act_units
                out.append({
                    "severity": "high" if erosion > 5000 else "medium",
                    "stake": erosion, "product": r.product, "market": r.market,
                    "month": str(r.month),
                    "issue": "cost rose, price held",
                    "detail": (f"Cost moved {r.first_cost:,.2f} to "
                               f"{r.last_cost:,.2f}, up {rise:,.2f} a box. "
                               f"Price unchanged, so {erosion:,.0f} of margin "
                               f"has quietly gone."),
                    "action": (f"A {rise / r.price * 100:.0f}% price rise "
                               f"restores the original margin."),
                })

    # 4. Thin margin carrying real volume.
    thin = sold[(sold["cm_pct"] > 0) & (sold["cm_pct"] < 0.15)]
    for r in thin.itertuples():
        out.append({
            "severity": "medium", "stake": r.act_net_lc * (0.30 - r.cm_pct),
            "product": r.product, "market": r.market, "month": str(r.month),
            "issue": "thin margin at volume",
            "detail": (f"{r.cm_pct:.0%} margin on {r.act_units:,.0f} boxes. "
                       f"Contributing only {r.cm_total:,.0f} against "
                       f"{r.act_net_lc:,.0f} of revenue."),
            "action": (f"A {((0.30 - r.cm_pct) / (1 - 0.30)) * 100:.0f}% "
                       f"price rise reaches 30%. Or free the freight space "
                       f"for something that earns more per box."),
        })

    # 5. Poor use of freight space. Only meaningful against the alternatives.
    if len(sold) > 3:
        sold["cm_box"] = sold["cm_unit"]
        med = sold["cm_box"].median()
        weak = sold[(sold["cm_box"] < med * 0.5) & (sold["cm_box"] > 0)]
        for r in weak.nlargest(5, "act_units").itertuples():
            fore = (med - r.cm_box) * r.act_units
            out.append({
                "severity": "low", "stake": fore,
                "product": r.product, "market": r.market, "month": str(r.month),
                "issue": "low margin per box",
                "detail": (f"{r.cm_box:,.2f} a box against a median of "
                           f"{med:,.2f}. On {r.act_units:,.0f} boxes of "
                           f"freight that is {fore:,.0f} of margin foregone "
                           f"against a typical product."),
                "action": ("Worth carrying only if it brings customers who "
                           "buy other things. Check basket composition "
                           "before cutting."),
            })

    if not out:
        return pd.DataFrame(columns=["severity", "stake", "product", "market",
                                     "issue", "detail", "action"])

    df = pd.DataFrame(out)
    order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    df["_o"] = df["severity"].map(order)
    return (df.sort_values(["_o", "stake"], ascending=[True, False])
            .drop(columns="_o").reset_index(drop=True))


def portfolio_price_health(combined: pd.DataFrame,
                           market: str | None = None) -> pd.DataFrame:
    """One row per product: what it earns, and what a price move would need.

    The summary a commercial review actually wants — where margin sits, how
    exposed each product is, and how much volume a five percent cut would
    have to find.
    """
    d = combined[combined["act_units"] > 0].copy()
    if market:
        d = d[d["market"] == market]
    if d.empty:
        return pd.DataFrame()

    d["price"] = d["act_net_lc"] / d["act_units"]
    if "act_cm_dated_lc" in d.columns and d["act_cm_dated_lc"].notna().any():
        d["cost"] = (d["act_net_lc"] - d["act_cm_dated_lc"]) / d["act_units"]
    else:
        d["cost"] = d["plan_cogs_unit_lc"]

    g = d.groupby(["market", "product"], observed=True).agg(
        units=("act_units", "sum"), revenue=("act_net_lc", "sum"),
        plan_price=("plan_price_lc", "mean")).reset_index()
    costs = d.groupby(["market", "product"], observed=True).apply(
        lambda x: np.average(x["cost"], weights=x["act_units"])
        if x["act_units"].sum() else np.nan, include_groups=False)
    g["cost"] = costs.values
    g["price"] = g["revenue"] / g["units"]
    g["cm_box"] = g["price"] - g["cost"]
    g["cm_pct"] = g["cm_box"] / g["price"]
    g["cm_total"] = g["cm_box"] * g["units"]
    g["cm_share"] = g["cm_total"] / g["cm_total"].sum()
    g["realisation"] = (g["price"] / g["plan_price"]).where(g["plan_price"].gt(0))
    # A five percent cut is the standard promotional move, so its cost is the
    # most useful single sensitivity to carry per product.
    after = g["cm_box"] - g["price"] * 0.05
    g["breakeven_at_minus5"] = np.where(
        after > 0, (g["cm_box"] / after - 1) * 100, np.nan)
    return g.sort_values("cm_total", ascending=False).reset_index(drop=True)
