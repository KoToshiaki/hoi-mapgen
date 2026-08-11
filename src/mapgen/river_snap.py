"""River -> hex-edge map matching (MAPGEN-003, hardened in MAPGEN-003A).

Rivers are NOT snapped point-by-point to the nearest edge (that fragments and
jitters). Instead each river branch is matched to a CONTINUOUS path through
the hex-edge graph with a STATEFUL shortest-path search:

  step cost = length * (1 + (dist(edge_mid, source_line)/scale)^2) * water_pen
            + length * direction_weight * (1 - cos(angle to source tangent))/2
            + same_turn_penalty * side_len   (when the turn curls the same way
                                              twice in a row)

- Distance keeps the path in the corridor; TANGENT ALIGNMENT keeps it moving
  along the source river (kills wander through braided/parallel arms);
  the SAME-TURN penalty suppresses curling zigzag. On a hex-corner lattice
  every step turns exactly +-60 deg, so "straightness" means alternating turn
  signs — repeated signs are the real detour signal. Immediate reversal is
  impossible by construction (the search never returns to the previous node).
- A curved source river stays curved: alignment follows the LOCAL tangent,
  so following a meander is cheap and cutting it off is expensive.
- The search is restricted to a corridor around the source polyline.
- Edges lying fully between two water hexes (ocean/lake interior) carry a
  heavy penalty, so EDGE_RIVERs do not run through open water.
- Branches are processed in importance-descending order (GREAT first); a
  tributary's downstream endpoint is FORCED onto a node of the already
  snapped receiving branch nearest the true confluence, preserving topology.
- Flow direction is preserved by construction: the path is stored
  upstream -> downstream.
"""
from __future__ import annotations

import heapq
import math

import numpy as np
import shapely

from .hex_edges import HexEdgeGraph, edge_direction_deg
from .rivers import Branch


def line_turn_density(line: shapely.LineString, simplify_tol: float) -> float:
    """Source-line complexity: total absolute heading change per 100 km,
    expressed in 60-degree hex-turn equivalents (comparable to snapped
    turns_per_100km)."""
    simp = shapely.simplify(line, simplify_tol)
    xy = shapely.get_coordinates(simp)
    if len(xy) < 3 or line.length <= 0:
        return 0.0
    v = np.diff(xy, axis=0)
    ang = np.arctan2(v[:, 1], v[:, 0])
    d = np.abs(np.diff(ang))
    d = np.minimum(d, 2 * np.pi - d)
    total_turns_60 = float(np.degrees(d).sum() / 60.0)
    return total_turns_60 / (line.length / 100000.0)


def _edge_lines(g: HexEdgeGraph) -> np.ndarray:
    pts = np.asarray(g.node_xy)
    n1 = np.array([e["n1"] for e in g.edges])
    n2 = np.array([e["n2"] for e in g.edges])
    coords = np.stack([pts[n1], pts[n2]], axis=1)
    return shapely.linestrings(coords)


class RiverSnapper:
    def __init__(self, graph: HexEdgeGraph, hex_water: dict[str, str],
                 scfg: dict):
        self.g = graph
        self.hex_water = hex_water
        self.cfg = scfg
        self.edge_geoms = _edge_lines(graph)
        self.tree = shapely.STRtree(self.edge_geoms)
        self.node_pts = np.asarray(graph.node_xy)
        # reach id -> (branch, node_path) of already snapped branches
        self.junctions: dict[int, tuple[Branch, list[int]]] = {}
        self._water_pen = np.array([self._water_penalty(e) for e in graph.edges])

    def _water_penalty(self, e: dict) -> float:
        wa = self.hex_water.get(e["hex_a"], "NONE")
        wb = self.hex_water.get(e["hex_b"], "NONE") if e["hex_b"] else wa
        both_water = wa in ("OCEAN", "LAKE") and wb in ("OCEAN", "LAKE")
        return self.cfg["water_edge_penalty"] if both_water else 1.0

    # ------------------------------------------------------------------
    def snap_branch(self, branch: Branch) -> dict | None:
        """Match one branch to a continuous edge path. Returns result dict or
        None when no path exists inside the corridor.

        Matching runs against a SIMPLIFIED source line: meanders smaller than
        the hex scale are invisible at 6 km resolution but would otherwise be
        amplified into hex-sized detours (the MAPGEN-003 Rhine inflation).
        Endpoints are preserved by simplification; offset metrics are still
        measured against the ORIGINAL line.
        """
        orig_line = branch.line
        tol = float(self.cfg.get("simplify_tolerance_m", 0.0))
        line = (shapely.simplify(orig_line, tol) if tol > 0 else orig_line)
        corridor = line.buffer(self.cfg["corridor_m"])
        cand = self.tree.query(corridor, predicate="intersects")
        if len(cand) == 0:
            return None
        cand = np.sort(cand)
        mids = shapely.points(
            np.array([self.g.edge_midpoint(int(i)) for i in cand]))
        dist = shapely.distance(mids, line)
        scale = self.cfg["distance_cost_scale_m"]
        lengths = np.array([self.g.edge_length(int(i)) for i in cand])
        costs = lengths * (1.0 + (dist / scale) ** 2) * self._water_pen[cand]
        cost_by_edge = dict(zip(cand.tolist(), costs.tolist()))

        # Local adjacency restricted to corridor edges.
        cand_set = set(cand.tolist())
        adj: dict[int, list[tuple[int, int]]] = {}
        for eidx in cand_set:
            e = self.g.edges[eidx]
            for a, b in ((e["n1"], e["n2"]), (e["n2"], e["n1"])):
                adj.setdefault(a, []).append((b, eidx))

        # Directed tangent-alignment costs (forward = n1 -> n2 traversal).
        dir_w = float(self.cfg.get("direction_weight", 1.2))
        dircost = {}
        if dir_w > 0:
            tangents = self._tangents(line, cand)
            for i, eidx in enumerate(cand.tolist()):
                e = self.g.edges[eidx]
                (x1, y1), (x2, y2) = (self.g.node_xy[e["n1"]],
                                      self.g.node_xy[e["n2"]])
                ex, ey = x2 - x1, y2 - y1
                el = math.hypot(ex, ey)
                tx, ty = tangents[i]
                tl = math.hypot(tx, ty)
                cos_f = ((ex * tx + ey * ty) / (el * tl)) if el > 0 and tl > 0 else 0.0
                dircost[(eidx, True)] = lengths[i] * dir_w * (1.0 - cos_f) / 2.0
                dircost[(eidx, False)] = lengths[i] * dir_w * (1.0 + cos_f) / 2.0
        else:
            for i, eidx in enumerate(cand.tolist()):
                dircost[(eidx, True)] = 0.0
                dircost[(eidx, False)] = 0.0

        start_xy = shapely.get_coordinates(line)[0]
        end_xy = shapely.get_coordinates(line)[-1]
        start = self._nearest_node(adj, start_xy)
        target_nodes, confluence_reach = self._target(branch, adj, end_xy)
        if start is None or not target_nodes:
            return None

        if start in target_nodes:
            # Branch shorter than one hex edge whose junction coincides with
            # its start: trivially connected, no edges of its own.
            for rid in branch.reach_ids:
                self.junctions[rid] = (branch, [start])
            return {
                "branch": branch, "node_path": [start], "edges": [],
                "offsets": np.array([0.0]), "snapped_length_m": 0.0,
                "extension_length_m": 0.0,
                "offset_mean_m": 0.0, "offset_median_m": 0.0,
                "offset_p90_m": 0.0, "offset_p95_m": 0.0, "offset_max_m": 0.0,
                "excess_turn_count": 0, "sharp_turn_count": 0, "turn_count": 0,
                "turns_per_100km": 0.0, "source_turns_per_100km": 0.0,
                "snapped_turn_excess": 0.0, "direction_reversal_count": 0,
                "straight_progress_efficiency": 1.0,
                "confluence_reach": confluence_reach,
                "connected_to_receiver": bool(confluence_reach),
            }
        path = self._stateful_dijkstra(adj, cost_by_edge, dircost, start,
                                       target_nodes)
        if path is None or len(path) < 2:
            return None
        return self._result(branch, path, orig_line, confluence_reach)

    def _nearest_node(self, adj: dict, xy) -> int | None:
        if not adj:
            return None
        nodes = np.fromiter(adj.keys(), dtype=np.int64)
        d = np.hypot(self.node_pts[nodes, 0] - xy[0],
                     self.node_pts[nodes, 1] - xy[1])
        return int(nodes[np.argmin(d)])

    def _target(self, branch: Branch, adj: dict, end_xy):
        """Downstream target node(s). If the receiving branch was already
        snapped, force the connection onto its path (confluence preservation);
        otherwise the node nearest the source end point (mouth/border)."""
        if branch.next_down_reach and branch.next_down_reach in self.junctions:
            _, node_path = self.junctions[branch.next_down_reach]
            usable = [n for n in node_path if n in adj]
            if usable:
                pts = self.node_pts[np.array(usable)]
                d = np.hypot(pts[:, 0] - end_xy[0], pts[:, 1] - end_xy[1])
                order = np.argsort(d)
                return [int(usable[i]) for i in order[:3]], branch.next_down_reach
        n = self._nearest_node(adj, end_xy)
        return ([n] if n is not None else []), 0

    def _tangents(self, line, cand) -> list[tuple[float, float]]:
        """Local source tangent nearest each candidate edge midpoint."""
        out = []
        length = line.length
        delta = 400.0
        for eidx in cand.tolist():
            mid = shapely.Point(self.g.edge_midpoint(int(eidx)))
            s = float(shapely.line_locate_point(line, mid))
            p0 = line.interpolate(max(s - delta, 0.0))
            p1 = line.interpolate(min(s + delta, length))
            out.append((p1.x - p0.x, p1.y - p0.y))
        return out

    def _stateful_dijkstra(self, adj, cost_by_edge, dircost, start,
                           targets) -> list[int] | None:
        """Shortest path with heading state: (node, prev_node, last_turn_sign).

        Adds tangent-alignment cost per directed edge and a penalty when two
        consecutive turns curl the same way (the hex-lattice detour signal).
        """
        target_set = set(targets)
        turn_pen = float(self.cfg.get("same_turn_penalty", 0.6)) * self.g.grid.side
        xy = self.node_pts
        best: dict[tuple[int, int, int], float] = {(start, -1, 0): 0.0}
        prev_map: dict[tuple[int, int, int], tuple] = {}
        pq = [(0.0, start, -1, 0)]
        goal_state = None
        while pq:
            d, node, prev, sign = heapq.heappop(pq)
            state = (node, prev, sign)
            if d > best.get(state, np.inf):
                continue
            if node in target_set:
                goal_state = state
                break
            for w, eidx in adj.get(node, ()):
                if w == prev:
                    continue
                e = self.g.edges[eidx]
                forward = e["n1"] == node
                step = cost_by_edge[eidx] + dircost[(eidx, forward)]
                nsign = 0
                if prev >= 0:
                    ax, ay = xy[node, 0] - xy[prev, 0], xy[node, 1] - xy[prev, 1]
                    bx, by = xy[w, 0] - xy[node, 0], xy[w, 1] - xy[node, 1]
                    nsign = int(np.sign(ax * by - ay * bx))
                    if nsign != 0 and nsign == sign:
                        step += turn_pen
                nd = d + step
                nstate = (w, node, nsign)
                if nd < best.get(nstate, np.inf):
                    best[nstate] = nd
                    prev_map[nstate] = state
                    heapq.heappush(pq, (nd, w, node, nsign))
        if goal_state is None:
            return None
        path = [goal_state[0]]
        cur = goal_state
        while cur in prev_map:
            cur = prev_map[cur]
            path.append(cur[0])
        return path[::-1]

    def _dijkstra(self, adj, cost_by_edge, start, targets) -> list[int] | None:
        target_set = set(targets)
        best = {start: 0.0}
        prev: dict[int, tuple[int, int]] = {}
        pq = [(0.0, start)]
        while pq:
            d, u = heapq.heappop(pq)
            if u in target_set:
                path = [u]
                while path[-1] != start:
                    path.append(prev[path[-1]][0])
                return path[::-1]
            if d > best.get(u, np.inf):
                continue
            for v, eidx in adj.get(u, ()):
                nd = d + cost_by_edge[eidx]
                if nd < best.get(v, np.inf):
                    best[v] = nd
                    prev[v] = (u, eidx)
                    heapq.heappush(pq, (nd, v))
        return None

    # ------------------------------------------------------------------
    def _result(self, branch: Branch, path: list[int], line, confluence_reach):
        g = self.g
        edge_rows = []
        offsets = []
        turn_signs = []
        snapped_len = 0.0
        for i in range(len(path) - 1):
            n1, n2 = path[i], path[i + 1]
            key = (min(n1, n2), max(n1, n2))
            eidx = g.edge_by_nodes[key]
            e = g.edges[eidx]
            length = g.edge_length(eidx)
            snapped_len += length
            mid = shapely.Point(g.edge_midpoint(eidx))
            d_mid = float(shapely.distance(mid, line))
            offsets.append(d_mid)
            edge_rows.append({
                "edge_id": e["edge_id"],
                "hex_a_id": e["hex_a"],
                "hex_b_id": e["hex_b"],
                "edge_direction": round(edge_direction_deg(g, e["n1"], e["n2"]), 1),
                "flow_direction": round(edge_direction_deg(g, n1, n2), 1),
                "flow_from_node": n1,
                "flow_to_node": n2,
                "snap_distance_m": round(d_mid, 1),
            })
            if i >= 1:
                p0 = g.node_xy[path[i - 1]]
                p1 = g.node_xy[n1]
                p2 = g.node_xy[n2]
                ax, ay = p1[0] - p0[0], p1[1] - p0[1]
                bx, by = p2[0] - p1[0], p2[1] - p1[1]
                turn_signs.append(int(np.sign(ax * by - ay * bx)))
        sharp_turns = sum(
            1 for a, b in zip(turn_signs, turn_signs[1:]) if a == b and a != 0)

        # Direction reversals: path edges travelling against the local source
        # tangent (> 120 deg off).
        reversals = 0
        tangents = self._tangents(
            line, np.array([g.edge_by_nodes[(min(a, b), max(a, b))]
                            for a, b in zip(path, path[1:])]))
        for i in range(len(path) - 1):
            (x1, y1), (x2, y2) = g.node_xy[path[i]], g.node_xy[path[i + 1]]
            ex, ey = x2 - x1, y2 - y1
            tx, ty = tangents[i]
            el, tl = math.hypot(ex, ey), math.hypot(tx, ty)
            if el > 0 and tl > 0 and (ex * tx + ey * ty) / (el * tl) < -0.5:
                reversals += 1

        # Register every reach of this branch for later tributaries.
        for rid in branch.reach_ids:
            self.junctions[rid] = (branch, path)

        offsets = np.array(offsets)
        sx, sy = g.node_xy[path[0]]
        ex_, ey_ = g.node_xy[path[-1]]
        euclid = math.hypot(ex_ - sx, ey_ - sy)
        km100 = snapped_len / 100000.0
        source_turns = line_turn_density(line, g.grid.side / 2.0)
        turns_per_100km = (len(turn_signs) / km100) if km100 > 0 else 0.0
        return {
            "branch": branch,
            "node_path": path,
            "edges": edge_rows,
            "offsets": offsets,
            "snapped_length_m": snapped_len,
            "extension_length_m": 0.0,
            "offset_mean_m": float(offsets.mean()),
            "offset_median_m": float(np.median(offsets)),
            "offset_p90_m": float(np.percentile(offsets, 90)),
            "offset_p95_m": float(np.percentile(offsets, 95)),
            "offset_max_m": float(offsets.max()),
            "excess_turn_count": int(sharp_turns),
            "sharp_turn_count": int(sharp_turns),
            "turn_count": int(len(turn_signs)),
            "turns_per_100km": float(turns_per_100km),
            "source_turns_per_100km": float(source_turns),
            "snapped_turn_excess": float(turns_per_100km - source_turns),
            "direction_reversal_count": int(reversals),
            "straight_progress_efficiency": float(
                euclid / snapped_len) if snapped_len > 0 else 0.0,
            "confluence_reach": confluence_reach,
            "connected_to_receiver": bool(confluence_reach),
        }


def water_hex_river_hexes(branch: Branch, hex_polys: np.ndarray,
                          hex_ids: list[str], exaggeration: float) -> list[str]:
    """Hexes occupied by a WATER_HEX_RIVER branch: those intersecting the
    centerline buffered to half the effective game width."""
    eff_width = branch.width_est_m * exaggeration
    buf = branch.line.buffer(eff_width / 2.0)
    tree = shapely.STRtree(hex_polys)
    idx = tree.query(buf, predicate="intersects")
    return [hex_ids[int(i)] for i in np.sort(idx)]
