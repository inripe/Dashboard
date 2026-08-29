"""The SharePoint write path: conflicts, retries, and nothing lost."""
import sys, qa_book, io, types, engine, entry, qa_book
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
import sharepoint_loader as sp

print("=== A. A SAVE CARRIES THE VERSION ===")
seen={}
class R:
    def __init__(self,code,body=None): self.status_code=code; self._b=body or {}
    def json(self): return self._b
    text=""
class Req:
    @staticmethod
    def post(url,**kw):
        return R(200,{"access_token":"t","expires_in":86400})
    @staticmethod
    def get(url,**kw):
        if url.endswith("/content"): 
            r=R(200); r.content=b"x"; return r
        return R(200,{"id":"i","eTag":'"v1"',"lastModifiedDateTime":"2026-08-25T10:00:00Z",
                      "name":"f.xlsx","size":10,"webUrl":"","value":[{"id":"i","name":"f.xlsx"}]})
    @staticmethod
    def put(url,**kw):
        seen.update(kw.get("headers",{}))
        if seen.get("If-Match")=='"stale"': return R(412)
        return R(200,{"eTag":'"v2"',"lastModifiedDateTime":"2026-08-25T10:05:00Z"})
sp.requests=Req; sp._token=lambda: "t"
sp._item_cache={"site":"s","id":"i"}
out=sp.upload_workbook(b"data", etag='"v1"')
ck("If-Match header sent", seen.get("If-Match")=='"v1"', seen.get("If-Match"))
ck("new version returned", out["etag"]=='"v2"', out)
ck("content type is xlsx", "spreadsheetml" in seen.get("Content-Type",""), seen.get("Content-Type"))

print("=== B. A CLASH IS REPORTED, NOT SWALLOWED ===")
try:
    sp.upload_workbook(b"data", etag='"stale"')
    ck("stale version refused", False, "it saved anyway")
except sp.ConflictError as ex:
    ck("stale version refused", True, str(ex)[:46])
ck("the clash has its own error type", issubclass(sp.ConflictError, RuntimeError))

print("=== C. RETRY AFTER A CLASH LOSES NOTHING ===")
base=open(qa_book.book(),"rb").read()
s0,m0,c0,cfg0,e0=engine.load(io.BytesIO(base))
# whichever market actually has data - the sheet does not always start with
# Qatar, and a suite that assumes it collapses on a UAE-only workbook
MKT = s0["Market"].dropna().iloc[0]
USER = qa_book.entry_user(cfg0, MKT) or qa_book.entry_user(cfg0) or "manual"
OTHER = qa_book.entry_user(cfg0) or USER
SHIP=s0[s0.Market==MKT]["Shipment ID"].iloc[0]
ITEM=s0[s0["Shipment ID"]==SHIP]["Item Name"].iloc[0]
# scrap is used here rather than received: this suite is about two people
# saving at once, not about quantity limits
mk=lambda q: {"Date":entry.market_now(MKT).date(),"Shipment No":SHIP,
              "Movement":"Scrap","Item Name":ITEM,"Out":q,"Reason":"Damage"}
# person A and person B both start from the same file
a,_=entry.append_moves(base,[mk(3)],USER, MKT)
b,_=entry.append_moves(base,[mk(7)],OTHER, MKT)
# A wins the race; B is refused and re-appends onto A's file
b_retry,_=entry.append_moves(a,[mk(7)],OTHER, MKT)
sf,mf,cf,cfgf,ef=engine.load(io.BytesIO(b_retry))
ck("both entries survive the retry", len(mf)==len(m0)+2, f"{len(m0)} -> {len(mf)}")
qtys=list(mf.tail(2)["Qty"])
ck("both quantities are there", sorted(qtys)==[3,7], qtys)
ck("no duplicate entry ids",
   mf["Entry ID"].dropna().is_unique, "unique")
ck("the naive overwrite would have lost one",
   len(engine.load(io.BytesIO(b))[1])==len(m0)+1, "b alone has only one new row")

print("=== D. TWO MARKETS NEVER COLLIDE IN IDS ===")
q,_=entry.append_moves(base,[mk(1)],USER, MKT)
ids_q=[i for i in engine.load(io.BytesIO(q))[1]["Entry ID"].dropna()]
LET = {"Qatar":"Q","UAE":"U","KSA":"K","Egypt":"E"}.get(MKT, MKT[0].upper())
ck(f"{MKT} ids start with {LET}",
   all(str(i).startswith(f"{LET}-") for i in ids_q), ids_q[-1:])
u_id=entry.next_entry_id(__import__("openpyxl").load_workbook(io.BytesIO(q))["MOVES"],"UAE")
ck("uae ids start with U", u_id.startswith("U-"), u_id)
ck("a uae id cannot equal a qatar one", u_id not in ids_q)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)
