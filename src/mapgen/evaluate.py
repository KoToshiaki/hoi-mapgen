"""Evaluation metrics per hex size.

Evaluation is strictly read-only over generated data: it never feeds back into
generation and never selects a "winning" hex size.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .projection import WORLD_HALF_EXTENT_M


def _pct(values: np.ndarray, p: float) -> float:
    return float(np.percentile(values, p)) if len(values) else float("nan")


def summarize(run_id: str, hex_size_m: float, hex_df: pd.DataFrame,
              cities_df: pd.DataFrame, coast_df: pd.DataFrame,
              source_land_area_m2: float, hex_area_m2: float,
              collision: dict, generated_file_size_mb: float,
              generation_time_s: float, evaluation_time_s: float,
              peak_memory_mb: float) -> dict:
    """One evaluation_summary row for one hex size.

    ``source_land_area_m2`` must be measured over the same domain the hexes
    cover, so binary-vs-source differences are pure quantisation error.
    """
    is_land = hex_df["land_class"] == "land"
    binary_land_area_m2 = float(is_land.sum()) * hex_area_m2
    fractional_land_area_m2 = float(hex_df["land_intersection_m2"].sum())
    class_error_m2 = float(hex_df["classification_error_area_m2"].sum())

    errors = coast_df["coast_error_m"].to_numpy()
    c2h = cities_df["city_to_hex_centre_m"].to_numpy() if len(cities_df) else np.array([])

    # Same grid density extended over the full square Web Mercator world plane.
    world_area_m2 = (2.0 * WORLD_HALF_EXTENT_M) ** 2
    estimated_world_hex_count = int(round(world_area_m2 / hex_area_m2))

    overall = collision["overall"]
    row = {
        "run_id": run_id,
        "hex_size_m": hex_size_m,
        "total_hex_count": int(len(hex_df)),
        "land_hex_count": int(is_land.sum()),
        "water_hex_count": int((~is_land).sum()),
        "coastal_hex_count": int(hex_df["is_coastal"].sum()),
        "source_land_area_km2": source_land_area_m2 / 1e6,
        "binary_hex_land_area_km2": binary_land_area_m2 / 1e6,
        "fractional_hex_land_area_km2": fractional_land_area_m2 / 1e6,
        "binary_land_area_error_km2": (binary_land_area_m2 - source_land_area_m2) / 1e6,
        "binary_land_area_error_pct": (
            100.0 * (binary_land_area_m2 - source_land_area_m2) / source_land_area_m2
            if source_land_area_m2 > 0 else float("nan")
        ),
        "classification_error_area_km2": class_error_m2 / 1e6,
        "classification_error_pct": (
            100.0 * class_error_m2 / source_land_area_m2
            if source_land_area_m2 > 0 else float("nan")
        ),
        "coast_sample_count": int(len(errors)),
        "coast_error_mean_m": float(errors.mean()) if len(errors) else float("nan"),
        "coast_error_median_m": _pct(errors, 50),
        "coast_error_p90_m": _pct(errors, 90),
        "coast_error_p95_m": _pct(errors, 95),
        "coast_error_max_m": float(errors.max()) if len(errors) else float("nan"),
        "city_count": int(len(cities_df)),
        "city_to_hex_centre_mean_m": float(c2h.mean()) if len(c2h) else float("nan"),
        "city_to_hex_centre_median_m": _pct(c2h, 50),
        "city_to_hex_centre_p95_m": _pct(c2h, 95),
        "city_to_hex_centre_max_m": float(c2h.max()) if len(c2h) else float("nan"),
        "cities_sharing_hex_count": overall["cities_sharing_hex_count"],
        "city_hex_collision_count": overall["city_hex_collision_count"],
        "collision_population_sum": overall["collision_population_sum"],
        "collision_city_names": overall["collision_city_names"],
        "estimated_world_hex_count": estimated_world_hex_count,
        "generated_file_size_mb": generated_file_size_mb,
        "generation_time_s": generation_time_s,
        "evaluation_time_s": evaluation_time_s,
        "peak_memory_mb": peak_memory_mb,
    }
    # Per-population-threshold collision stats.
    for key, stats in collision.items():
        if key == "overall":
            continue
        row[f"cities_sharing_hex_count_{key}"] = stats["cities_sharing_hex_count"]
        row[f"city_hex_collision_count_{key}"] = stats["city_hex_collision_count"]
    return row
