"""MAPGEN-022 — Sicily and Sardinia, and the traps they set.

The islands were swapped between the same two powers in 1720 and 1738, so
the load-bearing test here is that neither island's owner can be inferred
from a dynasty's name.
"""
from pathlib import Path

import pandas as pd
import pytest

H = Path("data/historical")
SD = Path("data/scenarios/seven_years_war_1756_08_01")
SIC_SP, SAR_SP, NAP_SP = "sp_14ee92dede27", "sp_5f0f4d8d4788", "sp_def69cc80f28"
SUBJ_SIC = "hsub_sicily_main_island"
SUBJ_SAR = "hsub_sardinia_main_island"


@pytest.fixture(scope="module")
def ev():
    return pd.read_csv(H / "mediterranean_historical_evidence.csv",
                       keep_default_na=False, na_values=[])


@pytest.fixture(scope="module")
def ident():
    return pd.read_csv(H / "mediterranean_landmass_identity.csv",
                       keep_default_na=False, na_values=[]).fillna("")


@pytest.fixture(scope="module")
def mix():
    return pd.read_csv(H / "mediterranean_hex_membership_audit.csv",
                       keep_default_na=False, na_values=[])


@pytest.fixture(scope="module")
def canon():
    return pd.read_csv(SD / "territorial_control.csv",
                       keep_default_na=False, na_values=[""])


# ---------------------------------------------------------------------------
# authority, not names
# ---------------------------------------------------------------------------
def test_each_island_has_its_own_sovereignty_basis(ev):
    """Neither island may be owned because a dynasty is named after it."""
    assert (ev["name_inference_used"] == "NO").all()
    for pol, year in (("pol_sicily", "1738"), ("pol_sardinia", "1720")):
        sov = ev[(ev.polity == pol) & (ev.kind == "SOVEREIGNTY_BASIS")]
        assert len(sov) == 1, pol
        assert year in sov.iloc[0]["exact_locator"]
        assert sov.iloc[0]["in_force_at_snapshot"] == "YES"


def test_each_island_has_contemporary_in_island_evidence(ev):
    for pol in ("pol_sicily", "pol_sardinia"):
        now = ev[(ev.polity == pol)
                 & ev.kind.str.startswith("CONTEMPORARY")]
        assert len(now) >= 1, pol
        assert (now["in_force_at_snapshot"] == "YES").all()
        assert (now["exact_locator"].str.len() > 40).all()


def test_sardinia_evidence_records_the_1720_institutional_start(ev):
    """The Savoyard secretariat opens in the year of the exchange."""
    r = ev[ev.evidence_id == "med_1756_sardinia_institutions"].iloc[0]
    assert "1720-1848" in r["exact_locator"]
    assert "Segreteria di Stato e di Guerra" in r["exact_locator"]


def test_sicily_evidence_records_its_own_parliament_organ(ev):
    r = ev[ev.evidence_id == "med_1756_sicily_institutions"].iloc[0]
    assert "Deputazione del regno" in r["exact_locator"]
    assert "1547-1819" in r["exact_locator"]


def test_post_snapshot_states_are_recorded_and_not_in_force(ev):
    cut = ev[ev.evidence_role == "TEMPORAL_BOUNDARY"]
    assert len(cut) >= 3
    assert (cut["in_force_at_snapshot"] == "NO").all()
    assert (cut["effective_date"] > "1756-08-01").all()
    ids = set(cut["evidence_id"])
    assert "med_1816_two_sicilies_cutoff" in ids
    assert "med_1847_fusione_perfetta_cutoff" in ids


def test_no_evidence_row_is_boundary_position(ev):
    assert set(ev["evidence_role"]) <= {"POLITICAL_CONTROL",
                                        "ADMINISTRATIVE_SCOPE",
                                        "TEMPORAL_BOUNDARY"}


# ---------------------------------------------------------------------------
# separation
# ---------------------------------------------------------------------------
def test_sicily_naples_share_a_king_but_no_territory(canon):
    sic = set(canon.loc[canon["controller_scenario_polity_id"] == SIC_SP,
                        "territorial_target_id"])
    nap = set(canon.loc[canon["controller_scenario_polity_id"] == NAP_SP,
                        "territorial_target_id"])
    assert sic
    assert not nap, "Naples must hold nothing: it was not produced here"
    assert not sic & nap


def test_sardinia_mainland_is_not_inherited(canon, mix):
    """One component of the actor's scope was authorised, not the actor.

    MAPGEN-023 corrected the wording this test used to assert. Saying the
    kingdom legally IS the island redefined the actor to justify the
    scope; the scope stands on its own. What must hold is that the
    mainland is recorded as unevaluated, and that Sardinia's canonical
    rows still come only from the island component.
    """
    mp = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    basis = mp.loc[mp.historical_subject_id == SUBJ_SAR,
                   "mapping_basis"].iloc[0]
    assert "Savoy-Piedmont" in basis
    assert "NOT_PRODUCED" in basis
    assert "legally IS the island" not in basis
    sar = canon[canon["controller_scenario_polity_id"] == SAR_SP]
    assert len(sar) == int((mix["winner"] == "sardinia").sum())


def test_corsica_is_excluded_and_its_contested_audit_survives(canon):
    e = pd.read_csv(H / "mediterranean_exclusion_audit.csv",
                    keep_default_na=False, na_values=[]).fillna("")
    cor = e[e["named_identification"].str.contains("Corsica", na=False)]
    assert len(cor) == 1
    assert cor.iloc[0]["exclusion_reason"] == (
        "SEPARATE_CONTESTED_POLITY_NOT_SARDINIA")
    assert "1768" in cor.iloc[0]["note"]
    sp = pd.read_csv(SD / "scenario_polities.csv", keep_default_na=False,
                     na_values=[""])
    cor_sp = sp.loc[sp.polity_id == "pol_corsican_republic",
                    "scenario_polity_id"]
    assert len(cor_sp) == 1
    assert int((canon["controller_scenario_polity_id"]
                == cor_sp.iloc[0]).sum()) == 0


def test_malta_is_excluded_from_sicily():
    e = pd.read_csv(H / "mediterranean_exclusion_audit.csv",
                    keep_default_na=False, na_values=[]).fillna("")
    mal = e[e["named_identification"].str.contains("Malta", na=False)]
    assert len(mal) == 1
    assert mal.iloc[0]["exclusion_reason"] == "HOSPITALLER_MALTA_NOT_SICILY_1756"


def test_no_modern_italian_administrative_source(ev):
    assert (ev["modern_administrative_geography_used"] == "NO").all()
    snapf = pd.read_csv(H / "historical_snapshot_features_1756_08_01.csv")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    allowed = set(reg.loc[reg["citation_key"].isin(
        ["osm_land_polygons_split_3857",
         "guida_generale_archivi_stato_palermo",
         "sias_archivio_di_stato_cagliari",
         "european_peace_settlements_1720_1738",
         # MAPGEN-023 hardening: archival provenance for the same titles
         "wenck_codex_juris_gentium_recentissimi_i",
         "asto_corte_paesi_sardegna"]), "global_source_id"])
    used = set()
    for v in snapf[snapf.historical_subject_id.isin(
            [SUBJ_SIC, SUBJ_SAR])]["bundle_source_ids"]:
        used |= {x for x in str(v).split("|") if x}
    assert used and used <= allowed


# ---------------------------------------------------------------------------
# geometry and identity
# ---------------------------------------------------------------------------
def test_physical_geometry_alone_cannot_create_ownership():
    a = pd.read_csv(H / "historical_evidence_assertions.csv")
    geo = a[(a.historical_subject_id.isin([SUBJ_SIC, SUBJ_SAR]))
            & (a.assertion_type == "GEOMETRIC_SUBSTRATE_ONLY")]
    assert len(geo) == 2
    assert (geo["geometry_authority"] == "YES").all()
    assert (geo["political_authority"] == "NO").all()
    pol = a[(a.historical_subject_id.isin([SUBJ_SIC, SUBJ_SAR]))
            & (a.assertion_type == "POLITICAL_CONTROL")]
    # two per island from MAPGEN-022, plus one archive-grade title each
    # from the MAPGEN-023 hardening
    assert len(pol) == 6
    assert (pol["geometry_authority"] == "NO").all()


def test_identity_is_by_anchor_not_by_size(ident):
    """Both targets rank below North Africa and the Italian mainland."""
    sic = ident[ident.stage_role == "MAIN_LANDMASS_SICILY"].iloc[0]
    sar = ident[ident.stage_role == "MAIN_LANDMASS_SARDINIA"].iloc[0]
    assert int(sic["rank_by_area"]) > 1
    assert int(sar["rank_by_area"]) > 1
    assert len(sic["anchors_contained_sicily"].split(";")) == 3
    assert len(sar["anchors_contained_sardinia"].split(";")) == 3
    assert (ident["anchor_role"]
            == "IDENTITY_QA_ONLY_NOT_OWNERSHIP_SOURCE").all()


def test_component_areas_match_published_islands(ident):
    sic = ident[ident.stage_role == "MAIN_LANDMASS_SICILY"].iloc[0]
    sar = ident[ident.stage_role == "MAIN_LANDMASS_SARDINIA"].iloc[0]
    assert 24_000 < float(sic["ground_area_km2"]) < 27_000
    assert 22_500 < float(sar["ground_area_km2"]) < 25_500


def test_area_semantics_are_measured_not_asserted():
    a = pd.read_csv(H / "mediterranean_area_semantics.csv")
    assert len(a) == 2
    assert (a["n_interior_rings"] == 0).all()
    assert a["inland_water_treatment"].str.startswith("MEASURED").all()
    # the intertidal mechanism is named but explicitly not quantified
    assert a["intertidal_treatment"].str.contains("NOT measured").all()
    # and the Mercator factor is checked against theory
    for r in a.itertuples():
        assert abs(r.mercator_inflation_factor
                   - r.expected_inflation_1_over_cos2_lat) < 0.01


def test_geometry_is_exact_and_stored_once():
    g = pd.read_csv(H / "geometry_storage_audit.csv")
    assert len(g) >= 2
    assert (g["simplified"] == "NO").all()
    assert (g["duplicated_as_wkt_csv"] == "NO").all()
    assert (g["simplification_tolerance_m"] == 0).all()
    # the snapshot CSV must not carry geometry
    s = pd.read_csv(H / "historical_snapshot_features_1756_08_01.csv")
    assert "geometry" not in s.columns


# ---------------------------------------------------------------------------
# membership and promotion
# ---------------------------------------------------------------------------
def test_membership_is_whole_land_not_centroid(mix):
    assert (mix["hex_land_km2"] > 0).all()
    assert "centre_lon" not in mix.columns
    ctrl = mix[mix["control_status"] == "CONTROLLED"]
    assert (ctrl["unaudited_share"] <= 0.02).all()


def test_mixed_island_components_are_held_back(mix):
    held = mix[mix["basis"] == "MIXED_UNAUDITED_LAND_COMPONENT"]
    assert (held["control_status"] == "UNRESOLVED").all()
    assert (held["winner"] == "").all()


def test_the_two_islands_never_share_a_hex(mix):
    both = mix[(mix["sicily_km2"] > 0) & (mix["sardinia_km2"] > 0)]
    assert len(both) == 0


def test_sicily_promoted(canon):
    sic = canon[canon["controller_scenario_polity_id"] == SIC_SP]
    assert int((sic["control_status"] == "CONTROLLED").sum()) > 1000


def test_sardinia_promoted(canon):
    sar = canon[canon["controller_scenario_polity_id"] == SAR_SP]
    assert int((sar["control_status"] == "CONTROLLED").sum()) > 1000


def test_every_mediterranean_row_has_provenance(canon, mix):
    prov = pd.read_csv(SD / "territorial_control_provenance.csv",
                       keep_default_na=False, na_values=[""])
    t = set(mix["hex_id"])
    rows = canon[canon["territorial_target_id"].isin(t)]
    assert len(rows) == len(mix)
    p = prov[prov["territorial_target_id"].isin(t)]
    assert len(p) == len(mix)
    assert (p["scenario_source_id"].str.len() > 0).all()
    srcs = pd.read_csv(SD / "sources.csv", keep_default_na=False,
                       na_values=[""])
    assert set(p["scenario_source_id"]) <= set(srcs["source_id"])


def test_promotion_rerun_is_idempotent():
    from mapgen.scenario_promotion import promote_control
    canon = pd.read_csv(SD / "territorial_control.csv",
                        keep_default_na=False, na_values=[""])
    prov = pd.read_csv(SD / "territorial_control_provenance.csv",
                       keep_default_na=False, na_values=[""])
    log = pd.read_csv(SD / "scenario_control_promotion_log.csv",
                      keep_default_na=False, na_values=[""])
    empty = pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"])
    c2, _, _, rep = promote_control(
        canon, prov, log, empty, "seven_years_war_1756_08_01",
        "MAPGEN-022", "x", "none", "src_none", promoted_utc="2026-08-15")
    assert rep["inserted"] == 0
    assert len(c2) == len(canon)


def test_coverage_is_partial_never_complete():
    cov = pd.read_csv(SD / "political_coverage.csv", keep_default_na=False,
                      na_values=[""])
    rows = cov[cov["coverage_unit_id"].isin(
        ["region_sicily_main_island_1756",
         "region_sardinia_main_island_1756"])]
    assert len(rows) == 2
    assert (rows["control_coverage_status"] == "TERRITORY_PARTIAL").all()
    assert int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0


# ---------------------------------------------------------------------------
# the reporting contract
# ---------------------------------------------------------------------------
def test_completion_summary_matches_committed_output():
    """The reported figures must come from the artifact, not from memory.

    MAPGEN-021's verbal report quoted membership numbers that its own
    committed summary contradicted. This test makes the artifact the
    authority for the next stage too.
    """
    from mapgen.historical_mediterranean_pipeline import committed_baseline
    base = committed_baseline()
    assert base["canonical_rows_after"] == 29578
    assert base["gb_membership_rows"] == 20396
    assert base["gb_controlled"] == 20310
    assert base["ie_membership_rows"] == 7568
    assert base["ie_controlled"] == 7520
    canon = pd.read_csv(SD / "territorial_control.csv",
                        keep_default_na=False, na_values=[""])
    # Canonical before ANY island production, plus the two British Isles
    # membership counts the committed summary itself reports, must be the
    # MAPGEN-021 total. Stated this way it stays true as later island
    # stages land on top.
    from _production_baseline import strip_island_production
    pre_island = len(strip_island_production(canon))
    assert (pre_island + base["gb_membership_rows"]
            + base["ie_membership_rows"]) == base["canonical_rows_after"]


def test_british_isles_production_survives(canon):
    gb = int((canon["controller_scenario_polity_id"]
              == "sp_6b03622fc98a").sum())
    ie = int((canon["controller_scenario_polity_id"]
              == "sp_c8f0dcb42a96").sum())
    assert gb == 20310
    assert ie == 7520


def test_brandenburg_still_holds_nothing(canon):
    assert not canon["controller_scenario_polity_id"].str.contains(
        "brandenburg", case=False, na=False).any()
    assert (H / "brandenburg_boundary_segment_continuity.csv").exists()
