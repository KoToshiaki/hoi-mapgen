"""MAPGEN-004 — Authoritative Geography Integration.

Joins the MAPGEN-001 hex grid, MAPGEN-002A layered terrain and MAPGEN-003A
hydrography into the single canonical game dataset:

  geography_hexes   — 1 hex = 1 row master table (kanto = MAPGEN-001 set)
  game_river_edges  — adopted UNCHANGED from MAPGEN-003A (canonical)

Principles:
- Never regenerate upstream pipelines. The only recomputation is the OSM
  coast classification over the FULL kanto hex set (the hydro run used a
  9 km margin vs terrain's 15 km, so the outer ring lacks hydro land values)
  plus HydroLAKES per-hex stats over the same set, and incremental terrain
  resampling for individual hexes whose raw data is invalid.
- Water authority = MAPGEN-003A hydro (OSM land + HydroLAKES + water-hex
  rivers). MAPGEN-002A's WorldCover water estimate and the Natural Earth
  mask are demoted to audit columns.
- Priority on conflict: OCEAN > LAKE > RIVER > NONE; conflicts are reported,
  never silently resolved differently.
"""
from __future__ import annotations

import datetime as _dt
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import shapely

from .config import MapgenConfig
from .hex_edges import build_edge_graph
from .hex_grid import HexGrid
from .hydro_pipeline import hex_lake_stats, load_lakes, load_osm_land
from .hydro_sources import hydrolakes_shp, osm_land_shp
from .land import classify_hexes, source_coastline
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .projection import bbox_to_mercator
from .rivers import RIVER_CLASSES
from .sources import sha256_of
from .terrain import sample_region_terrain
from .terrain_face import military_metrics
from .terrain_layers import (TERRAIN_SCHEMA_VERSION_V3, WATER_TYPE_ID,
                             classify_layers_authoritative)
from .terrain_pipeline import FRACTION_RENAMES

GEOGRAPHY_SCHEMA_VERSION = "1.0.0"       # geography_hexes master schema
# MAPGEN-004 integration algorithm namespace (new; NOT the MAPGEN-001..003
# generation algorithm_version, which stays with those pipelines).
INTEGRATION_ALGORITHM_VERSION = "1.0.0"

RAW_TERRAIN_COLUMNS = [
    "elevation_mean_m", "elevation_min_m", "elevation_max_m",
    "elevation_range_m", "slope_mean_deg", "slope_p90_deg", "slope_max_deg",
    "terrain_roughness", "dem_nodata_fraction",
    "tree_fraction", "grassland_fraction", "cropland_fraction",
    "shrub_fraction", "bare_ground_fraction", "wetland_fraction",
    "urban_fraction", "permanent_snow_ice_fraction", "inland_water_fraction",
    "moss_lichen_fraction", "mangrove_fraction", "landcover_nodata_fraction",
    "climate_zone", "biome_class",
    "is_tropical", "is_arid", "is_cold", "is_tundra_climate",
    "is_ice_cap_climate",
]
MILITARY_COLUMNS = [
    "foot_mobility", "wheeled_mobility", "tracked_mobility", "visibility",
    "concealment", "defensive_value", "logistics_passability",
    "construction_suitability", "deployment_capacity",
]


def resolve_water_authority(is_ocean: np.ndarray, lake_fraction: np.ndarray,
                            is_river_corridor: np.ndarray,
                            lake_threshold: float):
    """Final water_type per hex with OCEAN > LAKE > RIVER > NONE priority.

    Returns (water_type array, conflicts list). A conflict is any hex where
    more than one authority claims water — resolved by priority, reported.
    """
    n = len(is_ocean)
    lake_cand = (~np.isnan(lake_fraction)) & (lake_fraction >= lake_threshold)
    water_type = np.full(n, "NONE", dtype=object)
    conflicts = []
    for i in range(n):
        claims = []
        if is_ocean[i]:
            claims.append("OCEAN")
        if lake_cand[i]:
            claims.append("LAKE")
        if is_river_corridor[i]:
            claims.append("RIVER")
        if claims:
            water_type[i] = claims[0]  # priority order == append order
            if len(claims) > 1:
                conflicts.append({
                    "index": i,
                    "claims": "|".join(claims),
                    "resolved": claims[0],
                    "lake_fraction": float(lake_fraction[i]),
                })
    return water_type, conflicts


def river_convenience_fields(hex_ids: list[str],
                             game_edges: pd.DataFrame) -> pd.DataFrame:
    """Lightweight per-hex river summary derived from game_river_edges.

    These are search helpers ONLY — the crossing authority remains the edge
    table, so effects can never be applied from both sides.
    """
    n = len(hex_ids)
    idx = {h: i for i, h in enumerate(hex_ids)}
    count = np.zeros(n, dtype=np.int64)
    max_class = np.full(n, "", dtype=object)
    max_dis = np.zeros(n)
    primary = np.full(n, "", dtype=object)
    rank = {c: i for i, c in enumerate(RIVER_CLASSES)}
    for _, row in game_edges.iterrows():
        for h in (row["hex_a_id"], row["hex_b_id"]):
            i = idx.get(h)
            if i is None:
                continue
            count[i] += 1
            if rank.get(row["dominant_river_class"], -1) >= rank.get(
                    max_class[i], -1):
                max_class[i] = row["dominant_river_class"]
            if row["max_discharge_m3_s"] > max_dis[i]:
                max_dis[i] = row["max_discharge_m3_s"]
                primary[i] = row["dominant_river_id"]
    return pd.DataFrame({
        "river_edge_count": count,
        "max_river_class": np.where(max_class == "", None, max_class),
        "max_river_discharge_m3_s": max_dis,
        "primary_river_id": np.where(primary == "", None, primary),
    })


def run_geography(cfg: MapgenConfig, run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    gcfg = cfg.raw["geography"]
    tcfg = cfg.raw["terrain"]
    if run_id is None:
        run_id = f"geography_v1_{_dt.datetime.now():%Y%m%d}"
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    val_rows: list[dict] = []

    def _check(check_id, ok, detail):
        val_rows.append({"run_id": run_id, "check_id": check_id,
                         "pass": bool(ok), "detail": str(detail)})
        if not ok:
            warnings.append(f"VALIDATION FAIL {check_id}: {detail}")

    # ---- input load ------------------------------------------------------
    t0 = time.perf_counter()
    terrain_dir = cfg.output_dir / gcfg["terrain_run"]
    hydro_dir = cfg.output_dir / gcfg["hydro_run"]
    m1_dir = cfg.output_dir / gcfg["mapgen001_run"] / "6000m"
    tdf_all = pd.read_parquet(terrain_dir / "terrain_hexes.parquet")
    tdf = tdf_all[tdf_all["region"] == "kanto"].reset_index(drop=True)
    m1_ids = set(pd.read_parquet(m1_dir / "hex_cells.parquet")["hex_id"])
    hydro_water = pd.read_csv(hydro_dir / "water_hexes.csv")
    game_edges = pd.read_csv(hydro_dir / "game_river_edges.csv")
    membership = pd.read_csv(hydro_dir / "river_edge_membership.csv")
    audit = pd.read_csv(hydro_dir / "river_confluence_audit.csv")
    whq = pd.read_csv(hydro_dir / "water_hex_river_quality.csv")
    timings["input_load_s"] = time.perf_counter() - t0

    # Canonical order: sort by hex_id.
    tdf = tdf.sort_values("hex_id").reset_index(drop=True)
    hex_ids = tdf["hex_id"].tolist()
    q = tdf["q"].to_numpy()
    r = tdf["r"].to_numpy()
    grid = HexGrid(flat_to_flat=float(tcfg["hex_size_m"]),
                   orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)
    polys = grid.polygons(q, r)
    centres = np.stack(grid.axial_to_xy(q, r), axis=1)

    # ---- coast authority over the FULL kanto set -------------------------
    # (The hydro run classified only its 9 km-margin subset; terrain uses a
    # 15 km margin. This is a targeted recomputation of ONE stage — the same
    # deterministic classify_hexes over the same OSM source — not a rerun of
    # the hydro pipeline.)
    t0 = time.perf_counter()
    bbox_3857 = bbox_to_mercator(cfg.bbox_wgs84)
    clip_margin = cfg.margin_m + 10000.0
    osm_land = load_osm_land(osm_land_shp(cfg.data_dir), bbox_3857, clip_margin)
    min_x, min_y, max_x, max_y = bbox_3857
    osm_coast = source_coastline(osm_land, (min_x - clip_margin,
                                            min_y - clip_margin,
                                            max_x + clip_margin,
                                            max_y + clip_margin))
    osm_cls = classify_hexes(polys, centres, osm_land, osm_coast, grid.area,
                             cfg.land_threshold)
    # Consistency with the hydro run where both computed the same hexes.
    hk = hydro_water[hydro_water["region"] == "kanto"]
    hydro_lf = dict(zip(hk["hex_id"], hk["land_fraction"]))
    mism = sum(1 for h, lf in zip(hex_ids, osm_cls["land_fraction"])
               if h in hydro_lf and abs(hydro_lf[h] - round(float(lf), 4)) > 1e-3)
    _check("coast_matches_hydro_run", mism == 0,
           f"{mism} overlap hexes differ from hydro land_fraction")
    timings["coast_authority_s"] = time.perf_counter() - t0

    # ---- lakes over the full set ----------------------------------------
    t0 = time.perf_counter()
    lakes = load_lakes(hydrolakes_shp(cfg.data_dir),
                       (cfg.bbox_wgs84.min_x - 0.3, cfg.bbox_wgs84.min_y - 0.3,
                        cfg.bbox_wgs84.max_x + 0.3, cfg.bbox_wgs84.max_y + 0.3),
                       float(cfg.raw["hydro"]["lake"]["min_lake_area_km2"]))
    lake_df = hex_lake_stats(polys, hex_ids, grid.area, lakes)
    timings["lake_s"] = time.perf_counter() - t0

    # ---- water authority resolution --------------------------------------
    t0 = time.perf_counter()
    is_ocean = (osm_cls["land_class"] == "water")
    river_hexes = set(hk[hk["water_type"] == "RIVER"]["hex_id"])
    is_river = np.array([h in river_hexes for h in hex_ids])
    water_type, conflicts = resolve_water_authority(
        np.asarray(is_ocean), lake_df["lake_fraction"].to_numpy(),
        is_river, float(cfg.raw["hydro"]["lake"]["majority_threshold"]))
    conflict_rows = [{
        "run_id": run_id, "hex_id": hex_ids[c["index"]],
        "claims": c["claims"], "resolved_water_type": c["resolved"],
        "lake_fraction": c["lake_fraction"],
        "land_fraction": round(float(osm_cls["land_fraction"][c["index"]]), 4),
    } for c in conflicts]
    pd.DataFrame(conflict_rows, columns=[
        "run_id", "hex_id", "claims", "resolved_water_type", "lake_fraction",
        "land_fraction"]).to_csv(
        run_dir / "water_authority_conflicts.csv", index=False)
    timings["water_authority_s"] = time.perf_counter() - t0

    # ---- coast-change audit ---------------------------------------------
    t0 = time.perf_counter()
    ne_lf = tdf["land_fraction"].to_numpy(dtype=float)
    ne_land = tdf["land_class"].to_numpy() == "land"
    osm_lf = np.asarray(osm_cls["land_fraction"], dtype=float)
    osm_is_land = ~np.asarray(is_ocean)
    thr = float(gcfg["land_fraction_change_threshold"])
    changed = []
    for i, h in enumerate(hex_ids):
        cat = None
        if ne_land[i] and not osm_is_land[i]:
            cat = "NE_LAND_TO_OSM_WATER"
        elif (not ne_land[i]) and osm_is_land[i]:
            cat = "NE_WATER_TO_OSM_LAND"
        elif abs(ne_lf[i] - osm_lf[i]) > thr:
            cat = "LAND_FRACTION_SHIFT"
        if cat:
            changed.append({
                "run_id": run_id, "hex_id": h, "change_category": cat,
                "ne_land_fraction": round(float(ne_lf[i]), 4),
                "osm_land_fraction": round(float(osm_lf[i]), 4),
                "final_water_type": water_type[i],
                "needs_layer_reeval": cat != "LAND_FRACTION_SHIFT",
                "terrain_resampled": False,
            })
    changed_df = pd.DataFrame(changed, columns=[
        "run_id", "hex_id", "change_category", "ne_land_fraction",
        "osm_land_fraction", "final_water_type", "needs_layer_reeval",
        "terrain_resampled"])

    # ---- incremental terrain correction ----------------------------------
    # Raw terrain was sampled for EVERY hex in MAPGEN-002A (water included),
    # so newly-land hexes normally reuse their existing raw values. Only
    # hexes whose landcover coverage is invalid get resampled, individually.
    resample_thr = float(gcfg["resample_landcover_nodata_threshold"])
    newly_land = [i for i, h in enumerate(hex_ids)
                  if (not ne_land[i]) and osm_is_land[i]]
    need_resample = [i for i in newly_land
                     if (tdf["landcover_nodata_fraction"].iloc[i] > resample_thr
                         or not np.isfinite(tdf["elevation_mean_m"].iloc[i]))]
    if need_resample:
        sub_polys = polys[np.array(need_resample)]
        raw_new, _ = sample_region_terrain(sub_polys, cfg.data_dir, tcfg)
        raw_new["wetland_fraction"] = (raw_new["lc_herbaceous_wetland_fraction"]
                                       + raw_new["lc_mangroves_fraction"])
        raw_new = raw_new.rename(columns=FRACTION_RENAMES)
        from .terrain_face import climate_flags

        raw_new = pd.concat(
            [raw_new, climate_flags(raw_new["koppen_class"].to_numpy())], axis=1)
        for j, i in enumerate(need_resample):
            for col in RAW_TERRAIN_COLUMNS:
                if col in raw_new.columns:
                    tdf.loc[i, col] = raw_new[col].iloc[j]
        resampled_ids = {hex_ids[i] for i in need_resample}
        changed_df.loc[changed_df["hex_id"].isin(resampled_ids),
                       "terrain_resampled"] = True
    changed_df.to_csv(run_dir / "integration_changed_hexes.csv", index=False)
    _check("newly_land_terrain_available", True,
           f"{len(newly_land)} newly-land hexes, "
           f"{len(need_resample)} incrementally resampled")

    # ---- layer classification with authoritative water --------------------
    layers = classify_layers_authoritative(tdf, tcfg, water_type)
    timings["terrain_correction_s"] = time.perf_counter() - t0

    # ---- assemble geography_hexes ----------------------------------------
    t0 = time.perf_counter()
    lon = tdf["centre_lon"].to_numpy()
    lat = tdf["centre_lat"].to_numpy()
    geo = pd.DataFrame({
        "geography_schema_version": GEOGRAPHY_SCHEMA_VERSION,
        "run_id": run_id,
        "region": "kanto",
        "hex_id": hex_ids,
        "q": q, "r": r,
        "centre_x_m": centres[:, 0], "centre_y_m": centres[:, 1],
        "centre_lon": lon, "centre_lat": lat,
        "hex_size_m": float(tcfg["hex_size_m"]),
        "hex_area_m2": grid.area,
        # authoritative land/water (OSM coast + HydroLAKES + hydro rivers)
        "land_fraction": osm_lf,
        "is_land": osm_is_land,
        "is_coastal": np.asarray(osm_cls["is_coastal"], dtype=bool),
        "lake_fraction": lake_df["lake_fraction"].to_numpy(),
        "lake_ids": lake_df["lake_ids"],
        "primary_lake_id": lake_df["primary_lake_id"],
        "primary_lake_name": lake_df["primary_lake_name"],
        "primary_lake_area_km2": lake_df["primary_lake_area_km2"],
        "is_water_hex_river": is_river,
        # audit-only Natural Earth comparison (NOT game authority)
        "ne_land_fraction_audit": ne_lf,
        "ne_land_class_audit": tdf["land_class"],
    })
    geo = pd.concat([geo, tdf[RAW_TERRAIN_COLUMNS].reset_index(drop=True),
                     layers.reset_index(drop=True)], axis=1)
    mil = military_metrics(tdf, None)
    geo = pd.concat([geo, mil.reset_index(drop=True)], axis=1)
    kanto_edges = game_edges[game_edges["region"] == "kanto"]
    geo = pd.concat([geo, river_convenience_fields(hex_ids, kanto_edges)],
                    axis=1)
    timings["join_s"] = time.perf_counter() - t0
    return _finish_geography(cfg, gcfg, run_dir, run_id, geo, grid, polys,
                             osm_coast, game_edges, membership, audit, whq,
                             changed_df, conflict_rows, m1_ids, val_rows,
                             _check, warnings, timings, t_start,
                             terrain_dir, hydro_dir, m1_dir)


def confluence_offset_stats(audit: pd.DataFrame, review_m: float) -> dict:
    d = audit["distance_m"].dropna().to_numpy(dtype=float)
    if len(d) == 0:
        return {"count": 0}
    return {
        "count": int(len(d)),
        "mean_m": round(float(d.mean()), 1),
        "median_m": round(float(np.median(d)), 1),
        "p90_m": round(float(np.percentile(d, 90)), 1),
        "p95_m": round(float(np.percentile(d, 95)), 1),
        "max_m": round(float(d.max()), 1),
        "over_3000_count": int((d > 3000).sum()),
        "over_6000_count": int((d > 6000).sum()),
        "review_threshold_m": review_m,
    }


def _finish_geography(cfg, gcfg, run_dir, run_id, geo, grid, polys, osm_coast,
                      game_edges, membership, audit, whq, changed_df,
                      conflict_rows, m1_ids, val_rows, _check, warnings,
                      timings, t_start, terrain_dir, hydro_dir, m1_dir):
    # ---- validation ------------------------------------------------------
    t0 = time.perf_counter()
    base = gcfg["regression_baseline"]
    hex_ids = geo["hex_id"].tolist()

    # GRID
    _check("grid_row_count_matches_mapgen001", len(geo) == len(m1_ids),
           f"{len(geo)} rows vs {len(m1_ids)} MAPGEN-001 hexes")
    _check("grid_hex_id_unique", geo["hex_id"].is_unique, "primary key")
    _check("grid_hex_id_set_matches_mapgen001",
           set(hex_ids) == m1_ids,
           f"symmetric diff = {len(set(hex_ids) ^ m1_ids)}")

    # WATER
    valid_wt = set(WATER_TYPE_ID)
    _check("water_type_enum_valid",
           geo["water_type"].isin(valid_wt).all(), "enum members only")
    _check("ocean_vs_is_land_consistent",
           (~((geo["water_type"] == "OCEAN") & geo["is_land"])).all(),
           "no OCEAN hex flagged land")
    lakes_ok = geo[geo["water_type"] == "LAKE"]["lake_fraction"] >= float(
        cfg.raw["hydro"]["lake"]["majority_threshold"])
    _check("lake_hexes_have_hydrolakes_evidence", lakes_ok.all(),
           f"{int((~lakes_ok).sum())} LAKE hexes without polygon majority")
    _check("river_hexes_have_water_hex_river_evidence",
           (geo[geo["water_type"] == "RIVER"]["is_water_hex_river"]).all()
           if (geo["water_type"] == "RIVER").any() else True,
           f"{int((geo['water_type'] == 'RIVER').sum())} RIVER hexes")
    water_mask = geo["water_type"] != "NONE"
    layers_none = ((geo.loc[water_mask, "surface_class"] == "NONE")
                   & (geo.loc[water_mask, "relief_class"] == "NONE")
                   & (geo.loc[water_mask, "vegetation_class"] == "NONE"))
    _check("water_hex_layers_normalised", layers_none.all(),
           f"{int((~layers_none).sum())} water hexes with live terrain layers")

    # LAND
    land_mask = ~water_mask
    land_ok = ((geo.loc[land_mask, "surface_class"] != "NONE")
               & (geo.loc[land_mask, "relief_class"] != "NONE")
               & (geo.loc[land_mask, "vegetation_class"] != "NONE")
               & geo.loc[land_mask, "elevation_mean_m"].notna())
    _check("all_land_hexes_have_terrain_layers", land_ok.all(),
           f"{int((~land_ok).sum())} land hexes missing layers/raw")
    newly = changed_df[changed_df["change_category"] == "NE_WATER_TO_OSM_LAND"]
    newly_ok = geo[geo["hex_id"].isin(newly["hex_id"])
                   & land_mask]["surface_class"] != "NONE"
    _check("newly_land_hexes_classified", newly_ok.all(),
           f"{len(newly)} newly-land hexes, "
           f"{int(changed_df['terrain_resampled'].sum())} resampled")

    # RIVER (canonical adoption regression)
    dup = int(game_edges.duplicated(["region", "edge_id"]).sum())
    _check("canonical_edge_duplicates_zero", dup == base["canonical_duplicates"],
           f"{dup} duplicates")
    _check("canonical_edge_count_baseline",
           len(game_edges) == base["canonical_game_edges"],
           f"{len(game_edges)} vs baseline {base['canonical_game_edges']}")
    kanto_edges = game_edges[game_edges["region"] == "kanto"]
    hexset = set(hex_ids)
    refs_ok = kanto_edges["hex_a_id"].isin(hexset) & (
        kanto_edges["hex_b_id"].isna() | kanto_edges["hex_b_id"].isin(hexset))
    _check("kanto_edge_hex_references_valid", refs_ok.all(),
           f"{int((~refs_ok).sum())} kanto edges reference unknown hexes")
    mem_ids = set(zip(membership["region"], membership["edge_id"]))
    game_ids = set(zip(game_edges["region"], game_edges["edge_id"]))
    _check("membership_covers_canonical", game_ids <= mem_ids,
           f"{len(game_ids - mem_ids)} canonical edges without membership")
    _check("confluences_preserved_baseline",
           len(audit) == base["total_confluences"]
           and int(audit["preserved"].sum()) == base["preserved_confluences"]
           and int((audit["exception_reason"].fillna("") != "").sum())
           == base["confluence_exceptions"],
           f"{int(audit['preserved'].sum())}/{len(audit)} preserved")
    am = whq[whq["river_name"] == "Amazon"]
    am_ok = (len(am) == 1
             and int(am["corridor_hex_count"].iloc[0]) == base["amazon_corridor_hexes"]
             and int(am["river_hex_connected_components"].iloc[0])
             == base["amazon_corridor_components"]
             and float(am["source_line_inside_corridor_fraction"].iloc[0])
             >= base["amazon_source_containment"]
             and int(am["source_confluence_count"].iloc[0]) == base["amazon_confluences"]
             and int(am["preserved_confluence_count"].iloc[0])
             == base["amazon_confluences"])
    _check("amazon_corridor_quality_baseline", am_ok,
           am.to_dict("records")[0] if len(am) else "missing")

    # Confluence offset QA (regression, not re-calibration).
    stats = confluence_offset_stats(audit, float(gcfg["confluence_offset_review_m"]))
    audit_out = audit.copy()
    audit_out["over_review_threshold"] = (
        audit_out["distance_m"] > float(gcfg["confluence_offset_review_m"]))
    audit_out.to_csv(run_dir / "confluence_offset_audit.csv", index=False)
    _check("confluence_offset_within_baseline",
           stats.get("max_m", 0) <= 6900.0 and stats.get("over_6000_count", 0) <= 1,
           stats)

    _check("water_authority_conflicts_reported", True,
           f"{len(conflict_rows)} conflicts recorded")
    timings["validation_s"] = time.perf_counter() - t0

    # ---- outputs ---------------------------------------------------------
    t0 = time.perf_counter()
    geo.to_parquet(run_dir / "geography_hexes.parquet", index=False)
    import gzip

    csv_bytes = geo.to_csv(index=False, float_format="%.6f").encode("utf-8")
    with gzip.open(run_dir / "geography_hexes.csv.gz", "wb") as f:
        f.write(csv_bytes)
    game_edges.to_csv(run_dir / "game_river_edges.csv", index=False)
    game_edges.to_parquet(run_dir / "game_river_edges.parquet", index=False)
    membership.to_csv(run_dir / "river_edge_membership.csv", index=False)
    pd.DataFrame(val_rows).to_csv(run_dir / "geography_validation.csv",
                                  index=False)

    # Summary for review.
    summary_rows = [
        {"metric": "hex_count", "value": len(geo)},
        {"metric": "land_hexes", "value": int(geo["is_land"].sum())},
        {"metric": "water_hexes", "value": int((~geo["is_land"]).sum())},
    ]
    for wt in ("OCEAN", "LAKE", "RIVER", "NONE"):
        summary_rows.append({"metric": f"water_type_{wt}",
                             "value": int((geo["water_type"] == wt).sum())})
    for face, cnt in geo["dominant_terrain_face"].value_counts().items():
        summary_rows.append({"metric": f"dominant_{face}", "value": int(cnt)})
    for cat, cnt in changed_df["change_category"].value_counts().items():
        summary_rows.append({"metric": f"changed_{cat}", "value": int(cnt)})
    for k, v in stats.items():
        summary_rows.append({"metric": f"confluence_offset_{k}", "value": v})
    pd.DataFrame(summary_rows).to_csv(run_dir / "geography_summary.csv",
                                      index=False)
    timings["output_s"] = time.perf_counter() - t0
    return _render_and_manifest(cfg, gcfg, run_dir, run_id, geo, grid, polys,
                                osm_coast, game_edges, changed_df, stats,
                                val_rows, warnings, timings, t_start,
                                terrain_dir, hydro_dir, m1_dir)


# --------------------------------------------------------------------------
# Rendering + manifest + review package
# --------------------------------------------------------------------------
INTEGRATED_WATER_COLORS = {"OCEAN": "#b3cde3", "LAKE": "#5b8fc9",
                           "RIVER": "#3d6fb4"}
CHANGE_COLORS = {"NE_WATER_TO_OSM_LAND": "#1f8f3a",
                 "NE_LAND_TO_OSM_WATER": "#c0392b",
                 "LAND_FRACTION_SHIFT": "#e2a72e",
                 "UNCHANGED": "#e8e4d0"}


def _edge_segments(grid, q, r, hex_ids, edges_df):
    graph = build_edge_graph(grid, q, r, hex_ids)
    by_id = {e["edge_id"]: i for i, e in enumerate(graph.edges)}
    segs, classes = [], []
    for _, row in edges_df.iterrows():
        i = by_id.get(row["edge_id"])
        if i is None:
            continue
        e = graph.edges[i]
        segs.append((graph.node_xy[e["n1"]], graph.node_xy[e["n2"]]))
        classes.append(row["dominant_river_class"])
    return segs, classes


def _render_integrated(out_png, title, polys, display_class, extent,
                       coastline=None, segs=None, seg_classes=None,
                       palette_extra=None, dpi=160, hex_lw=0.2):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection, PolyCollection

    from .hydro_render import RIVER_CLASS_COLORS, RIVER_CLASS_LW
    from .render import _draw_lines
    from .terrain_face import FACE_COLORS
    from .terrain_render import _finish, _verts

    palette = {**{k: v for k, v in FACE_COLORS.items() if k != "WATER"},
               **INTEGRATED_WATER_COLORS}
    if palette_extra:
        palette = {**palette, **palette_extra}
    fig, ax = plt.subplots(figsize=(12, 12), dpi=dpi)
    colors = [palette.get(c, "#dddddd") for c in display_class]
    ax.add_collection(PolyCollection(_verts(polys), facecolors=colors,
                                     edgecolors="#55555530",
                                     linewidths=hex_lw))
    if coastline is not None and not shapely.is_empty(coastline):
        _draw_lines(ax, coastline, "#1a355e", 0.5)
    if segs:
        ax.add_collection(LineCollection(
            segs,
            colors=[RIVER_CLASS_COLORS.get(c, "#333") for c in seg_classes],
            linewidths=[RIVER_CLASS_LW.get(c, 1.0) for c in seg_classes]))
    present = [k for k in palette if k in set(display_class)]
    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=palette[k],
                             edgecolor="gray") for k in present]
    ax.legend(handles, present, loc="lower right", fontsize=6, framealpha=0.85)
    _finish(ax, extent, title)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def _render_hydro_region_integrated(cfg, out_png, title, region_name, bbox,
                                    hydro_dir, game_edges):
    """Hydro-only regions (biwa, amazon_mouth): water authority + edges."""
    from .config import BBox

    tcfg = cfg.raw["terrain"]
    grid = HexGrid(flat_to_flat=float(tcfg["hex_size_m"]),
                   orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)
    bbox_3857 = bbox_to_mercator(bbox)
    margin = float(cfg.raw["hydro"]["margin_m"])
    q, r = grid.hexes_covering_bbox(bbox_3857[0] - margin, bbox_3857[1] - margin,
                                    bbox_3857[2] + margin, bbox_3857[3] + margin)
    ids = grid.hex_ids(q, r)
    polys = grid.polygons(q, r)
    hw = pd.read_csv(hydro_dir / "water_hexes.csv")
    hw = hw[hw["region"] == region_name]
    wt = dict(zip(hw["hex_id"], hw["water_type"]))
    display = [wt.get(h, "LAND") for h in ids]
    edges_df = game_edges[game_edges["region"] == region_name]
    segs, seg_classes = _edge_segments(grid, q, r, ids, edges_df)
    _render_integrated(out_png, title, polys, display, bbox_3857,
                       segs=segs, seg_classes=seg_classes,
                       palette_extra={"LAND": "#e8e4d0"}, hex_lw=0.35)


def _render_and_manifest(cfg, gcfg, run_dir, run_id, geo, grid, polys,
                         osm_coast, game_edges, changed_df, offset_stats,
                         val_rows, warnings, timings, t_start,
                         terrain_dir, hydro_dir, m1_dir):
    from .config import BBox

    t0 = time.perf_counter()
    bbox_3857 = bbox_to_mercator(cfg.bbox_wgs84)
    q = geo["q"].to_numpy()
    r = geo["r"].to_numpy()
    hex_ids = geo["hex_id"].tolist()
    display = np.where(geo["water_type"] != "NONE", geo["water_type"],
                       geo["dominant_terrain_face"]).astype(object)
    kanto_edges = game_edges[game_edges["region"] == "kanto"]
    segs, seg_classes = _edge_segments(grid, q, r, hex_ids, kanto_edges)

    _render_integrated(run_dir / "integrated_kanto.png",
                       f"geography authority — kanto ({run_id})",
                       polys, display, bbox_3857, coastline=osm_coast,
                       segs=segs, seg_classes=seg_classes)
    tz = cfg.raw["zooms"]["tokyo_bay"] if "zooms" in cfg.raw else None
    _render_integrated(run_dir / "integrated_tokyo_bay.png",
                       "tokyo bay — authoritative water + rivers",
                       polys, display,
                       bbox_to_mercator(BBox.from_lonlat_dict(tz)),
                       coastline=osm_coast, segs=segs,
                       seg_classes=seg_classes, hex_lw=0.5)
    for chk in cfg.raw["hydro"].get("lake_checks", []):
        if chk["region"] == "kanto":
            _render_integrated(
                run_dir / f"integrated_{chk['id']}.png",
                f"{chk['id']} — LAKE authority + rivers",
                polys, display,
                bbox_to_mercator(BBox.from_lonlat_dict(chk["zoom"])),
                coastline=osm_coast, segs=segs, seg_classes=seg_classes,
                hex_lw=0.5)
        else:
            _render_hydro_region_integrated(
                cfg, run_dir / f"integrated_{chk['id']}.png",
                f"{chk['id']} — water authority + rivers",
                chk["region"],
                BBox.from_lonlat_dict(
                    cfg.raw["terrain"]["validation_regions"][chk["region"]]),
                hydro_dir, game_edges)
    _render_hydro_region_integrated(
        cfg, run_dir / "integrated_amazon_mouth.png",
        "amazon mouth — WATER_HEX_RIVER corridor + edge rivers",
        "amazon_mouth", BBox.from_lonlat_dict(
            cfg.raw["hydro"]["regions"]["amazon_mouth"]),
        hydro_dir, game_edges)
    # Changed hexes highlight.
    change_map = dict(zip(changed_df["hex_id"], changed_df["change_category"]))
    change_display = [change_map.get(h, "UNCHANGED") for h in hex_ids]
    _render_integrated(run_dir / "coast_changed_hexes_kanto.png",
                       "kanto — NE -> OSM authority changes",
                       polys, change_display, bbox_3857,
                       coastline=osm_coast, palette_extra=CHANGE_COLORS)
    _render_integrated(run_dir / "water_authority_kanto.png",
                       "kanto — final water_type authority",
                       polys,
                       np.where(geo["water_type"] == "NONE", "LAND",
                                geo["water_type"]).astype(object),
                       bbox_3857, coastline=osm_coast,
                       palette_extra={"LAND": "#e8e4d0"})
    timings["render_s"] = time.perf_counter() - t0

    # ---- manifest --------------------------------------------------------
    total_s = time.perf_counter() - t_start
    peak_mb = _peak_memory_mb()
    source_manifest = json.loads(
        (cfg.data_dir / "source_manifest.json").read_text(encoding="utf-8"))
    manifest = {
        "stage": "MAPGEN-004 — Authoritative Geography Integration",
        "run_id": run_id,
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "hex_size_m": cfg.raw["terrain"]["hex_size_m"],
        "geography_schema_version": GEOGRAPHY_SCHEMA_VERSION,
        "terrain_schema_version": TERRAIN_SCHEMA_VERSION_V3,
        "hydro_schema_version": "1.0.0",
        # New namespace: version of the MAPGEN-004 integration algorithm
        # itself (deliberately NOT copied from the MAPGEN-001..003
        # generation pipelines' algorithm_version).
        "integration_algorithm_version": INTEGRATION_ALGORITHM_VERSION,
        "upstream_runs": {
            "mapgen001": {"run_id": gcfg["mapgen001_run"],
                          "path": str(m1_dir),
                          "hex_cells_sha256": sha256_of(m1_dir / "hex_cells.parquet")},
            "mapgen002a_terrain": {"run_id": gcfg["terrain_run"],
                                   "path": str(terrain_dir),
                                   "terrain_hexes_sha256": sha256_of(
                                       terrain_dir / "terrain_hexes.parquet")},
            "mapgen003a_hydro": {"run_id": gcfg["hydro_run"],
                                 "path": str(hydro_dir),
                                 "game_river_edges_sha256": sha256_of(
                                     hydro_dir / "game_river_edges.parquet")},
        },
        "config_snapshot_sha256": sha256_of(cfg.config_path),
        "source_datasets": {
            k: {kk: vv for kk, vv in v.items() if kk != "files"}
            | {"file_count": len(v.get("files", []))}
            for k, v in source_manifest.get("datasets", {}).items()},
        "confluence_offset_stats": offset_stats,
        "timings_s": {k: round(v, 2) for k, v in timings.items()},
        "total_duration_s": round(total_s, 2),
        "peak_memory_mb": round(peak_mb, 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    _build_review_package(run_dir, run_id, gcfg, geo, changed_df,
                          offset_stats, val_rows, warnings)
    n_fail = sum(1 for v in val_rows if not v["pass"])
    print(f"[geography] {len(geo)} hexes, validation "
          f"{len(val_rows) - n_fail}/{len(val_rows)} passed")
    print(f"[geography] done in {total_s:.1f}s, peak memory {peak_mb:.0f} MB")
    print(f"[geography] output: {run_dir}")
    return run_dir


def _build_review_package(run_dir, run_id, gcfg, geo, changed_df,
                          offset_stats, val_rows, warnings):
    import shutil

    review = run_dir / "chatgpt_review"
    review.mkdir(parents=True, exist_ok=True)
    for n in ("geography_summary.csv", "geography_validation.csv",
              "integration_changed_hexes.csv", "water_authority_conflicts.csv",
              "confluence_offset_audit.csv", "game_river_edges.csv",
              "river_edge_membership.csv", "run_manifest.json",
              "integrated_kanto.png", "integrated_tokyo_bay.png",
              "integrated_kasumigaura.png", "integrated_biwa.png",
              "integrated_amazon_mouth.png", "coast_changed_hexes_kanto.png",
              "water_authority_kanto.png"):
        src = run_dir / n
        if src.exists():
            shutil.copy2(src, review / n)

    n_fail = sum(1 for v in val_rows if not v["pass"])
    files = "\n".join(f"- {p.name}" for p in sorted(review.glob("*")))
    warn_text = "\n".join(f"- {w}" for w in warnings) if warnings else "None."
    wt_counts = geo["water_type"].value_counts().to_dict()
    text = f"""# README_REVIEW — MAPGEN-004 Authoritative Geography Integration

Stage: MAPGEN-004 — Authoritative Geography Integration
Run ID: {run_id}
Date: {_dt.date.today().isoformat()}
geography_schema_version: {GEOGRAPHY_SCHEMA_VERSION}
integration_algorithm_version: {INTEGRATION_ALGORITHM_VERSION} (new namespace
for the integration step; upstream pipelines keep their own versions)

What this dataset is:
geography_hexes.parquet is THE canonical per-hex geography table for the game
({len(geo)} kanto hexes = the exact MAPGEN-001 set; hex_id is the primary
key). game_river_edges is the canonical crossing table, adopted UNCHANGED
from MAPGEN-003A. From MAPGEN-004 onward, game logic must read only these
two; the per-stage outputs (MAPGEN-001/002A/003A) become build inputs.

Water authority (single source of truth):
- OCEAN: OSM land polygons majority (Natural Earth is demoted to the
  ne_*_audit columns; game logic must not read it).
- LAKE: HydroLAKES polygon majority (>= 0.5 of hex area).
- RIVER: MAPGEN-003A WATER_HEX_RIVER corridors.
- Priority on conflict: OCEAN > LAKE > RIVER > NONE (all conflicts listed in
  water_authority_conflicts.csv; a lake traversed by a river stays LAKE and
  the river connectivity lives in the edge/graph tables).
Final counts: {wt_counts}

Terrain semantics on water hexes:
surface/relief/vegetation layers are normalised to NONE and the display
faces to WATER; raw DEM/landcover/climate values are PRESERVED for future
coastal overlays and scenario editing. Land hexes are re-classified from the
MAPGEN-002A raw values with the CURRENT layer classifier (schema
{TERRAIN_SCHEMA_VERSION_V3}) under the authoritative water layer — the
WorldCover water estimate no longer decides anything.

Coast authority change audit:
integration_changed_hexes.csv lists every hex whose land/water state or
land_fraction (> {gcfg["land_fraction_change_threshold"]}) differs between
the Natural Earth basis (MAPGEN-002A) and the OSM authority, including
whether its terrain had to be incrementally resampled. Newly-land hexes
reuse their existing raw terrain (MAPGEN-002A sampled every hex, water
included); only hexes with invalid landcover coverage are resampled
individually — never a full re-run.

River regression (MAPGEN-003A must not degrade):
- canonical edges, duplicates, confluence 401/401, Amazon corridor quality
  are re-verified against the baseline (see geography_validation.csv).
- confluence_offset_audit.csv adds offset QA: {offset_stats}
  (>3000 m rows flagged for review; thresholds NOT re-calibrated here.)

Validation: {len(val_rows) - n_fail}/{len(val_rows)} checks passed.

Known limitations (unchanged, out of scope this stage):
- Provisional thresholds: terrain layer thresholds, river classes,
  WATER_HEX_RIVER width — all still awaiting world calibration.
- 6 km hex limits: sub-hex islands (Toshima) remain lost; strategic island
  preservation is a proposed future spec.
- Amazon estuary water surface still needs OSM water polygons (MAPGEN-005+).
- geography_hexes covers the kanto master region; validation patches remain
  per-stage outputs until world generation.

Warnings/errors:
{warn_text}

Files:
{files}
"""
    (review / "README_REVIEW.md").write_text(text, encoding="utf-8")
    return review
