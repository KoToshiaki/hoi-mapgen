# -*- coding: utf-8 -*-
"""MAPGEN-013 — canonical control promotion, audit-terminology split and
transform stability.

Every test here defends a semantic rule, not an implementation detail:
staged control is not authority until promoted, promotion is idempotent,
a target holds one active row, provenance survives the namespace
migration, and cartographic uncertainty is never conflated with
multi-polity contention.
"""
from pathlib import Path

import pandas as pd
import pytest

from mapgen.historical_georeference import (TRANSFORM_MODELS,
                                            select_model_stable)
from mapgen.historical_pilot_pipeline import classify_hex_confidence
from mapgen.scenario_promotion import (
    CONTROL_KEY, PROMOTION_LOG_COLUMNS, PROVENANCE_COLUMNS,
    REVIEW_STATUSES, make_promotion_id, promote_control,
    sha256_of_frame, validate_canonical_control)

SC = "test_scenario"
SRC = "src_test0000"


def _candidate(n=3, start=0, status="CONTROLLED", controller="sp_a"):
    return pd.DataFrame([{
        "scenario_id": SC,
        "territorial_target_type": "TERRESTRIAL_HEX",
        "territorial_target_id": f"h6000_q+00000{start + i}_r+000001",
        "controller_scenario_polity_id":
            controller if status == "CONTROLLED" else None,
        "control_status": status,
        "source_confidence": "MEDIUM",
        "source_id": "hsrc_global0001",
        "source_ids": "hsrc_global0001",
        "political_evidence_ids": "hev_0001|hev_0002",
        "boundary_feature_ids": "hbf_0001",
        "historical_subject_ids": "hsub_test",
        "notes": "",
    } for i in range(n)])


def _empty():
    return (pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"]),
        pd.DataFrame(columns=PROVENANCE_COLUMNS),
        pd.DataFrame(columns=PROMOTION_LOG_COLUMNS))


def _promote(candidate, canonical=None, provenance=None, log=None,
             stage="MAPGEN-013", **kw):
    if canonical is None:
        canonical, provenance, log = _empty()
    return promote_control(canonical, provenance, log, candidate, SC,
                           stage, "deadbeef", "artifact.csv", SRC,
                           promoted_utc="2026-08-13", **kw)


def test_promotion_id_is_deterministic_for_same_artifact():
    a, b = _candidate(), _candidate()
    assert make_promotion_id(SC, "MAPGEN-013", sha256_of_frame(a)) \
        == make_promotion_id(SC, "MAPGEN-013", sha256_of_frame(b))


def test_promotion_id_changes_when_the_artifact_changes():
    a = _candidate()
    b = _candidate(n=4)
    assert make_promotion_id(SC, "MAPGEN-013", sha256_of_frame(a)) \
        != make_promotion_id(SC, "MAPGEN-013", sha256_of_frame(b))


def test_promotion_inserts_rows_and_logs_once():
    canonical, provenance, log, rep = _promote(_candidate())
    assert len(canonical) == 3 and rep["inserted"] == 3
    assert len(log) == 1 and log.iloc[0]["promotion_status"] == "PROMOTED"
    assert log.iloc[0]["controlled_count"] == 3


def test_promotion_is_idempotent():
    cand = _candidate()
    c1, p1, l1, _ = _promote(cand)
    c2, p2, l2, rep = _promote(cand, c1.copy(), p1.copy(), l1.copy())
    assert rep["inserted"] == 0 and rep["already_present"] == 3
    assert len(c2) == len(c1) and len(l2) == len(l1)
    pd.testing.assert_frame_equal(c1, c2)


def test_a_target_may_hold_only_one_active_row():
    """A different promotion touching an owned target must raise, not
    overwrite: replacing reviewed authority needs its own review."""
    c1, p1, l1, _ = _promote(_candidate())
    other = _candidate(controller="sp_b")
    other.loc[0, "notes"] = "different evidence"
    with pytest.raises(ValueError, match="different promotion"):
        _promote(other, c1, p1, l1, stage="MAPGEN-014")


def test_candidate_with_duplicate_targets_is_rejected():
    cand = pd.concat([_candidate(1), _candidate(1)], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate target keys"):
        _promote(cand)


def test_only_reviewed_candidates_may_be_promoted():
    for status in ["STAGED", "REJECTED", "SUPERSEDED"]:
        assert status in REVIEW_STATUSES
        with pytest.raises(ValueError, match="only REVIEWED"):
            _promote(_candidate(), review_status=status)


def test_unknown_review_status_is_rejected():
    with pytest.raises(ValueError, match="unknown review_status"):
        _promote(_candidate(), review_status="APPROVED_BY_VIBES")


def test_canonical_source_id_stays_in_the_scenario_namespace():
    """The migration must not leak the global hsrc_ namespace into the
    canonical foreign key."""
    canonical, prov, _, _ = _promote(_candidate())
    assert canonical["source_id"].eq(SRC).all()
    assert not canonical["source_id"].str.startswith("hsrc_").any()


def test_global_bundle_survives_in_provenance():
    _, prov, _, _ = _promote(_candidate())
    row = prov.iloc[0]
    assert row["global_source_ids"] == "hsrc_global0001"
    assert row["historical_evidence_ids"] == "hev_0001|hev_0002"
    assert row["boundary_feature_ids"] == "hbf_0001"
    assert row["scenario_source_id"] == SRC
    assert list(prov.columns) == PROVENANCE_COLUMNS


def test_unresolved_rows_never_carry_a_controller():
    canonical, _, log, _ = _promote(_candidate(status="UNRESOLVED"))
    assert canonical["controller_scenario_polity_id"].isna().all()
    assert log.iloc[0]["unresolved_count"] == 3
    assert log.iloc[0]["controlled_count"] == 0


def _validate(canonical, provenance, **kw):
    args = {
        "scenario_polities": pd.DataFrame({
            "scenario_polity_id": ["sp_a", "sp_container"]}),
        "scenario_sources": pd.DataFrame({"source_id": [SRC]}),
        "terrestrial_hexes": set(canonical["territorial_target_id"]),
        "island_components": set(),
        "structural_polities": {"sp_container"},
    }
    args.update(kw)
    return validate_canonical_control(canonical, provenance, **args)


def test_validate_accepts_a_clean_canonical_table():
    canonical, prov, _, _ = _promote(_candidate())
    assert _validate(canonical, prov) == []


def test_validate_catches_duplicate_target_keys():
    canonical, prov, _, _ = _promote(_candidate())
    dup = pd.concat([canonical, canonical.iloc[[0]]], ignore_index=True)
    assert any("duplicate" in v for v in _validate(dup, prov))


def test_validate_catches_orphan_controller():
    canonical, prov, _, _ = _promote(_candidate(controller="sp_ghost"))
    assert any("orphan controller" in v for v in _validate(canonical, prov))


def test_validate_catches_orphan_scenario_source():
    canonical, prov, _, _ = _promote(_candidate())
    canonical.loc[0, "source_id"] = "src_unregistered"
    assert any("orphan scenario source" in v
               for v in _validate(canonical, prov))


def test_structural_container_may_not_hold_control():
    canonical, prov, _, _ = _promote(_candidate(controller="sp_container"))
    assert any("structural container" in v
               for v in _validate(canonical, prov))


def test_validate_catches_non_terrestrial_target():
    canonical, prov, _, _ = _promote(_candidate())
    assert any("non-terrestrial" in v
               for v in _validate(canonical, prov, terrestrial_hexes=set()))


def test_validate_catches_orphan_provenance_row():
    canonical, prov, _, _ = _promote(_candidate())
    assert any("provenance rows without" in v
               for v in _validate(canonical.iloc[:1], prov))


def test_cartographic_uncertainty_is_not_multi_polity_contention():
    """The two conditions are independent: a hex deep inside one polity
    can still be uncertain, and a shared hex can still be far from the
    drawn line."""
    near_edge_single = {"distance_to_source_boundary_km": 1.0,
                        "border_hex": False}
    far_shared = {"distance_to_source_boundary_km": 40.0,
                  "border_hex": True}
    far_single = {"distance_to_source_boundary_km": 40.0,
                  "border_hex": False}
    assert classify_hex_confidence(near_edge_single, 9.168) \
        == "BORDER_UNCERTAIN"
    assert classify_hex_confidence(far_shared, 9.168) \
        == "MULTI_POLITY_BORDER"
    assert classify_hex_confidence(far_single, 9.168) \
        == "INTERIOR_CONFIDENT"


def test_widening_uncertainty_can_only_remove_confident_hexes():
    hexes = [{"distance_to_source_boundary_km": d, "border_hex": False}
             for d in (0.5, 3.0, 8.0, 12.0, 30.0)]
    narrow = [classify_hex_confidence(h, 2.975) for h in hexes]
    wide = [classify_hex_confidence(h, 9.168) for h in hexes]
    assert narrow.count("BORDER_UNCERTAIN") == 1
    assert wide.count("BORDER_UNCERTAIN") == 3
    for n, w in zip(narrow, wide):
        assert not (n == "BORDER_UNCERTAIN" and w != "BORDER_UNCERTAIN")


def _audit(indep):
    return pd.DataFrame([
        {"model": m, "status": "FITTED", "holdout_rms_m": h,
         "independent_check_max_m": i}
        for m, h, i in zip(TRANSFORM_MODELS, [1177.9, 87.9, 66.2], indep)])


def test_polynomial_cannot_win_by_snaking_through_the_graticule():
    """POLYNOMIAL_2 has the best graticule holdout and is still wrong by
    thousands of km between the nodes."""
    assert select_model_stable(_audit([9043.5, 9433.8, 3_906_462.0]),
                               "independent_check_max_m") == "PROJECTIVE"


def test_stability_guard_never_rewards_complexity_on_a_tie():
    audit = _audit([9000.0, 9000.0, 9000.0])
    audit["holdout_rms_m"] = [80.0, 80.0, 80.0]
    assert select_model_stable(audit, "independent_check_max_m") \
        == "AFFINE"


def test_no_globally_stable_model_is_an_error_not_a_fallback():
    with pytest.raises(ValueError, match="globally stable"):
        select_model_stable(_audit([1e6, 1e6, 1e6]),
                            "independent_check_max_m")


PRODUCTION = Path("data/scenarios/seven_years_war_1756_08_01")


@pytest.mark.skipif(not (PRODUCTION / "territorial_control.csv").exists(),
                    reason="production scenario not built")
def test_production_canonical_control_has_no_duplicate_target():
    c = pd.read_csv(PRODUCTION / "territorial_control.csv")
    assert not c.duplicated(subset=CONTROL_KEY).any()


@pytest.mark.skipif(
    not (PRODUCTION / "territorial_control_provenance.csv").exists(),
    reason="promotion has not been run")
def test_production_provenance_covers_every_promoted_row():
    c = pd.read_csv(PRODUCTION / "territorial_control.csv")
    p = pd.read_csv(PRODUCTION / "territorial_control_provenance.csv")
    assert set(p["territorial_target_id"]) <= set(c["territorial_target_id"])
    assert p["global_source_ids"].str.startswith("hsrc_").all()


@pytest.mark.skipif(
    not (PRODUCTION / "territorial_control.csv").exists(),
    reason="production scenario not built")
def test_production_unresolved_never_became_neutral():
    c = pd.read_csv(PRODUCTION / "territorial_control.csv")
    unresolved = c[c["control_status"] == "UNRESOLVED"]
    assert len(unresolved) > 0
    assert unresolved["controller_scenario_polity_id"].isna().all()
    assert "NEUTRAL" not in set(c["control_status"])
