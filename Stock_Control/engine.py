"""INRIPE stock control - calculation engine. Single source of truth."""
import pandas as pd, numpy as np

SHEETS = {"MASTER": None, "SHIPMENTS": 5, "MOVES": 5, "COUNT": 5}
MV = ["Received","Customs / Loss","Scrap","To Courier","Orders Assigned","Courier Handover",
      "Delivered","Returned","Return to Saleable","Return to Scrap","Count Adjustment"]

def _tbl(xl, sheet, header_row, ncols):
    """Read a sheet's table. Tolerates a file with fewer columns than expected."""
    try:
        df = xl.parse(sheet, header=header_row, usecols=range(ncols))
    except Exception:
        df = xl.parse(sheet, header=header_row)
        if df.shape[1] > ncols:
            df = df.iloc[:, :ncols]
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    if df.empty or not len(df.columns):
        return df
    key = df.columns[0]
    return df[df[key].notna()].reset_index(drop=True)

def load(path_or_buf):
    xl = pd.ExcelFile(path_or_buf)
    ship  = _tbl(xl,"SHIPMENTS",5,9)
    moves = _tbl(xl,"MOVES",5,16)
    count = _tbl(xl,"COUNT",5,8)
    if "Shipment No" not in ship.columns and "Shipment ID" not in ship.columns:
        raise ValueError(
            "This looks like an older version of the entry file. "
            "Use the current INRIPE_Stock_Entry file - SHIPMENTS should start with 'Shipment No'.")
    if "In" not in moves.columns or "Out" not in moves.columns:
        raise ValueError(
            "This looks like an older version of the entry file. "
            "MOVES needs separate 'In' and 'Out' columns. Replace the Excel file with the current one.")
    # normalise the friendly column names to what the engine works in
    ship = ship.rename(columns={"Shipment No":"Shipment ID","Item Code":"Item Code"})
    if "Ship Date" not in ship.columns:
        ship["Ship Date"] = ship["Arrival Date"]
    moves = moves.rename(columns={"Shipment No":"Shipment"})
    if "Item Code" in moves.columns:
        moves["Item"] = moves["Item Code"]
    count = count.rename(columns={"Shipment No":"Shipment"})
    if "Item Code" in count.columns:
        count["Item"] = count["Item Code"]
    # Count Adjustment split into Add / Remove -> one signed movement
    if "Movement" in moves.columns:
        moves["Movement"] = moves["Movement"].replace({
            "Count Adjustment - Add":"Count Adjustment",
            "Count Adjustment - Remove":"Count Adjustment Out"})
    try:
        disp = _tbl(xl,"DISPATCH",5,9)
        disp = disp.rename(columns={"Shipment No":"Shipment"})
        if "Item Code" in disp.columns: disp["Item"] = disp["Item Code"]
        disp = disp[disp["Order"].notna() & (disp["Order"].astype(str).str.strip()!="")]
        disp["Qty"] = pd.to_numeric(disp["Qty"], errors="coerce").fillna(0)
        disp["Date"] = pd.to_datetime(disp["Date"])
    except Exception:
        disp = pd.DataFrame(columns=["Date","Market","Order","Shipment","Item","Qty","Courier"])
    if "Void" in moves.columns:
        moves = moves[moves["Void"].astype(str).str.strip().str.lower() != "yes"].reset_index(drop=True)
    if len(disp):
        extra = pd.DataFrame({
            "Date": disp["Date"], "Market": disp["Market"], "Shipment": disp["Shipment"],
            "Movement": "To Courier", "Item": disp["Item"], "Qty": disp["Qty"],
            "Orders": np.nan, "Courier": disp["Courier"], "Reason": np.nan,
            "Note": "from DISPATCH", "Check": "OK"})
        moves = pd.concat([moves, extra], ignore_index=True)
    for d,c in ((ship,"Ship Date"),(ship,"Arrival Date"),(moves,"Date"),(count,"Date")):
        d[c] = pd.to_datetime(d[c])
    for d,cols in ((ship,["Shipped Qty"]),(moves,["Qty","Orders"]),(count,["Physical Qty"])):
        for c in cols:
            if c in d.columns: d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
    # "Count Adjustment Out" is negative
    if "Movement" in moves.columns:
        neg = moves["Movement"] == "Count Adjustment Out"
        moves.loc[neg,"Qty"] = -moves.loc[neg,"Qty"]
        moves.loc[neg,"Movement"] = "Count Adjustment"
    cfg = xl.parse("MASTER", header=None, usecols=[1,2], nrows=11)
    cfg = dict(zip(cfg[1].astype(str), cfg[2]))
    try:
        mk = xl.parse("MASTER", header=14, usecols=[5,6])
        mk.columns = ["Market","Active"]
        market_list = mk.loc[mk["Market"].notna() &
                             (mk["Active"].astype(str).str.strip().str.lower()=="yes"),
                             "Market"].astype(str).tolist()
    except Exception:
        market_list = []
    try:
        it = xl.parse("MASTER", header=14, usecols=[1,2])
        it.columns = ["Item Name","Item Code"]
        item_names = dict(zip(it["Item Code"].dropna().astype(str),
                              it["Item Name"].fillna("").astype(str)))
    except Exception:
        item_names = {}
    settings = {
        "as_of": pd.to_datetime(cfg.get("As-Of Date", pd.Timestamp.today())),
        "courier_limit": float(cfg.get("Courier holding limit (days)", 3)),
        "clear_target": float(cfg.get("Shipment clearance target (days)", 4)),
        "loss_target": float(cfg.get("Loss % target", 0.03)),
        "var_tol": float(cfg.get("Count variance tolerance", 0.02)),
        "markets": market_list,
        "item_names": item_names,
    }
    errors = pd.concat([_err(ship,"SHIPMENTS"), _err(moves,"MOVES"), _err(count,"COUNT")],
                       ignore_index=True)
    return ship, moves, count, settings, errors

def _err(df, name):
    if "Check" not in df.columns or df.empty:
        return pd.DataFrame({"Sheet":pd.Series(dtype=str),"Row":pd.Series(dtype=str),"Problem":pd.Series(dtype=str)})
    chk = df["Check"]
    blank = chk.isna() | (chk.astype(str).str.strip() == "")
    if blank.all():
        return pd.DataFrame([{"Sheet": name, "Row": "all",
            "Problem": "Check column is empty - open the file in Excel and save it so the checks recalculate"}])
    bad = df[~blank & (~chk.astype(str).str.strip().isin(["OK","VOID"]))].copy()
    if bad.empty: return pd.DataFrame({"Sheet":pd.Series(dtype=str),"Row":pd.Series(dtype=str),"Problem":pd.Series(dtype=str)})
    bad["Sheet"] = name; bad["Row"] = (bad.index + 7).astype(str)
    return bad[["Sheet","Row","Check"]].rename(columns={"Check":"Problem"})

def _q(moves, mtype, by):
    d = moves[moves["Movement"] == mtype]
    return d.groupby(by)["Qty"].sum()

def _o(moves, mtype, by):
    d = moves[moves["Movement"] == mtype]
    return d.groupby(by)["Orders"].sum()

def stock_by_item(ship, moves, as_of):
    """One row per Shipment x Item. Store stock, aging, reconciliation."""
    base = ship[["Shipment ID","Market","Item Code","Arrival Date","Shipped Qty","Source"]].copy()
    base = base.rename(columns={"Shipment ID":"Shipment","Item Code":"Item"})
    k = ["Shipment","Item"]
    m = moves.rename(columns={"Shipment":"Shipment","Item":"Item"})
    for label, mt in [("Received","Received"),("Customs","Customs / Loss"),("Scrap","Scrap"),
                      ("ToSaleable","Return to Saleable"),("ReturnScrap","Return to Scrap"),
                      ("CountAdj","Count Adjustment"),("ToCourier","To Courier")]:
        base[label] = base.set_index(k).index.map(_q(m, mt, k)).fillna(0) if len(m) else 0
    base = base.fillna({c:0 for c in ["Received","Customs","Scrap","ToSaleable","ReturnScrap","CountAdj","ToCourier"]})
    base["Store"] = base["Received"] - base["Scrap"] + base["ToSaleable"] + base["CountAdj"] - base["ToCourier"]
    base["ShipDiff"] = base["Shipped Qty"] - base["Customs"] - base["Received"]
    base["AgeDays"] = (as_of - base["Arrival Date"]).dt.days
    base["QA"] = (base["Received"] - base["Scrap"] + base["ToSaleable"]
                  + base["CountAdj"] - base["ToCourier"] - base["Store"])
    return base

def clearance_by_shipment(ship, moves, as_of, settings):
    hdr = ship.groupby("Shipment ID").agg(
        Market=("Market","first"), Arrival=("Arrival Date","min")).reset_index()
    hdr = hdr.rename(columns={"Shipment ID":"Shipment"})
    k = "Shipment"
    g = lambda mt, col: hdr[k].map(_q(moves, mt, k) if col=="Qty" else _o(moves, mt, k)).fillna(0)
    hdr["Received"]  = g("Received","Qty")
    hdr["Scrap"]     = g("Scrap","Qty") + g("Return to Scrap","Qty")
    hdr["Delivered"] = g("Delivered","Qty")
    hdr["Returned"]  = g("Returned","Qty")
    hdr["CountAdj"] = g("Count Adjustment","Qty")
    hdr["Outstanding"] = (hdr["Received"] - hdr["Delivered"] - hdr["Scrap"] + hdr["CountAdj"])
    hdr["DaysOpen"] = (as_of - hdr["Arrival"]).dt.days
    dl = moves[moves["Movement"]=="Delivered"]
    if len(dl):
        last = dl.groupby("Shipment")["Date"].max()
        hdr["Span"] = (hdr["Shipment"].map(last) - hdr["Arrival"]).dt.days
    else:
        hdr["Span"] = np.nan
    hdr["Cleared"] = np.where(hdr["Outstanding"] <= 0, "Yes", "No")
    hdr["OrdersAssigned"] = g("Orders Assigned","Orders")
    hdr["OrdersHanded"]   = g("Courier Handover","Orders")
    hdr["OrdersDelivered"]= g("Delivered","Orders")
    hdr["OrdersReturned"] = g("Returned","Orders")
    hdr["OrdersOutstanding"] = hdr["OrdersHanded"] - hdr["OrdersDelivered"] - hdr["OrdersReturned"]
    hdr["OrdersVsAssigned"]  = hdr["OrdersHanded"] - hdr["OrdersAssigned"]
    hdr["Overdue"] = (hdr["Outstanding"] > 0) & (hdr["DaysOpen"] > settings["clear_target"])
    return hdr

def courier_positions(ship, moves, as_of, settings):
    d = moves[moves["Courier"].notna()].copy()
    if d.empty:
        return pd.DataFrame(columns=["Shipment","Courier","ToCourier","Delivered","Returned",
                                     "Held","OrdersHanded","OrdersDelivered","OrdersReturned",
                                     "OrdersOutstanding","DaysSince","Flag","Market"])
    k = ["Shipment","Courier"]
    idx = d[k].drop_duplicates().reset_index(drop=True)
    mp = lambda mt, col: idx.set_index(k).index.map(
        (_q(d, mt, k) if col=="Qty" else _o(d, mt, k))).fillna(0)
    idx["ToCourier"] = mp("To Courier","Qty")
    idx["Delivered"] = mp("Delivered","Qty")
    idx["Returned"]  = mp("Returned","Qty")
    idx["Held"] = idx["ToCourier"] - idx["Delivered"] - idx["Returned"]
    idx["OrdersHanded"]    = mp("Courier Handover","Orders")
    idx["OrdersDelivered"] = mp("Delivered","Orders")
    idx["OrdersReturned"]  = mp("Returned","Orders")
    idx["OrdersOutstanding"] = idx["OrdersHanded"] - idx["OrdersDelivered"] - idx["OrdersReturned"]
    tc = d[d["Movement"]=="To Courier"].groupby(k)["Date"].min()
    idx["DaysSince"] = (as_of - idx.set_index(k).index.map(tc)).days if len(tc) else np.nan
    mk = ship.drop_duplicates("Shipment ID").set_index("Shipment ID")["Market"]
    idx["Market"] = idx["Shipment"].map(mk)
    idx["Flag"] = np.select(
        [idx["Held"] < 0,
         (idx["Held"] > 0) & (idx["DaysSince"] > settings["courier_limit"]),
         idx["OrdersOutstanding"] < 0],
        ["Over-delivered","Holding too long","Order count error"], default="OK")
    return idx

def variance(stock, count):
    if count.empty: return pd.DataFrame(columns=["Shipment","Item","System","Physical","Var"])
    latest = count.sort_values("Date").groupby(["Shipment","Item"]).tail(1)
    s = stock.set_index(["Shipment","Item"])["Store"]
    out = latest[["Date","Shipment","Item","Physical Qty"]].copy()
    out["System"] = out.set_index(["Shipment","Item"]).index.map(s).fillna(0)
    out = out.rename(columns={"Physical Qty":"Physical"})
    out["Var"] = out["Physical"] - out["System"]
    out["VarPct"] = np.where(out["System"]!=0, out["Var"]/out["System"], 0)
    return out
