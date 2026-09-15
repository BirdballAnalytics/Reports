"""Normalize TrackMan / TruMedia exports into one canonical frame.

Vendors disagree on column names and change them between versions, so every
field carries a list of known aliases. Matching is case- and punctuation-
insensitive. Anything unrecognized fails loudly rather than silently
producing empty plots.
"""
from __future__ import annotations

import re
import pandas as pd

CANON = {
    "pitcher":    ["Pitcher", "PitcherName", "pitcher_name", "Player", "pitcher"],
    "throws":     ["PitcherThrows", "PitcherHand", "pitcher_hand", "ThrowHand",
                   "P_Throws", "pitcherThrows", "Hand"],
    "pitch_type": ["TaggedPitchType", "PitchType", "pitch_type", "AutoPitchType",
                   "PitchTypeTagged", "pitch_name"],
    "velo":       ["RelSpeed", "ReleaseSpeed", "release_speed", "Velo",
                   "PitchVelocity", "StartSpeed", "pitch_speed"],
    "spin":       ["SpinRate", "ReleaseSpinRate", "release_spin_rate", "Spin",
                   "spin_rate"],
    "ivb":        ["InducedVertBreak", "InducedVerticalBreak", "IVB",
                   "induced_vert_break", "pfx_z_induced", "VertBreakInduced"],
    "hb":         ["HorzBreak", "HorizontalBreak", "HB", "horz_break",
                   "pfx_x", "HorzBreakInduced"],
}

OPTIONAL = {
    "uid":     ["PitchUID", "pitch_uid", "PlayID", "pitch_id", "uid"],
    "date":    ["Date", "GameDate", "game_date", "date"],
    "pitch_no": ["PitchNo", "pitch_number", "PitchNumber"],
    "game_id": ["GameID", "game_pk", "GameUID"],
}

REQUIRED = list(CANON)

# Vendors spell the same pitch a dozen ways; fold them onto our seven.
PITCH_ALIASES = {
    "fastball": "Fastball", "four-seam": "Fastball", "fourseam": "Fastball",
    "four-seam fastball": "Fastball", "4-seam fastball": "Fastball",
    "ff": "Fastball", "fa": "Fastball", "4s": "Fastball",
    "sinker": "Sinker", "two-seam": "Sinker", "twoseam": "Sinker",
    "two-seam fastball": "Sinker", "si": "Sinker", "ft": "Sinker", "2s": "Sinker",
    "slider": "Slider", "sl": "Slider", "sweeper": "Slider", "st": "Slider",
    "slurve": "Slider", "sv": "Slider",
    "curveball": "Curveball", "curve": "Curveball", "cu": "Curveball",
    "kc": "Curveball", "knuckle curve": "Curveball",
    "changeup": "ChangeUp", "change-up": "ChangeUp", "change": "ChangeUp",
    "ch": "ChangeUp",
    "cutter": "Cutter", "cut fastball": "Cutter", "fc": "Cutter", "ct": "Cutter",
    "splitter": "Splitter", "split-finger": "Splitter", "fs": "Splitter",
    "sp": "Splitter",
}

HAND_ALIASES = {
    "r": "Right", "right": "Right", "rhp": "Right", "righty": "Right",
    "l": "Left", "left": "Left", "lhp": "Left", "lefty": "Left",
}

# Tags that mean "the unit did not classify this", not a real pitch.
JUNK_TAGS = {"undefined", "knuckleball", "other", "unknown", "", "nan"}


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


class SchemaError(ValueError):
    pass


def detect_columns(df: pd.DataFrame) -> dict:
    """Map canonical field -> actual column name present in df."""
    lookup = {_key(c): c for c in df.columns}
    found = {}
    for field, aliases in {**CANON, **OPTIONAL}.items():
        for alias in aliases:
            if _key(alias) in lookup:
                found[field] = lookup[_key(alias)]
                break
    return found


def normalize(df: pd.DataFrame, mapping: dict | None = None,
              source: str = "") -> pd.DataFrame:
    """Return a canonical frame. Raises SchemaError listing what is missing."""
    mapping = mapping or detect_columns(df)
    missing = [f for f in REQUIRED if f not in mapping]
    if missing:
        raise SchemaError(
            f"{source or 'File'}: could not find column(s) for "
            f"{', '.join(missing)}. Map them by hand, or check the export."
        )

    out = pd.DataFrame()
    for field, col in mapping.items():
        out[field] = df[col]

    for c in ("velo", "spin", "ivb", "hb"):
        out[c] = pd.to_numeric(out[c], errors="coerce")

    out["pitcher"] = out["pitcher"].astype(str).str.strip()
    out["throws"] = (out["throws"].astype(str).str.strip().str.lower()
                     .map(HAND_ALIASES).fillna("Right"))

    raw = out["pitch_type"].astype(str).str.strip()
    out["pitch_type"] = raw.str.lower().map(PITCH_ALIASES).fillna(raw)

    if "date" in out:
        out["date"] = pd.to_datetime(out["date"], errors="coerce",
                                     format="mixed", dayfirst=False)
    if "uid" not in out:
        out["uid"] = [f"{source}:{i}" for i in range(len(out))]
    out["uid"] = out["uid"].astype(str)
    out["source"] = source
    return out


def split_tracked(df: pd.DataFrame):
    """Rows with no velo reading carry no usable metrics. Junk tags likewise."""
    has_data = df["velo"].notna() & df["ivb"].notna() & df["hb"].notna()
    junk = df["pitch_type"].astype(str).str.lower().isin(JUNK_TAGS)
    tracked = df[has_data & ~junk].copy()
    dropped = df[~(has_data & ~junk)].copy()
    return tracked, dropped


def load_many(files) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    """files: iterable of (name, file-like). Returns tracked, dropped, notes."""
    frames, notes = [], []
    for name, fh in files:
        raw = pd.read_csv(fh, low_memory=False)
        frames.append(normalize(raw, source=name))
        notes.append(f"{name}: {len(raw)} rows")
    if not frames:
        raise SchemaError("No files supplied.")
    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)
    combined = combined.drop_duplicates(subset="uid", keep="first")
    if len(combined) < before:
        notes.append(f"Removed {before - len(combined)} duplicate pitch IDs "
                     f"across files.")
    tracked, dropped = split_tracked(combined)
    if len(dropped):
        notes.append(f"Excluded {len(dropped)} untracked or unclassified "
                     f"pitches ({len(tracked)} usable).")
    return tracked, dropped, notes


# ------------------------------------------------------------------ hitting
HIT_CANON = {
    "batter":      ["Batter", "BatterName", "batter_name", "Hitter", "batter"],
    "pitch_call":  ["PitchCall", "pitch_call", "PitchResult", "Call"],
    "plate_x":     ["PlateLocSide", "plate_x", "PlateSide", "px"],
    "plate_z":     ["PlateLocHeight", "plate_z", "PlateHeight", "pz"],
}
HIT_OPTIONAL = {
    "batter_side":    ["BatterSide", "BatsHand", "batter_side", "Stand"],
    "pitcher":        ["Pitcher", "PitcherName", "pitcher"],
    "pitcher_throws": ["PitcherThrows", "PitcherHand", "P_Throws"],
    "pitch_type":     ["AutoPitchType", "TaggedPitchType", "PitchType",
                       "pitch_name"],
    "play_result":    ["PlayResult", "play_result", "Result", "events"],
    "kor_bb":         ["KorBB", "kor_bb", "KOrBB"],
    "hit_type":       ["TaggedHitType", "HitType", "bb_type"],
    "exit_speed":     ["ExitSpeed", "exit_speed", "ExitVelocity", "launch_speed"],
    "angle":          ["Angle", "LaunchAngle", "launch_angle", "VertHitAngle"],
    "distance":       ["Distance", "HitDistance", "hit_distance_sc", "Dist"],
    "bearing":        ["Bearing", "bearing", "HitBearing", "spray_angle"],
    "inning":         ["Inning", "inning"],
    "half":           ["Top/Bottom", "TopBottom", "inning_half", "Half"],
    "pa_of_inning":   ["PAofInning", "pa_of_inning", "PA"],
    "pitch_of_pa":    ["PitchofPA", "pitch_of_pa", "PitchNumber"],
    "date":           ["Date", "GameDate", "game_date"],
    "home_team":      ["HomeTeam", "home_team"],
    "away_team":      ["AwayTeam", "away_team"],
    "game_id":        ["GameID", "game_pk", "GameUID"],
}


def normalize_hitting(df: pd.DataFrame, source: str = "") -> pd.DataFrame:
    lookup = {_key(c): c for c in df.columns}
    mapping = {}
    for field, aliases in {**HIT_CANON, **HIT_OPTIONAL}.items():
        for alias in aliases:
            if _key(alias) in lookup:
                mapping[field] = lookup[_key(alias)]
                break
    missing = [f for f in HIT_CANON if f not in mapping]
    if missing:
        raise SchemaError(
            f"{source or 'File'}: could not find column(s) for "
            f"{', '.join(missing)}. This export may not carry hitting data.")

    out = pd.DataFrame()
    for field, col in mapping.items():
        out[field] = df[col]
    for c in ("plate_x", "plate_z", "exit_speed", "angle", "distance",
              "bearing", "inning", "pa_of_inning", "pitch_of_pa"):
        if c in out:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    for c in ("batter", "pitcher", "pitch_call", "play_result", "kor_bb",
              "hit_type", "pitch_type"):
        if c in out:
            out[c] = out[c].astype(str).str.strip()
    for c in ("play_result", "kor_bb", "hit_type"):
        if c in out:
            out.loc[out[c].str.lower().isin(["undefined", "nan"]), c] = ""
    if "date" in out:
        out["date"] = pd.to_datetime(out["date"], errors="coerce",
                                     format="mixed")
        # single-game exports often have a few blank Date cells; filling them
        # keeps those pitches from vanishing when filtering by game
        days = out["date"].dropna().dt.normalize().unique()
        if len(days) == 1:
            out["date"] = out["date"].fillna(pd.Timestamp(days[0]))
    out["source"] = source
    return out


def games_in(df: pd.DataFrame) -> list:
    """Distinct (label, mask-key) games present, newest first."""
    if "date" not in df.columns:
        return [("All pitches", None)]
    keys = df["date"].dropna().unique()
    return sorted(keys, reverse=True)


def _first(sub: pd.DataFrame, col: str):
    """First populated value in a column, or None. Row zero is not safe --
    exports routinely carry blank cells at the top of a file."""
    if col not in sub.columns:
        return None
    vals = sub[col].dropna()
    return vals.iloc[0] if len(vals) else None


def matchup_label(sub: pd.DataFrame) -> str:
    away, home = _first(sub, "away_team"), _first(sub, "home_team")
    when = _first(sub, "date")
    vs = f"{away} at {home}" if away and home else ""
    day = when.strftime("%B %-d, %Y") if when is not None else ""
    return " \u2014 ".join([p for p in (vs, day) if p])
