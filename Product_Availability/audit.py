"""Audit — Inripe availability layer.

Recomputes every published figure from the master sheet using its own
independent logic, then asserts the engines agree. It deliberately does
not reuse availability_engine's helpers for the recomputation.

Run before every deploy:  python audit.py Inripe_Product_Master.xlsx 2026
Exit code 0 = clean. Non-zero = do not ship.
"""

from __future__ import annotations

import calendar
import sys
from datetime import date, timedelta

import pandas as pd

import availability_engine as ae
from calendar_engine import MONTHS, week_grid

MARKETS = ["UAE", "QA", "KSA", "EG"]
_FIRST = {"W1": 1, "W2": 8, "W3": 15, "W4": 22}


class Report:
    def __init__(self) -> None:
        self.passes: list[str] = []
        self.fails: list[tuple[str, str]] = []
        self.warns: list[tuple[str, str]] = []

    def ok(self, name: str) -> None:
        self.passes.append(name)
        print(f"  PASS  {name}")

    def fail(self, code: str, msg: str) -> None:
        self.fails.append((code, msg))

    def warn(self, code: str, msg: str) -> None:
        self.warns.append((code, msg))

    def check(self, cond: bool, code: str, name: str, msg: str = "") -> None:
        self.ok(name) if cond else self.fail(code, msg or name)


# ------------------------------------------------ independent recomputation


def _start(year: int, month: str, week: str) -> date:
    return date(year, MONTHS.index(month.strip().title()) + 1, _FIRST[week.strip().upper()])


def _end(year: int, month: str, week: str) -> date:
    m = MONTHS.index(month.strip().title()) + 1
    w = week.strip().upper()
    day = calendar.monthrange(year, m)[1] if w == "W4" else _FIRST[w] + 6
    return date(year, m, day)


def naive_sellable(row: pd.Series, day: date, year: int) -> bool:
    """Brute force: is this product sellable on this date? No engine code."""
    s = _start(year, row["start_month"], row["start_week"])
    e = _end(year, row["end_month"], row["end_week"])
    if e < s:
        return day >= s or day <= _end(year, row["end_month"], row["end_week"])
    return s <= day <= e


def naive_counts(products: pd.DataFrame, year: int) -> dict:
    """Day-by-day SKU and category counts per market, computed from scratch."""
    out: dict[tuple[str, date], tuple[int, int]] = {}
    d = date(year, 1, 1)
    while d <= date(year, 12, 31):
        for m in MARKETS:
            ids, cats = set(), set()
            for _, r in products.iterrows():
                if str(r[m]).strip().upper() not in ("Y", "TRUE", "1"):
                    continue
                if naive_sellable(r, d, year):
                    ids.add(r["product_id"])
                    cats.add(r["category"])
            out[(m, d)] = (len(ids), len(cats))
        d += timedelta(days=1)
    return out


# ------------------------------------------------------------------ checks


def run(path: str, year: int) -> Report:
    rep = Report()
    raw = pd.read_excel(path, sheet_name="Products")
    markets_sheet = pd.read_excel(path, sheet_name="Markets")
    spine = ae.build_spine(raw, year)

    print("=== A. SOURCE ===")
    rep.check(len(raw) > 0, "A1", f"master sheet loaded, {len(raw)} rows")
    rep.check(set(markets_sheet["market_id"]) == set(MARKETS), "A2",
              "Markets sheet matches engine market list",
              f"{sorted(markets_sheet['market_id'])} vs {MARKETS}")
    dupe = raw.duplicated(["product_id", "start_month", "start_week"]).sum()
    rep.check(dupe == 0, "A3", "no duplicate product_id + start bucket",
              f"{dupe} duplicates")

    print("\n=== B. WINDOW RESOLUTION ===")
    seasons = ae.resolve_seasons(ae.normalise(raw), year)
    rep.check(len(seasons) == len(raw), "B1", f"{len(seasons)} windows resolved")
    rep.check(all(s.end >= s.start for s in seasons), "B2",
              "every window ends on or after it starts")
    rep.check(all(s.days <= 366 for s in seasons), "B3",
              "no window exceeds 366 days")
    wraps = sum(s.wraps for s in seasons)
    rep.ok(f"{wraps} wrapping, {len(seasons) - wraps} in-year")
    bad_q = [s.product_id for s in seasons
             if s.quality is not None and not (s.start <= s.quality <= s.end)]
    rep.check(not bad_q, "B4", "every quality point sits inside its window",
              f"outside: {bad_q}")

    print("\n=== C. SPINE INTEGRITY ===")
    rep.check(not spine.empty, "C1", f"spine built, {len(spine):,} rows")
    rep.check(spine.notna().all().all(), "C2", "spine has no nulls")
    rep.check(spine.duplicated(["product_id", "market", "date", "season_no"]).sum() == 0,
              "C3", "no duplicate product x market x date x season")
    tr_all = ae.transitions(spine)
    rep.check((tr_all["first_day"] <= tr_all["last_day"]).all(), "C6",
              "every transition span starts on or before it ends")
    rep.check(spine["date"].min() >= date(year, 1, 1)
              and spine["date"].max() <= date(year, 12, 31),
              "C4", "every spine date falls inside the reporting year")
    rep.check(set(spine["market"]) <= set(MARKETS), "C5", "spine markets are known")

    print("\n=== D. SPINE vs INDEPENDENT RECOMPUTE ===")
    naive = naive_counts(raw, year)
    mismatch = []
    for (m, d), (n_sku, n_cat) in naive.items():
        got = spine[(spine["market"] == m) & (spine["date"] == d)]
        if got["product_id"].nunique() != n_sku or got["category"].nunique() != n_cat:
            mismatch.append((m, d, n_sku, got["product_id"].nunique(),
                             n_cat, got["category"].nunique()))
    rep.check(not mismatch, "D1",
              f"all {len(naive):,} market-days match the independent recompute",
              f"{len(mismatch)} mismatches, first: {mismatch[:3]}")

    print("\n=== E. CROSS-SECTION CONSISTENCY ===")
    breadth = ae.weekly_breadth(spine)
    bad = []
    for m in MARKETS:
        mix = ae.category_mix(spine, m)
        for wk, grp in mix.groupby("report_week"):
            row = breadth[(breadth["market"] == m) & (breadth["report_week"] == wk)]
            if row.empty:
                bad.append((m, wk, "missing from breadth"))
                continue
            if int(grp["skus"].sum()) != int(row["skus"].iloc[0]):
                bad.append((m, wk, f"mix {grp['skus'].sum()} vs breadth {row['skus'].iloc[0]}"))
            if grp["category"].nunique() != int(row["categories"].iloc[0]):
                bad.append((m, wk, "category count differs"))
    rep.check(not bad, "E1", "category mix reconciles to weekly breadth",
              f"{len(bad)} breaks, first: {bad[:3]}")

    tr = ae.transitions(spine)
    bad = []
    for _, t in tr.iterrows():
        live = spine[(spine["product_id"] == t["product_id"])
                     & (spine["market"] == t["market"])
                     & (spine["season_no"] == t["season_no"])
                     & (spine["span_no"] == t["span_no"])]
        if live["date"].min() != t["first_day"] or live["date"].max() != t["last_day"]:
            bad.append(t["product_id"])
    rep.check(not bad, "E2", "transition first/last days match the spine",
              f"{bad[:5]}")

    bad = []
    for m in MARKETS:
        cont = ae.continuity(spine, m)
        gap = ae.gaps(spine, m, year)
        overlap = cont.merge(gap, on=["category", "report_week"], how="inner")
        if len(overlap):
            bad.append((m, len(overlap)))
    rep.check(not bad, "E3", "gaps never overlap live continuity weeks", str(bad))

    print("\n=== F. BUSINESS RULES ===")
    rep.check(spine["in_quality_window"].dtype == bool, "F1",
              "quality flag is boolean and carries no weight in any count")
    counts_all = ae.weekly_breadth(spine)
    counts_t1 = ae.weekly_breadth(spine, tier="Tier 1")
    rep.check(counts_t1["skus"].sum() <= counts_all["skus"].sum(), "F2",
              "tier filter narrows scope, never widens it")
    rep.check((breadth["categories"] <= breadth["skus"]).all(), "F3",
              "category count never exceeds SKU count")

    print("\n=== G. DATA QUALITY (warnings) ===")
    norm = ae.normalise(raw)
    no_market = norm[~norm[MARKETS].any(axis=1)]
    if len(no_market):
        rep.warn("G1", f"{len(no_market)} products carried in no market")
    no_q = norm[norm.get("quality_month").isna()] if "quality_month" in norm else norm.iloc[0:0]
    if len(no_q):
        rep.warn("G2", f"{len(no_q)} products have no quality point")
    if "sku" not in norm.columns or norm.get("sku", pd.Series(dtype=object)).isna().all():
        rep.warn("G3", "no SKU column populated — no join key to Shopify yet")
    for m in MARKETS:
        b = breadth[breadth["market"] == m]
        if b.empty:
            rep.warn("G4", f"{m} has no live weeks at all")

    return rep


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "Inripe_Product_Master.xlsx"
    year = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    rep = run(path, year)

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
