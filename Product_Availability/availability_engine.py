"""Availability engine — Inripe.

Turns the Product Master into one daily spine at product x market x date.
Every dashboard view is a groupby on that spine. There is no second
calculation path.

Rules enforced here:
  * A window whose end month/week falls before its start wraps into the
    next year. It is split into two spans inside the reporting year.
  * A product may have several rows sharing one product_id. Each row is a
    separate season window; attributes are taken from the first row.
  * Missing is never zero. Products outside their window are absent from
    the spine, not present with a zero.
  * Quality point is carried for display and never affects any count.

Pure pandas. No Streamlit, no file paths, no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd

from calendar_engine import (
    MONTHS,
    bucket_of,
    bucket_start,
    bucket_end,
    iso_week,
    week_grid,
    week_of,
    year_days,
)

MARKETS = ["UAE", "QA", "KSA", "EG"]

REQUIRED = [
    "product_id", "category", "product", "weight_kg", "tier", "origin",
    "start_month", "start_week", "end_month", "end_week",
]

ATTRS = [
    "product_id", "category", "product", "category_ar", "product_ar",
    "weight_kg", "tier", "origin",
]


class AvailabilityError(ValueError):
    """Raised when the master sheet cannot be interpreted."""


@dataclass(frozen=True)
class Season:
    """One resolved availability window inside one reporting year."""

    product_id: str
    season_no: int
    start: date
    end: date
    wraps: bool
    quality: date | None

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def normalise(products: pd.DataFrame) -> pd.DataFrame:
    """Trim strings, validate required columns, coerce market flags to bool."""
    df = products.copy()
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise AvailabilityError(f"missing columns: {missing}")
    for m in MARKETS:
        if m not in df.columns:
            raise AvailabilityError(f"missing market column: {m}")

    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: v.strip() if isinstance(v, str) else v)

    for m in MARKETS:
        df[m] = df[m].map(lambda v: str(v).strip().upper() in ("Y", "TRUE", "1"))

    blank = df[df[REQUIRED].isna().any(axis=1)]
    if len(blank):
        ids = blank["product_id"].tolist()
        raise AvailabilityError(f"blank required fields on: {ids}")

    return df.reset_index(drop=True)


def resolve_seasons(products: pd.DataFrame, year: int) -> list[Season]:
    """One Season per row. Wrapping windows keep their true end date."""
    out: list[Season] = []
    counter: dict[str, int] = {}
    for _, r in products.iterrows():
        pid = r["product_id"]
        counter[pid] = counter.get(pid, 0) + 1

        start = bucket_start(year, r["start_month"], r["start_week"])
        end = bucket_end(year, r["end_month"], r["end_week"])
        wraps = end < start
        if wraps:
            end = bucket_end(year + 1, r["end_month"], r["end_week"])

        quality = None
        qm, qw = r.get("quality_month"), r.get("quality_week")
        if isinstance(qm, str) and isinstance(qw, str) and qm and qw:
            quality = bucket_start(year, qm, qw)
            if wraps and quality < start:
                quality = bucket_start(year + 1, qm, qw)

        out.append(Season(pid, counter[pid], start, end, wraps, quality))
    return out


def _spans_in_year(season: Season, year: int) -> list[tuple[date, date]]:
    """Clip a season to the reporting year.

    A wrapping window contributes two spans: the tail carried in from the
    previous year and the head that runs out of this one.
    """
    jan1, dec31 = date(year, 1, 1), date(year, 12, 31)
    spans: list[tuple[date, date]] = []

    head = (season.start, min(season.end, dec31))
    if head[0] <= head[1]:
        spans.append(head)

    if season.wraps:
        prior_end = season.end.replace(year=season.end.year - 1)
        tail = (jan1, min(prior_end, dec31))
        if tail[0] <= tail[1]:
            spans.append(tail)

    return spans


def build_spine(products: pd.DataFrame, year: int) -> pd.DataFrame:
    """The one table everything else reads.

    Grain: product_id x market x date, sellable days only.
    Columns: product_id, category, product, tier, origin, weight_kg,
             market, date, season_no, in_quality_window, month, week_bucket,
             iso_week, report_week.
    """
    df = normalise(products)
    seasons = resolve_seasons(df, year)
    grid = week_grid(year)
    attrs = df.drop_duplicates("product_id").set_index("product_id")

    rows: list[dict] = []
    for (_, r), season in zip(df.iterrows(), seasons):
        markets = [m for m in MARKETS if r[m]]
        if not markets:
            continue
        for span_no, (span_start, span_end) in enumerate(
            sorted(_spans_in_year(season, year)), start=1
        ):
            for d in pd.date_range(span_start, span_end, freq="D"):
                d = d.date()
                month, bucket = bucket_of(d)
                in_quality = season.quality is not None and d >= season.quality
                for m in markets:
                    rows.append({
                        "product_id": r["product_id"],
                        "market": m,
                        "date": d,
                        "season_no": season.season_no,
                        "span_no": span_no,
                        "in_quality_window": in_quality,
                        "month": month,
                        "week_bucket": bucket,
                        "iso_week": iso_week(d)[1],
                        "report_week": week_of(d, grid),
                    })

    spine = pd.DataFrame(rows)
    if spine.empty:
        return spine

    spine = spine.merge(
        attrs.reset_index()[[c for c in ATTRS if c in attrs.reset_index().columns]],
        on="product_id", how="left",
    )
    spine["month"] = pd.Categorical(spine["month"], categories=MONTHS, ordered=True)
    return spine.sort_values(["market", "date", "product_id"]).reset_index(drop=True)


# ---------------------------------------------------------------- rollups


def _scope(spine: pd.DataFrame, **filters) -> pd.DataFrame:
    """Apply selector filters. None or empty means no filter."""
    out = spine
    for col, val in filters.items():
        if val is None:
            continue
        wanted = [val] if isinstance(val, str) else list(val)
        if not wanted:
            continue
        out = out[out[col].isin(wanted)]
    return out


def weekly_breadth(spine: pd.DataFrame, **filters) -> pd.DataFrame:
    """Per market per reporting week: how many SKUs, how many categories."""
    s = _scope(spine, **filters)
    if s.empty:
        return pd.DataFrame(columns=["market", "report_week", "skus", "categories"])
    g = s.groupby(["market", "report_week"], observed=True)
    return (
        g.agg(skus=("product_id", "nunique"), categories=("category", "nunique"))
        .reset_index()
    )


def live_on(spine: pd.DataFrame, day: date, **filters) -> pd.DataFrame:
    """Everything sellable on one date."""
    s = _scope(spine, **filters)
    return s[s["date"] == day]


def category_mix(spine: pd.DataFrame, market: str, **filters) -> pd.DataFrame:
    """SKU count per category per reporting week, one market."""
    s = _scope(spine, market=market, **filters)
    if s.empty:
        return pd.DataFrame(columns=["report_week", "category", "skus"])
    return (
        s.groupby(["report_week", "category"], observed=True)["product_id"]
        .nunique().reset_index(name="skus")
    )


def transitions(spine: pd.DataFrame, **filters) -> pd.DataFrame:
    """First and last sellable date per product x market x span.

    Wrapping products get one row per span, so a season running Aug to
    March reports its January tail and its August start separately
    instead of collapsing to 1 Jan - 31 Dec.
    """
    s = _scope(spine, **filters)
    cols = ["product_id", "product", "category", "market",
            "season_no", "span_no", "first_day", "last_day"]
    if s.empty:
        return pd.DataFrame(columns=cols)
    g = s.groupby(["product_id", "product", "category", "market",
                   "season_no", "span_no"], observed=True)["date"]
    out = g.agg(first_day="min", last_day="max").reset_index()
    return out.sort_values(["market", "first_day", "product"]).reset_index(drop=True)


def continuity(spine: pd.DataFrame, market: str) -> pd.DataFrame:
    """Per category per week: is anything live, and how many varieties."""
    s = _scope(spine, market=market)
    if s.empty:
        return pd.DataFrame(columns=["category", "report_week", "varieties", "live"])
    out = (
        s.groupby(["category", "report_week"], observed=True)["product_id"]
        .nunique().reset_index(name="varieties")
    )
    out["live"] = out["varieties"] > 0
    return out


def gaps(spine: pd.DataFrame, market: str, year: int) -> pd.DataFrame:
    """Weeks in which a category has nothing live, for categories that
    exist in that market at some point in the year."""
    grid_weeks = [n for n, _, _ in week_grid(year)]
    s = _scope(spine, market=market)
    if s.empty:
        return pd.DataFrame(columns=["category", "report_week"])
    present = (
        s.groupby(["category", "report_week"], observed=True).size()
        .reset_index(name="n")
    )
    cats = sorted(s["category"].unique())
    full = pd.MultiIndex.from_product(
        [cats, grid_weeks], names=["category", "report_week"]
    ).to_frame(index=False)
    merged = full.merge(present, on=["category", "report_week"], how="left")
    return merged[merged["n"].isna()].drop(columns=["n"]).reset_index(drop=True)
