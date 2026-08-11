import numpy as np
import pandas as pd
import pytest
import shapely

from mapgen.hex_edges import build_edge_graph
from mapgen.hex_grid import HexGrid
from mapgen.hydro_pipeline import (_hex_sets_touch, _qr_maps,
                                   build_game_edges, coastline_outlier_audit,
                                   confluence_audit, snapping_summary,
                                   water_hex_quality)
from mapgen.river_snap import RiverSnapper
from mapgen.rivers import Branch, classify_discharge

GRID = HexGrid(flat_to_flat=6000.0)
THRESHOLDS = {"MINOR": 10, "MEDIUM": 50, "MAJOR": 300, "GREAT": 8000}
SNAP_CFG = {"corridor_m": 15000, "distance_cost_scale_m": 2000,
            "water_edge_penalty": 25.0, "direction_weight": 1.2,
            "same_turn_penalty": 0.6}
QCFG = {"min_length_for_ratio_km": 30, "length_ratio_warn": 1.55,
        "length_ratio_fail": 1.65, "p95_offset_max_m": 3000,
        "coast_outlier_top_n": 100, "coast_outlier_audit_m": 10000}


def _patch(x0=-60000, y0=-30000, x1=60000, y1=30000):
    q, r = GRID.hexes_covering_bbox(x0, y0, x1, y1)
    ids = GRID.hex_ids(q, r)
    graph = build_edge_graph(GRID, q, r, ids)
    return q, r, ids, graph


def _branch(line, discharge=100.0, branch_id="br_1", next_down=0,
            reach_ids=None, name=None, representation="EDGE_RIVER"):
    b = Branch(branch_id=branch_id, reach_ids=reach_ids or [1], line=line,
               discharge_cms=discharge, strahler=4,
               river_class=classify_discharge(discharge, THRESHOLDS),
               main_riv=1, next_down_reach=next_down,
               source_length_m=line.length, width_est_m=50.0)
    b.name = name
    b.representation = representation
    return b


def _reg(q, r, ids, graph, branches, snap_results, river_hex_ids=None):
    return {"name": "test", "q": q, "r": r, "hex_ids": ids, "graph": graph,
            "polys": GRID.polygons(q, r), "grid": GRID,
            "branches": branches, "snap_results": snap_results,
            "river_hex_ids": river_hex_ids or {}}


# ---------------------------------------------------------------------------
def test_straight_river_has_no_extra_zigzag():
    q, r, ids, graph = _patch()
    snapper = RiverSnapper(graph, {h: "NONE" for h in ids}, SNAP_CFG)
    line = shapely.LineString([(-50000, 1000), (50000, 1000)])
    res = snapper.snap_branch(_branch(line))
    # Ideal hex-edge zigzag along a straight line: ratio = 2/sqrt(3) ~ 1.155.
    ratio = res["snapped_length_m"] / line.length
    assert ratio <= 1.25
    # Perfect alternation: no same-sign turn pairs.
    assert res["sharp_turn_count"] <= 1
    assert res["direction_reversal_count"] == 0


def test_curved_river_is_not_straightened():
    q, r, ids, graph = _patch()
    snapper = RiverSnapper(graph, {h: "NONE" for h in ids}, SNAP_CFG)
    # A wide arc: cutting the curve would create large offsets.
    t = np.linspace(np.pi, 0, 60)
    xs = 40000 * np.cos(t)
    ys = -22000 + 40000 * np.sin(t) * 0.9
    line = shapely.LineString(np.column_stack([xs, ys]))
    res = snapper.snap_branch(_branch(line))
    assert res is not None
    # The path follows the meander: every edge stays close to the arc.
    assert res["offset_max_m"] <= GRID.flat_to_flat
    assert res["offset_p95_m"] <= GRID.flat_to_flat * 0.75


def test_confluence_audit_edge_tributary():
    q, r, ids, graph = _patch()
    snapper = RiverSnapper(graph, {h: "NONE" for h in ids}, SNAP_CFG)
    main = _branch(shapely.LineString([(-50000, 0), (50000, 0)]),
                   discharge=500.0, branch_id="br_main", reach_ids=[10],
                   name="Main")
    res_main = snapper.snap_branch(main)
    trib = _branch(shapely.LineString([(-10000, 25000), (0, 500)]),
                   discharge=60.0, branch_id="br_trib", next_down=10,
                   reach_ids=[20])
    res_trib = snapper.snap_branch(trib)
    reg = _reg(q, r, ids, graph, [main, trib], [res_main, res_trib])
    audit = confluence_audit(reg, "t")
    assert len(audit) == 1
    row = audit.iloc[0]
    assert row["preserved"]
    assert row["source_downstream_branch_id"] == "br_main"
    assert row["distance_m"] < 2 * GRID.flat_to_flat


def test_water_hex_tributary_preserved_by_corridor_adjacency():
    q, r, ids, graph = _patch()
    qr_by = {(int(a), int(b)): h for a, b, h in zip(q, r, ids)}
    q0, r0 = int(q[0]), int(r[0])
    # Receiver corridor and an adjacent tributary corridor.
    main = _branch(shapely.LineString([(-30000, 0), (30000, 0)]),
                   discharge=200000, branch_id="br_m", reach_ids=[10],
                   name="Big", representation="WATER_HEX_RIVER")
    trib = _branch(shapely.LineString([(-10000, 20000), (-8000, 4000)]),
                   discharge=9000, branch_id="br_t", next_down=10,
                   reach_ids=[20], representation="WATER_HEX_RIVER")
    centre = qr_by.get((0, 0))
    nbr = qr_by.get((1, 0))
    far = qr_by.get((5, 3))
    reg = _reg(q, r, ids, graph, [main, trib], [],
               river_hex_ids={"br_m": {centre}, "br_t": {nbr}})
    audit = confluence_audit(reg, "t")
    assert audit.iloc[0]["preserved"]          # adjacent corridors touch
    reg2 = _reg(q, r, ids, graph, [main, trib], [],
                river_hex_ids={"br_m": {centre}, "br_t": {far}})
    audit2 = confluence_audit(reg2, "t")
    assert not audit2.iloc[0]["preserved"]     # distant corridor: LOST


def test_topology_pass_strict_and_exception():
    q, r, ids, graph = _patch()
    main = _branch(shapely.LineString([(-50000, 0), (50000, 0)]),
                   discharge=500.0, branch_id="br_main", reach_ids=[10],
                   name="Main")
    snapper = RiverSnapper(graph, {h: "NONE" for h in ids}, SNAP_CFG)
    res_main = snapper.snap_branch(main)
    reg = _reg(q, r, ids, graph, [main], [res_main])
    audit = pd.DataFrame([{
        "source_downstream_branch_id": "br_main",
        "source_upstream_branch_ids": "br_x",
        "preserved": False, "exception_reason": "",
    }, {
        "source_downstream_branch_id": "br_main",
        "source_upstream_branch_ids": "br_y",
        "preserved": True, "exception_reason": "",
    }])
    rows = snapping_summary(reg, [{"name": "Main",
                                   "expected_min_class": "MEDIUM"}],
                            "t", audit, QCFG)
    assert rows[0]["source_confluence_count"] == 2
    assert rows[0]["preserved_confluence_count"] == 1
    assert rows[0]["topology_pass"] is False   # 1/2 must NEVER pass silently
    audit.loc[0, "exception_reason"] = "source dataset boundary artefact"
    rows2 = snapping_summary(reg, [{"name": "Main",
                                    "expected_min_class": "MEDIUM"}],
                             "t", audit, QCFG)
    assert rows2[0]["topology_pass"] is True   # explicit exception only


def test_game_edges_canonical_unique_and_no_double_crossing():
    membership = pd.DataFrame([
        # Same river, two branches sharing one edge near a confluence.
        {"region": "t", "edge_id": "e_a_b", "hex_a_id": "a", "hex_b_id": "b",
         "river_id": "riv_1", "source_segment_id": "br_1",
         "river_class": "MAJOR", "discharge_m3_s": 500.0,
         "effective_game_width_m": 160.0, "flow_direction": 90.0,
         "flow_from_node": 1, "flow_to_node": 2, "mouth_extension": False},
        {"region": "t", "edge_id": "e_a_b", "hex_a_id": "a", "hex_b_id": "b",
         "river_id": "riv_1", "source_segment_id": "br_2",
         "river_class": "MEDIUM", "discharge_m3_s": 80.0,
         "effective_game_width_m": 64.0, "flow_direction": 90.0,
         "flow_from_node": 2, "flow_to_node": 3, "mouth_extension": False},
        # A second river on the same edge.
        {"region": "t", "edge_id": "e_a_b", "hex_a_id": "a", "hex_b_id": "b",
         "river_id": "riv_2", "source_segment_id": "br_9",
         "river_class": "MINOR", "discharge_m3_s": 12.0,
         "effective_game_width_m": 25.0, "flow_direction": 210.0,
         "flow_from_node": 5, "flow_to_node": 2, "mouth_extension": False},
        {"region": "t", "edge_id": "e_b_c", "hex_a_id": "b", "hex_b_id": "c",
         "river_id": "riv_1", "source_segment_id": "br_1",
         "river_class": "MAJOR", "discharge_m3_s": 500.0,
         "effective_game_width_m": 160.0, "flow_direction": 90.0,
         "flow_from_node": 2, "flow_to_node": 4, "mouth_extension": False},
    ])
    game = build_game_edges(membership, {}, "t")
    # Canonical: unique edge_id, one crossing row despite 3 memberships.
    assert len(game) == 2
    assert not game.duplicated(["region", "edge_id"]).any()
    row = game[game["edge_id"] == "e_a_b"].iloc[0]
    assert row["river_count"] == 2
    assert row["dominant_river_id"] == "riv_1"
    assert row["dominant_river_class"] == "MAJOR"
    assert row["max_discharge_m3_s"] == 500.0
    assert "riv_2" in row["river_ids"]


def test_water_hex_quality_metrics():
    q, r, ids, graph = _patch()
    line = shapely.LineString([(-30000, 0), (30000, 0)])
    b = _branch(line, discharge=200000, branch_id="br_m", reach_ids=[10],
                name="Big", representation="WATER_HEX_RIVER")
    b.endorheic = 0
    from mapgen.river_snap import water_hex_river_hexes

    b.width_est_m = 5000.0
    hexes = set(water_hex_river_hexes(b, GRID.polygons(q, r), ids, 1.0))
    reg = _reg(q, r, ids, graph, [b], [], river_hex_ids={"br_m": hexes})
    rows = water_hex_quality(reg, confluence_audit(reg, "t"), "t")
    assert len(rows) == 1
    m = rows[0]
    assert m["river_hex_connected_components"] == 1
    assert m["source_line_inside_corridor_fraction"] > 0.95
    assert m["source_line_distance_to_corridor_p95_m"] == 0.0
    assert m["downstream_connection_pass"]


def test_coastline_outlier_classification():
    q, r, ids, graph = _patch()
    n = len(ids)
    cls = {
        "land_class": np.array(["water"] * n, dtype=object),
        "land_fraction": np.zeros(n),
        "is_coastal": np.zeros(n, bool),
    }
    # Make western hexes land.
    cx, _ = GRID.axial_to_xy(q, r)
    cx = np.atleast_1d(cx)
    cls["land_class"][cx < -20000] = "land"
    cls["land_fraction"][cx < -20000] = 1.0
    reg = {"name": "test", "grid": GRID, "q": q, "r": r, "hex_ids": ids,
           "cls": cls}
    # A tiny island far out in the water side + a normal coastal sample.
    island = shapely.Point(30000, 0).buffer(800)
    mainland = shapely.box(-200000, -50000, -20000, 50000)
    osm_land = shapely.union_all([island, mainland])
    samples = np.array([[30000.0, 800.0],     # on the island coast
                        [-20500.0, 0.0]])     # near the real coast
    errors = np.array([25000.0, 900.0])
    out = coastline_outlier_audit(samples, errors, reg, osm_land, "t",
                                  top_n=10, audit_threshold_m=10000)
    assert out.iloc[0]["cause_category"] == "SMALL_ISLAND_LOST"
    assert out.iloc[0]["error_m"] == 25000.0
    assert out.iloc[1]["cause_category"] == "HEX_MAJORITY_QUANTISATION"


def test_surface_enum_is_normal_based():
    from mapgen.terrain_layers import SURFACE_CLASSES

    assert [n for n, _ in SURFACE_CLASSES] == [
        "NONE", "NORMAL", "TUNDRA", "DESERT", "WETLAND", "PERMANENT_SNOW_ICE"]
