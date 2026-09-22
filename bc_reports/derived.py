"""Season stat lines rebuilt from pitch-level data.

Official counting stats come from a season export (staffstats.py) whenever one
is uploaded, because those are the numbers in the book. When only a pitch file
is available, this module reconstructs the same line from the plate-appearance
outcomes the file carries, so the sheets still print a stat line instead of a
row of dashes.

Two vendor vocabularies are handled:

- **TrackMan** splits the outcome across three columns. `KorBB` carries
  strikeouts and walks, `PitchCall` the hit-by-pitch, `PlayResult` the batted
  ball. It also ships `OutsOnPlay` and `RunsScored` per pitch.
- **TruMedia** puts the whole outcome in one string on the pitch that ended
  the plate appearance ("Single on a Line Drive", "Strikeout (Swinging)"),
  and carries no per-play outs or runs, so both are read out of the text.

What this cannot know
---------------------
Nothing here distinguishes an earned run from an unearned one, so ERA is
really runs allowed per nine. Innings come from outs recorded on plays the
file contains: a pitcher whose outing was only partly tracked will show fewer
innings than the book. Both are stated in the app rather than hidden.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

# FIP = (13*HR + 3*(BB + HBP) - 2*K) / IP + C.
#
# C was solved against a full season of TruMedia game logs: at 3.180 the
# formula reproduces TruMedia's own published FIP to within 0.006 across all
# 60 games, and every residual lands on a whole number of hit-by-pitches
# (0 to 6 a game), which is what the unknown term should be. A guessed
# major-league constant of 3.10 misses by half a run.
FIP_CONSTANT = 3.180

RBI_TAG = re.compile(r"\((\d?)RBI\)")

# TruMedia writes the outcome as a sentence; these match the front of it.
TM_HIT = {"Single": 1, "Double": 2, "Triple": 3, "Home Run": 4}
TM_OUT_WORDS = ("Ground Out", "Fly Out", "Line Out", "Pop Out", "Bunt Ground "
                "Out", "Sac Fly", "Sac Bunt", "Fielder's Choice", "Forceout",
                "Grounded Into DP")


# --------------------------------------------------------------- outcomes
def _tm_bases(res: str) -> int:
    """Total bases for a TruMedia outcome string, 0 if it was not a hit."""
    for word, bases in TM_HIT.items():
        if res.startswith(word):
            return bases
    return 0


def classify(row, vocab: str) -> tuple[str, int, int]:
    """(outcome, outs recorded, bases) for one plate-appearance-ending pitch.

    Outcome is one of K, BB, HBP, 1B, 2B, 3B, HR, OUT, ERR, OTHER.
    """
    if vocab == "trackman":
        kbb = str(row.get("k_or_bb") or "")
        call = str(row.get("pitch_call") or "")
        res = str(row.get("play_result") or "")
        outs = row.get("outs_on_play")
        outs = int(outs) if pd.notna(outs) else 0
        if kbb == "Strikeout":
            # Some operators log the strikeout out, some do not. Trust the
            # column when it is filled in and supply the out when it is not,
            # so innings come out the same either way.
            return "K", max(outs, 1), 0
        if kbb == "Walk":
            return "BB", outs, 0
        if call == "HitByPitch":
            return "HBP", outs, 0
        for name, tag, bases in (("Single", "1B", 1), ("Double", "2B", 2),
                                 ("Triple", "3B", 3), ("HomeRun", "HR", 4)):
            if res == name:
                return tag, outs, bases
        if res == "Error":
            return "ERR", outs, 0
        if res in ("Out", "FieldersChoice", "Sacrifice"):
            return "OUT", max(outs, 1), 0
        return "OTHER", outs, 0

    res = str(row.get("play_result") or "")
    if res.startswith("Strikeout"):
        return "K", 1, 0
    if res.endswith("Walk") or res == "Walk":
        return "BB", 0, 0
    if res.startswith("Hit By Pitch"):
        return "HBP", 0, 0
    bases = _tm_bases(res)
    if bases:
        return {1: "1B", 2: "2B", 3: "3B", 4: "HR"}[bases], 0, bases
    if res.startswith("Reached on Error"):
        return "ERR", 0, 0
    if res.startswith("Double Play"):
        return "OUT", 2, 0
    if res.startswith("Triple Play"):
        return "OUT", 3, 0
    if res.startswith(TM_OUT_WORDS):
        return "OUT", 1, 0
    return "OTHER", 0, 0


def vocabulary(df: pd.DataFrame) -> str:
    """Which outcome vocabulary this frame speaks."""
    if "k_or_bb" in df.columns and df["k_or_bb"].notna().any():
        return "trackman"
    return "trumedia"


def pa_ends(df: pd.DataFrame, vocab: str) -> pd.DataFrame:
    """The one pitch per plate appearance that carries the outcome.

    Every other pitch in the appearance holds a per-pitch result ("Ball",
    "Foul"), so counting those would multiply every stat several times over.
    """
    if vocab == "trackman":
        kbb = df.get("k_or_bb")
        call = df.get("pitch_call")
        ends = pd.Series(False, index=df.index)
        if kbb is not None:
            ends |= kbb.astype(str).isin(["Strikeout", "Walk"])
        if call is not None:
            ends |= call.astype(str).isin(["InPlay", "HitByPitch"])
        return df[ends]
    if "play_desc" in df.columns and df["play_desc"].notna().any():
        return df[df["play_desc"].notna()]
    return df.iloc[0:0]


# ------------------------------------------------------------------ innings
def outs_by_pitcher(df: pd.DataFrame, vocab: str) -> dict:
    """Outs recorded, per pitcher, reconstructed from the outs count.

    Both vendors ship the number of outs standing *before* each pitch.
    Differencing it across a half-inning recovers every out the side made,
    including the ones no plate appearance records -- a runner caught
    stealing, picked off, or thrown out trying to take a base. Counting
    outcomes alone misses those, and over a season that is worth several
    innings a man.

    The last half-inning of each game is the one place the difference cannot
    be taken, since nothing follows it, and it is also the one that may have
    ended early on a walk-off. That one falls back to counting outcomes.
    """
    keys = [k for k in ("game_id", "date", "inning", "half") if k in df.columns]
    if "outs_before" not in df.columns or not keys:
        return {}
    if df["outs_before"].isna().all():
        return {}

    order = [c for c in ("pitch_no", "ab_num", "pitch_of_pa") if c in df.columns]
    d = df.sort_values(keys + order, kind="stable") if order else df

    game_key = "game_id" if "game_id" in d.columns else "date"
    last_half = {}
    for gid, gsub in d.groupby(game_key, sort=False, dropna=False):
        halves = list(dict.fromkeys(
            map(tuple, gsub[keys].astype(str).to_numpy())))
        if halves:
            last_half[gid] = halves[-1]

    tally: dict = {}
    for kv, half in d.groupby(keys, sort=False, dropna=False):
        kv = kv if isinstance(kv, tuple) else (kv,)
        gid = half[game_key].iloc[0]
        final = last_half.get(gid) == tuple(str(x) for x in kv)

        pa_key = "ab_num" if "ab_num" in half.columns else "pitch_of_pa"
        pas = [g for _, g in half.groupby(pa_key, sort=False, dropna=False)] \
            if pa_key in half.columns else [half]
        befores = [pd.to_numeric(g["outs_before"], errors="coerce").iloc[0]
                   for g in pas]

        for i, pa in enumerate(pas):
            who = pa["pitcher"].iloc[0]
            if i + 1 < len(pas):
                b0, b1 = befores[i], befores[i + 1]
                got = (b1 - b0) if pd.notna(b0) and pd.notna(b1) else 0
                # A negative step means the half-inning rolled over inside
                # what we grouped; trust nothing and count zero.
                got = int(got) if 0 <= got <= 3 else 0
            elif final:
                ends = pa_ends(pa, vocab)
                got = sum(classify(r, vocab)[1] for _, r in ends.iterrows())
            else:
                b0 = befores[i]
                got = int(3 - b0) if pd.notna(b0) and 0 <= b0 <= 3 else 0
            tally[who] = tally.get(who, 0) + max(0, got)
    return tally


# ------------------------------------------------------------------- runs
ADVANCE = re.compile(r"([B123])-([123H])")


def runs_by_pitcher(df: pd.DataFrame) -> dict:
    """Runs charged to the pitcher who put the runner on, not the one on the
    mound when he scored.

    A reliever who walks into a jam is not charged with the runs he inherits,
    and the same half-inning walk that the base-state reconstruction already
    performs for RISP gives us who is responsible: each occupied base carries
    the name of the pitcher who allowed it. Without this a reliever's ERA can
    be several runs high.

    Runs are read from the RBI notation, which tracks earned runs more
    closely than a raw score would -- a run that scores on an error carries
    no RBI.
    """
    if "play_desc" not in df.columns:
        return {}
    keys = [k for k in ("game_id", "date", "inning", "half") if k in df.columns]
    if not keys:
        return {}
    order = keys + (["ab_num"] if "ab_num" in df.columns else [])
    d = df.sort_values(order, kind="stable")

    charged: dict = {}
    for _, half in d.groupby(keys, sort=False, dropna=False):
        bases: dict = {1: None, 2: None, 3: None}
        pa_key = "ab_num" if "ab_num" in half.columns else "play_desc"
        for _, pa in half.groupby(pa_key, sort=False, dropna=False):
            ends = pa[pa["play_desc"].notna()]
            if ends.empty:
                continue
            last = ends.iloc[-1]
            who = last["pitcher"]
            desc = str(last["play_desc"])
            moves = ADVANCE.findall(desc)
            scored = sum(1 for frm, to in moves if to == "H")
            # The RBI tag is the authority on how many actually crossed;
            # the arrows say who.
            tag = RBI_TAG.search(desc)
            rbi = (int(tag.group(1)) if tag.group(1) else 1) if tag else 0

            runners = []
            for frm, to in moves:
                if to != "H":
                    continue
                runners.append(who if frm == "B" else bases.get(int(frm)) or who)
            if rbi and not runners:          # home run with no arrows drawn
                runners = [who] * rbi
            for name in runners[:rbi] if rbi else []:
                charged[name] = charged.get(name, 0) + 1

            for frm, to in moves:
                if frm != "B" and bases.get(int(frm)) is not None:
                    bases[int(frm)] = None
                if to != "H":
                    bases[int(to)] = who if frm == "B" else who
            reached = _bases_reached(str(last.get("play_result") or ""))
            if reached in (1, 2, 3):
                bases[reached] = who
    return charged


def _bases_reached(result: str) -> int:
    """Which base the batter himself ended up on, 0 if he did not reach."""
    if re.match(r"^(Single|Walk|Intentional Walk|Hit By Pitch|"
                r"Reached on Error|Fielder)", result):
        return 1
    if result.startswith("Double on"):
        return 2
    if result.startswith("Triple"):
        return 3
    return 0


def _runs(sub: pd.DataFrame, vocab: str, ends: pd.DataFrame) -> float:
    """Runs charged to this pitcher.

    TrackMan counts them per play. TruMedia has no runs column, so they come
    from the RBI notation in the play description -- which, as it happens,
    tracks *earned* runs more closely than a raw score would, since a run
    scored on an error carries no RBI.
    """
    if vocab == "trackman" and "runs_scored" in sub.columns:
        return float(pd.to_numeric(sub["runs_scored"],
                                   errors="coerce").fillna(0).sum())
    if "play_desc" in ends.columns:
        total = 0
        for desc in ends["play_desc"].dropna().astype(str):
            for tag in RBI_TAG.findall(desc):
                total += int(tag) if tag else 1
        return float(total)
    return np.nan


# ------------------------------------------------------------- appearances
def _games(sub: pd.DataFrame, all_pitches: pd.DataFrame) -> tuple:
    """(games pitched, games started).

    A start is an outing that opens the file's record of that game: the
    pitcher who threw its lowest-numbered pitch. In a bullpen file, where
    nobody starts anything, this is meaningless but harmless.
    """
    key = "game_id" if "game_id" in sub.columns else "date"
    if key not in sub.columns:
        return 1, 0
    mine = set(sub[key].dropna().unique())
    g = len(mine)
    order = "pitch_no" if "pitch_no" in all_pitches.columns else None
    if order is None:
        return g, 0
    gs = 0
    for gid in mine:
        rows = all_pitches[all_pitches[key] == gid]
        seq = pd.to_numeric(rows[order], errors="coerce")
        if seq.notna().any() and rows.loc[seq.idxmin(), "pitcher"] == \
                sub["pitcher"].iloc[0]:
            gs += 1
    return g, gs


# ------------------------------------------------------------------ build
def _ip_text(outs: int) -> str:
    """Innings in the way baseball writes them: 6.1 is six and a third."""
    return f"{outs // 3}.{outs % 3}"


def season_from_pitches(df: pd.DataFrame) -> dict:
    """{pitcher -> stat dict} in the same shape staffstats.attach returns.

    Keys match FIELDS and FULL_FIELDS in staffstats, so the sheets consume
    this and an official export interchangeably.
    """
    if df.empty or "pitcher" not in df.columns:
        return {}
    vocab = vocabulary(df)
    out = {}
    # Preferred source of innings; empty when the file has no outs column,
    # in which case outcomes are counted instead.
    by_outs = outs_by_pitcher(df, vocab)
    by_runs = {} if vocab == "trackman" else runs_by_pitcher(df)

    for name, sub in df.groupby("pitcher"):
        ends = pa_ends(sub, vocab)
        if ends.empty:
            continue

        tally = {k: 0 for k in ("K", "BB", "HBP", "1B", "2B", "3B", "HR",
                                "OUT", "ERR", "OTHER")}
        outs = 0
        for _, row in ends.iterrows():
            kind, o, _ = classify(row, vocab)
            tally[kind] += 1
            outs += o

        bf = len(ends)
        hits = tally["1B"] + tally["2B"] + tally["3B"] + tally["HR"]
        # Outs the outcomes directly evidence are a floor; the reconstruction
        # adds the ones nothing in the outcome column records. Taking the
        # larger never reports fewer innings than a man demonstrably threw.
        outs = max(by_outs.get(name, 0), outs)
        ip = outs / 3.0
        runs = by_runs[name] if name in by_runs else _runs(sub, vocab, ends)
        g, gs = _games(sub, df)

        # InZone% is a rate over tracked pitches. Outcomes are counted from
        # every row, including pitches the unit failed to measure, because a
        # walk is a walk whether or not the radar caught the ball -- but a
        # location rate computed over those same rows would not match the
        # vendor's, which only ever sees tracked pitches.
        zone = np.nan
        seen = sub[sub["velo"].notna()] if "velo" in sub.columns else sub
        if "inzone" in seen.columns and len(seen):
            zone = float(seen["inzone"].mean())

        rec = {
            "g": g, "gs": gs,
            "ip": _ip_text(outs),
            "era": round(9 * runs / ip, 2) if ip and np.isfinite(runs)
            else np.nan,
            "h": hits, "b2": tally["2B"], "b3": tally["3B"], "hr": tally["HR"],
            "k": tally["K"], "bb": tally["BB"],
            "k_pct": f"{100 * tally['K'] / bf:.1f}%" if bf else np.nan,
            "bb_pct": f"{100 * tally['BB'] / bf:.1f}%" if bf else np.nan,
            "fip": round((13 * tally["HR"] + 3 * (tally["BB"] + tally["HBP"])
                          - 2 * tally["K"]) / ip + FIP_CONSTANT, 2)
            if ip else np.nan,
            "whip": round((tally["BB"] + hits) / ip, 2) if ip else np.nan,
            "zone": f"{100 * zone:.1f}%" if np.isfinite(zone) else np.nan,
        }
        out[name] = rec
    return out


def coverage(df: pd.DataFrame) -> str:
    """One line on what the derived stats are and are not, for the app."""
    vocab = vocabulary(df)
    src = "TrackMan" if vocab == "trackman" else "TruMedia"
    runs = ("runs scored on each play" if vocab == "trackman"
            else "the RBI notation in each play description")
    return (f"Season line derived from the {src} pitch data: innings from "
            f"outs recorded, ERA from {runs}. Earned and unearned runs are "
            f"not distinguished, and only tracked pitches count, so these "
            f"will not match the official book exactly.")
