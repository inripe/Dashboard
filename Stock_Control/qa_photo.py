# -*- coding: utf-8 -*-
"""
A write-off with no evidence is a claim nobody can support, so scrap needs a
photo. The photo lives beside the workbook, never inside it.
"""
import sys, io, types
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
import sharepoint_loader as sp
import entry_ui

print("=== A. WHICH MOVEMENTS NEED ONE ===")
ck("scrap needs a photo", "Scrap" in entry_ui.PHOTO_MOVES)
ck("so does returning to scrap", "Return to Scrap" in entry_ui.PHOTO_MOVES)
ck("receiving does not", "Received" not in entry_ui.PHOTO_MOVES)
ck("handing to a courier does not", "To Courier" not in entry_ui.PHOTO_MOVES)
ck("nor does a count adjustment",
   not any("Count" in m for m in entry_ui.PHOTO_MOVES),
   sorted(entry_ui.PHOTO_MOVES))

print("=== B. THE NAME IS BUILT, NEVER TYPED ===")
n = sp.photo_name("Q-20260827-0004", "Q-26-001", "Mango Fas")
ck("it carries the shipment", n.startswith("Q-26-001"), n)
ck("and the item", "Mango-Fas" in n, n)
ck("and the entry id", "Q-20260827-0004" in n, n)
ck("it ends in jpg by default", n.endswith(".jpg"), n)
ck("an odd item name is made safe",
   "/" not in sp.photo_name("x", "Q-26-001", "Fig / big"),
   sp.photo_name("x", "Q-26-001", "Fig / big"))
ck("a png keeps its extension",
   sp.photo_name("x", "s", "i", "png").endswith(".png"))
ck("two entries never share a name",
   sp.photo_name("A", "s", "i") != sp.photo_name("B", "s", "i"))

print("=== C. IT GOES BESIDE THE WORKBOOK, NOT INSIDE IT ===")
sent = {}
class R:
    def __init__(self, c, b=None): self.status_code=c; self._b=b or {}; self.text=""
    def json(self): return self._b
class Req:
    @staticmethod
    def post(url, **kw): return R(200, {"access_token":"t","expires_in":86400})
    @staticmethod
    def put(url, **kw):
        sent["url"] = url; sent["headers"] = kw.get("headers", {})
        sent["bytes"] = len(kw.get("data") or b"")
        return R(201, {"name":"a.jpg","webUrl":"http://x/a.jpg","size":2048})
    @staticmethod
    def get(url, **kw): return R(200, {"id":"i","value":[]})
sp.requests = Req; sp._token = lambda: "t"; sp._item_cache = {"site":"s","id":"i"}
info = sp.upload_photo(b"x"*2048, "Q-26-001__Mango-Fas__Q-1.jpg")
ck("it goes to the Stock_Scrap folder", "Stock_Scrap" in sent["url"], sent["url"][-60:])
ck("as an image", sent["headers"].get("Content-Type") == "image/jpeg",
   sent["headers"].get("Content-Type"))
ck("the size comes back", info["size_kb"] == 2.0, info)
ck("and a link", bool(info.get("url")), info.get("url"))
src = open("entry.py").read()
ck("nothing image-like is ever written into the workbook",
   "image/" not in src and "photo" not in src.lower(), "")

print("=== D. A LOCKED OR REFUSED UPLOAD SAYS SO ===")
class Req2(Req):
    @staticmethod
    def put(url, **kw): return R(423)
sp.requests = Req2
try:
    sp.upload_photo(b"x", "a.jpg"); ck("a locked file is reported", False)
except sp.LockedError:
    ck("a locked file is reported", True)
class Req3(Req):
    @staticmethod
    def put(url, **kw): return R(403)
sp.requests = Req3
try:
    sp.upload_photo(b"x", "a.jpg"); ck("no permission is reported", False)
except RuntimeError as e:
    ck("no permission is reported", "read" in str(e), str(e)[:50])

print("=== E. THE FORM ===")
ui = open("entry_ui.py").read()
ck("it asks for a photo", 'st.file_uploader("photo"' in ui)
ck("only images", 'type=["jpg", "jpeg", "png"]' in ui)
ck("it is optional, never blocking", "(optional)" in ui
   and "a photo, or why there is none" not in ui)
ck("there is no excuse field to fill in", "No photo? Say why" not in ui)
ck("the saved name is shown back", "photo saved as" in ui)
app = open("app.py").read()
ck("the entry is written before the photo",
   app.index("ids = _write(make)") < app.index("sp.upload_photo"))
ck("a failed photo does not lose the entry",
   "The entry saved, but the photo did not" in app)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)
