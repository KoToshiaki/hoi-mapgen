import numpy as np
import pandas as pd

from mapgen.cities import add_collision_stats, assign_cities, collision_summary
from mapgen.hex_grid import HexGrid
from mapgen.projection import to_wgs84

GRID = HexGrid(flat_to_flat=6000.0)


def _cities_at_xy(points):
    """Build a city DataFrame from EPSG:3857 points."""
    xy = np.array(points, dtype=float)
    lon, lat = to_wgs84(xy[:, 0], xy[:, 1])
    return pd.DataFrame({
        "city_id": np.arange(len(points), dtype=np.int64),
        "city_name": [f"city{i}" for i in range(len(points))],
        "population": [100000 * (i + 1) for i in range(len(points))],
        "source_lon": lon,
        "source_lat": lat,
    })


def test_city_assigned_to_expected_hex():
    # Points placed exactly at known hex centres (plus a small offset).
    targets = [(3, -2), (0, 0), (-5, 4)]
    centres = [GRID.axial_to_xy(q, r) for q, r in targets]
    pts = [(x + 200.0, y - 300.0) for x, y in centres]
    df = assign_cities(_cities_at_xy(pts), GRID)
    for (q, r), (_, row) in zip(targets, df.iterrows()):
        assert (row["assigned_q"], row["assigned_r"]) == (q, r)
        assert row["assigned_hex_id"] == GRID.hex_id(q, r)
        assert abs(row["city_to_hex_centre_m"] - np.hypot(200.0, 300.0)) < 1.0


def test_collision_stats():
    cx, cy = GRID.axial_to_xy(0, 0)
    ox, oy = GRID.axial_to_xy(10, 10)
    # Two cities in hex (0,0), one alone in hex (10,10).
    df = assign_cities(
        _cities_at_xy([(cx + 100, cy), (cx - 100, cy), (ox, oy)]), GRID
    )
    df = add_collision_stats(df)
    assert df["cities_in_same_hex"].tolist() == [2, 2, 1]
    assert df["shares_hex_with_other_city"].tolist() == [True, True, False]
    # city0's nearest other city is city1 at 200 m.
    assert df.loc[0, "nearest_other_city_name"] == "city1"
    assert abs(df.loc[0, "nearest_other_city_distance_m"] - 200.0) < 1e-6

    summary = collision_summary(df, [150000, 1000000])
    assert summary["overall"]["cities_sharing_hex_count"] == 2
    assert summary["overall"]["city_hex_collision_count"] == 1
    assert summary["overall"]["collision_city_names"] == "city1+city0"
    # Threshold 150000 keeps city1 (200k) and city2 (300k) -> different hexes.
    assert summary["population_ge_150000"]["city_hex_collision_count"] == 0
    assert summary["population_ge_1000000"]["city_count"] == 0
