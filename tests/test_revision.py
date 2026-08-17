# -*- coding: utf-8 -*-
"""MAPGEN-014 — corroboration, model correction and authority revision.

The rules defended here: a superseded model artifact must stop being a
territorial actor without being deleted, an unpartitioned source region
must never bind, a derivative source must never count as corroboration,
off-date geometry needs continuity rather than mere existence, and a
reviewed row that is known to be stale must not survive a revision.
"""
from pathlib import Path

import pandas as pd
import pytest

from mapgen.historical_geometry import (FEATURE_ROLE_REQUIREMENTS,
                                        GAMEPLAY_CONVERTIBLE_ROLES)
from mapgen.scenario_promotion import (REVISION_LOG_COLUMNS, promote_control,
                                       revise_control)

DATA = Path("data")
H = DATA / "historical"
SC = "seven_years_war_1756_08_01"
SD = DATA / "scenarios" / SC
WASH = "hsub_schwarzburg_unpartitioned_wash"
NEW = ["pol_schwarzburg_rudolstadt", "pol_schwarzburg_sondershausen"]
SRC = "src_test0000"


def _cand(n=3, status="CONTROLLED", controller="sp_a", start=0):
    return pd.DataFrame([{
        "scenario_id": "s", "territorial_target_type": "TERRESTRIAL_HEX",
        "territorial_target_id": f"h{start + i}",
        "controller_scenario_polity_id":
            controller if status == "CONTROLLED" else None,
        "control_status": status, "source_confidence": "MEDIUM",
        "source_id": "hsrc_x", "source_ids": "hsrc_x",
        "political_evidence_ids": "hev_x", "boundary_feature_ids": "hbf_x",
        "historical_subject_ids": "hsub_x", "notes": "",
    } for i in range(n)])


def _empty():
    return (pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"]),
        pd.DataFrame(columns=[
            "scenario_id", "territorial_target_type",
            "territorial_target_id", "scenario_source_id",
            "global_source_ids", "historical_evidence_ids",
            "boundary_feature_ids", "historical_subject_ids",
            "bundle_confidence", "promotion_id", "source_stage", "notes"]),
        pd.DataFrame(columns=[
            "promotion_id", "scenario_id", "source_stage",
            "source_commit_sha", "candidate_artifact", "candidate_sha256",
            "review_status", "promotion_status", "promoted_utc",
            "promoted_row_count", "controlled_count", "unresolved_count",
            "supersedes_promotion_id", "notes"]),
        pd.DataFrame(columns=REVISION_LOG_COLUMNS))


def _promoted():
    c, p, lg, rv = _empty()
    c, p, lg, _ = promote_control(c, p, lg, _cand(), "s", "OLD", "sha",
                                  "a.csv", SRC, promoted_utc="2026-01-01")
    return c, p, lg, rv


def _revise(candidate, **kw):
    c, p, lg, rv = _promoted()
    args = dict(scenario_id="s", stage="NEW", source_commit_sha="sha2",
                candidate_artifact="b.csv", scenario_source_id=SRC,
                reason="re-measured", old_uncertainty_km=2.975,
                new_uncertainty_km=9.168, promoted_utc="2026-08-13")
    args.update(kw)
    return revise_control(c, p, lg, rv, candidate, **args)


def test_stale_authority_cannot_survive_a_revision():
    c, p, lg, rv, rep = _revise(_cand(status="UNRESOLVED"))
    assert rep["revised"] == 3 and rep["unchanged"] == 0
    assert set(c["control_status"]) == {"UNRESOLVED"}
    assert c["controller_scenario_polity_id"].isna().all()


def test_revision_writes_the_full_before_and_after():
    _, _, _, rv, _ = _revise(_cand(status="UNRESOLVED"))
    assert list(rv.columns) == REVISION_LOG_COLUMNS
    r = rv.iloc[0]
    assert r["old_status"] == "CONTROLLED" and r["new_status"] == "UNRESOLVED"
    assert r["old_controller"] == "sp_a" and pd.isna(r["new_controller"])
    assert r["old_uncertainty_km"] == 2.975
    assert r["new_uncertainty_km"] == 9.168
    assert r["old_promotion_id"] and r["new_promotion_id"]


def test_superseded_promotion_is_marked_not_deleted():
    _, _, lg, _, _ = _revise(_cand(status="UNRESOLVED"))
    assert len(lg) == 2
    assert (lg["promotion_status"] == "SUPERSEDED").sum() == 1
    assert lg.iloc[-1]["supersedes_promotion_id"]


def test_revision_is_idempotent_and_logs_nothing_the_second_time():
    cand = _cand(status="UNRESOLVED")
    c, p, lg, rv, _ = _revise(cand)
    c2, p2, lg2, rv2, rep2 = revise_control(
        c.copy(), p.copy(), lg.copy(), rv.copy(), cand, "s", "NEW", "sha2",
        "b.csv", SRC, "re-measured", 2.975, 9.168,
        promoted_utc="2026-08-13")
    assert rep2["revised"] == 0 and rep2["unchanged"] == 3
    assert len(rv2) == len(rv)
    pd.testing.assert_frame_equal(c, c2)


def test_unchanged_rows_produce_no_revision_entry():
    _, _, _, rv, rep = _revise(_cand())
    assert rep["revised"] == 0 and rep["unchanged"] == 3 and len(rv) == 0


def test_revision_can_also_change_the_controller():
    _, _, _, rv, rep = _revise(_cand(controller="sp_b"))
    assert rep["revised"] == 3
    assert (rv["old_controller"] == "sp_a").all()
    assert (rv["new_controller"] == "sp_b").all()


def test_revision_inserts_targets_that_did_not_exist():
    _, _, _, rv, rep = _revise(_cand(n=2, start=90))
    assert rep["inserted"] == 2 and rep["revised"] == 0 and len(rv) == 0


def test_conflict_target_revision_replaces_provenance_not_history():
    c, p, lg, rv, _ = _revise(_cand(status="UNRESOLVED"))
    assert len(p) == 3                      # one provenance row per target
    assert set(p["source_stage"]) == {"NEW"}
    assert len(lg) == 2                     # both promotions remain
    assert set(p["territorial_target_id"]) <= set(
        c["territorial_target_id"])


def test_unpartitioned_wash_role_is_not_gameplay_convertible():
    assert "UNCERTAIN_BOUNDARY" not in GAMEPLAY_CONVERTIBLE_ROLES
    assert "UNCERTAIN_BOUNDARY" not in FEATURE_ROLE_REQUIREMENTS


PROD = (H / "historical_boundary_features.parquet").exists()
pytestmark_prod = pytest.mark.skipif(not PROD, reason="no production data")


@pytest.mark.skipif(not PROD, reason="no production data")
def test_production_wash_cannot_bind():
    import geopandas as gpd

    f = gpd.read_parquet(H / "historical_boundary_features.parquet")
    row = f[f["historical_subject_id"] == WASH]
    assert len(row) == 1
    assert row.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY"
    mp = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    assert WASH not in set(mp["historical_subject_id"])
    assert "hsub_schwarzburg" not in set(f["historical_subject_id"])


@pytest.mark.skipif(not PROD, reason="no production data")
def test_superseded_artifact_is_retained_but_not_a_territorial_actor():
    sp = pd.read_csv(SD / "scenario_polities.csv")
    row = sp[sp["polity_id"] == "pol_schwarzburg"]
    assert len(row) == 1, "the artifact must not be deleted"
    assert row.iloc[0]["existence_status"] == "MODEL_ARTIFACT_SUPERSEDED"
    assert row.iloc[0]["territorial_authority_role"] \
        == "NON_TERRITORIAL_INSTITUTION"
    assert row.iloc[0]["territorial_authority_role"] \
        != "STRUCTURAL_CONTAINER", "a dynasty is not a container"


@pytest.mark.skipif(not PROD, reason="no production data")
def test_two_replacement_polities_remain_distinct():
    pol = pd.read_csv(DATA / "scenarios" / "polities.csv")
    sp = pd.read_csv(SD / "scenario_polities.csv")
    assert set(NEW) <= set(pol["polity_id"])
    rows = sp[sp["polity_id"].isin(NEW)]
    assert len(rows) == 2
    assert rows["scenario_polity_id"].nunique() == 2
    assert rows["display_name"].nunique() == 2
    rel = pd.read_csv(SD / "scenario_polity_relationships.csv")
    for sid in rows["scenario_polity_id"]:
        assert ((rel["from_scenario_polity_id"] == sid)
                & (rel["relationship_type"] == "IMPERIAL_MEMBER_OF")).any()


@pytest.mark.skipif(not PROD, reason="no production data")
def test_neither_replacement_polity_controls_territory():
    c = pd.read_csv(SD / "territorial_control.csv")
    sp = pd.read_csv(SD / "scenario_polities.csv")
    ids = set(sp.loc[sp["polity_id"].isin(NEW), "scenario_polity_id"])
    assert not c["controller_scenario_polity_id"].isin(ids).any()


@pytest.mark.skipif(not PROD, reason="no production data")
def test_source_lineage_rejects_derivative_corroboration():
    lin = pd.read_csv(H / "historical_source_lineage.csv")
    assert len(lin) >= 4
    elig = lin[lin["corroboration_eligible"] == "YES"]
    assert not elig["independence_status"].isin(
        ["DERIVATIVE", "SAME_PLATE"]).any()
    assert elig["independence_reason"].str.len().min() > 40
    assert lin["plate_family"].nunique() >= 2


@pytest.mark.skipif(not PROD, reason="no production data")
def test_off_date_source_has_no_geometry_authority():
    """1747 geometry may not become 1756 control without a continuity
    bridge — and no continuity assertion has been made, so it must carry
    no geometry authority at all."""
    a = pd.read_csv(H / "historical_evidence_assertions.csv")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    sid = reg.loc[reg["citation_key"].str.contains("zollmann_1747"),
                  "global_source_id"]
    assert len(sid) == 1
    rows = a[a["global_source_id"] == sid.iloc[0]]
    assert not (rows["geometry_authority"] == "YES").any()


@pytest.mark.skipif(not PROD, reason="no production data")
def test_existence_evidence_is_never_continuity():
    a = pd.read_csv(H / "historical_evidence_assertions.csv")
    ndb = a[a["exact_locator"].fillna("").str.contains("NDB 24")]
    assert len(ndb) == 2
    assert set(ndb["assertion_type"]) == {"POLITY_EXISTENCE"}
    assert set(ndb["geometry_authority"]) == {"NO"}
    assert set(ndb["political_authority"]) == {"YES"}


@pytest.mark.skipif(not PROD, reason="no production data")
def test_revision_log_only_moved_rows_out_of_controlled():
    p = SD / "territorial_control_revision_log.csv"
    if not p.exists():
        pytest.skip("revision not run")
    rv = pd.read_csv(p)
    assert len(rv) > 0
    # MAPGEN-014 moved rows OUT of CONTROLLED after re-measuring, and this
    # is the test of that. MAPGEN-027 moves rows the other way, on new
    # evidence rather than a new measurement, so it is scoped out by its
    # own reason rather than by weakening the assertion.
    m14 = rv[~rv["reason"].str.contains("Portugal safe interior v",
                                        na=False)]
    assert len(m14) > 0
    assert not ((m14["old_status"] == "UNRESOLVED")
                & (m14["new_status"] == "CONTROLLED")).any()
    assert (m14["new_uncertainty_km"] > m14["old_uncertainty_km"]).all()


@pytest.mark.skipif(not PROD, reason="no production data")
def test_no_stale_uncertainty_left_in_canonical_authority():
    p = SD / "territorial_control_revision_log.csv"
    if not p.exists():
        pytest.skip("revision not run")
    rv = pd.read_csv(p)
    c = pd.read_csv(SD / "territorial_control.csv")
    revised = set(rv["territorial_target_id"])
    assert revised <= set(c["territorial_target_id"])
    m14 = rv[~rv["reason"].str.contains("Portugal safe interior v",
                                        na=False)]
    assert float(m14["old_uncertainty_km"].max()) == 2.975


def test_unchanged_rows_keep_their_original_provenance():
    """A revision must not strip provenance from rows it did not change:
    that would erase which promotion established them."""
    c, p, lg, rv = _promoted()
    before = len(p)
    cand = pd.concat([_cand(n=2), _cand(n=1, status="UNRESOLVED",
                                        start=2)], ignore_index=True)
    c2, p2, lg2, rv2, rep = revise_control(
        c, p, lg, rv, cand, "s", "NEW", "sha2", "b.csv", SRC,
        "re-measured", 2.975, 9.168, promoted_utc="2026-08-13")
    assert rep["unchanged"] == 2 and rep["revised"] == 1
    assert len(p2) == before, "no provenance row may be lost"
    assert set(p2["source_stage"]) == {"OLD", "NEW"}
    assert p2[p2["source_stage"] == "NEW"]["territorial_target_id"].tolist() \
        == ["h2"]
