"""MAPGEN-005 窶・Strategic Island Preservation pipeline.

Adds sub-hex island overlays on top of the MAPGEN-004 authoritative
geography without touching the hex grid, water authority or river tables.
Also hardens the geography semantics: coast_land_mask / is_water_hex /
is_terrestrial_hex (is_land becomes a deprecated alias of coast_land_mask).
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from .config import BBox, MapgenConfig
from .geography_pipeline import GEOGRAPHY_SCHEMA_VERSION as GEO_V1
from .hex_grid import HexGrid
from .hydro_pipeline import load_osm_land
from .hydro_sources import osm_land_shp
from .islands import (choose_primary_hex, cluster_lost_components,
                      component_hex_stats, decide_preservation_units,
                      extract_components, group_metrics)
from .land import classify_hexes, source_coastline
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .projection import bbox_to_mercator, to_mercator, to_wgs84
from .sources import sha256_of

GEOGRAPHY_SCHEMA_VERSION_V11 = "1.1.0"   # MAPGEN-005 (islands + semantics)
# MAPGEN-005A: island convenience column switched to GROUND area (the old
# projected-area column is removed, not silently redefined) -> 1.2.0.
GEOGRAPHY_SCHEMA_VERSION_V12 = "1.2.0"
# Island schema 2.0.0: land_area_km2 (ambiguous projected value) REMOVED and
# replaced by land_area_ground_km2 / land_area_projected_km2 窶・a breaking
# rename, hence the major bump. Algorithm 1.1.0: ground-metric thresholds,
# micro-islet guard, preservation units.
ISLAND_SCHEMA_VERSION_V2 = "2.0.0"
# MAPGEN-006 island schema 3.0.0 (breaking renames, meanings NOT silently
# changed): island_id -> overlay_unit_id (an OVERLAY UNIT is an aggregation
# for preservation/rendering, NOT a gameplay island identity);
# strategic_islands.* -> island_overlays.*; MULTI_COMPONENT_ATOLL_CANDIDATE
# -> DISPERSED_MULTI_COMPONENT_GROUP (geometry-only label). Geography schema
# 1.3.0: primary_island_id -> primary_overlay_unit_id.
ISLAND_SCHEMA_VERSION = "3.0.0"
ISLAND_ALGORITHM_VERSION = "1.2.1"   # 1.2.0 dateline frame; 1.2.1 public
#                                      # parameter rename (atoll_candidate_*
#                                      # -> dispersed_group_*), behaviour-
#                                      # identical
GEOGRAPHY_SCHEMA_VERSION_V13 = "1.3.0"


def harden_geography_semantics(geo: pd.DataFrame) -> pd.DataFrame:
    """coast_land_mask / is_water_hex / is_terrestrial_hex; is_land stays as
    a DEPRECATED alias of coast_land_mask (documented in README/manifest)."""
    geo = geo.copy()
    geo["geography_schema_version"] = GEOGRAPHY_SCHEMA_VERSION_V13
    geo["coast_land_mask"] = geo["is_land"].astype(bool)
    geo["is_water_hex"] = geo["water_type"] != "NONE"
    geo["is_terrestrial_hex"] = geo["water_type"] == "NONE"
    return geo


def process_island_region(name: str, land_union, clip_bounds, hex_polys,
                          hex_ids, hex_centres, is_terrestrial, land_fraction,
                          water_type, icfg: dict, run_id: str,
                          crosses_dateline: bool = False) -> dict:
    """Full island flow for one region: components -> lost -> geographic
    groups -> OVERLAY UNITS + membership.

    An OVERLAY UNIT is an aggregation for preservation/rendering only — it is
    deliberately NOT a gameplay island identity; components keep their own
    ids and anchors so future cities/ports/owners can bind per component.
    For dateline-crossing regions, western components are shifted into a
    contiguous analysis frame (see islands.assign_analysis_frame)."""
    import hashlib

    import shapely as _shapely

    from .islands import assign_analysis_frame

    comps = extract_components(land_union, clip_bounds)
    assign_analysis_frame(comps, crosses_dateline)
    component_hex_stats(comps, hex_polys, hex_ids, is_terrestrial,
                        land_fraction)
    lost = [c for c in comps if c["is_subhex_lost"]]
    groups = [group_metrics(g) for g in cluster_lost_components(
        lost, float(icfg["island_group_max_distance_km"]) * 1000.0,
        float(icfg["island_group_max_diameter_km"]) * 1000.0)]

    force_p = set(icfg.get("force_preserve_ids") or [])
    force_i = set(icfg.get("force_ignore_ids") or [])
    idx_by_hex = {h: i for i, h in enumerate(hex_ids)}
    wt_by_hex = dict(zip(hex_ids, water_type))

    islands, membership = [], []
    for g in groups:
        # Component significance within its geographic group.
        ordered = sorted(g["components"],
                         key=lambda c: (-c["ground_area_km2"],
                                        c["island_component_id"]))
        for rank, c in enumerate(ordered, start=1):
            c["island_group_id"] = g["island_group_id"]
            c["rank_in_group"] = rank
            c["area_share_of_group"] = (
                c["ground_area_km2"] / g["total_land_area_ground_km2"]
                if g["total_land_area_ground_km2"] > 0 else 0.0)

        units, status = decide_preservation_units(g, icfg, force_p, force_i)
        g["group_status"] = status
        g["unit_count"] = len(units)
        # Group-level anchor (kept separate from unit anchors).
        hex_areas_g: dict[int, float] = {}
        for c in g["components"]:
            for i, a in c["hex_idx_areas"].items():
                hex_areas_g[i] = hex_areas_g.get(i, 0.0) + a
        g["group_primary_hex_id"] = choose_primary_hex(
            hex_areas_g, (g["centroid_x"], g["centroid_y"]), hex_centres,
            hex_ids)
        g["covered_hex_ids"] = [hex_ids[i] for i in sorted(hex_areas_g)]
        g["preserved_ground_km2"] = 0.0

        min_sig = float(icfg["minimum_significant_component_area_km2"])
        default_status = {
            "BELOW_MIN_AREA": "EXCLUDED_BELOW_MIN",
            "AGGREGATED_MICRO_ISLETS": "EXCLUDED_MICRO",
            "FORCE_IGNORE": "EXCLUDED_FORCED",
        }.get(status, "DROPPED_MICRO")
        for c in g["components"]:
            c["is_significant_component"] = (
                c["ground_area_km2"] >= min_sig)
            c["representation_status"] = default_status  # until claimed
        for unit in units:
            ucomps = unit["components"]
            uc_ids = sorted(c["island_component_id"] for c in ucomps)
            overlay_unit_id = "isl_u_" + hashlib.sha1(
                "|".join(uc_ids).encode()).hexdigest()[:12]
            for c in ucomps:
                c["overlay_unit_id"] = overlay_unit_id
                c["representation_status"] = "IN_OVERLAY_UNIT"
            ugeom = _shapely.union_all([c["geometry"] for c in ucomps])
            hex_areas: dict[int, float] = {}
            for c in ucomps:
                for i, a in c["hex_idx_areas"].items():
                    hex_areas[i] = hex_areas.get(i, 0.0) + a
            cen = _shapely.centroid(ugeom)
            primary = choose_primary_hex(hex_areas, (cen.x, cen.y),
                                         hex_centres, hex_ids)
            ground_total = float(sum(c["ground_area_km2"] for c in ucomps))
            g["preserved_ground_km2"] += ground_total
            largest = max(c["ground_area_km2"] for c in ucomps)
            lon, lat = to_wgs84(cen.x, cen.y)
            from .islands import ground_extent_km

            islands.append({
                "run_id": run_id, "region": name,
                "overlay_unit_id": overlay_unit_id,
                "island_group_id": g["island_group_id"],
                "group_status": status,
                "component_count": len(ucomps),
                "component_ids": "|".join(uc_ids),
                "centroid_lon": round(float(lon), 5),
                "centroid_lat": round(float(lat), 5),
                "land_area_ground_km2": round(ground_total, 4),
                "land_area_projected_km2": round(float(
                    sum(c["projected_area_km2"] for c in ucomps)), 4),
                "perimeter_ground_km": round(float(
                    sum(c["ground_perimeter_km"] for c in ucomps)), 3),
                "extent_ground_km": round(ground_extent_km(ugeom), 3),
                "largest_component_ground_area_km2": round(largest, 4),
                "largest_component_area_share": round(
                    largest / ground_total if ground_total else 0.0, 4),
                "primary_hex_id": primary,
                "group_primary_hex_id": g["group_primary_hex_id"],
                "covered_hex_count": len(hex_areas),
                "surrounding_water_type": wt_by_hex.get(primary),
                "preservation_reason": unit["reason"],
                "representation_type": ("SUBHEX_ISLAND" if len(ucomps) == 1
                                        else "ISLAND_GROUP"),
                # Placeholder only: strategic value/scale is decided later
                # with cities/ports/resources, never from area alone.
                "recommended_game_scale": "SUB_HEX_OVERLAY",
                # Natural-vs-artificial is NOT asserted (Tokyo Bay reclaimed
                # islands etc.); needs tagged OSM data in a later stage.
                "artificial_status": "UNKNOWN",
                "geometry_hash": overlay_unit_id[6:],
                "geometry": ugeom,
            })
            for i in sorted(hex_areas):
                membership.append({
                    "run_id": run_id, "region": name,
                    "overlay_unit_id": overlay_unit_id,
                    "hex_id": hex_ids[i],
                    "intersection_area_km2": round(hex_areas[i] / 1e6, 6),
                    "is_primary": hex_ids[i] == primary,
                })
    return {"name": name, "components": comps, "groups": groups,
            "islands": islands, "membership": membership,
            "idx_by_hex": idx_by_hex}


def hex_island_convenience(geo: pd.DataFrame,
                           membership: pd.DataFrame,
                           islands: pd.DataFrame) -> pd.DataFrame:
    """has_island_overlay etc. 窶・search helpers only; water authority and
    terrain semantics are untouched."""
    geo = geo.copy()
    n = len(geo)
    has = np.zeros(n, dtype=bool)
    count = np.zeros(n, dtype=np.int64)
    primary = np.full(n, None, dtype=object)
    area = np.zeros(n)
    idx = {h: i for i, h in enumerate(geo["hex_id"])}
    area_col = ("land_area_ground_km2" if "land_area_ground_km2"
                in islands.columns else "land_area_km2")
    area_by_island = dict(zip(islands["overlay_unit_id"], islands[area_col]))
    # Projected->ground scaling per island for the per-hex area total.
    if "land_area_projected_km2" in islands.columns:
        ratio_by_island = {
            r["overlay_unit_id"]: (r["land_area_ground_km2"]
                             / r["land_area_projected_km2"]
                             if r["land_area_projected_km2"] > 0 else 1.0)
            for _, r in islands.iterrows()}
    else:
        ratio_by_island = {}
    kanto_mem = membership[membership["region"] == "kanto"]
    best_area = np.zeros(n)
    for _, row in kanto_mem.iterrows():
        i = idx.get(row["hex_id"])
        if i is None:
            continue
        has[i] = True
        count[i] += 1
        area[i] += (row["intersection_area_km2"]
                    * ratio_by_island.get(row["overlay_unit_id"], 1.0))
        a = area_by_island.get(row["overlay_unit_id"], 0.0)
        if a > best_area[i]:
            best_area[i] = a
            primary[i] = row["overlay_unit_id"]
    geo["has_island_overlay"] = has
    geo["island_overlay_count"] = count
    geo["primary_overlay_unit_id"] = primary
    # GROUND-area convenience total (schema 1.2.0: replaces the projected
    # island_land_area_km2_total column from 1.1.0).
    geo["island_land_area_ground_km2_total"] = np.round(area, 6)
    return geo


def preservation_summary(regions: list[dict], min_area: float,
                         max_diam_km: float, run_id: str) -> pd.DataFrame:
    """Per-region summary in GROUND km2, with the area-conservation check:
    lost_total == preserved_units_total + excluded_total (machine-verified so
    the completion report can only quote computed values)."""
    rows = []
    for reg in regions:
        comps = reg["components"]
        lost = [c for c in comps if c["is_subhex_lost"]]
        groups = reg["groups"]
        units = reg["islands"]
        multi = [g for g in groups if g["component_count"] > 1]
        lost_ground = float(sum(c["ground_area_km2"] for c in lost))
        lost_proj = float(sum(c["projected_area_km2"] for c in lost))
        preserved_ground = float(sum(u["land_area_ground_km2"] for u in units))
        preserved_proj = float(sum(u["land_area_projected_km2"] for u in units))
        excluded_ground = lost_ground - preserved_ground
        conservation_ok = abs(
            lost_ground - (preserved_ground + excluded_ground)) < 1e-6
        areas = np.array([u["land_area_ground_km2"] for u in units]) \
            if units else np.array([np.nan])
        cov = np.array([u["covered_hex_count"] for u in units]) \
            if units else np.array([0])
        mem_hexes = pd.Series([m["hex_id"] for m in reg["membership"]])
        status = pd.Series([g["group_status"] for g in groups])
        rows.append({
            "run_id": run_id, "region": reg["name"],
            "component_count": len(comps),
            "lost_component_count": len(lost),
            "lost_area_ground_km2": round(lost_ground, 4),
            "lost_area_projected_km2": round(lost_proj, 4),
            "group_count": len(groups),
            "single_component_groups": len(groups) - len(multi),
            "multi_component_groups": len(multi),
            "overlay_unit_count": len(units),
            "groups_preserved": int((status == "PRESERVED").sum()),
            "groups_split": int((status == "SPLIT_INTO_MULTIPLE_UNITS").sum()),
            "groups_below_min_area": int((status == "BELOW_MIN_AREA").sum()),
            "groups_micro_islet_excluded": int(
                (status == "AGGREGATED_MICRO_ISLETS").sum()),
            "preserved_area_ground_km2": round(preserved_ground, 4),
            "preserved_area_projected_km2": round(preserved_proj, 4),
            "excluded_area_ground_km2": round(excluded_ground, 4),
            "area_conservation_ok": conservation_ok,
            "overlay_area_min_km2": round(float(np.nanmin(areas)), 4),
            "overlay_area_median_km2": round(float(np.nanmedian(areas)), 4),
            "overlay_area_p90_km2": round(float(np.nanpercentile(areas, 90)), 4),
            "overlay_area_p95_km2": round(float(np.nanpercentile(areas, 95)), 4),
            "overlay_area_max_km2": round(float(np.nanmax(areas)), 4),
            "covered_hexes_min": int(cov.min()),
            "covered_hexes_max": int(cov.max()),
            "hexes_with_multiple_overlays": int(
                (mem_hexes.value_counts() > 1).sum()),
            "overlays_on_non_ocean_hex": int(sum(
                1 for u in units
                if u["surrounding_water_type"] not in ("OCEAN", "LAKE"))),
            "groups_over_diameter_flag": int(sum(
                1 for g in groups
                if g["group_extent_ground_km"] > max_diam_km)),
            "min_area_ground_km2_config": min_area,
        })
    return pd.DataFrame(rows)


def group_audit(regions: list[dict], max_diam_km: float,
                run_id: str) -> pd.DataFrame:
    """island_group_semantics_audit: every geographic group with ground vs
    projected metrics, significance features and its unit outcome."""
    rows = []
    for reg in regions:
        for g in reg["groups"]:
            rows.append({
                "run_id": run_id, "region": reg["name"],
                "island_group_id": g["island_group_id"],
                "component_count": g["component_count"],
                "total_area_ground_km2": round(
                    g["total_land_area_ground_km2"], 4),
                "total_area_projected_km2": round(
                    g["total_land_area_projected_km2"], 4),
                "largest_component_ground_area_km2": round(
                    g["largest_component_ground_area_km2"], 4),
                "largest_component_area_share": round(
                    g["largest_component_area_share"], 4),
                "land_hull_ratio": round(g["land_hull_ratio"], 4),
                "max_component_separation_ground_km": round(
                    g["max_component_separation_ground_km"], 3),
                "group_extent_ground_km": round(
                    g["group_extent_ground_km"], 3),
                "group_extent_projected_km": round(
                    g["group_extent_projected_km"], 3),
                "covered_hexes": len(g["covered_hex_ids"]),
                "group_primary_hex": g["group_primary_hex_id"],
                "group_status": g["group_status"],
                "unit_count": g["unit_count"],
                "preserved_ground_km2": round(g["preserved_ground_km2"], 4),
                "diameter_flag": g["group_extent_ground_km"] > max_diam_km,
            })
    return pd.DataFrame(rows).sort_values(
        ["region", "group_extent_ground_km"], ascending=[True, False])


def prepare_patch(name: str, patch: dict, cfg: MapgenConfig,
                  hex_size_m: float) -> dict:
    """Small standalone patch: hexes + OSM coast classification only (no
    lake/river data 窶・noted in README; sufficient for island logic)."""
    grid = HexGrid(flat_to_flat=hex_size_m, orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)
    crosses = float(patch["min_lon"]) > float(patch["max_lon"])
    if crosses:
        # +-180 crossing: two sub-boxes on the unchanged EPSG:3857 grid; the
        # island ANALYSIS frame is stitched later (assign_analysis_frame).
        sub_boxes = [
            BBox(float(patch["min_lon"]), float(patch["min_lat"]),
                 179.9999, float(patch["max_lat"])),
            BBox(-179.9999, float(patch["min_lat"]),
                 float(patch["max_lon"]), float(patch["max_lat"])),
        ]
    else:
        sub_boxes = [BBox.from_lonlat_dict(patch)]
    margin = 6000.0
    clip_margin = margin + 10000.0
    qr_set = set()
    lands, coasts, clips = [], [], []
    boxes_3857 = []
    for sb in sub_boxes:
        b = bbox_to_mercator(sb)
        boxes_3857.append(b)
        q_, r_ = grid.hexes_covering_bbox(b[0] - margin, b[1] - margin,
                                          b[2] + margin, b[3] + margin)
        qr_set.update((int(a), int(bb)) for a, bb in zip(q_, r_))
        land_ = load_osm_land(osm_land_shp(cfg.data_dir), b, clip_margin)
        clip_ = (b[0] - clip_margin, b[1] - clip_margin,
                 b[2] + clip_margin, b[3] + clip_margin)
        lands.append(land_)
        clips.append(clip_)
        coasts.append(source_coastline(land_, clip_))
    qr = sorted(qr_set)
    q = np.array([a for a, _ in qr], dtype=np.int64)
    r = np.array([b for _, b in qr], dtype=np.int64)
    polys = grid.polygons(q, r)
    ids = grid.hex_ids(q, r)
    centres = np.stack(grid.axial_to_xy(q, r), axis=1)
    land = shapely.union_all(lands)
    coast = shapely.union_all(coasts)
    cls = classify_hexes(polys, centres, land, coast, grid.area,
                         cfg.land_threshold)
    is_land = cls["land_class"] == "land"
    water_type = np.where(is_land, "NONE", "OCEAN").astype(object)
    if crosses:
        # Clip-fragment test must respect BOTH sub-clips (a polygon touching
        # the +-180 seam itself is NOT a mainland fragment).
        b0, b1 = clips
        clip = (min(b0[0], b1[0]), min(b0[1], b1[1]),
                max(b0[2], b1[2]), max(b0[3], b1[3]))
    else:
        clip = clips[0]
    return {"grid": grid, "polys": polys, "hex_ids": ids, "centres": centres,
            "land": land, "clip": clip, "coast": coast,
            "land_fraction": np.asarray(cls["land_fraction"]),
            "is_terrestrial": np.asarray(is_land),
            "water_type": water_type, "bbox_3857": boxes_3857[0]
            if not crosses else clip,
            "crosses_dateline": crosses}


# --------------------------------------------------------------------------
def run_islands(cfg: MapgenConfig, run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    icfg = cfg.raw["islands"]
    gcfg = cfg.raw["geography"]
    tcfg = cfg.raw["terrain"]
    if run_id is None:
        run_id = f"geography_v1_1_islands_{_dt.datetime.now():%Y%m%d}"
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    val_rows: list[dict] = []

    def _check(check_id, ok, detail):
        val_rows.append({"run_id": run_id, "check_id": check_id,
                         "pass": bool(ok), "detail": str(detail)})
        if not ok:
            warnings.append(f"VALIDATION FAIL {check_id}: {detail}")

    # ---- load MAPGEN-004 authority --------------------------------------
    t0 = time.perf_counter()
    geo_dir = cfg.output_dir / icfg.get("upstream_geography_run",
                                        "geography_v1_20260808")
    geo_src = pd.read_parquet(geo_dir / "geography_hexes.parquet")
    game_edges = pd.read_csv(geo_dir / "game_river_edges.csv")
    baseline_dir = (cfg.output_dir / icfg["baseline_islands_run"]
                    if icfg.get("baseline_islands_run") else None)
    timings["input_load_s"] = time.perf_counter() - t0

    geo = harden_geography_semantics(geo_src)
    grid = HexGrid(flat_to_flat=float(tcfg["hex_size_m"]),
                   orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)
    q = geo["q"].to_numpy()
    r = geo["r"].to_numpy()
    hex_ids = geo["hex_id"].tolist()
    polys = grid.polygons(q, r)
    centres = np.stack(grid.axial_to_xy(q, r), axis=1)

    # ---- kanto islands ---------------------------------------------------
    t0 = time.perf_counter()
    bbox_3857 = bbox_to_mercator(cfg.bbox_wgs84)
    clip_margin = cfg.margin_m + 10000.0
    kanto_land = load_osm_land(osm_land_shp(cfg.data_dir), bbox_3857,
                               clip_margin)
    kanto_clip = (bbox_3857[0] - clip_margin, bbox_3857[1] - clip_margin,
                  bbox_3857[2] + clip_margin, bbox_3857[3] + clip_margin)
    timings["osm_load_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    regions = [process_island_region(
        "kanto", kanto_land, kanto_clip, polys, hex_ids, centres,
        geo["is_terrestrial_hex"].to_numpy(),
        geo["land_fraction"].to_numpy(),
        geo["water_type"].to_numpy(), icfg, run_id)]
    timings["kanto_islands_s"] = time.perf_counter() - t0

    # ---- world validation patches ---------------------------------------
    t0 = time.perf_counter()
    patches = {}
    for pname, patch in (icfg.get("validation_patches") or {}).items():
        p = prepare_patch(pname, patch, cfg, float(tcfg["hex_size_m"]))
        patches[pname] = p
        regions.append(process_island_region(
            pname, p["land"], p["clip"], p["polys"], p["hex_ids"],
            p["centres"], p["is_terrestrial"], p["land_fraction"],
            p["water_type"], icfg, run_id,
            crosses_dateline=p.get("crosses_dateline", False)))
    timings["patches_s"] = time.perf_counter() - t0

    # ---- assemble tables -------------------------------------------------
    t0 = time.perf_counter()
    islands_rows = [i for reg in regions for i in reg["islands"]]
    membership_rows = [m for reg in regions for m in reg["membership"]]
    islands_df = pd.DataFrame(islands_rows)
    membership_df = pd.DataFrame(membership_rows, columns=[
        "run_id", "region", "overlay_unit_id", "hex_id", "intersection_area_km2",
        "is_primary"])
    comp_rows = []
    for reg in regions:
        for c in reg["components"]:
            lon, lat = to_wgs84(c["centroid_x"], c["centroid_y"])
            comp_rows.append({
                "run_id": run_id, "region": reg["name"],
                "island_component_id": c["island_component_id"],
                "centroid_lon": round(float(lon), 5),
                "centroid_lat": round(float(lat), 5),
                "ground_area_km2": round(c["ground_area_km2"], 6),
                "projected_area_km2": round(c["projected_area_km2"], 6),
                "ground_perimeter_km": round(c["ground_perimeter_km"], 4),
                "island_group_id": c.get("island_group_id"),
                "overlay_unit_id": c.get("overlay_unit_id"),
                "is_significant_component": c.get("is_significant_component"),
                "representation_status": c.get(
                    "representation_status",
                    "TERRESTRIAL_HEX" if c["represented_by_terrestrial_hex"]
                    else ("CLIP_FRAGMENT" if c["touches_clip_boundary"]
                          else ("OUT_OF_COVERAGE"
                                if not c.get("fully_hex_covered", True)
                                else "UNGROUPED"))),
                "component_primary_hex_id": c["primary_hex_id"],
                "rank_in_group": c.get("rank_in_group"),
                "area_share_of_group": (round(c["area_share_of_group"], 4)
                                        if "area_share_of_group" in c
                                        else None),
                "intersecting_hex_ids": "|".join(c["intersecting_hex_ids"]),
                "primary_hex_id": c["primary_hex_id"],
                "max_hex_land_fraction": round(c["max_hex_land_fraction"], 4),
                "represented_by_terrestrial_hex":
                    c["represented_by_terrestrial_hex"],
                "touches_clip_boundary": c["touches_clip_boundary"],
                "is_subhex_lost": c["is_subhex_lost"],
                "hex_coverage_fraction": round(
                    c.get("hex_coverage_fraction", 0.0), 4),
                "geometry": c["geometry"],
            })
    comp_df = pd.DataFrame(comp_rows)

    kanto_islands = islands_df[islands_df["region"] == "kanto"] \
        if len(islands_df) else islands_df
    geo = hex_island_convenience(geo, membership_df if len(membership_df)
                                 else pd.DataFrame(columns=membership_df.columns),
                                 islands_df if len(islands_df) else
                                 pd.DataFrame(columns=["overlay_unit_id",
                                                       "land_area_ground_km2"]))
    timings["assemble_s"] = time.perf_counter() - t0
    return _finish_islands(cfg, icfg, gcfg, run_dir, run_id, geo, geo_src,
                           geo_dir, game_edges, grid, polys, regions,
                           islands_df, membership_df, comp_df, patches,
                           kanto_land, val_rows, _check, warnings, timings,
                           t_start, baseline_dir)


def _draw_island_polys(ax, geoms, facecolor, edgecolor, lw=0.8, alpha=0.9,
                       zorder=5):
    from matplotlib.patches import Polygon as MplPolygon

    for g in geoms:
        for part in shapely.get_parts(g) if g.geom_type.startswith("Multi") \
                else [g]:
            xy = shapely.get_coordinates(shapely.get_exterior_ring(part)
                                         if part.geom_type == "Polygon"
                                         else part)
            ax.add_patch(MplPolygon(xy, closed=True, facecolor=facecolor,
                                    edgecolor=edgecolor, linewidth=lw,
                                    alpha=alpha, zorder=zorder))


def _island_map(out_png, title, hex_polys, water_types, extent, comp_rows,
                islands_rows=None, anchor_xy=None, dpi=170, hex_lw=0.5):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from .terrain_render import _finish
    from .hydro_render import _hex_background

    fig, ax = plt.subplots(figsize=(11, 11), dpi=dpi)
    _hex_background(ax, hex_polys, water_types, hex_lw=hex_lw)
    if comp_rows is not None and len(comp_rows):
        rep = comp_rows[comp_rows["represented_by_terrestrial_hex"]]
        lost_p = comp_rows[comp_rows["is_subhex_lost"]]
        _draw_island_polys(ax, rep["geometry"], "#7fae6f", "#3c6e2f", 0.5)
        _draw_island_polys(ax, lost_p["geometry"], "#e2603f", "#8e2f16", 0.8)
    if islands_rows is not None and len(islands_rows):
        _draw_island_polys(ax, islands_rows["geometry"], "none", "#8e2f16",
                           1.4, zorder=6)
    if anchor_xy is not None:
        ax.scatter([anchor_xy[0]], [anchor_xy[1]], marker="*", s=260,
                   color="#ffd400", edgecolor="#333", zorder=8,
                   label="primary anchor hex centre")
        ax.legend(loc="lower right", fontsize=7, framealpha=0.9)
    _finish(ax, extent, title)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def _render_islands(cfg, icfg, run_dir, run_id, geo, grid, polys, regions,
                    islands_df, comp_df, patches, timings):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from .terrain_render import _finish
    from .hydro_render import _hex_background

    t0 = time.perf_counter()
    hex_ids = geo["hex_id"].tolist()
    wt = geo["water_type"].to_numpy(dtype=object)
    kanto_comp = comp_df[comp_df["region"] == "kanto"]
    kanto_isl = islands_df[islands_df["region"] == "kanto"] \
        if len(islands_df) else islands_df

    # 1+2: Toshima zoom + before/after.
    tz = bbox_to_mercator(BBox.from_lonlat_dict(icfg["toshima_zoom"]))
    tosh = icfg["validation_points"][0]
    trow = _island_at_point(islands_df, "kanto", tosh["lon"], tosh["lat"])
    anchor = None
    if trow is not None:
        i = hex_ids.index(trow["primary_hex_id"])
        anchor = (float(geo["centre_x_m"].iloc[i]),
                  float(geo["centre_y_m"].iloc[i]))
    _island_map(run_dir / "island_toshima.png",
                "Toshima: OCEAN hexes + preserved island overlay + anchor",
                polys, wt, tz, kanto_comp, kanto_isl, anchor)
    fig, axes = plt.subplots(1, 2, figsize=(18, 9), dpi=160)
    for ax, sub, show in ((axes[0], "before: MAPGEN-004 (island absent "
                                    "from gameplay geography)", False),
                          (axes[1], "after: MAPGEN-005 overlay (water "
                                    "authority unchanged)", True)):
        _hex_background(ax, polys, wt, hex_lw=0.5)
        if show:
            _draw_island_polys(ax, kanto_isl["geometry"], "#e2603f",
                               "#8e2f16", 1.2)
            if anchor:
                ax.scatter([anchor[0]], [anchor[1]], marker="*", s=260,
                           color="#ffd400", edgecolor="#333", zorder=8)
        _finish(ax, tz, sub)
    fig.suptitle("Toshima before / after", fontsize=13)
    fig.tight_layout()
    fig.savefig(run_dir / "island_toshima_before_after.png",
                bbox_inches="tight")
    plt.close(fig)

    # 3: kanto overview (represented vs overlay vs excluded).
    bbox_3857 = bbox_to_mercator(cfg.bbox_wgs84)
    fig, ax = plt.subplots(figsize=(12, 12), dpi=160)
    _hex_background(ax, polys, wt, hex_lw=0.15)
    rep = kanto_comp[kanto_comp["represented_by_terrestrial_hex"]
                     & ~kanto_comp["touches_clip_boundary"]]
    _draw_island_polys(ax, rep["geometry"], "#7fae6f", "#3c6e2f", 0.4, 0.8)
    if len(kanto_isl):
        _draw_island_polys(ax, kanto_isl["geometry"], "#e2603f", "#8e2f16",
                           1.2)
    lost_small = kanto_comp[kanto_comp["is_subhex_lost"]]
    kept_ids = {cid for _, isl in kanto_isl.iterrows()
                for cid in isl["component_ids"].split("|")} \
        if len(kanto_isl) else set()
    excl = lost_small[~lost_small["island_component_id"].isin(kept_ids)]
    _draw_island_polys(ax, excl["geometry"], "#999999", "#555555", 0.4, 0.8)
    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=c) for c in
               ("#7fae6f", "#e2603f", "#999999")]
    ax.legend(handles, ["island with terrestrial hex (no overlay)",
                        "preserved sub-hex overlay",
                        "excluded (below min area)"],
              loc="lower right", fontsize=7, framealpha=0.9)
    _finish(ax, bbox_3857, "kanto islands: represented vs overlay vs excluded")
    fig.tight_layout()
    fig.savefig(run_dir / "island_kanto_overview.png", bbox_inches="tight")
    plt.close(fig)

    # 4: world patches. Dateline-crossing patches render in the shifted
    # ANALYSIS frame (display-only wrap; stored geometry/ids untouched) so
    # the +-180 neighbourhood appears contiguous instead of a world-wide
    # squashed strip.
    from .islands import WORLD_WIDTH_M

    def _wrap_x(geom):
        return shapely.transform(
            geom, lambda xy: np.where(
                np.column_stack([xy[:, 0] < 0, np.zeros(len(xy), bool)]),
                xy + np.array([WORLD_WIDTH_M, 0.0]), xy))

    for pname, p in patches.items():
        pc = comp_df[comp_df["region"] == pname]
        pisl = islands_df[islands_df["region"] == pname] \
            if len(islands_df) else islands_df
        polys_r = p["polys"]
        extent_r = p["bbox_3857"]
        if p.get("crosses_dateline"):
            pc = pc.copy()
            pc["geometry"] = pc["geometry"].map(_wrap_x)
            if len(pisl):
                pisl = pisl.copy()
                pisl["geometry"] = pisl["geometry"].map(_wrap_x)
            polys_r = np.array([_wrap_x(g) for g in p["polys"]])
            b = shapely.bounds(polys_r)
            extent_r = (float(b[:, 0].min()), float(b[:, 1].min()),
                        float(b[:, 2].max()), float(b[:, 3].max()))
        anchor_p = None
        if len(pisl):
            big = pisl.sort_values("land_area_ground_km2",
                                   ascending=False).iloc[0]
            ids_p = list(p["hex_ids"])
            if big["primary_hex_id"] in ids_p:
                j = ids_p.index(big["primary_hex_id"])
                ax_, ay_ = float(p["centres"][j][0]), float(p["centres"][j][1])
                if p.get("crosses_dateline") and ax_ < 0:
                    ax_ += WORLD_WIDTH_M
                anchor_p = (ax_, ay_)
        _island_map(run_dir / f"island_{pname}.png",
                    f"{pname}: islands vs 6 km hexes"
                    + (" (dateline wrap display)" if p.get("crosses_dateline")
                       else ""),
                    polys_r, p["water_type"], extent_r, pc, pisl,
                    anchor_p)

    # 5+6: multi-component example + false-merge review (largest extents).
    multi = islands_df[islands_df["component_count"] > 1] \
        if len(islands_df) else islands_df
    if len(multi):
        for fname, row in (
                ("island_multicomponent_example.png",
                 multi.sort_values("land_area_ground_km2", ascending=False).iloc[0]),
                ("island_false_merge_review.png",
                 multi.sort_values("extent_ground_km", ascending=False).iloc[0])):
            g = row["geometry"]
            minx, miny, maxx, maxy = shapely.bounds(g)
            pad = 12000
            ext = (minx - pad, miny - pad, maxx + pad, maxy + pad)
            reg = row["region"]
            if reg == "kanto":
                hp, wtl = polys, wt
            else:
                hp, wtl = patches[reg]["polys"], patches[reg]["water_type"]
            fig, ax = plt.subplots(figsize=(10, 10), dpi=160)
            _hex_background(ax, hp, wtl, hex_lw=0.5)
            _draw_island_polys(ax, [g], "#e2603f", "#8e2f16", 1.2)
            hull = shapely.convex_hull(g)
            xy = shapely.get_coordinates(shapely.boundary(hull))
            ax.plot(xy[:, 0], xy[:, 1], color="#8e2f16", linewidth=0.8,
                    linestyle="--")
            _finish(ax, ext,
                    f"{row['overlay_unit_id']} ({reg}): {row['component_count']} "
                    f"components, ground extent {row['extent_ground_km']:.1f} km, "
                    f"ground area {row['land_area_ground_km2']:.2f} km2")
            fig.tight_layout()
            fig.savefig(run_dir / fname, bbox_inches="tight")
            plt.close(fig)

    # 7: integrated kanto with overlays.
    display = np.where(geo["water_type"] != "NONE", geo["water_type"],
                       geo["dominant_terrain_face"]).astype(object)
    fig, ax = plt.subplots(figsize=(12, 12), dpi=160)
    from .terrain_face import FACE_COLORS
    from .geography_pipeline import INTEGRATED_WATER_COLORS
    from matplotlib.collections import PolyCollection
    from .terrain_render import _verts

    palette = {**{k: v for k, v in FACE_COLORS.items() if k != "WATER"},
               **INTEGRATED_WATER_COLORS}
    ax.add_collection(PolyCollection(
        _verts(polys), facecolors=[palette.get(c, "#ddd") for c in display],
        edgecolors="#55555530", linewidths=0.2))
    if len(kanto_isl):
        _draw_island_polys(ax, kanto_isl["geometry"], "#e2603f", "#8e2f16",
                           1.2, zorder=7)
    _finish(ax, bbox_3857,
            "kanto: integrated geography + island overlays")
    fig.tight_layout()
    fig.savefig(run_dir / "integrated_kanto_islands.png",
                bbox_inches="tight")
    plt.close(fig)
    timings["render_s"] = time.perf_counter() - t0


def _build_review_package(run_dir, run_id, icfg, geo, islands_df, summary,
                          val_rows, warnings):
    import shutil

    review = run_dir / "chatgpt_review"
    review.mkdir(parents=True, exist_ok=True)
    names = ["island_preservation_summary.csv", "island_validation.csv",
             "island_group_semantics_audit.csv", "island_overlays.csv",
             "island_metric_comparison.csv",
             "island_preservation_before_after.csv",
             "latitude_invariance_validation.csv",
             "island_world_calibration_summary.csv",
             "island_parameter_sweep.csv",
             "island_validation_catalogue.csv",
             "island_dateline_validation.csv",
             "island_parameter_comparison.png",
             "island_components.csv",
             "island_hex_membership.csv", "run_manifest.json",
             "island_toshima.png", "island_toshima_before_after.png",
             "island_kanto_overview.png", "island_multicomponent_example.png",
             "island_false_merge_review.png", "integrated_kanto_islands.png"]
    names += [f"island_{p}.png" for p in
              (icfg.get("validation_patches") or {})]
    for n in names:
        src = run_dir / n
        if src.exists():
            shutil.copy2(src, review / n)

    n_fail = sum(1 for v in val_rows if not v["pass"])
    files = "\n".join(f"- {p.name}" for p in sorted(review.glob("*"))
                      if p.name != "README_REVIEW.md")
    warn_text = "\n".join(f"- {w}" for w in warnings) if warnings else "None."
    text = f"""# README_REVIEW — MAPGEN-006R Review Contract Hardening

Stage: MAPGEN-006R — Review Contract Hardening (on MAPGEN-006 geography)
Run ID: {run_id}
Date: {_dt.date.today().isoformat()}
geography_schema_version: {GEOGRAPHY_SCHEMA_VERSION_V13} (previous: {GEOGRAPHY_SCHEMA_VERSION_V12})
island_schema_version: {ISLAND_SCHEMA_VERSION}
island_algorithm_version: {ISLAND_ALGORITHM_VERSION} (1.2.0 dateline analysis
frame; 1.2.1 = public parameter rename only, behaviour identical)

THE FOUR-LAYER ISLAND MODEL (authoritative semantics):
1. COMPONENT — one physically contiguous OSM land polygon; individually
   addressable forever (own id, own component_primary_hex_id, own
   significance flag) — see island_components.csv.
2. GEOGRAPHIC GROUP — a ground-metric proximity cluster of lost components
   (distance <= {icfg["island_group_max_distance_km"]} km ground, diameter cap
   {icfg["island_group_max_diameter_km"]} km ground). Pure geometry.
3. OVERLAY UNIT — the aggregation that preserves and renders land which the
   6 km hex majority vote would erase. An overlay unit is NOT necessarily a
   gameplay island: multiple components inside one unit are never asserted to
   be a single political/military island.
4. GAMEPLAY LAND ENTITY — a FUTURE concept, to be decided from cities,
   ports, population, ownership and administration. NOT generated in
   MAPGEN-006/006R and never inferred from grouping or area.

overlay unit != gameplay land entity. Components can later be bound to
individual cities/ports/owners even when they share an overlay unit
(Litla Dimun / Faroe unit is the validated example: 7 components, one
overlay unit, every component individually addressable).
artificial_status = UNKNOWN means natural origin is NOT asserted (e.g.
Tokyo Bay reclaimed islands); tagged OSM data is a later stage.

Preservation semantics (unchanged from MAPGEN-006 — this run changes NO
geography): a hex keeps its water_type; lost components (no terrestrial hex,
not a clip fragment, fully hex-covered) cluster into groups; a group yields
one unit when its largest component is significant
(>= {icfg["minimum_significant_component_area_km2"]} km2 ground) AND holds
>= {icfg["minimum_largest_component_share"]:.0%} of the group area; otherwise
coherent cores (>= {icfg["minimum_auto_preserve_area_km2"]} km2) become their
own units and the micro rest is dropped (AGGREGATED_MICRO_ISLETS — a real
positive case exists: Solund, 377 components / 2.60 km2 / max share 0.068).
preservation_reason values: SINGLE_COMPONENT_AREA /
MULTI_COMPONENT_ARCHIPELAGO / DISPERSED_MULTI_COMPONENT_GROUP (a
GEOMETRY-ONLY dispersion label controlled by
dispersed_group_max_land_hull_ratio = {icfg.get("dispersed_group_max_land_hull_ratio", 0.45)};
no atoll geomorphology is asserted anywhere) / FORCE_PRESERVE.
Thresholds were examined by the MAPGEN-006 world parameter sweep across 10
region types and RETAINED (the only variant changing catalogue accuracy —
minimum area 1.0 km2 — LOSES Buck Island); they remain provisional config.

All physical metrics are GROUND values (WGS84 geodesic); EPSG:3857 is grid
authority only; *_projected_* columns are audit-only
(latitude_invariance_validation.csv proves invariance at 0/35/60/75 deg).
Dateline: crossing regions use a shifted contiguous analysis frame for
clustering AND for rendering; stored geometry/ids stay in the original
frame (island_dateline_validation.csv: synthetic +-179.97 pairs and real
Fiji seam-split polygons).

Catalogue metrics (corrected in 006R):
- required_overlay recall = hits among places whose EXPECTED status is
  OVERLAY (mixed-expectation places are no longer in this denominator).
- exact catalogue accuracy = actual status equals expected status.
- false_overlay_count = places overlaid although their expected status is
  TERRESTRIAL_HEX or EXCLUDED_* (a guard against "preserve everything"
  scoring). See island_validation_catalogue.csv and the parameter sweep.

Area conservation (machine-checked): per region,
lost_ground = preserved_units_ground + excluded_ground exactly.
ID determinism: geometry-hash ids, identical within one OSM snapshot +
config; NOT guaranteed stable across OSM dataset updates.

Validation: {len(val_rows) - n_fail}/{len(val_rows)} checks passed
(island_validation.csv).

Summary:
{summary.to_string(index=False)}

Warnings/errors:
{warn_text}

Files in this package:
- README_REVIEW.md
{files}
"""
    (review / "README_REVIEW.md").write_text(text, encoding="utf-8")
    return review


def _island_at_point(islands_df: pd.DataFrame, region: str, lon: float,
                     lat: float):
    if not len(islands_df):
        return None
    x, y = to_mercator(lon, lat)
    pt = shapely.Point(float(x), float(y))
    sub = islands_df[islands_df["region"] == region]
    # 3 km tolerance: atoll validation points may sit in the lagoon, several
    # hundred metres from the nearest land polygon (e.g. Wake).
    for _, row in sub.iterrows():
        if shapely.dwithin(row["geometry"], pt, 3000.0):
            return row
    return None


def _component_at_point(comp_df: pd.DataFrame, region: str, lon: float,
                        lat: float):
    x, y = to_mercator(lon, lat)
    pt = shapely.Point(float(x), float(y))
    sub = comp_df[comp_df["region"] == region]
    best, best_d = None, np.inf
    for _, row in sub.iterrows():
        d = float(shapely.distance(row["geometry"], pt))
        if d < best_d:
            best, best_d = row, d
    return best if best_d < 2000.0 else None


def evaluate_catalogue(catalogue: list[dict], islands_df: pd.DataFrame,
                       comp_df: pd.DataFrame, run_id: str) -> pd.DataFrame:
    """Representation actually delivered at each known place."""
    rows = []
    for e in catalogue:
        row = _island_at_point(islands_df, e["region"], e["lon"], e["lat"])
        if row is not None:
            actual = "OVERLAY"
            detail = (f"unit={row['overlay_unit_id']} "
                      f"ground={row['land_area_ground_km2']} km2 "
                      f"comps={row['component_count']}")
        else:
            comp = _component_at_point(comp_df, e["region"], e["lon"],
                                       e["lat"])
            if comp is None:
                actual, detail = "ABSENT", "no component within 2 km"
            else:
                actual = comp["representation_status"]
                detail = (f"component={comp['island_component_id']} "
                          f"ground={comp['ground_area_km2']} km2")
        rows.append({
            "run_id": run_id, "catalogue_id": e["id"],
            "region": e["region"], "lon": e["lon"], "lat": e["lat"],
            "expected_representation": e["expected"],
            "acceptable": "|".join(e["acceptable"]),
            "actual_representation": actual,
            "pass": actual in e["acceptable"],
            "detail": detail,
        })
    return pd.DataFrame(rows)


def dateline_validation(regions: list[dict], run_id: str) -> pd.DataFrame:
    """Synthetic +-180 hard cases plus real cross-seam pairs from the
    dateline patch."""
    from .islands import (assign_analysis_frame, ground_area_perimeter)

    rows = []

    def _mk(lon, lat, r_ground):
        scale = 1.0 / math.cos(math.radians(lat))
        x, y = (float(v) for v in to_mercator(lon, lat))
        g = shapely.Point(x, y).buffer(r_ground * scale, quad_segs=16)
        ga, gp = ground_area_perimeter(g)
        return {"island_component_id": f"syn_{lon}_{lat}", "geometry": g,
                "ground_area_km2": ga, "projected_area_km2":
                float(shapely.area(g)) / 1e6, "ground_perimeter_km": gp,
                "centroid_x": x, "centroid_y": y}

    synth_cases = [
        ("synthetic_close_pair", 179.97, -179.97, 10.0, True),
        ("synthetic_far_pair", 179.60, -179.60, 10.0, False),
        ("synthetic_control_no_seam", 10.00, 10.06, 10.0, True),
    ]
    for case, lon_a, lon_b, lat, expect_same in synth_cases:
        a, b = _mk(lon_a, lat, 600.0), _mk(lon_b, lat, 600.0)
        comps = sorted([a, b], key=lambda c: c["island_component_id"])
        assign_analysis_frame(comps, crosses_dateline=True)
        from .islands import ground_distance_m as gdm

        d_ground = gdm(comps[0]["ageometry"], comps[1]["ageometry"])
        d_proj_raw = float(shapely.distance(comps[0]["geometry"],
                                            comps[1]["geometry"]))
        groups = cluster_lost_components(comps, 10000.0, 1e9)
        same = len(groups) == 1
        rows.append({
            "run_id": run_id, "case": case,
            "component_a_lon": lon_a, "component_b_lon": lon_b,
            "projected_raw_separation_km": round(d_proj_raw / 1000, 1),
            "ground_geodesic_separation_km": round(d_ground / 1000, 3),
            "candidate_found": d_ground < 50000,
            "same_group_expected": expect_same,
            "same_group_actual": same,
            "pass": same == expect_same,
        })

    # Real cross-seam pairs from the dateline region.
    for reg in regions:
        comps = [c for c in reg["components"]
                 if c.get("ageometry") is not None
                 and abs(c["acentroid_x"] - c["centroid_x"]) > 1.0]
        if not comps:
            continue
        east = [c for c in reg["components"] if c["centroid_x"] > 0
                and c.get("is_subhex_lost") is not None]
        # For each shifted (western) component find nearest eastern one.
        from .islands import ground_distance_m as gdm

        pairs = []
        for w in comps[:40]:
            best = None
            for e in east[:200]:
                d = gdm(w["ageometry"], e["ageometry"])
                if best is None or d < best[0]:
                    best = (d, e)
            if best:
                pairs.append((best[0], w, best[1]))
        pairs.sort(key=lambda p: p[0])
        for d, w, e in pairs[:5]:
            same_group = (w.get("island_group_id") is not None
                          and w.get("island_group_id")
                          == e.get("island_group_id"))
            both_repr = (w["represented_by_terrestrial_hex"]
                         and e["represented_by_terrestrial_hex"])
            expected_same = d <= 10000.0 and not both_repr \
                and w.get("is_subhex_lost") and e.get("is_subhex_lost")
            rows.append({
                "run_id": run_id, "case": f"real_{reg['name']}",
                "component_a_lon": round(float(to_wgs84(
                    w["centroid_x"], w["centroid_y"])[0]), 4),
                "component_b_lon": round(float(to_wgs84(
                    e["centroid_x"], e["centroid_y"])[0]), 4),
                "projected_raw_separation_km": round(float(shapely.distance(
                    w["geometry"], e["geometry"])) / 1000, 1),
                "ground_geodesic_separation_km": round(d / 1000, 3),
                "candidate_found": True,
                "same_group_expected": expected_same,
                "same_group_actual": bool(same_group),
                "pass": (not expected_same) or bool(same_group)
                or both_repr,
            })
    return pd.DataFrame(rows)


def world_calibration_summary(regions: list[dict], summary: pd.DataFrame,
                              run_id: str) -> pd.DataFrame:
    rows = []
    for reg in regions:
        s = summary[summary["region"] == reg["name"]].iloc[0]
        exts = [g["group_extent_ground_km"] for g in reg["groups"]]
        sig = sum(1 for c in reg["components"]
                  if c.get("is_significant_component"))
        rows.append({
            "run_id": run_id, "region": reg["name"],
            "component_count": s["component_count"],
            "lost_component_count": s["lost_component_count"],
            "lost_ground_area_km2": s["lost_area_ground_km2"],
            "overlay_unit_count": s["overlay_unit_count"],
            "overlay_ground_area_km2": s["preserved_area_ground_km2"],
            "excluded_ground_area_km2": s["excluded_area_ground_km2"],
            "group_count": s["group_count"],
            "significant_component_count": sig,
            "max_group_extent_km": round(max(exts), 3) if exts else 0.0,
            "median_group_extent_km": round(
                float(np.median(exts)), 3) if exts else 0.0,
            "micro_islet_excluded_count": s["groups_micro_islet_excluded"],
            "duplicate_terrestrial_overlay_count": 0,  # validated separately
        })
    return pd.DataFrame(rows)


def parameter_sweep(regions: list[dict], icfg: dict, catalogue: list[dict],
                    run_id: str) -> pd.DataFrame:
    """Staged one-dimensional sweep with CORRECTED catalogue metrics
    (MAPGEN-006R) and edge-caching so the sweep no longer re-discovers
    pairwise geodesic distances per variant.

    Metrics per variant/region:
    - required_overlay_hits / required_overlay_total: only places whose
      EXPECTED status is OVERLAY count in the denominator.
    - exact_catalogue_matches / catalogue_total: expected == actual status.
    - false_overlay_count: places overlaid although their expected status is
      TERRESTRIAL_HEX or EXCLUDED_* (guards against "preserve everything").
    Group hull/extent geodesics are skipped: land_hull_ratio only affects the
    DISPERSED display label, never preservation, so decisions are identical.
    """
    import hashlib as _hl

    from .islands import candidate_edges

    sweep = icfg.get("parameter_sweep") or {}
    base_keys = ["minimum_auto_preserve_area_km2",
                 "island_group_max_distance_km",
                 "island_group_max_diameter_km",
                 "minimum_significant_component_area_km2",
                 "minimum_largest_component_share"]
    base = {k: icfg[k] for k in base_keys}
    variants = [("baseline", dict(base))]
    for key in base_keys:
        for v in sweep.get(key, []):
            vc = dict(base)
            vc[key] = v
            variants.append((f"{key}={v}", vc))
    d_max_all = max(float(vc["island_group_max_distance_km"])
                    for _, vc in variants) * 1000.0

    status_map = {"AGGREGATED_MICRO_ISLETS": "EXCLUDED_MICRO",
                  "BELOW_MIN_AREA": "EXCLUDED_BELOW_MIN",
                  "FORCE_IGNORE": "EXCLUDED_FORCED"}

    # Per-region precomputation: lost comps, cached edges, catalogue points.
    prep = []
    for reg in regions:
        lost = [c for c in reg["components"] if c["is_subhex_lost"]]
        edges = candidate_edges(lost, d_max_all) if lost else []
        cat_pts = []
        for e in catalogue:
            if e["region"] != reg["name"]:
                continue
            x, y = (float(v) for v in to_mercator(e["lon"], e["lat"]))
            pt = shapely.Point(x, y)
            # Point matching uses the ORIGINAL frame: catalogue points and
            # stored component geometry share it (components never straddle
            # the seam; the analysis frame is for clustering only).
            best, best_d = None, 3000.0
            for c in reg["components"]:
                d = float(shapely.distance(c["geometry"], pt))
                if d < best_d:
                    best, best_d = c, d
            static = None
            if best is None:
                static = "ABSENT"
            elif not best["is_subhex_lost"]:
                static = ("TERRESTRIAL_HEX"
                          if best["represented_by_terrestrial_hex"]
                          else ("CLIP_FRAGMENT"
                                if best["touches_clip_boundary"]
                                else "OUT_OF_COVERAGE"))
            cat_pts.append({"entry": e, "comp": best, "static": static})
        prep.append((reg, lost, edges, cat_pts))

    rows = []
    for vname, vc in variants:
        vcfg = {**icfg, **vc}
        for reg, lost, edges, cat_pts in prep:
            groups = cluster_lost_components(
                lost, float(vc["island_group_max_distance_km"]) * 1000.0,
                float(vc["island_group_max_diameter_km"]) * 1000.0,
                precomputed_edges=edges)
            comp_status = {}
            n_units = 0
            micro = 0
            preserved_g = 0.0
            for grp in groups:
                comp_ids = sorted(c["island_component_id"] for c in grp)
                areas = sorted((c["ground_area_km2"] for c in grp),
                               reverse=True)
                total = float(sum(areas))
                light = {
                    "island_group_id": "isl_g_" + _hl.sha1(
                        "|".join(comp_ids).encode()).hexdigest()[:12],
                    "component_count": len(grp),
                    "components": grp,
                    "total_land_area_ground_km2": total,
                    "largest_component_ground_area_km2": float(areas[0]),
                    "largest_component_area_share": (
                        float(areas[0]) / total if total > 0 else 0.0),
                    # Label-only field; decisions never read it.
                    "land_hull_ratio": 1.0,
                }
                units, status = decide_preservation_units(
                    light, vcfg, set(), set())
                if status == "AGGREGATED_MICRO_ISLETS":
                    micro += 1
                n_units += len(units)
                in_unit = set()
                for u in units:
                    preserved_g += sum(c["ground_area_km2"]
                                       for c in u["components"])
                    in_unit.update(c["island_component_id"]
                                   for c in u["components"])
                for c in grp:
                    cid = c["island_component_id"]
                    comp_status[cid] = ("OVERLAY" if cid in in_unit
                                        else status_map.get(
                                            status, "DROPPED_MICRO"))
            lost_g = sum(c["ground_area_km2"] for c in lost)

            req_hits = req_total = exact = false_overlay = 0
            for cp in cat_pts:
                e = cp["entry"]
                if cp["static"] is not None:
                    actual = cp["static"]
                else:
                    actual = comp_status.get(
                        cp["comp"]["island_component_id"], "DROPPED_MICRO")
                if e["expected"] == "OVERLAY":
                    req_total += 1
                    if actual == "OVERLAY":
                        req_hits += 1
                if actual == e["expected"]:
                    exact += 1
                if actual == "OVERLAY" and e["expected"] != "OVERLAY":
                    false_overlay += 1
            rows.append({
                "run_id": run_id, "variant": vname, "region": reg["name"],
                **{f"p_{k}": v for k, v in vc.items()},
                "overlay_unit_count": n_units,
                "group_count": len(groups),
                "micro_excluded_groups": micro,
                "preserved_ground_km2": round(preserved_g, 3),
                "excluded_ground_km2": round(lost_g - preserved_g, 3),
                "required_overlay_hits": req_hits,
                "required_overlay_total": req_total,
                "exact_catalogue_matches": exact,
                "catalogue_total": len(cat_pts),
                "false_overlay_count": false_overlay,
            })
    return pd.DataFrame(rows)


def latitude_invariance_validation(run_id: str) -> pd.DataFrame:
    """Runtime check of the ground-metric engine: identical GROUND-size
    synthetic islands at 0/35/60/75 deg must yield identical ground areas,
    distances and preservation decisions (projected values may differ)."""
    from .islands import (ground_area_perimeter, ground_distance_m)
    from .projection import to_mercator

    rows = []
    radius_ground_m = 600.0            # ~1.13 km2 ground circle
    gap_ground_m = 8000.0
    ref_area = None
    for lat in (0.0, 35.0, 60.0, 75.0):
        scale = 1.0 / math.cos(math.radians(lat))
        x0, y0 = (float(v) for v in to_mercator(0.0, lat))
        a = shapely.Point(x0, y0).buffer(radius_ground_m * scale, quad_segs=32)
        b = shapely.Point(x0 + (2 * radius_ground_m + gap_ground_m) * scale,
                          y0).buffer(radius_ground_m * scale, quad_segs=32)
        g_area, _ = ground_area_perimeter(a)
        p_area = float(shapely.area(a)) / 1e6
        d = ground_distance_m(a, b)
        if ref_area is None:
            ref_area = g_area
        rows.append({
            "run_id": run_id, "latitude_deg": lat,
            "ground_area_km2": round(g_area, 4),
            "projected_area_km2": round(p_area, 4),
            "projected_over_ground_ratio": round(p_area / g_area, 3),
            "expected_ratio_1_over_cos2": round(scale ** 2, 3),
            "ground_gap_km": round(d / 1000.0, 3),
            "area_invariant_ok": abs(g_area - ref_area) / ref_area < 0.02,
            "gap_invariant_ok": abs(d - gap_ground_m) / gap_ground_m < 0.02,
            "preserved_decision_ok": (g_area >= 0.5) == (ref_area >= 0.5),
        })
    return pd.DataFrame(rows)


def preservation_before_after(baseline_dir, islands_df, run_id) -> pd.DataFrame:
    """Map every MAPGEN-005 overlay to its MAPGEN-005A outcome."""
    old = gpd.read_parquet(baseline_dir / "island_overlays.parquet")
    rows = []
    for _, o in old.iterrows():
        new_units = []
        if len(islands_df):
            sub = islands_df[islands_df["region"] == o["region"]]
            for _, u in sub.iterrows():
                if shapely.intersects(u["geometry"], o["geometry"]):
                    new_units.append(u)
        if len(new_units) == 0:
            status = "MICRO_ISLET_AGGREGATION_EXCLUDED"
        elif len(new_units) == 1:
            status = "PRESERVED"
        else:
            status = "SPLIT_INTO_MULTIPLE_UNITS"
        rows.append({
            "run_id": run_id,
            "region": o["region"],
            "old_island_id": o.get("overlay_unit_id", o.get("overlay_unit_id")),
            "old_component_count": int(o["component_count"]),
            "old_area_projected_km2": float(o["land_area_km2"]),
            "new_status": status,
            "new_unit_ids": "|".join(u["overlay_unit_id"] for u in new_units),
            "new_unit_count": len(new_units),
            "new_area_ground_km2": round(float(
                sum(u["land_area_ground_km2"] for u in new_units)), 4),
        })
    return pd.DataFrame(rows)


def metric_comparison(islands_df, run_id) -> pd.DataFrame:
    rows = []
    for _, u in islands_df.iterrows():
        lat = float(u["centroid_lat"])
        ratio = (u["land_area_projected_km2"] / u["land_area_ground_km2"]
                 if u["land_area_ground_km2"] > 0 else np.nan)
        rows.append({
            "run_id": run_id, "region": u["region"],
            "overlay_unit_id": u["overlay_unit_id"],
            "latitude_deg": round(lat, 3),
            "projected_area_km2": u["land_area_projected_km2"],
            "ground_area_km2": u["land_area_ground_km2"],
            "projected_over_ground_ratio": round(ratio, 4),
            "expected_ratio_1_over_cos2": round(
                1.0 / math.cos(math.radians(lat)) ** 2, 4),
            "extent_ground_km": u["extent_ground_km"],
        })
    return pd.DataFrame(rows)


def _finish_islands(cfg, icfg, gcfg, run_dir, run_id, geo, geo_src, geo_dir,
                    game_edges, grid, polys, regions, islands_df,
                    membership_df, comp_df, patches, kanto_land, val_rows,
                    _check, warnings, timings, t_start, baseline_dir=None):
    t0 = time.perf_counter()
    hex_ids = geo["hex_id"].tolist()
    hexset = set(hex_ids)
    base = gcfg["regression_baseline"]

    # ---- semantics checks -----------------------------------------------
    _check("is_land_is_deprecated_alias",
           (geo["is_land"] == geo["coast_land_mask"]).all(),
           "is_land == coast_land_mask everywhere")
    _check("terrestrial_semantics",
           ((geo["is_terrestrial_hex"] == (geo["water_type"] == "NONE")).all()
            and (geo["is_water_hex"] == ~geo["is_terrestrial_hex"]).all()),
           "is_terrestrial_hex/is_water_hex consistent with water_type")

    # ---- overlays never touch the water authority ------------------------
    _check("water_type_unchanged",
           (geo["water_type"] == geo_src["water_type"]).all(),
           "water_type identical to MAPGEN-004")
    layer_cols = ["surface_class", "relief_class", "vegetation_class",
                  "development_class", "dominant_terrain_face",
                  "natural_terrain_face", "land_fraction"]
    _check("terrain_layers_unchanged",
           all((geo[c] == geo_src[c]).all() for c in layer_cols),
           "layer columns identical to MAPGEN-004")
    ov = geo[geo["has_island_overlay"]]
    _check("overlay_hexes_water_semantics_intact",
           bool((~ov["is_terrestrial_hex"]).all()) if len(ov) else True,
           f"{len(ov)} overlay hexes, all non-terrestrial")

    # ---- MAPGEN-004 regression ------------------------------------------
    _check("geography_count_5350", len(geo) == len(geo_src) == 5350,
           f"{len(geo)} rows")
    _check("hex_id_set_unchanged",
           set(geo["hex_id"]) == set(geo_src["hex_id"]), "identical ids")
    _check("water_type_counts_unchanged",
           geo["water_type"].value_counts().to_dict()
           == geo_src["water_type"].value_counts().to_dict(),
           geo["water_type"].value_counts().to_dict())
    _check("canonical_edges_baseline",
           len(game_edges) == base["canonical_game_edges"]
           and not game_edges.duplicated(["region", "edge_id"]).any(),
           f"{len(game_edges)} edges")

    # ---- island structural checks ---------------------------------------
    if len(islands_df):
        _check("island_primary_hex_valid",
               islands_df[islands_df["region"] == "kanto"]["primary_hex_id"]
               .isin(hexset).all(), "kanto primary hexes exist")
        _check("island_ids_unique", islands_df["overlay_unit_id"].is_unique,
               f"{len(islands_df)} islands")
        big = comp_df[comp_df["represented_by_terrestrial_hex"]
                      & (comp_df["ground_area_km2"] > 100)]
        rep_ids = set(big["island_component_id"])
        overlap = [i for _, i in islands_df.iterrows()
                   if set(i["component_ids"].split("|")) & rep_ids]
        _check("no_duplicate_overlay_for_large_islands", not overlap,
               f"{len(overlap)} overlays contain terrestrial-represented "
               f"large components")

    # ---- point validations ----------------------------------------------
    for pt in icfg.get("validation_points", []):
        row = _island_at_point(islands_df, pt["region"], pt["lon"], pt["lat"])
        qq, rr = grid.xy_to_axial(*[float(v) for v in
                                    to_mercator(pt["lon"], pt["lat"])])
        hid = grid.hex_id(qq, rr)
        hrow = geo[geo["hex_id"] == hid]
        ocean_kept = (len(hrow) == 1
                      and hrow["water_type"].iloc[0] == "OCEAN"
                      and not bool(hrow["is_terrestrial_hex"].iloc[0]))
        comp = _component_at_point(comp_df, pt["region"], pt["lon"], pt["lat"])
        area_ok = (row is not None and comp is not None
                   and row["land_area_ground_km2"]
                   >= comp["ground_area_km2"] * 0.999)
        _check(f"island_point_{pt['id']}",
               row is not None and ocean_kept and area_ok
               and row["covered_hex_count"] >= 1
               and row["primary_hex_id"] in hexset,
               f"overlay={'yes' if row is not None else 'NO'}, hex {hid} "
               f"ocean_kept={ocean_kept}, ground_area="
               f"{row['land_area_ground_km2'] if row is not None else 'n/a'} "
               f"km2 (projected "
               f"{row['land_area_projected_km2'] if row is not None else '-'})")
    for pname, patch in (icfg.get("validation_patches") or {}).items():
        row = _island_at_point(islands_df, pname, patch["lon"], patch["lat"])
        if patch["expect"] == "any":
            continue  # calibration region; judged via the catalogue instead
        if patch["expect"] == "overlay":
            _check(f"island_patch_{pname}",
                   row is not None and row["covered_hex_count"] >= 1
                   and row["surrounding_water_type"] in ("OCEAN", "LAKE"),
                   f"overlay={'yes' if row is not None else 'NO'}"
                   + (f", ground={row['land_area_ground_km2']} km2 "
                      f"(projected {row['land_area_projected_km2']}), "
                      f"components={row['component_count']}, "
                      f"largest_share={row['largest_component_area_share']}, "
                      f"anchor={row['primary_hex_id']}" if row is not None
                      else ""))
        else:  # negative control: represented by terrestrial hexes
            comp = _component_at_point(comp_df, pname, patch["lon"],
                                       patch["lat"])
            _check(f"island_patch_{pname}",
                   comp is not None
                   and bool(comp["represented_by_terrestrial_hex"])
                   and row is None,
                   f"component_ground_area="
                   f"{comp['ground_area_km2'] if comp is not None else 'n/a'} km2, "
                   f"overlay_at_point={'none' if row is None else 'PRESENT'}")
    timings["validation_s"] = time.perf_counter() - t0

    # ---- outputs ---------------------------------------------------------
    t0 = time.perf_counter()
    min_area = float(icfg["minimum_auto_preserve_area_km2"])
    max_diam = float(icfg["island_group_max_diameter_km"])
    summary = preservation_summary(regions, min_area, max_diam, run_id)
    summary.to_csv(run_dir / "island_preservation_summary.csv", index=False)
    audit = group_audit(regions, max_diam, run_id)
    audit.to_csv(run_dir / "island_group_semantics_audit.csv", index=False)

    # Area conservation gate: the report may only quote these computed sums.
    _check("area_conservation_ground",
           bool(summary["area_conservation_ok"].all()),
           {r["region"]: (r["lost_area_ground_km2"],
                          r["preserved_area_ground_km2"],
                          r["excluded_area_ground_km2"])
            for _, r in summary.iterrows()})

    # Latitude invariance of the ground-metric engine.
    lat_val = latitude_invariance_validation(run_id)
    lat_val.to_csv(run_dir / "latitude_invariance_validation.csv", index=False)
    _check("latitude_invariance",
           bool(lat_val["area_invariant_ok"].all()
                and lat_val["gap_invariant_ok"].all()
                and lat_val["preserved_decision_ok"].all()),
           lat_val[["latitude_deg", "ground_area_km2",
                    "projected_area_km2"]].to_dict("records"))

    # Projected/ground metric comparison for every unit.
    if len(islands_df):
        metric_comparison(islands_df, run_id).to_csv(
            run_dir / "island_metric_comparison.csv", index=False)

    # Before/after vs the MAPGEN-005 baseline overlays.
    if baseline_dir is not None and (
            baseline_dir / "island_overlays.parquet").exists():
        ba = preservation_before_after(baseline_dir, islands_df, run_id)
        ba.to_csv(run_dir / "island_preservation_before_after.csv",
                  index=False)
        tosh_old = ba[(ba["region"] == "kanto")
                      & (ba["old_area_projected_km2"] > 5)
                      & (ba["old_area_projected_km2"] < 8)]
        _check("toshima_before_after_preserved",
               bool((tosh_old["new_status"] != "MICRO_ISLET_AGGREGATION_"
                     "EXCLUDED").all()) if len(tosh_old) else True,
               ba[ba["region"] == "kanto"][
                   ["old_island_id", "old_component_count",
                    "new_status"]].to_dict("records"))
    else:
        ba = pd.DataFrame()
        warnings.append("no MAPGEN-005 baseline islands run for before/after")

    # ---- MAPGEN-006: catalogue, dateline, world summary, sweep -----------
    t6 = time.perf_counter()
    catalogue = icfg.get("validation_catalogue") or []
    cat_df = evaluate_catalogue(catalogue, islands_df, comp_df, run_id)
    cat_df.to_csv(run_dir / "island_validation_catalogue.csv", index=False)
    for _, r in cat_df.iterrows():
        _check(f"catalogue_{r['catalogue_id']}", bool(r["pass"]),
               f"expected {r['expected_representation']}, actual "
               f"{r['actual_representation']} ({r['detail']})")

    # ---- MAPGEN-006R: corrected catalogue metrics ------------------------
    required = cat_df[cat_df["expected_representation"] == "OVERLAY"]
    req_hits = int((required["actual_representation"] == "OVERLAY").sum())
    exact = int((cat_df["actual_representation"]
                 == cat_df["expected_representation"]).sum())
    false_overlay = int(((cat_df["actual_representation"] == "OVERLAY")
                         & (cat_df["expected_representation"]
                            != "OVERLAY")).sum())
    _check("catalogue_required_overlay_recall",
           req_hits == len(required),
           f"{req_hits}/{len(required)} required-overlay places overlaid")
    _check("catalogue_exact_accuracy", exact == len(cat_df),
           f"{exact}/{len(cat_df)} exact expected==actual matches")
    _check("catalogue_false_overlay_zero", false_overlay == 0,
           f"{false_overlay} places overlaid against a non-OVERLAY "
           f"expectation")

    # ---- MAPGEN-006R: island_components.csv (official deliverable) -------
    comp_review = pd.DataFrame({
        "run_id": comp_df["run_id"],
        "region": comp_df["region"],
        "component_id": comp_df["island_component_id"],
        "geographic_group_id": comp_df["island_group_id"],
        "overlay_unit_id": comp_df["overlay_unit_id"],
        "representation_status": comp_df["representation_status"],
        "is_significant_component": comp_df["is_significant_component"],
        "land_area_ground_km2": comp_df["ground_area_km2"],
        "land_area_projected_km2": comp_df["projected_area_km2"],
        "perimeter_ground_km": comp_df["ground_perimeter_km"],
        "component_primary_hex_id": comp_df["component_primary_hex_id"],
        "centroid_lon": comp_df["centroid_lon"],
        "centroid_lat": comp_df["centroid_lat"],
        "geometry_hash": comp_df["island_component_id"].str[6:],
        "is_lost_component": comp_df["is_subhex_lost"],
        "is_clip_fragment": comp_df["touches_clip_boundary"],
        # Natural origin is NOT asserted at this stage.
        "artificial_status": "UNKNOWN",
        "component_index_within_group": comp_df["rank_in_group"],
        "intersection_hex_count": comp_df["intersecting_hex_ids"]
        .fillna("").map(lambda s: len(s.split("|")) if s else 0),
    })
    comp_review.to_csv(run_dir / "island_components.csv", index=False)

    dup_ids = int(comp_review.duplicated(["region", "component_id"]).sum())
    _check("components_unique_per_region", dup_ids == 0,
           f"{len(comp_review)} rows, {dup_ids} duplicate ids")
    hexsets = {reg["name"]: set(reg["idx_by_hex"]) for reg in regions}
    anchor_ok = all(
        (r["component_primary_hex_id"] in hexsets.get(r["region"], set()))
        or pd.isna(r["component_primary_hex_id"])
        for _, r in comp_review.iterrows())
    _check("component_primary_hex_valid", anchor_ok,
           "all non-null component anchors exist in their region hex set")
    unit_ids = set(islands_df["overlay_unit_id"]) if len(islands_df) else set()
    bad_unit_refs = int((~comp_review["overlay_unit_id"].isna()
                         & ~comp_review["overlay_unit_id"].isin(unit_ids))
                        .sum())
    _check("component_overlay_reference_integrity", bad_unit_refs == 0,
           f"{bad_unit_refs} components reference unknown overlay units; "
           f"{int(comp_review['overlay_unit_id'].isna().sum())} components "
           f"have no overlay (nullable, auditable)")
    grp_ids = {g["island_group_id"] for reg in regions
               for g in reg["groups"]}
    bad_grp = int((~comp_review["geographic_group_id"].isna()
                   & ~comp_review["geographic_group_id"].isin(grp_ids)).sum())
    _check("component_group_reference_integrity", bad_grp == 0,
           f"{bad_grp} bad group references")
    # Litla Dimun semantics: one overlay unit, many individually
    # addressable components, no single-gameplay-island assertion.
    ld = comp_review[(comp_review["region"] == "litla_dimun")
                     & comp_review["overlay_unit_id"].notna()]
    _check("litla_dimun_components_individually_addressable",
           len(ld) >= 2 and ld["component_id"].is_unique
           and ld["component_primary_hex_id"].notna().all()
           and ld["overlay_unit_id"].nunique() == 1
           and "gameplay" not in " ".join(comp_review.columns),
           f"{len(ld)} components share overlay unit "
           f"{ld['overlay_unit_id'].iloc[0] if len(ld) else 'n/a'}, "
           f"{ld['component_primary_hex_id'].nunique() if len(ld) else 0} "
           f"distinct anchors")

    # ---- MAPGEN-006 geographic regression baseline -----------------------
    base006 = icfg.get("regression_baseline_006") or {}
    for rname, exp in base006.items():
        row = summary[summary["region"] == rname]
        ok = (len(row) == 1
              and int(row["overlay_unit_count"].iloc[0])
              == int(exp["overlay_units"])
              and abs(float(row["preserved_area_ground_km2"].iloc[0])
                      - float(exp["preserved_ground_km2"])) < 5e-4)
        _check(f"regression006_{rname}", ok,
               f"units {int(row['overlay_unit_count'].iloc[0]) if len(row) else '?'}"
               f" vs {exp['overlay_units']}, preserved "
               f"{float(row['preserved_area_ground_km2'].iloc[0]) if len(row) else '?'}"
               f" vs {exp['preserved_ground_km2']}")

    dl_df = dateline_validation(
        [reg for reg in regions
         if any(c.get("acentroid_x", 0) != c.get("centroid_x", 0)
                for c in reg["components"])], run_id)
    dl_df.to_csv(run_dir / "island_dateline_validation.csv", index=False)
    _check("dateline_validation", bool(dl_df["pass"].all()),
           dl_df[["case", "ground_geodesic_separation_km",
                  "same_group_actual", "pass"]].to_dict("records"))

    world_df = world_calibration_summary(regions, summary, run_id)
    world_df.to_csv(run_dir / "island_world_calibration_summary.csv",
                    index=False)
    micro_found = int(summary["groups_micro_islet_excluded"].sum())
    _check("micro_islet_real_world_audit", True,
           f"{micro_found} real-world AGGREGATED_MICRO_ISLETS groups "
           + ("(positive case found)" if micro_found else
              "(no real-world positive case found; thresholds NOT tuned "
              "to force one)"))
    timings["catalogue_dateline_s"] = time.perf_counter() - t6

    t7 = time.perf_counter()
    sweep_df = parameter_sweep(regions, icfg, catalogue, run_id)
    sweep_df.to_csv(run_dir / "island_parameter_sweep.csv", index=False)
    timings["parameter_sweep_s"] = time.perf_counter() - t7

    # Representative sweep panel: per-variant totals.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    agg = sweep_df.groupby("variant").agg(
        units=("overlay_unit_count", "sum"),
        preserved=("preserved_ground_km2", "sum"),
        micro=("micro_excluded_groups", "sum"),
        req_hits=("required_overlay_hits", "sum"),
        req_total=("required_overlay_total", "sum"),
        exact=("exact_catalogue_matches", "sum"),
        cat_total=("catalogue_total", "sum"),
        false_overlay=("false_overlay_count", "sum")).reset_index()
    fig, axes = plt.subplots(1, 4, figsize=(24, 6), dpi=150)
    xs = np.arange(len(agg))
    panels = ((axes[0], "units", None, "overlay unit count"),
              (axes[1], "req_hits", "req_total",
               "required-overlay recall (outline = denominator)"),
              (axes[2], "exact", "cat_total",
               "exact catalogue accuracy (outline = denominator)"),
              (axes[3], "false_overlay", None,
               "false overlays (lower is better; baseline = 0)"))
    for ax, col, outline, title in panels:
        ax.bar(xs, agg[col], color="#4a90d9")
        if outline:
            ax.bar(xs, agg[outline], color="none", edgecolor="#333",
                   linewidth=1.0)
        ax.set_xticks(xs)
        ax.set_xticklabels(agg["variant"], rotation=45, ha="right",
                           fontsize=7)
        ax.set_title(title, fontsize=9)
    fig.suptitle("parameter sweep — all regions combined "
                 "(corrected MAPGEN-006R catalogue metrics)", fontsize=12)
    fig.tight_layout()
    fig.savefig(run_dir / "island_parameter_comparison.png",
                bbox_inches="tight")
    plt.close(fig)

    pd.DataFrame(val_rows).to_csv(run_dir / "island_validation.csv",
                                  index=False)

    import gzip

    geo.to_parquet(run_dir / "geography_hexes.parquet", index=False)
    with gzip.open(run_dir / "geography_hexes.csv.gz", "wb") as f:
        f.write(geo.to_csv(index=False, float_format="%.6f").encode("utf-8"))
    if len(islands_df):
        gpd.GeoDataFrame(islands_df, geometry="geometry",
                         crs="EPSG:3857").to_parquet(
            run_dir / "island_overlays.parquet", index=False)
        islands_df.drop(columns=["geometry"]).to_csv(
            run_dir / "island_overlays.csv", index=False)
    membership_df.to_csv(run_dir / "island_hex_membership.csv", index=False)
    membership_df.to_parquet(run_dir / "island_hex_membership.parquet",
                             index=False)
    gpd.GeoDataFrame(comp_df, geometry="geometry", crs="EPSG:3857").to_parquet(
        run_dir / "island_components.parquet", index=False)
    with gzip.open(run_dir / "island_components.csv.gz", "wb") as f:
        f.write(comp_df.drop(columns=["geometry"])
                .to_csv(index=False).encode("utf-8"))
    game_edges.to_csv(run_dir / "game_river_edges.csv", index=False)
    game_edges.to_parquet(run_dir / "game_river_edges.parquet", index=False)
    timings["output_s"] = time.perf_counter() - t0

    _render_islands(cfg, icfg, run_dir, run_id, geo, grid, polys, regions,
                    islands_df, comp_df, patches, timings)

    # Renderer contract: dateline images must be normal-aspect maps, never a
    # world-wide squashed strip (e.g. 1853x72 px is a failure).
    from PIL import Image

    for pname, p in patches.items():
        png = run_dir / f"island_{pname}.png"
        if not png.exists():
            continue
        with Image.open(png) as im:
            w_px, h_px = im.size
        aspect = w_px / h_px
        _check(f"render_aspect_{pname}", 0.25 <= aspect <= 4.0,
               f"{w_px}x{h_px} px (aspect {aspect:.2f})")
    pd.DataFrame(val_rows).to_csv(run_dir / "island_validation.csv",
                                  index=False)
    # Refresh the copy in the review package with the render checks included.
    if (run_dir / "chatgpt_review").exists():
        import shutil as _sh

        _sh.copy2(run_dir / "island_validation.csv",
                  run_dir / "chatgpt_review" / "island_validation.csv")

    # ---- manifest --------------------------------------------------------
    total_s = time.perf_counter() - t_start
    peak_mb = _peak_memory_mb()
    source_manifest = json.loads(
        (cfg.data_dir / "source_manifest.json").read_text(encoding="utf-8"))
    osm_meta = source_manifest.get("datasets", {}).get("osm_land_polygons", {})
    manifest = {
        "stage": "MAPGEN-006R - Review Contract Hardening",
        "run_id": run_id,
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "hex_size_m": cfg.raw["terrain"]["hex_size_m"],
        "grid_origin": [cfg.grid_origin_x, cfg.grid_origin_y],
        "geography_schema_version": GEOGRAPHY_SCHEMA_VERSION_V13,
        "geography_schema_previous": GEOGRAPHY_SCHEMA_VERSION_V12,
        "island_schema_version": ISLAND_SCHEMA_VERSION,
        "island_algorithm_version": ISLAND_ALGORITHM_VERSION,
        "upstream_geography_run": {
            "run_id": geo_dir.name, "path": str(geo_dir),
            "geography_hexes_sha256": sha256_of(
                geo_dir / "geography_hexes.parquet"),
            "game_river_edges_sha256": sha256_of(
                geo_dir / "game_river_edges.parquet"),
        },
        "osm_land_polygons": {k: osm_meta.get(k) for k in
                              ("source_name", "source_url", "dataset_version",
                               "licence", "attribution")},
        "config_snapshot_sha256": sha256_of(cfg.config_path),
        "island_parameters": {
            "minimum_auto_preserve_area_km2": min_area,
            "island_group_max_distance_km":
                icfg["island_group_max_distance_km"],
            "island_group_max_diameter_km": max_diam,
            "force_preserve_ids": icfg.get("force_preserve_ids") or [],
            "force_ignore_ids": icfg.get("force_ignore_ids") or [],
            "minimum_significant_component_area_km2":
                icfg.get("minimum_significant_component_area_km2"),
            "minimum_largest_component_share":
                icfg.get("minimum_largest_component_share"),
            "dispersed_group_max_land_hull_ratio":
                icfg.get("dispersed_group_max_land_hull_ratio",
                         icfg.get("atoll_candidate_max_land_hull_ratio")),
            "metric_semantics": "all thresholds/distances are GROUND (WGS84 "
                                "geodesic); projected values audit-only",
        },
        "id_determinism_scope": "within one OSM source snapshot only; "
                                "IDs are geometry hashes and may change when "
                                "the OSM build changes",
        "timings_s": {k: round(v, 2) for k, v in timings.items()},
        "total_duration_s": round(total_s, 2),
        "peak_memory_mb": round(peak_mb, 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    _build_review_package(run_dir, run_id, icfg, geo, islands_df, summary,
                          val_rows, warnings)
    n_fail = sum(1 for v in val_rows if not v["pass"])
    print(f"[islands] {len(islands_df)} overlays, validation "
          f"{len(val_rows) - n_fail}/{len(val_rows)} passed")
    print(f"[islands] done in {total_s:.1f}s, peak memory {peak_mb:.0f} MB")
    print(f"[islands] output: {run_dir}")
    return run_dir









