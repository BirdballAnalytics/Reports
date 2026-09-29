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

# ReportLab defaults every text field to maxlen=100, which writes /MaxLen 100
# into the PDF. Viewers then show a character counter beside the box and stop
# accepting input at a hundred characters -- about two sentences, in a field
# meant to hold a week's worth of feedback. Passing a falsy value makes
# ReportLab omit /MaxLen altogether, which is what an open-ended box needs.
NO_LIMIT = 0

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


def form_safe(text) -> str:
    """Make a string safe to put inside an AcroForm field.

    ReportLab escapes form values against a Latin-1 table and raises a bare
    KeyError on anything outside it -- an en dash in a date range is enough
    to do it. Drawn text has no such problem, so this applies only to field
    values: typographic punctuation is folded to ASCII and anything still
    unmappable is dropped rather than bringing the build down.
    """
    s = str(text or "")
    for bad, good in (("–", "-"), ("—", "-"), ("−", "-"),
                      ("‘", "'"), ("’", "'"), ("“", '"'),
                      ("”", '"'), ("…", "..."), ("·", "-")):
        s = s.replace(bad, good)
    return s.encode("latin-1", "ignore").decode("latin-1")


def _field_box(c, x, y, w, h):
    c.setStrokeColor(FIELD_BORDER)
    c.setLineWidth(0.7)
    c.rect(x, y, w, h, stroke=1, fill=0)


def _pa_block(c, sub, x, top, w):
    """The plate-appearance log, at the top of the feedback page.

    It sits here rather than on the chart page because it is the thing a
    coach reads alongside the hitter while filling the form in, and because
    at full width nothing has to be truncated -- the old half-width version
    collapsed everything past the eighth at-bat into a "+3 more" row.
    """
    from . import hitting

    rows = hitting.pa_table(hitting.summarize(sub)) if len(sub) else []
    c.setFillColor(MAROON)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(x, top, "PLATE APPEARANCES")
    y = top - 6
    if not rows:
        c.setFillColor(SOFT)
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(x, y - 12, "No plate appearances in this range.")
        return y - 20
    weights = [26, 78, 24, 20, 62, 34, 30, 34]
    widths = [wt * w / sum(weights) for wt in weights]
    # Whatever is left once the feedback box and the development plan have
    # been kept back. A fortnight of at-bats will not fit at a readable row
    # height, so past that the tail collapses into one line rather than
    # running off the bottom of the page.
    min_rh, floor = 10.5, MARGIN + 270.0
    room = max(top - 6 - 19 - floor, min_rh)
    max_rows = max(int(room // min_rh), 1)
    if len(rows) > max_rows:
        extra = len(rows) - (max_rows - 1)
        rows = rows[:max_rows - 1] + [[f"+{extra} more", "", "", "", "",
                                       "", "", ""]]
    rh = min(15.0, max(min_rh, room / max(len(rows), 1)))
    hitting._draw_table(
        c, ["Inn", "Pitcher", "Thr", "P", "Result", "EV", "LA", "Dist"],
        rows, widths, x, y, align_first_left=False, rh=rh, hh=19)
    return y - 19 - rh * len(rows)


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
    c.drawString(MARGIN + 14, top - 25, "WEEKLY HITTER FEEDBACK")
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 8.2)
    c.drawString(MARGIN + 14, top - 37, team.upper())

    y = top - bar_h - gold_h - 20

    # ---- player / date / opponent (pre-filled, still editable) -------
    # The date field carries the whole span the report covers, and the
    # opponent field every team faced in it -- a week is rarely one of each.
    from .schema import date_span, opponent_label
    when = date_span(sub)
    prefill = [("PLAYER", batter, 3.0), ("DATES", when, 2.0),
               ("OPPONENTS", opponent_label(sub) or opponent_of(sub), 2.4)]
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
        form.textfield(name=f"{tag}_{label.lower()}", value=form_safe(value),
                       x=fx, y=y - 15, width=fw, height=17,
                       borderColor=FIELD_BORDER, fillColor=white,
                       textColor=INK, borderWidth=0.7, fontSize=8.5,
                       fontName="Helvetica", forceBorder=True,
                       maxlen=NO_LIMIT)
        x = fx + fw + gap
    y -= 26

    y -= 6

    # ---- plate appearances ------------------------------------------
    # The ten-row self-assessment table and its colour legend used to live
    # here. They came out at the coaches' request; what the page is for now
    # is the log, one block of coach feedback and the plan that follows.
    y = _pa_block(c, sub, MARGIN, y, PW - 2 * MARGIN)

    # ---- coach feedback ---------------------------------------------
    tw = PW - 2 * MARGIN
    y -= 26
    c.setFillColor(MAROON)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, y, "COACH FEEDBACK")
    y -= 6
    # Given the room the stripped page leaves, this is now the main writing
    # space rather than an afterthought under a table.
    box_h = max(90.0, y - MARGIN - 150.0)
    form.textfield(name=f"{tag}_comments", value="", x=MARGIN, y=y - box_h,
                   width=tw, height=box_h, borderColor=FIELD_BORDER,
                   fillColor=white, textColor=INK, borderWidth=0.7,
                   fontSize=9, fontName="Helvetica", forceBorder=True,
                   fieldFlags="multiline", maxlen=NO_LIMIT)
    y -= box_h

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
                       fontName="Helvetica", forceBorder=True,
                       maxlen=NO_LIMIT)
    return y
