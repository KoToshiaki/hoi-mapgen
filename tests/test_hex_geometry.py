import math

import numpy as np
import pytest
import shapely

from mapgen.hex_grid import SQRT3, HexGrid


@pytest.fixture(params=["pointy", "flat"])
def grid(request):
    return HexGrid(flat_to_flat=6000.0, orientation=request.param)


def test_scalar_geometry(grid):
    assert math.isclose(grid.side, 6000.0 / SQRT3)
    assert math.isclose(grid.point_to_point, 2 * 6000.0 / SQRT3)
    assert math.isclose(grid.area, (SQRT3 / 2) * 6000.0**2)


def test_polygon_is_regular_hexagon(grid):
    poly = grid.polygon(3, -2)
    coords = shapely.get_coordinates(poly)[:-1]  # drop closing point
    assert len(coords) == 6
    cx, cy = grid.axial_to_xy(3, -2)
    # All vertices at circumradius from the centre.
    dist = np.hypot(coords[:, 0] - cx, coords[:, 1] - cy)
    assert np.allclose(dist, grid.side, rtol=1e-12)
    # All sides equal to the side length.
    sides = np.hypot(*(np.roll(coords, -1, axis=0) - coords).T)
    assert np.allclose(sides, grid.side, rtol=1e-12)


def test_flat_to_flat_distance_matches_config(grid):
    poly = grid.polygon(0, 0)
    coords = shapely.get_coordinates(poly)[:-1]
    # Opposite edge midpoints are flat_to_flat apart.
    mids = (coords + np.roll(coords, -1, axis=0)) / 2
    for i in range(3):
        d = np.hypot(*(mids[i] - mids[i + 3]))
        assert math.isclose(d, grid.flat_to_flat, rel_tol=1e-12)


def test_polygon_area_matches_theory(grid):
    poly = grid.polygon(10, 7)
    assert math.isclose(poly.area, grid.area, rel_tol=1e-12)


def test_six_neighbors_no_overlap_no_gap(grid):
    q0, r0 = 2, -1
    nbrs = grid.neighbors(q0, r0)
    assert len(nbrs) == 6
    centre_poly = grid.polygon(q0, r0)
    x0, y0 = grid.axial_to_xy(q0, r0)
    polys = [centre_poly]
    for q, r in nbrs:
        p = grid.polygon(q, r)
        x, y = grid.axial_to_xy(q, r)
        # Neighbour centres at exactly flat_to_flat distance.
        assert math.isclose(math.hypot(x - x0, y - y0), grid.flat_to_flat,
                            rel_tol=1e-12)
        # The shared edge midpoint lies on both hex boundaries.
        mid = shapely.Point((x0 + x) / 2, (y0 + y) / 2)
        assert centre_poly.exterior.distance(mid) < 1e-6
        assert p.exterior.distance(mid) < 1e-6
        # No overlap beyond floating-point slivers.
        assert centre_poly.intersection(p).area < 1e-6
        polys.append(p)
    union = shapely.union_all(polys)
    # No overlap: union area == sum of areas (within float tolerance).
    assert math.isclose(union.area, 7 * grid.area, rel_tol=1e-9)
    # No gap: the union has no holes bigger than floating-point slivers.
    holes = [
        shapely.Polygon(union.interiors[i]).area
        for i in range(len(union.interiors))
    ] if union.geom_type == "Polygon" else []
    assert all(a < 1e-6 for a in holes)


def test_tiling_covers_bbox(grid):
    box = shapely.box(-20000, -20000, 20000, 20000)
    q, r = grid.hexes_covering_bbox(-20000, -20000, 20000, 20000)
    polys = grid.polygons(q, r)
    union = shapely.union_all(polys)
    # No overlaps: union area equals count * hex area.
    assert math.isclose(union.area, len(q) * grid.area, rel_tol=1e-9)
    # Full coverage of the bbox (1 mm buffer absorbs float slivers).
    assert union.buffer(1e-3).contains(box)
