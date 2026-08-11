"""HydroRIVERS loading, importance classification and branch decomposition
(MAPGEN-003).

Only militarily meaningful rivers enter the game. Classification is driven by
HydroRIVERS mean discharge (DIS_AV_CMS) with all thresholds in config —
provisional, tuned against known rivers, never finalised here.

Provider isolation: only the fields below leave this module; the game schema
never exposes HydroRIVERS-specific columns directly, so the source network
(e.g. a future HydroSHEDS v2) can be swapped behind this interface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely

RIVER_CLASSES = ["MINOR", "MEDIUM", "MAJOR", "GREAT"]  # ascending
RIVER_CLASS_ID = {c: i + 1 for i, c in enumerate(RIVER_CLASSES)}  # IGNORED=0


def classify_discharge(dis_cms: float, thresholds: dict) -> str | None:
    """River class from mean discharge; None = ignored (below MINOR)."""
    for cls in reversed(RIVER_CLASSES):
        if dis_cms >= thresholds[cls]:
            return cls
    return None


def estimate_width_m(dis_cms, wcfg: dict):
    """Empirical hydraulic-geometry width estimate w = a * Q^b (metres).

    HydroRIVERS carries no usable width; this estimate (and later optional
    GRWL/OSM widths) feeds representation decisions. Both the source estimate
    and the separately-exaggerated game width are preserved.
    """
    return wcfg["coefficient"] * np.power(np.maximum(dis_cms, 0.0),
                                          wcfg["exponent"])


@dataclass
class Branch:
    """A chain of reaches between network junctions (confluence/source/mouth)."""
    branch_id: str
    reach_ids: list[int]
    line: shapely.LineString          # EPSG:3857, upstream -> downstream
    discharge_cms: float              # at downstream end
    strahler: int
    river_class: str
    main_riv: int                     # HydroRIVERS MAIN_RIV of the chain
    next_down_reach: int              # HYRIV_ID of the reach it flows into (0 = mouth)
    source_length_m: float = 0.0       # PROJECTED metres (EPSG:3857), same
    #                                    unit as snapped lengths — never mix
    #                                    with ground km (Mercator factor!)
    source_length_ground_km: float = 0.0  # HydroRIVERS LENGTH_KM (ground)
    width_est_m: float = 0.0
    name: str | None = None
    representation: str = "EDGE_RIVER"
    endorheic: int = 0                # 0 = drains to the ocean (HydroRIVERS)


def load_reaches(shp_path: Path, bbox_wgs84: tuple[float, float, float, float],
                 thresholds: dict) -> gpd.GeoDataFrame:
    """Reaches in bbox with class >= MINOR, projected to EPSG:3857."""
    gdf = gpd.read_file(shp_path, bbox=bbox_wgs84)
    if gdf.empty:
        return gdf
    gdf = gdf[gdf["DIS_AV_CMS"] >= thresholds["MINOR"]].copy()
    if gdf.empty:
        return gdf
    gdf = gdf.to_crs("EPSG:3857")
    gdf["river_class"] = [classify_discharge(d, thresholds)
                          for d in gdf["DIS_AV_CMS"]]
    return gdf.sort_values("HYRIV_ID").reset_index(drop=True)


def decompose_branches(reaches: gpd.GeoDataFrame, thresholds: dict,
                       wcfg: dict) -> list[Branch]:
    """Split the filtered reach network into branches.

    A branch is a maximal downstream chain whose internal reaches have exactly
    one filtered upstream contributor; branches end at confluences (>= 2
    contributors), at the mouth, or where the network leaves the bbox/filter.
    """
    if reaches.empty:
        return []
    by_id = {int(r.HYRIV_ID): r for r in reaches.itertuples()}
    in_set = set(by_id)
    n_upstream: dict[int, int] = {}
    for rid, row in by_id.items():
        nd = int(row.NEXT_DOWN)
        if nd in in_set:
            n_upstream[nd] = n_upstream.get(nd, 0) + 1

    # Branch heads: reaches with 0 or >=2 filtered upstream contributors.
    heads = [rid for rid in sorted(in_set) if n_upstream.get(rid, 0) != 1]
    branches: list[Branch] = []
    for head in heads:
        chain = [head]
        cur = head
        while True:
            nd = int(by_id[cur].NEXT_DOWN)
            if nd not in in_set or n_upstream.get(nd, 0) != 1:
                break
            chain.append(nd)
            cur = nd
        rows = [by_id[rid] for rid in chain]
        merged = shapely.line_merge(
            shapely.union_all([r.geometry for r in rows]))
        # line_merge may keep MultiLineString on tiny gaps; take longest part
        # but record the defect via source components (handled upstream).
        if merged.geom_type == "MultiLineString":
            parts = list(shapely.get_parts(merged))
            merged = max(parts, key=lambda p: p.length)
        # Orient upstream -> downstream: the downstream end is the end of the
        # LAST reach in the chain.
        tail_end = shapely.get_coordinates(rows[-1].geometry)[-1]
        coords = shapely.get_coordinates(merged)
        if (np.hypot(*(coords[0] - tail_end))
                < np.hypot(*(coords[-1] - tail_end))):
            merged = shapely.reverse(merged)
        last = rows[-1]
        dis = float(last.DIS_AV_CMS)
        branches.append(Branch(
            branch_id=f"br_{chain[0]}",
            reach_ids=chain,
            line=merged,
            discharge_cms=dis,
            strahler=int(last.ORD_STRA),
            river_class=classify_discharge(dis, thresholds),
            main_riv=int(last.MAIN_RIV),
            next_down_reach=int(last.NEXT_DOWN) if int(last.NEXT_DOWN) in in_set
            else 0,
            # Projected length — the ONLY length comparable with snapped
            # edge lengths. Using LENGTH_KM here was the MAPGEN-003 bug that
            # inflated length_ratio by the Mercator factor (1.62 at 52N).
            source_length_m=float(merged.length),
            source_length_ground_km=float(sum(r.LENGTH_KM for r in rows)),
            width_est_m=float(estimate_width_m(dis, wcfg)),
            endorheic=int(last.ENDORHEIC),
        ))
    # Importance descending: big rivers are snapped first and stay stable.
    branches.sort(key=lambda b: -b.discharge_cms)
    return branches


def name_branches(branches: list[Branch], named_rivers: list[dict],
                  reaches: gpd.GeoDataFrame) -> None:
    """Attach human names from config seed points (HydroRIVERS has no names).

    The seed's nearest reach identifies a MAIN_RIV id; every branch on the
    maximal-discharge chain of that MAIN_RIV downstream of the seed gets the
    name (enough for validation metrics).
    """
    if reaches.empty:
        return
    from .projection import to_mercator

    branch_by_reach = {}
    for b in branches:
        for rid in b.reach_ids:
            branch_by_reach[rid] = b
    geoms = reaches.geometry.values
    for spec in named_rivers:
        x, y = to_mercator(spec["lon"], spec["lat"])
        pt = shapely.Point(float(x), float(y))
        dists = shapely.distance(geoms, pt)
        idx = int(np.argmin(dists))
        if dists[idx] > 15000:
            continue
        seed = reaches.iloc[idx]
        b = branch_by_reach.get(int(seed.HYRIV_ID))
        # Name the whole downstream chain of branches.
        while b is not None and b.name is None:
            b.name = spec["name"]
            b = branch_by_reach.get(b.next_down_reach)
