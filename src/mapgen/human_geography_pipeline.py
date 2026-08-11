"""MAPGEN-007 — Reference Administrative & Settlement Geography Foundation.

Builds the REFERENCE human-geography layer (Natural Earth cultural data,
canonicalised) on top of the untouched MAPGEN-006R physical geography.

REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP. Nothing here is
historical or gameplay authority; admin info is kept in separate tables and
never burned into geography_hexes.
"""
from __future__ import annotations

import datetime as _dt
import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from .config import BBox, MapgenConfig
from .hex_grid import HexGrid
from .human_geography import (HUMAN_GEOGRAPHY_ALGORITHM_VERSION,
                              HUMAN_GEOGRAPHY_SCHEMA_VERSION,
                              REFERENCE_SEMANTICS, bind_point_to_admin,
                              bind_point_to_land, bind_point_to_water,
                              build_admin0, build_admin0_hierarchy,
                              build_admin1, build_disputed,
                              choose_dominant_admin, repair_geometries)
from .human_geography import bidirectional_hex_audit
from .hydro_pipeline import load_osm_land
from .hydro_sources import osm_land_shp
from .islands import ground_area_perimeter
from .islands_pipeline import prepare_patch
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .projection import bbox_to_mercator, to_mercator
from .sources import sha256_of

NE_DATASETS = {
    "ne_10m_admin_0_countries": "Admin-0 Countries",
    "ne_10m_admin_0_map_units": "Admin-0 Map Units",
    "ne_10m_admin_1_states_provinces": "Admin-1 States and Provinces",
    "ne_10m_admin_0_disputed_areas": "Admin-0 Breakaway/Disputed Areas",
    "ne_10m_populated_places": "Populated Places",
    "ne_10m_ports": "Ports",
}


def _load_ne(data_dir: Path, name: str) -> gpd.GeoDataFrame:
    shp = data_dir / "raw" / name / f"{name}.shp"
    gdf = gpd.read_file(shp)
    return gdf.to_crs("EPSG:3857")


def _prep_region_bindings(name: str, grid, hex_ids, polys, water_type,
                          comp_df: pd.DataFrame, crosses: bool,
                          land_fraction=None) -> dict:
    terrestrial = np.array([w == "NONE" for w in water_type])
    water_mask = ~terrestrial
    comp_sub = comp_df[(comp_df["region"] == name)
                       & (comp_df["representation_status"]
                          == "IN_OVERLAY_UNIT")].reset_index(drop=True)
    comp_geoms = np.array(list(comp_sub["geometry"])) \
        if len(comp_sub) else np.array([], dtype=object)
    return {
        "name": name, "grid": grid, "hex_ids": list(hex_ids),
        "polys": polys, "water_type": np.asarray(water_type, dtype=object),
        "terrestrial_by_hex": dict(zip(hex_ids, terrestrial)),
        "water_by_hex": dict(zip(hex_ids, water_type)),
        "terr_polys": polys[terrestrial],
        "terr_hex_ids": [h for h, t in zip(hex_ids, terrestrial) if t],
        "terr_tree": shapely.STRtree(polys[terrestrial]),
        "water_polys": polys[water_mask],
        "water_hex_ids": [h for h, t in zip(hex_ids, terrestrial) if not t],
        "water_types": [w for w, t in zip(water_type, terrestrial) if not t],
        "water_tree": shapely.STRtree(polys[water_mask]),
        "comp_geoms": comp_geoms,
        "comp_ids": list(comp_sub["island_component_id"]) if len(comp_sub)
        else [],
        "comp_units": list(comp_sub["overlay_unit_id"]) if len(comp_sub)
        else [],
        "comp_tree": shapely.STRtree(comp_geoms) if len(comp_geoms)
        else shapely.STRtree(np.array([shapely.Point(0, 0)])),
        "crosses_dateline": crosses,
        "land_fraction_by_hex": dict(zip(hex_ids, land_fraction))
        if land_fraction is not None else {},
    }


def hex_admin_membership(region: dict, admin_df: pd.DataFrame,
                         admin_level: str, disputed_geoms,
                         run_id: str) -> tuple[list[dict], dict]:
    """Ground-metric many-to-many hex x admin membership for one region."""
    id_col = ("reference_admin0_id" if admin_level == "ADMIN0"
              else "reference_admin1_id")
    src_col = ("source_feature_id" if admin_level == "ADMIN0"
               else "source_feature_id")
    polys = region["polys"]
    hex_ids = region["hex_ids"]
    bounds = shapely.bounds(polys)
    region_box = shapely.box(bounds[:, 0].min(), bounds[:, 1].min(),
                             bounds[:, 2].max(), bounds[:, 3].max())
    sub = admin_df[shapely.intersects(
        np.array(list(admin_df["geometry"])), region_box)]
    if not len(sub):
        return [], {}
    a_geoms = np.array(list(sub["geometry"]))
    a_ids = list(sub[id_col])
    a_src = list(sub[src_col])
    tree = shapely.STRtree(a_geoms)
    disp_tree = shapely.STRtree(disputed_geoms) if len(disputed_geoms) \
        else None

    hex_ground = {}
    per_hex: dict[str, list[dict]] = {}
    rows = []
    pairs = tree.query(polys, predicate="intersects")
    inter_by_hex: dict[int, list[tuple[int, float]]] = {}
    for hi, ai in zip(*pairs):
        inter = shapely.intersection(polys[int(hi)], a_geoms[int(ai)])
        if shapely.is_empty(inter):
            continue
        g_km2, _ = ground_area_perimeter(inter)
        if g_km2 <= 1e-9:
            continue
        inter_by_hex.setdefault(int(hi), []).append((int(ai), g_km2))
    for hi, lst in sorted(inter_by_hex.items()):
        hid = hex_ids[hi]
        if hid not in hex_ground:
            hex_ground[hid], _ = ground_area_perimeter(polys[hi])
        covered = sum(a for _, a in lst)
        disp = bool(disp_tree is not None
                    and len(disp_tree.query(polys[hi],
                                            predicate="intersects")))
        for ai, g_km2 in sorted(lst):
            e = {
                "run_id": run_id, "region": region["name"], "hex_id": hid,
                "admin_level": admin_level,
                "reference_admin_id": a_ids[ai],
                "source_stable_id": str(a_src[ai]),
                "intersection_ground_km2": round(g_km2, 6),
                "share_of_admin_covered_land": round(g_km2 / covered, 6),
                "share_of_hex_ground_area": round(
                    g_km2 / hex_ground[hid], 6),
                "assignment_method": "GROUND_INTERSECTION",
                "intersects_reference_dispute": disp,
            }
            per_hex.setdefault(hid, []).append(e)
            rows.append(e)
    # Dominant flags (reference convenience only, never an owner).
    for hid, entries in per_hex.items():
        dom = choose_dominant_admin(entries)
        for e in entries:
            e["is_dominant_reference_assignment"] = \
                e["reference_admin_id"] == dom
    return rows, hex_ground


def component_admin_binding(comp_df: pd.DataFrame, admin0_df, admin1_df,
                            disputed_geoms, fallback_max_m: float,
                            run_id: str) -> pd.DataFrame:
    """Bind EVERY island component geometry to reference admin polygons.

    Works directly on component geometry — the underlying OCEAN hex is never
    touched and water authority is completely unchanged."""
    a0_geoms = np.array(list(admin0_df["geometry"]))
    a0_ids = list(admin0_df["reference_admin0_id"])
    a0_tree = shapely.STRtree(a0_geoms)
    a1_geoms = np.array(list(admin1_df["geometry"]))
    a1_ids = list(admin1_df["reference_admin1_id"])
    a1_tree = shapely.STRtree(a1_geoms)
    disp_tree = shapely.STRtree(disputed_geoms) if len(disputed_geoms) \
        else None
    rows = []
    for t in comp_df.itertuples():
        g = t.geometry
        comp_ground = t.ground_area_km2
        hits = np.sort(a0_tree.query(g, predicate="intersects"))
        best = None
        for ai in hits:
            inter = shapely.intersection(g, a0_geoms[int(ai)])
            if shapely.is_empty(inter):
                continue
            a_km2, _ = ground_area_perimeter(inter)
            if best is None or a_km2 > best[1]:
                best = (int(ai), a_km2)
        method, fb_dist = "GROUND_INTERSECTION", None
        a0 = a1 = None
        share = None
        inter_km2 = 0.0
        if best is not None and best[1] > 1e-9:
            a0 = a0_ids[best[0]]
            inter_km2 = best[1]
            share = min(1.0, inter_km2 / comp_ground) if comp_ground else None
        else:
            near = a0_tree.query(g.buffer(fallback_max_m),
                                 predicate="intersects")
            nb, nd = None, fallback_max_m
            for ai in np.sort(near):
                d = float(shapely.distance(a0_geoms[int(ai)], g))
                if d < nd:
                    nb, nd = int(ai), d
            if nb is not None:
                from .islands import ground_distance_m

                a0 = a0_ids[nb]
                method = "NEAREST_REFERENCE_POLYGON"
                fb_dist = round(ground_distance_m(a0_geoms[nb], g), 1)
            else:
                method = "UNRESOLVED"
        if a0 is not None:
            h1 = np.sort(a1_tree.query(g, predicate="intersects"))
            best1 = None
            for ai in h1:
                inter = shapely.intersection(g, a1_geoms[int(ai)])
                if shapely.is_empty(inter):
                    continue
                a_km2, _ = ground_area_perimeter(inter)
                if best1 is None or a_km2 > best1[1]:
                    best1 = (int(ai), a_km2)
            if best1 is not None and best1[1] > 1e-9:
                a1 = a1_ids[best1[0]]
        disp = bool(disp_tree is not None
                    and len(disp_tree.query(g, predicate="intersects")))
        rows.append({
            "run_id": run_id, "region": t.region,
            "component_id": t.island_component_id,
            "overlay_unit_id": t.overlay_unit_id
            if isinstance(t.overlay_unit_id, str) else None,
            "reference_admin0_id": a0,
            "reference_admin1_id": a1,
            "assignment_method": method,
            "intersection_ground_km2": round(inter_km2, 6),
            "admin_share": round(share, 6) if share is not None else None,
            "fallback_distance_m": fb_dist,
            "intersects_reference_dispute": disp,
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Settlements and ports
# --------------------------------------------------------------------------
def _admin_trees(admin0_df, admin1_df):
    a0 = {"geoms": np.array(list(admin0_df["geometry"])),
          "ids": list(admin0_df["reference_admin0_id"])}
    a0["tree"] = shapely.STRtree(a0["geoms"])
    a1 = {"geoms": np.array(list(admin1_df["geometry"])),
          "ids": list(admin1_df["reference_admin1_id"])}
    a1["tree"] = shapely.STRtree(a1["geoms"])
    return a0, a1


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if np.isnan(f) or f < 0:
        return None
    return f


def build_settlements(pp: gpd.GeoDataFrame, a0: dict, a1: dict,
                      fallback_max_m: float, run_id: str) -> pd.DataFrame:
    rows = []
    for t in pp.itertuples():
        pt = t.geometry
        b0, m0, d0 = bind_point_to_admin(pt, a0["geoms"], a0["ids"],
                                         a0["tree"], fallback_max_m)
        b1, m1, d1 = bind_point_to_admin(pt, a1["geoms"], a1["ids"],
                                         a1["tree"], fallback_max_m)
        rows.append({
            "run_id": run_id,
            "reference_settlement_id": f"setl_{int(t.NE_ID)}",
            "source_dataset": "ne_10m_populated_places",
            "source_feature_id": int(t.NE_ID),
            "name": t.NAME,
            "name_ascii": getattr(t, "NAMEASCII", None),
            "feature_class": getattr(t, "FEATURECLA", None),
            "scalerank": int(t.SCALERANK),
            "source_admin0_a3": getattr(t, "ADM0_A3", None),
            "source_admin0_name": getattr(t, "ADM0NAME", None),
            "source_admin1_name": getattr(t, "ADM1NAME", None),
            "population_max": _num(getattr(t, "POP_MAX", None)),
            "population_min": _num(getattr(t, "POP_MIN", None)),
            "population_semantics": "SOURCE_REFERENCE_ESTIMATE",
            "is_reference_admin0_capital": bool(
                _num(getattr(t, "ADM0CAP", 0)) == 1.0),
            "capital_semantics": REFERENCE_SEMANTICS,
            "lon": float(t.LONGITUDE), "lat": float(t.LATITUDE),
            "x_3857": float(pt.x), "y_3857": float(pt.y),
            "reference_admin0_id": b0, "admin0_binding_method": m0,
            "admin0_binding_distance_m": round(d0, 1)
            if d0 is not None else None,
            "reference_admin1_id": b1, "admin1_binding_method": m1,
            "admin1_binding_distance_m": round(d1, 1)
            if d1 is not None else None,
            "reference_semantics": REFERENCE_SEMANTICS,
            "gameplay_authoritative": False,
        })
    return pd.DataFrame(rows).sort_values(
        "reference_settlement_id").reset_index(drop=True)


def build_ports(pg: gpd.GeoDataFrame, a0: dict, a1: dict,
                fallback_max_m: float, run_id: str) -> pd.DataFrame:
    rows = []
    for t in pg.itertuples():
        pt = t.geometry
        b0, m0, d0 = bind_point_to_admin(pt, a0["geoms"], a0["ids"],
                                         a0["tree"], fallback_max_m)
        rows.append({
            "run_id": run_id,
            "reference_port_id": f"port_{int(t.ne_id)}",
            "source_dataset": "ne_10m_ports",
            "source_feature_id": int(t.ne_id),
            "name": t.name,
            "feature_class": getattr(t, "featurecla", None),
            "scalerank": int(t.scalerank),
            "natlscale": _num(getattr(t, "natlscale", None)),
            "website": getattr(t, "website", None) or None,
            # These fields do not exist in NE 10m ports 5.0.0 — kept as
            # explicit nulls per spec (never invented).
            "port_type_if_available": None,
            "activity_level_if_available": None,
            "x_3857": float(pt.x), "y_3857": float(pt.y),
            "reference_admin0_id": b0, "admin0_binding_method": m0,
            "admin0_binding_distance_m": round(d0, 1)
            if d0 is not None else None,
            "port_semantics": "REFERENCE_COMMERCIAL_PORT_NOT_NAVAL_BASE",
            "reference_semantics": REFERENCE_SEMANTICS,
            "gameplay_authoritative": False,
        })
    return pd.DataFrame(rows).sort_values(
        "reference_port_id").reset_index(drop=True)


def bind_points_to_regions(df: pd.DataFrame, regions: dict,
                           land_snap_m: float,
                           water_snap_m: float | None = None) -> pd.DataFrame:
    """Assign each point to the region whose hex set contains it (exact,
    dateline-safe: containment is via the point's own hex id) and run land
    (and optionally water) binding there. Points outside every covered
    region are formally OUT_OF_REGION_COVERAGE, never guessed."""
    out = {"binding_region": [], "coverage_status": [],
           "land_binding_kind": [], "land_binding_method": [],
           "terrestrial_hex_id": [], "island_component_id": [],
           "overlay_unit_id": [], "land_binding_distance_m": []}
    if water_snap_m is not None:
        out.update({"water_access_hex_id": [], "water_access_type": [],
                    "water_access_distance_m": []})
    for x, y in zip(df["x_3857"], df["y_3857"]):
        pt = shapely.Point(x, y)
        rname = None
        for cand, reg in regions.items():
            g = reg["grid"]
            q, r = g.xy_to_axial(x, y)
            if g.hex_id(int(q), int(r)) in reg["terrestrial_by_hex"]:
                rname = cand
                break
        if rname is None:
            out["binding_region"].append(None)
            out["coverage_status"].append("OUT_OF_REGION_COVERAGE")
            out["land_binding_kind"].append(None)
            out["land_binding_method"].append(None)
            out["terrestrial_hex_id"].append(None)
            out["island_component_id"].append(None)
            out["overlay_unit_id"].append(None)
            out["land_binding_distance_m"].append(None)
            if water_snap_m is not None:
                out["water_access_hex_id"].append(None)
                out["water_access_type"].append(None)
                out["water_access_distance_m"].append(None)
            continue
        reg = regions[rname]
        lb = bind_point_to_land(pt, reg, land_snap_m)
        out["binding_region"].append(rname)
        out["coverage_status"].append("IN_REGION")
        out["land_binding_kind"].append(lb["land_binding_kind"])
        out["land_binding_method"].append(lb["binding_method"])
        out["terrestrial_hex_id"].append(lb["terrestrial_hex_id"])
        out["island_component_id"].append(lb["island_component_id"])
        out["overlay_unit_id"].append(lb["overlay_unit_id"])
        out["land_binding_distance_m"].append(lb["binding_distance_m"])
        if water_snap_m is not None:
            wb = bind_point_to_water(pt, reg, water_snap_m)
            out["water_access_hex_id"].append(wb["water_access_hex_id"])
            out["water_access_type"].append(wb["water_access_type"])
            out["water_access_distance_m"].append(
                wb["water_access_distance_m"])
    for k, v in out.items():
        df[k] = v
    return df


# --------------------------------------------------------------------------
# Renders (reference visualisation only)
# --------------------------------------------------------------------------
WATER_FILL = {"OCEAN": "#a8c8e8", "LAKE": "#7fb2e0", "NONE": "#e8e2d0"}


def _hex_coll(ax, polys, colors, lw=0.15, ec="#888888"):
    from matplotlib.collections import PolyCollection

    verts = [np.asarray(p.exterior.coords)[:-1] for p in polys]
    ax.add_collection(PolyCollection(verts, facecolors=colors,
                                     edgecolors=ec, linewidths=lw))


def _admin_palette(ids):
    import matplotlib

    uniq = sorted({i for i in ids if i})
    cmap = matplotlib.colormaps["tab20"]
    return {u: cmap(i % 20) for i, u in enumerate(uniq)}


def _plot_admin_boundaries(ax, admin_df, box, color="#333333", lw=0.9,
                           shift=None):
    geoms = [g for g in admin_df["geometry"]
             if shapely.intersects(g, box)]
    for g in geoms:
        b = shapely.intersection(shapely.boundary(g), box)
        if shapely.is_empty(b):
            continue
        if shift is not None:
            b = shapely.transform(b, shift)
        parts = shapely.get_parts(b) if b.geom_type.startswith("Multi") \
            or b.geom_type == "GeometryCollection" else [b]
        for p in parts:
            if p.geom_type == "LineString":
                xs, ys = zip(*p.coords)
                ax.plot(xs, ys, color=color, linewidth=lw, zorder=5)


def _save(fig, path):
    fig.savefig(path, dpi=140, bbox_inches="tight")
    import matplotlib.pyplot as plt

    plt.close(fig)


def render_region_admin(path, region, mem_df, admin0_df, admin1_df,
                        settl, ports, title, color_level="ADMIN1",
                        zoom_3857=None, label_settlements=False,
                        wrap=False):
    """Generic reference-admin region render. wrap=True shifts x<0 geometry
    by +world width for DISPLAY only (same rule as the 006R Fiji fix)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from .islands import WORLD_WIDTH_M

    def wx(x):
        return x + WORLD_WIDTH_M if (wrap and x < 0) else x

    shift = (lambda xy: np.column_stack(
        [np.where(xy[:, 0] < 0, xy[:, 0] + WORLD_WIDTH_M, xy[:, 0]),
         xy[:, 1]])) if wrap else None

    polys = region["polys"]
    disp_polys = np.array([shapely.transform(p, shift) for p in polys]) \
        if wrap else polys
    dom = mem_df[(mem_df["region"] == region["name"])
                 & (mem_df["admin_level"] == color_level)
                 & (mem_df["is_dominant_reference_assignment"])]
    dom_by_hex = dict(zip(dom["hex_id"], dom["reference_admin_id"]))
    pal = _admin_palette(dom_by_hex.values())
    colors = []
    for hid, w in zip(region["hex_ids"], region["water_type"]):
        if w != "NONE":
            colors.append(WATER_FILL.get(w, WATER_FILL["OCEAN"]))
        else:
            colors.append(pal.get(dom_by_hex.get(hid), "#cccccc"))
    fig, ax = plt.subplots(figsize=(11, 11))
    _hex_coll(ax, disp_polys, colors)
    b = shapely.bounds(disp_polys)
    box = shapely.box(shapely.bounds(polys)[:, 0].min(),
                      b[:, 1].min(),
                      shapely.bounds(polys)[:, 2].max(), b[:, 3].max())
    bdf = admin1_df if color_level == "ADMIN1" else admin0_df
    _plot_admin_boundaries(ax, bdf, box, shift=shift)
    _plot_admin_boundaries(ax, admin0_df, box, color="#000000", lw=1.4,
                           shift=shift)
    if settl is not None and len(settl):
        xs = [wx(x) for x in settl["x_3857"]]
        ax.scatter(xs, settl["y_3857"], s=14, c="#b40000", zorder=6)
        if label_settlements:
            for x, y, n in zip(xs, settl["y_3857"], settl["name"]):
                ax.annotate(n, (x, y), fontsize=7, zorder=7,
                            xytext=(3, 3), textcoords="offset points")
    if ports is not None and len(ports):
        xs = [wx(x) for x in ports["x_3857"]]
        ax.scatter(xs, ports["y_3857"], s=30, marker="^", c="#5500aa",
                   edgecolors="white", linewidths=0.4, zorder=6)
    if zoom_3857:
        ax.set_xlim(zoom_3857[0], zoom_3857[2])
        ax.set_ylim(zoom_3857[1], zoom_3857[3])
    else:
        ax.set_xlim(b[:, 0].min(), b[:, 2].max())
        ax.set_ylim(b[:, 1].min(), b[:, 3].max())
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=10)
    ax.set_axis_off()
    _save(fig, path)


def render_border_hexes(path, region, mem_df, admin0_df, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    m0 = mem_df[(mem_df["region"] == region["name"])
                & (mem_df["admin_level"] == "ADMIN0")]
    n_by_hex = m0.groupby("hex_id")["reference_admin_id"].nunique().to_dict()
    dom = dict(zip(
        m0[m0["is_dominant_reference_assignment"]]["hex_id"],
        m0[m0["is_dominant_reference_assignment"]]["reference_admin_id"]))
    pal = _admin_palette(dom.values())
    colors = []
    for hid, w in zip(region["hex_ids"], region["water_type"]):
        n = n_by_hex.get(hid, 0)
        if n >= 2:
            colors.append("#ff8c00")
        elif w != "NONE":
            colors.append(WATER_FILL.get(w, WATER_FILL["OCEAN"]))
        else:
            colors.append(pal.get(dom.get(hid), "#cccccc"))
    fig, ax = plt.subplots(figsize=(11, 8))
    _hex_coll(ax, region["polys"], colors, lw=0.3)
    b = shapely.bounds(region["polys"])
    box = shapely.box(b[:, 0].min(), b[:, 1].min(),
                      b[:, 2].max(), b[:, 3].max())
    _plot_admin_boundaries(ax, admin0_df, box, color="#000000", lw=1.6)
    n_multi = sum(1 for v in n_by_hex.values() if v >= 2)
    ax.set_xlim(b[:, 0].min(), b[:, 2].max())
    ax.set_ylim(b[:, 1].min(), b[:, 3].max())
    ax.set_aspect("equal")
    ax.set_title(f"{title}\norange = hex with >=2 reference admin0 "
                 f"memberships (n={n_multi})", fontsize=10)
    ax.set_axis_off()
    _save(fig, path)


def render_component_binding(path, region, comp_bind, admin0_df, title,
                             zoom_3857=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    method_color = {"GROUND_INTERSECTION": "#1a7a1a",
                    "NEAREST_REFERENCE_POLYGON": "#e07800",
                    "UNRESOLVED": "#c00000"}
    colors = [WATER_FILL.get(w, WATER_FILL["OCEAN"])
              if w != "NONE" else "#d8d2c0"
              for w in region["water_type"]]
    fig, ax = plt.subplots(figsize=(11, 11))
    _hex_coll(ax, region["polys"], colors)
    cb = comp_bind[comp_bind["region"] == region["name"]]
    m_by_comp = dict(zip(cb["component_id"], cb["assignment_method"]))
    for g, cid in zip(region["comp_geoms"], region["comp_ids"]):
        c = method_color.get(m_by_comp.get(cid), "#555555")
        parts = shapely.get_parts(g) if g.geom_type.startswith("Multi") \
            else [g]
        for p in parts:
            xs, ys = zip(*p.exterior.coords)
            ax.fill(xs, ys, color=c, zorder=6, linewidth=0)
    b = shapely.bounds(region["polys"])
    box = shapely.box(b[:, 0].min(), b[:, 1].min(),
                      b[:, 2].max(), b[:, 3].max())
    _plot_admin_boundaries(ax, admin0_df, box, color="#000000", lw=1.2)
    if zoom_3857:
        ax.set_xlim(zoom_3857[0], zoom_3857[2])
        ax.set_ylim(zoom_3857[1], zoom_3857[3])
    else:
        ax.set_xlim(b[:, 0].min(), b[:, 2].max())
        ax.set_ylim(b[:, 1].min(), b[:, 3].max())
    ax.set_aspect("equal")
    ax.set_title(f"{title}\ngreen=GROUND_INTERSECTION  "
                 "orange=NEAREST(dist recorded)  red=UNRESOLVED",
                 fontsize=10)
    ax.set_axis_off()
    _save(fig, path)


CLASS_COLORS = {"MATCHED": "#ddd6c2", "UNDERCOVERED": "#2b6cb0",
                "OVERCOVERED": "#c53030",
                "BIDIRECTIONAL_MISMATCH": "#6b46c1"}


def render_coast_admin_mismatch(path, region, cov_df, admin0_df,
                                zoom_3857, title):
    """Two panels: (1) bidirectional audit classes with the OSM coast
    authority outline vs the NE Admin-0 outline; (2) hexes the OLD one-way
    audit called FULL that the new audit reveals as mismatched. Display
    only — no geometry is modified."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    sub = cov_df[cov_df["region"] == region["name"]]
    cls_by_hex = dict(zip(sub["hex_id"], sub["coverage_class"]))
    old_by_hex = dict(zip(sub["hex_id"], sub["coverage_quality"]))
    box = shapely.box(zoom_3857[0], zoom_3857[1],
                      zoom_3857[2], zoom_3857[3])
    fig, axes = plt.subplots(1, 2, figsize=(18, 9))
    for panel, ax in enumerate(axes):
        colors = []
        for hid, w in zip(region["hex_ids"], region["water_type"]):
            if w != "NONE":
                colors.append(WATER_FILL.get(w, WATER_FILL["OCEAN"]))
            elif panel == 0:
                colors.append(CLASS_COLORS.get(cls_by_hex.get(hid),
                                               "#bbbbbb"))
            else:
                fixed = (old_by_hex.get(hid) == "FULL"
                         and cls_by_hex.get(hid) not in (None, "MATCHED"))
                colors.append("#ff8c00" if fixed else "#e5e0d0")
        _hex_coll(ax, region["polys"], colors, lw=0.25)
        coast = region["coast_land"]
        if coast is not None and not shapely.is_empty(coast):
            cb = shapely.intersection(shapely.boundary(coast), box)
            for p in shapely.get_parts(cb):
                if p.geom_type == "LineString" and len(p.coords) > 1:
                    xs, ys = zip(*p.coords)
                    ax.plot(xs, ys, color="#1a7a1a", linewidth=1.3,
                            zorder=6)
        _plot_admin_boundaries(ax, admin0_df, box, color="#000000", lw=1.1)
        ax.set_xlim(zoom_3857[0], zoom_3857[2])
        ax.set_ylim(zoom_3857[1], zoom_3857[3])
        ax.set_aspect("equal")
        ax.set_axis_off()
    axes[0].set_title("bidirectional audit classes\n"
                      "green line = OSM coast authority, "
                      "black line = NE Admin-0", fontsize=10)
    n_fixed = sum(1 for hid in sub["hex_id"]
                  if old_by_hex.get(hid) == "FULL"
                  and cls_by_hex.get(hid) != "MATCHED")
    axes[1].set_title("orange = OLD audit said FULL, new audit reveals "
                      f"mismatch (n={n_fixed} in region)", fontsize=10)
    axes[0].legend(handles=[Patch(color=v, label=k)
                            for k, v in CLASS_COLORS.items()]
                   + [Line2D([0], [0], color="#1a7a1a", label="OSM coast"),
                      Line2D([0], [0], color="#000000", label="NE Admin-0")],
                   loc="lower right", fontsize=8)
    fig.suptitle(title, fontsize=11)
    _save(fig, path)


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------
def run_human_geography(cfg: MapgenConfig, run_id: str | None = None) -> Path:
    from .sources import update_source_manifest

    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    hcfg = cfg.raw["human_geography"]
    icfg = cfg.raw["islands"]
    if run_id is None:
        run_id = f"human_geography_v1_{_dt.datetime.now():%Y%m%d}"
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    val_rows: list[dict] = []

    def _check(check_id, ok, detail):
        val_rows.append({"run_id": run_id, "check_id": check_id,
                         "pass": bool(ok), "detail": str(detail)})
        if not ok:
            warnings.append(f"VALIDATION FAIL {check_id}: {detail}")

    # ---- 1. upstream (006R) load + physical regression ------------------
    t0 = time.perf_counter()
    up_dir = cfg.output_dir / hcfg["upstream_run"]
    up_files = ["geography_hexes.parquet", "island_components.parquet",
                "island_overlays.parquet", "game_river_edges.csv"]
    up_sha_before = {f: sha256_of(up_dir / f) for f in up_files}
    geo = pd.read_parquet(up_dir / "geography_hexes.parquet")
    comps = gpd.read_parquet(up_dir / "island_components.parquet")
    overlays = gpd.read_parquet(up_dir / "island_overlays.parquet")
    edges = pd.read_csv(up_dir / "game_river_edges.csv")
    wt_counts = geo["water_type"].value_counts().to_dict()
    kov = overlays[overlays["region"] == "kanto"]
    _check("V01_upstream_hex_count", len(geo) == 5350, f"hexes={len(geo)}")
    _check("V02_upstream_water_authority",
           wt_counts == {"NONE": 2908, "OCEAN": 2428, "LAKE": 14},
           f"water_type counts={wt_counts}")
    _check("V03_upstream_river_edges",
           len(edges) == 3920 and int(edges["edge_id"].duplicated().sum()) == 0,
           f"edges={len(edges)} dup={int(edges['edge_id'].duplicated().sum())}")
    _check("V04_upstream_kanto_overlays",
           len(kov) == 6
           and round(float(kov["land_area_ground_km2"].sum()), 4) == 13.3783,
           f"kanto overlays={len(kov)} "
           f"ground_km2={round(float(kov['land_area_ground_km2'].sum()), 4)}")
    _check("V05_upstream_component_count", len(comps) == 8912,
           f"components={len(comps)}")
    admin_leak = [c for c in geo.columns
                  if "admin" in c.lower() or "country" in c.lower()]
    _check("V06_no_admin_in_geography", len(admin_leak) == 0,
           f"admin-like columns in geography_hexes: {admin_leak}")
    timings["upstream_load_s"] = time.perf_counter() - t0

    # ---- 2. NE canonical reference tables -------------------------------
    t0 = time.perf_counter()
    ne_keys = list(NE_DATASETS)
    src_manifest = update_source_manifest(cfg.data_dir, ne_keys)
    raw = {k: _load_ne(cfg.data_dir, k) for k in ne_keys}
    repair_audits = []
    for k in ["ne_10m_admin_0_countries", "ne_10m_admin_0_map_units",
              "ne_10m_admin_1_states_provinces",
              "ne_10m_admin_0_disputed_areas"]:
        raw[k], audit = repair_geometries(raw[k], k)
        repair_audits.append(audit)
    admin0 = build_admin0(raw["ne_10m_admin_0_countries"])
    hierarchy = build_admin0_hierarchy(raw["ne_10m_admin_0_map_units"],
                                       admin0)
    admin1 = build_admin1(raw["ne_10m_admin_1_states_provinces"], admin0)
    disputed = build_disputed(raw["ne_10m_admin_0_disputed_areas"])
    disputed_geoms = np.array(list(disputed["geometry"]))
    for df, name in [(admin0, "reference_admin0"),
                     (admin1, "reference_admin1"),
                     (disputed, "reference_disputed_areas")]:
        gpd.GeoDataFrame(df.assign(run_id=run_id), geometry="geometry",
                         crs="EPSG:3857").to_parquet(
            run_dir / f"{name}.parquet")
    hierarchy.assign(run_id=run_id).to_parquet(
        run_dir / "reference_admin0_hierarchy.parquet")
    _check("V07_admin0_canonical",
           len(admin0) == 258
           and admin0["reference_admin0_id"].is_unique
           and admin0["reference_admin0_id"].notna().all(),
           f"admin0 rows={len(admin0)} unique_ids="
           f"{admin0['reference_admin0_id'].is_unique}")
    iso_null = int(admin0["iso_a3"].isna().sum())
    _check("V08_admin0_iso_nulls_audited", True,
           f"iso_a3 null (source -99, kept null, audited)={iso_null}")
    h_linked = hierarchy["reference_admin0_id"].notna()
    h_valid = hierarchy.loc[h_linked, "reference_admin0_id"].isin(
        set(admin0["reference_admin0_id"])).all()
    _check("V09_hierarchy_integrity",
           len(hierarchy) == 298 and bool(h_valid),
           f"map_units={len(hierarchy)} linked={int(h_linked.sum())} "
           f"all links resolve={bool(h_valid)} "
           f"unlinked={int((~h_linked).sum())}")
    p_linked = admin1["parent_reference_admin0_id"].notna()
    p_valid = admin1.loc[p_linked, "parent_reference_admin0_id"].isin(
        set(admin0["reference_admin0_id"])).all()
    p_null_reasoned = admin1.loc[~p_linked, "parent_null_reason"].notna().all()
    _check("V10_admin1_integrity",
           len(admin1) == 4596 and admin1["reference_admin1_id"].is_unique
           and bool(p_valid) and bool(p_null_reasoned),
           f"admin1={len(admin1)} parents_resolve={bool(p_valid)} "
           f"parent_null={int((~p_linked).sum())} all_null_reasoned="
           f"{bool(p_null_reasoned)}")
    _check("V11_disputed_canonical",
           len(disputed) == 99 and disputed["reference_dispute_id"].is_unique,
           f"disputed rows={len(disputed)}")
    n_repairs = sum(a["invalid_count"] for a in repair_audits)
    all_valid = all(
        bool(shapely.is_valid(np.array(list(d["geometry"]))).all())
        for d in [admin0, admin1, disputed])
    _check("V12_geometry_validity",
           all_valid, f"post-repair all valid={all_valid}, "
           f"repaired={n_repairs} (audited in run_manifest)")
    timings["canonical_tables_s"] = time.perf_counter() - t0

    # ---- 3. regions ------------------------------------------------------
    t0 = time.perf_counter()
    hex_size = float(geo["hex_size_m"].iloc[0])
    grid = HexGrid(flat_to_flat=hex_size, orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)
    regions: dict[str, dict] = {}
    kanto_polys = grid.polygons(geo["q"].to_numpy(), geo["r"].to_numpy())
    regions["kanto"] = _prep_region_bindings(
        "kanto", grid, list(geo["hex_id"]), kanto_polys,
        list(geo["water_type"]), comps, False,
        land_fraction=list(geo["land_fraction"]))
    # OSM coast-authority land for the audit — reconstructed EXACTLY as in
    # MAPGEN-004/005/006R (same shapefile, same bbox, same clip margin);
    # never a different coastline dataset.
    regions["kanto"]["coast_land"] = load_osm_land(
        osm_land_shp(cfg.data_dir), bbox_to_mercator(cfg.bbox_wgs84),
        cfg.margin_m + 10000.0)
    for rname, rcfg in hcfg["regions"].items():
        if rname == "kanto":
            continue
        patch = (icfg["validation_patches"][rname]
                 if rcfg.get("source") == "islands_patch" else rcfg)
        pp = prepare_patch(rname, patch, cfg, hex_size)
        regions[rname] = _prep_region_bindings(
            rname, pp["grid"], list(pp["hex_ids"]), pp["polys"],
            list(pp["water_type"]), comps, pp["crosses_dateline"],
            land_fraction=list(pp["land_fraction"]))
        regions[rname]["coast_land"] = pp["land"]
    timings["regions_s"] = time.perf_counter() - t0

    # ---- 4. hex x admin membership (many-to-many, ground metric) --------
    t0 = time.perf_counter()
    mem_rows: list[dict] = []
    hex_ground_all: dict[tuple[str, str], float] = {}
    for rname, reg in regions.items():
        for level, adf in [("ADMIN0", admin0), ("ADMIN1", admin1)]:
            rows, hg = hex_admin_membership(reg, adf, level, disputed_geoms,
                                            run_id)
            mem_rows.extend(rows)
            if level == "ADMIN0":
                for h, a in hg.items():
                    hex_ground_all[(rname, h)] = a
    mem = pd.DataFrame(mem_rows)
    mem.to_parquet(run_dir / "reference_admin_hex_membership.parquet")
    timings["hex_membership_s"] = time.perf_counter() - t0
    # Coverage audit: mismatch is AUDITED, never gated at 100%.
    # MAPGEN-007R: bidirectional coast/admin geometry audit. The legacy
    # columns (land_ground_km2_est, admin0_coverage_ground_km2,
    # admin0_coverage_ratio_of_land, coverage_quality) keep their ORIGINAL
    # formulas as deprecated aliases; the new columns are the official
    # audit values. No admin or coast geometry is modified.
    t_aud = time.perf_counter()
    acfg = hcfg.get("audit", {})
    match_abs = float(acfg.get("match_abs_tolerance_km2", 0.01))
    match_rel = float(acfg.get("match_rel_tolerance", 0.005))
    cons_tol = float(acfg.get("conservation_abs_tolerance_km2", 0.001))
    alias_tol = float(acfg.get("alias_equivalence_tolerance", 0.02))
    cov_rows = []
    a0_cov = mem[mem["admin_level"] == "ADMIN0"].groupby(
        ["region", "hex_id"])["intersection_ground_km2"].sum().to_dict()
    a0_geoms_all = np.array(list(admin0["geometry"]))
    a0_tree_all = shapely.STRtree(a0_geoms_all)
    for rname, reg in regions.items():
        coast = reg["coast_land"]
        coast_parts = (shapely.get_parts(coast)
                       if coast is not None and not shapely.is_empty(coast)
                       else np.array([], dtype=object))
        ptree = shapely.STRtree(coast_parts) if len(coast_parts) else None
        for hid, w, poly in zip(reg["hex_ids"], reg["water_type"],
                                reg["polys"]):
            if w != "NONE":
                continue
            hg = hex_ground_all.get((rname, hid))
            if hg is None:
                hg, _ = ground_area_perimeter(poly)
            lf = float(reg["land_fraction_by_hex"].get(hid, 1.0))
            cov = float(a0_cov.get((rname, hid), 0.0))
            land_km2 = hg * lf
            ratio = cov / land_km2 if land_km2 > 0 else None
            if cov <= 0:
                quality = "NONE"
            elif ratio is not None and ratio >= 0.98:
                quality = "FULL"
            elif ratio is not None and ratio >= 0.5:
                quality = "PARTIAL"
            else:
                quality = "LOW"
            if ptree is not None:
                hits = np.sort(ptree.query(poly, predicate="intersects"))
                A = (shapely.union_all(coast_parts[hits])
                     if len(hits) else None)
            else:
                A = None
            a_hits = np.sort(a0_tree_all.query(poly,
                                               predicate="intersects"))
            audit = bidirectional_hex_audit(poly, A, a0_geoms_all[a_hits],
                                            match_abs, match_rel)
            cov_rows.append({
                "run_id": run_id, "region": rname, "hex_id": hid,
                "hex_ground_km2": round(hg, 6),
                "land_fraction": round(lf, 6),
                # ---- deprecated aliases (original formulas, will be
                # removed in a future schema major bump) ----
                "land_ground_km2_est": round(land_km2, 6),
                "admin0_coverage_ground_km2": round(cov, 6),
                "admin0_coverage_ratio_of_land": round(ratio, 6)
                if ratio is not None else None,
                "coverage_quality": quality,
                # ---- official bidirectional audit (MAPGEN-007R) ----
                **audit,
            })
    cov_df = pd.DataFrame(cov_rows)
    cov_df.to_csv(run_dir / "admin_coverage_audit.csv", index=False)
    timings["bidirectional_audit_s"] = time.perf_counter() - t_aud
    # V13: share sums on fully-inland terrestrial hexes ~ 1.
    m0 = mem[mem["admin_level"] == "ADMIN0"]
    inland = cov_df[(cov_df["region"] == "kanto")
                    & (cov_df["land_fraction"] >= 0.999)]["hex_id"]
    sums = m0[m0["hex_id"].isin(set(inland))].groupby(
        "hex_id")["share_of_hex_ground_area"].sum()
    _check("V13_inland_share_sum",
           len(sums) > 0 and float(sums.min()) >= 0.985
           and float(sums.max()) <= 1.015,
           f"kanto inland hexes={len(sums)} share-sum "
           f"min={float(sums.min()):.6f} max={float(sums.max()):.6f}")
    over = m0.groupby(["region", "hex_id"])["share_of_hex_ground_area"].sum()
    _check("V14_share_never_exceeds_hex",
           float(over.max()) <= 1.02,
           f"max admin0 share-sum per hex={float(over.max()):.6f}")
    bb = m0[m0["region"] == "border_benelux"]
    multi = bb.groupby("hex_id")["reference_admin_id"].nunique()
    n_multi = int((multi >= 2).sum())
    _check("V15_border_many_to_many", n_multi >= 1,
           f"border_benelux hexes with >=2 admin0 memberships={n_multi} "
           f"of {len(multi)}")
    dom_counts = m0[m0["is_dominant_reference_assignment"]].groupby(
        ["region", "hex_id"]).size()
    _check("V16_dominant_unique",
           int(dom_counts.max()) == 1 and len(dom_counts) == len(over),
           f"hexes with admin0={len(over)} dominant-marked="
           f"{len(dom_counts)} max-per-hex={int(dom_counts.max())}")
    q_counts = cov_df["coverage_quality"].value_counts().to_dict()
    _check("V17_coverage_audited_not_gated",
           len(cov_df) == sum(1 for r in regions.values()
                              for w in r["water_type"] if w == "NONE"),
           f"terrestrial hexes audited={len(cov_df)} quality={q_counts}")

    # ---- 5. island component -> reference admin (ALL components) --------
    t0 = time.perf_counter()
    comp_bind = component_admin_binding(
        comps, admin0, admin1, disputed_geoms,
        float(hcfg["component_admin_fallback_max_km"]) * 1000.0, run_id)
    comp_bind.to_parquet(run_dir / "island_component_reference_admin.parquet")
    meth = comp_bind["assignment_method"].value_counts().to_dict()
    bound = comp_bind["reference_admin0_id"].notna()
    ref_ok = comp_bind.loc[bound, "reference_admin0_id"].isin(
        set(admin0["reference_admin0_id"])).all()
    _check("V18_component_binding_complete",
           len(comp_bind) == 8912 and bool(ref_ok),
           f"components bound={len(comp_bind)} methods={meth} "
           f"refs_resolve={bool(ref_ok)} "
           f"unresolved={int((~bound).sum())}")
    fb = comp_bind[comp_bind["assignment_method"]
                   == "NEAREST_REFERENCE_POLYGON"]
    fb_max = float(fb["fallback_distance_m"].max()) if len(fb) else 0.0
    _check("V19_component_fallback_distances",
           bool((fb["fallback_distance_m"].notna()).all()) if len(fb)
           else True,
           f"nearest-fallback n={len(fb)} max_ground_m={fb_max:.0f} "
           "(all recorded, <=30km by construction)")
    jp = admin0.loc[admin0["adm0_a3"] == "JPN", "reference_admin0_id"]
    jp_id = jp.iloc[0] if len(jp) else None
    kb = comp_bind[(comp_bind["region"] == "kanto")
                   & comp_bind["component_id"].isin(
                       set(comps[comps["representation_status"]
                                 == "IN_OVERLAY_UNIT"]
                           ["island_component_id"]))]
    kb_jp = float((kb["reference_admin0_id"] == jp_id).mean()) if len(kb) \
        else 0.0
    _check("V20_kanto_overlay_components_jpn", kb_jp >= 0.95,
           f"kanto IN_OVERLAY_UNIT components={len(kb)} bound to JPN "
           f"share={kb_jp:.4f}")
    timings["component_binding_s"] = time.perf_counter() - t0

    # ---- 6. settlements + ports -----------------------------------------
    t0 = time.perf_counter()
    a0t, a1t = _admin_trees(admin0, admin1)
    pt_fb_m = float(hcfg["point_admin_fallback_max_km"]) * 1000.0
    settl = build_settlements(raw["ne_10m_populated_places"], a0t, a1t,
                              pt_fb_m, run_id)
    settl = bind_points_to_regions(
        settl, regions,
        float(hcfg["settlement_land_snap_max_km"]) * 1000.0)
    gpd.GeoDataFrame(
        settl, geometry=gpd.points_from_xy(settl["x_3857"],
                                           settl["y_3857"]),
        crs="EPSG:3857").to_parquet(run_dir / "reference_settlements.parquet")
    ports = build_ports(raw["ne_10m_ports"], a0t, a1t, pt_fb_m, run_id)
    ports = bind_points_to_regions(
        ports, regions,
        float(hcfg["port_land_snap_max_km"]) * 1000.0,
        water_snap_m=float(hcfg["port_water_snap_max_km"]) * 1000.0)
    gpd.GeoDataFrame(
        ports, geometry=gpd.points_from_xy(ports["x_3857"],
                                           ports["y_3857"]),
        crs="EPSG:3857").to_parquet(run_dir / "reference_ports.parquet")
    _check("V21_settlements_canonical",
           len(settl) == len(raw["ne_10m_populated_places"])
           and settl["reference_settlement_id"].is_unique
           and (settl["population_semantics"]
                == "SOURCE_REFERENCE_ESTIMATE").all()
           and (~settl["gameplay_authoritative"]).all(),
           f"settlements={len(settl)} unique ids, semantics constant, "
           "gameplay_authoritative all False")
    s_bound = settl["reference_admin0_id"].notna()
    s_ref_ok = settl.loc[s_bound, "reference_admin0_id"].isin(
        set(admin0["reference_admin0_id"])).all()
    s_meth = settl["admin0_binding_method"].value_counts().to_dict()
    s_near = settl[settl["admin0_binding_method"]
                   == "NEAREST_REFERENCE_POLYGON"]
    _check("V22_settlement_admin_binding",
           bool(s_ref_ok)
           and (s_near["admin0_binding_distance_m"].notna().all()
                if len(s_near) else True),
           f"admin0 methods={s_meth} refs_resolve={bool(s_ref_ok)} "
           f"unresolved={int((~s_bound).sum())}")
    _check("V23_ports_canonical",
           len(ports) == len(raw["ne_10m_ports"])
           and ports["reference_port_id"].is_unique
           and ports["port_type_if_available"].isna().all()
           and ports["activity_level_if_available"].isna().all(),
           f"ports={len(ports)} unique ids; port_type/activity absent in "
           "NE 5.0.0 source -> all null (documented)")
    # Kanto settlement catalogue: only candidates PRESENT in the source.
    cand = list(hcfg.get("kanto_settlement_candidates", []))
    cat_rows = []
    in_kanto = settl["binding_region"] == "kanto"
    for name in cand:
        m = settl[(settl["source_admin0_a3"] == "JPN")
                  & ((settl["name"] == name)
                     | (settl["name_ascii"] == name))]
        if not len(m):
            cat_rows.append({"run_id": run_id, "candidate": name,
                             "present_in_source": False,
                             "reference_settlement_id": None,
                             "in_kanto_region": None,
                             "land_binding_kind": None,
                             "terrestrial_hex_id": None,
                             "population_max": None})
            continue
        s = m.iloc[0]
        cat_rows.append({
            "run_id": run_id, "candidate": name,
            "present_in_source": True,
            "reference_settlement_id": s["reference_settlement_id"],
            "in_kanto_region": bool(s["binding_region"] == "kanto"),
            "land_binding_kind": s["land_binding_kind"],
            "terrestrial_hex_id": s["terrestrial_hex_id"],
            "population_max": s["population_max"],
        })
    cat = pd.DataFrame(cat_rows)
    cat.to_csv(run_dir / "kanto_settlement_catalogue.csv", index=False)
    present = cat[cat["present_in_source"]]
    ok_bound = present[(present["in_kanto_region"])
                       & (present["land_binding_kind"]
                          == "TERRESTRIAL_HEX")]
    _check("V24_kanto_settlement_catalogue",
           len(present) >= 1 and len(ok_bound) == len(present),
           f"candidates={len(cand)} present_in_source={len(present)} "
           f"bound TERRESTRIAL_HEX in kanto={len(ok_bound)} "
           f"absent={sorted(cat[~cat['present_in_source']]['candidate'])}")
    kanto_ports = ports[(ports["binding_region"] == "kanto")]
    dual = kanto_ports[
        kanto_ports["land_binding_kind"].isin(
            ["TERRESTRIAL_HEX", "ISLAND_COMPONENT_OVERLAY"])
        & kanto_ports["water_access_hex_id"].notna()]
    _check("V25_port_dual_access_positive", len(dual) >= 1,
           f"kanto ports in region={len(kanto_ports)} with land+water "
           f"access={len(dual)} e.g. "
           f"{sorted(dual['name'].head(3)) if len(dual) else '-'}")
    s_unres = settl[in_kanto
                    & (settl["land_binding_kind"] == "UNRESOLVED")]
    _check("V26_unresolved_is_formal_state", True,
           f"UNRESOLVED land bindings kanto settlements={len(s_unres)}, "
           f"out-of-coverage settlements="
           f"{int((settl['coverage_status'] == 'OUT_OF_REGION_COVERAGE').sum())}"
           " (formal states, never silently snapped)")
    timings["points_s"] = time.perf_counter() - t0

    # ---- 7. dateline checks ---------------------------------------------
    fj = m0[m0["region"] == "fiji_dateline"]
    fj_id = None
    fj_row = admin0.loc[admin0["adm0_a3"] == "FJI", "reference_admin0_id"]
    if len(fj_row):
        fj_id = fj_row.iloc[0]
    fj_dom = fj[fj["is_dominant_reference_assignment"]]
    fj_hex_x = {h: regions["fiji_dateline"]["polys"][
        regions["fiji_dateline"]["hex_ids"].index(h)].centroid.x
        for h in fj["hex_id"].unique()}
    west = sum(1 for x in fj_hex_x.values() if x < 0)
    east = sum(1 for x in fj_hex_x.values() if x > 0)
    _check("V27_dateline_membership_both_sides",
           west >= 1 and east >= 1
           and len(fj_dom) > 0
           and bool((fj_dom["reference_admin_id"] == fj_id).all()),
           f"fiji membership hexes east(+x)={east} west(-x)={west}, "
           f"dominant admin0 all FJI={bool((fj_dom['reference_admin_id'] == fj_id).all())}")
    fj_comps = comp_bind[comp_bind["region"] == "fiji_dateline"]
    fj_bound = fj_comps["reference_admin0_id"].notna()
    fj_fji = float((fj_comps.loc[fj_bound, "reference_admin0_id"]
                    == fj_id).mean()) if int(fj_bound.sum()) else 0.0
    fj_dist = fj_comps["fallback_distance_m"].dropna()
    _check("V28_dateline_component_binding",
           fj_fji >= 0.95
           and (float(fj_dist.max()) < 100_000 if len(fj_dist) else True),
           f"fiji components={len(fj_comps)} bound FJI share={fj_fji:.4f} "
           f"max fallback dist={float(fj_dist.max()) if len(fj_dist) else 0:.0f}m "
           "(no 40,000km dateline artifacts)")

    # ---- 8. renders ------------------------------------------------------
    t0 = time.perf_counter()
    s_k = settl[settl["binding_region"] == "kanto"]
    p_k = ports[ports["binding_region"] == "kanto"]
    s_cand = s_k[s_k["name"].isin(cand) | s_k["name_ascii"].isin(cand)]
    render_region_admin(
        run_dir / "human_geography_kanto.png", regions["kanto"], mem,
        admin0, admin1, s_cand, p_k,
        "MAPGEN-007 kanto: hexes by DOMINANT reference admin1 "
        "(REFERENCE ONLY, not gameplay ownership)",
        label_settlements=True)
    tb = (*to_mercator(139.55, 35.15), *to_mercator(140.35, 35.80))
    render_region_admin(
        run_dir / "human_geography_tokyo_bay.png", regions["kanto"], mem,
        admin0, admin1, s_k, p_k,
        "Tokyo Bay: reference settlements (red) + reference ports (purple)",
        zoom_3857=(tb[0], tb[1], tb[2], tb[3]), label_settlements=True)
    render_border_hexes(
        run_dir / "human_geography_border_hex.png",
        regions["border_benelux"], mem, admin0,
        "border_benelux: many-to-many reference admin0 hex membership "
        "(BEL/NLD)")
    render_region_admin(
        run_dir / "human_geography_malta.png", regions["malta"], mem,
        admin0, admin1,
        settl[settl["binding_region"] == "malta"],
        ports[ports["binding_region"] == "malta"],
        "malta: reference admin binding (island region, admin0 level)",
        color_level="ADMIN0")
    render_region_admin(
        run_dir / "human_geography_fiji_dateline.png",
        regions["fiji_dateline"], mem, admin0, admin1,
        settl[settl["binding_region"] == "fiji_dateline"],
        ports[ports["binding_region"] == "fiji_dateline"],
        "fiji_dateline: +-180 crossing, wrap DISPLAY frame "
        "(storage stays original frame)",
        color_level="ADMIN0", wrap=True)
    izu = (*to_mercator(138.9, 34.4), *to_mercator(140.3, 35.75))
    render_component_binding(
        run_dir / "human_geography_island_component_admin_binding.png",
        regions["kanto"], comp_bind, admin0,
        "kanto overlay island components -> reference admin binding "
        "(component-level; overlay unit is NEVER an admin unit)",
        zoom_3857=(izu[0], izu[1], izu[2], izu[3]))
    render_coast_admin_mismatch(
        run_dir / "human_geography_admin_coast_mismatch.png",
        regions["kanto"], cov_df, admin0,
        (*to_mercator(139.55, 35.15), *to_mercator(140.35, 35.80)),
        "Tokyo Bay: bidirectional OSM-coast vs NE-Admin0 audit "
        "(MAPGEN-007R; audit only, no geometry modified)")
    from PIL import Image

    img_names = [
        "human_geography_kanto.png", "human_geography_tokyo_bay.png",
        "human_geography_border_hex.png", "human_geography_malta.png",
        "human_geography_fiji_dateline.png",
        "human_geography_island_component_admin_binding.png",
        "human_geography_admin_coast_mismatch.png"]
    aspects = {}
    for n in img_names:
        with Image.open(run_dir / n) as im:
            w, h = im.size
        aspects[n] = round(w / h, 3)
    _check("V29_renders",
           all((run_dir / n).exists() for n in img_names)
           and all(0.3 <= a <= 4.0 for a in aspects.values()),
           f"{len(img_names)} renders, aspect ratios={aspects} "
           "(fiji wrap-displayed, not a world-wide strip)")
    timings["render_s"] = time.perf_counter() - t0

    # ---- 9. immutability + versions -------------------------------------
    up_sha_after = {f: sha256_of(up_dir / f) for f in up_files}
    _check("V30_upstream_immutable",
           up_sha_before == up_sha_after
           and not (run_dir / "geography_hexes.parquet").exists(),
           "006R inputs byte-identical before/after (SHA-256) and "
           "geography_hexes NOT rewritten by this stage")
    _check("V31_namespace_versions",
           HUMAN_GEOGRAPHY_SCHEMA_VERSION == "1.1.0"
           and HUMAN_GEOGRAPHY_ALGORITHM_VERSION == "1.0.1"
           and REFERENCE_SEMANTICS == "CONTEMPORARY_DE_FACTO_REFERENCE",
           f"human_geography_schema={HUMAN_GEOGRAPHY_SCHEMA_VERSION} "
           f"algorithm={HUMAN_GEOGRAPHY_ALGORITHM_VERSION} "
           f"semantics={REFERENCE_SEMANTICS}")

    # Spec 29: every cross-table link resolves — broken references = 0.
    broken = 0
    hex_sets = {r: set(reg["hex_ids"]) for r, reg in regions.items()}
    comp_ids_all = set(comps["island_component_id"])
    unit_ids_all = set(overlays["overlay_unit_id"])
    a0_ids_all = set(admin0["reference_admin0_id"])
    a1_ids_all = set(admin1["reference_admin1_id"])
    broken += int(sum(h not in hex_sets[r]
                      for r, h in zip(mem["region"], mem["hex_id"])))
    broken += int((~mem[mem["admin_level"] == "ADMIN0"]
                   ["reference_admin_id"].isin(a0_ids_all)).sum())
    broken += int((~mem[mem["admin_level"] == "ADMIN1"]
                   ["reference_admin_id"].isin(a1_ids_all)).sum())
    broken += int((~comp_bind["component_id"].isin(comp_ids_all)).sum())
    for df in (comp_bind, settl, ports):
        u = df["overlay_unit_id"].dropna()
        broken += int((~u.isin(unit_ids_all)).sum())
        a = df["reference_admin0_id"].dropna()
        broken += int((~a.isin(a0_ids_all)).sum())
    for df in (settl, ports):
        sub = df[df["terrestrial_hex_id"].notna()]
        broken += int(sum(h not in hex_sets[r] for r, h in
                          zip(sub["binding_region"],
                              sub["terrestrial_hex_id"])))
        c = df["island_component_id"].dropna()
        broken += int((~c.isin(comp_ids_all)).sum())
    pw = ports[ports["water_access_hex_id"].notna()]
    broken += int(sum(h not in hex_sets[r] for r, h in
                      zip(pw["binding_region"], pw["water_access_hex_id"])))
    p1 = admin1["parent_reference_admin0_id"].dropna()
    broken += int((~p1.isin(a0_ids_all)).sum())
    _check("V32_referential_integrity", broken == 0,
           f"broken cross-table references={broken} (membership hex ids, "
           "admin refs, component ids, overlay unit ids, settlement/port "
           "hex+component refs, admin1 parents)")

    # ---- MAPGEN-007R: bidirectional audit validations -------------------
    area_cols = ["coast_land_ground_km2", "admin0_union_ground_km2",
                 "matched_ground_km2", "undercovered_ground_km2",
                 "overcovered_ground_km2", "symmetric_difference_ground_km2"]
    e1 = (cov_df["coast_land_ground_km2"] - cov_df["matched_ground_km2"]
          - cov_df["undercovered_ground_km2"]).abs()
    _check("V33_coast_conservation", float(e1.max()) <= cons_tol,
           f"coast = matched + undercovered on all {len(cov_df)} hexes, "
           f"max abs error={float(e1.max()):.6f} km2 (tol {cons_tol})")
    e2 = (cov_df["admin0_union_ground_km2"] - cov_df["matched_ground_km2"]
          - cov_df["overcovered_ground_km2"]).abs()
    _check("V34_admin_conservation", float(e2.max()) <= cons_tol,
           f"admin_union = matched + overcovered on all hexes, "
           f"max abs error={float(e2.max()):.6f} km2 (tol {cons_tol})")
    e3 = (cov_df["symmetric_difference_ground_km2"]
          - cov_df["undercovered_ground_km2"]
          - cov_df["overcovered_ground_km2"]).abs()
    _check("V35_symmetric_difference_conservation",
           float(e3.max()) <= cons_tol,
           f"symdiff = under + over, max abs error={float(e3.max()):.9f}")
    lcf = cov_df["land_coverage_fraction"].dropna()
    _check("V36_coverage_fraction_bounds",
           len(lcf) == len(cov_df) and float(lcf.min()) >= 0.0
           and float(lcf.max()) <= 1.0,
           f"land_coverage_fraction in [0,1] for all {len(lcf)} hexes: "
           f"min={float(lcf.min()):.6f} max={float(lcf.max()):.6f}")
    both = cov_df[["admin0_coverage_ratio_of_land",
                   "admin0_to_coast_land_area_ratio"]].dropna()
    e4 = (both["admin0_coverage_ratio_of_land"]
          - both["admin0_to_coast_land_area_ratio"]).abs()
    _check("V37_deprecated_alias_equivalence",
           float(e4.max()) <= alias_tol,
           f"old-formula ratio vs geometry area ratio: n={len(both)} "
           f"max abs diff={float(e4.max()):.6f} (tol {alias_tol}); alias "
           "kept with UNCHANGED old formula, deprecated")
    classes = {"MATCHED", "UNDERCOVERED", "OVERCOVERED",
               "BIDIRECTIONAL_MISMATCH"}
    cls_counts = cov_df["coverage_class"].value_counts().to_dict()
    _check("V38_classification_exhaustive",
           cov_df["coverage_class"].notna().all()
           and set(cls_counts) <= classes,
           f"every audited hex has exactly one class: {cls_counts}")
    neg = int((cov_df[area_cols] < 0).sum().sum())
    _check("V39_no_negative_areas", neg == 0,
           f"negative audit areas={neg}")
    bad_nan = int(cov_df[area_cols].isna().sum().sum())
    frac_cols = ["land_coverage_fraction", "admin0_to_coast_land_area_ratio",
                 "undercoverage_fraction", "overcoverage_fraction",
                 "symmetric_difference_fraction"]
    zero_coast = cov_df["coast_land_ground_km2"] <= 0
    bad_frac_nan = int(cov_df.loc[~zero_coast, frac_cols].isna().sum().sum())
    _check("V40_no_unexpected_nan",
           bad_nan == 0 and bad_frac_nan == 0
           and not np.isinf(cov_df[area_cols].to_numpy()).any(),
           f"NaN in area cols={bad_nan}, NaN in fraction cols with "
           f"coast_land>0={bad_frac_nan}, inf=0 "
           f"(fractions are null only for {int(zero_coast.sum())} "
           "zero-coast-land hexes, allowed by spec)")
    # Canonical geography/admin/binding results must equal approved 007.
    base_dir = cfg.output_dir / hcfg["regression_baseline_run"]
    canon = ["reference_admin0.parquet", "reference_admin0_hierarchy.parquet",
             "reference_admin1.parquet", "reference_disputed_areas.parquet",
             "reference_admin_hex_membership.parquet",
             "island_component_reference_admin.parquet",
             "reference_settlements.parquet", "reference_ports.parquet"]
    mismatched = []
    for f in canon:
        geof = f not in ("reference_admin0_hierarchy.parquet",
                         "reference_admin_hex_membership.parquet",
                         "island_component_reference_admin.parquet")
        rd = gpd.read_parquet if geof else pd.read_parquet
        try:
            a = rd(base_dir / f).drop(columns=["run_id"])
            b = rd(run_dir / f).drop(columns=["run_id"])
            same = a.equals(b)
            if "geometry" in a.columns:
                same = same and a.geometry.equals(b.geometry)
        except Exception as exc:  # missing baseline is a hard fail
            same = False
            mismatched.append(f"{f}: {exc}")
        if not same and f not in [m.split(":")[0] for m in mismatched]:
            mismatched.append(f)
    _check("V41_canonical_tables_match_007", not mismatched,
           f"8 canonical tables normalized-equal to {base_dir.name} "
           f"(run_id excluded); mismatches={mismatched or 0}")
    base_mem = pd.read_parquet(
        base_dir / "reference_admin_hex_membership.parquet")
    bm = base_mem[(base_mem["region"] == "border_benelux")
                  & (base_mem["admin_level"] == "ADMIN0")]
    base_multi = set(bm.groupby("hex_id")["reference_admin_id"]
                     .nunique().loc[lambda s: s >= 2].index)
    cur_multi = set(multi.loc[multi >= 2].index)
    _check("V42_border_multi_admin_unchanged",
           base_multi == cur_multi and len(cur_multi) == 37,
           f"border_benelux multi-admin0 hex set unchanged: "
           f"{len(cur_multi)}/37, symmetric diff="
           f"{len(base_multi ^ cur_multi)}")
    # Coast-authority snapshot proof: the audit's A-geometry reproduces the
    # geography land_fraction of MAPGEN-004/006R (same OSM source, same
    # loader, same margins) — not a different coastline dataset.
    kc = cov_df[cov_df["region"] == "kanto"]
    gf = (kc["coast_land_ground_km2"] / kc["hex_ground_km2"])
    e5 = (gf - kc["land_fraction"]).abs()
    _check("V43_coast_authority_snapshot",
           float(e5.max()) <= 0.01,
           f"recomputed OSM coast land fraction vs geography_hexes "
           f"land_fraction (kanto, n={len(kc)}): max abs diff="
           f"{float(e5.max()):.6f}, p99={float(e5.quantile(0.99)):.6f} "
           "(same authority/snapshot as MAPGEN-004/005/006R)")

    val = pd.DataFrame(val_rows)
    val.to_csv(run_dir / "human_geography_validation.csv", index=False)

    # ---- 10. summary / manifest / README --------------------------------
    n_pass = int(val["pass"].sum())
    summary_rows = [
        ("human_geography_schema_version", HUMAN_GEOGRAPHY_SCHEMA_VERSION),
        ("human_geography_algorithm_version",
         HUMAN_GEOGRAPHY_ALGORITHM_VERSION),
        ("reference_semantics", REFERENCE_SEMANTICS),
        ("upstream_run", hcfg["upstream_run"]),
        ("admin0_features", len(admin0)),
        ("admin0_map_units", len(hierarchy)),
        ("admin1_features", len(admin1)),
        ("disputed_features", len(disputed)),
        ("geometry_repairs_audited", n_repairs),
        ("regions", ",".join(regions)),
        ("membership_rows_total", len(mem)),
        ("membership_rows_admin0", int((mem["admin_level"]
                                        == "ADMIN0").sum())),
        ("membership_rows_admin1", int((mem["admin_level"]
                                        == "ADMIN1").sum())),
        ("border_multi_admin0_hexes", n_multi),
        ("terrestrial_hexes_coverage_audited", len(cov_df)),
        ("coverage_quality_counts_deprecated", json.dumps(q_counts)),
        ("coverage_class_counts", json.dumps(cls_counts)),
        ("undercovered_ground_km2_total",
         round(float(cov_df["undercovered_ground_km2"].sum()), 4)),
        ("overcovered_ground_km2_total",
         round(float(cov_df["overcovered_ground_km2"].sum()), 4)),
        ("symmetric_difference_ground_km2_total",
         round(float(cov_df["symmetric_difference_ground_km2"].sum()), 4)),
        ("land_coverage_fraction_min_p50_p95_max", json.dumps([
            round(float(cov_df["land_coverage_fraction"].min()), 6),
            round(float(cov_df["land_coverage_fraction"].quantile(0.5)), 6),
            round(float(cov_df["land_coverage_fraction"].quantile(0.95)), 6),
            round(float(cov_df["land_coverage_fraction"].max()), 6)])),
        ("admin0_to_coast_land_area_ratio_min_p50_p95_max", json.dumps([
            round(float(cov_df["admin0_to_coast_land_area_ratio"].min()), 6),
            round(float(cov_df["admin0_to_coast_land_area_ratio"]
                        .quantile(0.5)), 6),
            round(float(cov_df["admin0_to_coast_land_area_ratio"]
                        .quantile(0.95)), 6),
            round(float(cov_df["admin0_to_coast_land_area_ratio"].max()),
                  6)])),
        ("area_ratio_above_1_hexes",
         int((cov_df["admin0_to_coast_land_area_ratio"] > 1.0).sum())),
        ("island_components_bound", len(comp_bind)),
        ("component_binding_methods", json.dumps(meth)),
        ("settlements_canonical", len(settl)),
        ("settlements_admin0_pip",
         int((settl["admin0_binding_method"]
              == "POINT_IN_POLYGON").sum())),
        ("settlements_in_covered_regions",
         int((settl["coverage_status"] == "IN_REGION").sum())),
        ("kanto_settlement_candidates_present", len(present)),
        ("ports_canonical", len(ports)),
        ("kanto_ports_dual_access", len(dual)),
        ("validation_pass", f"{n_pass}/{len(val)}"),
    ]
    pd.DataFrame(summary_rows, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "human_geography_summary.csv",
                              index=False)
    manifest = {
        "run_id": run_id,
        "stage": "MAPGEN-007",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "human_geography_schema_version": HUMAN_GEOGRAPHY_SCHEMA_VERSION,
        "human_geography_algorithm_version":
            HUMAN_GEOGRAPHY_ALGORITHM_VERSION,
        "reference_semantics": REFERENCE_SEMANTICS,
        "gameplay_authoritative": False,
        "upstream_run": hcfg["upstream_run"],
        "upstream_sha256": up_sha_before,
        "datasets": {k: src_manifest["datasets"][k] for k in ne_keys},
        "geometry_repair_audits": repair_audits,
        "parameters": {
            "settlement_land_snap_max_km":
                hcfg["settlement_land_snap_max_km"],
            "port_land_snap_max_km": hcfg["port_land_snap_max_km"],
            "port_water_snap_max_km": hcfg["port_water_snap_max_km"],
            "point_admin_fallback_max_km":
                hcfg["point_admin_fallback_max_km"],
            "component_admin_fallback_max_km":
                hcfg["component_admin_fallback_max_km"],
        },
        # MAPGEN-007R audit — explicit, never hidden magic numbers. These
        # classify the audit only; they never gate membership or bindings.
        "audit_tolerances": {
            "match_abs_tolerance_km2": match_abs,
            "match_rel_tolerance": match_rel,
            "conservation_abs_tolerance_km2": cons_tol,
            "alias_equivalence_tolerance": alias_tol,
            "coverage_fraction_float_noise_clamp": 1e-6,
        },
        "deprecated_columns": {
            "admin_coverage_audit.csv": [
                "land_ground_km2_est", "admin0_coverage_ground_km2",
                "admin0_coverage_ratio_of_land", "coverage_quality"],
            "note": ("original MAPGEN-007 formulas kept unchanged as "
                     "aliases; official values are the bidirectional "
                     "audit columns; removal planned for a future "
                     "schema major bump"),
        },
        "coast_authority": {
            "source": "OSM land-polygons-split-3857 (same file as "
                      "MAPGEN-003..006R)",
            "reconstruction": "load_osm_land(osm_land_shp, "
                              "bbox_to_mercator(cfg.bbox), margin+10km) — "
                              "identical to islands/geography pipelines",
            "proof": "V43 land_fraction reproduction gate",
        },
        "id_determinism_scope": (
            "reference ids derive from Natural Earth stable ids (NE_ID / "
            "adm1_code); stable across runs for a fixed NE version, NOT "
            "across NE version upgrades"),
        "regions": {r: {"hexes": len(reg["hex_ids"]),
                        "crosses_dateline": reg["crosses_dateline"]}
                    for r, reg in regions.items()},
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_readme(run_dir, run_id, hcfg, admin0, admin1, hierarchy,
                  disputed, mem, cov_df, comp_bind, settl, ports, cat,
                  val, n_multi, dual, aspects, q_counts, meth)
    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    import shutil

    for f in (["README_REVIEW.md", "human_geography_validation.csv",
               "human_geography_summary.csv", "admin_coverage_audit.csv",
               "kanto_settlement_catalogue.csv", "run_manifest.json"]
              + img_names):
        shutil.copy2(run_dir / f, review / f)
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[humangeo] {run_id}: validation {n_pass}/{len(val)}, "
          f"{len(mem)} membership rows, {len(comp_bind)} components bound, "
          f"{len(settl)} settlements, {len(ports)} ports "
          f"({timings['total_s']:.0f}s)")
    for w in warnings:
        print(f"[humangeo][WARN] {w}")
    return run_dir


def _write_readme(run_dir, run_id, hcfg, admin0, admin1, hierarchy,
                  disputed, mem, cov_df, comp_bind, settl, ports, cat,
                  val, n_multi, dual, aspects, q_counts, meth):
    n_pass = int(val["pass"].sum())
    cls_counts = cov_df["coverage_class"].value_counts().to_dict()
    m0 = mem[mem["admin_level"] == "ADMIN0"]
    s_meth = settl["admin0_binding_method"].value_counts().to_dict()
    lb = settl[settl["coverage_status"] == "IN_REGION"][
        "land_binding_kind"].value_counts().to_dict()
    plb = ports[ports["coverage_status"] == "IN_REGION"][
        "land_binding_kind"].value_counts().to_dict()
    present = cat[cat["present_in_source"]]
    lines = [
        "# MAPGEN-007 Review — REFERENCE ADMINISTRATION IS NOT GAMEPLAY "
        "OWNERSHIP",
        "",
        f"Run: `{run_id}` — Reference Administrative & Settlement Geography "
        "Foundation.",
        "",
        "## Semantics contract (read this first)",
        "",
        "- Every table in this stage is `reference_semantics = "
        "CONTEMPORARY_DE_FACTO_REFERENCE` and `gameplay_authoritative = "
        "false`.",
        "- Natural Earth admin boundaries are a contemporary de-facto "
        "snapshot — **not** historical borders, and never game ownership.",
        "- Populations are `SOURCE_REFERENCE_ESTIMATE` (NE POP_MAX/POP_MIN) "
        "— not game populations. Capitals are reference capitals, not game "
        "capitals. Ports are reference commercial ports, not naval bases.",
        "- Nothing was written into `geography_hexes` (SHA-proved "
        "immutable); all admin data lives in separate reference tables.",
        "- Island OVERLAY UNITS are never admin units: admin binding is "
        "done per island COMPONENT (spec: 'overlay unitごとにcountryを1つ"
        "というschemaは禁止').",
        "",
        "## Canonical reference tables",
        "",
        f"- `reference_admin0.parquet` — {len(admin0)} countries "
        "(id `adm0_<NE_ID>`; ISO codes cleaned, `-99` -> null, audited).",
        f"- `reference_admin0_hierarchy.parquet` — {len(hierarchy)} map "
        "units with MAP_UNIT_OF_COUNTRY / MAP_UNIT_OF_DEPENDENT_TERRITORY "
        "relations as stated by the source.",
        f"- `reference_admin1.parquet` — {len(admin1)} states/provinces "
        "(id `adm1_<adm1_code>`).",
        f"- `reference_disputed_areas.parquet` — {len(disputed)} disputed "
        "areas (kept verbatim as reference disputes).",
        "",
        "## Hex x admin membership (many-to-many, ground metric)",
        "",
        f"- `reference_admin_hex_membership.parquet`: {len(mem)} rows "
        f"({int((mem['admin_level'] == 'ADMIN0').sum())} admin0, "
        f"{int((mem['admin_level'] == 'ADMIN1').sum())} admin1) across "
        f"regions {sorted(mem['region'].unique())}.",
        "- Intersection areas are WGS84 geodesic ground km2; "
        "`share_of_hex_ground_area` and dominant flags are reference "
        "conveniences only.",
        f"- border_benelux many-to-many positive: {n_multi} hexes carry "
        ">=2 admin0 memberships (see `human_geography_border_hex.png`).",
        f"- Coverage is AUDITED, never gated: {len(cov_df)} terrestrial "
        "hexes in `admin_coverage_audit.csv`.",
        "",
        "## Bidirectional coast/admin coverage audit (MAPGEN-007R)",
        "",
        "- OSM coast authority and Natural Earth Admin-0 are different "
        "snapshots at different resolutions: a mismatch between them is "
        "an AUDIT FINDING, not necessarily a bug — and it is preserved, "
        "never repaired. Admin polygons are NOT clipped, expanded or "
        "snapped to the coastline.",
        "- Per terrestrial hex, A = hex-clipped OSM coast-authority land "
        "(reconstructed with the exact MAPGEN-004/005/006R loader and "
        "source file; proved by the V43 land_fraction reproduction gate) "
        "and B = hex-clipped UNION of all intersecting NE Admin-0 "
        "polygons (union first, so border-polygon micro-overlaps are "
        "never double counted; many-to-many membership is kept).",
        "- Official audit columns (WGS84 geodesic ground km2): "
        "`coast_land_ground_km2`=area(A), `admin0_union_ground_km2`="
        "area(B), `matched_ground_km2`=area(A∩B), "
        "`undercovered_ground_km2`=area(A−B) (OSM land NE fails to "
        "cover), `overcovered_ground_km2`=area(B−A) (NE reaches beyond "
        "the OSM coast), `symmetric_difference_ground_km2`=under+over.",
        "- `land_coverage_fraction` = matched/coast is a true coverage "
        "fraction in [0,1] (hard-validated). "
        "`admin0_to_coast_land_area_ratio` = admin_union/coast may "
        "legitimately exceed 1 on overcoverage. The denominator of "
        "`undercoverage_fraction`/`overcoverage_fraction`/"
        "`symmetric_difference_fraction` is coast_land_ground_km2 (null "
        "when a hex has no coast land); over/symdiff fractions may "
        "therefore exceed 1 on extreme overcoverage.",
        "- `coverage_class` (MATCHED / UNDERCOVERED / OVERCOVERED / "
        "BIDIRECTIONAL_MISMATCH) is an audit classification, NOT a "
        "quality gate: it never drops membership, never fails the run, "
        "and is never gameplay semantics. Noise floor: a side is "
        "significant above max(0.01 km2, 0.5% of hex coast land) — "
        "recorded in run_manifest.audit_tolerances.",
        f"- Class counts: {json.dumps(cls_counts)}; deprecated one-way "
        f"quality (kept as alias): {q_counts}.",
        "- DEPRECATED aliases kept with their ORIGINAL formulas: "
        "`admin0_coverage_ratio_of_land` (est-based, superseded by "
        "`admin0_to_coast_land_area_ratio`, equality validated within "
        "tolerance), `land_ground_km2_est`, "
        "`admin0_coverage_ground_km2`, `coverage_quality`. They will be "
        "removed in a future schema major bump.",
        "- Membership, dominant assignment, component/settlement/port "
        "bindings and all canonical tables are byte-identical to "
        "MAPGEN-007 (V41/V42).",
        "",
        "## Island component -> reference admin",
        "",
        f"- `island_component_reference_admin.parquet`: all "
        f"{len(comp_bind)} components bound; methods={meth}.",
        "- Fallbacks always record ground distance (<=30 km); UNRESOLVED "
        "is a formal state, silent snapping is forbidden.",
        "",
        "## Settlements and ports",
        "",
        f"- `reference_settlements.parquet`: {len(settl)} settlements; "
        f"admin0 binding methods={s_meth}.",
        f"- Land bindings inside covered regions: {lb}; outside coverage "
        "= OUT_OF_REGION_COVERAGE (formal, audited).",
        f"- Kanto candidate catalogue (source-checked, never assumed): "
        f"{len(present)}/{len(cat)} present "
        f"({sorted(present['candidate'])}); absent: "
        f"{sorted(cat[~cat['present_in_source']]['candidate'])}.",
        f"- `reference_ports.parquet`: {len(ports)} ports; port_type/"
        "activity do NOT exist in NE ports 5.0.0 -> explicit nulls.",
        f"- Port land bindings in covered regions: {plb}; kanto dual "
        f"land+water access positives: {len(dual)}.",
        "",
        "## Dateline",
        "",
        "- fiji_dateline (min_lon > max_lon) is processed as two EPSG:3857 "
        "sub-boxes; bindings use ground distances with the +world-width "
        "shifted frame, so +-180 never looks like 40,000 km.",
        "- The Fiji render uses the 006R wrap DISPLAY rule (storage stays "
        "in the original frame).",
        "",
        "## Images",
        "",
    ]
    for n, a in aspects.items():
        lines.append(f"- `{n}` (aspect {a})")
    lines += [
        "",
        "## Validation",
        "",
        f"- `human_geography_validation.csv`: **{n_pass}/{len(val)}** "
        "machine-checked gates (incl. 006R physical regression V01-V06 "
        "and upstream immutability V30).",
        "",
        "## Determinism and ID scope",
        "",
        "- Reference ids derive from NE stable ids (NE_ID / adm1_code): "
        "stable across runs for a fixed NE version; a NE version upgrade "
        "is a new reference snapshot.",
        "- Run-level determinism is proved by a second run + normalized "
        "SHA-256 comparison (see completion report).",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
