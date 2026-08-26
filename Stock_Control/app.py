import streamlit as st, pandas as pd, numpy as np, altair as alt, os
import engine
import sharepoint_loader as sp
import entry, entry_ui, auth, labels as L
import dispatch as dsp
import shopify_reader as shopify

st.set_page_config(page_title="Inripe · Inventory Control", page_icon="📦", layout="wide")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("INRIPE_FILE", os.path.join(HERE, "INRIPE_Stock_Entry_v1.xlsx"))

NAVY="#13233B"; PANEL="#FFFFFF"; LINE="#E2E8F2"; INK="#1E2A3D"; MUT="#6B7A91"
ACC="#2E75B6"; GRN="#1D8A5E"; RED="#C0392B"; AMB="#C77E1B"; VIO="#6C4FBF"

st.markdown(f"""<style>
.block-container{{padding-top:4.2rem;padding-bottom:3rem;max-width:1500px}}
[lang="ar"],.ar{{font-family:"Noto Naskh Arabic","Geeza Pro",serif}}
h2{{font-size:.78rem!important;font-weight:600!important;text-transform:uppercase;
   letter-spacing:.09em;color:{MUT}!important;margin:1.7rem 0 .6rem!important}}
h3{{font-size:.95rem!important;font-weight:600!important;margin:1rem 0 .4rem!important;color:{INK}}}
button[data-baseweb="tab"]{{font-weight:600;font-size:.88rem}}
div[data-baseweb="tab-highlight"]{{background:{ACC}!important}}
div[data-baseweb="tab-list"]{{gap:.3rem;border-bottom:1px solid {LINE}}}
.stButton>button{{border-radius:8px;font-size:.8rem;border:1px solid {LINE}}}
.stButton>button:hover{{border-color:{ACC};color:{ACC}}}
hr{{border-color:{LINE}}}
[data-testid="stHeaderActionElements"]{{display:none}}
.band{{background:{NAVY};margin:0 -5rem 1.1rem;padding:1.5rem 5rem 1.3rem;
       overflow:visible;border-radius:0}}
.hdr{{display:flex;align-items:center;gap:14px;line-height:1.25}}
.hdr h1{{font-size:1.55rem;font-weight:600;margin:0;padding:.12em 0;color:#FFFFFF;
        letter-spacing:-.01em;line-height:1.3}}
.band .sub{{color:#9BB0CC;font-size:.79rem;margin:.25rem 0 0 58px}}
.kpi{{background:{PANEL};border:1px solid {LINE};border-left:3px solid {ACC};
   border-radius:10px;padding:.7rem .85rem}}
.kpi .l{{font-size:.66rem;color:{MUT};text-transform:uppercase;letter-spacing:.07em;font-weight:600}}
.kpi .v{{font-size:1.7rem;font-weight:600;line-height:1.25;color:{INK}}}
.kpi .n{{font-size:.66rem;color:{MUT}}}
.sl{{font-size:.66rem;color:{MUT};text-transform:uppercase;letter-spacing:.07em;font-weight:600}}
.sd{{float:right;font-weight:600;letter-spacing:0;text-transform:none}}
.tw{{overflow-x:auto;border:1px solid {LINE};border-radius:10px;background:{PANEL}}}
.tw.scroll{{overflow-y:auto;max-height:var(--tw-h,400px)}}
.tw.scroll thead th{{position:sticky;top:0;z-index:2}}
.tw table{{width:100%;border-collapse:collapse;font-size:.82rem}}
.tw th{{background:#F1F5FA;color:{MUT};font-weight:600;text-transform:uppercase;
   font-size:.65rem;letter-spacing:.06em;padding:.55rem .7rem;text-align:right;
   white-space:nowrap;border-bottom:1px solid {LINE}}}
.tw th.blank,.tw th.index_name,.tw th.row_heading,.tw th.col0{{text-align:left}}
.tw td{{padding:.5rem .7rem;text-align:right;border-bottom:1px solid #EEF2F8;color:{INK};white-space:nowrap}}
.tw th.row_heading,.tw td:first-child{{text-align:left;font-weight:500}}
.tw tbody tr:last-child td{{border-bottom:none}}
.tw tbody tr:hover td{{background:#F5F8FC}}
.pill{{display:inline-block;padding:.12rem .5rem;border-radius:999px;font-size:.68rem;font-weight:600}}
.note{{color:{MUT};font-size:.72rem;margin-top:.35rem}}
.card{{background:{PANEL};border:1px solid {LINE};border-radius:10px;padding:.8rem .95rem;color:{INK}}}
</style>""", unsafe_allow_html=True)

LOGO = f"""<svg width="44" height="44" viewBox="0 0 48 48" fill="none">
<rect x="1" y="1" width="46" height="46" rx="11" fill="#1B3050" stroke="#2A456B"/>
<path d="M24 11 L35 16.5 L24 22 L13 16.5 Z" fill="#6BA7E8"/>
<path d="M13 19.5 L24 25 L24 37 L13 31.5 Z" fill="#6BA7E8" opacity=".42"/>
<path d="M35 19.5 L24 25 L24 37 L35 31.5 Z" fill="#6BA7E8" opacity=".68"/>
<path d="M5 26 h4 M5 30 h6 M5 34 h3" stroke="#4FD1A5" stroke-width="1.6" stroke-linecap="round"/>
</svg>"""
st.markdown(f'<div class="band"><div class="hdr">{LOGO}<h1>Inripe · Inventory Control</h1></div>'
            f'<div class="sub">Shipments, stock, couriers and losses across all markets</div></div>',
            unsafe_allow_html=True)

MARKET_TZ = {"Qatar": "Asia/Qatar", "UAE": "Asia/Dubai",
             "KSA": "Asia/Riyadh", "Egypt": "Africa/Cairo"}


def in_market_time(ts, market):
    """Show a moment in the market's own clock, so a Cairo user is not reading
    Gulf time. Returns (formatted, short tz label)."""
    if ts is None:
        return "unknown", ""
    tz = MARKET_TZ.get(market)
    t = pd.to_datetime(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    if tz:
        t = t.tz_convert(tz)
        return t.strftime("%d %b %Y · %H:%M"), f"{market} time"
    return t.tz_convert(None).strftime("%d %b %Y · %H:%M"), "UTC"


@st.cache_data(ttl=300, show_spinner="Loading data…")
def get_local(path, _mtime):
    return engine.load(path)

@st.cache_data(ttl=120, show_spinner=False)
def dispatch_run(_orders, _stock, _codes, strategy, cap_days, key):
    """Cached so switching strategy or reopening the tab is instant."""
    d, sh, xx, pool = dsp.allocate(_orders, _stock, _codes, strategy, cap_days)
    return d, sh, xx, pool, dsp.passed_over(), dsp.dead_stage2(_orders)

@st.cache_data(ttl=120, show_spinner=False)
def dispatch_compare(_orders, _stock, _codes, cap_days, key):
    return dsp.compare_strategies(_orders, _stock, _codes, cap_days)

@st.cache_data(ttl=30, show_spinner=False)
def sp_meta(_bust):
    """Cheap check: has the file been saved since we last read it?"""
    return sp.fetch_meta()

@st.cache_data(show_spinner="Loading from SharePoint…")
def get_sharepoint(stamp, _bust):
    """Keyed on the file's last-modified stamp, so a save is picked up by itself."""
    buf, meta = sp.fetch_workbook()
    return engine.load(buf) + (meta,)

SOURCE, SP_META, SP_ERROR = "local", None, None
if sp.is_configured():
    try:
        bust = st.session_state.get("_refresh", 0)
        stamp = sp_meta(bust).get("modified")
        ship, moves, count, cfg, errs, SP_META = get_sharepoint(stamp, bust)
        SOURCE = "sharepoint"
    except Exception as e:
        SP_ERROR = str(e)
if SOURCE == "local":
    if not os.path.exists(DATA):
        st.error(f"Entry file not found: {DATA}")
        if SP_ERROR: st.error(f"SharePoint also failed: {SP_ERROR}")
        st.stop()
    ship, moves, count, cfg, errs = get_local(DATA, os.path.getmtime(DATA))

ENTRY_ON = auth.is_enabled(cfg.get("users", {}))

# Three jobs, not nine tabs. Record is what happened, Dispatch is what goes out
# today, Review is how we are doing. The filters above belong to Review alone,
# which is why Record can never be blocked by one.
_sess = st.session_state.get("auth")
MODES = []
if ENTRY_ON:
    MODES.append("Record")
MODES.append("Dispatch")
MODES.append("Review")
_default = 0 if (ENTRY_ON and _sess and
                 str(_sess.get("role","")).lower() == "entry") else len(MODES)-1
if _sess and str(_sess.get("role","")).lower() == "dispatch":
    _default = MODES.index("Dispatch")
_m1, _m2 = st.columns([2, 3])
with _m1:
    MODE = st.radio("What are you doing?", MODES, index=_default,
                    horizontal=True, label_visibility="collapsed", key="mode")
with _m2:
    st.markdown(f'<div class="note" style="padding-top:.55rem">'
                f'{ {"Record":"what happened  ·  ما الذي حدث",
                     "Dispatch":"what goes out today",
                     "Review":"how we are doing"}[MODE] }</div>',
                unsafe_allow_html=True)


# the market and shipment filters belong to Review. Record writes new records
# and Dispatch reads live orders - neither should be narrowed by a filter, and
# neither can be blocked by one that happens to match nothing.
if MODE == "Review":
    f1, f2, f3, f4 = st.columns([1.2, 1.2, 1.3, 2.1])
    markets = ["All markets"] + (cfg["markets"]
                                 or sorted(ship["Market"].dropna().unique().tolist()))
    mkt = f1.selectbox("Market", markets, label_visibility="collapsed")
    shipments = ["All shipments"] + sorted(ship["Shipment ID"].dropna().unique().tolist())
    shp = f2.selectbox("Shipment", shipments, label_visibility="collapsed")
    as_of = pd.Timestamp(f3.date_input("As of", cfg["as_of"].date(),
                                       label_visibility="collapsed"))
else:
    mkt, shp = "All markets", "All shipments"
    as_of = pd.Timestamp(cfg["as_of"])
    f4 = st.container()
with f4:
    if SOURCE == "sharepoint":
        _tzm = mkt if mkt in MARKET_TZ else (
            shopify.configured_markets()[0] if shopify.configured_markets() else None)
        _when, _lbl = in_market_time(SP_META["modified"], _tzm)
        st.caption(f"SharePoint · edited {_when}"
                   + (f" ({_lbl})" if _lbl else "")
                   + f" by {SP_META.get('modified_by') or 'unknown'}")
    else:
        st.caption(f"Local file · {pd.Timestamp.fromtimestamp(os.path.getmtime(DATA)):%d %b %Y · %H:%M}")
    if st.button("Refresh"):
        st.cache_data.clear()
        st.session_state["_refresh"] = st.session_state.get("_refresh", 0) + 1
        st.rerun()
if SP_ERROR:
    st.warning(f"SharePoint unavailable, showing the file in the repo instead. {SP_ERROR}")

sf = ship.copy(); mf = moves.copy()
if mkt != "All markets": sf = sf[sf["Market"] == mkt]; mf = mf[mf["Market"] == mkt]
if shp != "All shipments": sf = sf[sf["Shipment ID"] == shp]; mf = mf[mf["Shipment"] == shp]
mf = mf[mf["Date"] <= as_of]
cf = count[count["Shipment"].isin(sf["Shipment ID"])] if len(sf) else count.iloc[0:0]

NAMES = cfg.get("item_names", {})
nm = lambda code: NAMES.get(code, code)
stock = engine.stock_by_item(sf, mf, as_of)
stock["ItemName"] = stock["Item"].map(nm)
clear = engine.clearance_by_shipment(sf, mf, as_of, cfg)
cour  = engine.courier_positions(sf, mf, as_of, cfg)
var   = engine.variance(stock, cf)

# ---------------- shared helpers ----------------
R_BLUE=["#F2F7FD","#E4EFFA","#CFE2F6","#B4D2F1","#95BEEA","#74A8E2"]
R_HEAT=["#E9F4E4","#F4F3D6","#FBEEDA","#F9DCB4","#F5BFA0","#F0A79E"]
R_RED =["#FCEEEE","#FADFDF","#F7CBCB","#F3B6B6","#EE9F9F","#E88686"]

def _shade(v, lo, hi, ramp):
    if pd.isna(v) or hi <= lo: return ""
    i = int(round((float(v)-lo)/(hi-lo)*(len(ramp)-1)))
    return f"background-color: {ramp[max(0,min(i,len(ramp)-1))]}"

def legend(text, ramp, low="low", high="high", extra=""):
    """A small colour key under a shaded table. Colour with no key is just decoration."""
    sw = "".join(f'<span style="display:inline-block;width:15px;height:9px;'
                 f'background:{c};border:1px solid rgba(0,0,0,.06)"></span>' for c in ramp)
    st.markdown(
        f'<div class="note" style="margin-top:-.35rem">{text} '
        f'<span style="color:{MUT}">{low}</span> {sw} '
        f'<span style="color:{MUT}">{high}</span>'
        + (f' &nbsp;&middot;&nbsp; {extra}' if extra else "") + '</div>',
        unsafe_allow_html=True)


def neg_red(df, cols):
    """Negative numbers in red. A negative box count is impossible, so it must show."""
    out = pd.DataFrame("", index=df.index, columns=df.columns)
    for c in cols:
        if c not in df.columns:
            continue
        v = pd.to_numeric(df[c], errors="coerce")
        out[c] = [f"color:{RED};font-weight:600" if (pd.notna(x) and x < 0) else ""
                  for x in v]
    return out


def heat_cols(df, cols, ramp, skip_zero=True):
    """Shade a numeric column. Zero and blank stay uncoloured by default."""
    out = pd.DataFrame("", index=df.index, columns=df.columns)
    for c in cols:
        v = pd.to_numeric(df[c], errors="coerce")
        pos = v[v > 0] if skip_zero else v.dropna()
        if pos.empty:
            continue
        lo, hi = pos.min(), pos.max()
        out[c] = ["" if (pd.isna(x) or (skip_zero and x <= 0))
                  else _shade(x, lo, hi, ramp) for x in v]
    return out

def heat_all(df, ramp):
    v = pd.to_numeric(df.stack(), errors="coerce").dropna()
    if v.empty:
        return pd.DataFrame("", index=df.index, columns=df.columns)
    v = df.apply(pd.to_numeric, errors="coerce")
    lo, hi = np.nanmin(v.values), np.nanmax(v.values)
    return pd.DataFrame([[_shade(x, lo, hi, ramp) for x in r] for r in v.values],
                        index=df.index, columns=df.columns)

TABLE_H = 400   # height in px of a scrolling table. 100px is about 2 rows.

def table(styler, index=False, scroll=False, height=None):
    """Text columns align left, numbers right — headers follow their column.
    scroll=True keeps the table at a fixed height with its own scrollbar."""
    s = styler if index else styler.hide(axis="index")
    df = s.data
    txt = [i for i, c in enumerate(df.columns)
           if df[c].dtype == object or not pd.api.types.is_numeric_dtype(df[c])]
    if txt:
        s = s.set_properties(subset=[df.columns[i] for i in txt], **{"text-align": "left"})
        s = s.set_table_styles([{"selector": f"th.col{i}",
                                 "props": [("text-align", "left")]} for i in txt],
                               overwrite=False)
    cls = "tw scroll" if scroll else "tw"
    sty = f' style="--tw-h:{height or TABLE_H}px"' if scroll else ""
    st.markdown(f'<div class="{cls}"{sty}>{s.to_html()}</div>', unsafe_allow_html=True)

def kpi(col, label, value, note=""):
    col.markdown(f'<div class="kpi"><div class="l">{label}</div>'
                 f'<div class="v">{value}</div><div class="n">{note}</div></div>',
                 unsafe_allow_html=True)

def dark(ch, h=280):
    return (ch.properties(height=h, background="transparent")
              .configure_view(strokeWidth=0)
              .configure_axis(grid=True, gridColor="#EDF1F7", domainColor="#DDE3EC",
                              labelColor=MUT, titleColor=MUT, labelFontSize=11, titleFontSize=11)
              .configure_legend(labelColor=MUT, titleColor=MUT, labelFontSize=11))

def pill(text, kind):
    c = {"ok":(GRN,"#E6F4EC"), "warn":(AMB,"#FCF0DC"), "bad":(RED,"#FBE9E7"), "mut":(MUT,"#EEF2F8")}[kind]
    return f'<span class="pill" style="color:{c[0]};background:{c[1]}">{text}</span>'

def _short(t, n=3):
    parts=[p for p in str(t).split(", ") if p]
    if len(parts)<=n: return ", ".join(parts)
    return ", ".join(parts[:n]) + f" … and {len(parts)-n} more"

def build_exceptions():
    rows=[]
    a=lambda w,c,d,p: rows.append({"Exception":w,"Count":int(c),"Where":d,"Priority":p})
    held = cour[cour["Flag"]=="Holding too long"] if len(cour) else cour
    a("Courier holding beyond limit", len(held),
      ", ".join(f"{r.Courier} · {r.Shipment} · {int(r.DaysSince)}d" for r in held.itertuples()), "High")
    od = clear[clear["Overdue"]]
    a("Shipment overdue to clear", len(od),
      ", ".join(f"{r.Shipment} · {int(r.Outstanding)} boxes" for r in od.itertuples()), "High")
    vv = var[var["VarPct"].abs() > cfg["var_tol"]] if len(var) else var
    a("Physical count variance", len(vv),
      ", ".join(f"{r.Shipment} · {nm(r.Item)} · {int(r.Var):+d}" for r in vv.itertuples()), "Med")
    neg = stock[stock["Store"] < 0]
    a("Negative stock", len(neg), ", ".join(f"{r.Shipment} · {nm(r.Item)}" for r in neg.itertuples()), "High")
    qa = stock[stock["QA"].round(6) != 0]
    a("Stock balance error", len(qa), ", ".join(f"{r.Shipment} · {nm(r.Item)}" for r in qa.itertuples()), "High")
    sd = stock[stock["ShipDiff"].round(6) != 0]
    a("Shipment quantity unexplained", len(sd),
      ", ".join(f"{r.Shipment} · {nm(r.Item)} · {int(r.ShipDiff):+d}" for r in sd.itertuples()), "High")
    ov = cour[cour["Flag"]=="Over-delivered"] if len(cour) else cour
    a("Courier over-delivered", len(ov), ", ".join(f"{r.Courier} · {r.Shipment}" for r in ov.itertuples()), "High")
    oc = cour[cour["Flag"]=="Order count error"] if len(cour) else cour
    a("Order counts do not add up", len(oc), ", ".join(f"{r.Courier} · {r.Shipment}" for r in oc.itertuples()), "Med")
    rq = (mf.loc[mf.Movement=="Returned","Qty"].sum()
          - mf.loc[mf.Movement=="Return to Saleable","Qty"].sum()
          - mf.loc[mf.Movement=="Return to Scrap","Qty"].sum())
    a("Returns not split to item", 1 if abs(rq) > .001 else 0, f"{rq:+.0f} boxes unaccounted" if rq else "", "Med")
    a("Rows with entry errors", len(errs), f"{len(errs)} rows across the logs", "High")
    return pd.DataFrame(rows)

def history(days=30):
    """True levels: cumulate from the first ever movement, then show the last N days."""
    if mf.empty:
        return pd.DataFrame({"Date": [as_of], "Available": [0], "Delivered": [0],
                             "LossPct": [np.nan], "Held": [0]})
    if not len(mf) or mf["Date"].isna().all():
        return pd.DataFrame(columns=["Date","Available","Delivered","LossPct","Held"])
    full = pd.date_range(mf["Date"].min(), as_of, freq="D")
    q = lambda mt: mf[mf.Movement == mt].groupby("Date")["Qty"].sum().reindex(full, fill_value=0)
    rec, scr, tos = q("Received"), q("Scrap"), q("Return to Saleable")
    adj, tc, dlv, ret = q("Count Adjustment"), q("To Courier"), pd.Series(0, index=full), q("Returned")
    out = pd.DataFrame(index=full)
    out["Available"] = (rec - scr + tos + adj - tc).cumsum()
    out["Delivered"] = dlv.rolling(7, min_periods=1).mean()
    cl_ = (scr + q("Not received") + q("Return to Scrap")).cumsum(); cr = rec.cumsum()
    out["LossPct"] = np.where(cr > 0, cl_ / cr * 100, np.nan)
    out["Held"] = (tc - dlv - ret).cumsum()
    return out.tail(days).reset_index(names="Date")

def spark(df,col,color):
    d=df.dropna(subset=[col])
    if d.empty or d[col].nunique()<=1 or len(d)<2:
        return (alt.Chart(pd.DataFrame({"x":[0],"y":[0]})).mark_point(opacity=0)
                .encode(x=alt.X("x:Q",axis=None), y=alt.Y("y:Q",axis=None))
                .properties(height=42, background="transparent").configure_view(strokeWidth=0))
    return (alt.Chart(d).mark_line(color=color, strokeWidth=2, interpolate="monotone")
            .encode(x=alt.X("Date:T",axis=None), y=alt.Y(f"{col}:Q",axis=None,scale=alt.Scale(zero=False)),
                    tooltip=[alt.Tooltip("Date:T",format="%d %b"),alt.Tooltip(f"{col}:Q",format=".1f")])
            .properties(height=42, background="transparent").configure_view(strokeWidth=0))

def delta(df,col,unit=""):
    d=df.dropna(subset=[col])
    if len(d)<8: return None
    now,prev=d[col].iloc[-1],d[col].iloc[-8]
    if prev==0: return None
    return f"{(now-prev)/abs(prev)*100:+.0f}%" if not unit else f"{now-prev:+.1f}{unit}"

EMPTY = len(sf)==0
REVIEW_TABS = ["Overview","Stock","Shipments","Couriers","Losses",
               "Data check","Guide"]
if MODE == "Record":
    _names = ["Stock moved","Shipment arrived","Today"]
elif MODE == "Dispatch":
    _names = ["Today's run"]
else:
    _names = REVIEW_TABS
TABS = st.tabs(_names)
_tab = dict(zip(_names, TABS))


def _slot(name):
    """A tab in this mode, or a container that is never shown. Each mode stops
    after its own section, so the others never run at all."""
    return _tab.get(name) or st.container()


TE  = _slot("Stock moved")
TSH = _slot("Shipment arrived")
TTD = _slot("Today")
TD  = _slot("Today's run")
T1  = _slot("Overview")
T2  = _slot("Stock")
T3  = _slot("Shipments")
T4  = _slot("Couriers")
T5  = _slot("Losses")
T6  = _slot("Data check")
T7  = _slot("Guide")


def _gate(tab, title):
      """Sign-in for one tab. The other seven stay open to everyone."""
      sess = st.session_state.get("auth")
      if sess and auth.can_open(sess, tab):
          c1, c2 = st.columns([4, 1])
          c1.markdown(f'<div class="note">Signed in as <b>{sess["user"]}</b> '
                      f'&nbsp;&middot;&nbsp; {sess["role"]}'
                      f'{" &middot; " + sess["market"] if sess.get("market") else ""}'
                      f'</div>', unsafe_allow_html=True)
          if c2.button("Sign out", key=f"out_{tab}"):
              st.session_state.pop("auth", None)
              st.rerun()
          return sess
      if sess:
          st.warning(f"{sess['user']} is signed in as {sess['role']}, which does not "
                     f"open {title}. Roles that do: "
                     + ", ".join(auth.roles_for(tab)).title() + ".")
          if st.button("Sign out", key=f"out2_{tab}"):
              st.session_state.pop("auth", None)
              st.rerun()
          return None
      st.markdown(f"**{title} — Sign in**"
                + ("  ·  تسجيل الدخول" if tab == "entry" else ""))
      names = sorted(un for un, r in cfg.get("users", {}).items()
                     if auth.can_open({"role": r.get("role")}, tab))
      c1, c2, c3 = st.columns([2, 2, 1])
      if names:
          u = c1.selectbox("User", names, index=None,
                           placeholder="Choose your name", key=f"u_{tab}")
      else:
          u = c1.text_input("User", key=f"u_{tab}")
          st.warning("No user on the MASTER sheet has a role that opens "
                     + title + ". Add one with role "
                     + " or ".join(auth.roles_for(tab)).title() + ".")
      p = c2.text_input("Password", type="password", key=f"p_{tab}")
      c3.markdown('<div style="height:1.75rem"></div>', unsafe_allow_html=True)
      if c3.button("Sign in", type="primary", key=f"in_{tab}"):
          ok, res = auth.check(u, p, cfg.get("users", {}))
          if not ok:
              st.error(res)
          elif not auth.can_open(res, tab):
              st.error(f"{res['user']} is a {res['role']} user, which does not open "
                       f"{title}.")
          else:
              st.session_state["auth"] = res
              for k in list(st.session_state):
                  if k.startswith("e_"):
                      st.session_state.pop(k, None)
              st.rerun()
      st.markdown('<div class="note">Users are listed on the MASTER sheet. Your market '
                  'comes from there, so it cannot be picked by mistake.</div>',
                  unsafe_allow_html=True)
      return None


# ============================= RECORD =============================
if ENTRY_ON and MODE == "Record":
    with TE:
        sess = _gate("entry", "Record")
    if sess:
        def _write(make, tries=4):
            """Read, change, write. Retries a clash, a lock, or a busy
            SharePoint - each of those is temporary and worth waiting for."""
            import time
            if SOURCE != "sharepoint":
                raise RuntimeError(
                    "Entry writes to the SharePoint copy. This session is "
                    "reading a local file, so saving is switched off.")
            last = None
            for attempt in range(1, tries + 1):
                buf, meta = sp.fetch_workbook()
                out, result = make(buf.getvalue())
                try:
                    sp.upload_workbook(out, etag=meta.get("etag"))
                    st.cache_data.clear()
                    return result
                except (sp.ConflictError, sp.LockedError, sp.BusyError) as ex:
                    last = ex
                    if attempt == tries:
                        break
                    time.sleep(2 * attempt)
            raise last

        def _save(rows, market):
            def make(data):
                return entry.append_moves(data, rows, sess["user"], market)
            return _write(make)

        def _void(entry_id, market):
            def make(data):
                return entry.void_entry(data, entry_id, sess["user"], market), None
            return _write(make)

        def _new_shipment(rows, market):
            def make(data):
                return entry.append_shipment(data, rows, sess["user"], market)
            return _write(make)

        _clear_all = engine.clearance_by_shipment(ship, moves, as_of, cfg)
        _stock_all = engine.stock_by_item(ship, moves, as_of)
        if SOURCE != "sharepoint":
            with TE:
                st.warning("Reading a local file, so entry is read-only here. "
                           "On the deployed app it writes to SharePoint.")

        with TE:
            try:
                entry_ui.render(ship, moves, _clear_all, _stock_all, cfg, sess,
                                _save, _void, cfg.get("item_names"),
                                show_today=False)
            except Exception as ex:
                st.error(f"This could not be shown: {ex}")

        with TSH:
            if str(sess.get("role", "")).lower() != "admin":
                st.info("Only an admin records a new shipment. Ask "
                        "whoever manages the market to add it, then record "
                        "what arrived under Stock moved.")
            else:
                if SOURCE == "sharepoint" and "s_next" not in st.session_state:
                    try:
                        buf, _m = sp.fetch_workbook()
                        raw = buf.getvalue()
                        st.session_state["s_next"] = {
                            m: entry.next_shipment_no(raw, m)
                            for m in (cfg.get("markets") or [])}
                    except Exception:
                        st.session_state["s_next"] = {}
                try:
                    entry_ui.render_shipment(ship, cfg, sess, _new_shipment)
                except Exception as ex:
                    st.error(f"This could not be shown: {ex}")

        with TTD:
            try:
                entry_ui.render_today(moves, sess, cfg, _void)
            except Exception as ex:
                st.error(f"This could not be shown: {ex}")


if MODE == "Record":
    st.stop()          # nothing below this belongs to Record


# ============================= 6 · DISPATCH =============================
if MODE == "Dispatch":
  with TD:
    _dsess = _gate("dispatch", "Dispatch") if ENTRY_ON else {"role": "open"}
    if _dsess:
        cfg_markets = shopify.configured_markets()
        if not cfg_markets:
            st.warning("No Shopify store is connected yet. Add SHOP_<MARKET>_DOMAIN, "
                       "SHOP_<MARKET>_CLIENT_ID and SHOP_<MARKET>_CLIENT_SECRET to the "
                       "app secrets - for example SHOP_QATAR_DOMAIN.")
            st.markdown('<div class="note">Until then this tab stays empty. '
                        'Nothing else on the dashboard is affected.</div>',
                        unsafe_allow_html=True)
        else:
            sheet_markets = set(stock["Market"].dropna().unique())
            usable = [m for m in cfg_markets if m in sheet_markets]
            missing_stock = [m for m in cfg_markets if m not in sheet_markets]
            if not usable:
                st.warning("Connected to " + ", ".join(cfg_markets) +
                           ", but the entry sheet has no stock for "
                           + ("either" if len(cfg_markets) == 2 else "any") + " of them.")
                usable = []
            m1, m2 = st.columns([1, 3])
            with m1:
                smkt = st.selectbox("Market", usable, index=0) if usable else None
            if missing_stock:
                m2.markdown(f'<div class="note" style="padding-top:1.9rem">Also connected: '
                            f'{", ".join(missing_stock)} \u2014 no stock in the sheet yet.'
                            f'</div>', unsafe_allow_html=True)
            d_stock = stock[stock["Market"] == smkt] if smkt else stock.iloc[0:0]
            if d_stock.empty:
                if smkt:
                    st.warning(f"No stock in the sheet for {smkt}.")
            else:
                cA, cB = st.columns([3, 1])
                with cB:
                    win = st.selectbox("Order window", [0, 7, 14, 30, 60], index=0,
                                       format_func=lambda d: "All dates" if d == 0
                                       else f"Last {d} days")
                shop_read_at = None
                truncated = False
                try:
                    with st.spinner("Reading orders from Shopify…"):
                        orders, truncated = shopify.fetch_orders(smkt, days=win or None)
                    shop_read_at = pd.Timestamp.now()
                except Exception as e:
                    orders = None
                    st.error(f"Could not read Shopify: {e}")

                if orders is not None:
                    codes = set(cfg.get("item_names", {}).keys())
                    as_of_orders = pd.Timestamp.now().normalize()
                    if SOURCE == "sharepoint" and SP_META:
                        _w, _ = in_market_time(SP_META["modified"], smkt)
                        stock_stamp = "saved " + _w.split(" · ")[0].rsplit(" ", 1)[0] \
                            + " " + _w.split(" · ")[1]
                    elif os.path.exists(DATA):
                        _w, _ = in_market_time(
                            pd.Timestamp.fromtimestamp(os.path.getmtime(DATA), tz="UTC"), smkt)
                        stock_stamp = "saved " + _w.split(" · ")[0].rsplit(" ", 1)[0] \
                            + " " + _w.split(" · ")[1]
                    else:
                        stock_stamp = "unknown"
                    if shop_read_at is not None:
                        _r, _ = in_market_time(shop_read_at.tz_localize("UTC")
                                               if shop_read_at.tzinfo is None
                                               else shop_read_at, smkt)
                        shop_stamp = _r.split(" · ")[0].rsplit(" ", 1)[0] + " " + _r.split(" · ")[1]
                    else:
                        shop_stamp = "unknown"

                    # ---------- 1 · strategy ----------
                    st.subheader("1 \u00b7 How to allocate")
                    g1, g2 = st.columns([1, 3])
                    with g1:
                        cap = st.selectbox("Nothing waits longer than", [1, 2, 3, 5, 7, 0],
                                           index=2,
                                           format_func=lambda d: "no cap" if d == 0
                                           else f"{d} day" + ("" if d == 1 else "s"))
                    cap_days = None if cap == 0 else cap
                    run_key = (len(orders), int(d_stock["Store"].sum()),
                               shop_read_at.isoformat() if shop_read_at is not None else "",
                               stock_stamp)
                    with st.spinner("Working out the best combinations…"):
                        cmpdf = dispatch_compare(orders, d_stock, codes, cap_days, run_key)
                    names = cmpdf["Strategy"].tolist()
                    same = {}
                    for a in names:
                        for b in names:
                            if a != b and cmpdf.loc[cmpdf.Strategy == a, "_sel"].iloc[0] == \
                                          cmpdf.loc[cmpdf.Strategy == b, "_sel"].iloc[0]:
                                same.setdefault(a, b)
                    view = cmpdf.drop(columns="_sel").copy()
                    view["Use it when"] = [
                        f"Same as {same[n]} today" if n in same and names.index(same[n]) < names.index(n)
                        else w for n, w in zip(view["Strategy"], view["Use it when"])]
                    strat = st.radio("Strategy", names, index=1, horizontal=True,
                                     label_visibility="collapsed")
                    def _sstyle(dfx):
                        o = pd.DataFrame("", index=dfx.index, columns=dfx.columns)
                        for i2 in dfx.index:
                            if dfx.loc[i2, "Strategy"] == strat:
                                o.loc[i2, :] = f"background-color:#EAF2FB;color:{ACC};font-weight:600"
                        return o
                    table(view.style.format({"Orders": "{:,.0f}", "Boxes out": "{:,.0f}",
                                             "Left in store": "{:,.0f}",
                                             "Oldest waiting": "{:,.0f} days"})
                          .apply(_sstyle, axis=None))
                    n_cap = 0
                    st.markdown(f'<div class="note">Urgent orders are always in, whatever you '
                                f'pick. {int(d_stock["Store"].sum()):,} boxes in stock.</div>',
                                unsafe_allow_html=True)

                    dd, sh_, xx, pool_after, nchosen, dead = dispatch_run(
                        orders, d_stock, codes, strat, cap_days, run_key)
                    chk = dsp.checks(dd, sh_, xx, orders, d_stock, pool_after,
                                     cap_days, None, codes)
                    shipno = dsp.ship_no_per_order(dd)
                    xg = dsp.group_excluded(xx)
                    rec = dsp.reconcile(dd, sh_, orders, d_stock, codes, cfg.get("item_names"))
                    o_fun, b_fun, ex = dsp.funnel(orders, dd, sh_, d_stock, codes)
                    allpass = bool(chk["Pass"].all())
                    n_disp = dd["Order"].nunique() if len(dd) else 0
                    if len(dd):
                        n_cap = int((dd.drop_duplicates("Order")["Rule"] == "CAP").sum())

                    # what changes if you switch
                    cur = cmpdf.loc[cmpdf.Strategy == strat, "_sel"].iloc[0]
                    bits = []
                    for other in names:
                        if other == strat:
                            continue
                        osel = cmpdf.loc[cmpdf.Strategy == other, "_sel"].iloc[0]
                        add, drop = sorted(cur - osel), sorted(osel - cur)
                        if not add and not drop:
                            bits.append(f"<b>{strat} instead of {other}</b> "
                                        f"<span style=\'color:{MUT}\'>&mdash; same orders</span>")
                        else:
                            bits.append(
                                f"<b>{strat} instead of {other}</b> "
                                f"<span style=\'color:{MUT}\'>&mdash; adds {len(add)}, "
                                f"drops {len(drop)}</span><br>"
                                + (f"adds: {', '.join(add[:4])}"
                                   + (f" +{len(add)-4} more" if len(add) > 4 else "") + "<br>" if add else "")
                                + (f"drops: {', '.join(drop[:4])}"
                                   + (f" +{len(drop)-4} more" if len(drop) > 4 else "") if drop else ""))
                    cc1, cc2 = st.columns(2)
                    for col, b in zip((cc1, cc2), bits):
                        col.markdown(f'<div class="card" style="font-size:.78rem;'
                                     f'line-height:1.7">{b}</div>', unsafe_allow_html=True)
                    st.write("")

                    bar_c, bar_t = (GRN, "All checks pass") if allpass else (RED, "A check failed")
                    st.markdown(
                        f'<div class="card" style="border-left:3px solid {bar_c}">'
                        f'<b style="color:{bar_c}">{bar_t}</b> &nbsp;&middot;&nbsp; '
                        f'<b>{ex["allocated"]:,.0f}</b> boxes ready for <b>{n_disp}</b> orders'
                        f' &nbsp;&middot;&nbsp; <span style="color:{MUT}">read-only, '
                        f'nothing is written</span>'
                        f'<div class="note">{strat}'
                        f'{f" &middot; {cap_days} day cap &middot; {n_cap} orders forced out" if cap_days else " &middot; no age cap"}'
                        f' &nbsp;&middot;&nbsp; stock from '
                        f'{"SharePoint" if SOURCE=="sharepoint" else "the local file"} '
                        f'({stock_stamp}) &nbsp;&middot;&nbsp; Shopify read {shop_stamp}'
                        f' &nbsp;&middot;&nbsp; {smkt} time'
                        f'</div></div>', unsafe_allow_html=True)

                    _wl = "all dates" if not win else f"last {win} days"
                    st.subheader(f"2 \u00b7 Orders \u00b7 {smkt}, {_wl}")
                    def _ostyle(d):
                        out = pd.DataFrame("", index=d.index, columns=d.columns)
                        for i in d.index:
                            stg = str(d.loc[i, "Stage"])
                            if stg.startswith("READY"):
                                out.loc[i, :] = f"color:{GRN};font-weight:600"
                            elif "short" in stg:
                                out.loc[i, :] = f"color:{AMB}"
                            elif stg.startswith("   "):
                                out.loc[i, :] = f"color:{MUT}"
                            else:
                                out.loc[i, :] = "font-weight:600"
                        return out
                    table(o_fun.style.format({"Orders": "{:,.0f}", "Boxes": "{:,.0f}"},
                                             na_rep="\u2014").apply(_ostyle, axis=None))

                    st.subheader("3 \u00b7 Boxes")
                    def _bstyle(d):
                        out = pd.DataFrame("", index=d.index, columns=d.columns)
                        for i in d.index:
                            w = str(d.loc[i, "Where the boxes are"])
                            if w.startswith("SHORT"):
                                out.loc[i, :] = f"color:{RED};font-weight:600"
                            elif "allocated" in w:
                                out.loc[i, :] = f"color:{GRN};font-weight:600"
                            elif "blocked" in w:
                                out.loc[i, :] = f"color:{AMB}"
                            elif w.startswith("   "):
                                out.loc[i, :] = f"color:{MUT}"
                            else:
                                out.loc[i, :] = "font-weight:600"
                        return out
                    table(b_fun.style.format({"Qty": "{:,.0f}"}).apply(_bstyle, axis=None))
                    st.markdown('<div class="note">Available = Allocated + Left'
                                ' &nbsp;&middot;&nbsp; Wanted = Allocated + Blocked</div>',
                                unsafe_allow_html=True)

                    with st.expander("By item", expanded=True):
                        if len(rec):
                            r2 = rec.rename(columns={"Needed": "Wanted",
                                                     "Not allocated": "Blocked"})
                            icols = ["Available","Wanted","Allocated","Blocked",
                                     "Short to buy","Left"]
                            tot = {"Item": "Total"}
                            for c in icols: tot[c] = r2[c].sum()
                            r2 = pd.concat([r2, pd.DataFrame([tot])], ignore_index=True)
                            def _istyle(d):
                                out = pd.DataFrame("", index=d.index, columns=d.columns)
                                for i in d.index:
                                    if d.loc[i, "Item"] == "Total":
                                        out.loc[i, :] = "font-weight:600"
                                    elif float(d.loc[i, "Wanted"]) == 0:
                                        out.loc[i, :] = f"color:{MUT}"
                                return out
                            table(r2[["Item"] + icols].style
                                  .format({c: "{:,.0f}" for c in icols})
                                  .apply(_istyle, axis=None)
                                  .apply(lambda d: heat_cols(d, ["Short to buy"], R_RED),
                                         axis=None),
                                  scroll=True, height=320)
                            legend("Boxes you would need to buy:", R_RED, "few", "many")
                            bad = int((rec["Stock check"] != "OK").sum()
                                      + (rec["Demand check"] != "OK").sum())
                            if bad:
                                st.markdown(f'<div class="note" style="color:{RED}">'
                                            f'{bad} rows do not reconcile.</div>',
                                            unsafe_allow_html=True)
                            else:
                                st.markdown('<div class="note">Every row reconciles. '
                                            'Totals tie to the funnel above.</div>',
                                            unsafe_allow_html=True)

                    st.subheader(f"4 \u00b7 Dispatch list \u00b7 {n_disp} orders")
                    if len(dd):
                        lines = dd.assign(ItemName=dd["Item"].map(nm))
                        items = (lines.groupby(["Order","ItemName"])["Qty"].sum()
                                      .reset_index()
                                      .assign(txt=lambda t: t["ItemName"] + " x" +
                                              t["Qty"].astype(int).astype(str))
                                      .groupby("Order")["txt"]
                                      .apply(lambda v: ", ".join(v)))
                        per = (lines.groupby("Order")
                                    .agg(Placed=("Placed","first"), Rule=("Rule","first"),
                                         Boxes=("Qty","sum"),
                                         From=("Shipment", lambda v: ", ".join(sorted(set(v)))))
                                    .reset_index())
                        per["Items"] = per["Order"].map(items)
                        per["Ship. No."] = per["Order"].map(shipno)
                        per["_u"] = (per["Rule"] != "URG")
                        per = per.sort_values(["_u","Placed"]).drop(columns="_u")
                        dcols = ["Order","Placed","Rule","Items","Boxes","From","Ship. No."]
                        table(per[dcols].style.format({"Boxes":"{:,.0f}"}), scroll=True)
                        urg_txt = f" \u00b7 {ex['urgent']} urgent first" if ex["urgent"] else ""
                        st.markdown(f'<div class="note">{len(per)} orders{urg_txt} '
                                    f'\u00b7 scroll inside the table</div>',
                                    unsafe_allow_html=True)
                        st.download_button(
                            "Download dispatch list",
                            per[dcols].to_csv(index=False).encode("utf-8"),
                            file_name=f"dispatch_{smkt}_{pd.Timestamp.now():%Y%m%d_%H%M}.csv",
                            mime="text/csv")
                    else:
                        st.markdown(f'<span style="color:{MUT}">Nothing can be dispatched '
                                    f'from current stock.</span>', unsafe_allow_html=True)

                    blockers = ""
                    if len(sh_):
                        top = (sh_.assign(Item=sh_["Item"].map(nm))
                                  .groupby("Item")["Short by"].sum()
                                  .sort_values(ascending=False).head(2).index.tolist())
                        blockers = " \u00b7 blocked by " + " and ".join(top)
                    with st.expander(f"5 \u00b7 Short \u00b7 {ex['short_orders']} orders, "
                                     f"{ex['short_boxes']:,.0f} boxes{blockers}"):
                        if len(sh_):
                            table(sh_.assign(Item=sh_["Item"].map(nm))
                                  .style.format({"Short by":"{:,.0f}"}),
                                  scroll=True, height=300)
                            st.markdown('<div class="note">Boxes to buy are in the By item '
                                        'table above.</div>', unsafe_allow_html=True)
                        else:
                            st.markdown(f'<span style="color:{MUT}">Nothing short.</span>',
                                        unsafe_allow_html=True)

                    summ = ""
                    if len(xg):
                        summ = " \u00b7 " + ", ".join(
                            f"{int(r.Orders)} {str(r.Reason).lower()}"
                            for r in xg.head(2).itertuples())
                    with st.expander(f"6 \u00b7 Excluded \u00b7 {len(xx)} of "
                                     f"{ex['scope']} stage 2 orders{summ}"
                                     + (f"  \u00b7  plus {len(dead)} cancelled or voided"
                                        if len(dead) else "")):
                        if len(xx):
                            st.markdown('<div class="note">These are stage 2 orders the engine '
                                        'cannot allocate. Each one is listed with its reason.'
                                        '</div>', unsafe_allow_html=True)
                            xd = xx.copy()
                            if len(xd) > 15:
                                table(xg.style.format({"Orders": "{:,.0f}"}))
                                st.write("")
                            table(xd.style, scroll=True, height=280)
                            st.markdown(f'<div class="note">{n_disp} ready + '
                                        f'{ex["short_orders"]} short + {len(xx)} excluded '
                                        f'= {ex["scope"]} orders at stage 2.</div>',
                                        unsafe_allow_html=True)
                        else:
                            st.markdown(f'<span style="color:{MUT}">Nothing excluded \u2014 '
                                        f'every stage 2 order could be allocated.</span>',
                                        unsafe_allow_html=True)
                        if len(dead):
                            st.write("")
                            st.markdown('<div class="note">Cancelled or voided, so not '
                                        'counted anywhere above. Shopify hides these too, '
                                        'which is why the stage 2 count matches your '
                                        'Shopify view.</div>', unsafe_allow_html=True)
                            table(dead.style)

                    with st.expander(f"7 \u00b7 All stage 2 orders \u00b7 {ex['scope']} "
                                     f"\u00b7 for checking against Shopify"):
                        sl = dsp.scope_list(orders, dd, sh_, xx)
                        if len(sl):
                            table(sl.style.format({"Boxes": "{:,.0f}"}), scroll=True, height=340)
                            st.download_button(
                                "Download this list as CSV",
                                sl.to_csv(index=False).encode("utf-8"),
                                file_name=f"stage2_orders_{smkt}_"
                                          f"{pd.Timestamp.now():%Y%m%d_%H%M}.csv",
                                mime="text/csv")
                            st.markdown('<div class="note">Export the same view from Shopify '
                                        'and compare the order numbers. Any order here but '
                                        'not there, or the reverse, is the one to look at.'
                                        '</div>', unsafe_allow_html=True)
                        else:
                            st.markdown(f'<span style="color:{MUT}">No stage 2 orders.</span>',
                                        unsafe_allow_html=True)

                    ctxt = f"all {len(chk)} pass" if allpass else "FAILED"
                    with st.expander(f"8 \u00b7 Checks \u00b7 {ctxt}"):
                        cc = st.columns(2)
                        for i, r in enumerate(chk.itertuples()):
                            mark, colr = ("PASS", GRN) if r.Pass else ("FAIL", RED)
                            cc[i % 2].markdown(
                                f'<div style="font-size:.8rem;color:{colr}">{mark} \u2014 '
                                f'{r.Check} <span style="color:{MUT}">\u2014 {r.Result}'
                                f'</span></div>', unsafe_allow_html=True)

                    st.markdown(f'<div class="card" style="border-left:3px solid {MUT}">'
                                f'<b>Confirm is not available in this build.</b>'
                                f'<div class="note">Writing to Shopify and Excel is added '
                                f'only after this list has been checked against your own '
                                f'judgement.</div></div>', unsafe_allow_html=True)


if MODE == "Dispatch":
    st.stop()          # the reports below belong to Review only


if EMPTY and MODE == "Review":
    if True:
        for T, name in zip(TABS, _names):
            with T:
                st.info("No shipments match this filter. Choose another market "
                        "or shipment above.")
    st.stop()

exc = build_exceptions(); open_exc = exc[exc["Count"]>0]
hist = history()
held_total = cour["Held"].sum() if len(cour) else 0
oldest = int(stock.loc[stock["Store"]>0,"AgeDays"].max()) if (stock["Store"]>0).any() else 0

# ============================ 1 · OVERVIEW ============================
with T1:
    if len(open_exc):
        n=int(open_exc["Count"].sum())
        kinds=" · ".join(f'{r.Exception} ({r.Count})' for r in open_exc.head(3).itertuples())
        more=f" · +{len(open_exc)-3} more types" if len(open_exc)>3 else ""
        st.markdown(f'<div class="card" style="border-left:3px solid {RED}">'
                    f'<b style="color:{RED}">{n} item{"s" if n!=1 else ""} need action</b>'
                    f'<div class="note">{kinds}{more}</div></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="card" style="border-left:3px solid {GRN}">'
                    f'<b style="color:{GRN}">All controls pass</b></div>', unsafe_allow_html=True)
    st.write("")
    k=st.columns(6)
    kpi(k[0],"Available to sell",f"{stock['Store'].sum():,.0f}","boxes in store")
    kpi(k[1],"With couriers",f"{held_total:,.0f}","still Inripe stock")
    kpi(k[2],"Open shipments",f"{int((clear['Cleared']=='No').sum())}","not fully cleared")
    kpi(k[3],"Oldest stock",f"{oldest}","days since arrival")
    kpi(k[4],"Orders outstanding",f"{clear['OrdersOutstanding'].sum():,.0f}","with couriers")
    kpi(k[5],"Exceptions",f"{int(open_exc['Count'].sum())}","need action")

    st.subheader("30-day trend")
    s=st.columns(4)
    for col,(lab,fld,c,unit,good_up) in zip(s,[
        ("Available","Available",ACC,"",True),("Delivered per day (7-day avg)","Delivered",GRN,"",True),
        ("Loss % of received","LossPct",RED,"pp",False),("Boxes with couriers","Held",AMB,"",False)]):
        with col:
            d=delta(hist,fld,unit); up=bool(d and d.startswith("+"))
            dc=(GRN if up==good_up else RED) if d else MUT
            st.markdown(f'<div class="sl">{lab}<span class="sd" style="color:{dc}">{d or ""}</span></div>',
                        unsafe_allow_html=True)
            st.altair_chart(spark(hist,fld,c), use_container_width=True)

    st.subheader("Available to sell")
    piv=stock.pivot_table(index="ItemName",columns="Market",values="Store",aggfunc="sum",fill_value=0)
    piv.columns.name=None; piv.index.name=None
    piv["Total"]=piv.sum(axis=1)
    piv=piv.sort_values("Total",ascending=False)
    piv.loc["Total"]=piv.sum()
    piv=piv.reset_index().rename(columns={"index":"Item"})
    body=piv.iloc[:-1,1:-1]
    sty=pd.DataFrame("",index=piv.index,columns=piv.columns)
    sty.loc[body.index,body.columns]=heat_all(body,R_BLUE).values
    _pcols=[c for c in piv.columns if c!="Item"]
    table(piv.style.format({c:"{:,.0f}" for c in _pcols})
             .apply(lambda _:sty,axis=None)
             .apply(lambda d: neg_red(d,_pcols),axis=None))
    _neg=int((pd.to_numeric(piv[_pcols].stack(),errors="coerce")<0).sum())
    legend("Boxes in store:", R_BLUE, "fewer", "more",
           extra=(f'<b style="color:{RED}">{_neg} negative</b> - more went out than '
                  f'was received, check MOVES' if _neg else ""))

    st.subheader("What needs action")
    if len(open_exc):
        rows=[]
        for r in open_exc.itertuples():
            parts=[p for p in str(r.Where).split(", ") if p]
            if not parts: parts=[""]
            for i,p in enumerate(parts[:4]):
                bits=[b.strip() for b in p.split("·")]
                rows.append({"Priority": r.Priority if i==0 else "",
                             "What": r.Exception if i==0 else "",
                             "Where": bits[0] if bits else "",
                             "Detail": " · ".join(bits[1:]) if len(bits)>1 else ""})
            if len(parts)>4:
                rows.append({"Priority":"","What":"","Where":f"+{len(parts)-4} more","Detail":""})
        act=pd.DataFrame(rows)
        def _st(d):
            o=pd.DataFrame("",index=d.index,columns=d.columns)
            o["Priority"]=[f"color:{RED};font-weight:600" if v=="High"
                           else (f"color:{AMB};font-weight:600" if v=="Med" else "") for v in d["Priority"]]
            o["What"]=["font-weight:600" if v else "" for v in d["What"]]
            return o
        table(act.style.apply(_st,axis=None))
    else:
        st.markdown(f'<div class="card" style="border-left:3px solid {GRN}">'
                    f'<b style="color:{GRN}">Nothing needs action</b></div>', unsafe_allow_html=True)

# ============================== 2 · STOCK ==============================
with T2:
    k=st.columns(4)
    kpi(k[0],"Store stock",f"{stock['Store'].sum():,.0f}")
    kpi(k[1],"With couriers",f"{held_total:,.0f}")
    kpi(k[2],"Total owned",f"{stock['Store'].sum()+held_total:,.0f}")
    kpi(k[3],"Oldest",f"{oldest}","days")

    st.subheader("Stock aging · oldest first")
    ag=stock[stock["Store"]>0][["ItemName","Market","Shipment","Arrival Date","AgeDays","Store"]]
    ag=ag.rename(columns={"ItemName":"Item"})
    ag=ag.sort_values("AgeDays",ascending=False).rename(
        columns={"AgeDays":"Days","Store":"Qty","Arrival Date":"Arrival"})
    if len(ag):
        ag["Arrival"]=ag["Arrival"].dt.strftime("%d %b")
        table(ag.style.format({"Qty":"{:,.0f}"}).apply(lambda d: heat_cols(d,["Days"],R_HEAT),axis=None))
        legend("Days since arrival:", R_HEAT, "newer", "older")
        st.altair_chart(dark(alt.Chart(ag).mark_bar(cornerRadiusEnd=3).encode(
            x=alt.X("Qty:Q",title="Boxes"), y=alt.Y("Item:N",title=None,sort="-x"),
            color=alt.Color("Days:Q",scale=alt.Scale(range=["#B4D2F1","#E9A13B","#C0392B"]),title="Days"),
            tooltip=["Item","Market","Shipment","Days","Qty"]),
            h=max(140,38*ag["Item"].nunique())), use_container_width=True)

    st.subheader("Movements on the selected day")
    day=mf[mf["Date"]==as_of]
    mv=day.groupby("Movement")["Qty"].sum().reindex(engine.MV).fillna(0).reset_index()
    mv=mv[mv["Qty"]!=0]
    if len(mv): table(mv.style.format({"Qty":"{:,.0f}"}))
    else: st.markdown(f'<span style="color:{MUT}">No movements on this date.</span>',unsafe_allow_html=True)

# ============================ 3 · SHIPMENTS ============================
with T3:
    st.subheader("Shipment status")
    d=clear.copy(); d["Arrival"]=d["Arrival"].dt.strftime("%d %b")
    d["Status"]=np.where(d["Overdue"],"Overdue",np.where(d["Cleared"]=="Yes","Cleared","Open"))
    cols=["Shipment","Market","Arrival","Received","Scrap","ToCourier","Returned","Outstanding",
          "DaysOpen","Span","Status","OrdersAssigned","OrdersHanded","OrdersOutstanding","OrdersVsAssigned"]
    table(d[cols].style.format({c:"{:,.0f}" for c in
        ["Received","Scrap","ToCourier","Returned","Outstanding","DaysOpen","Span",
         "OrdersAssigned","OrdersHanded","OrdersOutstanding","OrdersVsAssigned"]}, na_rep="—")
        .apply(lambda x: heat_cols(x,["Outstanding"],R_HEAT),axis=None))
    legend("Boxes still outstanding:", R_HEAT, "few", "many")

    st.subheader("Clearance curve")
    st.markdown(f'<span style="color:{MUT};font-size:.78rem">Cumulative % of received delivered, by day '
                f'since arrival. Target {cfg["clear_target"]:.0f} days.</span>', unsafe_allow_html=True)
    dl=mf[mf["Movement"]=="To Courier"].copy()
    if len(dl):
        arr=clear.set_index("Shipment")["Arrival"]; base=clear.set_index("Shipment")["Received"]
        dl["Day"]=(dl["Date"]-dl["Shipment"].map(arr)).dt.days
        cur=dl.groupby(["Shipment","Day"])["Qty"].sum().reset_index()
        cur["Cum"]=cur.groupby("Shipment")["Qty"].cumsum()
        cur["Pct"]=cur["Cum"]/cur["Shipment"].map(base)*100
        st.altair_chart(dark(alt.Chart(cur).mark_line(point=True,strokeWidth=2).encode(
            x=alt.X("Day:Q",title="Days since arrival"),
            y=alt.Y("Pct:Q",title="% delivered",scale=alt.Scale(domain=[0,100])),
            color=alt.Color("Shipment:N",title=None,
                            scale=alt.Scale(range=[ACC,GRN,AMB,VIO,RED])),
            tooltip=["Shipment","Day",alt.Tooltip("Pct:Q",format=".1f")]), h=300),
            use_container_width=True)
    else:
        st.markdown(f'<span style="color:{MUT}">No deliveries recorded yet.</span>',unsafe_allow_html=True)

    st.subheader("Item breakdown")
    pick=None
    if len(clear): pick=st.selectbox("Shipment",clear["Shipment"].tolist(),label_visibility="collapsed")
    if pick:
        b=stock[stock["Shipment"]==pick][["ItemName","Source","Shipped Qty","Customs","Received",
            "Scrap","ToSaleable","ToCourier","Store","AgeDays"]]
        b=b.rename(columns={"ItemName":"Item","Shipped Qty":"Shipped","ToSaleable":"Back to stock",
                            "ToCourier":"To courier","Store":"In store","AgeDays":"Days"})
        table(b.style.format({c:"{:,.0f}" for c in b.columns if c not in ("Item","Source")}))

# ============================ 4 · COURIERS ============================
with T4:
    if not len(cour):
        st.markdown(f'<span style="color:{MUT}">No courier activity in this filter.</span>',unsafe_allow_html=True)
    else:
        sc=cour.groupby(["Courier","Market"]).agg(
            OrdersHanded=("OrdersHanded","sum"),OrdersDelivered=("OrdersDelivered","sum"),
            OrdersReturned=("OrdersReturned","sum"),OrdersOutstanding=("OrdersOutstanding","sum"),
            QtyOut=("ToCourier","sum"),QtyHeld=("Held","sum"),MaxDays=("DaysSince","max")).reset_index()
        sc["Return %"]=np.where(sc["OrdersHanded"]>0,sc["OrdersReturned"]/sc["OrdersHanded"]*100,0)
        sc["Flag"]=np.where(sc["QtyHeld"]<0,"Over-delivered",
                    np.where((sc["QtyHeld"]>0)&(sc["MaxDays"]>cfg["courier_limit"]),"Holding too long","OK"))
        k=st.columns(4)
        kpi(k[0],"Orders handed",f"{sc['OrdersHanded'].sum():,.0f}")
        kpi(k[1],"Orders outstanding",f"{sc['OrdersOutstanding'].sum():,.0f}")
        kpi(k[2],"Boxes held",f"{sc['QtyHeld'].sum():,.0f}")
        kpi(k[3],"Return rate",f"{sc['OrdersReturned'].sum()/max(sc['OrdersHanded'].sum(),1)*100:.1f}%")

        st.subheader("Scorecard")
        table(sc.style.format({"OrdersHanded":"{:,.0f}","OrdersDelivered":"{:,.0f}",
            "OrdersReturned":"{:,.0f}","OrdersOutstanding":"{:,.0f}","QtyOut":"{:,.0f}",
            "QtyHeld":"{:,.0f}","MaxDays":"{:,.0f}","Return %":"{:.1f}%"}, na_rep="—")
            .apply(lambda d: heat_cols(d,["Return %"],R_RED),axis=None))
        legend("Return rate:", R_RED, "low", "high")

        c1,c2=st.columns(2)
        with c1:
            st.subheader("Boxes held now")
            st.altair_chart(dark(alt.Chart(sc).mark_bar(cornerRadiusEnd=3).encode(
                x=alt.X("QtyHeld:Q",title="Boxes"), y=alt.Y("Courier:N",title=None,sort="-x"),
                color=alt.condition(alt.datum.MaxDays>cfg["courier_limit"],alt.value(RED),alt.value(ACC)),
                tooltip=["Courier","QtyHeld","MaxDays"]), h=max(140,42*len(sc))),
                use_container_width=True)
        with c2:
            st.subheader("Open positions")
            op=cour[cour["Held"]!=0][["Courier","Shipment","Market","ToCourier",
                                      "Returned","Held","DaysSince"]]
            if len(op):
                table(op.style.format({c:"{:,.0f}" for c in
                    ["ToCourier","Returned","Held","DaysSince"]},na_rep="—"))
            else:
                st.markdown(f'<span style="color:{MUT}">Every courier is clear.</span>',unsafe_allow_html=True)

# ============================= 5 · LOSSES =============================
with T5:
    rec=stock["Received"].sum(); customs=stock["Customs"].sum()
    scrap=stock["Scrap"].sum(); rscrap=stock["ReturnScrap"].sum()
    total_loss=customs+scrap+rscrap; loss_pct=total_loss/rec*100 if rec else 0
    k=st.columns(4)
    kpi(k[0],"Customs / transit",f"{customs:,.0f}","not scrap")
    kpi(k[1],"QC scrap",f"{scrap:,.0f}")
    kpi(k[2],"Return scrap",f"{rscrap:,.0f}")
    kpi(k[3],"Total loss",f"{total_loss:,.0f}",
        f"{loss_pct:.1f}% of received · target {cfg['loss_target']*100:.0f}%")

    st.subheader("Loss % of received")
    h=hist.dropna(subset=["LossPct"])
    if len(h):
        line=alt.Chart(h).mark_line(color=RED,strokeWidth=2,interpolate="monotone").encode(
            x=alt.X("Date:T",title=None),y=alt.Y("LossPct:Q",title="% of received"),
            tooltip=[alt.Tooltip("Date:T",format="%d %b"),alt.Tooltip("LossPct:Q",format=".2f")])
        tgt=alt.Chart(pd.DataFrame({"y":[cfg["loss_target"]*100]})).mark_rule(
            color=MUT,strokeDash=[5,4]).encode(y="y:Q")
        st.altair_chart(dark(line+tgt,h=250), use_container_width=True)

    c1,c2=st.columns(2)
    with c1:
        st.subheader("Scrap by reason")
        sr=mf[mf["Movement"].isin(["Scrap","Return to Scrap"])].groupby("Reason")["Qty"].sum().reset_index()
        if len(sr):
            st.altair_chart(dark(alt.Chart(sr).mark_bar(color=AMB,cornerRadiusEnd=3).encode(
                x=alt.X("Qty:Q",title="Boxes"),y=alt.Y("Reason:N",title=None,sort="-x"),
                tooltip=["Reason","Qty"]), h=max(140,36*len(sr))), use_container_width=True)
        else: st.markdown(f'<span style="color:{MUT}">No scrap recorded.</span>',unsafe_allow_html=True)
    with c2:
        st.subheader("Returns by reason")
        rr=mf[mf["Movement"]=="Returned"].groupby("Reason")["Qty"].sum().reset_index()
        if len(rr):
            st.altair_chart(dark(alt.Chart(rr).mark_bar(color=VIO,cornerRadiusEnd=3).encode(
                x=alt.X("Qty:Q",title="Boxes"),y=alt.Y("Reason:N",title=None,sort="-x"),
                tooltip=["Reason","Qty"]), h=max(140,36*len(rr))), use_container_width=True)
        else: st.markdown(f'<span style="color:{MUT}">No returns recorded.</span>',unsafe_allow_html=True)

    st.subheader("Loss by item")
    li=stock.groupby("ItemName").agg(Received=("Received","sum"),Customs=("Customs","sum"),
        Scrap=("Scrap","sum"),ReturnScrap=("ReturnScrap","sum")).reset_index()
    li=li.rename(columns={"ItemName":"Item"}).sort_values("Received",ascending=False)
    li["Total loss"]=li["Customs"]+li["Scrap"]+li["ReturnScrap"]
    li["Loss %"]=np.where(li["Received"]>0,li["Total loss"]/li["Received"]*100,0)
    table(li.style.format({c:"{:,.0f}" for c in
        ["Received","Customs","Scrap","ReturnScrap","Total loss"]} | {"Loss %":"{:.1f}%"})
        .apply(lambda d: heat_cols(d,["Loss %"],R_RED),axis=None))
    legend("Loss as a share of received:", R_RED, "low", "high")

# =========================== 6 · DATA CHECK ===========================
with T6:
    st.subheader("Is this data trustworthy?")
    trust_ok = len(errs)==0 and abs(stock["QA"]).sum()<1e-6 and abs(stock["ShipDiff"]).sum()==0
    if trust_ok:
        st.markdown(f'<div class="card" style="border-left:3px solid {GRN}">'
                    f'<b style="color:{GRN}">Data is clean</b>'
                    f'<div class="note">Every row passed its entry check and every balance reconciles.</div></div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="card" style="border-left:3px solid {RED}">'
                    f'<b style="color:{RED}">Do not trust these numbers yet</b>'
                    f'<div class="note">Fix the rows listed below in the Excel file, save, then hit Refresh.</div></div>',
                    unsafe_allow_html=True)
    st.write("")

    st.subheader("Entry errors in the Excel file")
    if len(errs):
        st.markdown(f'<div class="card" style="border-left:3px solid {RED};margin-bottom:.6rem">'
                    f'<b style="color:{RED}">{len(errs)} rows need fixing</b>'
                    f'<div class="note">Open the sheet, go to the row number, read the red Check column.</div></div>',
                    unsafe_allow_html=True)
        table(errs.style)
    else:
        st.markdown(f'<div class="card">{pill("Clean","ok")} &nbsp;'
                    f'<span style="color:{MUT}">0 rows flagged across SHIPMENTS, MOVES and COUNT.</span></div>',
                    unsafe_allow_html=True)

    st.subheader("Reconciliation")
    checks=[("Shipment", abs(stock["ShipDiff"]).sum()==0,
             "shipped = customs + received", f"{stock['Shipped Qty'].sum():,.0f} shipped"),
            ("Stock", abs(stock["QA"]).sum()<1e-6,
             "received − scrap + returns − to courier = store", f"{stock['Store'].sum():,.0f} in store"),
            ("Courier", (cour["Held"]>=0).all() if len(cour) else True,
             "out = delivered + returned + held", f"{held_total:,.0f} held"),
            ("Returns", abs(mf.loc[mf.Movement=="Returned","Qty"].sum()
                            -mf.loc[mf.Movement=="Return to Saleable","Qty"].sum()
                            -mf.loc[mf.Movement=="Return to Scrap","Qty"].sum())<1e-6,
             "returned = back to stock + scrapped",
             f"{mf.loc[mf.Movement=='Returned','Qty'].sum():,.0f} returned")]
    cc=st.columns(4)
    for col,(name,ok,note,val) in zip(cc,checks):
        c,bg=(GRN,"#E6F4EC") if ok else (RED,"#FBE9E7")
        col.markdown(f'<div class="card" style="border-left:3px solid {c}">'
                     f'<div class="l" style="font-size:.66rem;color:{MUT};text-transform:uppercase;'
                     f'letter-spacing:.07em;font-weight:600">{name}</div>'
                     f'<div style="font-size:1.05rem;font-weight:600;color:{c}">'
                     f'{"Balanced" if ok else "Off"}</div>'
                     f'<div class="note">{val}<br>{note}</div></div>', unsafe_allow_html=True)

    st.subheader("Exceptions")
    e=exc.copy()
    e["Status"]=np.where(e["Count"]>0,e["Priority"],"clear")
    def _row_style(d):
        out=pd.DataFrame("",index=d.index,columns=d.columns)
        for i in d.index:
            if d.loc[i,"Count"]>0:
                bg="#FBE9E7" if d.loc[i,"Priority"]=="High" else "#FCF0DC"
                out.loc[i,:]=f"background-color: {bg}"
            else:
                out.loc[i,:]=f"color: {MUT}"
        return out
    e["Where"]=e["Where"].map(lambda t: _short(t, 2))
    table(e[["Exception","Count","Where","Status"]].style.apply(
        lambda d: _row_style(e).loc[:, ["Exception","Count","Where","Status"]], axis=None))

    st.subheader("Physical count variance")
    if len(var):
        v=var[["Date","Shipment","Item","System","Physical","Var"]].copy()
        v["Item"]=v["Item"].map(nm)
        v["Date"]=v["Date"].dt.strftime("%d %b")
        table(v.style.format({c:"{:,.0f}" for c in ["System","Physical","Var"]})
              .apply(lambda d: heat_cols(d.assign(AbsVar=d["Var"].abs()).drop(columns="AbsVar"),
                                         ["Var"],R_RED),axis=None))
        legend("Variance against the system figure:", R_RED, "small", "large")
        st.markdown(f'<div class="note">To correct a variance, post a Count Adjustment row in MOVES '
                    f'with a reason. A count never changes stock by itself.</div>',unsafe_allow_html=True)
    else:
        st.markdown(f'<span style="color:{MUT}">No counts recorded in this filter.</span>',unsafe_allow_html=True)

# ============================== 7 · GUIDE ==============================
with T7:
    st.subheader("How a shipment flows  ·  كيف تسير الشحنة")
    st.markdown(f"""<div class="card">
<b>Two people, two jobs.</b> You record what was <b>sent</b>. The store records
what <b>arrived</b>. The difference is your transit loss, and it only stays
visible because they are entered separately.
<div style="direction:rtl;text-align:right;margin-top:.5rem">
<b>شخصان، مهمتان.</b> أنت تسجل ما تم <b>إرساله</b>. المخزن يسجل ما <b>وصل</b>.
الفرق بينهما هو الفاقد أثناء النقل، ويظل ظاهراً لأن كلاً منهما يُسجَّل على حدة.
</div></div>""", unsafe_allow_html=True)

    flow = pd.DataFrame([
        ["1", "Shipment created — 500 shipped", "You", "Entry → New shipment",
         "\u0625\u0646\u0634\u0627\u0621 \u0627\u0644\u0634\u062d\u0646\u0629 \u2014 500 \u0645\u0631\u0633\u0644"],
        ["2", "480 arrive", "Store", "Entry → \u2193 IN Received",
         "\u0648\u0635\u0644 480 \u2014 \u0627\u0633\u062a\u0644\u0627\u0645"],
        ["3", "5 damaged", "Store", "Entry → \u2191 OUT Scrap, reason Damage",
         "5 \u062a\u0627\u0644\u0641 \u2014 \u0625\u062a\u0644\u0627\u0641"],
        ["4", "15 never arrived", "You", "Entry → \u2191 OUT Not received",
         "15 \u0644\u0645 \u062a\u0635\u0644 \u2014 \u0641\u0642\u062f \u0641\u064a \u0627\u0644\u062c\u0645\u0627\u0631\u0643"],
        ["5", "475 sold and handed over", "Store", "Entry → \u2191 OUT To Courier",
         "\u062a\u0633\u0644\u064a\u0645 \u0644\u0644\u0645\u0646\u062f\u0648\u0628"],
        ["6", "Customer refuses, it comes back", "Store",
         "Entry → \u2193 IN Returned",
         "\u0645\u0631\u062a\u062c\u0639"],
        ["7", "Everything else the courier took", "nobody",
         "counted for you, never typed",
         "\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644 \u2014 "
         "\u064a\u064f\u062d\u0633\u0628 \u062a\u0644\u0642\u0627\u0626\u064a\u0627\u064b"],
    ], columns=["", "What happened", "Who", "Where", "\u0627\u0644\u0639\u0631\u0628\u064a\u0629"])
    def _fstyle(d):
        o = pd.DataFrame("", index=d.index, columns=d.columns)
        o["Who"] = [f"color:{ACC};font-weight:600" if v == "You"
                    else (f"color:{MUT}" if v == "nobody"
                          else f"color:{GRN};font-weight:600") for v in d["Who"]]
        o["\u0627\u0644\u0639\u0631\u0628\u064a\u0629"] = "direction:rtl;text-align:right"
        return o
    table(flow.style.apply(_fstyle, axis=None))
    st.markdown(f'<div class="note">Shipped 500, received 480, scrapped 5 → '
                f'<b>15 lost in transit</b>, <b>475 sellable</b>. If the store '
                f'had simply entered 480 as the shipment, those 15 would have '
                f'disappeared without trace.</div>', unsafe_allow_html=True)

    st.subheader("Where things are recorded")
    st.markdown(f"""<div class="card">
<b>Nobody types in the Excel any more.</b> Everything goes through the Entry tab,
and the workbook is the record it writes to.<br><br>
<span style="color:{MUT}">Entry → New shipment</span> — admin only. What was sent.<br>
<span style="color:{MUT}">Entry → Movement</span> — the store. What physically happened.<br>
<span style="color:{MUT}">SHIPMENTS, MOVES, COUNT</span> — written by the app, read by this dashboard.<br><br>
<b>Golden rule:</b> stock only ever changes through a movement. A count never
changes stock by itself — post a Count Adjustment instead.
<div style="direction:rtl;text-align:right;margin-top:.6rem">
<b>القاعدة الذهبية:</b> المخزون لا يتغير إلا بحركة. الجرد وحده لا يغيّر المخزون —
سجّل تسوية جرد بدلاً من ذلك.
</div></div>""", unsafe_allow_html=True)

    st.subheader("The numbers, and how each one is worked out")
    terms=pd.DataFrame([
     ["Available to sell","Received − scrap + returns back to stock + count adjustments − sent to courier",
      "Boxes physically in the store, free to sell today."],
     ["With couriers","Sent to courier − delivered − returned",
      "Still your stock. It only stops being yours when it is delivered or scrapped."],
     ["Total owned","Available + with couriers","Everything Inripe owns in that market."],
     ["Stock age (days)","Today − the shipment's arrival date",
      "Returned boxes keep their original age. The clock never resets."],
     ["Outstanding (shipment)","Received − delivered − scrap",
      "What is left of that shipment, in the store or on a van."],
     ["Clearance span","Last handover date − arrival date",
      "How many days that shipment took to clear. Lower is better."],
     ["Return %","Boxes returned ÷ boxes handed to that courier",
      "The courier number that costs you stock and a day of shelf life."],
     ["Loss %","(customs + QC scrap + return scrap) ÷ received",
      "Everything that never reached a customer, as a share of what arrived."],
     ["Count variance","Physical counted − system calculated",
      "Never overwrites stock. Post a Count Adjustment in MOVES to correct it."],
    ], columns=["Term","How it is calculated","What it tells you"])
    table(terms.style)

    st.subheader("The nine movement types")
    mtypes=pd.DataFrame([
     ["Received","item, qty","Goods counted in at the store"],
     ["Not received","item, qty, reason","Never arrived from the supplier."],
     ["Scrap","item, qty, reason","Thrown away from store stock"],
     ["To Courier","item, qty, courier","Handed to a courier"],
     ["Returned","item, qty, courier, reason","Came back from the courier"],
     ["Return to Saleable","item, qty","Returned goods that passed QC"],
     ["Return to Scrap","item, qty, reason","Returned goods that failed QC"],
     ["Count Adjustment","item, qty, reason","Corrects stock after a physical count"],
    ], columns=["Movement","What you fill in","What it means"])
    table(mtypes.style)

    st.subheader("Your daily routine")
    st.markdown(f"""<div class="card">
<b>1.</b> New shipment landed? Add its lines on SHIPMENTS first — one row per item.<br>
<b>2.</b> Type today's events on MOVES, one row each. Pick the Movement first; the Check column
tells you which fields it needs.<br>
<b>3.</b> Check every new row shows OK in the Check column.<br>
<b>4.</b> Save the file in SharePoint.<br>
<b>5.</b> Come here, press Refresh, and read the Overview tab.<br><br>
<span style="color:{MUT}">If the Data check tab is red, fix the row it names before trusting any number.</span>
</div>""", unsafe_allow_html=True)

    st.subheader("Settings behind these numbers")
    settings=pd.DataFrame([
     ["Courier holding limit", f"{cfg['courier_limit']:.0f} days",
      "A courier holding stock longer than this is flagged"],
     ["Shipment clearance target", f"{cfg['clear_target']:.0f} days",
      "A shipment still open past this is flagged overdue"],
     ["Loss % target", f"{cfg['loss_target']*100:.1f}%", "The dashed line on the loss chart"],
     ["Count variance tolerance", f"{cfg['var_tol']*100:.1f}%",
      "Variance beyond this raises an exception"],
    ], columns=["Setting","Current value","What it controls"])
    table(settings.style)
    st.markdown(f'<div class="note">All four live on the MASTER sheet of the Excel file. '
                f'Change them there — not in code.</div>', unsafe_allow_html=True)
