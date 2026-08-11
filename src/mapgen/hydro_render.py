"""Rendering for MAPGEN-003 hydrography (coast v2, lakes, rivers)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import shapely
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.lines import Line2D

from .render import _draw_lines
from .terrain_render import WATER_TYPE_COLORS, _finish, _verts

RIVER_CLASS_COLORS = {
    "MINOR": "#8ab6dd", "MEDIUM": "#4a90d9", "MAJOR": "#1f5fa8",
    "GREAT": "#0d3a6e",
}
RIVER_CLASS_LW = {"MINOR": 0.8, "MEDIUM": 1.3, "MAJOR": 2.0, "GREAT": 3.0}
LAND_WATER_COLORS = {"land": "#e3d5a5", "water": "#b3cde3"}


def _hex_background(ax, hex_polys, water_types, hex_lw=0.2):
    colors = [WATER_TYPE_COLORS.get(w, "#e8e4d0") for w in water_types]
    pc = PolyCollection(_verts(hex_polys), facecolors=colors,
                        edgecolors="#55555530", linewidths=hex_lw)
    ax.add_collection(pc)


def _draw_branches(ax, branches, lw_scale=1.0, alpha=0.9, color_override=None):
    for b in branches:
        color = color_override or RIVER_CLASS_COLORS.get(b.river_class, "#333")
        lw = RIVER_CLASS_LW.get(b.river_class, 1.0) * lw_scale
        xy = shapely.get_coordinates(b.line)
        ax.plot(xy[:, 0], xy[:, 1], color=color, linewidth=lw, alpha=alpha,
                solid_capstyle="round")


def _draw_snapped(ax, snap_results, node_xy, lw_scale=1.0):
    for res in snap_results:
        b = res["branch"]
        color = RIVER_CLASS_COLORS.get(b.river_class, "#333")
        lw = RIVER_CLASS_LW.get(b.river_class, 1.0) * lw_scale
        path = res["node_path"]
        pts = np.array([node_xy[n] for n in path])
        ax.plot(pts[:, 0], pts[:, 1], color=color, linewidth=lw,
                solid_capstyle="round", solid_joinstyle="round")


def _river_legend(ax, extra=()):
    handles = [Line2D([0], [0], color=RIVER_CLASS_COLORS[c],
                      linewidth=RIVER_CLASS_LW[c]) for c in RIVER_CLASS_COLORS]
    labels = list(RIVER_CLASS_COLORS)
    for h, l in extra:
        handles.append(h)
        labels.append(l)
    ax.legend(handles, labels, loc="lower right", fontsize=6, framealpha=0.85)


def render_hydro_map(out_png: Path, title: str, hex_polys, water_types,
                     extent, coastline=None, lakes_geom=None,
                     source_branches=(), snap_results=(), node_xy=None,
                     source_as_reference=False, figsize=(12, 12), dpi=160):
    """Hydro overview: hex water background + lakes + rivers.

    With ``snap_results``: snapped edge paths in class colours, source rivers
    as thin grey reference lines (same-image comparison).
    """
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    _hex_background(ax, hex_polys, water_types)
    if coastline is not None and not shapely.is_empty(coastline):
        _draw_lines(ax, coastline, "#1a355e", 0.6)
    if lakes_geom is not None and not shapely.is_empty(lakes_geom):
        _draw_lines(ax, shapely.boundary(lakes_geom), "#2a5fa0", 0.7)
    if snap_results and node_xy is not None:
        if source_as_reference:
            _draw_branches(ax, [r["branch"] for r in snap_results],
                           lw_scale=0.5, alpha=0.65, color_override="#777777")
        _draw_snapped(ax, snap_results, node_xy)
        extra = [(Line2D([0], [0], color="#777777", linewidth=0.8),
                  "source river (reference)")] if source_as_reference else []
        _river_legend(ax, extra)
    elif source_branches:
        _draw_branches(ax, source_branches)
        _river_legend(ax)
    _finish(ax, extent, title)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def render_snapping_before_after(out_png: Path, title: str, hex_polys,
                                 water_types, extent, coastline,
                                 source_branches, before_segments,
                                 after_results, node_xy, conf_markers=None,
                                 dpi=150):
    """MAPGEN-003 vs MAPGEN-003A snapped rivers, same extent.

    before_segments: list of (segment_coords(2,2), river_class).
    conf_markers: optional list of (x, y, preserved_bool) confluence dots
    drawn on the AFTER panel.
    """
    fig, axes = plt.subplots(1, 2, figsize=(20, 11), dpi=dpi)
    for ax, sub in ((axes[0], "before: MAPGEN-003"),
                    (axes[1], "after: MAPGEN-003A")):
        _hex_background(ax, hex_polys, water_types)
        if coastline is not None and not shapely.is_empty(coastline):
            _draw_lines(ax, coastline, "#1a355e", 0.5)
        _draw_branches(ax, source_branches, lw_scale=0.5, alpha=0.6,
                       color_override="#777777")
        _finish(ax, extent, sub)
    segs = [s for s, _ in before_segments]
    if segs:
        colors = [RIVER_CLASS_COLORS.get(c, "#333") for _, c in before_segments]
        lws = [RIVER_CLASS_LW.get(c, 1.0) for _, c in before_segments]
        axes[0].add_collection(LineCollection(segs, colors=colors,
                                              linewidths=lws))
    _draw_snapped(axes[1], after_results, node_xy)
    if conf_markers:
        ok = [(x, y) for x, y, p in conf_markers if p]
        bad = [(x, y) for x, y, p in conf_markers if not p]
        if ok:
            axes[1].scatter(*zip(*ok), s=40, marker="o", facecolors="none",
                            edgecolors="#1f8f3a", linewidths=1.6, zorder=6,
                            label="confluence preserved")
        if bad:
            axes[1].scatter(*zip(*bad), s=60, marker="x", color="#c0392b",
                            linewidths=2.0, zorder=6,
                            label="confluence LOST")
        axes[1].legend(loc="upper right", fontsize=7, framealpha=0.9)
    _river_legend(axes[0])
    fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def render_coast_before_after(out_png: Path, title: str, hex_polys,
                              ne_classes, osm_classes, osm_coastline,
                              extent, dpi=150):
    fig, axes = plt.subplots(1, 2, figsize=(20, 11), dpi=dpi)
    for ax, classes, sub in ((axes[0], ne_classes, "before: Natural Earth 1:10m"),
                             (axes[1], osm_classes, "after: OSM land polygons")):
        colors = [LAND_WATER_COLORS[c] for c in classes]
        pc = PolyCollection(_verts(hex_polys), facecolors=colors,
                            edgecolors="#55555530", linewidths=0.2)
        ax.add_collection(pc)
        _draw_lines(ax, osm_coastline, "#1a355e", 0.5)
        _finish(ax, extent, sub)
    fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def render_lake_zoom(out_png: Path, title: str, hex_polys, water_types,
                     lakes_geom, extent, dpi=160):
    fig, ax = plt.subplots(figsize=(10, 10), dpi=dpi)
    _hex_background(ax, hex_polys, water_types, hex_lw=0.5)
    if lakes_geom is not None and not shapely.is_empty(lakes_geom):
        _draw_lines(ax, shapely.boundary(lakes_geom), "#153e6e", 1.2)
    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=WATER_TYPE_COLORS[k],
                             edgecolor="gray")
               for k in ("NONE", "OCEAN", "LAKE", "RIVER")]
    ax.legend(handles, ["land", "ocean", "lake hex", "river hex"],
              loc="lower right", fontsize=7, framealpha=0.85)
    _finish(ax, extent, title)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)
