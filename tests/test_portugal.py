"""MAPGEN-027 — evidence moved the line, not a new map.

Three tests carry this stage. The first is that Spain did not move: the
whole point of a follow-up is that it corrects what was missing without
disturbing what was right. The second is that Portugal's gain is
attributable to named evidence rather than to a loosened threshold — the
uncertainty is byte-identical to MAPGEN-026's. The third is that the
Algarve decision rests on institutions and not on the plate's lettering,
in either direction.

The rest guard the specific ways this stage could have cheated: bridging a
strip that another crown's cells reach into, owning an OCEAN hex through
the back door of a fragment, manufacturing control points for a map that
was never georeferenced, or quietly calling the model-selection holdout
blind.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

H = Path("data/historical")
SD = Path("data/scenarios/seven_years_war_1756_08_01")
EU = Path("output/europe_foundation_20260811/europe_hex_coverage.parquet")
SPAIN_SP, PORTUGAL_SP = "sp_b622a2799f94", "sp_fef06587fead"


@pytest.fixture(scope="module")
def canon():
    return pd.read_csv(SD / "territorial_control.csv",
                       keep_default_na=False, na_values=[""])


@pytest.fixture(scope="module")
def cells():
    return pd.read_csv(H / "iberia_cell_ownership_audit.csv",
                       keep_default_na=False, na_values=[])


@pytest.fixture(scope="module")
def corridors():
    return pd.read_csv(H / "portugal_corridor_audit.csv",
                       keep_default_na=False, na_values=[])


@pytest.fixture(scope="module")
def frags():
    return pd.read_csv(H / "iberia_land_fragment_production.csv")


# ---------------------------------------------------------------------------
# the three rules everything else rests on
# ---------------------------------------------------------------------------
def test_spain_did_not_move(canon):
    """A follow-up that disturbs what it was not asked to touch is not a
    follow-up. Spain's hex set must be the MAPGEN-026 set exactly."""
    s = canon[(canon.controller_scenario_polity_id == SPAIN_SP)
              & (canon.territorial_target_type == "TERRESTRIAL_HEX")]
    assert len(s) == 5431
    rv = pd.read_csv(SD / "territorial_control_revision_log.csv",
                     keep_default_na=False, na_values=[""])
    mine = rv[rv.reason.str.contains("Portugal safe interior v2", na=False)]
    assert len(mine) > 0
    assert not (mine.new_controller == SPAIN_SP).any()
    assert not (mine.old_controller == SPAIN_SP).any()


def test_portugals_gain_is_evidence_not_a_loosened_threshold():
    """The uncertainty is unchanged. If a later stage ever grows Portugal
    by moving this number instead, this test is where it shows."""
    v2 = pd.read_csv(H / "portugal_safe_interior_v2.csv")
    tr = json.loads((H / "iberia_lerouge_transform.json").read_text(
        encoding="utf-8"))
    assert abs(float(v2.iloc[0].uncertainty_km)
               - tr["unseen_p95_m"] / 1000) < 0.02
    assert bool(v2.iloc[0].v1_fully_contained_in_v2)
    assert float(v2.iloc[0].overlap_with_spain_safe_km2) < 1e-3
    assert (float(v2.iloc[0].v2_area_km2_3857)
            > float(v2.iloc[0].v1_area_km2_3857))
    assert bool(v2.iloc[0].spain_feature_area_unchanged)


def test_the_algarve_decision_is_institutional(cells):
    audit = pd.read_csv(H / "algarve_constitutional_audit.csv",
                        keep_default_na=False, na_values=[])
    dec = pd.read_csv(H / "algarve_primary_evidence.csv",
                      keep_default_na=False, na_values=[])
    assert {"ROYAL_TITULATURE", "CROWN_IDENTITY", "LEGISLATIVE_AUTHORITY",
            "ADMINISTRATION", "JUDICIAL_STRUCTURE", "TAXATION",
            "REPRESENTATION"} <= set(audit.axis)
    assert "TITLE_IS_NOT_ACTOR_EVIDENCE" in set(audit.verdict)
    assert str(dec.iloc[0].decision) == "PART_OF_POL_PORTUGAL"
    assert str(dec.iloc[0].map_title_used_as_evidence) == "NO"
    assert str(dec.iloc[0].auto_merged_for_convenience) == "NO"
    assert int(dec.iloc[0].axes_supporting_separate_actor) == 0
    # and no new polity was invented for it
    sp = pd.read_csv(SD / "scenario_polities.csv", keep_default_na=False,
                     na_values=[])
    assert not sp.polity_id.str.contains("algarve", case=False).any()
    assert cells.loc[cells.cell == 18, "crown"].iloc[0] == "PORTUGAL"


# ---------------------------------------------------------------------------
# the specific ways this stage could have cheated
# ---------------------------------------------------------------------------
def test_a_corridor_is_bridged_only_when_no_other_crown_reaches_it(
        corridors):
    assert len(corridors) >= 9
    bridged = corridors[corridors.decision == "BRIDGED"]
    assert (bridged.other_crown_cell_overlap_km2 < 1.0).all()
    assert (bridged.settlements_read.str.len() > 5).all()
    for r in corridors.itertuples():
        if r.other_crown_cell_overlap_km2 >= 1.0:
            assert r.decision == "NOT_BRIDGED"


def test_no_ocean_hex_is_owned_through_a_fragment(canon, frags):
    hx = pd.read_parquet(EU, columns=["hex_id", "is_terrestrial_hex"])
    terr = set(hx.loc[hx.is_terrestrial_hex, "hex_id"])
    assert not (set(frags.hex_id) & terr)
    hex_rows = set(canon.loc[canon.territorial_target_type
                             == "TERRESTRIAL_HEX",
                             "territorial_target_id"])
    assert not (set(frags.hex_id) & hex_rows)
    assert (frags.canonical_water_type == "OCEAN").all()


def test_other_components_in_a_shared_hex_are_measured_and_left_unowned():
    multi = pd.read_csv(H / "iberia_multi_fragment_capability.csv")
    assert len(multi) > 100
    assert int(multi.distinct_land_components_in_hex.max()) > 50
    assert (multi.second_fragment_produced == "NO").all()
    assert (multi.key_is_a_function_of_both == "YES").all()
    # the id really is a function of both, so two subjects in one hex
    # cannot collide
    assert not (set(multi.mainland_fragment_id)
                & set(multi.second_fragment_id_if_authorised))
    # and at least one hex holds more islet land than mainland land,
    # which is what makes a whole-hex winner indefensible
    assert (multi.other_component_km2 > multi.mainland_km2).any()


def test_no_control_point_was_manufactured_for_an_ungeoreferenced_map():
    audit = pd.read_csv(H / "portugal_georeference_audit.csv")
    prelim = pd.read_csv(H / "portugal_preliminary_accuracy_check.csv")
    assert str(audit.iloc[0].status) == "PRELIMINARY_NOT_A_GEOREFERENCE"
    assert (prelim.eligible_as_gcp == "NO").all()
    assert not (H / "portugal_transform.json").exists()
    seg = pd.read_csv(H / "portugal_frontier_segments.csv")
    assert seg.empty
    cmp_ = pd.read_csv(H / "portugal_cross_source_comparison.csv")
    assert str(cmp_.iloc[0].status) == "NOT_PERFORMED"
    assert str(cmp_.iloc[0].handed_to) == "MAPGEN-028"


def test_the_model_selection_holdout_is_not_called_blind():
    m = pd.read_csv(H / "portugal_georeference_metric_separation.csv")
    assert set(m.metric_set) == {"FIT", "MODEL_SELECTION_HOLDOUT",
                                 "BLIND_VALIDATION", "ALL_NONFIT"}
    ms = m[m.metric_set == "MODEL_SELECTION_HOLDOUT"].iloc[0]
    assert ms.statistically_blind == "NO"
    bl = m[m.metric_set == "BLIND_VALIDATION"].iloc[0]
    assert bl.statistically_blind == "YES"
    used = m[m.used_for_production_uncertainty == "YES"]
    assert len(used) == 1
    assert used.iloc[0].metric_set == "ALL_NONFIT"
    # and the one actually used is the more conservative of the two
    assert float(used.iloc[0].p95_km) > float(bl.p95_km)


def test_the_new_source_is_reusable_and_its_lineage_is_unresolved():
    reg = pd.read_csv(H / "portugal_map_source_registry.csv")
    lin = pd.read_csv(H / "portugal_source_lineage.csv")
    assert len(reg) >= 2
    assert (reg.rights.str.contains("CC BY 4.0")).all()
    assert (reg.gitignored == "YES").all()
    assert (reg.sha256.str.len() == 64).all()
    assert (lin.independence_status == "UNRESOLVED").all()
    assert (lin.corroboration_eligible == "NO").all()


def test_the_1762_sheet_carries_a_continuity_argument_it_does_not_spend():
    c = pd.read_csv(H / "portugal_source_continuity_audit.csv")
    assert len(c) == 1
    assert "1762" in str(c.iloc[0].war_risk)
    assert "Alcanices" in str(c.iloc[0].finding)
    assert "not relied on" in str(c.iloc[0].note)


# ---------------------------------------------------------------------------
# evidence hardening
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("who,days", [("spain", 5), ("portugal", 47)])
def test_each_crown_has_authority_dated_before_the_snapshot(who, days):
    d = pd.read_csv(H / f"{who}_snapshot_evidence_hardening.csv")
    assert str(d.iloc[0].relation_to_snapshot) == "AFTER_SNAPSHOT"
    assert str(d.iloc[0].relation_to_snapshot_new) == "BEFORE_SNAPSHOT"
    assert int(d.iloc[0].days_before_snapshot) == days
    assert str(d.iloc[0].earlier_evidence_retained) == "YES"
    assert len(str(d.iloc[0].acts_on_the_ground)) > 20


def test_the_bundle_actually_carries_the_new_evidence():
    ev = pd.read_csv(H / "historical_evidence_assertions.csv",
                     keep_default_na=False, na_values=[])
    links = pd.read_csv(H / "historical_boundary_feature_evidence.csv",
                        keep_default_na=False, na_values=[])
    snap = pd.read_csv(H / "historical_snapshot_features_1756_08_01.csv",
                       keep_default_na=False, na_values=[])
    ib = snap[snap.historical_subject_id.str.contains("iberian_mainland")]
    assert len(ib) == 2
    for r in ib.itertuples():
        ids = set(str(r.bundle_evidence_ids).split("|"))
        assert len(ids) >= 4
        sub = ev[ev.historical_evidence_id.isin(ids)]
        assert (sub.political_authority == "YES").any()
        assert (sub.geometry_authority == "YES").any()
    assert len(links[links.evidence_role == "POLITICAL_STATUS"]) >= 8


# ---------------------------------------------------------------------------
# the stage as a whole
# ---------------------------------------------------------------------------
def test_every_gate_passed():
    v = pd.read_csv("reviews/MAPGEN-027/validation.csv")
    assert len(v) == 46
    assert bool(v["pass"].all()), v[~v["pass"]].to_string()


def test_the_summary_reports_what_actually_happened():
    s = pd.read_csv("reviews/MAPGEN-027/summary.csv")
    d = dict(zip(s.metric.astype(str), s.value.astype(str)))
    assert d["outcome"] == "ACCEPTABLE"
    assert d["mapgen026_outcome_restated"] == \
        "ACCEPTABLE_PRODUCTION_WITH_FOLLOWUP_GAPS"
    assert int(d["portugal_controlled_before"]) == 26
    assert int(d["portugal_controlled"]) > 100
    assert int(d["spain_controlled"]) == int(d["spain_controlled_before"])
    assert float(d["positional_uncertainty_km"]) == 34.61
    assert d["larger_scale_source_status"] == \
        "PRELIMINARY_NOT_A_GEOREFERENCE"
