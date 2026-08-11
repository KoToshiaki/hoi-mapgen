"""Coastline sampling and reproduction-error measurement.

The source coastline (from the land dataset) is sampled at a fixed interval on
the EPSG:3857 plane; for each sample point we measure the distance to the
nearest point of the *generated* coastline (the land/water boundary of the
binary hex classification).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import shapely

from .projection import to_wgs84


def sample_coastline(coastline_3857: shapely.Geometry, interval_m: float,
                     core_bbox_3857: tuple[float, float, float, float]) -> np.ndarray:
    """Sample points every ``interval_m`` along the source coastline.

    Only samples inside the core bbox are kept, so clip/margin artifacts near
    the region edge do not contaminate the error statistics.
    Returns an (n, 2) array of x/y coordinates, deterministically ordered.
    """
    if shapely.is_empty(coastline_3857):
        return np.empty((0, 2))
    merged = shapely.line_merge(coastline_3857)
    lines = []
    for geom in shapely.get_parts(np.asarray([merged]).ravel()):
        for part in shapely.get_parts(geom) if geom.geom_type.startswith("Multi") else [geom]:
            if part.geom_type == "LineString" and part.length > 0:
                lines.append(part)
    # Deterministic ordering: by first coordinate.
    lines.sort(key=lambda g: (g.coords[0][0], g.coords[0][1]))

    pts = []
    for line in lines:
        distances = np.arange(0.0, line.length, interval_m)
        if len(distances) == 0:
            continue
        sampled = shapely.line_interpolate_point(line, distances)
        coords = shapely.get_coordinates(sampled)
        pts.append(coords)
    if not pts:
        return np.empty((0, 2))
    coords = np.vstack(pts)
    min_x, min_y, max_x, max_y = core_bbox_3857
    mask = (
        (coords[:, 0] >= min_x) & (coords[:, 0] <= max_x)
        & (coords[:, 1] >= min_y) & (coords[:, 1] <= max_y)
    )
    return coords[mask]


def coastline_errors(sample_xy: np.ndarray,
                     generated_coast_3857: shapely.Geometry) -> pd.DataFrame:
    """Distance from each source sample to the nearest generated-coast point."""
    n = len(sample_xy)
    if n == 0 or shapely.is_empty(generated_coast_3857):
        return pd.DataFrame(
            columns=["sample_id", "source_x_m", "source_y_m", "source_lon", "source_lat",
                     "nearest_generated_coast_x_m", "nearest_generated_coast_y_m",
                     "coast_error_m"]
        )
    points = shapely.points(sample_xy)
    # shortest_line is vectorised; its second endpoint lies on the generated coast.
    lines = shapely.shortest_line(points, generated_coast_3857)
    coords = shapely.get_coordinates(lines).reshape(n, 2, 2)
    nearest = coords[:, 1, :]
    errors = np.hypot(sample_xy[:, 0] - nearest[:, 0], sample_xy[:, 1] - nearest[:, 1])
    lon, lat = to_wgs84(sample_xy[:, 0], sample_xy[:, 1])
    return pd.DataFrame(
        {
            "sample_id": np.arange(n, dtype=np.int64),
            "source_x_m": sample_xy[:, 0],
            "source_y_m": sample_xy[:, 1],
            "source_lon": lon,
            "source_lat": lat,
            "nearest_generated_coast_x_m": nearest[:, 0],
            "nearest_generated_coast_y_m": nearest[:, 1],
            "coast_error_m": errors,
        }
    )
