# -*- coding: utf-8 -*-
"""
Load the history from the colleague's own sheet.

    python3 import_history.py history.csv            show what it would write
    python3 import_history.py history.csv --apply    write it

Her sheet, one row per item per day:

  Item | Date | Warehouse | Source | Old Stock | Sh Quantity | Different |
  Shipment Stock | Scrap | Ofd | Return | Delivered | All Stock | Shipment Code

What each column becomes:

  Sh Quantity      PO Qty on SHIPMENTS - what was ordered
  Shipment Stock   Shipped Qty, and a Received movement. Nobody recorded what
                   actually left, so for the history the two are the same.
  Scrap            Scrap out
  Ofd              To Courier out
  Return           Returned in
  Old Stock        on the first day only, a Count Adjustment - Add, because
                   that stock came from a shipment nobody tracked
  Delivered        not entered - it is what the courier took and kept
  All Stock        not entered - it is worked out

Nothing is written until --apply, and every line is checked first.
"""
import sys, io, csv, re, unicodedata, warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import datetime as dt
from collections import defaultdict

# every way each market is written in her sheets and codes
MARKET = {"UAE": "UAE", "QATAR": "Qatar", "QTR": "Qatar",
          "KSA": "KSA", "SAUDI": "KSA", "SAUDIA": "KSA",
          "EGYPT": "Egypt", "EG": "Egypt", "EGY": "Egypt"}

# her spellings against the names on MASTER. Anything not here and not an
# exact match is reported rather than guessed at.
ALIASES = {
    "graps banati": "Grapes Banati",
    "graps red": "Grapes Red",
    "guave banati": "Guava Banati",
    "mango timor": "Mango Timour",
    "prickly pear": "Fig Shouki",
    "graps white": "Grapes White",
    "cantaloup": "Cantaloupe",
    "guave banati": "Guava Banati",
}
LETTER = {"Qatar": "Q", "UAE": "U", "KSA": "K", "Egypt": "E"}


def clean(x):
    """Her numbers carry spaces, commas and brackets for negatives."""
    s = str(x or "").strip().replace(",", "").replace("\u00a0", " ").strip()
    if not s or s in ("-", "—"):
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


def strip_flags(x):
    """Warehouse reads 'UAE \U0001F1E6\U0001F1EA', and saving as CSV can turn
    the flag into '????'. Keep only the letters."""
    s = "".join(c for c in str(x or "")
                if unicodedata.category(c) not in ("So", "Cf"))
    s = re.sub(r"[^A-Za-z ]+", " ", s)
    return " ".join(s.split()).strip()


def parse_date(x, year):
    """Her dates read '8-May' with no year. The year comes from the shipment
    code, which carries it."""
    s = str(x or "").strip()
    for f in ("%d-%b", "%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d",
              "%d/%m/%y", "%d-%m-%Y", "%d %b %Y", "%d %b"):
        try:
            d = dt.datetime.strptime(s, f)
            if "%y" not in f.lower() or f in ("%d-%b", "%d %b"):
                d = d.replace(year=year)
            return d.date()
        except ValueError:
            continue
    return None


def our_code(theirs, market):
    """2026-UAE-08-028 becomes U-26-08-028."""
    m = re.match(r"(\d{4})-([A-Za-z]+)-(\d{2})-(\d+)", str(theirs or "").strip())
    if m:
        yr, mk, mo, n = m.groups()
        return f"{LETTER.get(MARKET.get(mk.upper(), mk), 'X')}-{yr[2:]}-{mo}-{int(n):03d}"
    return str(theirs or "").strip()


def read(path, names):
    """Her rows, cleaned and mapped. Returns rows and anything unrecognised.

    The last day of a file is sometimes pasted twice - the same item, date and
    shipment appearing as two identical rows. Counting it twice would double
    that day's scrap and handovers, so an exact repeat is dropped and
    reported."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096); f.seek(0)
        delim = "\t" if sample.count("\t") > sample.count(",") else ","
        rows = list(csv.DictReader(f, delimiter=delim))
    out, unknown, matched, dupes = [], set(), {}, []
    seen_rows = set()
    lower = {n.strip().lower(): n for n in names}
    for r in rows:
        r = {(k or "").strip(): v for k, v in r.items()}
        item = str(r.get("Item") or "").strip()
        if not item:
            continue
        wh = strip_flags(r.get("Warehouse")).upper()
        mk = MARKET.get(wh)
        if not mk:
            for word in wh.split():
                if word in MARKET:
                    mk = MARKET[word]; break
        code = str(r.get("Shipment Code") or "").strip()
        year = 2026
        m = re.match(r"(\d{4})", code)
        if m:
            year = int(m.group(1))
        key = item.lower().strip()
        name = lower.get(key) or lower.get(ALIASES.get(key, "").lower())
        if not name:
            # a near miss is worth offering rather than silently skipping
            import difflib
            near = difflib.get_close_matches(item, names, n=1, cutoff=0.82)
            if near:
                name = near[0]
                matched.setdefault(item, name)
            else:
                unknown.add(item)
        sig = (item, str(r.get("Date") or "").strip(), code,
               str(r.get("Old Stock")), str(r.get("Shipment Stock")),
               str(r.get("Scrap")), str(r.get("Ofd")), str(r.get("Return")))
        if sig in seen_rows:
            dupes.append(sig)
            continue
        seen_rows.add(sig)
        out.append({
            "their_item": item, "item": name, "market": mk,
            "date": parse_date(r.get("Date"), year),
            "source": str(r.get("Source") or "").strip() or "Egypt",
            "old": clean(r.get("Old Stock")),
            "po": clean(r.get("Sh Quantity")),
            "received": clean(r.get("Shipment Stock")),
            "scrap": clean(r.get("Scrap")),
            "ofd": clean(r.get("Ofd")),
            "ret": clean(r.get("Return")),
            "allstock": clean(r.get("All Stock")),
            "code": our_code(code, mk), "their_code": code,
        })
    return out, sorted(unknown), matched, dupes


def build(rows, courier_of):
    """Turn her rows into shipment lines and movements.

    Her sheet tracks stock per item: Old Stock carries from day to day, and a
    movement is filed under whichever shipment was open that day. Ours tracks
    it per shipment. Rather than guessing which shipment a box came from, each
    movement keeps the code she gave it - and where her book had stock ours
    has not seen, the difference is written as a count adjustment, in the
    open, before the movement that needs it.
    """
    rows = sorted(rows, key=lambda r: (r["date"] or dt.date(1900, 1, 1),
                                       r["code"], r["their_item"]))
    ships, moves, notes = {}, [], []
    store = {}          # (code, item) -> boxes we have accounted for
    courier = {}        # (code, item) -> boxes with the courier
    seen_item = set()
    adjust = 0

    def top_up(key, need, date, why):
        """Make sure the shipment holds enough, and say so if it did not."""
        nonlocal adjust
        have = store.get(key, 0.0)
        if have >= need - 0.001:
            return
        short = round(need - have, 3)
        moves.append({"Date": date, "Shipment No": key[0],
                      "Movement": "Count Adjustment - Add",
                      "Item Name": key[1], "In": short,
                      "Reason": "Count Adjustment", "Note": why})
        store[key] = have + short
        adjust += 1

    for r in rows:
        if not r["item"] or not r["market"] or not r["date"]:
            continue
        key = (r["code"], r["item"])

        if r["received"] and key not in ships:
            ships[key] = {"Shipment No": r["code"], "Market": r["market"],
                          "Arrival Date": r["date"], "Source": r["source"],
                          "Item Name": r["item"],
                          "Shipped Qty": r["received"], "PO Qty": r["po"]}
            if r["po"] and r["po"] != r["received"]:
                notes.append(f"{r['code']} {r['item']}: ordered {r['po']:.0f}, "
                             f"{r['received']:.0f} arrived")

        # her opening stock, once per item
        if r["item"] not in seen_item and r["old"]:
            moves.append({"Date": r["date"], "Shipment No": r["code"],
                          "Movement": "Count Adjustment - Add",
                          "Item Name": r["item"], "In": r["old"],
                          "Reason": "Count Adjustment",
                          "Note": "opening balance, not tracked before"})
            store[key] = store.get(key, 0.0) + r["old"]
        seen_item.add(r["item"])

        if r["received"]:
            moves.append({"Date": r["date"], "Shipment No": r["code"],
                          "Movement": "Received", "Item Name": r["item"],
                          "In": r["received"]})
            store[key] = store.get(key, 0.0) + r["received"]

        if r["scrap"]:
            top_up(key, r["scrap"], r["date"],
                   "stock her sheet held that ours had not seen")
            moves.append({"Date": r["date"], "Shipment No": r["code"],
                          "Movement": "Scrap", "Item Name": r["item"],
                          "Out": r["scrap"], "Reason": "Quality"})
            store[key] -= r["scrap"]

        if r["ofd"]:
            top_up(key, r["ofd"], r["date"],
                   "stock her sheet held that ours had not seen")
            moves.append({"Date": r["date"], "Shipment No": r["code"],
                          "Movement": "To Courier", "Item Name": r["item"],
                          "Out": r["ofd"],
                          "Courier": courier_of.get(r["market"])})
            store[key] -= r["ofd"]
            courier[key] = courier.get(key, 0.0) + r["ofd"]

        if r["ret"]:
            # by now the day's handover has been recorded, so the courier
            # usually holds enough. Only where it does not - a return from a
            # handover before her file begins - is one reconstructed.
            top_up_courier = r["ret"] - courier.get(key, 0.0)
            if top_up_courier > 0.001:
                top_up(key, top_up_courier, r["date"],
                       "sent out before this sheet begins")
                moves.append({"Date": r["date"], "Shipment No": r["code"],
                              "Movement": "To Courier", "Item Name": r["item"],
                              "Out": round(top_up_courier, 3),
                              "Courier": courier_of.get(r["market"]),
                              "Note": "reconstructed: a return needs a handover"})
                store[key] -= top_up_courier
                courier[key] = courier.get(key, 0.0) + top_up_courier
            moves.append({"Date": r["date"], "Shipment No": r["code"],
                          "Movement": "Returned", "Item Name": r["item"],
                          "In": r["ret"],
                          "Courier": courier_of.get(r["market"]),
                          "Reason": "Other Return"})
            courier[key] = courier.get(key, 0.0) - r["ret"]
            store[key] = store.get(key, 0.0) + r["ret"]

    if adjust:
        notes.append(f"{adjust} count adjustments were needed where her book "
                     f"held stock this one had not seen")
    return list(ships.values()), moves, notes


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__); return 1
    path = args[0]
    apply = "--apply" in sys.argv
    import sharepoint_loader as sp, engine, entry
    buf, meta = sp.fetch_workbook()
    data = buf.getvalue()
    s0, m0, c0, cfg, e0 = engine.load(io.BytesIO(data))
    names = list((cfg.get("item_names") or {}).values())
    courier_of = {k: (v or [None])[0]
                  for k, v in (cfg.get("couriers_by_market") or {}).items()}

    rows, unknown, matched, dupes = read(path, names)
    print(f"{path}: {len(rows)} rows read")
    if dupes:
        print(f"  {len(dupes)} identical rows dropped - the same item, date "
              f"and shipment twice over")
        for d in dupes[:3]:
            print(f"    {d[0]} on {d[1]} in {d[2]}")
    print()
    if matched:
        print("SPELLINGS MATCHED TO MASTER  - check these are right")
        for k, v in sorted(matched.items()):
            print(f"  {k:<26} -> {v}")
        print()
    if unknown:
        # count what each one is worth, so the decision to add or ignore is
        # made against how much history it carries
        weight = {}
        for r in rows:
            if r["their_item"] in unknown:
                d = weight.setdefault(r["their_item"],
                                      {"rows": 0, "boxes": 0.0, "codes": set()})
                d["rows"] += 1
                d["boxes"] += r["received"]
                d["codes"].add(r["their_code"])
        print("ITEMS NOT ON MASTER  - these rows would be skipped")
        print(f"  {'ITEM':<26}{'ROWS':>6}{'BOXES':>8}  SHIPMENTS")
        for u in sorted(unknown, key=lambda x: -weight.get(x, {}).get("boxes", 0)):
            d = weight.get(u, {"rows": 0, "boxes": 0, "codes": set()})
            print(f"  {u[:25]:<26}{d['rows']:>6}{d['boxes']:>8,.0f}"
                  f"  {len(d['codes'])}")
        print("  Add them to MASTER, or add a spelling to ALIASES in this file.")
        print()
    bad_mkt = sorted({r["their_item"] for r in rows if not r["market"]})
    if bad_mkt:
        print(f"  {len(bad_mkt)} rows with an unrecognised warehouse\n")

    ships, moves, notes = build(rows, courier_of)
    print(f"WOULD WRITE")
    print(f"  {len(ships)} shipment lines")
    print(f"  {len(moves)} movements")
    by = defaultdict(int)
    for mv in moves:
        by[mv["Movement"]] += 1
    for k in sorted(by):
        print(f"    {by[k]:>4}  {k}")
    codes = sorted({s_["Shipment No"] for s_ in ships})
    print(f"  shipments: {', '.join(codes[:8])}"
          + (" …" if len(codes) > 8 else ""))
    adj = sum(1 for mv in moves
              if mv["Movement"].startswith("Count Adjustment"))
    if adj:
        opening = sum(1 for mv in moves
                      if "opening balance" in str(mv.get("Note", "")))
        print(f"\n  {adj} count adjustments")
        print(f"    {opening} opening balances - stock she already had when "
              f"her sheet begins")
        print(f"    {adj - opening} where her book held stock this one had "
              f"not seen")
        print( "    Both are recorded with a note saying which, so they can "
               "be told apart later.")
    po = [n for n in notes if "ordered" in n]
    if po:
        print(f"\n  {len(po)} lines where the order and the arrival differ:")
        for n in po[:8]:
            print(f"    {n}")

    if not apply:
        print("\nNothing was written. Run again with --apply.")
        return 0

    out = data
    out, made = entry.append_shipment(out, ships, "manual", ships[0]["Market"])
    print(f"\n  {len(ships)} shipment lines written")

    # in batches, and in date order. One at a time would rewrite the whole
    # workbook 1,700 times, which takes twenty minutes and risks a timeout.
    ok = err = 0
    refusals = []
    BATCH = 100
    market = ships[0]["Market"]
    for i in range(0, len(moves), BATCH):
        chunk = moves[i:i + BATCH]
        try:
            out, _ = entry.append_moves(out, chunk, "manual", market)
            ok += len(chunk)
        except Exception:
            # one bad line refuses the whole batch, so fall back to one at a
            # time for that batch only and report exactly which line failed
            for mv in chunk:
                try:
                    out, _ = entry.append_moves(out, [mv], "manual", market)
                    ok += 1
                except Exception as ex:
                    err += 1
                    refusals.append((mv, str(ex)))
        print(f"    {min(i + BATCH, len(moves)):>5} of {len(moves)} …",
              end="\r", flush=True)
    print(f"  {ok} movements written, {err} refused" + " " * 20)
    if refusals:
        print("\n  REFUSED")
        seen = {}
        for mv, why in refusals:
            key = why.split(" - ")[-1][:60]
            seen.setdefault(key, []).append(mv)
        for why, group in sorted(seen.items(), key=lambda kv: -len(kv[1])):
            print(f"    {len(group):>4}  {why}")
            for mv in group[:2]:
                print(f"          {mv['Date']} {mv['Shipment No']} "
                      f"{mv['Movement']} {mv['Item Name']} "
                      f"{mv.get('In') or mv.get('Out')}")
    s1, m1, c1, cfg1, e1 = engine.load(io.BytesIO(out))
    st = engine.stock_by_item(s1, m1, cfg1["as_of"])
    print(f"\n  {len(s1)} shipment lines · {len(m1)} movements · "
          f"{float(st['Store'].sum()):,.0f} boxes in store · {len(e1)} errors")
    if len(e1):
        print("  refusing to save - the workbook would not be clean")
        return 1
    sp.upload_workbook(out, etag=meta.get("etag"))
    print("\nSaved to SharePoint. Now run:  python3 validate.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
