"""Hex edge graph (MAPGEN-003).

Rivers snap to the SHARED EDGES of adjacent hexes, so the hex tiling is
turned into a graph: nodes = hex corners, edges = hex sides. A path through
this graph is a continuous chain of hex edges — the EDGE_RIVER geometry.

Edge identity is deterministic: an edge is keyed by its two corner nodes
(quantised coordinates), and carries the two adjacent hex ids (A/B sorted by
hex_id) plus the geometric direction of the A->B crossing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import shapely

from .hex_grid import HexGrid

_Q = 1000.0  # node coordinate quantisation: 1 mm


def _node_key(x: float, y: float) -> tuple[int, int]:
    return (round(x * _Q), round(y * _Q))


@dataclass
class HexEdgeGraph:
    grid: HexGrid
    nodes: dict[tuple[int, int], int] = field(default_factory=dict)  # key -> node idx
    node_xy: list[tuple[float, float]] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)                  # edge records
    edge_by_nodes: dict[tuple[int, int], int] = field(default_factory=dict)
    adjacency: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    # node idx -> [(neighbour node idx, edge idx)]

    def _node(self, x: float, y: float) -> int:
        key = _node_key(x, y)
        idx = self.nodes.get(key)
        if idx is None:
            idx = len(self.node_xy)
            self.nodes[key] = idx
            self.node_xy.append((x, y))
            self.adjacency[idx] = []
        return idx

    def node_point(self, idx: int) -> tuple[float, float]:
        return self.node_xy[idx]

    def edge_midpoint(self, eidx: int) -> tuple[float, float]:
        e = self.edges[eidx]
        (x1, y1), (x2, y2) = self.node_xy[e["n1"]], self.node_xy[e["n2"]]
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    def edge_length(self, eidx: int) -> float:
        e = self.edges[eidx]
        (x1, y1), (x2, y2) = self.node_xy[e["n1"]], self.node_xy[e["n2"]]
        return math.hypot(x2 - x1, y2 - y1)


def build_edge_graph(grid: HexGrid, q: np.ndarray, r: np.ndarray,
                     hex_ids: list[str]) -> HexEdgeGraph:
    """Build the edge graph for a set of hexes.

    Each hex side becomes one edge shared with its neighbour; the neighbour is
    identified geometrically (mirror of the centre across the side midpoint),
    which works for any orientation. Edges on the patch border (neighbour not
    generated) still exist, with hex_b = None.
    """
    g = HexEdgeGraph(grid=grid)
    id_by_qr = {(int(qi), int(ri)): hid for qi, ri, hid in zip(q, r, hex_ids)}
    polys = grid.polygons(q, r)
    cx, cy = grid.axial_to_xy(q, r)
    cx = np.atleast_1d(cx)
    cy = np.atleast_1d(cy)

    for i in range(len(q)):
        coords = shapely.get_coordinates(polys[i])[:-1]
        hex_id = id_by_qr[(int(q[i]), int(r[i]))]
        for k in range(6):
            x1, y1 = coords[k]
            x2, y2 = coords[(k + 1) % 6]
            n1 = g._node(x1, y1)
            n2 = g._node(x2, y2)
            nkey = (min(n1, n2), max(n1, n2))
            eidx = g.edge_by_nodes.get(nkey)
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            if eidx is None:
                # Geometric neighbour: centre mirrored across the edge midpoint.
                nq, nr = grid.xy_to_axial(2 * mx - cx[i], 2 * my - cy[i])
                nbr_id = id_by_qr.get((int(nq), int(nr)))
                eidx = len(g.edges)
                g.edges.append({
                    "n1": nkey[0], "n2": nkey[1],
                    "hex_a": hex_id, "hex_b": nbr_id,
                })
                g.edge_by_nodes[nkey] = eidx
                g.adjacency[n1].append((n2, eidx))
                g.adjacency[n2].append((n1, eidx))
            else:
                e = g.edges[eidx]
                if e["hex_b"] is None and e["hex_a"] != hex_id:
                    e["hex_b"] = hex_id
    # Canonical hex order and stable edge id.
    for e in g.edges:
        a, b = e["hex_a"], e["hex_b"]
        if b is not None and b < a:
            e["hex_a"], e["hex_b"] = b, a
        e["edge_id"] = f"e_{e['hex_a']}_{e['hex_b'] or 'OUT'}"
    return g


def edge_direction_deg(g: HexEdgeGraph, n_from: int, n_to: int) -> float:
    (x1, y1), (x2, y2) = g.node_xy[n_from], g.node_xy[n_to]
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 360.0
