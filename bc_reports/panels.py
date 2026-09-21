"""Chart panels for the expanded scouting sheets.

Pitch-location density is a magnitude, so the heat maps use a single-hue
sequential ramp (cream -> maroon) rather than the conventional blue-to-red
rainbow, which implies a midpoint that raw density does not have.

Damage panels carry far fewer points -- a median of ten 95+ mph batted balls
per pitcher against left-handers -- so they plot the actual locations instead
of smoothing ten dots into a misleading cloud.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Rectangle
from scipy.ndimage import gaussian_filter

from .advanced import GROUP_COLOR, GROUP_LABEL, ZONE_X, ZONE_Y

MAROON = "#8c2232"
GOLD = "#dbcca6"
INK = "#1f1f1f"
CREAM = "#f6f2e9"

# sequential, one hue, light -> dark
HEAT = LinearSegmentedColormap.from_list(
    "bc_heat", ["#ffffff", "#f4ece0", "#e4c9ae", "#cf9277", "#b25548",
                "#8c2232", "#5e1622"])

# Catcher's view: x is negated, so a right-handed hitter stands on the LEFT of
# each panel and a lefty on the right, matching Savant, Brooks and TrackMan.
# The exported column ships the other way round -- hit-by-pitches put righties
# at +x -- so the flip happens here. Set False for pitcher's view; the home
# plate follows automatically, so the two can never disagree.
CATCHER_VIEW = True

VIEW = 2.6           # half-width of the binned area, in zone units
XPAD = 2.74          # a little wider than tall, to seat the plate
YPAD = 2.52
GRID = 64

def _zone_box(ax, lw=1.4):
    ax.add_patch(Rectangle((-ZONE_X, -ZONE_Y), 2 * ZONE_X, 2 * ZONE_Y,
                           fill=False, edgecolor=MAROON, lw=lw, zorder=5))
    # thirds, faint
    for f in (1 / 3, -1 / 3):
        ax.plot([-ZONE_X, ZONE_X], [ZONE_Y * f] * 2,
                color=MAROON, lw=0.4, alpha=0.30, zorder=5)
        ax.plot([ZONE_X * f] * 2, [-ZONE_Y, ZONE_Y],
                color=MAROON, lw=0.4, alpha=0.30, zorder=5)


# Home plate is 17 inches across and so is the strike zone, so the plate is
# drawn exactly as wide as the zone box and lines up beneath it. In catcher's
# view the near point faces the viewer and sits at the bottom; from the mound
# the flat edge is nearest, so the point flips away.
PLATE = "#9a9a9a"
PLATE_TOP = -1.92
PLATE_SHOULDER = -2.12
PLATE_POINT = -2.34


def _home_plate(ax):
    import matplotlib.patches as mp
    if CATCHER_VIEW:                       # point toward the viewer
        pts = [(-ZONE_X, PLATE_TOP), (ZONE_X, PLATE_TOP),
               (ZONE_X, PLATE_SHOULDER), (0.0, PLATE_POINT),
               (-ZONE_X, PLATE_SHOULDER)]
    else:                                  # flat edge nearest, point away
        pts = [(-ZONE_X, PLATE_POINT), (ZONE_X, PLATE_POINT),
               (ZONE_X, PLATE_SHOULDER), (0.0, PLATE_TOP),
               (-ZONE_X, PLATE_SHOULDER)]
    ax.add_patch(mp.Polygon(pts, closed=True, facecolor="white",
                            edgecolor=PLATE, lw=1.1, joinstyle="miter",
                            zorder=4))


def _frame(ax, pad=True):
    """Padded frame leaves room under the zone for home plate."""
    ax.set_xlim(-XPAD, XPAD) if pad else ax.set_xlim(-VIEW, VIEW)
    ax.set_ylim(-YPAD, YPAD) if pad else ax.set_ylim(-VIEW, VIEW)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#bdbdbd")
        s.set_linewidth(0.5)


def heat_map(sub, path, title="", size=1.30, dpi=340):
    """Smoothed density of pitch locations.

    An empty frame still draws the zone and the plate, so a group the
    pitcher does not throw reads as a deliberate blank rather than a gap in
    the sheet."""
    fig, ax = plt.subplots(figsize=(size, size * YPAD / XPAD), dpi=dpi)
    if len(sub):
        x = sub["plate_x"].to_numpy(float) * (-1 if CATCHER_VIEW else 1)
        y = sub["plate_z"].to_numpy(float)
        H, _, _ = np.histogram2d(x, y, bins=GRID,
                                 range=[[-VIEW, VIEW], [-VIEW, VIEW]])
        H = gaussian_filter(H, sigma=GRID / 22.0)
        if H.max() > 0:
            H = H / H.max()
        ax.imshow(H.T, origin="lower", extent=[-VIEW, VIEW, -VIEW, VIEW],
                  cmap=HEAT, vmin=0, vmax=1, interpolation="bilinear",
                  zorder=1)

    _home_plate(ax)
    _zone_box(ax)
    _frame(ax)
    if title:
        ax.set_title(title, fontsize=6.4, color=INK, pad=2.2,
                     fontweight="bold")
    fig.savefig(path, bbox_inches="tight", pad_inches=0.012, transparent=True)
    plt.close(fig)


def damage_map(sub, path, title="", size=1.30, dpi=340):
    """Individual 95+ mph batted-ball locations. Too few points to smooth."""
    fig, ax = plt.subplots(figsize=(size, size * YPAD / XPAD), dpi=dpi)
    if len(sub):
        ev = sub["exit_velo"].to_numpy(float)
        # size carries exit velocity; color stays constant so the eye reads
        # position first
        s = 10 + (np.clip(ev, 95, 112) - 95) * 1.7
        px = sub["plate_x"] * (-1 if CATCHER_VIEW else 1)
        ax.scatter(px, sub["plate_z"], s=s, c=MAROON,
                   alpha=0.78, edgecolors="white", linewidths=0.45, zorder=4)
    _home_plate(ax)
    _zone_box(ax)
    _frame(ax)
    if title:
        ax.set_title(title, fontsize=6.4, color=INK, pad=2.2,
                     fontweight="bold")
    fig.savefig(path, bbox_inches="tight", pad_inches=0.012, transparent=True)
    plt.close(fig)


def usage_bars(use_df, path, width=3.0, height=1.05, dpi=340):
    """Horizontal stacked shares, one row per situation."""
    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    # drawn top-down in the order given, so the caller controls the order
    rows = list(use_df.index)
    groups = [g for g in ("FB", "BB", "CH", "CUT") if g in use_df.columns]

    for i, situ in enumerate(rows):
        left = 0.0
        for g in groups:
            v = use_df.loc[situ, g]
            if not np.isfinite(v) or v <= 0:
                continue
            ax.barh(i, v, left=left, height=0.62,
                    color=GROUP_COLOR[g], edgecolor="white", linewidth=1.2)
            if v >= 0.13:                       # selective direct labels only
                ax.text(left + v / 2, i, f"{v*100:.0f}",
                        ha="center", va="center", fontsize=5.6,
                        color="white", fontweight="bold")
            left += v

    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows, fontsize=6.0, color=INK)
    ax.set_xlim(0, 1)
    ax.set_xticks([])
    ax.invert_yaxis()
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.015, transparent=True)
    plt.close(fig)


def usage_legend_items():
    return [(GROUP_LABEL[g], GROUP_COLOR[g]) for g in ("FB", "BB", "CH", "CUT")]
