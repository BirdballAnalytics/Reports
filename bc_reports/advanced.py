"""Advanced scouting analytics derived from pitch-level TruMedia exports.

Everything here is computed from the pitch file. Season counting stats come
from the separate stats export (see staffstats.py) because they are official.

Zone geometry: TruMedia's x/y are normalised to the strike zone, not feet
off the plate. The box below was fitted against the InZone% column that
TruMedia publishes in its season export -- it reproduces their own figure to
within 0.2 percentage points on average, so a per-pitch InZone% computed here
agrees with the official season number rather than competing with it.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

# The zone geometry lives with the coordinate handling, in schema.py, so the
# box drawn on the panels and the box used to rescale a feet-based export can
# never drift apart. Re-exported here because panels.py and the sheets have
# always imported it from this module.
from .schema import ZONE_X, ZONE_Y  # noqa: F401

# The four groups the staff scouts by. Cutter stands alone rather than
# folding into the fastballs.
GROUPS = {
    # keys are matched case-insensitively against both the raw vendor
    # spelling and the canonical name schema.normalize() produces
    "fastball": "FB", "four-seam": "FB", "fourseam": "FB", "sinker": "FB",
    "two-seam": "FB", "twoseam": "FB",
    "slider": "BB", "curveball": "BB", "sweeper": "BB", "slurve": "BB",
    "knuckle curve": "BB", "curve": "BB",
    "changeup": "CH", "change-up": "CH", "splitter": "CH",
    "split-finger": "CH", "screwball": "CH", "forkball": "CH",
    "cutter": "CUT",
}
GROUP_ORDER = ["FB", "BB", "CH", "CUT"]
GROUP_LABEL = {"FB": "Fastballs", "BB": "Breaking", "CH": "Changeups",
               "CUT": "Cutters"}
GROUP_COLOR = {"FB": "#D22D49", "BB": "#00D1ED", "CH": "#1DBE3A",
               "CUT": "#933F2C"}
HEAT_TITLE = {"FB": "FASTBALL", "BB": "BREAKING BALL", "CH": "CHANGEUP",
              "CUT": "CUTTER"}

HARD_HIT = 95.0
# No minimum: every pitch a man threw shows up, down to a single one. A map
# built from one or two pitches is a couple of dots rather than a tendency,
# which is exactly what it should look like.
MIN_HEATMAP = 1

ON_BASE = re.compile(r"^(Single|Walk|Intentional Walk|Hit By Pitch|"
                     r"Reached on Error|Fielder)")
ADVANCE = re.compile(r"([B123])-([123H])")
RBI_TAG = re.compile(r"\((\d?)RBI\)")


# ------------------------------------------------------------------ basics
def group_of(pitch_type) -> str | None:
    return GROUPS.get(str(pitch_type).strip().lower())


def in_zone(df: pd.DataFrame) -> pd.Series:
    return df["plate_x"].abs().le(ZONE_X) & df["plate_z"].abs().le(ZONE_Y)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Add the derived columns the rest of this module depends on."""
    d = df.copy()
    d["grp"] = d["pitch_type"].map(group_of)
    d["inzone"] = in_zone(d)
    if "count" in d.columns:
        d["two_k"] = d["count"].astype(str).str.strip().str.endswith("-2")
    else:
        d["two_k"] = False
    return d


# ------------------------------------------------------------- base state
def _bases_reached(result: str) -> int:
    r = str(result)
    if ON_BASE.match(r):
        return 1
    if r.startswith("Double on"):
        return 2
    if r.startswith("Triple"):
        return 3
    if "Home Run" in r:
        return 4
    return 0


def add_risp(df: pd.DataFrame) -> pd.DataFrame:
    """Flag each pitch with whether a runner stood on 2nd or 3rd.

    TruMedia exports carry no baserunner column, so base state is rebuilt by
    walking each half-inning and applying the advancement notation in the
    play description ("W.2-3;1-2"). Validated against RBI notation: of 229
    scoring plays in the reference season only one had fewer runners on base
    than the RBI count required.

    It cannot see steals, pickoffs or wild pitches, which move runners
    without ending a plate appearance, so treat it as close rather than
    exact.
    """
    from . import derived

    d = df.copy()
    d["risp"] = False
    if "inning" not in d.columns:
        return d
    vocab = derived.vocabulary(d)
    if vocab == "trumedia" and "play_desc" not in d.columns:
        return d

    keys = [k for k in ("game_id", "date", "inning", "half") if k in d.columns]
    if not keys:
        return d
    order = keys + (["ab_num"] if "ab_num" in d.columns else [])
    d = d.sort_values(order, kind="stable")

    risp = pd.Series(False, index=d.index)
    for _, half in d.groupby(keys, sort=False, dropna=False):
        bases = {1: False, 2: False, 3: False}
        pa_key = ("ab_num" if "ab_num" in half.columns
                  else ("play_desc" if vocab == "trumedia" else "pitch_of_pa"))
        for _, pa in half.groupby(pa_key, sort=False, dropna=False):
            risp.loc[pa.index] = bases[2] or bases[3]
            # Only the pitch that ENDED the plate appearance carries the
            # outcome. Every other pitch in the PA has a per-pitch result
            # ("Ball", "Foul"), so read the terminal row.
            ends = derived.pa_ends(pa, vocab)
            if ends.empty:
                continue
            last = ends.iloc[-1]
            desc = str(last.get("play_desc") or "")
            if desc and desc.lower() != "nan":
                # TruMedia spells out where every runner went.
                for frm, to in ADVANCE.findall(desc):
                    if frm != "B" and bases.get(int(frm)):
                        bases[int(frm)] = False
                    if to != "H":
                        bases[int(to)] = True
                if _bases_reached(last["play_result"]) in (1, 2, 3):
                    bases[_bases_reached(last["play_result"])] = True
                continue
            # TrackMan gives the outcome but not the baserunning, so runners
            # are moved on the standard assumption: everyone advances by as
            # many bases as the batter took, and a walk pushes only forced
            # runners. It misses steals and extra bases taken, so treat
            # TrackMan RISP as close rather than exact.
            kind = derived.classify(last, vocab)[0]
            adv = {"1B": 1, "2B": 2, "3B": 3, "HR": 4, "ERR": 1}.get(kind, 0)
            if kind in ("BB", "HBP"):
                if bases[1] and bases[2] and not bases[3]:
                    bases[3] = True
                if bases[1] and not bases[2]:
                    bases[2] = True
                bases[1] = True
            elif adv:
                nb = {1: False, 2: False, 3: False}
                for b in (3, 2, 1):
                    if bases[b] and b + adv <= 3:
                        nb[b + adv] = True
                if adv <= 3:
                    nb[adv] = True
                bases = nb
    d["risp"] = risp
    return d


# ----------------------------------------------------------------- splits
def hand_splits(df: pd.DataFrame) -> pd.DataFrame:
    """AVG / OBP / OPS and counting stats against each batter hand.

    One row per plate appearance, taken from the pitch that ended it. Which
    pitch that is, and what the outcome was, is read through the shared
    classifier so a TrackMan export -- which splits the result across KorBB,
    PitchCall and PlayResult -- produces the same table as a TruMedia one.
    """
    from . import derived

    vocab = derived.vocabulary(df)
    pa = derived.pa_ends(df, vocab)
    if pa.empty:
        return pd.DataFrame()
    kinds = pd.Series([derived.classify(r, vocab)[0] for _, r in pa.iterrows()],
                      index=pa.index)
    sacs = pa["play_result"].fillna("").astype(str).str.startswith("Sac")

    rows = []
    for hand in ("R", "L", "ALL"):
        mask = slice(None) if hand == "ALL" else (pa["bat_hand"] == hand)
        g = pa if hand == "ALL" else pa[mask]
        if g.empty:
            continue
        k_g = kinds if hand == "ALL" else kinds[mask]
        single = int((k_g == "1B").sum())
        dbl = int((k_g == "2B").sum())
        tpl = int((k_g == "3B").sum())
        hr = int((k_g == "HR").sum())
        hits = single + dbl + tpl + hr
        bb = int((k_g == "BB").sum())
        hbp = int((k_g == "HBP").sum())
        k = int((k_g == "K").sum())
        sac = int((sacs if hand == "ALL" else sacs[mask]).sum())
        pa_n = len(g)
        ab = pa_n - bb - hbp - sac
        tb = single + 2 * dbl + 3 * tpl + 4 * hr
        avg = hits / ab if ab else np.nan
        obp = (hits + bb + hbp) / (ab + bb + hbp + sac) if (ab + bb + hbp + sac) else np.nan
        slg = tb / ab if ab else np.nan
        rows.append({
            "hand": hand, "PA": pa_n, "AVG": avg, "OBP": obp,
            "OPS": (obp + slg) if pd.notna(obp) and pd.notna(slg) else np.nan,
            "H": hits, "2B": dbl, "3B": tpl, "HR": hr,
            "K%": k / pa_n if pa_n else np.nan,
            "BB%": bb / pa_n if pa_n else np.nan,
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ usage
def usage(df: pd.DataFrame) -> pd.DataFrame:
    """Share of pitches by group across the four scouting situations."""
    d = df[df["grp"].notna()]
    if d.empty:
        return pd.DataFrame()

    slices = {
        "Total": d,
        "vs RHH": d[d["bat_hand"] == "R"],
        "vs LHH": d[d["bat_hand"] == "L"],
        "2K": d[d["two_k"]],
        "RISP": d[d["risp"]] if "risp" in d.columns else d.iloc[0:0],
    }
    out = {}
    for label, sub in slices.items():
        if sub.empty:
            out[label] = {g: np.nan for g in GROUP_ORDER}
            out[label]["n"] = 0
            continue
        share = sub["grp"].value_counts(normalize=True)
        out[label] = {g: float(share.get(g, 0.0)) for g in GROUP_ORDER}
        out[label]["n"] = len(sub)
    return pd.DataFrame(out).T[GROUP_ORDER + ["n"]]


# -------------------------------------------------------------- pitch line
def metrics_table(df: pd.DataFrame) -> list:
    """Per-pitch-type averages, including the four new columns."""
    from .reports import pitch_rank

    rows = []
    for pt, g in df.groupby("pitch_type"):
        if str(pt).strip() in ("", "nan", "None"):
            continue
        rows.append({
            "pt": pt, "n": len(g),
            "avg": g["velo"].mean(), "mx": g["velo"].max(),
            "spin": g["spin"].mean(),
            "ivb": g["ivb"].mean(), "hb": g["hb"].mean(),
            "vaa": g["vaa"].mean() if "vaa" in g else np.nan,
            "ext": g["ext"].mean() if "ext" in g else np.nan,
            "relh": g["rel_h"].mean() if "rel_h" in g else np.nan,
            "zone": g["inzone"].mean() if "inzone" in g else np.nan,
        })
    return sorted(rows, key=lambda r: pitch_rank(r["pt"]))


# --------------------------------------------------------------- heat maps
def heat_panels(df: pd.DataFrame, min_n: int = MIN_HEATMAP) -> list:
    """(group, hand, frame) for all four groups against each hand.

    The grid is fixed so every sheet reads the same way. A group the pitcher
    does not throw comes back empty and draws as a blank zone.
    """
    out = []
    d = df.dropna(subset=["plate_x", "plate_z"])
    for hand in ("R", "L"):
        for g in GROUP_ORDER:
            sub = d[(d["bat_hand"] == hand) & (d["grp"] == g)]
            out.append((g, hand, sub if len(sub) >= min_n else sub.iloc[0:0]))
    return out


def damage(df: pd.DataFrame, hand: str, thresh: float = HARD_HIT):
    """95+ mph batted balls against one batter hand."""
    d = df.dropna(subset=["plate_x", "plate_z"])
    if "exit_velo" not in d.columns:
        return d.iloc[0:0]
    return d[(d["bat_hand"] == hand) & (d["exit_velo"] >= thresh)]
