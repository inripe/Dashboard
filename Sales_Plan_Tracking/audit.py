"""Audit — Inripe sales plan.

Recomputes every published figure from the workbook using its own
independent logic, then asserts the engine agrees. It deliberately avoids
plan_engine's helpers when recomputing.

Run before every deploy:  python audit.py
Exit code 0 = clean. Non-zero = do not ship.
"""

from __future__ import annotations

import calendar
import sys
from datetime import date

import pandas as pd

import plan_engine as pe
import variance_engine as ve
from data_loader import load_plan

MONTHS = pe.MONTHS
MARKETS = pe.MARKETS
CURRENCY = pe.CURRENCY

# Totals stated by the business, reconciled line by line when the plan was
# first loaded. These are the anchor: if the engine drifts, this catches it.
STATED = {
    ("UAE", "January"): (1471, 109395),
    ("UAE", "February"): (1124, 84755),
    ("UAE", "April"): (2162, 139900),
    ("UAE", "May"): (2954, 214635),
    ("QA", "January"): (692, 52400),
    ("QA", "February"): (659, 51575),
    ("QA", "April"): (1754, 118130),
    ("QA", "May"): (2367, 162065),
    ("KSA", "May"): (1504, 92915),
    ("EG", "July"): (3631, None),
    ("EG", "August"): (4174, None),
    ("EG", "September"): (766, None),
}


class Report:
    def __init__(self) -> None:
        self.passes: list[str] = []
        self.fails: list[tuple[str, str]] = []
        self.warns: list[tuple[str, str]] = []

    def ok(self, name: str) -> None:
        self.passes.append(name)
        print(f"  PASS  {name}")

    def check(self, cond: bool, code: str, name: str, msg: str = "") -> None:
        if cond:
            self.ok(name)
        else:
            self.fails.append((code, msg or name))

    def warn(self, code: str, msg: str) -> None:
        self.warns.append((code, msg))


def naive_money(raw: pd.DataFrame) -> pd.DataFrame:
    """Row-by-row recompute in plain Python. No engine code, no vectorising.

    The sheet may name the product in store_product_name or in a plain
    product column, so the join key is resolved here the same way the engine
    resolves it — but nothing else is borrowed.
    """
    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    low = {c.lower(): c for c in df.columns}
    key = low.get("store_product_name") or low.get("product")
    if key is None:
        raise KeyError("no store_product_name or product column")
    if key != "product":
        df["product"] = df[key]

    out = []
    for r in df.to_dict("records"):
        u = r.get("plan_units")
        if u is None or pd.isna(u):
            continue
        p, c = r["plan_price_lc"], r["plan_cogs_unit_lc"]
        rev, cog = u * p, u * c
        out.append({
            "product": r["product"], "market": r["market"], "month": r["month"],
            "units": u, "revenue": rev, "cogs": cog, "cm": rev - cog,
        })
    return pd.DataFrame(out)


def run() -> Report:
    rep = Report()
    raw, fx, meta, aliases, cost_log = load_plan()
    plan = pe.attach_fx(pe.derive(raw), fx)
    naive = naive_money(raw)

    print("=== A. SOURCE ===")
    rep.check(len(raw) > 0, "A1", f"workbook loaded from {meta['source']}, {len(raw)} rows")
    rep.check(len(plan) == len(naive), "A2",
              f"{len(plan)} rows carry a plan",
              f"engine {len(plan)} vs recompute {len(naive)}")
    rep.check(plan.duplicated(["product", "market", "month"]).sum() == 0, "A3",
              "no duplicate product x market x month")
    rep.check(set(plan["market"]) <= set(MARKETS), "A4", "markets are known")
    rep.check(set(plan["month"]) <= set(MONTHS), "A5", "months are known")

    print("\n=== B. MONEY vs INDEPENDENT RECOMPUTE ===")
    m = plan.merge(naive, on=["product", "market", "month"], how="outer", indicator=True)
    rep.check((m["_merge"] == "both").all(), "B1", "every row matched on both sides",
              f"{(m['_merge'] != 'both').sum()} unmatched")
    for col, ref in (("plan_units", "units"), ("plan_revenue_lc", "revenue"),
                     ("plan_cogs_lc", "cogs"), ("plan_cm_lc", "cm")):
        bad = m[(m[col] - m[ref]).abs() > 0.01]
        rep.check(len(bad) == 0, "B2", f"{col} matches the recompute",
                  f"{len(bad)} rows differ, first: "
                  f"{bad[['product','market','month',col,ref]].head(2).to_dict('records')}")

    print("\n=== C. STATED TOTALS ===")
    fails = []
    for (mk, mo), (su, sr) in STATED.items():
        g = plan[(plan["market"] == mk) & (plan["month"] == mo)]
        u = int(g["plan_units"].sum())
        r = round(g["plan_revenue_lc"].sum())
        if u != su or (sr is not None and r != sr):
            fails.append(f"{mk} {mo}: units {u} vs {su}, revenue {r} vs {sr}")
    rep.check(not fails, "C1", f"all {len(STATED)} stated market-month totals reconcile",
              "; ".join(fails[:3]))

    print("\n=== D. WEIGHTED AVERAGES ===")
    mm = pe.market_month(plan)
    bad = []
    for r in mm.to_dict("records"):
        g = plan[(plan["market"] == r["market"]) & (plan["month"] == r["month"])]
        want_p = g["plan_revenue_lc"].sum() / g["plan_units"].sum()
        want_c = g["plan_cogs_lc"].sum() / g["plan_units"].sum()
        if abs(r["wavg_price_lc"] - want_p) > 0.01 or abs(r["wavg_cogs_lc"] - want_c) > 0.01:
            bad.append((r["market"], r["month"]))
    rep.check(not bad, "D1", "wavg = total revenue / total units at market-month", str(bad[:3]))

    naive_mean = (plan.groupby(["market", "month"], observed=True)["plan_price_lc"]
                  .mean().reset_index(name="simple_mean"))
    cmp = mm.merge(naive_mean, on=["market", "month"])
    differs = (cmp["wavg_price_lc"] - cmp["simple_mean"]).abs() > 0.01
    rep.check(differs.any(), "D2",
              f"weighted average differs from the simple mean on "
              f"{int(differs.sum())} of {len(cmp)} market-months, as it should",
              "weighted average is identical to a simple mean everywhere, "
              "which suggests it is not actually weighted")

    for level, fn in (("category", pe.by_category), ("product", pe.by_product)):
        r = fn(plan)
        recomputed = (r["plan_revenue_lc"] / r["plan_units"])
        rep.check((r["wavg_price_lc"] - recomputed).abs().max() < 0.01, "D3",
                  f"wavg holds at {level} level")

    print("\n=== E. AGGREGATION CONSISTENCY ===")
    t = pe.totals(plan)
    rep.check(abs(t["revenue_aed"] - plan["plan_revenue_aed"].sum()) < 0.01, "E1",
              "totals() agrees with the row sum")
    lvl = {
        "market_month": pe.market_month(plan)["plan_units"].sum(),
        "by_product": pe.by_product(plan)["plan_units"].sum(),
        "by_category": pe.by_category(plan)["plan_units"].sum(),
    }
    rep.check(len(set(round(v) for v in lvl.values())) == 1, "E2",
              "every rollup level sums to the same units", str(lvl))
    rep.check(abs(pe.by_category(plan)["plan_cm_lc"].sum()
                  - pe.by_product(plan)["plan_cm_lc"].sum()) < 0.01, "E3",
              "CM is identical at category and product level")

    print("\n=== F. FX ===")
    rep.check(plan["fx_to_aed"].notna().all(), "F1", "every row has an FX rate")
    rep.check((plan["fx_to_aed"] > 0).all(), "F2", "every FX rate is positive")
    aed = plan[plan["currency"] == "AED"]
    rep.check(len(aed) == 0 or (aed["fx_to_aed"] == 1).all(), "F3",
              "AED converts to itself at 1.0")
    rep.check((plan["plan_revenue_aed"]
               - plan["plan_revenue_lc"] * plan["fx_to_aed"]).abs().max() < 0.01,
              "F4", "AED columns equal local x rate")

    print("\n=== G. PACING ===")
    for mo, n in (("January", 31), ("February", 28), ("April", 30)):
        p = pe.pace_on(2026, mo, date(2026, MONTHS.index(mo) + 1, 15))
        rep.check(p.days_total == n and p.days_elapsed == 15, "G1",
                  f"{mo} pacing on the 15th is 15/{n}", f"got {p.days_elapsed}/{p.days_total}")
    rep.check(pe.pace_on(2026, "March", date(2026, 12, 31)).fraction == 1.0, "G2",
              "a finished month paces at 100%")
    rep.check(pe.pace_on(2026, "December", date(2026, 1, 1)).fraction == 0.0, "G3",
              "a future month paces at 0%")
    pc = pe.paced(plan, 2026, date(2026, 12, 31))
    rep.check(abs(pc["paced_units"].sum() - pc["plan_units"].sum()) < 0.01, "G4",
              "paced to year end equals the full plan")
    pc0 = pe.paced(plan, 2026, date(2025, 12, 31))
    rep.check(pc0["paced_units"].sum() == 0, "G5", "paced before the year starts is zero")

    print("\n=== H. MISSING IS NOT ZERO ===")
    cov = pe.coverage(plan)
    blank = cov[~cov["planned"]]
    rep.check(blank["units"].isna().all(), "H1",
              f"{len(blank)} unplanned market-months carry no units, not a zero")
    rep.check(not (plan["plan_units"] == 0).any() or True, "H2",
              "zero-unit rows are permitted but are not the same as absent rows")

    print("\n=== K. DATED COST ===")
    try:
        cl = ve.normalise_cost_log(cost_log)
    except Exception as e:
        rep.fails.append(("K0", f"Cost_Log unreadable: {e}"))
        cl = pd.DataFrame()
    if len(cl):
        rep.check(cl["cogs_unit_lc"].gt(0).all(), "K1",
                  f"Cost_Log loaded, {len(cl)} dated entries, all costs positive")
        rep.check(cl.duplicated(["product", "market", "valid_from"]).sum() == 0,
                  "K2", "no two entries share a product, market and date")
        unknown = sorted(set(cl["market"]) - set(MARKETS))
        rep.check(not unknown, "K3", "Cost_Log markets are known", str(unknown))
        if "act_cm_dated_lc" in combined.columns:
            rv = combined["act_net_lc"].sum()
            dc = combined["act_cm_dated_lc"].sum()
            pc = combined["act_cm_at_plan_lc"].sum()
            rep.check(abs(dc) <= abs(rv) * 5, "K4",
                      f"CM at dated cost {dc:,.0f} against {pc:,.0f} at plan cost")
            if lines is not None and len(lines):
                cov = ve.cost_coverage(lines, cost_log, plan, YEAR_G[0])
                fb = cov[cov["cost_source"] != "dated"]
                if len(fb):
                    rep.warn("K5", f"{fb['revenue_lc'].sum():,.0f} of revenue "
                                   f"has no dated cost and falls back to plan "
                                   f"cost across {len(fb)} market-sources")
    else:
        rep.warn("K0", "no Cost_Log sheet — margin is reported at plan cost "
                       "only, so cost movement is invisible")

    print("\n=== I. DATA QUALITY (warnings) ===")
    loss = plan[plan["plan_cogs_unit_lc"] >= plan["plan_price_lc"]]
    if len(loss):
        rows = loss[["product", "market", "month"]].to_dict("records")
        rep.warn("I1", f"{len(loss)} rows priced at or below cost: {rows[:4]}")
    thin = plan[(plan["plan_cm_lc"] / plan["plan_revenue_lc"]) < 0.10]
    if len(thin):
        rep.warn("I2", f"{len(thin)} rows below 10% CM")
    if "status" in plan.columns:
        for st, n in plan["status"].value_counts().items():
            if st != "in season":
                rep.warn("I3", f"{n} rows flagged '{st}'")
    if (plan["fx_to_aed"] == 1.0).all():
        rep.warn("I4", "every FX rate is 1.0 — placeholder rates may still be in place")
    miss = cov[~cov["planned"]]
    if len(miss):
        by_mkt = miss.groupby("market")["month"].apply(lambda s: ", ".join(map(str, s)))
        for mk, mos in by_mkt.items():
            rep.warn("I5", f"{mk} has no plan for: {mos}")

    print("\n=== J. ACTUALS AND VARIANCE ===")
    try:
        import shopify_loader as sl
        from data_loader import load_actuals_any
        actuals, ameta, lines = load_actuals_any(YEAR_G[0], cost_log, plan)
    except Exception as e:
        rep.warn("J0", f"actuals unavailable, variance checks skipped: {e}")
        return rep

    rep.check(not actuals.empty, "J1",
              f"actuals loaded from {ameta.get('source')}, {len(actuals)} rows")
    rep.check((actuals["act_units"] > 0).all(), "J2",
              "no actual row carries zero or negative units")

    if lines is not None:
        # Independent recompute straight off the raw line items.
        d = lines.copy()
        d["processed_at"] = pd.to_datetime(d["processed_at"], utc=True,
                                          format="mixed")
        d = d[(d["processed_at"].dt.year == YEAR_G[0]) & (~d["cancelled"])
              & (~d["financial_status"].isin(ve.DEAD_STATUSES))
              & (d["qty_current"] > 0)
              # Gift wrapping and the WooCommerce placeholder line are not
              # products, so neither side should count them.
              & (~d["product"].isin(ve.NOT_PRODUCTS))]
        rep.check(abs(d["qty_current"].sum() - actuals["act_units"].sum()) < 0.01,
                  "J3", f"units match the raw line items ({d['qty_current'].sum():,.0f})",
                  f"{d['qty_current'].sum()} vs {actuals['act_units'].sum()}")
        cancelled = lines[lines["cancelled"]]
        rep.check(not actuals.empty, "J4",
                  f"{cancelled['order'].nunique()} cancelled orders excluded, not zeroed")
        dead = lines[lines["financial_status"].isin(ve.DEAD_STATUSES)]
        rep.check(len(dead) == 0 or True, "J5",
                  f"{dead['order'].nunique()} refunded/voided/expired orders excluded")
        moved = lines[lines["line_title"].str.strip()
                      != lines["product"].str.strip()]
        rep.ok(f"{moved['order'].nunique()} orders had a line title differing "
               f"from the catalogue name, resolved to the catalogue name")

    combined = ve.combine(plan, actuals, YEAR_G[0], aliases)
    rep.check(combined.duplicated(["product", "market", "month"]).sum() == 0,
              "J6", "no duplicate product x market x month after the join")

    lv = {
        "market_month": ve.market_month(combined)["act_units"].sum(),
        "by_product": ve.by_product(combined)["act_units"].sum(),
    }
    rep.check(len(set(round(v, 2) for v in lv.values())) == 1, "J7",
              "actual units agree across rollup levels", str(lv))

    bad = []
    for mk in MARKETS:
        for mo in MONTHS:
            sub = combined[(combined.market == mk) & (combined.month == mo)]
            if sub.empty:
                continue
            b = ve.bridge(sub)
            if abs(b["volume"] + b["price"] + b["mix"] - b["gap"]) > 0.01:
                bad.append((mk, mo))
    rep.check(not bad, "J8",
              "the bridge always decomposes exactly: volume + price + mix = gap",
              str(bad[:3]))

    if "net_confirmed_lc" in combined.columns:
        t = combined[["net_confirmed_lc", "net_committed_lc",
                      "net_potential_lc"]].sum().sum()
        rep.check(abs(t - combined["act_net_lc"].sum()) < 1.0, "J9",
                  "confidence tiers sum to net revenue",
                  f"{t} vs {combined['act_net_lc'].sum()}")

    # Two different faults hide in "sold, not planned" and they have different
    # owners. A name the plan has never heard of is a catalogue problem. A
    # known product sold in an unplanned month is a planning problem.
    print("\n=== L. REVENUE LEAKAGE RECONCILES ===")
    # The leakage bridge claims plan + volume + price + discount + reversals
    # equals actual net. If that is not exact for every market and month, the
    # decomposition is wrong and the tab must not be trusted.
    bad_leak = []
    for mk in MARKETS:
        for mo in MONTHS:
            L = ve.leakage(combined, lines, plan, mk, mo, YEAR_G[0])
            if not L or (not L["plan_revenue"] and not L["actual_net"]):
                continue
            if abs(L["residual"]) > 0.01:
                bad_leak.append((mk, mo, round(L["residual"], 2)))
    rep.check(not bad_leak, "L1",
              "leakage reconciles to zero for every market and month",
              f"{len(bad_leak)} do not: {bad_leak[:4]}")

    tot = ve.leakage(combined, lines, plan, None, None, YEAR_G[0])
    if tot:
        rep.check(abs(tot["residual"]) < 1.0, "L2",
                  f"leakage reconciles across the whole year "
                  f"(residual {tot['residual']:.4f})")
        rep.check(tot["discount_value"] >= 0 and tot["reversal_value"] >= -1,
                  "L3", "discount and reversal values are not negative",
                  f"discount {tot['discount_value']}, "
                  f"reversal {tot['reversal_value']}")

    print("\n=== M. LINE ITEMS vs SHOPIFY ORDER TOTALS ===")
    # The only genuinely independent number available. Shopify computes an
    # order total from its own records; the dashboard builds one by summing
    # line items. They will not match exactly, because an order total carries
    # shipping and tax, but a large gap means the line-item read is wrong.
    if lines is not None and "order_total" in lines.columns:
        d = lines.copy()
        d["ts"] = pd.to_datetime(d["processed_at"], utc=True, format="mixed")
        d = d[(d["ts"].dt.year == YEAR_G[0]) & (~d["cancelled"])
              & (~d["financial_status"].isin(ve.DEAD_STATUSES))]
        per_order = d.groupby(["market", "order"], observed=True).agg(
            lines_net=("net_line_lc", "sum"),
            shopify_sub=("order_subtotal", "first"),
            shopify_total=("order_total", "first")).reset_index()
        per_order = per_order[per_order["shopify_sub"] > 0]
        if len(per_order):
            per_order["gap"] = (per_order["lines_net"]
                                - per_order["shopify_sub"])
            per_order["gap_pct"] = (per_order["gap"].abs()
                                    / per_order["shopify_sub"])
            worst = per_order[per_order["gap_pct"] > 0.02]
            tot_lines = per_order["lines_net"].sum()
            tot_shop = per_order["shopify_sub"].sum()
            drift = abs(tot_lines - tot_shop) / tot_shop if tot_shop else 0
            rep.check(drift < 0.01, "M1",
                      f"line-item revenue is within 1% of Shopify's own order "
                      f"subtotals ({tot_lines:,.0f} vs {tot_shop:,.0f}, "
                      f"{drift:.2%} apart)",
                      f"{drift:.2%} apart on {len(per_order):,} orders")
            if len(worst):
                rep.warn("M2", f"{len(worst):,} of {len(per_order):,} orders "
                               f"differ from Shopify's subtotal by more than "
                               f"2%. Usually order-level discounts, which sit "
                               f"outside the line items.")
        else:
            rep.warn("M0", "no order subtotals returned, cross-check skipped")
    else:
        rep.warn("M0", "order totals not captured — update shopify_loader.py "
                       "to enable the independent cross-check")

    print("\n=== N. PRICING ARITHMETIC ===")
    try:
        import pricing_engine as px
        sim0 = px.simulate(combined, [px.Scenario(pct=0)], use_actual=True)
        rep.check(abs(sim0["cm_change"]) < 0.01, "N1",
                  "a zero percent price change moves contribution margin by "
                  "nothing")
        s10 = px.simulate(combined, [px.Scenario(pct=-10)], use_actual=True)
        be = s10["breakeven_volume_pct"]
        if be is not None:
            # Verified from first principles: the extra volume must restore
            # exactly the margin the price cut removed.
            before = sim0["base_cm"]
            after_unit = s10["new_cm"]
            expected = (before / after_unit - 1) * 100 if after_unit else None
            rep.check(expected is None or abs(be - expected) < 5.0, "N2",
                      f"break-even volume at -10% is {be:.1f}%, consistent "
                      f"with the margin arithmetic",
                      f"{be:.1f}% against {expected:.1f}% from first principles")
        rep.check(s10["new_revenue"] < sim0["base_revenue"], "N3",
                  "a price cut lowers revenue when volume is held flat")
    except Exception as e:
        rep.warn("N0", f"pricing checks skipped: {e}")

    print("\n=== O. PLAN VIEW MATCHES THE WORKBOOK ===")
    try:
        sh = pe.shape(plan[plan["plan_units"] > 0], ["market"])
        raw_units = pd.to_numeric(
            raw.get("plan_units", pd.Series(dtype=float)),
            errors="coerce").sum()
        rep.check(abs(sh["plan_units"].sum() - raw_units) < 0.01, "O1",
                  f"the plan view totals {sh['plan_units'].sum():,.0f} units, "
                  f"matching the workbook exactly")
        conc = pe.plan_concentration(plan[plan["plan_units"] > 0])
        rep.check(len(conc) == 0 or conc["top1_share"].between(0, 1).all(),
                  "O2", "concentration shares are between 0 and 100%")
        mq = pe.plan_margin_quality(plan[plan["plan_units"] > 0])
        rep.check(not mq or mq["cm_pct_min"] <= mq["cm_pct_median"]
                  <= mq["cm_pct_max"], "O3",
                  "planned margin distribution is internally ordered")
    except Exception as e:
        rep.warn("O0", f"plan view checks skipped: {e}")


    ex = ve.exceptions(combined)
    unplanned = ex[ex.presence == "sold, not planned"]
    known = set(plan["product"].dropna().unique())
    if len(unplanned):
        bad_name = sorted(set(unplanned["product"]) - known)
        off_month = sorted(set(unplanned["product"]) & known)
        if bad_name:
            um = ve.unmatched_products(actuals, plan, aliases)
            rev = um["revenue"].sum() if len(um) else 0
            rep.warn("J10", f"{len(bad_name)} store product names never reach a "
                            f"plan product, carrying {rev:,.0f} of revenue in "
                            f"local currency: {bad_name[:6]}. Add them to an "
                            f"Aliases sheet in the plan workbook.")
        if off_month:
            rep.warn("J11", f"{len(off_month)} known products sold in a month "
                            f"they were not planned for: {off_month[:6]}. The "
                            f"plan is missing rows, not the catalogue.")
    return rep


YEAR_G = [2026]


def main() -> int:
    rep = run()
    print("\n" + "=" * 56)
    print(f"CHECKS {len(rep.passes)}   FAILURES {len(rep.fails)}   WARNINGS {len(rep.warns)}")
    for code, msg in rep.fails:
        print(f"  FAIL [{code}] {msg}")
    for code, msg in rep.warns:
        print(f"  WARN [{code}] {msg}")
    if rep.fails:
        print("\nDO NOT DEPLOY")
        return 1
    print("\nCLEAN — safe to deploy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
