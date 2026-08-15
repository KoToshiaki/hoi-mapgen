"""MAPGEN-023 — an instrument decides the scope, not the map.

The load-bearing test in this file is the Comino one. Gozo and Comino are
both small islands in the same archipelago, both within sight of Malta.
One is produced and one is not, and the only thing that separates them is
whether a document from 1530 writes their name down.
"""
from pathlib import Path

import pandas as pd
import pytest

H = Path("data/historical")
SD = Path("data/scenarios/seven_years_war_1756_08_01")
DK_SP, OSJ_SP = "sp_44c79eb0f89c", "sp_20bf1d9af6ea"
SUBJ_ICE = "hsub_iceland_main_island"
SUBJ_MLT = "hsub_malta_main_island"
SUBJ_GOZ = "hsub_gozo_island"


@pytest.fixture(scope="module")
def ice_ev():
    return pd.read_csv(H / "iceland_historical_evidence.csv",
                       keep_default_na=False, na_values=[])


@pytest.fixture(scope="module")
def mlt_ev():
    return pd.read_csv(H / "malta_historical_evidence.csv",
                       keep_default_na=False, na_values=[])


@pytest.fixture(scope="module")
def mix():
    return pd.read_csv(H / "island_hex_membership_audit.csv",
                       keep_default_na=False, na_values=[])


@pytest.fixture(scope="module")
def canon():
    return pd.read_csv(SD / "territorial_control.csv",
                       keep_default_na=False, na_values=[""])


@pytest.fixture(scope="module")
def hard():
    return pd.read_csv(H / "mapgen022_source_hardening.csv",
                       keep_default_na=False, na_values=[])


# ---------------------------------------------------------------------------
# the rule everything else rests on
# ---------------------------------------------------------------------------
def test_comino_is_withheld_because_the_instrument_does_not_name_it(mlt_ev):
    """Gozo and Comino differ by one word in a document from 1530.

    Nothing about the geography separates them. If proximity could
    authorise territory, Comino would be produced.
    """
    grant = mlt_ev[mlt_ev.kind == "SOVEREIGNTY_BASIS"].iloc[0]
    assert "Gozo" in grant["exact_locator"]
    assert "Comino" not in grant["exact_locator"]
    ex = pd.read_csv(H / "malta_exclusion_audit.csv",
                     keep_default_na=False, na_values=[])
    com = ex[ex["named_identification"].str.contains("Comino", na=False)]
    assert len(com) >= 1
    assert (com["exclusion_reason"]
            == "NOT_NAMED_IN_THE_1530_PRIVILEGE").all()
    snapf = pd.read_csv(H / "historical_snapshot_features_1756_08_01.csv")
    assert SUBJ_GOZ in set(snapf["historical_subject_id"])
    assert not any("comino" in s for s in snapf["historical_subject_id"])


def test_surtsey_did_not_exist_at_the_snapshot():
    """Land created in 1963 cannot be owned in 1756."""
    ex = pd.read_csv(H / "iceland_exclusion_audit.csv",
                     keep_default_na=False, na_values=[])
    s = ex[ex["named_identification"].str.contains("Surtsey", na=False)]
    assert len(s) == 1
    assert (s.iloc[0]["exclusion_reason"]
            == "LAND_THAT_DID_NOT_EXIST_AT_THE_SNAPSHOT")
    assert "1963" in s.iloc[0]["note"]


def test_physical_geometry_alone_cannot_create_ownership():
    a = pd.read_csv(H / "historical_evidence_assertions.csv")
    three = [SUBJ_ICE, SUBJ_MLT, SUBJ_GOZ]
    geo = a[(a.historical_subject_id.isin(three))
            & (a.assertion_type == "GEOMETRIC_SUBSTRATE_ONLY")]
    assert len(geo) == 3
    assert (geo["geometry_authority"] == "YES").all()
    assert (geo["political_authority"] == "NO").all()
    pol = a[(a.historical_subject_id.isin(three))
            & (a.assertion_type == "POLITICAL_CONTROL")]
    assert len(pol) == 6
    assert (pol["political_authority"] == "YES").all()
    assert (pol["geometry_authority"] == "NO").all()


def test_a_bundle_without_political_evidence_is_rejected():
    """Negative fixture: strip the political link and the features fail."""
    import geopandas as gpd

    from mapgen.historical_binding import compile_authorised_snapshot_features
    feats = gpd.read_parquet(H / "historical_boundary_features.parquet")
    links = pd.read_csv(H / "historical_boundary_feature_evidence.csv")
    gutted = links[links["evidence_role"] != "POLITICAL_STATUS"]
    ok, rej = compile_authorised_snapshot_features(
        feats, gutted,
        pd.read_csv(H / "historical_evidence_assertions.csv"),
        pd.read_csv(H / "historical_source_registry.csv"),
        pd.read_csv(H / "historical_subject_scenario_mapping.csv"),
        "1756-08-01")
    authorised = set(ok["historical_subject_id"]) if len(ok) else set()
    for s in (SUBJ_ICE, SUBJ_MLT, SUBJ_GOZ):
        assert s not in authorised
    assert "POLITICAL_STATUS" in " ".join(rej["rejection_reasons"])


# ---------------------------------------------------------------------------
# the MAPGEN-022 repair
# ---------------------------------------------------------------------------
def test_sicily_and_sardinia_sources_are_hardened(hard):
    h = hard[hard.correction == "SOVEREIGNTY_SOURCE_HARDENED"]
    assert set(h["target"]) == {"pol_sicily", "pol_sardinia"}
    a = pd.read_csv(H / "historical_evidence_assertions.csv")
    w = a[a["exact_locator"].str.contains("Wenck", na=False)]
    t = a[a["exact_locator"].str.contains("Archivio di Stato di Torino",
                                          na=False)]
    assert len(w) == 1 and "Art. III" in w.iloc[0]["exact_locator"]
    assert len(t) == 1 and "Mazzo 1, n. 17" in t.iloc[0]["exact_locator"]


def test_the_repair_changed_no_control_rows(hard, canon):
    """A provenance repair that moves a boundary is not a repair."""
    assert (hard["control_rows_changed"].astype(int) == 0).all()
    from _production_baseline import hex_control
    from mapgen.historical_batch_islands_pipeline import committed_baseline
    base = committed_baseline()
    # hex totals, not fragment totals: MAPGEN-025 added LAND_FRAGMENT rows
    # for the same polities, which are additional territory of another kind
    hx = hex_control(canon)
    for sp, key in (("sp_14ee92dede27", "sicily_controlled"),
                    ("sp_5f0f4d8d4788", "sardinia_controlled")):
        assert int((hx["controller_scenario_polity_id"]
                    == sp).sum()) == base[key]


def test_the_archive_grade_assertion_is_the_required_evidence():
    links = pd.read_csv(H / "historical_boundary_feature_evidence.csv",
                        keep_default_na=False, na_values=[])
    a = pd.read_csv(H / "historical_evidence_assertions.csv")
    hard_ids = set(a.loc[a["exact_locator"].str.contains(
        "Wenck|Archivio di Stato di Torino", na=False, regex=True),
        "historical_evidence_id"])
    req = links[(links["evidence_role"] == "POLITICAL_STATUS")
                & (links["is_required"] == "YES")
                & (links["historical_evidence_id"].isin(hard_ids))]
    assert len(req) == 2


def test_pares_lead_is_recorded_as_unreachable_not_cited(hard):
    """A locator that could not be opened must not be quoted anyway."""
    p = hard[hard.correction == "PREFERRED_LEAD_NOT_RETRIEVED"]
    assert len(p) == 1
    assert p.iloc[0]["after"].startswith("ATTEMPTED_AND_UNREACHABLE")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    assert not reg["citation_key"].str.contains("pares", case=False).any()
    a = pd.read_csv(H / "historical_evidence_assertions.csv")
    assert not a["exact_locator"].str.contains("6079718", na=False).any()


def test_sardinia_actor_scope_wording_is_aligned():
    """The actor is not redefined to justify the scope."""
    sp = pd.read_csv(SD / "scenario_polities.csv",
                     keep_default_na=False, na_values=[])
    assert (sp.loc[sp.polity_id == "pol_sardinia", "display_name"].iloc[0]
            == "Kingdom of Sardinia (Savoy-Piedmont)")
    for path, col in ((H / "historical_evidence_assertions.csv", "notes"),
                      (H / "historical_subject_scenario_mapping.csv",
                       "mapping_basis"),
                      (SD / "political_coverage.csv", "notes")):
        d = pd.read_csv(path, keep_default_na=False, na_values=[])
        assert not d[col].str.contains("legally IS the island",
                                       na=False).any()
        assert not d[col].str.contains("not part of the Kingdom of Sardinia",
                                       na=False).any()


# ---------------------------------------------------------------------------
# authority
# ---------------------------------------------------------------------------
def test_iceland_title_is_icelands_own_act(ice_ev):
    r = ice_ev[ice_ev.kind == "SOVEREIGNTY_BASIS"].iloc[0]
    assert r["document_date"] == "1662-07-28"
    assert "Kopavog" in r["exact_locator"]
    assert "p. 273" in r["exact_locator"]
    assert "Nye kongel" in r["exact_locator"]
    assert r["in_force_at_snapshot"] == "YES"


def test_iceland_has_a_document_dated_before_the_snapshot(ice_ev):
    now = ice_ev[ice_ev.kind.str.startswith("CONTEMPORARY")]
    assert len(now) >= 2
    pre = now[now["document_date"] <= "1756-08-01"]
    assert len(pre) >= 1
    assert pre.iloc[0]["document_date"] == "1756-07-16"
    assert "42A" in pre.iloc[0]["exact_locator"]


def test_malta_has_a_dated_1756_act_of_government(mlt_ev):
    now = mlt_ev[mlt_ev.kind.str.startswith("CONTEMPORARY")]
    press = now[now["document_date"] == "1756-06-05"]
    assert len(press) == 1
    assert press.iloc[0]["document_date"] <= "1756-08-01"
    assert "Pinto" in press.iloc[0]["title"]


def test_1798_is_recorded_and_not_in_force(mlt_ev):
    c = mlt_ev[mlt_ev.evidence_role == "TEMPORAL_BOUNDARY"]
    assert len(c) >= 1
    assert (c["in_force_at_snapshot"] == "NO").all()
    assert (c["effective_date"] > "1756-08-01").all()


def test_no_evidence_row_is_boundary_position(ice_ev, mlt_ev):
    both = pd.concat([ice_ev, mlt_ev])
    assert set(both["evidence_role"]) <= {"POLITICAL_CONTROL",
                                          "ADMINISTRATIVE_SCOPE",
                                          "TEMPORAL_BOUNDARY"}


def test_no_name_inference_and_no_modern_administration(ice_ev, mlt_ev):
    both = pd.concat([ice_ev, mlt_ev])
    assert (both["modern_administrative_geography_used"] == "NO").all()
    assert (both["name_inference_used"] == "NO").all()
    snapf = pd.read_csv(H / "historical_snapshot_features_1756_08_01.csv")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    allowed = set(reg.loc[reg["citation_key"].isin(
        ["osm_land_polygons_split_3857", "lovsamling_for_island_i",
         "thjodskjalasafn_skjalasafn_amtmanns",
         "charles_v_privilege_1530_malta_gozo",
         "aom_national_library_of_malta",
         "malta_government_printing_press_history"]), "global_source_id"])
    used = set()
    for v in snapf[snapf.historical_subject_id.isin(
            [SUBJ_ICE, SUBJ_MLT, SUBJ_GOZ])]["bundle_source_ids"]:
        used |= {x for x in str(v).split("|") if x}
    assert used and used <= allowed


# ---------------------------------------------------------------------------
# scope discipline
# ---------------------------------------------------------------------------
def test_denmark_norway_inherits_only_iceland(canon, mix):
    from _production_baseline import hex_control
    dk = hex_control(canon)
    dk = dk[dk["controller_scenario_polity_id"] == DK_SP]
    assert len(dk) == int((mix["winner"] == "iceland").sum())
    sp = pd.read_csv(SD / "scenario_polities.csv",
                     keep_default_na=False, na_values=[])
    for p in ("pol_norway", "pol_denmark", "pol_faroe_islands",
              "pol_greenland", "pol_iceland"):
        assert p not in set(sp["polity_id"])
    mp = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    basis = mp.loc[mp.historical_subject_id == SUBJ_ICE,
                   "mapping_basis"].iloc[0]
    assert "Greenland" in basis and "UNASSESSED" in basis


def test_the_faroes_are_excluded_despite_the_shared_crown():
    """Same monarch, separate act of homage, separate territory."""
    ex = pd.read_csv(H / "iceland_exclusion_audit.csv",
                     keep_default_na=False, na_values=[])
    f = ex[ex["named_identification"].str.contains("Faroe", na=False)]
    assert len(f) >= 5
    assert (f["exclusion_reason"]
            == "SEPARATE_HOMAGE_SEPARATE_TERRITORY_NOT_ICELAND").all()
    assert "Thorshavn" in f.iloc[0]["note"]


def test_malta_and_gozo_map_only_to_the_order(canon, mix):
    from _production_baseline import hex_control
    mp = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    assert set(mp.loc[mp.historical_subject_id.isin([SUBJ_MLT, SUBJ_GOZ]),
                      "scenario_polity_id"]) == {OSJ_SP}
    osj = hex_control(canon)
    osj = osj[osj["controller_scenario_polity_id"] == OSJ_SP]
    assert len(osj) == int(mix["winner"].isin(["malta", "gozo"]).sum())
    assert int((mix["winner"] == "gozo").sum()) > 0


# ---------------------------------------------------------------------------
# membership
# ---------------------------------------------------------------------------
def test_membership_is_whole_land_not_centroid(mix):
    assert "centre_lon" not in mix.columns
    ctrl = mix[mix.control_status == "CONTROLLED"]
    assert (ctrl[["iceland_km2", "malta_km2", "gozo_km2"]].max(axis=1)
            > 0).all()
    assert (mix["hex_land_km2"] > 0).all()


def test_mixed_components_are_held_back(mix):
    held = mix[mix.basis == "MIXED_UNAUDITED_LAND_COMPONENT"]
    assert (held["control_status"] == "UNRESOLVED").all()
    assert (mix.loc[mix.control_status == "CONTROLLED",
                    "unaudited_share"] <= 0.02).all()


def test_no_hex_carries_two_authorised_components(mix):
    n = ((mix["iceland_km2"] > 0).astype(int)
         + (mix["malta_km2"] > 0).astype(int)
         + (mix["gozo_km2"] > 0).astype(int))
    assert int((n > 1).sum()) == 0


def test_the_terrestrial_hex_cost_is_measured_not_hidden(mix):
    """The canonical majority-land rule withholds real land. Say so.

    Every island stage so far paid this and none reported it. On Malta it
    is roughly half the hexes carrying Maltese land, so it stops being a
    rounding detail.
    """
    npd = mix[mix.control_status == "NOT_PRODUCED"]
    assert len(npd) > 0
    assert (npd["basis"] == "NOT_A_CANONICAL_TERRESTRIAL_HEX").all()
    assert not npd["is_terrestrial_hex"].any()
    assert npd["hex_land_km2"].sum() > 0
    canon = pd.read_csv(SD / "territorial_control.csv",
                        keep_default_na=False, na_values=[""])
    assert not set(npd["hex_id"]) & set(canon["territorial_target_id"])
    mlt = npd[npd.region == "malta"]
    assert len(mlt) >= int((mix.control_status == "CONTROLLED")
                           .loc[mix.region == "malta"].sum()) - 1


# ---------------------------------------------------------------------------
# audits and promotion
# ---------------------------------------------------------------------------
def test_area_semantics_cover_every_island_produced():
    a = pd.read_csv(H / "island_area_semantics.csv")
    assert {"Iceland", "Malta", "Gozo", "Sicily", "Sardinia"} <= set(
        a["landmass"])
    assert (a["n_interior_rings"] == 0).all()
    assert a["inland_water_treatment"].str.startswith("MEASURED").all()
    assert (a["difference_pct"].abs() < 2).all()


def test_physical_change_is_audited_without_stopping_the_interior():
    cc = pd.concat([pd.read_csv(H / "iceland_coastal_change_audit.csv"),
                    pd.read_csv(H / "malta_coastal_change_audit.csv")])
    assert len(cc) >= 5
    assert (cc["interior_affected"] == "NO").all()
    assert cc["measured"].str.startswith("YES").any()
    assert cc["measured"].str.startswith("NO").any()
    assert cc["mechanism"].str.contains("GLACIER").any()


def test_geometry_is_exact_and_stored_once():
    g = pd.read_csv(H / "geometry_storage_audit.csv")
    assert len(g) >= 7
    assert (g["simplified"] == "NO").all()
    assert (g["duplicated_as_wkt_csv"] == "NO").all()
    assert (g["simplification_tolerance_m"] == 0).all()
    assert g["wkb_sha256"].is_unique
    s = pd.read_csv(H / "historical_snapshot_features_1756_08_01.csv")
    assert "geometry" not in s.columns


def test_every_row_has_provenance(canon, mix):
    prov = pd.read_csv(SD / "territorial_control_provenance.csv",
                       keep_default_na=False, na_values=[""])
    ours = set(mix.loc[mix.control_status != "NOT_PRODUCED", "hex_id"])
    rows = canon[canon["territorial_target_id"].isin(ours)]
    assert len(rows) == len(ours)
    assert rows["source_id"].astype(str).str.len().gt(0).all()
    p = prov[prov["territorial_target_id"].isin(ours)]
    assert p["historical_subject_ids"].astype(str).str.len().gt(0).all()


def test_promotion_rerun_is_idempotent(canon):
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
        "seven_years_war_1756_08_01", "MAPGEN-023", "x", "none", "src_none",
        promoted_utc="2026-08-15")
    assert rep["inserted"] == 0
    assert len(c2) == len(canon)
    assert not rep["collisions"]


def test_coverage_is_partial_never_complete():
    cov = pd.read_csv(SD / "political_coverage.csv",
                      keep_default_na=False, na_values=[])
    new = cov[cov["coverage_unit_id"].isin(
        ["region_iceland_main_island_1756",
         "region_malta_main_island_1756", "region_gozo_1756"])]
    assert len(new) == 3
    assert (new["control_coverage_status"] == "TERRITORY_PARTIAL").all()
    assert int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0


def test_completion_summary_matches_committed_output():
    """The reported figures come from the artifact, not from memory."""
    from mapgen.historical_batch_islands_pipeline import committed_baseline
    base = committed_baseline()
    assert base["canonical_rows_after"] == 32193
    assert base["canonical_controlled_after"] == 31140
    assert base["sicily_controlled"] == 1305
    assert base["sardinia_controlled"] == 1308


def test_earlier_stages_are_untouched(canon):
    from _production_baseline import strip_island_production
    assert len(strip_island_production(canon)) == 1614
    for sp in ("sp_6b03622fc98a", "sp_c8f0dcb42a96"):
        assert int((canon["controller_scenario_polity_id"] == sp).sum()) > 0
