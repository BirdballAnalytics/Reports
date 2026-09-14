"""Bullpen report generator.

Upload TrackMan / TruMedia CSVs, correct any mis-tagged pitches, download the
individual reports and the foldable staff sheet.
"""
from __future__ import annotations

import os
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from bc_reports import reports, retags, schema
from bc_reports.retags import DROP, METRICS, OPS, RetagBook, Rule

DATA_DIR = os.environ.get("PITCHLAB_DATA", "data")
BOOK_PATH = os.path.join(DATA_DIR, "retags.json")
LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "assets", "Retro_on_Red.png")
TYPES = reports.PITCH_ORDER

st.set_page_config(page_title="Bullpen Reports", page_icon="\u26be",
                   layout="wide")


# ----------------------------------------------------------------- access
def gate() -> bool:
    try:
        pw = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        pw = ""                          # no secrets.toml present at all
    pw = pw or os.environ.get("APP_PASSWORD", "")
    if not pw:
        return True                      # no password configured: open
    if st.session_state.get("ok"):
        return True
    st.title("Bullpen Reports")
    entered = st.text_input("Password", type="password")
    if entered:
        if entered == pw:
            st.session_state["ok"] = True
            st.rerun()
        st.error("Incorrect.")
    st.stop()


# ------------------------------------------------------------ persistence
def load_book() -> RetagBook:
    if "book" not in st.session_state:
        text = ""
        if os.path.exists(BOOK_PATH):
            text = open(BOOK_PATH).read()
        st.session_state["book"] = RetagBook.from_json(text)
    return st.session_state["book"]


def save_book(book: RetagBook):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(BOOK_PATH, "w") as fh:
        fh.write(book.to_json())


# ----------------------------------------------------------------- charts
def movement_fig(sub: pd.DataFrame, selected: set[str]) -> go.Figure:
    fig = go.Figure()
    for pt in sorted(sub["pitch_type"].unique(), key=reports.pitch_rank):
        g = sub[sub["pitch_type"] == pt]
        fig.add_trace(go.Scattergl(
            x=g["hb"], y=g["ivb"], mode="markers",
            name=f"{reports.display(pt)} ({len(g)})",
            customdata=g[["uid", "velo", "spin"]].values,
            marker=dict(size=11, color=reports.color(pt),
                        line=dict(width=[2.5 if u in selected else 0.6
                                         for u in g["uid"]],
                                  color="#111111")),
            hovertemplate=("%{customdata[1]:.1f} mph<br>"
                           "%{customdata[2]:.0f} rpm<br>"
                           "IVB %{y:.1f} / HB %{x:.1f}<extra></extra>")))
    fig.update_xaxes(range=[-25, 25], zeroline=True, zerolinecolor="#888",
                     dtick=10, title="Horizontal Break (in.)",
                     gridcolor="#eeeeee")
    fig.update_yaxes(range=[-25, 25], zeroline=True, zerolinecolor="#888",
                     dtick=10, title="Induced Vertical Break (in.)",
                     gridcolor="#eeeeee", scaleanchor="x", scaleratio=1)
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10),
                      dragmode="lasso", plot_bgcolor="white",
                      legend=dict(orientation="h", y=-0.15))
    return fig


# ------------------------------------------------------------------- main
gate()
book = load_book()

st.title("Bullpen Reports")

with st.sidebar:
    st.header("Files")
    ups = st.file_uploader("TrackMan / TruMedia CSVs", type=["csv"],
                           accept_multiple_files=True)
    st.caption("Multiple files are combined; duplicate pitch IDs are dropped.")

    st.header("Profiles")
    auto = st.checkbox("Re-center cutoffs on this staff", value=True,
                       help="Horizontal separation naturally runs wider than "
                            "vertical, so a neutral arsenal sits below 1.0. "
                            "Re-centering keeps the buckets meaningful for a "
                            "roster whose shape differs from the reference "
                            "staff the defaults were fit to.")
    lo = st.number_input("East/West below", value=reports.DEFAULT_CUTS[0],
                         step=0.05, disabled=auto)
    hi = st.number_input("North/South above", value=reports.DEFAULT_CUTS[1],
                         step=0.05, disabled=auto)

    st.header("Corrections")
    st.download_button("Download corrections", book.to_json(),
                       file_name="retags.json", mime="application/json",
                       use_container_width=True)
    restored = st.file_uploader("Restore corrections", type=["json"])
    if restored is not None and st.button("Load file",
                                          use_container_width=True):
        st.session_state["book"] = RetagBook.from_json(
            restored.getvalue().decode())
        save_book(st.session_state["book"])
        st.rerun()

if not ups:
    st.info("Upload one or more CSVs to begin.")
    st.stop()

try:
    tracked, dropped, notes = schema.load_many([(f.name, f) for f in ups])
except schema.SchemaError as e:
    st.error(str(e))
    st.stop()

fixed, log = book.apply(tracked)
if fixed.empty:
    st.error("No usable pitches after corrections.")
    st.stop()

cuts = reports.staff_cuts(fixed) if auto else (lo, hi)
profiles = reports.profiles_for(fixed, cuts)

for n in notes:
    st.caption(n)

tab_retag, tab_review, tab_out = st.tabs(
    ["Corrections", "Review", "Download"])

# ------------------------------------------------------------ corrections
with tab_retag:
    pitchers = sorted(fixed["pitcher"].unique())
    who = st.selectbox("Pitcher", pitchers)
    sub = fixed[fixed["pitcher"] == who].copy()

    left, right = st.columns([3, 2])

    with left:
        st.caption("Lasso or box-select pitches, then reassign them below. "
                   "Double-click the plot to clear.")
        sel_key = f"sel_{who}"
        event = st.plotly_chart(
            movement_fig(sub, set(book.manual)), use_container_width=True,
            key=sel_key, on_select="rerun",
            selection_mode=("points", "box", "lasso"))
        picked = []
        if event and getattr(event, "selection", None):
            picked = [p["customdata"][0]
                      for p in event.selection.get("points", [])]

    with right:
        st.subheader("Selected pitches")
        if picked:
            st.write(f"**{len(picked)}** selected")
            dest = st.selectbox("Reassign to", TYPES + [DROP],
                                key=f"dest_{who}")
            if st.button("Apply to selection", type="primary",
                         use_container_width=True):
                book.set_manual(picked, dest)
                save_book(book)
                st.rerun()
        else:
            st.caption("Nothing selected yet.")

        st.divider()
        st.subheader("Rule")
        st.caption("Rules re-apply to every future upload for this pitcher.")
        src = st.selectbox("From", ["*"] + TYPES, key=f"src_{who}")
        use_cond = st.checkbox("Only when\u2026", key=f"uc_{who}")
        metric = op = None
        val = 0.0
        if use_cond:
            c1, c2, c3 = st.columns([2, 1, 2])
            metric = c1.selectbox("Metric", list(METRICS),
                                  format_func=lambda m: METRICS[m],
                                  key=f"m_{who}")
            op = c2.selectbox("Op", list(OPS), key=f"o_{who}")
            val = c3.number_input("Value", value=0.0, step=0.5,
                                  key=f"v_{who}")
        to = st.selectbox("Becomes", TYPES + [DROP], key=f"to_{who}")
        if st.button("Add rule", use_container_width=True):
            book.add_rule(Rule(who, src, to, metric or "", op or "<",
                               float(val)))
            save_book(book)
            st.rerun()

    mine = book.for_pitcher(who)
    if mine:
        st.subheader(f"Active rules \u2014 {who}")
        for i, r in enumerate(mine):
            c1, c2 = st.columns([8, 1])
            c1.write(f"\u2022 {r.describe()}")
            if c2.button("Remove", key=f"rm_{who}_{i}"):
                book.rules.remove(r)
                save_book(book)
                st.rerun()
    if mine or any(u in book.manual
                   for u in fixed.loc[fixed["pitcher"] == who, "uid"]):
        if st.button(f"Clear all corrections for {who}"):
            book.clear_pitcher(who, tracked)
            save_book(book)
            st.rerun()

# ---------------------------------------------------------------- review
with tab_review:
    if log:
        st.subheader("Applied this run")
        for line in log:
            st.write(f"\u2022 {line}")
    st.subheader("Staff")
    rows = []
    for p in sorted(fixed["pitcher"].unique()):
        g = fixed[fixed["pitcher"] == p]
        r = reports.spread_ratio(g)
        rows.append({"Pitcher": reports.split_name(p),
                     "Hand": reports.hand(g["throws"].iloc[0]),
                     "Pitches": len(g),
                     "Types": g["pitch_type"].nunique(),
                     "V/H ratio": None if r is None else round(r, 2),
                     "Profile": profiles[p]})
    st.dataframe(pd.DataFrame(rows), use_container_width=True,
                 hide_index=True)
    st.caption(f"Cutoffs in use: East/West below {cuts[0]:.2f}, "
               f"North/South above {cuts[1]:.2f}.")
    if len(dropped):
        with st.expander(f"{len(dropped)} excluded pitches"):
            st.dataframe(dropped[["pitcher", "pitch_type", "velo", "ivb",
                                  "hb"]], use_container_width=True,
                         hide_index=True)

# -------------------------------------------------------------- download
with tab_out:
    stamp = date.today().isoformat()
    title = st.text_input("Staff sheet title", "Pitching Staff")
    if st.button("Generate PDFs", type="primary"):
        with st.spinner("Building\u2026"):
            ind = reports.build_individual_pdf(fixed, profiles, LOGO)
            staff = reports.build_staff_pdf(fixed, profiles, LOGO, title)
        st.session_state["pdfs"] = (ind, staff, stamp)
    if "pdfs" in st.session_state:
        ind, staff, stamp = st.session_state["pdfs"]
        c1, c2 = st.columns(2)
        c1.download_button("Individual reports", ind,
                           file_name=f"{stamp}-Individual-Reports.pdf",
                           mime="application/pdf", use_container_width=True)
        c2.download_button("Staff sheet", staff,
                           file_name=f"{stamp}-Staff-Sheet.pdf",
                           mime="application/pdf", use_container_width=True)
