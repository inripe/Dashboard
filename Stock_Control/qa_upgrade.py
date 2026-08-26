"""The upgrade must add, never remove. This is what protects the live file."""
import sys, io, openpyxl, engine, upgrade_sheet
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
def eq(n,got,want):
    try: ok=abs(float(got)-float(want))<1e-6
    except (TypeError,ValueError): ok=str(got)==str(want)
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}: got {got}, want {want}")

# an old-style workbook, with edits of the kind you make on MASTER
import qa_book
wb=openpyxl.load_workbook(qa_book.old_style_copy()); ms=wb["MASTER"]
for i,mk in enumerate(["Qatar","UAE","KSA","Egypt"]):
    ms.cell(16+i,6).value=mk; ms.cell(16+i,7).value="Yes"
ms.cell(17,9).value="iFast"; ms.cell(17,10).value="UAE"; ms.cell(17,11).value="Yes"
b=io.BytesIO(); wb.save(b); OLD=b.getvalue()

print("=== A. IT KEEPS WHAT WAS THERE ===")
s0,m0,c0,cfg0,e0=engine.load(io.BytesIO(OLD))
NEW,notes=upgrade_sheet.upgrade(OLD)
s1,m1,c1,cfg1,e1=engine.load(io.BytesIO(NEW))
eq("every shipment line survives", len(s1), len(s0))
eq("every movement survives", len(m1), len(m0))
eq("counts survive", len(c1), len(c0))
ck("markets on MASTER are kept",
   cfg1.get("markets")==cfg0.get("markets"), cfg1.get("markets"))
ck("couriers are kept", cfg1.get("couriers_by_market").get("UAE")==["iFast"],
   cfg1.get("couriers_by_market"))
ck("shipment numbers are unchanged",
   sorted(set(s1["Shipment ID"]))==sorted(set(s0["Shipment ID"])))
ck("quantities are unchanged",
   list(s1["Shipped Qty"])==list(s0["Shipped Qty"]))

print("=== B. IT ADDS WHAT WAS MISSING ===")
for a in ("Entry ID","Entered by","Entered at"):
    ck(f"{a} added", a in m1.columns)
ck("old rows are marked as typed by hand",
   set(str(x) for x in m1["Entered by"].dropna())=={"manual"},
   set(m1["Entered by"].dropna()))
ck("users table added", len(cfg1.get("users") or {})>0, list(cfg1.get("users")))
ck("an admin exists",
   any(str(v["role"]).lower()=="admin" for v in cfg1["users"].values()))
ck("one entry user per market",
   {v["market"] for v in cfg1["users"].values() if v["role"]=="Entry"}
   >= {"Qatar","UAE","KSA","Egypt"},
   {v["market"] for v in cfg1["users"].values()})

print("=== C. THE NUMBERS COME OUT RIGHT ===")
st1=engine.stock_by_item(s1,m1,cfg1["as_of"])
eq("no entry errors afterwards", len(e1), 0)
ck("stock is a real number, not a formula", float(st1["Store"].sum())>0,
   float(st1["Store"].sum()))
ck("the check column is filled in",
   m1["Check"].notna().all() and not any(str(x).startswith("=")
                                         for x in m1["Check"].dropna()))

print("=== D. SAFE TO RUN TWICE ===")
AGAIN,notes2=upgrade_sheet.upgrade(NEW)
s2,m2,c2,cfg2,e2=engine.load(io.BytesIO(AGAIN))
eq("no rows added the second time", len(m2), len(m1))
eq("no shipment lines added", len(s2), len(s1))
ck("it says the columns are already there",
   any("already" in n for n in notes2), notes2)
ck("users are not duplicated", len(cfg2["users"])==len(cfg1["users"]))
eq("stock is the same",
   engine.stock_by_item(s2,m2,cfg2["as_of"])["Store"].sum(),
   st1["Store"].sum())

print("=== E. IT DOES NOT WRITE UNLESS TOLD ===")
src=open("upgrade_sheet.py").read()
ck("upload only happens with --apply", 'if not apply:' in src and 'sp.upload_workbook' in src)
ck("it shows a before and after first", src.count("summarise(")>=3)
ck("it names every change", 'for n in notes' in src)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)
