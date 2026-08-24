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


def _dead(o):
    """Cancelled, voided or refunded. Can never be dispatched, so never counted.
    Shopify's order views hide these too, which is why the counts agree."""
    return (bool(o.get("cancelled"))
            or str(o.get("financial", "")).upper() in EXCLUDED_FINANCIAL)


def in_scope(orders):
    """Stage 2, still alive. Everything else is not this run's business."""
    return [o for o in orders
            if (o.get("stage") or "").strip() == INCLUDE_STAGE and not _dead(o)]


def dead_stage2(orders):
    """Stage-2 orders that were cancelled, voided or refunded. Shown, never counted."""
    rows = []
    for o in orders:
        if (o.get("stage") or "").strip() == INCLUDE_STAGE and _dead(o):
            why = ("Cancelled" if o.get("cancelled")
                   else str(o.get("financial", "")).title())
            rows.append({"Order": o["name"], "Reason": why,
                         "Urgent": "Yes" if o.get("urgent") else ""})
    return pd.DataFrame(rows)


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


_LAST_PASSED = None

STRATEGIES = {
    "Most orders":    {"w": 12, "when": "Backlog of waiting customers"},
    "Balanced":       {"w": 3,  "when": "Normal day"},
    "Most stock out": {"w": 0,  "when": "Stock ageing, needs to move"},
}


def _optimise(pool, left, w, iters=45000, seed=0):
    """Pick the best combination of orders that fits the stock left.

    Greedy picking leaves stock unused, because it never reconsiders an early
    choice. This anneals: it keeps trying swaps and keeps whatever scores best.
    w weights orders against boxes - high w favours more orders, w=0 favours
    moving the most boxes.
    """
    import random, math
    M = len(pool)
    if not M:
        return []
    rnd = random.Random(seed)

    def feasible(sel):
        u = {}
        for i in sel:
            for k, v in pool[i]["_need"].items():
                u[k] = u.get(k, 0) + v
        return all(u.get(k, 0) <= left.get(k, 0) for k in u)

    def score(sel):
        return w * len(sel) + sum(pool[i]["_boxes"] for i in sel)

    sel, cur = set(), {}
    for i in sorted(range(M), key=lambda i: pool[i]["_placed"]):
        if all(cur.get(k, 0) + v <= left.get(k, 0)
               for k, v in pool[i]["_need"].items()):
            sel.add(i)
            for k, v in pool[i]["_need"].items():
                cur[k] = cur.get(k, 0) + v
    best, best_score, cur_score = set(sel), score(sel), score(sel)
    for it in range(iters):
        T = max(0.02, 3.0 * (1 - it / iters))
        i = rnd.randrange(M)
        new = set(sel)
        if i in new:
            new.discard(i)
        else:
            new.add(i)
            tries = 0
            while not feasible(new) and tries < 6:
                drops = [x for x in new if x != i]
                if not drops:
                    break
                new.discard(rnd.choice(drops))
                tries += 1
            if not feasible(new):
                continue
        if not feasible(new):
            continue
        ns = score(new)
        if ns >= cur_score or rnd.random() < math.exp((ns - cur_score) / T):
            sel, cur_score = new, ns
            if ns > best_score:
                best, best_score = set(new), ns
    return [pool[i] for i in best]


def allocate(orders, stock, item_codes, strategy="Balanced", cap_days=3, as_of=None):
    """Return (dispatch_df, short_df, excluded_df, pool_after).

    Order of business:
      1. Urgent orders, oldest first - always in if they fit
      2. Anything cap_days old or older - always in if it fits
      3. The rest - best combination the optimiser can find
    All-or-nothing per order. Stock taken oldest shipment first.
    """
    elig, excl = screen_orders(orders, item_codes)
    pool = available_pool(stock)
    left = pool.groupby("Item")["Avail"].sum().to_dict()

    for o in elig:
        o["_need"] = _need(o)
        o["_boxes"] = sum(o["_need"].values())
        o["_urgent"] = bool(o.get("urgent"))
        o["_placed"] = pd.to_datetime(o["created"]).tz_localize(None) \
            if pd.to_datetime(o["created"]).tzinfo else pd.to_datetime(o["created"])

    today = pd.Timestamp(as_of).normalize() if as_of is not None else (
        max((o["_placed"] for o in elig), default=pd.Timestamp.now()).normalize())

    def take(o):
        for s, q in o["_need"].items():
            left[s] -= q

    picked, rule = [], {}
    for o in sorted([o for o in elig if o["_urgent"]], key=lambda o: o["_placed"]):
        if _can_fill(o["_need"], left):
            take(o); picked.append(o); rule[o["name"]] = "URG"

    if cap_days is not None:
        aged = [o for o in elig if o not in picked
                and (today - o["_placed"].normalize()).days >= cap_days]
        for o in sorted(aged, key=lambda o: o["_placed"]):
            if _can_fill(o["_need"], left):
                take(o); picked.append(o); rule[o["name"]] = "CAP"

    rest = [o for o in elig if o not in picked]
    w = STRATEGIES.get(strategy, STRATEGIES["Balanced"])["w"]
    def greedy(order_key):
        l2, got = dict(left), []
        for o in sorted(rest, key=order_key):
            if all(l2.get(k, 0) >= v for k, v in o["_need"].items()):
                for k, v in o["_need"].items():
                    l2[k] -= v
                got.append(o)
        return got

    # anneal from several seeds, plus deterministic candidates, keep the best.
    # without the deterministic ones a strategy can lose to another strategy,
    # which would make its label untrue.
    runs = [_optimise(rest, left, w, seed=s_) for s_ in (0, 1, 2)]
    runs += [greedy(lambda o: o["_placed"]),
             greedy(lambda o: (o["_boxes"], o["_placed"])),
             greedy(lambda o: (-o["_boxes"], o["_placed"]))]
    if w == 0:
        runs += [_optimise(rest, left, 3, seed=s_) for s_ in (0, 1)]
    elif w >= 12:
        runs += [_optimise(rest, left, 3, seed=s_) for s_ in (0, 1)]
    else:
        runs += [_optimise(rest, left, 0, seed=0), _optimise(rest, left, 12, seed=0)]
    key = ((lambda g: (sum(x["_boxes"] for x in g), len(g))) if w == 0
           else ((lambda g: (len(g), sum(x["_boxes"] for x in g))) if w >= 12
                 else (lambda g: (w * len(g) + sum(x["_boxes"] for x in g), len(g)))))
    for o in max(runs, key=key):
        take(o); picked.append(o); rule[o["name"]] = "FIT"

    rows, pool = [], pool.copy()
    for o in sorted(picked, key=lambda o: ({"URG": 0, "CAP": 1, "FIT": 2}[rule[o["name"]]],
                                           o["_placed"])):
        for sku, qty in o["_need"].items():
            need = qty
            for i in pool.index[(pool["Item"] == sku) & (pool["Avail"] > 0)]:
                if need <= 0:
                    break
                t = min(need, pool.at[i, "Avail"])
                pool.at[i, "Avail"] -= t
                need -= t
                rows.append({"Order": o["name"], "Placed": o["_placed"].date(),
                             "Rule": rule[o["name"]], "Item": sku, "Qty": t,
                             "Shipment": pool.at[i, "Shipment"],
                             "Arrival": pool.at[i, "Arrival Date"]})
    dispatch = pd.DataFrame(rows)

    srows, passed = [], []
    for o in [x for x in elig if x not in picked]:
        gaps = {sku: q - max(0, left.get(sku, 0)) for sku, q in o["_need"].items()}
        if any(g > 0 for g in gaps.values()):
            for sku, g in gaps.items():
                if g > 0:
                    srows.append({"Order": o["name"], "Item": sku, "Short by": int(g)})
        else:
            passed.append({"Order": o["name"], "Boxes": o["_boxes"],
                           "Why": "stock would cover it, but a better "
                                  "combination was chosen"})
    short = pd.DataFrame(srows)
    global _LAST_PASSED
    _LAST_PASSED = pd.DataFrame(passed)
    excluded = pd.DataFrame([{"Order": o["name"], "Reason": o["reason"]} for o in excl])
    return dispatch, short, excluded, pool


def passed_over(orders=None):
    """Orders the optimiser could have filled but did not choose."""
    return (_LAST_PASSED if _LAST_PASSED is not None
            else pd.DataFrame(columns=["Order", "Boxes", "Why"]))


def compare_strategies(orders, stock, item_codes, cap_days=3, as_of=None):
    """Run all three so the dispatcher can see the trade before choosing."""
    total = float(stock["Store"].sum())
    out = []
    for name, cfg in STRATEGIES.items():
        d, sh, xx, pool = allocate(orders, stock, item_codes, name, cap_days, as_of)
        boxes = float(d["Qty"].sum()) if len(d) else 0.0
        n = d["Order"].nunique() if len(d) else 0
        sel = set(d["Order"]) if len(d) else set()
        elig, _ = screen_orders(orders, item_codes)
        waiting = [o for o in elig if o["name"] not in sel]
        today = pd.Timestamp(as_of).normalize() if as_of is not None else (
            max((pd.to_datetime(o["created"]).tz_localize(None) for o in elig),
                default=pd.Timestamp.now()).normalize())
        oldest = max([(today - pd.to_datetime(o["created"]).tz_localize(None)
                       .normalize()).days for o in waiting], default=0)
        out.append({"Strategy": name, "Orders": n, "Boxes out": boxes,
                    "Left in store": total - boxes, "Oldest waiting": oldest,
                    "Use it when": cfg["when"], "_sel": sel})
    return pd.DataFrame(out)


def ship_no_per_order(dispatch):
    """The shipment that gave the most boxes wins the Ship. No. metafield."""
    if dispatch.empty: return {}
    g = dispatch.groupby(["Order", "Shipment"])["Qty"].sum().reset_index()
    g = g.sort_values("Qty", ascending=False).drop_duplicates("Order")
    return dict(zip(g["Order"], g["Shipment"]))


def checks(dispatch, short, excluded, orders, stock, pool_after,
           cap_days=None, as_of=None, item_codes=None):
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
    n_pass = len(passed_over())
    a("Order counts add up to the stage-2 orders",
      n_disp + n_short + n_excl + n_pass == n_scope,
      f"{n_disp} + {n_short} + {n_excl} + {n_pass} = {n_scope}")
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
    if cap_days is not None and item_codes is not None:
        elig, _ = screen_orders(orders, item_codes)
        sel = set(dispatch["Order"]) if len(dispatch) else set()
        today = pd.Timestamp(as_of).normalize() if as_of is not None else (
            max((pd.to_datetime(o["created"]).tz_localize(None) for o in elig),
                default=pd.Timestamp.now()).normalize())
        breaches = []
        left_after = pool_after.groupby("Item")["Avail"].sum().to_dict() \
            if len(pool_after) else {}
        for o in elig:
            if o["name"] in sel:
                continue
            age = (today - pd.to_datetime(o["created"]).tz_localize(None)
                   .normalize()).days
            if age >= cap_days and _can_fill(_need(o), left_after):
                breaches.append(o["name"])
        a(f"Nothing older than {cap_days:.0f} days was skipped while it could fit",
          not breaches,
          "none" if not breaches else ", ".join(breaches[:4]))
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
        {"Stage": "   less short",          "Orders": short_orders, "Boxes": short_boxes,
         "Note": "cannot complete"},
        {"Stage": "   less not chosen",      "Orders": len(passed_over()),
         "Boxes": float(passed_over()["Boxes"].sum()) if len(passed_over()) else 0.0,
         "Note": "a better combination was picked"},
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
