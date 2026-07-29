"""
Read the Product Master straight from SharePoint via Microsoft Graph.

Same pattern as the DM dashboards. No file is downloaded to disk and nothing
is committed to git. The team edits the workbook in SharePoint as normal; the
dashboard pulls the current bytes on each cache refresh.

Configuration lives in Streamlit secrets (or environment variables):

    SP_TENANT_ID     Directory (tenant) ID from the app registration
    SP_CLIENT_ID     Application (client) ID
    SP_CLIENT_SECRET the client secret Value
    SP_HOSTNAME      e.g. inripe.sharepoint.com
    SP_SITE_PATH     e.g. LT-PerformanceManagement
    SP_FILE_NAME     e.g. Inripe_Product_Master.xlsx

If any of those are missing, is_configured() returns False and the app falls
back to the local copy — so nothing breaks while this is being set up.
"""

from __future__ import annotations

import io
import os

import requests

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
TIMEOUT = 30

_KEYS = ("SP_TENANT_ID", "SP_CLIENT_ID", "SP_CLIENT_SECRET",
         "SP_HOSTNAME", "SP_SITE_PATH", "SP_FILE_NAME")


def _cfg(key):
    """Read from env first, then Streamlit secrets. Neither is required to exist."""
    v = os.environ.get(key)
    if v:
        return v.strip()
    try:
        import streamlit as st
        v = st.secrets.get(key)
        return v.strip() if isinstance(v, str) else v
    except Exception:
        return None


def is_configured() -> bool:
    return all(_cfg(k) for k in _KEYS)


def missing_keys() -> list:
    return [k for k in _KEYS if not _cfg(k)]


def _token() -> str:
    r = requests.post(
        f"{LOGIN}/{_cfg('SP_TENANT_ID')}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": _cfg("SP_CLIENT_ID"),
            "client_secret": _cfg("SP_CLIENT_SECRET"),
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(
            "Could not sign in to Microsoft Graph. Check the tenant ID, client ID "
            f"and client secret. Azure said: {r.status_code} {r.text[:200]}")
    return r.json()["access_token"]


def _site_id(hdr) -> str:
    host, path = _cfg("SP_HOSTNAME"), _cfg("SP_SITE_PATH").strip("/")
    r = requests.get(f"{GRAPH}/sites/{host}:/sites/{path}", headers=hdr, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(
            f"Could not find the SharePoint site '{path}' on '{host}'. "
            f"Check the hostname spelling and the site name. "
            f"Graph said: {r.status_code} {r.text[:200]}")
    return r.json()["id"]


def _file_item(hdr, site_id) -> dict:
    """Find the workbook by name anywhere in the site's default document library."""
    name = _cfg("SP_FILE_NAME")
    stem = name.rsplit(".", 1)[0]
    r = requests.get(f"{GRAPH}/sites/{site_id}/drive/root/search(q='{stem}')",
                     headers=hdr, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"Search failed: {r.status_code} {r.text[:200]}")
    items = r.json().get("value", [])
    exact = [i for i in items if i.get("name") == name]
    if exact:
        return exact[0]
    xlsx = [i for i in items if i.get("name", "").endswith(".xlsx")]
    if xlsx:
        return xlsx[0]
    found = ", ".join(i.get("name", "?") for i in items[:8]) or "nothing"
    raise FileNotFoundError(
        f"'{name}' was not found in that SharePoint site. Search returned: {found}. "
        f"Check SP_FILE_NAME matches the file name exactly, including the extension.")


def fetch_workbook() -> tuple[io.BytesIO, dict]:
    """Return (file-like workbook, metadata). Raises with a readable message."""
    hdr = {"Authorization": f"Bearer {_token()}"}
    site_id = _site_id(hdr)
    item = _file_item(hdr, site_id)
    r = requests.get(f"{GRAPH}/sites/{site_id}/drive/items/{item['id']}/content",
                     headers=hdr, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Could not download the file: {r.status_code} {r.text[:200]}")
    meta = {
        "name": item.get("name"),
        "modified": item.get("lastModifiedDateTime"),
        "modified_by": (item.get("lastModifiedBy", {})
                        .get("user", {}).get("displayName")),
        "size_kb": round(item.get("size", 0) / 1024),
        "web_url": item.get("webUrl"),
    }
    return io.BytesIO(r.content), meta


def selftest() -> None:
    """Run directly to check the connection: python sharepoint_loader.py"""
    if not is_configured():
        print("NOT CONFIGURED. Missing:", ", ".join(missing_keys()))
        return
    try:
        buf, meta = fetch_workbook()
        size = len(buf.getvalue())
        print("CONNECTED OK")
        print(f"  file        : {meta['name']}")
        print(f"  size        : {size:,} bytes")
        print(f"  last edited : {meta['modified']} by {meta['modified_by']}")
    except Exception as e:
        print("FAILED\n ", e)


if __name__ == "__main__":
    selftest()
