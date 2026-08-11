"""MAPGEN-010 — Europe canonical 6 km hex coverage (chunked, deterministic).

Uses the EXISTING global hex grid (same q/r axial system, ids, orientation,
world anchor and area rule) — never a second grid. Land/water comes from
the same OSM coast authority as MAPGEN-003..007R. Coverage rows are
GEOMETRY_COVERAGE_ONLY: terrain/river/lake layers are deliberately absent
and explicitly marked, never faked.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from .config import BBox
from .hex_grid import HexGrid
from .projection import bbox_to_mercator, to_wgs84

EUROPE_COVERAGE_SCHEMA_VERSION = "1.0.0"
COVERAGE_STATUS_GEOMETRY_ONLY = "GEOMETRY_COVERAGE_ONLY"
WATER_AUTHORITY_STATUS = "OSM_COAST_ONLY"  # no HydroLAKES/rivers yet
CHUNK_MARGIN_M = 12000.0  # 2 hexes: safe classification margin


def chunk_id(ix: int, iy: int) -> str:
    return f"euc_{ix:02d}_{iy:02d}"


def europe_chunk_grid(ecfg: dict) -> list[dict]:
    """Deterministic chunk tiling of the configured Europe extent.

    A hex belongs to EXACTLY one chunk: the one whose EPSG:3857 box
    contains its centre (half-open [x0,x1) x [y0,y1); the outermost
    column/row close the global boundary).
    """
    min_lon, max_lon = float(ecfg["min_lon"]), float(ecfg["max_lon"])
    min_lat, max_lat = float(ecfg["min_lat"]), float(ecfg["max_lat"])
    dlon, dlat = float(ecfg["chunk_deg_lon"]), float(ecfg["chunk_deg_lat"])
    nx = int(round((max_lon - min_lon) / dlon))
    ny = int(round((max_lat - min_lat) / dlat))
    chunks = []
    for iy in range(ny):
        for ix in range(nx):
            lo_lon = min_lon + ix * dlon
            lo_lat = min_lat + iy * dlat
            bbox = BBox(lo_lon, lo_lat, min(lo_lon + dlon, max_lon),
                        min(lo_lat + dlat, max_lat))
            b = bbox_to_mercator(bbox)
            chunks.append({
                "chunk_id": chunk_id(ix, iy), "ix": ix, "iy": iy,
                "min_lon": bbox.min_x, "min_lat": bbox.min_y,
                "max_lon": bbox.max_x, "max_lat": bbox.max_y,
                "bbox_3857": b,
                "last_col": ix == nx - 1, "last_row": iy == ny - 1,
            })
    return chunks


def build_land_cache(osm_shp: Path, ecfg: dict, cache_path: Path) -> Path:
    """One linear pass over the OSM land shapefile for the Europe extent,
    cached as GeoParquet (same source authority, no reshaping)."""
    if cache_path.exists():
        return cache_path
    b = bbox_to_mercator(BBox(float(ecfg["min_lon"]), float(ecfg["min_lat"]),
                              float(ecfg["max_lon"]),
                              float(ecfg["max_lat"])))
    gdf = gpd.read_file(osm_shp, bbox=(b[0] - CHUNK_MARGIN_M,
                                       b[1] - CHUNK_MARGIN_M,
                                       b[2] + CHUNK_MARGIN_M,
                                       b[3] + CHUNK_MARGIN_M))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    gdf[["geometry"]].to_parquet(cache_path)
    return cache_path


def generate_chunk(grid: HexGrid, chunk: dict, parts: np.ndarray,
                   tree: shapely.STRtree,
                   land_threshold: float) -> gpd.GeoDataFrame:
    """Generate one chunk's hexes on the canonical global grid.

    Membership: hex centre in the chunk's half-open 3857 box (outermost
    column/row inclusive), so adjacent chunks can NEVER duplicate or drop
    a hex. Land fraction: exact hex∩land area against the individual OSM
    split polygons (a non-overlapping partition of land, so the per-part
    sum equals the union intersection).
    """
    x0, y0, x1, y1 = chunk["bbox_3857"]
    q, r = grid.hexes_covering_bbox(x0 - CHUNK_MARGIN_M, y0 - CHUNK_MARGIN_M,
                                    x1 + CHUNK_MARGIN_M, y1 + CHUNK_MARGIN_M)
    cx, cy = grid.axial_to_xy(q, r)
    cx = np.atleast_1d(np.asarray(cx, dtype=float))
    cy = np.atleast_1d(np.asarray(cy, dtype=float))
    in_x = (cx >= x0) & ((cx < x1) | chunk["last_col"] & (cx <= x1))
    in_y = (cy >= y0) & ((cy < y1) | chunk["last_row"] & (cy <= y1))
    keep = in_x & in_y
    q, r, cx, cy = q[keep], r[keep], cx[keep], cy[keep]
    order = np.lexsort((q, r))
    q, r, cx, cy = q[order], r[order], cx[order], cy[order]
    polys = grid.polygons(q, r)
    ids = grid.hex_ids(q, r)
    n = len(polys)
    land_area = np.zeros(n)
    if len(parts):
        hi, pi = tree.query(polys, predicate="intersects")
        if len(hi):
            inter = shapely.intersection(polys[hi], parts[pi])
            np.add.at(land_area, hi, shapely.area(inter))
    land_frac = np.clip(land_area / grid.area, 0.0, 1.0)
    is_land = land_frac >= land_threshold
    lon, lat = to_wgs84(cx, cy)
    return gpd.GeoDataFrame({
        "hex_id": ids, "q": q, "r": r,
        "centre_x_m": cx, "centre_y_m": cy,
        "centre_lon": np.round(lon, 6), "centre_lat": np.round(lat, 6),
        "chunk_id": chunk["chunk_id"],
        "land_fraction": np.round(land_frac, 6),
        "is_terrestrial_hex": is_land,
        "water_type": np.where(is_land, "NONE", "OCEAN"),
        "coverage_status": COVERAGE_STATUS_GEOMETRY_ONLY,
        "water_authority_status": WATER_AUTHORITY_STATUS,
        "geometry": polys,
    }, crs="EPSG:3857")


def chunk_canonical_hash(df: pd.DataFrame) -> str:
    """Normalized chunk content hash (ids + classification, no volatile)."""
    payload = "\n".join(
        f"{h}|{lf:.6f}|{w}" for h, lf, w in zip(
            df["hex_id"], df["land_fraction"], df["water_type"]))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
