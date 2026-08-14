"""MAPGEN-021 — a coastline is a shape, not a title deed.

The load-bearing test in this file is the one that proves physical
geography alone cannot produce ownership. Everything else follows from it.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

H = Path("data/historical")
SD = Path("data/scenarios/seven_years_war_1756_08_01")
GB_SP, IE_SP = "sp_6b03622fc98a", "sp_c8f0dcb42a96"
SUBJ_GB = "hsub_great_britain_main_island"
SUBJ_IE = "hsub_ireland_main_island"


@pytest.fixture(scope="module")
def ev():
    return pd.read_csv(H / "british_isles_historical_evidence.csv",
                       keep_default_na=False, na_values=[])


@pytest.fixture(scope="module")
def ident():
    return pd.read_csv(H / "british_isles_landmass_identity.csv",
                       keep_default_na=False, na_values=[]).fillna("")


@pytest.fixture(scope="module")
def mix():
    return pd.read_csv(H / "british_isles_hex_membership_audit.csv",
                       keep_default_na=False, na_values=[])


@pytest.fixture(scope="module")
def canon():
    return pd.read_csv(SD / "territorial_control.csv",
                       keep_default_na=False, na_values=[""])


# ---------------------------------------------------------------------------
# the rule everything else rests on
# ---------------------------------------------------------------------------
def test_physical_geometry_alone_cannot_create_ownership():
    """The coastline carries geometry authority and NOTHING else.

    'A modern coastline exists, therefore Great Britain owns it' must be
    inexpressible: the geometry assertion is explicitly political_authority
    = NO, so a bundle built on it alone fails validation.
    """
    a = pd.read_csv(H / "historical_evidence_assertions.csv")
    geo = a[(a["historical_subject_id"].isin([SUBJ_GB, SUBJ_IE]))
            & (a["assertion_type"] == "GEOMETRIC_SUBSTRATE_ONLY")]
    assert len(geo) == 2
    assert (geo["geometry_authority"] == "YES").all()
    assert (geo["political_authority"] == "NO").all()


def test_political_authority_carries_no_geometry():
    a = pd.read_csv(H / "historical_evidence_assertions.csv")
    pol = a[(a["historical_subject_id"].isin([SUBJ_GB, SUBJ_IE]))
            & (a["assertion_type"] == "POLITICAL_CONTROL")]
    assert len(pol) == 2
    assert (pol["political_authority"] == "YES").all()
    assert (pol["geometry_authority"] == "NO").all()


def test_a_bundle_without_political_evidence_is_rejected():
    """Negative fixture: strip the political link and the feature must fail."""
    import geopandas as gpd

    from mapgen.historical_binding import compile_authorised_snapshot_features
    feats = gpd.read_parquet(H / "historical_boundary_features.parquet")
    links = pd.read_csv(H / "historical_boundary_feature_evidence.csv")
    asrt = pd.read_csv(H / "historical_evidence_assertions.csv")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    mp = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    gutted = links[links["evidence_role"] != "POLITICAL_STATUS"]
    ok, rej = compile_authorised_snapshot_features(
        feats, gutted, asrt, reg, mp, "1756-08-01")
    authorised = set(ok["historical_subject_id"]) if len(ok) else set()
    assert SUBJ_GB not in authorised
    assert SUBJ_IE not in authorised
    reasons = " ".join(rej["rejection_reasons"]) if len(rej) else ""
    assert "POLITICAL_STATUS" in reasons


# ---------------------------------------------------------------------------
# historical authority
# ---------------------------------------------------------------------------
def test_1707_union_article_i_quoted_with_locator(ev):
    r = ev[ev["evidence_id"] == "bi_1707_union_article_i"].iloc[0]
    assert "ARTICLE I" in r["exact_locator"]
    assert "one Kingdom by the name of Great Britain" in r["quotation"]
    assert r["effective_date"] == "1707-05-01"
    assert r["in_force_at_snapshot"] == "YES"


def test_1756_statutes_cover_both_former_kingdoms(ev):
    gb = ev[(ev["polity"] == "pol_great_britain")
            & (ev["document_date"].astype(str) == "1756")]
    assert len(gb) >= 2
    wording = " | ".join(gb["territorial_wording"])
    assert "North Britain" in wording      # Scotland
    assert "York" in wording               # England


def test_irish_authority_is_in_force_before_the_snapshot(ev):
    ie = ev[ev["polity"] == "pol_kingdom_of_ireland"]
    assert len(ie) >= 1
    inforce = ie[ie["effective_date"] <= "1756-08-01"]
    assert len(inforce) >= 1
    assert inforce["exact_locator"].str.contains("irishstatutebook").any()


def test_1801_union_is_recorded_and_not_in_force(ev):
    r = ev[ev["evidence_id"] == "bi_1801_union_temporal_cutoff"].iloc[0]
    assert r["effective_date"] == "1801-01-01"
    assert r["in_force_at_snapshot"] == "NO"
    assert r["evidence_role"] == "TEMPORAL_BOUNDARY"


def test_no_evidence_row_is_boundary_position(ev):
    assert set(ev["evidence_role"]) <= {"POLITICAL_CONTROL",
                                        "ADMINISTRATIVE_SCOPE",
                                        "TEMPORAL_BOUNDARY"}


# ---------------------------------------------------------------------------
# polity separation
# ---------------------------------------------------------------------------
def test_great_britain_and_ireland_are_separate_actors(canon):
    gb = set(canon.loc[canon["controller_scenario_polity_id"] == GB_SP,
                       "territorial_target_id"])
    ie = set(canon.loc[canon["controller_scenario_polity_id"] == IE_SP,
                       "territorial_target_id"])
    assert gb and ie
    assert not gb & ie


def test_personal_union_inherits_zero_territory(canon):
    """A shared crown is not a shared border."""
    import hashlib
    han = "sp_" + hashlib.sha1(
        b"seven_years_war_1756_08_01|pol_hanover").hexdigest()[:12]
    assert int((canon["controller_scenario_polity_id"] == han).sum()) == 0
    mp = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    assert set(mp.loc[mp.historical_subject_id == SUBJ_GB,
                      "scenario_polity_id"]) == {GB_SP}
    assert set(mp.loc[mp.historical_subject_id == SUBJ_IE,
                      "scenario_polity_id"]) == {IE_SP}


def test_no_modern_administrative_source_reaches_production(ev):
    assert (ev["modern_administrative_geography_used"] == "NO").all()
    snapf = pd.read_csv(H / "historical_snapshot_features_1756_08_01.csv")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    allowed = set(reg.loc[reg["citation_key"].isin(
        ["osm_land_polygons_split_3857", "legislation_gov_uk_apgb",
         "irish_statute_book_pre_union"]), "global_source_id"])
    used = set()
    for v in snapf[snapf["historical_subject_id"].isin(
            [SUBJ_GB, SUBJ_IE])]["bundle_source_ids"]:
        used |= {x for x in str(v).split("|") if x}
    assert used and used <= allowed


# ---------------------------------------------------------------------------
# landmass identity
# ---------------------------------------------------------------------------
def test_main_landmasses_are_the_two_largest_components(ident):
    gb = ident[ident["stage_role"] == "MAIN_LANDMASS_GREAT_BRITAIN"]
    ie = ident[ident["stage_role"] == "MAIN_LANDMASS_IRELAND"]
    assert len(gb) == 1 and len(ie) == 1
    assert int(gb.iloc[0]["rank_by_area"]) == 0
    assert int(ie.iloc[0]["rank_by_area"]) == 1
    assert gb.iloc[0]["ground_area_km2"] > ie.iloc[0]["ground_area_km2"]


def test_identity_is_confirmed_by_three_anchors_each(ident):
    gb = ident[ident["stage_role"] == "MAIN_LANDMASS_GREAT_BRITAIN"].iloc[0]
    ie = ident[ident["stage_role"] == "MAIN_LANDMASS_IRELAND"].iloc[0]
    assert len(gb["anchors_contained_gb"].split(";")) == 3
    assert len(ie["anchors_contained_ie"].split(";")) == 3


def test_anchors_are_never_an_ownership_source(ident):
    assert (ident["anchor_role"]
            == "IDENTITY_QA_ONLY_NOT_OWNERSHIP_SOURCE").all()
    assert (ident["ownership_source"] == "HISTORICAL_EVIDENCE_BUNDLE").all()


def test_isle_of_man_is_excluded_and_1765_is_not_backdated():
    e = pd.read_csv(H / "british_isles_exclusion_audit.csv",
                    keep_default_na=False, na_values=[]).fillna("")
    iom = e[e["named_identification"] == "Isle of Man"]
    assert len(iom) == 1
    assert iom.iloc[0]["exclusion_reason"] == (
        "HISTORICAL_AUTHORITY_NOT_GREAT_BRITAIN_1756")
    assert "1765" in iom.iloc[0]["note"]
    assert 500 < float(iom.iloc[0]["ground_area_km2"]) < 650


def test_offshore_components_are_not_swept_in_by_proximity():
    e = pd.read_csv(H / "british_isles_exclusion_audit.csv",
                    keep_default_na=False, na_values=[]).fillna("")
    named = set(e["named_identification"])
    for isl in ("Lewis and Harris", "Skye", "Orkney Mainland",
                "Shetland Mainland", "Anglesey", "Isle of Wight"):
        assert isl in named, isl
    assert (e["exclusion_reason"].str.len() > 0).all()


# ---------------------------------------------------------------------------
# membership
# ---------------------------------------------------------------------------
def test_membership_is_whole_land_not_centroid(mix):
    assert (mix["hex_land_km2"] > 0).all()
    for c in ("great_britain_km2", "ireland_km2", "unaudited_other_km2"):
        assert c in mix.columns
    # every CONTROLLED hex is essentially all one authorised landmass
    ctrl = mix[mix["control_status"] == "CONTROLLED"]
    assert (ctrl["unaudited_share"] <= 0.02).all()


def test_mixed_component_hexes_are_held_back(mix):
    held = mix[mix["basis"] == "MIXED_UNAUDITED_LAND_COMPONENT"]
    assert len(held) > 0
    assert (held["control_status"] == "UNRESOLVED").all()
    assert (held["winner"] == "").all()


def test_no_collision_is_resolved_silently(mix):
    both = mix[(mix["great_britain_km2"] > 0) & (mix["ireland_km2"] > 0)]
    if len(both):
        assert both["basis"].isin(
            ["GB_IE_RESOLVED_ON_LAND_INTERSECTION",
             "MIXED_UNAUDITED_LAND_COMPONENT", "GB_IE_EXACT_TIE"]).all()


def test_landmass_areas_match_published_figures(ident):
    """A crude but load-bearing sanity check: if the component were wrong,
    the area would not land within a few per cent of the real island."""
    gb = ident[ident["stage_role"] == "MAIN_LANDMASS_GREAT_BRITAIN"].iloc[0]
    ie = ident[ident["stage_role"] == "MAIN_LANDMASS_IRELAND"].iloc[0]
    assert 200_000 < float(gb["ground_area_km2"]) < 235_000
    assert 78_000 < float(ie["ground_area_km2"]) < 90_000


# ---------------------------------------------------------------------------
# canonical promotion
# ---------------------------------------------------------------------------
def test_great_britain_promoted(canon):
    gb = canon[canon["controller_scenario_polity_id"] == GB_SP]
    assert int((gb["control_status"] == "CONTROLLED").sum()) > 10_000


def test_ireland_promoted(canon):
    ie = canon[canon["controller_scenario_polity_id"] == IE_SP]
    assert int((ie["control_status"] == "CONTROLLED").sum()) > 4_000


def test_every_british_isles_row_has_provenance(canon, mix):
    prov = pd.read_csv(SD / "territorial_control_provenance.csv",
                       keep_default_na=False, na_values=[""])
    targets = set(mix["hex_id"])
    rows = canon[canon["territorial_target_id"].isin(targets)]
    assert len(rows) == len(mix)
    p = prov[prov["territorial_target_id"].isin(targets)]
    assert len(p) == len(mix)
    assert (p["scenario_source_id"].str.len() > 0).all()
    assert (p["boundary_feature_ids"].str.len() > 0).all()
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
        "MAPGEN-021", "x", "none", "src_none", promoted_utc="2026-08-15")
    assert rep["inserted"] == 0
    assert len(c2) == len(canon)


def test_coverage_is_partial_never_complete():
    cov = pd.read_csv(SD / "political_coverage.csv", keep_default_na=False,
                      na_values=[""])
    rows = cov[cov["coverage_unit_id"].isin(
        ["region_great_britain_main_island_1756",
         "region_ireland_main_island_1756"])]
    assert len(rows) == 2
    assert (rows["control_coverage_status"] == "TERRITORY_PARTIAL").all()
    assert int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0


def test_earlier_stages_are_untouched(canon):
    """Everything MAPGEN-020 left behind must still be there underneath."""
    from _production_baseline import strip_island_production
    rest = strip_island_production(canon)
    assert len(rest) == 1614
    v = rest["control_status"].value_counts().to_dict()
    assert v["CONTROLLED"] == 697 and v["UNRESOLVED"] == 917
