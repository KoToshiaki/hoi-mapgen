"""City loading, hex assignment and collision statistics."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from .hex_grid import HexGrid
from .projection import to_mercator, to_wgs84


GEONAMES_COLUMNS = [
    "geonameid", "name", "asciiname", "alternatenames", "latitude", "longitude",
    "feature_class", "feature_code", "country_code", "cc2", "admin1", "admin2",
    "admin3", "admin4", "population", "elevation", "dem", "timezone", "mod_date",
]


def load_cities_geonames(txt_path: Path, bbox_wgs84) -> pd.DataFrame:
    """Load GeoNames cities15000.txt places inside the WGS84 bbox.

    Returns city_id / city_name / population / source_lon / source_lat.
    """
    raw = pd.read_csv(
        txt_path, sep="\t", header=None, names=GEONAMES_COLUMNS,
        dtype={"geonameid": np.int64, "population": np.int64},
        keep_default_na=False, na_values=[], quoting=3, encoding="utf-8",
    )
    mask = (
        (raw["longitude"] >= bbox_wgs84.min_x) & (raw["longitude"] <= bbox_wgs84.max_x)
        & (raw["latitude"] >= bbox_wgs84.min_y) & (raw["latitude"] <= bbox_wgs84.max_y)
    )
    sub = raw[mask]
    df = pd.DataFrame(
        {
            "city_id": sub["geonameid"].to_numpy(),
            "city_name": sub["name"].astype(str).to_numpy(),
            "population": sub["population"].to_numpy(),
            "source_lon": sub["longitude"].astype(float).to_numpy(),
            "source_lat": sub["latitude"].astype(float).to_numpy(),
        }
    )
    return df.sort_values("city_id").reset_index(drop=True)


def load_cities(shp_path: Path, bbox_wgs84) -> pd.DataFrame:
    """Load populated places inside the WGS84 bbox.

    Returns a plain DataFrame with city_id / city_name / population / lon / lat.
    Population is Natural Earth POP_MAX (may be 0/unknown for small places).
    """
    gdf = gpd.read_file(
        shp_path,
        bbox=(bbox_wgs84.min_x, bbox_wgs84.min_y, bbox_wgs84.max_x, bbox_wgs84.max_y),
    )
    if gdf.empty:
        return pd.DataFrame(
            columns=["city_id", "city_name", "population", "source_lon", "source_lat"]
        )
    df = pd.DataFrame(
        {
            "city_id": gdf["NE_ID"].astype(np.int64),
            "city_name": gdf["NAME"].astype(str),
            "population": pd.to_numeric(gdf["POP_MAX"], errors="coerce").fillna(0).astype(np.int64),
            "source_lon": gdf.geometry.x.astype(float),
            "source_lat": gdf.geometry.y.astype(float),
        }
    )
    # Deterministic ordering regardless of source file order.
    df = df.sort_values("city_id").reset_index(drop=True)
    return df


def assign_cities(cities: pd.DataFrame, grid: HexGrid) -> pd.DataFrame:
    """Project cities to EPSG:3857 and assign each to its containing hex."""
    df = cities.copy()
    if df.empty:
        for col in ("source_x_m", "source_y_m", "assigned_q", "assigned_r",
                    "assigned_hex_id", "hex_centre_x_m", "hex_centre_y_m",
                    "hex_centre_lon", "hex_centre_lat", "city_to_hex_centre_m"):
            df[col] = []
        return df
    x, y = to_mercator(df["source_lon"].values, df["source_lat"].values)
    q, r = grid.xy_to_axial(x, y)
    cx, cy = grid.axial_to_xy(q, r)
    clon, clat = to_wgs84(cx, cy)
    df["source_x_m"] = x
    df["source_y_m"] = y
    df["assigned_q"] = q
    df["assigned_r"] = r
    df["assigned_hex_id"] = grid.hex_ids(q, r)
    df["hex_centre_x_m"] = cx
    df["hex_centre_y_m"] = cy
    df["hex_centre_lon"] = clon
    df["hex_centre_lat"] = clat
    df["city_to_hex_centre_m"] = np.hypot(x - cx, y - cy)
    return df


def add_collision_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Per-city collision / nearest-neighbour statistics (EPSG:3857 distances)."""
    df = df.copy()
    n = len(df)
    if n == 0:
        for col in ("cities_in_same_hex", "shares_hex_with_other_city",
                    "nearest_other_city_name", "nearest_other_city_distance_m"):
            df[col] = []
        return df

    counts = df.groupby("assigned_hex_id")["city_id"].transform("count")
    df["cities_in_same_hex"] = counts.astype(np.int64)
    df["shares_hex_with_other_city"] = counts > 1

    if n == 1:
        df["nearest_other_city_name"] = None
        df["nearest_other_city_distance_m"] = np.nan
    else:
        xy = df[["source_x_m", "source_y_m"]].to_numpy()
        d2 = ((xy[:, None, :] - xy[None, :, :]) ** 2).sum(axis=2)
        np.fill_diagonal(d2, np.inf)
        nearest_idx = d2.argmin(axis=1)
        df["nearest_other_city_name"] = df["city_name"].to_numpy()[nearest_idx]
        df["nearest_other_city_distance_m"] = np.sqrt(d2[np.arange(n), nearest_idx])
    return df


def collision_summary(df: pd.DataFrame, population_thresholds: list[int]) -> dict:
    """Aggregate collision statistics, overall and per population threshold."""
    def _stats(sub: pd.DataFrame) -> dict:
        if sub.empty:
            return {
                "city_count": 0,
                "cities_sharing_hex_count": 0,
                "city_hex_collision_count": 0,
                "collision_population_sum": 0,
                "collision_city_names": "",
            }
        counts = sub.groupby("assigned_hex_id")["city_id"].count()
        collided_hexes = counts[counts > 1]
        sharing = sub[sub["assigned_hex_id"].isin(collided_hexes.index)]
        names = []
        for hex_id, grp in sharing.sort_values(
            ["assigned_hex_id", "population"], ascending=[True, False]
        ).groupby("assigned_hex_id"):
            names.append("+".join(grp["city_name"].tolist()))
        return {
            "city_count": int(len(sub)),
            "cities_sharing_hex_count": int(len(sharing)),
            "city_hex_collision_count": int(len(collided_hexes)),
            "collision_population_sum": int(sharing["population"].sum()),
            "collision_city_names": "; ".join(sorted(names)),
        }

    result = {"overall": _stats(df)}
    for thr in population_thresholds:
        result[f"population_ge_{thr}"] = _stats(df[df["population"] >= thr])
    return result
