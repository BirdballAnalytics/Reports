"""Boston College Baseball report tools.

Two modes, chosen on entry:
  Scouting - pitcher movement reports and the foldable staff sheet
  Hitting  - one-page hitter game reports
"""
from __future__ import annotations

import os
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import bc_reports
from bc_reports import (advanced, derived, feedback, hitting, reports,
                        schema, scout, staffstats)
from bc_reports.retags import DROP, METRICS, OPS, RetagBook, Rule

# A partial upload can leave a stale module behind, which otherwise surfaces
# as a redacted AttributeError deep in a callback. Fail loudly and early.
_REQUIRED = {
    "bc_reports/schema.py": (schema, ["normalize_hitting", "matchup_label",
                                      "load_many"]),
    "bc_reports/hitting.py": (hitting, ["build_hitting_pdf", "fence_radius"]),
    "bc_reports/reports.py": (reports, ["build_staff_pdf", "staff_cuts",
                                        "RHH_RED", "LHH_BLUE"]),
    "bc_reports/staffstats.py": (staffstats, ["load_stats", "attach"]),
    "bc_reports/feedback.py": (feedback, ["draw_feedback_page"]),
    "bc_reports/advanced.py": (advanced, ["add_risp", "hand_splits", "usage"]),
    "bc_reports/scout.py": (scout, ["build_individual_1page",
                                    "build_staff_expanded", "ip_value"]),
    "bc_reports/derived.py": (derived, ["season_from_pitches", "coverage"]),
}
_STALE = [f"{path} (missing {a})" for path, (mod, attrs) in _REQUIRED.items()
          for a in attrs if not hasattr(mod, a)]

DATA_DIR = os.environ.get("PITCHLAB_DATA", "data")
BOOK_PATH = os.path.join(DATA_DIR, "retags.json")
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
LOGO = os.path.join(ASSETS, "Retro_on_Red.png")
TYPES = reports.PITCH_ORDER

MAROON = "#8c2232"
GOLD = "#dbcca6"

st.set_page_config(page_title="BC Baseball Reports", page_icon="\u26be",
                   layout="wide")

st.markdown(f"""
<style>
  .bc-bar {{
      background:{MAROON}; padding:14px 22px;
      border-bottom:4px solid {GOLD}; border-radius:6px 6px 0 0;
      margin-bottom:18px;
  }}
  .bc-bar h1 {{ color:{GOLD}; font-size:1.45rem; margin:0; font-weight:700;
                display:inline; }}
  .bc-bar span {{ color:{GOLD}; opacity:.7; font-size:.85rem;
                  margin-left:14px; }}
  .stButton>button[kind="primary"] {{
      background:{MAROON}; border-color:{MAROON}; color:{GOLD};
  }}
  .stButton>button[kind="primary"]:hover {{
      background:#731c29; border-color:#731c29; color:{GOLD};
  }}
  .stTabs [aria-selected="true"] {{ color:{MAROON} !important; }}
  h2, h3 {{ color:{MAROON}; }}
</style>
""", unsafe_allow_html=True)


def bar(title: str, sub: str = ""):
    st.markdown(f'<div class="bc-bar"><h1>{title}</h1><span>{sub}</span></div>',
                unsafe_allow_html=True)


# ----------------------------------------------------------------- access
def gate():
    try:
        pw = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        pw = ""
    pw = pw or os.environ.get("APP_PASSWORD", "")
    if not pw or st.session_state.get("ok"):
        return
    bar("BC Baseball Reports")
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
        text = open(BOOK_PATH).read() if os.path.exists(BOOK_PATH) else ""
        st.session_state["book"] = RetagBook.from_json(text)
    return st.session_state["book"]


def save_book(book: RetagBook):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(BOOK_PATH, "w") as fh:
        fh.write(book.to_json())


# ------------------------------------------------------------------ entry
def landing():
    bar("BC Baseball Reports", "TrackMan / TruMedia \u2192 PDF")
    st.write("Pick a report type.")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Scouting")
        st.write("Pitcher movement profiles \u2014 one page per arm, plus the "
                 "foldable staff sheet. Includes the retag workspace.")
        if st.button("Open Scouting", type="primary",
                     use_container_width=True):
            st.session_state["mode"] = "scout"
            st.rerun()
    with c2:
        st.subheader("Hitting")
        st.write("One-page hitter game reports \u2014 spray chart, swing "
                 "decisions, contact quality, plate discipline and "
                 "pitch-group splits.")
        if st.button("Open Hitting", type="primary",
                     use_container_width=True):
            st.session_state["mode"] = "hit"
            st.rerun()


def mode_switch():
    with st.sidebar:
        if st.button("\u2190 Back to menu", use_container_width=True):
            for k in ("mode", "pdfs", "hit_pdf"):
                st.session_state.pop(k, None)
            st.rerun()
        # Which build is actually live. If this does not match what you just
        # deployed, the upload did not land.
        st.caption(f"v{bc_reports.__version__}")
        st.divider()


# --------------------------------------------------------------- scouting
def movement_fig(sub: pd.DataFrame, selected: set) -> go.Figure:
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


def roster_order(df: pd.DataFrame, season: dict) -> list:
    """Pitchers in the order the staff sheet prints them: innings, then name."""
    return sorted(df["pitcher"].dropna().unique(),
                  key=lambda n: (-scout.ip_value((season.get(n) or {}).get("ip")),
                                 n))


def roster_label(df: pd.DataFrame, season: dict):
    """'Radel - RHP  (87.2 IP, 412 pitches)' for the picker."""
    def fmt(name):
        g = df[df["pitcher"] == name]
        hand = reports.hand(g["throws"].iloc[0]) if len(g) else ""
        head = reports.split_name(name) + (f" - {hand}" if hand else "")
        ip = (season.get(name) or {}).get("ip")
        ip_txt = "" if ip is None or str(ip).strip().lower() in ("", "nan") \
            else f"{str(ip).strip()} IP, "
        return f"{head}  ({ip_txt}{len(g)} pitches)"
    return fmt


def roster_picker(df: pd.DataFrame, season: dict) -> list:
    """Choose which pitchers land on the PDFs.

    Everyone in the uploaded files is offered. The selection is reconciled on
    every run so that a pitcher who appears in a newly added file is included
    by default rather than silently left off, while names that are no longer
    in the data drop away.
    """
    everyone = roster_order(df, season)
    seen = st.session_state.get("_roster_seen")
    if seen is None:
        st.session_state["roster"] = list(everyone)
    else:
        keep = set(st.session_state.get("roster", []))
        keep |= {n for n in everyone if n not in seen}     # new arrivals in
        st.session_state["roster"] = [n for n in everyone if n in keep]
    st.session_state["_roster_seen"] = list(everyone)

    st.subheader("Pitchers on the reports")
    c1, c2, _ = st.columns([1, 1, 5])
    # Both buttons sit above the widget on purpose: Streamlit forbids writing
    # to a widget's key once that widget has been drawn this run.
    if c1.button("Select all", use_container_width=True):
        st.session_state["roster"] = list(everyone)
        st.rerun()
    if c2.button("Clear", use_container_width=True):
        st.session_state["roster"] = []
        st.rerun()
    chosen = st.multiselect(
        "Include", everyone, key="roster",
        format_func=roster_label(df, season),
        help="Everyone found in the uploaded files is listed, most innings "
             "first. Remove an arm here and he is left off both the "
             "individual sheets and the staff sheet. Profile cutoffs still "
             "come from the whole upload, so a pitcher's Stock / North-South "
             "/ East-West label does not shift with who else you print.")
    if chosen:
        pages = -(-len(chosen) // (scout.SCOLS * scout.SROWS))
        st.caption(f"{len(chosen)} of {len(everyone)} pitchers — "
                   f"{len(chosen)} individual page"
                   f"{'s' if len(chosen) != 1 else ''}, staff sheet on "
                   f"{pages} page{'s' if pages != 1 else ''}.")
    return chosen


def scouting_page():
    bar("Scouting", "Pitcher movement reports")
    book = load_book()

    with st.sidebar:
        st.header("Files")
        ups = st.file_uploader("TrackMan / TruMedia CSVs", type=["csv"],
                               accept_multiple_files=True, key="scout_up")
        st.caption("Files are combined; duplicate pitch IDs are dropped.")
        st.header("Season stats")
        st.caption("A season pitching export (player, IP, ERA, H, K, BB, "
                   "InZone%, and G/GS/2B/3B/HR/K%/BB%/FIP/WHIP for the "
                   "individual sheets). Optional \u2014 without it the whole "
                   "line is rebuilt from the pitch data instead. Upload it "
                   "when you want the official book: derived innings, "
                   "strikeouts and walks come out on the nose, but ERA "
                   "cannot tell an earned run from an unearned one.")
        stat_up = st.file_uploader("Season stats CSV", type=["csv"],
                                   key="stats_up")
        st.header("Profiles")
        auto = st.checkbox("Re-center cutoffs on this staff", value=True,
                           help="Horizontal separation naturally runs wider "
                                "than vertical, so a neutral arsenal sits "
                                "below 1.0. Re-centering keeps the buckets "
                                "meaningful for this roster.")
        lo = st.number_input("East/West below", value=reports.DEFAULT_CUTS[0],
                             step=0.05, disabled=auto)
        hi = st.number_input("North/South above", value=reports.DEFAULT_CUTS[1],
                             step=0.05, disabled=auto)
        st.header("Corrections")
        st.download_button("Download corrections", book.to_json(),
                           file_name="retags.json", mime="application/json",
                           use_container_width=True)
        restored = st.file_uploader("Restore corrections", type=["json"],
                                    key="restore")
        if restored is not None and st.button("Load file",
                                              use_container_width=True):
            st.session_state["book"] = RetagBook.from_json(
                restored.getvalue().decode())
            save_book(st.session_state["book"])
            st.rerun()

    if not ups:
        st.info("Upload one or more CSVs to begin.")
        return
    try:
        tracked, dropped, notes = schema.load_many([(f.name, f) for f in ups])
    except schema.SchemaError as e:
        st.error(str(e))
        return

    fixed, log = book.apply(tracked)
    if fixed.empty:
        st.error("No usable pitches after corrections.")
        return
    # pitch groups, in-zone flag, two-strike flag, and the reconstructed
    # runners-in-scoring-position flag the usage tables need
    fixed = advanced.add_risp(advanced.prepare(fixed))

    stat_lines, stat_missed, stats_df, season = {}, [], None, {}
    if stat_up is not None:
        try:
            stats_df = staffstats.load_stats(pd.read_csv(stat_up),
                                             stat_up.name)
            found, stat_missed = staffstats.attach(fixed, stats_df)
            season = found
            stat_lines = {k: staffstats.format_line(v)
                          for k, v in found.items()}
            st.caption(f"Season stats matched for {len(found)} of "
                       f"{fixed['pitcher'].nunique()} pitchers.")
            if stat_missed:
                st.warning("No stats row found for: "
                           + ", ".join(stat_missed))
        except schema.SchemaError as e:
            st.error(str(e))
    else:
        # No official export, so rebuild the line from the pitch data.
        # Outcomes are counted over every row, including pitches the unit
        # failed to measure: a walk is a walk whether or not the radar
        # caught the ball, and dropping those would cost real innings.
        outcomes = advanced.prepare(pd.concat([tracked, dropped],
                                              ignore_index=True))
        season = derived.season_from_pitches(outcomes)
        stat_lines = {k: staffstats.format_line(v) for k, v in season.items()}
        if season:
            st.caption(derived.coverage(outcomes))
    cuts = reports.staff_cuts(fixed) if auto else (lo, hi)
    profiles = reports.profiles_for(fixed, cuts)
    for n in notes:
        st.caption(n)

    t1, t2, t3 = st.tabs(["Corrections", "Review", "Download"])

    with t1:
        who = st.selectbox("Pitcher", sorted(fixed["pitcher"].unique()))
        sub = fixed[fixed["pitcher"] == who].copy()
        left, right = st.columns([3, 2])
        with left:
            st.caption("Lasso or box-select pitches, then reassign them. "
                       "Double-click the plot to clear.")
            ev = st.plotly_chart(movement_fig(sub, set(book.manual)),
                                 use_container_width=True, key=f"sel_{who}",
                                 on_select="rerun",
                                 selection_mode=("points", "box", "lasso"))
            picked = []
            if ev and getattr(ev, "selection", None):
                picked = [p["customdata"][0]
                          for p in ev.selection.get("points", [])]
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
            st.caption("Rules re-apply to every future upload.")
            src = st.selectbox("From", ["*"] + TYPES, key=f"src_{who}")
            cond = st.checkbox("Only when\u2026", key=f"uc_{who}")
            metric = op = None
            val = 0.0
            if cond:
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
            if st.button(f"Clear all corrections for {who}"):
                book.clear_pitcher(who, tracked)
                save_book(book)
                st.rerun()

    with t2:
        if log:
            st.subheader("Applied this run")
            for line in log:
                st.write(f"\u2022 {line}")
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
        st.caption(f"Cutoffs: East/West below {cuts[0]:.2f}, "
                   f"North/South above {cuts[1]:.2f}.")
        if len(dropped):
            with st.expander(f"{len(dropped)} excluded pitches"):
                st.dataframe(dropped[["pitcher", "pitch_type", "velo", "ivb",
                                      "hb"]], use_container_width=True,
                             hide_index=True)

    with t3:
        stamp = date.today().isoformat()
        chosen = roster_picker(fixed, season)
        st.divider()
        team = staffstats.team_label(stats_df, fixed)
        title = st.text_input(
            "Staff sheet title",
            f"{team} Pitching Staff" if team else "Pitching Staff")
        layout = st.radio(
            "Individual sheet layout", ["One page", "Two pages"],
            horizontal=True,
            help="One page fits everything on a single sheet. Two pages "
                 "gives the heat maps a full page of their own.")
        if not chosen:
            st.info("Pick at least one pitcher to build the reports.")
        elif st.button("Generate PDFs", type="primary"):
            with st.spinner("Building\u2026"):
                # Only the chosen arms reach the builders. Cutoffs and
                # profiles were fixed above from the full upload, so they
                # stay put whoever is printed.
                sel = fixed[fixed["pitcher"].isin(chosen)]
                build = (scout.build_individual_1page if layout == "One page"
                         else scout.build_individual_2page)
                st.session_state["pdfs"] = (
                    build(sel, season, LOGO),
                    scout.build_staff_expanded(sel, season, LOGO, title),
                    stamp)
        if "pdfs" in st.session_state:
            ind, staff, stamp = st.session_state["pdfs"]
            c1, c2 = st.columns(2)
            c1.download_button("Individual reports", ind,
                               file_name=f"{stamp}-Individual-Reports.pdf",
                               mime="application/pdf",
                               use_container_width=True)
            c2.download_button("Staff sheet", staff,
                               file_name=f"{stamp}-Staff-Sheet.pdf",
                               mime="application/pdf",
                               use_container_width=True)


# ---------------------------------------------------------------- hitting
def hitting_page():
    bar("Hitting", "Hitter game reports")
    with st.sidebar:
        st.header("Files")
        ups = st.file_uploader("TrackMan / TruMedia CSVs", type=["csv"],
                               accept_multiple_files=True, key="hit_up")
        st.header("Ballpark")
        st.caption("Outfield wall distances, in feet.")
        f1, f2, f3 = st.columns(3)
        fence = {
            "line": f1.number_input("Lines", value=330, step=1),
            "gap": f2.number_input("Gaps", value=375, step=1),
            "center": f3.number_input("Center", value=403, step=1),
        }
        st.header("Feedback form")
        with_fb = st.checkbox("Include post-series feedback page", value=True,
                              help="Adds a fillable form behind each hitter's "
                                   "report, pre-filled with player, date and "
                                   "opponent.")
        st.header("Footer")
        team = st.text_input("Left", "Boston College Baseball")
        srcs = st.text_input("Right", "Source: TrackMan")

    if not ups:
        st.info("Upload one or more CSVs to begin.")
        return

    frames = []
    for f in ups:
        try:
            frames.append(schema.normalize_hitting(
                pd.read_csv(f, low_memory=False), f.name))
        except schema.SchemaError as e:
            st.error(str(e))
            return
    d = pd.concat(frames, ignore_index=True)

    games = ["All games"]
    if "date" in d.columns and d["date"].notna().any():
        games += [str(pd.Timestamp(x).date())
                  for x in sorted(d["date"].dropna().unique(), reverse=True)]
    c1, c2 = st.columns([1, 2])
    game = c1.selectbox("Game", games)
    if game != "All games":
        d = d[d["date"].dt.date.astype(str) == game]
    if d.empty:
        st.warning("No pitches for that game.")
        return

    names = sorted(d["batter"].dropna().unique())
    picked = c2.multiselect("Batters", names,
                            default=names[:1] if names else [])
    matchup = schema.matchup_label(d)
    st.caption(matchup or "\u2014")
    if not picked:
        st.info("Pick at least one batter.")
        return

    preview = picked[0]
    s = hitting.summarize(d[d["batter"] == preview])
    st.subheader(preview)
    cells = [("PA", str(s["PA"])), ("H", s["line"]), ("XBH", str(s["XBH"])),
             ("BB/K/HBP", f"{s['BB']}/{s['K']}/{s['HBP']}"),
             ("Avg EV", f"{s['avg_ev']:.1f}" if s["avg_ev"] else "\u2014"),
             ("Max EV", f"{s['max_ev']:.1f}" if s["max_ev"] else "\u2014"),
             ("Hard hit", f"{s['hard_hit']*100:.0f}%"
              if s["hard_hit"] is not None else "\u2014")]
    for col, (lab, val) in zip(st.columns(7), cells):
        col.metric(lab, val)

    if st.button("Generate report", type="primary"):
        with st.spinner("Building\u2026"):
            st.session_state["hit_pdf"] = hitting.build_hitting_pdf(
                d, picked, matchup, team, srcs, fence, with_fb)
    if "hit_pdf" in st.session_state:
        stamp = game if game != "All games" else date.today().isoformat()
        st.download_button("Download hitting report",
                           st.session_state["hit_pdf"],
                           file_name=f"{stamp}-Hitting.pdf",
                           mime="application/pdf")


# ------------------------------------------------------------------- main
if _STALE:
    st.error(
        "Some files on the server are out of date, so the app can't start:\n\n"
        + "\n".join(f"- {x}" for x in _STALE)
        + "\n\nRe-upload the whole project to the repo, making sure the "
          "**bc_reports** folder is included, then let it redeploy.")
    st.stop()

gate()
mode = st.session_state.get("mode")
if mode == "scout":
    mode_switch()
    scouting_page()
elif mode == "hit":
    mode_switch()
    hitting_page()
else:
    landing()
