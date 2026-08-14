# -*- coding: utf-8 -*-
"""MAPGEN-016 — feature-point georeference discipline and the opening of
a new production front.

The rules defended here: a feature GCP needs a verified identity, an
exhausted source may not authorise geometry, a plate privilege date is
not a represented political date, a same-house plate is not corroboration,
a regional name is not a controller, and a large polity's interior may be
resolved even when its border is not.
"""
from pathlib import Path

import pandas as pd
import pytest

DATA = Path("data")
H = DATA / "historical"
SC = "seven_years_war_1756_08_01"
SD = DATA / "scenarios" / SC
PROD = (H / "zollmann_feature_gcp_candidates.csv").exists()
prod = pytest.mark.skipif(not PROD, reason="MAPGEN-016 data not built")
EXHAUSTED = "GEOREFERENCE_EXHAUSTED_FOR_CURRENT_SCAN"


# ---- semantics ----------------------------------------------------------
def _accept_gcp(row):
    """A feature point is usable only with a verified identity AND a
    reference coordinate from a named dataset."""
    if row.get("identity_confidence") != "HIGH":
        return False
    if row.get("reference_lon") is None or row.get("reference_lat") is None:
        return False
    return bool(row.get("reference_source"))


def test_feature_gcp_needs_identity_and_reference():
    ok = {"identity_confidence": "HIGH", "reference_lon": 11.3,
          "reference_lat": 51.0, "reference_source": "GeoNames"}
    assert _accept_gcp(ok)
    assert not _accept_gcp({**ok, "identity_confidence": "MEDIUM"})
    assert not _accept_gcp({**ok, "reference_lon": None})
    assert not _accept_gcp({**ok, "reference_source": ""})


def test_citadel_is_not_the_town_centre():
    """The Erfurt case: a crisply drawn symbol is useless if it is not
    the feature the reference coordinate names."""
    erfurt = {"identity_confidence": "MEDIUM", "reference_lon": 11.03,
              "reference_lat": 50.98, "reference_source": "GeoNames"}
    assert not _accept_gcp(erfurt)


def _can_fit(n_accepted, model="AFFINE"):
    need = {"AFFINE": 3, "PROJECTIVE": 4, "POLYNOMIAL_2": 6}[model]
    if n_accepted < need:
        raise ValueError(f"{model} needs >= {need} control points, "
                         f"got {n_accepted}")
    return True


def test_one_point_cannot_define_a_transform():
    for n in (0, 1, 2):
        with pytest.raises(ValueError):
            _can_fit(n)
    assert _can_fit(3)


def _split(points, holdout_fraction=0.3):
    """Fit/holdout must be spatially stratified and may never place the
    same feature on both sides."""
    names = [p["name"] for p in points]
    if len(set(names)) != len(names):
        raise ValueError("a feature may not appear twice")
    n_hold = max(1, round(len(points) * holdout_fraction))
    if len(points) - n_hold < 3:
        raise ValueError("too few points to fit after holding out")
    ordered = sorted(points, key=lambda p: (p["x"], p["y"]))
    hold = ordered[::max(1, len(ordered) // n_hold)][:n_hold]
    fit = [p for p in ordered if p not in hold]
    return fit, hold


def test_fit_holdout_split_is_stratified_and_unique():
    pts = [{"name": f"t{i}", "x": i * 10, "y": (i * 7) % 50}
           for i in range(12)]
    fit, hold = _split(pts)
    assert len(hold) >= 3 and len(fit) >= 8
    assert not ({p["name"] for p in fit} & {p["name"] for p in hold})


def test_same_feature_cannot_be_fit_and_holdout():
    pts = [{"name": "weimar", "x": 1, "y": 1},
           {"name": "weimar", "x": 2, "y": 2},
           {"name": "jena", "x": 3, "y": 3},
           {"name": "erfurt", "x": 4, "y": 4}]
    with pytest.raises(ValueError, match="twice"):
        _split(pts)


def test_too_few_points_cannot_be_split():
    with pytest.raises(ValueError, match="too few"):
        _split([{"name": f"t{i}", "x": i, "y": i} for i in range(3)])


def _may_authorise(status, has_assertion):
    if status == EXHAUSTED:
        return False
    return has_assertion


def test_exhausted_source_cannot_authorise_geometry():
    assert not _may_authorise(EXHAUSTED, True)
    assert _may_authorise("GEOREFERENCED", True)
    assert not _may_authorise("GEOREFERENCED", False)


def _represented_date(plate_date, verified):
    """A privilege/plate date is not a represented political date."""
    return plate_date if verified else "UNVERIFIED"


def test_plate_date_is_not_a_political_date():
    assert _represented_date("1751", False) == "UNVERIFIED"
    assert _represented_date("1751", True) == "1751"


def _continuity_ok(gap_years, evidence):
    if not evidence:
        raise ValueError("a small date gap is not continuity evidence")
    return True


def test_small_gap_is_not_continuity():
    with pytest.raises(ValueError):
        _continuity_ok(5, [])
    assert _continuity_ok(5, ["Amt-level territorial record"])


def _corroborates(plate_family_a, plate_family_b, independence):
    return plate_family_a != plate_family_b and independence not in (
        "DERIVATIVE", "SAME_PLATE")


def test_same_house_plate_is_not_corroboration():
    fam = "FRENCH_SANSON_JAILLOT_VAUGONDY"
    assert not _corroborates(fam, fam, "DERIVATIVE")
    assert _corroborates(fam, "GERMAN_HOMANN_NUREMBERG",
                         "PARTIALLY_INDEPENDENT")


def _controller_for(region_name, audited_polity):
    if audited_polity is None:
        raise ValueError(f"'{region_name}' is a regional name, not a "
                         "controller; it needs its own polity audit")
    return audited_polity


def test_regional_name_is_not_a_controller():
    with pytest.raises(ValueError, match="regional name"):
        _controller_for("Pomerania", None)
    assert _controller_for("Brandenburg", "pol_brandenburg") \
        == "pol_brandenburg"


def _classify(distance_to_border_km, uncertainty_km):
    return ("BORDER_UNCERTAIN" if distance_to_border_km < uncertainty_km
            else "INTERIOR_CONFIDENT")


def test_large_polity_interior_resolves_even_with_a_coarse_border():
    """A 10 km uncertainty destroys a small territory but leaves a large
    one's interior intact — the reason to keep expanding."""
    big = [_classify(d, 10.0) for d in (2, 8, 25, 60, 120)]
    small = [_classify(d, 10.0) for d in (1, 3, 5, 7, 9)]
    assert big.count("INTERIOR_CONFIDENT") == 3
    assert small.count("INTERIOR_CONFIDENT") == 0


def _root_control(root_targets, member_targets):
    overlap = set(root_targets) & set(member_targets)
    if overlap:
        raise ValueError("a composite root may not duplicate a registered "
                         f"member's control: {sorted(overlap)[:3]}")
    return True


def test_composite_root_cannot_duplicate_member_control():
    with pytest.raises(ValueError):
        _root_control(["hA"], ["hA", "hB"])
    assert _root_control([], ["hA", "hB"])


# ---- production ---------------------------------------------------------
@prod
def test_production_route_b_recorded_every_rejection():
    c = pd.read_csv(H / "zollmann_feature_gcp_candidates.csv",
                    keep_default_na=False, na_values=[""])
    assert len(c) >= 10
    rej = c[c["accepted"] == "NO"]
    assert rej["excluded_reason"].str.len().min() > 20
    acc = c[c["accepted"] == "YES"]
    assert (acc["identity_confidence"] == "HIGH").all()
    assert acc["reference_lon"].notna().all()
    assert acc["reference_source"].str.contains("GeoNames").all()


@prod
def test_production_zollmann_is_deferred_and_authorises_nothing():
    """MAPGEN-017 relabelled EXHAUSTED -> DEFERRED_AFTER_BOUNDED_ATTEMPT:
    the bounded attempt is unchanged, but it never proved the scan
    ungeoreferenceable."""
    a = pd.read_csv(H / "zollmann_georeference_final_audit.csv")
    assert a.iloc[0]["final_status"] == "DEFERRED_AFTER_BOUNDED_ATTEMPT"
    assert int(a.iloc[0]["fit_count"]) == 0
    assert int(a.iloc[0]["sheets_georeferenced"]) == 0
    reg = pd.read_csv(H / "historical_source_registry.csv")
    sid = reg.loc[reg["citation_key"].str.contains("zollmann_1747"),
                  "global_source_id"].iloc[0]
    ev = pd.read_csv(H / "historical_evidence_assertions.csv")
    assert sid not in set(ev["global_source_id"])


@prod
def test_production_brandenburg_source_is_not_corroboration():
    lin = pd.read_csv(H / "historical_source_lineage.csv")
    row = lin[lin["global_source_id"].isin(
        pd.read_csv(H / "historical_source_registry.csv").loc[
            lambda d: d["citation_key"].str.contains("vaugondy_1751"),
            "global_source_id"])]
    assert len(row) == 1
    # MAPGEN-017: "same house" does not prove derivation, but it still
    # is not independence.
    assert row.iloc[0]["independence_status"] == "SHARED_ATLAS_LINEAGE"
    assert row.iloc[0]["corroboration_eligible"] == "NO"


@prod
def test_production_brandenburg_has_no_geometry_and_no_uncertainty():
    b = pd.read_csv(H / "brandenburg_georeference_audit.csv")
    assert pd.isna(b.iloc[0]["positional_uncertainty_km"])
    assert len(pd.read_csv(H / "brandenburg_map_gcps.csv")) == 0
    c = pd.read_csv(H / "brandenburg_continuity_audit.csv")
    assert c.iloc[0]["continuity_status"] == "NOT_ESTABLISHED"
    import geopandas as gpd

    f = gpd.read_parquet(H / "historical_boundary_features.parquet")
    # MAPGEN-021 added two British Isles landmass features. The intent
    # here is that no BRANDENBURG feature exists, so assert that directly.
    assert not f["historical_subject_id"].str.contains(
        "brandenburg", case=False, na=False).any(),         "no Brandenburg feature may exist yet"


@prod
def test_production_canonical_untouched_by_this_stage():
    c = pd.read_csv(SD / "territorial_control.csv")
    from _production_baseline import strip_island_production
    c = strip_island_production(c)
    assert len(c) == 1614
    v = c["control_status"].value_counts().to_dict()
    assert v["CONTROLLED"] == 697 and v["UNRESOLVED"] == 917


@prod
def test_production_coverage_unit_opened_as_unknown():
    cov = pd.read_csv(SD / "political_coverage.csv")
    row = cov[cov["coverage_unit_id"] == "region_brandenburg_1756_pilot"]
    assert len(row) == 1
    assert row.iloc[0]["control_coverage_status"] == "UNASSESSED"
    # MAPGEN-017 acquired the BnF copy, so the SOURCE status advanced.
    # The CONTROL coverage is what must not move: an acquired raster
    # is not a resolved territory.
    assert row.iloc[0]["source_evidence_status"] in (
        "SOURCE_IDENTIFIED_NOT_ACQUIRED", "SOURCE_ACQUIRED",
        "GEOREFERENCED", "GEOREFERENCE_PROVISIONAL", "GEOREFERENCED_VALIDATED")
    assert (cov["control_coverage_status"] == "COMPLETE").sum() == 0


@prod
def test_production_weimar_evidence_levels_are_separated():
    u = pd.read_csv(H / "weimar_eisenach_model_evidence_update.csv",
                    keep_default_na=False, na_values=[""])
    levels = set(u["concept_level"])
    assert {"TERRITORIAL_ACQUISITION_AND_NAME", "ADMINISTRATION",
            "DYNASTIC_OR_COLLECTIVE_NAME", "CONSTITUTIONAL"} <= levels
    gap = u[u["evidence_type"] == "NOT_OBTAINED"]
    assert len(gap) == 1 and gap.iloc[0]["confidence"] == "UNKNOWN"
    dec = u[u["evidence_type"] == "DECISION"].iloc[0]
    assert "TWO_DISTINCT_ACTORS_IN_PERSONAL_UNION" in dec["outcome"]
    assert "umbrella_dynastic_or_collective_name" in dec["outcome"]
