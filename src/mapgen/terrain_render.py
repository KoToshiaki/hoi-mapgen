"""PNG rendering for terrain faces and raw terrain values (MAPGEN-002).

Terrain face colours are fixed in terrain_face.FACE_COLORS and never change
between runs.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely
from matplotlib.collections import PolyCollection

from .terrain_face import FACE_COLORS

# Fixed layer palettes (stable across runs, like FACE_COLORS).
WATER_TYPE_COLORS = {
    "NONE": "#e8e4d0", "OCEAN": "#b3cde3", "LAKE": "#5b8fc9",
    "RIVER": "#3d6fb4",
}
SURFACE_COLORS = {
    "NONE": "#b3cde3", "NORMAL": "#d5d98b", "TUNDRA": "#aebcae",
    "DESERT": "#e8c56b", "WETLAND": "#6fa8a0", "PERMANENT_SNOW_ICE": "#f0f0f5",
}
RELIEF_COLORS = {
    "NONE": "#b3cde3", "FLAT": "#ece7cb", "ROLLING": "#d6c491",
    "HILLS": "#b09a6a", "MOUNTAIN": "#8a7f77",
}
VEGETATION_COLORS = {
    "NONE": "#b3cde3", "OPEN": "#e6e2b8", "FOREST": "#4f8f4f",
    "RAINFOREST": "#1e6b3a",
}
DEVELOPMENT_COLORS = {
    "NONE": "#eae8dc", "SETTLED": "#d9b38c", "URBAN": "#b06a4a",
    "DENSE_URBAN": "#7a2e2e",
}
LAYER_PALETTES = {
    "water_type": WATER_TYPE_COLORS,
    "surface_class": SURFACE_COLORS,
    "relief_class": RELIEF_COLORS,
    "vegetation_class": VEGETATION_COLORS,
    "development_class": DEVELOPMENT_COLORS,
    "dominant_terrain_face": FACE_COLORS,
    "natural_terrain_face": FACE_COLORS,
}


def _verts(polys: np.ndarray) -> list[np.ndarray]:
    return [shapely.get_coordinates(p) for p in polys]


def _finish(ax, extent, title):
    min_x, min_y, max_x, max_y = extent
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=10)


def render_face_map(out_png: Path, title: str, faces: pd.Series,
                    hex_polys: np.ndarray, extent, coastline=None,
                    hex_lw: float = 0.25, figsize=(11, 11), dpi=160):
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    colors = [FACE_COLORS[f] for f in faces]
    pc = PolyCollection(_verts(hex_polys), facecolors=colors,
                        edgecolors="#55555540", linewidths=hex_lw)
    ax.add_collection(pc)
    if coastline is not None and not shapely.is_empty(coastline):
        from .render import _draw_lines
        _draw_lines(ax, coastline, "#1a355e", 0.7)
    present = [f for f in FACE_COLORS if f in set(faces)]
    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=FACE_COLORS[f],
                             edgecolor="gray") for f in present]
    ax.legend(handles, present, loc="lower right", fontsize=6, framealpha=0.85)
    _finish(ax, extent, title)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def _draw_categorical(ax, values, hex_polys, palette, extent, coastline=None,
                      hex_lw=0.25, title=""):
    colors = [palette[v] for v in values]
    pc = PolyCollection(_verts(hex_polys), facecolors=colors,
                        edgecolors="#55555540", linewidths=hex_lw)
    ax.add_collection(pc)
    if coastline is not None and not shapely.is_empty(coastline):
        from .render import _draw_lines
        _draw_lines(ax, coastline, "#1a355e", 0.6)
    present = [k for k in palette if k in set(values)]
    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=palette[k],
                             edgecolor="gray") for k in present]
    ax.legend(handles, present, loc="lower right", fontsize=6, framealpha=0.85)
    _finish(ax, extent, title)


def render_layer_map(out_png: Path, title: str, values, hex_polys: np.ndarray,
                     palette: dict, extent, coastline=None, hex_lw=0.25,
                     figsize=(11, 11), dpi=160):
    """One categorical layer as a single map."""
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    _draw_categorical(ax, values, hex_polys, palette, extent, coastline,
                      hex_lw, title)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def render_layer_panel(out_png: Path, title: str, df, hex_polys: np.ndarray,
                       extent, coastline=None, dpi=150):
    """2x2 panel: surface / relief / vegetation / development, same extent."""
    fig, axes = plt.subplots(2, 2, figsize=(15, 15), dpi=dpi)
    panels = [("surface_class", SURFACE_COLORS, "surface"),
              ("relief_class", RELIEF_COLORS, "relief"),
              ("vegetation_class", VEGETATION_COLORS, "vegetation"),
              ("development_class", DEVELOPMENT_COLORS, "development")]
    for ax, (col, palette, name) in zip(axes.ravel(), panels):
        _draw_categorical(ax, df[col], hex_polys, palette, extent, coastline,
                          hex_lw=0.45, title=name)
    fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def render_before_after(out_png: Path, title: str, before_faces, after_faces,
                        hex_polys: np.ndarray, extent, coastline=None, dpi=150):
    """MAPGEN-002 terrain_face vs MAPGEN-002A dominant face, side by side."""
    fig, axes = plt.subplots(1, 2, figsize=(20, 11), dpi=dpi)
    _draw_categorical(axes[0], before_faces, hex_polys, FACE_COLORS, extent,
                      coastline, hex_lw=0.3, title="before: MAPGEN-002 terrain_face")
    _draw_categorical(axes[1], after_faces, hex_polys, FACE_COLORS, extent,
                      coastline, hex_lw=0.3, title="after: MAPGEN-002A dominant_terrain_face")
    fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def render_value_map(out_png: Path, title: str, values: np.ndarray,
                     hex_polys: np.ndarray, extent, cmap: str, label: str,
                     vmin=None, vmax=None, hex_lw: float = 0.15,
                     figsize=(11, 11), dpi=160):
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    values = np.asarray(values, dtype=float)
    pc = PolyCollection(_verts(hex_polys), array=values, cmap=cmap,
                        edgecolors="#55555530", linewidths=hex_lw)
    if vmin is not None or vmax is not None:
        pc.set_clim(vmin, vmax)
    ax.add_collection(pc)
    fig.colorbar(pc, ax=ax, shrink=0.6, label=label)
    _finish(ax, extent, title)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)
