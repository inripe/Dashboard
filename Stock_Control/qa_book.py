"""Which workbook the suites test, and who to sign in as. One place."""
import os, io, shutil

_SEEDED = {"path": None}


def book():
    """The file under test. qa_all.py sets QA_BOOK; otherwise the app's own.

    If it is empty, a seeded copy is written once and used from then on, so
    the app under test and the suites both see the same thing."""
    p = _book_path()
    raw = open(p, "rb").read()
    if not _is_empty(raw):
        return p
    if not _SEEDED["path"]:
        import tempfile
        f = os.path.join(tempfile.gettempdir(), "qa_seeded.xlsx")
        open(f, "wb").write(_seed(raw))
        _SEEDED["path"] = f
        os.environ.setdefault("INRIPE_FILE", f)
    return _SEEDED["path"]


def _book_path():
    for p in (os.environ.get("QA_BOOK"),
              "INRIPE_Stock_Entry_v1.xlsx",
              "INRIPE_Stock_Entry_v3.xlsx"):
        if p and os.path.exists(p):
            return p
    raise FileNotFoundError("No workbook to test. Put INRIPE_Stock_Entry_v1.xlsx "
                            "in this folder or pass --book.")

def data():
    """The workbook under test, with a little sample data if it is empty.

    A cleared sheet is a perfectly good state for the live file - it is what
    you get before the history goes in - but the rule suites need something to
    push against. So they get a small seeded copy rather than every suite
    collapsing on an empty frame."""
    return open(book(), "rb").read()


def _is_empty(raw):
    import openpyxl, io as _io
    ws = openpyxl.load_workbook(_io.BytesIO(raw))["SHIPMENTS"]
    return all(ws.cell(r, 1).value in (None, "")
               for r in range(7, max(ws.max_row, 7) + 1))


def _seed(raw):
    """One shipment, a few items, a few movements. Enough for every rule to
    have something to refuse."""
    import io as _io, datetime as _dt
    import engine as _e, entry as _en
    s, m, c, cfg, e = _e.load(_io.BytesIO(raw))
    items = list((cfg.get("item_names") or {}).values())[:4]
    market = (cfg.get("markets") or ["Qatar"])[0]
    if not items:
        return raw
    # well back, so a suite writing a movement "yesterday" is never dated
    # before the shipment it belongs to
    arrival = _dt.date(2026, 8, 24)
    sid = _en.next_shipment_no(raw, market)
    rows = [{"Shipment No": sid, "Market": market, "Arrival Date": arrival,
             "Source": "Egypt", "Item Name": it, "Shipped Qty": q}
            for it, q in zip(items, (40, 25, 60, 15))]
    out, made = _en.append_shipment(raw, rows, "qa", market)
    moves = [{"Date": arrival, "Shipment No": made, "Movement": "Received",
              "Item Name": it, "In": q}
             for it, q in zip(items, (40, 25, 58, 15))]
    moves.append({"Date": arrival, "Shipment No": made,
                  "Movement": "Not received", "Item Name": items[2],
                  "Out": 2, "Reason": "Customs"})
    moves.append({"Date": arrival, "Shipment No": made, "Movement": "Scrap",
                  "Item Name": items[0], "Out": 3, "Reason": "Quality"})
    cour = ((cfg.get("couriers_by_market") or {}).get(market) or [None])[0]
    if cour:
        moves.append({"Date": _dt.date.today(), "Shipment No": made,
                      "Movement": "To Courier", "Item Name": items[1],
                      "Out": 10, "Courier": cour})
    for mv in moves:
        try:
            out, _ = _en.append_moves(out, [mv], "qa", market)
        except Exception:
            pass
    return out

def admin_user(cfg):
    """Whatever the admin is called on this sheet."""
    for u, r in (cfg.get("users") or {}).items():
        if str(r.get("role", "")).strip().lower() == "admin":
            return u
    return None

def entry_user(cfg, market=None):
    for u, r in (cfg.get("users") or {}).items():
        if str(r.get("role", "")).strip().lower() == "entry" \
                and (market is None or r.get("market") == market):
            return u
    return None

def old_style_copy(path="/tmp/qa_old.xlsx"):
    """A copy with the audit columns and users table stripped out, to test the
    upgrade against something genuinely old."""
    import openpyxl
    wb = openpyxl.load_workbook(book())
    ws = wb["MOVES"]
    cols = {ws.cell(6, c).value: c for c in range(1, ws.max_column + 1)
            if ws.cell(6, c).value}
    for name in ("Entered at", "Entered by", "Entry ID"):
        if name in cols:
            ws.delete_cols(cols[name])
            cols = {ws.cell(6, c).value: c for c in range(1, ws.max_column + 1)
                    if ws.cell(6, c).value}
    if "tblMoves" in ws.tables:
        del ws.tables["tblMoves"]
    from openpyxl.worksheet.table import Table, TableStyleInfo
    from openpyxl.utils import get_column_letter as CL
    last = ws.max_row
    t = Table(displayName="tblMoves", ref=f"A6:{CL(ws.max_column)}{last}")
    t.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(t)
    ms = wb["MASTER"]
    if "tblUsers" in ms.tables:
        del ms.tables["tblUsers"]
        for r in range(15, 30):
            for c in range(25, 29):
                ms.cell(r, c).value = None
    wb.save(path)
    return path
