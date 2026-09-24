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
                   "P_Throws", "pitcherThrows", "Hand", "throwsHand"],
    "pitch_type": ["TaggedPitchType", "PitchType", "pitch_type", "AutoPitchType",
                   "PitchTypeTagged", "pitch_name", "pitchTypeFull", "type"],
    "velo":       ["RelSpeed", "ReleaseSpeed", "release_speed", "Velo",
                   "PitchVelocity", "StartSpeed", "pitch_speed", "Vel",
                   "releaseVelocity"],
    "spin":       ["SpinRate", "ReleaseSpinRate", "release_spin_rate", "Spin",
                   "spin_rate"],
    "ivb":        ["InducedVertBreak", "InducedVerticalBreak", "IVB",
                   "induced_vert_break", "pfx_z_induced", "VertBreakInduced",
                   "IndVertBrk"],
    "hb":         ["HorzBreak", "HorizontalBreak", "HB", "horz_break",
                   "pfx_x", "HorzBreakInduced", "HorzBrk"],
}

OPTIONAL = {
    "uid":     ["PitchUID", "pitch_uid", "PlayID", "pitch_id", "uid",
                "uniqPitchId", "playGuid"],
    "date":    ["Date", "GameDate", "game_date", "date", "gameDate"],
    "pitch_no": ["PitchNo", "pitch_number", "PitchNumber", "pitchNumInGame"],
    "game_id": ["GameID", "game_pk", "GameUID", "gameId"],
    "team":    ["PitcherTeam", "pitchingTeam", "pitcher_team", "Team", "team"],
    # TruMedia's `pitcher` column is the bare surname and its `fullName`
    # column is the TEAM, not the player. The nearest thing to a full name in
    # the pitch export is the abbreviated form, "J. Radel". A real first name
    # only arrives with the season stats export.
    "pitcher_full": ["pitcherAbbrevName", "PitcherFullName",
                     "pitcher_full_name"],
    # Both vendors number their players, and a split stats export identifies
    # its pitcher by that number alone, so it is worth carrying through.
    "pitcher_id": ["PitcherId", "pitcherId", "pitcher_id"],
    # --- advanced scouting: locations, shape detail and plate-appearance
    # context. All optional, so an export lacking them still loads.
    "plate_x":   ["PlateLocSide", "plate_x", "PlateSide", "px", "x"],
    "plate_z":   ["PlateLocHeight", "plate_z", "PlateHeight", "pz", "y"],
    "vaa":       ["VertApprAngle", "VAA", "vert_appr_angle",
                  "VerticalApproachAngle"],
    "ext":       ["Extension", "ext", "release_extension"],
    "rel_h":     ["RelHeight", "ReleaseHeight", "rel_height", "z0"],
    "rel_s":     ["RelSide", "ReleaseSide", "rel_side", "x0"],
    "bat_hand":  ["BatterSide", "batterHand", "BatsHand", "Stand",
                  "batter_hand"],
    "count":     ["count", "Count", "balls_strikes"],
    # TrackMan keeps the two halves of the count in separate columns; they
    # are folded into `count` below so the two-strike slice works either way.
    "balls":     ["Balls"],
    "strikes":   ["Strikes"],
    "play_result": ["PlayResult", "pitchResult", "play_result", "events"],
    "play_desc": ["atbatDesc", "play_desc", "des", "description"],
    "inning":    ["Inning", "inn", "inning"],
    "half":      ["Top/Bottom", "TopBottom", "inning_half", "Half"],
    "ab_num":    ["abNumInGame", "PAofInning", "ab_num", "at_bat_number"],
    "exit_velo": ["ExitSpeed", "ExitVel", "exit_speed", "exitVelocity",
                  "launch_speed"],
    # --- outcome detail, used to derive season stats when no stats export is
    # uploaded. TrackMan splits the plate-appearance result across three
    # columns (KorBB carries strikeouts and walks, PlayResult the batted
    # ball, PitchCall the hit-by-pitch); TruMedia puts all of it in one.
    "k_or_bb":      ["KorBB", "k_or_bb"],
    "pitch_call":   ["PitchCall", "pitchOutcome", "pitch_call"],
    "outs_on_play": ["OutsOnPlay", "outs_on_play"],
    # Outs BEFORE the pitch. Differencing it across a half-inning recovers
    # every out, including the ones no plate appearance records -- caught
    # stealing, pickoffs, runners thrown out.
    "outs_before":  ["Outs", "outs"],
    "runs_scored":  ["RunsScored", "runs_scored"],
    "pitch_of_pa":  ["PitchofPA", "pitchNumInAB", "pitch_of_pa"],
}

# --- plate-location units -------------------------------------------------
# The strike zone, in the normalised space everything downstream works in.
# Fitted against the InZone% TruMedia publishes in its season export, which it
# reproduces to within 0.2 percentage points.
ZONE_X, ZONE_Y = 1.175, 1.125

# TrackMan and Statcast instead report feet: side from the middle of the
# plate, height from the ground. Half the plate is 8.5in and a ball's radius
# is 1.45in, so a pitch catching the black sits 9.95in off centre; the rule
# zone runs 1.5ft to 3.5ft off the ground.
PLATE_HALF_FT = 9.95 / 12.0
ZONE_BOT_FT, ZONE_TOP_FT = 1.5, 3.5
ZONE_MID_FT = (ZONE_TOP_FT + ZONE_BOT_FT) / 2
ZONE_HALF_FT = (ZONE_TOP_FT - ZONE_BOT_FT) / 2


def plate_units(plate_z: pd.Series) -> str:
    """'feet' or 'zone' -- which coordinate system a file's locations use.

    Decided from the height column rather than the column name, so an export
    from a vendor we have not seen still lands in the right branch. A height
    measured from the ground clusters around two and a half feet; one
    normalised to the zone is centred on zero, and its median cannot plausibly
    sit a full zone-height above the middle of the zone.
    """
    z = pd.to_numeric(plate_z, errors="coerce").dropna()
    if z.empty:
        return "zone"
    return "feet" if z.median() > 1.0 else "zone"


def to_zone_space(out: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Convert feet-from-the-ground locations into the normalised space.

    Returns the frame and whether a conversion happened, so the caller can
    say so. Sign conventions already agree: in both vendors' exports a
    right-handed hitter stands at positive x (verified from hit-by-pitch
    locations), and the catcher's-view flip is applied once, at draw time.
    """
    if "plate_z" not in out or "plate_x" not in out:
        return out, False
    if plate_units(out["plate_z"]) != "feet":
        return out, False
    out["plate_x"] = out["plate_x"] / PLATE_HALF_FT * ZONE_X
    out["plate_z"] = (out["plate_z"] - ZONE_MID_FT) / ZONE_HALF_FT * ZONE_Y
    return out, True

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
    """Normalise a column name for matching.

    A percent sign is kept as 'pct' rather than stripped: season exports
    carry both `K` and `K%`, which would otherwise collide on the same key
    and let the rate silently overwrite the count.
    """
    return re.sub(r"[^a-z0-9]", "", str(s).lower().replace("%", "pct"))


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

    for c in ("velo", "spin", "ivb", "hb", "plate_x", "plate_z", "vaa",
              "ext", "rel_h", "rel_s", "exit_velo", "ab_num",
              "outs_on_play", "runs_scored", "pitch_of_pa", "outs_before"):
        if c in out:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    if "count" not in out and {"balls", "strikes"} <= set(out.columns):
        b = pd.to_numeric(out["balls"], errors="coerce")
        s = pd.to_numeric(out["strikes"], errors="coerce")
        out["count"] = (b.astype("Int64").astype(str) + "-"
                        + s.astype("Int64").astype(str))
        out.loc[b.isna() | s.isna(), "count"] = None

    # Locations arrive in feet from some vendors and normalised to the zone
    # from others. One space from here on.
    out, converted = to_zone_space(out)
    out.attrs["plate_converted"] = converted
    # `inning` is only ever a grouping key, and TruMedia writes it as
    # "Bot 1" / "Top 3". Coercing it to a number would silently blank it.
    if "inning" in out:
        out["inning"] = out["inning"].astype(str).str.strip()

    if "bat_hand" in out:
        out["bat_hand"] = (out["bat_hand"].astype(str).str.strip()
                           .str[:1].str.upper()
                           .where(lambda s: s.isin(["R", "L"])))
    for c in ("play_result", "play_desc", "count", "half", "k_or_bb",
              "pitch_call"):
        if c in out:
            out[c] = out[c].astype(str).str.strip()
            out.loc[out[c].str.lower().isin(["nan", "undefined", ""]), c] = None

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
        one = normalize(raw, source=name)
        frames.append(one)
        note = f"{name}: {len(raw)} rows"
        if one.attrs.get("plate_converted"):
            note += " (locations in feet, rescaled to the strike zone)"
        notes.append(note)
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
    "batter_team":    ["BatterTeam", "batter_team", "battingTeam"],
    "pitcher_team":   ["PitcherTeam", "pitcher_team", "pitchingTeam"],
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
