"""MAPGEN-012 tests — authorised snapshot compiler + the real 1756
Central Europe production pilot artifacts."""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely

from mapgen.hex_grid import HexGrid
from mapgen.historical_binding import (bind_snapshot_to_hexes,
                                       compile_authorised_snapshot_features,
                                       controls_from_membership,
                                       hexification_audit,
                                       membership_conservation_audit)
from mapgen.historical_georeference import (PRIME_MERIDIANS,
                                            apply_transform,
                                            evaluate_models, fit_transform,
                                            line_intersection,
                                            residuals_m, select_model,
                                            to_greenwich)
from mapgen.historical_geometry import (make_evidence_assertion_id,
                                        make_global_source_id)

DATA = Path("data")
H = DATA / "historical"
GRID = HexGrid(flat_to_flat=6000.0)
SC = "seven_years_war_1756_08_01"
SNAP = "1756-08-01"
SUBJ = "hsub_e2e"
GS = make_global_source_id("e2e_map")
PS = make_global_source_id("e2e_pol")


def _e2e_inputs():
    reg = pd.DataFrame([
        {"global_source_id": GS,
         "authority_level": "BOUNDARY_AUTHORITY_CANDIDATE"},
        {"global_source_id": PS, "authority_level": "ACADEMIC_REFERENCE"}])
    a_geom = {"historical_evidence_id": make_evidence_assertion_id(
        GS, SUBJ, "BOUNDARY_POSITION", "1756-01-01", "1756-12-31"),
        "global_source_id": GS, "historical_subject_id": SUBJ,
        "assertion_type": "BOUNDARY_POSITION",
        "valid_from": "1756-01-01", "valid_to": "1756-12-31",
        "temporal_precision": "YEAR", "exact_locator": "sheet 1",
        "interpretation_level": "DIRECT", "confidence": "HIGH",
        "geometry_authority": "YES", "political_authority": "NO",
        "notes": "TEST ONLY"}
    a_pol = dict(a_geom, historical_evidence_id=make_evidence_assertion_id(
        PS, SUBJ, "POLITICAL_CONTROL", "1748-01-01", "1763-12-31"),
        global_source_id=PS, assertion_type="POLITICAL_CONTROL",
        valid_from="1748-01-01", valid_to="1763-12-31",
        confidence="MEDIUM", geometry_authority="NO",
        political_authority="YES", exact_locator="page 12")
    ass = pd.DataFrame([a_geom, a_pol])
    poly = GRID.polygon(11, 11).buffer(9000)
    feat = gpd.GeoDataFrame([{
        "boundary_feature_id": "hbf_e2e", "historical_subject_id": SUBJ,
        "feature_role": "DE_FACTO_CONTROL_BOUNDARY",
        "valid_from": "1756-01-01", "valid_to": "1756-12-31",
        "temporal_precision": "YEAR", "global_source_id": GS,
        "geometry_source_id": GS, "political_evidence_source_id": PS,
        "political_evidence_id": None, "source_locator": "sheet 1",
        "interpretation_level": "DERIVED", "source_confidence": "HIGH",
        "positional_uncertainty_km": 2.5,
        "digitisation_method": "TEST", "geometry_status":
            "GEOMETRY_PRESENT", "notes": "TEST ONLY",
        "geometry": poly}], geometry="geometry", crs="EPSG:3857")
    links = pd.DataFrame([
        {"boundary_feature_id": "hbf_e2e",
         "historical_evidence_id": a_geom["historical_evidence_id"],
         "evidence_role": "GEOMETRY_SHAPE", "is_required": "YES",
         "notes": ""},
        {"boundary_feature_id": "hbf_e2e",
         "historical_evidence_id": a_pol["historical_evidence_id"],
         "evidence_role": "POLITICAL_STATUS", "is_required": "YES",
         "notes": ""}])
    mapping = pd.DataFrame([{"historical_subject_id": SUBJ,
                             "scenario_polity_id": "sp_e2e"}])
    return feat, links, ass, reg, mapping


def test_end_to_end_source_to_control():
    feat, links, ass, reg, mapping = _e2e_inputs()
    auth, rej = compile_authorised_snapshot_features(
        feat, links, ass, reg, mapping, SNAP)
    assert len(auth) == 1 and len(rej) == 0
    row = auth.iloc[0]
    assert row["production_authorised"] is True or row[
        "production_authorised"]
    assert row["bundle_confidence"] == "MEDIUM"      # HIGH + MEDIUM
    assert row["scenario_polity_id"] == "sp_e2e"
    assert set(row["bundle_source_ids"].split("|")) == {GS, PS}
    b = row.geometry.bounds
    q, r = GRID.hexes_covering_bbox(*b)
    polys, ids = GRID.polygons(q, r), GRID.hex_ids(q, r)
    fmem, mem = bind_snapshot_to_hexes(
        auth, polys, ids, polys, np.ones(len(polys), bool), SC, SNAP)
    assert len(mem) > 0
    assert set(mem["source_confidence"]) == {"MEDIUM"}
    assert set(mem["bundle_source_ids"]) == {row["bundle_source_ids"]}
    ctrl = controls_from_membership(mem[mem["is_dominant"]], SC)
    assert len(ctrl) > 0
    assert set(ctrl["source_confidence"]) == {"MEDIUM"}
    assert set(ctrl["source_ids"]) == {row["bundle_source_ids"]}
    assert (ctrl["control_status"] == "CONTROLLED").all()
    assert "claimant_scenario_polity_id" not in ctrl.columns
    land = dict(zip(ids, polys))
    cons = membership_conservation_audit(auth, mem, land)
    hexa = hexification_audit(auth, mem, land)
    assert abs(cons.iloc[0]["conservation_error_km2"]) \
        <= cons.iloc[0]["source_land_ground_km2"] * 1e-3
    assert hexa.iloc[0]["represented_hex_count"] > 0


def test_raw_feature_cannot_bind_directly():
    feat, *_ = _e2e_inputs()
    with pytest.raises(ValueError, match="authorised snapshot"):
        bind_snapshot_to_hexes(feat, np.array([], dtype=object), [],
                               np.array([], dtype=object),
                               np.array([], dtype=bool), SC, SNAP)


def test_deprecated_aliases_cannot_change_compiled_snapshot():
    feat, links, ass, reg, mapping = _e2e_inputs()
    base, _ = compile_authorised_snapshot_features(
        feat, links, ass, reg, mapping, SNAP)
    mutated = feat.copy()
    mutated["political_evidence_id"] = "hev_BOGUS"
    mutated["political_evidence_source_id"] = "hsrc_BOGUS"
    mutated["source_confidence"] = "HIGH"
    other, _ = compile_authorised_snapshot_features(
        mutated, links, ass, reg, mapping, SNAP)
    for c in ("bundle_confidence", "bundle_evidence_ids",
              "bundle_source_ids", "scenario_polity_id"):
        assert list(base[c]) == list(other[c])


def test_missing_subject_mapping_rejects_feature():
    feat, links, ass, reg, _ = _e2e_inputs()
    auth, rej = compile_authorised_snapshot_features(
        feat, links, ass, reg,
        pd.DataFrame(columns=["historical_subject_id",
                              "scenario_polity_id"]), SNAP)
    assert len(auth) == 0 and len(rej) == 1
    assert "no explicit scenario polity mapping" in \
        rej.iloc[0]["rejection_reasons"]


def test_uncertainty_must_be_measured():
    feat, links, ass, reg, mapping = _e2e_inputs()
    bad = feat.copy()
    bad["positional_uncertainty_km"] = 0.0
    auth, rej = compile_authorised_snapshot_features(
        bad, links, ass, reg, mapping, SNAP)
    assert len(auth) == 0
    assert "positional_uncertainty_km" in rej.iloc[0]["rejection_reasons"]


# --------------------------------------------------------------------------
# Georeference
# --------------------------------------------------------------------------
def test_prime_meridian_not_assumed_greenwich():
    assert PRIME_MERIDIANS["GREENWICH"] == 0.0
    ferro = PRIME_MERIDIANS["FERRO_20W_OF_PARIS"]
    assert -17.7 < ferro < -17.6
    assert abs(float(to_greenwich(31.4, "FERRO_20W_OF_PARIS")) - 13.74) \
        < 0.01


def test_transform_roundtrip_and_overfit_rejection():
    rng = np.random.default_rng(7)
    px = rng.uniform(0, 6000, 12)
    py = rng.uniform(0, 5000, 12)
    lon = 10.0 + px / 1000.0
    lat = 50.0 - py / 1500.0
    g = pd.DataFrame({"historical_x": px, "historical_y": py,
                      "reference_lon": lon, "reference_lat": lat,
                      "included_in_fit": [True] * 8 + [False] * 4,
                      "holdout": [False] * 8 + [True] * 4})
    audit = evaluate_models(g)
    assert set(audit["model"]) == {"AFFINE", "PROJECTIVE",
                                   "POLYNOMIAL_2"}
    assert select_model(audit) == "AFFINE"   # simplest adequate model
    t = fit_transform("AFFINE", px, py, lon, lat)
    assert float(residuals_m(t, px, py, lon, lat).max()) < 1.0


def test_underdetermined_model_is_not_fittable():
    g = pd.DataFrame({"historical_x": [0.0, 1.0, 2.0],
                      "historical_y": [0.0, 1.0, 0.0],
                      "reference_lon": [10.0, 10.1, 10.2],
                      "reference_lat": [50.0, 50.1, 50.0],
                      "included_in_fit": [True] * 3,
                      "holdout": [False] * 3})
    audit = evaluate_models(g, models=["POLYNOMIAL_2"])
    assert audit.iloc[0]["status"].startswith("NOT_FITTABLE")


def test_graticule_intersection_is_deterministic():
    a = line_intersection((10, 0), (12, 100), (0, 40), (100, 42))
    b = line_intersection((10, 0), (12, 100), (0, 40), (100, 42))
    assert a == b
    with pytest.raises(ValueError):
        line_intersection((0, 0), (1, 0), (0, 5), (1, 5))


# --------------------------------------------------------------------------
# Real production artifacts
# --------------------------------------------------------------------------
def test_production_boundary_feature_is_real_and_sourced():
    feats = gpd.read_parquet(H / "historical_boundary_features.parquet")
    assert len(feats) >= 1
    f = feats.iloc[0]
    assert f["geometry_status"] == "GEOMETRY_PRESENT"
    assert float(f["positional_uncertainty_km"]) > 0
    assert shapely.is_valid(f.geometry)
    reg = pd.read_csv(H / "historical_source_registry.csv")
    assert f["geometry_source_id"] in set(reg["global_source_id"])
    links = pd.read_csv(H / "historical_boundary_feature_evidence.csv")
    roles = set(links.loc[links["boundary_feature_id"]
                          == f["boundary_feature_id"], "evidence_role"])
    assert {"GEOMETRY_SHAPE", "POLITICAL_STATUS"} <= roles


def test_gcp_artifact_uses_map_graticule_not_modern_admin():
    g = pd.read_csv(H / "historical_map_gcps.csv")
    assert len(g) >= 10 and g["gcp_id"].is_unique
    assert (g["reference_type"].isin(
        ["MAP_GRATICULE", "SETTLEMENT_MODERN_REFERENCE"])).all()
    assert (g["reference_type"] == "MAP_GRATICULE").sum() >= 8
    # holdout points exist and residuals are recorded for every GCP
    assert g["holdout"].astype(bool).sum() >= 3
    assert g["residual_m"].notna().all()


def test_georeference_audit_rejects_overfitting():
    a = pd.read_csv(H / "historical_map_georeference_audit.csv")
    sel = a[a["selected"].astype(bool)].iloc[0]
    poly2 = a[a["model"] == "POLYNOMIAL_2"].iloc[0]
    assert sel["model"] != "POLYNOMIAL_2"
    assert poly2["fit_rms_m"] < sel["fit_rms_m"]        # better fit
    assert poly2["holdout_rms_m"] > sel["holdout_rms_m"]  # worse truth


def test_low_countries_source_gap_unchanged():
    cat = pd.read_csv(H / "historical_geometry_catalogue.csv")
    assert cat.loc[cat["catalogue_id"] == "hgc_low_countries_pilot",
                   "geometry_status"].iloc[0] == "SOURCE_GAP"
    feats = gpd.read_parquet(H / "historical_boundary_features.parquet")
    halc = make_global_source_id("historical_atlas_low_countries")
    assert not feats["geometry_source_id"].eq(halc).any()


def test_polity_model_gaps_recorded():
    gaps = pd.read_csv(H / "historical_polity_model_gaps.csv")
    assert len(gaps) >= 2
    assert set(gaps["gap_type"]) <= {"POLITY_MODEL_GAP",
                                     "SOURCE_EXTRACTION_GAP"}
    mapping = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    assert (mapping["reviewed"] == "YES").all()
    assert mapping["scenario_polity_id"].notna().all()
