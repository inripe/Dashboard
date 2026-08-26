"""What the workbook actually holds right now."""
import io, sys
import sharepoint_loader as sp, engine, openpyxl, pandas as pd
buf, meta = sp.fetch_workbook()
data = buf.getvalue()
print(f"{meta['name']} · saved {meta['modified']} · {meta['size_kb']} KB\n")
wb = openpyxl.load_workbook(io.BytesIO(data))
ws = wb["MOVES"]
c = {ws.cell(6, i).value: i for i in range(1, ws.max_column + 1) if ws.cell(6, i).value}
rows = []
for r in range(7, ws.max_row + 1):
    if ws.cell(r, c["Date"]).value in (None, ""):
        continue
    rows.append({k: ws.cell(r, i).value for k, i in c.items()})
print(f"{len(rows)} movement rows. The last five:\n")
for x in rows[-5:]:
    print(f"  {str(x.get('Date'))[:10]}  {str(x.get('Movement')):<16} "
          f"{str(x.get('Item Name') or ''):<20} in={x.get('In')} out={x.get('Out')} "
          f"reason={x.get('Reason')} by={x.get('Entered by')} id={x.get('Entry ID')}")
nr = [x for x in rows if str(x.get("Movement")).strip() == "Not received"]
print(f"\n'Not received' rows: {len(nr)}")
for x in nr:
    print(f"  {x.get('Shipment No')} {x.get('Item Name')} out={x.get('Out')} "
          f"reason={x.get('Reason')} void={x.get('Void')}")
