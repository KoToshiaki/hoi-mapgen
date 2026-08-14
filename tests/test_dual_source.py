"""MAPGEN-020 — two sources, and the distinctions that keep them honest.

The load-bearing one: a territory staying under the same ruler and a drawn
line staying in the same place are different claims, and only the first was
ever shown.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

H = Path("data/historical")
SD = Path("data/scenarios/seven_years_war_1756_08_01")


@pytest.fixture(scope="module")
def seg():
    return pd.read_csv(H / "brandenburg_boundary_segment_continuity.csv",
                       keep_default_na=False, na_values=[""])


@pytest.fixture(scope="module")
def cases():
    return pd.read_csv(H / "brandenburg_local_boundary_cases.csv")


@pytest.fixture(scope="module")
def blha():
    return pd.read_csv(H / "brandenburg_blha_observed_points.csv")


# ---------------------------------------------------------------------------
# continuity semantics
# ---------------------------------------------------------------------------
def test_political_and_boundary_continuity_are_separate_columns(seg):
    """MAPGEN-019 had one column asserting both. It cannot come back."""
    assert "territorial_political_continuity" in seg.columns
    assert "boundary_position_continuity" in seg.columns
    assert "continuity_status" not in seg.columns


def test_political_continuity_does_not_imply_boundary_continuity(seg):
    pol_ok = seg[seg["territorial_political_continuity"] == "CONTINUOUS"]
    assert len(pol_ok) >= 8
    unconfirmed = pol_ok[pol_ok["boundary_position_continuity"]
                         != "CONFIRMED_WITHIN_SOURCE_UNCERTAINTY"]
    assert len(unconfirmed) >= 4, (
        "if every politically continuous subsegment also had a confirmed "
        "boundary, the split would be doing no work")


def test_every_frontier_with_a_local_case_also_has_a_remainder(seg):
    """A single Feldmark must never condemn a whole frontier."""
    local = seg[~seg["boundary_position_continuity"].isin(
        ["CONFIRMED_WITHIN_SOURCE_UNCERTAINTY", "NOT_APPLICABLE"])]
    for sid in local["segment_id"].unique():
        sub = seg[seg["segment_id"] == sid]
        assert len(sub) >= 2, f"{sid} has a local case but no remainder"


def test_subsegment_ids_are_unique_and_nested_under_segments(seg):
    assert seg["subsegment_id"].nunique() == len(seg)
    assert seg["segment_id"].nunique() < len(seg)


def test_swedish_pomerania_is_not_a_brandenburg_frontier(seg):
    """After the 1720 Treaty of Stockholm the Swedish line lay north of the
    Peene, bordering Prussian Pomerania and Mecklenburg."""
    sw = seg[seg["segment_id"] == "seg_swedish_pomerania"]
    assert len(sw) == 1
    assert sw.iloc[0]["territorial_political_continuity"] == "NOT_APPLICABLE"
    assert sw.iloc[0]["boundary_position_continuity"] == "NOT_APPLICABLE"
    assert "1720" in sw.iloc[0]["change_evidence"]
    # and the real northern frontier is recorded under its own name
    assert (seg["segment_id"] == "seg_prussian_pomerania").any()


# ---------------------------------------------------------------------------
# archival cases
# ---------------------------------------------------------------------------
def test_all_archival_cases_carry_a_verifiable_locator(cases):
    assert len(cases) == 5
    assert (cases["verified_at_source"] == "YES").all()
    for r in cases.itertuples():
        assert r.archival_signature
        assert r.bestand
        assert r.classification_path
        assert r.laufzeit
        assert str(r.blha_internal_id).isdigit()


def test_saxony_case_is_the_international_one(cases):
    r = cases[cases.case_id == "case_saxony_branitz_weissagk_groetsch"].iloc[0]
    assert r["is_international"] == "YES"
    assert r["laufzeit"] == "1748-1751"
    assert "Ebeling" in r["corroborating_file"]
    assert r["settled_before_1751_source_state"] == "UNRESOLVED"


def test_glauchow_sabor_is_a_forest_boundary_not_a_transfer(cases):
    """The Laufzeit spans the window, which is why it had to be read rather
    than assumed."""
    r = cases[cases.case_id == "case_silesia_glauchow_sabor"].iloc[0]
    assert "Forstgrenzen" in r["classification_path"]
    assert r["is_international"] == "NO"
    assert r["classification"] == (
        "BOUNDARY_REGULATION_WITHOUT_TERRITORIAL_TRANSFER")


def test_gartz_dispute_is_not_settled_inside_the_window(cases):
    r = cases[cases.case_id == "case_pompom_gartz_vierraden"].iloc[0]
    assert r["effective_date"] == "NOT_SETTLED_IN_WINDOW"
    assert "1770-1789" in r["corroborating_file"]


def test_a_claim_is_not_a_boundary_change(cases):
    r = cases[cases.case_id == "case_commonwealth_drage_driesen"].iloc[0]
    assert r["classification"] == "CLAIM_WITHOUT_EFFECTED_CHANGE"
    assert r["effective_date"] == "NO_CHANGE_EFFECTED"


# ---------------------------------------------------------------------------
# the BLHA georeference is independent
# ---------------------------------------------------------------------------
def test_blha_points_never_reuse_the_bnf_transform_or_pixels(blha):
    bnf = pd.read_csv(H / "brandenburg_observed_feature_points.csv")
    assert (blha["bnf_transform_used"] == "NO").all()
    assert (blha["bnf_pixel_reused"] == "NO").all()
    assert (blha["georeference_source"] == "BLHA_AKS_1145_A_ONLY").all()
    shared = (set(zip(bnf["pixel_x"].round(1), bnf["pixel_y"].round(1)))
              & set(zip(blha["pixel_x"].round(1), blha["pixel_y"].round(1))))
    assert not shared


def test_blha_meets_the_point_minimum_and_spans_zones(blha):
    assert len(blha) >= 16
    assert blha["zone"].nunique() == 5


def test_blha_split_is_disjoint_and_blind_is_large_enough(blha):
    sets = {r: set(blha.loc[blha.split_role == r, "point_id"])
            for r in ("FIT", "MODEL_SELECTION_HOLDOUT", "BLIND_VALIDATION")}
    assert not sets["FIT"] & sets["MODEL_SELECTION_HOLDOUT"]
    assert not sets["FIT"] & sets["BLIND_VALIDATION"]
    assert not sets["MODEL_SELECTION_HOLDOUT"] & sets["BLIND_VALIDATION"]
    assert len(sets["BLIND_VALIDATION"]) >= 4


def test_seeded_points_cannot_be_blind_validation(blha):
    blind = blha[blha.split_role == "BLIND_VALIDATION"]
    assert (blind["discovery"] == "MAP_FIRST_GLOBAL_SYMBOL_SCAN").all()


def test_blha_uncertainty_is_not_the_bnf_figure():
    a = pd.read_csv(H / "brandenburg_blha_georeference_audit.csv")
    sel = a[a["selected"].astype(bool)].iloc[0]
    bnf = json.loads((H / "brandenburg_bnf_transform.json").read_text(
        encoding="utf-8"))
    assert sel["independent_of_bnf"] == "YES"
    assert abs(float(sel["positional_uncertainty_km"])
               - float(bnf["positional_uncertainty_km"])) > 1.0
    assert float(sel["positional_uncertainty_km"]) >= float(
        sel["blind_p90_km"])


def test_the_two_sheets_do_not_share_a_prime_meridian():
    """Independent witnesses, demonstrated rather than assumed."""
    blha = json.loads((H / "brandenburg_blha_transform.json").read_text(
        encoding="utf-8"))
    bnf = json.loads((H / "brandenburg_bnf_transform.json").read_text(
        encoding="utf-8"))
    assert bnf["prime_meridian"] == "FERRO_20W_OF_PARIS"
    assert blha["prime_meridian"] != bnf["prime_meridian"]
    cand = pd.read_csv(H / "brandenburg_blha_prime_meridian_audit.csv")
    ferro = cand[cand.candidate == "FERRO_20W_OF_PARIS"].iloc[0]
    best = cand.sort_values("median_residual_km").iloc[0]
    assert float(ferro["median_residual_km"]) > 100.0
    assert float(best["median_residual_km"]) < 30.0


def test_blha_rejections_are_recorded_not_silently_dropped():
    rej = pd.read_csv(H / "brandenburg_blha_rejected_candidates.csv")
    assert len(rej) >= 2
    assert (rej["reason"].str.len() > 40).all()
    assert rej["candidate"].is_unique


# ---------------------------------------------------------------------------
# geometry discipline
# ---------------------------------------------------------------------------
def test_colour_is_never_the_controller():
    comp = pd.read_csv(H / "brandenburg_component_audit.csv")
    assert (comp["colour_used_as_controller"] == "NO").all()
    assert comp["controller_basis"].str.contains("LABEL").all()


def test_brandenburg_components_audited_and_neighbours_excluded():
    comp = pd.read_csv(H / "brandenburg_component_audit.csv")
    inside = set(comp[comp.in_brandenburg == "YES"]["component"])
    outside = set(comp[comp.in_brandenburg == "NO"]["component"])
    assert {"Altmark", "Mittelmark", "Neumark", "Uckermark",
            "Prignitz"} <= inside
    assert {"Duchy of Magdeburg", "Principality of Halberstadt",
            "Pomerania"} <= outside
    assert not inside & outside


def test_inset_keeps_its_own_gap():
    i = pd.read_csv(H / "brandenburg_inset_audit.csv").iloc[0]
    assert i["main_transform_applied"] == "NO"
    assert i["status"] == "INSET_GEOMETRY_GAP"
    assert i["resolved_by_blha"] == "NO"


def test_digitisation_failure_is_recorded_not_hidden():
    d = pd.read_csv(H / "brandenburg_source_digitisation_audit.csv",
                    keep_default_na=False, na_values=[""])
    assert len(d) == 2
    assert (d["geometry_written"] == "NO").all()
    assert (d["traced_from_other_source"] == "NO").all()
    bnf = d[d["sheet"].str.contains("BnF")].iloc[0]
    assert bnf["attempted"] == "YES"
    assert bnf["conclusion"] == "NO_POLYGON_PRODUCED"
    assert len(str(bnf["diagnosis"])) > 60


def test_no_cross_source_audit_was_invented():
    """An audit file with zero samples would read as 'measured and agreed'."""
    assert not (H / "brandenburg_cross_source_boundary_audit.csv").exists()


def test_no_safe_interior_audit_without_polygons():
    assert not (H / "brandenburg_safe_interior_audit.csv").exists()


# ---------------------------------------------------------------------------
# nothing was produced, and that is recorded honestly
# ---------------------------------------------------------------------------
def test_no_geometry_and_no_control_were_produced():
    import geopandas as gpd
    f = gpd.read_parquet(H / "historical_boundary_features.parquet")
    assert len(f) == 3
    assert "hsrc_d22d155bbd4a" not in set(f["global_source_id"])
    ev = pd.read_csv(H / "historical_evidence_assertions.csv")
    assert "hsrc_d22d155bbd4a" not in set(ev["global_source_id"])


def test_brandenburg_holds_nothing_and_no_root_duplicates():
    c = pd.read_csv(SD / "territorial_control.csv", keep_default_na=False,
                    na_values=[""])
    assert len(c) == 1614
    v = c["control_status"].value_counts().to_dict()
    assert v["CONTROLLED"] == 697 and v["UNRESOLVED"] == 917
    assert not c["controller_scenario_polity_id"].str.contains(
        "brandenburg", case=False).any()


def test_coverage_control_status_stays_unassessed():
    cov = pd.read_csv(SD / "political_coverage.csv", keep_default_na=False,
                      na_values=[""])
    row = cov[cov["coverage_unit_id"] == "region_brandenburg_1756_pilot"]
    assert len(row) == 1
    assert row.iloc[0]["control_coverage_status"] == "UNASSESSED"
    assert int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0


def test_1756_political_evidence_is_carried_forward_unchanged():
    pol = pd.read_csv(H / "brandenburg_1756_political_evidence.csv",
                      keep_default_na=False, na_values=[""])
    assert len(pol) == 5
    assert (pol["status"] == "OBTAINED").all()
    assert set(pol["evidence_role"]) <= {"POLITICAL_CONTROL",
                                         "ADMINISTRATIVE_SCOPE"}
