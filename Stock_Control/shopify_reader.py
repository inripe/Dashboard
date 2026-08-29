"""
Read-only Shopify client.  There is no write function in this file by design.

Since 1 Jan 2026 Shopify no longer issues static Admin API tokens.  Dev Dashboard
apps use the client credentials grant: the Client ID and Secret are exchanged for
a token that lasts about 24 hours.  This module does that exchange itself and
caches the token in memory.

One store per market. Secrets are named per market:

    SHOP_QATAR_DOMAIN / SHOP_QATAR_CLIENT_ID / SHOP_QATAR_CLIENT_SECRET
    SHOP_UAE_DOMAIN   / SHOP_UAE_CLIENT_ID   / SHOP_UAE_CLIENT_SECRET
    ... and the same for KSA and EGYPT.

The older single-market names (SHOP_DOMAIN, SHOP_CLIENT_ID, SHOP_CLIENT_SECRET,
SHOP_MARKET) still work and are treated as one configured market.
"""
from __future__ import annotations
import os, requests

API = "2024-10"
TIMEOUT = 30
KEY_STAGE  = ("custom", "order_stage")
KEY_URGENT = ("custom", "5_order_exceptions")
# both list fields the person can rank dispatch by. Whatever values exist in
# Shopify show up on their own - nothing is listed here.
KEY_ADDINFO = ("custom", "2_order_additional_info_for_sales_customer_service")
MARKETS = ("Qatar", "UAE", "KSA", "Egypt")
_token_cache = {}


def _cfg(k):
    v = os.environ.get(k)
    if v: return v.strip()
    try:
        import streamlit as st
        v = st.secrets.get(k)
        return v.strip() if isinstance(v, str) else v
    except Exception:
        return None


def _slug(market): return str(market).strip().upper()


def _keys(market):
    s = _slug(market)
    return (f"SHOP_{s}_DOMAIN", f"SHOP_{s}_CLIENT_ID", f"SHOP_{s}_CLIENT_SECRET")


def _creds(market):
    """Per-market secrets, falling back to the old single-market names."""
    dom, cid, sec = (_cfg(k) for k in _keys(market))
    if not (dom and cid and sec):
        legacy_market = _cfg("SHOP_MARKET")
        if legacy_market and _slug(legacy_market) == _slug(market):
            dom = dom or _cfg("SHOP_DOMAIN")
            cid = cid or _cfg("SHOP_CLIENT_ID")
            sec = sec or _cfg("SHOP_CLIENT_SECRET")
    return dom, cid, sec


def configured_markets():
    """Every market that has a full set of credentials."""
    return [m for m in MARKETS if all(_creds(m))]


def is_configured(market=None):
    if market is None:
        return bool(configured_markets())
    return all(_creds(market))


def missing_keys(market=None):
    if market is None:
        return [f"SHOP_<MARKET>_DOMAIN / _CLIENT_ID / _CLIENT_SECRET"] \
            if not configured_markets() else []
    dom, cid, sec = _creds(market)
    ks = _keys(market)
    return [k for k, v in zip(ks, (dom, cid, sec)) if not v]


def market():
    ms = configured_markets()
    return ms[0] if ms else None


def _access_token(market) -> str:
    """Client credentials grant, per market. Cached until shortly before expiry."""
    import time
    c = _token_cache.get(_slug(market))
    if c and time.time() < c["expires"]:
        return c["value"]
    dom, cid, sec = _creds(market)
    if not (dom and cid and sec):
        raise RuntimeError(f"{market} is not configured. Missing: "
                           + ", ".join(missing_keys(market)))
    r = requests.post(
        f"https://{dom}/admin/oauth/access_token", timeout=TIMEOUT,
        json={"client_id": cid, "client_secret": sec,
              "grant_type": "client_credentials"})
    if r.status_code != 200:
        raise RuntimeError(
            "Could not get a token from Shopify. Check the Client ID and Secret, and that "
            f"the app is installed on {dom}. Shopify said: {r.status_code} "
            f"{r.text[:200]}")
    body = r.json()
    tok = body.get("access_token")
    if not tok:
        raise RuntimeError(f"Shopify returned no access token: {str(body)[:200]}")
    _token_cache[_slug(market)] = {
        "value": tok,
        "expires": time.time() + max(60, int(body.get("expires_in", 86400)) - 300)}
    return tok


QUERY = """
query($cursor: String, $filter: String) {
  orders(first: 100, after: $cursor, sortKey: CREATED_AT, reverse: true, query: $filter) {
    pageInfo { hasNextPage endCursor }
    edges { node {
      name createdAt cancelledAt
      displayFulfillmentStatus displayFinancialStatus
      stage: metafield(namespace:"custom", key:"order_stage") { value }
      urgent: metafield(namespace:"custom", key:"5_order_exceptions") { value }
      addinfo: metafield(namespace:"custom",
               key:"2_order_additional_info_for_sales_customer_service") { value }
      lineItems(first: 25) { edges { node { title quantity sku } } }
    } }
  }
}
"""


def fetch_orders(market=None, limit_pages: int = 40, days: int | None = 30):
    """Return (orders, truncated). Read-only.

    days=None reads every unfulfilled order, no date cutoff.
    `truncated` is True if Shopify still had more pages when we stopped -
    the caller must surface that, never hide it.
    """
    import datetime as _dt
    filt = "fulfillment_status:unfulfilled"
    if days:
        since = (_dt.datetime.now(_dt.timezone.utc)
                 - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
        filt += f" AND created_at:>={since}"
    market = market or _default_market()
    dom, _, _ = _creds(market)
    tok = _access_token(market)
    url = f"https://{dom}/admin/api/{API}/graphql.json"
    hdr = {"X-Shopify-Access-Token": tok, "Content-Type": "application/json"}
    out, cursor, truncated = [], None, False
    for _ in range(limit_pages):
        r = requests.post(url, headers=hdr, timeout=30,
                          json={"query": QUERY,
                                "variables": {"cursor": cursor, "filter": filt}})
        if r.status_code != 200:
            raise RuntimeError(f"Shopify said {r.status_code}: {r.text[:200]}")
        body = r.json()
        if "errors" in body:
            raise RuntimeError(f"Shopify query error: {str(body['errors'])[:200]}")
        blk = body["data"]["orders"]
        for e in blk["edges"]:
            n = e["node"]
            def _list(raw):
                """The field is a list, so keep every value rather than only
                asking whether it says urgent."""
                raw = raw or ""
                try:
                    import json as _json
                    out = _json.loads(raw) if raw.strip().startswith("[") \
                        else raw.replace(";", ",").split(",")
                except Exception:
                    out = [raw]
                return [str(x).strip() for x in out if str(x).strip()]

            urgent_raw = (n.get("urgent") or {}).get("value") or ""
            # the field is a list, so keep every flag rather than only asking
            # whether it says urgent. New flags then appear on their own.
            flags = _list(urgent_raw)
            extra = _list((n.get("addinfo") or {}).get("value"))
            out.append({
                "name": n["name"],
                "created": n["createdAt"],
                "cancelled": bool(n.get("cancelledAt")),
                "fulfillment": n.get("displayFulfillmentStatus"),
                "financial": n.get("displayFinancialStatus"),
                "stage": (n.get("stage") or {}).get("value"),
                "urgent": any("urgent" in f.lower() for f in flags),
                "exceptions": flags,
                "additional": extra,
                "lines": [{"title": li["node"]["title"],
                           "quantity": li["node"]["quantity"],
                           "sku": li["node"].get("sku")}
                          for li in n["lineItems"]["edges"]],
            })
        if not blk["pageInfo"]["hasNextPage"]:
            break
        cursor = blk["pageInfo"]["endCursor"]
    else:
        truncated = True
    return out, truncated


def _default_market():
    ms = configured_markets()
    if not ms:
        raise RuntimeError("No market is configured.")
    return ms[0]


def selftest():
    ms = configured_markets()
    if not ms:
        print("NOT CONFIGURED. Add SHOP_<MARKET>_DOMAIN, SHOP_<MARKET>_CLIENT_ID "
              "and SHOP_<MARKET>_CLIENT_SECRET - for example SHOP_QATAR_DOMAIN.")
        return
    print("configured markets:", ", ".join(ms))
    for m in ms:
        dom, _, _ = _creds(m)
        try:
            _access_token(m)
            o, trunc = fetch_orders(m, limit_pages=1)
            print(f"  {m:<7} OK   {len(o)} unfulfilled orders from {dom}"
                  + ("  (more pages available)" if trunc else ""))
            if o:
                print(f"          newest {o[0]['name']} | {o[0]['stage']}")
        except Exception as e:
            print(f"  {m:<7} FAILED  {e}")
    for m in MARKETS:
        if m not in ms:
            print(f"  {m:<7} not configured")


if __name__ == "__main__":
    selftest()
