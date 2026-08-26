# -*- coding: utf-8 -*-
"""
One pass over everything I cannot reach from here: the live workbook, all four
Shopify stores, SharePoint read and write, and the environment.

    python3 probe.py            collect and print
    python3 probe.py > probe.txt    save it to a file to send

It writes one harmless test file to SharePoint and deletes nothing. The
workbook is never modified.
"""
import sys, io, json, platform, traceback
import datetime as dt

OUT = []
def say(*a):
    line = " ".join(str(x) for x in a)
    OUT.append(line); print(line)
def head(t):
    say(""); say("=" * 62); say(t); say("=" * 62)

head("1 · ENVIRONMENT")
say(f"python        {platform.python_version()} on {platform.system()} "
    f"{platform.machine()}")
for mod in ("pandas", "numpy", "openpyxl", "streamlit", "requests", "altair"):
    try:
        m = __import__(mod)
        say(f"{mod:<14}{getattr(m, '__version__', '?')}")
    except Exception as e:
        say(f"{mod:<14}MISSING - {e}")
import os
say(f"files here    {len([f for f in os.listdir('.') if f.endswith('.py')])} python, "
    f"{len([f for f in os.listdir('.') if f.endswith('.xlsx')])} workbooks")

head("2 · SECRETS PRESENT (values never printed)")
import auth, shopify_reader as sr
for k in ("ENTRY_PASSWORD", "DISPATCH_PASSWORD", "ADMIN_PASSWORD"):
    say(f"{k:<22}{'set' if auth._secret(k) else 'MISSING'}")
for m in sr.MARKETS:
    dom, cid, sec = sr._creds(m)
    say(f"shopify {m:<14}{'ok' if all((dom,cid,sec)) else 'not configured'}"
        f"{'   ' + dom if dom else ''}")
import sharepoint_loader as sp
for k in ("SP_TENANT_ID","SP_CLIENT_ID","SP_CLIENT_SECRET","SP_HOSTNAME",
          "SP_SITE_PATH","SP_FILE_NAME"):
    say(f"{k:<22}{'set' if sp._cfg(k) else 'MISSING'}")

head("3 · SHAREPOINT")
data = None
try:
    import base64
    t = sp._token(); p = t.split(".")[1]; p += "=" * (-len(p) % 4)
    claims = json.loads(base64.urlsafe_b64decode(p))
    say(f"token roles   {claims.get('roles')}")
    buf, meta = sp.fetch_workbook()
    data = buf.getvalue()
    say(f"read          ok · {meta['name']} · {meta['size_kb']} KB · "
        f"saved {meta['modified']}")
    say(f"etag          {'present' if meta.get('etag') else 'MISSING'}")
except Exception as e:
    say(f"read          FAILED - {e}")

if data:
    try:
        r = sp.upload_workbook(data, etag=meta.get("etag"))
        say(f"write         ok · new version {r.get('etag')}")
    except Exception as e:
        say(f"write         FAILED - {type(e).__name__}: {str(e)[:120]}")
    try:
        sp.upload_workbook(data, etag='"deliberately-stale"')
        say("stale write   NOT REFUSED - the version guard is not working")
    except sp.ConflictError:
        say("stale write   correctly refused")
    except Exception as e:
        say(f"stale write   refused with {type(e).__name__}")

head("4 · THE WORKBOOK")
if data:
    import engine, entry, openpyxl
    try:
        s, m, c, cfg, e = engine.load(io.BytesIO(data))
        st = engine.stock_by_item(s, m, cfg["as_of"])
        cl = engine.clearance_by_shipment(s, m, cfg["as_of"], cfg)
        cp = engine.courier_positions(s, m, cfg["as_of"], cfg)
        say(f"shipment lines {len(s)}   movements {len(m)}   counts {len(c)}")
        say(f"markets        {cfg.get('markets')}")
        say(f"couriers       {cfg.get('couriers_by_market')}")
        say(f"users          {[(u, r['market'], r['role']) for u, r in (cfg.get('users') or {}).items()]}")
        say(f"items          {len(cfg.get('item_names') or {})}")
        say(f"reasons        {cfg.get('reasons')}")
        say(f"settings       clear_target={cfg.get('clear_target')} "
            f"loss_target={cfg.get('loss_target')} as_of={cfg.get('as_of')}")
        say(f"entry errors   {len(e)}")
        if len(e):
            for _, r in e.head(10).iterrows():
                say(f"   {r['Sheet']} {r['Row']}: {r['Problem']}")
        say(f"shipments      {sorted(set(s['Shipment ID']))}")
        say(f"movement types {sorted(set(m['Movement'].dropna()))}")
        say(f"stock          {float(st['Store'].sum()):,.0f} boxes across "
            f"{len(st)} lines")
        say(f"negative lines {int((st['Store'] < 0).sum())}")
        gap = st["Shipped Qty"] - st["Received"] - st["Customs"]
        say(f"unbalanced     {int(gap.abs().gt(0.001).sum())} lines")
        say(f"with couriers  {float(cp['Held'].sum()) if len(cp) else 0:,.0f}")
        say(f"open shipments {int((cl['Cleared'] == 'No').sum())}")
        ws = openpyxl.load_workbook(io.BytesIO(data))
        for sh in ("SHIPMENTS", "MOVES", "COUNT", "DISPATCH", "MASTER"):
            if sh in ws.sheetnames:
                w = ws[sh]
                tabs = {n: (w.tables[n].ref if not isinstance(w.tables[n], str)
                            else w.tables[n]) for n in w.tables}
                say(f"{sh:<11}rows to {w.max_row}, cols to {w.max_column}, "
                    f"tables {tabs}")
        mv = ws["MOVES"]
        cc = {mv.cell(6, i).value: i for i in range(1, mv.max_column + 1)
              if mv.cell(6, i).value}
        say(f"MOVES columns  {list(cc)}")
        voided = sum(1 for r in range(7, mv.max_row + 1)
                     if str(mv.cell(r, cc["Void"]).value or "").lower() == "yes")
        say(f"voided rows    {voided}")
    except Exception as ex:
        say(f"FAILED - {ex}")
        say(traceback.format_exc()[-800:])

head("5 · SHOPIFY, EACH STORE")
for mk in sr.configured_markets():
    try:
        orders, trunc = sr.fetch_orders(mk, limit_pages=2)
        stages = {}
        skuless = lines = 0
        for o in orders:
            stages[o.get("stage") or "(none)"] = stages.get(o.get("stage") or "(none)", 0) + 1
            for ln in o.get("lines", []):
                lines += 1
                if not ln.get("sku"):
                    skuless += 1
        say(f"{mk:<8} {len(orders)} orders read"
            + ("  (more pages)" if trunc else ""))
        for k, v in sorted(stages.items(), key=lambda x: -x[1]):
            say(f"         {v:>4}  {k}")
        say(f"         {lines} line items, {skuless} with no SKU")
        if orders:
            o = orders[0]
            say(f"         newest {o['name']} · {o['created'][:16]} · "
                f"financial {o.get('financial')} · urgent {o.get('urgent')}")
    except Exception as e:
        say(f"{mk:<8} FAILED - {type(e).__name__}: {str(e)[:110]}")

head("6 · DISPATCH AGAINST LIVE ORDERS")
if data:
    try:
        import dispatch as dsp
        for mk in sr.configured_markets():
            d_stock = st[st["Market"] == mk]
            if not len(d_stock):
                say(f"{mk:<8} no stock in the sheet"); continue
            orders, _ = sr.fetch_orders(mk, limit_pages=3)
            codes = set(cfg.get("item_names", {}).keys())
            scope = dsp.in_scope(orders)
            dead = dsp.dead_stage2(orders)
            cmp_ = dsp.compare_strategies(orders, d_stock, codes, 3)
            say(f"{mk:<8} stage 2: {len(scope)} live, {len(dead)} cancelled or voided")
            for _, r in cmp_.drop(columns="_sel").iterrows():
                say(f"         {r['Strategy']:<15} {r['Orders']:>4} orders  "
                    f"{r['Boxes out']:>5,.0f} boxes  "
                    f"{r['Left in store']:>5,.0f} left  "
                    f"oldest waiting {r['Oldest waiting']:.0f}d")
            dd, sh_, xx, pool = dsp.allocate(orders, d_stock, codes, "Balanced", 3)
            chk = dsp.checks(dd, sh_, xx, orders, d_stock, pool, 3, None, codes)
            bad = chk[~chk["Pass"]]
            say(f"         checks: {'all pass' if not len(bad) else bad['Check'].tolist()}")
    except Exception as e:
        say(f"FAILED - {e}")
        say(traceback.format_exc()[-600:])

head("7 · DONE")
say(f"collected {len(OUT)} lines at {dt.datetime.now():%d %b %H:%M}")
