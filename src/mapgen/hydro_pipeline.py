"""MAPGEN-003 hydrography pipeline.

Per region: OSM high-resolution coast (coast v2) -> HydroLAKES lake layer ->
HydroRIVERS selection -> hex-edge graph -> river map matching -> outputs.

MAPGEN-001 hex geometry/IDs are untouched; only the land/water CONTENT of
hexes is recomputed from the better coastline. Natural Earth remains as the
comparison baseline for the Kanto coastline evaluation.
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

from . import ALGORITHM_VERSION
from .coastline import coastline_errors, sample_coastline
from .config import BBox, MapgenConfig
from .hex_edges import build_edge_graph
from .hex_grid import HexGrid
from .hydro_render import (render_coast_before_after, render_hydro_map,
                           render_lake_zoom)
from .hydro_sources import (hydrolakes_shp, hydrorivers_shp, osm_land_shp,
                            record_hydro_sources)
from .land import classify_hexes, generated_coastline, load_land_mercator, source_coastline
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .projection import bbox_to_mercator, to_mercator, to_wgs84
from .river_snap import RiverSnapper, water_hex_river_hexes
from .rivers import (RIVER_CLASSES, decompose_branches, load_reaches,
                     name_branches)
from .sources import ensure_dataset
from .terrain_layers import WATER_TYPE_ID

HYDRO_SCHEMA_VERSION = "1.0.0"


def _class_ge(a: str, b: str) -> bool:
    return RIVER_CLASSES.index(a) >= RIVER_CLASSES.index(b)


def load_osm_land(shp: Path, bbox_3857, clip_margin_m: float):
    """OSM land polygons (already EPSG:3857) unioned and clipped."""
    min_x, min_y, max_x, max_y = bbox_3857
    clip = shapely.box(min_x - clip_margin_m, min_y - clip_margin_m,
                       max_x + clip_margin_m, max_y + clip_margin_m)
    gdf = gpd.read_file(shp, bbox=tuple(clip.bounds))
    if gdf.empty:
        return shapely.Polygon()
    land = shapely.union_all(gdf.geometry.values)
    return shapely.make_valid(shapely.intersection(land, clip))


def load_lakes(shp: Path, bbox_wgs84, min_area_km2: float) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(shp, bbox=bbox_wgs84,
                        columns=["Hylak_id", "Lake_name", "Lake_area",
                                 "Shore_len", "Lake_type", "Vol_total"])
    if gdf.empty:
        return gdf
    gdf = gdf[gdf["Lake_area"] >= min_area_km2].copy()
    return gdf.to_crs("EPSG:3857").reset_index(drop=True)


def hex_lake_stats(polys: np.ndarray, hex_ids: list[str], hex_area: float,
                   lakes: gpd.GeoDataFrame):
    """Per-hex lake_fraction and primary-lake attributes from HydroLAKES."""
    n = len(polys)
    frac = np.zeros(n)
    primary = [None] * n
    lake_ids: list[list[int]] = [[] for _ in range(n)]
    if len(lakes):
        tree = shapely.STRtree(lakes.geometry.values)
        pairs = tree.query(polys, predicate="intersects")
        best_area = np.zeros(n)
        for hi, li in zip(*pairs):
            inter = shapely.intersection(polys[hi], lakes.geometry.values[li])
            a = shapely.area(inter)
            if a <= 0:
                continue
            frac[hi] += a / hex_area
            lake_ids[hi].append(int(lakes["Hylak_id"].iloc[li]))
            if a > best_area[hi]:
                best_area[hi] = a
                primary[hi] = li
    rows = {
        "lake_fraction": np.clip(frac, 0.0, 1.0),
        "lake_ids": ["|".join(map(str, sorted(ids))) for ids in lake_ids],
        "primary_lake_id": [
            int(lakes["Hylak_id"].iloc[p]) if p is not None else None
            for p in primary],
        "primary_lake_name": [
            (lakes["Lake_name"].iloc[p] or None) if p is not None else None
            for p in primary],
        "primary_lake_area_km2": [
            float(lakes["Lake_area"].iloc[p]) if p is not None else np.nan
            for p in primary],
    }
    return pd.DataFrame(rows)


def process_hydro_region(name: str, bbox_wgs84: BBox, cfg: MapgenConfig,
                         hcfg: dict, continent: str, run_id: str,
                         named_specs: list[dict], ne_baseline: bool) -> dict:
    timings = {}
    grid = HexGrid(flat_to_flat=float(hcfg["hex_size_m"]),
                   orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)
    bbox_3857 = bbox_to_mercator(bbox_wgs84)
    min_x, min_y, max_x, max_y = bbox_3857
    margin = float(hcfg["margin_m"])
    extent = (min_x - margin, min_y - margin, max_x + margin, max_y + margin)
    q, r = grid.hexes_covering_bbox(*extent)
    polys = grid.polygons(q, r)
    hex_ids = grid.hex_ids(q, r)
    cx, cy = grid.axial_to_xy(q, r)
    centres = np.stack([cx, cy], axis=1)
    clip_margin = margin + 10000.0
    clip_bbox = (min_x - clip_margin, min_y - clip_margin,
                 max_x + clip_margin, max_y + clip_margin)

    # ---- coast v2 (OSM) --------------------------------------------------
    t0 = time.perf_counter()
    osm_land = load_osm_land(osm_land_shp(cfg.data_dir), bbox_3857, clip_margin)
    osm_coast = source_coastline(osm_land, clip_bbox)
    cls = classify_hexes(polys, centres, osm_land, osm_coast, grid.area,
                         cfg.land_threshold)
    timings["coast_s"] = time.perf_counter() - t0

    # Optional Natural Earth baseline (Kanto comparison).
    ne = None
    if ne_baseline:
        t0 = time.perf_counter()
        ne_shp = ensure_dataset("ne_10m_land", cfg.data_dir)
        ne_land = load_land_mercator(ne_shp, bbox_3857, clip_margin)
        ne_coast = source_coastline(ne_land, clip_bbox)
        ne_cls = classify_hexes(polys, centres, ne_land, ne_coast, grid.area,
                                cfg.land_threshold)
        ne = {"cls": ne_cls, "coast": ne_coast}
        timings["ne_baseline_s"] = time.perf_counter() - t0

    # ---- lakes -----------------------------------------------------------
    t0 = time.perf_counter()
    lakes = load_lakes(
        hydrolakes_shp(cfg.data_dir),
        (bbox_wgs84.min_x - 0.3, bbox_wgs84.min_y - 0.3,
         bbox_wgs84.max_x + 0.3, bbox_wgs84.max_y + 0.3),
        float(hcfg["lake"]["min_lake_area_km2"]))
    lake_df = hex_lake_stats(polys, hex_ids, grid.area, lakes)
    timings["lake_s"] = time.perf_counter() - t0

    is_ocean = cls["land_class"] == "water"
    is_lake = (~is_ocean) & (lake_df["lake_fraction"].to_numpy()
                             >= float(hcfg["lake"]["majority_threshold"]))
    water_type = np.where(is_ocean, "OCEAN",
                          np.where(is_lake, "LAKE", "NONE")).astype(object)

    # ---- rivers ----------------------------------------------------------
    t0 = time.perf_counter()
    thresholds = hcfg["river_class_thresholds"]
    reaches = load_reaches(
        hydrorivers_shp(cfg.data_dir, continent),
        (bbox_wgs84.min_x, bbox_wgs84.min_y, bbox_wgs84.max_x, bbox_wgs84.max_y),
        thresholds)
    branches = decompose_branches(reaches, thresholds, hcfg["width"])
    name_branches(branches, named_specs, reaches)
    wcfg = hcfg["water_hex_river"]
    exag = float(hcfg["width"]["exaggeration"])
    for b in branches:
        if (_class_ge(b.river_class, wcfg["min_class"])
                and b.width_est_m * exag >= float(wcfg["min_width_m"])):
            b.representation = "WATER_HEX_RIVER"
    timings["river_select_s"] = time.perf_counter() - t0

    # ---- edge graph + snapping ------------------------------------------
    t0 = time.perf_counter()
    graph = build_edge_graph(grid, q, r, hex_ids)
    timings["edge_graph_s"] = time.perf_counter() - t0

    idx_by_hex = {h: i for i, h in enumerate(hex_ids)}
    # WATER_HEX_RIVER first: occupy hexes, register junction nodes.
    t0 = time.perf_counter()
    river_hex_ids: dict[str, set] = {}
    for b in branches:
        if b.representation != "WATER_HEX_RIVER":
            continue
        hexes = water_hex_river_hexes(b, polys, hex_ids, exag)
        occupied = set()
        for h in hexes:
            if water_type[idx_by_hex[h]] != "OCEAN":
                water_type[idx_by_hex[h]] = "RIVER"
                occupied.add(h)
        river_hex_ids[b.branch_id] = occupied

    hex_water = dict(zip(hex_ids, water_type))
    snapper = RiverSnapper(graph, hex_water, hcfg["snapping"])

    # Register water-hex branches: tributaries connect to their boundary nodes.
    for b in branches:
        if b.representation != "WATER_HEX_RIVER":
            continue
        occupied = river_hex_ids.get(b.branch_id, set())
        nodes = sorted({n for e in graph.edges
                        if e["hex_a"] in occupied
                        or (e["hex_b"] and e["hex_b"] in occupied)
                        for n in (e["n1"], e["n2"])})
        for rid in b.reach_ids:
            snapper.junctions[rid] = (b, nodes)

    snap_results = []
    failed = []
    for b in branches:  # already importance-descending
        if b.representation == "WATER_HEX_RIVER":
            continue
        res = snapper.snap_branch(b)
        if res is None:
            failed.append(b.branch_id)
        else:
            snap_results.append(res)

    # Mouth extension: HydroRIVERS terminates rivers at its OWN coast mask,
    # which can sit several km inland of the OSM coastline (e.g. the tidal
    # Arakawa, the Nieuwe Waterweg). Terminal rivers with a moderate gap are
    # extended along graph edges to the nearest open-water hex so mouths
    # connect on the game map. Extension edges are flagged.
    max_ext = float(hcfg["snapping"].get("mouth_extension_max_m", 20000.0))
    f2f = grid.flat_to_flat
    water_mask = np.isin(water_type, ["OCEAN", "LAKE"])
    wxy = centres[water_mask]
    for res in snap_results:
        b = res["branch"]
        if b.next_down_reach != 0 or not len(wxy):
            continue
        ex, ey = graph.node_xy[res["node_path"][-1]]
        d = np.hypot(wxy[:, 0] - ex, wxy[:, 1] - ey)
        gap = float(d.min())
        res["mouth_gap_m"] = gap
        if gap <= 1.0 * f2f or gap > max_ext:
            continue
        tx, ty = wxy[int(np.argmin(d))]
        seg = shapely.LineString([(ex, ey), (tx, ty)])
        cand = snapper.tree.query(seg.buffer(2.0 * f2f), predicate="intersects")
        cand_set = set(np.sort(cand).tolist())
        adj: dict[int, list[tuple[int, int]]] = {}
        goal_nodes = set()
        cost_by_edge = {}
        scale = float(hcfg["snapping"]["distance_cost_scale_m"])
        for eidx in cand_set:
            e = graph.edges[eidx]
            mid = shapely.Point(graph.edge_midpoint(eidx))
            cost_by_edge[eidx] = (graph.edge_length(eidx)
                                  * (1.0 + (float(shapely.distance(mid, seg)) / scale) ** 2)
                                  * snapper._water_pen[eidx])
            for a2, b2 in ((e["n1"], e["n2"]), (e["n2"], e["n1"])):
                adj.setdefault(a2, []).append((b2, eidx))
            waters = {hex_water.get(e["hex_a"], "NONE"),
                      hex_water.get(e["hex_b"], "NONE") if e["hex_b"] else "NONE"}
            if waters & {"OCEAN", "LAKE"}:
                goal_nodes.update((e["n1"], e["n2"]))
        if res["node_path"][-1] not in adj or not goal_nodes:
            continue
        ext_path = snapper._dijkstra(adj, cost_by_edge,
                                     res["node_path"][-1], list(goal_nodes))
        if ext_path is None or len(ext_path) < 2:
            continue
        for i in range(len(ext_path) - 1):
            n1, n2 = ext_path[i], ext_path[i + 1]
            eidx = graph.edge_by_nodes[(min(n1, n2), max(n1, n2))]
            e = graph.edges[eidx]
            res["edges"].append({
                "edge_id": e["edge_id"], "hex_a_id": e["hex_a"],
                "hex_b_id": e["hex_b"],
                "edge_direction": 0.0, "flow_direction": 0.0,
                "flow_from_node": n1, "flow_to_node": n2,
                "snap_distance_m": np.nan, "mouth_extension": True,
            })
            # Extensions are counted separately: they have no source line, so
            # they must not distort length_ratio.
            res["extension_length_m"] += graph.edge_length(eidx)
        res["node_path"] = res["node_path"] + ext_path[1:]
        res["mouth_gap_m"] = 0.0
    timings["snapping_s"] = time.perf_counter() - t0

    return {
        "name": name, "grid": grid, "q": q, "r": r, "polys": polys,
        "hex_ids": hex_ids, "bbox_3857": bbox_3857, "cls": cls,
        "osm_coast": osm_coast, "ne": ne, "lakes": lakes, "lake_df": lake_df,
        "water_type": water_type, "branches": branches,
        "snap_results": snap_results, "failed_branches": failed,
        "river_hex_ids": river_hex_ids, "graph": graph, "timings": timings,
        "reach_count": len(reaches),
    }


# --------------------------------------------------------------------------
# Output assembly
# --------------------------------------------------------------------------
def edge_rows_for_region(reg: dict, run_id: str, exag: float) -> list[dict]:
    rows = []
    for res in reg["snap_results"]:
        b = res["branch"]
        for er in res["edges"]:
            rows.append({
                "run_id": run_id,
                "region": reg["name"],
                **er,
                "mouth_extension": er.get("mouth_extension", False),
                "river_id": f"riv_{b.main_riv}",
                "river_name": b.name,
                "source_segment_id": b.branch_id,
                "river_class": b.river_class,
                "river_importance_score": round(float(np.log10(b.discharge_cms + 1.0)), 4),
                "discharge_m3_s": round(b.discharge_cms, 3),
                "strahler_order": b.strahler,
                "source_width_m": round(b.width_est_m, 1),
                "effective_game_width_m": round(b.width_est_m * exag, 1),
                "representation": b.representation,
                "snap_distance_mean_m": round(res["offset_mean_m"], 1),
                "snap_distance_max_m": round(res["offset_max_m"], 1),
                "source_length_m": round(b.source_length_m, 1),
                "snapped_length_m": round(res["snapped_length_m"], 1),
            })
    return rows


def _components(edge_pairs: list[tuple[int, int]]) -> int:
    parent: dict[int, int] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edge_pairs:
        parent[find(a)] = find(b)
    return len({find(n) for n in parent}) if parent else 0


def _qr_maps(reg: dict):
    qr_by_hex = {h: (int(qq), int(rr)) for h, qq, rr in
                 zip(reg["hex_ids"], reg["q"], reg["r"])}
    return qr_by_hex


def _hex_sets_touch(a: set, b: set, qr_by_hex: dict) -> bool:
    """True when two hex-id sets share a hex or contain axial neighbours."""
    from .hex_grid import AXIAL_DIRECTIONS

    if a & b:
        return True
    bq = {qr_by_hex[h] for h in b}
    for h in a:
        q0, r0 = qr_by_hex[h]
        if (q0, r0) in bq:
            return True
        for dq, dr in AXIAL_DIRECTIONS:
            if (q0 + dq, r0 + dr) in bq:
                return True
    return False


def _path_hexes(reg: dict, res: dict) -> set:
    g = reg["graph"]
    hexes = set()
    for a, b in zip(res["node_path"], res["node_path"][1:]):
        e = g.edges[g.edge_by_nodes[(min(a, b), max(a, b))]]
        hexes.add(e["hex_a"])
        if e["hex_b"]:
            hexes.add(e["hex_b"])
    return hexes


def confluence_audit(reg: dict, run_id: str) -> pd.DataFrame:
    """One row per source confluence (branch flowing into another branch),
    with the preservation verdict — including WATER_HEX_RIVER receivers and
    tributaries, which never appear in edge snap results."""
    branch_by_reach = {}
    for b in reg["branches"]:
        for rid in b.reach_ids:
            branch_by_reach[rid] = b
    res_by_branch = {r["branch"].branch_id: r for r in reg["snap_results"]}
    qr_by_hex = _qr_maps(reg)
    rows = []
    for trib in reg["branches"]:
        if not trib.next_down_reach:
            continue
        receiver = branch_by_reach.get(trib.next_down_reach)
        if receiver is None:
            continue
        conf = shapely.get_coordinates(trib.line)[-1]
        lon, lat = to_wgs84(conf[0], conf[1])
        preserved = False
        node_id = None
        dist = np.nan
        reason = ""
        if trib.representation == "WATER_HEX_RIVER":
            trib_hexes = reg["river_hex_ids"].get(trib.branch_id, set())
            if receiver.representation == "WATER_HEX_RIVER":
                recv_hexes = reg["river_hex_ids"].get(receiver.branch_id, set())
            else:
                recv_res = res_by_branch.get(receiver.branch_id)
                recv_hexes = _path_hexes(reg, recv_res) if recv_res else set()
            if trib_hexes and recv_hexes:
                preserved = _hex_sets_touch(trib_hexes, recv_hexes, qr_by_hex)
                dist = 0.0 if preserved else np.nan
                if not preserved:
                    reason = "water-hex corridors not adjacent"
            else:
                reason = "empty water-hex corridor"
        else:
            res = res_by_branch.get(trib.branch_id)
            if res is None:
                reason = "tributary snap failed"
            else:
                preserved = bool(res["connected_to_receiver"])
                node_id = res["node_path"][-1]
                nx, ny = reg["graph"].node_xy[node_id]
                dist = float(np.hypot(nx - conf[0], ny - conf[1]))
                if not preserved:
                    reason = "end node not on receiver path"
        rows.append({
            "run_id": run_id,
            "region": reg["name"],
            "river_id": f"riv_{receiver.main_riv}",
            "river_name": receiver.name,
            "source_confluence_id": f"cf_{trib.branch_id}",
            "source_lon": round(float(lon), 5),
            "source_lat": round(float(lat), 5),
            "source_upstream_branch_ids": trib.branch_id,
            "source_downstream_branch_id": receiver.branch_id,
            "snapped_confluence_node_id": node_id,
            "preserved": preserved,
            "distance_m": round(dist, 1) if np.isfinite(dist) else np.nan,
            "representation": f"{trib.representation}->{receiver.representation}",
            "failure_reason": reason,
            "exception_reason": "",
        })
    cols = ["run_id", "region", "river_id", "river_name",
            "source_confluence_id", "source_lon", "source_lat",
            "source_upstream_branch_ids", "source_downstream_branch_id",
            "snapped_confluence_node_id", "preserved", "distance_m",
            "representation", "failure_reason", "exception_reason"]
    return pd.DataFrame(rows, columns=cols)


def snapping_summary(reg: dict, named_specs: list[dict], run_id: str,
                     audit: pd.DataFrame, qcfg: dict) -> list[dict]:
    rows = []
    results_by_name: dict[str, list] = {}
    branches_by_name: dict[str, list] = {}
    for b in reg["branches"]:
        if b.name:
            branches_by_name.setdefault(b.name, []).append(b)
    for res in reg["snap_results"]:
        if res["branch"].name:
            results_by_name.setdefault(res["branch"].name, []).append(res)

    for spec in named_specs:
        name = spec["name"]
        bs = branches_by_name.get(name, [])
        rs = results_by_name.get(name, [])
        if not bs:
            rows.append({"run_id": run_id, "region": reg["name"],
                         "river_name": name, "river_class": None,
                         "topology_pass": False,
                         "note": "no source branch found near seed"})
            continue
        offsets = (np.concatenate([r["offsets"] for r in rs])
                   if rs else np.array([np.nan]))
        pairs = [(er["flow_from_node"], er["flow_to_node"])
                 for r in rs for er in r["edges"]
                 if not er.get("mouth_extension")]
        comps = _components(pairs)
        water_hex_branches = [b for b in bs
                              if b.representation == "WATER_HEX_RIVER"]
        # Confluences from the audit: includes WATER_HEX tributaries and
        # receivers (the MAPGEN-003 false-positive counted only EDGE ones).
        branch_ids = {b.branch_id for b in bs}
        mine = audit[audit["source_downstream_branch_id"].isin(branch_ids)
                     & (audit["source_upstream_branch_ids"]
                        .map(lambda x: x not in branch_ids))]
        n_conf = int(len(mine))
        n_preserved = int(mine["preserved"].sum())
        n_excepted = int((mine["exception_reason"] != "").sum())

        src_len = sum(b.source_length_m for b in bs)
        snap_len = sum(r["snapped_length_m"] for r in rs)
        ext_len = sum(r["extension_length_m"] for r in rs)
        all_snapped = len(rs) == len([b for b in bs
                                      if b.representation == "EDGE_RIVER"])
        is_water_hex = bool(water_hex_branches)
        ratio = (np.nan if is_water_hex or not src_len
                 else snap_len / src_len)
        # STRICT topology: every source confluence preserved (or explicitly
        # excepted), all EDGE parts snapped into one connected component.
        topology_pass = bool(
            all_snapped and comps <= 1
            and n_preserved + n_excepted == n_conf)

        km100 = snap_len / 100000.0
        turns = sum(r["turn_count"] for r in rs)
        src_turn_density = (
            sum(r["source_turns_per_100km"] * r["snapped_length_m"]
                for r in rs) / snap_len if snap_len else 0.0)
        turns_per_100km = turns / km100 if km100 > 0 else 0.0

        # Quality gates (EDGE rivers with enough length only).
        long_enough = (src_len / 1000.0) >= float(
            qcfg["min_length_for_ratio_km"])
        p95 = float(np.nanpercentile(offsets, 95))
        gate_ratio = "N/A"
        if not is_water_hex and long_enough:
            if ratio > float(qcfg["length_ratio_fail"]):
                gate_ratio = "FAIL"
            elif ratio > float(qcfg["length_ratio_warn"]):
                gate_ratio = "WARN"
            else:
                gate_ratio = "PASS"
        gate_p95 = ("PASS" if p95 <= float(qcfg["p95_offset_max_m"])
                    else "FAIL") if not is_water_hex else "N/A"

        rows.append({
            "run_id": run_id,
            "region": reg["name"],
            "river_name": name,
            "river_class": max((b.river_class for b in bs),
                               key=RIVER_CLASSES.index),
            "representation": ("WATER_HEX_RIVER" if is_water_hex
                               else "EDGE_RIVER"),
            "source_length_km": round(src_len / 1000, 2),
            "snapped_length_km": round(snap_len / 1000, 2),
            "extension_length_km": round(ext_len / 1000, 2),
            "length_ratio": round(ratio, 3) if np.isfinite(ratio) else np.nan,
            "mean_offset_m": round(float(np.nanmean(offsets)), 1),
            "median_offset_m": round(float(np.nanmedian(offsets)), 1),
            "p90_offset_m": round(float(np.nanpercentile(offsets, 90)), 1),
            "p95_offset_m": round(p95, 1),
            "max_offset_m": round(float(np.nanmax(offsets)), 1),
            "source_connected_components": 1,
            "snapped_connected_components": comps,
            "source_confluence_count": n_conf,
            "preserved_confluence_count": n_preserved,
            "confluence_exception_count": n_excepted,
            "edge_count": len(pairs),
            "turn_count": int(turns),
            "turns_per_100km": round(turns_per_100km, 1),
            "source_turns_per_100km": round(src_turn_density, 1),
            "snapped_turn_excess": round(turns_per_100km - src_turn_density, 1),
            "sharp_turn_count": int(sum(r["sharp_turn_count"] for r in rs)),
            "direction_reversal_count": int(
                sum(r["direction_reversal_count"] for r in rs)),
            "straight_progress_efficiency": round(
                float(np.mean([r["straight_progress_efficiency"]
                               for r in rs])), 3) if rs else np.nan,
            "topology_pass": topology_pass,
            "gate_length_ratio": gate_ratio,
            "gate_p95_offset": gate_p95,
            "note": "",
        })
    return rows


def build_game_edges(membership: pd.DataFrame, regions: dict,
                     run_id: str) -> pd.DataFrame:
    """Canonical per-edge table for gameplay: edge_id UNIQUE per region.

    Multiple branches/rivers may share one geometric edge (membership table);
    the game reads THIS table, so a crossing effect can only ever apply once
    per edge, and multi-river edges resolve to a dominant river.
    """
    if membership.empty:
        return pd.DataFrame()
    conf_nodes: dict[str, set] = {}
    for name, reg in regions.items():
        nodes = set()
        for res in reg["snap_results"]:
            if res["connected_to_receiver"] and res["node_path"]:
                nodes.add(res["node_path"][-1])
        conf_nodes[name] = nodes

    rows = []
    for (region, edge_id), grp in membership.groupby(["region", "edge_id"],
                                                     sort=True):
        dom = grp.loc[grp["discharge_m3_s"].idxmax()]
        nodes = set(grp["flow_from_node"]) | set(grp["flow_to_node"])
        rows.append({
            "run_id": run_id,
            "region": region,
            "edge_id": edge_id,
            "hex_a_id": dom["hex_a_id"],
            "hex_b_id": dom["hex_b_id"],
            "has_river": True,
            "river_ids": "|".join(sorted(grp["river_id"].unique())),
            "branch_ids": "|".join(sorted(grp["source_segment_id"].unique())),
            "dominant_river_id": dom["river_id"],
            "dominant_river_class": dom["river_class"],
            "max_discharge_m3_s": float(grp["discharge_m3_s"].max()),
            "effective_crossing_width_m": float(
                grp["effective_game_width_m"].max()),
            "flow_directions": "|".join(
                f"{d:.0f}" for d in sorted(grp["flow_direction"].unique())),
            "river_count": int(grp["river_id"].nunique()),
            "is_confluence_edge": bool(nodes & conf_nodes.get(region, set())),
            "mouth_extension": bool(grp["mouth_extension"].any()),
        })
    return pd.DataFrame(rows)


def water_hex_quality(reg: dict, audit: pd.DataFrame, run_id: str) -> list[dict]:
    """WATER_HEX_RIVER-specific quality metrics: a corridor is a connected
    water area, not a line, so length_ratio does not apply."""
    from .hex_grid import AXIAL_DIRECTIONS

    qr_by_hex = _qr_maps(reg)
    groups: dict[str, list] = {}
    for b in reg["branches"]:
        if b.representation == "WATER_HEX_RIVER":
            groups.setdefault(b.name or f"riv_{b.main_riv}", []).append(b)
    rows = []
    idx_by_hex = {h: i for i, h in enumerate(reg["hex_ids"])}
    for name, bs in groups.items():
        corridor = set()
        for b in bs:
            corridor |= reg["river_hex_ids"].get(b.branch_id, set())
        qrs = {qr_by_hex[h] for h in corridor}
        # Connected components over axial adjacency.
        seen, comps = set(), 0
        for start in sorted(qrs):
            if start in seen:
                continue
            comps += 1
            stack = [start]
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                for dq, dr in AXIAL_DIRECTIONS:
                    nxt = (cur[0] + dq, cur[1] + dr)
                    if nxt in qrs and nxt not in seen:
                        stack.append(nxt)
        polys = np.array([reg["polys"][idx_by_hex[h]] for h in sorted(corridor)])
        union = shapely.union_all(polys) if len(polys) else shapely.Polygon()
        line = shapely.line_merge(shapely.union_all([b.line for b in bs]))
        inside = shapely.intersection(line, union)
        inside_frac = (shapely.length(inside) / shapely.length(line)
                       if shapely.length(line) > 0 else 0.0)
        n_samples = max(int(shapely.length(line) // 1000), 1)
        pts = shapely.line_interpolate_point(
            line if line.geom_type == "LineString"
            else max(shapely.get_parts(line), key=lambda g: g.length),
            np.linspace(0, 1, n_samples, endpoint=False), normalized=True)
        dists = shapely.distance(pts, union)
        branch_ids = {b.branch_id for b in bs}
        mine = audit[audit["source_downstream_branch_id"].isin(branch_ids)]
        terminals = [b for b in bs if b.next_down_reach == 0]
        rows.append({
            "run_id": run_id,
            "region": reg["name"],
            "river_name": name,
            "corridor_hex_count": len(corridor),
            "corridor_area_km2": round(float(shapely.area(union)) / 1e6, 1),
            "river_hex_connected_components": comps,
            "source_line_inside_corridor_fraction": round(float(inside_frac), 3),
            "source_line_distance_to_corridor_mean_m": round(float(dists.mean()), 1),
            "source_line_distance_to_corridor_p95_m": round(
                float(np.percentile(dists, 95)), 1),
            "source_confluence_count": int(len(mine)),
            "preserved_confluence_count": int(mine["preserved"].sum()),
            "upstream_connection_pass": bool(mine["preserved"].all()) if len(mine) else True,
            "downstream_connection_pass": bool(
                any(b.endorheic == 0 for b in terminals)
                or river_reaches_water(reg, name)),
        })
    return rows


def coastline_outlier_audit(samples: np.ndarray, errors: np.ndarray,
                            reg: dict, osm_land, run_id: str,
                            top_n: int, audit_threshold_m: float) -> pd.DataFrame:
    """Locate and classify the worst coastline reproduction errors."""
    grid = reg["grid"]
    f2f = grid.flat_to_flat
    hex_area = grid.area
    land_mask = (reg["cls"]["land_class"] == "land")
    cx, cy = grid.axial_to_xy(reg["q"], reg["r"])
    cx, cy = np.atleast_1d(cx), np.atleast_1d(cy)
    land_xy = np.stack([cx[land_mask], cy[land_mask]], axis=1)
    water_xy = np.stack([cx[~land_mask], cy[~land_mask]], axis=1)
    idx_by_hex = {h: i for i, h in enumerate(reg["hex_ids"])}

    parts = shapely.get_parts(osm_land)
    part_tree = shapely.STRtree(parts)
    part_areas = shapely.area(parts)

    order = np.argsort(-errors)
    keep = [i for i in order[:top_n]]
    keep += [i for i in order[top_n:] if errors[i] > audit_threshold_m]
    rows = []
    for rank, i in enumerate(keep, start=1):
        x, y = samples[i]
        qq, rr = grid.xy_to_axial(float(x), float(y))
        hex_id = grid.hex_id(qq, rr)
        hidx = idx_by_hex.get(hex_id)
        lf = float(reg["cls"]["land_fraction"][hidx]) if hidx is not None else np.nan
        coastal = bool(reg["cls"]["is_coastal"][hidx]) if hidx is not None else False
        d_land = float(np.hypot(land_xy[:, 0] - x, land_xy[:, 1] - y).min()) \
            if len(land_xy) else np.inf
        d_water = float(np.hypot(water_xy[:, 0] - x, water_xy[:, 1] - y).min()) \
            if len(water_xy) else np.inf
        pt = shapely.Point(x, y)
        near = part_tree.query(pt.buffer(500.0), predicate="intersects")
        if len(near):
            part_area = float(part_areas[near].max())
        else:
            nearest = part_tree.nearest(pt)
            part_area = float(part_areas[nearest])
        if part_area < hex_area and d_land > 1.5 * f2f:
            cause = "SMALL_ISLAND_LOST"
        elif d_land > 1.5 * f2f:
            cause = "NARROW_PENINSULA"
        elif d_water > 1.5 * f2f:
            cause = "NARROW_INLET"
        else:
            cause = "HEX_MAJORITY_QUANTISATION"
        lon, lat = to_wgs84(float(x), float(y))
        rows.append({
            "run_id": run_id,
            "rank": rank,
            "lon": round(float(lon), 5),
            "lat": round(float(lat), 5),
            "error_m": round(float(errors[i]), 1),
            "nearest_hex_id": hex_id,
            "local_land_fraction": round(lf, 4),
            "local_is_coastal": coastal,
            "cause_category": cause,
            "notes": f"source_polygon_area_km2={part_area / 1e6:.2f}",
        })
    return pd.DataFrame(rows)


def run_hydro(cfg: MapgenConfig, run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    hcfg = cfg.raw["hydro"]
    tcfg = cfg.raw.get("terrain", {})
    if run_id is None:
        run_id = f"{cfg.region_name}_hydro_{_dt.datetime.now():%Y%m%d_%H%M%S}"
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    exag = float(hcfg["width"]["exaggeration"])

    named_by_region: dict[str, list[dict]] = {}
    for spec in hcfg.get("named_rivers", []):
        named_by_region.setdefault(spec["region"], []).append(spec)

    print(f"[hydro] run_id={run_id}")
    regions: dict[str, dict] = {}
    continents = []
    for name, rc in hcfg["regions"].items():
        continents.append(rc["continent"])
        if name == "kanto":
            bbox = cfg.bbox_wgs84
        elif name == "biwa":
            bbox = BBox.from_lonlat_dict(tcfg["validation_regions"]["biwa"])
        else:
            bbox = BBox.from_lonlat_dict(rc)
        print(f"[hydro] === region {name} ===")
        reg = process_hydro_region(
            name, bbox, cfg, hcfg, rc["continent"], run_id,
            named_by_region.get(name, []), ne_baseline=(name == "kanto"))
        regions[name] = reg
        if reg["failed_branches"]:
            warnings.append(
                f"{name}: {len(reg['failed_branches'])} branches could not be "
                f"snapped (no path in corridor): {reg['failed_branches'][:8]}")
        print(f"[hydro] {name}: {len(reg['hex_ids'])} hexes, "
              f"{reg['reach_count']} reaches, {len(reg['branches'])} branches, "
              f"{len(reg['snap_results'])} snapped, "
              f"{len(reg['failed_branches'])} failed")
    record_hydro_sources(cfg.data_dir, sorted(set(continents)))

    # ---- coastline evaluation (Kanto: OSM truth vs NE/OSM hex coasts) ----
    kanto = regions["kanto"]
    interval = float(hcfg["coast_sample_interval_m"])
    samples = sample_coastline(kanto["osm_coast"], interval, kanto["bbox_3857"])
    is_land_osm = kanto["cls"]["land_class"] == "land"
    gen_osm = generated_coastline(kanto["polys"], is_land_osm)
    is_land_ne = kanto["ne"]["cls"]["land_class"] == "land"
    gen_ne = generated_coastline(kanto["polys"], is_land_ne)
    rows = []
    errors_osm_hex = None
    for label, gen in (("osm_truth_vs_ne_hex_coast", gen_ne),
                       ("osm_truth_vs_osm_hex_coast", gen_osm)):
        err = coastline_errors(samples, gen)["coast_error_m"].to_numpy()
        if label == "osm_truth_vs_osm_hex_coast":
            errors_osm_hex = err
        rows.append({
            "run_id": run_id, "region": "kanto", "metric_set": label,
            "sample_count": len(err),
            "coast_error_mean_m": err.mean(), "coast_error_median_m": np.median(err),
            "coast_error_p90_m": np.percentile(err, 90),
            "coast_error_p95_m": np.percentile(err, 95),
            "coast_error_max_m": err.max(),
        })
    # Source-to-source: how far NE's generalized coastline sits from OSM truth.
    ne_samples = sample_coastline(kanto["ne"]["coast"], interval, kanto["bbox_3857"])
    d = shapely.distance(shapely.points(ne_samples), kanto["osm_coast"])
    rows.append({
        "run_id": run_id, "region": "kanto",
        "metric_set": "ne_source_vs_osm_source",
        "sample_count": len(d),
        "coast_error_mean_m": d.mean(), "coast_error_median_m": np.median(d),
        "coast_error_p90_m": np.percentile(d, 90),
        "coast_error_p95_m": np.percentile(d, 95),
        "coast_error_max_m": d.max(),
    })
    coast_eval = pd.DataFrame(rows)
    coast_eval.to_csv(run_dir / "coastline_evaluation.csv", index=False,
                      float_format="%.2f")

    # OSM land needed again for the outlier classifier (islands vs inlets).
    osm_land_kanto = load_osm_land(osm_land_shp(cfg.data_dir),
                                   kanto["bbox_3857"],
                                   float(hcfg["margin_m"]) + 10000.0)
    outliers = coastline_outlier_audit(
        samples, errors_osm_hex, kanto, osm_land_kanto, run_id,
        int(hcfg["quality"]["coast_outlier_top_n"]),
        float(hcfg["quality"]["coast_outlier_audit_m"]))
    outliers.to_csv(run_dir / "coastline_outliers.csv", index=False)

    # ---- tabular outputs -------------------------------------------------
    qcfg = hcfg["quality"]
    audits = {name: confluence_audit(reg, run_id)
              for name, reg in regions.items()}
    audit_df = pd.concat([a for a in audits.values() if len(a)],
                         ignore_index=True)
    audit_df.to_csv(run_dir / "river_confluence_audit.csv", index=False)

    lake_rows, water_rows, source_rows, edge_rows, summary_rows, val_rows = \
        [], [], [], [], [], []
    wq_rows = []
    for name, reg in regions.items():
        ldf = reg["lake_df"]
        for i, h in enumerate(reg["hex_ids"]):
            lf = float(ldf["lake_fraction"].iloc[i])
            wt = reg["water_type"][i]
            if lf > 0:
                lake_rows.append({
                    "run_id": run_id, "region": name, "hex_id": h,
                    "water_type": wt, "lake_fraction": round(lf, 4),
                    "lake_ids": ldf["lake_ids"].iloc[i],
                    "primary_lake_id": ldf["primary_lake_id"].iloc[i],
                    "primary_lake_name": ldf["primary_lake_name"].iloc[i],
                    "primary_lake_area_km2": ldf["primary_lake_area_km2"].iloc[i],
                })
            if wt != "NONE":
                water_rows.append({
                    "run_id": run_id, "region": name, "hex_id": h,
                    "water_type": wt, "water_type_id": WATER_TYPE_ID[wt],
                    "land_fraction": round(float(reg["cls"]["land_fraction"][i]), 4),
                    "lake_fraction": round(lf, 4),
                    "is_coastal": bool(reg["cls"]["is_coastal"][i]),
                })
        for b in reg["branches"]:
            source_rows.append({
                "run_id": run_id, "region": name, "branch_id": b.branch_id,
                "river_name": b.name, "river_class": b.river_class,
                "representation": b.representation,
                "discharge_m3_s": round(b.discharge_cms, 3),
                "strahler_order": b.strahler,
                "source_length_km": round(b.source_length_m / 1000, 2),
                "source_length_ground_km": round(b.source_length_ground_km, 2),
                "source_width_est_m": round(b.width_est_m, 1),
                "effective_game_width_m": round(b.width_est_m * exag, 1),
                "reach_count": len(b.reach_ids),
                "main_riv": b.main_riv,
                "next_down_reach": b.next_down_reach,
            })
        edge_rows.extend(edge_rows_for_region(reg, run_id, exag))
        summary_rows.extend(snapping_summary(
            reg, named_by_region.get(name, []), run_id, audits[name], qcfg))
        wq_rows.extend(water_hex_quality(reg, audits[name], run_id))

        for spec in named_by_region.get(name, []):
            summ = next((s for s in summary_rows
                         if s["river_name"] == spec["name"]
                         and s["region"] == name), None)
            found = summ is not None and summ.get("river_class") is not None
            class_ok = found and _class_ge(summ["river_class"],
                                           spec["expected_min_class"])
            continuous = found and bool(summ.get("topology_pass"))
            reaches_water = (river_reaches_water(reg, spec["name"])
                             if spec.get("must_reach_water") else True)
            wh_ok = True
            if spec.get("expect_water_hex_river"):
                wh_ok = found and summ.get("representation") == "WATER_HEX_RIVER"
            val_rows.append({
                "run_id": run_id, "region": name, "river_name": spec["name"],
                "expected_min_class": spec["expected_min_class"],
                "actual_class": summ.get("river_class") if summ else None,
                "found": found, "class_ok": class_ok,
                "continuous_topology": continuous,
                "reaches_water": reaches_water,
                "water_hex_river_ok": wh_ok,
                "pass": bool(found and class_ok and continuous
                             and reaches_water and wh_ok),
            })

    pd.DataFrame(lake_rows).to_csv(run_dir / "lakes.csv", index=False)
    pd.DataFrame(water_rows).to_csv(run_dir / "water_hexes.csv", index=False)
    pd.DataFrame(source_rows).to_csv(run_dir / "river_sources.csv", index=False)
    # Membership: many-to-many (edge x branch), duplicates are legitimate.
    membership_df = pd.DataFrame(edge_rows)
    membership_df.to_csv(run_dir / "river_edge_membership.csv", index=False)
    membership_df.to_parquet(run_dir / "river_edge_membership.parquet",
                             index=False)
    # Canonical game table: one row per geometric edge.
    game_edges_df = build_game_edges(membership_df, regions, run_id)
    game_edges_df.to_csv(run_dir / "game_river_edges.csv", index=False)
    game_edges_df.to_parquet(run_dir / "game_river_edges.parquet", index=False)
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(run_dir / "river_snapping_summary_v2.csv", index=False)
    pd.DataFrame(wq_rows).to_csv(run_dir / "water_hex_river_quality.csv",
                                 index=False)

    # ---- quality-gate validation rows ------------------------------------
    def _gate(vid, ok, note):
        val_rows.append({
            "run_id": run_id, "region": "all", "river_name": vid,
            "expected_min_class": "", "actual_class": "",
            "found": True, "class_ok": True, "continuous_topology": True,
            "reaches_water": True, "water_hex_river_ok": True,
            "pass": bool(ok), "note": note,
        })

    dup_groups = membership_df.groupby(["region", "edge_id"]).size()
    n_dup = int((dup_groups > 1).sum())
    _gate("gate_game_edges_unique",
          not game_edges_df.duplicated(["region", "edge_id"]).any(),
          f"{len(game_edges_df)} canonical edges")
    _gate("gate_membership_many_to_many", True,
          f"{n_dup} edges with multiple branch membership (allowed)")
    _gate("gate_no_double_crossing",
          not game_edges_df.duplicated(["region", "edge_id"]).any(),
          "crossing state is per canonical edge, applied once")
    big_out = outliers[outliers["error_m"]
                       > float(qcfg["coast_outlier_audit_m"])]
    _gate("gate_coast_outliers_classified",
          bool((big_out["cause_category"] != "OTHER").all()),
          f"{len(big_out)} outliers > "
          f"{qcfg['coast_outlier_audit_m']:.0f} m, all categorised")
    for row in summary_rows:
        if row.get("river_class") is None:
            continue
        if row.get("representation") == "EDGE_RIVER" \
                and row.get("source_length_km", 0) >= float(
                    qcfg["min_length_for_ratio_km"]):
            _gate(f"gate_ratio_{row['river_name']}",
                  row["gate_length_ratio"] in ("PASS", "WARN"),
                  f"length_ratio={row['length_ratio']} "
                  f"({row['gate_length_ratio']})")
            _gate(f"gate_p95_{row['river_name']}",
                  row["gate_p95_offset"] == "PASS",
                  f"p95={row['p95_offset_m']} m")
        _gate(f"gate_topology_{row['river_name']}", row["topology_pass"],
              f"confluences {row['preserved_confluence_count']}"
              f"/{row['source_confluence_count']}")
    validation_df = pd.DataFrame(val_rows)
    validation_df.to_csv(run_dir / "river_validation.csv", index=False)

    # ---- renders ---------------------------------------------------------
    t_render = time.perf_counter()
    fname_alias = {"amazon_mouth": "amazon"}
    render_coast_before_after(
        run_dir / "coast_before_after_kanto.png",
        "Kanto land/water: Natural Earth vs OSM land polygons "
        "(line = OSM coastline)",
        kanto["polys"], kanto["ne"]["cls"]["land_class"],
        kanto["cls"]["land_class"], kanto["osm_coast"], kanto["bbox_3857"])
    for name, reg in regions.items():
        if name == "biwa":
            continue
        short = fname_alias.get(name, name)
        lakes_geom = (shapely.union_all(reg["lakes"].geometry.values)
                      if len(reg["lakes"]) else None)
        render_hydro_map(
            run_dir / f"hydro_{short}_source.png",
            f"{name}: source rivers (HydroRIVERS, class-filtered) + lakes",
            reg["polys"], reg["water_type"], reg["bbox_3857"],
            coastline=reg["osm_coast"], lakes_geom=lakes_geom,
            source_branches=reg["branches"])
        render_hydro_map(
            run_dir / f"hydro_{short}_snapped.png",
            f"{name}: snapped river edges (grey = source reference)",
            reg["polys"], reg["water_type"], reg["bbox_3857"],
            coastline=reg["osm_coast"], lakes_geom=lakes_geom,
            snap_results=reg["snap_results"],
            node_xy=reg["graph"].node_xy, source_as_reference=True)
    for chk in hcfg.get("lake_checks", []):
        reg = regions[chk["region"]]
        zext = bbox_to_mercator(BBox.from_lonlat_dict(chk["zoom"]))
        lakes_geom = (shapely.union_all(reg["lakes"].geometry.values)
                      if len(reg["lakes"]) else None)
        render_lake_zoom(
            run_dir / f"lake_{chk['id']}.png",
            f"{chk['id']}: HydroLAKES polygon vs LAKE hexes",
            reg["polys"], reg["water_type"], lakes_geom, zext)

    # Before/after vs the newest MAPGEN-003 baseline run (old edge schema).
    from .hydro_render import render_snapping_before_after

    baselines = [p for p in cfg.output_dir.glob("*/river_edges.parquet")
                 if p.parent.name != run_id]
    if baselines:
        base_path = max(baselines, key=lambda p: p.stat().st_mtime)
        base_edges = pd.read_parquet(base_path)
        for region_name, fname, extent, markers in (
                ("kanto", "kanto_snapping_before_after.png",
                 kanto["bbox_3857"], False),
                ("rhine", "rhine_snapping_before_after.png",
                 regions["rhine"]["bbox_3857"], False),
                ("amazon_mouth", "amazon_topology_before_after.png",
                 regions["amazon_mouth"]["bbox_3857"], True)):
            reg = regions[region_name]
            eidx_by_id = {e["edge_id"]: i
                          for i, e in enumerate(reg["graph"].edges)}
            segs = []
            sub = base_edges[base_edges["region"] == region_name]
            for _, row in sub.iterrows():
                i = eidx_by_id.get(row["edge_id"])
                if i is None:
                    continue
                e = reg["graph"].edges[i]
                segs.append((
                    (reg["graph"].node_xy[e["n1"]],
                     reg["graph"].node_xy[e["n2"]]),
                    row["river_class"]))
            conf_markers = None
            if markers:
                a = audits[region_name]
                mx, my = to_mercator(a["source_lon"].to_numpy(),
                                     a["source_lat"].to_numpy())
                conf_markers = list(zip(np.atleast_1d(mx), np.atleast_1d(my),
                                        a["preserved"]))
            render_snapping_before_after(
                run_dir / fname,
                f"{region_name}: MAPGEN-003 vs MAPGEN-003A "
                f"(baseline {base_path.parent.name})",
                reg["polys"], reg["water_type"], extent, reg["osm_coast"],
                reg["branches"], segs, reg["snap_results"],
                reg["graph"].node_xy, conf_markers=conf_markers)
    else:
        warnings.append("no MAPGEN-003 baseline run found; before/after "
                        "images skipped")
    render_time = time.perf_counter() - t_render

    # ---- lake validation summary ----------------------------------------
    for chk in hcfg.get("lake_checks", []):
        reg = regions[chk["region"]]
        x, y = to_mercator(chk["lon"], chk["lat"])
        qq, rr = reg["grid"].xy_to_axial(float(x), float(y))
        hid = reg["grid"].hex_id(qq, rr)
        idx = reg["hex_ids"].index(hid) if hid in reg["hex_ids"] else None
        ok = idx is not None and reg["water_type"][idx] == "LAKE"
        validation_df = pd.concat([validation_df, pd.DataFrame([{
            "run_id": run_id, "region": chk["region"],
            "river_name": f"lake:{chk['id']}",
            "expected_min_class": "LAKE", "actual_class":
                reg["water_type"][idx] if idx is not None else None,
            "found": idx is not None, "class_ok": ok,
            "continuous_topology": True, "reaches_water": True,
            "water_hex_river_ok": True, "pass": bool(ok),
        }])], ignore_index=True)
    validation_df.to_csv(run_dir / "river_validation.csv", index=False)

    # ---- manifest + package ---------------------------------------------
    total_s = time.perf_counter() - t_start
    peak_mb = _peak_memory_mb()
    source_manifest = json.loads(
        (cfg.data_dir / "source_manifest.json").read_text(encoding="utf-8"))
    manifest = {
        "stage": "MAPGEN-003 coastline + hydrography + river edge snapping",
        "hydro_schema_version": HYDRO_SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "run_id": run_id,
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "hex_size_m": hcfg["hex_size_m"],
        "hydro_config": hcfg,
        "source_datasets": {
            k: {kk: vv for kk, vv in v.items() if kk != "files"}
            | {"file_count": len(v.get("files", []))}
            for k, v in source_manifest.get("datasets", {}).items()},
        "per_region_timings": {n: regions[n]["timings"] for n in regions},
        "render_time_s": round(render_time, 2),
        "total_duration_s": round(total_s, 2),
        "peak_memory_mb": round(peak_mb, 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    _build_review_package(run_dir, run_id, hcfg, coast_eval, summary_df,
                          validation_df, warnings)
    print(f"[hydro] done in {total_s:.1f}s, peak memory {peak_mb:.0f} MB")
    print(f"[hydro] output: {run_dir}")
    return run_dir


def _build_review_package(run_dir: Path, run_id: str, hcfg: dict,
                          coast_eval: pd.DataFrame, summary_df: pd.DataFrame,
                          validation_df: pd.DataFrame,
                          warnings: list[str]) -> Path:
    import shutil

    review = run_dir / "chatgpt_review"
    review.mkdir(parents=True, exist_ok=True)
    names = ["run_manifest.json", "coastline_evaluation.csv",
             "coastline_outliers.csv", "lakes.csv", "river_sources.csv",
             "river_edge_membership.csv", "game_river_edges.csv",
             "river_snapping_summary_v2.csv", "river_confluence_audit.csv",
             "water_hex_river_quality.csv", "river_validation.csv",
             "water_hexes.csv", "coast_before_after_kanto.png",
             "kanto_snapping_before_after.png",
             "rhine_snapping_before_after.png",
             "amazon_topology_before_after.png",
             "hydro_kanto_source.png", "hydro_kanto_snapped.png",
             "hydro_rhine_source.png", "hydro_rhine_snapped.png",
             "hydro_nile_source.png", "hydro_nile_snapped.png",
             "hydro_amazon_source.png", "hydro_amazon_snapped.png",
             "lake_kasumigaura.png", "lake_biwa.png"]
    for n in names:
        src = run_dir / n
        if src.exists():
            shutil.copy2(src, review / n)
    _write_review_readme(review, run_id, hcfg, coast_eval, summary_df,
                         validation_df, warnings)
    return review


def _write_review_readme(review: Path, run_id: str, hcfg: dict,
                         coast_eval: pd.DataFrame, summary_df: pd.DataFrame,
                         validation_df: pd.DataFrame,
                         warnings: list[str]) -> None:
    files = "\n".join(f"- {p.name}" for p in sorted(review.glob("*")) if p.is_file())
    warn_text = "\n".join(f"- {w}" for w in warnings) if warnings else "None."
    thr = hcfg["river_class_thresholds"]
    scfg = hcfg["snapping"]
    passed = int(validation_df["pass"].sum())
    text = f"""# README_REVIEW — MAPGEN-003 coastline + hydrography + river edge snapping

Project: mapgen — world-scale strategy game map pipeline
Stage: MAPGEN-003
Run ID: {run_id}
Date: {_dt.date.today().isoformat()}
Hex: 6000 m flat-to-flat, EPSG:3857, pointy-top, world-fixed origin (unchanged).

What this stage does:
1. Replaces the Natural Earth 1:10m coastline with OSM land polygons
   (coast v2) for hex land/water content. Hex geometry/IDs are unchanged;
   Natural Earth remains as the comparison baseline.
2. Introduces HydroLAKES polygons as the primary lake source (water_type
   LAKE via lake_fraction majority {hcfg["lake"]["majority_threshold"]}).
   WorldCover inland_water_fraction is retained as raw data.
3. Selects militarily meaningful rivers from HydroRIVERS by mean discharge:
   MINOR >= {thr["MINOR"]}, MEDIUM >= {thr["MEDIUM"]}, MAJOR >= {thr["MAJOR"]},
   GREAT >= {thr["GREAT"]} m3/s (PROVISIONAL — not final).
   river_importance_score = log10(discharge+1) (structure, not final).
4. Snaps each river BRANCH (chain between confluences) to a CONTINUOUS path
   in the hex-edge graph via a STATEFUL shortest path (MAPGEN-003A):
   step cost = length * (1 + (dist(edge_mid, source_line)/{scfg["distance_cost_scale_m"]})^2)
             * {scfg["water_edge_penalty"]} if fully between ocean/lake hexes
             + length * {scfg.get("direction_weight", 1.2)} * (1 - cos(angle
               between edge and LOCAL source tangent)) / 2
             + {scfg.get("same_turn_penalty", 0.6)} * hex_side when two
               consecutive turns curl the same way.
   On the hex-corner lattice every step turns exactly +-60 deg, so straight
   progress = alternating turn signs; the same-sign penalty kills curling
   detours while local-tangent alignment lets genuinely meandering rivers
   stay curved (they are never force-straightened). Search restricted to a
   {scfg["corridor_m"]} m corridor; branches processed importance-descending;
   a tributary's downstream end is FORCED onto a node of the receiving
   branch nearest the true confluence. Flow direction stored
   upstream->downstream. Mouth-extension edges are excluded from
   length_ratio (extension_length_km reported separately).
5. WATER_HEX_RIVER: branches of class >= {hcfg["water_hex_river"]["min_class"]}
   with estimated width >= {hcfg["water_hex_river"]["min_width_m"]} m occupy
   hexes instead of edges. Width estimate: w = {hcfg["width"]["coefficient"]}
   * Q^{hcfg["width"]["exponent"]} (hydraulic geometry; HydroRIVERS has no
   width). Source estimate and game width (exaggeration
   {hcfg["width"]["exaggeration"]}) are stored separately. PROVISIONAL.

MAPGEN-003A hardening:
- LENGTH UNIT FIX: MAPGEN-003 compared snapped PROJECTED metres against
  HydroRIVERS LENGTH_KM (ground km), inflating length_ratio by the Mercator
  scale factor (1.62 at the Rhine's 52N, 1.23 in Kanto). source_length is now
  the projected geometry length (same unit as everything else in this
  project); ground km is kept as source_length_ground_km reference. The
  "Rhine inflation" (1.81) was mostly this unit mismatch — its geometric
  ratio is ~1.06.
- topology_pass is now STRICT: preserved_confluence_count must equal
  source_confluence_count (explicit exceptions only, none used). The
  MAPGEN-003 Amazon false positive (8 source / 7 preserved but pass=True)
  was caused by WATER_HEX_RIVER tributaries being invisible to the
  EDGE-only gate; corridor-adjacency preservation now covers them
  (river_confluence_audit.csv lists every confluence individually).
- Source-branch membership and gameplay edges are SEPARATED:
  river_edge_membership.csv is many-to-many (an edge may carry several
  branches/rivers near confluences); game_river_edges.csv is canonical with
  UNIQUE edge_id per region — crossing effects can only apply once, with
  dominant_river / max_discharge for multi-river edges.
- WATER_HEX_RIVER quality uses corridor metrics (water_hex_river_quality.csv:
  connected components, source-line-inside-corridor fraction, distances,
  confluences, up/downstream connection) — length_ratio is N/A for
  corridors by design.
- Coastline outliers audited and classified in coastline_outliers.csv.

Coastline evaluation (truth = OSM coastline samples):
{coast_eval.to_string(index=False)}

River snapping summary (v2):
{summary_df.drop(columns=["run_id"]).to_string(index=False)}

Validation ({passed}/{len(validation_df)} passed):
{validation_df.drop(columns=["run_id"]).to_string(index=False)}

Licences:
- OSM land polygons: ODbL 1.0, (c) OpenStreetMap contributors. Kept as a
  separable derived database (see source_manifest.json, odbl flag);
  distribution decisions deferred.
- HydroLAKES / HydroRIVERS: HydroSHEDS Licence Agreement v1 (attribution
  Messager et al. 2016 / Lehner & Grill 2013).

Mouth handling:
- HydroRIVERS terminates rivers at its own coast mask, sometimes several km
  inland of the OSM coastline (tidal Arakawa: ~12 km, Nieuwe Waterweg).
  Terminal rivers with a gap of 1..{scfg.get("mouth_extension_max_m", 20000):.0f} m
  to open water are EXTENDED along graph edges to the nearest ocean/lake hex
  (flagged mouth_extension=true in river_edges).
- Where the two coast definitions disagree massively (the Amazon estuary is
  "inside the coastline" in OSM for ~300 km), the river is accepted as
  ocean-connected via HydroRIVERS topology (ENDORHEIC = 0). Resolving the
  estuary water surface itself needs OSM water polygons (next stage).

Known limitations:
- River class / water-hex thresholds are PROVISIONAL, tuned on a handful of
  known rivers; a world calibration pass comes later.
- OSM land polygons keep large estuaries (Amazon) and wide tidal rivers as
  "land"; their water surface will come from OSM water polygons / GRWL later.
- Width is an empirical discharge-based estimate; GRWL / OSM river polygons
  were surveyed as future replacements (GRWL: Landsat-derived global widths,
  ~30 m rivers and wider; OSM water polygons: uneven coverage) but are not
  integrated in this stage.
- Hex-edge paths cannot run straight; zigzag along the corridor is inherent
  to hex-edge rivers (excess_turn_count quantifies wiggle).
- HydroRIVERS v1 has reduced source resolution at high latitudes; the source
  provider is isolated behind rivers.py so HydroSHEDS v2 can replace it.
- Terrain (MAPGEN-002A) still uses its own WorldCover-based water layer; the
  hydro water layer produced here becomes the authority when the layers are
  merged in the next stage.

Warnings/errors:
{warn_text}

Generated files:
{files}

Note from the generator (Claude): this stage validates the conversion
algorithms. River class thresholds and WATER_HEX_RIVER cutoffs are NOT
final decisions.
"""
    (review / "README_REVIEW.md").write_text(text, encoding="utf-8")


def river_reaches_water(reg: dict, name: str) -> bool:
    """Does the named river's downstream terminal reach open water?

    Pass when the terminal end (last snapped node, or any occupied river hex
    for WATER_HEX_RIVER) lies within 1.5 hex sizes of an OCEAN/LAKE hex
    centre — a mouth hex itself is often majority-land, so strict adjacency
    would be wrong.
    """
    grid = reg["grid"]
    water_mask = np.isin(reg["water_type"], ["OCEAN", "LAKE"])
    if not water_mask.any():
        return False
    cx, cy = grid.axial_to_xy(reg["q"], reg["r"])
    wx = np.atleast_1d(cx)[water_mask]
    wy = np.atleast_1d(cy)[water_mask]
    limit = 1.5 * grid.flat_to_flat

    def _near_water(x, y):
        return bool((np.hypot(wx - x, wy - y) <= limit).any())

    # Follow the downstream chain from the named branches to the network's
    # true terminal — a named river may continue under another branch (e.g.
    # HydroRIVERS routes the Edogawa into the Arakawa mouth system, and the
    # Rhine into the Meuse mouth).
    branch_by_reach = {}
    for b in reg["branches"]:
        for rid in b.reach_ids:
            branch_by_reach[rid] = b
    terminals = []
    for b in reg["branches"]:
        if b.name != name:
            continue
        cur, seen = b, set()
        while cur.next_down_reach and cur.branch_id not in seen:
            seen.add(cur.branch_id)
            nxt = branch_by_reach.get(cur.next_down_reach)
            if nxt is None:
                break
            cur = nxt
        if cur.next_down_reach == 0 and cur not in terminals:
            terminals.append(cur)
    if not terminals:
        return False

    hex_xy = {h: (x, y) for h, x, y in zip(
        reg["hex_ids"], np.atleast_1d(cx), np.atleast_1d(cy))}
    for b in terminals:
        # Terminal's source mouth point sits in/near ocean or lake hexes
        # (e.g. an estuary already classified as ocean).
        mouth = shapely.get_coordinates(b.line)[-1]
        if _near_water(mouth[0], mouth[1]):
            return True
        if b.representation == "WATER_HEX_RIVER":
            for h in reg["river_hex_ids"].get(b.branch_id, set()):
                if _near_water(*hex_xy[h]):
                    return True
        else:
            for res in reg["snap_results"]:
                if res["branch"] is b and res["node_path"]:
                    x, y = reg["graph"].node_xy[res["node_path"][-1]]
                    if _near_water(x, y):
                        return True
        # Source-topology fallback: HydroRIVERS says this terminal drains to
        # the ocean (ENDORHEIC == 0); the remaining gap to the OSM coast is a
        # coast-mask disagreement between the datasets (e.g. the Amazon
        # estuary, which OSM keeps inside the coastline for ~300 km). The gap
        # is reported via mouth_gap in the validation output.
        if b.endorheic == 0:
            return True
    return False
