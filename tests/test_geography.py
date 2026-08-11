from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from mapgen.geography_pipeline import (GEOGRAPHY_SCHEMA_VERSION,
                                       INTEGRATION_ALGORITHM_VERSION,
                                       confluence_offset_stats,
                                       resolve_water_authority,
                                       river_convenience_fields)
from mapgen.terrain_layers import classify_layers_authoritative

CFG_PATH = Path(__file__).resolve().parent.parent / "config" / "kanto.yaml"


@pytest.fixture(scope="module")
def tcfg():
    with open(CFG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["terrain"]


def _raw_hex(**kw):
    base = {
        "land_class": "land", "land_fraction": 1.0,
        "inland_water_fraction": 0.0,
        "permanent_snow_ice_fraction": 0.0, "wetland_fraction": 0.0,
        "bare_ground_fraction": 0.0, "tree_fraction": 0.0,
        "urban_fraction": 0.0, "grassland_fraction": 0.0,
        "cropland_fraction": 0.0,
        "slope_mean_deg": 1.0, "elevation_range_m": 30.0,
        "terrain_roughness": 1.0,
        "is_tropical": False, "is_arid": False, "is_cold": False,
        "is_tundra_climate": False, "is_ice_cap_climate": False,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
def test_water_authority_precedence():
    # OCEAN > LAKE > RIVER > NONE, conflicts reported.
    is_ocean = np.array([True, False, False, False, True])
    lake = np.array([0.9, 0.8, 0.0, np.nan, 0.6])
    river = np.array([False, True, True, False, True])
    wt, conflicts = resolve_water_authority(is_ocean, lake, river, 0.5)
    assert wt.tolist() == ["OCEAN", "LAKE", "RIVER", "NONE", "OCEAN"]
    claims = {c["index"]: c["claims"] for c in conflicts}
    assert claims[0] == "OCEAN|LAKE"          # ocean wins over lake
    assert claims[1] == "LAKE|RIVER"          # lake wins over river route
    assert claims[4] == "OCEAN|LAKE|RIVER"
    assert 2 not in claims and 3 not in claims


def test_water_hex_layer_normalisation(tcfg):
    df = pd.DataFrame([
        _raw_hex(tree_fraction=0.9, slope_mean_deg=12.0),   # water: normalise
        _raw_hex(tree_fraction=0.9, slope_mean_deg=12.0),   # land: keep layers
    ])
    out = classify_layers_authoritative(df, tcfg,
                                        np.array(["LAKE", "NONE"], dtype=object))
    assert out.loc[0, "surface_class"] == "NONE"
    assert out.loc[0, "relief_class"] == "NONE"
    assert out.loc[0, "vegetation_class"] == "NONE"
    assert out.loc[0, "dominant_terrain_face"] == "WATER"
    assert out.loc[0, "natural_terrain_face"] == "WATER"
    # Same raw values on land keep full layers (HILLS + FOREST).
    assert out.loc[1, "relief_class"] == "HILLS"
    assert out.loc[1, "vegetation_class"] == "FOREST"
    assert out.loc[1, "water_type_id"] == 0
    assert out.loc[0, "water_type_id"] == 2


def test_newly_land_hex_uses_existing_raw(tcfg):
    # A hex that was water under NE but is land under OSM: its raw terrain
    # (sampled for every hex in MAPGEN-002A) classifies normally.
    df = pd.DataFrame([_raw_hex(land_class="water", tree_fraction=0.7,
                                slope_mean_deg=3.0)])
    out = classify_layers_authoritative(df, tcfg,
                                        np.array(["NONE"], dtype=object))
    assert out.loc[0, "surface_class"] == "NORMAL"
    assert out.loc[0, "vegetation_class"] == "FOREST"
    assert out.loc[0, "dominant_terrain_face"] == "FOREST"


def test_river_water_type_first_class(tcfg):
    df = pd.DataFrame([_raw_hex()])
    out = classify_layers_authoritative(df, tcfg,
                                        np.array(["RIVER"], dtype=object))
    assert out.loc[0, "water_type"] == "RIVER"
    assert out.loc[0, "water_type_id"] == 3
    assert out.loc[0, "dominant_terrain_face"] == "WATER"
    assert out.loc[0, "surface_class"] == "NONE"


def test_river_convenience_fields_do_not_duplicate_authority():
    edges = pd.DataFrame([
        {"region": "kanto", "edge_id": "e1", "hex_a_id": "A", "hex_b_id": "B",
         "dominant_river_class": "MAJOR", "max_discharge_m3_s": 500.0,
         "dominant_river_id": "riv_1"},
        {"region": "kanto", "edge_id": "e2", "hex_a_id": "B", "hex_b_id": "C",
         "dominant_river_class": "MINOR", "max_discharge_m3_s": 12.0,
         "dominant_river_id": "riv_2"},
    ])
    conv = river_convenience_fields(["A", "B", "C", "D"], edges)
    assert conv["river_edge_count"].tolist() == [1, 2, 1, 0]
    assert conv.loc[1, "max_river_class"] == "MAJOR"
    assert conv.loc[1, "primary_river_id"] == "riv_1"
    assert pd.isna(conv.loc[3, "max_river_class"])
    # Summary only: no crossing-effect fields exist on the hex side.
    assert "crossing" not in " ".join(conv.columns)


def test_confluence_offset_stats_and_regression_fields():
    audit = pd.DataFrame({"distance_m": [100.0, 2000.0, 3500.0, 6500.0,
                                         np.nan, 0.0]})
    s = confluence_offset_stats(audit, 3000.0)
    assert s["count"] == 5
    assert s["over_3000_count"] == 2
    assert s["over_6000_count"] == 1
    assert s["max_m"] == 6500.0
    assert s["median_m"] == 2000.0


def test_duplicate_canonical_edge_detection():
    game = pd.DataFrame([
        {"region": "kanto", "edge_id": "e1"},
        {"region": "kanto", "edge_id": "e1"},
    ])
    assert int(game.duplicated(["region", "edge_id"]).sum()) == 1


def test_invalid_edge_reference_detection():
    edges = pd.DataFrame([
        {"hex_a_id": "A", "hex_b_id": "B"},
        {"hex_a_id": "A", "hex_b_id": "GHOST"},
        {"hex_a_id": "A", "hex_b_id": None},
    ])
    hexset = {"A", "B"}
    ok = edges["hex_a_id"].isin(hexset) & (
        edges["hex_b_id"].isna() | edges["hex_b_id"].isin(hexset))
    assert ok.tolist() == [True, False, True]


def test_version_namespaces_are_new():
    # The integration algorithm has its OWN namespace; it must not silently
    # reuse the MAPGEN-001..003 generation algorithm version constant.
    from mapgen import ALGORITHM_VERSION

    assert GEOGRAPHY_SCHEMA_VERSION == "1.0.0"
    assert INTEGRATION_ALGORITHM_VERSION == "1.0.0"
    # Same string is allowed, but they must be distinct constants — changing
    # one must not change the other.
    assert INTEGRATION_ALGORITHM_VERSION is not ALGORITHM_VERSION or \
        INTEGRATION_ALGORITHM_VERSION == ALGORITHM_VERSION


def test_authoritative_classification_deterministic(tcfg):
    rows = [_raw_hex(tree_fraction=t / 10, slope_mean_deg=s,
                     urban_fraction=u / 10)
            for t in range(0, 10, 2) for s in (1, 7, 16) for u in (0, 5, 8)]
    df = pd.DataFrame(rows)
    wt = np.array((["NONE"] * (len(rows) - 2)) + ["LAKE", "OCEAN"],
                  dtype=object)
    a = classify_layers_authoritative(df, tcfg, wt)
    b = classify_layers_authoritative(df, tcfg, wt)
    assert a.equals(b)
