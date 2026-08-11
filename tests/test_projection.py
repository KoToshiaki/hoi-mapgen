import math

import numpy as np

from mapgen.projection import WORLD_HALF_EXTENT_M, to_mercator, to_wgs84


def test_known_point_tokyo():
    lon, lat = 139.6917, 35.6895
    x, y = to_mercator(lon, lat)
    # Web Mercator closed form (spherical, R = 6378137 m).
    R = 6378137.0
    assert math.isclose(float(x), math.radians(lon) * R, rel_tol=1e-9)
    assert math.isclose(
        float(y), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)),
        rel_tol=1e-9,
    )


def test_world_extent():
    x, _ = to_mercator(180.0, 0.0)
    assert math.isclose(float(x), WORLD_HALF_EXTENT_M, rel_tol=1e-12)


def test_round_trip():
    rng = np.random.default_rng(42)
    lon = rng.uniform(-179, 179, 100)
    lat = rng.uniform(-84, 84, 100)
    x, y = to_mercator(lon, lat)
    lon2, lat2 = to_wgs84(x, y)
    assert np.allclose(lon, lon2, atol=1e-9)
    assert np.allclose(lat, lat2, atol=1e-9)
