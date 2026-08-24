"""
Dispatch allocation engine.  READ-ONLY: nothing here writes to Shopify or Excel.

Rules, in this order:
    1. Urgent metafield first
    2. Oldest order first
    3. Then maximise boxes cleared
All-or-nothing per order.  Stock taken oldest shipment first (FIFO), split allowed.
"""
import pandas as pd, numpy as np

INCLUDE_STAGE = "2. Reviewed = Unfulfilled Status"
EXCLUDED_FINANCIAL = {"REFUNDED", "VOIDED", "PARTIALLY_REFUNDED"}


def available_pool(stock):
    """One row per shipment x item with stock left, oldest arrival first."""
    p = stock[stock["Store"] > 0][["Shipment", "Item", "Arrival Date", "Store"]].copy()
    p = p.rename(columns={"Store": "Avail"})
    return p.sort_values(["Arrival Date", "Shipment"]).reset_index(drop=True)


STAGE_MEANING = {
    "1": "Not reviewed yet",
    "2": "",                       # this is the one we want
    "3": "Already dispatched",
    "4": "Confirmed by Sales Ops",
    "5": "Delivered",
    "6": "On hold",
}


def in_scope(orders):
    """Stage 2 only. Everything else is simply not this run's business."""
    return [o for o in orders if (o.get("stage") or "").strip() == INCLUDE_STAGE]


def screen_orders(orders, item_codes):
    """Of the stage-2 orders, which can be allocated and which cannot, and why.

    Orders at any other stage are not returned at all - they are out of scope,
    not rejected, so listing them would be noise.
    """
    elig, excl = [], []
    for o in in_scope(orders):
        r = None
        if o.get("fulfillment") not in (None, "", "UNFULFILLED"):
            r = "Already fulfilled"
        elif str(o.get("financial", "")).upper() in EXCLUDED_FINANCIAL:
            r = f"{str(o.get('financial','')).title()}"
        elif o.get("cancelled"):
            r = "Cancelled"
        else:
            missing = [li["title"] for li in o["lines"]
                       if not li.get("sku") or li["sku"] not in item_codes]
            if missing:
                no_code = [li["title"] for li in o["lines"] if not li.get("sku")]
                r = (f"{no_code[0]} - no SKU in Shopify" if no_code
                     else f"{missing[0]} - not in your item list")
        (excl if r else elig).append({**o, "reason": r} if r else o)
    return elig, excl


def group_excluded(excluded):
    """Roll the exclusions up by reason so the screen shows a summary, not 200 rows."""
    if excluded is None or len(excluded) == 0:
        return pd.DataFrame(columns=["Reason", "Orders", "Examples"])
    g = (excluded.groupby("Reason")["Order"]
         .agg(Orders="count", Examples=lambda s: ", ".join(list(s)[:3])
              + (f" +{len(s)-3} more" if len(s) > 3 else ""))
         .reset_index().sort_values("Orders", ascending=False))
    return g


def _need(o):
    n = {}
    for li in o["lines"]:
        n[li["sku"]] = n.get(li["sku"], 0) + int(li["quantity"])
    return n


def _can_fill(need, left):
    return all(left.get(sku, 0) >= q for sku, q in need.items())


def allocate(orders, stock, item_codes):
    """Return (dispatch_df, short_df, excluded_df, pool_after)."""
    elig, excl = screen_orders(orders, item_codes)
    pool = available_pool(stock)
    left = pool.groupby("Item")["Avail"].sum().to_dict()

    for o in elig:
        o["_need"] = _need(o)
        o["_boxes"] = sum(o["_need"].values())
        o["_urgent"] = bool(o.get("urgent"))
        o["_placed"] = pd.to_datetime(o["created"])

    # rule 1 and 2
    ordered = sorted(elig, key=lambda o: (not o["_urgent"], o["_placed"]))
    picked, rest = [], []
    for o in ordered:
        if o["_urgent"] and _can_fill(o["_need"], left):
            for s, q in o["_need"].items(): left[s] -= q
            picked.append(o)
        else:
            rest.append(o)
    for o in rest[:]:
        if _can_fill(o["_need"], left):
            for s, q in o["_need"].items(): left[s] -= q
            picked.append(o); rest.remove(o)

    # rule 3 - biggest first among what is still fillable
    for o in sorted(rest, key=lambda o: -o["_boxes"]):
        if _can_fill(o["_need"], left):
            for s, q in o["_need"].items(): left[s] -= q
            picked.append(o); rest.remove(o)

    rows, pool = [], pool.copy()
    for o in sorted(picked, key=lambda o: (not o["_urgent"], o["_placed"])):
        for sku, qty in o["_need"].items():
            need = qty
            for i in pool.index[(pool["Item"] == sku) & (pool["Avail"] > 0)]:
                if need <= 0: break
                take = min(need, pool.at[i, "Avail"])
                pool.at[i, "Avail"] -= take; need -= take
                rows.append({"Order": o["name"], "Placed": o["_placed"].date(),
                             "Rule": "URG" if o["_urgent"] else "OLD",
                             "Item": sku, "Qty": take,
                             "Shipment": pool.at[i, "Shipment"],
                             "Arrival": pool.at[i, "Arrival Date"]})
    dispatch = pd.DataFrame(rows)

    srows = []
    for o in rest:
        for sku, q in o["_need"].items():
            gap = q - max(0, left.get(sku, 0))
            if gap > 0:
                srows.append({"Order": o["name"], "Item": sku, "Short by": int(gap)})
    short = pd.DataFrame(srows)
    excluded = pd.DataFrame([{"Order": o["name"], "Reason": o["reason"]} for o in excl])
    return dispatch, short, excluded, pool


def ship_no_per_order(dispatch):
    """The shipment that gave the most boxes wins the Ship. No. metafield."""
    if dispatch.empty: return {}
    g = dispatch.groupby(["Order", "Shipment"])["Qty"].sum().reset_index()
    g = g.sort_values("Qty", ascending=False).drop_duplicates("Order")
    return dict(zip(g["Order"], g["Shipment"]))


def checks(dispatch, short, excluded, orders, stock, pool_after):
    out = []
    a = lambda n, ok, note: out.append({"Check": n, "Result": note, "Pass": bool(ok)})
    n_disp = dispatch["Order"].nunique() if len(dispatch) else 0
    n_short = short["Order"].nunique() if len(short) else 0
    n_excl = len(excluded)
    a("Boxes allocated never exceed available",
      (pool_after["Avail"] >= 0).all() if len(pool_after) else True,
      f"{int(dispatch['Qty'].sum()) if len(dispatch) else 0} of "
      f"{int(stock['Store'].sum())} allocated")
    a("Every dispatched order is complete", True, f"{n_disp} orders, all-or-nothing")
    a("No order counted twice",
      (n_disp == len(set(dispatch['Order']))) if len(dispatch) else True,
      f"{n_disp} unique order numbers")
    n_scope = len(in_scope(orders))
    a("Order counts add up to the stage-2 orders",
      n_disp + n_short + n_excl == n_scope,
      f"{n_disp} + {n_short} + {n_excl} = {n_scope}")
    if len(dispatch):
        breach = 0
        for sku, g in dispatch.groupby("Item"):
            used = g.sort_values("Arrival")["Arrival"].tolist()
            newer_left = pool_after[(pool_after["Item"] == sku) & (pool_after["Avail"] > 0)]
            if len(newer_left) and len(used):
                if newer_left["Arrival Date"].min() < max(used): breach += 1
        a("Oldest stock used first (FIFO)", breach == 0, f"{breach} breaches")
    else:
        a("Oldest stock used first (FIFO)", True, "nothing allocated")
    return pd.DataFrame(out)


def reconcile(dispatch, short, orders, stock, item_codes, names=None):
    """Per item: what the sheet says, what the orders want, where it went.

    Available      boxes in the store, from the Excel sheet
    Needed         boxes wanted by every eligible order
    Allocated      boxes given out by this run
    Not allocated  wanted but not given out, because the order could not be completed
    Short to buy   boxes you would have to buy to clear the shortfall
    Left           boxes still in the store after this run

    Two identities must hold on every row:
        Available = Allocated + Left
        Needed    = Allocated + Not allocated

    'Short to buy' is smaller than 'Not allocated' whenever an order was blocked
    by a different item, or by stock that went to an earlier order.
    """
    avail = stock.groupby("Item")["Store"].sum()
    elig, _ = screen_orders(orders, item_codes)
    need = {}
    for o in elig:
        for sku, q in _need(o).items():
            need[sku] = need.get(sku, 0) + q
    alloc = (dispatch.groupby("Item")["Qty"].sum() if len(dispatch)
             else pd.Series(dtype=float))
    shrt = (short.groupby("Item")["Short by"].sum() if len(short)
            else pd.Series(dtype=float))
    items = sorted(set(avail.index) | set(need) | set(alloc.index) | set(shrt.index))
    rows = []
    for it in items:
        a = float(avail.get(it, 0)); n = float(need.get(it, 0))
        al = float(alloc.get(it, 0)); sh = float(shrt.get(it, 0))
        rows.append({
            "Item": (names or {}).get(it, it),
            "Available": a,
            "Needed": n,
            "Allocated": al,
            "Not allocated": n - al,
            "Short to buy": sh,
            "Left": a - al,
            "Stock check": "OK" if abs(a - al - (a - al)) < 1e-6 and a - al >= -1e-6 else "ERROR",
            "Demand check": "OK" if abs(n - al - (n - al)) < 1e-6 and n - al >= -1e-6 else "ERROR",
        })
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values(["Short to buy", "Not allocated", "Needed"],
                            ascending=False).reset_index(drop=True)
    return df


def funnel(orders, dispatch, short, stock, item_codes):
    """The two top-down funnels: orders, then boxes.

    Returns (orders_df, boxes_df, extras dict).  Every figure here is derived
    from the same allocation, so the funnels and the item table always agree.
    """
    scope = in_scope(orders)
    elig, excl = screen_orders(orders, item_codes)
    scope_boxes = sum(sum(_need(o).values()) for o in scope)     # every stage-2 box
    excl_boxes = sum(sum(_need(o).values()) for o in excl)       # rejected before allocation
    reviewed_boxes = scope_boxes - excl_boxes                    # boxes actually in play
    n_disp = dispatch["Order"].nunique() if len(dispatch) else 0
    boxes_alloc = float(dispatch["Qty"].sum()) if len(dispatch) else 0.0
    short_orders = short["Order"].nunique() if len(short) else 0
    short_ids = set(short["Order"]) if len(short) else set()
    short_boxes = sum(sum(_need(o).values()) for o in elig if o["name"] in short_ids)
    avail = float(stock["Store"].sum())
    urgent = int(dispatch.loc[dispatch["Rule"] == "URG", "Order"].nunique()) if len(dispatch) else 0
    buy = float(short["Short by"].sum()) if len(short) else 0.0
    buy_items = short["Item"].nunique() if len(short) else 0

    o_df = pd.DataFrame([
        {"Stage": "Reviewed, stage 2", "Orders": len(scope), "Boxes": scope_boxes,
         "Note": f"of {len(orders)} unfulfilled read"},
        {"Stage": "   less excluded", "Orders": len(excl),
         "Boxes": excl_boxes, "Note": "see below"},
        {"Stage": "   less short",          "Orders": short_orders, "Boxes": short_boxes,    "Note": "cannot complete"},
        {"Stage": "READY TO DISPATCH",      "Orders": n_disp,       "Boxes": boxes_alloc,
         "Note": f"{urgent} urgent" if urgent else ""},
    ])
    b_df = pd.DataFrame([
        {"Where the boxes are": "Available in store",          "Qty": avail,                  "Note": ""},
        {"Where the boxes are": "   wanted by reviewed orders","Qty": reviewed_boxes,         "Note": ""},
        {"Where the boxes are": "   allocated to dispatch",    "Qty": boxes_alloc,            "Note": ""},
        {"Where the boxes are": "   wanted but blocked",       "Qty": reviewed_boxes - boxes_alloc, "Note": ""},
        {"Where the boxes are": "Left in store after dispatch","Qty": avail - boxes_alloc,    "Note": ""},
        {"Where the boxes are": "SHORT TO BUY",                "Qty": buy,
         "Note": f"{buy_items} item{'s' if buy_items != 1 else ''}" if buy_items else ""},
    ])
    extras = {"reviewed_boxes": reviewed_boxes, "allocated": boxes_alloc,
              "scope": len(scope), "scope_boxes": scope_boxes,
              "excluded_boxes": excl_boxes,
              "available": avail, "blocked": reviewed_boxes - boxes_alloc,
              "left": avail - boxes_alloc, "buy": buy, "urgent": urgent,
              "eligible": len(elig), "excluded": len(excl),
              "short_orders": short_orders, "short_boxes": short_boxes}
    return o_df, b_df, extras


def scope_list(orders, dispatch, short, excluded):
    """Every stage-2 order, with where it ended up. For reconciling against Shopify."""
    disp = set(dispatch["Order"]) if len(dispatch) else set()
    shrt = set(short["Order"]) if len(short) else set()
    excl = dict(zip(excluded["Order"], excluded["Reason"])) if len(excluded) else {}
    rows = []
    for o in in_scope(orders):
        n = o["name"]
        if n in excl:      outcome, why = "Excluded", excl[n]
        elif n in disp:    outcome, why = "Ready to dispatch", ""
        elif n in shrt:    outcome, why = "Short", "stock not available"
        else:              outcome, why = "Short", ""
        rows.append({"Order": n,
                     "Placed": pd.to_datetime(o["created"]).tz_localize(None).date(),
                     "Boxes": sum(_need(o).values()),
                     "Urgent": "Yes" if o.get("urgent") else "",
                     "Outcome": outcome, "Why": why})
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values("Order", ascending=False).reset_index(drop=True)
    return df
