# -*- coding: utf-8 -*-
"""Show every shipment line where received does not match what was shipped."""
import io, sys
import engine

def report(data_or_path):
    s, m, c, cfg, e = engine.load(data_or_path)
    st = engine.stock_by_item(s, m, cfg["as_of"])
    nm = cfg.get("item_names") or {}
    st = st.copy()
    if "ItemName" not in st.columns:
        st["ItemName"] = st["Item"].map(lambda x: nm.get(x, x))
    st["Gap"] = st["Shipped Qty"] - st["Received"] - st["Customs"]
    bad = st[st["Gap"].abs() > 0.001].copy()
    print(f"{len(st)} shipment lines · {len(bad)} do not balance\n")
    if not len(bad):
        print("  Everything balances: shipped = received + customs on every line.")
        return
    print(f"  {'SHIPMENT':<10} {'ITEM':<22} {'SHIPPED':>8} {'RECEIVED':>9} "
          f"{'CUSTOMS':>8} {'GAP':>8}")
    for _, r in bad.sort_values("Gap").iterrows():
        print(f"  {str(r['Shipment']):<10} {str(r['ItemName'])[:21]:<22} "
              f"{r['Shipped Qty']:>8,.0f} {r['Received']:>9,.0f} "
              f"{r['Customs']:>8,.0f} {r['Gap']:>8,.0f}")
    print(f"\n  A negative gap means more was received than was ever shipped.")
    print(f"  Either the shipped figure is too low, or a movement was typed wrong.")
    mv = m[m["Shipment"].isin(set(bad["Shipment"]))]
    mv = mv[mv["Movement"].isin(["Received", "Not received"])]
    if len(mv):
        print(f"\n  The movements behind them:")
        cols = [x for x in ["Date","Shipment","Movement","Item Name","Qty",
                            "Entered by","Entry ID"] if x in mv.columns]
        for _, r in mv[cols].iterrows():
            print("   ", "  ".join(f"{str(r[c])[:18]:<18}" for c in cols))

if __name__ == "__main__":
    if "--live" in sys.argv:
        import sharepoint_loader as sp
        buf, meta = sp.fetch_workbook()
        print(f"{meta['name']} · saved {meta['modified']}\n")
        report(io.BytesIO(buf.getvalue()))
    else:
        import qa_book
        report(qa_book.book())
