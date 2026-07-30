"""Forecast engine — Inripe.

What this is, and deliberately is not.

You have one partial season: January to July 2026, plus a fragment of
September and October 2025. Most products sell inside a six to twelve week
window, so a single product's history is forty to ninety daily observations,
observed once. ARIMA, SARIMA and Prophet all need two or more complete
seasonal cycles before their seasonal terms mean anything. Fitted to this
data they would model noise and report it with confidence. They are not used.

What the data does support is a multiplicative decomposition where the
seasonal shape is pooled across products rather than estimated per product:

    units  =  level  x  weekday  x  season position  x  trend

  level            recent demand for this product in this market
  weekday          pooled across all products in a market. Seven months of
                   daily data estimates seven numbers comfortably
  season position  pooled per category. Fifteen mango varieties across four
                   markets estimate one arc; one variety cannot estimate its
                   own. This is hierarchical pooling, and it is the right
                   move when each series is short
  trend            recent slope, damped so it cannot extrapolate absurdly

Uncertainty comes from the empirical spread of backtest residuals, not from
assuming a normal distribution. Fresh produce demand is skewed and spiky, so
a normal interval would be too narrow exactly when it matters.

Orders are forecast separately as new and returning, because they behave
differently and have different owners. Returning demand is a slow-moving
base. New demand is a marketing lever. A units-only model can tell you a
month is short; this one can tell you whether it was fewer customers or
smaller baskets.

Pure pandas and numpy. No Streamlit, no I/O, no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
DEAD_STATUSES = {"REFUNDED", "VOIDED", "EXPIRED"}

# A window shorter than this cannot say anything about its own shape, so it
# leans entirely on the pooled category curve.
MIN_DAYS_FOR_OWN_SHAPE = 21
# Below this many observations a weekday profile is noise, so the market
# falls back to a flat week.
MIN_DAYS_FOR_WEEKDAY = 42
# The trend is damped towards one so a short run of good days cannot
# extrapolate into an absurd forecast.
TREND_DAMPING = 0.75
TREND_CAP = (0.6, 1.6)


class ForecastError(ValueError):
    """Raised when there is not enough history to forecast honestly."""


@dataclass
class Fit:
    """Everything learned from history, kept so it can be inspected."""

    daily: pd.DataFrame
    weekday: pd.DataFrame
    season: pd.DataFrame
    windows: pd.DataFrame
    residual_quantiles: dict
    coverage: dict = field(default_factory=dict)
    spans: dict = field(default_factory=dict)


# ------------------------------------------------------------------ shaping


def daily_units(lines: pd.DataFrame, year: int | None = None) -> pd.DataFrame:
    """One row per product, market and day. Billable demand only.

    Cancelled and dead-status orders are excluded, not zeroed: they were
    never demand that could have been served.
    """
    d = lines.copy()
    d["date"] = pd.to_datetime(d["processed_at"], utc=True,
                               format="mixed").dt.tz_localize(None).dt.normalize()
    d = d[(~d["cancelled"]) & (~d["financial_status"].isin(DEAD_STATUSES))
          & (d["qty_current"] > 0)]
    if year is not None:
        d = d[d["date"].dt.year == year]
    if d.empty:
        raise ForecastError("no billable lines to forecast from")

    agg = {"units": ("qty_current", "sum"),
           "revenue_lc": ("net_line_lc", "sum"),
           "orders": ("order", "nunique")}
    if "pack_kg" in d.columns:
        d["kg"] = d["qty_current"] * pd.to_numeric(d["pack_kg"], errors="coerce")
        agg["kg"] = ("kg", "sum")

    g = (d.groupby(["product", "market", "date"], observed=True)
         .agg(**agg).reset_index())
    return g.sort_values(["market", "product", "date"]).reset_index(drop=True)


def expected_spans(windows: pd.DataFrame, as_of: pd.Timestamp) -> dict:
    """How long a selling window usually lasts, per fruit group.

    A window still open on the last day of data has not finished, so its
    observed length says nothing about its true length. Taking it at face
    value places a product that is ramping up at the end of its own arc and
    applies the decline factor to it — which is how a forecast comes back at
    a fifth of actual on a season launch.

    So only windows that closed before the data ended are used to learn a
    typical length, and open windows borrow it.
    """
    closed = windows[windows["last"] < as_of - pd.Timedelta(days=3)].copy()
    closed["group"] = closed["product"].map(lambda p: str(p).split()[0])
    out = {}
    if len(closed):
        for grp, sub in closed.groupby("group", observed=True):
            if len(sub) >= 2:
                out[grp] = float(sub["days"].median())
        out["_default"] = float(closed["days"].median())
    else:
        out["_default"] = 60.0
    return out


def selling_windows(daily: pd.DataFrame) -> pd.DataFrame:
    """First and last day each product actually sold, per market.

    A product is only in season while it is selling, so the window is taken
    from the data rather than assumed from a calendar.
    """
    g = (daily.groupby(["product", "market"], observed=True)["date"]
         .agg(first="min", last="max").reset_index())
    g["days"] = (g["last"] - g["first"]).dt.days + 1
    tot = (daily.groupby(["product", "market"], observed=True)["units"]
           .sum().reset_index(name="total_units"))
    return g.merge(tot, on=["product", "market"])


# ------------------------------------------------------------- the factors


def weekday_factors(daily: pd.DataFrame) -> pd.DataFrame:
    """How much each weekday differs from an average day, per market.

    Pooled across every product in the market. Individual products are far
    too thin for this; the market as a whole is not. A market with too little
    history gets a flat week rather than a fabricated one.
    """
    d = daily.copy()
    d["weekday"] = d["date"].dt.dayofweek
    rows = []
    for market, grp in d.groupby("market", observed=True):
        by_day = grp.groupby("date", observed=True)["units"].sum()
        if len(by_day) < MIN_DAYS_FOR_WEEKDAY:
            for wd in range(7):
                rows.append({"market": market, "weekday": wd, "factor": 1.0,
                             "basis": "flat, too little history"})
            continue
        frame = by_day.reset_index()
        frame["weekday"] = frame["date"].dt.dayofweek
        overall = frame["units"].mean()
        for wd in range(7):
            sub = frame[frame["weekday"] == wd]["units"]
            f = (sub.mean() / overall) if len(sub) and overall else 1.0
            rows.append({"market": market, "weekday": wd,
                         "factor": float(np.clip(f, 0.3, 2.5)),
                         "basis": f"{len(sub)} observations"})
    return pd.DataFrame(rows)


def season_curves(daily: pd.DataFrame, windows: pd.DataFrame,
                  bins: int = 10) -> pd.DataFrame:
    """The shape of a selling window, pooled per category-like group.

    Each completed window is normalised twice: its dates onto 0 to 1, and its
    daily volume onto its own mean. What is left is pure shape — ramp, peak,
    decline — comparable across products that sell wildly different volumes.
    Averaging those shapes gives a curve that a single short window could
    never estimate for itself.

    Grouping is by the first word of the product name, which for this
    catalogue is the fruit: Mango, Fig, Grapes. It is a deliberate proxy for
    category so this engine does not need the plan sheet to run.
    """
    d = daily.merge(windows, on=["product", "market"])
    d = d[d["days"] >= MIN_DAYS_FOR_OWN_SHAPE].copy()
    if d.empty:
        return pd.DataFrame(columns=["group", "bin", "factor", "windows"])

    d["pos"] = ((d["date"] - d["first"]).dt.days
                / (d["days"] - 1).clip(lower=1)).clip(0, 1)
    d["bin"] = (d["pos"] * bins).astype(int).clip(0, bins - 1)
    mean_by_window = (d.groupby(["product", "market"], observed=True)["units"]
                      .transform("mean"))
    d["norm"] = d["units"] / mean_by_window.replace(0, np.nan)
    d["group"] = d["product"].map(lambda p: str(p).split()[0])

    rows = []
    for grp, sub in d.groupby("group", observed=True):
        n_windows = sub.groupby(["product", "market"]).ngroups
        for b in range(bins):
            vals = sub[sub["bin"] == b]["norm"].dropna()
            rows.append({
                "group": grp, "bin": b,
                "factor": float(vals.mean()) if len(vals) else 1.0,
                "windows": n_windows, "observations": len(vals)})
    curves = pd.DataFrame(rows)

    # A group built from one or two windows is that product's own noise
    # dressed up as a shape, so it is replaced by the all-product average.
    overall = (curves.groupby("bin")["factor"].mean()
               .rename("fallback").reset_index())
    curves = curves.merge(overall, on="bin")
    thin = curves["windows"] < 3
    curves.loc[thin, "factor"] = curves.loc[thin, "fallback"]
    curves["basis"] = np.where(thin, "pooled across all products",
                               "pooled within group")
    return curves.drop(columns=["fallback"])


def _trend(units: pd.Series, span: int = 28) -> float:
    """Recent direction, damped and capped.

    An undamped slope from three weeks of a rising season will happily
    forecast a product into orbit. Damping pulls it back towards flat, and
    the cap stops any single burst from dominating.
    """
    if len(units) < 10:
        return 1.0
    recent = units.tail(span)
    half = max(3, len(recent) // 2)
    early, late = recent.head(half).mean(), recent.tail(half).mean()
    if not early or np.isnan(early) or np.isnan(late):
        return 1.0
    raw = late / early
    damped = 1.0 + (raw - 1.0) * TREND_DAMPING
    return float(np.clip(damped, *TREND_CAP))


# ------------------------------------------------------------------- fit


def fit(lines: pd.DataFrame, year: int | None = None) -> Fit:
    """Learn every factor from history. No forecasting happens here."""
    daily = daily_units(lines, year)
    windows = selling_windows(daily)
    wd = weekday_factors(daily)
    curves = season_curves(daily, windows)

    coverage = {
        "days": int(daily["date"].nunique()),
        "from": daily["date"].min().date(),
        "to": daily["date"].max().date(),
        "products": int(daily["product"].nunique()),
        "series": int(daily.groupby(["product", "market"]).ngroups),
        "windows_over_3_weeks": int((windows["days"] >= MIN_DAYS_FOR_OWN_SHAPE).sum()),
    }
    f = Fit(daily=daily, weekday=wd, season=curves, windows=windows,
            residual_quantiles={}, coverage=coverage)
    f.spans = expected_spans(windows, daily["date"].max())
    coverage["typical_window_days"] = round(f.spans.get("_default", 0))
    return f


# -------------------------------------------------------------- forecast


def _level(series: pd.DataFrame, as_of: pd.Timestamp, span: int = 21,
           deseason=None) -> float:
    """Weighted recent mean, most recent days counting most.

    Crucially the recent days are de-seasonalised first. The last three weeks
    already sit somewhere on the season arc; if that is not divided out, the
    forecast multiplies by a season factor twice and a product observed near
    its peak is projected to stay there. That mistake shows up as a forecast
    running at roughly half of actual on the declining side of a window,
    which is exactly what the backtest caught.
    """
    hist = series[series["date"] <= as_of].tail(span)
    if hist.empty:
        return 0.0
    units = hist["units"].astype(float).to_numpy()
    if deseason is not None:
        f = np.array([max(0.15, deseason(d)) for d in hist["date"]])
        units = units / f
    w = np.linspace(0.4, 1.0, len(units))
    return float(np.average(units, weights=w))


def forecast(f: Fit, start: date, end: date,
             market: str | None = None, product: str | None = None,
             as_of: date | None = None) -> pd.DataFrame:
    """Daily forecast per product, market and day, with P10, P50 and P90.

    Any horizon is allowed. Accuracy is not uniform across it, which is why
    the interval widens rather than the estimate being restated as fact.
    """
    as_of = pd.Timestamp(as_of or f.daily["date"].max())
    days = pd.date_range(start, end, freq="D")
    if not len(days):
        return pd.DataFrame()

    wd = f.weekday.set_index(["market", "weekday"])["factor"].to_dict()
    curves = f.season.set_index(["group", "bin"])["factor"].to_dict()
    win = f.windows.set_index(["product", "market"])

    rows = []
    keys = f.daily.groupby(["product", "market"], observed=True).groups.keys()
    for prod, mkt in keys:
        if market and mkt != market:
            continue
        if product and prod != product:
            continue
        series = f.daily[(f.daily["product"] == prod)
                         & (f.daily["market"] == mkt)]
        grp = str(prod).split()[0]

        try:
            w = win.loc[(prod, mkt)]
            first, last, observed = w["first"], w["last"], max(1, int(w["days"]))
        except KeyError:
            first, last, observed = (series["date"].min(),
                                     series["date"].max(), 30)

        # A window still open at the end of the data has not run its course,
        # so its span is taken from products of the same group that finished.
        still_open = last >= as_of - pd.Timedelta(days=3)
        if still_open:
            typical = f.spans.get(grp, f.spans.get("_default", 60.0))
            span = max(observed, int(typical))
        else:
            span = observed

        def _factor_on(day, _first=first, _span=span, _grp=grp, _mkt=mkt):
            pos = float(np.clip((day - _first).days / max(1, _span - 1), 0, 1))
            b = int(np.clip(pos * 10, 0, 9))
            return (curves.get((_grp, b), 1.0)
                    * wd.get((_mkt, day.dayofweek), 1.0))

        # De-seasonalised level, so the season is applied once and not twice.
        lvl = _level(series, as_of, deseason=_factor_on)
        if lvl <= 0:
            continue
        des = series.assign(
            base=series["units"] / series["date"].map(
                lambda d: max(0.15, _factor_on(d))))
        tr = _trend(des["base"])

        for i, day in enumerate(days):
            # Beyond the observed window the position is extrapolated, which
            # is exactly where the season factor is least trustworthy — the
            # widening interval below is the honest response.
            pos = float(np.clip((day - first).days / max(1, span - 1), 0, 1))
            b = int(np.clip(pos * 10, 0, 9))
            sf = curves.get((grp, b), 1.0)
            wf = wd.get((mkt, day.dayofweek), 1.0)
            # Damp the trend across the horizon so day 60 is not day 1's
            # slope compounded sixty times.
            tf = 1.0 + (tr - 1.0) * (TREND_DAMPING ** (i / 14.0))
            rows.append({
                "product": prod, "market": mkt, "date": day,
                "p50": max(0.0, lvl * sf * wf * tf),
                "level": lvl, "season_factor": sf, "weekday_factor": wf,
                "trend_factor": tf,
                "beyond_history": bool(day > last),
                "days_ahead": int((day - as_of).days),
            })

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    # The interval widens with the horizon and again beyond observed history.
    # Multipliers come from backtest residuals when available, and from a
    # deliberately wide default when not.
    q = f.residual_quantiles or {"p10": 0.55, "p90": 1.70}
    h = (out["days_ahead"].clip(lower=0) / 30.0).clip(0, 3)
    widen = 1.0 + 0.25 * h + 0.35 * out["beyond_history"].astype(float)
    out["p10"] = out["p50"] * (1 - (1 - q["p10"]) * widen)
    out["p90"] = out["p50"] * (1 + (q["p90"] - 1) * widen)
    out["p10"] = out["p10"].clip(lower=0)
    return out.sort_values(["market", "product", "date"]).reset_index(drop=True)


# -------------------------------------------------------------- backtest


def backtest(lines: pd.DataFrame, year: int | None = None,
             horizon: int = 14, folds: int = 4) -> dict:
    """Hold out the last weeks, forecast them, compare against naive.

    A forecast that is not beaten against a naive baseline is decoration. The
    baseline here is the trailing 21 day mean — genuinely hard to beat on
    short noisy series, which is the point.

    Also calibrates the prediction interval: the residual spread it measures
    is what later sets P10 and P90.
    """
    daily = daily_units(lines, year)
    last = daily["date"].max()
    results, ratios = [], []

    for k in range(folds, 0, -1):
        cut = last - pd.Timedelta(days=horizon * k)
        train = daily[daily["date"] <= cut]
        test = daily[(daily["date"] > cut)
                     & (daily["date"] <= cut + pd.Timedelta(days=horizon))]
        if train.empty or test.empty or train["date"].nunique() < 30:
            continue

        sub = lines.copy()
        sub["_d"] = pd.to_datetime(sub["processed_at"], utc=True,
                                   format="mixed").dt.tz_localize(None)
        f = fit(sub[sub["_d"] <= cut].drop(columns=["_d"]), year)
        fc = forecast(f, (cut + pd.Timedelta(days=1)).date(),
                      (cut + pd.Timedelta(days=horizon)).date(), as_of=cut.date())
        if fc.empty:
            continue

        m = test.merge(fc[["product", "market", "date", "p50"]],
                       on=["product", "market", "date"], how="left")
        m["p50"] = m["p50"].fillna(0)

        naive = (train.groupby(["product", "market"], observed=True)["units"]
                 .apply(lambda s: s.tail(21).mean()).rename("naive").reset_index())
        m = m.merge(naive, on=["product", "market"], how="left")
        m["naive"] = m["naive"].fillna(0)

        results.append({
            "fold": folds - k + 1,
            "from": (cut + pd.Timedelta(days=1)).date(),
            "to": (cut + pd.Timedelta(days=horizon)).date(),
            "n": len(m),
            "actual": float(m["units"].sum()),
            "forecast": float(m["p50"].sum()),
            "mae_model": float((m["units"] - m["p50"]).abs().mean()),
            "mae_naive": float((m["units"] - m["naive"]).abs().mean()),
            "bias": float((m["p50"] - m["units"]).sum()),
        })
        good = m[m["p50"] > 0]
        if len(good):
            ratios.extend((good["units"] / good["p50"]).tolist())

    if not results:
        return {"folds": [], "verdict": "not enough history to backtest",
                "residual_quantiles": {}}

    r = pd.DataFrame(results)
    mm, mn = r["mae_model"].mean(), r["mae_naive"].mean()
    lift = (1 - mm / mn) if mn else 0.0
    arr = np.array(ratios) if ratios else np.array([1.0])
    q = {"p10": float(np.clip(np.quantile(arr, 0.10), 0.2, 0.95)),
         "p90": float(np.clip(np.quantile(arr, 0.90), 1.05, 3.0))}

    if lift > 0.10:
        verdict = f"model beats naive by {lift:.0%} — use it"
    elif lift > 0:
        verdict = (f"model beats naive by only {lift:.0%} — marginal, treat "
                   f"the forecast as indicative")
    else:
        verdict = (f"model does NOT beat a trailing mean ({lift:+.0%}) — the "
                   f"history is too thin, use the naive baseline instead")

    return {"folds": results, "mae_model": mm, "mae_naive": mn,
            "lift_vs_naive": lift, "verdict": verdict,
            "residual_quantiles": q,
            "total_bias": float(r["bias"].sum())}


def fit_and_calibrate(lines: pd.DataFrame, year: int | None = None) -> tuple:
    """Fit, then set the interval from the model's own backtest error."""
    bt = backtest(lines, year)
    f = fit(lines, year)
    if bt.get("residual_quantiles"):
        f.residual_quantiles = bt["residual_quantiles"]
    return f, bt


# --------------------------------------------------- orders and customers


def order_forecast(lines: pd.DataFrame, start: date, end: date,
                   market: str | None = None, year: int | None = None) -> dict:
    """Orders split into new and returning customers.

    Returning demand is a base that moves slowly. New demand is bought, and
    is the volatile part. Forecasting them together hides which one moved,
    and they have different owners.
    """
    d = lines.copy()
    d["date"] = pd.to_datetime(d["processed_at"], utc=True,
                               format="mixed").dt.tz_localize(None).dt.normalize()
    d = d[(~d["cancelled"]) & (~d["financial_status"].isin(DEAD_STATUSES))
          & (d["qty_current"] > 0)]
    if year is not None:
        d = d[d["date"].dt.year == year]
    if market:
        d = d[d["market"] == market]
    if d.empty:
        return {}

    orders = (d.groupby(["order", "date", "customer_type"], observed=True)
              .agg(units=("qty_current", "sum"),
                   revenue=("net_line_lc", "sum")).reset_index())
    per_day = (orders.groupby(["date", "customer_type"], observed=True)
               .agg(orders=("order", "nunique"), units=("units", "sum"))
               .reset_index())

    horizon = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    out = {"horizon_days": horizon, "segments": {}}
    for seg in ("New", "Returning", "Unknown"):
        sub = per_day[per_day["customer_type"] == seg]
        if sub.empty:
            continue
        recent = sub.tail(28)
        rate = float(recent["orders"].mean())
        basket = float(recent["units"].sum() / max(1, recent["orders"].sum()))
        out["segments"][seg] = {
            "orders_per_day": rate,
            "basket": basket,
            "forecast_orders": rate * horizon,
            "forecast_units": rate * horizon * basket,
            "share_of_orders": float(
                sub["orders"].sum() / per_day["orders"].sum()),
        }
    tot = sum(v["forecast_orders"] for v in out["segments"].values())
    out["forecast_orders"] = tot
    out["forecast_units"] = sum(v["forecast_units"]
                                for v in out["segments"].values())
    return out


def repeat_behaviour(lines: pd.DataFrame, year: int | None = None) -> pd.DataFrame:
    """How much of demand is repeat, and how quickly it repeats.

    For a perishable sold on a short season, the repeat base is the asset.
    A market growing only through new customers is renting its revenue.
    """
    d = lines.copy()
    d["date"] = pd.to_datetime(d["processed_at"], utc=True,
                               format="mixed").dt.tz_localize(None).dt.normalize()
    d = d[(~d["cancelled"]) & (~d["financial_status"].isin(DEAD_STATUSES))
          & (d["qty_current"] > 0)]
    if year is not None:
        d = d[d["date"].dt.year == year]
    if d.empty or "customer_type" not in d.columns:
        return pd.DataFrame()

    o = (d.groupby(["market", "order", "customer_type"], observed=True)
         .agg(date=("date", "min"), units=("qty_current", "sum"),
              revenue=("net_line_lc", "sum")).reset_index())
    g = (o.groupby(["market", "customer_type"], observed=True)
         .agg(orders=("order", "nunique"), units=("units", "sum"),
              revenue=("revenue", "sum")).reset_index())
    tot = g.groupby("market")["orders"].transform("sum")
    g["order_share"] = g["orders"] / tot
    g["basket"] = g["units"] / g["orders"]
    g["aov"] = g["revenue"] / g["orders"]
    return g.sort_values(["market", "customer_type"]).reset_index(drop=True)
