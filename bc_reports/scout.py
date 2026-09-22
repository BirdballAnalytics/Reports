"""Expanded individual scouting sheets.

Two layouts of the same content, so the staff can pick:
  build_individual_1page  -- everything on one sheet, panels run small
  build_individual_2page  -- page 1 profile and metrics, page 2 splits,
                             usage and heat maps at full size
"""
from __future__ import annotations

import io
import os
import tempfile

import pandas as pd
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from . import advanced, panels, staffstats
from .reports import (DEFAULT_LOGO, GOLD, INK, IRULE, ISOFT, LHH_BLUE, MAROON,
                      PROFILE, RHH_RED, TINT, classify, color, display, hand,
                      pitch_rank, split_name)

PW, PH = letter
MARGIN = 34
HEADER_H = 74
# Height the RHH / LHH notes block needs: heading and rule, then two lines.
NOTES_H = 62.0


# ------------------------------------------------------------------ blocks
def _header(c, name, throws, profile, logo, sub=""):
    c.setFillColor(MAROON)
    c.rect(0, PH - HEADER_H, PW, HEADER_H, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.rect(0, PH - HEADER_H - 4, PW, 4, stroke=0, fill=1)

    img = ImageReader(logo)
    iw, ih = img.getSize()
    lh = 54.0
    c.drawImage(img, 26, PH - HEADER_H / 2 - lh / 2, width=lh * (iw / ih),
                height=lh, mask="auto", preserveAspectRatio=True)

    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(PW / 2, PH - HEADER_H / 2 - 8,
                        f"{split_name(name)} - {hand(throws)}")
    if sub:
        c.setFont("Helvetica", 8)
        c.drawCentredString(PW / 2, PH - HEADER_H / 2 - 21, sub)

    fill, txt = PROFILE[profile]
    c.setFont("Helvetica-Bold", 8.5)
    bw = c.stringWidth(profile, "Helvetica-Bold", 8.5) + 20
    bx, by, bh = PW - MARGIN - bw, PH - HEADER_H / 2 - 9, 18
    c.setFillColor(HexColor(fill))
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.9)
    c.roundRect(bx, by, bw, bh, 4, stroke=1, fill=1)
    c.setFillColor(txt)
    c.drawCentredString(bx + bw / 2, by + 5.6, profile)


def _season_strip(c, stat, top, h=32.0):
    """Full-season line. Values come from the official stats export."""
    w = PW - 2 * MARGIN
    cells = [(lab, stat.get(k)) for k, lab in staffstats.FULL_FIELDS]
    cw = w / len(cells)
    c.setFillColor(TINT)
    c.rect(MARGIN, top - h, w, h, stroke=0, fill=1)
    c.setStrokeColor(IRULE)
    c.setLineWidth(0.6)
    c.rect(MARGIN, top - h, w, h, stroke=1, fill=0)
    for i, (lab, val) in enumerate(cells):
        x = MARGIN + i * cw
        if i:
            c.setStrokeColor(IRULE)
            c.line(x, top - h + 4, x, top - 4)
        txt = "—" if val is None or (isinstance(val, float) and pd.isna(val)) \
            else str(val).strip()
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawCentredString(x + cw / 2, top - 14, txt)
        c.setFillColor(ISOFT)
        c.setFont("Helvetica", 5.8)
        c.drawCentredString(x + cw / 2, top - 24, lab)
    return top - h


def _metrics_table(c, rows, x, top, w):
    """Pitch averages including VAA, EXT, RelH and InZone%."""
    heads = ["PITCH", "#", "AVG", "MAX", "SPIN", "IVB", "HB", "VAA", "EXT",
             "RELH", "ZONE"]
    wts = [2.30, 0.70, 0.98, 0.98, 1.06, 0.88, 0.88, 0.88, 0.84, 0.90, 0.98]
    tot = sum(wts)
    cols = [w * t / tot for t in wts]
    hh, rh = 17.0, 15.0

    c.setFillColor(MAROON)
    c.rect(x, top - hh, w, hh, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 6.6)
    cx = x
    for cw, hd in zip(cols, heads):
        if hd == "PITCH":
            c.drawString(cx + 8, top - hh + 5.8, hd)
        else:
            c.drawCentredString(cx + cw / 2, top - hh + 5.8, hd)
        cx += cw

    y = top - hh
    for i, r in enumerate(rows):
        y -= rh
        if i % 2 == 1:
            c.setFillColor(TINT)
            c.rect(x, y, w, rh, stroke=0, fill=1)
        c.setFillColor(HexColor(color(r["pt"])))
        c.circle(x + 11, y + rh / 2, 3.8, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 7.4)
        c.drawString(x + 19, y + 4.6, display(r["pt"]))

        def num(v, fmt):
            return "—" if v is None or pd.isna(v) else format(v, fmt)
        vals = [str(r["n"]), num(r["avg"], ".1f"), num(r["mx"], ".1f"),
                num(r["spin"], ".0f"), num(r["ivb"], ".1f"),
                num(r["hb"], ".1f"), num(r["vaa"], ".1f"),
                num(r["ext"], ".1f"), num(r["relh"], ".1f"),
                "—" if pd.isna(r["zone"]) else f"{r['zone']*100:.0f}%"]
        c.setFont("Helvetica", 7.2)
        cx = x + cols[0]
        for cw, v in zip(cols[1:], vals):
            c.drawCentredString(cx + cw / 2, y + 4.6, v)
            cx += cw
    c.setStrokeColor(IRULE)
    c.setLineWidth(0.5)
    c.rect(x, y, w, top - y, stroke=1, fill=0)
    return y


def _splits_table(c, sp, x, top, w):
    """Results against each batter hand, derived from the pitch data."""
    heads = ["VS", "PA", "AVG", "OBP", "OPS", "H", "2B", "3B", "HR", "K%",
             "BB%"]
    wts = [1.05, 0.80, 1.05, 1.05, 1.05, 0.66, 0.66, 0.66, 0.66, 0.92, 0.92]
    tot = sum(wts)
    cols = [w * t / tot for t in wts]
    hh, rh = 15.0, 14.0

    c.setFillColor(MAROON)
    c.rect(x, top - hh, w, hh, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 6.4)
    cx = x
    for cw, hd in zip(cols, heads):
        c.drawCentredString(cx + cw / 2, top - hh + 5.0, hd)
        cx += cw

    y = top - hh
    label = {"R": "RHH", "L": "LHH", "ALL": "TOTAL"}
    tone = {"R": RHH_RED, "L": LHH_BLUE, "ALL": INK}
    for i, hnd in enumerate(("ALL", "R", "L")):
        row = sp[sp["hand"] == hnd] if not sp.empty else sp
        y -= rh
        if hnd == "ALL":
            c.setFillColor(HexColor("#ece6d8"))
            c.rect(x, y, w, rh, stroke=0, fill=1)
        elif i % 2 == 1:
            c.setFillColor(TINT)
            c.rect(x, y, w, rh, stroke=0, fill=1)
        c.setFillColor(tone[hnd])
        c.setFont("Helvetica-Bold", 7.4)
        c.drawCentredString(x + cols[0] / 2, y + 4.2, label[hnd])
        c.setFillColor(INK)
        c.setFont("Helvetica", 7.2)
        if row.empty:
            vals = ["—"] * 10
        else:
            r = row.iloc[0]
            def f3(v):
                return "—" if pd.isna(v) else f"{v:.3f}".lstrip("0")
            vals = [str(int(r["PA"])), f3(r["AVG"]), f3(r["OBP"]), f3(r["OPS"]),
                    str(int(r["H"])), str(int(r["2B"])), str(int(r["3B"])),
                    str(int(r["HR"])), f"{r['K%']*100:.0f}%",
                    f"{r['BB%']*100:.0f}%"]
        cx = x + cols[0]
        for cw, v in zip(cols[1:], vals):
            c.drawCentredString(cx + cw / 2, y + 4.2, v)
            cx += cw
    c.setStrokeColor(IRULE)
    c.setLineWidth(0.5)
    c.rect(x, y, w, top - y, stroke=1, fill=0)
    return y


def _section(c, label, x, y, note=""):
    c.setFillColor(MAROON)
    c.setFont("Helvetica-Bold", 8.6)
    c.drawString(x, y, label)
    if note:
        c.setFillColor(ISOFT)
        c.setFont("Helvetica-Oblique", 6.2)
        c.drawString(x + c.stringWidth(label, "Helvetica-Bold", 8.6) + 7,
                     y, note)


def _usage_legend(c, x, y, text=None, size=6.0):
    """text defaults to muted ink; pass GOLD when drawing on the maroon bar."""
    c.setFont("Helvetica", size)
    for lab, col in panels.usage_legend_items():
        c.setFillColor(HexColor(col))
        c.rect(x, y - 1, size + 1, size, stroke=0, fill=1)
        c.setFillColor(text or ISOFT)
        c.drawString(x + size + 4, y, lab)
        x += size + 4 + c.stringWidth(lab, "Helvetica", size) + 12


def _heat_grid(c, sub, tmp, tag, x, top, w, cols=4, gap=7.0, bottom=None):
    """Four groups across, one row per batter hand, spanning the full width.

    The grid is always four by two: a group the pitcher does not throw draws
    as an empty zone rather than being skipped, so every sheet reads alike.

    Pass `bottom` and the panels size themselves to the room that is left.
    The block above this one grows with the number of pitches a man throws --
    six write-in lines take more room than two -- and it is far better for
    the maps to give up a few points than for the page to run off the end.
    """
    picked = advanced.heat_panels(sub)
    cell = (w - (cols - 1) * gap) / cols
    if bottom is not None:
        # Each of the two rows carries a 12pt hand label above and 9pt of air
        # below its panels, and a panel is within a percent of square once
        # the group title is counted.
        fit = (top - bottom) / 2.0 - 21.0
        cell = max(48.0, min(cell, fit))
        gap = (w - cols * cell) / (cols - 1)
    y = top
    for hnd in ("R", "L"):
        row = [(g, s2) for g, h, s2 in picked if h == hnd]
        c.setFillColor(RHH_RED if hnd == "R" else LHH_BLUE)
        c.setFont("Helvetica-Bold", 7.6)
        c.drawString(x, y - 8, f"vs {hnd}HH")
        y -= 12
        cx = x
        low = 0
        for g, s2 in row:
            p = os.path.join(tmp, f"{tag}_{hnd}_{g}.png")
            panels.heat_map(s2, p, advanced.HEAT_TITLE[g], size=1.9)
            ir = ImageReader(p)
            iw, ih = ir.getSize()
            h = cell * (ih / iw)
            low = max(low, h)
            c.drawImage(ir, cx, y - h, width=cell, height=h, mask="auto")
            cx += cell + gap
        y -= low + 9
    return y


def _pitch_notes(c, rows, x, top, w):
    """A write-in line for each pitch this man actually throws.

    Sits directly under the metrics table so the note is read next to the
    numbers it describes. Only his own pitch types appear -- a sheet for a
    two-pitch reliever gets two lines, not six empty ones.

    The step tightens for a six-pitch arsenal: those are rare, and the few
    points saved are what keep the block from pushing the heat maps off the
    bottom of the page.
    """
    if not rows:
        return top
    step = 13.0 if len(rows) <= 5 else 11.5
    c.setFillColor(MAROON)
    c.setFont("Helvetica-Bold", 7.0)
    c.drawString(x, top - 7.5, "NOTES BY PITCH")
    y = top - 11.0
    for r in rows:
        y -= step
        c.setFillColor(HexColor(color(r["pt"])))
        c.circle(x + 3.4, y + 2.4, 2.6, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 7.2)
        lab = display(r["pt"])
        c.drawString(x + 9.5, y + 0.8, lab)
        c.setStrokeColor(IRULE)
        c.setLineWidth(0.5)
        c.line(x + 62, y, x + w, y)
    return y


def _notes(c, x, top, bottom, w):
    c.setFillColor(MAROON)
    c.setFont("Helvetica-Bold", 8.6)
    c.drawString(x, top - 9, "NOTES")
    c.setStrokeColor(MAROON)
    c.setLineWidth(1.0)
    c.line(x, top - 14, x + w, top - 14)
    step = max(14.0, min(26.0, ((top - 22) - bottom) / 2))
    y = top - 22
    for lab, col in (("RHH:", RHH_RED), ("LHH:", LHH_BLUE)):
        y -= step
        c.setFillColor(col)
        c.setFont("Helvetica-Bold", 8.4)
        c.drawString(x + 2, y + 1, lab)
        c.setStrokeColor(IRULE)
        c.setLineWidth(0.5)
        c.line(x + 34, y, x + w, y)
    return y


# ------------------------------------------------------------------ pieces
def _prep(df, name):
    sub = df[df["pitcher"] == name]
    return sub, advanced.metrics_table(sub), advanced.hand_splits(sub), \
        advanced.usage(sub)


def _movement(c, sub, tmp, tag, x, top, size):
    from .reports import _full_plot
    p = os.path.join(tmp, f"{tag}_mv.png")
    _full_plot(sub, sub["throws"].iloc[0], p)
    ir = ImageReader(p)
    iw, ih = ir.getSize()
    w = size * (iw / ih)
    c.drawImage(ir, x, top - size, width=w, height=size, mask="auto")
    return w


# ------------------------------------------------------------- one page
def build_individual_1page(df, stats=None, logo=DEFAULT_LOGO,
                           batters=None) -> bytes:
    stats = stats or {}
    names = batters or sorted(df["pitcher"].unique())
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle("Individual scouting reports")

    with tempfile.TemporaryDirectory() as tmp:
        for i, name in enumerate(names):
            sub, mets, sp, use = _prep(df, name)
            _header(c, name, sub["throws"].iloc[0], classify(sub), logo)
            y = PH - HEADER_H - 12
            y = _season_strip(c, stats.get(name, {}), y) - 12

            # movement plot beside the metrics table
            plot_h = 134.0
            pw = _movement(c, sub, tmp, f"{i}", MARGIN, y, plot_h)
            tx = MARGIN + pw + 12
            tw = PW - MARGIN - tx
            tbl_bot = _metrics_table(c, mets, tx, y, tw)
            notes_bot = _pitch_notes(c, mets, tx, tbl_bot - 6, tw)
            # The right-hand column can run past the plot when a man throws
            # five or six pitches, so the row takes whichever is taller.
            y -= max(plot_h, y - notes_bot + 4) + 12

            # splits left, usage right
            ux = PW / 2 + 10
            _section(c, "SPLITS", MARGIN, y)
            _section(c, "USAGE", ux, y)
            y -= 10
            _splits_table(c, sp, MARGIN, y, PW / 2 - MARGIN - 14)

            up = os.path.join(tmp, f"{i}_use.png")
            panels.usage_bars(use, up, width=4.0, height=1.25)
            ir = ImageReader(up)
            iw, ih = ir.getSize()
            uw = PW - MARGIN - ux
            uh = uw * (ih / iw)
            c.drawImage(ir, ux, y - uh, width=uw, height=uh, mask="auto")
            _usage_legend(c, ux, y - uh - 9)
            y -= max(uh + 20, 58)

            _section(c, "LOCATION", MARGIN, y)
            y -= 6
            # Room kept back for the notes block: its rule, then two lines.
            y = _heat_grid(c, sub, tmp, f"{i}", MARGIN, y,
                           PW - 2 * MARGIN, bottom=MARGIN + NOTES_H)

            _notes(c, MARGIN, y - 4, MARGIN, PW - 2 * MARGIN)
            c.showPage()
    c.save()
    return buf.getvalue()


# ------------------------------------------------------------- two pages
def build_individual_2page(df, stats=None, logo=DEFAULT_LOGO,
                           batters=None) -> bytes:
    stats = stats or {}
    names = batters or sorted(df["pitcher"].unique())
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle("Individual scouting reports")

    with tempfile.TemporaryDirectory() as tmp:
        for i, name in enumerate(names):
            sub, mets, sp, use = _prep(df, name)
            prof = classify(sub)

            # ---- page 1: profile, shape, notes
            _header(c, name, sub["throws"].iloc[0], prof, logo)
            y = PH - HEADER_H - 14
            y = _season_strip(c, stats.get(name, {}), y, h=36.0) - 16

            plot_h = 232.0
            pw = _movement(c, sub, tmp, f"{i}", MARGIN, y, plot_h)
            tx = MARGIN + pw + 16
            tw = PW - MARGIN - tx
            tbl_bot = _metrics_table(c, mets, tx, y, tw)
            notes_bot = _pitch_notes(c, mets, tx, tbl_bot - 10, tw)
            y -= max(plot_h, y - notes_bot + 4) + 18

            _section(c, "SPLITS", MARGIN, y)
            y -= 8
            y = _splits_table(c, sp, MARGIN, y, PW - 2 * MARGIN) - 18

            _notes(c, MARGIN, y, MARGIN, PW - 2 * MARGIN)
            c.showPage()

            # ---- page 2: usage and location
            _header(c, name, sub["throws"].iloc[0], prof, logo,
                    sub="Usage and location")
            y = PH - HEADER_H - 18

            _section(c, "USAGE", MARGIN, y)
            y -= 10
            up = os.path.join(tmp, f"{i}_use2.png")
            panels.usage_bars(use, up, width=4.0, height=1.25)
            ir = ImageReader(up)
            iw, ih = ir.getSize()
            uw = 330.0
            c.drawImage(ir, MARGIN, y - uw * (ih / iw), width=uw,
                        height=uw * (ih / iw), mask="auto")
            _usage_legend(c, MARGIN + uw + 16, y - 30)
            y -= uw * (ih / iw) + 22

            _section(c, "LOCATION", MARGIN, y)
            y -= 6
            _heat_grid(c, sub, tmp, f"{i}b", MARGIN, y, PW - 2 * MARGIN)
            c.showPage()
    c.save()
    return buf.getvalue()


# ============================================================ staff sheet
SPW, SPH = letter                 # portrait, folded once down the middle
SM = 18.0
SHEAD, SFOOT = 40.0, 15.0
SCOLS, SROWS = 2, 10
# Gutter wide enough that the centre crease clears both cards by 4mm.
SGX, SGY = 24.0, 4.0
# Breathing room under the maroon header band, so the first row of cards
# does not butt up against it.
SGAP = 10.0


def ip_value(ip) -> float:
    """Innings pitched as a number.

    Baseball writes thirds after the point: 6.1 is six and a third, 6.2 is
    six and two thirds. Sorting the raw string would put 6.2 above 6.1 but
    also above 10.0, so it has to be converted."""
    try:
        txt = str(ip).strip()
        whole, _, frac = txt.partition(".")
        return float(whole or 0) + {"1": 1 / 3, "2": 2 / 3}.get(frac[:1], 0.0)
    except Exception:
        return 0.0


def _card_rows(mets, cap=6, floor=0.0):
    """Every pitch type he throws, most-used first, then back into order.

    This used to drop anything under five pitches or 2% of the arsenal and
    cap the card at four rows, which quietly cost real pitches -- a starter's
    85 curveballs among them. The card has room for six, which covers every
    arsenal seen so far, so nothing is dropped unless a man throws more than
    that, and then it is the least-used that goes.
    """
    total = sum(r["n"] for r in mets) or 1
    keep = [r for r in mets if r["n"] >= floor * total] if floor else list(mets)
    keep = sorted(keep, key=lambda r: -r["n"])[:cap]
    return sorted(keep, key=lambda r: pitch_rank(r["pt"]))


def _abbr(pt):
    from .reports import ABBR
    return ABBR.get(pt, str(pt)[:2].upper())


def _staff_metrics(c, rows, x, top, w, rh=None, fs=4.3):
    # A six-pitch arsenal is rare and the card has just enough height for it
    # at a slightly tighter row. Compressing the row on those few cards is
    # invisible; running the usage block off the bottom would not be.
    if rh is None:
        rh = 4.8 if len(rows) <= 5 else 4.2
    heads = ["PITCH", "AVG", "MAX", "SPIN", "IVB", "HB", "VAA", "EXT",
             "RELH", "ZN"]
    wts = [1.85, 1.00, 1.00, 1.08, 0.86, 0.86, 0.86, 0.80, 0.88, 0.82]
    tot = sum(wts)
    cols = [w * t / tot for t in wts]
    hh = 5.0
    c.setFillColor(MAROON)
    c.rect(x, top - hh, w, hh, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 3.6)
    cx = x
    for cw, hd in zip(cols, heads):
        if hd == "PITCH":
            c.drawString(cx + 5.5, top - hh + 1.5, hd)
        else:
            c.drawCentredString(cx + cw / 2, top - hh + 1.5, hd)
        cx += cw

    y = top - hh
    for i, r in enumerate(rows):
        y -= rh
        if i % 2 == 1:
            c.setFillColor(TINT)
            c.rect(x, y, w, rh, stroke=0, fill=1)
        c.setFillColor(HexColor(color(r["pt"])))
        c.circle(x + 3.4, y + rh / 2, 1.5, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", fs)
        c.drawString(x + 6.0, y + 1.2, _abbr(r["pt"]))

        def num(v, fmt):
            return "—" if v is None or pd.isna(v) else format(v, fmt)
        vals = [num(r["avg"], ".1f"), num(r["mx"], ".1f"),
                num(r["spin"], ".0f"), num(r["ivb"], ".1f"),
                num(r["hb"], ".1f"), num(r["vaa"], ".1f"),
                num(r["ext"], ".1f"), num(r["relh"], ".1f"),
                "—" if pd.isna(r["zone"]) else f"{r['zone']*100:.0f}"]
        c.setFont("Helvetica", fs)
        cx = x + cols[0]
        for cw, v in zip(cols[1:], vals):
            c.drawCentredString(cx + cw / 2, y + 1.2, v)
            cx += cw
    c.setStrokeColor(IRULE)
    c.setLineWidth(0.3)
    c.rect(x, y, w, top - y, stroke=1, fill=0)
    return y


def _usage_block(c, use, x, top, w):
    """Usage as plain numbers, split by batter hand."""
    lab_w = 26.0
    slot = (w - lab_w) / 4
    rh = 4.9

    c.setFillColor(MAROON)
    c.setFont("Helvetica-Bold", 4.3)
    c.drawString(x, top - 3.4, "USAGE")
    c.setFont("Helvetica-Bold", 3.6)
    for i, g in enumerate(advanced.GROUP_ORDER):
        c.setFillColor(HexColor(advanced.GROUP_COLOR[g]))
        c.drawCentredString(x + lab_w + i * slot + slot / 2, top - 3.4, g)

    y = top - 3.4
    for situ, tone in (("vs RHH", RHH_RED), ("vs LHH", LHH_BLUE)):
        y -= rh
        c.setFillColor(tone)
        c.setFont("Helvetica-Bold", 4.3)
        c.drawString(x, y, situ)
        c.setFillColor(INK)
        c.setFont("Helvetica", 4.3)
        for i, g in enumerate(advanced.GROUP_ORDER):
            v = use.loc[situ, g] if (not use.empty and situ in use.index) \
                else None
            txt = "—" if v is None or not pd.notna(v) else f"{v*100:.0f}%"
            c.drawCentredString(x + lab_w + i * slot + slot / 2, y, txt)
    return y


def _stat_line(stat):
    parts = []
    for k, lab in staffstats.FIELDS:
        v = stat.get(k)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        txt = str(v).strip()
        if txt and txt.lower() != "nan":
            parts.append(f"{lab} {txt}")
    return "   ".join(parts)


def _staff_card(c, x, y, w, h, name, sub, stat, tmp, tag):
    """Tables on the left, shape and damage on the right."""
    from .reports import _mini_plot
    prof = classify(sub)
    c.setStrokeColor(IRULE)
    c.setLineWidth(0.5)
    c.rect(x, y, w, h, stroke=1, fill=0)

    nb = 8.0
    fill, txt = PROFILE[prof]
    c.setFillColor(HexColor(fill))
    c.rect(x, y + h - nb, w, nb, stroke=0, fill=1)
    c.setFillColor(txt)
    c.setFont("Helvetica-Bold", 5.5)
    c.drawCentredString(x + w / 2, y + h - nb + 2.3,
                        f"{split_name(name)} - {hand(sub['throws'].iloc[0])}")

    top = y + h - nb
    c.setFillColor(HexColor("#4a4a4a"))
    c.setFont("Helvetica", 4.3)
    c.drawCentredString(x + w / 2, top - 4.6, _stat_line(stat))
    top -= 6.6

    left_w = 150.0
    gap = 4.0
    tbl_bot = _staff_metrics(c, _card_rows(advanced.metrics_table(sub)),
                             x + 2, top, left_w)
    use_bot = _usage_block(c, advanced.usage(sub), x + 2, tbl_bot - 2.0,
                           left_w)

    # movement plot and the two damage maps, right of the tables
    rx = x + 2 + left_w + gap
    rw = x + w - 2 - rx
    pgap = 2.0
    pw = (rw - 2 * pgap) / 3

    # Labels are set here rather than as chart titles: scaled down to panel
    # width, a ten-character matplotlib title would be unreadable.
    lab_h = 5.4
    p_top = top - lab_h
    avail = p_top - (y + 2.0)

    mp = os.path.join(tmp, f"{tag}_mv.png")
    _mini_plot(sub, mp)
    imgs = [(mp, None)] + [(os.path.join(tmp, f"{tag}_d{hh}.png"), hh)
                           for hh in ("L", "R")]
    for img, hnd in imgs:
        if hnd is not None:
            panels.heat_map(advanced.damage(sub, hnd), img, "", size=1.5)
            c.setFillColor(LHH_BLUE if hnd == "L" else RHH_RED)
            c.setFont("Helvetica-Bold", 4.2)
            c.drawCentredString(rx + pw / 2, top - 3.8, f"{hnd}HH Damage")
        ir = ImageReader(img)
        iw, ih = ir.getSize()
        wd, ht = pw, pw * (ih / iw)
        if ht > avail:
            ht, wd = avail, avail * (iw / ih)
        c.drawImage(ir, rx + (pw - wd) / 2, p_top - ht, width=wd, height=ht,
                    mask="auto")
        rx += pw + pgap
    # How much room was left under the lowest thing on the card. Negative
    # means the tables ran past the bottom edge; the tests watch this.
    return use_bot - y


def _profile_key(c, x, y):
    """Stock / North-South / East-West swatches, gold type on the maroon bar."""
    c.setFont("Helvetica-Bold", 5.8)
    items = [(k, c.stringWidth(k, "Helvetica-Bold", 5.8) + 19) for k in PROFILE]
    cx = x - sum(w for _, w in items)
    for label, wdt in items:
        c.setFillColor(HexColor(PROFILE[label][0]))
        c.roundRect(cx, y - 1.4, 9.5, 8, 1.4, stroke=0, fill=1)
        c.setFillColor(GOLD)
        c.drawString(cx + 13, y + 1, label)
        cx += wdt


def build_staff_expanded(df, stats=None, logo=DEFAULT_LOGO,
                         title="Pitching Staff") -> bytes:
    """Portrait staff sheet, folded once down the middle.

    Pitchers run from most innings to fewest, filled left to right across the
    fold (1 2 / 3 4 / 5 6), so the arms that matter are along the top."""
    stats = stats or {}
    names = sorted(df["pitcher"].unique(),
                   key=lambda n: (-ip_value(stats.get(n, {}).get("ip")), n))
    per = SCOLS * SROWS
    cw = (SPW - 2 * SM - (SCOLS - 1) * SGX) / SCOLS
    grid_top = SPH - SHEAD - SGAP
    ch = (grid_top - SM - SFOOT - (SROWS - 1) * SGY) / SROWS

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle(title)
    with tempfile.TemporaryDirectory() as tmp:
        overflow = []
        pages = [names[i:i + per] for i in range(0, len(names), per)] or [[]]
        for pg, chunk in enumerate(pages):
            c.setFillColor(MAROON)
            c.rect(0, SPH - SHEAD, SPW, SHEAD, stroke=0, fill=1)
            c.setFillColor(GOLD)
            c.rect(0, SPH - SHEAD - 3, SPW, 3, stroke=0, fill=1)
            img = ImageReader(logo)
            iw, ih = img.getSize()
            lh = 28.0
            c.drawImage(img, 14, SPH - SHEAD / 2 - lh / 2,
                        width=lh * (iw / ih), height=lh, mask="auto",
                        preserveAspectRatio=True)
            c.setFillColor(GOLD)
            c.setFont("Helvetica-Bold", 13)
            lab = title if len(pages) == 1 else f"{title} ({pg+1}/{len(pages)})"
            c.drawString(48, SPH - SHEAD / 2 - 4.5, lab)
            _profile_key(c, SPW - SM, SPH - SHEAD / 2 - 3)

            for i, nm in enumerate(chunk):
                # Row-major: 1 2 / 3 4 / 5 6, so the two highest-innings arms
                # sit side by side at the top and the eye reads across, not
                # down one folded face and back up the other.
                r, col = divmod(i, SCOLS)
                x = SM + col * (cw + SGX)
                yy = grid_top - (r + 1) * ch - r * SGY
                slack = _staff_card(c, x, yy, cw, ch, nm,
                                    df[df["pitcher"] == nm],
                                    stats.get(nm, {}), tmp, f"{pg}_{i}")
                if slack is not None and slack < 0:
                    overflow.append((nm, round(slack, 2)))

            # the single crease, sitting in the gutter
            c.setStrokeColor(HexColor("#cfcfcf"))
            c.setLineWidth(0.4)
            c.setDash(1.5, 3)
            c.line(SPW / 2, SM - 6, SPW / 2, SPH - SHEAD - 2)
            c.setDash()

            # Nothing in the footer: the usage block on each card names
            # FB/BB/CH/CUT in their own colours and every metrics row carries
            # a coloured dot, so a key down here would only repeat them.
            c.showPage()
    c.save()
    return buf.getvalue()
