# -*- coding: utf-8 -*-
"""
A full season against a copy of the live workbook.

    python3 simulate.py

Writes simulate.txt. Send me that file.

Nothing touches the live workbook: it is downloaded once, copied, and every
change happens to the copy in memory. Shopify is read only, never written.

What it does: builds shipments, receives them with the shortfalls and
over-deliveries a real store produces, scraps, hands to couriers, takes
returns, sorts them, counts stock, voids mistakes, and tries every illegal
move it can think of. After every single step it checks the whole ledger
against nine rules that must always hold.
"""
import sys, io, os, random, traceback
import datetime as dt
import pandas as pd, openpyxl

OUT = []
def say(*a):
    line = " ".join(str(x) for x in a); OUT.append(line); print(line)
def head(t):
    say(""); say("=" * 64); say(t); say("=" * 64)

FAIL = []
def bad(where, what, detail=""):
    FAIL.append((where, what, detail))
    say(f"    BROKEN  {where}: {what}  {detail}")

import engine, entry, entry_ui


# ------------------------------------------------------------------ the rules
def audit(data, where):
    """Nine things that must be true of the ledger, always. Run after every
    step, so the exact action that breaks one is known."""
    try:
        s, m, c, cfg, e = engine.load(io.BytesIO(data))
        st = engine.stock_by_item(s, m, cfg["as_of"])
        cl = engine.clearance_by_shipment(s, m, cfg["as_of"], cfg)
        cp = engine.courier_positions(s, m, cfg["as_of"], cfg)
    except Exception as ex:
        bad(where, "the workbook could not be read", str(ex)[:80]); return None

    if len(e):
        bad(where, f"{len(e)} entry errors", e.iloc[0].to_dict())
    if len(st) and (st["Store"] < -0.001).any():
        bad(where, "negative stock",
            st[st["Store"] < 0][["Shipment", "Item", "Store"]].head(2).to_dict("records"))
    if len(st):
        # what arrived plus what never arrived can never exceed what was sent.
        # The reverse - a shipment part received - is normal while it is still
        # being worked through, so it is only an error once it is settled.
        over = st[st["Received"] + st["Customs"] - st["Shipped Qty"] > 0.001]
        if len(over):
            bad(where, f"{len(over)} lines account for more than was sent",
                over[["Shipment", "Item", "Shipped Qty", "Received", "Customs"]]
                .head(2).to_dict("records"))
        settled = set(cl[cl["Cleared"] == "Yes"]["Shipment"]) if len(cl) else set()
        off = st[st["Shipment"].isin(settled)
                 & ((st["Shipped Qty"] - st["Received"] - st["Customs"]).abs() > 0.001)]
        if len(off):
            bad(where, f"{len(off)} settled lines do not balance",
                off[["Shipment", "Item", "Shipped Qty", "Received", "Customs"]]
                .head(2).to_dict("records"))
        idn = st["Received"] - st["Scrap"] + st["ToSaleable"] - st["ToCourier"] \
            + st.get("CountAdj", 0) - st["Store"]
        if (idn.abs() > 0.001).any():
            bad(where, "store is not what came in less what went out")
    if len(cp) and (cp["Held"] < -0.001).any():
        bad(where, "a courier is holding a negative number")
    if len(cl) and (cl["DaysOpen"] < 0).any():
        bad(where, "a shipment has been open for a negative number of days")
    if len(st) and (st["AgeDays"] < 0).any():
        bad(where, "stock with a negative age")
    if len(m) and "Entry ID" in m.columns:
        ids = m["Entry ID"].dropna()
        if not ids.is_unique:
            bad(where, "an entry id is used twice")
    if len(m) and set(m["Movement"].dropna()) - set(engine.MV):
        bad(where, "a movement the engine does not know",
            sorted(set(m["Movement"].dropna()) - set(engine.MV)))
    return s, m, c, cfg, st, cl, cp


def try_write(fn, where, expect="ok"):
    """Run a write. expect='ok' means it must succeed, 'refused' means it must
    not. Returns the new bytes, or None."""
    try:
        out = fn()
        if expect == "refused":
            bad(where, "an illegal move was accepted")
            return out
        return out
    except Exception as ex:
        if expect == "ok":
            bad(where, "a legal move was refused", str(ex)[:90])
            return None
        return None


# ------------------------------------------------------------------ the season
def in_store(data, shipment, item):
    """What is actually in the store right now, read from the ledger rather
    than tracked by the simulator, which would drift."""
    wb = openpyxl.load_workbook(io.BytesIO(data))
    store, _, _ = entry.stock_now(wb, shipment)
    return float(store.get(item, 0))


def season(data, cfg, s0, rounds=6, seed=7, quiet=False):
    rnd = random.Random(seed)
    _say = (lambda *a: None) if quiet else say
    markets = [m for m in (cfg.get("markets") or []) ]
    couriers = cfg.get("couriers_by_market") or {}
    items = sorted((cfg.get("item_names") or {}).values())
    reasons = cfg.get("reasons") or ["Quality"]
    scrap_reasons = [r for r in reasons if r in
                     ("Quality", "Damage", "Overstay")] or [reasons[0]]
    miss_reasons = [r for r in reasons if r in
                    ("Customs", "Short shipped", "Damaged in transit",
                     "Lost in transit")] or [reasons[0]]
    ret_reasons = [r for r in reasons if r in
                   ("Customer Refused", "Customer Unavailable", "Cancelled",
                    "Wrong Address")] or [reasons[0]]
    if not items:
        say("  no items on MASTER - nothing to simulate"); return data
    steps = legal = refused = 0
    today = dt.date.today()

    for rd in range(1, rounds + 1):
        mkt = markets[(rd - 1) % len(markets)] if markets else "Qatar"
        cour = (couriers.get(mkt) or [None])[0]
        _say("")
        _say(f"  round {rd} · {mkt}")

        # --- a shipment goes out ---------------------------------------
        pick = rnd.sample(items, min(len(items), rnd.randint(3, 8)))
        sent = {it: rnd.randint(5, 120) for it in pick}
        sid = entry.next_shipment_no(data, mkt)
        arrival = today - dt.timedelta(days=rnd.randint(0, 4))
        rows = [{"Shipment No": sid, "Market": mkt, "Arrival Date": arrival,
                 "Source": "Egypt", "Item Name": it, "Shipped Qty": q}
                for it, q in sent.items()]
        new = try_write(lambda: entry.append_shipment(data, rows, "admin", mkt)[0],
                        f"round {rd} · shipment {sid}")
        steps += 1
        if new is None:
            continue
        data = new; legal += 1
        audit(data, f"round {rd} · after shipment {sid}")
        _say(f"    {sid} sent {sum(sent.values()):,} boxes of {len(sent)} items")

        # the same item twice on one shipment must be refused
        dupe = [rows[0]]
        try_write(lambda: entry.append_shipment(data, dupe, "admin", mkt)[0],
                  f"round {rd} · same item twice", expect="refused")
        refused += 1; steps += 1

        # --- it arrives, imperfectly -----------------------------------
        got, missing = {}, {}
        for it, q in sent.items():
            roll = rnd.random()
            if roll < 0.65:
                got[it] = q                       # all of it
            elif roll < 0.9:
                got[it] = max(q - rnd.randint(1, min(5, q)), 0)   # short
            else:
                got[it] = 0                       # never turned up
            missing[it] = q - got[it]
        recv = [{"Date": arrival, "Shipment No": sid, "Movement": "Received",
                 "Item Name": it, "In": v} for it, v in got.items() if v]
        if recv:
            new = try_write(lambda: entry.append_moves(data, recv, "store", mkt)[0],
                            f"round {rd} · received {sid}")
            steps += 1
            if new: data = new; legal += 1
            audit(data, f"round {rd} · after receiving {sid}")
        _say(f"    received {sum(got.values()):,}, "
            f"{sum(missing.values()):,} never arrived")

        # receiving more than was sent must be refused
        over = [{"Date": arrival, "Shipment No": sid, "Movement": "Received",
                 "Item Name": pick[0], "In": sent[pick[0]] + 10}]
        try_write(lambda: entry.append_moves(data, over, "store", mkt)[0],
                  f"round {rd} · received more than sent", expect="refused")
        refused += 1; steps += 1

        # --- the shortfall is explained --------------------------------
        miss = [{"Date": arrival, "Shipment No": sid, "Movement": "Not received",
                 "Item Name": it, "Out": v, "Reason": rnd.choice(miss_reasons)}
                for it, v in missing.items() if v]
        if miss:
            new = try_write(lambda: entry.append_moves(data, miss, "admin", mkt)[0],
                            f"round {rd} · not received {sid}")
            steps += 1
            if new: data = new; legal += 1
            audit(data, f"round {rd} · after explaining the shortfall")
            # claiming the same missing box twice must be refused
            try_write(lambda: entry.append_moves(data, [miss[0]], "admin", mkt)[0],
                      f"round {rd} · claimed a missing box twice", expect="refused")
            refused += 1; steps += 1

        # --- some of it is thrown away ---------------------------------
        for it in rnd.sample(list(got), min(2, len(got))):
            have = in_store(data, sid, it)
            if have < 2: continue
            n = rnd.randint(1, max(1, int(have) // 10))
            row = [{"Date": today, "Shipment No": sid, "Movement": "Scrap",
                    "Item Name": it, "Out": n,
                    "Reason": rnd.choice(scrap_reasons)}]
            new = try_write(lambda: entry.append_moves(data, row, "store", mkt)[0],
                            f"round {rd} · scrap {it}")
            steps += 1
            if new: data = new; legal += 1; got[it] -= n
        audit(data, f"round {rd} · after scrap")

        # scrapping more than exists must be refused
        if got:
            it = list(got)[0]
            row = [{"Date": today, "Shipment No": sid, "Movement": "Scrap",
                    "Item Name": it, "Out": int(in_store(data, sid, it)) + 500,
                    "Reason": scrap_reasons[0]}]
            try_write(lambda: entry.append_moves(data, row, "store", mkt)[0],
                      f"round {rd} · scrapped more than exists", expect="refused")
            refused += 1; steps += 1

        # --- out to the courier, and some comes back -------------------
        if cour:
            handed = {}
            for it in rnd.sample(list(got), min(3, len(got))):
                have = in_store(data, sid, it)
                if have < 2: continue
                n = rnd.randint(1, int(have))
                row = [{"Date": today, "Shipment No": sid,
                        "Movement": "To Courier", "Item Name": it,
                        "Out": n, "Courier": cour}]
                new = try_write(lambda: entry.append_moves(data, row, "store", mkt)[0],
                                f"round {rd} · to courier {it}")
                steps += 1
                if new:
                    data = new; legal += 1; got[it] -= n; handed[it] = n
            audit(data, f"round {rd} · after handing to the courier")
            _say(f"    {sum(handed.values()):,} boxes went out with {cour}")

            back = {}
            for it, n in handed.items():
                if n < 2 or rnd.random() > 0.5: continue
                k = rnd.randint(1, max(1, n // 3))
                row = [{"Date": today, "Shipment No": sid, "Movement": "Returned",
                        "Item Name": it, "In": k, "Courier": cour,
                        "Reason": rnd.choice(ret_reasons)}]
                new = try_write(lambda: entry.append_moves(data, row, "store", mkt)[0],
                                f"round {rd} · returned {it}")
                steps += 1
                if new: data = new; legal += 1; back[it] = k
            if back:
                audit(data, f"round {rd} · after returns")
                _say(f"    {sum(back.values()):,} boxes came back")

            # returning more than the courier holds must be refused
            if handed:
                it = list(handed)[0]
                row = [{"Date": today, "Shipment No": sid, "Movement": "Returned",
                        "Item Name": it, "In": 9999, "Courier": cour,
                        "Reason": ret_reasons[0]}]
                try_write(lambda: entry.append_moves(data, row, "store", mkt)[0],
                          f"round {rd} · returned more than went out",
                          expect="refused")
                refused += 1; steps += 1

            # --- returns are sorted ------------------------------------
            for it, k in back.items():
                good = rnd.randint(0, k)
                if good:
                    row = [{"Date": today, "Shipment No": sid,
                            "Movement": "Return to Saleable",
                            "Item Name": it, "In": good}]
                    new = try_write(
                        lambda: entry.append_moves(data, row, "store", mkt)[0],
                        f"round {rd} · back to saleable {it}")
                    steps += 1
                    if new: data = new; legal += 1
                left = min(k - good, int(in_store(data, sid, it)))
                if left > 0:
                    row = [{"Date": today, "Shipment No": sid,
                            "Movement": "Return to Scrap", "Item Name": it,
                            "Out": left,
                            "Reason": rnd.choice(scrap_reasons)}]
                    new = try_write(
                        lambda: entry.append_moves(data, row, "store", mkt)[0],
                        f"round {rd} · returns scrapped {it}")
                    steps += 1
                    if new: data = new; legal += 1
            audit(data, f"round {rd} · after sorting the returns")

            # sorting more than came back must be refused
            if back:
                it = list(back)[0]
                row = [{"Date": today, "Shipment No": sid,
                        "Movement": "Return to Saleable",
                        "Item Name": it, "In": 9999}]
                try_write(lambda: entry.append_moves(data, row, "store", mkt)[0],
                          f"round {rd} · sorted more than came back",
                          expect="refused")
                refused += 1; steps += 1

        # --- a mistake, then voided -------------------------------------
        if got:
            it = [x for x in got if in_store(data, sid, x) > 1]
            if it:
                it = it[0]
                row = [{"Date": today, "Shipment No": sid, "Movement": "Scrap",
                        "Item Name": it, "Out": 1, "Reason": scrap_reasons[0]}]
                before = engine.stock_by_item(*engine.load(io.BytesIO(data))[:2],
                                              cfg["as_of"])["Store"].sum()
                try:
                    data2, ids = entry.append_moves(data, row, "store", mkt)
                    data = data2; legal += 1; steps += 1
                    data = entry.void_entry(data, ids[0], "store", mkt)
                    steps += 1
                    after = engine.stock_by_item(*engine.load(io.BytesIO(data))[:2],
                                                 cfg["as_of"])["Store"].sum()
                    if abs(before - after) > 0.001:
                        bad(f"round {rd}", "voiding did not put the stock back",
                            f"{before} then {after}")
                    audit(data, f"round {rd} · after a void")
                except Exception as ex:
                    bad(f"round {rd}", "void failed", str(ex)[:80])

        # --- rubbish input ----------------------------------------------
        junk = [
            ("no such movement",
             {"Date": today, "Shipment No": sid, "Movement": "Teleport",
              "Item Name": pick[0], "In": 1}),
            ("no such shipment",
             {"Date": today, "Shipment No": "Z-99-999", "Movement": "Received",
              "Item Name": pick[0], "In": 1}),
            ("an item not on this shipment",
             {"Date": today, "Shipment No": sid, "Movement": "Received",
              "Item Name": "\u00a0nothing\u00a0", "In": 1}),
            ("in and out both filled",
             {"Date": today, "Shipment No": sid, "Movement": "Received",
              "Item Name": pick[0], "In": 1, "Out": 1}),
            ("a date before it arrived",
             {"Date": dt.date(2000, 1, 1), "Shipment No": sid,
              "Movement": "Received", "Item Name": pick[0], "In": 1}),
            ("scrap with no reason",
             {"Date": today, "Shipment No": sid, "Movement": "Scrap",
              "Item Name": pick[0], "Out": 1}),
            ("nothing at all",
             {"Date": today, "Shipment No": sid, "Movement": "Received",
              "Item Name": pick[0], "In": 0}),
        ]
        for label, row in junk:
            try_write(lambda: entry.append_moves(data, [row], "store", mkt)[0],
                      f"round {rd} · {label}", expect="refused")
            refused += 1; steps += 1
        # one bad row in a batch must write nothing at all
        n_before = len(engine.load(io.BytesIO(data))[1])
        try_write(lambda: entry.append_moves(
            data, [dict(junk[0][1]), {"Date": today, "Shipment No": sid,
                                      "Movement": "Received",
                                      "Item Name": pick[0], "In": 1}],
            "store", mkt)[0], f"round {rd} · a batch with one bad row",
            expect="refused")
        if len(engine.load(io.BytesIO(data))[1]) != n_before:
            bad(f"round {rd}", "a refused batch still wrote something")
        refused += 1; steps += 1

    _say("")
    _say(f"  {steps} actions · {legal} legal and accepted · "
        f"{refused} illegal and refused")
    return data


def two_at_once(data, cfg, s0):
    """Two people saving from the same starting copy. The second must not lose
    the first, which is what the version guard exists for."""
    mkt = (cfg.get("markets") or ["Qatar"])[0]
    s, m, c, cfg2, e = engine.load(io.BytesIO(data))
    live = s[s["Market"] == mkt]
    if not len(live):
        say("  no shipment in this market to test with"); return data
    sid = live["Shipment ID"].iloc[-1]
    item = live[live["Shipment ID"] == sid]["Item Name"].iloc[0]
    row = lambda q: [{"Date": dt.date.today(), "Shipment No": sid,
                      "Movement": "Count Adjustment - Add", "Item Name": item,
                      "In": q, "Reason": "Count Adjustment"}]
    before = len(m)
    try:
        a, _ = entry.append_moves(data, row(3), "user.a", mkt)
        b, _ = entry.append_moves(data, row(7), "user.b", mkt)   # same start
        merged, _ = entry.append_moves(a, row(7), "user.b", mkt) # b retries on a
        n = len(engine.load(io.BytesIO(merged))[1])
        if n != before + 2:
            bad("two at once", "a retry lost an entry", f"{before} then {n}")
        else:
            say(f"  both entries survive a retry: {before} rows became {n}")
        lost = len(engine.load(io.BytesIO(b))[1])
        say(f"  without the retry only {lost - before} of 2 would have landed")
        audit(merged, "two at once")
        return merged
    except Exception as ex:
        bad("two at once", "failed", str(ex)[:90]); return data


_ORIGINAL = {"data": None}
def _fresh():
    return _ORIGINAL["data"]


def main():
    head("0 · THE COPY")
    try:
        import sharepoint_loader as sp
        buf, meta = sp.fetch_workbook()
        data = buf.getvalue()
        say(f"  {meta['name']} · {meta['size_kb']} KB · saved {meta['modified']}")
        say("  working on a copy in memory. The live workbook is never written.")
    except Exception as ex:
        say(f"  could not read SharePoint: {ex}")
        try:
            import qa_book
            path = qa_book.book()
        except Exception:
            local = sorted(f for f in os.listdir(".") if f.endswith(".xlsx"))
            if not local:
                say("  and no workbook here either - stopping."); return 1
            path = local[0]
        data = open(path, "rb").read()
        say(f"  using {path} instead")

    _ORIGINAL["data"] = data
    s0, m0, c0, cfg, e0 = engine.load(io.BytesIO(data))
    st0 = engine.stock_by_item(s0, m0, cfg["as_of"])
    say(f"  starting from {len(s0)} shipment lines, {len(m0)} movements, "
        f"{float(st0['Store'].sum()):,.0f} boxes")

    head("1 · THE LEDGER AS IT STANDS")
    audit(data, "before anything")
    say(f"  {'clean' if not FAIL else str(len(FAIL)) + ' problems already'}")

    head("2 · A SEASON OF REAL WORK")
    data = season(data, cfg, s0)

    head("3 · TWO PEOPLE AT ONCE")
    data = two_at_once(data, cfg, s0)

    head("4 · WHERE IT ENDED UP")
    r = audit(data, "at the end")
    if r:
        s, m, c, cfg2, st, cl, cp = r
        say(f"  {len(s)} shipment lines · {len(m)} movements")
        say(f"  {float(st['Store'].sum()):,.0f} boxes in store")
        say(f"  {float(cp['Held'].sum()) if len(cp) else 0:,.0f} with couriers")
        say(f"  {int((cl['Cleared']=='No').sum())} shipments still open")
        say(f"  movement types used: {sorted(set(m['Movement'].dropna()))}")
        rows = m[m["Entered by"].notna()] if "Entered by" in m.columns else m
        say(f"  {len(rows)} rows carry who entered them")

    head("5 · THE SAME SEASON, FIVE MORE TIMES")
    say("  a different order of events each time, to find what one run misses")
    base_fail = len(FAIL)
    for sd in (11, 23, 42, 99, 137):
        before = len(FAIL)
        d = season(_fresh(), cfg, s0, rounds=4, seed=sd, quiet=True)
        d = two_at_once(d, cfg, s0)
        audit(d, f"seed {sd} · at the end")
        n = len(FAIL) - before
        say(f"  seed {sd:<5} {'clean' if not n else str(n) + ' problems'}")

    head("6 · VERDICT")
    if not FAIL:
        say("  Nothing broke. Every legal action was accepted, every illegal")
        say("  one refused, and the ledger held after every single step.")
    else:
        say(f"  {len(FAIL)} problems:")
        for where, what, detail in FAIL[:40]:
            say(f"    {where}: {what}  {detail}")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        say(""); say("the simulation itself crashed:")
        say(traceback.format_exc()[-1500:])
        code = 1
    open("simulate.txt", "w").write("\n".join(OUT))
    print(f"\n\nwritten to simulate.txt · {len(OUT)} lines", file=sys.stderr)
    sys.exit(code)
