# -*- coding: utf-8 -*-
"""
No save may go out without a version tag.

The probe found that SharePoint's search endpoint returns no eTag, so every
real save was unguarded: two people saving at once would have overwritten each
other silently. The conflict test had passed only because it supplied a fake
tag of its own.
"""
import sys, types
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
import sharepoint_loader as sp
FAKE={"SP_HOSTNAME":"x.sharepoint.com","SP_SITE_PATH":"site",
      "SP_FILE_NAME":"f.xlsx","SP_TENANT_ID":"t","SP_CLIENT_ID":"c",
      "SP_CLIENT_SECRET":"s"}
sp._cfg = lambda k: FAKE.get(k)

print("=== A. A SAVE WITHOUT A VERSION IS REFUSED ===")
calls={}
class R:
    def __init__(self,c,b=None): self.status_code=c; self._b=b or {}; self.text=""
    def json(self): return self._b
class Req:
    @staticmethod
    def post(url,**kw): return R(200,{"access_token":"t","expires_in":86400})
    @staticmethod
    def put(url,**kw):
        calls["headers"]=kw.get("headers",{})
        return R(200,{"eTag":'"v2"',"lastModifiedDateTime":"x"})
    @staticmethod
    def get(url,**kw):
        if url.endswith("/content"):
            r=R(200); r.content=b"x"; return r
        if "/search(" in url:
            return R(200,{"value":[{"id":"i","name":"f.xlsx"}]})   # no eTag here
        return R(200,{"id":"i","eTag":'"v1"',"name":"f.xlsx","size":10,
                      "webUrl":"","lastModifiedDateTime":"2026-08-26T20:00:00Z",
                      "lastModifiedBy":{"user":{"displayName":"someone"}}})
sp.requests=Req; sp._token=lambda: "t"; sp._item_cache={"site":"s","id":"i"}
try:
    sp.upload_workbook(b"data")
    ck("saving with no version is refused", False, "it saved anyway")
except RuntimeError as e:
    ck("saving with no version is refused", True, str(e)[:48])
    ck("and says why", "overwrite" in str(e), str(e)[:60])
try:
    sp.upload_workbook(b"data", etag=None)
    ck("an explicit None is refused too", False)
except RuntimeError:
    ck("an explicit None is refused too", True)

print("=== B. THE VERSION IS ACTUALLY FETCHED ===")
sp._item_cache={"site":"s","id":None}
buf, meta = sp.fetch_workbook()
ck("the read carries a version", bool(meta.get("etag")), meta.get("etag"))
ck("it is the one from the item, not the search",
   meta.get("etag")=='"v1"', meta.get("etag"))
item = sp._file_item({"Authorization":"x"}, "s")
ck("the file lookup returns a version", bool(item.get("eTag")), item.get("eTag"))

print("=== C. IT IS SENT ON EVERY SAVE ===")
sp.upload_workbook(b"data", etag=meta["etag"])
ck("If-Match is on the request", "If-Match" in calls.get("headers",{}),
   sorted(calls.get("headers",{})))
ck("it carries the version we read",
   calls["headers"].get("If-Match")==meta["etag"],
   calls["headers"].get("If-Match"))

print("=== D. A CLASH IS STILL CAUGHT ===")
class Req2(Req):
    @staticmethod
    def put(url,**kw): return R(412)
sp.requests=Req2
try:
    sp.upload_workbook(b"data", etag='"v1"')
    ck("a stale version is refused", False, "it saved")
except sp.ConflictError:
    ck("a stale version is refused", True)

print("=== E. THE APP ALWAYS PASSES ONE ===")
src=open("app.py").read()
ck("every upload in the app carries a version",
   src.count("sp.upload_workbook(") == src.count('sp.upload_workbook(out, etag='),
   f"{src.count('sp.upload_workbook(')} uploads")
for tool in ("fix_gaps.py","fix_duplicates.py","clean_sheet.py"):
    try:
        t=open(tool).read()
        ck(f"{tool} passes one too",
           "upload_workbook(new, etag=" in t or "upload_workbook(" not in t, "")
    except FileNotFoundError:
        pass

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)
