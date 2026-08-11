import math

import numpy as np
import pandas as pd
import pytest
import shapely

from mapgen.hex_grid import HexGrid
from mapgen.islands import (choose_primary_hex, cluster_lost_components,
                            component_hex_stats, component_id,
                            decide_preservation_units, extract_components,
                            ground_area_perimeter, ground_distance_m,
                            group_metrics)
from mapgen.islands_pipeline import (harden_geography_semantics,
                                     hex_island_convenience,
                                     process_island_region)
from mapgen.projection import to_mercator

GRID = HexGrid(flat_to_flat=6000.0)
CLIP = (-80000.0, -80000.0, 80000.0, 80000.0)
ICFG = {"minimum_auto_preserve_area_km2": 0.5,
        "island_group_max_distance_km": 10,
        "island_group_max_diameter_km": 20,
        "minimum_significant_component_area_km2": 0.05,
        "minimum_largest_component_share": 0.20,
        "atoll_candidate_max_land_hull_ratio": 0.45,
        "force_preserve_ids": [], "force_ignore_ids": []}


def _hexes():
    q, r = GRID.hexes_covering_bbox(-60000, -60000, 60000, 60000)
    ids = GRID.hex_ids(q, r)
    polys = GRID.polygons(q, r)
    centres = np.stack(GRID.axial_to_xy(q, r), axis=1)
    return q, r, ids, polys, centres


def _island(cx, cy, radius_m):
    return shapely.Point(cx, cy).buffer(radius_m, quad_segs=16)


def _region(land_parts, terrestrial_from_land=True):
    q, r, ids, polys, centres = _hexes()
    land = shapely.union_all(land_parts)
    if terrestrial_from_land:
        inter = shapely.area(shapely.intersection(polys, land))
        lf = inter / GRID.area
    else:
        lf = np.zeros(len(ids))
    is_terr = lf >= 0.5
    wt = np.where(is_terr, "NONE", "OCEAN").astype(object)
    reg = process_island_region("test", land, CLIP, polys, ids, centres,
                                is_terr, lf, wt, ICFG, "t")
    return reg, ids, polys, wt


# ---------------------------------------------------------------------------
# Ground metric engine
# ---------------------------------------------------------------------------
def _ground_circle(lat_deg, radius_ground_m, lon_deg=0.0, dx_ground_m=0.0):
    scale = 1.0 / math.cos(math.radians(lat_deg))
    x, y = (float(v) for v in to_mercator(lon_deg, lat_deg))
    return shapely.Point(x + dx_ground_m * scale, y).buffer(
        radius_ground_m * scale, quad_segs=32)


def test_geodesic_area_latitude_invariance():
    areas = []
    for lat in (0.0, 35.0, 60.0, 75.0):
        g = _ground_circle(lat, 600.0)
        a, _ = ground_area_perimeter(g)
        areas.append(a)
    ref = areas[0]
    assert all(abs(a - ref) / ref < 0.02 for a in areas)
    # Projected area explodes with latitude; ground area must not.
    proj75 = float(shapely.area(_ground_circle(75.0, 600.0))) / 1e6
    assert proj75 / areas[-1] > 10.0


def test_ground_distance_latitude_invariance():
    for lat in (0.0, 35.0, 60.0, 75.0):
        a = _ground_circle(lat, 600.0)
        b = _ground_circle(lat, 600.0, dx_ground_m=9200.0)
        d = ground_distance_m(a, b)
        assert abs(d - 8000.0) < 200.0   # 9200 - 2*600 = 8000 m ground gap


def test_projected_area_not_used_for_threshold():
    # At 60N a 0.3 km2 GROUND islet has ~1.2 km2 projected area 窶・over the
    # 0.5 threshold in projected terms, under it in ground terms. It must be
    # EXCLUDED (ground authority).
    g = _ground_circle(60.0, 309.0)   # ~0.30 km2 ground
    a_ground, _ = ground_area_perimeter(g)
    a_proj = float(shapely.area(g)) / 1e6
    assert a_ground < 0.5 < a_proj
    comp = {"island_component_id": "c1", "geometry": g,
            "ground_area_km2": a_ground, "projected_area_km2": a_proj,
            "ground_perimeter_km": 1.9, "centroid_x": g.centroid.x,
            "centroid_y": g.centroid.y}
    gm = group_metrics([comp])
    units, status = decide_preservation_units(gm, ICFG, set(), set())
    assert status == "BELOW_MIN_AREA"
    assert units == []


def test_projected_distance_not_used_for_clustering():
    # Two islets 8 km GROUND apart at 60N are ~16 km apart in projected
    # metres 窶・beyond the 10 km threshold if it were misread as projected.
    lat = 60.0
    a = _ground_circle(lat, 600.0)
    b = _ground_circle(lat, 600.0, dx_ground_m=9200.0)
    lost = []
    for i, g in enumerate((a, b)):
        lost.append({"island_component_id": f"c{i}", "geometry": g,
                     "ground_area_km2": 1.13, "projected_area_km2": 4.5,
                     "ground_perimeter_km": 3.8,
                     "centroid_x": g.centroid.x, "centroid_y": g.centroid.y})
    lost.sort(key=lambda c: c["island_component_id"])
    groups = cluster_lost_components(lost, 10000.0, 100000.0)
    assert len(groups) == 1   # ground 8 km <= 10 km -> one group


# ---------------------------------------------------------------------------
# Preservation semantics (synthetic patches near lat 0 -> ground ~ projected)
# ---------------------------------------------------------------------------
def test_subhex_island_does_not_alter_water_type():
    reg, ids, polys, wt = _region([_island(1000, 500, 1100)])
    assert all(w == "OCEAN" for w in wt)
    assert len(reg["islands"]) == 1
    isl = reg["islands"][0]
    assert isl["surrounding_water_type"] == "OCEAN"
    assert isl["preservation_reason"] == "SINGLE_COMPONENT_AREA"


def test_lost_island_creates_overlay_and_membership():
    reg, ids, polys, wt = _region([_island(0, 0, 1100)])
    assert len(reg["islands"]) == 1
    isl = reg["islands"][0]
    assert isl["covered_hex_count"] >= 1
    assert isl["primary_hex_id"] in ids
    assert isl["land_area_ground_km2"] > 0
    mem = pd.DataFrame(reg["membership"])
    assert (mem["overlay_unit_id"] == isl["overlay_unit_id"]).all()
    assert mem["is_primary"].sum() == 1


def test_represented_island_creates_no_duplicate_overlay():
    reg, ids, polys, wt = _region([_island(0, 0, 8000)])
    comp = reg["components"][0]
    assert comp["represented_by_terrestrial_hex"]
    assert not comp["is_subhex_lost"]
    assert len(reg["islands"]) == 0


def test_archipelago_with_dominant_component_preserved():
    # Wake-like: one dominant island + small satellites: total 0.6 km2,
    # largest share ~0.65 -> preserved as ONE multi-component unit.
    parts = [_island(0, 0, 355), _island(1500, 0, 200),
             _island(-1500, 0, 160)]
    reg, *_ = _region(parts)
    assert len(reg["groups"]) == 1
    g = reg["groups"][0]
    assert g["group_status"] == "PRESERVED"
    assert len(reg["islands"]) == 1
    u = reg["islands"][0]
    assert u["component_count"] == 3
    assert u["preservation_reason"] in ("MULTI_COMPONENT_ARCHIPELAGO",
                                       "DISPERSED_MULTI_COMPONENT_GROUP")
    assert u["largest_component_area_share"] >= 0.2


def test_micro_islet_aggregation_guard():
    # Six equal micro rocks, total over the min area but no significant
    # dominant component -> AGGREGATED_MICRO_ISLETS, no unit.
    parts = [_island(i * 2500, 0, 205) for i in range(6)]
    reg, *_ = _region(parts)
    assert len(reg["groups"]) == 1
    g = reg["groups"][0]
    assert g["total_land_area_ground_km2"] >= 0.5
    assert g["group_status"] == "AGGREGATED_MICRO_ISLETS"
    assert len(reg["islands"]) == 0


def test_split_into_multiple_units():
    # One coherent core (>= min area) drowned in micro rocks that kill the
    # share guard: the core survives as its own unit, the rest is dropped.
    parts = [_island(0, 0, 480)]                      # ~0.72 km2 core
    parts += [_island(2500 + (i % 12) * 800, 2500 + (i // 12) * 1700, 210)
              for i in range(24)]
    reg, *_ = _region(parts)
    assert len(reg["groups"]) == 1
    g = reg["groups"][0]
    assert g["largest_component_area_share"] < 0.20
    assert g["group_status"] == "SPLIT_INTO_MULTIPLE_UNITS"
    assert len(reg["islands"]) == 1
    u = reg["islands"][0]
    assert u["component_count"] == 1
    assert u["preservation_reason"] == "SINGLE_COMPONENT_AREA"
    # Conservation: preserved + dropped == lost total.
    dropped = g["total_land_area_ground_km2"] - g["preserved_ground_km2"]
    assert dropped > 0
    assert abs(g["preserved_ground_km2"] - u["land_area_ground_km2"]) < 1e-3


def test_below_threshold_rock_is_excluded():
    reg, *_ = _region([_island(0, 0, 200)])
    assert reg["groups"][0]["group_status"] == "BELOW_MIN_AREA"
    assert len(reg["islands"]) == 0


def test_far_components_do_not_false_merge():
    parts = [_island(-40000, -40000, 900), _island(40000, 40000, 900)]
    reg, *_ = _region(parts)
    assert len(reg["groups"]) == 2


def test_force_preserve_and_ignore_paths():
    g = {"island_group_id": "isl_g_x", "total_land_area_ground_km2": 0.1,
         "component_count": 1, "components": [
             {"island_component_id": "c", "ground_area_km2": 0.1}],
         "largest_component_ground_area_km2": 0.1,
         "largest_component_area_share": 1.0, "land_hull_ratio": 1.0}
    units, status = decide_preservation_units(g, ICFG, {"isl_g_x"}, set())
    assert status == "PRESERVED" and units[0]["reason"] == "FORCE_PRESERVE"
    units2, status2 = decide_preservation_units(g, ICFG, set(), {"isl_g_x"})
    assert status2 == "FORCE_IGNORE" and units2 == []


def test_group_and_component_anchors_separate():
    parts = [_island(0, 0, 480)]
    parts += [_island(2500 + (i % 12) * 800, 2500 + (i // 12) * 1700, 210)
              for i in range(24)]
    reg, ids, *_ = _region(parts)
    g = reg["groups"][0]
    u = reg["islands"][0]
    assert g["group_primary_hex_id"] in ids
    assert u["primary_hex_id"] in ids
    assert u["group_primary_hex_id"] == g["group_primary_hex_id"]
    # Component-level anchors exist independently.
    for c in reg["components"]:
        if c["is_subhex_lost"]:
            assert c["primary_hex_id"] in ids


def test_primary_hex_selection_deterministic():
    centres = np.array([[0.0, 0.0], [6000.0, 0.0], [12000.0, 0.0]])
    ids = ["hA", "hB", "hC"]
    areas = {0: 100.0, 1: 100.0, 2: 50.0}
    assert choose_primary_hex(areas, (5500.0, 0.0), centres, ids) == "hB"
    areas2 = {0: 500.0, 1: 100.0}
    assert choose_primary_hex(areas2, (5500.0, 0.0), centres, ids) == "hA"


def test_semantics_and_deprecated_alias():
    geo = pd.DataFrame({
        "is_land": [True, False, True],
        "water_type": ["NONE", "OCEAN", "LAKE"],
    })
    out = harden_geography_semantics(geo)
    assert (out["is_land"] == out["coast_land_mask"]).all()
    assert out["is_water_hex"].tolist() == [False, True, True]
    assert out["is_terrestrial_hex"].tolist() == [True, False, False]
    assert out.loc[2, "coast_land_mask"] and not out.loc[2, "is_terrestrial_hex"]


def test_hex_island_convenience_fields():
    geo = pd.DataFrame({"hex_id": ["h1", "h2"],
                        "is_land": [False, False],
                        "water_type": ["OCEAN", "OCEAN"]})
    geo = harden_geography_semantics(geo)
    mem = pd.DataFrame([
        {"region": "kanto", "overlay_unit_id": "isl_a", "hex_id": "h1",
         "intersection_area_km2": 1.5, "is_primary": True},
        {"region": "kanto", "overlay_unit_id": "isl_b", "hex_id": "h1",
         "intersection_area_km2": 0.4, "is_primary": True},
    ])
    isl = pd.DataFrame([
        {"overlay_unit_id": "isl_a", "land_area_ground_km2": 1.6,
         "land_area_projected_km2": 2.0},
        {"overlay_unit_id": "isl_b", "land_area_ground_km2": 0.48,
         "land_area_projected_km2": 0.6},
    ])
    out = hex_island_convenience(geo, mem, isl)
    assert out.loc[0, "has_island_overlay"]
    assert out.loc[0, "island_overlay_count"] == 2
    assert out.loc[0, "primary_overlay_unit_id"] == "isl_a"
    # Ground scaling: 1.5*(1.6/2.0) + 0.4*(0.48/0.6) = 1.2 + 0.32
    assert out.loc[0, "island_land_area_ground_km2_total"] == pytest.approx(1.52)
    assert not out.loc[1, "has_island_overlay"]
    assert out["water_type"].tolist() == ["OCEAN", "OCEAN"]


def test_island_and_ground_metric_determinism():
    parts = [_island(-4000, 0, 500), _island(0, 0, 500)]
    reg1, *_ = _region(parts)
    reg2, *_ = _region(parts)
    assert [c["island_component_id"] for c in reg1["components"]] == \
           [c["island_component_id"] for c in reg2["components"]]
    assert [g["island_group_id"] for g in reg1["groups"]] == \
           [g["island_group_id"] for g in reg2["groups"]]
    assert [i["overlay_unit_id"] for i in reg1["islands"]] == \
           [i["overlay_unit_id"] for i in reg2["islands"]]
    assert [i["land_area_ground_km2"] for i in reg1["islands"]] == \
           [i["land_area_ground_km2"] for i in reg2["islands"]]
    assert component_id(parts[0]) != component_id(parts[1])


def test_clip_boundary_fragment_is_not_lost_island():
    mainland = shapely.box(-90000, -20000, -70000, 20000)
    reg, *_ = _region([mainland, _island(0, 0, 1100)])
    frags = [c for c in reg["components"] if c["touches_clip_boundary"]]
    assert len(frags) == 1
    assert not frags[0]["is_subhex_lost"]
    assert len(reg["islands"]) == 1




# ---------------------------------------------------------------------------
# MAPGEN-006: dateline hardening + overlay/gameplay identity separation
# ---------------------------------------------------------------------------
def _seam_comp(lon, lat, r_ground=600.0):
    from mapgen.islands import ground_area_perimeter
    scale = 1.0 / math.cos(math.radians(lat))
    x, y = (float(v) for v in to_mercator(lon, lat))
    g = shapely.Point(x, y).buffer(r_ground * scale, quad_segs=16)
    ga, gp = ground_area_perimeter(g)
    return {"island_component_id": component_id(g), "geometry": g,
            "ground_area_km2": ga, "projected_area_km2":
            float(shapely.area(g)) / 1e6, "ground_perimeter_km": gp,
            "centroid_x": x, "centroid_y": y}


def test_dateline_synthetic_short_distance():
    from mapgen.islands import assign_analysis_frame, ground_distance_m
    a = _seam_comp(179.97, 10.0)
    b = _seam_comp(-179.97, 10.0)
    comps = sorted([a, b], key=lambda c: c["island_component_id"])
    assign_analysis_frame(comps, crosses_dateline=True)
    d = ground_distance_m(comps[0]["ageometry"], comps[1]["ageometry"])
    # 0.06 deg of longitude at lat 10 ~ 6.6 km ground, minus 2 radii.
    assert d < 7000.0
    # Raw projected frame sees them a world apart.
    assert float(shapely.distance(a["geometry"], b["geometry"])) > 3.9e7


def test_dateline_clustering_and_non_clustering():
    from mapgen.islands import assign_analysis_frame
    close = sorted([_seam_comp(179.97, 10.0), _seam_comp(-179.97, 10.0)],
                   key=lambda c: c["island_component_id"])
    assign_analysis_frame(close, crosses_dateline=True)
    assert len(cluster_lost_components(close, 10000.0, 1e9)) == 1
    far = sorted([_seam_comp(179.60, 10.0), _seam_comp(-179.60, 10.0)],
                 key=lambda c: c["island_component_id"])
    assign_analysis_frame(far, crosses_dateline=True)
    # 0.8 deg ~ 87 km ground: must NOT cluster at a 10 km threshold.
    assert len(cluster_lost_components(far, 10000.0, 1e9)) == 2


def test_dateline_deterministic_ids():
    from mapgen.islands import assign_analysis_frame
    def _run():
        comps = sorted([_seam_comp(179.97, 10.0), _seam_comp(-179.97, 10.0)],
                       key=lambda c: c["island_component_id"])
        assign_analysis_frame(comps, crosses_dateline=True)
        groups = cluster_lost_components(comps, 10000.0, 1e9)
        return ([c["island_component_id"] for c in comps],
                [group_metrics(g)["island_group_id"] for g in groups])
    assert _run() == _run()
    # Hash comes from the ORIGINAL geometry, not the shifted analysis frame.
    c = _seam_comp(-179.97, 10.0)
    cid_before = c["island_component_id"]
    from mapgen.islands import assign_analysis_frame as aaf
    aaf([c], crosses_dateline=True)
    assert component_id(c["geometry"]) == cid_before


def test_overlay_unit_is_not_gameplay_identity():
    # Multi-component unit: components keep distinct ids, individual anchors
    # and significance flags -- no field claims a single gameplay island.
    parts = [_island(0, 0, 355), _island(1500, 0, 200), _island(-1500, 0, 160)]
    reg, ids, *_ = _region(parts)
    u = reg["islands"][0]
    assert u["overlay_unit_id"].startswith("isl_u_")
    assert u["island_group_id"].startswith("isl_g_")
    assert u["overlay_unit_id"] != u["island_group_id"]
    comps = [c for c in reg["components"] if c.get("overlay_unit_id")]
    assert len({c["island_component_id"] for c in comps}) == 3
    for c in comps:
        assert c["primary_hex_id"] in ids          # per-component anchor
        assert "is_significant_component" in c
        assert c["representation_status"] == "IN_OVERLAY_UNIT"
    assert "gameplay" not in " ".join(u.keys())


def test_atoll_semantics_not_asserted():
    # The geometry-only dispersion label never claims ATOLL.
    parts = [_island(0, 0, 300), _island(3000, 3000, 250),
             _island(-3000, 3000, 250), _island(0, -4000, 250)]
    reg, *_ = _region(parts)
    for u in reg["islands"]:
        assert "ATOLL" not in u["preservation_reason"]
    from mapgen.islands import decide_preservation_units as dpu
    import inspect
    assert "ATOLL" not in inspect.getsource(dpu).replace(
        "atoll_candidate_max_land_hull_ratio", "")


# ---------------------------------------------------------------------------
# MAPGEN-006R: review contract hardening
# ---------------------------------------------------------------------------
def test_dispersed_ratio_rename_with_deprecated_alias():
    # New public name works; old name still accepted as deprecated alias;
    # behaviour identical (0.45 either way).
    parts = [_island(0, 0, 300), _island(3000, 3000, 250),
             _island(-3000, 3000, 250), _island(0, -4000, 250)]
    land = shapely.union_all(parts)
    q, r, ids, polys, centres = _hexes()
    lf = shapely.area(shapely.intersection(polys, land)) / GRID.area
    is_terr = lf >= 0.5
    wt = np.where(is_terr, "NONE", "OCEAN").astype(object)
    new_cfg = dict(ICFG)
    new_cfg.pop("atoll_candidate_max_land_hull_ratio", None)
    new_cfg["dispersed_group_max_land_hull_ratio"] = 0.45
    old_cfg = dict(ICFG)
    old_cfg.pop("dispersed_group_max_land_hull_ratio", None)
    old_cfg["atoll_candidate_max_land_hull_ratio"] = 0.45
    r1 = process_island_region("t", land, CLIP, polys, ids, centres,
                               is_terr, lf, wt, new_cfg, "x")
    r2 = process_island_region("t", land, CLIP, polys, ids, centres,
                               is_terr, lf, wt, old_cfg, "x")
    assert [u["preservation_reason"] for u in r1["islands"]] == \
           [u["preservation_reason"] for u in r2["islands"]]
    assert [u["overlay_unit_id"] for u in r1["islands"]] == \
           [u["overlay_unit_id"] for u in r2["islands"]]


def test_edge_cache_produces_identical_clusters():
    from mapgen.islands import candidate_edges
    parts = [_island(i * 3000, (i % 3) * 2000, 400) for i in range(8)]
    parts += [_island(50000, -50000, 600)]
    reg, *_ = _region(parts)
    lost = [c for c in reg["components"] if c["is_subhex_lost"]]
    edges = candidate_edges(lost, 10000.0)
    for dist in (3000.0, 5000.0, 10000.0):
        direct = cluster_lost_components(lost, dist, 20000.0)
        cached = cluster_lost_components(lost, dist, 20000.0,
                                         precomputed_edges=edges)
        assert [[c["island_component_id"] for c in g] for g in direct] == \
               [[c["island_component_id"] for c in g] for g in cached]


def test_display_wrap_helper_contiguous():
    # Display-only wrap: west-side polygons shift +world-width so a dateline
    # region renders as a normal-aspect neighbourhood.
    from mapgen.islands import WORLD_WIDTH_M
    east = _seam_comp(179.97, -16.8)["geometry"]
    west = _seam_comp(-179.97, -16.8)["geometry"]

    def wrap(geom):
        return shapely.transform(
            geom, lambda xy: np.where(
                np.column_stack([xy[:, 0] < 0, np.zeros(len(xy), bool)]),
                xy + np.array([WORLD_WIDTH_M, 0.0]), xy))

    we = wrap(east)
    ww = wrap(west)
    assert shapely.equals_exact(we, east, tolerance=0.001)  # east unchanged
    gap = float(shapely.distance(we, ww))
    assert gap < 10000.0            # contiguous in the display frame
    span = max(shapely.bounds(we)[2], shapely.bounds(ww)[2]) - \
        min(shapely.bounds(we)[0], shapely.bounds(ww)[0])
    assert span < 50000.0           # region-sized, not world-sized


def test_components_review_frame_invariants():
    parts = [_island(0, 0, 480)]
    parts += [_island(2500 + (i % 12) * 800, 2500 + (i // 12) * 1700, 210)
              for i in range(24)]
    reg, ids, *_ = _region(parts)
    comps = reg["components"]
    cids = [c["island_component_id"] for c in comps]
    assert len(cids) == len(set(cids))                      # unique
    for c in comps:
        assert c["primary_hex_id"] in ids
        assert "representation_status" in c or c["represented_by_terrestrial_hex"] is not None
    in_unit = [c for c in comps if c.get("overlay_unit_id")]
    assert all(c["representation_status"] == "IN_OVERLAY_UNIT"
               for c in in_unit)
    dropped = [c for c in comps
               if c.get("representation_status") == "DROPPED_MICRO"]
    assert len(dropped) > 0          # split case leaves auditable dropped rest
