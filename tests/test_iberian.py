"""MAPGEN-026 — a safe interior is a claim about doubt, not about land.

Three tests here carry the whole design. The first is that the produced
geometry is a SUBSET of an extent and never the extent itself, so nobody
downstream can read the outline of Spain's safe interior as the outline of
Spain. The second is that the erosion distance is a measurement — the p95
residual at points the fit never saw — and not a number somebody liked.
The third is that everything the plate cannot place gets an explicit
UNRESOLVED row, because a missing row reads as "nobody looked".

The rest guard the specific ways this stage could have cheated: absorbing
Gibraltar or Andorra, back-dating Olivenza, folding the Algarve into
Portugal for tidiness, or quietly claiming a cell that holds settlements of
both crowns.
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
def obs():
    return pd.read_csv(H / "iberia_lerouge_observed_points.csv")


@pytest.fixture(scope="module")
def transform():
    return json.loads((H / "iberia_lerouge_transform.json").read_text(
        encoding="utf-8"))


@pytest.fixture(scope="module")
def mix():
    return pd.read_csv(H / "iberia_hex_membership_audit.csv")


@pytest.fixture(scope="module")
def cells():
    return pd.read_csv(H / "iberia_cell_ownership_audit.csv",
                       keep_default_na=False, na_values=[])


# ---------------------------------------------------------------------------
# the three rules everything else rests on
# ---------------------------------------------------------------------------
def test_the_feature_is_a_subset_not_a_boundary():
    """The geometry says 'ground this crown held', never 'here is Spain'.

    If this ever became a POLITY_EXTERNAL_BOUNDARY, or lost the note that
    says what it is not, a later stage would read a safe interior as a
    country outline and every frontier hex would silently move.
    """
    import geopandas as gpd
    f = gpd.read_parquet(H / "historical_boundary_features.parquet")
    ib = f[f.historical_subject_id.str.contains("iberian_mainland")]
    assert len(ib) == 2
    assert set(ib.feature_role) == {"DE_FACTO_CONTROL_BOUNDARY"}
    assert (ib.geometry_status
            == "SAFE_INTERIOR_SUBSET_OF_AUTHORISED_EXTENT").all()
    assert ib.notes.str.startswith("NOT the crown's boundary").all()


def test_the_erosion_distance_is_measured(obs, transform):
    """34.6 km is a p95 of residuals, not a round number somebody chose."""
    unseen = obs[obs.split_role != "FIT"]
    assert len(unseen) == transform["n_unseen"] > 0
    import numpy as np
    p95 = float(np.percentile(unseen.residual_m, 95))
    assert abs(transform["unseen_p95_m"] - p95) < 1.0
    # and it is the number the features actually carry
    import geopandas as gpd
    f = gpd.read_parquet(H / "historical_boundary_features.parquet")
    ib = f[f.historical_subject_id.str.contains("iberian_mainland")]
    assert (abs(ib.positional_uncertainty_km - p95 / 1000) < 0.01).all()


def test_everything_unplaceable_gets_an_explicit_row(canon, mix):
    """Absence of a row means UNKNOWN, so absence is never left to speak."""
    produced = set(mix.loc[mix.control_status != "NOT_PRODUCED", "hex_id"])
    rows = canon[canon.territorial_target_id.isin(produced)]
    assert len(rows) == len(produced)
    unresolved = rows[rows.control_status == "UNRESOLVED"]
    assert len(unresolved) > 10000
    assert unresolved.controller_scenario_polity_id.fillna("").eq("").all()
    assert unresolved.notes.str.contains("held back").all()


# ---------------------------------------------------------------------------
# the specific ways this stage could have cheated
# ---------------------------------------------------------------------------
def test_special_cases_are_withheld_from_both_crowns():
    cases = pd.read_csv(H / "iberia_special_cases.csv")
    assert {"GIBRALTAR", "ANDORRA", "LLIVIA", "OLIVENZA", "COUTO_MISTO",
            "CEUTA"} <= set(cases.case)
    assert (cases.treatment
            == "WITHHELD_FROM_EVERY_SAFE_INTERIOR").all()
    assert (cases.withheld_radius_km > 30).all()


def test_no_cell_with_two_crowns_was_ever_owned(cells):
    owned = cells[cells.outcome == "OWNED"]
    assert len(owned) >= 9
    assert (owned.reason == "ONE_CROWN_ONLY_IN_CELL").all()
    assert set(owned.crown) <= {"SPAIN", "PORTUGAL", "FRANCE"}
    leaks = cells[cells.reason == "MIXED_CROWN_LEAK"]
    assert len(leaks) >= 2
    assert (leaks.crown == "").all()


def test_the_algarve_deferral_was_superseded_by_evidence(cells):
    """MAPGEN-026 deferred the Algarve rather than annexing it on a map
    title. That was right, and MAPGEN-027 ended the deferral the only way
    it could be ended: with institutional evidence, recorded per axis.

    The assertion here is not that the Algarve is still withheld - it is
    that it stopped being withheld because of an audit, and that the audit
    is on the record.
    """
    alg = cells[cells.cell == 18]
    assert len(alg) == 1
    assert alg.iloc[0].crown == "PORTUGAL"
    assert alg.iloc[0].decided_by_stage == "MAPGEN-027"
    audit = pd.read_csv(H / "algarve_constitutional_audit.csv",
                        keep_default_na=False, na_values=[])
    assert len(audit) >= 7
    assert "TITLE_IS_NOT_ACTOR_EVIDENCE" in set(audit.verdict)
    assert "SEPARATE_ACTOR" not in set(audit.verdict)


def test_france_was_identified_only_to_be_kept_out(canon, cells):
    """French cells are read so Spain cannot absorb Gascony or Roussillon,
    and then no French control row is written: this stage has no French
    political evidence and produces none."""
    assert "FRANCE" in set(cells.crown)
    ib = set(pd.read_csv(H / "iberia_hex_membership_audit.csv")["hex_id"])
    rows = canon[canon.territorial_target_id.isin(ib)]
    assert set(rows.controller_scenario_polity_id.fillna("")) <= {
        "", SPAIN_SP, PORTUGAL_SP}


# ---------------------------------------------------------------------------
# georeference discipline
# ---------------------------------------------------------------------------
def test_border_ticks_are_never_two_dimensional_control():
    g = pd.read_csv(H / "iberia_lerouge_plate_graticule_observations.csv")
    assert len(g) > 30
    assert (g.eligible_as_2d_gcp == "NO").all()
    assert (g.second_coordinate_known == "NO").all()


def test_the_split_was_frozen_before_any_model_was_fitted(obs):
    assert set(obs.split_role) == {"FIT", "MODEL_SELECTION_HOLDOUT",
                                   "BLIND_VALIDATION"}
    assert obs.split_reason.str.startswith("frozen before any fit").all()
    # the rule is reproducible from the data alone
    face = (232, 262, 6022, 4630)
    mx, my = (face[0] + face[2]) / 2, (face[1] + face[3]) / 2
    cycle = ["FIT", "FIT", "MODEL_SELECTION_HOLDOUT", "FIT",
             "BLIND_VALIDATION"]
    zone = [("N" if y < my else "S") + ("W" if x < mx else "E")
            for x, y in zip(obs.pixel_x, obs.pixel_y)]
    got = {}
    d = obs.assign(zone=zone)
    for z, sub in d.groupby("zone"):
        for i, pid in enumerate(sorted(sub.point_id)):
            got[pid] = cycle[i % len(cycle)]
    assert got == dict(zip(obs.point_id, obs.split_role))


def test_the_simplest_model_inside_the_holdout_band_won(transform):
    from mapgen.historical_georeference import TRANSFORM_MODELS
    m = pd.read_csv(H / "iberia_lerouge_model_comparison.csv")
    ok = m[m.status == "FITTED"].dropna(subset=["holdout_rms_m"])
    assert set(ok.model) == set(TRANSFORM_MODELS)
    best = ok.holdout_rms_m.min()
    within = ok[ok.holdout_rms_m <= best * 1.10]
    simplest = sorted(within.model, key=TRANSFORM_MODELS.index)[0]
    assert transform["model"] == simplest
    assert not transform["jacobian"]["folding"]


def test_the_prime_meridian_is_audited_and_never_applied(transform):
    a = pd.read_csv(H / "iberia_lerouge_prime_meridian_candidate_audit.csv")
    assert (a.scored_on.str.contains("blind untouched")).all()
    assert list(a.status).count("ADOPTED_AS_PLATE_MERIDIAN") == 1
    assert "GREENWICH" in set(a.candidate) and "PARIS" in set(a.candidate)
    assert transform["prime_meridian_role"].startswith("DIAGNOSTIC_ONLY")


def test_rejected_anchors_carry_a_reason_each():
    r = pd.read_csv(H / "iberia_lerouge_rejected_candidates.csv",
                    keep_default_na=False, na_values=[])
    assert len(r) >= 10
    assert (r.reason.str.len() > 5).all()
    assert {"NO_SYMBOL_AT_RECORDED_PIXEL", "WRONG_SETTLEMENT",
            "AMBIGUOUS_LABEL"} <= set(r.reason)


def test_enough_correspondences_and_all_of_them_observed(obs):
    assert len(obs) >= 32                       # the brief's target
    assert (obs.observation_class == "OBSERVED_FEATURE_POINT").all()
    assert (obs.pixel_coordinate_directly_observed == "YES").all()
    assert obs.point_id.is_unique
    assert obs.geonameid.is_unique


# ---------------------------------------------------------------------------
# production
# ---------------------------------------------------------------------------
def test_only_whole_land_hexes_are_controlled(mix):
    c = mix[mix.control_status == "CONTROLLED"]
    assert (c.basis == "WHOLE_HEX_LAND_INSIDE_SAFE_INTERIOR").all()
    share = ((c.spain_safe_km2 + c.portugal_safe_km2) / c.hex_land_km2)
    assert share.min() >= 0.98
    assert c.is_terrestrial_hex.all()


def test_no_non_terrestrial_hex_was_produced(canon, mix):
    hx = pd.read_parquet(EU, columns=["hex_id", "is_terrestrial_hex"])
    terr = set(hx.loc[hx.is_terrestrial_hex, "hex_id"])
    produced = set(mix.loc[mix.control_status != "NOT_PRODUCED", "hex_id"])
    assert produced <= terr
    assert int((mix.control_status == "NOT_PRODUCED").sum()) > 0


def test_earlier_stages_are_untouched(canon):
    from _production_baseline import strip_iberia_production
    before = strip_iberia_production(canon)
    assert len(before) == 53579
    assert int((before.control_status == "CONTROLLED").sum()) == 52510
    assert int((before.control_status == "UNRESOLVED").sum()) == 1069


def test_portugal_result_is_thin_and_that_is_recorded(mix):
    """The 26 hexes are the finding. If this ever grows without the
    uncertainty shrinking, something has been loosened."""
    c = mix[mix.control_status == "CONTROLLED"]
    assert int((c.winner == "PORTUGAL").sum()) == 26
    assert int((c.winner == "SPAIN").sum()) > 5000
    cov = pd.read_csv(SD / "political_coverage.csv", keep_default_na=False,
                      na_values=[])
    row = cov[cov.coverage_unit_id == "region_portugal_iberian_mainland_1756"]
    assert len(row) == 1
    assert row.iloc[0].control_coverage_status == "TERRITORY_PARTIAL"
    assert "THIN" in row.iloc[0].notes


def test_the_source_licence_permits_commercial_reuse():
    a = pd.read_csv(H / "historical_source_assessment.csv",
                    keep_default_na=False, na_values=[])
    reg = pd.read_csv(H / "historical_source_registry.csv",
                      keep_default_na=False, na_values=[])
    gsid = reg.loc[reg.citation_key
                   == "lerouge_1756_atlas_portatif_espagne_portugal",
                   "global_source_id"].iloc[0]
    row = a[a.global_source_id == gsid].iloc[0]
    assert row.licence_verified == "YES"
    assert row.redistribution_allowed == "YES"
    note = reg.loc[reg.global_source_id == gsid,
                   "licence_or_usage_note"].iloc[0].lower()
    assert "not david rumsey" in note and "not gallica" in note


def test_lineage_is_recorded_as_unestablished():
    """Le Rouge compiled other houses' plates. Not knowing whose is a
    fact about the source and is written down as one."""
    ln = pd.read_csv(H / "historical_source_lineage.csv",
                     keep_default_na=False, na_values=[])
    reg = pd.read_csv(H / "historical_source_registry.csv",
                      keep_default_na=False, na_values=[])
    gsid = reg.loc[reg.citation_key
                   == "lerouge_1756_atlas_portatif_espagne_portugal",
                   "global_source_id"].iloc[0]
    row = ln[ln.global_source_id == gsid].iloc[0]
    assert row.independence_status == "LINEAGE_NOT_ESTABLISHED"
    assert row.corroboration_eligible == "NO"


def test_every_gate_passed():
    v = pd.read_csv(
        "reviews/MAPGEN-026/validation.csv")
    assert len(v) == 44
    assert bool(v["pass"].all()), v[~v["pass"]].to_string()
