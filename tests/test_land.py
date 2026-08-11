import numpy as np
import shapely

from mapgen.hex_grid import HexGrid
from mapgen.land import classify_hexes, generated_coastline

GRID = HexGrid(flat_to_flat=1000.0)


def _classify(land, hexes):
    q = np.array([h[0] for h in hexes])
    r = np.array([h[1] for h in hexes])
    polys = GRID.polygons(q, r)
    cx, cy = GRID.axial_to_xy(q, r)
    centres = np.stack([cx, cy], axis=1)
    coast = shapely.boundary(land)
    return classify_hexes(polys, centres, land, coast, GRID.area, 0.5)


def test_fully_land_fully_water_and_coastal():
    # Land = huge half-plane x <= 0 (approximated by a big box).
    land = shapely.box(-1e6, -1e6, 0, 1e6)
    hexes = [(-30, 0), (30, 0), (0, 0)]  # deep land, deep water, on the coast
    res = _classify(land, hexes)

    assert res["land_fraction"][0] == 1.0
    assert res["land_class"][0] == "land"
    assert not res["is_coastal"][0]
    assert res["classification_error_area_m2"][0] == 0.0

    assert res["land_fraction"][1] == 0.0
    assert res["land_class"][1] == "water"
    assert not res["is_coastal"][1]

    # Hex (0,0) is centred exactly on the coast x=0: half land.
    assert abs(res["land_fraction"][2] - 0.5) < 1e-9
    assert res["is_coastal"][2]
    # Whatever the binary class, the discarded area is half the hex.
    assert abs(res["classification_error_area_m2"][2] - GRID.area / 2) < 1e-6


def test_fraction_sum_and_water_fraction():
    land = shapely.box(-1e6, -1e6, 250.0, 1e6)  # coast shifted into hex (0,0)
    res = _classify(land, [(0, 0)])
    lf, wf = res["land_fraction"][0], res["water_fraction"][0]
    assert 0.5 < lf < 1.0
    assert abs(lf + wf - 1.0) < 1e-12
    assert res["land_class"][0] == "land"
    assert abs(
        res["classification_error_area_m2"][0] - res["water_intersection_m2"][0]
    ) < 1e-9


def test_distance_centre_to_coast():
    land = shapely.box(-1e6, -1e6, 0, 1e6)
    res = _classify(land, [(-30, 0)])
    cx, _ = GRID.axial_to_xy(-30, 0)
    # Distance from centre to the x=0 coastline equals |cx|.
    assert abs(res["distance_centre_to_source_coast_m"][0] - abs(cx)) < 1e-6


def test_generated_coastline_is_land_water_boundary():
    land = shapely.box(-1e6, -1e6, 0, 1e6)
    q, r = GRID.hexes_covering_bbox(-5000, -5000, 5000, 5000)
    polys = GRID.polygons(q, r)
    cx, cy = GRID.axial_to_xy(q, r)
    centres = np.stack([cx, cy], axis=1)
    res = classify_hexes(polys, centres, land, shapely.boundary(land), GRID.area, 0.5)
    coast = generated_coastline(polys, res["land_class"] == "land")
    assert not shapely.is_empty(coast)
    # Every point of the true coast (x=0) must be within one hex width of the
    # generated hex coastline.
    true_coast = shapely.LineString([(0, -3000), (0, 3000)])
    samples = shapely.line_interpolate_point(true_coast, np.arange(0, 6000, 100.0))
    dists = shapely.distance(samples, coast)
    assert dists.max() <= GRID.flat_to_flat
