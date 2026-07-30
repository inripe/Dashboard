"""Data loader — Inripe sales plan.

SharePoint via Microsoft Graph when configured, local file otherwise.
Same pattern as the DM and availability dashboards.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

import sharepoint_loader as sp

LOCAL = Path(__file__).parent / "Sales_Plan_2026_V1.xlsx"
LOCAL_ACTUALS = Path(__file__).parent / "Sales_Actuals_2026_V1.xlsx"
ACTUALS_NAME = "Sales_Actuals_2026_V1.xlsx"
MARKETS = ["UAE", "QA", "KSA", "EG"]


def load_plan() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(Plan, FX, source metadata)."""
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

    plan = pd.read_excel(src, sheet_name="Plan")
    if isinstance(src, io.BytesIO):
        src.seek(0)
    fx = pd.read_excel(src, sheet_name="FX")
    # Optional. Maps a store's product name onto the plan's name for cases the
    # automatic resolver will not guess at.
    aliases = None
    try:
        if isinstance(src, io.BytesIO):
            src.seek(0)
        aliases = pd.read_excel(src, sheet_name="Aliases")
    except Exception:
        aliases = None
    # Append-only dated cost history. Optional.
    cost_log = None
    try:
        if isinstance(src, io.BytesIO):
            src.seek(0)
        cost_log = pd.read_excel(src, sheet_name="Cost_Log")
    except Exception:
        cost_log = None
    meta["has_aliases"] = aliases is not None
    meta["has_cost_log"] = cost_log is not None and len(cost_log) > 0
    return plan, fx, meta, aliases, cost_log


def load_actuals() -> tuple[dict, dict]:
    """({market: DataFrame}, source metadata). One sheet per market."""
    import sharepoint_loader as spl

    blob = None
    meta = {"source": "local file", "name": ACTUALS_NAME,
            "modified": None, "modified_by": None, "web_url": None}
    if spl.is_configured():
        import os
        prev = os.environ.get("SP_FILE_NAME")
        os.environ["SP_FILE_NAME"] = ACTUALS_NAME
        try:
            blob, meta = spl.fetch_workbook()
            meta["source"] = "SharePoint"
        finally:
            if prev is None:
                os.environ.pop("SP_FILE_NAME", None)
            else:
                os.environ["SP_FILE_NAME"] = prev

    if blob is None:
        if not LOCAL_ACTUALS.exists():
            raise FileNotFoundError(f"{ACTUALS_NAME} not found")
        src: io.BytesIO | Path = LOCAL_ACTUALS
    else:
        src = blob

    sheets = {}
    for m in MARKETS:
        if isinstance(src, io.BytesIO):
            src.seek(0)
        try:
            sheets[m] = pd.read_excel(src, sheet_name=m)
        except ValueError:
            continue
    return sheets, meta


def load_actuals_api(year: int = 2026, cost_log=None, plan=None):
    """Actuals from the Shopify API, rolled up to product x market x month.

    Preferred over the workbook: the API exposes processedAt, so migrated
    orders land in the month the customer actually bought, and it resolves
    the catalogue product name for line items recorded under an old title.
    """
    import shopify_loader as sl
    import variance_engine as ve

    lines, meta = sl.fetch_all(year)
    return ve.from_line_items(lines, year, cost_log, plan), meta, lines


def load_actuals_any(year: int = 2026, cost_log=None, plan=None):
    """API when configured, the pasted workbook otherwise."""
    import shopify_loader as sl
    if sl.is_configured():
        return load_actuals_api(year, cost_log, plan)
    import variance_engine as ve
    sheets, meta = load_actuals()
    return ve.normalise_actuals(sheets), meta, None
