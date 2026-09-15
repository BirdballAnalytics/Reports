"""Rebuild the reference game from the numbers printed on the source PDF,
so the generated report can be checked line by line against it.

Nine pitches, five plate appearances. Locations are chosen to produce the
printed plate-discipline splits: 4 in zone (all swung at), 5 out of zone
(one chased). Bearings are invented -- the source PDF does not print them.
"""
import csv

ZONE_IN = [(-0.20, 2.60), (0.25, 2.30), (-0.45, 2.05), (0.10, 1.75)]
ZONE_OUT = [(-1.55, 2.35), (-1.60, 1.95), (-1.50, 1.60), (-1.20, 2.90)]
CHASE = (-0.95, 2.15)

# inning, pitcher, throws, call, pitch type, result, korbb, ev, la, dist, bearing
PITCHES = [
    (1, "DeCastro, Ryan",  "Right", "InPlay",      "Fastball",  "Out",     "", 102.2, 25.0, 389.0,   4.0, ZONE_IN[0],  1),
    (3, "DeCastro, Ryan",  "Right", "InPlay",      "ChangeUp",  "Out",     "",  93.7, 19.0, 314.0, -27.0, ZONE_IN[1],  1),
    (5, "Kassebaum, Alex", "Left",  "InPlay",      "Sinker",    "HomeRun", "",  97.4, 34.0, 375.0,  31.0, ZONE_IN[2],  1),
    (7, "Jankowski, Cole", "Right", "InPlay",      "Slider",    "Out",     "",  91.3, 37.0, 322.0, -19.0, ZONE_IN[3],  1),
    (9, "Jankowski, Cole", "Right", "BallCalled",  "Slider",    "",        "", None, None, None, None, ZONE_OUT[0], 1),
    (9, "Jankowski, Cole", "Right", "FoulBall",    "Slider",    "",        "", None, None, None, None, CHASE,       2),
    (9, "Jankowski, Cole", "Right", "BallCalled",  "Slider",    "",        "", None, None, None, None, ZONE_OUT[1], 3),
    (9, "Jankowski, Cole", "Right", "BallCalled",  "Fastball",  "",        "", None, None, None, None, ZONE_OUT[2], 4),
    (9, "Jankowski, Cole", "Right", "BallCalled",  "Fastball",  "Undefined", "Walk", None, None, None, None, ZONE_OUT[3], 5),
]

HEAD = ["Date", "HomeTeam", "AwayTeam", "Inning", "Top/Bottom", "PAofInning",
        "PitchofPA", "Batter", "BatterSide", "Pitcher", "PitcherThrows",
        "PitchCall", "AutoPitchType", "PlayResult", "KorBB", "TaggedHitType",
        "ExitSpeed", "Angle", "Distance", "Bearing", "PlateLocSide",
        "PlateLocHeight"]


def hit_type(la):
    if la is None:
        return ""
    return "GroundBall" if la < 10 else ("LineDrive" if la < 25 else "FlyBall")


def write(path="toomey_fixture.csv"):
    rows = []
    for (inn, p, thr, call, pt, res, kbb, ev, la, dist, brg, loc,
         pofpa) in PITCHES:
        rows.append({
            "Date": "5/30/26", "HomeTeam": "LON_ISL22", "AwayTeam": "BOC_EAG",
            "Inning": inn, "Top/Bottom": "Top", "PAofInning": 1,
            "PitchofPA": pofpa, "Batter": "Toomey, Jack", "BatterSide": "Right",
            "Pitcher": p, "PitcherThrows": thr, "PitchCall": call,
            "AutoPitchType": pt, "PlayResult": res or "Undefined",
            "KorBB": kbb or "Undefined", "TaggedHitType": hit_type(la),
            "ExitSpeed": ev, "Angle": la, "Distance": dist, "Bearing": brg,
            "PlateLocSide": loc[0], "PlateLocHeight": loc[1],
        })
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HEAD)
        w.writeheader()
        w.writerows(rows)
    return path


if __name__ == "__main__":
    print(write())
