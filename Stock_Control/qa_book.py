"""Which workbook the suites test, and who to sign in as. One place."""
import os, io, shutil

def book():
    """The file under test. qa_all.py sets QA_BOOK; otherwise the app's own."""
    for p in (os.environ.get("QA_BOOK"),
              "INRIPE_Stock_Entry_v1.xlsx",
              "INRIPE_Stock_Entry_v3.xlsx"):
        if p and os.path.exists(p):
            return p
    raise FileNotFoundError("No workbook to test. Put INRIPE_Stock_Entry_v1.xlsx "
                            "in this folder or pass --book.")

def data():
    return open(book(), "rb").read()

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
