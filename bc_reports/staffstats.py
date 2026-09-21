"""Season pitching totals, joined onto the pitch data by name.

IP, ERA, H, K, BB and InZone% are official counting stats. They can be
approximated from pitch-level data, but the approximation drifts -- untracked
pitches and missing games pull innings and hits down -- and it will disagree
with the published book. So they come from a separate stats export instead.
"""
from __future__ import annotations

import re
import pandas as pd

from .schema import SchemaError, _key

STAT_CANON = {
    "last":  ["player", "lastName", "last_name", "Player", "Last"],
    "ip":    ["IP", "InningsPitched", "ip", "innings"],
    "era":   ["ERA", "era", "EarnedRunAvg"],
    "h":     ["H", "Hits", "hits", "HA"],
    "k":     ["K", "SO", "StrikeOuts", "strikeouts", "Ks"],
    "bb":    ["BB", "Walks", "walks", "BBA"],
    "zone":  ["InZone%", "Zone%", "InZonePct", "zone_pct", "InZone"],
}
# Present in fuller season exports; absent from leaner ones, so optional.
STAT_EXTRA = {
    "g":      ["G", "Games", "App"],
    "gs":     ["GS", "GamesStarted", "Starts"],
    "b2":     ["2B", "Doubles"],
    "b3":     ["3B", "Triples"],
    "hr":     ["HR", "HomeRuns", "HomeRunsAllowed"],
    "k_pct":  ["K%", "KPct", "StrikeoutPct"],
    "bb_pct": ["BB%", "BBPct", "WalkPct"],
    "fip":    ["FIP", "fip"],
    "whip":   ["WHIP", "whip"],
}
STAT_OPTIONAL = {
    "first":     ["playerFirstName", "firstName", "first_name", "First"],
    "full":      ["playerFullName", "fullName", "Name", "full_name"],
    "abbrev":    ["abbrevName", "abbrev_name"],
    "throws":    ["throwsHand", "ThrowsHand", "PitcherThrows", "Throws"],
    "pos":       ["pos", "Position", "POS"],
    "team":      ["newestTeamAbbrevName", "TeamAbbrev", "Team", "team"],
    "team_name": ["newestTeamLocation", "newestTeamName", "TeamName"],
}

# Fields shown on the staff sheet, in order
FIELDS = [("ip", "IP"), ("era", "ERA"), ("h", "H"),
          ("k", "K"), ("bb", "BB"), ("zone", "Zone")]

# The fuller line on the individual sheets
FULL_FIELDS = [("g", "G"), ("gs", "GS"), ("ip", "IP"), ("era", "ERA"),
               ("h", "H"), ("b2", "2B"), ("b3", "3B"), ("hr", "HR"),
               ("k_pct", "K%"), ("bb_pct", "BB%"), ("fip", "FIP"),
               ("whip", "WHIP")]


def name_key(value) -> str:
    """Reduce a name to a comparable surname.

    Pitch exports write 'Radel', 'Radel, Jack' or 'Jack Radel' depending on
    the vendor; all three have to land on the same key."""
    s = str(value or "").strip()
    if not s:
        return ""
    if "," in s:
        s = s.split(",")[0]
    else:
        parts = [p for p in re.split(r"\s+", s) if p]
        if len(parts) > 1 and not parts[-1].endswith("."):
            s = parts[-1]
    return _key(s)


def first_initial(value) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    if "," in s:
        rest = s.split(",", 1)[1].strip()
        return rest[:1].lower()
    parts = [p for p in re.split(r"\s+", s) if p]
    return parts[0][:1].lower() if len(parts) > 1 else ""


def load_stats(df: pd.DataFrame, source: str = "") -> pd.DataFrame:
    lookup = {_key(c): c for c in df.columns}
    mapping = {}
    for field, aliases in {**STAT_CANON, **STAT_OPTIONAL,
                           **STAT_EXTRA}.items():
        for a in aliases:
            if _key(a) in lookup:
                mapping[field] = lookup[_key(a)]
                break
    missing = [f for f in STAT_CANON if f not in mapping]
    if missing:
        raise SchemaError(
            f"{source or 'Stats file'}: missing column(s) for "
            f"{', '.join(missing)}. Expected a season pitching export with "
            f"player, IP, ERA, H, K, BB and InZone%.")

    out = pd.DataFrame({k: df[v] for k, v in mapping.items()})
    # No position filter. Two-way players are listed at their primary spot --
    # a catcher with 36 innings pitched is still a pitcher on this sheet --
    # and attach() only ever looks up names that threw pitches anyway.
    out["_key"] = out["last"].map(name_key)
    out["_init"] = (out["first"].astype(str).str[:1].str.lower()
                    if "first" in out else "")
    return out.reset_index(drop=True)


def team_label(stats: pd.DataFrame | None, pitches: pd.DataFrame | None) -> str:
    """Best available name for the staff being scouted."""
    if stats is not None and len(stats):
        for col in ("team_name", "team"):
            if col in stats.columns:
                vals = stats[col].dropna()
                if len(vals):
                    return str(vals.iloc[0])
    if pitches is not None and "team" in getattr(pitches, "columns", []):
        vals = pitches["team"].dropna()
        if len(vals):
            return str(vals.iloc[0])
    return ""


def attach(pitches: pd.DataFrame, stats: pd.DataFrame | None):
    """Return {pitcher name -> stat dict} plus a list of unmatched names."""
    if stats is None or stats.empty:
        return {}, []

    by_key: dict[str, list] = {}
    for _, r in stats.iterrows():
        by_key.setdefault(r["_key"], []).append(r)

    found, missed = {}, []
    for name in sorted(pitches["pitcher"].dropna().unique()):
        cands = by_key.get(name_key(name), [])
        if len(cands) > 1:                # same surname: split on first initial
            ini = first_initial(name)
            narrowed = [c for c in cands if str(c.get("_init", "")) == ini]
            cands = narrowed or cands
        if not cands:
            missed.append(name)
            continue
        r = cands[0]
        keys = {k for k, _ in FIELDS} | {k for k, _ in FULL_FIELDS}
        found[name] = {k: r.get(k) for k in keys}
    return found, missed


def format_line(stat: dict | None) -> str:
    if not stat:
        return ""
    parts = []
    for key, label in FIELDS:
        v = stat.get(key)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        txt = str(v).strip()
        if not txt or txt.lower() == "nan":
            continue
        parts.append(f"{label} {txt}")
    return "  \u00b7  ".join(parts)
