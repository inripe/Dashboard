"""
Read-only Shopify client.  There is no write function in this file by design.

Since 1 Jan 2026 Shopify no longer issues static Admin API tokens.  Dev Dashboard
apps use the client credentials grant: the Client ID and Secret are exchanged for
a token that lasts about 24 hours.  This module does that exchange itself and
caches the token in memory.

Secrets (Streamlit secrets or env):
    SHOP_DOMAIN         e.g. ismailiamango-qa.myshopify.com   (the .myshopify.com one)
    SHOP_CLIENT_ID      Client ID from the Dev Dashboard app
    SHOP_CLIENT_SECRET  Secret from the same app
    SHOP_MARKET         the market these orders belong to, e.g. Qatar
"""
from __future__ import annotations
import os, requests

API = "2024-10"
TIMEOUT = 30
KEY_STAGE  = ("custom", "order_stage")
KEY_URGENT = ("custom", "5_order_exceptions")
_KEYS = ("SHOP_DOMAIN", "SHOP_CLIENT_ID", "SHOP_CLIENT_SECRET", "SHOP_MARKET")
_token_cache = {"value": None, "expires": 0.0}


def _cfg(k):
    v = os.environ.get(k)
    if v: return v.strip()
    try:
        import streamlit as st
        v = st.secrets.get(k)
        return v.strip() if isinstance(v, str) else v
    except Exception:
        return None


def is_configured(): return all(_cfg(k) for k in _KEYS)
def missing_keys():  return [k for k in _KEYS if not _cfg(k)]
def market():        return _cfg("SHOP_MARKET")


def _access_token() -> str:
    """Client credentials grant. Cached until shortly before it expires."""
    import time
    if _token_cache["value"] and time.time() < _token_cache["expires"]:
        return _token_cache["value"]
    dom = _cfg("SHOP_DOMAIN")
    r = requests.post(
        f"https://{dom}/admin/oauth/access_token", timeout=TIMEOUT,
        json={"client_id": _cfg("SHOP_CLIENT_ID"),
              "client_secret": _cfg("SHOP_CLIENT_SECRET"),
              "grant_type": "client_credentials"})
    if r.status_code != 200:
        raise RuntimeError(
            "Could not get a token from Shopify. Check the Client ID and Secret, and that "
            f"the app is installed on {dom}. Shopify said: {r.status_code} {r.text[:200]}")
    body = r.json()
    tok = body.get("access_token")
    if not tok:
        raise RuntimeError(f"Shopify returned no access token: {str(body)[:200]}")
    _token_cache["value"] = tok
    _token_cache["expires"] = time.time() + max(60, int(body.get("expires_in", 86400)) - 300)
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
      lineItems(first: 25) { edges { node { title quantity sku } } }
    } }
  }
}
"""


def fetch_orders(limit_pages: int = 40, days: int | None = 30):
    """Return (orders, truncated). Read-only.

    days=None reads every unfulfilled order, no date cutoff.
    `truncated` is True if Shopify still had more pages when we stopped -
    the caller must surface that, never hide it.
    """
    import datetime as _dt
    filt = "fulfillment_status:unfulfilled"
    if days:
        since = (_dt.datetime.utcnow() - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
        filt += f" AND created_at:>={since}"
    dom = _cfg("SHOP_DOMAIN")
    tok = _access_token()
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
            urgent_raw = (n.get("urgent") or {}).get("value") or ""
            out.append({
                "name": n["name"],
                "created": n["createdAt"],
                "cancelled": bool(n.get("cancelledAt")),
                "fulfillment": n.get("displayFulfillmentStatus"),
                "financial": n.get("displayFinancialStatus"),
                "stage": (n.get("stage") or {}).get("value"),
                "urgent": "urgent" in urgent_raw.lower(),
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


def selftest():
    if not is_configured():
        print("NOT CONFIGURED. Missing:", ", ".join(missing_keys())); return
    try:
        _access_token(); print("token obtained OK")
        o, trunc = fetch_orders(limit_pages=1)
        print(f"CONNECTED OK - {len(o)} unfulfilled orders read from {_cfg('SHOP_DOMAIN')}"
              + (" (more pages available)" if trunc else ""))
        if o: print("  newest:", o[0]["name"], "|", o[0]["stage"])
    except Exception as e:
        print("FAILED\n ", e)


if __name__ == "__main__":
    selftest()
