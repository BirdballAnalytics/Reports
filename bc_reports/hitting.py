"""Hitter game report: one page per batter per game.

Layout mirrors the reference one-pager: header bar, seven-cell stat strip,
spray chart + swing decisions, contact quality + plate discipline, plate
appearance log + pitch-group splits, footer.
"""
from __future__ import annotations

import io
import math
import os
import tempfile

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Wedge
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor, white

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets")

MAROON = HexColor("#8c2232")
GOLD = HexColor("#dbcca6")
INK = HexColor("#1f1f1f")
SOFT = HexColor("#6b6b6b")
RULE = HexColor("#d8d2c4")
TINT = HexColor("#f6f2e9")
MAROON_HEX = "#8c2232"
GOLD_HEX = "#dbcca6"
DARKGOLD_HEX = "#b39b63"
TINT_HEX = "#f6f2e9"

PW, PH = letter
MARGIN = 40

# ------------------------------------------------------------ definitions
SWING_CALLS = {"strikeswinging", "foulball", "foulballnotfieldable",
               "foulballfieldable", "inplay", "foultip"}
WHIFF_CALLS = {"strikeswinging", "foultip"}
FOUL_CALLS = {"foulball", "foulballnotfieldable", "foulballfieldable",
              "foultip"}
HITS = {"single", "double", "triple", "homerun"}
XBH = {"double", "triple", "homerun"}

# Rulebook zone and Statcast attack zones, in feet
ZONE = dict(x=0.83, lo=1.50, hi=3.50)
HEART = dict(x=0.558, lo=1.83, hi=3.17)
SHADOW = dict(x=1.108, lo=1.17, hi=3.83)

# Fence profile: distance down the lines, to the gaps, to straightaway center
FENCE = {"line": 330.0, "gap": 375.0, "center": 403.0}


def fence_radius(bearing_deg, fence=None):
    """Distance to the wall at a given bearing (0 = center, +/-45 = lines).

    Fits r = a + c1*b^2 + c2*b^4 through the three control distances. Even
    powers only, so the curve runs smoothly through center instead of
    forming a point there."""
    f = fence or FENCE
    a = float(f["center"])
    x = np.array([22.5, 45.0])
    A = np.vstack([x ** 2, x ** 4]).T
    c1, c2 = np.linalg.solve(A, np.array([float(f["gap"]) - a,
                                          float(f["line"]) - a]))
    b = np.clip(np.abs(np.asarray(bearing_deg, dtype=float)), 0, 45)
    return a + c1 * b ** 2 + c2 * b ** 4


HARD_HIT = 95.0
SWEET_LO, SWEET_HI = 8.0, 32.0        # sweet-spot% definition
SHADE_LA = (10.0, 30.0)               # shaded box on the contact chart
EV_TOP = 115.0

GROUPS = {
    "Fastball": {"fastball", "four-seam", "fourseam", "four-seam fastball",
                 "sinker", "two-seam", "twoseam", "cutter"},
    "Breaking": {"slider", "curveball", "sweeper", "slurve", "knuckle curve",
                 "cutter_breaking"},
    "Offspeed": {"changeup", "change-up", "splitter", "split-finger",
                 "screwball", "forkball"},
}
GROUP_ORDER = ["Breaking", "Fastball", "Offspeed"]


def pitch_group(name: str) -> str:
    n = str(name).strip().lower()
    for g, members in GROUPS.items():
        if n in members:
            return g
    return "Other"


def _n(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def pct(num, den, digits=0):
    if not den:
        return "\u2014"
    return f"{round(100 * num / den):.{digits}f}%"


# ------------------------------------------------------------------ stats
def pa_boundaries(df: pd.DataFrame) -> pd.DataFrame:
    """Tag each pitch with a plate-appearance index."""
    d = df.copy()
    keys = [c for c in ("date", "inning", "half", "pa_of_inning")
            if c in d.columns and d[c].notna().any()]
    if keys:
        d["pa_id"] = d.groupby(keys, dropna=False).ngroup()
    else:                                    # fall back to PitchofPA resets
        starts = (d.get("pitch_of_pa", pd.Series(1, index=d.index)) == 1)
        d["pa_id"] = starts.cumsum()
    return d


def summarize(df: pd.DataFrame) -> dict:
    d = pa_boundaries(df)
    call = d["pitch_call"].astype(str).str.lower().str.replace(" ", "")
    swing = call.isin(SWING_CALLS)
    whiff = call.isin(WHIFF_CALLS)

    inzone = ((d["plate_x"].abs() <= ZONE["x"]) &
              d["plate_z"].between(ZONE["lo"], ZONE["hi"]))
    inheart = ((d["plate_x"].abs() <= HEART["x"]) &
               d["plate_z"].between(HEART["lo"], HEART["hi"]))
    loc = d["plate_x"].notna() & d["plate_z"].notna()

    # one row per plate appearance: the final pitch carries the outcome
    last = d.groupby("pa_id").tail(1)
    res = last["play_result"].astype(str).str.lower()
    kbb = last["kor_bb"].astype(str).str.lower()
    hbp = call.loc[last.index].eq("hitbypitch")

    pa = len(last)
    bb = int((kbb == "walk").sum())
    k = int((kbb == "strikeout").sum())
    hbp_n = int(hbp.sum())
    sac = int(res.isin({"sacrifice", "sacrificebunt", "sacrificefly"}).sum())
    hits = int(res.isin(HITS).sum())
    xbh = int(res.isin(XBH).sum())
    ab = pa - bb - hbp_n - sac

    bip = d[call == "inplay"].copy()
    ev = bip["exit_speed"].dropna()
    la = bip["angle"].dropna()

    if "hit_type" in bip.columns and bip["hit_type"].notna().any():
        ht = bip["hit_type"].astype(str).str.lower()
        gb = int(ht.str.contains("ground").sum())
        ld = int(ht.str.contains("line").sum())
        fb = int((ht.str.contains("fly") | ht.str.contains("pop")).sum())
        if gb + ld + fb == 0:
            gb = ld = fb = None
    else:
        gb = ld = fb = None
    if gb is None and len(la):
        gb = int((la < 10).sum())
        ld = int(la.between(10, 25, inclusive="left").sum())
        fb = int((la >= 25).sum())

    batted = max(len(la), 1) if len(la) else 0

    out = {
        "PA": pa, "AB": ab, "H": hits, "XBH": xbh,
        "BB": bb, "K": k, "HBP": hbp_n,
        "line": f"{hits}-for-{ab}" if ab else f"{hits}-for-0",
        "avg_ev": ev.mean() if len(ev) else None,
        "max_ev": ev.max() if len(ev) else None,
        "hard_hit": (ev >= HARD_HIT).mean() if len(ev) else None,
        "pitches": len(d),
        "swing": swing.sum() / len(d) if len(d) else None,
        "zone_swing": (swing & inzone).sum() / inzone.sum() if inzone.sum() else None,
        "chase": ((swing & loc & ~inzone).sum() / (loc & ~inzone).sum()
                  if (loc & ~inzone).sum() else None),
        "whiff": whiff.sum() / swing.sum() if swing.sum() else None,
        "zone_contact": ((swing & inzone & ~whiff).sum() / (swing & inzone).sum()
                         if (swing & inzone).sum() else None),
        "heart_swing": ((swing & inheart).sum() / inheart.sum()
                        if inheart.sum() else None),
        "sweet": (la.between(SWEET_LO, SWEET_HI).mean() if len(la) else None),
        "gb": gb / batted if batted and gb is not None else None,
        "ld": ld / batted if batted and ld is not None else None,
        "fb": fb / batted if batted and fb is not None else None,
    }
    out["_pa_rows"] = last
    out["_bip"] = bip
    out["_d"] = d
    out["_swing"] = swing
    out["_whiff"] = whiff
    out["_inzone"] = inzone
    out["_loc"] = loc
    return out


def pa_table(s: dict) -> list:
    rows = []
    for _, r in s["_pa_rows"].iterrows():
        res = str(r.get("play_result", "")).strip()
        kbb = str(r.get("kor_bb", "")).strip().lower()
        call = str(r.get("pitch_call", "")).strip().lower().replace(" ", "")
        if kbb == "walk":
            label = "Walk"
        elif kbb == "strikeout":
            label = "Strikeout"
        elif call == "hitbypitch":
            label = "HBP"
        elif res.lower() in ("undefined", "nan", ""):
            label = "\u2014"
        else:
            label = res
        n_pitches = int(r.get("pitch_of_pa") or 1)
        rows.append([
            str(int(r["inning"])) if pd.notna(r.get("inning")) else "\u2014",
            str(r.get("pitcher", "")).split(",")[0].strip(),
            "L" if str(r.get("pitcher_throws", "")).lower().startswith("l") else "R",
            str(n_pitches),
            label,
            f"{r['exit_speed']:.1f}" if pd.notna(r.get("exit_speed")) else "\u2014",
            f"{r['angle']:.1f}" if pd.notna(r.get("angle")) else "\u2014",
            f"{r['distance']:.1f}" if pd.notna(r.get("distance")) else "\u2014",
        ])
    return rows


def group_table(s: dict) -> list:
    d = s["_d"].copy()
    d["_grp"] = d["pitch_type"].map(pitch_group)
    call = d["pitch_call"].astype(str).str.lower().str.replace(" ", "")
    d["_sw"] = call.isin(SWING_CALLS)
    d["_wh"] = call.isin(WHIFF_CALLS)
    d["_ip"] = call == "inplay"
    d["_iz"] = ((d["plate_x"].abs() <= ZONE["x"]) &
                d["plate_z"].between(ZONE["lo"], ZONE["hi"]))
    d["_loc"] = d["plate_x"].notna() & d["plate_z"].notna()

    rows = []
    for g in GROUP_ORDER + ["Other"]:
        sub = d[d["_grp"] == g]
        if sub.empty:
            continue
        oz = sub[sub["_loc"] & ~sub["_iz"]]
        bip = sub[sub["_ip"]]
        ev = bip["exit_speed"].dropna()
        rows.append([
            g, str(len(sub)),
            pct(sub["_sw"].sum(), len(sub)),
            pct(oz["_sw"].sum(), len(oz)) if len(oz) else "\u2014",
            pct(sub["_wh"].sum(), sub["_sw"].sum()) if sub["_sw"].sum() else "\u2014",
            str(len(bip)),
            f"{ev.mean():.1f}" if len(ev) else "\u2014",
            pct((ev >= HARD_HIT).sum(), len(ev)) if len(ev) else "\u2014",
        ])
    return rows


# ----------------------------------------------------------------- charts
RESULT_STYLE = {
    "homerun": ("Home run", "#d9a900", "*", 220),
    "single":  ("Hit", GOLD_HEX, "o", 70),
    "double":  ("Hit", GOLD_HEX, "o", 70),
    "triple":  ("Hit", GOLD_HEX, "o", 70),
    "out":     ("Out", MAROON_HEX, "o", 70),
}


def spray_chart(bip: pd.DataFrame, path: str, fence=None):
    fig, ax = plt.subplots(figsize=(3.9, 3.3), dpi=300)
    f = fence or FENCE
    line_d = float(f["line"])
    max_d = float(f["center"])

    # infield dirt arc and diamond
    ia = np.linspace(math.radians(45), math.radians(135), 120)
    ax.plot(150 * np.cos(ia), 150 * np.sin(ia), color=DARKGOLD_HEX,
            lw=0.9, ls=":")
    b = 90 / math.sqrt(2)
    ax.plot([0, -b, 0, b, 0], [0, b, 2 * b, b, 0], color=DARKGOLD_HEX, lw=1.4)
    # foul lines run to the corners, then the wall curves between them
    corner = line_d / math.sqrt(2)
    ax.plot([0, -corner], [0, corner], color=MAROON_HEX, lw=1.4)
    ax.plot([0, corner], [0, corner], color=MAROON_HEX, lw=1.4)
    brg = np.linspace(-45, 45, 241)
    rad = fence_radius(brg, f)
    ax.plot(rad * np.sin(np.radians(brg)), rad * np.cos(np.radians(brg)),
            color=MAROON_HEX, lw=1.6)

    seen = {}
    for _, r in bip.iterrows():
        d_, brg = _n(r.get("distance")), _n(r.get("bearing"))
        if d_ is None or brg is None:
            continue
        x = d_ * math.sin(math.radians(brg))
        y = d_ * math.cos(math.radians(brg))
        key = str(r.get("play_result", "out")).lower()
        lab, col, mk, sz = RESULT_STYLE.get(key, ("Out", MAROON_HEX, "o", 70))
        ax.scatter([x], [y], s=sz, c=col, marker=mk,
                   edgecolors="white" if mk == "o" else col,
                   linewidths=0.7, zorder=4,
                   label=lab if lab not in seen else None)
        seen[lab] = True

    span = max(corner, max_d * 0.62)
    ax.set_xlim(-span * 1.20, span * 1.20)
    ax.set_ylim(-max_d * 0.09, max_d * 1.07)
    ax.set_aspect("equal")
    ax.axis("off")
    if seen:
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.04),
                  ncol=len(seen), frameon=False, fontsize=7.5,
                  handletextpad=0.3, columnspacing=1.4)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.02, transparent=True)
    plt.close(fig)


def zone_chart(d: pd.DataFrame, path: str):
    fig, ax = plt.subplots(figsize=(3.0, 3.3), dpi=300)

    ax.add_patch(Rectangle((-SHADOW["x"], SHADOW["lo"]), 2 * SHADOW["x"],
                           SHADOW["hi"] - SHADOW["lo"], fill=False,
                           edgecolor=DARKGOLD_HEX, lw=0.8, ls=(0, (4, 3))))
    ax.add_patch(Rectangle((-HEART["x"], HEART["lo"]), 2 * HEART["x"],
                           HEART["hi"] - HEART["lo"], facecolor=TINT_HEX,
                           edgecolor="none", zorder=1))
    ax.add_patch(Rectangle((-ZONE["x"], ZONE["lo"]), 2 * ZONE["x"],
                           ZONE["hi"] - ZONE["lo"], fill=False,
                           edgecolor=MAROON_HEX, lw=1.6, zorder=2))

    call = d["pitch_call"].astype(str).str.lower().str.replace(" ", "")
    style = []
    for c in call:
        if c == "inplay":
            style.append(("In play", MAROON_HEX, "D", 52))
        elif c in FOUL_CALLS:
            style.append(("Foul", DARKGOLD_HEX, "o", 42))
        elif c in WHIFF_CALLS:
            style.append(("Whiff", "#8a8a8a", "X", 55))
        else:
            style.append(("Take", "#c4c4c4", "o", 38))

    seen = {}
    for (lab, col, mk, sz), (_, r) in zip(style, d.iterrows()):
        if pd.isna(r["plate_x"]) or pd.isna(r["plate_z"]):
            continue
        ax.scatter([r["plate_x"]], [r["plate_z"]], s=sz, c=col, marker=mk,
                   edgecolors="white", linewidths=0.6, zorder=4,
                   label=lab if lab not in seen else None)
        seen[lab] = True

    # home plate outline beneath the zone
    ax.plot([-0.71, 0.71, 0.71, 0, -0.71, -0.71],
            [0.62, 0.62, 0.44, 0.30, 0.44, 0.62],
            color="#5a5a5a", lw=1.0)

    ax.set_xlim(-2.2, 2.2)
    ax.set_ylim(0.02, 4.70)
    ax.set_aspect("equal")
    ax.axis("off")
    if seen:
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.09),
                  ncol=min(4, len(seen)), frameon=False, fontsize=7.5,
                  handletextpad=0.3, columnspacing=1.2)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.02, transparent=True)
    plt.close(fig)


def contact_chart(bip: pd.DataFrame, path: str):
    fig, ax = plt.subplots(figsize=(3.9, 2.85), dpi=300)
    ax.add_patch(Rectangle((SHADE_LA[0], HARD_HIT),
                           SHADE_LA[1] - SHADE_LA[0], EV_TOP - HARD_HIT,
                           facecolor=TINT_HEX, edgecolor="none", zorder=1))
    ax.axhline(HARD_HIT, color=DARKGOLD_HEX, lw=1.0, ls="--", zorder=2)
    ax.text(58, HARD_HIT + 1.5, "hard hit", fontsize=7, color=DARKGOLD_HEX,
            ha="right", va="bottom")

    seen = {}
    for _, r in bip.iterrows():
        if pd.isna(r.get("angle")) or pd.isna(r.get("exit_speed")):
            continue
        hit = str(r.get("play_result", "")).lower() in HITS
        lab, col = ("Hit", DARKGOLD_HEX) if hit else ("Out", MAROON_HEX)
        ax.scatter([r["angle"]], [r["exit_speed"]], s=46, c=col,
                   edgecolors="white", linewidths=0.6, zorder=4,
                   label=lab if lab not in seen else None)
        seen[lab] = True

    ax.set_xlim(-65, 65)
    ax.set_ylim(30, EV_TOP)
    ax.set_xlabel("Launch angle (deg)", fontsize=8)
    ax.set_ylabel("Exit velocity (mph)", fontsize=8)
    ax.tick_params(labelsize=7.5, colors="#4a4a4a")
    ax.grid(True, color="#ededed", lw=0.6, zorder=0)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_color("#b8b8b8")
        s.set_linewidth(0.7)
    if seen:
        ax.legend(loc="lower right", frameon=False, fontsize=7.5,
                  handletextpad=0.3)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.03, transparent=True)
    plt.close(fig)


# ----------------------------------------------------------------- layout
def _logo(name):
    p = os.path.join(ASSETS, name)
    return p if os.path.exists(p) else None


def _draw_header(c, batter, matchup):
    h = 48
    c.setFillColor(MAROON)
    c.rect(0, PH - h, PW, h, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.rect(0, PH - h - 4, PW, 4, stroke=0, fill=1)

    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(MARGIN, PH - h / 2 - 5.5, batter)
    c.setFont("Helvetica", 9)
    c.drawRightString(PW - MARGIN, PH - h / 2 - 4, matchup)

    mark = _logo("wordmark.png") or _logo("Retro_on_Red.png")
    if mark:
        img = ImageReader(mark)
        iw, ih = img.getSize()
        mh = 34.0
        c.drawImage(img, PW / 2 - mh * (iw / ih) / 2, PH - h / 2 - mh / 2,
                    width=mh * (iw / ih), height=mh, mask="auto",
                    preserveAspectRatio=True)


def _draw_statstrip(c, s, top):
    cells = [
        (str(s["PA"]), "PA"),
        (s["line"], "H"),
        (str(s["XBH"]), "XBH"),
        (f"{s['BB']} / {s['K']} / {s['HBP']}", "BB / K / HBP"),
        (f"{s['avg_ev']:.1f}" if s["avg_ev"] is not None else "\u2014", "Avg EV"),
        (f"{s['max_ev']:.1f}" if s["max_ev"] is not None else "\u2014", "Max EV"),
        (pct(round((s["hard_hit"] or 0) * 100), 100) if s["hard_hit"] is not None
         else "\u2014", "Hard hit"),
    ]
    w = PW - 2 * MARGIN
    h = 52
    cw = w / len(cells)
    c.setFillColor(TINT)
    c.rect(MARGIN, top - h, w, h, stroke=0, fill=1)
    c.setStrokeColor(RULE)
    c.setLineWidth(0.7)
    c.rect(MARGIN, top - h, w, h, stroke=1, fill=0)
    for i, (val, lab) in enumerate(cells):
        x = MARGIN + i * cw
        if i:
            c.setStrokeColor(RULE)
            c.line(x, top - h + 6, x, top - 6)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(x + cw / 2, top - 24, val)
        c.setFillColor(SOFT)
        c.setFont("Helvetica", 6.8)
        c.drawCentredString(x + cw / 2, top - 38, lab)
    return top - h


def _title(c, text, x, y, width=None):
    c.setFillColor(MAROON)
    c.setFont("Helvetica-Bold", 11)
    if width:
        c.drawCentredString(x + width / 2, y, text)
    else:
        c.drawString(x, y, text)


def _draw_discipline(c, s, x, y, w):
    rows = [
        ("Pitches seen", str(s["pitches"])),
        ("Swing%", pct(round((s["swing"] or 0) * 1000) / 10, 100)
         if s["swing"] is not None else "\u2014"),
        ("Zone swing%", pct(round((s["zone_swing"] or 0) * 1000) / 10, 100)
         if s["zone_swing"] is not None else "\u2014"),
        ("Chase%", pct(round((s["chase"] or 0) * 1000) / 10, 100)
         if s["chase"] is not None else "\u2014"),
        ("Whiff%", pct(round((s["whiff"] or 0) * 1000) / 10, 100)
         if s["whiff"] is not None else "\u2014"),
        ("Zone contact%", pct(round((s["zone_contact"] or 0) * 1000) / 10, 100)
         if s["zone_contact"] is not None else "\u2014"),
        ("Heart swing%", pct(round((s["heart_swing"] or 0) * 1000) / 10, 100)
         if s["heart_swing"] is not None else "\u2014"),
        ("Sweet spot%", pct(round((s["sweet"] or 0) * 1000) / 10, 100)
         if s["sweet"] is not None else "\u2014"),
    ]
    if s["gb"] is not None:
        rows.append(("GB / LD / FB",
                     " / ".join(pct(round(v * 100), 100)
                                for v in (s["gb"], s["ld"], s["fb"]))))
    step = 18.3
    for i, (lab, val) in enumerate(rows):
        ry = y - i * step
        c.setFillColor(SOFT)
        c.setFont("Helvetica", 8.2)
        c.drawString(x + 4, ry, lab)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 8.4)
        c.drawRightString(x + w, ry, val)
        c.setStrokeColor(RULE)
        c.setLineWidth(0.45)
        c.line(x, ry - 5.5, x + w, ry - 5.5)
    return y - len(rows) * step


def _draw_table(c, heads, rows, widths, x, y, align_first_left=True,
                rh=18.0, hh=20.0):
    tw = sum(widths)
    c.setFillColor(MAROON)
    c.rect(x, y - hh, tw, hh, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 7.1)
    cx = x
    for wdt, hd in zip(widths, heads):
        c.drawCentredString(cx + wdt / 2, y - hh + 6.6, hd)
        cx += wdt
    ry = y - hh
    for i, row in enumerate(rows):
        ry -= rh
        if i % 2 == 1:
            c.setFillColor(TINT)
            c.rect(x, ry, tw, rh, stroke=0, fill=1)
        c.setFillColor(INK)
        fs = min(7.4, rh * 0.60)
        base = ry + (rh - fs) / 2 + 0.8
        cx = x
        for j, (wdt, val) in enumerate(zip(widths, row)):
            c.setFont("Helvetica-Bold" if j == 0 and align_first_left
                      else "Helvetica", fs)
            if j == 0 and align_first_left:
                c.drawString(cx + 5, base, str(val))
            else:
                c.drawCentredString(cx + wdt / 2, base, str(val))
            cx += wdt
    c.setStrokeColor(RULE)
    c.setLineWidth(0.5)
    c.rect(x, ry, tw, y - ry, stroke=1, fill=0)
    return ry


def _draw_footer(c, team, source):
    y = 26
    c.setFillColor(SOFT)
    c.setFont("Helvetica", 7.6)
    c.drawString(MARGIN, y, team)
    c.drawRightString(PW - MARGIN, y, source)
    acc = _logo("conference.png")
    if acc:
        img = ImageReader(acc)
        iw, ih = img.getSize()
        mh = 22.0
        c.drawImage(img, PW / 2 - mh * (iw / ih) / 2, y - 7,
                    width=mh * (iw / ih), height=mh, mask="auto",
                    preserveAspectRatio=True)


def build_hitting_pdf(df: pd.DataFrame, batters, matchup: str = "",
                      team: str = "Boston College Baseball",
                      source: str = "Source: TrackMan",
                      fence: dict | None = None) -> bytes:
    """One page per batter, in the order given."""
    if isinstance(batters, str):
        batters = [batters]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle("Hitting reports" if len(batters) > 1
               else f"{batters[0]} \u2014 hitting")
    with tempfile.TemporaryDirectory() as tmp:
        for i, batter in enumerate(batters):
            _hitting_page(c, df, batter, matchup, team, source, tmp, i,
                          fence)
            c.showPage()
    c.save()
    return buf.getvalue()


def _hitting_page(c, df, batter, matchup, team, source, tmp, idx,
                  fence=None):
    sub = df[df["batter"] == batter].copy()
    s = summarize(sub)
    if True:
        spray_p = os.path.join(tmp, f"spray{idx}.png")
        zone_p = os.path.join(tmp, f"zone{idx}.png")
        cq_p = os.path.join(tmp, f"cq{idx}.png")
        spray_chart(s["_bip"], spray_p, fence)
        zone_chart(s["_d"], zone_p)
        contact_chart(s["_bip"], cq_p)

        _draw_header(c, batter, matchup)
        _draw_statstrip(c, s, PH - 52 - 12)

        colw = (PW - 2 * MARGIN - 26) / 2
        lx = MARGIN
        rx = MARGIN + colw + 26

        # row 1 : spray + zone
        _title(c, "Batted balls", lx, 664, colw)
        _title(c, "Swing decisions", rx, 664, colw)
        for img_p, cx in ((spray_p, lx), (zone_p, rx)):
            ir = ImageReader(img_p)
            iw, ih = ir.getSize()
            hgt = 191.0
            wdt = hgt * (iw / ih)
            if wdt > colw:
                wdt, hgt = colw, colw * (ih / iw)
            c.drawImage(ir, cx + (colw - wdt) / 2, 652 - hgt, width=wdt,
                        height=hgt, mask="auto")

        # row 2 : contact quality + plate discipline
        _title(c, "Contact quality", lx, 419, colw)
        _title(c, "Plate discipline", rx, 419)
        ir = ImageReader(cq_p)
        iw, ih = ir.getSize()
        hgt = 178.0
        wdt = hgt * (iw / ih)
        if wdt > colw:
            wdt, hgt = colw, colw * (ih / iw)
        c.drawImage(ir, lx + (colw - wdt) / 2, 410 - hgt, width=wdt,
                    height=hgt, mask="auto")
        _draw_discipline(c, s, rx, 404, colw)

        # row 3 : plate appearances + pitch groups
        _title(c, "Plate appearances", lx, 209)
        _title(c, "By pitch group", rx, 209)
        pa_rows = pa_table(s)
        gp_rows = group_table(s)
        pa_w = [22, 62, 20, 16, 48, 30, 26, 29]
        gp_w = [46, 18, 38, 38, 36, 22, 28, 27]
        avail = 196 - 50
        min_rh = 10.5                      # below this the text stops fitting
        max_pa = max(int((avail - 22) // min_rh), 1)
        if len(pa_rows) > max_pa:
            extra = len(pa_rows) - (max_pa - 1)
            pa_rows = pa_rows[:max_pa - 1] + [
                [f"+{extra} more", "", "", "", "", "", "", ""]]
        pa_rh = min(19.0, (avail - 22) / max(len(pa_rows), 1))
        gp_rh = min(32.0, (avail - 22) / max(len(gp_rows), 1))
        _draw_table(c, ["Inn", "Pitcher", "Thr", "P", "Result", "EV", "LA",
                        "Dist"], pa_rows, pa_w, lx, 196,
                    align_first_left=False, rh=pa_rh, hh=22)
        _draw_table(c, ["Pitch", "#", "Swing%", "Chase%", "Whiff%", "BIP",
                        "EV", "HH%"], gp_rows, gp_w, rx, 196, rh=gp_rh, hh=22)

        _draw_footer(c, team, source)
