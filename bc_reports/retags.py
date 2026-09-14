"""Retag layer.

Two kinds of correction, both saved per pitcher so they survive re-uploads:

  rule   - "Fronio, Zach: cutters with ivb < -10 become curveballs"
           Re-applies to every future bullpen automatically.
  manual - a specific set of pitch UIDs reassigned by hand (lasso-select).
           Only ever touches those exact pitches.

Rules run in order, then manual overrides, so a hand correction always wins.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field

import pandas as pd

METRICS = {"velo": "Velo", "spin": "Spin", "ivb": "IVB", "hb": "HB"}
OPS = {
    "<": lambda s, v: s < v,
    "<=": lambda s, v: s <= v,
    ">": lambda s, v: s > v,
    ">=": lambda s, v: s >= v,
}
DROP = "— drop —"


@dataclass
class Rule:
    pitcher: str
    from_type: str          # "*" matches any tag
    to_type: str            # DROP removes the pitches entirely
    metric: str = ""        # blank = no condition, convert all of from_type
    op: str = "<"
    value: float = 0.0

    def describe(self) -> str:
        src = "any pitch" if self.from_type == "*" else self.from_type
        cond = (f" with {METRICS.get(self.metric, self.metric)} "
                f"{self.op} {self.value:g}") if self.metric else ""
        dest = "drop" if self.to_type == DROP else f"\u2192 {self.to_type}"
        return f"{src}{cond} {dest}"

    def mask(self, df: pd.DataFrame) -> pd.Series:
        m = df["pitcher"] == self.pitcher
        if self.from_type != "*":
            m &= df["pitch_type"] == self.from_type
        if self.metric:
            m &= OPS[self.op](df[self.metric], self.value)
        return m


@dataclass
class RetagBook:
    rules: list = field(default_factory=list)
    manual: dict = field(default_factory=dict)   # uid -> pitch type (or DROP)

    # -- persistence -----------------------------------------------------
    def to_json(self) -> str:
        return json.dumps(
            {"rules": [asdict(r) for r in self.rules], "manual": self.manual},
            indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "RetagBook":
        if not text or not text.strip():
            return cls()
        raw = json.loads(text)
        return cls(rules=[Rule(**r) for r in raw.get("rules", [])],
                   manual=dict(raw.get("manual", {})))

    # -- editing ---------------------------------------------------------
    def add_rule(self, rule: Rule):
        self.rules.append(rule)

    def set_manual(self, uids, to_type: str):
        for u in uids:
            self.manual[str(u)] = to_type

    def clear_pitcher(self, pitcher: str, df: pd.DataFrame):
        self.rules = [r for r in self.rules if r.pitcher != pitcher]
        owned = set(df.loc[df["pitcher"] == pitcher, "uid"].astype(str))
        self.manual = {k: v for k, v in self.manual.items() if k not in owned}

    def for_pitcher(self, pitcher: str) -> list:
        return [r for r in self.rules if r.pitcher == pitcher]

    # -- application -----------------------------------------------------
    def apply(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list]:
        out, log = df.copy(), []
        for rule in self.rules:
            m = rule.mask(out)
            n = int(m.sum())
            if n:
                out.loc[m, "pitch_type"] = rule.to_type
                log.append(f"{rule.pitcher}: {rule.describe()} ({n})")
        if self.manual:
            hit = out["uid"].astype(str).map(self.manual)
            m = hit.notna()
            if m.any():
                out.loc[m, "pitch_type"] = hit[m]
                log.append(f"{int(m.sum())} pitch(es) set by hand")
        dropped = out["pitch_type"] == DROP
        if dropped.any():
            log.append(f"{int(dropped.sum())} pitch(es) dropped")
            out = out[~dropped]
        return out, log
