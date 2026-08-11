"""Strategic island preservation core logic (MAPGEN-005).

Concepts (kept strictly separate):
- island COMPONENT: one physically contiguous OSM land polygon.
- island GROUP: nearby lost components clustered into one game island
  (atolls / tight archipelagos that are split across polygons).
- island OVERLAY: a preserved group attached to ordinary OCEAN/LAKE hexes.

The hex grid, water_type and coast authority are NEVER modified here: a
sub-hex island lives as an overlay on top of an unchanged OCEAN hex.

Determinism: component/group/island ids derive from canonical geometry
hashes (mm-precision WKB), so the same source snapshot + config reproduces
identical ids. Persistence ACROSS OSM snapshot updates is explicitly not
guaranteed (see README).
"""
from __future__ import annotations

import hashlib
import math

import numpy as np
import pandas as pd
import shapely
from pyproj import Geod

from .projection import WORLD_HALF_EXTENT_M, to_wgs84

# WGS84 ellipsoid: the authority for all PHYSICAL island metrics (area,
# perimeter, distances, extents). EPSG:3857 stays the authority for hex GRID
# geometry only 窶・projected values are audit columns, never thresholds.
GEOD = Geod(ellps="WGS84")

WORLD_WIDTH_M = 2.0 * WORLD_HALF_EXTENT_M


def assign_analysis_frame(comps: list[dict], crosses_dateline: bool) -> None:
    """Dateline hardening: give every component an ANALYSIS geometry.

    The EPSG:3857 hex authority keeps its +-180 seam; for regions that cross
    it, western-hemisphere components are shifted +world-width into a
    contiguous analysis frame so projected nearest-pair search, clustering,
    hulls and bbox caps all see true neighbourhoods. Geodesic distances on
    shifted coordinates stay correct (pyproj normalises longitudes > 180).
    Hex intersections and stored geometries remain in the original frame.
    """
    for c in comps:
        if crosses_dateline and c["centroid_x"] < 0:
            c["ageometry"] = shapely.transform(
                c["geometry"],
                lambda xy: xy + np.array([WORLD_WIDTH_M, 0.0]))
            c["acentroid_x"] = c["centroid_x"] + WORLD_WIDTH_M
        else:
            c["ageometry"] = c["geometry"]
            c["acentroid_x"] = c["centroid_x"]


def _to_lonlat(geom3857):
    def _tf(coords):
        lon, lat = to_wgs84(coords[:, 0], coords[:, 1])
        return np.column_stack([lon, lat])

    return shapely.transform(geom3857, _tf)


def ground_area_perimeter(geom3857) -> tuple[float, float]:
    """Geodesic (WGS84 ellipsoid) area [km2] and perimeter [km]."""
    g = _to_lonlat(geom3857)
    area_m2, perim_m = GEOD.geometry_area_perimeter(g)
    return abs(area_m2) / 1e6, perim_m / 1000.0

def ground_point_distance_m(x1, y1, x2, y2) -> float:
    """Geodesic distance between two EPSG:3857 points."""
    lon1, lat1 = to_wgs84(x1, y1)
    lon2, lat2 = to_wgs84(x2, y2)
    _, _, d = GEOD.inv(float(lon1), float(lat1), float(lon2), float(lat2))
    return float(d)


def ground_distance_m(geom_a, geom_b) -> float:
    """Geodesic distance between two nearby geometries.

    The nearest point PAIR is found in projected space (locally the Mercator
    scale factor is constant, so the pair is correct at the ~10 km scales
    used here); the distance between that pair is then measured on the
    ellipsoid.
    """
    from shapely.ops import nearest_points

    pa, pb = nearest_points(geom_a, geom_b)
    return ground_point_distance_m(pa.x, pa.y, pb.x, pb.y)


def ground_extent_km(geom3857) -> float:
    """Max geodesic distance between convex-hull vertices [km]."""
    hull = shapely.convex_hull(geom3857)
    pts = shapely.get_coordinates(hull)
    if len(pts) < 2:
        return 0.0
    lon, lat = to_wgs84(pts[:, 0], pts[:, 1])
    best = 0.0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            _, _, d = GEOD.inv(float(lon[i]), float(lat[i]),
                               float(lon[j]), float(lat[j]))
            best = max(best, d)
    return best / 1000.0


def geometry_hash(geom, precision: float = 0.001) -> str:
    canon = shapely.set_precision(geom, precision)
    return hashlib.sha1(shapely.to_wkb(canon)).hexdigest()


def component_id(geom) -> str:
    return f"isl_c_{geometry_hash(geom)[:12]}"


def extract_components(land_union, clip_bounds: tuple[float, float, float, float],
                       boundary_tol_m: float = 2.0) -> list[dict]:
    """Detached land polygons from the (clipped) OSM land union.

    Components touching the clip rectangle are mainland/offscreen fragments,
    not islands 窶・flagged and never treated as lost islands.
    """
    min_x, min_y, max_x, max_y = clip_bounds
    inner = shapely.box(min_x + boundary_tol_m, min_y + boundary_tol_m,
                        max_x - boundary_tol_m, max_y - boundary_tol_m)
    comps = []
    for part in shapely.get_parts(land_union):
        if part.is_empty or part.geom_type != "Polygon":
            continue
        g_area, g_perim = ground_area_perimeter(part)
        comps.append({
            "island_component_id": component_id(part),
            "geometry": part,
            # PHYSICAL metrics = geodesic; projected values are audit-only.
            "ground_area_km2": g_area,
            "ground_perimeter_km": g_perim,
            "projected_area_km2": float(shapely.area(part)) / 1e6,
            "projected_perimeter_km": float(
                shapely.length(shapely.boundary(part))) / 1000.0,
            "centroid_x": float(shapely.centroid(part).x),
            "centroid_y": float(shapely.centroid(part).y),
            "touches_clip_boundary": not bool(
                shapely.contains_properly(inner, part)),
        })
    # Deterministic order.
    comps.sort(key=lambda c: c["island_component_id"])
    return comps


def component_hex_stats(components: list[dict], hex_polys: np.ndarray,
                        hex_ids: list[str], is_terrestrial: np.ndarray,
                        land_fraction: np.ndarray) -> None:
    """Annotate components in-place with hex intersections and lost status.

    Spatial-index based (never all-components x all-hexes).
    """
    tree = shapely.STRtree(hex_polys)
    for c in components:
        idxs = np.sort(tree.query(c["geometry"], predicate="intersects"))
        inter_areas = {}
        for i in idxs:
            a = float(shapely.area(
                shapely.intersection(hex_polys[int(i)], c["geometry"])))
            if a > 0:
                inter_areas[int(i)] = a
        idx_list = sorted(inter_areas)
        c["hex_idx_areas"] = inter_areas
        c["intersecting_hex_ids"] = [hex_ids[i] for i in idx_list]
        c["max_hex_land_fraction"] = (
            max(float(land_fraction[i]) for i in idx_list) if idx_list else 0.0)
        c["represented_by_terrestrial_hex"] = any(
            bool(is_terrestrial[i]) for i in idx_list)
        c["primary_hex_id"] = (
            hex_ids[max(idx_list, key=lambda i: (inter_areas[i], -i))]
            if idx_list else None)
        covered = sum(inter_areas.values())
        # Coverage compares projected areas with projected hex intersections
        # (grid-space bookkeeping, not a physical metric).
        c["hex_coverage_fraction"] = (
            covered / (c["projected_area_km2"] * 1e6)
            if c["projected_area_km2"] > 0 else 0.0)
        # Components partially outside the generated hex set (bbox margin
        # edge) cannot be judged 窶・never treated as lost islands.
        c["fully_hex_covered"] = c["hex_coverage_fraction"] >= 0.98
        c["is_subhex_lost"] = (bool(idx_list)
                               and not c["represented_by_terrestrial_hex"]
                               and not c["touches_clip_boundary"]
                               and c["fully_hex_covered"])


def candidate_edges(lost: list[dict], max_distance_ground_m: float
                    ) -> list[tuple]:
    """Ground-distance candidate edges (d, id_i, id_j, i, j) for clustering.

    Exposed so a parameter sweep can compute them ONCE at the largest
    distance and re-filter per variant — identical results, no re-discovery.
    """
    n = len(lost)
    geoms = np.array([c.get("ageometry", c["geometry"]) for c in lost])
    tree = shapely.STRtree(geoms)
    edges = []
    for i in range(n):
        _, lat_i = to_wgs84(lost[i].get("acentroid_x", lost[i]["centroid_x"]),
                            lost[i]["centroid_y"])
        scale = 1.0 / max(math.cos(math.radians(float(lat_i))), 0.05)
        buf = max_distance_ground_m * scale * 1.2
        cand = tree.query(geoms[i].buffer(buf), predicate="intersects")
        for j in np.sort(cand):
            j = int(j)
            if j <= i:
                continue
            d = ground_distance_m(geoms[i], geoms[j])
            if d <= max_distance_ground_m:
                edges.append((round(d, 3),
                              lost[i]["island_component_id"],
                              lost[j]["island_component_id"], i, j))
    edges.sort()
    return edges


def cluster_lost_components(lost: list[dict], max_distance_ground_m: float,
                            max_diameter_ground_m: float = np.inf,
                            precomputed_edges: list[tuple] | None = None
                            ) -> list[list[dict]]:
    """Diameter-capped union-find clustering of lost components in GROUND
    metres (WGS84 geodesic).

    Candidate pairs (ground distance <= threshold) merge in ascending ground
    distance order (ties broken by component ids 窶・fully deterministic); a
    merge is REJECTED when the combined bounding box's geodesic diagonal
    would exceed the ground diameter cap. Projected distances are used only
    to pre-select candidates (with a latitude-aware safety buffer) 窶・never
    for the threshold comparison itself.
    """
    n = len(lost)
    if n == 0:
        return []
    geoms = np.array([c.get("ageometry", c["geometry"]) for c in lost])
    bounds = shapely.bounds(geoms)  # (n, 4)
    parent = list(range(n))
    root_bounds = {i: bounds[i].copy() for i in range(n)}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _bbox_ground_diag(b) -> float:
        return ground_point_distance_m(b[0], b[1], b[2], b[3])

    if precomputed_edges is not None:
        edges = [e for e in precomputed_edges
                 if e[0] <= max_distance_ground_m]
    else:
        edges = candidate_edges(lost, max_distance_ground_m)

    for _, _, _, i, j in edges:
        ra, rb = find(i), find(j)
        if ra == rb:
            continue
        ba, bb = root_bounds[ra], root_bounds[rb]
        merged = np.array([min(ba[0], bb[0]), min(ba[1], bb[1]),
                           max(ba[2], bb[2]), max(ba[3], bb[3])])
        if _bbox_ground_diag(merged) > max_diameter_ground_m:
            continue
        root = min(ra, rb)
        parent[max(ra, rb)] = root
        root_bounds[root] = merged

    groups: dict[int, list[dict]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(lost[i])
    # Deterministic order by first component id.
    out = sorted(groups.values(),
                 key=lambda g: g[0]["island_component_id"])
    return out


def group_metrics(group: list[dict]) -> dict:
    # Analysis frame (dateline-shifted where applicable) for all physical
    # metrics; stored geometry keeps the original EPSG:3857 frame.
    aunion = shapely.union_all([c.get("ageometry", c["geometry"])
                                for c in group])
    union = shapely.union_all([c["geometry"] for c in group])
    hull = shapely.convex_hull(aunion)
    pts = shapely.get_coordinates(hull)
    proj_extent = 0.0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            proj_extent = max(proj_extent, math.hypot(*(pts[i] - pts[j])))
    proj_sep = 0.0
    ground_sep = 0.0
    if len(group) > 1:
        for i in range(len(group)):
            dists = [(float(shapely.distance(
                group[i].get("ageometry", group[i]["geometry"]),
                group[j].get("ageometry", group[j]["geometry"]))), j)
                     for j in range(len(group)) if j != i]
            dmin, jmin = min(dists)
            proj_sep = max(proj_sep, dmin)
            ground_sep = max(ground_sep, ground_distance_m(
                group[i].get("ageometry", group[i]["geometry"]),
                group[jmin].get("ageometry", group[jmin]["geometry"])))
    cen = shapely.centroid(aunion)
    comp_ids = sorted(c["island_component_id"] for c in group)
    gid = "isl_g_" + hashlib.sha1("|".join(comp_ids).encode()).hexdigest()[:12]
    ground_areas = sorted((c["ground_area_km2"] for c in group), reverse=True)
    total_ground = float(sum(ground_areas))
    hull_ground_km2, _ = ground_area_perimeter(hull)
    return {
        "island_group_id": gid,
        "component_ids": comp_ids,
        "component_count": len(group),
        "components": group,
        "geometry": union,
        # GROUND metrics (authoritative for preservation semantics).
        "total_land_area_ground_km2": total_ground,
        "ground_perimeter_km": float(
            sum(c["ground_perimeter_km"] for c in group)),
        "group_extent_ground_km": ground_extent_km(aunion),
        "max_component_separation_ground_km": ground_sep / 1000.0,
        "largest_component_ground_area_km2": float(ground_areas[0]),
        "largest_component_area_share": (
            float(ground_areas[0]) / total_ground if total_ground > 0 else 0.0),
        "land_hull_ratio": (total_ground / hull_ground_km2
                            if hull_ground_km2 > 0 else 1.0),
        # PROJECTED audit values.
        "total_land_area_projected_km2": float(
            sum(c["projected_area_km2"] for c in group)),
        "group_extent_projected_km": proj_extent / 1000.0,
        "max_component_separation_projected_km": proj_sep / 1000.0,
        "centroid_x": float(cen.x),
        "centroid_y": float(cen.y),
    }


def choose_primary_hex(hex_areas: dict[int, float], centroid_xy,
                       hex_centres: np.ndarray, hex_ids: list[str]) -> str | None:
    """Deterministic anchor hex: max intersection area, then closest centre
    to the group centroid, then stable hex_id order."""
    if not hex_areas:
        return None
    cx, cy = centroid_xy

    def key(i):
        d = math.hypot(hex_centres[i][0] - cx, hex_centres[i][1] - cy)
        return (-round(hex_areas[i], 6), round(d, 6), hex_ids[i])

    best = min(hex_areas, key=key)
    return hex_ids[best]


def decide_preservation(group: dict, min_area_km2: float,
                        force_preserve: set, force_ignore: set) -> tuple[bool, str]:
    """MAPGEN-005 legacy rule (kept for reference; superseded by
    decide_preservation_units)."""
    gid = group["island_group_id"]
    if gid in force_ignore:
        return False, "FORCE_IGNORE"
    if gid in force_preserve:
        return True, "FORCE_PRESERVE"
    if group["total_land_area_ground_km2"] >= min_area_km2:
        return True, "AUTO_AREA_THRESHOLD"
    return False, "BELOW_MIN_AREA"


def decide_preservation_units(group: dict, icfg: dict, force_preserve: set,
                              force_ignore: set) -> tuple[list[dict], str]:
    """MAPGEN-005A preservation semantics 窶・GROUND areas only.

    Returns (units, group_status). A UNIT is what becomes a gameplay island
    overlay; a geographic group may yield 0, 1 or several units:

    - FORCE_IGNORE / BELOW_MIN_AREA: no units.
    - single component >= min area: one unit (SINGLE_COMPONENT_AREA).
    - multi-component group passing the micro-islet guard (largest component
      significant AND holding a minimum share): one unit
      (MULTI_COMPONENT_ARCHIPELAGO, or DISPERSED_MULTI_COMPONENT_GROUP when the
      land/hull ratio indicates spatial dispersion - a GEOMETRY-ONLY label;
      true atoll classification is deferred until lagoon/water data exists).
    - guard failed but the group contains coherent cores (component ground
      area >= min area): one unit per core, the micro rest is dropped
      (group_status SPLIT_INTO_MULTIPLE_UNITS).
    - guard failed with no cores: no units (AGGREGATED_MICRO_ISLETS).
    """
    min_area = float(icfg["minimum_auto_preserve_area_km2"])
    min_sig = float(icfg["minimum_significant_component_area_km2"])
    min_share = float(icfg["minimum_largest_component_share"])
    # MAPGEN-006R public name; the old atoll_candidate_* key is accepted as a
    # deprecated alias only (same value, same behaviour, no atoll assertion).
    dispersed_ratio = float(icfg.get(
        "dispersed_group_max_land_hull_ratio",
        icfg.get("atoll_candidate_max_land_hull_ratio", 0.45)))
    gid = group["island_group_id"]

    if gid in force_ignore:
        return [], "FORCE_IGNORE"
    forced = gid in force_preserve
    if not forced and group["total_land_area_ground_km2"] < min_area:
        return [], "BELOW_MIN_AREA"

    def _unit(components, reason):
        return {"components": components, "reason": reason}

    if group["component_count"] == 1:
        return [_unit(group["components"],
                      "FORCE_PRESERVE" if forced else "SINGLE_COMPONENT_AREA")], \
            "PRESERVED"

    guard_ok = (group["largest_component_ground_area_km2"] >= min_sig
                and group["largest_component_area_share"] >= min_share)
    if forced:
        return [_unit(group["components"], "FORCE_PRESERVE")], "PRESERVED"
    if guard_ok:
        reason = ("DISPERSED_MULTI_COMPONENT_GROUP"
                  if group["land_hull_ratio"] <= dispersed_ratio
                  else "MULTI_COMPONENT_ARCHIPELAGO")
        return [_unit(group["components"], reason)], "PRESERVED"

    cores = [c for c in group["components"]
             if c["ground_area_km2"] >= min_area]
    if cores:
        units = [_unit([c], "SINGLE_COMPONENT_AREA")
                 for c in sorted(cores,
                                 key=lambda c: c["island_component_id"])]
        return units, "SPLIT_INTO_MULTIPLE_UNITS"
    return [], "AGGREGATED_MICRO_ISLETS"


