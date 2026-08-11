"""Layered terrain classification (MAPGEN-002A, terrain schema 3.0.0).

A hex is no longer collapsed to one exclusive terrain label. Each hex carries:

  water layer        (NONE / OCEAN / LAKE / RIVER)
  surface layer      (NORMAL / TUNDRA / DESERT / WETLAND / PERMANENT_SNOW_ICE)
  relief layer       (FLAT / ROLLING / HILLS / MOUNTAIN)
  vegetation layer   (OPEN / FOREST / RAINFOREST) + continuous density
  development layer  (NONE / SETTLED / URBAN / DENSE_URBAN)
  natural_terrain_face / dominant_terrain_face (UI summary only)

"HILLS with FOREST" or "DESERT with MOUNTAIN" are normal states, not
conflicts. Development never erases natural terrain — the natural face is
always recoverable for scenario/era variants. The dominant face is a display
summary and NEVER the sole simulation truth: combat models will read raw
values and layers.

All thresholds come from config ``terrain.layers`` and are provisional.
Enum IDs are stable and must never be renumbered (asset pools / save games).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .terrain_face import FACE_ID

TERRAIN_SCHEMA_VERSION_V3 = "3.1.0"  # 3.1: surface PLAINS renamed to NORMAL; water_type RIVER enabled

WATER_TYPES = [("NONE", 0), ("OCEAN", 1), ("LAKE", 2), ("RIVER", 3)]
# MAPGEN-003: the ordinary land surface is NORMAL (was PLAINS in 2.x — the
# old name clashed with combinations like surface+MOUNTAIN; PLAINS remains a
# DISPLAY face only). The enum id (1) is unchanged.
SURFACE_CLASSES = [("NONE", 0), ("NORMAL", 1), ("TUNDRA", 2), ("DESERT", 3),
                   ("WETLAND", 4), ("PERMANENT_SNOW_ICE", 5)]
RELIEF_CLASSES = [("NONE", 0), ("FLAT", 1), ("ROLLING", 2), ("HILLS", 3),
                  ("MOUNTAIN", 4)]
VEGETATION_CLASSES = [("NONE", 0), ("OPEN", 1), ("FOREST", 2), ("RAINFOREST", 3)]
DEVELOPMENT_CLASSES = [("NONE", 0), ("SETTLED", 1), ("URBAN", 2),
                       ("DENSE_URBAN", 3)]

WATER_TYPE_ID = dict(WATER_TYPES)
SURFACE_ID = dict(SURFACE_CLASSES)
RELIEF_ID = dict(RELIEF_CLASSES)
VEGETATION_ID = dict(VEGETATION_CLASSES)
DEVELOPMENT_ID = dict(DEVELOPMENT_CLASSES)


def _band_confidence(x: np.ndarray, edges: list[float], band_idx: np.ndarray) -> np.ndarray:
    """Confidence of a banded classification: distance to the nearest band
    edge, normalised by half the band width (open-ended bands use the width
    of the neighbouring band). 0 = on an edge, 1 = deep inside the band."""
    x = np.asarray(x, dtype=float)
    conf = np.zeros_like(x)
    bounds = [-np.inf] + list(edges) + [np.inf]
    for i in range(len(bounds) - 1):
        sel = band_idx == i
        if not sel.any():
            continue
        lo, hi = bounds[i], bounds[i + 1]
        if np.isinf(lo):
            width = bounds[i + 2] - hi if not np.isinf(bounds[i + 2]) else hi
            c = np.minimum(1.0, (hi - x[sel]) / (width / 2))
        elif np.isinf(hi):
            width = lo - bounds[i - 1] if not np.isinf(bounds[i - 1]) else lo
            c = np.minimum(1.0, (x[sel] - lo) / (width / 2))
        else:
            half = (hi - lo) / 2
            c = np.minimum(x[sel] - lo, hi - x[sel]) / half
        conf[sel] = np.clip(c, 0.0, 1.0)
    return conf


def classify_water(df: pd.DataFrame, lcfg: dict) -> pd.DataFrame:
    """Water layer. OCEAN from the MAPGEN-001 land/water classification.

    LAKE: land hex whose *inland* water majority remains after subtracting
    the expected sea share. WorldCover's water class includes sea pixels in
    coastal hexes, so the sea share (1 - land_fraction) is deducted first —
    a coastal hex can never become a lake by sea pixels alone.
    """
    thr = float(lcfg["water"]["lake_majority_threshold"])
    is_ocean = (df["land_class"] == "water").to_numpy()
    wc_water = df["inland_water_fraction"].to_numpy(dtype=float)
    sea_share = 1.0 - df["land_fraction"].to_numpy(dtype=float)
    inland_est = np.clip(wc_water - sea_share, 0.0, 1.0)
    is_lake = (~is_ocean) & (inland_est >= thr)

    water_type = np.where(is_ocean, "OCEAN", np.where(is_lake, "LAKE", "NONE"))
    conf = np.where(
        is_ocean, 1.0,
        np.clip(np.abs(inland_est - thr) / thr, 0.0, 1.0),
    )
    return pd.DataFrame({
        "water_type": water_type,
        "water_type_id": [WATER_TYPE_ID[w] for w in water_type],
        "inland_water_est": inland_est,
        "water_confidence": conf,
    }, index=df.index)


def classify_surface(df: pd.DataFrame, lcfg: dict) -> pd.DataFrame:
    """Surface layer: climatic/ground nature, independent of relief.

    Priority: PERMANENT_SNOW_ICE > WETLAND > DESERT > TUNDRA > NORMAL.
    DESERT REQUIRES an arid climate (is_arid) — bare ground in non-arid
    climates (beaches, construction) is absorbed into NORMAL etc.
    """
    c = lcfg["surface"]
    snow = df["permanent_snow_ice_fraction"].to_numpy(dtype=float)
    wet = df["wetland_fraction"].to_numpy(dtype=float)
    bare = df["bare_ground_fraction"].to_numpy(dtype=float)
    icecap = df["is_ice_cap_climate"].to_numpy(dtype=bool)
    arid = df["is_arid"].to_numpy(dtype=bool)
    tundra_cl = df["is_tundra_climate"].to_numpy(dtype=bool)

    is_snow = (snow >= c["snow_ice_threshold"]) | (
        icecap & (snow >= c["icecap_snow_threshold"]))
    is_wet = wet >= c["wetland_threshold"]
    is_desert = arid & (bare >= c["desert_bare_threshold"])

    surface = np.select(
        [is_snow, is_wet, is_desert, tundra_cl],
        ["PERMANENT_SNOW_ICE", "WETLAND", "DESERT", "TUNDRA"],
        default="NORMAL",
    )
    # Confidence: margin of the decisive fraction against its threshold; for
    # PLAINS, how far every special trigger stays below its threshold.
    snow_m = snow / c["snow_ice_threshold"]
    wet_m = wet / c["wetland_threshold"]
    desert_m = np.where(arid, bare / c["desert_bare_threshold"], 0.0)
    conf = np.select(
        [is_snow, is_wet, is_desert, tundra_cl],
        [np.clip(snow_m - 1.0, 0.0, 1.0),
         np.clip(wet_m - 1.0, 0.0, 1.0),
         np.clip(desert_m - 1.0, 0.0, 1.0),
         np.clip(1.0 - np.maximum(snow_m, wet_m), 0.0, 1.0)],
        default=np.clip(1.0 - np.maximum.reduce([snow_m, wet_m, desert_m]),
                        0.0, 1.0),
    )
    return pd.DataFrame({
        "surface_class": surface,
        "surface_class_id": [SURFACE_ID[s] for s in surface],
        "surface_confidence": conf,
    }, index=df.index)


def classify_relief(df: pd.DataFrame, lcfg: dict) -> pd.DataFrame:
    """Relief layer from slope (primary), with a large-local-relief
    alternative entry into MOUNTAIN. Never from absolute elevation alone."""
    c = lcfg["relief"]
    slope = df["slope_mean_deg"].to_numpy(dtype=float)
    erange = df["elevation_range_m"].to_numpy(dtype=float)

    edges = [c["rolling_slope_deg"], c["hills_slope_deg"], c["mountain_slope_deg"]]
    band = np.digitize(slope, edges)  # 0 FLAT, 1 ROLLING, 2 HILLS, 3 MOUNTAIN
    alt_mountain = (slope >= c["mountain_alt_slope_deg"]) & (
        erange >= c["mountain_alt_relief_m"])
    band = np.where(alt_mountain, 3, band)
    names = np.array(["FLAT", "ROLLING", "HILLS", "MOUNTAIN"])
    relief = names[band]
    conf = _band_confidence(slope, edges, band)
    conf = np.where(alt_mountain, np.maximum(conf, 0.5), conf)
    return pd.DataFrame({
        "relief_class": relief,
        "relief_class_id": [RELIEF_ID[r] for r in relief],
        "relief_confidence": conf,
    }, index=df.index)


def classify_vegetation(df: pd.DataFrame, lcfg: dict) -> pd.DataFrame:
    """Vegetation layer. OPEN / FOREST / RAINFOREST plus continuous density.

    No SPARSE class: vegetation_density (= tree_fraction) already carries the
    continuum, and asset placement uses class+density, so a fourth class
    would add boundaries without adding information.
    Conifer/broadleaf is not split visually (WorldCover v200 does not
    distinguish them; nothing extra to preserve).
    """
    thr = float(lcfg["vegetation"]["forest_tree_threshold"])
    tree = df["tree_fraction"].to_numpy(dtype=float)
    tropical = df["is_tropical"].to_numpy(dtype=bool)
    forested = tree >= thr
    veg = np.where(forested, np.where(tropical, "RAINFOREST", "FOREST"), "OPEN")
    conf = np.clip(np.abs(tree - thr) / thr, 0.0, 1.0)
    return pd.DataFrame({
        "vegetation_class": veg,
        "vegetation_class_id": [VEGETATION_ID[v] for v in veg],
        "vegetation_density": tree,
        "vegetation_confidence": conf,
    }, index=df.index)


def classify_development(df: pd.DataFrame, lcfg: dict) -> pd.DataFrame:
    """Development layer, fully independent of natural terrain. The 2021
    WorldCover built-up state is the current-era baseline; scenarios may
    overwrite this layer later without touching natural terrain."""
    c = lcfg["development"]
    urban = df["urban_fraction"].to_numpy(dtype=float)
    edges = [c["settled_threshold"], c["urban_threshold"], c["dense_urban_threshold"]]
    band = np.digitize(urban, edges)
    names = np.array(["NONE", "SETTLED", "URBAN", "DENSE_URBAN"])
    dev = names[band]
    conf = _band_confidence(urban, edges, band)
    return pd.DataFrame({
        "development_class": dev,
        "development_class_id": [DEVELOPMENT_ID[d] for d in dev],
        "development_confidence": conf,
    }, index=df.index)


def _face_chain(layers: pd.DataFrame, lcfg: dict, with_development: bool):
    """Representative face from the layers (priority chain, not scores)."""
    dcfg = lcfg["dominant"]
    n = len(layers)
    face = np.full(n, "PLAINS", dtype=object)
    conf = layers["surface_confidence"].to_numpy(dtype=float).copy()

    water = layers["water_type"].to_numpy() != "NONE"
    snow = layers["surface_class"].to_numpy() == "PERMANENT_SNOW_ICE"
    mountain = layers["relief_class"].to_numpy() == "MOUNTAIN"
    hills = layers["relief_class"].to_numpy() == "HILLS"
    hills_strong = hills & (
        layers["slope_mean_deg"].to_numpy(dtype=float)
        >= dcfg["hills_dominant_slope_deg"])
    surface = layers["surface_class"].to_numpy()
    veg = layers["vegetation_class"].to_numpy()

    dev_order = ["NONE", "SETTLED", "URBAN", "DENSE_URBAN"]
    min_dev = dev_order.index(dcfg["urban_face_min_class"])
    dev_rank = np.array([dev_order.index(d)
                         for d in layers["development_class"]])
    urban_face = with_development & (dev_rank >= min_dev)

    relief_conf = layers["relief_confidence"].to_numpy(dtype=float)
    veg_conf = layers["vegetation_confidence"].to_numpy(dtype=float)
    surf_conf = layers["surface_confidence"].to_numpy(dtype=float)
    dev_conf = layers["development_confidence"].to_numpy(dtype=float)
    water_conf = layers["water_confidence"].to_numpy(dtype=float)

    # Priority chain, later assignments win — so apply in reverse priority.
    veg_face = np.isin(veg, ["FOREST", "RAINFOREST"])
    face[hills] = "HILLS"
    conf[hills] = relief_conf[hills]
    face[veg_face] = veg[veg_face]
    conf[veg_face] = veg_conf[veg_face]
    special = np.isin(surface, ["DESERT", "TUNDRA", "WETLAND"])
    face[special] = surface[special]
    conf[special] = surf_conf[special]
    face[hills_strong] = "HILLS"
    conf[hills_strong] = relief_conf[hills_strong]
    face[mountain] = "MOUNTAIN"
    conf[mountain] = relief_conf[mountain]
    if with_development:
        face[urban_face] = "URBAN"
        conf[urban_face] = dev_conf[urban_face]
    face[snow] = "PERMANENT_SNOW_ICE"
    conf[snow] = surf_conf[snow]
    face[water] = "WATER"
    conf[water] = water_conf[water]
    return face, np.clip(conf, 0.0, 1.0)


def classify_layers_authoritative(df: pd.DataFrame, tcfg: dict,
                                  water_type: np.ndarray) -> pd.DataFrame:
    """Layered classification with an EXTERNAL water authority (MAPGEN-004).

    Identical to classify_layers except the water layer is supplied (from the
    hydro pipeline: OSM coast + HydroLAKES + WATER_HEX_RIVER) instead of the
    WorldCover estimate. Surface/relief/vegetation/development come from the
    same raw values and the same classifiers; water hexes are normalised to
    NONE terrain layers, and RIVER is a first-class water type.
    """
    lcfg = tcfg["layers"]
    water_type = np.asarray(water_type, dtype=object)
    out = pd.concat([
        classify_surface(df, lcfg),
        classify_relief(df, lcfg),
        classify_vegetation(df, lcfg),
        classify_development(df, lcfg),
    ], axis=1)
    out.insert(0, "water_type", water_type)
    out.insert(1, "water_type_id",
               np.array([WATER_TYPE_ID[w] for w in water_type], dtype=np.int64))
    out.insert(2, "water_confidence", 1.0)  # authoritative source

    is_water_hex = out["water_type"] != "NONE"
    for col, id_col in (("surface_class", "surface_class_id"),
                        ("relief_class", "relief_class_id"),
                        ("vegetation_class", "vegetation_class_id")):
        out.loc[is_water_hex, col] = "NONE"
        out.loc[is_water_hex, id_col] = 0

    helper = pd.concat([out, df[["slope_mean_deg"]]], axis=1)
    natural, nat_conf = _face_chain(helper, lcfg, with_development=False)
    dominant, dom_conf = _face_chain(helper, lcfg, with_development=True)
    out["natural_terrain_face"] = natural
    out["natural_terrain_face_id"] = [FACE_ID[f] for f in natural]
    out["dominant_terrain_face"] = dominant
    out["dominant_terrain_face_id"] = [FACE_ID[f] for f in dominant]
    out["dominant_face_confidence"] = dom_conf
    return out


def classify_layers(df: pd.DataFrame, tcfg: dict) -> pd.DataFrame:
    """Full layered classification. Input df needs raw terrain + climate
    flags + land_class/land_fraction. Returns all layer columns."""
    lcfg = tcfg["layers"]
    out = pd.concat([
        classify_water(df, lcfg),
        classify_surface(df, lcfg),
        classify_relief(df, lcfg),
        classify_vegetation(df, lcfg),
        classify_development(df, lcfg),
    ], axis=1)

    # Water hexes: surface/relief/vegetation stay as computed (sea-floor
    # values are meaningless but harmless); mark the classes NONE for clarity.
    is_water_hex = out["water_type"] != "NONE"
    for col, id_col in (("surface_class", "surface_class_id"),
                        ("relief_class", "relief_class_id"),
                        ("vegetation_class", "vegetation_class_id"),
                        ("development_class", "development_class_id")):
        if col == "development_class":
            continue  # development can exist on reclaimed/lakeside hexes
        out.loc[is_water_hex, col] = "NONE"
        out.loc[is_water_hex, id_col] = 0

    helper = pd.concat(
        [out, df[["slope_mean_deg"]]], axis=1
    )
    natural, nat_conf = _face_chain(helper, lcfg, with_development=False)
    dominant, dom_conf = _face_chain(helper, lcfg, with_development=True)
    out["natural_terrain_face"] = natural
    out["natural_terrain_face_id"] = [FACE_ID[f] for f in natural]
    out["dominant_terrain_face"] = dominant
    out["dominant_terrain_face_id"] = [FACE_ID[f] for f in dominant]
    out["dominant_face_confidence"] = dom_conf
    out = out.drop(columns=["slope_mean_deg"], errors="ignore")
    return out
