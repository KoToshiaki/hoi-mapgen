"""MAPGEN-007 core helpers — reference human geography (NOT gameplay).

Semantics: every reference table produced here is a CONTEMPORARY, DE-FACTO
REFERENCE snapshot of Natural Earth cultural data. It is never gameplay or
historical authority: reference_admin ids are not owners, admin1 units are
not game states, populations are source estimates, ports are not naval
bases, and Natural Earth boundaries are not historical boundaries.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import shapely

from .islands import (WORLD_WIDTH_M, geometry_hash, ground_area_perimeter,
                      ground_point_distance_m)

# 1.1.0 (MAPGEN-007R): additive bidirectional coast/admin coverage audit
# columns; admin0_coverage_ratio_of_land kept as deprecated alias (old
# formula, unchanged meaning). Reference/binding tables are unchanged.
HUMAN_GEOGRAPHY_SCHEMA_VERSION = "1.1.0"
# 1.0.1: audit computation only — reference geography and every binding
# algorithm are identical to 1.0.0.
HUMAN_GEOGRAPHY_ALGORITHM_VERSION = "1.0.1"
REFERENCE_SEMANTICS = "CONTEMPORARY_DE_FACTO_REFERENCE"


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    s = str(v)
    return None if s in ("-99", "-099", "") else s


def build_admin0(gdf) -> pd.DataFrame:
    """Canonical reference admin0 table from NE admin_0_countries."""
    rows = []
    for t in gdf.itertuples():
        ne_id = getattr(t, "NE_ID", None)
        rid = (f"adm0_{int(ne_id)}" if ne_id is not None
               else f"adm0_h{geometry_hash(t.geometry)[:12]}")
        rows.append({
            "reference_admin0_id": rid,
            "source_dataset": "ne_10m_admin_0_countries",
            "source_feature_id": int(ne_id) if ne_id is not None else None,
            "name": t.NAME,
            "name_long": getattr(t, "NAME_LONG", None),
            "adm0_a3": _clean(getattr(t, "ADM0_A3", None)),
            "iso_a2": _clean(getattr(t, "ISO_A2_EH", None)
                             or getattr(t, "ISO_A2", None)),
            "iso_a3": _clean(getattr(t, "ISO_A3_EH", None)
                             or getattr(t, "ISO_A3", None)),
            "sovereign_name": getattr(t, "SOVEREIGNT", None),
            "sovereign_a3": _clean(getattr(t, "SOV_A3", None)),
            "country_name": getattr(t, "ADMIN", None),
            "map_unit_name": None,
            "source_type": getattr(t, "TYPE", None),
            "reference_boundary_semantics": REFERENCE_SEMANTICS,
            "gameplay_authoritative": False,
            "historical_authoritative": False,
            "geometry": t.geometry,
            "geometry_hash": geometry_hash(t.geometry)[:16],
        })
    df = pd.DataFrame(rows).sort_values("reference_admin0_id")
    return df.reset_index(drop=True)


def build_admin0_hierarchy(map_units, admin0_df) -> pd.DataFrame:
    """Sovereignty -> country -> map unit relations (as given by the source;
    no new political theory is inferred)."""
    a3_to_id = dict(zip(admin0_df["adm0_a3"], admin0_df["reference_admin0_id"]))
    rows = []
    for t in map_units.itertuples():
        ne_id = getattr(t, "NE_ID", None)
        mu_id = (f"adm0mu_{int(ne_id)}" if ne_id is not None
                 else f"adm0mu_h{geometry_hash(t.geometry)[:12]}")
        adm0_a3 = _clean(getattr(t, "ADM0_A3", None))
        sov_a3 = _clean(getattr(t, "SOV_A3", None))
        rows.append({
            "reference_map_unit_id": mu_id,
            "map_unit_name": t.NAME,
            "reference_admin0_id": a3_to_id.get(adm0_a3),
            "source_country_id": adm0_a3,
            "source_sovereign_id": sov_a3,
            "relationship_type": ("MAP_UNIT_OF_COUNTRY" if adm0_a3 == sov_a3
                                  else "MAP_UNIT_OF_DEPENDENT_TERRITORY"),
            "source_type": getattr(t, "TYPE", None),
            "source_dataset": "ne_10m_admin_0_map_units",
            "geometry_hash": geometry_hash(t.geometry)[:16],
        })
    return pd.DataFrame(rows).sort_values(
        "reference_map_unit_id").reset_index(drop=True)


def build_admin1(gdf, admin0_df) -> pd.DataFrame:
    a3_to_id = dict(zip(admin0_df["adm0_a3"], admin0_df["reference_admin0_id"]))
    rows = []
    for t in gdf.itertuples():
        code = _clean(getattr(t, "adm1_code", None))
        rid = (f"adm1_{code}" if code
               else f"adm1_h{geometry_hash(t.geometry)[:12]}")
        adm0_a3 = _clean(getattr(t, "adm0_a3", None))
        parent = a3_to_id.get(adm0_a3)
        rows.append({
            "reference_admin1_id": rid,
            "parent_reference_admin0_id": parent,
            "parent_null_reason": (None if parent
                                   else f"no admin0 match for {adm0_a3}"),
            "name": getattr(t, "name", None),
            "name_local": _clean(getattr(t, "name_local", None)),
            "source_feature_id": code,
            "source_admin_code": _clean(getattr(t, "code_hasc", None)),
            "source_iso_3166_2": _clean(getattr(t, "iso_3166_2", None)),
            "reference_boundary_semantics": REFERENCE_SEMANTICS,
            "gameplay_authoritative": False,
            "geometry": t.geometry,
            "geometry_hash": geometry_hash(t.geometry)[:16],
        })
    return pd.DataFrame(rows).sort_values(
        "reference_admin1_id").reset_index(drop=True)


def build_disputed(gdf) -> pd.DataFrame:
    rows = []
    for t in gdf.itertuples():
        ne_id = getattr(t, "NE_ID", None)
        rows.append({
            "reference_dispute_id": (f"disp_{int(ne_id)}" if ne_id is not None
                                     else f"disp_h{geometry_hash(t.geometry)[:12]}"),
            "name": t.NAME,
            "source_feature_id": int(ne_id) if ne_id is not None else None,
            "source_classification": getattr(t, "TYPE", None)
            or getattr(t, "featurecla", None),
            "reference_boundary_semantics": REFERENCE_SEMANTICS,
            "gameplay_authoritative": False,
            "geometry": t.geometry,
            "geometry_hash": geometry_hash(t.geometry)[:16],
        })
    return pd.DataFrame(rows).sort_values(
        "reference_dispute_id").reset_index(drop=True)


def repair_geometries(gdf, label: str) -> tuple:
    """make_valid with a full audit (never silently reshaping)."""
    invalid = ~shapely.is_valid(gdf.geometry.values)
    n_bad = int(invalid.sum())
    audit = {"dataset": label, "invalid_count": n_bad, "repairs": []}
    if n_bad:
        geoms = gdf.geometry.values.copy()
        for i in np.flatnonzero(invalid):
            before = float(shapely.area(geoms[i]))
            fixed = shapely.make_valid(geoms[i])
            after = float(shapely.area(fixed))
            audit["repairs"].append({
                "index": int(i),
                "area_projected_before": before,
                "area_projected_after": after,
                "method": "shapely.make_valid",
            })
            geoms[i] = fixed
        gdf = gdf.copy()
        gdf["geometry"] = list(geoms)
    return gdf, audit


# --------------------------------------------------------------------------
# Point bindings (pure helpers — unit-testable, dateline-aware)
# --------------------------------------------------------------------------
def dateline_ground_distance_m(geom, pt, crosses_dateline: bool) -> float:
    """Geodesic distance point<->geometry, trying the +world-width shifted
    frame near the seam so ±180 never looks like 40,000 km."""
    from .islands import ground_distance_m

    d = ground_distance_m(geom, pt)
    if not crosses_dateline:
        return d
    shifted = shapely.transform(
        pt, lambda xy: xy + np.array([WORLD_WIDTH_M
                                      if xy[0, 0] < 0 else -WORLD_WIDTH_M,
                                      0.0]))
    return min(d, ground_distance_m(geom, shifted))


def bind_point_to_admin(pt, admin_geoms: np.ndarray, admin_ids: list[str],
                        tree: shapely.STRtree, fallback_max_m: float,
                        crosses_dateline: bool = False):
    """Point-in-polygon first, nearest-polygon fallback with distance."""
    hits = tree.query(pt, predicate="covered_by")
    if len(hits):
        i = int(np.sort(hits)[0])
        return admin_ids[i], "POINT_IN_POLYGON", 0.0
    near = tree.query(pt.buffer(fallback_max_m * 2.5),
                      predicate="intersects")
    best, best_d = None, fallback_max_m
    for i in np.sort(near):
        d = dateline_ground_distance_m(admin_geoms[int(i)], pt,
                                       crosses_dateline)
        if d < best_d:
            best, best_d = int(i), d
    if best is not None:
        return admin_ids[best], "NEAREST_REFERENCE_POLYGON", best_d
    return None, "UNRESOLVED", None


def bind_point_to_land(pt, region: dict, snap_max_m: float):
    """Land binding order (spec 16): terrestrial hex -> overlay island
    component -> nearest within snap_max -> UNRESOLVED.

    region dict needs: grid, hex_ids(set-like list), terrestrial_by_hex
    (dict hex_id -> bool), comp_geoms / comp_ids / comp_units (overlay
    components only) + comp_tree, terr_tree/terr_polys/terr_hex_ids.
    Returns dict with kind/method/hex/component/unit/distance.
    """
    grid = region["grid"]
    q, r = grid.xy_to_axial(float(pt.x), float(pt.y))
    hid = grid.hex_id(q, r)
    known = hid in region["terrestrial_by_hex"]
    if known and region["terrestrial_by_hex"][hid]:
        return {"land_binding_kind": "TERRESTRIAL_HEX",
                "binding_method": "CONTAINS",
                "terrestrial_hex_id": hid, "island_component_id": None,
                "overlay_unit_id": None, "binding_distance_m": 0.0}
    if len(region["comp_geoms"]):
        hits = region["comp_tree"].query(pt, predicate="covered_by")
        if len(hits):
            i = int(np.sort(hits)[0])
            return {"land_binding_kind": "ISLAND_COMPONENT_OVERLAY",
                    "binding_method": "COMPONENT_CONTAINS",
                    "terrestrial_hex_id": None,
                    "island_component_id": region["comp_ids"][i],
                    "overlay_unit_id": region["comp_units"][i],
                    "binding_distance_m": 0.0}
    # Fallbacks, distance always recorded.
    best = None
    if len(region["terr_polys"]):
        near = region["terr_tree"].query(pt.buffer(snap_max_m),
                                         predicate="intersects")
        for i in np.sort(near):
            d = dateline_ground_distance_m(region["terr_polys"][int(i)], pt,
                                           region.get("crosses_dateline",
                                                      False))
            if d <= snap_max_m and (best is None or d < best[0]):
                best = (d, "NEAREST_TERRESTRIAL",
                        {"terrestrial_hex_id": region["terr_hex_ids"][int(i)],
                         "island_component_id": None,
                         "overlay_unit_id": None},
                        "TERRESTRIAL_HEX")
    if len(region["comp_geoms"]):
        near = region["comp_tree"].query(pt.buffer(snap_max_m),
                                         predicate="intersects")
        for i in np.sort(near):
            d = dateline_ground_distance_m(region["comp_geoms"][int(i)], pt,
                                           region.get("crosses_dateline",
                                                      False))
            if d <= snap_max_m and (best is None or d < best[0]):
                best = (d, "NEAREST_COMPONENT",
                        {"terrestrial_hex_id": None,
                         "island_component_id": region["comp_ids"][int(i)],
                         "overlay_unit_id": region["comp_units"][int(i)]},
                        "ISLAND_COMPONENT_OVERLAY")
    if best is not None:
        d, method, fields, kind = best
        return {"land_binding_kind": kind, "binding_method": method,
                "binding_distance_m": round(d, 1), **fields}
    return {"land_binding_kind": "UNRESOLVED", "binding_method": "UNRESOLVED",
            "terrestrial_hex_id": None, "island_component_id": None,
            "overlay_unit_id": None, "binding_distance_m": None}


def bind_point_to_water(pt, region: dict, snap_max_m: float):
    """Water access: containing water hex, else nearest water hex within
    snap_max_m. Distance always recorded."""
    grid = region["grid"]
    q, r = grid.xy_to_axial(float(pt.x), float(pt.y))
    hid = grid.hex_id(q, r)
    wt = region["water_by_hex"].get(hid)
    if wt and wt != "NONE":
        return {"water_access_hex_id": hid, "water_access_type": wt,
                "water_access_distance_m": 0.0}
    best = None
    if len(region["water_polys"]):
        near = region["water_tree"].query(pt.buffer(snap_max_m),
                                          predicate="intersects")
        for i in np.sort(near):
            d = dateline_ground_distance_m(region["water_polys"][int(i)], pt,
                                           region.get("crosses_dateline",
                                                      False))
            if d <= snap_max_m and (best is None or d < best[0]):
                best = (d, int(i))
    if best is not None:
        d, i = best
        return {"water_access_hex_id": region["water_hex_ids"][i],
                "water_access_type": region["water_types"][i],
                "water_access_distance_m": round(d, 1)}
    return {"water_access_hex_id": None, "water_access_type": None,
            "water_access_distance_m": None}


# --------------------------------------------------------------------------
# MAPGEN-007R: bidirectional coast/admin coverage audit (AUDIT ONLY —
# never used for binding, membership, dominance or any gameplay decision)
# --------------------------------------------------------------------------
def _ground_km2(geom) -> float:
    if geom is None or shapely.is_empty(geom):
        return 0.0
    a, _ = ground_area_perimeter(geom)
    return a


def bidirectional_hex_audit(hex_poly, coast_land_in_hex, admin_geoms,
                            match_abs_km2: float,
                            match_rel: float) -> dict:
    """Bidirectional coast/admin mismatch audit for ONE hex.

    A = OSM coast-authority terrestrial land clipped to the hex (passed in
    already clipped). B = union of the NE Admin-0 polygons intersecting the
    hex, clipped to the hex (union FIRST at hex scale, so border-polygon
    micro-overlaps are never double counted). All official values are WGS84
    geodesic ground km2; nothing here modifies either geometry.

    Classification is an AUDIT CLASSIFICATION, not a quality gate: a
    mismatch side counts as significant when it exceeds
    max(match_abs_km2, match_rel * coast_land_ground_km2).
    """
    A = coast_land_in_hex
    if A is not None and not shapely.is_empty(A):
        A = shapely.intersection(hex_poly, A)
    if len(admin_geoms):
        B = shapely.intersection(
            hex_poly, shapely.union_all(list(admin_geoms)))
    else:
        B = None
    a_km2 = _ground_km2(A)
    b_km2 = _ground_km2(B)
    if A is None or shapely.is_empty(A):
        matched, under = 0.0, 0.0
        over = b_km2
    elif B is None or shapely.is_empty(B):
        matched, over = 0.0, 0.0
        under = a_km2
    else:
        matched = _ground_km2(shapely.intersection(A, B))
        under = _ground_km2(shapely.difference(A, B))
        over = _ground_km2(shapely.difference(B, A))
    symdiff = under + over
    tol = max(match_abs_km2, match_rel * a_km2)
    under_sig = under > tol
    over_sig = over > tol
    if under_sig and over_sig:
        cls = "BIDIRECTIONAL_MISMATCH"
    elif under_sig:
        cls = "UNDERCOVERED"
    elif over_sig:
        cls = "OVERCOVERED"
    else:
        cls = "MATCHED"
    frac = (lambda v: round(v / a_km2, 6)) if a_km2 > 0 else (lambda v: None)
    if a_km2 > 0:
        cov = matched / a_km2
        # Explicit float-noise handling only: values in (1, 1+1e-6] are
        # exact-cover hexes measured twice on the ellipsoid; anything
        # beyond that tolerance is left as-is so validation fails loudly.
        if 1.0 < cov <= 1.0 + 1e-6:
            cov = 1.0
        cov = round(cov, 6)
    else:
        cov = None
    return {
        "coast_land_ground_km2": round(a_km2, 6),
        "admin0_union_ground_km2": round(b_km2, 6),
        "matched_ground_km2": round(matched, 6),
        "undercovered_ground_km2": round(under, 6),
        "overcovered_ground_km2": round(over, 6),
        "symmetric_difference_ground_km2": round(symdiff, 6),
        # matched/coast is a true coverage fraction, always within [0, 1].
        "land_coverage_fraction": cov,
        # admin/coast AREA ratio — legitimately exceeds 1 on overcoverage.
        "admin0_to_coast_land_area_ratio": (round(b_km2 / a_km2, 6)
                                            if a_km2 > 0 else None),
        "undercoverage_fraction": frac(under),
        # Denominator = coast_land_ground_km2 (documented in README);
        # null when there is no coast land to compare against.
        "overcoverage_fraction": frac(over),
        "symmetric_difference_fraction": frac(symdiff),
        "coverage_class": cls,
    }


def choose_dominant_admin(entries: list[dict]) -> str | None:
    """Deterministic: max ground area -> stable source id -> reference id.

    A REFERENCE convenience only — never a game owner."""
    if not entries:
        return None
    return min(entries, key=lambda e: (
        -e["intersection_ground_km2"],
        str(e.get("source_stable_id") or ""),
        e["reference_admin_id"]))["reference_admin_id"]
