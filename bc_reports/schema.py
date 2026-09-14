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
