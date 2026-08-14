"""MAPGEN-008 unit tests — scenario political geography foundation.

Synthetic fixtures live ONLY here (tmp dirs); production scenario data
contains no synthetic political rows.
"""
from pathlib import Path

import pandas as pd
import pytest

from mapgen.scenario import (SCENARIO_ALGORITHM_VERSION, SCENARIO_FILES,
                             SCENARIO_SCHEMA_VERSION, ScenarioNotFoundError,
                             load_scenario, load_scenario_registry,
                             make_evidence_id, make_relationship_id,
                             make_scenario_polity_id, make_source_id)

DATA = Path("data")
SC = "seven_years_war_1756_08_01"


def _write_synthetic(root: Path, scenario_id="syn_test_scenario_0001"):
    sdir = root / "scenarios" / scenario_id
    sdir.mkdir(parents=True)
    pd.DataFrame([{
        "scenario_id": scenario_id, "display_name_en": "Synthetic",
        "display_name_ja": "合成テスト", "snapshot_date": "1700-01-01",
        "scenario_type": "CAMPAIGN_START", "historicity": "SYNTHETIC_TEST",
        "description": "TEST ONLY", "data_status": "FOUNDATION_ONLY",
        "political_geography_complete": False,
        "gameplay_authoritative": True,
        "source_set_id": "srcset_syn", "scenario_schema_version": "1.0.0",
    }]).to_csv(root / "scenarios" / "scenario_registry.csv", index=False)
    pd.DataFrame([
        {"polity_id": "pol_syn_a", "canonical_name": "Synthetic A",
         "polity_kind": "STATE", "notes": "TEST ONLY"},
        {"polity_id": "pol_syn_b", "canonical_name": "Synthetic B",
         "polity_kind": "STATE", "notes": "TEST ONLY"},
    ]).to_csv(root / "scenarios" / "polities.csv", index=False)
    sp_a = make_scenario_polity_id(scenario_id, "pol_syn_a")
    sp_b = make_scenario_polity_id(scenario_id, "pol_syn_b")
    pd.DataFrame([
        {"scenario_id": scenario_id, "scenario_polity_id": s,
         "polity_id": p, "display_name": n, "short_name": n,
         "existence_status": "EXISTS", "government_type_if_known": None,
         "capital_binding_type": "UNKNOWN", "capital_reference_id": None,
         "capital_lat": None, "capital_lon": None,
         "parent_scenario_polity_id": None,
         "subject_status": "UNEVALUATED", "source_confidence": "UNKNOWN",
         "notes": "TEST ONLY"}
        for s, p, n in [(sp_a, "pol_syn_a", "A"), (sp_b, "pol_syn_b", "B")]
    ]).to_csv(sdir / "scenario_polities.csv", index=False)
    src = make_source_id(scenario_id, "syn_source")
    pd.DataFrame([{
        "source_id": src, "scenario_id": scenario_id,
        "citation_key": "syn_source", "title": "Synthetic source",
        "author_or_institution": "tests", "source_type": "CURATED_DATASET",
        "publication_year": 2026, "source_date_range": None, "url": None,
        "local_file": None, "licence_or_usage_note": "TEST ONLY",
        "retrieved_date": None, "geographic_scope": "synthetic",
        "authority_scope": "synthetic", "notes": None,
    }]).to_csv(sdir / "sources.csv", index=False)
    # One OCEAN-hex island component controlled by A, one hex UNRESOLVED.
    pd.DataFrame([
        {"scenario_id": scenario_id,
         "territorial_target_type": "ISLAND_COMPONENT",
         "territorial_target_id": "isl_c_syn000000001",
         "controller_scenario_polity_id": sp_a,
         "control_status": "CONTROLLED", "source_confidence": "HIGH",
         "source_id": src, "notes": "TEST ONLY"},
        {"scenario_id": scenario_id,
         "territorial_target_type": "TERRESTRIAL_HEX",
         "territorial_target_id": "h6000_q+000001_r+000001",
         "controller_scenario_polity_id": None,
         "control_status": "UNRESOLVED", "source_confidence": "UNKNOWN",
         "source_id": None, "notes": "TEST ONLY unresolved"},
    ]).to_csv(sdir / "territorial_control.csv", index=False)
    # BOTH polities claim the SAME component (many-to-many).
    pd.DataFrame([
        {"scenario_id": scenario_id,
         "territorial_target_type": "ISLAND_COMPONENT",
         "territorial_target_id": "isl_c_syn000000001",
         "claimant_scenario_polity_id": s, "claim_type": "SOVEREIGN_CLAIM",
         "source_confidence": "LOW", "source_id": src, "notes": "TEST ONLY"}
        for s in (sp_a, sp_b)
    ]).to_csv(sdir / "territorial_claims.csv", index=False)
    pd.DataFrame([{
        "evidence_id": make_evidence_id(scenario_id, src, "SYNTHETIC",
                                        "ISLAND_COMPONENT",
                                        "isl_c_syn000000001"),
        "scenario_id": scenario_id, "source_id": src,
        "evidence_type": "SYNTHETIC",
        "target_type": "ISLAND_COMPONENT",
        "target_id": "isl_c_syn000000001", "confidence": "LOW",
        "interpretation_notes": "TEST ONLY",
        "source_locator": "UNKNOWN", "fact_summary": "TEST ONLY",
        "interpretation_level": "DIRECT", "notes": "TEST ONLY",
    }]).to_csv(sdir / "evidence.csv", index=False)
    # A and B in personal union (symmetric) — TEST ONLY.
    pd.DataFrame([{
        "relationship_id": make_relationship_id(
            scenario_id, sp_a, sp_b, "PERSONAL_UNION"),
        "scenario_id": scenario_id,
        "from_scenario_polity_id": min(sp_a, sp_b),
        "to_scenario_polity_id": max(sp_a, sp_b),
        "relationship_type": "PERSONAL_UNION",
        "directionality": "SYMMETRIC",
        "constitutional_or_administrative": "DYNASTIC",
        "source_confidence": "LOW", "source_id": src,
        "evidence_locator": "UNKNOWN", "notes": "TEST ONLY",
    }]).to_csv(sdir / "scenario_polity_relationships.csv", index=False)
    pd.DataFrame([{
        "scenario_id": scenario_id, "candidate_name": "Synthetic A",
        "canonical_candidate_id": "cand_syn_a", "region": "SYNTHETIC",
        "historical_entity_type": "STATE", "inclusion_status": "INCLUDED",
        "included_polity_id": "pol_syn_a", "reason": "TEST ONLY",
        "source_id": src, "source_confidence": "LOW",
        "six_km_representation_risk": "UNKNOWN",
        "recommended_future_representation": "DECIDE_LATER",
        "notes": "TEST ONLY",
    }]).to_csv(sdir / "scenario_polity_inclusion_audit.csv", index=False)
    pd.DataFrame([{
        "scenario_id": scenario_id, "coverage_unit_id": "syn_unit_a",
        "coverage_unit_type": "REGION",
        "control_coverage_status": "UNASSESSED",
        "claim_coverage_status": "UNASSESSED",
        "island_component_coverage_status": "UNASSESSED",
        "historical_overlay_coverage_status": "UNASSESSED",
        "source_evidence_status": "UNASSESSED", "notes": "TEST ONLY",
    }]).to_csv(sdir / "political_coverage.csv", index=False)
    return scenario_id


# --------------------------------------------------------------------------
# Registry + loader
# --------------------------------------------------------------------------
def test_real_registry_has_exactly_the_1756_scenario():
    reg = load_scenario_registry(DATA)
    assert list(reg["scenario_id"]) == [SC]
    row = reg.iloc[0]
    assert row["snapshot_date"] == "1756-08-01"
    assert row["display_name_ja"] == "七年戦争前夜"
    assert row["historicity"] == "HISTORICAL"
    assert row["data_status"] == "FOUNDATION_ONLY"
    assert row["political_geography_complete"] in (False, "False")


def test_real_loader_returns_full_snapshot():
    s = load_scenario(DATA, SC)
    assert s.scenario_id == SC
    assert len(s.polities) >= 1
    assert len(s.scenario_polities) >= 1
    assert len(s.territorial_control) >= 1
    assert len(s.sources) >= 1
    assert len(s.evidence) >= 1
    assert s.metadata["gameplay_authoritative"] in (True, "True")


def test_unknown_scenario_id_is_explicit_error():
    with pytest.raises(ScenarioNotFoundError):
        load_scenario(DATA, "definitely_not_registered")
    with pytest.raises(ScenarioNotFoundError):
        load_scenario(DATA, "")  # no silent default fallback


def test_synthetic_scenario_loader_roundtrip(tmp_path):
    sid = _write_synthetic(tmp_path)
    s = load_scenario(tmp_path, sid)
    assert len(s.scenario_polities) == 2
    assert len(s.territorial_claims) == 2


def test_missing_scenario_file_is_error(tmp_path):
    sid = _write_synthetic(tmp_path)
    (tmp_path / "scenarios" / sid / "evidence.csv").unlink()
    with pytest.raises(FileNotFoundError):
        load_scenario(tmp_path, sid)


# --------------------------------------------------------------------------
# Concept separation
# --------------------------------------------------------------------------
def test_polity_and_scenario_polity_are_separate():
    s = load_scenario(DATA, SC)
    assert "polity_id" in s.polities.columns
    assert "scenario_polity_id" in s.scenario_polities.columns
    # scenario polity REFERENCES the polity concept, never replaces it
    assert set(s.scenario_polities["polity_id"]) <= set(
        s.polities["polity_id"])
    assert "scenario_id" not in s.polities.columns  # concept is timeless


def test_control_and_claims_are_separate_tables():
    s = load_scenario(DATA, SC)
    assert "controller_scenario_polity_id" in s.territorial_control.columns
    assert "claimant_scenario_polity_id" in s.territorial_claims.columns
    assert "claimant_scenario_polity_id" \
        not in s.territorial_control.columns
    assert "controller_scenario_polity_id" \
        not in s.territorial_claims.columns


def test_target_types_are_hex_or_component_never_overlay():
    s = load_scenario(DATA, SC)
    for df in (s.territorial_control, s.territorial_claims):
        assert df["territorial_target_type"].isin(
            ["TERRESTRIAL_HEX", "ISLAND_COMPONENT"]).all()
        assert not df["territorial_target_id"].str.startswith(
            "isl_u_").any()
        assert "overlay_unit_id" not in df.columns


def test_real_terrestrial_hex_control_row():
    s = load_scenario(DATA, SC)
    hexes = s.territorial_control[
        (s.territorial_control["territorial_target_type"]
         == "TERRESTRIAL_HEX")
        & (s.territorial_control["control_status"] == "CONTROLLED")]
    assert len(hexes) >= 1
    assert hexes["territorial_target_id"].str.startswith("h6000_").all()
    assert hexes["source_id"].notna().all()  # provenance mandatory


def test_real_island_component_control_row():
    s = load_scenario(DATA, SC)
    comp = s.territorial_control[
        s.territorial_control["territorial_target_type"]
        == "ISLAND_COMPONENT"]
    assert len(comp) >= 1
    assert comp["territorial_target_id"].str.startswith("isl_c_").all()
    assert comp["source_id"].notna().all()


def test_multiple_claims_on_same_target(tmp_path):
    sid = _write_synthetic(tmp_path)
    s = load_scenario(tmp_path, sid)
    per_target = s.territorial_claims.groupby(
        "territorial_target_id")["claimant_scenario_polity_id"].nunique()
    assert int(per_target.max()) == 2  # many-to-many proven


def test_unresolved_is_formal_state():
    s = load_scenario(DATA, SC)
    unres = s.territorial_control[
        s.territorial_control["control_status"] == "UNRESOLVED"]
    assert len(unres) >= 1
    assert unres["controller_scenario_polity_id"].isna().all()
    assert unres["notes"].notna().all()  # reason documented, not guessed


def test_provenance_links_resolve():
    s = load_scenario(DATA, SC)
    src_ids = set(s.sources["source_id"])
    assert s.territorial_control["source_id"].dropna().isin(src_ids).all()
    assert s.evidence["source_id"].isin(src_ids).all()
    controlled = s.territorial_control[
        s.territorial_control["control_status"] == "CONTROLLED"]
    assert controlled["source_id"].notna().all()


def test_no_reference_admin_auto_ownership():
    # Data layer: the scenario module must be fully decoupled from the
    # contemporary reference layer (AST scan: imports, identifiers and
    # non-docstring strings; docs may describe the ban, code may not
    # cross it).
    from mapgen.scenario_pipeline import scan_forbidden_reference_code

    hits = scan_forbidden_reference_code(Path("src/mapgen/scenario.py"))
    assert hits == []
    # Data: no controller/claimant is a reference admin id.
    s = load_scenario(DATA, SC)
    ids = pd.concat([
        s.territorial_control["controller_scenario_polity_id"].dropna(),
        s.territorial_claims["claimant_scenario_polity_id"].dropna()])
    assert not ids.str.startswith(("adm0_", "adm1_")).any()


def test_deterministic_ids_reproduce():
    s = load_scenario(DATA, SC)
    for t in s.scenario_polities.itertuples():
        assert make_scenario_polity_id(SC, t.polity_id) \
            == t.scenario_polity_id
    for t in s.sources.itertuples():
        assert make_source_id(SC, t.citation_key) == t.source_id
    for t in s.evidence.itertuples():
        assert make_evidence_id(SC, t.source_id, t.evidence_type,
                                t.target_type, t.target_id) \
            == t.evidence_id
    assert SCENARIO_SCHEMA_VERSION == "1.4.0"
    assert SCENARIO_ALGORITHM_VERSION == "1.0.2"  # unchanged since 009R


def test_schema_is_generic_not_1756_specific():
    s = load_scenario(DATA, SC)
    for df in (s.territorial_control, s.territorial_claims,
               s.scenario_polities, s.scenario_polity_relationships,
               s.scenario_polity_inclusion_audit):
        for col in df.columns:
            low = col.lower()
            assert "prussia" not in low and "france" not in low \
                and "tokugawa" not in low and "1756" not in low


# --------------------------------------------------------------------------
# MAPGEN-009: constitutional relationship model
# --------------------------------------------------------------------------
def _sp_by_name(s, name):
    m = s.scenario_polities[s.scenario_polities["display_name"] == name]
    assert len(m) == 1, name
    return m.iloc[0]["scenario_polity_id"]


def test_multi_relationship_polity():
    # Hanover is BOTH an imperial member and a personal-union participant.
    s = load_scenario(DATA, SC)
    han = _sp_by_name(s, "Electorate of Brunswick-Lüneburg (Hanover)")
    rel = s.scenario_polity_relationships
    mine = rel[(rel["from_scenario_polity_id"] == han)
               | (rel["to_scenario_polity_id"] == han)]
    assert set(mine["relationship_type"]) \
        == {"PERSONAL_UNION", "IMPERIAL_MEMBER_OF"}


def test_personal_union_is_not_ownership_merge():
    s = load_scenario(DATA, SC)
    gb = _sp_by_name(s, "Kingdom of Great Britain")
    han = _sp_by_name(s, "Electorate of Brunswick-Lüneburg (Hanover)")
    assert gb != han  # two distinct scenario polities
    ctrl = s.territorial_control
    # MAPGEN-021 gave Great Britain territory from its OWN statutes (the
    # Acts of Union and two 1756 acts), which is not a union inheritance.
    # What the personal union must still never do is move land between the
    # two crowns, so Hanover holds nothing and no hex is shared.
    assert not ctrl["controller_scenario_polity_id"].eq(han).any()
    gb_hexes = set(ctrl.loc[ctrl["controller_scenario_polity_id"] == gb,
                            "territorial_target_id"])
    han_hexes = set(ctrl.loc[ctrl["controller_scenario_polity_id"] == han,
                             "territorial_target_id"])
    assert not gb_hexes & han_hexes


def test_empire_membership_is_not_ownership():
    s = load_scenario(DATA, SC)
    hre = _sp_by_name(s, "Holy Roman Empire")
    sp = s.scenario_polities
    row = sp[sp["scenario_polity_id"] == hre].iloc[0]
    assert row["territorial_authority_role"] == "STRUCTURAL_CONTAINER"
    rel = s.scenario_polity_relationships
    members = rel[(rel["relationship_type"] == "IMPERIAL_MEMBER_OF")
                  & (rel["to_scenario_polity_id"] == hre)]
    assert len(members) >= 15
    ctrl = s.territorial_control
    assert not (ctrl["controller_scenario_polity_id"] == hre).any()


def test_composite_monarchy_structure():
    s = load_scenario(DATA, SC)
    hab = _sp_by_name(s, "Habsburg Monarchy")
    rel = s.scenario_polity_relationships
    members = rel[(rel["relationship_type"] == "COMPOSITE_MEMBER_OF")
                  & (rel["to_scenario_polity_id"] == hab)]
    assert len(members) >= 4
    # Hungary is a Habsburg constituent but NOT an imperial member.
    hun = _sp_by_name(s, "Kingdom of Hungary")
    assert hun in set(members["from_scenario_polity_id"])
    hre = _sp_by_name(s, "Holy Roman Empire")
    imp = rel[(rel["relationship_type"] == "IMPERIAL_MEMBER_OF")
              & (rel["to_scenario_polity_id"] == hre)]
    assert hun not in set(imp["from_scenario_polity_id"])


def test_symmetric_relationship_id_is_order_invariant():
    a = make_relationship_id(SC, "sp_aaa", "sp_bbb", "PERSONAL_UNION")
    b = make_relationship_id(SC, "sp_bbb", "sp_aaa", "PERSONAL_UNION")
    assert a == b
    # Directed types keep direction.
    c = make_relationship_id(SC, "sp_aaa", "sp_bbb", "SUBJECT_OF")
    d = make_relationship_id(SC, "sp_bbb", "sp_aaa", "SUBJECT_OF")
    assert c != d


def test_relationship_provenance_resolves():
    s = load_scenario(DATA, SC)
    rel = s.scenario_polity_relationships
    assert rel["source_id"].notna().all()
    assert rel["source_id"].isin(set(s.sources["source_id"])).all()
    assert rel["evidence_locator"].notna().all()
    assert rel["relationship_id"].is_unique


def test_pinpoint_evidence_locator_columns():
    s = load_scenario(DATA, SC)
    ev = s.evidence
    for col in ("source_locator", "fact_summary", "interpretation_level"):
        assert col in ev.columns
        assert ev[col].notna().all()
    # UNKNOWN locators must carry a reason; no fabricated pages.
    unk = ev[ev["source_locator"] == "UNKNOWN"]
    assert unk["notes"].notna().all()
    assert ev["interpretation_level"].isin(
        ["DIRECT", "DERIVED", "RECONSTRUCTED", "UNCERTAIN"]).all()


def test_inclusion_audit_covers_all_europe_polities():
    s = load_scenario(DATA, SC)
    tokugawa = make_scenario_polity_id(SC, "pol_tokugawa_shogunate")
    europe = s.scenario_polities[
        s.scenario_polities["scenario_polity_id"] != tokugawa]
    audit = s.scenario_polity_inclusion_audit
    audited = set(audit["included_polity_id"].dropna())
    # MAPGEN-014: a superseded model artifact keeps its scenario row for
    # audit history but is no longer named by an active audit row — its
    # candidate row records the replacements instead.
    superseded = set(s.scenario_polities.loc[
        s.scenario_polities["existence_status"]
        == "MODEL_ARTIFACT_SUPERSEDED", "polity_id"])
    assert set(europe["polity_id"]) - superseded <= audited
    for p in superseded:
        assert audit["superseded_by_candidate_ids"].fillna("").str.len().gt(
            0).any()
    # And the audit also tracks evaluated-but-not-included candidates.
    assert (audit["included_polity_id"].isna()).sum() >= 5


def test_subhex_required_is_accepted_state_with_basis():
    # MAPGEN-009R: SUBHEX_REQUIRED is a GEOMETRY finding — it remains an
    # accepted audit state but ONLY with an explicit representability
    # basis (never a political-size label).
    s = load_scenario(DATA, SC)
    audit = s.scenario_polity_inclusion_audit
    sub = audit[(audit["six_km_representation_risk"] == "SUBHEX_REQUIRED")
                | (audit["inclusion_status"] == "SUBHEX_REQUIRED")]
    assert len(sub) >= 1  # imperial knights' estates class
    assert sub["representability_basis"].notna().all()
    assert not sub["representability_basis"].str.startswith(
        "UNKNOWN").any()


def test_unknown_representation_risk_is_explicit():
    s = load_scenario(DATA, SC)
    audit = s.scenario_polity_inclusion_audit
    assert audit["six_km_representation_risk"].notna().all()
    assert (audit["six_km_representation_risk"] == "UNKNOWN").sum() >= 1


def test_no_modern_admin_generation_for_catalogue():
    from mapgen.scenario_pipeline import scan_forbidden_reference_code

    assert scan_forbidden_reference_code(
        Path("src/mapgen/scenario.py")) == []
    s = load_scenario(DATA, SC)
    # No ISO columns anywhere; no Natural Earth source registered.
    for df in (s.polities, s.scenario_polities,
               s.scenario_polity_relationships,
               s.scenario_polity_inclusion_audit):
        assert not [c for c in df.columns if "iso" in c.lower()]
    assert not s.sources["title"].str.contains("Natural Earth",
                                               case=False).any()


CONTROL_BASELINE = Path(
    "output/scenario_foundation_20260811/chatgpt_review")


def assert_mapgen008_rows_semantically_intact():
    """MAPGEN-013 promotes 1,611 rows into this file, so byte identity is
    gone by design. What must survive is the MEANING of the three
    MAPGEN-008 rows: same targets, same controllers, same statuses, same
    confidence. Claims are still byte-identical — control never generates
    claims."""
    import hashlib

    base = pd.read_csv(CONTROL_BASELINE / "territorial_control.csv",
                       keep_default_na=False, na_values=[""])
    cur = pd.read_csv(Path("data/scenarios") / SC
                      / "territorial_control.csv",
                      keep_default_na=False, na_values=[""])
    cols = ["scenario_id", "territorial_target_type",
            "territorial_target_id", "controller_scenario_polity_id",
            "control_status", "source_confidence", "source_id"]
    assert len(base) == 3
    kept = cur[cur["territorial_target_id"].isin(
        base["territorial_target_id"])]
    assert len(kept) == 3
    pd.testing.assert_frame_equal(
        base[cols].sort_values("territorial_target_id")
        .reset_index(drop=True),
        kept[cols].sort_values("territorial_target_id")
        .reset_index(drop=True))

    def sha(p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()

    assert sha(Path("data/scenarios") / SC / "territorial_claims.csv") \
        == sha(CONTROL_BASELINE / "territorial_claims.csv")


def test_mapgen008_control_rows_semantically_immutable():
    assert_mapgen008_rows_semantically_intact()


def test_mapgen013_promotion_only_ever_added_rows():
    """Promotion may add authority; it may never delete or rewrite a row
    that was already reviewed."""
    base = pd.read_csv(CONTROL_BASELINE / "territorial_control.csv")
    cur = pd.read_csv(Path("data/scenarios") / SC
                      / "territorial_control.csv")
    assert len(cur) >= len(base)
    assert set(base["territorial_target_id"]) <= set(
        cur["territorial_target_id"])


def test_playability_not_decided():
    """No playability decision has been taken for any polity that is
    still an active actor. A superseded model artifact is explicitly
    NON_PLAYABLE, which is a correction, not a design decision."""
    s = load_scenario(DATA, SC)
    sp = s.scenario_polities
    active = sp[sp["existence_status"] != "MODEL_ARTIFACT_SUPERSEDED"]
    assert (active["playability_status"] == "UNDECIDED").all()
    superseded = sp[sp["existence_status"] == "MODEL_ARTIFACT_SUPERSEDED"]
    assert (superseded["playability_status"] == "NON_PLAYABLE").all()


# --------------------------------------------------------------------------
# MAPGEN-009R: granularity + representability hardening
# --------------------------------------------------------------------------
REVIEW = Path("data/scenarios") / SC / "review"


def test_hex_area_is_machine_computed():
    from mapgen.hex_grid import HexGrid
    from mapgen.scenario import (HEX_PLANE_AREA_KM2,
                                 hex_ground_area_km2_at_lat)

    assert HEX_PLANE_AREA_KM2 == round(
        HexGrid(flat_to_flat=6000.0).area / 1e6, 6)
    # ground area shrinks with latitude (Mercator grid contract)
    assert hex_ground_area_km2_at_lat(0.0) == HEX_PLANE_AREA_KM2
    assert hex_ground_area_km2_at_lat(60.0) < HEX_PLANE_AREA_KM2 / 3.5


def test_microstates_not_subhex_by_label():
    s = load_scenario(DATA, SC)
    audit = s.scenario_polity_inclusion_audit
    micro = audit[audit["canonical_candidate_id"].isin(
        ["cand_san_marino", "cand_monaco", "cand_andorra",
         "cand_liechtenstein"])]
    assert len(micro) == 4
    assert not (micro["six_km_representation_risk"]
                == "SUBHEX_REQUIRED").any()
    # 3 re-audited to INCLUDED, Monaco honestly UNRESOLVED
    st = dict(zip(micro["canonical_candidate_id"],
                  micro["inclusion_status"]))
    assert st["cand_san_marino"] == "INCLUDED"
    assert st["cand_andorra"] == "INCLUDED"
    assert st["cand_liechtenstein"] == "INCLUDED"
    assert st["cand_monaco"] == "UNRESOLVED"


def test_representability_corrections_file():
    df = pd.read_csv(REVIEW / "six_km_representability_corrections.csv")
    assert len(df) == 4
    assert (df["before_risk"] == "SUBHEX_REQUIRED").all()
    assert not (df["after_risk"] == "SUBHEX_REQUIRED").any()
    from mapgen.scenario import HEX_PLANE_AREA_KM2

    assert (df["hex_plane_area_km2"] == HEX_PLANE_AREA_KM2).all()
    assert "SANITY_CHECK_ONLY" in " ".join(df.columns)


def test_hre_majors_individually_audited():
    s = load_scenario(DATA, SC)
    audit = s.scenario_polity_inclusion_audit
    for cand in ("cand_muenster", "cand_wuerzburg", "cand_bamberg",
                 "cand_salzburg", "cand_hesse_darmstadt",
                 "cand_baden_durlach", "cand_baden_baden",
                 "cand_hamburg", "cand_nuremberg"):
        row = audit[audit["canonical_candidate_id"] == cand]
        assert len(row) == 1, cand
        assert row.iloc[0]["inclusion_status"] == "INCLUDED"
        assert isinstance(row.iloc[0]["included_polity_id"], str)
    hre = pd.read_csv(REVIEW / "hre_individual_polity_audit.csv")
    assert len(hre) >= 15
    for col in ("a_territorial_actor_1756", "b_visible_at_6km",
                "c_independent_7yw_significance"):
        assert col in hre.columns


def test_aggregation_classes_never_own_territory():
    s = load_scenario(DATA, SC)
    audit = s.scenario_polity_inclusion_audit
    agg = audit[audit["inclusion_status"] == "AGGREGATION_CANDIDATE"]
    assert len(agg) >= 8
    assert agg["included_polity_id"].isna().all()
    # No controller can therefore ever be an aggregation class.
    ctrl = s.territorial_control["controller_scenario_polity_id"].dropna()
    assert ctrl.isin(set(
        s.scenario_polities["scenario_polity_id"])).all()


def test_corsica_two_sided_model():
    s = load_scenario(DATA, SC)
    names = set(s.polities["polity_id"])
    assert "pol_corsican_republic" in names
    assert "pol_genoa" in names  # de-jure claimant kept distinct
    c = pd.read_csv(REVIEW / "contested_polity_audit.csv")
    row = c[c["case"] == "corsica_1756"].iloc[0]
    assert "genoa" in row["de_jure_side"].lower()
    assert "corsican" in row["de_facto_side"].lower()
    assert "claim" in row["modeling_contract"].lower()


def test_no_royal_prussia_conflation():
    s = load_scenario(DATA, SC)
    names = pd.concat([s.scenario_polities["display_name"],
                       s.polities["canonical_name"]])
    assert not names.str.contains("Royal Prussia", case=False).any()
    pk = s.polities[s.polities["polity_id"]
                    == "pol_prussia_kingdom_proper"].iloc[0]
    assert "Ducal" in pk["canonical_name"]
    assert "Commonwealth" in pk["notes"]
    terms = pd.read_csv(REVIEW / "prussia_terminology_audit.csv")
    assert terms["term"].str.contains("Royal Prussia").any()
    assert terms["term"].str.contains("King in Prussia").any()


def test_composite_roots_binding_contract():
    s = load_scenario(DATA, SC)
    sp = s.scenario_polities
    roots = sp[sp["territorial_authority_role"]
               == "COMPOSITE_TERRITORIAL_ACTOR"]
    assert set(roots["polity_id"]) == {"pol_habsburg_monarchy",
                                       "pol_prussia_monarchy"}
    ctrl = s.territorial_control["controller_scenario_polity_id"].dropna()
    assert not ctrl.isin(set(roots["scenario_polity_id"])).any()
    # Structural containers likewise own nothing.
    struct = sp[sp["territorial_authority_role"]
                == "STRUCTURAL_CONTAINER"]
    assert not ctrl.isin(set(struct["scenario_polity_id"])).any()


def test_historical_titles_present_but_never_fabricated():
    s = load_scenario(DATA, SC)
    sp = s.scenario_polities
    assert "historical_title_at_snapshot" in sp.columns
    t = sp.set_index("polity_id")["historical_title_at_snapshot"]
    assert "King in Prussia" in t["pol_prussia_monarchy"]
    # Unverified titles stay null instead of being invented.
    assert t.isna().sum() > len(sp) / 2


# --------------------------------------------------------------------------
# MAPGEN-009R2: superseded audit semantics
# --------------------------------------------------------------------------
def test_superseded_parent_keeps_history_but_not_active():
    s = load_scenario(DATA, SC)
    audit = s.scenario_polity_inclusion_audit
    assert audit["audit_record_status"].isin(
        ["ACTIVE", "SUPERSEDED"]).all()
    parent = audit[audit["canonical_candidate_id"]
                   == "cand_schleswig_holstein_complex"].iloc[0]
    assert parent["audit_record_status"] == "SUPERSEDED"
    assert parent["superseded_by_candidate_ids"] == \
        "cand_schleswig_holstein_royal|cand_holstein_gottorp"
    # Targets exist and are ACTIVE.
    by_id = audit.set_index("canonical_candidate_id")
    for child in parent["superseded_by_candidate_ids"].split("|"):
        assert by_id.loc[child, "audit_record_status"] == "ACTIVE"
    # ACTIVE rows never carry superseded_by.
    act = audit[audit["audit_record_status"] == "ACTIVE"]
    assert act["superseded_by_candidate_ids"].isna().all()


def test_active_counts_exclude_superseded_no_double_unresolved():
    s = load_scenario(DATA, SC)
    audit = s.scenario_polity_inclusion_audit
    act = audit[audit["audit_record_status"] == "ACTIVE"]
    sup = audit[audit["audit_record_status"] == "SUPERSEDED"]
    assert len(act) + len(sup) == len(audit)
    # Schleswig-Holstein (MAPGEN-009R) and the Schwarzburg model artifact
    # (MAPGEN-014) — both replaced by refined children, neither deleted.
    assert len(sup) == 2
    unres = act[act["inclusion_status"] == "UNRESOLVED"]
    # Schleswig contributes via its two refined children ONLY —
    # the superseded parent never double-counts.
    sh_like = unres["candidate_name"].str.contains(
        "Schleswig|Gottorp", case=False)
    assert int(sh_like.sum()) == 2
    assert "cand_schleswig_holstein_complex" not in set(
        unres["canonical_candidate_id"])


def test_superseded_rows_cannot_register_or_control():
    s = load_scenario(DATA, SC)
    audit = s.scenario_polity_inclusion_audit
    sup = audit[audit["audit_record_status"] == "SUPERSEDED"]
    assert sup["included_polity_id"].isna().all()
    controllers = s.territorial_control[
        "controller_scenario_polity_id"].dropna()
    assert controllers.isin(set(
        s.scenario_polities["scenario_polity_id"])).all()


def test_009r_historical_content_unchanged_by_r2():
    # MAPGEN-013 registered exactly two further imperial estates that the
    # 1756 sheet labels itself (Saxe-Weimar, Schwarzburg); everything the
    # 009R2 review approved is otherwise untouched.
    s = load_scenario(DATA, SC)
    # MAPGEN-013 added Saxe-Weimar and Schwarzburg; MAPGEN-014 superseded
    # the Schwarzburg artifact and registered the two principalities that
    # actually existed. Nothing the 009R2 review approved was touched.
    added = {"pol_saxe_weimar", "pol_schwarzburg",
             "pol_schwarzburg_rudolstadt", "pol_schwarzburg_sondershausen",
             "pol_saxe_eisenach"}
    assert added <= set(s.polities["polity_id"])
    assert len(s.polities) == 66 + len(added)
    assert len(s.scenario_polities) == 66 + len(added)
    # the superseded artifact lost its live imperial relationship;
    # MAPGEN-015 added Saxe-Eisenach's imperial membership AND the
    # Weimar/Eisenach personal union.
    assert len(s.scenario_polity_relationships) == 46 + len(added) + 1 - 1
    rc = s.scenario_polity_relationships[
        "relationship_type"].value_counts().to_dict()
    assert rc["IMPERIAL_MEMBER_OF"] == 29 + len(added) - 1
    assert "pol_corsican_republic" in set(s.polities["polity_id"])
    active = s.scenario_polities[
        s.scenario_polities["existence_status"]
        != "MODEL_ARTIFACT_SUPERSEDED"]
    assert (active["playability_status"] == "UNDECIDED").all()


def test_mapgen008_controls_still_untouched_after_009r():
    assert_mapgen008_rows_semantically_intact()
