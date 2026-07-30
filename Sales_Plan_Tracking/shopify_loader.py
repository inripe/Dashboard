"""Shopify loader — Inripe sales tracking.

Pulls order line items from every store via the Admin GraphQL API.

Why this exists rather than a CSV export:

  * The orders CSV exposes `Created at`, which for migrated WooCommerce
    orders is the import timestamp, not the order date. Over a thousand
    KSA orders all carry one timestamp. `processedAt` carries the true
    date, and only the API exposes it.
  * The analytics report drops migrated line items entirely.
  * `product { title }` resolves to the catalogue name, so a line item
    recorded as "Fas Mango" is correctly attributed to "Mango Fas".
  * `currentQuantity` reflects removals and partial refunds, so revenue
    self-corrects as customers change their minds.

Authentication uses the client credentials grant, so there is no
long-lived access token to store or leak. Tokens are minted per run from
the client id and secret and cached in memory only.

Configuration lives in Streamlit secrets, one block per market:

    [shopify.KSA]
    shop = "ismailia-mango-ksa.myshopify.com"
    client_id = "..."
    client_secret = "..."

Requires read_all_orders for history beyond 60 days.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import pandas as pd
import requests

API_VERSION = "2026-07"
TIMEOUT = 60
PAGE = 50
MARKETS = ["UAE", "QA", "KSA", "EG"]

# Financial statuses that mean the money is gone or never existed.
DEAD_STATUSES = {"REFUNDED", "VOIDED", "EXPIRED"}

# Shopify records the origin of an order in sourceName. Manual orders raised
# by the team, typically from a WhatsApp conversation, arrive as draft orders.
# sourceName alone separates the storefront from manually raised orders. The
# commercially meaningful split is three ways, and the third signal lives in
# the tags: an order carrying an advertising tag came from paid social.
AD_TAGS = {"ad", "ads", "advert", "advertising", "paid", "meta", "facebook",
           "instagram", "tiktok", "snapchat", "google"}

# Tags that mark how an order arrived rather than who handled it. Anything
# left after removing these, on a manually raised order, is taken to be the
# agent — a heuristic, so it is reported as such and never silently trusted.
SYSTEM_TAGS = AD_TAGS | {
    "api", "woocommerce", "migrated-from-woocommerce", "pp", "cod",
    "riyadh", "jeddah", "dubai", "doha", "cairo", "abu dhabi", "sharjah",
    "dammam", "ofd", "delivered", "returned", "cancelled", "urgent",
}

DRAFT_SOURCES = {"shopify_draft_order", "draft_order"}


def classify(source: str | None, tags: list[str]) -> tuple[str, str | None]:
    """(channel, agent) for one order.

    Paid social wins over everything, because an advertised order that an
    agent later keys in is still an order the advertising bought. An order
    with no tags at all is Anonymous rather than Direct: absence of a tag is
    not evidence of an unattributed sale, and lumping the two together would
    quietly inflate whichever bucket it landed in.
    """
    low = {str(t).strip().lower() for t in (tags or []) if str(t).strip()}
    agent = None
    if low & AD_TAGS:
        channel = "Paid social"
    elif (source or "") in DRAFT_SOURCES:
        channel = "Agent"
    elif not low:
        channel = "Anonymous"
    else:
        channel = "Direct"

    if channel in ("Agent", "Paid social"):
        rest = [t for t in (tags or [])
                if str(t).strip().lower() not in SYSTEM_TAGS]
        if len(rest) == 1:
            agent = str(rest[0]).strip()
    return channel, agent


def pack_kg(title: str) -> float | None:
    """Kilos per box, read from the storefront title: 'Mango Fas - 4 KG'.

    Air freight is sold by weight, so a count of boxes is not a measure of
    what was shipped. A range such as '7 to 9 KG' is taken at its midpoint.
    """
    import re
    t = str(title)
    rng = re.search(r"([\d.]+)\s*(?:to|-|–)\s*([\d.]+)\s*kg", t, re.I)
    if rng:
        try:
            return (float(rng.group(1)) + float(rng.group(2))) / 2
        except ValueError:
            return None
    one = re.search(r"([\d.]+)\s*kg", t, re.I)
    if one:
        try:
            return float(one.group(1))
        except ValueError:
            return None
    return None

ORDERS_QUERY = """
query Orders($q: String!, $first: Int!, $after: String) {
  orders(first: $first, after: $after, query: $q, sortKey: PROCESSED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      name
      processedAt
      cancelledAt
      test
      displayFinancialStatus
      displayFulfillmentStatus
      currencyCode
      sourceName
      tags
      shippingAddress { city countryCodeV2 }
      customerJourneySummary { customerOrderIndex }
      lineItems(first: 50) {
        nodes {
          title
          sku
          quantity
          currentQuantity
          product { title }
          originalTotalSet { shopMoney { amount } }
          discountedTotalSet { shopMoney { amount } }
        }
      }
    }
  }
}
"""


class ShopifyError(RuntimeError):
    """Raised when a store cannot be reached or read."""


@dataclass(frozen=True)
class Store:
    market: str
    shop: str
    client_id: str
    client_secret: str


def _cfg() -> dict:
    """Read the shopify block from env or Streamlit secrets."""
    try:
        import streamlit as st
        cfg = st.secrets.get("shopify")
        if cfg:
            return dict(cfg)
    except Exception:
        pass

    out = {}
    for m in MARKETS:
        shop = os.environ.get(f"SHOPIFY_{m}_SHOP")
        cid = os.environ.get(f"SHOPIFY_{m}_CLIENT_ID")
        sec = os.environ.get(f"SHOPIFY_{m}_CLIENT_SECRET")
        if shop and cid and sec:
            out[m] = {"shop": shop, "client_id": cid, "client_secret": sec}
    return out


def stores() -> list[Store]:
    """Every market that is fully configured. Others are simply absent."""
    out = []
    for market, c in _cfg().items():
        if market not in MARKETS:
            continue
        if all(c.get(k) for k in ("shop", "client_id", "client_secret")):
            out.append(Store(market, str(c["shop"]).strip(),
                             str(c["client_id"]).strip(),
                             str(c["client_secret"]).strip()))
    return out


def is_configured() -> bool:
    return bool(stores())


def missing_markets() -> list[str]:
    have = {s.market for s in stores()}
    return [m for m in MARKETS if m not in have]


_TOKENS: dict[str, tuple[str, float]] = {}


def _token(store: Store) -> str:
    """Mint a short-lived access token. Cached in memory until it expires."""
    cached = _TOKENS.get(store.shop)
    if cached and cached[1] > time.time() + 60:
        return cached[0]

    r = requests.post(
        f"https://{store.shop}/admin/oauth/access_token",
        json={
            "client_id": store.client_id,
            "client_secret": store.client_secret,
            "grant_type": "client_credentials",
        },
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise ShopifyError(
            f"{store.market}: could not authenticate against {store.shop}. "
            f"Check the client id and secret, and that the app is installed. "
            f"Shopify said: {r.status_code} {r.text[:200]}")
    body = r.json()
    tok = body.get("access_token")
    if not tok:
        raise ShopifyError(f"{store.market}: no access token in the response")
    ttl = float(body.get("expires_in", 3600))
    _TOKENS[store.shop] = (tok, time.time() + ttl)
    return tok


def _post(store: Store, variables: dict) -> dict:
    """One GraphQL call, retrying on throttle."""
    url = f"https://{store.shop}/admin/api/{API_VERSION}/graphql.json"
    head = {"X-Shopify-Access-Token": _token(store),
            "Content-Type": "application/json"}
    for attempt in range(5):
        r = requests.post(url, headers=head,
                          json={"query": ORDERS_QUERY, "variables": variables},
                          timeout=TIMEOUT)
        if r.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise ShopifyError(
                f"{store.market}: query failed {r.status_code} {r.text[:200]}")
        body = r.json()
        errs = body.get("errors")
        if errs:
            msg = str(errs)[:300]
            if "THROTTLED" in msg.upper():
                time.sleep(2 * (attempt + 1))
                continue
            if "read_all_orders" in msg:
                raise ShopifyError(
                    f"{store.market}: this app cannot read orders older than "
                    f"60 days. Add read_all_orders to shopify.app.toml, "
                    f"redeploy, and reinstall the app.")
            raise ShopifyError(f"{store.market}: {msg}")
        return body["data"]["orders"]
    raise ShopifyError(f"{store.market}: still throttled after 5 attempts")


def _clean(name: str) -> str:
    """Strip the pack size a storefront title carries: 'Mango Fas - 4 KG'."""
    s = str(name).strip()
    for sep in (" - ", " – "):
        if sep in s:
            head = s.split(sep)[0].strip()
            if head:
                s = head
                break
    return s


def fetch_store(store: Store, year: int) -> pd.DataFrame:
    """Every line item processed in the given year, one row each.

    Filtered on processed_at, never created_at, so migrated orders land in
    the month the customer actually bought.
    """
    q = f"processed_at:>={year}-01-01 processed_at:<={year}-12-31"
    rows: list[dict] = []
    after = None
    while True:
        page = _post(store, {"q": q, "first": PAGE, "after": after})
        for o in page["nodes"]:
            if o.get("test"):
                continue
            addr = o.get("shippingAddress") or {}
            journey = o.get("customerJourneySummary") or {}
            idx = journey.get("customerOrderIndex")
            tags = o.get("tags") or []
            channel, agent = classify(o.get("sourceName"), tags)
            for li in o["lineItems"]["nodes"]:
                prod = (li.get("product") or {}).get("title")
                rows.append({
                    "city": (addr.get("city") or "Unknown").strip().title(),
                    "country": addr.get("countryCodeV2") or "",
                    "channel": channel,
                    "agent": agent,
                    "source_name": o.get("sourceName"),
                    "customer_type": ("New" if idx == 1
                                      else "Returning" if idx else "Unknown"),
                    "tags": ", ".join(o.get("tags") or []),
                    "market": store.market,
                    "order": o["name"],
                    "processed_at": o["processedAt"],
                    "cancelled": o.get("cancelledAt") is not None,
                    "financial_status": o.get("displayFinancialStatus"),
                    "fulfillment_status": o.get("displayFulfillmentStatus"),
                    "currency": o.get("currencyCode"),
                    # The catalogue name wins. A migrated line item reading
                    # "Fas Mango" resolves to "Mango Fas" and joins the plan.
                    "product": _clean(prod or li["title"]),
                    "line_title": li["title"],
                    "sku": li.get("sku"),
                    "pack_kg": pack_kg(li.get("variantTitle") or li["title"]),
                    "qty_ordered": li.get("quantity") or 0,
                    "qty_current": li.get("currentQuantity") or 0,
                    "gross_lc": float(li["originalTotalSet"]["shopMoney"]["amount"]),
                    "net_line_lc": float(li["discountedTotalSet"]["shopMoney"]["amount"]),
                })
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return pd.DataFrame(rows)


def fetch_all(year: int) -> tuple[pd.DataFrame, dict]:
    """Line items from every configured store, plus a source summary."""
    st = stores()
    if not st:
        raise ShopifyError(
            "no store is configured. Add a [shopify.<MARKET>] block with "
            "shop, client_id and client_secret.")
    frames, meta = [], {"source": "Shopify API", "markets": [], "errors": {}}
    for s in st:
        try:
            df = fetch_store(s, year)
            frames.append(df)
            meta["markets"].append(s.market)
        except ShopifyError as e:
            meta["errors"][s.market] = str(e)
    if not frames:
        raise ShopifyError(f"every store failed: {meta['errors']}")
    out = pd.concat(frames, ignore_index=True)
    meta["missing"] = missing_markets()
    meta["rows"] = len(out)
    return out, meta


def selftest(year: int = 2026) -> None:
    """Check the connection: python shopify_loader.py"""
    st = stores()
    if not st:
        print("NOT CONFIGURED. Add a [shopify.<MARKET>] block per store.")
        return
    print(f"configured markets: {', '.join(s.market for s in st)}")
    if missing_markets():
        print(f"not configured yet: {', '.join(missing_markets())}")
    for s in st:
        try:
            df = fetch_store(s, year)
            live = df[(~df.cancelled)
                      & (~df.financial_status.isin(DEAD_STATUSES))]
            print(f"\n{s.market} CONNECTED  {s.shop}")
            print(f"  line rows      {len(df):,}")
            print(f"  orders         {df['order'].nunique():,}")
            print(f"  units billable {live.qty_current.sum():,.0f}")
            print(f"  revenue        {live.net_line_lc.sum():,.0f} "
                  f"{df.currency.dropna().iloc[0] if len(df) else ''}")
            m = (pd.to_datetime(df.processed_at, utc=True, format="mixed")
                 .dt.strftime("%Y-%m").value_counts().sort_index())
            print("  months         " + ", ".join(f"{k}:{v}" for k, v in m.items()))
        except ShopifyError as e:
            print(f"\n{s.market} FAILED\n  {e}")


if __name__ == "__main__":
    selftest()
