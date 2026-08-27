# -*- coding: utf-8 -*-
"""
Which products have no SKU, per store.

    python3 no_sku.py

An order line with no SKU cannot be matched to your stock, so the order can
never be dispatched. This lists the products to fix, how many orders each is
blocking, and whether the name already matches an item on MASTER.

Reads only. Nothing is written to Shopify or the workbook.
"""
import sys, io
import shopify_reader as sr


def main():
    try:
        import engine, qa_book
        cfg = engine.load(qa_book.book())[3]
    except Exception:
        import sharepoint_loader as sp, engine
        buf, _ = sp.fetch_workbook()
        cfg = engine.load(io.BytesIO(buf.getvalue()))[3]
    names = cfg.get("item_names") or {}          # code -> name
    by_name = {v.strip().lower(): k for k, v in names.items()}

    for mkt in sr.configured_markets():
        print()
        print("=" * 66)
        print(f"{mkt}")
        print("=" * 66)
        try:
            orders, trunc = sr.fetch_orders(mkt, limit_pages=10)
        except Exception as e:
            print(f"  could not read: {e}"); continue

        blocked, seen = {}, 0
        for o in orders:
            hit = False
            for ln in o.get("lines", []):
                if not ln.get("sku"):
                    title = (ln.get("title") or "(no name)").strip()
                    d = blocked.setdefault(title, {"lines": 0, "orders": set()})
                    d["lines"] += 1
                    d["orders"].add(o["name"])
                    hit = True
            seen += 1 if hit else 0

        if not blocked:
            print(f"  every product has a SKU. {len(orders)} orders read.")
            continue

        print(f"  {len(blocked)} products with no SKU, blocking {seen} of "
              f"{len(orders)} orders read"
              + ("  (more pages exist)" if trunc else ""))
        print()
        print(f"  {'PRODUCT':<34}{'ORDERS':>7}   SUGGESTED SKU FROM MASTER")
        for title, d in sorted(blocked.items(), key=lambda x: -len(x[1]["orders"])):
            code = by_name.get(title.lower())
            if not code:
                for nm_, cd in by_name.items():
                    if nm_ in title.lower() or title.lower() in nm_:
                        code = cd; break
            print(f"  {title[:33]:<34}{len(d['orders']):>7}   "
                  f"{code or 'not on MASTER - add the item first'}")
        print()
        print(f"  Shopify admin for {mkt} → Products → open each one →")
        print(f"  Variants → SKU → paste the code above → Save.")

    print()
    print("A product not on MASTER needs adding to the item list first, "
          "otherwise\nthe SKU will match nothing.")


if __name__ == "__main__":
    main()
