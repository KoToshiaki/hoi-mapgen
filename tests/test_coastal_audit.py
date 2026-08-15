"""MAPGEN-024 — an audit stage must not change what it is auditing.

The load-bearing test in this file is the one that proves the renderer
cannot touch canonical data. Everything else measures a gap; that one
guarantees the measurement is honest.
"""
import subprocess
from pathlib import Path

import pandas as pd
import pytest

H = Path("data/historical")
SD = Path("data/scenarios/seven_years_war_1756_08_01")
LANDMASSES = {"Great Britain", "Ireland", "Sicily", "Sardinia", "Iceland",
              "Malta", "Gozo"}


@pytest.fixture(scope="module")
def audit():
    return pd.read_csv(H / "coastal_hex_representability_audit.csv",
                       keep_default_na=False, na_values=[])


@pytest.fixture(scope="module")
def gap(audit):
    return audit[audit.representability_class
                 == "AUTHORISED_LAND_NON_TERRESTRIAL"]


@pytest.fixture(scope="module")
def summ():
    return pd.read_csv(H / "coastal_hex_landmass_summary.csv")


@pytest.fixture(scope="module")
def canon():
    return pd.read_csv(SD / "territorial_control.csv",
                       keep_default_na=False, na_values=[""])


# ---------------------------------------------------------------------------
# the rule everything else rests on
# ---------------------------------------------------------------------------
def test_the_renderer_cannot_alter_canonical_data(tmp_path):
    """Render the whole preview and prove nothing moved.

    A QA renderer that can write to the data it draws is not a QA
    renderer. This hashes canonical control and the land cache, renders,
    and hashes again.
    """
    import hashlib

    from mapgen.config import load_config
    from mapgen.scenario_preview import render_scenario_preview

    watched = [SD / "territorial_control.csv",
               SD / "territorial_control_provenance.csv",
               Path("output/europe_land_cache/europe_land_parts.parquet"),
               H / "coastal_hex_representability_audit.csv"]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    out = render_scenario_preview(load_config("config/kanto.yaml"),
                                  out_dir=tmp_path / "prev")
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    assert before == after
    import json
    man = json.loads((out / "preview_manifest.json").read_text())
    assert man["authoritative"] is False
    assert man["purpose"] == "QA_AND_PRESENTATION_ONLY"


def test_audit_stage_produced_no_territory(canon):
    from mapgen.historical_coastal_audit_pipeline import committed_baseline
    base = committed_baseline()
    assert len(canon) == base["canonical_rows_after"] == 50565
    assert int((canon["control_status"] == "CONTROLLED").sum()) \
        == base["canonical_controlled_after"]
    assert int((canon["control_status"] == "UNRESOLVED").sum()) \
        == base["canonical_unresolved_after"]


# ---------------------------------------------------------------------------
# detection and measurement
# ---------------------------------------------------------------------------
def test_authorised_land_in_non_terrestrial_hexes_is_detected(gap):
    assert len(gap) > 0
    assert not gap["is_terrestrial_hex"].any()
    assert (gap["authorised_land_area_km2"] > 0).all()
    assert (gap["canonical_water_class"] == "OCEAN").all()


def test_exact_area_conservation(audit):
    """Measured ground land can never exceed the hex it sits in.

    It did, by a factor of two, until the measurement stopped summing
    per-tile intersections: the canonical land cache stores 3,480 tiles
    twice and holds further tiles that overlap without being identical.
    Unioning the pieces inside each hex is exact whatever the tiling does.
    """
    assert float(audit["land_fraction_measured_ground"].max()) <= 1.01
    assert (audit["authorised_land_area_km2"]
            <= audit["canonical_land_area_km2"] + 1e-6).all()
    assert (audit["other_land_component_area_km2"] >= -1e-9).all()
    r = (audit["land_fraction_measured_ground"]
         - audit["canonical_land_fraction_projected"]).abs()
    assert float(r.mean()) < 0.01


def test_iceland_1089_gap_reproduced(summ):
    r = summ[summ.landmass == "Iceland"].iloc[0]
    assert int(r["withheld_non_terrestrial"]) == 1089


def test_malta_gozo_15_gap_reproduced(summ):
    mg = summ[summ.landmass.isin(["Malta", "Gozo"])]
    assert int(mg["withheld_non_terrestrial"].sum()) == 15
    assert int(summ[summ.landmass == "Malta"]
               ["withheld_non_terrestrial"].iloc[0]) == 9
    assert int(summ[summ.landmass == "Gozo"]
               ["withheld_non_terrestrial"].iloc[0]) == 6


def test_retroactive_island_audits_cover_the_four_never_measured(summ):
    for name in ("Great Britain", "Ireland", "Sicily", "Sardinia"):
        r = summ[summ.landmass == name].iloc[0]
        assert int(r["withheld_non_terrestrial"]) > 0
        assert float(r["authorised_km2_withheld"]) > 0
    assert set(summ["landmass"]) == LANDMASSES


def test_the_gap_scales_with_smallness(summ):
    """The point of the whole stage: the error is not a constant."""
    big = summ[summ.landmass.isin(["Great Britain", "Ireland", "Iceland",
                                   "Sicily", "Sardinia"])]
    assert (big["withheld_share_of_authorised_pct"] < 3).all()
    assert float(summ[summ.landmass == "Gozo"]
                 ["withheld_share_of_authorised_pct"].iloc[0]) > 10


def test_physical_water_class_is_preserved(gap):
    """The audit reads the water class; it never proposes changing it."""
    import pandas as pd
    hx = pd.read_parquet(
        "output/europe_foundation_20260811/europe_hex_coverage.parquet",
        columns=["hex_id", "water_type", "is_terrestrial_hex"])
    m = hx.set_index("hex_id").loc[gap["hex_id"].values]
    assert (m["water_type"] == "OCEAN").all()
    assert not m["is_terrestrial_hex"].any()


def test_political_target_semantics_are_isolated(gap, canon):
    """Not one withheld hex leaked into canonical control."""
    assert not set(gap["hex_id"]) & set(canon["territorial_target_id"])


def test_mixed_components_are_not_merged_into_the_gap_reason(gap):
    mixed = gap[gap.mixed_unaudited]
    plain = gap[~gap.mixed_unaudited]
    assert len(mixed) > 0 and len(plain) > 0
    assert (mixed["reason_not_produced"]
            == "NON_TERRESTRIAL_HEX_AND_MIXED_UNAUDITED_LAND").all()
    assert plain["reason_not_produced"].str.startswith(
        "CANONICAL_PHYSICAL_CLASSIFICATION_IS_OCEAN").all()


def test_land_fraction_distribution_partitions_the_gap(gap):
    d = pd.read_csv(H / "coastal_hex_land_fraction_distribution.csv")
    dall = d[d.landmass == "ALL"]
    assert int(dall["hexes"].sum()) == len(gap)
    assert abs(float(dall["authorised_km2"].sum())
               - float(gap["authorised_land_area_km2"].sum())) < 0.5
    assert float(gap["canonical_land_fraction_projected"].max()) < 0.5


# ---------------------------------------------------------------------------
# semantics and models
# ---------------------------------------------------------------------------
def test_is_terrestrial_hex_usage_separates_physical_from_political():
    u = pd.read_csv(H / "is_terrestrial_hex_usage_audit.csv",
                    keep_default_na=False, na_values=[])
    assert set(u["is_political"]) == {"YES", "NO"}
    assert int((u.is_political == "YES").sum()) >= 4
    assert int((u.is_political == "NO").sum()) >= 4
    assert u["what"].str.contains("classification_error_area_m2").any()
    assert u["site"].str.contains("scenario.py:23-26").any()
    # the claim that movement does not read the flag must be sourced
    mv = u[u.layer == "MOVEMENT"]
    assert len(mv) == 1 and "reads neither" in mv.iloc[0]["what"]


def test_the_documented_invariant_still_exists_in_the_code():
    """The conclusion rests on a docstring. Prove it is still there."""
    src = Path("src/mapgen/scenario.py").read_text(encoding="utf-8")
    assert "an OCEAN hex" in src and "never itself a land-control target" \
        in src
    assert 'TARGET_TYPES = ["TERRESTRIAL_HEX", "ISLAND_COMPONENT"]' in src
    pipe = Path("src/mapgen/scenario_pipeline.py").read_text(encoding="utf-8")
    assert 'geo.loc[geo["is_terrestrial_hex"], "hex_id"]' in pipe


def test_all_four_models_evaluated_on_every_axis():
    m = pd.read_csv(H / "political_target_model_comparison.csv",
                    keep_default_na=False, na_values=[])
    assert set(m["model"]) == {"A", "B", "C", "D"}
    axes = ["historical_correctness", "gameplay_semantics",
            "movement_implications", "terrain_implications", "data_size",
            "migration_cost", "compatibility", "island_overlays",
            "mixed_controller_risk", "verdict"]
    for a in axes:
        assert m[a].astype(str).str.strip().str.len().gt(0).all()
    assert m[m.model == "C"].iloc[0]["verdict"].startswith("RECOMMENDED")
    assert m[m.model == "D"].iloc[0]["verdict"].startswith("REJECTED")


def test_island_component_contract_is_compared_not_assumed():
    c = pd.read_csv(H / "island_component_comparison.csv",
                    keep_default_na=False, na_values=[])
    assert len(c) >= 6
    assert (c["same"] == "NO").sum() >= 4
    assert c["coastal_fragment_case"].str.contains(
        "is_subhex_lost is False").any()


def test_no_threshold_was_tuned():
    from mapgen.config import load_config
    assert float(load_config("config/kanto.yaml").land_threshold) == 0.5
    rec = (H / "representation_recommendation.md").read_text(encoding="utf-8")
    assert "No threshold was tuned" in rec
    assert "C. ARCHITECTURAL_GAP" in rec


# ---------------------------------------------------------------------------
# renderer
# ---------------------------------------------------------------------------
def test_colours_are_deterministic_and_do_not_merge_unions():
    from mapgen.scenario_preview import polity_colour
    assert polity_colour("pol_sicily") == polity_colour("pol_sicily")
    pairs = [("pol_great_britain", "pol_hanover"),
             ("pol_great_britain", "pol_kingdom_of_ireland"),
             ("pol_sicily", "pol_naples"),
             ("pol_sardinia", "pol_sicily")]
    for a, b in pairs:
        assert polity_colour(a) != polity_colour(b)
    sp = pd.read_csv(SD / "scenario_polities.csv",
                     keep_default_na=False, na_values=[])
    canon = pd.read_csv(SD / "territorial_control.csv",
                        keep_default_na=False, na_values=[""])
    active = sp[sp["scenario_polity_id"].isin(
        canon.loc[canon.control_status == "CONTROLLED",
                  "controller_scenario_polity_id"])]
    cols = [polity_colour(p) for p in active["polity_id"]]
    assert len(set(cols)) == len(cols)


def test_unknown_unresolved_and_gap_are_three_categories():
    from mapgen.scenario_preview import GAP_C, LAND_UNKNOWN, UNRESOLVED_C
    assert len({GAP_C, LAND_UNKNOWN, UNRESOLVED_C}) == 3


# ---------------------------------------------------------------------------
# repository hygiene
# ---------------------------------------------------------------------------
def test_no_tracked_file_over_50mb():
    from mapgen.historical_coastal_audit_pipeline import (
        MAX_TRACKED_BYTES, tracked_file_sizes)
    t = tracked_file_sizes(Path.cwd())
    over = t[t["bytes"] > MAX_TRACKED_BYTES]
    assert len(over) == 0, over.to_dict("records")


def test_tracked_files_over_25mb_are_allowlisted():
    from mapgen.historical_coastal_audit_pipeline import (
        WARN_TRACKED_BYTES, tracked_file_sizes)
    b = pd.read_csv(H / "git_blob_size_audit.csv",
                    keep_default_na=False, na_values=[])
    allow = set(b.loc[b["allowlisted"].str.startswith("ALLOWLISTED"),
                      "path"])
    t = tracked_file_sizes(Path.cwd())
    over = t[t["bytes"] > WARN_TRACKED_BYTES]
    assert set(over["path"]) <= allow


def test_no_review_csv_duplicates_geometry_as_wkt():
    bad = []
    for p in Path("reviews").rglob("*.csv"):
        try:
            cols = pd.read_csv(p, nrows=0).columns
        except Exception:
            continue
        if any(c.lower() in ("geometry", "wkt", "geom") for c in cols):
            bad.append(str(p))
    assert not bad, bad


def test_legacy_blob_is_documented_and_not_rewritten():
    b = pd.read_csv(H / "git_blob_size_audit.csv",
                    keep_default_na=False, na_values=[])
    legacy = b[b["state"].str.startswith("LEGACY_HISTORY_DEBT")]
    assert len(legacy) == 1
    assert "NOT" in legacy.iloc[0]["note"]
    # the commit the review chain cites must still resolve
    r = subprocess.run(["git", "rev-parse", "--verify", "c12ee10"],
                       capture_output=True)
    assert r.returncode == 0
