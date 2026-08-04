"""Audit — Inripe sales performance.

Checks the figures the dashboard shows, using logic that does not share code
with the engine wherever a genuinely independent recompute is possible.

Run before every deploy:  python audit_metrics.py
Exit code 0 = clean. Non-zero = do not ship.

Six groups:

  A  the data arrives and is shaped as expected
  B  classification is exhaustive and mutually exclusive
  C  the chain multiplies, on every scope
  D  every gap decomposition reconciles to zero
  E  money adds up — cash buckets, discount, loss
  F  cost is matched correctly and the basis is declared

A failure here means a number on screen is wrong. A warning means it is
right but resting on something worth knowing about.
"""

from __future__ import annotations

import sys
from datetime import date

import numpy as np
import pandas as pd

import metrics_engine as me
import plan_engine as pe
from data_loader import load_plan, load_actuals_any

YEAR = 2026
TOL = 0.01


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
            print(f"  FAIL  [{code}] {msg or name}")

    def warn(self, code: str, msg: str) -> None:
        self.warns.append((code, msg))


def scopes() -> list[tuple[str, me.Scope]]:
    """The scope combinations a user can actually select.

    Includes a partial range, because a half month is where a filter that
    moves one side without the other shows up.
    """
    out = [("all markets, full year", me.Scope(YEAR, None, None))]
    for mk in me.MARKETS:
        out.append((f"{mk}, full year", me.Scope(YEAR, mk, None)))
    for mo in ("July", "August"):
        out.append((f"all markets, {mo}", me.Scope(YEAR, None, mo)))
        for mk in me.MARKETS:
            out.append((f"{mk}, {mo}", me.Scope(YEAR, mk, mo)))
    out.append(("KSA, first half of July",
                me.Scope(YEAR, "KSA", "July",
                         start=date(YEAR, 7, 1), end=date(YEAR, 7, 15))))
    out.append(("KSA, second half of July",
                me.Scope(YEAR, "KSA", "July",
                         start=date(YEAR, 7, 16), end=date(YEAR, 7, 31))))
    return out


def run() -> Report:
    rep = Report()
    raw, fx, pmeta, aliases, cost_log = load_plan()
    plan = pe.attach_fx(pe.derive(raw), fx)
    actuals, ameta, lines = load_actuals_any(YEAR, cost_log, plan)

    print("=== A. SOURCE ===")
    rep.check(lines is not None and len(lines) > 0, "A1",
              f"order lines loaded from {ameta.get('source')}, "
              f"{0 if lines is None else len(lines):,} rows")
    if lines is None or lines.empty:
        return rep
    needed = ["market", "order", "processed_at", "cancelled",
              "financial_status", "fulfillment_status", "product",
              "qty_ordered", "qty_current", "gross_lc", "net_line_lc"]
    missing = [c for c in needed if c not in lines.columns]
    rep.check(not missing, "A2", "every column the engine needs is present",
              f"missing: {missing}")
    rep.check(len(plan) > 0, "A3", f"plan loaded, {len(plan):,} rows")

    base = me.Scope(YEAR, None, None)
    d = me.prepare(lines, base)
    rep.check(len(d) > 0, "A4", f"{len(d):,} lines in {YEAR} after filtering")

    print("\n=== B. CLASSIFICATION ===")
    # Exhaustive and mutually exclusive. A line in two states, or in none,
    # means every count downstream is wrong.
    rep.check(d["state"].isin(["delivered", "open", "lost"]).all(), "B1",
              "every line is delivered, open or lost — no third state")
    rep.check(d["cash"].isin(["collected", "owed", "prepaid", "at risk",
                              "lost"]).all(), "B2",
              "every line has exactly one cash state")

    # Independent recompute of the lost rule, without engine code.
    naive_lost = (lines["cancelled"]
                  | lines["financial_status"].isin(me.LOST_FINANCIAL))
    naive_lost = naive_lost[d.index] if len(d) < len(lines) else naive_lost
    eng_lost = d["state"].eq("lost")
    agree = int((naive_lost.reindex(d.index).fillna(False) == eng_lost).sum())
    rep.check(agree == len(d), "B3",
              f"the lost rule matches an independent recompute on all "
              f"{len(d):,} lines", f"{len(d) - agree} disagree")

    lost_rows = d[d["state"] == "lost"]
    rep.check(len(lost_rows) == 0 or float(lost_rows["revenue"].sum()) == 0.0,
              "B4", "no lost line carries revenue",
              f"{lost_rows['revenue'].sum():,.2f} on lost lines")
    rep.check(len(lost_rows) == 0 or float(lost_rows["units"].sum()) == 0.0,
              "B5", "no lost line carries units")

    print("\n=== C. THE CHAIN ===")
    bad_chain = []
    tested = 0
    for name, s in scopes():
        try:
            c = me.cards(lines, plan, s, cost_log)
        except Exception as e:
            bad_chain.append((name, f"raised {type(e).__name__}: {e}"))
            continue
        if c.get("empty"):
            continue
        tested += 1
        for prob in me.check_chain(c):
            bad_chain.append((name, prob))
    rep.check(not bad_chain, "C1",
              f"orders x basket = units and units x price = revenue on all "
              f"{tested} populated scopes",
              f"{len(bad_chain)} breaks: {bad_chain[:3]}")

    print("\n=== D. GAP DECOMPOSITION ===")
    bad_dec = []
    for name, s in scopes():
        try:
            c = me.cards(lines, plan, s, cost_log)
        except Exception:
            continue
        if c.get("empty"):
            continue
        for metric in ("orders", "units", "revenue", "margin"):
            steps = me.gap_decomposition(c, metric)
            if not steps:
                continue
            total = steps[0]["value"] + sum(x["value"] for x in steps[1:-1])
            end = steps[-1]["value"]
            if abs(total - end) > max(1.0, abs(end) * 0.01):
                bad_dec.append((name, metric, round(total - end, 2)))
    rep.check(not bad_dec, "D1",
              "every gap decomposition reconciles to its actual",
              f"{len(bad_dec)} do not: {bad_dec[:4]}")

    print("\n=== E. RANGE SPLITS ===")
    # A range that is cut in two must sum back to the whole. If it does not,
    # the filter is moving one side and not the other — which is exactly the
    # fault the old as_of control had.
    whole = me.cards(lines, plan, me.Scope(YEAR, "KSA", "July"), cost_log)
    h1 = me.cards(lines, plan, me.Scope(YEAR, "KSA", "July",
                                        start=date(YEAR, 7, 1),
                                        end=date(YEAR, 7, 15)), cost_log)
    h2 = me.cards(lines, plan, me.Scope(YEAR, "KSA", "July",
                                        start=date(YEAR, 7, 16),
                                        end=date(YEAR, 7, 31)), cost_log)
    if not any(x.get("empty") for x in (whole, h1, h2)):
        for label, key in (("units", "units"), ("revenue", "revenue")):
            w = whole[key]["total"]
            parts = h1[key]["total"] + h2[key]["total"]
            rep.check(abs(parts - w) < max(1.0, abs(w) * TOL), "E0",
                      f"the two halves of July sum to the whole on {label}",
                      f"{parts:,.2f} against {w:,.2f}")
        wp = whole["revenue"]["plan_full"]
        pp = h1["revenue"]["plan_full"] + h2["revenue"]["plan_full"]
        rep.check(abs(pp - wp) < max(1.0, abs(wp) * TOL), "E0b",
                  "the pro-rated plan halves sum to the whole month",
                  f"{pp:,.2f} against {wp:,.2f}")

    print("\n=== E. MONEY ===")
    for name, s in [("all markets, full year", base)] + scopes()[:5]:
        c = me.cards(lines, plan, s, cost_log)
        if c.get("empty"):
            continue
        o, u, r = c["orders"], c["units"], c["revenue"]
        # Orders must exclude lost, and the divisors behind AOV and basket
        # must match the numerators. Both errors cancel in the chain check,
        # so they are asserted directly.
        rep.check(o["total"] == o["delivered"] + o["open"], "E6",
                  f"the orders headline excludes lost · {name}",
                  f"{o['total']} against {o['delivered'] + o['open']}")
        rep.check(o["total"] + o["lost"] == o["placed"], "E7",
                  f"orders plus lost equals orders placed · {name}")
        if o["aov"]:
            rep.check(abs(o["aov"] * o["total"] - r["total"])
                      < max(1.0, r["total"] * TOL), "E8",
                      f"AOV times orders equals revenue · {name}")
        if u["per_order"]:
            rep.check(abs(u["per_order"] * o["total"] - u["total"])
                      < max(0.5, u["total"] * TOL), "E9",
                      f"basket times orders equals units · {name}")
        buckets = r["collected"] + r["owed"] + r["prepaid"] + r["at_risk"]
        rep.check(abs(buckets - r["total"]) < max(1.0, r["total"] * TOL),
                  "E1", f"cash buckets sum to revenue · {name}",
                  f"{buckets:,.2f} against {r['total']:,.2f}")
        break

    dd = me.attach_cost(d, cost_log, plan)
    live = dd[dd["state"].ne("lost")]
    rep.check((live["revenue"] <= live["gross"] + TOL).all(), "E2",
              "net revenue never exceeds gross on any line")
    rep.check((live["discount"] >= -TOL).all(), "E3",
              "discount is never negative")
    rep.check(abs(float((live["revenue"] - live["cogs"] - live["cm"]).sum()))
              < 1.0, "E4", "revenue minus cost equals margin, line by line")

    c_all = me.cards(lines, plan, base, cost_log)
    if not c_all.get("empty"):
        m = c_all["margin"]
        rep.check(abs((m["cm_at_plan_cost"] + m["cost_effect"]) - m["cm"])
                  < 1.0, "E5",
                  "margin at plan cost plus cost movement equals actual margin",
                  f"{m['cm_at_plan_cost'] + m['cost_effect']:,.2f} against "
                  f"{m['cm']:,.2f}")

    print("\n=== F. COST ===")
    rep.check(dd["cost_basis"].isin(["dated", "plan", "none"]).all(), "F1",
              "every line declares which cost basis it used")
    none_share = float((dd["cost_basis"] == "none").mean())
    rep.check(none_share < 0.5, "F2",
              f"{1 - none_share:.0%} of lines have a cost",
              f"{none_share:.0%} have none at all")

    if cost_log is not None and len(cost_log):
        import variance_engine as ve
        cl = ve.normalise_cost_log(cost_log)
        rep.check(len(cl) > 0, "F3", f"cost log parsed, {len(cl)} entries")
        rep.check(cl["cogs_unit_lc"].gt(0).all(), "F4",
                  "every cost log entry is positive")
        rep.check(cl.duplicated(["product", "market", "valid_from"]).sum() == 0,
                  "F5", "no two cost entries share a product, market and moment")

        # A line's cost must come from an entry dated on or before its order.
        dated = dd[dd["cost_basis"] == "dated"]
        if len(dated):
            wrong = 0
            for (prod, mkt), grp in cl.groupby(["product", "market"]):
                sub = dated[(dated["product"] == prod)
                            & (dated["market"] == mkt)]
                for _, row in sub.iterrows():
                    valid = grp[grp["valid_from"] <= row["ts"]]
                    if valid.empty:
                        wrong += 1
                    elif abs(valid.iloc[-1]["cogs_unit_lc"]
                             - row["unit_cost"]) > TOL:
                        wrong += 1
            rep.check(wrong == 0, "F6",
                      f"all {len(dated):,} dated lines took the cost in force "
                      f"on their order date", f"{wrong} took the wrong entry")
    else:
        rep.warn("F3", "no cost log — margin is at plan cost everywhere, so "
                       "cost movement is invisible")

    plan_share = float((dd["cost_basis"] == "plan").mean())
    if plan_share > 0.05:
        rep.warn("F7", f"{plan_share:.0%} of lines fall back to plan cost")

    print("\n=== H. FORECAST ===")
    # A forecast whose parts do not multiply is two forecasts pretending to
    # be one. These assert the chain holds on every basis.
    fscope = me.Scope(YEAR, "KSA", date.today().strftime("%B")
                      if date.today().year == YEAR else "August")
    fc = me.forecast(lines, plan, fscope, cost_log)
    if not fc:
        rep.warn("H0", "no period in progress, forecast checks skipped")
    else:
        sf = fc["so_far"]
        bad = []
        for name, b in fc["bases"].items():
            inc_orders = b["orders"] - sf["orders"]
            exp_units = sf["units"] + inc_orders * b["basket"]
            if abs(b["units"] - exp_units) > max(1.0, exp_units * TOL):
                bad.append((name, "units", round(b["units"] - exp_units, 2)))
            exp_rev = sf["revenue"] + (b["units"] - sf["units"]) * b["price"]
            if abs(b["revenue"] - exp_rev) > max(1.0, abs(exp_rev) * TOL):
                bad.append((name, "revenue", round(b["revenue"] - exp_rev, 2)))
            if abs((b["revenue"] - b["cogs"]) - b["cm"]) > 1.0:
                bad.append((name, "margin", "revenue less cost is not margin"))
            if b["orders"] < sf["orders"] - 1:
                bad.append((name, "orders", "projection is below what is banked"))
        rep.check(not bad, "H1",
                  f"the forecast chain holds on all {len(fc['bases'])} bases",
                  f"{bad[:3]}")

        ms = fc["margin_split"]
        total = ms["volume"] + ms["cost"] + ms["price"]
        actual = fc["bases"]["run_rate"]["cm"] - fc["plan"]["cm"]
        rep.check(abs(total - actual) < max(1.0, abs(actual) * TOL), "H2",
                  "the projected margin split reconciles to the gap",
                  f"{total:,.2f} against {actual:,.2f}")
        rep.check(fc["bases"]["at_plan"]["cm_pct_of_plan"] is None
                  or fc["bases"]["at_plan"]["cm_pct_of_plan"] >= 0.5, "H3",
                  "the plan basis lands near plan, as it must by construction")

    print("\n=== I. PORTFOLIO PRICING ===")
    pf = me.portfolio(lines, plan, me.Scope(YEAR, "KSA", "August"), cost_log)
    if not pf:
        rep.warn("I0", "no sales to price against, portfolio checks skipped")
    else:
        # A zero move must change nothing. If it does, the tool is unsafe to
        # act on, because the baseline it compares against is not the truth.
        zero = me.apply_moves(pf, {})
        rep.check(abs(zero["new_cm"] - pf["cm"]) < 1.0, "I1",
                  "a zero move leaves margin exactly unchanged",
                  f"{zero['new_cm']:,.2f} against {pf['cm']:,.2f}")
        rep.check(abs(zero["recovered"]) < 1.0, "I2",
                  "a zero move recovers nothing")

        prods = pf["products"]["product"].tolist()
        if prods:
            # The alone figure must actually close the gap.
            first = pf["products"].iloc[0]
            if pd.notna(first["alone_pct"]):
                test = me.apply_moves(
                    pf, {first["product"]: first["alone_pct"] * 100})
                rep.check(abs(test["gap_after"]) < max(1.0, abs(pf["gap"]) * 0.02),
                          "I3",
                          f"the alone figure for {first['product']} closes the "
                          f"gap exactly",
                          f"{test['gap_after']:,.2f} left")

            up = me.apply_moves(pf, {prods[0]: 10.0})
            down = me.apply_moves(pf, {prods[0]: -10.0})
            rep.check(up["new_cm"] > pf["cm"] > down["new_cm"], "I4",
                      "raising price raises margin and cutting it lowers "
                      "margin, at flat volume")
            if up.get("breakeven_volume") is not None:
                rep.check(up["breakeven_volume"] < 0, "I5",
                          "a price rise produces a negative break-even — "
                          "volume you can afford to lose")

    print("\n=== G. DATA QUALITY (warnings) ===")
    for name, s in [("all markets, full year", base)]:
        ex = me.exceptions(lines, plan, s, cost_log)
        for e in ex:
            rep.warn("G", f"{e['title']} — {e['detail']}")

    return rep


def main() -> int:
    rep = run()
    print("\n" + "=" * 58)
    print(f"CHECKS {len(rep.passes)}   FAILURES {len(rep.fails)}   "
          f"WARNINGS {len(rep.warns)}")
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
