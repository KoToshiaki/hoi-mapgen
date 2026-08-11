from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from mapgen.raster import KOPPEN_CODES
from mapgen.terrain_face import (FACE_ID, classify, climate_flags,
                                 compute_scores, military_metrics)

CFG_PATH = Path(__file__).resolve().parent.parent / "config" / "kanto.yaml"


@pytest.fixture(scope="module")
def tcfg():
    with open(CFG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["terrain"]


def _row(**kw):
    base = {
        "slope_mean_deg": 1.0, "terrain_roughness": 1.0, "elevation_range_m": 20.0,
        "lc_tree_fraction": 0.0, "lc_shrub_fraction": 0.0,
        "lc_grassland_fraction": 0.0, "lc_cropland_fraction": 0.0,
        "lc_built_up_fraction": 0.0, "lc_bare_sparse_fraction": 0.0,
        "lc_snow_ice_fraction": 0.0, "lc_herbaceous_wetland_fraction": 0.0,
        "lc_mangroves_fraction": 0.0, "lc_moss_lichen_fraction": 0.0,
        "koppen": "Cfb", "water": False,
    }
    base.update(kw)
    return base


CASES = [
    ("PLAINS", _row(lc_grassland_fraction=0.5, lc_cropland_fraction=0.4)),
    ("FOREST", _row(lc_tree_fraction=0.8, slope_mean_deg=2.0)),
    ("RAINFOREST", _row(lc_tree_fraction=0.9, koppen="Af")),
    ("DESERT", _row(lc_bare_sparse_fraction=0.95, koppen="BWh")),
    ("WETLAND", _row(lc_herbaceous_wetland_fraction=0.5,
                     lc_grassland_fraction=0.3)),
    ("HILLS", _row(slope_mean_deg=6.0, lc_grassland_fraction=0.3,
                   lc_tree_fraction=0.2, terrain_roughness=8.0)),
    ("MOUNTAIN", _row(slope_mean_deg=25.0, terrain_roughness=30.0,
                      elevation_range_m=1500.0, lc_tree_fraction=0.6)),
    ("URBAN", _row(lc_built_up_fraction=0.6, lc_grassland_fraction=0.2)),
    ("TUNDRA", _row(koppen="ET", lc_moss_lichen_fraction=0.5,
                    lc_grassland_fraction=0.3, lc_tree_fraction=0.05)),
    ("PERMANENT_SNOW_ICE", _row(lc_snow_ice_fraction=0.8, koppen="EF")),
    ("WATER", _row(water=True, lc_tree_fraction=0.9)),
]


def _build_df(cases):
    df = pd.DataFrame([c[1] for c in cases])
    kop = np.array([KOPPEN_CODES.index(k) + 1 for k in df["koppen"]])
    df = pd.concat([df, climate_flags(kop)], axis=1)
    return df


def test_expected_faces_win(tcfg):
    df = _build_df(CASES)
    scores = compute_scores(df, tcfg)
    result = classify(df, scores, df["water"].to_numpy())
    for (expected, _), face in zip(CASES, result["terrain_face"]):
        assert face == expected, f"expected {expected}, got {face}"
    # Rainforest case: FOREST must be the runner-up, proving both scored.
    rf = result.iloc[2]
    assert rf["terrain_face_second"] == "FOREST"
    assert 0 < rf["terrain_face_confidence"] < 1


def test_face_ids_stable(tcfg):
    assert FACE_ID["WATER"] == 0
    assert FACE_ID["PLAINS"] == 1
    assert FACE_ID["MOUNTAIN"] == 8
    assert FACE_ID["PERMANENT_SNOW_ICE"] == 10


def test_deterministic(tcfg):
    df = _build_df(CASES)
    s1 = compute_scores(df, tcfg)
    s2 = compute_scores(df, tcfg)
    assert np.array_equal(s1.to_numpy(), s2.to_numpy())
    r1 = classify(df, s1, df["water"].to_numpy())
    r2 = classify(df, s2, df["water"].to_numpy())
    assert r1["terrain_face"].tolist() == r2["terrain_face"].tolist()
    assert np.array_equal(r1["terrain_face_confidence"], r2["terrain_face_confidence"])


def test_no_signal_hex_does_not_crash(tcfg):
    # All-zero raw data (e.g. total nodata) must classify without errors and
    # produce zero confidence, not a silent failure elsewhere.
    df = _build_df([("X", _row())])
    scores = compute_scores(df, tcfg)
    res = classify(df, scores, np.array([False]))
    assert res.loc[0, "terrain_face_confidence"] == 0.0


def test_climate_flags():
    kop = np.array([KOPPEN_CODES.index(k) + 1 for k in ["Af", "BWh", "Dfb", "ET", "EF"]]
                   + [0])
    flags = climate_flags(kop)
    assert flags["is_tropical"].tolist() == [True, False, False, False, False, False]
    assert flags["is_arid"].tolist() == [False, True, False, False, False, False]
    assert flags["is_cold"].tolist() == [False, False, True, True, True, False]
    assert flags["is_tundra_climate"].tolist() == [False, False, False, True, False, False]
    assert flags["is_ice_cap_climate"].tolist() == [False, False, False, False, True, False]
    assert flags.loc[5, "climate_zone"] == "unknown"


def test_military_metrics_range(tcfg):
    df = _build_df(CASES)
    scores = compute_scores(df, tcfg)
    mil = military_metrics(df, scores)
    assert ((mil >= 0.0) & (mil <= 1.0)).all().all()
    # Steep mountain hex must be less mobile than flat plains hex.
    assert mil.loc[6, "foot_mobility"] < mil.loc[0, "foot_mobility"]
    assert mil.loc[6, "wheeled_mobility"] < mil.loc[0, "wheeled_mobility"]
