import numpy as np
import shapely

from mapgen.hex_grid import HexGrid
from mapgen.land import classify_hexes


def _run_once():
    grid = HexGrid(flat_to_flat=5000.0)
    q, r = grid.hexes_covering_bbox(100000, 200000, 180000, 260000)
    polys = grid.polygons(q, r)
    cx, cy = grid.axial_to_xy(q, r)
    centres = np.stack([cx, cy], axis=1)
    land = shapely.box(50000, 150000, 140000, 300000)
    res = classify_hexes(polys, centres, land, shapely.boundary(land),
                         grid.area, 0.5)
    ids = grid.hex_ids(q, r)
    return q, r, cx, cy, ids, res


def test_two_runs_identical():
    q1, r1, cx1, cy1, ids1, res1 = _run_once()
    q2, r2, cx2, cy2, ids2, res2 = _run_once()
    assert np.array_equal(q1, q2)
    assert np.array_equal(r1, r2)
    assert np.array_equal(cx1, cx2)
    assert np.array_equal(cy1, cy2)
    assert ids1 == ids2
    assert np.array_equal(res1["land_class"], res2["land_class"])
    assert np.array_equal(res1["land_fraction"], res2["land_fraction"])
    assert np.array_equal(res1["is_coastal"], res2["is_coastal"])
