"""PDF builders: per-pitcher reports (portrait, one page each) and the
foldable staff sheet (portrait, two columns either side of the crease).

Expects a canonical frame: pitcher, throws, pitch_type, velo, spin, ivb, hb.
"""
from __future__ import annotations

import io
import os
import tempfile

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor, white

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOGO = os.path.join(HERE, "..", "assets", "Retro_on_Red.png")

MAROON = HexColor("#8c2232")
GOLD = HexColor("#dbcca6")
INK = HexColor("#1f1f1f")
SOFT = HexColor("#7a7a7a")      # staff sheet muted text
ISOFT = HexColor("#6b6b6b")     # individual-page muted text
RULE = HexColor("#d6d0c2")      # staff sheet card borders
IRULE = HexColor("#c9c9c9")     # individual-page rules (cooler gray)
TINT = HexColor("#f6f2e9")

# Official Baseball Savant palette (Tom Tango / MLBAM)
SAVANT = {"Fastball": "#D22D49", "Sinker": "#FE9D00", "Slider": "#EEE716",
          "Curveball": "#00D1ED", "ChangeUp": "#1DBE3A", "Cutter": "#933F2C",
          "Splitter": "#3BACAC"}
LABEL = {"ChangeUp": "Changeup"}
ABBR = {"Fastball": "FB", "Sinker": "SI", "Slider": "SL", "Curveball": "CB",
        "ChangeUp": "CH", "Cutter": "CT", "Splitter": "SP"}
PITCH_ORDER = ["Fastball", "Sinker", "Slider", "Curveball",
               "ChangeUp", "Cutter", "Splitter"]
OTHER = "#9E9E9E"

PROFILE = {"Stock": ("#c8102e", white),
           "North/South": ("#005daa", white),
           "East/West": ("#ffc72c", INK)}
DEFAULT_CUTS = (0.75, 1.10)
MIN_REPS = 3


def pitch_rank(pt):
    return PITCH_ORDER.index(pt) if pt in PITCH_ORDER else len(PITCH_ORDER)


def color(pt):
    return SAVANT.get(pt, OTHER)


def display(pt):
    return LABEL.get(pt, pt)


def short(pt):
    return ABBR.get(pt, str(pt)[:2].upper())


# ---------------------------------------------------------------- profiles
def spread_ratio(sub: pd.DataFrame, min_reps: int = MIN_REPS):
    """Vertical spread over horizontal spread across the arsenal.

    Pitch types below min_reps are ignored so a single mis-tag can't define
    a pitcher's shape."""
    m = sub.groupby("pitch_type").agg(n=("velo", "size"), ivb=("ivb", "mean"),
                                      hb=("hb", "mean"))
    m = m[m["n"] >= min_reps]
    if len(m) < 2:
        return None
    h = m["hb"].max() - m["hb"].min()
    if h <= 0:
        return float("inf")
    return (m["ivb"].max() - m["ivb"].min()) / h


def classify(sub, cuts=DEFAULT_CUTS, min_reps=MIN_REPS):
    r = spread_ratio(sub, min_reps)
    if r is None:
        return "Stock"
    lo, hi = cuts
    return "East/West" if r < lo else ("North/South" if r > hi else "Stock")


def staff_cuts(df, base=DEFAULT_CUTS, min_reps=MIN_REPS):
    """Re-center the cutoffs on this staff's median ratio.

    Horizontal separation naturally runs wider than vertical, so a neutral
    arsenal sits below 1.0. Anchoring on the group keeps the three buckets
    meaningful for a roster whose shape differs from the reference staff."""
    ratios = [spread_ratio(g, min_reps) for _, g in df.groupby("pitcher")]
    ratios = [r for r in ratios if r is not None and r != float("inf")]
    if not ratios:
        return base
    med = pd.Series(ratios).median()
    ref = 0.87  # median of the staff the defaults were fit to
    return (base[0] * med / ref, base[1] * med / ref)


def profiles_for(df, cuts=DEFAULT_CUTS, min_reps=MIN_REPS):
    return {p: classify(g, cuts, min_reps) for p, g in df.groupby("pitcher")}


def summarize(sub):
    rows = []
    for pt, g in sub.groupby("pitch_type"):
        rows.append({"pt": pt, "n": len(g), "avg": g["velo"].mean(),
                     "mx": g["velo"].max(), "spin": g["spin"].mean(),
                     "ivb": g["ivb"].mean(), "hb": g["hb"].mean()})
    return sorted(rows, key=lambda r: pitch_rank(r["pt"]))


def split_name(name):
    if "," in name:
        last, first = [p.strip() for p in name.split(",", 1)]
        return f"{first} {last}"
    return name.strip()


def hand(throws):
    return "LHP" if str(throws).lower().startswith("l") else "RHP"


# ------------------------------------------------------------------ plots
def _full_plot(sub, throws, path):
    fig, ax = plt.subplots(figsize=(3.6, 3.6), dpi=300)
    for pt in sorted(sub["pitch_type"].unique(), key=pitch_rank):
        g = sub[sub["pitch_type"] == pt]
        ax.scatter(g["hb"], g["ivb"], s=46, c=color(pt), alpha=0.9,
                   edgecolors="white", linewidths=0.5,
                   label=f"{display(pt)} ({len(g)})", zorder=3)
    ax.axhline(0, color="#4a4a4a", lw=0.9, zorder=2)
    ax.axvline(0, color="#4a4a4a", lw=0.9, zorder=2)
    ax.set_xlim(-25, 25)
    ax.set_ylim(-25, 25)
    ax.set_aspect("equal")
    ax.set_xticks(range(-20, 21, 10))
    ax.set_yticks(range(-20, 21, 10))
    ax.grid(True, color="#e2e2e2", lw=0.6, zorder=1)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_color("#b0b0b0")
        s.set_linewidth(0.8)
    ax.tick_params(labelsize=7.5, colors="#4a4a4a", length=3)
    ax.set_xlabel("Horizontal Break (in.)", fontsize=8.5, color="#333333",
                  labelpad=4)
    ax.set_ylabel("Induced Vertical Break (in.)", fontsize=8.5,
                  color="#333333", labelpad=2)
    # +HB is arm side for a righty, glove side for a lefty
    left, right = (("Arm", "Glove") if str(throws).lower().startswith("l")
                   else ("Glove", "Arm"))
    ax.text(-24, -23.4, f"\u2190 {left} side", fontsize=7, color="#8a8a8a",
            ha="left")
    ax.text(24, -23.4, f"{right} side \u2192", fontsize=7, color="#8a8a8a",
            ha="right")
    n = len(sub["pitch_type"].unique())
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13),
              ncol=3 if n > 4 else 2, fontsize=6.8, frameon=False,
              handletextpad=0.35, columnspacing=1.0, labelspacing=0.35,
              borderaxespad=0)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.04, transparent=True)
    plt.close(fig)


def _mini_plot(sub, path):
    fig, ax = plt.subplots(figsize=(1.15, 1.15), dpi=340)
    for pt in sorted(sub["pitch_type"].unique(), key=pitch_rank):
        g = sub[sub["pitch_type"] == pt]
        ax.scatter(g["hb"], g["ivb"], s=5.0, c=color(pt), alpha=0.92,
                   edgecolors="white", linewidths=0.15, zorder=3)
    ax.set_xlim(-25, 25)
    ax.set_ylim(-25, 25)
    ax.set_aspect("equal")
    ax.set_xticks(range(-20, 21, 10))
    ax.set_yticks(range(-20, 21, 10))
    ax.set_xticklabels(["-20", "", "0", "", "20"])
    ax.set_yticklabels(["-20", "", "0", "", "20"])
    ax.tick_params(length=0, pad=1.1, labelsize=4.0, colors="#8a8a8a")
    ax.grid(True, color="#e8e8e8", lw=0.35, zorder=1)
    ax.set_axisbelow(True)
    ax.axhline(0, color="#5a5a5a", lw=0.5, zorder=2)
    ax.axvline(0, color="#5a5a5a", lw=0.5, zorder=2)
    for s in ax.spines.values():
        s.set_color("#c0c0c0")
        s.set_linewidth(0.45)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.01, transparent=True)
    plt.close(fig)


# ------------------------------------------------- individual report pages
IPW, IPH = letter
IMARGIN = 40
IHEADER_H = 88


def _ind_header(c, name, throws, profile, logo):
    c.setFillColor(MAROON)
    c.rect(0, IPH - IHEADER_H, IPW, IHEADER_H, stroke=0, fill=1)
    lh = 64.0
    img = ImageReader(logo)
    iw, ih = img.getSize()
    c.drawImage(img, 30, IPH - IHEADER_H / 2 - lh / 2, width=lh * (iw / ih),
                height=lh, mask="auto", preserveAspectRatio=True)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 25)
    c.drawCentredString(IPW / 2, IPH - IHEADER_H / 2 - 9,
                        f"{split_name(name)} - {hand(throws)}")

    fill, txt = PROFILE[profile]
    c.setFont("Helvetica-Bold", 9)
    bw = c.stringWidth(profile, "Helvetica-Bold", 9) + 22
    bx, by, bh = IPW - IMARGIN - bw, IPH - IHEADER_H / 2 - 10, 20
    c.setFillColor(HexColor(fill))
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.9)
    c.roundRect(bx, by, bw, bh, 4, stroke=1, fill=1)
    c.setFillColor(txt)
    c.drawCentredString(bx + bw / 2, by + 6.5, profile)


def _ind_table(c, rows, top):
    cols = [132, 44, 74, 74, 76, 66, 66]
    heads = ["PITCH", "#", "AVG VELO", "MAX VELO", "SPIN", "IVB", "HB"]
    x0, hh, rh = IMARGIN, 21, 17.5
    c.setFillColor(MAROON)
    c.rect(x0, top - hh, sum(cols), hh, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 8.2)
    x = x0
    for w, h in zip(cols, heads):
        if h == "PITCH":
            c.drawString(x + 10, top - hh + 7, h)
        else:
            c.drawCentredString(x + w / 2, top - hh + 7, h)
        x += w

    y = top - hh
    for i, r in enumerate(rows):
        y -= rh
        if i % 2 == 1:
            c.setFillColor(TINT)
            c.rect(x0, y, sum(cols), rh, stroke=0, fill=1)
        c.setFillColor(HexColor(color(r["pt"])))
        c.circle(x0 + 15, y + rh / 2, 4.6, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x0 + 26, y + 5.6, display(r["pt"]))
        vals = [str(r["n"]), f"{r['avg']:.1f}", f"{r['mx']:.1f}",
                f"{r['spin']:.0f}", f"{r['ivb']:.1f}", f"{r['hb']:.1f}"]
        c.setFont("Helvetica", 9)
        x = x0 + cols[0]
        for w, v in zip(cols[1:], vals):
            c.drawCentredString(x + w / 2, y + 5.6, v)
            x += w
    c.setStrokeColor(IRULE)
    c.setLineWidth(0.5)
    c.rect(x0, y, sum(cols), top - y, stroke=1, fill=0)
    return y


def _ind_notes(c, rows, top, bottom):
    c.setFillColor(MAROON)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(IMARGIN, top - 10, "NOTES")
    c.setStrokeColor(MAROON)
    c.setLineWidth(1.1)
    c.line(IMARGIN, top - 15, IPW - IMARGIN, top - 15)
    labels = [display(r["pt"]) for r in rows] + ["Overall"]
    cols = [color(r["pt"]) for r in rows] + [None]
    step = min(30.0, ((top - 24) - bottom) / len(labels))
    y = top - 24
    for lab, col in zip(labels, cols):
        y -= step
        if col:
            c.setFillColor(HexColor(col))
            c.circle(IMARGIN + 5, y + 3.4, 4.2, stroke=0, fill=1)
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 8.4)
        else:
            c.setFillColor(ISOFT)
            c.setFont("Helvetica-Oblique", 8.4)
        c.drawString(IMARGIN + 15, y + 1, lab)
        c.setStrokeColor(IRULE)
        c.setLineWidth(0.5)
        c.line(IMARGIN + 92, y, IPW - IMARGIN, y)


def build_individual_pdf(df, profiles=None, logo=DEFAULT_LOGO) -> bytes:
    profiles = profiles or profiles_for(df)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle("Pitching \u2013 Individual Reports")
    with tempfile.TemporaryDirectory() as tmp:
        for i, name in enumerate(sorted(df["pitcher"].unique())):
            sub = df[df["pitcher"] == name]
            img = os.path.join(tmp, f"{i}.png")
            _full_plot(sub, sub["throws"].iloc[0], img)
            _ind_header(c, name, sub["throws"].iloc[0],
                        profiles.get(name, "Stock"), logo)
            rows = summarize(sub)
            table_h = 21 + len(rows) * 17.5
            notes_h = 24 + (len(rows) + 1) * 18.5
            body_top = IPH - IHEADER_H
            plot_h = body_top - IMARGIN - table_h - notes_h - 40
            plot_h = max(238, min(312, plot_h))
            ir = ImageReader(img)
            iw, ih = ir.getSize()
            pw = plot_h * (iw / ih)
            if pw > 372:
                pw, plot_h = 372, 372 * (ih / iw)
            c.drawImage(ir, (IPW - pw) / 2, body_top - 14 - plot_h,
                        width=pw, height=plot_h, mask="auto")
            tbot = _ind_table(c, rows, body_top - 14 - plot_h - 16)
            _ind_notes(c, rows, tbot - 20, IMARGIN)
            c.showPage()
    c.save()
    return buf.getvalue()


# ------------------------------------------------------------ staff sheet
SPW, SPH = letter
SMARGIN = 18
FOLD_GUT = 28
SHEADER_H = 44
KEY_H = 24
SCOLS, SROWS = 2, 8
ROW_GUT = 4
NAME_H = 12.0
STAT_H = 8.6          # season-stat strip, only drawn when stats are supplied
PLOT_S = 71.0
PLOT_S_STATS = 61.0   # plot shrinks to make room for that strip
THEAD_H = 8.0
TROW_H = 8.0


def _staff_header(c, logo, title):
    c.setFillColor(MAROON)
    c.rect(0, SPH - SHEADER_H, SPW, SHEADER_H, stroke=0, fill=1)
    lh = 32.0
    img = ImageReader(logo)
    iw, ih = img.getSize()
    c.drawImage(img, 18, SPH - SHEADER_H / 2 - lh / 2, width=lh * (iw / ih),
                height=lh, mask="auto", preserveAspectRatio=True)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(62, SPH - SHEADER_H / 2 - 5.5, title)
    # key sits entirely right of the crease
    c.setFont("Helvetica-Bold", 6.4)
    items = [(k, c.stringWidth(k, "Helvetica-Bold", 6.4) + 21) for k in PROFILE]
    x = SPW - SMARGIN - sum(w for _, w in items)
    ky = SPH - SHEADER_H / 2 - 4.5
    for label, w in items:
        c.setFillColor(HexColor(PROFILE[label][0]))
        c.roundRect(x, ky - 1.5, 11, 9, 1.6, stroke=0, fill=1)
        c.setFillColor(GOLD)
        c.drawString(x + 15, ky + 1, label)
        x += w


def _staff_key(c, present):
    y = SPH - SHEADER_H - KEY_H
    x = SMARGIN
    for p in [q for q in PITCH_ORDER if q in present]:
        lab = display(p)
        c.setFillColor(HexColor(color(p)))
        c.circle(x + 3.4, y + 8, 2.7, stroke=0, fill=1)
        c.setFillColor(SOFT)
        c.setFont("Helvetica", 6.2)
        c.drawString(x + 9, y + 5.9, lab)
        x += c.stringWidth(lab, "Helvetica", 6.2) + 17
    c.setFillColor(HexColor("#a09a8c"))
    c.setFont("Helvetica-Oblique", 6.0)
    c.drawRightString(SPW - SMARGIN, y + 5.9,
                      "Movement plots: \u00b125 in., gridlines every 10 in.")


def _staff_card(c, x, y, w, h, name, throws, profile, sub, img,
                stat_line="", stat_h=0.0, plot_s=PLOT_S, row_h=TROW_H):
    c.setStrokeColor(RULE)
    c.setLineWidth(0.6)
    c.rect(x, y, w, h, stroke=1, fill=0)
    fill, txt = PROFILE[profile]
    c.setFillColor(HexColor(fill))
    c.rect(x, y + h - NAME_H, w, NAME_H, stroke=0, fill=1)
    c.setFillColor(txt)
    c.setFont("Helvetica-Bold", 7.4)
    c.drawCentredString(x + w / 2, y + h - NAME_H + 3.8,
                        f"{split_name(name)} - {hand(throws)}")

    if stat_h:
        sy = y + h - NAME_H - stat_h
        c.setFillColor(HexColor("#f0ece2"))
        c.rect(x, sy, w, stat_h, stroke=0, fill=1)
        c.setStrokeColor(RULE)
        c.setLineWidth(0.35)
        c.line(x, sy, x + w, sy)
        if stat_line:
            c.setFillColor(HexColor("#4a4a4a"))
            c.setFont("Helvetica", 5.9)
            c.drawCentredString(x + w / 2, sy + 2.6, stat_line)

    body_top = y + h - NAME_H - stat_h
    ir = ImageReader(img)
    iw, ih = ir.getSize()
    c.drawImage(ir, x + 2, body_top - 1 - plot_s, width=plot_s * (iw / ih),
                height=plot_s, mask="auto")

    rows = summarize(sub)
    cols = [33, 33, 33, 35, 29.5, 29.5]
    heads = ["", "AVG", "MAX", "SPIN", "IVB", "HB"]
    tw = sum(cols)
    tx, ty = x + w - 5 - tw, body_top - 2
    c.setFillColor(HexColor("#efe9dc"))
    c.rect(tx, ty - THEAD_H, tw, THEAD_H, stroke=0, fill=1)
    c.setFillColor(MAROON)
    c.setFont("Helvetica-Bold", 5.3)
    cx = tx
    for cw, hd in zip(cols, heads):
        if hd:
            c.drawCentredString(cx + cw / 2, ty - THEAD_H + 2.7, hd)
        cx += cw
    ry = ty - THEAD_H
    for i, r in enumerate(rows):
        ry -= row_h
        if i % 2 == 1:
            c.setFillColor(TINT)
            c.rect(tx, ry, tw, row_h, stroke=0, fill=1)
        c.setFillColor(HexColor(color(r["pt"])))
        c.circle(tx + 7.5, ry + row_h / 2, 2.5, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 6.0)
        c.drawString(tx + 12.5, ry + (row_h - 6.0) / 2 + 1.3, short(r["pt"]))
        c.setFont("Helvetica", 6.0)
        vals = [f"{r['avg']:.1f}", f"{r['mx']:.1f}", f"{r['spin']:.0f}",
                f"{r['ivb']:.1f}", f"{r['hb']:.1f}"]
        cx = tx + cols[0]
        for cw, v in zip(cols[1:], vals):
            c.drawCentredString(cx + cw / 2, ry + (row_h - 6.0) / 2 + 1.3, v)
            cx += cw
    c.setStrokeColor(RULE)
    c.setLineWidth(0.4)
    c.rect(tx, ry, tw, ty - ry, stroke=1, fill=0)


def _profile_key_card(c, x, y, w, h):
    c.setStrokeColor(RULE)
    c.setLineWidth(0.6)
    c.rect(x, y, w, h, stroke=1, fill=0)
    c.setFillColor(MAROON)
    c.rect(x, y + h - NAME_H, w, NAME_H, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 7.4)
    c.drawCentredString(x + w / 2, y + h - NAME_H + 3.8, "Profile Key")
    ty = y + h - NAME_H - 16
    for label, desc in [
            ("Stock", "Separates about evenly in both planes."),
            ("North/South", "Separation is mostly vertical (IVB)."),
            ("East/West", "Separation is mostly horizontal (HB).")]:
        c.setFillColor(HexColor(PROFILE[label][0]))
        c.roundRect(x + 8, ty - 1.8, 10, 8, 1.5, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 6.2)
        c.drawString(x + 22, ty + 0.6, label)
        c.setFillColor(SOFT)
        c.setFont("Helvetica", 6.2)
        c.drawString(x + 22 + c.stringWidth(label, "Helvetica-Bold", 6.2) + 4,
                     ty + 0.6, desc)
        ty -= 13


def build_staff_pdf(df, profiles=None, logo=DEFAULT_LOGO,
                    title="Pitching Staff", stats=None) -> bytes:
    profiles = profiles or profiles_for(df)
    stats = stats or {}
    stat_h = STAT_H if stats else 0.0
    plot_s = PLOT_S_STATS if stats else PLOT_S
    pitchers = sorted(df["pitcher"].unique())
    per_page = SCOLS * SROWS
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle(title)
    cw = (SPW - 2 * SMARGIN - FOLD_GUT) / SCOLS
    grid_top = SPH - SHEADER_H - KEY_H - 2
    ch = (grid_top - SMARGIN - (SROWS - 1) * ROW_GUT) / SROWS

    # keep the tallest arsenal inside its card; uniform across the sheet
    widest = max((df.groupby("pitcher")["pitch_type"].nunique().max(), 1))
    row_h = min(TROW_H, (ch - NAME_H - stat_h - THEAD_H) / widest)

    with tempfile.TemporaryDirectory() as tmp:
        pages = [pitchers[i:i + per_page]
                 for i in range(0, len(pitchers), per_page)] or [[]]
        for pg, chunk in enumerate(pages):
            _staff_header(c, logo, title if len(pages) == 1
                          else f"{title} ({pg + 1}/{len(pages)})")
            _staff_key(c, set(df["pitch_type"]))
            for i, name in enumerate(chunk):
                col, r = divmod(i, SROWS)      # column-major: each folded
                x = SMARGIN + col * (cw + FOLD_GUT)   # face reads in order
                y = grid_top - (r + 1) * ch - r * ROW_GUT
                sub = df[df["pitcher"] == name]
                img = os.path.join(tmp, f"{pg}_{i}.png")
                _mini_plot(sub, img)
                _staff_card(c, x, y, cw, ch, name, sub["throws"].iloc[0],
                            profiles.get(name, "Stock"), sub, img,
                            stats.get(name, ""), stat_h, plot_s, row_h)
            if len(chunk) < per_page:
                col, r = divmod(len(chunk), SROWS)
                if col < SCOLS:
                    _profile_key_card(c, SMARGIN + col * (cw + FOLD_GUT),
                                      grid_top - (r + 1) * ch - r * ROW_GUT,
                                      cw, ch)
            c.setStrokeColor(HexColor("#cfcfcf"))
            c.setLineWidth(0.4)
            c.setDash(1.5, 3)
            c.line(SPW / 2, SMARGIN - 8, SPW / 2, SPH - SHEADER_H + 4)
            c.setDash()
            c.showPage()
    c.save()
    return buf.getvalue()
