"""MAPGEN-002/002A terrain pipeline (terrain schema 3.0.0, layered).

Raw multi-axis terrain sampling (MAPGEN-002) is unchanged; classification is
layered (MAPGEN-002A): water / surface / relief / vegetation / development
layers plus a natural and a dominant display face. The old single-label
terrain_face scoring (terrain_face.py) is deprecated and no longer used by
the pipeline; it is kept only as reference (and for before/after comparison
against MAPGEN-002 runs).

terrain_hexes.* joins 1:1 with MAPGEN-001 hex_cells.* on hex_id.
"""
from __future__ import annotations

import datetime as _dt
import gzip
import json
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import ALGORITHM_VERSION
from .config import BBox, MapgenConfig
from .hex_grid import HexGrid
from .land import classify_hexes, load_land_mercator, source_coastline
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .projection import bbox_to_mercator, to_mercator, to_wgs84
from .sources import ensure_dataset
from .terrain import sample_region_terrain
from .terrain_face import climate_flags, military_metrics
from .terrain_layers import TERRAIN_SCHEMA_VERSION_V3, classify_layers
from .terrain_render import (LAYER_PALETTES, render_before_after,
                             render_layer_map, render_layer_panel,
                             render_value_map)

# Spec-facing landcover column names derived from WorldCover fractions.
FRACTION_RENAMES = {
    "lc_tree_fraction": "tree_fraction",
    "lc_grassland_fraction": "grassland_fraction",
    "lc_cropland_fraction": "cropland_fraction",
    "lc_shrub_fraction": "shrub_fraction",
    "lc_bare_sparse_fraction": "bare_ground_fraction",
    "lc_built_up_fraction": "urban_fraction",
    "lc_snow_ice_fraction": "permanent_snow_ice_fraction",
    "lc_water_fraction": "inland_water_fraction",
    "lc_moss_lichen_fraction": "moss_lichen_fraction",
    "lc_mangroves_fraction": "mangrove_fraction",
}

LAYER_COLUMNS = [
    "water_type", "water_type_id", "water_confidence", "inland_water_est",
    "surface_class", "surface_class_id", "surface_confidence",
    "relief_class", "relief_class_id", "relief_confidence",
    "vegetation_class", "vegetation_class_id", "vegetation_density",
    "vegetation_confidence",
    "development_class", "development_class_id", "development_confidence",
    "natural_terrain_face", "natural_terrain_face_id",
    "dominant_terrain_face", "dominant_terrain_face_id",
    "dominant_face_confidence",
]

CSV_COLUMNS = [
    "terrain_schema_version", "run_id", "region", "hex_size_m",
    "hex_id", "q", "r", "centre_x_m", "centre_y_m", "centre_lon", "centre_lat",
    "land_fraction", "land_class",
    "elevation_mean_m", "elevation_min_m", "elevation_max_m", "elevation_range_m",
    "slope_mean_deg", "slope_p90_deg", "slope_max_deg", "terrain_roughness",
    "dem_nodata_fraction",
    "tree_fraction", "grassland_fraction", "cropland_fraction", "shrub_fraction",
    "bare_ground_fraction", "wetland_fraction", "urban_fraction",
    "permanent_snow_ice_fraction", "inland_water_fraction",
    "moss_lichen_fraction", "mangrove_fraction", "landcover_nodata_fraction",
    "climate_zone", "biome_class",
    "is_tropical", "is_arid", "is_cold", "is_tundra_climate", "is_ice_cap_climate",
    *LAYER_COLUMNS,
    "foot_mobility", "wheeled_mobility", "tracked_mobility",
    "visibility", "concealment", "defensive_value",
    "logistics_passability", "construction_suitability", "deployment_capacity",
]

LAYERS_CSV_COLUMNS = [
    "run_id", "region", "hex_id", "lon", "lat",
    "water_type", "surface_class", "relief_class",
    "vegetation_class", "vegetation_density", "development_class",
    "natural_terrain_face", "dominant_terrain_face",
    "urban_fraction", "tree_fraction", "wetland_fraction",
    "inland_water_fraction",
    "slope_mean_deg", "terrain_roughness", "elevation_range_m",
    "water_confidence", "surface_confidence", "relief_confidence",
    "vegetation_confidence", "development_confidence",
    "dominant_face_confidence",
]


def process_region(name: str, bbox_wgs84: BBox, margin_m: float,
                   cfg: MapgenConfig, tcfg: dict, run_id: str) -> dict:
    """Generate hexes + land classification + raw terrain + layers for one
    region. Raw sampling is identical to MAPGEN-002."""
    size = float(tcfg["hex_size_m"])
    grid = HexGrid(flat_to_flat=size, orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)
    bbox_3857 = bbox_to_mercator(bbox_wgs84)
    min_x, min_y, max_x, max_y = bbox_3857
    extent = (min_x - margin_m, min_y - margin_m, max_x + margin_m, max_y + margin_m)

    t0 = time.perf_counter()
    q, r = grid.hexes_covering_bbox(*extent)
    polys = grid.polygons(q, r)
    cx, cy = grid.axial_to_xy(q, r)
    lon, lat = to_wgs84(cx, cy)

    land_shp = ensure_dataset("ne_10m_land", cfg.data_dir)
    clip_margin = margin_m + 10000.0
    land = load_land_mercator(land_shp, bbox_3857, clip_margin)
    coast = source_coastline(land, (min_x - clip_margin, min_y - clip_margin,
                                    max_x + clip_margin, max_y + clip_margin))
    centres = np.stack([cx, cy], axis=1)
    land_cls = classify_hexes(polys, centres, land, coast, grid.area,
                              cfg.land_threshold)
    grid_time = time.perf_counter() - t0

    raw_df, timings = sample_region_terrain(polys, cfg.data_dir, tcfg)
    timings["grid_land_s"] = grid_time

    t1 = time.perf_counter()
    base = pd.DataFrame({
        "terrain_schema_version": TERRAIN_SCHEMA_VERSION_V3,
        "run_id": run_id,
        "region": name,
        "hex_size_m": size,
        "hex_id": grid.hex_ids(q, r),
        "q": q,
        "r": r,
        "centre_x_m": cx,
        "centre_y_m": cy,
        "centre_lon": lon,
        "centre_lat": lat,
        "land_fraction": land_cls["land_fraction"],
        "land_class": land_cls["land_class"],
    })
    df = pd.concat([base, raw_df.reset_index(drop=True)], axis=1)
    df["wetland_fraction"] = (df["lc_herbaceous_wetland_fraction"]
                              + df["lc_mangroves_fraction"])
    df = df.rename(columns=FRACTION_RENAMES)
    df = pd.concat([df, climate_flags(df["koppen_class"].to_numpy())], axis=1)

    layers = classify_layers(df, tcfg)
    df = pd.concat([df, layers], axis=1)
    if tcfg.get("military", {}).get("enabled", True):
        df = pd.concat([df, military_metrics(df, None)], axis=1)
    timings["classification_s"] = time.perf_counter() - t1

    return {
        "name": name, "df": df, "polys": polys, "grid": grid, "coast": coast,
        "bbox_3857": bbox_3857, "timings": timings,
        "dem_missing_tiles": raw_df.attrs.get("dem_missing_tiles", []),
        "worldcover_missing_tiles": raw_df.attrs.get("worldcover_missing_tiles", []),
    }


# --------------------------------------------------------------------------
# Aggregation outputs
# --------------------------------------------------------------------------
def layer_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-layer value counts (long format: layer, value, hex_count, pct)."""
    rows = []
    total = len(df)
    for layer, col in (("WATER", "water_type"), ("SURFACE", "surface_class"),
                       ("RELIEF", "relief_class"),
                       ("VEGETATION", "vegetation_class"),
                       ("DEVELOPMENT", "development_class"),
                       ("NATURAL_FACE", "natural_terrain_face"),
                       ("DOMINANT_FACE", "dominant_terrain_face")):
        counts = df[col].value_counts()
        for value, count in counts.items():
            rows.append({
                "layer": layer, "value": value, "hex_count": int(count),
                "percentage": 100.0 * count / total,
            })
    return pd.DataFrame(rows)


def layer_combinations(df: pd.DataFrame) -> pd.DataFrame:
    """Observed surface|relief|vegetation|development combinations on land
    hexes (all regions) — the input for Tripo asset-pool combination design."""
    land = df[df["water_type"] == "NONE"]
    combos = (land.groupby(["surface_class", "relief_class",
                            "vegetation_class", "development_class"])
              .size().reset_index(name="hex_count")
              .sort_values("hex_count", ascending=False))
    combos["percentage"] = 100.0 * combos["hex_count"] / len(land)
    return combos


def transition_cases(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Low-confidence dominant faces. HILLS+FOREST style coexistence is NOT
    listed here any more — layers make it a normal state; only genuinely
    ambiguous dominant faces (low deciding-layer margin) appear."""
    land = df[df["water_type"] == "NONE"]
    weak = land[land["dominant_face_confidence"] < threshold]
    weak = weak.sort_values("dominant_face_confidence")
    return weak[["hex_id", "region", "centre_lon", "centre_lat",
                 "dominant_terrain_face", "dominant_face_confidence",
                 "natural_terrain_face", "surface_class", "relief_class",
                 "vegetation_class", "development_class",
                 "surface_confidence", "relief_confidence",
                 "vegetation_confidence", "development_confidence"]].rename(
        columns={"centre_lon": "lon", "centre_lat": "lat"})


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
_LAYER_KEY_TO_COL = {
    "water_type": "water_type",
    "surface": "surface_class",
    "relief": "relief_class",
    "vegetation": "vegetation_class",
    "development": "development_class",
}


def _raw_factors(row: pd.Series) -> str:
    return (f"tree={row['tree_fraction']:.2f} "
            f"open={row['grassland_fraction'] + row['cropland_fraction']:.2f} "
            f"urban={row['urban_fraction']:.2f} wet={row['wetland_fraction']:.2f} "
            f"bare={row['bare_ground_fraction']:.2f} "
            f"inwater={row['inland_water_fraction']:.2f} "
            f"slope={row['slope_mean_deg']:.1f}deg "
            f"rough={row['terrain_roughness']:.1f}m climate={row['climate_zone']}")


def run_validation(points: list[dict], checks: list[dict],
                   regions: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for pt in points:
        region = regions.get(pt["region"])
        row = {
            "validation_id": pt["id"],
            "kind": "point",
            "place_name": pt["place"],
            "lon": pt["lon"], "lat": pt["lat"],
            "expected_dominant": pt["expected"],
            "acceptable_dominant": "|".join(pt["acceptable"]),
            "layer_expectations": "; ".join(
                f"{k} in [{','.join(v)}]" for k, v in (pt.get("layers") or {}).items()
            ) or "",
        }
        if region is None:
            row.update({"pass": False, "notes": "region not generated"})
            rows.append(row)
            continue
        x, y = to_mercator(pt["lon"], pt["lat"])
        q, r = region["grid"].xy_to_axial(float(x), float(y))
        hex_id = region["grid"].hex_id(q, r)
        match = region["df"][region["df"]["hex_id"] == hex_id]
        if match.empty:
            row.update({"actual_hex_id": hex_id, "pass": False,
                        "notes": "point outside generated patch"})
            rows.append(row)
            continue
        m = match.iloc[0]
        ok = m["dominant_terrain_face"] in pt["acceptable"]
        fails = []
        for key, allowed in (pt.get("layers") or {}).items():
            col = _LAYER_KEY_TO_COL[key]
            if m[col] not in allowed:
                ok = False
                fails.append(f"{key}={m[col]} not in {allowed}")
        nat_ok = True
        if pt.get("natural_acceptable"):
            nat_ok = m["natural_terrain_face"] in pt["natural_acceptable"]
            if not nat_ok:
                fails.append(
                    f"natural={m['natural_terrain_face']} not in "
                    f"{pt['natural_acceptable']}")
        row.update({
            "actual_hex_id": hex_id,
            "actual_dominant": m["dominant_terrain_face"],
            "actual_natural": m["natural_terrain_face"],
            "water_type": m["water_type"],
            "surface_class": m["surface_class"],
            "relief_class": m["relief_class"],
            "vegetation_class": m["vegetation_class"],
            "development_class": m["development_class"],
            "pass": bool(ok and nat_ok),
            "notes": ("; ".join(fails) + " | " if fails else "") + _raw_factors(m),
        })
        rows.append(row)

    for chk in checks or []:
        region = regions.get(chk["region"])
        count = (int((region["df"][chk["layer"]] == chk["value"]).sum())
                 if region is not None else -1)
        rows.append({
            "validation_id": chk["id"],
            "kind": "region_check",
            "place_name": chk["region"],
            "layer_expectations": f"count({chk['layer']}={chk['value']}) "
                                  f"<= {chk['max_count']}",
            "actual_count": count,
            "pass": region is not None and count <= chk["max_count"],
            "notes": f"{chk['layer']}={chk['value']} count={count}",
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Before/after comparison against a MAPGEN-002 baseline run
# --------------------------------------------------------------------------
def find_baseline_run(output_dir: Path, current_run_id: str) -> Path | None:
    """Newest earlier terrain run whose parquet still has the v2 single-label
    terrain_face column."""
    import pyarrow.parquet as pq

    candidates = []
    for p in output_dir.glob("*/terrain_hexes.parquet"):
        if p.parent.name == current_run_id:
            continue
        try:
            schema_cols = pq.read_schema(p).names
        except Exception:
            continue
        if "terrain_face" in schema_cols:
            candidates.append(p)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def run_terrain(cfg: MapgenConfig, run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    tcfg = cfg.raw["terrain"]
    if run_id is None:
        run_id = f"{cfg.region_name}_terrain_{_dt.datetime.now():%Y%m%d_%H%M%S}"
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    print(f"[terrain] run_id={run_id} (schema {TERRAIN_SCHEMA_VERSION_V3})")
    regions: dict[str, dict] = {}
    print("[terrain] === region kanto ===")
    regions["kanto"] = process_region("kanto", cfg.bbox_wgs84, cfg.margin_m,
                                      cfg, tcfg, run_id)
    for name, d in tcfg.get("validation_regions", {}).items():
        print(f"[terrain] === region {name} ===")
        regions[name] = process_region(name, BBox.from_lonlat_dict(d),
                                       6000.0, cfg, tcfg, run_id)

    for reg in regions.values():
        for key in ("dem_missing_tiles", "worldcover_missing_tiles"):
            if reg[key]:
                warnings.append(
                    f"{reg['name']}: {key} (treated as ocean): {reg[key]}")
        nod = reg["df"]
        bad_lc = nod[(nod["land_class"] == "land")
                     & (nod["landcover_nodata_fraction"] > 0.5)]
        if len(bad_lc):
            warnings.append(
                f"{reg['name']}: {len(bad_lc)} land hexes with >50% landcover nodata")

    kanto = regions["kanto"]
    kdf = kanto["df"]
    all_df = pd.concat([regions[n]["df"] for n in regions], ignore_index=True)

    # ---- tabular outputs -------------------------------------------------
    csv_df = all_df[CSV_COLUMNS]
    csv_df.to_csv(run_dir / "terrain_hexes.csv", index=False, float_format="%.6f")
    csv_df.to_parquet(run_dir / "terrain_hexes.parquet", index=False)

    layers_df = all_df.rename(columns={"centre_lon": "lon", "centre_lat": "lat"})
    layers_df[LAYERS_CSV_COLUMNS].to_csv(
        run_dir / "terrain_layers.csv", index=False, float_format="%.6f")
    layers_df[LAYERS_CSV_COLUMNS].to_parquet(
        run_dir / "terrain_layers.parquet", index=False)

    layer_summary(kdf).to_csv(run_dir / "terrain_layer_summary.csv",
                              index=False, float_format="%.4f")
    layer_combinations(all_df).to_csv(run_dir / "terrain_combinations.csv",
                                      index=False, float_format="%.4f")
    conf_threshold = float(tcfg["transition_confidence_threshold"])
    transition_cases(all_df, conf_threshold).to_csv(
        run_dir / "terrain_transition_cases.csv", index=False,
        float_format="%.4f")

    validation = run_validation(tcfg.get("validation_points", []),
                                tcfg.get("validation_checks", []), regions)
    validation.to_csv(run_dir / "terrain_validation.csv", index=False,
                      float_format="%.4f")

    # ---- renders ---------------------------------------------------------
    t_render = time.perf_counter()
    ext = kanto["bbox_3857"]
    polys = kanto["polys"]
    for col, fname in (("surface_class", "surface_class_kanto.png"),
                       ("relief_class", "relief_class_kanto.png"),
                       ("vegetation_class", "vegetation_class_kanto.png"),
                       ("development_class", "development_class_kanto.png"),
                       ("water_type", "water_type_kanto.png"),
                       ("dominant_terrain_face", "dominant_face_kanto.png"),
                       ("natural_terrain_face", "natural_face_kanto.png")):
        render_layer_map(run_dir / fname, f"{col} — kanto ({run_id})",
                         kdf[col], polys, LAYER_PALETTES[col], ext,
                         coastline=kanto["coast"])
    render_value_map(run_dir / "vegetation_density_kanto.png",
                     "vegetation_density — kanto", kdf["vegetation_density"],
                     polys, ext, "Greens", "vegetation density", vmin=0, vmax=1)
    for zoom_name, zd in tcfg.get("zooms", {}).items():
        zext = bbox_to_mercator(BBox.from_lonlat_dict(zd))
        render_layer_panel(run_dir / f"terrain_layers_{zoom_name}.png",
                           f"terrain layers — {zoom_name}", kdf, polys, zext,
                           coastline=kanto["coast"])
    for name, reg in regions.items():
        if name == "kanto":
            continue
        render_layer_panel(run_dir / f"terrain_layers_{name}.png",
                           f"terrain layers — {name}", reg["df"], reg["polys"],
                           reg["bbox_3857"], coastline=reg["coast"])

    # Before/after vs the newest MAPGEN-002 (v2 schema) run.
    baseline = find_baseline_run(cfg.output_dir, run_id)
    if baseline is None:
        warnings.append("no MAPGEN-002 baseline run found; before/after "
                        "images skipped")
    else:
        old = pd.read_parquet(baseline,
                              columns=["hex_id", "region", "terrain_face"])
        for reg_name, fname, extent in (
                ("kanto", "before_after_kanto.png", ext),
                ("kanto", "before_after_tokyo.png",
                 bbox_to_mercator(BBox.from_lonlat_dict(tcfg["zooms"]["tokyo"]))),
                ("netherlands", "before_after_netherlands.png",
                 regions["netherlands"]["bbox_3857"])):
            reg = regions[reg_name]
            merged = reg["df"].merge(
                old[old["region"] == reg_name][["hex_id", "terrain_face"]],
                on="hex_id", how="left")
            before = merged["terrain_face"].fillna("WATER")
            render_before_after(
                run_dir / fname,
                f"{reg_name}: MAPGEN-002 vs MAPGEN-002A "
                f"(baseline {baseline.parent.name})",
                before, merged["dominant_terrain_face"], reg["polys"], extent,
                coastline=reg["coast"])
    render_time = time.perf_counter() - t_render

    # ---- manifest --------------------------------------------------------
    total_s = time.perf_counter() - t_start
    peak_mb = _peak_memory_mb()
    source_manifest = json.loads(
        (cfg.data_dir / "source_manifest.json").read_text(encoding="utf-8"))
    manifest = {
        "stage": "MAPGEN-002A layered terrain classification",
        "terrain_schema_version": TERRAIN_SCHEMA_VERSION_V3,
        "algorithm_version": ALGORITHM_VERSION,
        "run_id": run_id,
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "hex_size_m": tcfg["hex_size_m"],
        "projection": {"source_crs": "EPSG:4326", "map_crs": "EPSG:3857"},
        "hex_orientation": cfg.hex_orientation,
        "grid_origin": [cfg.grid_origin_x, cfg.grid_origin_y],
        "baseline_run": baseline.parent.name if baseline else None,
        "terrain_config": tcfg,
        "source_datasets": {
            k: {kk: vv for kk, vv in v.items() if kk != "files"}
            | {"file_count": len(v.get("files", []))}
            for k, v in source_manifest.get("datasets", {}).items()
        },
        "per_region_timings": {n: regions[n]["timings"] for n in regions},
        "render_time_s": round(render_time, 2),
        "total_duration_s": round(total_s, 2),
        "peak_memory_mb": round(peak_mb, 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    build_terrain_review_package(cfg, run_dir, run_id, tcfg, validation, warnings)
    print(f"[terrain] done in {total_s:.1f}s, peak memory {peak_mb:.0f} MB")
    print(f"[terrain] output: {run_dir}")
    return run_dir


# --------------------------------------------------------------------------
def build_terrain_review_package(cfg: MapgenConfig, run_dir: Path, run_id: str,
                                 tcfg: dict, validation: pd.DataFrame,
                                 warnings: list[str]) -> Path:
    review = run_dir / "chatgpt_review"
    review.mkdir(parents=True, exist_ok=True)

    names = ["run_manifest.json", "terrain_layers.parquet",
             "terrain_layer_summary.csv", "terrain_combinations.csv",
             "terrain_validation.csv", "terrain_transition_cases.csv",
             "surface_class_kanto.png", "relief_class_kanto.png",
             "vegetation_class_kanto.png", "development_class_kanto.png",
             "water_type_kanto.png", "dominant_face_kanto.png",
             "natural_face_kanto.png",
             "before_after_kanto.png", "before_after_tokyo.png",
             "before_after_netherlands.png"]
    names += [f"terrain_layers_{z}.png" for z in tcfg.get("zooms", {})]
    names += [f"terrain_layers_{r}.png" for r in tcfg.get("validation_regions", {})]
    for name in names:
        src = run_dir / name
        if src.exists():
            shutil.copy2(src, review / name)
    with open(run_dir / "terrain_layers.csv", "rb") as fin, \
            gzip.open(review / "terrain_layers.csv.gz", "wb") as fout:
        shutil.copyfileobj(fin, fout)

    _write_review_readme(cfg, review, run_id, tcfg, validation, warnings)
    return review


def _write_review_readme(cfg: MapgenConfig, review: Path, run_id: str,
                         tcfg: dict, validation: pd.DataFrame,
                         warnings: list[str]) -> None:
    lc = tcfg["layers"]
    files = "\n".join(f"- {p.name}" for p in sorted(review.glob("*")) if p.is_file())
    warn_text = "\n".join(f"- {w}" for w in warnings) if warnings else "None."
    passed = int(validation["pass"].sum())
    val_table = validation[["validation_id", "kind", "pass", "notes"]].to_string(index=False)
    text = f"""# README_REVIEW — MAPGEN-002A layered terrain classification

Project: mapgen — world-scale strategy game map pipeline
Stage: MAPGEN-002A (layered terrain classification refactor)
Schema version: {TERRAIN_SCHEMA_VERSION_V3}
Run ID: {run_id}
Date: {_dt.date.today().isoformat()}

Changed classification philosophy:
MAPGEN-002 collapsed each hex to ONE exclusive terrain_face via weighted
scores; the review showed that this destroys information (HILLS vs FOREST is
not one axis; URBAN erased natural terrain; non-arid bare ground became
DESERT; lake hexes had no valid class). MAPGEN-002A keeps ALL MAPGEN-002 raw
data unchanged and classifies five INDEPENDENT layers per hex, plus two
summary faces. "HILLS with FOREST" or "DESERT with MOUNTAIN" are normal
states. The dominant face is a UI summary only — simulation will use raw
values and layers, never the dominant face alone.

Layer meanings:
- water layer: NONE / OCEAN / LAKE (RIVER comes in MAPGEN-003)
- surface layer: climatic/ground nature, independent of relief (PLAINS / TUNDRA / DESERT / WETLAND / PERMANENT_SNOW_ICE)
- relief layer: landform skeleton (FLAT / ROLLING / HILLS / MOUNTAIN) — chooses geometry asset pools
- vegetation layer: OPEN / FOREST / RAINFOREST + continuous vegetation_density — chooses vegetation asset pools and tree counts
- development layer: NONE / SETTLED / URBAN / DENSE_URBAN — 2021 baseline, scenario-overridable, never erases natural terrain
- natural_terrain_face: display face ignoring development (era/scenario fallback)
- dominant_terrain_face: display face including development

Classification rules (ALL thresholds provisional, from config terrain.layers):

water_type:
  OCEAN  <- MAPGEN-001 land/water classification says water
  LAKE   <- land hex AND clip(worldcover_water - (1 - land_fraction), 0, 1) >= {lc["water"]["lake_majority_threshold"]}
            (the (1 - land_fraction) term removes expected SEA pixels, so a
             coastal hex can never become a lake from sea water)
  NONE   <- otherwise. Small water bodies stay as inland_water_fraction raw
            value for future visual overlays.

surface_class (priority order):
  PERMANENT_SNOW_ICE <- snow_fraction >= {lc["surface"]["snow_ice_threshold"]} OR (Koeppen EF AND snow_fraction >= {lc["surface"]["icecap_snow_threshold"]})
  WETLAND            <- wetland_fraction >= {lc["surface"]["wetland_threshold"]}
  DESERT             <- is_arid AND bare_ground_fraction >= {lc["surface"]["desert_bare_threshold"]}   (is_arid is a HARD requirement; non-arid bare ground can never be DESERT)
  TUNDRA             <- Koeppen ET
  PLAINS             <- otherwise (grassland+cropland absorbed here; raw fractions preserved)

relief_class (slope_mean_deg primary; never absolute elevation):
  FLAT     < {lc["relief"]["rolling_slope_deg"]} deg
  ROLLING  < {lc["relief"]["hills_slope_deg"]} deg
  HILLS    < {lc["relief"]["mountain_slope_deg"]} deg
  MOUNTAIN >= {lc["relief"]["mountain_slope_deg"]} deg, OR slope >= {lc["relief"]["mountain_alt_slope_deg"]} deg AND elevation_range >= {lc["relief"]["mountain_alt_relief_m"]} m

vegetation_class:
  FOREST/RAINFOREST <- tree_fraction >= {lc["vegetation"]["forest_tree_threshold"]} (RAINFOREST when is_tropical)
  OPEN              <- otherwise
  vegetation_density = tree_fraction (continuous 0..1)
  (No SPARSE class: density already carries the continuum; a fourth class
   would add boundaries without information. Conifer/broadleaf not split —
   WorldCover v200 does not distinguish them.)

development_class (urban_fraction bands):
  NONE < {lc["development"]["settled_threshold"]} <= SETTLED < {lc["development"]["urban_threshold"]} <= URBAN < {lc["development"]["dense_urban_threshold"]} <= DENSE_URBAN
  The old urban_score = 2.2 * urban_fraction competition against natural
  terrain is REMOVED; development never competes with or erases natural
  terrain.

dominant face (priority chain, natural face = same chain without the URBAN step):
  WATER <- water_type != NONE
  PERMANENT_SNOW_ICE <- surface says so
  URBAN <- development_class >= {lc["dominant"]["urban_face_min_class"]}
  MOUNTAIN <- relief MOUNTAIN
  HILLS <- relief HILLS AND slope_mean >= {lc["dominant"]["hills_dominant_slope_deg"]} deg
  DESERT/TUNDRA/WETLAND <- surface says so
  RAINFOREST/FOREST <- vegetation says so
  HILLS <- relief HILLS (weaker)
  PLAINS <- otherwise

Confidence definitions:
  Each layer has its own confidence (0 = on a threshold boundary, 1 = deep
  inside the class): banded metrics use distance-to-nearest-band-edge over
  half band width; threshold rules use |metric - threshold| / threshold.
  dominant_face_confidence = confidence of the layer that decided the face.

Compatibility with MAPGEN-002:
  Raw sampling (DEM/slope/roughness/WorldCover/Koeppen aggregation) is
  byte-identical — not re-evaluated. The v2 single-label terrain_face and its
  scores are REPLACED (schema major bump to 3.0.0), not kept as alias
  columns; the legacy scorer remains in the codebase (terrain_face.py) for
  reference and old runs keep their files. before_after_*.png compare v2 vs
  v3 from the baseline run.

Validation ({passed}/{len(validation)} passed):
{val_table}

Warnings/errors:
{warn_text}

Known limitations:
- All thresholds provisional; this review is the tuning input. Not final.
- WorldCover water on lakeshore hexes still mixes lake and land; LAKE needs
  a majority, so narrow lake arms stay land hexes with inland_water_fraction.
- Surface for water hexes is reported as NONE (sea floor values meaningless).
- Military metrics unchanged placeholder formulas (deliberately untouched).
- Köppen is 1 km modal; microclimates below hex scale invisible.

Generated files:
{files}

Note from the generator (Claude): classification is again NOT declared
final. The goal of this stage is the schema migration from one exclusive
label to layers; thresholds await this review.
"""
    (review / "README_REVIEW.md").write_text(text, encoding="utf-8")
