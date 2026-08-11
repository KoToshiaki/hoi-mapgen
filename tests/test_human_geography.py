"""MAPGEN-007 unit tests — synthetic fixtures only, no internet, no data/.

Covers the spec's TEST-ONLY synthetic island-overlay settlement/port
fixtures, dateline distance handling, dominant-admin determinism and the
reference (non-gameplay) semantics fields.
"""
import numpy as np
import pandas as pd
import shapely

from mapgen.hex_grid import HexGrid
from mapgen.human_geography import (REFERENCE_SEMANTICS,
                                    bidirectional_hex_audit,
                                    bind_point_to_admin, bind_point_to_land,
                                    bind_point_to_water, build_admin0,
                                    choose_dominant_admin,
                                    dateline_ground_distance_m,
                                    repair_geometries)
from mapgen.human_geography_pipeline import (_prep_region_bindings,
                                             hex_admin_membership)
from mapgen.islands import WORLD_WIDTH_M
from mapgen.projection import to_mercator

GRID = HexGrid(flat_to_flat=6000.0)


def _region(comp_geoms=(), comp_ids=(), comp_units=(), water="OCEAN",
            n=5, crosses=False, terrestrial_qr=()):
    """Synthetic region: n x n hex block, all water except terrestrial_qr."""
    qs, rs = np.meshgrid(np.arange(n), np.arange(n))
    q, r = qs.ravel(), rs.ravel()
    ids = GRID.hex_ids(q, r)
    polys = GRID.polygons(q, r)
    terr = set(terrestrial_qr)
    water_type = np.array([("NONE" if (qi, ri) in terr else water)
                           for qi, ri in zip(q, r)], dtype=object)
    comp_df = pd.DataFrame({
        "region": ["syn"] * len(comp_ids),
        "island_component_id": list(comp_ids),
        "overlay_unit_id": list(comp_units),
        "representation_status": ["IN_OVERLAY_UNIT"] * len(comp_ids),
        "geometry": list(comp_geoms),
    })
    return _prep_region_bindings("syn", GRID, ids, polys, water_type,
                                 comp_df, crosses,
                                 land_fraction=[1.0 if (qi, ri) in terr
                                                else 0.0
                                                for qi, ri in zip(q, r)])


# --------------------------------------------------------------------------
# Synthetic island-overlay settlement binding (spec fixture)
# --------------------------------------------------------------------------
def test_settlement_on_overlay_component_binds_to_component():
    cx, cy = GRID.axial_to_xy(2, 2)
    islet = shapely.Point(float(cx), float(cy)).buffer(400.0, quad_segs=16)
    reg = _region(comp_geoms=[islet], comp_ids=["isl_c_test"],
                  comp_units=["isl_u_test"])
    lb = bind_point_to_land(shapely.Point(float(cx), float(cy)), reg, 3000.0)
    assert lb["land_binding_kind"] == "ISLAND_COMPONENT_OVERLAY"
    assert lb["binding_method"] == "COMPONENT_CONTAINS"
    assert lb["island_component_id"] == "isl_c_test"
    assert lb["overlay_unit_id"] == "isl_u_test"
    assert lb["binding_distance_m"] == 0.0
    # The underlying hex stays OCEAN — water authority is untouched.
    hid = GRID.hex_id(2, 2)
    assert reg["water_by_hex"][hid] == "OCEAN"


def test_settlement_on_terrestrial_hex_wins_over_components():
    cx, cy = GRID.axial_to_xy(1, 1)
    reg = _region(terrestrial_qr=[(1, 1)])
    lb = bind_point_to_land(shapely.Point(float(cx), float(cy)), reg, 3000.0)
    assert lb["land_binding_kind"] == "TERRESTRIAL_HEX"
    assert lb["terrestrial_hex_id"] == GRID.hex_id(1, 1)
    assert lb["binding_distance_m"] == 0.0


def test_settlement_near_component_snaps_with_recorded_distance():
    cx, cy = GRID.axial_to_xy(2, 2)
    islet = shapely.Point(float(cx), float(cy)).buffer(300.0, quad_segs=16)
    reg = _region(comp_geoms=[islet], comp_ids=["isl_c_near"],
                  comp_units=["isl_u_near"])
    pt = shapely.Point(float(cx) + 800.0, float(cy))
    lb = bind_point_to_land(pt, reg, 3000.0)
    assert lb["land_binding_kind"] == "ISLAND_COMPONENT_OVERLAY"
    assert lb["binding_method"] == "NEAREST_COMPONENT"
    assert lb["binding_distance_m"] is not None
    assert 0.0 < lb["binding_distance_m"] < 800.0  # ground < projected here


def test_settlement_far_from_land_is_unresolved_not_snapped():
    reg = _region()
    pt = shapely.Point(*[float(v) for v in GRID.axial_to_xy(2, 2)])
    lb = bind_point_to_land(pt, reg, 3000.0)
    assert lb["land_binding_kind"] == "UNRESOLVED"
    assert lb["binding_method"] == "UNRESOLVED"
    assert lb["terrestrial_hex_id"] is None
    assert lb["binding_distance_m"] is None


# --------------------------------------------------------------------------
# Synthetic overlay-port dual access (spec fixture)
# --------------------------------------------------------------------------
def test_port_on_overlay_component_has_land_and_water_access():
    cx, cy = GRID.axial_to_xy(2, 2)
    islet = shapely.Point(float(cx), float(cy)).buffer(400.0, quad_segs=16)
    reg = _region(comp_geoms=[islet], comp_ids=["isl_c_port"],
                  comp_units=["isl_u_port"])
    pt = shapely.Point(float(cx), float(cy))
    lb = bind_point_to_land(pt, reg, 5000.0)
    wb = bind_point_to_water(pt, reg, 5000.0)
    assert lb["land_binding_kind"] == "ISLAND_COMPONENT_OVERLAY"
    assert lb["island_component_id"] == "isl_c_port"
    # Water access = the containing OCEAN hex itself (overlay never
    # changes the hex's water authority).
    assert wb["water_access_hex_id"] == GRID.hex_id(2, 2)
    assert wb["water_access_type"] == "OCEAN"
    assert wb["water_access_distance_m"] == 0.0


def test_port_on_terrestrial_hex_finds_neighbouring_water():
    cx, cy = GRID.axial_to_xy(1, 1)
    reg = _region(terrestrial_qr=[(1, 1)])
    pt = shapely.Point(float(cx), float(cy))
    wb = bind_point_to_water(pt, reg, 5000.0)
    assert wb["water_access_hex_id"] is not None
    assert wb["water_access_hex_id"] != GRID.hex_id(1, 1)
    assert wb["water_access_type"] == "OCEAN"
    assert 0.0 < wb["water_access_distance_m"] <= 5000.0


# --------------------------------------------------------------------------
# Dateline
# --------------------------------------------------------------------------
def test_dateline_distance_uses_shifted_frame():
    x_east = to_mercator(179.99, -17.0)[0]
    x_west = to_mercator(-179.99, -17.0)[0]
    y = to_mercator(179.99, -17.0)[1]
    geom = shapely.Point(x_east, y).buffer(500.0)
    pt = shapely.Point(x_west, y)
    naive = shapely.distance(geom, pt)
    assert naive > WORLD_WIDTH_M * 0.9  # projected frame sees ~40,000 km
    d = dateline_ground_distance_m(geom, pt, crosses_dateline=True)
    assert d < 5000.0  # ground truth: ~2 km across the seam
    # Without the crossing flag the naive (audited) distance remains.
    d_flat = dateline_ground_distance_m(geom, pt, crosses_dateline=False)
    assert d_flat > d


# --------------------------------------------------------------------------
# Dominant admin determinism + membership shares
# --------------------------------------------------------------------------
def _entry(rid, km2, src):
    return {"reference_admin_id": rid, "intersection_ground_km2": km2,
            "source_stable_id": src}


def test_choose_dominant_admin_is_deterministic_on_ties():
    a = _entry("adm0_2", 1.0, 20)
    b = _entry("adm0_1", 1.0, 10)
    assert choose_dominant_admin([a, b]) == "adm0_1"
    assert choose_dominant_admin([b, a]) == "adm0_1"
    assert choose_dominant_admin([a]) == "adm0_2"
    assert choose_dominant_admin([]) is None
    # Larger ground area always wins over id order.
    c = _entry("adm0_9", 2.0, 90)
    assert choose_dominant_admin([a, b, c]) == "adm0_9"


def test_hex_admin_membership_shares_sum_to_one():
    reg = _region(terrestrial_qr=[(1, 1), (2, 2)])
    b = shapely.bounds(reg["polys"])
    xmid = (b[:, 0].min() + b[:, 2].max()) / 2.0
    left = shapely.box(b[:, 0].min() - 1e4, b[:, 1].min() - 1e4,
                       xmid, b[:, 3].max() + 1e4)
    right = shapely.box(xmid, b[:, 1].min() - 1e4,
                        b[:, 2].max() + 1e4, b[:, 3].max() + 1e4)
    admin = pd.DataFrame({
        "reference_admin0_id": ["adm0_L", "adm0_R"],
        "source_feature_id": [1, 2],
        "geometry": [left, right],
    })
    rows, _ = hex_admin_membership(reg, admin, "ADMIN0",
                                   np.array([], dtype=object), "t")
    df = pd.DataFrame(rows)
    sums = df.groupby("hex_id")["share_of_hex_ground_area"].sum()
    assert float(sums.min()) > 0.999 and float(sums.max()) < 1.001
    # Hexes straddling the split carry BOTH admins (many-to-many).
    n_admins = df.groupby("hex_id")["reference_admin_id"].nunique()
    assert int(n_admins.max()) == 2
    dom = df[df["is_dominant_reference_assignment"]]
    assert dom.groupby("hex_id").size().max() == 1


# --------------------------------------------------------------------------
# Semantics + canonicalisation
# --------------------------------------------------------------------------
def test_admin0_semantics_fields_are_reference_only():
    import geopandas as gpd

    gdf = gpd.GeoDataFrame({
        "NE_ID": [1159320917], "NAME": ["Testland"],
        "NAME_LONG": ["Republic of Testland"], "ADM0_A3": ["TST"],
        "ISO_A2_EH": ["-99"], "ISO_A3_EH": ["TST"],
        "SOVEREIGNT": ["Testland"], "SOV_A3": ["TST"],
        "ADMIN": ["Testland"], "TYPE": ["Sovereign country"],
        "geometry": [shapely.box(0, 0, 1e5, 1e5)],
    }, crs="EPSG:3857")
    df = build_admin0(gdf)
    row = df.iloc[0]
    assert row["reference_admin0_id"] == "adm0_1159320917"
    assert row["reference_boundary_semantics"] == REFERENCE_SEMANTICS
    assert not bool(row["gameplay_authoritative"])
    assert not bool(row["historical_authoritative"])
    assert row["iso_a2"] is None  # -99 cleaned to null, never invented
    assert row["iso_a3"] == "TST"


# --------------------------------------------------------------------------
# MAPGEN-007R: bidirectional coast/admin coverage audit
# --------------------------------------------------------------------------
HEX = GRID.polygon(100, 200)
TOL_ABS, TOL_REL = 0.01, 0.005


def _audit(coast, admins):
    return bidirectional_hex_audit(HEX, coast, np.array(admins,
                                                        dtype=object),
                                   TOL_ABS, TOL_REL)


def test_audit_identical_polygons_are_matched():
    a = _audit(HEX, [HEX])
    assert a["coverage_class"] == "MATCHED"
    assert a["undercovered_ground_km2"] == 0.0
    assert a["overcovered_ground_km2"] == 0.0
    assert a["land_coverage_fraction"] == 1.0
    assert a["admin0_to_coast_land_area_ratio"] == 1.0


def test_audit_small_admin_is_undercovered():
    cx, cy = HEX.centroid.x, HEX.centroid.y
    admin = shapely.Point(cx, cy).buffer(1500.0, quad_segs=16)
    a = _audit(HEX, [admin])
    assert a["coverage_class"] == "UNDERCOVERED"
    assert a["undercovered_ground_km2"] > 0
    assert a["overcovered_ground_km2"] == 0.0
    assert 0.0 < a["land_coverage_fraction"] < 1.0
    assert a["admin0_to_coast_land_area_ratio"] < 1.0


def test_audit_large_admin_is_overcovered_ratio_above_one():
    cx, cy = HEX.centroid.x, HEX.centroid.y
    coast = shapely.Point(cx, cy).buffer(1500.0, quad_segs=16)
    a = _audit(coast, [HEX])  # admin covers whole hex, coast is small
    assert a["coverage_class"] == "OVERCOVERED"
    assert a["overcovered_ground_km2"] > 0
    assert a["land_coverage_fraction"] <= 1.0  # bounded even here
    assert a["admin0_to_coast_land_area_ratio"] > 1.0  # allowed >1


def test_audit_shifted_polygons_are_bidirectional():
    cx, cy = HEX.centroid.x, HEX.centroid.y
    coast = shapely.box(cx - 2500, cy - 2000, cx + 1500, cy + 2000)
    admin = shapely.box(cx - 1500, cy - 2000, cx + 2500, cy + 2000)
    a = _audit(coast, [admin])
    assert a["coverage_class"] == "BIDIRECTIONAL_MISMATCH"
    assert a["undercovered_ground_km2"] > 0
    assert a["overcovered_ground_km2"] > 0
    assert abs(a["symmetric_difference_ground_km2"]
               - a["undercovered_ground_km2"]
               - a["overcovered_ground_km2"]) < 1e-9


def test_audit_multi_admin_union_never_double_counts():
    # Two border admins overlapping in the middle of the hex: union first,
    # so the overlap band is counted once.
    b = HEX.bounds
    left = shapely.box(b[0] - 1e4, b[1] - 1e4,
                       (b[0] + b[2]) / 2 + 1000, b[3] + 1e4)
    right = shapely.box((b[0] + b[2]) / 2 - 1000, b[1] - 1e4,
                        b[2] + 1e4, b[3] + 1e4)
    a = _audit(HEX, [left, right])
    assert a["coverage_class"] == "MATCHED"
    assert abs(a["admin0_union_ground_km2"]
               - a["coast_land_ground_km2"]) < 0.01
    assert a["admin0_to_coast_land_area_ratio"] <= 1.000001


def test_audit_uses_geodesic_not_projected_area():
    # At 60N the Mercator scale factor is ~2, so projected area is ~4x
    # ground area. A projected-area implementation would report ~4x.
    x, y = to_mercator(10.0, 60.0)
    hex60 = shapely.Point(x, y).buffer(3000.0, quad_segs=32)
    a = bidirectional_hex_audit(hex60, hex60,
                                np.array([hex60], dtype=object),
                                TOL_ABS, TOL_REL)
    projected_km2 = shapely.area(hex60) / 1e6  # ~28.3
    assert a["coast_land_ground_km2"] < projected_km2 * 0.5
    assert a["coast_land_ground_km2"] > projected_km2 * 0.15


def test_audit_conservation_identities():
    cx, cy = HEX.centroid.x, HEX.centroid.y
    coast = shapely.union_all([
        shapely.box(cx - 2600, cy - 2200, cx + 900, cy + 1400),
        shapely.Point(cx + 1800, cy - 900).buffer(700.0, quad_segs=16)])
    admin = shapely.union_all([
        shapely.box(cx - 1200, cy - 2900, cx + 2400, cy + 2500),
        shapely.Point(cx - 2000, cy + 1800).buffer(500.0, quad_segs=16)])
    a = _audit(coast, [admin])
    assert abs(a["coast_land_ground_km2"] - a["matched_ground_km2"]
               - a["undercovered_ground_km2"]) <= 0.001
    assert abs(a["admin0_union_ground_km2"] - a["matched_ground_km2"]
               - a["overcovered_ground_km2"]) <= 0.001
    assert 0.0 <= a["land_coverage_fraction"] <= 1.0
    for k in ("coast_land_ground_km2", "admin0_union_ground_km2",
              "matched_ground_km2", "undercovered_ground_km2",
              "overcovered_ground_km2"):
        assert a[k] >= 0.0


def test_audit_deprecated_alias_matches_new_ratio():
    # Old formula: sum(per-admin hex intersections) / (hex_ground * lf).
    # On a non-overlapping admin set the two must agree closely.
    from mapgen.islands import ground_area_perimeter

    cx, cy = HEX.centroid.x, HEX.centroid.y
    admin = shapely.box(cx - 2500, cy - 2500, cx + 2500, cy + 2500)
    a = _audit(HEX, [admin])
    hex_ground, _ = ground_area_perimeter(HEX)
    inter_ground, _ = ground_area_perimeter(shapely.intersection(HEX, admin))
    old_ratio = inter_ground / (hex_ground * 1.0)
    assert abs(old_ratio - a["admin0_to_coast_land_area_ratio"]) < 0.02


def test_audit_dateline_hex_never_sees_world_width_mismatch():
    # Hex just west of the seam; the admin polygon is stored (original
    # frame) as parts on BOTH sides. Pure intersection math: the far part
    # simply does not intersect — no 40,000 km artifact in any area.
    x_w, y = to_mercator(-179.95, -16.8)
    x_e, _ = to_mercator(179.90, -16.8)
    hex_w = shapely.Point(x_w, y).buffer(3000.0, quad_segs=16)
    admin_parts = shapely.union_all([
        hex_w.buffer(500.0),                       # local part, west side
        shapely.Point(x_e, y).buffer(50_000.0)])   # far part, east side
    a = bidirectional_hex_audit(hex_w, hex_w,
                                np.array([admin_parts], dtype=object),
                                TOL_ABS, TOL_REL)
    assert a["coverage_class"] == "MATCHED"
    hex_ground = a["coast_land_ground_km2"]
    assert a["symmetric_difference_ground_km2"] < hex_ground * 0.01


def test_audit_does_not_mutate_membership_inputs():
    reg = _region(terrestrial_qr=[(1, 1), (2, 2)])
    b = shapely.bounds(reg["polys"])
    admin_geom = shapely.box(b[:, 0].min() - 1e4, b[:, 1].min() - 1e4,
                             b[:, 2].max() + 1e4, b[:, 3].max() + 1e4)
    admin = pd.DataFrame({"reference_admin0_id": ["adm0_X"],
                          "source_feature_id": [1],
                          "geometry": [admin_geom]})
    before, _ = hex_admin_membership(reg, admin, "ADMIN0",
                                     np.array([], dtype=object), "t")
    wkb_before = shapely.to_wkb(admin_geom)
    for poly in reg["polys"]:
        bidirectional_hex_audit(poly, admin_geom,
                                np.array([admin_geom], dtype=object),
                                TOL_ABS, TOL_REL)
    after, _ = hex_admin_membership(reg, admin, "ADMIN0",
                                    np.array([], dtype=object), "t")
    assert shapely.to_wkb(admin["geometry"].iloc[0]) == wkb_before
    ka = pd.DataFrame(before).drop(columns=["run_id"])
    kb = pd.DataFrame(after).drop(columns=["run_id"])
    assert ka.equals(kb)  # audit changed nothing about membership/dominant


def test_repair_geometries_audits_and_fixes():
    import geopandas as gpd

    bowtie = shapely.Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])
    gdf = gpd.GeoDataFrame({"geometry": [bowtie,
                                         shapely.box(5, 5, 6, 6)]},
                           crs="EPSG:3857")
    fixed, audit = repair_geometries(gdf, "syn")
    assert audit["invalid_count"] == 1
    assert len(audit["repairs"]) == 1
    assert audit["repairs"][0]["method"] == "shapely.make_valid"
    assert shapely.is_valid(fixed.geometry.values).all()
    # Untouched valid geometry stays identical.
    assert fixed.geometry.values[1].equals(shapely.box(5, 5, 6, 6))
