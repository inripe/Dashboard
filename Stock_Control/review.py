# -*- coding: utf-8 -*-
"""
The Review section: one function per tab.

Adding a tab is one function and one line in TABS. Nothing existing is
touched, so a new report cannot break an old one. Every function takes the
same context and only reads - none of them writes anything.

One rule holds throughout: every number carries a comparison. A target, last
month, or another market. A figure with nothing beside it cannot be judged,
so it does not earn a place on the screen.
"""
import pandas as pd
import numpy as np
import streamlit as st

TARGET_LOSS = 0.03          # falls back to the sheet's own setting
TARGET_DAYS = 3


# ----------------------------------------------------------------- helpers
def _months(moves, back=4):
    """The last few whole months present in the log, oldest first."""
    if not len(moves) or "Date" not in moves.columns:
        return []
    d = pd.to_datetime(moves["Date"], errors="coerce").dropna()
    if not len(d):
        return []
    ms = sorted(d.dt.to_period("M").unique())
    return [str(x) for x in ms[-back:]]


def _by_month(moves, movement, when):
    m = moves[moves["Movement"] == movement]
    if not len(m):
        return 0.0
    d = pd.to_datetime(m["Date"], errors="coerce")
    return float(m.loc[d.dt.to_period("M").astype(str) == when, "Qty"].sum())


def _rate(part, whole):
    return (part / whole * 100) if whole else 0.0


def _arrow(now, before, good="down"):
    """Which way it moved, and whether that is good."""
    if before is None or before == 0:
        return "", ""
    diff = now - before
    if abs(diff) < 0.05:
        return "level", ""
    up = diff > 0
    better = (not up) if good == "down" else up
    return ("up" if up else "down"), ("good" if better else "bad")


def tile(col, label, value, note="", tone=""):
    colour = {"bad": "#C0392B", "good": "#1D8A5E"}.get(tone, "#1E2A3D")
    bg = {"bad": "#FDF2F2", "good": "#F2FBF6"}.get(tone, "transparent")
    col.markdown(
        f'<div style="border:.5px solid #E3E7ED;border-radius:8px;'
        f'padding:.6rem .8rem;background:{bg}">'
        f'<div style="font-size:.68rem;letter-spacing:.06em;'
        f'text-transform:uppercase;color:#8A94A6">{label}</div>'
        f'<div style="font-size:1.5rem;font-weight:600;color:{colour};'
        f'line-height:1.25">{value}</div>'
        f'<div style="font-size:.75rem;color:#8A94A6">{note}</div></div>',
        unsafe_allow_html=True)


def bar(pct, cap=20.0, tone="warn"):
    c = {"bad": "#F3B6B6", "warn": "#F9DCB4", "good": "#CBE7D5"}[tone]
    w = min(max(pct / cap * 100, 2), 100)
    return (f'<div style="background:{c};height:9px;width:{w:.0f}%;'
            f'border-radius:2px"></div>')


# -------------------------------------------------------------------- tabs
def executive(x):
    """Season to date, and whether it is getting better or worse."""
    st_, mv, cfg = x["stock"], x["moves"], x["cfg"]
    target = float(cfg.get("loss_target") or TARGET_LOSS) * 100
    months = _months(mv)
    if not months:
        st.info("Nothing recorded yet.")
        return
    now, before = months[-1], (months[-2] if len(months) > 1 else None)

    def month_rates(when):
        recv = _by_month(mv, "Received", when)
        loss = (_by_month(mv, "Scrap", when)
                + _by_month(mv, "Return to Scrap", when)
                + _by_month(mv, "Not received", when))
        out = _by_month(mv, "To Courier", when)
        back = _by_month(mv, "Returned", when)
        return recv, _rate(loss, recv), _rate(back, out), out, back, loss

    r_now = month_rates(now)
    r_bef = month_rates(before) if before else None
    label = pd.Period(now).strftime("%b")

    k = st.columns(4)
    tile(k[0], "Received", f"{st_['Received'].sum():,.0f}",
         f"{x['ship']['Shipment ID'].nunique()} shipments")
    d, tone = _arrow(r_now[1], r_bef[1] if r_bef else None)
    tile(k[1], "Thrown away", f"{r_now[1]:.1f}%",
         f"{label} · target {target:.0f}%"
         + (f" · was {r_bef[1]:.1f}%" if r_bef else ""),
         "bad" if r_now[1] > target else "good")
    d2, tone2 = _arrow(r_now[2], r_bef[2] if r_bef else None)
    tile(k[2], "Came back", f"{r_now[2]:.1f}%",
         f"{label}" + (f" · was {r_bef[2]:.1f}%" if r_bef else ""),
         "bad" if tone2 == "bad" else "")
    # how long a shipment took to empty, measured on the ones that did. Days
    # open counts the age of everything including shipments long since
    # finished, which is not the same question.
    cl = x["clear"]
    done = cl[cl["Cleared"] == "Yes"] if len(cl) else cl
    open_now = cl[cl["Cleared"] == "No"] if len(cl) else cl
    med = float(done["Span"].dropna().median()) if len(done) and \
        done["Span"].notna().any() else float("nan")
    late = int((open_now["DaysOpen"] > TARGET_DAYS).sum()) if len(open_now) else 0
    tile(k[3], "Clears in",
         f"{med:.0f} days" if med == med else "—",
         f"target {TARGET_DAYS} · {late} still open past it"
         if late else f"target {TARGET_DAYS} · none overdue",
         "bad" if late else "good")

    st.subheader("Month by month")
    rows = []
    for w in months:
        recv, loss_pct, ret_pct, out, back, loss = month_rates(w)
        rows.append({"Month": pd.Period(w).strftime("%b"), "Received": recv,
                     "Scrap %": loss_pct, "Out": out, "Return %": ret_pct})
    d = pd.DataFrame(rows)
    html = ['<table style="width:100%;border-collapse:collapse;font-size:.85rem">',
            '<tr style="color:#8A94A6;font-size:.72rem"><td style="padding:4px 6px">'
            '</td><td style="text-align:right">Received</td>'
            '<td style="text-align:right">Scrap %</td><td style="width:20%"></td>'
            '<td style="text-align:right">Return %</td><td style="width:20%"></td></tr>']
    for r in d.itertuples():
        html.append(
            f'<tr style="border-top:.5px solid #EEF1F5">'
            f'<td style="padding:6px">{r.Month}</td>'
            f'<td style="text-align:right">{r.Received:,.0f}</td>'
            f'<td style="text-align:right">{getattr(r, "_3"):.1f}%</td>'
            f'<td>{bar(getattr(r, "_3"), max(d["Scrap %"].max(), target * 2), "bad" if getattr(r, "_3") > target else "good")}</td>'
            f'<td style="text-align:right">{getattr(r, "_5"):.1f}%</td>'
            f'<td>{bar(getattr(r, "_5"), max(d["Return %"].max(), 1))}</td></tr>')
    html.append("</table>")
    st.markdown("".join(html), unsafe_allow_html=True)
    st.markdown(f'<div class="note">Scrap target {target:.0f}%. '
                f'Every figure is from the ledger, none is forecast.</div>',
                unsafe_allow_html=True)

    st.subheader("What the supplier sent")
    if "PO Qty" in x["ship"].columns:
        s = x["ship"].copy()
        s["PO Qty"] = pd.to_numeric(s["PO Qty"], errors="coerce").fillna(0)
        po = s[s["PO Qty"] > 0]
        if len(po):
            g = po.groupby("Market").agg(
                Ordered=("PO Qty", "sum"), Sent=("Shipped Qty", "sum"))
            g["Short"] = g["Ordered"] - g["Sent"]
            g["Short %"] = g["Short"] / g["Ordered"] * 100
            recv = st_.groupby("Market")["Received"].sum()
            g["Arrived"] = g.index.map(recv).fillna(0)
            g["Lost in transit"] = g["Sent"] - g["Arrived"]
            x["table"](g.reset_index().style.format(
                {c: "{:,.0f}" for c in
                 ["Ordered", "Sent", "Short", "Arrived", "Lost in transit"]}
                | {"Short %": "{:.1f}%"}))
            st.markdown('<div class="note">Ordered against sent is the '
                        'supplier. Sent against arrived is the journey.</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown('<div class="note">No order quantities recorded yet.'
                        '</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="note">No PO column on the sheet yet.</div>',
                    unsafe_allow_html=True)


def today(x):
    """Anything that needs attention right now, and nothing else."""
    x["today_body"](x)


def stock(x):
    x["stock_body"](x)


def shipments(x):
    x["shipments_body"](x)


def losses(x):
    x["losses_body"](x)


def couriers(x):
    x["couriers_body"](x)


def data_check(x):
    x["datacheck_body"](x)


def guide(x):
    x["guide_body"](x)


# Order on screen. Adding a report is one function above and one line here.
TABS = [
    ("Executive",  executive,  "how the season is going"),
    ("Today",      today,      "anything wrong right now"),
    ("Stock",      stock,      "what we hold and how old"),
    ("Shipments",  shipments,  "ordered, sent, arrived, cleared"),
    ("Losses",     losses,     "what we threw away and why"),
    ("Couriers",   couriers,   "who brings stock back"),
    ("Data check", data_check, "what does not add up"),
    ("Guide",      guide,      "how to use it"),
]

NAMES = [t[0] for t in TABS]
