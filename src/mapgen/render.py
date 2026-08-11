"""PNG rendering of generated hex maps.

All rendering happens on the EPSG:3857 plane so hexes appear perfectly uniform,
matching how the game will draw the map.
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
from matplotlib.lines import Line2D

LAND_COLOR = "#e3d5a5"
WATER_COLOR = "#b3cde3"
COASTAL_EDGE = "#c0392b"
HEX_EDGE = "#88888855"
SOURCE_COAST_COLOR = "#1a355e"
CITY_COLOR = "#111111"


def _hex_verts(polys: np.ndarray) -> list[np.ndarray]:
    return [shapely.get_coordinates(p) for p in polys]


def _draw_lines(ax, geom: shapely.Geometry, color: str, lw: float, label=None):
    first = True
    stack = [geom]
    while stack:
        g = stack.pop()
        if g is None or shapely.is_empty(g):
            continue
        if g.geom_type in ("MultiLineString", "GeometryCollection", "MultiPolygon"):
            stack.extend(shapely.get_parts(g))
        elif g.geom_type == "Polygon":
            stack.append(g.boundary)
        elif g.geom_type in ("LineString", "LinearRing"):
            xy = shapely.get_coordinates(g)
            ax.plot(xy[:, 0], xy[:, 1], color=color, linewidth=lw,
                    label=label if first else None, solid_capstyle="round")
            first = False


def _plot_map(ax, hex_df: pd.DataFrame, hex_polys: np.ndarray,
              coastline_3857: shapely.Geometry, cities_df: pd.DataFrame,
              extent: tuple[float, float, float, float],
              label_min_population: int, show_city_labels: bool,
              hex_lw: float = 0.3):
    min_x, min_y, max_x, max_y = extent
    is_land = (hex_df["land_class"] == "land").to_numpy()
    is_coastal = hex_df["is_coastal"].to_numpy().astype(bool)

    verts = _hex_verts(hex_polys)
    facecolors = np.where(is_land, LAND_COLOR, WATER_COLOR)
    pc = PolyCollection(verts, facecolors=facecolors, edgecolors=HEX_EDGE,
                        linewidths=hex_lw)
    ax.add_collection(pc)
    # Coastal hex outline overlay.
    coastal_verts = [v for v, c in zip(verts, is_coastal) if c]
    if coastal_verts:
        pc2 = PolyCollection(coastal_verts, facecolors="none",
                             edgecolors=COASTAL_EDGE, linewidths=hex_lw * 1.6)
        ax.add_collection(pc2)

    if coastline_3857 is not None and not shapely.is_empty(coastline_3857):
        _draw_lines(ax, coastline_3857, SOURCE_COAST_COLOR, 0.9)

    if len(cities_df):
        ax.scatter(cities_df["source_x_m"], cities_df["source_y_m"],
                   s=10, color=CITY_COLOR, zorder=5)
        if show_city_labels:
            major = cities_df[cities_df["population"] >= label_min_population]
            for _, row in major.iterrows():
                ax.annotate(row["city_name"],
                            (row["source_x_m"], row["source_y_m"]),
                            xytext=(3, 3), textcoords="offset points",
                            fontsize=6, zorder=6)

    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])


def _legend(ax):
    handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor=LAND_COLOR, edgecolor="gray"),
        plt.Rectangle((0, 0), 1, 1, facecolor=WATER_COLOR, edgecolor="gray"),
        plt.Rectangle((0, 0), 1, 1, facecolor="none", edgecolor=COASTAL_EDGE),
        Line2D([0], [0], color=SOURCE_COAST_COLOR, linewidth=1.2),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=CITY_COLOR,
               markersize=4),
    ]
    labels = ["land hex", "water hex", "coastal hex", "source coastline", "city"]
    ax.legend(handles, labels, loc="lower right", fontsize=6, framealpha=0.85)


def render_preview(out_png: Path, title: str, hex_df: pd.DataFrame,
                   hex_polys: np.ndarray, coastline_3857, cities_df: pd.DataFrame,
                   extent, label_min_population: int, hex_lw: float = 0.3,
                   figsize=(11, 11), dpi=160):
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    _plot_map(ax, hex_df, hex_polys, coastline_3857, cities_df, extent,
              label_min_population, show_city_labels=True, hex_lw=hex_lw)
    _legend(ax)
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def render_contact_sheet(out_png: Path, per_size: list[dict], extent,
                         label_min_population: int, dpi=150):
    """2x2 grid of all hex sizes, identical extent and scale."""
    fig, axes = plt.subplots(2, 2, figsize=(16, 16), dpi=dpi)
    for ax, item in zip(axes.ravel(), per_size):
        _plot_map(ax, item["hex_df"], item["hex_polys"], item["coastline"],
                  item["cities_df"], extent, label_min_population,
                  show_city_labels=False, hex_lw=0.25)
        ax.set_title(f"{item['hex_size_m']:.0f} m flat-to-flat", fontsize=11)
    _legend(axes[0, 0])
    fig.suptitle("Hex size comparison (same extent, EPSG:3857)", fontsize=14)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def render_coast_error(out_png: Path, title: str, coast_df: pd.DataFrame,
                       generated_coast_3857, coastline_3857, extent, dpi=160):
    fig, ax = plt.subplots(figsize=(11, 11), dpi=dpi)
    if generated_coast_3857 is not None and not shapely.is_empty(generated_coast_3857):
        _draw_lines(ax, generated_coast_3857, "#999999", 0.7)
    if coastline_3857 is not None and not shapely.is_empty(coastline_3857):
        _draw_lines(ax, coastline_3857, SOURCE_COAST_COLOR, 0.6)
    if len(coast_df):
        sc = ax.scatter(coast_df["source_x_m"], coast_df["source_y_m"],
                        c=coast_df["coast_error_m"], cmap="viridis", s=4, zorder=5)
        fig.colorbar(sc, ax=ax, shrink=0.6, label="coastline error (m)")
    min_x, min_y, max_x, max_y = extent
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)
