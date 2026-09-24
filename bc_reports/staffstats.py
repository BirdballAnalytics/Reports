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
    "player_id": ["playerId", "player_id", "PlayerId", "pitcherId"],
    "split":     ["entityKey", "SplitBy", "splitByName", "Batter Hand",
                  "split"],
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


def name_from_source(source: str) -> str:
    """Pull a pitcher's name out of a file name.

    A split export names nobody inside the file, but the exports come off
    TruMedia called things like "M. Bradshaw - Scouting Sheet 2.csv", so the
    name is right there. Used only when the file itself has no name column,
    and only as a last resort behind the player id.
    """
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", str(source or "").strip())
    stem = stem.replace("_", " ").split("/")[-1]
    head = re.split(r"\s+-\s+", stem)[0].strip()
    # Drop a leading upload hash such as "1b351a71-M. Bradshaw", which some
    # upload paths prepend.
    head = re.sub(r"^[0-9a-f]{6,}[-\s]+", "", head, flags=re.I).strip()
    return head if re.search(r"[A-Za-z]{2,}", head) else ""


def load_many_stats(files) -> tuple:
    """files: iterable of (name, file-like). Returns one frame plus notes.

    Several files are allowed in the stats slot because the split exports
    come one per pitcher: scouting a staff means uploading a handful of them.
    A file that will not parse is reported and skipped rather than stopping
    the others.
    """
    frames, notes = [], []
    for name, fh in files:
        try:
            one = load_stats(pd.read_csv(fh, low_memory=False), name)
        except (SchemaError, ValueError) as e:
            notes.append(f"Skipped {name}: {e}")
            continue
        frames.append(one)
        notes.append(f"{name}: {len(one)} pitcher"
                     f"{'s' if len(one) != 1 else ''}")
    if not frames:
        raise SchemaError("No usable season stats in the uploaded file(s).")

    out = pd.concat(frames, ignore_index=True, sort=False)
    # The same man in two files -- a roster export and his own split file --
    # keeps whichever came first, so the order they are uploaded decides.
    before = len(out)
    subset = [c for c in ("player_id", "_key") if c in out.columns]
    if subset:
        out = out.drop_duplicates(subset=subset[:1], keep="first")
    if len(out) < before:
        notes.append(f"Dropped {before - len(out)} duplicate pitcher row(s) "
                     f"across files.")
    return out.reset_index(drop=True), notes


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
    # A split export -- one row per batter hand for a single pitcher -- names
    # nobody at all; it identifies the man by `playerId` only. That is a
    # better key than a surname anyway, so the name is not required when an
    # id is present.
    if "player_id" in mapping:
        missing = [f for f in missing if f != "last"]
    if missing:
        raise SchemaError(
            f"{source or 'Stats file'}: missing column(s) for "
            f"{', '.join(missing)}. Expected a season pitching export with "
            f"IP, ERA, H, K, BB, InZone% and either a player name or a "
            f"playerId.")

    out = pd.DataFrame({k: df[v] for k, v in mapping.items()})
    out = collapse_splits(out)
    # No position filter. Two-way players are listed at their primary spot --
    # a catcher with 36 innings pitched is still a pitcher on this sheet --
    # and attach() only ever looks up names that threw pitches anyway.
    if "last" not in out:
        # Nothing in the file names the pitcher, so fall back to the file
        # name itself. This is what lets a stack of per-pitcher split exports
        # be told apart when their ids do not match the pitch file's.
        out["last"] = name_from_source(source)
    out["_key"] = out["last"].map(name_key)
    out["_init"] = (out["first"].astype(str).str[:1].str.lower()
                    if "first" in out else "")
    return out.reset_index(drop=True)


# ------------------------------------------------------------ split files
def _ip_outs(ip) -> int:
    """Innings written in thirds -- 6.1 is six and a third -- as whole outs."""
    whole, _, frac = str(ip).strip().partition(".")
    try:
        return int(float(whole or 0)) * 3 + {"1": 1, "2": 2}.get(frac[:1], 0)
    except ValueError:
        return 0


def _num(v, default=float("nan")) -> float:
    try:
        return float(str(v).strip().rstrip("%"))
    except (TypeError, ValueError):
        return default


def _batters_faced(row) -> float:
    """Recover batters faced from a rate and its count.

    K% is strikeouts over batters faced, so the denominator falls out of the
    pair. Both K and BB give an estimate; the published rates are rounded to
    a tenth of a point, so averaging the two is steadier than trusting one.
    """
    ests = []
    for count, rate in (("k", "k_pct"), ("bb", "bb_pct")):
        n, r = _num(row.get(count)), _num(row.get(rate))
        if n == n and r == r and r > 0:
            ests.append(n / (r / 100.0))
    return sum(ests) / len(ests) if ests else float("nan")


def collapse_splits(df: pd.DataFrame) -> pd.DataFrame:
    """Fold a split export down to one season line per pitcher.

    TruMedia can export a pitcher's season broken out by batter hand: one
    Lefty row and one Righty row, each a complete stat line. The sheets want
    one line, so the rows are combined -- and combined properly rather than
    added up:

    - innings are summed in thirds, not as decimals (6.2 + 0.2 is 7.1)
    - G and GS repeat the season total on every row, so they are taken once
    - ERA is rebuilt from earned runs, which come back out of ERA and IP
    - FIP is innings-weighted, which is exact: FIP is a rate per inning, so
      the weighted mean is the same number the formula would give
    - K% and BB% are rebuilt over batters faced, recovered from the rates
    - InZone% is weighted by batters faced, the nearest thing to a pitch
      count the file carries

    A file that is already one row per pitcher passes through untouched.
    """
    if "split" not in df.columns or df.empty:
        return df
    key = "player_id" if "player_id" in df.columns else "last"
    if key not in df.columns or df.groupby(key, dropna=False).size().max() < 2:
        return df.drop(columns=["split"])

    rows = []
    for _, grp in df.groupby(key, sort=False, dropna=False):
        outs = sum(_ip_outs(v) for v in grp["ip"])
        ip = outs / 3.0
        bf = [_batters_faced(r) for _, r in grp.iterrows()]
        bf_tot = sum(b for b in bf if b == b)
        rec = {c: grp[c].iloc[0] for c in grp.columns if c != "split"}

        for c in ("h", "k", "bb", "b2", "b3", "hr"):
            if c in grp:
                rec[c] = int(sum(_num(v, 0) for v in grp[c]))
        for c in ("g", "gs"):                       # season totals, not splits
            if c in grp:
                rec[c] = int(max(_num(v, 0) for v in grp[c]))
        rec["ip"] = f"{outs // 3}.{outs % 3}"

        if ip:
            er = sum(_num(r["era"], 0) * _ip_outs(r["ip"]) / 3.0 / 9.0
                     for _, r in grp.iterrows() if "era" in grp)
            rec["era"] = round(9 * er / ip, 2)
            if "fip" in grp:
                num = sum(_num(r["fip"], 0) * _ip_outs(r["ip"]) / 3.0
                          for _, r in grp.iterrows())
                rec["fip"] = round(num / ip, 2)
            if "whip" in grp:
                rec["whip"] = round((rec.get("bb", 0) + rec.get("h", 0)) / ip,
                                    2)
        if bf_tot:
            if "k" in rec:
                rec["k_pct"] = f"{100 * rec['k'] / bf_tot:.1f}%"
            if "bb" in rec:
                rec["bb_pct"] = f"{100 * rec['bb'] / bf_tot:.1f}%"
            if "zone" in grp:
                z = sum(_num(r["zone"], 0) * b
                        for (_, r), b in zip(grp.iterrows(), bf) if b == b)
                rec["zone"] = f"{z / bf_tot:.1f}%"
        rows.append(rec)
    return pd.DataFrame(rows)


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

    # Id beats name wherever both files carry one: it survives nicknames,
    # accents and two men sharing a surname, and a split export has no name
    # in it at all.
    by_id: dict[str, list] = {}
    if "player_id" in stats.columns:
        for _, r in stats.iterrows():
            by_id.setdefault(str(r["player_id"]).strip(), []).append(r)
    ids = {}
    if by_id and "pitcher_id" in pitches.columns:
        for who, grp in pitches.groupby("pitcher"):
            vals = grp["pitcher_id"].dropna()
            if len(vals):
                ids[who] = str(vals.iloc[0]).strip()

    found, missed = {}, []
    for name in sorted(pitches["pitcher"].dropna().unique()):
        cands = by_id.get(ids.get(name, ""), []) or by_key.get(name_key(name),
                                                               [])
        if len(cands) > 1:                # same surname: split on first initial
            ini = first_initial(name)
            narrowed = [c for c in cands if str(c.get("_init", "")) == ini]
            cands = narrowed or cands
        if not cands and len(stats) == 1 and \
                pitches["pitcher"].nunique() == 1:
            # One pitcher on each side and nothing to join on -- a split
            # export names nobody, and its id will not line up if the pitches
            # came from the other vendor. There is only one thing it can be.
            cands = [stats.iloc[0]]
        if not cands:
            missed.append(name)
            continue
        r = cands[0]
        keys = {k for k, _ in FIELDS} | {k for k, _ in FULL_FIELDS}
        # `full` and `first` are not printed as stats; they are carried so the
        # sheets can head a page with the man's actual name. TruMedia's pitch
        # export only ever gives the surname, so this file is the one place a
        # first name exists.
        keys |= {"full", "first"}
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
