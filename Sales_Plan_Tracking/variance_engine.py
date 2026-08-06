"""Variance engine — Inripe sales tracking.

Reads the actuals workbook, normalises it, and compares it to the plan.

Rules enforced here:
  * Plan is compared against NET sales, after discounts and returns.
    Returns run 13% of gross in KSA, so gross would flatter every number.
  * Missing is not zero. A month with no actual rows and no plan rows is
    absent. A month with a plan and no actuals is 0% attainment, which is
    a real result. The two are never conflated.
  * The revenue gap is decomposed into volume, price and mix. A single
    variance number is not actionable; the split is.
  * CM is measured at plan cost: actual units x planned unit cost. This
    isolates commercial performance from cost movement, which is not
    tracked reliably.
  * Weighted averages are total / total, never the mean of a ratio.

Pure pandas. No Streamlit, no file paths, no network.
"""

from __future__ import annotations

import pandas as pd

import plan_engine as pe

MONTHS = pe.MONTHS
MARKETS = pe.MARKETS

# Column names as Shopify exports them.
SRC = {
    "Product title": "product",
    "Month": "month_raw",
    "Net items sold": "act_units",
    "Gross sales": "act_gross_lc",
    "Discounts": "act_discounts_lc",
    "Sales reversals": "act_returns_lc",
    "Net sales": "act_net_lc",
}

# Line items that are not products and must never reach product performance.
NOT_PRODUCTS = {"Gift Wrapping", "Gift wrapping", "Tip", "Shipping",
                "WooCommerce Order", "Woocommerce Order"}


class ActualsError(ValueError):
    """Raised when the actuals workbook cannot be interpreted."""


def normalise_actuals(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One frame from the per-market sheets. Market comes from the sheet name."""
    out = []
    for market, raw in sheets.items():
        if market not in MARKETS:
            continue
        df = raw.copy()
        df.columns = [str(c).strip() for c in df.columns]
        missing = [c for c in SRC if c not in df.columns]
        if missing:
            raise ActualsError(f"{market} sheet is missing columns: {missing}")

        df = df[list(SRC)].rename(columns=SRC)
        df = df[df["product"].notna()]
        if df.empty:
            continue

        df["product"] = df["product"].map(lambda v: str(v).strip())
        df = df[~df["product"].isin(NOT_PRODUCTS)]

        # Shopify writes the month as the first day of the month.
        m = pd.to_datetime(df["month_raw"], errors="coerce")
        if m.isna().any():
            bad = df.loc[m.isna(), "month_raw"].unique().tolist()
            raise ActualsError(f"{market}: unreadable months {bad[:4]}")
        df["month"] = m.dt.month.map(lambda n: MONTHS[n - 1])
        df["year"] = m.dt.year
        df = df.drop(columns=["month_raw"])

        for c in ("act_units", "act_gross_lc", "act_discounts_lc",
                  "act_returns_lc", "act_net_lc"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

        # Shopify exports these as negatives. Store magnitudes; keep signs out
        # of the arithmetic so nothing double-negates downstream.
        df["act_discounts_lc"] = df["act_discounts_lc"].abs()
        df["act_returns_lc"] = df["act_returns_lc"].abs()

        df["market"] = market
        out.append(df)

    if not out:
        raise ActualsError("no market sheet contained any rows")

    all_df = pd.concat(out, ignore_index=True)
    dupe = all_df.duplicated(["product", "market", "month", "year"]).sum()
    if dupe:
        raise ActualsError(f"{dupe} duplicate product x market x month rows")

    all_df["act_price_lc"] = (all_df["act_net_lc"] / all_df["act_units"]).where(
        all_df["act_units"].ne(0))
    all_df["return_rate"] = (all_df["act_returns_lc"] / all_df["act_gross_lc"]).where(
        all_df["act_gross_lc"].ne(0))
    return all_df.reset_index(drop=True)


DEAD_STATUSES = {"REFUNDED", "VOIDED", "EXPIRED"}
CONFIRMED = ("PAID",)


# Each market's own clock, so a cost change can be typed as the local hour it
# happened rather than converted by hand.
MARKET_TZ = {
    "UAE": "Asia/Dubai", "QA": "Asia/Qatar", "KSA": "Asia/Riyadh",
    "EG": "Africa/Cairo", "Dubai": "Asia/Dubai", "Doha": "Asia/Qatar",
    "Riyadh": "Asia/Riyadh", "Cairo": "Africa/Cairo", "UTC": "UTC",
}


def _to_utc_naive(ts, tz: str):
    """A local wall-clock stamp becomes a naive UTC one for comparison."""
    if pd.isna(ts):
        return ts
    if not tz or tz == "UTC":
        return ts
    try:
        from zoneinfo import ZoneInfo
        return (ts.tz_localize(ZoneInfo(tz), nonexistent="shift_forward",
                               ambiguous=True)
                .tz_convert("UTC").tz_localize(None))
    except Exception:
        return ts


def _stamps(col: pd.Series) -> pd.Series:
    """Order timestamps, always at nanosecond precision.

    Pandas returns microsecond precision for some inputs. Two timestamp
    columns of different precision refuse to merge, and the error names a
    dtype rather than the data, so it is pinned once here and every caller
    uses it.
    """
    return (pd.to_datetime(col, utc=True, format="mixed")
            .dt.tz_localize(None).astype("datetime64[ns]"))


def _parse_dates(col: pd.Series) -> pd.Series:
    """Read cost log dates without ever guessing the wrong way round.

    The workbook is maintained in a day-first locale, so 03/08/2026 is the
    third of August. Pandas defaults to month-first and silently moved every
    cost five months earlier, which made a current log look 152 days stale.

    ISO dates are handled first and separately, because dayfirst would read
    2026-08-03 as the eighth of March. Everything else is day-first.
    """
    raw = col.astype(str).str.strip()
    iso = raw.str.match(r"^\d{4}-\d{2}-\d{2}")
    out = pd.Series(pd.NaT, index=col.index, dtype="datetime64[ns]")
    if iso.any():
        out[iso] = pd.to_datetime(raw[iso], errors="coerce", format="mixed")
    if (~iso).any():
        out[~iso] = pd.to_datetime(raw[~iso], errors="coerce",
                                   format="mixed", dayfirst=True)
    return out


def normalise_cost_log(cost_log: pd.DataFrame | None) -> pd.DataFrame:
    """The dated cost history. Append-only by design.

    Each row states that from valid_from onwards, this product in this market
    costs this much. Nothing is ever overwritten, so the history stays intact
    and a past month keeps reporting the cost that actually applied at the
    time rather than today's.
    """
    cols = ["product", "market", "valid_from", "cogs_unit_lc"]
    if cost_log is None or len(cost_log) == 0:
        return pd.DataFrame(columns=cols)

    df = cost_log.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    name = ("store_product_name" if "store_product_name" in df.columns
            else "product" if "product" in df.columns else None)
    if name is None or "valid_from" not in df.columns:
        raise ActualsError("Cost_Log needs store_product_name, market, "
                           "valid_from and cogs_unit_lc")
    cost = ("cogs_unit_lc" if "cogs_unit_lc" in df.columns
            else "cost_unit_lc" if "cost_unit_lc" in df.columns else None)
    if cost is None:
        raise ActualsError("Cost_Log needs a cogs_unit_lc column")

    out = pd.DataFrame({
        "product": df[name].map(lambda v: str(v).strip()),
        "market": df["market"].map(lambda v: str(v).strip()),
        # dayfirst because the workbook is maintained in a day-first locale:
        # 03/08/2026 is the third of August. Pandas defaults to month-first,
        # which silently moved every cost five months earlier and made a
        # current log look 152 days stale.
        #
        # format="mixed" because a log legitimately holds both a bare date and
        # a date with a time, and pandas otherwise infers one format for the
        # whole column and discards the rest.
        "valid_from": _parse_dates(df["valid_from"]),
        "cogs_unit_lc": pd.to_numeric(df[cost], errors="coerce"),
    })

    # valid_from is typed in local time. Orders are timestamped in UTC, so the
    # two are reconciled here rather than leaving a silent few-hour offset
    # around any same-day cost change.
    zones = (df["timezone"].map(lambda v: str(v).strip())
             if "timezone" in df.columns
             else pd.Series([""] * len(df), index=df.index))
    out["timezone"] = [
        MARKET_TZ.get(z if z and z.lower() not in ("", "nan") else m, z or "UTC")
        if (z or "").upper() != "UTC" else "UTC"
        for z, m in zip(zones, out["market"])]
    # A bare date means the start of that day, and a cost that starts on the
    # third of August starts on the third — not at eight in the evening on the
    # second, which is what converting local midnight to UTC produces. Only
    # entries that actually carry a time are converted.
    has_time = (out["valid_from"].dt.hour.fillna(0).ne(0)
                | out["valid_from"].dt.minute.fillna(0).ne(0))
    # Rebuilt as a Series with an explicit dtype: a list comprehension over
    # Timestamps can come back as microsecond precision, which then refuses
    # to merge against the nanosecond timestamps everywhere else.
    out["valid_from"] = pd.Series(
        [_to_utc_naive(ts, tz) if t else ts
         for ts, tz, t in zip(out["valid_from"], out["timezone"], has_time)],
        index=out.index).astype("datetime64[ns]")
    # A row with no product name is not a data row: a spacer, a stray note,
    # or an empty line left behind. Those are dropped. A row that names a
    # product but has no readable date or cost is a genuine mistake and is
    # reported rather than skipped.
    named = out["product"].fillna("").str.strip().replace({"nan": ""}).ne("")
    out = out[named].copy()
    bad = out[out["valid_from"].isna() | out["cogs_unit_lc"].isna()]
    if len(bad):
        rows = bad[["product", "market"]].to_dict("records")
        raise ActualsError(
            f"{len(bad)} Cost_Log rows name a product but have an unreadable "
            f"date or cost: {rows[:4]}")
    if out.empty:
        return pd.DataFrame(columns=cols)
    # Two entries on the same day for the same product are ambiguous, so the
    # later-entered one wins and the duplicate is dropped rather than averaged.
    out = out.sort_values(["product", "market", "valid_from"])
    out = out.drop_duplicates(["product", "market", "valid_from"], keep="last")
    return out.reset_index(drop=True)


def apply_dated_cost(lines: pd.DataFrame, cost_log: pd.DataFrame,
                     plan: pd.DataFrame | None = None) -> pd.DataFrame:
    """Attach to each line the unit cost in effect on the day it was sold.

    A line sold before the first Cost_Log entry for its product falls back to
    the planned cost and is flagged, so the gap is visible rather than
    silently filled.
    """
    d = lines.copy()
    # Pinned to nanoseconds so it can merge against the cost log. Pandas
    # returns microsecond precision for some inputs, and merge_asof refuses
    # to join two timestamp columns of different precision.
    d["_ts"] = _stamps(d["processed_at"])
    cl = normalise_cost_log(cost_log)

    d["unit_cost_dated"] = pd.NA
    if len(cl):
        parts = []
        for (prod, mkt), grp in cl.groupby(["product", "market"], sort=False):
            sub = d[(d["product"] == prod) & (d["market"] == mkt)]
            if sub.empty:
                continue
            merged = pd.merge_asof(
                sub.sort_values("_ts"),
                grp.sort_values("valid_from")[["valid_from", "cogs_unit_lc"]],
                left_on="_ts", right_on="valid_from", direction="backward")
            merged.index = sub.sort_values("_ts").index
            parts.append(merged["cogs_unit_lc"])
        if parts:
            d.loc[:, "unit_cost_dated"] = pd.concat(parts).reindex(d.index)

    d["cost_source"] = "dated"
    missing = d["unit_cost_dated"].isna()
    if plan is not None and missing.any():
        d["_month"] = d["_ts"].dt.month.map(lambda n: MONTHS[n - 1])
        pc = (plan.drop_duplicates(["product", "market", "month"])
              .set_index(["product", "market", "month"])["plan_cogs_unit_lc"])
        idx = pd.MultiIndex.from_arrays([d["product"], d["market"], d["_month"]])
        fallback = pd.Series(pc.reindex(idx).to_numpy(), index=d.index)
        d.loc[missing, "unit_cost_dated"] = fallback[missing]
        d.loc[missing, "cost_source"] = "plan cost, no dated entry"
        d = d.drop(columns=["_month"])
    d.loc[d["unit_cost_dated"].isna(), "cost_source"] = "none"
    return d.drop(columns=["_ts"])


def cost_coverage(lines: pd.DataFrame, cost_log: pd.DataFrame,
                  plan: pd.DataFrame | None = None,
                  year: int = 2026) -> pd.DataFrame:
    """How much revenue is costed from the log versus falling back."""
    d = apply_dated_cost(lines, cost_log, plan)
    d["ts"] = _stamps(d["processed_at"])
    d = d[(d["ts"].dt.year == year) & (~d["cancelled"])
          & (~d["financial_status"].isin(DEAD_STATUSES)) & (d["qty_current"] > 0)]
    if d.empty:
        return pd.DataFrame(columns=["market", "cost_source"])
    g = d.groupby(["market", "cost_source"], observed=True).agg(
        units=("qty_current", "sum"),
        revenue_lc=("net_line_lc", "sum"),
        products=("product", "nunique")).reset_index()
    tot = g.groupby("market")["revenue_lc"].transform("sum")
    g["share"] = g["revenue_lc"] / tot
    return g.sort_values(["market", "revenue_lc"], ascending=[True, False])


def from_line_items(lines: pd.DataFrame, year: int = 2026,
                    cost_log: pd.DataFrame | None = None,
                    plan: pd.DataFrame | None = None) -> pd.DataFrame:
    """Roll Shopify line items up to product x market x month.

    Cancelled orders and dead financial statuses are dropped, not zeroed:
    they were never revenue. Everything else is counted on current
    quantities, so removals and partial refunds fall out on their own.

    Three confidence tiers are carried alongside the totals:
      Confirmed  delivered and paid
      Committed  delivered, cash not yet reconciled (normal for COD)
      Potential  not yet delivered, customer can still change their mind
    """
    df = lines.copy()
    df["processed_at"] = _stamps(df["processed_at"])
    df = df[df["processed_at"].dt.year == year]
    df = df[~df["cancelled"]]
    df = df[~df["financial_status"].isin(DEAD_STATUSES)]
    df = df[df["qty_current"] > 0]
    df = df[~df["product"].isin(NOT_PRODUCTS)]
    if df.empty:
        return pd.DataFrame(columns=["product", "market", "month", "year"])

    df["month"] = df["processed_at"].dt.month.map(lambda n: MONTHS[n - 1])
    df["year"] = df["processed_at"].dt.year

    # Current quantity can be lower than ordered. Scale the money with it so
    # a partially refunded line contributes only what the customer kept.
    ratio = (df["qty_current"] / df["qty_ordered"]).where(
        df["qty_ordered"].ne(0), 1.0).clip(upper=1.0)
    df["act_gross_lc"] = df["gross_lc"] * ratio
    df["act_net_lc"] = df["net_line_lc"] * ratio
    # Line-level and order-level discounts both belong in the discount
    # figure. The order-level part was allocated across lines when the data
    # was read, so it is already reflected in net; this keeps the reported
    # discount consistent with that.
    df["act_discounts_lc"] = (df["act_gross_lc"] - df["act_net_lc"]).clip(lower=0)

    # Cost in effect on the day of sale, applied per line so a mid-month
    # change splits the month correctly instead of averaging it away.
    if cost_log is not None and len(cost_log):
        costed = apply_dated_cost(df, cost_log, plan)
        df["unit_cost_dated"] = pd.to_numeric(costed["unit_cost_dated"],
                                              errors="coerce")
        df["cost_source"] = costed["cost_source"]
        df["act_cogs_dated_lc"] = df["qty_current"] * df["unit_cost_dated"]
        df["act_cm_dated_lc"] = df["act_net_lc"] - df["act_cogs_dated_lc"]
    else:
        df["act_cogs_dated_lc"] = pd.NA
        df["act_cm_dated_lc"] = pd.NA

    delivered = df["fulfillment_status"].eq("FULFILLED")
    paid = df["financial_status"].isin(CONFIRMED)
    df["tier"] = "Potential"
    df.loc[delivered, "tier"] = "Committed"
    df.loc[delivered & paid, "tier"] = "Confirmed"

    keys = ["product", "market", "month", "year"]
    agg = dict(act_units=("qty_current", "sum"),
               act_gross_lc=("act_gross_lc", "sum"),
               act_discounts_lc=("act_discounts_lc", "sum"),
               act_net_lc=("act_net_lc", "sum"),
               orders=("order", "nunique"))
    if df["act_cogs_dated_lc"].notna().any():
        agg["act_cogs_dated_lc"] = ("act_cogs_dated_lc", "sum")
        agg["act_cm_dated_lc"] = ("act_cm_dated_lc", "sum")
    g = df.groupby(keys, observed=True).agg(**agg).reset_index()

    tiers = (df.pivot_table(index=keys, columns="tier", values="act_net_lc",
                            aggfunc="sum", observed=True)
             .reset_index())
    for t in ("Confirmed", "Committed", "Potential"):
        if t not in tiers.columns:
            tiers[t] = 0.0
    tiers = tiers.rename(columns={"Confirmed": "net_confirmed_lc",
                                  "Committed": "net_committed_lc",
                                  "Potential": "net_potential_lc"})
    out = g.merge(tiers, on=keys, how="left").fillna(
        {"net_confirmed_lc": 0.0, "net_committed_lc": 0.0,
         "net_potential_lc": 0.0})

    # Returns are not represented at line level by this route. Cancelled and
    # refunded orders are excluded outright instead, which is the same answer
    # arrived at more honestly.
    out["act_returns_lc"] = 0.0
    out["act_price_lc"] = (out["act_net_lc"] / out["act_units"]).where(
        out["act_units"].ne(0))
    return out


# The plan sheet names two things. store_product_name is what Shopify calls
# the product and is the join key, because that is the only string the two
# sides share. inhouse_product_name is the label the business uses and is
# display only, so a store rename never breaks the join or the reporting.
STORE_COL = "store_product_name"
INHOUSE_COL = "inhouse_product_name"


def apply_naming(plan: pd.DataFrame) -> pd.DataFrame:
    """Accept either the new two-column naming or the old single 'product'.

    Older workbooks carry one 'product' column. Newer ones carry
    store_product_name and inhouse_product_name. Both are normalised to an
    internal 'product' (the join key) plus 'product_label' (for display).
    """
    df = plan.copy()
    df.columns = [str(c).strip() for c in df.columns]
    low = {c.lower(): c for c in df.columns}

    store = low.get(STORE_COL)
    house = low.get(INHOUSE_COL)

    if store:
        df["product"] = df[store].map(lambda v: str(v).strip())
    elif "product" not in df.columns:
        raise ActualsError(
            f"the plan needs either a '{STORE_COL}' column or a 'product' one")

    if house:
        lbl = df[house].map(lambda v: str(v).strip() if pd.notna(v) else "")
        df["product_label"] = lbl.where(lbl.ne(""), df["product"])
    else:
        df["product_label"] = df["product"]
    return df


def _tokens(name: str) -> frozenset:
    return frozenset(str(name).lower().replace("/", " ").split())


def resolve_products(actuals: pd.DataFrame, plan: pd.DataFrame,
                     aliases: pd.DataFrame | None = None
                     ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Match store product names onto plan product names.

    The stores do not agree with each other on word order. The plan says
    "Peach Baladi"; the UAE catalogue says "Baladi Peach"; a migrated
    WooCommerce line says "Baladi Peach" too. Same fruit, three spellings.

    Matching is deliberately conservative: exact name first, then the same
    set of words in any order, and only when that set maps to exactly one
    plan product. Anything ambiguous is left alone and surfaces as an
    exception rather than being guessed at.

    Returns (actuals with names resolved, a table of what was remapped).
    """
    known = set(plan["product"].dropna().unique())
    by_tokens: dict[frozenset, set[str]] = {}
    for name in known:
        by_tokens.setdefault(_tokens(name), set()).add(name)

    # Manual aliases win. They are the escape hatch for names that share no
    # words with the plan, such as a store calling Keshta "Custard Apple".
    manual: dict[str, str] = {}
    if aliases is not None and len(aliases):
        al = aliases.copy()
        al.columns = [str(c).strip().lower().replace(" ", "_")
                      for c in al.columns]
        if {"store_name", "plan_name"} <= set(al.columns):
            for r in al.dropna(subset=["store_name", "plan_name"]).itertuples():
                manual[str(r.store_name).strip()] = str(r.plan_name).strip()

    mapping: dict[str, str] = {}
    for name in actuals["product"].dropna().unique():
        if name in known:
            continue
        if name in manual:
            mapping[name] = manual[name]
            continue
        cands = by_tokens.get(_tokens(name), set())
        if len(cands) == 1:
            mapping[name] = next(iter(cands))

    out = actuals.copy()
    if mapping:
        out["product"] = out["product"].replace(mapping)
        keys = [c for c in ("product", "market", "month", "year")
                if c in out.columns]
        sums = {c: "sum" for c in out.columns
                if c not in keys and pd.api.types.is_numeric_dtype(out[c])}
        if sums:
            out = out.groupby(keys, observed=True).agg(sums).reset_index()
            if "act_units" in out.columns and "act_net_lc" in out.columns:
                out["act_price_lc"] = (out["act_net_lc"] / out["act_units"]
                                       ).where(out["act_units"].ne(0))

    report = pd.DataFrame(
        [{"store name": k, "plan name": v} for k, v in sorted(mapping.items())])
    return out, report


def unmatched_products(actuals: pd.DataFrame, plan: pd.DataFrame,
                       aliases: pd.DataFrame | None = None) -> pd.DataFrame:
    """Store product names that still do not reach a plan product.

    Each one means sales going unattributed and a plan row looking unsold.
    Fill them into the Aliases sheet of the plan workbook to close the gap.
    """
    res, _ = resolve_products(actuals, plan, aliases)
    known = set(plan["product"].dropna().unique())
    left = res[~res["product"].isin(known)]
    if left.empty:
        return pd.DataFrame(columns=["product", "markets", "units", "revenue"])
    g = left.groupby("product", observed=True).agg(
        markets=("market", lambda s: ", ".join(sorted(set(s)))),
        units=("act_units", "sum"),
        revenue=("act_net_lc", "sum")).reset_index()
    return g.sort_values("revenue", ascending=False).reset_index(drop=True)


def combine(plan: pd.DataFrame, actuals: pd.DataFrame,
            year: int = 2026, aliases: pd.DataFrame | None = None
            ) -> pd.DataFrame:
    """Plan and actual side by side, at product x market x month.

    An outer join on purpose. A product planned and not sold, and a product
    sold and not planned, are both real findings and both need to survive.
    """
    a = actuals[actuals["year"] == year] if "year" in actuals.columns else actuals
    a, _remap = resolve_products(a, plan, aliases)
    keys = ["product", "market", "month"]

    cols = keys + ["category", "plan_units", "plan_price_lc",
                   "plan_cogs_unit_lc", "plan_revenue_lc", "plan_cogs_lc",
                   "plan_cm_lc"]
    if "product_label" in plan.columns:
        cols.append("product_label")
    p = plan[cols].copy()
    cols = [c for c in a.columns if c.startswith("act_") or c == "return_rate"]
    out = p.merge(a[keys + cols], on=keys, how="outer", indicator="presence")

    out["presence"] = out["presence"].map({
        "both": "planned and sold",
        "left_only": "planned, not sold",
        "right_only": "sold, not planned",
    })
    for c in ("plan_units", "plan_revenue_lc", "plan_cogs_lc", "plan_cm_lc"):
        out[c] = out[c].fillna(0.0)
    for c in cols:
        if c != "return_rate":
            out[c] = out[c].fillna(0.0)

    out["category"] = out["category"].fillna("(unassigned)")
    # A product sold but never planned has no in-house label, so it falls back
    # to whatever the store calls it rather than going blank.
    if "product_label" in out.columns:
        out["product_label"] = out["product_label"].fillna(out["product"])
    else:
        out["product_label"] = out["product"]
    out["month"] = pd.Categorical(out["month"], categories=MONTHS, ordered=True)

    # CM at plan cost: actual units priced at planned unit cost. Keeps cost
    # movement out of a commercial measure.
    out["act_cogs_at_plan_lc"] = out["act_units"] * out["plan_cogs_unit_lc"].fillna(0)
    out["act_cm_at_plan_lc"] = out["act_net_lc"] - out["act_cogs_at_plan_lc"]

    out["var_units"] = out["act_units"] - out["plan_units"]
    out["var_revenue_lc"] = out["act_net_lc"] - out["plan_revenue_lc"]
    out["var_cm_lc"] = out["act_cm_at_plan_lc"] - out["plan_cm_lc"]

    # Markets sell in four currencies, so nothing consolidates without a rate.
    # The rate comes from the plan workbook, keyed on market and month, and is
    # applied to actuals as well as plan. A row sold but never planned still
    # gets its market's rate rather than being silently dropped.
    if "fx_to_aed" in plan.columns:
        fx = (plan.drop_duplicates(["market", "month"])
              .set_index(["market", "month"])["fx_to_aed"])
        idx = pd.MultiIndex.from_arrays([out["market"], out["month"]])
        out["fx_to_aed"] = pd.Series(fx.reindex(idx).to_numpy(), index=out.index)
        out["fx_to_aed"] = out.groupby("market")["fx_to_aed"].transform(
            lambda s: s.fillna(s.dropna().iloc[0] if s.notna().any() else 1.0))
        out["fx_to_aed"] = out["fx_to_aed"].fillna(1.0)
    else:
        out["fx_to_aed"] = 1.0

    for lc, aed in (("plan_revenue_lc", "plan_revenue_aed"),
                    ("plan_cogs_lc", "plan_cogs_aed"),
                    ("plan_cm_lc", "plan_cm_aed"),
                    ("act_gross_lc", "act_gross_aed"),
                    ("act_net_lc", "act_net_aed"),
                    ("act_cm_at_plan_lc", "act_cm_at_plan_aed"),
                    ("var_revenue_lc", "var_revenue_aed"),
                    ("var_cm_lc", "var_cm_aed")):
        if lc in out.columns:
            out[aed] = out[lc] * out["fx_to_aed"]
    return out.sort_values(["market", "month", "product"]).reset_index(drop=True)


def bridge(combined: pd.DataFrame, **filters) -> dict:
    """Split the revenue gap into volume, price and mix.

    volume  (actual units - plan units) x plan price
    price   (actual price - plan price) x actual units
    mix     the remainder: same units, different products, different prices

    Volume and price are computed per row, so mix falls out as the residual
    rather than being estimated. The three always sum to the total gap.
    """
    df = combined
    for col, val in filters.items():
        if val is None:
            continue
        wanted = [val] if isinstance(val, str) else list(val)
        if wanted:
            df = df[df[col].isin(wanted)]
    if df.empty:
        return {k: 0.0 for k in
                ("plan", "actual", "gap", "volume", "price", "mix")}

    pp = df["plan_price_lc"].fillna(0)
    ap = df["act_price_lc"].fillna(0)
    has_both = (df["plan_units"] > 0) & (df["act_units"] > 0)

    volume = ((df["act_units"] - df["plan_units"]) * pp).where(has_both, 0).sum()
    price = ((ap - pp) * df["act_units"]).where(has_both, 0).sum()

    plan_total = df["plan_revenue_lc"].sum()
    act_total = df["act_net_lc"].sum()
    gap = act_total - plan_total
    return {
        "plan": plan_total,
        "actual": act_total,
        "gap": gap,
        "volume": volume,
        "price": price,
        "mix": gap - volume - price,
    }


ADDITIVE = [
    "act_cogs_dated_lc", "act_cm_dated_lc",
    "net_confirmed_lc", "net_committed_lc", "net_potential_lc",
    "plan_units", "plan_revenue_lc", "plan_cogs_lc", "plan_cm_lc",
    "act_units", "act_gross_lc", "act_discounts_lc", "act_returns_lc",
    "act_net_lc", "act_cogs_at_plan_lc", "act_cm_at_plan_lc",
    "var_units", "var_revenue_lc", "var_cm_lc",
    "plan_revenue_aed", "plan_cogs_aed", "plan_cm_aed",
    "act_gross_aed", "act_net_aed", "act_cm_at_plan_aed",
    "var_revenue_aed", "var_cm_aed",
]


def _ratios(df: pd.DataFrame) -> pd.DataFrame:
    """Every ratio from summed numerators and denominators."""
    out = df.copy()
    pu, pr = out["plan_units"], out["plan_revenue_lc"]
    au, ar = out["act_units"], out["act_net_lc"]

    out["unit_attainment"] = (au / pu).where(pu.ne(0))
    out["revenue_attainment"] = (ar / pr).where(pr.ne(0))
    out["plan_cm_pct"] = (out["plan_cm_lc"] / pr).where(pr.ne(0))
    out["act_cm_pct"] = (out["act_cm_at_plan_lc"] / ar).where(ar.ne(0))
    out["plan_wavg_price"] = (pr / pu).where(pu.ne(0))
    out["act_wavg_price"] = (ar / au).where(au.ne(0))
    if "act_cm_dated_lc" in out.columns:
        out["act_cm_dated_pct"] = (out["act_cm_dated_lc"] / ar).where(ar.ne(0))
        out["dated_vs_plan_cost"] = (out["act_cm_dated_lc"]
                                     - out["act_cm_at_plan_lc"])
    out["return_rate"] = (out["act_returns_lc"] / out["act_gross_lc"]).where(
        out["act_gross_lc"].ne(0))
    out["discount_rate"] = (out["act_discounts_lc"] / out["act_gross_lc"]).where(
        out["act_gross_lc"].ne(0))

    # The same ratios on the consolidated basis. For a single market these are
    # identical to the local ones; across markets only these are meaningful.
    if "act_net_aed" in out.columns:
        pra, ara = out["plan_revenue_aed"], out["act_net_aed"]
        out["revenue_attainment_aed"] = (ara / pra).where(pra.ne(0))
        out["plan_cm_pct_aed"] = (out["plan_cm_aed"] / pra).where(pra.ne(0))
        out["act_cm_pct_aed"] = (out["act_cm_at_plan_aed"] / ara).where(ara.ne(0))
    return out


def rollup(combined: pd.DataFrame, by: list[str], **filters) -> pd.DataFrame:
    """Aggregate to any level, then recompute every ratio."""
    df = combined
    for col, val in filters.items():
        if val is None:
            continue
        wanted = [val] if isinstance(val, str) else list(val)
        if wanted:
            df = df[df[col].isin(wanted)]
    if df.empty:
        # An empty rollup still has to carry the derived columns, or every
        # caller that reads a ratio has to guard for their absence.
        return pd.DataFrame(columns=list(by) + ADDITIVE + [
            "unit_attainment", "revenue_attainment", "plan_cm_pct",
            "act_cm_pct", "plan_wavg_price", "act_wavg_price", "return_rate",
            "discount_rate", "revenue_attainment_aed", "plan_cm_pct_aed",
            "act_cm_pct_aed", "act_cm_dated_pct", "dated_vs_plan_cost"])

    cols = [c for c in ADDITIVE if c in df.columns]
    g = df.groupby(list(by), observed=True)[cols].sum().reset_index()
    if "month" in by:
        g["month"] = pd.Categorical(g["month"], categories=MONTHS, ordered=True)
        g = g.sort_values(list(by))
    return _ratios(g).reset_index(drop=True)


def market_month(combined: pd.DataFrame, **filters) -> pd.DataFrame:
    return rollup(combined, ["market", "month"], **filters)


def by_product(combined: pd.DataFrame, **filters) -> pd.DataFrame:
    by = ["market", "category", "product"]
    if "product_label" in combined.columns:
        by.append("product_label")
    return rollup(combined, by, **filters)


def exceptions(combined: pd.DataFrame) -> pd.DataFrame:
    """Rows that need a human: planned and not sold, or sold and not planned."""
    e = combined[combined["presence"] != "planned and sold"]
    keep = ["market", "month", "category", "product", "product_label",
            "presence", "plan_units", "act_units", "plan_revenue_lc",
            "act_net_lc"]
    return e[[c for c in keep if c in e.columns]].reset_index(drop=True)


# ------------------------------------------------- commercial diagnostics


def order_quality(lines: pd.DataFrame, plan: pd.DataFrame | None = None,
                  year: int = 2026) -> pd.DataFrame:
    """Per market per month: how many orders survived to become revenue.

    A cancellation is not a revenue miss, it is a write-off. On air-freight
    make-to-order the fruit was already procured and flown, so the cost is
    real even though the sale never happened. Valued at planned unit cost,
    which is the only cost basis tracked reliably.
    """
    d = lines.copy()
    d["processed_at"] = _stamps(d["processed_at"])
    d = d[d["processed_at"].dt.year == year]
    if d.empty:
        return pd.DataFrame(columns=["market", "month"])
    d["month"] = d["processed_at"].dt.month.map(lambda n: MONTHS[n - 1])

    d["lost"] = d["cancelled"] | d["financial_status"].isin(DEAD_STATUSES)
    if plan is not None:
        cost = (plan.drop_duplicates(["product", "market", "month"])
                .set_index(["product", "market", "month"])["plan_cogs_unit_lc"])
        idx = pd.MultiIndex.from_arrays(
            [d["product"], d["market"], d["month"]])
        d["unit_cost"] = cost.reindex(idx).to_numpy()
    else:
        d["unit_cost"] = 0.0
    d["unit_cost"] = d["unit_cost"].fillna(0.0)

    lost = d[d["lost"]]
    g = d.groupby(["market", "month"], observed=True).agg(
        orders=("order", "nunique"),
        units_ordered=("qty_ordered", "sum"),
    ).reset_index()
    l = lost.groupby(["market", "month"], observed=True).agg(
        orders_lost=("order", "nunique"),
        units_lost=("qty_ordered", "sum"),
        value_lost_lc=("gross_lc", "sum"),
    ).reset_index()
    l["cost_lost_lc"] = (lost["qty_ordered"] * lost["unit_cost"]).groupby(
        [lost["market"], lost["month"]], observed=True).sum().to_numpy() \
        if len(lost) else 0.0

    out = g.merge(l, on=["market", "month"], how="left").fillna(0.0)
    out["cancel_rate"] = (out["orders_lost"] / out["orders"]).where(
        out["orders"].ne(0))
    out["month"] = pd.Categorical(out["month"], categories=MONTHS, ordered=True)
    return out.sort_values(["market", "month"]).reset_index(drop=True)


def concentration(combined: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """How much of the revenue rests on one product.

    A high attainment number can still hide a fragile portfolio: one variety
    carrying half the month is one bad season away from a hole.
    """
    by = by or ["market", "month"]
    d = combined[combined["act_net_lc"] > 0]
    if d.empty:
        return pd.DataFrame(columns=by + ["top1_share", "top3_share"])

    rows = []
    for key, grp in d.groupby(by, observed=True):
        s = grp.groupby("product", observed=True)["act_net_lc"].sum().sort_values(
            ascending=False)
        tot = s.sum()
        rows.append(dict(zip(by, key if isinstance(key, tuple) else (key,))) | {
            "revenue_lc": tot,
            "products": len(s),
            "top1_product": s.index[0],
            "top1_share": s.iloc[0] / tot if tot else None,
            "top3_share": s.head(3).sum() / tot if tot else None,
        })
    out = pd.DataFrame(rows)
    if "month" in by:
        out["month"] = pd.Categorical(out["month"], categories=MONTHS, ordered=True)
        out = out.sort_values(by)
    return out.reset_index(drop=True)


def cm_per_box(combined: pd.DataFrame, **filters) -> pd.DataFrame:
    """Contribution margin per box, ranked.

    When freight capacity is the binding constraint, the right question is
    not which product has the best margin percentage but which earns the
    most per box shipped.
    """
    d = by_product(combined, **filters)
    if d.empty:
        return d
    d = d[d["act_units"] > 0].copy()
    d["cm_per_box"] = d["act_cm_at_plan_lc"] / d["act_units"]
    d["cm_share"] = d["act_cm_at_plan_lc"] / d["act_cm_at_plan_lc"].sum()
    d["price_realisation"] = (d["act_wavg_price"] / d["plan_wavg_price"]).where(
        d["plan_wavg_price"].gt(0))
    return d.sort_values("act_cm_at_plan_lc", ascending=False).reset_index(drop=True)


def landing(combined: pd.DataFrame, market: str, month: str,
            as_of: "date", year: int = 2026) -> dict:
    """Where the month ends if the current run rate holds.

    Attainment mid-month is meaningless on its own: 50% on the 15th is on
    track, 50% on the 30th is a miss. This projects forward on elapsed days
    so the two can be told apart.
    """
    from datetime import date as _date
    import calendar as _cal

    sub = combined[(combined["market"] == market) & (combined["month"] == month)]
    plan_total = sub["plan_revenue_lc"].sum()
    actual = sub["act_net_lc"].sum()

    n = MONTHS.index(month) + 1
    days = _cal.monthrange(year, n)[1]
    if as_of.year > year or (as_of.year == year and as_of.month > n):
        elapsed = days
    elif as_of.year < year or (as_of.year == year and as_of.month < n):
        elapsed = 0
    else:
        elapsed = min(as_of.day, days)

    paced = plan_total * elapsed / days if days else 0.0
    projected = actual * days / elapsed if elapsed else None
    return {
        "plan": plan_total,
        "actual": actual,
        "paced_plan": paced,
        "days_elapsed": elapsed,
        "days_total": days,
        "projected": projected,
        "vs_paced": (actual / paced) if paced else None,
        "projected_attainment": (projected / plan_total)
        if (projected is not None and plan_total) else None,
    }


def narrative(combined: pd.DataFrame, market: str, month: str) -> str:
    """One sentence a manager can act on.

    Deliberately blunt. It names the winning group, the losing group, and
    whether the gap was breadth or demand, because those have different
    owners.
    """
    sub = combined[(combined["market"] == market) & (combined["month"] == month)]
    sub = sub[(sub["plan_units"] > 0) | (sub["act_units"] > 0)]
    if sub.empty:
        return f"No plan and no sales for {market} in {month}."

    b = bridge(sub)
    att = (b["actual"] / b["plan"]) if b["plan"] else None
    cats = (sub.groupby("category", observed=True)[["plan_units", "act_units"]]
            .sum())
    cats = cats[cats["plan_units"] > 0]
    if cats.empty:
        return (f"{market} {month}: everything sold was outside the plan, "
                f"{b['actual']:,.0f} of unplanned revenue.")
    cats["att"] = cats["act_units"] / cats["plan_units"]
    cats["weight"] = cats["plan_units"] / cats["plan_units"].sum()

    best = cats.sort_values("weight", ascending=False)
    lead = best.index[0]
    lead_att = best.iloc[0]["att"]
    rest = cats.drop(index=lead)
    rest_att = (rest["act_units"].sum() / rest["plan_units"].sum()
                if len(rest) and rest["plan_units"].sum() else None)

    conc = concentration(sub, by=["market"])
    top = conc.iloc[0] if len(conc) else None

    parts = []
    if att is not None:
        parts.append(f"{market} {month} landed at {att:.0%} of revenue plan.")
    if rest_att is not None and lead_att - rest_att > 0.15:
        parts.append(f"{lead} delivered {lead_att:.0%} while everything else "
                     f"managed {rest_att:.0%} — the month missed on breadth, "
                     f"not demand.")
    elif rest_att is not None and rest_att - lead_att > 0.15:
        parts.append(f"{lead} delivered only {lead_att:.0%} against "
                     f"{rest_att:.0%} elsewhere, so the shortfall sits in the "
                     f"largest category.")
    else:
        drivers = {"volume": b["volume"], "price": b["price"], "mix": b["mix"]}
        worst = min(drivers, key=drivers.get)
        parts.append(f"The gap is mostly {worst} "
                     f"({drivers[worst]:+,.0f}).")
    if top is not None and top["top1_share"] and top["top1_share"] > 0.3:
        parts.append(f"{top['top1_share']:.0%} of revenue rests on "
                     f"{top['top1_product']}.")
    return " ".join(parts)


SEGMENTS = {
    "city": "City",
    "channel": "Channel",
    "customer_type": "Customer",
}


def by_segment(lines: pd.DataFrame, dim: str, plan: pd.DataFrame | None = None,
               year: int = 2026, market: str | None = None,
               month: str | None = None) -> pd.DataFrame:
    """Revenue, orders and margin split by city, channel or customer type.

    These dimensions live on the order, not the line, so they cannot be
    derived from the plan. They answer a different question: not whether the
    plan was met, but where the demand actually came from.

    Margin is at planned unit cost, the only cost basis tracked reliably.
    """
    if dim not in SEGMENTS:
        raise ActualsError(f"unknown segment {dim!r}")

    d = lines.copy()
    d["processed_at"] = _stamps(d["processed_at"])
    d = d[(d["processed_at"].dt.year == year) & (~d["cancelled"])
          & (~d["financial_status"].isin(DEAD_STATUSES))
          & (d["qty_current"] > 0)]
    if d.empty:
        return pd.DataFrame(columns=[dim])
    d["month"] = d["processed_at"].dt.month.map(lambda n: MONTHS[n - 1])
    if market:
        d = d[d["market"] == market]
    if month:
        d = d[d["month"] == month]
    if d.empty or dim not in d.columns:
        return pd.DataFrame(columns=[dim])

    ratio = (d["qty_current"] / d["qty_ordered"]).where(
        d["qty_ordered"].ne(0), 1.0).clip(upper=1.0)
    d["net_lc"] = d["net_line_lc"] * ratio

    if plan is not None:
        cost = (plan.drop_duplicates(["product", "market", "month"])
                .set_index(["product", "market", "month"])["plan_cogs_unit_lc"])
        idx = pd.MultiIndex.from_arrays([d["product"], d["market"], d["month"]])
        d["unit_cost"] = pd.Series(cost.reindex(idx).to_numpy(),
                                   index=d.index).fillna(0.0)
    else:
        d["unit_cost"] = 0.0
    d["cm_lc"] = d["net_lc"] - d["qty_current"] * d["unit_cost"]

    g = d.groupby(dim, observed=True).agg(
        orders=("order", "nunique"),
        units=("qty_current", "sum"),
        revenue_lc=("net_lc", "sum"),
        cm_lc=("cm_lc", "sum"),
        products=("product", "nunique"),
    ).reset_index()
    g["cm_pct"] = (g["cm_lc"] / g["revenue_lc"]).where(g["revenue_lc"].ne(0))
    g["aov_lc"] = (g["revenue_lc"] / g["orders"]).where(g["orders"].ne(0))
    g["units_per_order"] = (g["units"] / g["orders"]).where(g["orders"].ne(0))
    g["revenue_share"] = g["revenue_lc"] / g["revenue_lc"].sum()
    return g.sort_values("revenue_lc", ascending=False).reset_index(drop=True)


def order_count(lines: pd.DataFrame, year: int = 2026, market: str | None = None,
                month: str | None = None) -> int:
    """Billable orders. Cancelled and dead-status orders never count."""
    d = lines.copy()
    d["processed_at"] = _stamps(d["processed_at"])
    d = d[(d["processed_at"].dt.year == year) & (~d["cancelled"])
          & (~d["financial_status"].isin(DEAD_STATUSES))
          & (d["qty_current"] > 0)]
    if d.empty:
        return 0
    d["month"] = d["processed_at"].dt.month.map(lambda n: MONTHS[n - 1])
    if market:
        d = d[d["market"] == market]
    if month:
        d = d[d["month"] == month]
    return int(d["order"].nunique())


# ------------------------------------------------------- analyst layer


def traffic_basket(lines: pd.DataFrame, combined: pd.DataFrame,
                   year: int = 2026, market: str | None = None,
                   month: str | None = None) -> dict:
    """Split a unit shortfall into fewer orders versus smaller baskets.

    The plan holds units, not order counts, so an implied plan order count is
    derived from planned units at the achieved basket size. That makes the
    question answerable: did we lose customers, or did the customers we kept
    buy less? Those have different owners — marketing versus merchandising.
    """
    d = lines.copy()
    d["processed_at"] = _stamps(d["processed_at"])
    d = d[(d["processed_at"].dt.year == year) & (~d["cancelled"])
          & (~d["financial_status"].isin(DEAD_STATUSES)) & (d["qty_current"] > 0)]
    if d.empty:
        return {}
    d["month"] = d["processed_at"].dt.month.map(lambda n: MONTHS[n - 1])
    if market:
        d = d[d["market"] == market]
    if month:
        d = d[d["month"] == month]
    if d.empty:
        return {}

    sub = combined
    if market:
        sub = sub[sub["market"] == market]
    if month:
        sub = sub[sub["month"] == month]

    orders = int(d["order"].nunique())
    units = float(d["qty_current"].sum())
    plan_units = float(sub["plan_units"].sum())
    basket = units / orders if orders else None
    if not basket or not plan_units:
        return {"orders": orders, "units": units, "basket": basket}

    implied_orders = plan_units / basket
    return {
        "orders": orders,
        "implied_plan_orders": implied_orders,
        "units": units,
        "plan_units": plan_units,
        "basket": basket,
        "order_gap": orders - implied_orders,
        # Units lost because fewer orders arrived, at the achieved basket size.
        "units_from_orders": (orders - implied_orders) * basket,
        "units_from_basket": units - orders * basket,
    }


def momentum(combined: pd.DataFrame, lines: pd.DataFrame | None,
             plan: pd.DataFrame, market: str, month: str,
             year: int = 2026) -> dict:
    """This month against last, on the measures that drift quietly."""
    i = MONTHS.index(month)
    if i == 0:
        return {}
    prev = MONTHS[i - 1]
    out = {}
    for label, mo in (("now", month), ("prev", prev)):
        s = combined[(combined["market"] == market) & (combined["month"] == mo)]
        rev, cm = s["act_net_lc"].sum(), s["act_cm_at_plan_lc"].sum()
        c = concentration(s, by=["market"])
        out[label] = {
            "revenue": rev,
            "cm_pct": (cm / rev) if rev else None,
            "top1_share": c.iloc[0]["top1_share"] if len(c) else None,
            "confirmed_share": (s["net_confirmed_lc"].sum() / rev
                                if rev and "net_confirmed_lc" in s else None),
        }
    if lines is not None and len(lines):
        oq = order_quality(lines, plan, year)
        for label, mo in (("now", month), ("prev", prev)):
            r = oq[(oq["market"] == market) & (oq["month"] == mo)]
            out[label]["cancel_rate"] = (r.iloc[0]["cancel_rate"]
                                         if len(r) else None)
    out["prev_month"] = prev
    return out


def findings_all(combined: pd.DataFrame, lines: pd.DataFrame | None,
                 plan: pd.DataFrame, month: str, as_of, year: int = 2026,
                 markets: list[str] | None = None) -> list[dict]:
    """Findings across every market, ranked on a common currency.

    A finding is only meaningful once it is attributed, so each market is
    assessed on its own and the results are then merged. Stakes are converted
    to AED before ranking, because a QAR number and an EGP number cannot be
    compared as they stand — without that, Egypt would never surface and
    Qatar would always look worse than it is.
    """
    markets = markets or MARKETS
    fx = (combined.drop_duplicates(["market", "month"])
          .set_index(["market", "month"])["fx_to_aed"]
          if "fx_to_aed" in combined.columns else None)

    out: list[dict] = []
    for mk in markets:
        sub = combined[combined["market"] == mk]
        if sub.empty:
            continue
        try:
            fs = findings(combined, lines, plan, mk, month, as_of, year)
        except Exception:
            continue
        rate = 1.0
        if fx is not None:
            try:
                rate = float(fx.loc[(mk, month)])
            except Exception:
                rate = 1.0
        for f in fs:
            f = dict(f)
            f["market"] = mk
            f["stake_local"] = f["stake"]
            f["stake"] = f["stake"] * rate
            f["title"] = f"{mk} · {f['title']}"
            out.append(f)

    order = {"bad": 0, "warn": 1, "good": 2}
    return sorted(out, key=lambda f: (order[f["severity"]], -f["stake"]))


def landing_all(combined: pd.DataFrame, month: str, as_of, year: int = 2026,
                markets: list[str] | None = None) -> dict:
    """Consolidated pacing and landing estimate, in AED.

    Each market is paced against its own plan and then converted, rather than
    pacing a converted total. Those are not the same thing when a market has
    no plan for the month.
    """
    markets = markets or MARKETS
    plan_t = paced_t = actual_t = proj_t = 0.0
    days_total = days_elapsed = 0
    for mk in markets:
        sub = combined[combined["market"] == mk]
        if sub.empty:
            continue
        rate = 1.0
        if "fx_to_aed" in sub.columns:
            r = sub[sub["month"] == month]["fx_to_aed"].dropna()
            if len(r):
                rate = float(r.iloc[0])
        l = landing(combined, mk, month, as_of, year)
        plan_t += l["plan"] * rate
        paced_t += l["paced_plan"] * rate
        actual_t += l["actual"] * rate
        if l["projected"]:
            proj_t += l["projected"] * rate
        days_total = max(days_total, l["days_total"])
        days_elapsed = max(days_elapsed, l["days_elapsed"])
    return {
        "plan": plan_t, "paced_plan": paced_t, "actual": actual_t,
        "projected": proj_t or None,
        "days_total": days_total, "days_elapsed": days_elapsed,
        "vs_paced": (actual_t / paced_t) if paced_t else None,
        "projected_attainment": (proj_t / plan_t) if (proj_t and plan_t) else None,
    }


def findings(combined: pd.DataFrame, lines: pd.DataFrame | None,
             plan: pd.DataFrame, market: str, month: str,
             as_of, year: int = 2026) -> list[dict]:
    """Ranked findings, each with a magnitude and something to do about it.

    Ordered by money at stake, not by how interesting they are. A finding
    without a number attached is an opinion, so every entry carries one.
    """
    sub = combined[(combined["market"] == market) & (combined["month"] == month)]
    if sub.empty:
        return []
    out: list[dict] = []
    cur = "local"

    land = landing(combined, market, month, as_of, year)
    if land["paced_plan"] and land["vs_paced"] is not None:
        short = land["actual"] - land["paced_plan"]
        sev = "bad" if land["vs_paced"] < 0.9 else (
            "warn" if land["vs_paced"] < 1.0 else "good")
        out.append({
            "severity": sev, "stake": abs(short),
            "title": f"Pacing at {land['vs_paced']:.0%} of where the plan "
                     f"should be on day {land['days_elapsed']}",
            "detail": (f"{short:+,.0f} against a paced plan of "
                       f"{land['paced_plan']:,.0f}. Full month lands near "
                       f"{land['projected']:,.0f} "
                       f"({land['projected_attainment']:.0%} of plan) if the "
                       f"run rate holds."),
        })

    cats = sub.groupby("category", observed=True)[["plan_units", "act_units"]].sum()
    cats = cats[cats["plan_units"] > 0]
    if len(cats) > 1:
        cats["att"] = cats["act_units"] / cats["plan_units"]
        lead = cats["plan_units"].idxmax()
        rest = cats.drop(index=lead)
        if rest["plan_units"].sum():
            ra = rest["act_units"].sum() / rest["plan_units"].sum()
            la = cats.loc[lead, "att"]
            if abs(la - ra) > 0.15:
                miss = (rest["plan_units"].sum() - rest["act_units"].sum())
                out.append({
                    "severity": "bad" if ra < 0.7 else "warn",
                    "stake": miss * sub["plan_price_lc"].mean(),
                    "title": (f"{lead} at {la:.0%}, everything else at {ra:.0%}"
                              if la > ra else
                              f"{lead} at {la:.0%} against {ra:.0%} elsewhere"),
                    "detail": (f"{miss:,.0f} boxes short outside {lead}. "
                               f"The month turned on breadth, not demand — "
                               f"a merchandising and supply question, not a "
                               f"pricing one."),
                })

    conc = concentration(sub, by=["market"])
    if len(conc) and conc.iloc[0]["top1_share"] and conc.iloc[0]["top1_share"] > 0.30:
        cr = conc.iloc[0]
        out.append({
            "severity": "bad" if cr["top1_share"] > 0.45 else "warn",
            "stake": cr["revenue_lc"] * cr["top1_share"],
            "title": f"{cr['top1_share']:.0%} of revenue rests on "
                     f"{cr['top1_product']}",
            "detail": (f"Top three carry {cr['top3_share']:.0%} across "
                       f"{int(cr['products'])} products sold. A single quality "
                       f"or season failure removes "
                       f"{cr['revenue_lc'] * cr['top1_share']:,.0f}."),
        })

    if lines is not None and len(lines):
        oq = order_quality(lines, plan, year)
        r = oq[(oq["market"] == market) & (oq["month"] == month)]
        if len(r) and r.iloc[0]["cancel_rate"] and r.iloc[0]["cancel_rate"] > 0.05:
            o = r.iloc[0]
            out.append({
                "severity": "bad" if o["cancel_rate"] > 0.10 else "warn",
                "stake": o["cost_lost_lc"],
                "title": f"{o['cancel_rate']:.0%} of orders cancelled",
                "detail": (f"{int(o['orders_lost'])} of {int(o['orders'])} "
                           f"orders, {o['units_lost']:,.0f} boxes. At planned "
                           f"cost that is {o['cost_lost_lc']:,.0f} of fruit "
                           f"already procured — a write-off, not a lost sale."),
            })

        tb = traffic_basket(lines, combined, year, market, month)
        if tb.get("order_gap") is not None and abs(tb["order_gap"]) > 1:
            frm_o, frm_b = tb["units_from_orders"], tb["units_from_basket"]
            driver = "fewer orders" if abs(frm_o) > abs(frm_b) else "smaller baskets"
            out.append({
                "severity": "warn" if tb["order_gap"] < 0 else "good",
                "stake": abs(frm_o) * sub["plan_price_lc"].mean(),
                "title": f"The unit gap is mostly {driver}",
                "detail": (f"{tb['orders']:,.0f} orders against an implied "
                           f"{tb['implied_plan_orders']:,.0f} at the achieved "
                           f"basket of {tb['basket']:.1f} boxes. "
                           f"{frm_o:+,.0f} boxes from order count, "
                           f"{frm_b:+,.0f} from basket size."),
            })

    cb = cm_per_box(sub)
    if len(cb):
        weak = cb[cb["price_realisation"] < 0.90]
        if len(weak):
            lost = ((weak["plan_wavg_price"] - weak["act_wavg_price"])
                    * weak["act_units"]).sum()
            out.append({
                "severity": "warn", "stake": lost,
                "title": f"{len(weak)} product"
                         f"{'s' if len(weak) != 1 else ''} sold below 90% of "
                         f"plan price",
                "detail": (f"{', '.join(weak['product'].head(4))}"
                           f"{' and others' if len(weak) > 4 else ''}. "
                           f"{lost:,.0f} of revenue given away against plan "
                           f"price on units actually sold."),
            })

    # Discount and reversals only earn a place when they are material. A one
    # percent discount rate is noise; a twelve percent reversal rate is the
    # largest leak in the month and should outrank most other findings.
    L = leakage(combined, lines, plan, market, month, year)
    if L and abs(L.get("residual", 0)) < 1:
        if L.get("reversal_rate") and L["reversal_rate"] > 0.05:
            out.append({
                "severity": "bad" if L["reversal_rate"] > 0.10 else "warn",
                "stake": L["reversal_value"],
                "title": f"{L['reversal_rate']:.0%} of gross revenue reversed",
                "detail": (f"{L['reversal_value']:,.0f} lost to returns and "
                           f"cancelled orders against {L['actual_gross']:,.0f} "
                           f"of gross. That is "
                           f"{L['reversal_value'] / max(1, abs(L['discount_value'])):.0f}x "
                           f"what discounting costs. The fruit was procured "
                           f"and flown before the order died."),
            })
        if L.get("discount_rate") and L["discount_rate"] > 0.03:
            out.append({
                "severity": "warn" if L["discount_rate"] > 0.06 else "good",
                "stake": L["discount_value"],
                "title": f"{L['discount_rate']:.0%} of gross given away in "
                         f"discount",
                "detail": (f"{L['discount_value']:,.0f} on "
                           f"{L['act_units']:,.0f} boxes, "
                           f"{L['discount_value'] / max(1, L['act_units']):,.2f} "
                           f"a box. Cost does not fall when price does, so all "
                           f"of it comes straight off contribution margin."),
            })

    dead = sub[(sub["plan_units"] > 0) & (sub["act_units"] == 0)]
    if len(dead):
        out.append({
            "severity": "warn", "stake": dead["plan_revenue_lc"].sum(),
            "title": f"{len(dead)} planned product"
                     f"{'s' if len(dead) != 1 else ''} sold nothing",
            "detail": (f"{', '.join(dead['product'].head(4))}. "
                       f"{dead['plan_revenue_lc'].sum():,.0f} of planned "
                       f"revenue with no orders at all — either delisted, out "
                       f"of stock, or never launched."),
        })

    if "net_confirmed_lc" in sub.columns and sub["act_net_lc"].sum():
        soft = 1 - sub["net_confirmed_lc"].sum() / sub["act_net_lc"].sum()
        if soft > 0.5:
            out.append({
                "severity": "warn",
                "stake": sub["act_net_lc"].sum() * soft,
                "title": f"{soft:.0%} of revenue is not yet delivered or paid",
                "detail": (f"{sub['act_net_lc'].sum() * soft:,.0f} can still "
                           f"move. Normal for cash on delivery, but it means "
                           f"this month's number is not final."),
            })

    order = {"bad": 0, "warn": 1, "good": 2}
    return sorted(out, key=lambda f: (order[f["severity"]], -f["stake"]))


def leakage(combined: pd.DataFrame, lines: pd.DataFrame | None = None,
            plan: pd.DataFrame | None = None, market: str | None = None,
            month: str | None = None, year: int = 2026) -> dict:
    """Where planned revenue went, from plan down to cash actually invoiced.

    The margin bridge asks why the gap happened. This asks where the money
    leaked, which is a different question with different owners:

        plan revenue
          less volume        boxes never sold, at plan price
            of which cancelled   ordered, then lost while waiting
            of which never ordered
          plus or minus price  gross price achieved against plan price
          less discounts       given away at the till
        = net revenue

    The parts reconcile exactly to actual net revenue, because volume is
    valued at plan price and price is valued on units actually sold. Order
    that the other way round and the residual has to be hidden somewhere.

    Cancellation is shown inside volume rather than added on top. A cancelled
    order is already absent from actuals, so counting it separately would
    charge the same loss twice.
    """
    d = combined
    if market:
        d = d[d["market"] == market]
    if month:
        d = d[d["month"] == month]
    if d.empty:
        return {}

    plan_units = float(d["plan_units"].sum())
    plan_rev = float(d["plan_revenue_lc"].sum())
    act_units = float(d["act_units"].sum())
    act_gross = float(d["act_gross_lc"].sum())
    act_disc = float(d["act_discounts_lc"].sum())
    act_net = float(d["act_net_lc"].sum())

    plan_price = (plan_rev / plan_units) if plan_units else 0.0
    volume = (act_units - plan_units) * plan_price
    price = act_gross - act_units * plan_price
    discount = -act_disc
    # Whatever separates gross from net beyond discount is returns and
    # reversals. Deriving it rather than reading a column means the parts
    # always add up, whichever route the actuals arrived by.
    reversals = -(act_gross - act_disc - act_net)

    cancelled_units = cancelled_value = 0.0
    cancel_rate = None
    if lines is not None and len(lines):
        oq = order_quality(lines, plan, year)
        if market:
            oq = oq[oq["market"] == market]
        if month:
            oq = oq[oq["month"] == month]
        if len(oq):
            cancelled_units = float(oq["units_lost"].sum())
            cancelled_value = float(oq["value_lost_lc"].sum())
            tot_o = float(oq["orders"].sum())
            cancel_rate = (float(oq["orders_lost"].sum()) / tot_o
                           if tot_o else None)

    # Cancelled boxes are part of the volume gap, valued on the same basis so
    # the two are directly comparable.
    vol_cancelled = -cancelled_units * plan_price
    vol_never_ordered = volume - vol_cancelled

    return {
        "plan_revenue": plan_rev,
        "volume": volume,
        "volume_cancelled": vol_cancelled,
        "volume_never_ordered": vol_never_ordered,
        "price": price,
        "discount": discount,
        "reversals": reversals,
        "actual_net": act_net,
        "actual_gross": act_gross,
        "gap": act_net - plan_rev,
        # Reconciliation is asserted, not assumed. If this is not ~0 the
        # decomposition is wrong and should not be shown.
        "residual": act_net - (plan_rev + volume + price + discount
                               + reversals),
        "plan_units": plan_units, "act_units": act_units,
        "plan_price": plan_price,
        "act_gross_price": (act_gross / act_units) if act_units else None,
        "act_net_price": (act_net / act_units) if act_units else None,
        "discount_rate": (act_disc / act_gross) if act_gross else None,
        "discount_value": act_disc,
        "reversal_value": -reversals,
        "reversal_rate": (-reversals / act_gross) if act_gross else None,
        "cancelled_units": cancelled_units,
        "cancelled_value": cancelled_value,
        "cancel_rate": cancel_rate,
        # Margin lost to discount, since a discount is pure margin: the cost
        # of the box does not fall when the price does.
        "discount_cm_impact": -act_disc,
    }


def discount_detail(combined: pd.DataFrame, by: str = "product",
                    market: str | None = None,
                    month: str | None = None) -> pd.DataFrame:
    """Discount rate and value per product, category or month.

    A blended discount rate hides the products giving away the most. Every
    unit of discount is a unit of margin, because cost does not move when
    price does.
    """
    d = combined[combined["act_gross_lc"] > 0]
    if market:
        d = d[d["market"] == market]
    if month:
        d = d[d["month"] == month]
    if d.empty:
        return pd.DataFrame()

    keys = ["market", by] if by not in ("market",) else ["market"]
    g = d.groupby(keys, observed=True).agg(
        units=("act_units", "sum"),
        gross=("act_gross_lc", "sum"),
        discount=("act_discounts_lc", "sum"),
        net=("act_net_lc", "sum"),
        cm=("act_cm_at_plan_lc", "sum")).reset_index()
    g["discount_rate"] = g["discount"] / g["gross"]
    g["discount_per_box"] = g["discount"] / g["units"].where(g["units"].ne(0))
    g["cm_pct"] = g["cm"] / g["net"].where(g["net"].ne(0))
    # What the margin would have been with no discount at all.
    g["cm_pct_undiscounted"] = ((g["cm"] + g["discount"])
                                / g["gross"].where(g["gross"].ne(0)))
    g["cm_points_lost"] = (g["cm_pct_undiscounted"] - g["cm_pct"]) * 100
    return g.sort_values("discount", ascending=False).reset_index(drop=True)


def daily(lines: pd.DataFrame, plan: pd.DataFrame | None = None,
          year: int = 2026, market: str | None = None,
          month: str | None = None, cost_log: pd.DataFrame | None = None
          ) -> pd.DataFrame:
    """One row per day: orders, boxes, revenue, margin.

    Built from the same billable rule as everything else, so a daily figure
    and a monthly one can never disagree. Cancelled and dead-status orders
    are absent rather than zeroed, and a day with no sales at all is a real
    row of zeros rather than a missing one — a gap in a daily series is
    almost always more interesting than a low day.
    """
    d = lines.copy()
    d["date"] = _stamps(d["processed_at"]).dt.normalize()
    d = d[(d["date"].dt.year == year) & (~d["cancelled"])
          & (~d["financial_status"].isin(DEAD_STATUSES))
          & (d["qty_current"] > 0)
          & (~d["product"].isin(NOT_PRODUCTS))]
    if market:
        d = d[d["market"] == market]
    if month:
        d = d[d["date"].dt.month == MONTHS.index(month) + 1]
    if d.empty:
        return pd.DataFrame()

    ratio = (d["qty_current"] / d["qty_ordered"]).where(
        d["qty_ordered"].ne(0), 1.0).clip(upper=1.0)
    d["net"] = d["net_line_lc"] * ratio
    d["gross"] = d["gross_lc"] * ratio

    if cost_log is not None and len(cost_log):
        costed = apply_dated_cost(d, cost_log, plan)
        unit_cost = pd.to_numeric(costed["unit_cost_dated"], errors="coerce")
    elif plan is not None:
        d["_m"] = d["date"].dt.month.map(lambda n: MONTHS[n - 1])
        pc = (plan.drop_duplicates(["product", "market", "month"])
              .set_index(["product", "market", "month"])["plan_cogs_unit_lc"])
        idx = pd.MultiIndex.from_arrays([d["product"], d["market"], d["_m"]])
        unit_cost = pd.Series(pc.reindex(idx).to_numpy(), index=d.index)
        d = d.drop(columns=["_m"])
    else:
        unit_cost = pd.Series(0.0, index=d.index)
    d["cogs"] = d["qty_current"] * unit_cost.fillna(0)

    g = d.groupby("date", observed=True).agg(
        orders=("order", "nunique"),
        boxes=("qty_current", "sum"),
        gross=("gross", "sum"),
        revenue=("net", "sum"),
        cogs=("cogs", "sum"),
        products=("product", "nunique")).reset_index()

    # Fill the calendar so a silent day reads as zero, not as absent.
    full = pd.date_range(g["date"].min(), g["date"].max(), freq="D")
    g = (g.set_index("date").reindex(full, fill_value=0)
         .rename_axis("date").reset_index())

    g["cm"] = g["revenue"] - g["cogs"]
    g["cm_pct"] = (g["cm"] / g["revenue"]).where(g["revenue"].ne(0))
    g["discount"] = (g["gross"] - g["revenue"]).clip(lower=0)
    g["boxes_per_order"] = (g["boxes"] / g["orders"]).where(g["orders"].ne(0))
    g["aov"] = (g["revenue"] / g["orders"]).where(g["orders"].ne(0))
    g["weekday"] = g["date"].dt.day_name()
    g["rolling_7"] = g["revenue"].rolling(7, min_periods=1).mean()
    g["cumulative"] = g["revenue"].cumsum()
    return g


def daily_by_market(lines: pd.DataFrame, plan: pd.DataFrame | None = None,
                    year: int = 2026, month: str | None = None,
                    cost_log: pd.DataFrame | None = None) -> pd.DataFrame:
    """The daily series split by market, for comparing shapes side by side.

    Each market is built with the same rule as the single-market view, then
    stacked, so a market total here always matches that market read alone.
    """
    out = []
    for mk in MARKETS:
        d = daily(lines, plan, year, mk, month, cost_log)
        if d.empty:
            continue
        d = d.copy()
        d["market"] = mk
        out.append(d)
    if not out:
        return pd.DataFrame()
    return pd.concat(out, ignore_index=True)


def daily_summary(daily_df: pd.DataFrame, plan_month_revenue: float | None = None,
                  days_in_month: int | None = None) -> dict:
    """The four numbers that head a daily view.

    Yesterday rather than today, because today is still running and a
    part-day compared against a full one is misleading.
    """
    if daily_df is None or daily_df.empty:
        return {}
    d = daily_df
    last = d.iloc[-1]
    week = d.tail(7)
    prev_week = d.iloc[-14:-7] if len(d) >= 14 else None

    wd = (d[d["revenue"] > 0].groupby("weekday")["revenue"].mean()
          if (d["revenue"] > 0).any() else pd.Series(dtype=float))
    overall = d[d["revenue"] > 0]["revenue"].mean() if (d["revenue"] > 0).any() else 0

    return {
        "last_date": last["date"],
        "last_revenue": float(last["revenue"]),
        "last_orders": int(last["orders"]),
        "last_boxes": float(last["boxes"]),
        "avg_7": float(week["revenue"].mean()),
        "avg_7_prev": float(prev_week["revenue"].mean()) if prev_week is not None else None,
        "week_change": (float(week["revenue"].mean() / prev_week["revenue"].mean() - 1)
                        if prev_week is not None and prev_week["revenue"].mean() else None),
        "mtd": float(d["revenue"].sum()),
        "days_elapsed": int(len(d)),
        "plan_per_day": (plan_month_revenue / days_in_month
                         if plan_month_revenue and days_in_month else None),
        "mtd_vs_plan": (d["revenue"].sum() / (plan_month_revenue
                        * len(d) / days_in_month)
                        if plan_month_revenue and days_in_month else None),
        "best_weekday": (wd.idxmax() if len(wd) else None),
        "best_weekday_lift": (wd.max() / overall - 1) if len(wd) and overall else None,
        "zero_days": int((d["revenue"] == 0).sum()),
    }


def daily_products(lines: pd.DataFrame, year: int = 2026,
                   market: str | None = None, month: str | None = None,
                   window: int = 7) -> pd.DataFrame:
    """Product movement over the last window against the window before it.

    A monthly product table says what sold. This says what is changing, which
    is the only thing a daily view can act on. Days since the last sale is
    carried because on a perishable a product that quietly stopped selling is
    a stronger signal than one that merely sold less.
    """
    d = lines.copy()
    d["date"] = _stamps(d["processed_at"]).dt.normalize()
    d = d[(d["date"].dt.year == year) & (~d["cancelled"])
          & (~d["financial_status"].isin(DEAD_STATUSES))
          & (d["qty_current"] > 0)
          & (~d["product"].isin(NOT_PRODUCTS))]
    if market:
        d = d[d["market"] == market]
    if month:
        d = d[d["date"].dt.month == MONTHS.index(month) + 1]
    if d.empty:
        return pd.DataFrame()

    ratio = (d["qty_current"] / d["qty_ordered"]).where(
        d["qty_ordered"].ne(0), 1.0).clip(upper=1.0)
    d["net"] = d["net_line_lc"] * ratio

    last_day = d["date"].max()
    cur_from = last_day - pd.Timedelta(days=window - 1)
    prv_from = cur_from - pd.Timedelta(days=window)

    cur = d[d["date"] >= cur_from]
    prv = d[(d["date"] >= prv_from) & (d["date"] < cur_from)]

    def roll(x, tag):
        if x.empty:
            return pd.DataFrame(columns=["product", f"units_{tag}",
                                         f"revenue_{tag}", f"orders_{tag}"])
        return x.groupby("product", observed=True).agg(
            **{f"units_{tag}": ("qty_current", "sum"),
               f"revenue_{tag}": ("net", "sum"),
               f"orders_{tag}": ("order", "nunique")}).reset_index()

    g = roll(cur, "now").merge(roll(prv, "prev"), on="product", how="outer")
    for c in g.columns:
        if c != "product":
            g[c] = g[c].fillna(0)

    last_sale = d.groupby("product", observed=True)["date"].max()
    g["days_since_sale"] = g["product"].map(
        lambda p: (last_day - last_sale.get(p, last_day)).days)

    g["revenue_change"] = g["revenue_now"] - g["revenue_prev"]
    g["revenue_change_pct"] = (g["revenue_change"] / g["revenue_prev"]).where(
        g["revenue_prev"].gt(0))
    g["units_change"] = g["units_now"] - g["units_prev"]
    tot = g["revenue_now"].sum()
    g["share_now"] = g["revenue_now"] / tot if tot else 0
    g["price_now"] = (g["revenue_now"] / g["units_now"]).where(
        g["units_now"].gt(0))
    g["price_prev"] = (g["revenue_prev"] / g["units_prev"]).where(
        g["units_prev"].gt(0))

    g["status"] = "steady"
    g.loc[g["revenue_prev"].eq(0) & g["revenue_now"].gt(0), "status"] = "new"
    g.loc[g["revenue_now"].eq(0) & g["revenue_prev"].gt(0), "status"] = "stopped"
    g.loc[g["revenue_change_pct"].gt(0.25), "status"] = "rising"
    g.loc[g["revenue_change_pct"].lt(-0.25), "status"] = "fading"
    g["window_days"] = window
    g["as_of"] = last_day
    return g.sort_values("revenue_now", ascending=False).reset_index(drop=True)


def daily_product_mix(lines: pd.DataFrame, year: int = 2026,
                      market: str | None = None, month: str | None = None,
                      top: int = 6) -> pd.DataFrame:
    """Daily revenue for the leading products, everything else as one series."""
    d = lines.copy()
    d["date"] = _stamps(d["processed_at"]).dt.normalize()
    d = d[(d["date"].dt.year == year) & (~d["cancelled"])
          & (~d["financial_status"].isin(DEAD_STATUSES))
          & (d["qty_current"] > 0)
          & (~d["product"].isin(NOT_PRODUCTS))]
    if market:
        d = d[d["market"] == market]
    if month:
        d = d[d["date"].dt.month == MONTHS.index(month) + 1]
    if d.empty:
        return pd.DataFrame()

    ratio = (d["qty_current"] / d["qty_ordered"]).where(
        d["qty_ordered"].ne(0), 1.0).clip(upper=1.0)
    d["net"] = d["net_line_lc"] * ratio
    leaders = (d.groupby("product", observed=True)["net"].sum()
               .nlargest(top).index)
    d["band"] = d["product"].where(d["product"].isin(leaders), "Other")
    return (d.groupby(["date", "band"], observed=True)["net"].sum()
            .reset_index(name="revenue"))


def demand_note(daily_df: pd.DataFrame, window: int = 7) -> str:
    """One sentence decomposing the move into orders, basket and price.

    Revenue is orders times basket times price. Naming which of the three
    moved is the difference between a number and something to act on, and
    the three have different owners.
    """
    if daily_df is None or len(daily_df) < window * 2:
        return ""
    cur = daily_df.tail(window)
    prv = daily_df.iloc[-window * 2:-window]

    def parts(x):
        o = x["orders"].sum()
        u = x["boxes"].sum()
        r = x["revenue"].sum()
        return o, (u / o if o else 0), (r / u if u else 0), r

    o1, b1, p1, r1 = parts(prv)
    o2, b2, p2, r2 = parts(cur)
    if not r1 or not o1:
        return ""

    dr = r2 / r1 - 1
    do = o2 / o1 - 1 if o1 else 0
    db = b2 / b1 - 1 if b1 else 0
    dp = p2 / p1 - 1 if p1 else 0

    driver = max((abs(do), "orders"), (abs(db), "basket size"),
                 (abs(dp), "price"))[1]
    moved = {"orders": do, "basket size": db, "price": dp}[driver]

    lead = (f"Revenue {'up' if dr >= 0 else 'down'} {abs(dr):.0%} on the "
            f"previous {window} days.")
    detail = (f"Orders {do:+.0%}, basket {db:+.0%}, price {dp:+.0%} — "
              f"{driver} moved most at {moved:+.0%}.")
    owner = {
        "orders": "That is a demand question: traffic, campaigns, agents.",
        "basket size": "That is a merchandising question: bundles, minimums, "
                       "what is shown at checkout.",
        "price": "That is a mix or pricing question: cheaper products "
                 "carrying the day, or discount widening.",
    }[driver]
    return f"{lead} {detail} {owner}"


# Delivered, but the cash has not arrived. On cash on delivery this is normal
# for a few days and a problem after a few weeks, so it is aged rather than
# reported as one number.
COLLECTED = {"PAID"}
UNCOLLECTED = {"PENDING", "AUTHORIZED", "PARTIALLY_PAID"}
AGE_BANDS = [(0, 3, "0-3 days"), (4, 7, "4-7 days"), (8, 14, "8-14 days"),
             (15, 30, "15-30 days"), (31, 10_000, "over 30 days")]


def receivables(lines: pd.DataFrame, as_of=None, year: int = 2026,
                market: str | None = None) -> pd.DataFrame:
    """Orders delivered where the money has not been collected.

    Aged from the fulfilment date, not the order date, because the clock that
    matters starts when the customer took the goods. Where no fulfilment date
    was recorded the order date is used and the row says so, rather than being
    dropped or silently treated as new.
    """
    d = lines.copy()
    d["processed"] = _stamps(d["processed_at"]).dt.tz_localize(None)
    d = d[(d["processed"].dt.year == year) & (~d["cancelled"])
          & (d["qty_current"] > 0)]
    if market:
        d = d[d["market"] == market]
    if d.empty:
        return pd.DataFrame()

    delivered = d["fulfillment_status"].eq("FULFILLED")
    open_money = d["financial_status"].isin(UNCOLLECTED)
    d = d[delivered & open_money]
    if d.empty:
        return pd.DataFrame()

    ratio = (d["qty_current"] / d["qty_ordered"]).where(
        d["qty_ordered"].ne(0), 1.0).clip(upper=1.0)
    d["net"] = d["net_line_lc"] * ratio

    if "fulfilled_at" in d.columns:
        ff = pd.to_datetime(d["fulfilled_at"], utc=True, errors="coerce",
                            format="mixed").dt.tz_localize(None)
    else:
        ff = pd.Series(pd.NaT, index=d.index)
    d["date_basis"] = np.where(ff.notna(), "delivery", "order date")
    d["since"] = ff.fillna(d["processed"])

    ref = pd.Timestamp(as_of) if as_of is not None else d["processed"].max()
    d["age_days"] = (ref.normalize() - d["since"].dt.normalize()).dt.days.clip(lower=0)

    g = d.groupby(["market", "order"], observed=True).agg(
        outstanding=("net", "sum"),
        boxes=("qty_current", "sum"),
        age_days=("age_days", "max"),
        status=("financial_status", "first"),
        channel=("channel", "first"),
        agent=("agent", "first"),
        city=("city", "first"),
        basis=("date_basis", "first"),
        since=("since", "min")).reset_index()

    def band(n):
        for lo, hi, lbl in AGE_BANDS:
            if lo <= n <= hi:
                return lbl
        return AGE_BANDS[-1][2]

    g["age_band"] = g["age_days"].map(band)
    return g.sort_values("age_days", ascending=False).reset_index(drop=True)


def receivables_summary(rec: pd.DataFrame, collected_revenue: float | None = None
                        ) -> dict:
    """Headline figures for uncollected cash."""
    if rec is None or rec.empty:
        return {}
    order = [lbl for _, _, lbl in AGE_BANDS]
    by_band = (rec.groupby("age_band", observed=True)
               .agg(orders=("order", "nunique"),
                    outstanding=("outstanding", "sum")).reindex(order)
               .fillna(0).reset_index())
    over14 = rec[rec["age_days"] > 14]["outstanding"].sum()
    total = rec["outstanding"].sum()
    return {
        "orders": int(rec["order"].nunique()),
        "outstanding": float(total),
        "oldest_days": int(rec["age_days"].max()),
        "avg_age": float(rec["age_days"].mean()),
        "over_14": float(over14),
        "over_14_share": float(over14 / total) if total else None,
        "by_band": by_band,
        "share_of_revenue": (float(total / collected_revenue)
                             if collected_revenue else None),
        "no_delivery_date": int((rec["basis"] == "order date").sum()),
    }
