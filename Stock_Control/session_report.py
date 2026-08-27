# -*- coding: utf-8 -*-
"""
What actually happened in the app.

    python3 session_report.py           today
    python3 session_report.py --days 3  the last three days

Writes session.txt. Send me that file.

It reads the audit trail the app already keeps - who entered what, when, and
what it did to the stock - so a test does not depend on anybody remembering.
"""
import sys, io
import datetime as dt
import pandas as pd

OUT = []
def say(*a):
    line = " ".join(str(x) for x in a); OUT.append(line); print(line)


def main():
    days = 1
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    import engine
    try:
        import sharepoint_loader as sp
        buf, meta = sp.fetch_workbook()
        data = buf.getvalue()
        say(f"{meta['name']} · saved {meta['modified']}")
    except Exception as ex:
        say(f"could not read SharePoint: {ex}"); return 1

    s, m, c, cfg, e = engine.load(io.BytesIO(data))
    st = engine.stock_by_item(s, m, cfg["as_of"])
    cl = engine.clearance_by_shipment(s, m, cfg["as_of"], cfg)
    cp = engine.courier_positions(s, m, cfg["as_of"], cfg)
    nm = cfg.get("item_names") or {}

    if "Entered at" not in m.columns:
        say("this workbook has no audit trail"); return 1
    mm = m.copy()
    mm["Entered at"] = pd.to_datetime(mm["Entered at"], errors="coerce")
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days - 1)
    recent = mm[mm["Entered at"] >= cutoff].sort_values("Entered at")

    say("")
    say("=" * 70)
    say(f"WHAT WAS ENTERED  ·  last {days} day{'s' if days > 1 else ''}")
    say("=" * 70)
    if not len(recent):
        say("  nothing entered through the app in that time")
    else:
        say(f"  {'TIME':<7}{'WHO':<14}{'MOVEMENT':<22}{'ITEM':<22}"
            f"{'QTY':>5}  {'SHIPMENT':<12}{'ID':<18}VOID")
        for _, r in recent.iterrows():
            item = r.get("Item Name") or nm.get(r.get("Item", ""), "")
            say(f"  {r['Entered at']:%H:%M}  {str(r.get('Entered by') or ''):<14}"
                f"{str(r.get('Movement') or ''):<22}{str(item)[:21]:<22}"
                f"{float(r.get('Qty') or 0):>5,.0f}  "
                f"{str(r.get('Shipment') or ''):<12}"
                f"{str(r.get('Entry ID') or ''):<18}"
                f"{'yes' if str(r.get('Void') or '').lower()=='yes' else ''}")
        say("")
        by_who = recent.groupby(recent["Entered by"].astype(str)).size()
        say("  by person: " + ", ".join(f"{k} {v}" for k, v in by_who.items()))
        by_mv = recent.groupby(recent["Movement"].astype(str)).size()
        say("  by movement: " + ", ".join(f"{k} {v}" for k, v in by_mv.items()))
        voided = int((recent["Void"].astype(str).str.lower() == "yes").sum()) \
            if "Void" in recent.columns else 0
        say(f"  voided: {voided}")

    say("")
    say("=" * 70)
    say("WHERE THE STOCK STANDS NOW")
    say("=" * 70)
    for mkt in sorted(set(st["Market"].dropna())):
        sub = st[st["Market"] == mkt]
        say(f"  {mkt:<8}{float(sub['Store'].sum()):>8,.0f} boxes in store   "
            f"{float(cp[cp['Market']==mkt]['Held'].sum()) if len(cp) else 0:>6,.0f} with couriers")
    say("")
    say(f"  {'SHIPMENT':<12}{'ITEM':<24}{'SENT':>6}{'GOT':>6}"
        f"{'MISSING':>8}{'SCRAP':>7}{'OUT':>6}{'STORE':>7}")
    for _, r in st.sort_values(["Shipment", "Item"]).iterrows():
        if float(r["Shipped Qty"]) == 0 and float(r["Store"]) == 0:
            continue
        item = r.get("ItemName") or nm.get(r["Item"], r["Item"])
        say(f"  {str(r['Shipment']):<12}{str(item)[:23]:<24}"
            f"{float(r['Shipped Qty']):>6,.0f}{float(r['Received']):>6,.0f}"
            f"{float(r['Customs']):>8,.0f}{float(r['Scrap']):>7,.0f}"
            f"{float(r['ToCourier']):>6,.0f}{float(r['Store']):>7,.0f}")

    say("")
    say("=" * 70)
    say("DOES IT ADD UP")
    say("=" * 70)
    checks = [
        ("no negative stock", int((st["Store"] < -0.001).sum())),
        ("nothing accounted for beyond what was sent",
         int((st["Received"] + st["Customs"] - st["Shipped Qty"] > 0.001).sum())),
        ("no courier holding a negative number",
         int((cp["Held"] < -0.001).sum()) if len(cp) else 0),
        ("no negative age", int((st["AgeDays"] < 0).sum())),
        ("every entry has an id",
         int(recent["Entry ID"].isna().sum()) if len(recent) else 0),
        ("no entry errors in the workbook", len(e)),
    ]
    for label, n in checks:
        say(f"  {'ok  ' if not n else 'LOOK'}  {label}"
            + (f"  ({n})" if n else ""))
    say("")
    say(f"  {int((cl['Cleared']=='No').sum())} shipments still open")
    bad = sum(n for _, n in checks)
    say("")
    say("  Everything adds up." if not bad
        else f"  {bad} things to look at above.")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as ex:
        say(f"\nfailed: {ex}"); code = 1
    open("session.txt", "w").write("\n".join(OUT))
    print(f"\n\nwritten to session.txt · send me that file", file=sys.stderr)
    sys.exit(code)
