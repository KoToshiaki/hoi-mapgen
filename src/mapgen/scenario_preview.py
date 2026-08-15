"""Scenario political map preview — QA and presentation only.

This module renders what the 1756 scenario currently looks like. It is
NOT part of production and nothing it draws may ever flow back into the
data: it reads canonical control, it writes PNGs, and that is the whole
contract. Simplification here is a drawing convenience and is applied to
copies, never to the canonical geometry.

Three things it is careful about.

Colours are derived from the polity id alone, so the same polity is the
same colour in every figure forever. A shared monarch does not mean a
shared colour: Great Britain, Ireland and Hanover are three colours, and
so are Sicily and Naples, because rendering them alike would draw a
political claim the data does not make.

The three kinds of absence are drawn differently. UNKNOWN means nobody
looked yet, UNRESOLVED means somebody looked and could not decide, and
AUTHORISED_LAND_NON_TERRESTRIAL means the authority exists and the target
type cannot express it. Painting them one grey would hide the only
interesting one.

And the coastal gap gets its own layer, because a map that shows the
production as complete would be the most misleading thing this project
could draw.
"""
from __future__ import annotations

import colorsys
import datetime as _dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import shapely

from .config import MapgenConfig
from .hex_grid import HexGrid
from .scenario import load_scenario, scenarios_root

H = Path("data/historical")
WATER = "#dce9f2"
LAND_UNKNOWN = "#e8e4dc"
COAST = "#7f8c8d"
UNRESOLVED_C = "#f0a30a"
GAP_C = "#d81b8f"

def polity_colour(polity_id: str) -> str:
    """Deterministic per-polity colour.

    Keyed on the polity id and nothing else - not on the parent, not on
    the personal-union partner. Two polities that share a monarch get two
    colours, because they are two polities.

    A fixed palette of N entries collides as soon as more than a handful
    of polities are active (Great Britain and Denmark-Norway landed on the
    same red), and a palette that reshuffles to avoid collisions would
    break the identity promise. So the hue is taken continuously from the
    hash instead: stable forever, and effectively collision-free.
    """
    h = hashlib.sha1(str(polity_id).encode("utf-8")).digest()
    hue = int.from_bytes(h[0:4], "big") / 2 ** 32
    sat = 0.46 + (h[4] / 255.0) * 0.34
    val = 0.52 + (h[5] / 255.0) * 0.30
    r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255),
                              round(b * 255))



REGIONS = {
    "british_isles": dict(
        title="British Isles", bbox=(-1250000, 6550000, 350000, 8100000)),
    "iceland": dict(
        title="Iceland", bbox=(-2600000, 9250000, -1550000, 10050000)),
    "mediterranean": dict(
        title="Sicily and Sardinia",
        bbox=(830000, 4300000, 1820000, 5120000)),
    "malta_gozo": dict(
        title="Malta and Gozo", bbox=(1555000, 4265000, 1650000, 4330000)),
    "saxony_brandenburg": dict(
        title="Saxony and Brandenburg",
        bbox=(1150000, 6500000, 1750000, 7000000)),
}


def _grid(cfg: MapgenConfig) -> HexGrid:
    return HexGrid(flat_to_flat=float(cfg.raw["terrain"]["hex_size_m"]),
                   orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)


def _land_shapes(view_tolerance_m: float, bbox=None):
    """Coastline for drawing only.

    Simplified on a COPY at a tolerance that is meaningless next to a
    6 km hex. The canonical cache is never written to.
    """
    ld = pd.read_parquet("output/europe_land_cache/europe_land_parts.parquet")
    if bbox is not None:
        m = ((ld.maxx > bbox[0]) & (ld.minx < bbox[2])
             & (ld.maxy > bbox[1]) & (ld.miny < bbox[3]))
        ld = ld[m]
    g = shapely.from_wkb(ld["wkb"].values)
    if view_tolerance_m > 0:
        g = shapely.simplify(g, view_tolerance_m)
    return g[~shapely.is_empty(g)]


def _collect(cfg: MapgenConfig, scenario_id: str):
    """Everything the figures need, gathered once."""
    scfg = cfg.raw["scenarios"]
    eu = cfg.output_dir / scfg.get("mapgen010_run",
                                   "europe_foundation_20260811")
    sdir = scenarios_root(cfg.data_dir) / scenario_id
    hx = pd.read_parquet(eu / "europe_hex_coverage.parquet",
                         columns=["hex_id", "q", "r", "centre_x_m",
                                  "centre_y_m", "is_terrestrial_hex"])
    ctrl = pd.read_csv(sdir / "territorial_control.csv",
                       keep_default_na=False, na_values=[""])
    sp = load_scenario(cfg.data_dir, scenario_id).scenario_polities
    gap = pd.read_csv(H / "coastal_hex_representability_audit.csv")
    gap = gap[gap.representability_class
              == "AUTHORISED_LAND_NON_TERRESTRIAL"]
    name = dict(zip(sp["scenario_polity_id"], sp["short_name"]))
    pid = dict(zip(sp["scenario_polity_id"], sp["polity_id"]))
    canon = dict(controlled=int((ctrl.control_status == "CONTROLLED").sum()),
                 unresolved=int((ctrl.control_status == "UNRESOLVED").sum()),
                 island_component=int((ctrl.territorial_target_type
                                       == "ISLAND_COMPONENT").sum()))
    ctrl = ctrl[ctrl["territorial_target_type"] == "TERRESTRIAL_HEX"]
    pos = hx.set_index("hex_id")[["q", "r", "centre_x_m", "centre_y_m"]]
    before = len(ctrl)
    ctrl = ctrl.join(pos, on="territorial_target_id", how="inner")
    # MAPGEN-008 put two control rows on the Kanto grid, which this Europe
    # preview does not cover. Counted, not quietly dropped.
    canon["off_europe_grid"] = before - len(ctrl)
    gap = gap.join(pos, on="hex_id", how="inner")
    return dict(hx=hx, ctrl=ctrl, gap=gap, sp=sp, name=name, pid=pid,
                sdir=sdir, canon=canon)


def _polys(grid, q, r):
    """Hex corner arrays for matplotlib.

    Built from the grid maths rather than from stored WKB: the Europe
    grid has 1.9 million hexes and loading their geometry to draw fifty
    thousand of them would be absurd. A closed ring repeats its first
    coordinate, so the trailing one is dropped.
    """
    return shapely.get_coordinates(
        grid.polygons(np.asarray(q), np.asarray(r)),
        include_z=False).reshape(-1, 7, 2)[:, :6, :]


def _draw_base(ax, bbox, tol):
    import matplotlib.patches as mpatches
    from matplotlib.collections import PolyCollection

    ax.set_facecolor(WATER)
    land = _land_shapes(tol, bbox)
    verts = []
    for g in shapely.get_parts(land):
        for poly in shapely.get_parts(shapely.get_geometry(g, 0)) \
                if False else [g]:
            ext = shapely.get_exterior_ring(poly)
            if ext is None:
                continue
            verts.append(shapely.get_coordinates(ext))
    ax.add_collection(PolyCollection(verts, facecolors=LAND_UNKNOWN,
                                     edgecolors=COAST, linewidths=0.25,
                                     zorder=1))
    return mpatches


def _render_hexes(ax, grid, df, colours, zorder, edge=None, lw=0.0,
                  alpha=1.0):
    from matplotlib.collections import PolyCollection

    if not len(df):
        return
    v = _polys(grid, df["q"].values, df["r"].values)
    ax.add_collection(PolyCollection(
        v, facecolors=colours, edgecolors=edge or "none", linewidths=lw,
        zorder=zorder, alpha=alpha))


def _stats(d):
    ctrl = d["ctrl"]
    c = ctrl[ctrl.control_status == "CONTROLLED"]
    u = ctrl[ctrl.control_status == "UNRESOLVED"]
    terr = int(d["hx"]["is_terrestrial_hex"].sum())
    return dict(
        controlled=len(c), unresolved=len(u), gap=len(d["gap"]),
        polities=int(c["controller_scenario_polity_id"].nunique()),
        terrestrial_hexes=terr,
        unknown_terrestrial=terr - len(ctrl),
        controlled_share_pct=round(100 * len(c) / terr, 3),
        canonical_controlled=d["canon"]["controlled"],
        canonical_unresolved=d["canon"]["unresolved"],
        island_component_rows=d["canon"]["island_component"],
        off_europe_grid_rows=d["canon"]["off_europe_grid"])


def render_overview(path, cfg, d, grid, stats, width_px=4000):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bbox = (-2900000, 4000000, 5100000, 11600000)
    ar = (bbox[3] - bbox[1]) / (bbox[2] - bbox[0])
    fig = plt.figure(figsize=(width_px / 100, width_px * ar / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    _draw_base(ax, bbox, 900.0)
    ctrl = d["ctrl"]
    c = ctrl[ctrl.control_status == "CONTROLLED"]
    for spid, g in c.groupby("controller_scenario_polity_id"):
        _render_hexes(ax, grid, g, polity_colour(d["pid"].get(spid, spid)),
                      zorder=3)
    _render_hexes(ax, grid, ctrl[ctrl.control_status == "UNRESOLVED"],
                  UNRESOLVED_C, zorder=4)
    _render_hexes(ax, grid, d["gap"], GAP_C, zorder=5, alpha=0.95)
    for spid, g in c.groupby("controller_scenario_polity_id"):
        nm = d["name"].get(spid, spid)
        ax.text(g["centre_x_m"].mean(), g["centre_y_m"].mean(), str(nm),
                ha="center", va="center", fontsize=13, zorder=9,
                color="#ffffff", weight="bold",
                path_effects=_stroke())
    ax.set_xlim(bbox[0], bbox[2])
    ax.set_ylim(bbox[1], bbox[3])
    ax.set_axis_off()
    ax.text(0.006, 0.994,
            f"1756-08-01 scenario preview  |  canonical CONTROLLED "
            f"{stats['canonical_controlled']:,} / UNRESOLVED "
            f"{stats['canonical_unresolved']:,}  |  drawn here "
            f"{stats['controlled']:,} / {stats['unresolved']:,} across "
            f"{stats['polities']} polities "
            f"({stats['off_europe_grid_rows']} rows sit on the Kanto grid "
            f"and {stats['island_component_rows']} is an ISLAND_COMPONENT)"
            f"  |  authorised-but-unrepresentable {stats['gap']:,}",
            transform=ax.transAxes, va="top", ha="left", fontsize=15,
            family="monospace", zorder=10,
            bbox=dict(fc="#ffffff", ec="#bdc3c7", alpha=0.92, pad=6))
    fig.savefig(path, dpi=100, facecolor=WATER)
    plt.close(fig)


def _stroke():
    import matplotlib.patheffects as pe
    return [pe.withStroke(linewidth=3.2, foreground="#00000090")]


def render_legend(path, d, stats):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt

    c = d["ctrl"][d["ctrl"].control_status == "CONTROLLED"]
    counts = c["controller_scenario_polity_id"].value_counts()
    fig, ax = plt.subplots(figsize=(11, 9), dpi=140)
    ax.set_axis_off()
    handles = [mpatches.Patch(
        fc=polity_colour(d["pid"].get(s, s)), ec="#2c3e50",
        label=f"{d['name'].get(s, s)}  —  {n:,} hexes")
        for s, n in counts.items()]
    handles += [
        mpatches.Patch(fc=UNRESOLVED_C, ec="#2c3e50",
                       label=f"UNRESOLVED — researched, undecidable "
                             f"({stats['unresolved']:,})"),
        mpatches.Patch(fc=GAP_C, ec="#2c3e50",
                       label=f"AUTHORISED_LAND_NON_TERRESTRIAL — authority "
                             f"exists, no target type ({stats['gap']:,})"),
        mpatches.Patch(fc=LAND_UNKNOWN, ec=COAST,
                       label=f"UNKNOWN — not yet researched "
                             f"(~{stats['unknown_terrestrial']:,} "
                             f"terrestrial hexes)"),
        mpatches.Patch(fc=WATER, ec=COAST, label="water"),
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=11, frameon=False,
              title="1756-08-01 scenario — legend", title_fontsize=14)
    note = (
        "Colours are keyed on the polity id alone. A shared monarch does\n"
        "not merge colours: Great Britain, Ireland and Hanover are three\n"
        "colours; so are Sicily and Naples.\n\n"
        "The three absences are drawn differently on purpose.\n"
        "  UNKNOWN      nobody has researched it yet\n"
        "  UNRESOLVED   researched, and the evidence does not decide\n"
        "  GAP          authority exists and the target type cannot\n"
        "               express it (see MAPGEN-024)\n\n"
        f"CONTROLLED share of terrestrial hexes: "
        f"{stats['controlled_share_pct']}%\n"
        f"  denominator = all {stats['terrestrial_hexes']:,} canonical\n"
        f"  terrestrial hexes in the Europe grid, Europe-wide, including\n"
        f"  every region no stage has looked at yet.\n\n"
        "This renderer is QA only. Nothing it draws is authoritative."
    )
    ax.text(0.0, 0.02, note, transform=ax.transAxes, va="bottom",
            fontsize=9.5, family="monospace")
    fig.tight_layout()
    fig.savefig(path, dpi=140, facecolor="white")
    plt.close(fig)


def render_closeup(path, key, cfg, d, grid, stats):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    r = REGIONS[key]
    bbox = r["bbox"]
    ar = (bbox[3] - bbox[1]) / (bbox[2] - bbox[0])
    fig = plt.figure(figsize=(16, max(6.0, 16 * ar)), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    _draw_base(ax, bbox, 120.0)

    def clip(df, xc="centre_x_m", yc="centre_y_m"):
        return df[(df[xc] > bbox[0] - 9000) & (df[xc] < bbox[2] + 9000)
                  & (df[yc] > bbox[1] - 9000) & (df[yc] < bbox[3] + 9000)]

    ctrl = clip(d["ctrl"])
    c = ctrl[ctrl.control_status == "CONTROLLED"]
    for spid, g in c.groupby("controller_scenario_polity_id"):
        _render_hexes(ax, grid, g, polity_colour(d["pid"].get(spid, spid)),
                      zorder=3, edge="#ffffff", lw=0.35)
    _render_hexes(ax, grid, ctrl[ctrl.control_status == "UNRESOLVED"],
                  UNRESOLVED_C, zorder=4, edge="#ffffff", lw=0.35)
    gp = clip(d["gap"])
    # thin outline: at British Isles zoom a heavy stroke turns the whole
    # coast magenta and hides how narrow the gap actually is
    lw = 1.6 if (bbox[2] - bbox[0]) < 400000 else 0.7
    _render_hexes(ax, grid, gp, GAP_C, zorder=5, alpha=0.38)
    _render_hexes(ax, grid, gp, "none", zorder=6, edge=GAP_C, lw=lw)
    # coastline redrawn ON TOP: the whole point of a closeup is to see how
    # much land each hex actually holds, and an opaque fill hides it
    from matplotlib.collections import PolyCollection
    top = [shapely.get_coordinates(shapely.get_exterior_ring(g))
           for g in shapely.get_parts(_land_shapes(120.0, bbox))
           if shapely.get_exterior_ring(g) is not None]
    ax.add_collection(PolyCollection(top, facecolors="none",
                                     edgecolors="#1b2631", linewidths=0.8,
                                     zorder=7))
    ax.set_xlim(bbox[0], bbox[2])
    ax.set_ylim(bbox[1], bbox[3])
    ax.set_axis_off()
    lab = ", ".join(f"{d['name'].get(s, s)} {n:,} in view"
                    for s, n in c["controller_scenario_polity_id"]
                    .value_counts().items())
    ax.text(0.006, 0.994,
            f"{r['title']}  |  {lab or 'no control here'}  |  coastal gap "
            f"{len(gp):,} hexes outlined in magenta",
            transform=ax.transAxes, va="top", ha="left", fontsize=12,
            family="monospace", zorder=10,
            bbox=dict(fc="#ffffff", ec="#bdc3c7", alpha=0.92, pad=5))
    fig.savefig(path, dpi=150, facecolor=WATER)
    plt.close(fig)
    return len(gp)


def render_scenario_preview(cfg: MapgenConfig, out_dir: Path | None = None,
                            scenario_id: str | None = None) -> Path:
    """Render the whole preview set. Returns the output directory."""
    scenario_id = scenario_id or cfg.raw["scenarios"]["active_scenario"]
    out_dir = Path(out_dir or (cfg.output_dir / "scenario_preview"))
    out_dir.mkdir(parents=True, exist_ok=True)
    d = _collect(cfg, scenario_id)
    grid = _grid(cfg)
    stats = _stats(d)
    render_overview(out_dir / "scenario_1756_political_map.png", cfg, d,
                    grid, stats)
    render_legend(out_dir / "scenario_1756_political_map_legend.png", d,
                  stats)
    close = {}
    for key in REGIONS:
        close[key] = render_closeup(
            out_dir / f"{key}_political_closeup.png", key, cfg, d, grid,
            stats)
    (out_dir / "preview_manifest.json").write_text(json.dumps({
        "scenario_id": scenario_id,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "authoritative": False,
        "purpose": "QA_AND_PRESENTATION_ONLY",
        "stats": stats,
        "closeup_gap_hexes": close,
        "colour_rule": "sha1(polity_id)[0] % len(PALETTE); personal unions "
                       "and composite membership never share a colour",
    }, indent=2), encoding="utf-8")
    print(f"[scenario-preview] {out_dir}: CONTROLLED {stats['controlled']:,}"
          f", UNRESOLVED {stats['unresolved']:,}, gap {stats['gap']:,}")
    return out_dir
