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

    Her sheet tracks stock per item: what is left when a new shipment lands
    shows up as that day's Old Stock. Ours tracks it per shipment. So an
    outward movement is drawn from whichever shipments actually hold the item,
    oldest first - which is also how the fruit really moves, and it stops the
    leftover being counted twice when the shipment number changes.
    """
    rows = sorted(rows, key=lambda r: (r["date"] or dt.date(1900, 1, 1),
                                       r["code"], r["their_item"]))
    ships, moves, notes = {}, [], []
    lots = {}        # item -> [[shipment, in store], …] oldest first
    held = {}        # item -> [[shipment, with courier], …]
    seen_item = set()
    adjust = 0

    def add(book, item, shipment, qty):
        row = book.setdefault(item, [])
        for lot in row:
            if lot[0] == shipment:
                lot[1] += qty
                return
        row.append([shipment, qty])

    def draw(book, item, qty, fallback):
        """Take qty from the oldest lots. Returns [(shipment, n), …]."""
        out, left = [], qty
        for lot in book.get(item, []):
            if left <= 0.001:
                break
            n = min(lot[1], left)
            if n > 0.001:
                out.append((lot[0], n))
                lot[1] -= n
                left -= n
        if left > 0.001:
            out.append((fallback, left))
        return out, left

    for r in rows:
        if not r["item"] or not r["market"] or not r["date"]:
            continue
        item, code = r["item"], r["code"]

        if r["received"] and (code, item) not in ships:
            ships[(code, item)] = {
                "Shipment No": code, "Market": r["market"],
                "Arrival Date": r["date"], "Source": r["source"],
                "Item Name": item, "Shipped Qty": r["received"],
                "PO Qty": r["po"]}
            if r["po"] and r["po"] != r["received"]:
                notes.append(f"{code} {item}: ordered {r['po']:.0f}, "
                             f"{r['received']:.0f} arrived")

        # her opening stock, only for the very first day this item appears -
        # after that, what is left carries in the lots below
        if item not in seen_item and r["old"]:
            moves.append({"Date": r["date"], "Shipment No": code,
                          "Movement": "Count Adjustment - Add",
                          "Item Name": item, "In": r["old"],
                          "Reason": "Count Adjustment",
                          "Note": "opening balance, not tracked before"})
            add(lots, item, code, r["old"])
            adjust += 1
        seen_item.add(item)

        if r["received"]:
            moves.append({"Date": r["date"], "Shipment No": code,
                          "Movement": "Received", "Item Name": item,
                          "In": r["received"]})
            add(lots, item, code, r["received"])

        # a return comes back during the day, before that day's dispatch -
        # her figures are the net of the day, not a sequence
        if r["ret"]:
            back, short = draw(held, item, r["ret"], code)
            if short > 0.001:
                # a return from a handover before her file begins
                moves.append({"Date": r["date"], "Shipment No": code,
                              "Movement": "Count Adjustment - Add",
                              "Item Name": item, "In": round(short, 3),
                              "Reason": "Count Adjustment",
                              "Note": "sent out before this sheet begins"})
                moves.append({"Date": r["date"], "Shipment No": code,
                              "Movement": "To Courier", "Item Name": item,
                              "Out": round(short, 3),
                              "Courier": courier_of.get(r["market"]),
                              "Note": "reconstructed: a return needs a handover"})
                adjust += 1
            for sid, n in back:
                moves.append({"Date": r["date"], "Shipment No": sid,
                              "Movement": "Returned", "Item Name": item,
                              "In": round(n, 3),
                              "Courier": courier_of.get(r["market"]),
                              "Reason": "Other Return"})
                add(lots, item, sid, n)

        for qty, mv, extra in ((r["scrap"], "Scrap", {"Reason": "Quality"}),
                               (r["ofd"], "To Courier",
                                {"Courier": courier_of.get(r["market"])})):
            if not qty:
                continue
            taken, short = draw(lots, item, qty, code)
            if short > 0.001:
                moves.append({"Date": r["date"], "Shipment No": code,
                              "Movement": "Count Adjustment - Add",
                              "Item Name": item, "In": round(short, 3),
                              "Reason": "Count Adjustment",
                              "Note": "stock her book held that this one "
                                      "had not seen"})
                adjust += 1
            for sid, n in taken:
                row = {"Date": r["date"], "Shipment No": sid,
                       "Movement": mv, "Item Name": item, "Out": round(n, 3)}
                row.update(extra)
                moves.append(row)
                if mv == "To Courier":
                    add(held, item, sid, n)

    if adjust:
        notes.append(f"{adjust} count adjustments were needed")
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
    # her book is the source of truth for the history, so the import is
    # judged against it item by item rather than on its own say-so
    import datetime as _dt
    last = {}
    for r in sorted(rows, key=lambda r: (r["date"] or _dt.date(1900, 1, 1))):
        if r["item"]:
            last[r["item"]] = r["allstock"]
    nm = cfg1.get("item_names") or {}
    mine = {}
    for row in st[st["Market"] == ships[0]["Market"]].itertuples():
        n = nm.get(row.Item, row.Item)
        mine[n] = mine.get(n, 0) + row.Store
    diff = [(i, last.get(i, 0), mine.get(i, 0))
            for i in sorted(set(last) | set(mine))
            if abs(last.get(i, 0) - mine.get(i, 0)) > 0.001]
    print(f"\nAGAINST HER OWN CLOSING FIGURES")
    print(f"  her book {sum(last.values()):,.0f} boxes · "
          f"this one {sum(mine.values()):,.0f}")
    if diff:
        print(f"  {len(diff)} items differ:")
        print(f"    {'ITEM':<24}{'HERS':>7}{'OURS':>7}")
        for i, h, o in diff[:12]:
            print(f"    {i[:23]:<24}{h:>7,.0f}{o:>7,.0f}")
        print("\n  refusing to save - it does not match her book")
        return 1
    print("  every item matches exactly")

    sp.upload_workbook(out, etag=meta.get("etag"))
    print("\nSaved to SharePoint. Now run:  python3 validate.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
