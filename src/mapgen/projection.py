"""WGS84 (EPSG:4326) <-> Web Mercator (EPSG:3857) projection helpers.

All game-map geometry lives on the EPSG:3857 plane. These helpers are the only
place in mapgen where coordinate transformation happens.
"""
from __future__ import annotations

import numpy as np
from pyproj import Transformer

CRS_WGS84 = "EPSG:4326"
CRS_MERCATOR = "EPSG:3857"

# Web Mercator world half-extent in metres (x in [-E, E]; y likewise for
# latitude clamped to ~85.051 degrees).
WORLD_HALF_EXTENT_M = 20037508.342789244

_TO_MERCATOR = Transformer.from_crs(CRS_WGS84, CRS_MERCATOR, always_xy=True)
_TO_WGS84 = Transformer.from_crs(CRS_MERCATOR, CRS_WGS84, always_xy=True)


def to_mercator(lon, lat):
    """lon/lat (degrees) -> x/y metres on EPSG:3857. Accepts scalars or arrays."""
    return _TO_MERCATOR.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))


def to_wgs84(x, y):
    """x/y metres on EPSG:3857 -> lon/lat degrees. Accepts scalars or arrays."""
    return _TO_WGS84.transform(np.asarray(x, dtype=float), np.asarray(y, dtype=float))


def bbox_to_mercator(bbox) -> tuple[float, float, float, float]:
    """Project a WGS84 BBox to (min_x, min_y, max_x, max_y) in EPSG:3857 metres."""
    xs, ys = to_mercator([bbox.min_x, bbox.max_x], [bbox.min_y, bbox.max_y])
    return float(xs[0]), float(ys[0]), float(xs[1]), float(ys[1])
