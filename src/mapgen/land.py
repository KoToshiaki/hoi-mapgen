"""Land loading and hex land/water classification.

All classification is fractional: every hex polygon is intersected with the
source land geometry on the EPSG:3857 plane, and land_fraction / water_fraction
are always preserved. The binary land_class only applies a configurable
threshold on top of the fractions.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import box


def load_land_mercator(shp_path: Path, bbox_3857: tuple[float, float, float, float],
                       clip_margin_m: float) -> shapely.Geometry:
    """Load land polygons, clip to the (expanded) bbox, project to EPSG:3857.

    Returns a single (Multi)Polygon in EPSG:3857, clipped to the bbox expanded
    by ``clip_margin_m`` on every side.
    """
    min_x, min_y, max_x, max_y = bbox_3857
    clip_box_3857 = box(min_x - clip_margin_m, min_y - clip_margin_m,
                        max_x + clip_margin_m, max_y + clip_margin_m)
    # Pre-filter in WGS84 with a generous window before the precise 3857 clip.
    clip_gdf = gpd.GeoDataFrame(geometry=[clip_box_3857], crs="EPSG:3857")
    wgs_window = tuple(clip_gdf.to_crs("EPSG:4326").total_bounds)
    gdf = gpd.read_file(shp_path, bbox=wgs_window)
    if gdf.empty:
        return shapely.Polygon()
    merc = gdf.to_crs("EPSG:3857")
    land = shapely.union_all(merc.geometry.values)
    land = shapely.make_valid(land)
    clipped = shapely.intersection(land, clip_box_3857)
    return shapely.make_valid(clipped)


def source_coastline(land_3857: shapely.Geometry,
                     clip_bbox_3857: tuple[float, float, float, float]) -> shapely.Geometry:
    """Coastline = boundary of the land polygons, minus artificial clip edges.

    The land geometry was clipped to a rectangle; boundary segments lying on
    that rectangle's edge are clip artifacts, not real coastline, so they are
    removed by shrinking the rectangle by 1 m and intersecting.
    """
    boundary = shapely.boundary(land_3857)
    min_x, min_y, max_x, max_y = clip_bbox_3857
    inner = box(min_x + 1.0, min_y + 1.0, max_x - 1.0, max_y - 1.0)
    return shapely.intersection(boundary, inner)


def classify_hexes(hex_polys: np.ndarray, centres: np.ndarray,
                   land_3857: shapely.Geometry, coastline_3857: shapely.Geometry,
                   hex_area: float, land_threshold: float) -> dict[str, np.ndarray]:
    """Fractional land/water classification for an array of hex polygons.

    Returns a dict of per-hex arrays (see keys below).
    """
    n = len(hex_polys)
    land_geom = land_3857 if not shapely.is_empty(land_3857) else None

    if land_geom is None:
        land_area = np.zeros(n)
        coast_len = np.zeros(n)
        dist_coast = np.full(n, np.inf)
    else:
        # Vectorised intersection of every hex with the land union.
        inter = shapely.intersection(hex_polys, land_geom)
        land_area = shapely.area(inter)
        coast_inter = shapely.intersection(hex_polys, coastline_3857)
        coast_len = shapely.length(coast_inter)
        centre_points = shapely.points(centres)
        dist_coast = shapely.distance(centre_points, coastline_3857)

    land_frac = np.clip(land_area / hex_area, 0.0, 1.0)
    water_frac = 1.0 - land_frac
    is_land = land_frac >= land_threshold
    land_class = np.where(is_land, "land", "water")
    water_area = hex_area - land_area
    # Coastal: partially land, or crossed by the source coastline.
    eps = 1e-9
    is_coastal = ((land_frac > eps) & (land_frac < 1.0 - eps)) | (coast_len > 0.0)
    # Binary classification error: the intersection area that the binary class throws away.
    class_error_area = np.where(is_land, water_area, land_area)

    return {
        "land_intersection_m2": land_area,
        "water_intersection_m2": water_area,
        "land_fraction": land_frac,
        "water_fraction": water_frac,
        "land_class": land_class,
        "is_coastal": is_coastal,
        "coastline_intersection_m": coast_len,
        "distance_centre_to_source_coast_m": dist_coast,
        "classification_error_area_m2": class_error_area,
    }


def generated_coastline(hex_polys: np.ndarray, is_land: np.ndarray) -> shapely.Geometry:
    """Boundary between binary land hexes and water hexes.

    Built as the boundary of the union of all land-classified hex polygons.
    """
    land_polys = hex_polys[is_land]
    if len(land_polys) == 0:
        return shapely.LineString()
    union = shapely.union_all(land_polys)
    return shapely.boundary(union)
