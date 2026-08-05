"""Data quality tab — the page that shows what data_quality.py found.

Presentation only. Every figure comes from data_quality.run_all, so the tab
cannot disagree with the checks, and a check added there appears here
without this file changing.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import data_quality as dq

ICON = {"fail": "🔴", "warn": "🟡", "pass": "🟢"}
WORD = {"fail": "Failed", "warn": "Warning", "pass": "Passed"}


def _fmt(v: float | None) -> str:
    if v is None:
        return ""
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def render(lines: pd.DataFrame, plan: pd.DataFrame, scope,
           cost_log: pd.DataFrame | None = None,
           currency: str = "") -> None:
    """Draw the whole tab. Call this from app.py inside the tab block."""
    st.caption(
        "Every check that can tell you a figure on this dashboard is not to "
        "be trusted. Red means a headline number is wrong or unusable. "
        "Amber is worth knowing. Green is checked and clean."
    )

    with st.spinner("Running checks…"):
        results = dq.run_all(lines, plan, scope, cost_log)
    s = dq.summary(results)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Checks run", s["total"])
    c2.metric("Failed", s["failed"])
    c3.metric("Warnings", s["warnings"])
    c4.metric("Passed", s["passed"])

    if s["clean"]:
        st.success("No failures. Every headline figure reconciles.")
    else:
        st.error(
            f"{s['failed']} check(s) failed. Figures affected by a red check "
            "should not be acted on until it clears."
        )

    only_problems = st.toggle("Show problems only", value=True)

    st.divider()

    for section in dq.SECTIONS:
        rows = [r for r in results if r["section"] == section]
        if only_problems:
            rows = [r for r in rows if r["severity"] != "pass"]
        if not rows:
            continue

        fails = sum(1 for r in rows if r["severity"] == "fail")
        warns = sum(1 for r in rows if r["severity"] == "warn")
        tail = []
        if fails:
            tail.append(f"{fails} failed")
        if warns:
            tail.append(f"{warns} warning")
        st.subheader(section, anchor=False)
        if tail:
            st.caption(" · ".join(tail))

        for r in rows:
            head = f"{ICON.get(r['severity'], '')}  {r['title']}"
            if r["value"] is not None:
                head += f"  —  {currency} {_fmt(r['value'])}".rstrip()

            with st.expander(head, expanded=(r["severity"] == "fail")):
                if r["detail"]:
                    st.write(r["detail"])
                if r["fix"]:
                    st.info(f"**What to do:** {r['fix']}")
                rows_df = r.get("rows")
                if rows_df is not None and len(rows_df):
                    st.dataframe(rows_df, use_container_width=True,
                                 hide_index=True)
                    st.download_button(
                        "Download these rows",
                        rows_df.to_csv(index=False).encode("utf-8"),
                        file_name=f"{r['title'][:40].replace(' ', '_')}.csv",
                        mime="text/csv",
                        key=f"dl_{section}_{r['title'][:30]}",
                    )

        st.divider()

    st.caption(
        "Checks run against the current filter selection. Narrow the market "
        "or date range above to check a slice."
    )
