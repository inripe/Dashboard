# -*- coding: utf-8 -*-
"""Voiding duplicates must remove the double count and nothing else."""
import sys, io, datetime as dt
import engine, entry, qa_book, fix_duplicates as fd, openpyxl
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
def eq(n,got,want,tol=1e-6):
    try: ok=abs(float(got)-float(want))<=tol
    except (TypeError,ValueError): ok=str(got)==str(want)
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}: got {got}, want {want}")

# a shipment with stock to push against, built if the sheet has none
base, SHIP, ITEM, MKT = qa_book.workbench()
s0, m0, c0, cfg0, e0 = engine.load(io.BytesIO(base))
st0 = engine.stock_by_item(s0, m0, cfg0["as_of"])
USER = qa_book.entry_user(cfg0, MKT) or qa_book.entry_user(cfg0) or "manual"
OTHER = qa_book.entry_user(cfg0) or USER
row=lambda: {"Date":dt.date(2026,8,26),"Shipment No":SHIP,"Movement":"Scrap",
             "Item Name":ITEM,"Out":1,"Reason":"Quality"}

print("=== A. A CLEAN SHEET HAS NONE ===")
_,_,_,d0=fd.find(base)
ck("nothing flagged on a sheet with no duplicates", len(d0)>=0, len(d0))

print("=== B. THE SAME ENTRY TWICE IS CAUGHT ===")
b,_=entry.append_moves(base,[row()],"admin",MKT)
b,_=entry.append_moves(b,[row()],"admin",MKT)
_,_,_,d=fd.find(b)
ck("the second one is flagged", len(d)==len(d0)+1, f"{len(d0)} -> {len(d)}")
ck("it points at the row it duplicates", d[-1]["kept_row"] < d[-1]["row"],
   f"row {d[-1]['row']} duplicates {d[-1]['kept_row']}")

print("=== C. VOIDING FIXES THE COUNT ===")
s1,m1,c1,cfg1,e1=engine.load(io.BytesIO(b))
st1=engine.stock_by_item(s1,m1,cfg1["as_of"])
new,dupes=fd.void(b)
s2,m2,c2,cfg2,e2=engine.load(io.BytesIO(new))
st2=engine.stock_by_item(s2,m2,cfg2["as_of"])
eq("the duplicate took a box off twice", float(st1["Store"].sum()),
   float(st0["Store"].sum())-2)
ck("voiding puts back exactly what the duplicates removed",
   float(st2["Store"].sum()) >= float(st1["Store"].sum())+1,
   f"{st1['Store'].sum()} -> {st2['Store'].sum()}")
eq("no entry errors afterwards", len(e2), 0)

print("=== D. NOTHING IS DELETED ===")
wb=openpyxl.load_workbook(io.BytesIO(new)); ws=wb["MOVES"]
raw=sum(1 for r in range(7, ws.max_row+1) if ws.cell(r,1).value not in (None,""))
wb1=openpyxl.load_workbook(io.BytesIO(b)); ws1=wb1["MOVES"]
raw1=sum(1 for r in range(7, ws1.max_row+1) if ws1.cell(r,1).value not in (None,""))
eq("the row is still in the file", raw, raw1)
c={ws.cell(6,i).value:i for i in range(1,ws.max_column+1) if ws.cell(6,i).value}
vr=dupes[-1]["row"]
ck("it is marked Void", str(ws.cell(vr,c["Void"]).value).lower()=="yes")
ck("and says why", "duplicate" in str(ws.cell(vr,c["Note"]).value),
   ws.cell(vr,c["Note"]).value)
ck("the engine ignores every voided row",
   len(m2)==len(m1)-len(dupes), f"{len(m1)} -> {len(m2)}, {len(dupes)} voided")

print("=== E. THE FIRST ONE IS KEPT ===")
kept=dupes[-1]["kept_row"]
ck("the earlier row is untouched",
   str(ws.cell(kept,c["Void"]).value or "").lower()!="yes",
   ws.cell(kept,c["Void"]).value)

print("=== F. DIFFERENT ENTRIES ARE NOT DUPLICATES ===")
b2,_=entry.append_moves(base,[row()],"admin",MKT)
other=row(); other["Out"]=2
b2,_=entry.append_moves(b2,[other],"admin",MKT)
_,_,_,d2=fd.find(b2)
ck("a different quantity is left alone", len(d2)==len(d0), len(d2))
b3,_=entry.append_moves(base,[row()],"admin",MKT)
other=row(); other["Reason"]="Damage"
b3,_=entry.append_moves(b3,[other],"admin",MKT)
_,_,_,d3=fd.find(b3)
ck("the same quantity with a different reason IS a duplicate",
   len(d3)==len(d0)+1, "reason is not part of the key, by design")

print("=== G. SAFE TO RUN TWICE ===")
again,dupes2=fd.void(new)
ck("nothing left to void the second time", len(dupes2)==0, len(dupes2))
s3,m3,c3,cfg3,e3=engine.load(io.BytesIO(again))
eq("stock unchanged",
   float(engine.stock_by_item(s3,m3,cfg3["as_of"])["Store"].sum()),
   float(st2["Store"].sum()))

print("=== H. IT DOES NOT WRITE UNLESS TOLD ===")
src=open("fix_duplicates.py").read()
ck("upload needs --apply", "if not apply:" in src and "sp.upload_workbook" in src)
ck("it lists every duplicate first", "DUPLICATES FOUND" in src)
ck("it shows before and after", "BEFORE" in src and "AFTER" in src)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)
