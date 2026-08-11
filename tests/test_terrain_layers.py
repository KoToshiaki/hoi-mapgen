from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from mapgen.terrain_layers import (DEVELOPMENT_ID, RELIEF_ID, SURFACE_ID,
                                   TERRAIN_SCHEMA_VERSION_V3, VEGETATION_ID,
                                   WATER_TYPE_ID, classify_layers)

CFG_PATH = Path(__file__).resolve().parent.parent / "config" / "kanto.yaml"


@pytest.fixture(scope="module")
def tcfg():
    with open(CFG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["terrain"]


def _hex(**kw):
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


def _classify(tcfg, *rows):
    df = pd.DataFrame(list(rows))
    return classify_layers(df, tcfg)


def test_non_arid_bare_ground_is_not_desert(tcfg):
    # The Netherlands bug: bare ground without an arid climate.
    out = _classify(tcfg, _hex(bare_ground_fraction=0.9, is_arid=False))
    assert out.loc[0, "surface_class"] == "NORMAL"
    assert out.loc[0, "dominant_terrain_face"] != "DESERT"


def test_arid_bare_ground_is_desert(tcfg):
    out = _classify(tcfg, _hex(bare_ground_fraction=0.9, is_arid=True))
    assert out.loc[0, "surface_class"] == "DESERT"
    assert out.loc[0, "dominant_terrain_face"] == "DESERT"


def test_hills_and_forest_coexist(tcfg):
    # Boso: 92% forest on 10-degree hills 窶・BOTH layers hold simultaneously.
    out = _classify(tcfg, _hex(tree_fraction=0.92, slope_mean_deg=10.0,
                               terrain_roughness=12.0))
    assert out.loc[0, "relief_class"] == "HILLS"
    assert out.loc[0, "vegetation_class"] == "FOREST"
    assert out.loc[0, "vegetation_density"] == pytest.approx(0.92)
    # Display face is HILLS (slope over hills_dominant threshold), but no
    # information was lost.
    assert out.loc[0, "dominant_terrain_face"] == "HILLS"


def test_mountain_and_forest_coexist(tcfg):
    out = _classify(tcfg, _hex(tree_fraction=0.85, slope_mean_deg=20.0,
                               elevation_range_m=1400.0))
    assert out.loc[0, "relief_class"] == "MOUNTAIN"
    assert out.loc[0, "vegetation_class"] == "FOREST"
    assert out.loc[0, "dominant_terrain_face"] == "MOUNTAIN"


def test_dense_urban_preserves_natural_terrain(tcfg):
    # Central Tokyo: development never erases the natural terrain.
    out = _classify(tcfg, _hex(urban_fraction=0.9, grassland_fraction=0.05))
    assert out.loc[0, "development_class"] == "DENSE_URBAN"
    assert out.loc[0, "dominant_terrain_face"] == "URBAN"
    assert out.loc[0, "natural_terrain_face"] == "PLAINS"
    assert out.loc[0, "surface_class"] == "NORMAL"
    assert out.loc[0, "relief_class"] == "FLAT"


def test_moderate_urban_does_not_take_display_face(tcfg):
    # Suburbs (the MAPGEN-002 over-URBAN bug): 0.4 built-up is URBAN class
    # but the display face stays natural.
    out = _classify(tcfg, _hex(urban_fraction=0.4, grassland_fraction=0.3,
                               cropland_fraction=0.2))
    assert out.loc[0, "development_class"] == "URBAN"
    assert out.loc[0, "dominant_terrain_face"] == "PLAINS"


def test_inland_lake_majority_becomes_lake(tcfg):
    # Kasumigaura: NE polygon says land, WorldCover says ~all water.
    out = _classify(tcfg, _hex(inland_water_fraction=0.95, land_fraction=1.0))
    assert out.loc[0, "water_type"] == "LAKE"
    assert out.loc[0, "dominant_terrain_face"] == "WATER"
    assert out.loc[0, "natural_terrain_face"] == "WATER"


def test_ocean_hex(tcfg):
    out = _classify(tcfg, _hex(land_class="water", land_fraction=0.05,
                               inland_water_fraction=0.9))
    assert out.loc[0, "water_type"] == "OCEAN"
    assert out.loc[0, "dominant_terrain_face"] == "WATER"


def test_small_inland_water_keeps_land_layers(tcfg):
    out = _classify(tcfg, _hex(inland_water_fraction=0.2,
                               grassland_fraction=0.6, cropland_fraction=0.1))
    assert out.loc[0, "water_type"] == "NONE"
    assert out.loc[0, "surface_class"] == "NORMAL"
    assert out.loc[0, "dominant_terrain_face"] == "PLAINS"
    # The raw fraction survives for future visual overlays.
    assert out.loc[0, "inland_water_est"] == pytest.approx(0.2)


def test_coastal_sea_pixels_never_make_a_lake(tcfg):
    # Coastal land hex: 45% of WorldCover pixels are SEA water; after
    # subtracting the expected sea share (1 - land_fraction) no lake remains.
    out = _classify(tcfg, _hex(land_fraction=0.55, inland_water_fraction=0.45))
    assert out.loc[0, "water_type"] == "NONE"


def test_enum_ids_stable(tcfg):
    assert WATER_TYPE_ID == {"NONE": 0, "OCEAN": 1, "LAKE": 2, "RIVER": 3}
    # NORMAL keeps the id PLAINS had in schema 3.0 (rename only, no renumber).
    assert SURFACE_ID["NORMAL"] == 1 and SURFACE_ID["PERMANENT_SNOW_ICE"] == 5
    assert RELIEF_ID == {"NONE": 0, "FLAT": 1, "ROLLING": 2, "HILLS": 3,
                         "MOUNTAIN": 4}
    assert VEGETATION_ID == {"NONE": 0, "OPEN": 1, "FOREST": 2, "RAINFOREST": 3}
    assert DEVELOPMENT_ID == {"NONE": 0, "SETTLED": 1, "URBAN": 2,
                              "DENSE_URBAN": 3}
    assert TERRAIN_SCHEMA_VERSION_V3 == "3.1.0"


def test_tundra_desert_snow_and_rainforest_surfaces(tcfg):
    out = _classify(
        tcfg,
        _hex(is_tundra_climate=True, grassland_fraction=0.5),
        _hex(permanent_snow_ice_fraction=0.9, is_ice_cap_climate=True),
        _hex(wetland_fraction=0.5),
        _hex(tree_fraction=0.9, is_tropical=True),
        _hex(tree_fraction=0.9, is_tropical=True, slope_mean_deg=22.0,
             elevation_range_m=1300.0),
    )
    assert out.loc[0, "surface_class"] == "TUNDRA"
    assert out.loc[1, "surface_class"] == "PERMANENT_SNOW_ICE"
    assert out.loc[2, "surface_class"] == "WETLAND"
    assert out.loc[3, "vegetation_class"] == "RAINFOREST"
    assert out.loc[3, "dominant_terrain_face"] == "RAINFOREST"
    # Tropical mountain: relief wins the face, vegetation layer preserved.
    assert out.loc[4, "relief_class"] == "MOUNTAIN"
    assert out.loc[4, "vegetation_class"] == "RAINFOREST"
    assert out.loc[4, "dominant_terrain_face"] == "MOUNTAIN"


def test_deterministic(tcfg):
    rows = [_hex(tree_fraction=t / 10, slope_mean_deg=s,
                 urban_fraction=u / 10)
            for t in range(0, 10, 3) for s in (1, 5, 9, 18) for u in (0, 4, 7)]
    a = _classify(tcfg, *rows)
    b = _classify(tcfg, *rows)
    assert a.equals(b)


def test_layer_combinations_aggregation(tcfg):
    from mapgen.terrain_pipeline import layer_combinations

    out = _classify(
        tcfg,
        _hex(tree_fraction=0.9, slope_mean_deg=10.0),   # NORMAL|HILLS|FOREST|NONE
        _hex(tree_fraction=0.9, slope_mean_deg=10.0),
        _hex(urban_fraction=0.9),                        # NORMAL|FLAT|OPEN|DENSE_URBAN
        _hex(land_class="water"),                        # water: excluded
    )
    combos = layer_combinations(out)
    assert combos["hex_count"].sum() == 3
    top = combos.iloc[0]
    assert (top["surface_class"], top["relief_class"], top["vegetation_class"],
            top["development_class"]) == ("NORMAL", "HILLS", "FOREST", "NONE")
    assert top["hex_count"] == 2
