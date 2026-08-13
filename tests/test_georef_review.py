# -*- coding: utf-8 -*-
"""MAPGEN-018R — a reconstructed grid is not a set of control points.

The rules defended here: a Cartesian product of border ticks is not
observed control, a fit and its holdout may not share a primitive
measurement, a one-dimensional tick is not a two-dimensional GCP, one
check point cannot set a global uncertainty, and a provisional transform
may not authorise geometry.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

DATA = Path("data")
H = DATA / "historical"
SD = DATA / "scenarios" / "seven_years_war_1756_08_01"
PROVISIONAL = "GEOREFERENCE_PROVISIONAL_RECONSTRUCTED_GRID"
PROD = (H / "brandenburg_reconstructed_grid_points.csv").exists()
prod = pytest.mark.skipif(not PROD, reason="MAPGEN-018R data not built")


def _observed(point):
    if point.get("observation_type", "").startswith("CARTESIAN_PRODUCT"):
        return False
    return bool(point.get("pixel_coordinate_directly_observed") == "YES")


def test_cartesian_product_point_is_not_observed():
    p = {"observation_type": "CARTESIAN_PRODUCT_OF_BORDER_OBSERVATIONS",
         "pixel_coordinate_directly_observed": "NO"}
    assert not _observed(p)
    assert _observed({"observation_type": "DIRECT_INTERSECTION",
                      "pixel_coordinate_directly_observed": "YES"})


def _primitive_count(n_meridians, n_parallels):
    return n_meridians + n_parallels


def test_nine_measurements_do_not_become_eighteen_points():
    assert _primitive_count(6, 3) == 9
    assert 6 * 3 == 18
    assert _primitive_count(6, 3) < 6 * 3


def _split_ok(fit, hold):
    fp = {p for r in fit for p in r["primitives"]}
    hp = {p for r in hold for p in r["primitives"]}
    if fp & hp:
        raise ValueError("fit and holdout share primitive observations: "
                         f"{sorted(fp & hp)}")
    return True


def test_fit_and_holdout_may_not_share_a_primitive():
    fit = [{"primitives": {"mer_31", "par_55"}},
           {"primitives": {"mer_32", "par_54"}}]
    hold = [{"primitives": {"mer_33", "par_55"}}]
    with pytest.raises(ValueError, match="share primitive"):
        _split_ok(fit, hold)
    assert _split_ok(fit, [{"primitives": {"mer_33", "par_53"}}])


def _is_2d(tick):
    return tick.get("second_coordinate_known") == "YES"


def test_border_tick_is_one_dimensional():
    assert not _is_2d({"kind": "MERIDIAN_TICK",
                       "second_coordinate_known": "NO"})
    assert _is_2d({"kind": "INTERIOR_INTERSECTION",
                   "second_coordinate_known": "YES"})


def _global_uncertainty(residuals_km):
    if len(residuals_km) < 3:
        raise ValueError("a global uncertainty needs several spatially "
                         "distributed checks, not one")
    return round(float(np.percentile(residuals_km, 90)), 3)


def test_one_check_cannot_set_a_global_uncertainty():
    with pytest.raises(ValueError):
        _global_uncertainty([9.28])
    assert _global_uncertainty([7.6, 8.7, 9.3, 26.2, 28.6]) > 20


def _pick_meridian(cands):
    best = min(cands, key=lambda c: c["median_km"])
    rest = [c for c in cands if c is not best]
    if best["median_km"] * 50 > min(r["median_km"] for r in rest):
        return best["name"], "AMBIGUOUS"
    return best["name"], "CORROBORATED_BY_MULTIPLE_INDEPENDENT_POINTS"


def test_prime_meridian_needs_a_decisive_margin():
    cands = [{"name": "FERRO", "median_km": 9.27},
             {"name": "PARIS", "median_km": 1362.78},
             {"name": "GREENWICH", "median_km": 1206.75}]
    name, status = _pick_meridian(cands)
    assert name == "FERRO"
    assert status == "CORROBORATED_BY_MULTIPLE_INDEPENDENT_POINTS"
    close = [{"name": "A", "median_km": 9.0},
             {"name": "B", "median_km": 11.0}]
    assert _pick_meridian(close)[1] == "AMBIGUOUS"


def _may_digitise(status):
    if status != "GEOREFERENCED_VALIDATED":
        raise ValueError(f"status {status} may not authorise geometry")
    return True


def test_provisional_transform_cannot_authorise_geometry():
    with pytest.raises(ValueError):
        _may_digitise(PROVISIONAL)
    assert _may_digitise("GEOREFERENCED_VALIDATED")


def _systematic(by_quadrant):
    lo = min(by_quadrant.values())
    hi = max(by_quadrant.values())
    return hi > 2 * lo


def test_position_dependent_error_is_systematic_not_scatter():
    assert _systematic({"centre": 9.3, "SW": 7.6, "SE": 26.2, "NE": 28.6})
    assert not _systematic({"centre": 9.3, "SW": 8.6, "SE": 10.1})


@prod
def test_production_grid_points_are_reclassified():
    g = pd.read_csv(H / "brandenburg_reconstructed_grid_points.csv")
    assert len(g) == 18
    assert (g["classification"] == "RECONSTRUCTED_GRID_POINT").all()
    assert (g["counts_as_production_gcp"] == "NO").all()
    assert (g["pixel_coordinate_directly_observed"] == "NO").all()
    assert "reconstructed_grid_fit_residual_m" in g.columns
    assert "residual_m" not in g.columns


@prod
def test_production_primitive_observations_are_recorded():
    p = pd.read_csv(H / "brandenburg_border_observations.csv")
    assert len(p) == 9
    assert (p["kind"] == "MERIDIAN_TICK").sum() == 6
    assert (p["kind"] == "PARALLEL_TICK").sum() == 3
    assert (p["second_coordinate_known"] == "NO").all()


@prod
def test_production_checks_expose_a_systematic_error():
    c = pd.read_csv(H / "brandenburg_independent_feature_checks.csv")
    acc = c[c["accepted"] == "YES"]
    assert len(acc) >= 5
    assert len(set(acc["quadrant"])) >= 3
    east = acc[acc["quadrant"].isin(["SE", "NE"])]["residual_km"]
    centre = acc[acc["quadrant"].isin(["centre", "SW"])]["residual_km"]
    assert east.min() > centre.max() * 2


@prod
def test_production_prime_meridian_audit_is_decisive():
    a = pd.read_csv(H / "brandenburg_prime_meridian_candidate_audit.csv")
    assert len(a) == 3
    ferro = a[a["candidate"] == "FERRO_20W_OF_PARIS"].iloc[0]
    others = a[a["candidate"] != "FERRO_20W_OF_PARIS"]
    assert ferro["median_residual_km"] < others["median_residual_km"].min()
    assert ferro["n_checks"] >= 5


@prod
def test_production_status_and_uncertainty_downgraded():
    g = pd.read_csv(H / "brandenburg_bnf_georeference_audit.csv")
    sel = g[g["selected"].astype(bool)].iloc[0]
    assert sel["status"] == PROVISIONAL
    assert sel["positional_uncertainty_km"] > 9.282
    assert "reconstructed_grid_holdout_residual_m" in g.columns
    assert "holdout_rms_m" not in g.columns


@prod
def test_production_no_geometry_from_provisional_transform():
    import geopandas as gpd

    f = gpd.read_parquet(H / "historical_boundary_features.parquet")
    assert len(f) == 3
    reg = pd.read_csv(H / "historical_source_registry.csv")
    sid = reg.loc[reg["citation_key"].str.contains("vaugondy_1751"),
                  "global_source_id"].iloc[0]
    assert sid not in set(f["global_source_id"])
    ev = pd.read_csv(H / "historical_evidence_assertions.csv")
    assert sid not in set(ev["global_source_id"])


@prod
def test_production_coverage_rolled_back():
    cov = pd.read_csv(SD / "political_coverage.csv")
    row = cov[cov["coverage_unit_id"] == "region_brandenburg_1756_pilot"]
    assert row.iloc[0]["source_evidence_status"] \
        == "GEOREFERENCE_PROVISIONAL"
    assert row.iloc[0]["control_coverage_status"] == "UNASSESSED"


@prod
def test_production_canonical_untouched():
    c = pd.read_csv(SD / "territorial_control.csv")
    assert len(c) == 1614
    v = c["control_status"].value_counts().to_dict()
    assert v["CONTROLLED"] == 697 and v["UNRESOLVED"] == 917
