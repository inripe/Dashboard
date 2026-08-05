"""Data quality — Inripe sales performance.

Every check that can tell you a number on the dashboard is not to be
trusted, in one place. Four sections, because the failures have different
owners:

  Plan file             the Excel is wrong or incomplete
  Shopify actuals       the order records contradict themselves
  Cost log              margin is resting on a cost that is not there
  Dashboard consistency the page contradicts itself

Severity means what it costs, not how ugly it looks:

  fail      a headline figure is wrong or unusable
  warn      worth knowing, the figure still stands
  pass      checked and clean, stated so the silence is not ambiguous

Every check is wrapped. A check that raises reports itself as an error
rather than taking the tab down with it — a broken smoke alarm should not
burn the house.

Pure pandas. No Streamlit, no I/O, no network.
"""

from __future__ import annotations

import traceback
from datetime import date

import numpy as np
import pandas as pd

import metrics_engine as me

PLAN_FILE = "Plan file"
ACTUALS = "Shopify actuals"
COST_LOG = "Cost log"
CONSISTENCY = "Dashboard consistency"

SECTIONS = [PLAN_FILE, ACTUALS, COST_LOG, CONSISTENCY]
SEVERITY_ORDER = {"fail": 0, "warn": 1, "pass": 2}

# Thresholds, gathered here so they can be argued about in one place rather
# than hunted for in the middle of a function.
UNPAID_DAYS = 14
DATED_COST_MIN = 0.95
UNPLANNED_REVENUE_WARN = 0.02      # share of revenue with no plan row
CHAIN_TOLERANCE = 0.01
CONSOLIDATION_TOLERANCE = 0.005    # markets must sum to all-markets


def _check(section: str, severity: str, title: str, detail: str = "",
           value: float | None = None, rows: pd.DataFrame | None = None,
           fix: str = "") -> dict:
    return {"section": section, "severity": severity, "title": title,
            "detail": detail, "value": value, "rows": rows, "fix": fix}


def _safe(fn, section: str, label: str) -> list[dict]:
    """Run one check group. A raising check reports itself, nothing else."""
    try:
        out = fn()
        return out if out else []
    except Exception as exc:                                  # noqa: BLE001
        return [_check(section, "fail", f"Check failed to run: {label}",
                       f"{type(exc).__name__}: {exc}",
                       fix=traceback.format_exc(limit=3))]


# ------------------------------------------------------------- plan file


def check_plan(plan: pd.DataFrame, lines: pd.DataFrame,
               scope: me.Scope) -> list[dict]:
    out = []
    p = plan.copy()

    # One product id must mean one product. A join on the id silently merges
    # two different fruits otherwise, and every per-product figure is then a
    # blend of both with nothing to show it happened.
    if "product_id" in p.columns and "product" in p.columns:
        pairs = p[["product_id", "product"]].drop_duplicates()
        dupes = pairs.groupby("product_id").filter(lambda g: len(g) > 1)
        if len(dupes):
            g = (dupes.groupby("product_id")["product"]
                 .apply(lambda s: " / ".join(sorted(s))))
            out.append(_check(
                PLAN_FILE, "fail",
                f"{len(g)} product ids used for more than one product",
                " · ".join(f"{k} = {v}" for k, v in g.head(4).items()),
                rows=dupes.sort_values("product_id"),
                fix="Give each distinct product its own id, or drop the id "
                    "column and join on name."))
        else:
            out.append(_check(PLAN_FILE, "pass",
                              "Every product id maps to one product",
                              f"{pairs['product_id'].nunique()} ids checked"))

    # The same product, market and month appearing twice doubles that row's
    # plan without anyone seeing it.
    keys = [c for c in ("product", "market", "month") if c in p.columns]
    if len(keys) == 3:
        dupes = p[p.duplicated(keys, keep=False)]
        if len(dupes):
            out.append(_check(
                PLAN_FILE, "fail",
                f"{len(dupes)} duplicate product / market / month rows",
                "Plan for these is counted more than once.",
                rows=dupes.sort_values(keys),
                fix="Remove the repeated rows in the Excel."))
        else:
            out.append(_check(PLAN_FILE, "pass",
                              "No duplicate product / market / month rows",
                              f"{len(p)} rows checked"))

    # Units with no money against them, or money with no units. Either way
    # the row cannot be used and will quietly skew a per-unit figure.
    if {"plan_units", "plan_revenue_lc"} <= set(p.columns):
        u = pd.to_numeric(p["plan_units"], errors="coerce").fillna(0)
        r = pd.to_numeric(p["plan_revenue_lc"], errors="coerce").fillna(0)
        broken = p[((u > 0) & (r <= 0)) | ((u <= 0) & (r > 0))]
        if len(broken):
            out.append(_check(
                PLAN_FILE, "fail",
                f"{len(broken)} rows have units without revenue, or the reverse",
                "Plan price and attainment cannot be computed for these.",
                rows=broken,
                fix="Fill the missing side, or clear the row entirely."))

    # The stated margin percentage must be the one the numbers produce. If
    # it is not, someone has typed over a formula.
    need = {"plan_revenue_lc", "plan_cogs_lc", "plan_cm_pct"}
    if need <= set(p.columns):
        r = pd.to_numeric(p["plan_revenue_lc"], errors="coerce")
        c = pd.to_numeric(p["plan_cogs_lc"], errors="coerce")
        stated = pd.to_numeric(
            p["plan_cm_pct"].astype(str).str.rstrip("%"), errors="coerce")
        stated = np.where(stated.abs() > 1.5, stated / 100, stated)
        implied = ((r - c) / r).where(r.ne(0))
        gap = (pd.Series(stated, index=p.index) - implied).abs()
        bad = p[gap > 0.005]
        checked = int(gap.notna().sum())
        if len(bad):
            out.append(_check(
                PLAN_FILE, "fail",
                f"{len(bad)} rows where plan_cm_pct does not match the numbers",
                "The percentage has been overwritten and no longer follows "
                "from revenue less cogs.",
                rows=bad,
                fix="Restore the formula in the plan_cm_pct column."))
        elif checked:
            out.append(_check(
                PLAN_FILE, "pass",
                "plan_cm_pct reconciles to revenue less cogs",
                f"{checked} rows checked, no mismatches"))

    # A plan that loses money is a decision, not necessarily a mistake — but
    # it should be a decision someone made on purpose.
    if {"plan_units", "plan_cm_lc"} <= set(p.columns):
        u = pd.to_numeric(p["plan_units"], errors="coerce").fillna(0)
        cm = pd.to_numeric(p["plan_cm_lc"], errors="coerce").fillna(0)
        neg = p[(u > 0) & (cm < 0)]
        if len(neg):
            label = neg.apply(
                lambda x: f"{x.get('product', '?')} · {x.get('market', '?')} "
                          f"· {x.get('month', '?')}", axis=1)
            out.append(_check(
                PLAN_FILE, "warn",
                f"{len(neg)} planned rows carry a negative margin",
                " · ".join(label.head(3)),
                value=float(cm[neg.index].sum()), rows=neg,
                fix="Confirm this is intended, or correct the planned cost."))

    # Sales in a month with no plan. Real, if the month is genuinely
    # unplanned — but attainment for it is meaningless and the forecast
    # accuracy replay has to skip it.
    d = me.prepare(lines, me.Scope(scope.year, scope.market))
    if not d.empty and "month" in p.columns:
        live = d[d["state"].ne("lost")]
        sold_months = set(live["month"].unique())
        u = pd.to_numeric(p["plan_units"], errors="coerce").fillna(0)
        planned_months = set(p.loc[u > 0, "month"].unique())
        gap_months = [m for m in me.MONTHS
                      if m in sold_months and m not in planned_months]
        if gap_months:
            rev = float(live[live["month"].isin(gap_months)]["revenue"].sum())
            out.append(_check(
                PLAN_FILE, "warn",
                f"Sales in {len(gap_months)} month(s) with no plan rows",
                ", ".join(gap_months),
                value=rev,
                fix="Expected if the month is genuinely unplanned. "
                    "Attainment and forecast accuracy are skipped for it."))
        else:
            out.append(_check(PLAN_FILE, "pass",
                              "Every month with sales has plan rows",
                              f"{len(sold_months)} months checked"))

    return out


# --------------------------------------------------------------- actuals


def check_actuals(lines: pd.DataFrame, plan: pd.DataFrame, scope: me.Scope,
                  cost_log: pd.DataFrame | None = None) -> list[dict]:
    out = []
    d = me.attach_cost(me.prepare(lines, scope), cost_log, plan)
    if d.empty:
        return [_check(ACTUALS, "warn", "No order lines in the selected range",
                       "Nothing to check.")]

    ref = pd.Timestamp(min(date.today(), scope.end))

    # Delivered, unpaid, and old. Revenue is on the books and the cash is
    # not. The single most expensive discrepancy in the system.
    owed = d[d["cash"] == "owed"]
    if len(owed):
        ff = (pd.to_datetime(owed["fulfilled_at"], utc=True, errors="coerce",
                             format="mixed").dt.tz_localize(None)
              if "fulfilled_at" in owed.columns
              else pd.Series(pd.NaT, index=owed.index))
        since = ff.fillna(owed["ts"])
        age = (ref.normalize() - since.dt.normalize()).dt.days.clip(lower=0)
        o = owed.assign(age=age).groupby("order", observed=True).agg(
            outstanding=("revenue", "sum"), age=("age", "max"))
        old = o[o["age"] > UNPAID_DAYS]
        if len(old):
            out.append(_check(
                ACTUALS, "fail",
                f"{len(old)} orders delivered and unpaid over {UNPAID_DAYS} days",
                f"Oldest is {int(old['age'].max())} days.",
                value=float(old["outstanding"].sum()),
                rows=old.reset_index().sort_values("age", ascending=False),
                fix="Reconcile against the courier cash remittance, then "
                    "mark paid in Shopify admin."))
        else:
            out.append(_check(ACTUALS, "pass",
                              "No delivered orders unpaid beyond "
                              f"{UNPAID_DAYS} days",
                              f"{len(o)} outstanding orders, all recent"))

    # Cancelled after the goods left. The order says no sale, the warehouse
    # says the box is gone. Both cannot be true.
    if "cancelled" in d.columns:
        gone = d[d["cancelled"] & d["fulfillment_status"].isin(me.DELIVERED)]
        if len(gone):
            g = gone.groupby("order", observed=True).agg(
                value=("gross_lc", "sum"))
            out.append(_check(
                ACTUALS, "fail",
                f"{len(g)} orders cancelled after being fulfilled",
                "Goods dispatched, order voided, revenue unrecoverable.",
                value=float(g["value"].sum()),
                rows=g.reset_index(),
                fix="Decide per order: record the delivery and chase payment, "
                    "or process a return."))
        else:
            out.append(_check(ACTUALS, "pass",
                              "No orders cancelled after fulfilment"))

    # Delivered with no delivery date. Every ageing figure then falls back to
    # the order date and quietly understates how long the money has been out.
    if "fulfilled_at" in d.columns:
        deliv = d[d["state"] == "delivered"]
        if len(deliv):
            missing = deliv[pd.to_datetime(
                deliv["fulfilled_at"], utc=True, errors="coerce",
                format="mixed").isna()]
            n = int(missing["order"].nunique())
            if n:
                out.append(_check(
                    ACTUALS, "warn",
                    f"{n} delivered orders have no delivery date",
                    "Ageing for these falls back to the order date.",
                    rows=missing[["order", "product", "market"]].drop_duplicates(),
                    fix="Log the delivery event in Shopify when the driver "
                        "reports back."))

    # Tags that differ only by case or spacing are separate tags to Shopify,
    # so any count built on them is wrong by however many variants exist.
    if "tags" in d.columns:
        tags = (d["tags"].dropna().astype(str)
                .str.split(",").explode().str.strip())
        tags = tags[tags.ne("")]
        if len(tags):
            norm = tags.str.lower().str.replace(r"[\s_-]+", " ", regex=True)
            fam = pd.DataFrame({"tag": tags, "key": norm}).drop_duplicates()
            multi = fam.groupby("key").filter(lambda g: len(g) > 1)
            if len(multi):
                g = multi.groupby("key")["tag"].apply(
                    lambda s: " / ".join(sorted(set(s))))
                out.append(_check(
                    ACTUALS, "warn",
                    f"{len(g)} tags exist in more than one spelling",
                    " · ".join(g.head(3)),
                    rows=multi.sort_values("key"),
                    fix="Pick one spelling per tag. Shopify counts each "
                        "variant separately."))
            else:
                out.append(_check(ACTUALS, "pass",
                                  "Tag spellings are consistent",
                                  f"{fam['key'].nunique()} distinct tags"))

    # Revenue that cannot be attributed to a plan row. It still counts, but
    # no attainment figure can include it.
    live = d[d["state"].ne("lost")]
    p = me.plan_scope(plan, scope)
    planned = set(p["product"]) if len(p) else set()
    unplanned = live[~live["product"].isin(planned)]
    total_rev = float(live["revenue"].sum())
    if len(unplanned) and total_rev:
        val = float(unplanned["revenue"].sum())
        share = val / total_rev
        out.append(_check(
            ACTUALS, "warn" if share > UNPLANNED_REVENUE_WARN else "pass",
            f"{unplanned['product'].nunique()} products sold with no plan row",
            f"{share:.1%} of revenue in range",
            value=val,
            rows=(unplanned.groupby("product", observed=True)["revenue"]
                  .sum().sort_values(ascending=False).reset_index()),
            fix="Add plan rows, or accept that these sit outside attainment."))

    # A line cannot ship more than was ordered.
    if {"qty_current", "qty_ordered"} <= set(d.columns):
        over = d[d["qty_current"] > d["qty_ordered"]]
        if len(over):
            out.append(_check(
                ACTUALS, "fail",
                f"{len(over)} lines ship more units than were ordered",
                "Revenue on these is capped, so the figures understate.",
                rows=over[["order", "product", "qty_ordered", "qty_current"]],
                fix="Correct the order lines in Shopify."))

    return out


# -------------------------------------------------------------- cost log


def check_cost_log(lines: pd.DataFrame, plan: pd.DataFrame, scope: me.Scope,
                   cost_log: pd.DataFrame | None = None) -> list[dict]:
    out = []
    d = me.attach_cost(me.prepare(lines, scope), cost_log, plan)
    if d.empty:
        return []

    # How much of the margin is standing on a real, dated cost rather than a
    # plan assumption. Below the threshold, cost movement is invisible.
    dated = float((d["cost_basis"] == "dated").mean())
    out.append(_check(
        COST_LOG, "pass" if dated >= DATED_COST_MIN else "warn",
        "Dated cost coverage",
        f"{dated:.0%} of lines priced from the cost log, "
        f"threshold is {DATED_COST_MIN:.0%}",
        fix="" if dated >= DATED_COST_MIN else
            "Add cost log entries for the products falling back to plan."))

    none_basis = d[d["cost_basis"] == "none"]
    if len(none_basis):
        out.append(_check(
            COST_LOG, "fail",
            f"{none_basis['product'].nunique()} products have no cost at all",
            "Cost is treated as zero, so margin on these is overstated.",
            value=float(none_basis["revenue"].sum()),
            rows=(none_basis.groupby(["product", "market"], observed=True)
                  ["revenue"].sum().reset_index()),
            fix="Add these products to the cost log or the plan."))

    if cost_log is None or not len(cost_log):
        return out

    import variance_engine as ve
    cl = ve.normalise_cost_log(cost_log)
    if not len(cl):
        return out

    # A cost dated after the orders it is meant to price never reaches them,
    # because the match is backward-looking. The entry exists and does
    # nothing, which is worse than it being absent.
    live = d[d["state"].ne("lost")]
    first_sale = live.groupby(["product", "market"], observed=True)["ts"].min()
    first_cost = cl.groupby(["product", "market"])["valid_from"].min()
    joined = pd.concat([first_sale.rename("first_sale"),
                        first_cost.rename("first_cost")], axis=1).dropna()
    late = joined[joined["first_cost"] > joined["first_sale"]]
    if len(late):
        out.append(_check(
            COST_LOG, "fail",
            f"{len(late)} products priced by a cost dated after their first sale",
            "Those orders fall back to plan cost.",
            rows=late.reset_index(),
            fix="Backdate the first cost entry to on or before the first "
                "sale date."))
    else:
        out.append(_check(COST_LOG, "pass",
                          "Every cost entry predates the orders it prices",
                          f"{len(joined)} product and market pairs checked"))

    dupes = cl[cl.duplicated(["product", "market", "valid_from"], keep=False)]
    if len(dupes):
        out.append(_check(
            COST_LOG, "warn",
            f"{len(dupes)} cost entries share a product, market and date",
            "Which one applies is arbitrary.",
            rows=dupes.sort_values(["product", "market", "valid_from"]),
            fix="Keep one entry per product, market and date."))

    return out


# -------------------------------------------------- dashboard consistency


def check_consistency(lines: pd.DataFrame, plan: pd.DataFrame, scope: me.Scope,
                      cost_log: pd.DataFrame | None = None) -> list[dict]:
    out = []
    c = me.cards(lines, plan, scope, cost_log)
    if c.get("empty"):
        return [_check(CONSISTENCY, "warn", "No data in range",
                       "Consistency checks need figures to compare.")]

    # The chain the cards rest on. Already asserted in the engine; surfaced
    # here so a failure is seen rather than computed and discarded.
    problems = me.check_chain(c, CHAIN_TOLERANCE)
    if problems:
        out.append(_check(
            CONSISTENCY, "fail",
            f"{len(problems)} card figures contradict each other",
            " · ".join(problems[:2]),
            rows=pd.DataFrame({"problem": problems}),
            fix="The cards cannot all be right. Do not act on them until "
                "this clears."))
    else:
        out.append(_check(
            CONSISTENCY, "pass",
            "Card figures multiply out",
            "orders x basket = units, units x price = revenue, "
            "cash buckets sum to revenue"))

    # Each waterfall must land on the actual it claims to explain. A
    # decomposition with a silent residual explains nothing.
    bad = []
    for metric in ("orders", "units", "revenue", "margin"):
        try:
            steps = me.gap_decomposition(c, metric)
        except me.MetricError:
            continue
        if not steps:
            continue
        start = steps[0]["value"]
        end = steps[-1]["value"]
        moves = sum(s["value"] for s in steps[1:-1])
        if abs(start + moves - end) > max(1.0, abs(end) * CHAIN_TOLERANCE):
            bad.append({"metric": metric, "start": start, "steps": moves,
                        "should_reach": end,
                        "reaches": start + moves})
    if bad:
        out.append(_check(
            CONSISTENCY, "fail",
            f"{len(bad)} gap decompositions do not reach the actual",
            ", ".join(b["metric"] for b in bad),
            rows=pd.DataFrame(bad),
            fix="A step is missing or double counted in the waterfall."))
    else:
        out.append(_check(CONSISTENCY, "pass",
                          "Every gap decomposition reaches its actual",
                          "orders, units, revenue and margin"))

    # The same number on two screens. Cards, the product table and the
    # progress line all derive revenue separately; they must agree.
    pp = me.product_performance(lines, plan, scope, cost_log)
    if len(pp):
        table_rev = float(pp["revenue"].sum())
        card_rev = c["revenue"]["total"]
        if abs(table_rev - card_rev) > max(1.0, card_rev * CHAIN_TOLERANCE):
            out.append(_check(
                CONSISTENCY, "fail",
                "Revenue card and product table disagree",
                f"card {card_rev:,.0f} · table {table_rev:,.0f}",
                value=table_rev - card_rev,
                fix="Both read the same lines. A filter has diverged."))
        else:
            out.append(_check(CONSISTENCY, "pass",
                              "Revenue agrees across cards and product table",
                              f"{card_rev:,.0f}"))

    prog = me.progress(lines, plan, scope, "revenue", cost_log)
    if prog and prog.get("actual"):
        line_end = float(prog["actual"][-1])
        card_rev = c["revenue"]["total"]
        if abs(line_end - card_rev) > max(1.0, card_rev * CHAIN_TOLERANCE):
            out.append(_check(
                CONSISTENCY, "fail",
                "Progress line does not end at the revenue card",
                f"card {card_rev:,.0f} · line {line_end:,.0f}",
                value=line_end - card_rev,
                fix="The cumulative series is filtered differently."))

    # Consolidated must be the sum of its parts. The classic failure: the
    # all-markets view and the per-market views drift, and nobody notices
    # until someone adds the markets up in a meeting.
    if scope.consolidated:
        parts, rows = 0.0, []
        for mkt in me.MARKETS:
            s = me.Scope(scope.year, mkt, scope.month,
                         categories=scope.categories, products=scope.products,
                         start=scope.start, end=scope.end)
            cm = me.cards(lines, plan, s, cost_log)
            v = 0.0 if cm.get("empty") else cm["revenue"]["total"]
            parts += v
            rows.append({"market": mkt, "revenue": v})
        total = c["revenue"]["total"]
        rows.append({"market": "sum of markets", "revenue": parts})
        rows.append({"market": "all markets card", "revenue": total})
        if abs(parts - total) > max(1.0, total * CONSOLIDATION_TOLERANCE):
            out.append(_check(
                CONSISTENCY, "fail",
                "Markets do not sum to the all-markets figure",
                f"sum {parts:,.0f} · card {total:,.0f} · "
                f"difference {parts - total:,.0f}",
                value=parts - total, rows=pd.DataFrame(rows),
                fix="Usually a market label in the data that is not in "
                    "MARKETS, so it is counted once and never again."))
        else:
            out.append(_check(
                CONSISTENCY, "pass",
                "Markets sum to the all-markets figure",
                f"{total:,.0f} across {len(me.MARKETS)} markets"))

    # Pace must describe the range actually on screen.
    frac, elapsed, total_days = me.pace_fraction(scope)
    if total_days != scope.days:
        out.append(_check(
            CONSISTENCY, "fail", "Pace is measuring a different range",
            f"pace covers {total_days} days, the range is {scope.days}",
            fix="The scope and the pace calculation have diverged."))
    else:
        out.append(_check(
            CONSISTENCY, "pass", "Pace matches the selected range",
            f"day {elapsed} of {total_days} · {frac:.0%} elapsed"))

    # The three forecast bases should differ. Identical bases mean the
    # spread is not telling you anything about uncertainty.
    fc = me.forecast(lines, plan, scope, cost_log)
    if fc and fc.get("bases"):
        revs = [b["revenue"] for b in fc["bases"].values()]
        spread = (max(revs) - min(revs)) / max(revs) if max(revs) else 0.0
        if spread < 0.001:
            out.append(_check(
                CONSISTENCY, "warn",
                "All three forecast bases give the same answer",
                "The spread is meant to show uncertainty and currently "
                "shows none.",
                fix="Usually too few days elapsed for the bases to diverge."))
        else:
            out.append(_check(
                CONSISTENCY, "pass", "Forecast bases give a usable spread",
                f"{spread:.1%} between the highest and lowest"))

    return out


# ----------------------------------------------------------------- run it


def run_all(lines: pd.DataFrame, plan: pd.DataFrame, scope: me.Scope,
            cost_log: pd.DataFrame | None = None) -> list[dict]:
    """Every check, in section order, worst first within each section."""
    results = []
    results += _safe(lambda: check_plan(plan, lines, scope),
                     PLAN_FILE, "plan file")
    results += _safe(lambda: check_actuals(lines, plan, scope, cost_log),
                     ACTUALS, "Shopify actuals")
    results += _safe(lambda: check_cost_log(lines, plan, scope, cost_log),
                     COST_LOG, "cost log")
    results += _safe(lambda: check_consistency(lines, plan, scope, cost_log),
                     CONSISTENCY, "dashboard consistency")

    order = {s: i for i, s in enumerate(SECTIONS)}
    results.sort(key=lambda r: (order.get(r["section"], 99),
                                SEVERITY_ORDER.get(r["severity"], 9)))
    return results


def summary(results: list[dict]) -> dict:
    """Counts for the cards at the top of the tab."""
    n = {"fail": 0, "warn": 0, "pass": 0}
    for r in results:
        if r["severity"] in n:
            n[r["severity"]] += 1
    return {"total": len(results), "failed": n["fail"],
            "warnings": n["warn"], "passed": n["pass"],
            "clean": n["fail"] == 0}
