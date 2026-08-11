import numpy as np
import pytest

from mapgen.hex_grid import HexGrid


@pytest.fixture(params=["pointy", "flat"])
def grid(request):
    return HexGrid(flat_to_flat=5000.0, orientation=request.param,
                   origin_x=0.0, origin_y=0.0)


def test_axial_to_xy_to_axial_round_trip(grid):
    rng = np.random.default_rng(7)
    q = rng.integers(-5000, 5000, 500)
    r = rng.integers(-5000, 5000, 500)
    x, y = grid.axial_to_xy(q, r)
    q2, r2 = grid.xy_to_axial(x, y)
    assert np.array_equal(q, q2)
    assert np.array_equal(r, r2)


def test_random_points_map_to_containing_hex(grid):
    rng = np.random.default_rng(11)
    x = rng.uniform(-1e6, 1e6, 300)
    y = rng.uniform(-1e6, 1e6, 300)
    q, r = grid.xy_to_axial(x, y)
    polys = grid.polygons(q, r)
    import shapely

    pts = shapely.points(np.stack([x, y], axis=1))
    # Every point lies in (or on the boundary of) its assigned hex.
    assert shapely.dwithin(polys, pts, 1e-6).all()


def test_hex_id_deterministic_and_signed(grid):
    assert grid.hex_id(1234, -567) == "h5000_q+001234_r-000567"
    assert grid.hex_id(0, 0) == "h5000_q+000000_r+000000"


def test_hex_id_independent_of_region():
    # Same size and same (q, r) must give the same ID and centre regardless of
    # which bbox was generated (grid origin is world-fixed).
    g = HexGrid(flat_to_flat=8000.0)
    a = g.hexes_covering_bbox(0, 0, 50000, 50000)
    b = g.hexes_covering_bbox(-50000, -50000, 60000, 60000)
    ids_a = {(q, r): g.hex_id(q, r) for q, r in zip(*a)}
    ids_b = {(q, r): g.hex_id(q, r) for q, r in zip(*b)}
    common = set(ids_a) & set(ids_b)
    assert common
    for key in common:
        assert ids_a[key] == ids_b[key]
