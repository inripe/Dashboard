"""Data loader — Inripe availability layer.

Reads the Product Master. Local file during development; SharePoint via
Microsoft Graph once secrets are configured.

Credentials live in Streamlit secrets, never in git.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd

LOCAL = Path(__file__).parent / "Inripe_Product_Master.xlsx"


def _from_sharepoint() -> bytes | None:
    """Download the workbook from SharePoint. Returns None if not configured."""
    try:
        import streamlit as st
        cfg = st.secrets.get("sharepoint")
    except Exception:
        cfg = None
    if not cfg:
        return None

    import requests

    token = requests.post(
        f"https://login.microsoftonline.com/{cfg['tenant_id']}/oauth2/v2.0/token",
        data={
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=30,
    ).json()["access_token"]

    head = {"Authorization": f"Bearer {token}"}
    site = requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{cfg['hostname']}:{cfg['site_path']}",
        headers=head, timeout=30,
    ).json()["id"]
    url = (f"https://graph.microsoft.com/v1.0/sites/{site}"
           f"/drive/root:/{cfg['file_path']}:/content")
    resp = requests.get(url, headers=head, timeout=60)
    resp.raise_for_status()
    return resp.content


def load_master() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(Products, Markets). SharePoint if configured, else the local file."""
    blob = _from_sharepoint()
    src: io.BytesIO | Path = io.BytesIO(blob) if blob else LOCAL
    if isinstance(src, Path) and not src.exists():
        raise FileNotFoundError(f"{src} not found and SharePoint is not configured")
    products = pd.read_excel(src, sheet_name="Products")
    if isinstance(src, io.BytesIO):
        src.seek(0)
    markets = pd.read_excel(src, sheet_name="Markets")
    return products, markets
