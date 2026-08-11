"""Raster sampling machinery for terrain integration (MAPGEN-002).

All rasters are kept on their native EPSG:4326 grids; hex polygons (EPSG:3857)
are reprojected to 4326 and rasterized onto each grid, then per-hex statistics
are computed with vectorised groupbys. Hexes therefore evaluate rasters over
their full area, never at a single centre point.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import shapely
from rasterio import features as rio_features
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.windows import from_bounds as window_from_bounds

from .projection import to_wgs84

METRES_PER_DEGREE = 111320.0

# ESA WorldCover v200 class codes.
WORLDCOVER_CLASSES = {
    10: "tree",
    20: "shrub",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare_sparse",
    70: "snow_ice",
    80: "water",
    90: "herbaceous_wetland",
    95: "mangroves",
    100: "moss_lichen",
}

# Koeppen-Geiger V2 (Beck et al. 2023) class codes 1..30.
KOPPEN_CODES = [
    "Af", "Am", "Aw", "BWh", "BWk", "BSh", "BSk",
    "Csa", "Csb", "Csc", "Cwa", "Cwb", "Cwc",
    "Cfa", "Cfb", "Cfc",
    "Dsa", "Dsb", "Dsc", "Dsd", "Dwa", "Dwb", "Dwc", "Dwd",
    "Dfa", "Dfb", "Dfc", "Dfd",
    "ET", "EF",
]


def mosaic(paths: list[Path], bounds: tuple[float, float, float, float],
           res_deg: float, dtype, fill_value, resampling: Resampling):
    """Mosaic several EPSG:4326 rasters onto one target grid.

    bounds = (min_lon, min_lat, max_lon, max_lat). Returns (array, transform).
    Cells not covered by any source keep ``fill_value``.
    """
    min_lon, min_lat, max_lon, max_lat = bounds
    width = max(1, int(round((max_lon - min_lon) / res_deg)))
    height = max(1, int(round((max_lat - min_lat) / res_deg)))
    transform = from_origin(min_lon, max_lat, res_deg, res_deg)
    grid = np.full((height, width), fill_value, dtype=dtype)

    for path in paths:
        with rasterio.open(path) as src:
            sb = src.bounds
            ib = (max(min_lon, sb.left), max(min_lat, sb.bottom),
                  min(max_lon, sb.right), min(max_lat, sb.top))
            if ib[0] >= ib[2] or ib[1] >= ib[3]:
                continue
            # Destination slice (snap to target grid).
            c0 = int(round((ib[0] - min_lon) / res_deg))
            c1 = int(round((ib[2] - min_lon) / res_deg))
            r0 = int(round((max_lat - ib[3]) / res_deg))
            r1 = int(round((max_lat - ib[1]) / res_deg))
            c0, c1 = max(0, c0), min(width, c1)
            r0, r1 = max(0, r0), min(height, r1)
            if c1 <= c0 or r1 <= r0:
                continue
            dst_lon0 = min_lon + c0 * res_deg
            dst_lon1 = min_lon + c1 * res_deg
            dst_lat1 = max_lat - r0 * res_deg
            dst_lat0 = max_lat - r1 * res_deg
            win = window_from_bounds(dst_lon0, dst_lat0, dst_lon1, dst_lat1,
                                     src.transform)
            data = src.read(1, window=win, out_shape=(r1 - r0, c1 - c0),
                            resampling=resampling)
            if src.nodata is not None:
                valid = data != src.nodata
            else:
                valid = np.isfinite(data) if np.issubdtype(data.dtype, np.floating) else np.ones_like(data, bool)
            region = grid[r0:r1, c0:c1]
            region[valid] = data[valid].astype(dtype)
    return grid, transform


def slope_and_tri(dem: np.ndarray, transform) -> tuple[np.ndarray, np.ndarray]:
    """Per-pixel slope (degrees) and terrain ruggedness (m) from a 4326 DEM.

    Pixel spacing is converted to metres with a per-row cos(latitude)
    correction for the east-west axis.

    terrain_roughness (TRI) = mean absolute elevation difference between a
    pixel and its 8 neighbours, in metres. Flat plains < ~2 m, rolling hills
    ~5-15 m, mountains > ~20 m at 90 m resolution.
    """
    res_deg = transform.a
    top_lat = transform.f
    rows = np.arange(dem.shape[0])
    lat = top_lat - (rows + 0.5) * res_deg
    dy_m = res_deg * METRES_PER_DEGREE
    dx_m = res_deg * METRES_PER_DEGREE * np.clip(np.cos(np.deg2rad(lat)), 0.05, None)

    ddy, ddx = np.gradient(dem.astype(np.float32))
    dz_dy = ddy / dy_m
    dz_dx = ddx / dx_m[:, None]
    slope_deg = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))

    padded = np.pad(dem.astype(np.float32), 1, mode="edge")
    acc = np.zeros_like(dem, dtype=np.float32)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            shifted = padded[1 + dr:padded.shape[0] - 1 + dr,
                             1 + dc:padded.shape[1] - 1 + dc]
            acc += np.abs(dem - shifted)
    tri = acc / 8.0
    return slope_deg.astype(np.float32), tri.astype(np.float32)


def hex_polys_to_wgs84(polys3857: np.ndarray) -> np.ndarray:
    """Reproject an array of shapely polygons from EPSG:3857 to EPSG:4326."""
    def _tf(coords):
        lon, lat = to_wgs84(coords[:, 0], coords[:, 1])
        return np.column_stack([lon, lat])

    return shapely.transform(polys3857, _tf)


def rasterize_hex_index(polys4326: np.ndarray, shape: tuple[int, int],
                        transform) -> np.ndarray:
    """Rasterize hex polygons to an int32 grid of hex indices (-1 = no hex)."""
    shapes = ((geom, i) for i, geom in enumerate(polys4326))
    return rio_features.rasterize(
        shapes, out_shape=shape, transform=transform, fill=-1, dtype="int32"
    )


def aggregate_elevation(idx: np.ndarray, dem: np.ndarray, slope: np.ndarray,
                        tri: np.ndarray, valid: np.ndarray, n_hex: int) -> pd.DataFrame:
    """Per-hex elevation/slope/roughness statistics.

    ``valid`` marks pixels with real DEM coverage; invalid pixels are excluded
    from statistics and reported via dem_nodata_fraction.
    """
    flat_idx = idx.ravel()
    inside = flat_idx >= 0
    df_all = pd.DataFrame({"idx": flat_idx[inside], "ok": valid.ravel()[inside]})
    counts = df_all.groupby("idx")["ok"].agg(["size", "sum"])

    sel = inside & valid.ravel()
    df = pd.DataFrame({
        "idx": flat_idx[sel],
        "elev": dem.ravel()[sel],
        "slope": slope.ravel()[sel],
        "tri": tri.ravel()[sel],
    })
    g = df.groupby("idx")
    out = pd.DataFrame({
        "elevation_mean_m": g["elev"].mean(),
        "elevation_min_m": g["elev"].min(),
        "elevation_max_m": g["elev"].max(),
        "slope_mean_deg": g["slope"].mean(),
        "slope_p90_deg": g["slope"].quantile(0.9),
        "slope_max_deg": g["slope"].max(),
        "terrain_roughness": g["tri"].mean(),
    })
    out = out.reindex(range(n_hex))
    cov = counts.reindex(range(n_hex))
    with np.errstate(invalid="ignore", divide="ignore"):
        out["dem_nodata_fraction"] = 1.0 - (cov["sum"] / cov["size"]).fillna(0.0)
    out["elevation_range_m"] = out["elevation_max_m"] - out["elevation_min_m"]
    return out


def aggregate_landcover(idx: np.ndarray, lc: np.ndarray, n_hex: int) -> pd.DataFrame:
    """Per-hex WorldCover class fractions (fractions of valid landcover pixels)."""
    class_codes = sorted(WORLDCOVER_CLASSES)
    code_to_pos = np.zeros(256, dtype=np.int64)
    for pos, code in enumerate(class_codes):
        code_to_pos[code] = pos + 1  # 0 stays "nodata"

    flat_idx = idx.ravel()
    inside = flat_idx >= 0
    hex_idx = flat_idx[inside]
    cls_pos = code_to_pos[lc.ravel()[inside]]

    k = len(class_codes) + 1
    counts = np.bincount(hex_idx * k + cls_pos, minlength=n_hex * k).reshape(n_hex, k)
    total = counts.sum(axis=1)
    valid = total - counts[:, 0]
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(valid[:, None] > 0, counts[:, 1:] / valid[:, None], 0.0)
        nodata_frac = np.where(total > 0, counts[:, 0] / total, 1.0)
    out = pd.DataFrame(
        frac, columns=[f"lc_{WORLDCOVER_CLASSES[c]}_fraction" for c in class_codes]
    )
    out["landcover_nodata_fraction"] = nodata_frac
    return out


def aggregate_climate_mode(idx: np.ndarray, kg: np.ndarray, n_hex: int) -> np.ndarray:
    """Per-hex modal Koeppen-Geiger class (1..30; 0 where no valid data)."""
    flat_idx = idx.ravel()
    inside = flat_idx >= 0
    hex_idx = flat_idx[inside]
    cls = kg.ravel()[inside].astype(np.int64)
    k = 31
    counts = np.bincount(hex_idx * k + np.clip(cls, 0, 30),
                         minlength=n_hex * k).reshape(n_hex, k)
    counts[:, 0] = 0  # never pick nodata as the mode
    mode = counts.argmax(axis=1)
    mode[counts.max(axis=1) == 0] = 0
    return mode.astype(np.int64)


def sample_raster_at_points(path: Path, lons: np.ndarray, lats: np.ndarray):
    """Sample a raster's band 1 at lon/lat points (nearest pixel)."""
    with rasterio.open(path) as src:
        return np.array([v[0] for v in src.sample(np.column_stack([lons, lats]))])
