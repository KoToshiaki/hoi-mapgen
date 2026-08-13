# -*- coding: utf-8 -*-
"""MAPGEN-015 — metric semantics, model audit and georeference discipline.

The rules defended here: a metric may not carry a polity's name unless
it is filtered to that polity, a depiction-level agreement is not a
measured corroboration, an unreadable numeral stays empty, a rectified
page is not a georeferenced one, and uncertainty may not fall without
cross-source evidence.
"""
from pathlib import Path

import pandas as pd
import pytest

DATA = Path("data")
H = DATA / "historical"
SC = "seven_years_war_1756_08_01"
SD = DATA / "scenarios" / SC
PROD = (H / "historical_map_text_anchor_candidates.csv").exists()
prod = pytest.mark.skipif(not PROD, reason="MAPGEN-015 data not built")


# ---- pure semantics (no production data needed) -------------------------
def _counts(canonical, provenance, subject_key):
    """The aggregation MAPGEN-014 got wrong: filter by the subject named
    in each row's provenance, never by 'whatever was in the candidate'."""
    ids = [t for t, s in zip(provenance["territorial_target_id"],
                             provenance["historical_subject_ids"].fillna(""))
           if subject_key in s]
    v = canonical[canonical["territorial_target_id"].isin(ids)][
        "control_status"].value_counts().to_dict()
    return {"CONTROLLED": v.get("CONTROLLED", 0),
            "UNRESOLVED": v.get("UNRESOLVED", 0)}


def _fixture():
    canonical = pd.DataFrame([
        {"territorial_target_id": "hA", "control_status": "CONTROLLED"},
        {"territorial_target_id": "hB", "control_status": "UNRESOLVED"},
        {"territorial_target_id": "hC", "control_status": "UNRESOLVED"},
    ])
    provenance = pd.DataFrame([
        {"territorial_target_id": "hA", "historical_subject_ids": "hsub_x"},
        {"territorial_target_id": "hB", "historical_subject_ids": "hsub_x"},
        {"territorial_target_id": "hC", "historical_subject_ids": "hsub_y"},
    ])
    return canonical, provenance


def test_polity_specific_aggregation_does_not_absorb_a_neighbour():
    c, p = _fixture()
    assert _counts(c, p, "hsub_x") == {"CONTROLLED": 1, "UNRESOLVED": 1}
    assert _counts(c, p, "hsub_y") == {"CONTROLLED": 0, "UNRESOLVED": 1}


def test_candidate_scope_aggregate_is_the_sum_of_the_parts():
    c, p = _fixture()
    x, y = _counts(c, p, "hsub_x"), _counts(c, p, "hsub_y")
    whole = c["control_status"].value_counts().to_dict()
    assert x["UNRESOLVED"] + y["UNRESOLVED"] == whole["UNRESOLVED"]
    assert x["UNRESOLVED"] != whole["UNRESOLVED"], (
        "the whole-candidate figure is exactly the bug: it must not be "
        "reported under one polity's name")


def _is_measured(row):
    return (row["corroboration_level"] == "MEASURED"
            and row["n_samples"] > 0
            and row["median_distance_km"] is not None
            and not pd.isna(row["median_distance_km"]))


def test_depiction_agreement_is_not_a_measured_corroboration():
    row = {"corroboration_level": "DEPICTION_LEVEL", "n_samples": 0,
           "median_distance_km": None, "agreement_status": "AGREES"}
    assert not _is_measured(row)


def test_zero_samples_can_never_be_measured():
    row = {"corroboration_level": "MEASURED", "n_samples": 0,
           "median_distance_km": None}
    assert not _is_measured(row)


def test_measured_corroboration_needs_real_statistics():
    ok = {"corroboration_level": "MEASURED", "n_samples": 37,
          "median_distance_km": 3.4}
    assert _is_measured(ok)
    assert not _is_measured({**ok, "median_distance_km": None})


def _accept_numeral(reading, status):
    """An UNREADABLE anchor may never contribute a value."""
    if status == "UNREADABLE":
        if reading:
            raise ValueError("an unreadable anchor carries no reading")
        return None
    return reading if status == "CLEAR" else None


def test_unreadable_numeral_cannot_be_filled_in():
    assert _accept_numeral("", "UNREADABLE") is None
    with pytest.raises(ValueError):
        _accept_numeral("29", "UNREADABLE")


def test_ambiguous_numeral_is_not_accepted_as_a_control_value():
    assert _accept_numeral("4|5'", "AMBIGUOUS") is None
    assert _accept_numeral("2|9°", "CLEAR") == "2|9°"


def _uncertainty(current_km, proposed_km, n_samples, georeferenced):
    """Uncertainty may only fall on measured cross-source evidence."""
    if proposed_km >= current_km:
        return proposed_km
    if not georeferenced or n_samples <= 0:
        raise ValueError("cannot reduce uncertainty without measured "
                         "cross-source residuals")
    return proposed_km


def test_uncertainty_cannot_fall_without_corroboration():
    with pytest.raises(ValueError):
        _uncertainty(9.168, 2.0, n_samples=0, georeferenced=False)
    with pytest.raises(ValueError):
        _uncertainty(9.168, 2.0, n_samples=50, georeferenced=False)
    assert _uncertainty(9.168, 2.0, n_samples=50, georeferenced=True) == 2.0
    assert _uncertainty(9.168, 12.0, 0, False) == 12.0


def test_finer_scale_alone_does_not_justify_lower_uncertainty():
    with pytest.raises(ValueError):
        _uncertainty(9.168, 1.0, n_samples=0, georeferenced=True)


def _rectified_to_geographic(rect_transform, geo_transform):
    if geo_transform is None:
        raise ValueError("a rectified page is not a georeferenced page")
    return (rect_transform, geo_transform)


def test_rectification_is_not_georeference():
    with pytest.raises(ValueError):
        _rectified_to_geographic({"rotation_deg": -0.41}, None)
    assert _rectified_to_geographic({"rotation_deg": -0.41},
                                    {"model": "PROJECTIVE"})


def _seam(sheet_a_georef, sheet_b_georef, samples):
    if not (sheet_a_georef and sheet_b_georef):
        return "NOT_MEASURABLE_NO_GEOREFERENCE", 0
    return "MEASURED", len(samples)


def test_two_sheet_seam_is_not_reported_as_zero_offset():
    status, n = _seam(False, False, [])
    assert status == "NOT_MEASURABLE_NO_GEOREFERENCE" and n == 0


def _continuity_ok(assertions, source_id, subject):
    return any(a["global_source_id"] == source_id
               and a["historical_subject_id"] == subject
               and a["assertion_type"] == "TERRITORIAL_CONTINUITY"
               for a in assertions)


def test_off_date_geometry_needs_continuity_not_existence():
    a = [{"global_source_id": "hsrc_1747",
          "historical_subject_id": "hsub_w",
          "assertion_type": "POLITY_EXISTENCE"}]
    assert not _continuity_ok(a, "hsrc_1747", "hsub_w")
    a.append({"global_source_id": "hsrc_1747",
              "historical_subject_id": "hsub_w",
              "assertion_type": "TERRITORIAL_CONTINUITY"})
    assert _continuity_ok(a, "hsrc_1747", "hsub_w")


# ---- production data ----------------------------------------------------
@prod
def test_production_saxony_counts_are_polity_specific():
    c = pd.read_csv(SD / "territorial_control.csv")
    p = pd.read_csv(SD / "territorial_control_provenance.csv")
    sax = _counts(c, p, "meissen_electoral_saxony")
    wei = _counts(c, p, "duchy_of_saxe_weimar")
    assert sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
    assert wei["CONTROLLED"] == 0 and wei["UNRESOLVED"] > 0
    rv = pd.read_csv(SD / "territorial_control_revision_log.csv")
    assert len(rv) == 1096 - sax["CONTROLLED"] == 401


@prod
def test_production_anchor_readings_are_honest():
    a = pd.read_csv(H / "historical_map_text_anchor_candidates.csv",
                    keep_default_na=False, na_values=[""])
    assert set(a["reading_status"]) <= {"CLEAR", "AMBIGUOUS", "UNREADABLE"}
    unread = a[a["reading_status"] == "UNREADABLE"]
    assert unread["raw_reading"].fillna("").eq("").all()
    assert (unread["accepted"] == "NO").all()
    assert (a.loc[a["reading_status"] == "AMBIGUOUS",
                  "accepted"] == "NO").all()


@prod
def test_production_1747_has_no_gcp_and_no_assertion():
    g = pd.read_csv(H / "historical_map_gcps.csv")
    assert not g["map_source_id"].str.contains("hsrc_").eq(False).any()
    reg = pd.read_csv(H / "historical_source_registry.csv")
    sid = reg.loc[reg["citation_key"].str.contains("zollmann_1747"),
                  "global_source_id"].iloc[0]
    assert sid not in set(g["map_source_id"]), "no GCP may exist yet"
    a = pd.read_csv(H / "historical_evidence_assertions.csv")
    assert sid not in set(a["global_source_id"])
    assert reg.loc[reg["global_source_id"] == sid,
                   "georeference_status"].iloc[0] in (
        "NOT_YET_GEOREFERENCED", "DEFERRED_AFTER_BOUNDED_ATTEMPT")


@prod
def test_production_rectification_applied_nothing():
    r = pd.read_csv(H / "historical_scan_rectification.csv")
    assert len(r) == 8
    assert r["rotation_deg_applied"].isna().all()
    assert r["projective_parameters"].isna().all()
    assert set(r["detection_status"]) == {"RELIABLE", "DETECTOR_FAILED"}
    assert (r[r["detection_status"] == "RELIABLE"]["line_fit_rms_px"]
            < 20).all()


@prod
def test_production_weimar_eisenach_modelled_as_personal_union():
    sp = pd.read_csv(SD / "scenario_polities.csv")
    pol = pd.read_csv(DATA / "scenarios" / "polities.csv")
    assert "pol_saxe_eisenach" in set(pol["polity_id"])
    assert "pol_saxe_weimar_eisenach" not in set(pol["polity_id"])
    rows = sp[sp["polity_id"].isin(["pol_saxe_weimar",
                                    "pol_saxe_eisenach"])]
    assert len(rows) == 2
    assert (rows["territorial_authority_role"]
            == "DIRECT_TERRITORIAL_ACTOR").all()
    rel = pd.read_csv(SD / "scenario_polity_relationships.csv")
    ids = set(rows["scenario_polity_id"])
    pu = rel[(rel["relationship_type"] == "PERSONAL_UNION")
             & rel["from_scenario_polity_id"].isin(ids)
             & rel["to_scenario_polity_id"].isin(ids)]
    assert len(pu) == 1


@prod
def test_production_model_audit_records_the_disagreement():
    a = pd.read_csv(H / "saxe_weimar_eisenach_model_audit.csv",
                    keep_default_na=False, na_values=[""])
    assert len(a) >= 5
    assert "WEAK_YES" in set(a["supports_unified_polity"])
    assert "STRONG_YES" in set(a["supports_distinct_constituent"])
    dec = a[a["evidence_type"] == "DECISION"]
    assert len(dec) == 1
    assert "PERSONAL_UNION" in dec.iloc[0]["notes"]


@prod
def test_production_iiif_local_raster_is_native_maximum():
    i = pd.read_csv(H / "historical_iiif_acquisition_audit.csv")
    assert len(i) == 2
    assert (i["info_json_native_width"] == i["local_raster_width"]).all()
    assert (i["info_json_native_height"] == i["local_raster_height"]).all()
    assert (i["local_is_native_maximum"] == "YES").all()


@prod
def test_production_ferro_is_data_not_a_magic_constant():
    m = pd.read_csv(H / "historical_prime_meridian_contract.csv")
    assert len(m) >= 2
    assert (abs(m["conversion_to_greenwich_deg"] - (2.337229 - 20.0))
            < 1e-9).all()
    assert m["source_text"].str.len().min() > 20
    assert m["conversion_source"].str.len().min() > 20
