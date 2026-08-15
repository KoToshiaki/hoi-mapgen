"""MAPGEN-025 — a fragment is the land inside a hex, not the hex.

The load-bearing tests here are the two that could each undo the whole
design: that an ocean-majority hex still cannot be owned whole, and that
fragment identity contains no polity. Everything else follows.
"""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely

H = Path("data/historical")
SD = Path("data/scenarios/seven_years_war_1756_08_01")
EU = Path("output/europe_foundation_20260811/europe_hex_coverage.parquet")


@pytest.fixture(scope="module")
def canon():
    return pd.read_csv(SD / "territorial_control.csv",
                       keep_default_na=False, na_values=[""])


@pytest.fixture(scope="module")
def reg():
    return gpd.read_parquet(H / "land_fragment_registry.parquet")


@pytest.fixture(scope="module")
def hexes():
    return pd.read_parquet(EU, columns=["hex_id", "geometry", "water_type",
                                        "is_terrestrial_hex"])


# ---------------------------------------------------------------------------
# the two rules everything else rests on
# ---------------------------------------------------------------------------
def test_an_ocean_hex_still_cannot_be_owned_whole(canon, hexes):
    """The MAPGEN-006R invariant survives the new target type.

    If a fragment id were ever a hex id, or a TERRESTRIAL_HEX row ever
    pointed at an ocean hex, the whole justification for LAND_FRAGMENT
    would collapse into 'we owned the sea after all'.
    """
    terr = set(hexes.loc[hexes.is_terrestrial_hex, "hex_id"])
    geo = pd.read_parquet(
        "output/geography_v1_3_islands_006r_20260809/geography_hexes.parquet",
        columns=["hex_id", "water_type"])
    terr |= set(geo.loc[geo.water_type == "NONE", "hex_id"])
    t = canon[canon.territorial_target_type == "TERRESTRIAL_HEX"]
    assert set(t["territorial_target_id"]) <= terr
    f = canon[canon.territorial_target_type == "LAND_FRAGMENT"]
    assert not set(f["territorial_target_id"]) & set(hexes["hex_id"])


def test_fragment_identity_contains_no_polity(reg):
    sp = pd.read_csv(SD / "scenario_polities.csv", keep_default_na=False,
                     na_values=[])
    ids = set(sp["polity_id"]) | set(sp["scenario_polity_id"])
    for p in ids:
        assert not any(p in str(x) for x in reg["land_fragment_id"])
    assert not reg["land_subject_or_component_id"].isin(ids).any()
    # Malta and Gozo: two subjects, one polity - a polity key could not
    # tell them apart
    mp = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    osj = mp[mp.polity_id == "pol_order_st_john"]
    assert len(osj) == 2


def test_fragment_id_is_deterministic_and_scenario_independent():
    import hashlib
    import sys
    sys.path.insert(0, str(Path(
        "C:/Users/Owner/AppData/Local/Temp/claude/D--VScode-hoi/"
        "f33ff8be-aee2-4f6d-abe0-9abf43fa8060/scratchpad")))
    reg = pd.read_csv(H / "land_fragment_registry.csv")
    r = reg.iloc[0]
    key = f"{r['parent_hex_id']}|{r['land_subject_or_component_id']}"
    assert r["land_fragment_id"] == (
        "lfr_" + hashlib.sha1(key.encode()).hexdigest()[:14])
    assert "seven_years_war" not in key
    assert reg["land_fragment_id"].is_unique
    assert (reg["identity_algorithm_version"]
            == "v1_sha1_hexid_pipe_subjectid").all()


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
def test_land_fragment_schema_is_additive():
    from mapgen.scenario import SCENARIO_SCHEMA_VERSION, TARGET_TYPES
    assert TARGET_TYPES == ["TERRESTRIAL_HEX", "ISLAND_COMPONENT",
                            "LAND_FRAGMENT"]
    assert SCENARIO_SCHEMA_VERSION == "1.5.0"
    from mapgen.historical_geometry import HPG_SCHEMA_VERSION
    assert HPG_SCHEMA_VERSION == "1.4.0"


def test_backward_compatibility_of_old_target_rows(canon):
    """A reader that ignores fragments sees exactly MAPGEN-024.

    MAPGEN-026 later added Iberian hex rows, which are ordinary
    TERRESTRIAL_HEX rows and so cannot be told apart by target type; they
    are subtracted from their own membership audit.
    """
    from _production_baseline import strip_iberia_production
    old = strip_iberia_production(
        canon[canon.territorial_target_type != "LAND_FRAGMENT"])
    assert len(old) == 50565
    assert int((old.territorial_target_type
                == "TERRESTRIAL_HEX").sum()) == 50564
    assert int((old.territorial_target_type
                == "ISLAND_COMPONENT").sum()) == 1
    assert int((old.control_status == "CONTROLLED").sum()) == 49496
    assert int((old.control_status == "UNRESOLVED").sum()) == 1069


def test_validator_accepts_fragments_only_when_told_about_them(canon):
    from mapgen.scenario_promotion import validate_canonical_control
    prov = pd.read_csv(SD / "territorial_control_provenance.csv",
                       keep_default_na=False, na_values=[""])
    sp = pd.read_csv(SD / "scenario_polities.csv", keep_default_na=False,
                     na_values=[""])
    src = pd.read_csv(SD / "sources.csv", keep_default_na=False,
                      na_values=[""])
    reg = pd.read_csv(H / "land_fragment_registry.csv")
    geo = pd.read_parquet(
        "output/geography_v1_3_islands_006r_20260809/geography_hexes.parquet",
        columns=["hex_id", "water_type"])
    terr = set(geo.loc[geo.water_type == "NONE", "hex_id"])
    from _production_baseline import MEMBERSHIP_AUDITS
    for name in MEMBERSHIP_AUDITS:
        terr |= set(pd.read_csv(H / name, keep_default_na=False,
                                na_values=[])["hex_id"])
    # the earlier central-Europe stages bound their own membership sets
    for d in ("central_europe_1756_revision_20260813",
              "central_europe_1756_expand_20260813"):
        m = Path("output") / d / "historical_hex_membership.parquet"
        if m.exists():
            terr |= set(pd.read_parquet(m, columns=["hex_id"])["hex_id"])
    comps = set(pd.read_parquet(
        "output/geography_v1_3_islands_006r_20260809/"
        "island_components.parquet",
        columns=["island_component_id"])["island_component_id"])
    struct = set(sp.loc[sp["territorial_authority_role"].isin(
        ["STRUCTURAL_CONTAINER", "COMPOSITE_TERRITORIAL_ACTOR"]),
        "scenario_polity_id"])
    ok = validate_canonical_control(canon, prov, sp, src, terr, comps,
                                    struct, set(reg["land_fragment_id"]))
    assert ok == []
    # an old caller is warned, not fooled
    warned = validate_canonical_control(canon, prov, sp, src, terr, comps,
                                        struct)
    assert warned and "land fragment" in warned[0]


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------
def test_every_fragment_is_inside_its_parent_hex(reg, hexes):
    hxg = dict(zip(hexes["hex_id"], hexes["geometry"]))
    for r in reg.sample(250, random_state=1).itertuples():
        parent = shapely.from_wkb(hxg[r.parent_hex_id])
        assert shapely.covers(shapely.buffer(parent, 1e-6), r.geometry)


def test_fragments_sit_on_ocean_parents_and_have_positive_area(reg):
    assert (reg["canonical_water_type"] == "OCEAN").all()
    assert not reg["is_terrestrial_hex"].any()
    assert (reg["land_area_km2"] > 0).all()
    assert float(reg["land_area_km2"].max()) < 31.177


def test_no_fragment_covers_a_whole_hex(reg, hexes):
    """A fragment must be strictly smaller than its hex, or it would be
    a terrestrial hex and belong to the other target type."""
    hxg = dict(zip(hexes["hex_id"], hexes["geometry"]))
    for r in reg.sample(120, random_state=2).itertuples():
        parent = shapely.from_wkb(hxg[r.parent_hex_id])
        assert shapely.area(r.geometry) < shapely.area(parent)


# ---------------------------------------------------------------------------
# the overlap-safe helper
# ---------------------------------------------------------------------------
def test_duplicate_tile_fixture_double_counts_under_sum():
    """A hand-built fixture: the same square twice."""
    from mapgen.historical_binding import land_area_km2, land_in_hexes
    sq = shapely.box(0, 6_000_000, 1000, 6_001_000)
    hexp = shapely.box(-500, 5_999_000, 2000, 6_002_000)
    tiles = np.array([sq, sq], dtype=object)
    naive = sum(land_area_km2(
        [shapely.intersection(hexp, t) for t in tiles]))
    land, _ = land_in_hexes([hexp], tiles)
    safe = land_area_km2(land)[0]
    assert naive > safe * 1.9
    assert abs(safe - land_area_km2([sq])[0]) < 1e-9


def test_overlapping_non_identical_tile_fixture():
    """Deduplication alone would not save you."""
    from mapgen.historical_binding import land_area_km2, land_in_hexes
    a = shapely.box(0, 6_000_000, 1000, 6_001_000)
    b = shapely.box(500, 6_000_000, 1500, 6_001_000)
    hexp = shapely.box(-500, 5_999_000, 2500, 6_002_000)
    assert not a.equals(b)
    tiles = np.array([a, b], dtype=object)
    naive = sum(land_area_km2(
        [shapely.intersection(hexp, t) for t in tiles]))
    land, _ = land_in_hexes([hexp], tiles)
    safe = land_area_km2(land)[0]
    assert naive > safe
    assert abs(safe - land_area_km2([shapely.union_all([a, b])])[0]) < 1e-9


def test_helper_labels_split_land_by_component():
    from mapgen.historical_binding import land_area_km2, land_in_hexes
    a = shapely.box(0, 6_000_000, 1000, 6_001_000)
    b = shapely.box(2000, 6_000_000, 2500, 6_001_000)
    hexp = shapely.box(-500, 5_999_000, 3000, 6_002_000)
    land, per = land_in_hexes([hexp], np.array([a, b], dtype=object),
                              np.array(["A", "B"], dtype=object))
    assert set(per) == {"A", "B"}
    assert abs(land_area_km2(per["A"])[0]
               - land_area_km2([a])[0]) < 1e-9
    assert abs(land_area_km2(land)[0]
               - (land_area_km2([a])[0] + land_area_km2([b])[0])) < 1e-9


def test_real_cache_fixtures_all_pass():
    f = pd.read_csv(H / "land_cache_overlap_fixture_results.csv")
    assert bool(f["passed"].all())
    d = float(f.loc[f.fixture == "SUM_OVER_DUPLICATE_TILES_DOUBLE_COUNTS",
                    "measured"].iloc[0])
    assert d > 1.5


def test_unsafe_consumers_are_classified_and_none_affect_production():
    c = pd.read_csv(H / "land_cache_consumer_audit.csv",
                    keep_default_na=False, na_values=[])
    assert len(c) >= 6
    assert {"SAFE_UNION", "UNSAFE_SUM",
            "NOT_APPLICABLE"} <= set(c["classification"])
    assert int((c["affects_production"] == "YES").sum()) == 0


# ---------------------------------------------------------------------------
# production semantics
# ---------------------------------------------------------------------------
def test_mixed_component_hex_owns_only_its_fragment():
    m = pd.read_csv(H / "mixed_component_fragment_audit.csv")
    assert len(m) == 456
    assert not m["whole_hex_assigned"].any()
    cons = (m["land_area_km2"] + m["other_land_in_hex_km2"]
            - m["hex_total_land_km2"]).abs()
    assert float(cons.max()) < 1e-6
    assert float(m["fragment_share_of_hex"].min()) < 0.01


def test_same_hex_may_hold_multiple_fragments_by_key():
    """Not exercised by this scope, but the key must allow it."""
    import hashlib
    h = "h6000_q-000583_r+001236"
    a = "lfr_" + hashlib.sha1(f"{h}|hsub_a".encode()).hexdigest()[:14]
    b = "lfr_" + hashlib.sha1(f"{h}|hsub_b".encode()).hexdigest()[:14]
    assert a != b
    reg = pd.read_csv(H / "land_fragment_registry.csv")
    assert reg.groupby(["parent_hex_id",
                        "land_subject_or_component_id"]).size().max() == 1


def test_no_fragment_controller_collision(canon):
    f = canon[canon.territorial_target_type == "LAND_FRAGMENT"]
    assert f["territorial_target_id"].is_unique
    assert not canon.duplicated(subset=["territorial_target_type",
                                        "territorial_target_id"]).any()


def test_controller_comes_from_the_subject_mapping_not_adjacency(canon):
    reg = pd.read_csv(H / "land_fragment_registry.csv")
    mp = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    want = dict(zip(mp["historical_subject_id"], mp["scenario_polity_id"]))
    subj = dict(zip(reg["land_fragment_id"],
                    reg["land_subject_or_component_id"]))
    f = canon[canon.territorial_target_type == "LAND_FRAGMENT"]
    for r in f.itertuples():
        assert (r.controller_scenario_polity_id
                == want[subj[r.territorial_target_id]])


def test_every_fragment_row_has_full_provenance(canon):
    f = canon[canon.territorial_target_type == "LAND_FRAGMENT"]
    prov = pd.read_csv(SD / "territorial_control_provenance.csv",
                       keep_default_na=False, na_values=[""])
    p = prov[prov.territorial_target_id.isin(f["territorial_target_id"])]
    assert len(p) == len(f) == 3014
    for col in ("historical_evidence_ids", "boundary_feature_ids",
                "historical_subject_ids", "global_source_ids"):
        assert p[col].astype(str).str.len().gt(0).all()


def test_promotion_is_idempotent(canon):
    from mapgen.scenario_promotion import promote_control
    prov = pd.read_csv(SD / "territorial_control_provenance.csv",
                       keep_default_na=False, na_values=[""])
    log = pd.read_csv(SD / "scenario_control_promotion_log.csv",
                      keep_default_na=False, na_values=[""])
    empty = pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"])
    c2, _p, _l, rep = promote_control(
        canon.copy(), prov.copy(), log.copy(), empty,
        "seven_years_war_1756_08_01", "MAPGEN-025", "x", "none", "src_none",
        promoted_utc="2026-08-15")
    assert rep["inserted"] == 0 and len(c2) == len(canon)
    assert not rep["collisions"]


def test_toshima_remains_an_island_component(canon):
    isl = canon[canon.territorial_target_type == "ISLAND_COMPONENT"]
    assert len(isl) == 1
    assert isl.iloc[0]["territorial_target_id"] == "isl_c_1859af1e4767"


# ---------------------------------------------------------------------------
# physical geography untouched
# ---------------------------------------------------------------------------
def test_water_type_and_terrain_unchanged(hexes):
    from mapgen.config import load_config
    assert float(load_config("config/kanto.yaml").land_threshold) == 0.5
    # every fragment parent is still OCEAN, i.e. nothing was reclassified
    reg = pd.read_csv(H / "land_fragment_registry.csv")
    w = hexes.set_index("hex_id").loc[reg["parent_hex_id"].values]
    assert (w["water_type"] == "OCEAN").all()
    assert not w["is_terrestrial_hex"].any()


def test_viewer_fills_fragment_geometry_not_the_parent_hex():
    src = Path("src/mapgen/scenario_preview.py").read_text(encoding="utf-8")
    assert "_render_fragments" in src
    assert "never as their parent hex" in src
    import json
    p = Path("output/scenario_preview/preview_manifest.json")
    if p.exists():
        man = json.loads(p.read_text())
        assert man["authoritative"] is False
        assert man["stats"]["fragments"] == 3014
        assert man["stats"]["gap"] == 0


def test_no_wkt_duplication_in_the_registry_csv():
    reg = pd.read_csv(H / "land_fragment_registry.csv", nrows=0)
    assert "geometry" not in reg.columns
    assert (H / "land_fragment_registry.parquet").exists()
