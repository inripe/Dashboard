# -*- coding: utf-8 -*-
"""
Which SKU each product carries in each store.

    python3 sku_map.py

Reads only. Shows one row per product and the code each market uses, so a
market that codes things its own way is visible at a glance.
"""
import sys, io


def main():
    import shopify_reader as sr
    try:
        import engine, qa_book
        cfg = engine.load(qa_book.book())[3]
    except Exception:
        import sharepoint_loader as sp, engine
        buf, _ = sp.fetch_workbook()
        cfg = engine.load(io.BytesIO(buf.getvalue()))[3]
    on_master = {v.strip(): k for k, v in (cfg.get("item_names") or {}).items()}

    markets = sr.configured_markets()
    seen = {}
    for mkt in markets:
        try:
            orders, _ = sr.fetch_orders(mkt, limit_pages=10)
        except Exception as e:
            print(f"  {mkt}: could not read - {e}"); continue
        for o in orders:
            for ln in o.get("lines", []):
                t = (ln.get("title") or "").strip()
                if not t:
                    continue
                d = seen.setdefault(t, {})
                if ln.get("sku"):
                    d.setdefault(mkt, set()).add(ln["sku"].strip())

    w = max((len(t) for t in seen), default=10) + 2
    print()
    print(f"{'PRODUCT':<{w}}{'ON MASTER':<26}" +
          "".join(f"{m:<26}" for m in markets))
    print("-" * (w + 26 + 26 * len(markets)))
    differs, missing = [], []
    for t in sorted(seen):
        row = f"{t:<{w}}{on_master.get(t, '— not on MASTER —'):<26}"
        codes = set()
        for m in markets:
            v = seen[t].get(m)
            cell = ", ".join(sorted(v)) if v else "·"
            codes |= (v or set())
            row += f"{cell:<26}"
        print(row)
        if len(codes) > 1:
            differs.append((t, codes))
        if t not in on_master and codes:
            missing.append((t, sorted(codes)[0]))

    print()
    if differs:
        print("CODED DIFFERENTLY IN DIFFERENT STORES")
        for t, codes in differs:
            print(f"  {t}: {', '.join(sorted(codes))}")
    else:
        print("Every product uses the same code everywhere it is sold.")
    if missing:
        print()
        print("SOLD BUT NOT ON MASTER")
        for t, c in missing:
            print(f"  {t:<30}{c}")
    print()
    print("A product with no SKU in a store shows as ·  — the order line")
    print("carried no code, usually because it was placed before one was set.")


if __name__ == "__main__":
    main()
