"""Post-series hitter feedback form.

Rendered as a second page behind each hitter's game report, with real
fillable PDF fields so it can be completed on a laptop or tablet rather than
printed. Player, date and opponent arrive pre-filled from the game data and
stay editable.
"""
from __future__ import annotations

import pandas as pd
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfdoc import PDFtrue

PW, PH = letter
MARGIN = 32

MAROON = HexColor("#8c2232")
GOLD = HexColor("#dbcca6")
INK = HexColor("#1f1f1f")
SOFT = HexColor("#6b6b6b")
RULE = HexColor("#d8d2c4")
TINT = HexColor("#f6f2e9")
BAND = HexColor("#efe9dc")
FIELD_BORDER = HexColor("#c9b98f")

LEGEND = [("Yes*", "#7bc47f"), ("Partially", "#f2d06b"), ("No*", "#e8797f"),
          ("Unsure", "#8fb8dd"), ("No opportunity", "#c9c9c9")]
CHOICES = ["Select", "Yes*", "Partially", "No*", "Unsure", "No opportunity"]

# Column widths: assessment narrows because the evidence box is gone, and
# that width goes to the feedback column.
W_AREA, W_ASSESS, W_FEED = 216.0, 104.0, 228.0

ROWS = [
    ("PRE-2K APPROACH",
     "Did I have a clear plan/approach and commit to it?"),
    ("2K APPROACH",
     "Did I transition mentally and physically to our 2K approach? "
     "Did I fully commit to putting the ball in play?"),
    ("SWING DECISIONS",
     "Did I hunt appropriate pitches that fit my strengths and my "
     "plan/approach?"),
    ("CHASE",
     "Did I chase specific pitches outside the strike zone? If yes, what "
     "pitches and locations?"),
    ("TIMING",
     "Was I consistently on time, early, or late?"),
    ("BAT TO BALL",
     "Did I consistently barrel the baseball when I chose to swing at "
     "strikes? If not, was I mostly under or over the ball? Was I jammed "
     "or off the end of the bat?"),
    ("PREPARATION",
     "Did I execute my pre at-bat routine properly to prepare myself fully?"),
    ("MECHANICS",
     "How does your swing feel? Were there sequencing, movement pattern, "
     "bat path, etc. concerns?"),
    ("MINDSET",
     "Did I compete one pitch at a time with full conviction and "
     "confidence?"),
    ("SITUATIONAL EXECUTION",
     "3 < 2, bunts, 2K. Did I do my job?"),
]
OVERALL = ("OVERALL",
           "What do you want to focus on in practice this week? What changes "
           "do you want to make (if any)?")

DEV_ROWS = ["PRIMARY FOCUS", "SECONDARY FOCUS", "PRACTICE PLAN / DRILL WORK"]


def wrap(c, text, width, font="Helvetica", size=7.6):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if c.stringWidth(trial, font, size) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def opponent_of(sub: pd.DataFrame) -> str:
    """The team whose pitchers this hitter faced."""
    for col in ("pitcher_team", "home_team", "away_team"):
        if col in sub.columns:
            vals = sub[col].dropna()
            if len(vals):
                if col == "pitcher_team":
                    return str(vals.mode().iloc[0])
                break
    home = sub["home_team"].dropna() if "home_team" in sub else pd.Series([])
    away = sub["away_team"].dropna() if "away_team" in sub else pd.Series([])
    bat = sub["batter_team"].dropna() if "batter_team" in sub else pd.Series([])
    if len(bat) and len(home) and len(away):
        return str(away.iloc[0]) if str(bat.iloc[0]) == str(home.iloc[0]) \
            else str(home.iloc[0])
    if len(home):
        return str(home.iloc[0])
    return ""


def _field_box(c, x, y, w, h):
    c.setStrokeColor(FIELD_BORDER)
    c.setLineWidth(0.7)
    c.rect(x, y, w, h, stroke=1, fill=0)


def draw_feedback_page(c, batter: str, sub: pd.DataFrame, idx: int,
                       team: str = "BOSTON COLLEGE BASEBALL"):
    form = c.acroForm
    # ReportLab never sets this. Without it a viewer may keep showing the
    # old value after a selection, and programmatic fills show nothing at
    # all, because the cached appearance stream is never regenerated.
    form.extras["NeedAppearances"] = PDFtrue
    tag = f"p{idx}"

    # ---- header -----------------------------------------------------
    bar_h, gold_h = 44.0, 5.0
    top = PH - 20
    c.setFillColor(MAROON)
    c.rect(MARGIN, top - bar_h, PW - 2 * MARGIN, bar_h, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.rect(MARGIN, top - bar_h - gold_h, PW - 2 * MARGIN, gold_h,
           stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 19)
    c.drawString(MARGIN + 14, top - 25, "POST SERIES HITTER FEEDBACK")
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 8.2)
    c.drawString(MARGIN + 14, top - 37, team.upper())

    y = top - bar_h - gold_h - 20

    # ---- player / date / opponent (pre-filled, still editable) -------
    when = ""
    if "date" in sub.columns:
        d = sub["date"].dropna()
        if len(d):
            when = pd.Timestamp(d.iloc[0]).strftime("%m/%d/%Y")
    prefill = [("PLAYER", batter, 3.0), ("DATE", when, 1.4),
               ("OPPONENT", opponent_of(sub), 2.2)]
    gap, pad = 16.0, 8.0
    labels_w = sum(c.stringWidth(l, "Helvetica-Bold", 8) + pad
                   for l, _, _ in prefill)
    free = (PW - 2 * MARGIN) - labels_w - gap * (len(prefill) - 1)
    share = sum(w for _, _, w in prefill)
    x = MARGIN
    for label, value, weight in prefill:
        c.setFillColor(MAROON)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x, y - 10, label)
        fx = x + c.stringWidth(label, "Helvetica-Bold", 8) + pad
        fw = free * weight / share
        form.textfield(name=f"{tag}_{label.lower()}", value=value,
                       x=fx, y=y - 15, width=fw, height=17,
                       borderColor=FIELD_BORDER, fillColor=white,
                       textColor=INK, borderWidth=0.7, fontSize=8.5,
                       fontName="Helvetica", forceBorder=True)
        x = fx + fw + gap
    y -= 26

    # ---- legend -----------------------------------------------------
    x = MARGIN
    for label, col in LEGEND:
        c.setFillColor(HexColor(col))
        c.rect(x, y - 9, 10, 9, stroke=0, fill=1)
        c.setFillColor(SOFT)
        c.setFont("Helvetica", 7.2)
        c.drawString(x + 14, y - 7, label)
        x += 14 + c.stringWidth(label, "Helvetica", 7.2) + 22
    y -= 18

    # ---- table ------------------------------------------------------
    cols = [W_AREA, W_ASSESS, W_FEED]
    tw = sum(cols)
    hh = 20.0
    c.setFillColor(MAROON)
    c.rect(MARGIN, y - hh, tw, hh, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 8.4)
    for cx, head in zip(
            [MARGIN + 8, MARGIN + cols[0] + 8, MARGIN + cols[0] + cols[1] + 8],
            ["AREA TO REVIEW", "ASSESSMENT", "HITTERS FEEDBACK"]):
        c.drawString(cx, y - hh + 6.5, head)
    y -= hh

    def area_cell(title, desc, ry, rh, shade):
        if shade:
            c.setFillColor(TINT)
            c.rect(MARGIN, ry, tw, rh, stroke=0, fill=1)
        c.setStrokeColor(RULE)
        c.setLineWidth(0.5)
        c.rect(MARGIN, ry, tw, rh, stroke=1, fill=0)
        c.line(MARGIN + cols[0], ry, MARGIN + cols[0], ry + rh)
        c.setFillColor(MAROON)
        c.setFont("Helvetica-Bold", 8.2)
        c.drawString(MARGIN + 8, ry + rh - 12, title)
        c.setFillColor(HexColor("#3d3d3d"))
        c.setFont("Helvetica", 7.6)
        ty = ry + rh - 23
        for line in wrap(c, desc, cols[0] - 16):
            c.drawString(MARGIN + 8, ty, line)
            ty -= 8.6

    for i, (title, desc) in enumerate(ROWS):
        lines = len(wrap(c, desc, cols[0] - 16))
        rh = 11 + lines * 8.6 + 11
        y -= rh
        area_cell(title, desc, y, rh, i % 2 == 0)
        # assessment dropdown, vertically centred
        form.choice(name=f"{tag}_assess_{i}", value="Select", options=CHOICES,
                    x=MARGIN + cols[0] + 8, y=y + rh / 2 - 8,
                    width=cols[1] - 16, height=16,
                    borderColor=FIELD_BORDER, fillColor=white, textColor=INK,
                    borderWidth=0.7, fontSize=8, fontName="Helvetica",
                    forceBorder=True)
        fx = MARGIN + cols[0] + cols[1] + 8
        form.textfield(name=f"{tag}_feed_{i}", value="",
                       x=fx, y=y + 6, width=cols[2] - 16, height=rh - 12,
                       borderColor=FIELD_BORDER, fillColor=white,
                       textColor=INK, borderWidth=0.7, fontSize=8,
                       fontName="Helvetica", forceBorder=True,
                       fieldFlags="multiline")

    # OVERALL spans assessment + feedback
    title, desc = OVERALL
    lines = len(wrap(c, desc, cols[0] - 16))
    rh = 11 + lines * 8.6 + 20
    y -= rh
    area_cell(title, desc, y, rh, len(ROWS) % 2 == 0)
    form.textfield(name=f"{tag}_overall", value="",
                   x=MARGIN + cols[0] + 8, y=y + 6,
                   width=cols[1] + cols[2] - 16, height=rh - 12,
                   borderColor=FIELD_BORDER, fillColor=white, textColor=INK,
                   borderWidth=0.7, fontSize=8, fontName="Helvetica",
                   forceBorder=True, fieldFlags="multiline")
    # ---- additional comments ---------------------------------------
    y -= 22
    c.setFillColor(MAROON)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(MARGIN, y, "ADDITIONAL COMMENTS")
    y -= 6
    form.textfield(name=f"{tag}_comments", value="", x=MARGIN, y=y - 34,
                   width=tw, height=34, borderColor=FIELD_BORDER,
                   fillColor=white, textColor=INK, borderWidth=0.7,
                   fontSize=8, fontName="Helvetica", forceBorder=True,
                   fieldFlags="multiline")
    y -= 34

    # ---- development plan ------------------------------------------
    y -= 22
    c.setFillColor(MAROON)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, y, "DEVELOPMENT PLAN")
    y -= 8
    label_w = 150.0
    for j, label in enumerate(DEV_ROWS):
        y -= 24
        c.setFillColor(MAROON)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(MARGIN, y + 6, label)
        form.textfield(name=f"{tag}_dev_{j}", value="",
                       x=MARGIN + label_w, y=y, width=tw - label_w, height=19,
                       borderColor=FIELD_BORDER, fillColor=white,
                       textColor=INK, borderWidth=0.7, fontSize=8.5,
                       fontName="Helvetica", forceBorder=True)
    return y
