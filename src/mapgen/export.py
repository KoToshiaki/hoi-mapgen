"""Export of hex/city/coastline data as CSV, Parquet, GeoJSON and GeoParquet."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

# Column order for hex_cells.csv (superset of the required evaluation schema).
HEX_CSV_COLUMNS = [
    "schema_version", "run_id", "hex_size_m", "hex_flat_to_flat_m",
    "hex_id", "q", "r",
    "centre_x_m", "centre_y_m", "centre_lon", "centre_lat",
    "hex_area_m2",
    "land_intersection_m2", "water_intersection_m2",
    "land_fraction", "water_fraction", "land_class",
    "is_coastal", "coastline_intersection_m", "distance_centre_to_coast_m",
    "city_count", "primary_city_id", "primary_city_name",
    "same_hex_city_count",
    "source_land_area_m2", "classification_error_area_m2",
    "country_id", "state_id", "region_id", "city_area_id",
]

CITY_CSV_COLUMNS = [
    "run_id", "hex_size_m",
    "city_id", "city_name", "population",
    "source_lon", "source_lat", "source_x_m", "source_y_m",
    "assigned_hex_id", "assigned_q", "assigned_r",
    "hex_centre_lon", "hex_centre_lat",
    "city_to_hex_centre_m",
    "assigned_hex_land_fraction", "assigned_hex_land_class",
    "cities_in_same_hex",
    "nearest_other_city_name", "nearest_other_city_distance_m",
    "shares_hex_with_other_city",
]

COAST_CSV_COLUMNS = [
    "run_id", "hex_size_m",
    "sample_id",
    "source_x_m", "source_y_m", "source_lon", "source_lat",
    "nearest_generated_coast_x_m", "nearest_generated_coast_y_m",
    "coast_error_m",
]


def write_hex_outputs(out_dir: Path, hex_df: pd.DataFrame,
                      hex_polys: np.ndarray) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_df = hex_df[HEX_CSV_COLUMNS]
    csv_df.to_csv(out_dir / "hex_cells.csv", index=False, float_format="%.6f")
    csv_df.to_parquet(out_dir / "hex_cells.parquet", index=False)

    gdf = gpd.GeoDataFrame(csv_df.copy(), geometry=list(hex_polys), crs="EPSG:3857")
    gdf.to_parquet(out_dir / "hex_cells.geoparquet", index=False)
    # GeoJSON convention is WGS84.
    gdf.to_crs("EPSG:4326").to_file(out_dir / "hex_cells.geojson", driver="GeoJSON")


def write_city_outputs(out_dir: Path, cities_df: pd.DataFrame) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_df = cities_df[CITY_CSV_COLUMNS]
    csv_df.to_csv(out_dir / "cities.csv", index=False, float_format="%.6f")
    if len(csv_df):
        geom = gpd.points_from_xy(csv_df["source_lon"], csv_df["source_lat"])
        gdf = gpd.GeoDataFrame(csv_df.copy(), geometry=geom, crs="EPSG:4326")
        gdf.to_file(out_dir / "cities.geojson", driver="GeoJSON")


def write_coast_outputs(out_dir: Path, coast_df: pd.DataFrame,
                        generated_coast_3857: shapely.Geometry) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    coast_df[COAST_CSV_COLUMNS].to_csv(
        out_dir / "coastline_samples.csv", index=False, float_format="%.6f"
    )
    if not shapely.is_empty(generated_coast_3857):
        gdf = gpd.GeoDataFrame(geometry=[generated_coast_3857], crs="EPSG:3857")
        gdf.to_crs("EPSG:4326").to_file(
            out_dir / "generated_coastline.geojson", driver="GeoJSON"
        )


def dir_size_mb(path: Path) -> float:
    total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return total / (1024 * 1024)
