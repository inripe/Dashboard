"""Data loader — Inripe availability layer.

SharePoint via Microsoft Graph when configured, local file otherwise.
Same pattern as the DM dashboards.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

import sharepoint_loader as sp

LOCAL = Path(__file__).parent / "Inripe_Product_Master.xlsx"


def load_master() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(Products, Markets, source metadata)."""
    if sp.is_configured():
        buf, meta = sp.fetch_workbook()
        meta["source"] = "SharePoint"
        src: io.BytesIO | Path = buf
    else:
        if not LOCAL.exists():
            raise FileNotFoundError(
                f"{LOCAL.name} not found and SharePoint is not configured. "
                f"Missing secrets: {', '.join(sp.missing_keys())}")
        src = LOCAL
        meta = {"source": "local file", "name": LOCAL.name,
                "modified": None, "modified_by": None, "web_url": None}

    products = pd.read_excel(src, sheet_name="Products")
    if isinstance(src, io.BytesIO):
        src.seek(0)
    markets = pd.read_excel(src, sheet_name="Markets")
    return products, markets, meta
