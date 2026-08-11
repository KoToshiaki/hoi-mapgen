"""Per-hex raw terrain sampling for one region (MAPGEN-002).

Combines Copernicus DEM GLO-90 (elevation/slope/roughness), ESA WorldCover
(land cover fractions) and Koeppen-Geiger V2 (climate) into one raw-terrain
DataFrame per hex. Purely data extraction — no classification here.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from rasterio.enums import Resampling

from .config import BBox
from .raster import (aggregate_climate_mode, aggregate_elevation,
                     aggregate_landcover, hex_polys_to_wgs84, mosaic,
                     rasterize_hex_index, slope_and_tri)
from .terrain_sources import ensure_dem_tiles, ensure_koppen, ensure_worldcover_tiles

DEM_RES_DEG = 0.000833333333333  # 3 arcsec (GLO-90 native at low latitude)
WC_RES_DEG = 0.0000833333333333  # 10 m WorldCover native
KG_RES_DEG = 0.00833333333333    # 1 km Koeppen-Geiger


def sample_region_terrain(hex_polys_3857: np.ndarray, data_dir: Path,
                          tcfg: dict) -> tuple[pd.DataFrame, dict]:
    """Raw terrain metrics for every hex polygon. Returns (df, timings)."""
    timings = {}
    t0 = time.perf_counter()

    polys4326 = hex_polys_to_wgs84(hex_polys_3857)
    b = shapely.total_bounds(polys4326)
    pad = 0.02
    bounds = (b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad)
    bbox = BBox(*bounds)
    n_hex = len(hex_polys_3857)

    # ---- elevation -------------------------------------------------------
    dem_paths, dem_missing = ensure_dem_tiles(data_dir, bbox)
    dem, dem_tf = mosaic(dem_paths, bounds, DEM_RES_DEG, np.float32, np.nan,
                         Resampling.bilinear)
    valid = np.isfinite(dem)
    # Copernicus tiles that don't exist upstream (HTTP 404) are open ocean;
    # those pixels become sea level. dem_nodata_fraction still reports how
    # much of each hex had no real DEM coverage — nothing fails silently.
    dem = np.where(valid, dem, 0.0).astype(np.float32)
    slope, tri = slope_and_tri(dem, dem_tf)
    idx_dem = rasterize_hex_index(polys4326, dem.shape, dem_tf)
    elev_df = aggregate_elevation(idx_dem, dem, slope, tri, valid, n_hex)
    # Hexes entirely inside missing (ocean) tiles: report sea level, not NaN.
    all_missing = elev_df["elevation_mean_m"].isna()
    for col in ("elevation_mean_m", "elevation_min_m", "elevation_max_m",
                "elevation_range_m", "slope_mean_deg", "slope_p90_deg",
                "slope_max_deg", "terrain_roughness"):
        elev_df.loc[all_missing, col] = 0.0
    timings["dem_s"] = time.perf_counter() - t0

    # ---- land cover ------------------------------------------------------
    t1 = time.perf_counter()
    wc_paths, wc_missing = ensure_worldcover_tiles(data_dir, bbox)
    wc_res = WC_RES_DEG * float(tcfg.get("landcover_decimation", 8))
    lc, lc_tf = mosaic(wc_paths, bounds, wc_res, np.uint8, 0, Resampling.nearest)
    idx_lc = rasterize_hex_index(polys4326, lc.shape, lc_tf)
    lc_df = aggregate_landcover(idx_lc, lc, n_hex)
    timings["landcover_s"] = time.perf_counter() - t1

    # ---- climate ---------------------------------------------------------
    t2 = time.perf_counter()
    kg_path = ensure_koppen(data_dir, tcfg["climate_period"],
                            tcfg["climate_resolution"])
    kg, kg_tf = mosaic([kg_path], bounds, KG_RES_DEG, np.uint8, 0,
                       Resampling.nearest)
    idx_kg = rasterize_hex_index(polys4326, kg.shape, kg_tf)
    kg_mode = aggregate_climate_mode(idx_kg, kg, n_hex)
    # Small hexes can miss every 1 km pixel centre; fall back to the nearest
    # valid climate pixel at the hex centroid.
    missing_kg = kg_mode == 0
    if missing_kg.any():
        centres = shapely.centroid(polys4326[missing_kg])
        lon = shapely.get_x(centres)
        lat = shapely.get_y(centres)
        cols = np.clip(((lon - kg_tf.c) / kg_tf.a).astype(int), 0, kg.shape[1] - 1)
        rows = np.clip(((kg_tf.f - lat) / -kg_tf.e).astype(int), 0, kg.shape[0] - 1)
        kg_mode[missing_kg] = kg[rows, cols]
    timings["climate_s"] = time.perf_counter() - t2

    df = pd.concat([elev_df.reset_index(drop=True), lc_df], axis=1)
    df["koppen_class"] = kg_mode
    df.attrs["dem_missing_tiles"] = dem_missing
    df.attrs["worldcover_missing_tiles"] = wc_missing
    return df, timings
