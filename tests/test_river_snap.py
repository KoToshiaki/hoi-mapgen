import numpy as np
import pytest
import shapely

from mapgen.hex_edges import build_edge_graph
from mapgen.hex_grid import HexGrid
from mapgen.river_snap import RiverSnapper, water_hex_river_hexes
from mapgen.rivers import Branch, classify_discharge, decompose_branches

GRID = HexGrid(flat_to_flat=6000.0)
THRESHOLDS = {"MINOR": 10, "MEDIUM": 50, "MAJOR": 300, "GREAT": 8000}
SNAP_CFG = {"corridor_m": 15000, "distance_cost_scale_m": 2000,
            "water_edge_penalty": 25.0}


def _patch(x0=-60000, y0=-30000, x1=60000, y1=30000):
    q, r = GRID.hexes_covering_bbox(x0, y0, x1, y1)
    ids = GRID.hex_ids(q, r)
    graph = build_edge_graph(GRID, q, r, ids)
    return q, r, ids, graph


def _branch(line, discharge=100.0, branch_id="br_1", next_down=0):
    return Branch(branch_id=branch_id, reach_ids=[1], line=line,
                  discharge_cms=discharge, strahler=4,
                  river_class=classify_discharge(discharge, THRESHOLDS),
                  main_riv=1, next_down_reach=next_down,
                  source_length_m=line.length, width_est_m=50.0)


def test_edge_graph_structure():
    q, r, ids, graph = _patch()
    # Every edge connects two nodes and belongs to 1-2 hexes.
    assert len(graph.edges) > 0
    for e in graph.edges[:200]:
        assert e["hex_a"] is not None
        assert e["edge_id"].startswith("e_")
    # Interior edge count consistency: each hex has 6 edges, shared edges
    # counted once: E = (6*H + border) / 2 -> E < 6*H.
    assert len(graph.edges) < 6 * len(q)
    # Edge lengths all equal the hex side.
    lengths = [graph.edge_length(i) for i in range(0, len(graph.edges), 37)]
    assert np.allclose(lengths, GRID.side, rtol=1e-9)


def test_straight_river_snaps_continuously():
    q, r, ids, graph = _patch()
    snapper = RiverSnapper(graph, {h: "NONE" for h in ids}, SNAP_CFG)
    line = shapely.LineString([(-50000, 1000), (50000, 1000)])
    res = snapper.snap_branch(_branch(line))
    assert res is not None
    path = res["node_path"]
    # Continuous: consecutive nodes are adjacent (an edge exists).
    for a, b in zip(path, path[1:]):
        assert (min(a, b), max(a, b)) in graph.edge_by_nodes
    # Path stays close to the source line (within ~ one hex).
    assert res["offset_max_m"] <= GRID.flat_to_flat
    # Snapped length is not absurdly inflated vs the straight source.
    assert res["snapped_length_m"] / line.length < 1.35
    # Flow direction follows the source (west -> east overall).
    x_start = graph.node_xy[path[0]][0]
    x_end = graph.node_xy[path[-1]][0]
    assert x_end > x_start


def test_tributary_connects_to_mainstem():
    q, r, ids, graph = _patch()
    snapper = RiverSnapper(graph, {h: "NONE" for h in ids}, SNAP_CFG)
    main = _branch(shapely.LineString([(-50000, 0), (50000, 0)]),
                   discharge=500.0, branch_id="br_main")
    main.reach_ids = [10]
    res_main = snapper.snap_branch(main)
    assert res_main is not None
    trib = _branch(shapely.LineString([(-10000, 25000), (0, 500)]),
                   discharge=60.0, branch_id="br_trib", next_down=10)
    res_trib = snapper.snap_branch(trib)
    assert res_trib is not None
    assert res_trib["connected_to_receiver"]
    # The tributary's last node lies ON the mainstem path.
    assert res_trib["node_path"][-1] in set(res_main["node_path"])


def test_river_avoids_ocean_interior():
    q, r, ids, graph = _patch()
    cx, _ = GRID.axial_to_xy(q, r)
    cx = np.atleast_1d(cx)
    # Everything east of x=20km is ocean.
    hex_water = {h: ("OCEAN" if x > 20000 else "NONE")
                 for h, x in zip(ids, cx)}
    snapper = RiverSnapper(graph, hex_water, SNAP_CFG)
    # River ends right at the coast.
    line = shapely.LineString([(-50000, 0), (21000, 0)])
    res = snapper.snap_branch(_branch(line))
    assert res is not None
    ocean_interior = 0
    for er in res["edges"]:
        wa = hex_water.get(er["hex_a_id"], "NONE")
        wb = hex_water.get(er["hex_b_id"], "NONE") if er["hex_b_id"] else wa
        if wa == "OCEAN" and wb == "OCEAN":
            ocean_interior += 1
    assert ocean_interior == 0


def test_water_hex_river_marks_hexes():
    q, r, ids, _ = _patch()
    polys = GRID.polygons(q, r)
    b = _branch(shapely.LineString([(-40000, 0), (40000, 0)]),
                discharge=50000.0, branch_id="br_great")
    b.width_est_m = 5000.0
    b.representation = "WATER_HEX_RIVER"
    hexes = water_hex_river_hexes(b, polys, ids, exaggeration=1.0)
    assert len(hexes) >= 13  # a corridor of hexes, not a single line

def test_classify_discharge():
    assert classify_discharge(5, THRESHOLDS) is None
    assert classify_discharge(15, THRESHOLDS) == "MINOR"
    assert classify_discharge(80, THRESHOLDS) == "MEDIUM"
    assert classify_discharge(2000, THRESHOLDS) == "MAJOR"
    assert classify_discharge(200000, THRESHOLDS) == "GREAT"


def test_snapping_deterministic():
    q, r, ids, graph = _patch()
    line = shapely.LineString([(-45000, -8000), (0, 5000), (45000, -3000)])
    paths = []
    for _ in range(2):
        snapper = RiverSnapper(graph, {h: "NONE" for h in ids}, SNAP_CFG)
        res = snapper.snap_branch(_branch(line))
        paths.append(res["node_path"])
    assert paths[0] == paths[1]
