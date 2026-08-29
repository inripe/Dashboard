# -*- coding: utf-8 -*-
"""
Everything a test session left behind, in one file.

    python3 extract.py                  today
    python3 extract.py --days 7         the last week
    python3 extract.py --shipment Q-26-003    one shipment, start to finish

Writes extract.txt. Send me that file.

Reads only. It pulls the audit trail, walks each shipment from what was sent
to what is left, and checks the arithmetic at every step - so a test can be
judged on what reached the ledger rather than on what anybody remembers.
"""
import sys, io
import pandas as pd

OUT = []
def say(*a):
    line = " ".join(str(x) for x in a); OUT.append(line); print(line)
def head(t):
    say(""); say("=" * 72); say(t); say("=" * 72)


def main():
    days = 1
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    only = None
    if "--shipment" in sys.argv:
        only = sys.argv[sys.argv.index("--shipment") + 1].strip()
        days = 3650

    import engine, sharepoint_loader as sp
    buf, meta = sp.fetch_workbook()
    data = buf.getvalue()
    s, m, c, cfg, e = engine.load(io.BytesIO(data))
    st = engine.stock_by_item(s, m, cfg["as_of"])
    cl = engine.clearance_by_shipment(s, m, cfg["as_of"], cfg)
    cp = engine.courier_positions(s, m, cfg["as_of"], cfg)
    nm = cfg.get("item_names") or {}
    name = lambda r: r.get("Item Name") or nm.get(r.get("Item", ""), r.get("Item", ""))

    head("0 · THE FILE")
    say(f"  {meta['name']} · saved {meta['modified']} · {meta['size_kb']} KB")
    say(f"  {len(s)} shipment lines · {len(m)} movements · {len(e)} entry errors")

    mm = m.copy()
    if "Entered at" in mm.columns:
        mm["Entered at"] = pd.to_datetime(mm["Entered at"], errors="coerce")
        cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days - 1)
        recent = mm[mm["Entered at"] >= cutoff]
    else:
        recent = mm.iloc[0:0]
    if only:
        recent = recent[recent["Shipment"] == only]
        ships = [only]
    else:
        ships = sorted(set(recent["Shipment"].dropna())) or \
            sorted(set(s["Shipment ID"]))[-3:]

    head(f"1 · WHAT WAS ENTERED  ·  {'shipment ' + only if only else f'last {days} day(s)'}")
    if not len(recent):
        say("  nothing entered through the app")
    else:
        say(f"  {'WHEN':<12}{'WHO':<14}{'MOVEMENT':<24}{'ITEM':<24}"
            f"{'QTY':>5}  {'ENTRY ID':<18}VOID")
        for _, r in recent.sort_values("Entered at").iterrows():
            say(f"  {r['Entered at']:%d %b %H:%M}  "
                f"{str(r.get('Entered by') or ''):<14}"
                f"{str(r.get('Movement') or ''):<24}{str(name(r))[:23]:<24}"
                f"{float(r.get('Qty') or 0):>5,.0f}  "
                f"{str(r.get('Entry ID') or ''):<18}"
                f"{'yes' if str(r.get('Void') or '').lower()=='yes' else ''}")
        say("")
        say("  by person   : " + ", ".join(
            f"{k} {v}" for k, v in recent.groupby(
                recent['Entered by'].astype(str)).size().items()))
        say("  by movement : " + ", ".join(
            f"{k} {v}" for k, v in recent.groupby(
                recent['Movement'].astype(str)).size().items()))
        say(f"  voided      : "
            f"{int((recent['Void'].astype(str).str.lower()=='yes').sum())}")

    head("2 · EACH SHIPMENT, START TO FINISH")
    for sid in ships:
        sub = st[st["Shipment"] == sid]
        if not len(sub):
            continue
        row = cl[cl["Shipment"] == sid]
        say("")
        say(f"  {sid}  ·  {sub['Market'].iloc[0]}  ·  arrived "
            f"{pd.Timestamp(sub['Arrival Date'].iloc[0]):%d %b}"
            + (f"  ·  {row['Cleared'].iloc[0] == 'Yes' and 'cleared' or 'open'}"
               if len(row) else ""))
        say(f"    {'ITEM':<24}{'SENT':>6}{'GOT':>6}{'MISSING':>8}"
            f"{'SCRAP':>7}{'TO COURIER':>11}{'BACK':>6}{'LEFT':>7}")
        for _, r in sub.sort_values("Item").iterrows():
            say(f"    {str(name(r))[:23]:<24}{float(r['Shipped Qty']):>6,.0f}"
                f"{float(r['Received']):>6,.0f}{float(r['Customs']):>8,.0f}"
                f"{float(r['Scrap']):>7,.0f}{float(r['ToCourier']):>11,.0f}"
                f"{float(r.get('ToSaleable', 0)):>6,.0f}{float(r['Store']):>7,.0f}")
        tot = sub[["Shipped Qty", "Received", "Customs", "Scrap",
                   "ToCourier", "Store"]].sum()
        say(f"    {'total':<24}{tot['Shipped Qty']:>6,.0f}{tot['Received']:>6,.0f}"
            f"{tot['Customs']:>8,.0f}{tot['Scrap']:>7,.0f}"
            f"{tot['ToCourier']:>11,.0f}{'':>6}{tot['Store']:>7,.0f}")
        gap = tot["Shipped Qty"] - tot["Received"] - tot["Customs"]
        say(f"    sent {tot['Shipped Qty']:,.0f} = received {tot['Received']:,.0f}"
            f" + never arrived {tot['Customs']:,.0f}"
            + ("   ok" if abs(gap) < 0.001 else f"   OUT BY {gap:,.0f}"))
        left = tot["Received"] - tot["Scrap"] - tot["ToCourier"] \
            + float(sub.get("ToSaleable", pd.Series([0])).sum()) \
            + float(sub.get("CountAdj", pd.Series([0])).sum())
        say(f"    left {tot['Store']:,.0f} = received less scrap "
            f"less to courier plus returns"
            + ("   ok" if abs(left - tot["Store"]) < 0.001
               else f"   OUT BY {tot['Store'] - left:,.0f}"))

    head("3 · WHERE EVERYTHING STANDS")
    for mkt in sorted(set(st["Market"].dropna())):
        sub = st[st["Market"] == mkt]
        held = float(cp[cp["Market"] == mkt]["Held"].sum()) if len(cp) else 0
        say(f"  {mkt:<8}{float(sub['Store'].sum()):>8,.0f} in store   "
            f"{held:>6,.0f} with couriers   "
            f"{float(sub['Store'].sum()) + held:>8,.0f} still ours")

    head("4 · DOES IT ADD UP")
    checks = [
        ("no negative stock", int((st["Store"] < -0.001).sum())),
        ("nothing accounted for beyond what was sent",
         int((st["Received"] + st["Customs"] - st["Shipped Qty"] > 0.001).sum())),
        ("no courier holding a negative number",
         int((cp["Held"] < -0.001).sum()) if len(cp) else 0),
        ("no negative age", int((st["AgeDays"] < 0).sum())),
        ("no negative days open", int((cl["DaysOpen"] < 0).sum())),
        ("every entry carries an id",
         int(recent["Entry ID"].isna().sum()) if len(recent) else 0),
        ("every entry says who made it",
         int(recent["Entered by"].isna().sum()) if len(recent) else 0),
        ("no entry errors in the workbook", len(e)),
    ]
    for label, n in checks:
        say(f"  {'ok  ' if not n else 'LOOK'}  {label}" + (f"  ({n})" if n else ""))
    bad = sum(n for _, n in checks)
    say("")
    say("  Everything adds up." if not bad else f"  {bad} things to look at.")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as ex:
        say(f"\nfailed: {ex}"); code = 1
    open("extract.txt", "w").write("\n".join(OUT))
    print("\n\nwritten to extract.txt · send me that file", file=sys.stderr)
    sys.exit(code)
