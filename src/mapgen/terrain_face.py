"""Terrain face scoring and classification (MAPGEN-002).

Design principle: terrain_face is the representative "face" shown to the
player, NOT the simulation data itself. All raw fractions and relief metrics
are preserved alongside it; future combat models consume the raw values.

Every face gets a score; terrain_face = argmax(score) with one priority rule
(water hexes are always WATER). All numeric parameters come from the
``terrain:`` config section and are provisional until the ChatGPT review —
nothing here hard-fixes the weights.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .raster import KOPPEN_CODES

TERRAIN_SCHEMA_VERSION = "2.0.0"

# Stable enum: IDs must never change once assets/save games reference them.
TERRAIN_FACES = [
    ("WATER", 0),
    ("PLAINS", 1),
    ("FOREST", 2),
    ("RAINFOREST", 3),
    ("TUNDRA", 4),
    ("DESERT", 5),
    ("WETLAND", 6),
    ("HILLS", 7),
    ("MOUNTAIN", 8),
    ("URBAN", 9),
    ("PERMANENT_SNOW_ICE", 10),
]
FACE_ID = {name: fid for name, fid in TERRAIN_FACES}

# Fixed rendering colours — must stay stable across runs.
FACE_COLORS = {
    "WATER": "#b3cde3",
    "PLAINS": "#d5d98b",
    "FOREST": "#4f8f4f",
    "RAINFOREST": "#1e6b3a",
    "TUNDRA": "#aebcae",
    "DESERT": "#e8c56b",
    "WETLAND": "#6fa8a0",
    "HILLS": "#b09a6a",
    "MOUNTAIN": "#8a7f77",
    "URBAN": "#9e4a4a",
    "PERMANENT_SNOW_ICE": "#f0f0f5",
}

SCORE_COLUMNS = [
    "plains_score", "forest_score", "rainforest_score", "tundra_score",
    "desert_score", "wetland_score", "hills_score", "mountain_score",
    "urban_score", "permanent_snow_ice_score",
]


def ramp(x, low, high):
    """0 below low, 1 above high, linear in between. Vectorised."""
    x = np.asarray(x, dtype=float)
    return np.clip((x - low) / (high - low), 0.0, 1.0)


def climate_flags(koppen_class: np.ndarray) -> pd.DataFrame:
    """Derive climate_zone / biome_class / boolean flags from Koeppen classes.

    koppen_class: int array, 0 = no data, 1..30 = Beck et al. V2 classes.
    """
    codes = np.asarray(koppen_class, dtype=int)
    zone = np.array(["unknown"] + KOPPEN_CODES, dtype=object)[np.clip(codes, 0, 30)]
    letter = np.array([z[0] if z != "unknown" else "?" for z in zone])

    biome_map = {
        "A": "tropical", "B": "arid", "C": "temperate",
        "D": "continental", "E": "polar", "?": "unknown",
    }
    biome = np.array([biome_map[l] for l in letter], dtype=object)
    is_et = zone == "ET"
    is_ef = zone == "EF"
    return pd.DataFrame({
        "climate_zone": zone,
        "biome_class": biome,
        "is_tropical": letter == "A",
        "is_arid": letter == "B",
        "is_cold": (letter == "D") | (letter == "E"),
        "is_tundra_climate": is_et,
        "is_ice_cap_climate": is_ef,
    })


def compute_scores(df: pd.DataFrame, tcfg: dict) -> pd.DataFrame:
    """Compute all terrain face scores from raw per-hex terrain data.

    ``df`` needs the lc_*_fraction columns, slope/roughness/elevation stats and
    the climate flag columns. Returns a DataFrame with SCORE_COLUMNS.
    """
    rc = tcfg["relief"]
    fc = tcfg["faces"]

    slope = df["slope_mean_deg"].to_numpy(dtype=float)
    rough = df["terrain_roughness"].to_numpy(dtype=float)
    erange = df["elevation_range_m"].to_numpy(dtype=float)

    tree = df["lc_tree_fraction"].to_numpy(dtype=float)
    shrub = df["lc_shrub_fraction"].to_numpy(dtype=float)
    grass = df["lc_grassland_fraction"].to_numpy(dtype=float)
    crop = df["lc_cropland_fraction"].to_numpy(dtype=float)
    built = df["lc_built_up_fraction"].to_numpy(dtype=float)
    bare = df["lc_bare_sparse_fraction"].to_numpy(dtype=float)
    snow = df["lc_snow_ice_fraction"].to_numpy(dtype=float)
    wet = (df["lc_herbaceous_wetland_fraction"] + df["lc_mangroves_fraction"]).to_numpy(dtype=float)
    moss = df["lc_moss_lichen_fraction"].to_numpy(dtype=float)

    tropical = df["is_tropical"].to_numpy(dtype=bool)
    arid = df["is_arid"].to_numpy(dtype=bool)
    tundra_cl = df["is_tundra_climate"].to_numpy(dtype=bool)
    icecap_cl = df["is_ice_cap_climate"].to_numpy(dtype=bool)

    # Vegetation/open faces are damped on steep relief so MOUNTAIN can win
    # even against high forest fractions ("mountain overrides forest").
    relief_damp = 1.0 - rc["veg_suppression_max"] * ramp(
        slope, rc["veg_suppression_slope_low_deg"], rc["veg_suppression_slope_high_deg"]
    )

    p = fc["plains"]
    plains = (p["open_weight"] * (grass + crop)
              + p["shrub_weight"] * shrub
              + p["moss_weight"] * moss) * relief_damp
    # Tundra climate hands low open vegetation over to TUNDRA.
    plains = np.where(tundra_cl, plains * 0.3, plains)

    forest = fc["forest"]["tree_weight"] * tree * relief_damp
    rainforest = np.where(
        tropical, fc["rainforest"]["tree_weight"] * tree * relief_damp, 0.0
    )

    t = fc["tundra"]
    tundra = np.where(
        tundra_cl,
        (t["cover_weight"] * (moss + 0.6 * grass + 0.4 * shrub + 0.3 * bare)
         + t["base_bonus"]) * (1.0 - tree),
        0.0,
    )

    d = fc["desert"]
    desert = d["bare_weight"] * bare * np.where(
        arid, d["arid_factor"], d["non_arid_factor"]
    )

    wetland = fc["wetland"]["wetland_weight"] * wet * relief_damp
    urban = fc["urban"]["urban_weight"] * built

    s = fc["permanent_snow_ice"]
    snow_ice = s["snow_weight"] * snow + np.where(icecap_cl, s["icecap_bonus"], 0.0)

    hills = rc["hills_weight"] * ramp(
        slope, rc["hills_slope_low_deg"], rc["hills_slope_high_deg"]
    ) * (1.0 - ramp(slope, rc["hills_fade_low_deg"], rc["hills_fade_high_deg"]))

    w_sum = (rc["mountain_slope_weight"] + rc["mountain_roughness_weight"]
             + rc["mountain_relief_weight"])
    mountain = rc["mountain_weight"] * (
        rc["mountain_slope_weight"] * ramp(slope, rc["mountain_slope_low_deg"],
                                           rc["mountain_slope_high_deg"])
        + rc["mountain_roughness_weight"] * ramp(rough, rc["mountain_roughness_low_m"],
                                                 rc["mountain_roughness_high_m"])
        + rc["mountain_relief_weight"] * ramp(erange, rc["mountain_relief_low_m"],
                                              rc["mountain_relief_high_m"])
    ) / w_sum

    return pd.DataFrame({
        "plains_score": plains,
        "forest_score": forest,
        "rainforest_score": rainforest,
        "tundra_score": tundra,
        "desert_score": desert,
        "wetland_score": wetland,
        "hills_score": hills,
        "mountain_score": mountain,
        "urban_score": urban,
        "permanent_snow_ice_score": snow_ice,
    }, index=df.index)


def classify(df: pd.DataFrame, scores: pd.DataFrame,
             is_water: np.ndarray) -> pd.DataFrame:
    """Pick terrain_face / runner-up / confidence from the score table.

    Priority rule: water hexes (existing land/water classification) are WATER
    regardless of scores. confidence = (winner - runner_up) / winner
    (0 = tie or no signal, 1 = unchallenged winner).
    """
    face_names = np.array([c.replace("_score", "").upper() for c in SCORE_COLUMNS])
    mat = scores[SCORE_COLUMNS].to_numpy(dtype=float)
    order = np.argsort(-mat, axis=1)
    win_i = order[:, 0]
    run_i = order[:, 1]
    n = len(df)
    rows = np.arange(n)
    win_score = mat[rows, win_i]
    run_score = mat[rows, run_i]
    face = face_names[win_i].astype(object)
    second = face_names[run_i].astype(object)
    with np.errstate(invalid="ignore", divide="ignore"):
        conf = np.where(win_score > 0, (win_score - run_score) / win_score, 0.0)

    face = np.where(is_water, "WATER", face)
    second = np.where(is_water, "WATER", second)
    win_score = np.where(is_water, 1.0, win_score)
    run_score = np.where(is_water, 0.0, run_score)
    conf = np.where(is_water, 1.0, conf)

    face_id = np.array([FACE_ID[f] for f in face], dtype=np.int64)
    return pd.DataFrame({
        "terrain_face": face,
        "terrain_face_id": face_id,
        "terrain_face_score": win_score,
        "terrain_face_second": second,
        "terrain_face_second_score": run_score,
        "terrain_face_confidence": conf,
    }, index=df.index)


def military_metrics(df: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    """Provisional derived military metrics, 0..1 normalised.

    Deliberately simple: these are placeholders proving the structure; the
    real combat model will be built later from the preserved raw data.
    """
    def _col(*names):
        for name in names:
            if name in df.columns:
                return df[name].to_numpy(dtype=float)
        raise KeyError(names)

    slope = df["slope_mean_deg"].to_numpy(dtype=float)
    rough = df["terrain_roughness"].to_numpy(dtype=float)
    tree = _col("tree_fraction", "lc_tree_fraction")
    if "wetland_fraction" in df.columns:
        wet = df["wetland_fraction"].to_numpy(dtype=float)
    else:
        wet = (df["lc_herbaceous_wetland_fraction"]
               + df["lc_mangroves_fraction"]).to_numpy(dtype=float)
    built = _col("urban_fraction", "lc_built_up_fraction")
    snow = _col("permanent_snow_ice_fraction", "lc_snow_ice_fraction")

    slope_pen = ramp(slope, 2.0, 30.0)
    foot = np.clip(1.0 - 0.6 * slope_pen - 0.5 * wet - 0.3 * snow, 0.0, 1.0)
    wheeled = np.clip(1.0 - 1.0 * ramp(slope, 1.5, 15.0) - 0.8 * wet
                      - 0.3 * tree - 0.4 * snow, 0.0, 1.0)
    tracked = np.clip(1.0 - 0.8 * ramp(slope, 2.0, 20.0) - 0.7 * wet
                      - 0.2 * tree - 0.3 * snow, 0.0, 1.0)
    concealment = np.clip(0.75 * tree + 0.6 * built + 0.15 * ramp(rough, 5, 30), 0.0, 1.0)
    visibility = np.clip(1.0 - concealment, 0.0, 1.0)
    defensive = np.clip(0.4 * ramp(slope, 3.0, 20.0) + 0.3 * ramp(rough, 5, 30)
                        + 0.35 * built + 0.2 * tree, 0.0, 1.0)
    logistics = np.clip(1.0 - 0.7 * slope_pen - 0.7 * wet - 0.5 * snow, 0.0, 1.0)
    construction = np.clip(1.0 - 0.8 * slope_pen - 0.9 * wet - 0.8 * snow, 0.0, 1.0)
    deployment = np.clip(1.0 - 0.7 * slope_pen - 0.8 * wet - 0.4 * tree, 0.0, 1.0)

    return pd.DataFrame({
        "foot_mobility": foot,
        "wheeled_mobility": wheeled,
        "tracked_mobility": tracked,
        "visibility": visibility,
        "concealment": concealment,
        "defensive_value": defensive,
        "logistics_passability": logistics,
        "construction_suitability": construction,
        "deployment_capacity": deployment,
    }, index=df.index)
