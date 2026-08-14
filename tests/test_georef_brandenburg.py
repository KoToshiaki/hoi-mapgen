# -*- coding: utf-8 -*-
"""MAPGEN-018 — graticule georeference discipline for the BnF sheet.

The rules defended here: a numeral must be read before its line becomes a
control point, the holdout must not be an interpolation of its
neighbours, the simplest model wins on holdout, a prime meridian the
plate does not state must be corroborated, and uncertainty is earned per
map rather than borrowed.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

DATA = Path("data")
H = DATA / "historical"
SD = DATA / "scenarios" / "seven_years_war_1756_08_01"
PROD = (H / "brandenburg_bnf_gcps.csv").exists() and len(
    pd.read_csv(H / "brandenburg_bnf_gcps.csv")) > 0
prod = pytest.mark.skipif(not PROD, reason="MAPGEN-018 data not built")


def _gcp(value_read):
    if not value_read:
        raise ValueError("a detected graticule line without a read "
                         "numeral is not a control point")
    return True


def test_detected_line_needs_a_read_numeral():
    with pytest.raises(ValueError):
        _gcp(None)
    assert _gcp("54")


def _is_interpolation(hold_value, fit_values):
    lo = [v for v in fit_values if v < hold_value]
    hi = [v for v in fit_values if v > hold_value]
    return bool(lo and hi and min(hi) - max(lo) <= 2)


def test_holdout_should_not_be_a_simple_interpolation():
    assert _is_interpolation(33, [32, 34])
    assert not _is_interpolation(36, [31, 32, 34])


def _select(rows):
    ok = [r for r in rows if r["holdout_rms"] is not None]
    best = min(r["holdout_rms"] for r in ok)
    order = {"AFFINE": 0, "PROJECTIVE": 1, "POLYNOMIAL_2": 2}
    cand = [r for r in ok if r["holdout_rms"] <= best * 1.10]
    return sorted(cand, key=lambda r: order[r["model"]])[0]["model"]


def test_simplest_model_wins_on_holdout_not_fit():
    rows = [{"model": "AFFINE", "fit_rms": 59.9, "holdout_rms": 60.1},
            {"model": "PROJECTIVE", "fit_rms": 53.5, "holdout_rms": 64.5},
            {"model": "POLYNOMIAL_2", "fit_rms": 31.4,
             "holdout_rms": 65.3}]
    assert _select(rows) == "AFFINE"
    assert min(rows, key=lambda r: r["fit_rms"])["model"] == "POLYNOMIAL_2"


def _prime_meridian(stated_on_sheet, independent_residual_km):
    if stated_on_sheet:
        return "READ_FROM_PLATE"
    if independent_residual_km is None:
        raise ValueError("a prime meridian the plate does not state may "
                         "not be inherited without an independent check")
    if independent_residual_km > 25.0:
        raise ValueError("independent check too far to corroborate the "
                         "prime meridian")
    return "CORROBORATED_BY_INDEPENDENT_POINT"


def test_unstated_prime_meridian_needs_corroboration():
    with pytest.raises(ValueError):
        _prime_meridian(False, None)
    with pytest.raises(ValueError):
        _prime_meridian(False, 400.0)
    assert _prime_meridian(False, 9.3) == "CORROBORATED_BY_INDEPENDENT_POINT"
    assert _prime_meridian(True, None) == "READ_FROM_PLATE"


def _uncertainty(holdout_m, independent_m, line_m, digit_m):
    return round(float(np.sqrt(max(holdout_m, independent_m) ** 2
                               + line_m ** 2 + digit_m ** 2)) / 1000.0, 3)


def test_uncertainty_is_dominated_by_the_worst_real_measurement():
    u = _uncertainty(60.1, 9279.6, 168.3, 134.6)
    assert 9.2 < u < 9.4
    assert u != 9.168, "Saxony's value must not be reproduced by accident"


def _count_sources(objs):
    return len({(o["plate"], o["impression"]) for o in objs
                if o.get("identity") != "UNRESOLVED"}) or 0


def test_two_unresolved_objects_are_not_two_sources():
    objs = [{"plate": "p", "impression": "i", "identity": "UNRESOLVED"},
            {"plate": "p", "impression": "j", "identity": "UNRESOLVED"}]
    assert _count_sources(objs) == 0


def _admin_role(kind):
    if kind == "ADMINISTRATIVE_RECORD":
        return "POLITICAL_CONTROL"
    return None


def test_administrative_record_is_never_boundary_evidence():
    assert _admin_role("ADMINISTRATIVE_RECORD") == "POLITICAL_CONTROL"
    assert _admin_role("ADMINISTRATIVE_RECORD") != "BOUNDARY_POSITION"


def _may_close_polygon(segments):
    if any(s != "CONTINUITY_CONFIRMED" for s in segments):
        raise ValueError("an unresolved segment may not be closed by "
                         "guesswork to complete a polygon")
    return True


def test_unresolved_segment_cannot_close_a_polygon():
    with pytest.raises(ValueError):
        _may_close_polygon(["CONTINUITY_CONFIRMED", "UNRESOLVED"])
    assert _may_close_polygon(["CONTINUITY_CONFIRMED"] * 6)


@prod
def test_production_gcps_are_read_intersections():
    g = pd.read_csv(H / "brandenburg_bnf_gcps.csv")
    assert len(g) == 18
    assert sorted(set(g["longitude_raw"])) == [31, 32, 33, 34, 35, 36]
    assert sorted(set(g["latitude_raw"])) == [53, 54, 55]
    assert (g["reading_confidence"] == "HIGH").all()
    assert int(g["included_in_fit"].sum()) >= 12
    assert int(g["holdout"].sum()) >= 4
    assert not (g["included_in_fit"] & g["holdout"]).any()


@prod
def test_production_reconstructed_grid_residuals_are_renamed():
    """MAPGEN-018R: the 60 m figures describe a RECONSTRUCTED grid, not a
    geographic holdout, and must not be stored under a name that says
    otherwise."""
    a = pd.read_csv(H / "brandenburg_bnf_georeference_audit.csv")
    sel = a[a["selected"].astype(bool)].iloc[0]
    assert sel["model"] == "AFFINE"
    # MAPGEN-019 refitted on observed features, so the audit no longer
    # carries reconstructed-grid residuals at all. The renamed figures stay
    # with the reconstructed grid, which is where they belong.
    g = pd.read_csv(H / "brandenburg_reconstructed_grid_points.csv")
    assert "reconstructed_grid_fit_residual_m" in g.columns
    assert "residual_m" not in g.columns
    assert "reconstructed_grid_holdout_residual_m" not in a.columns
    assert "holdout_rms_m" not in a.columns
    poly = a[a["model"] == "POLYNOMIAL_2"].iloc[0]
    # a polynomial still fits better and still generalises worse
    assert poly["fit_rms_m"] < sel["fit_rms_m"]
    assert poly["hold_rms_m"] > sel["hold_rms_m"]


@prod
def test_production_uncertainty_is_map_specific():
    a = pd.read_csv(H / "brandenburg_bnf_georeference_audit.csv")
    sel = a[a["selected"].astype(bool)].iloc[0]
    # MAPGEN-018R replaced the one-point 9.282 km with a p90 over five
    # spatially distributed checks.
    assert sel["positional_uncertainty_km"] > 9.282
    assert sel["positional_uncertainty_km"] != 9.168
    # MAPGEN-019 derives the figure from blind validation and reports the
    # sampled Jacobian scale of the selected transform.
    assert sel["mean_pixel_scale_m"] > 0
    assert sel["positional_uncertainty_km"] >= sel["blind_p90_km"]


@prod
def test_production_independent_check_is_not_in_the_fit():
    c = pd.read_csv(H / "brandenburg_bnf_independent_checks.csv")
    assert len(c) == 1
    assert not bool(c.iloc[0]["included_in_fit"])
    assert c.iloc[0]["residual_m"] < 15000
    assert "GeoNames" in c.iloc[0]["reference_source"]


@prod
def test_production_georeference_authorises_nothing_yet():
    import geopandas as gpd

    reg = pd.read_csv(H / "historical_source_registry.csv")
    sid = reg.loc[reg["citation_key"].str.contains("vaugondy_1751"),
                  "global_source_id"].iloc[0]
    ev = pd.read_csv(H / "historical_evidence_assertions.csv")
    assert sid not in set(ev["global_source_id"])
    f = gpd.read_parquet(H / "historical_boundary_features.parquet")
    assert len(f) == 3 and sid not in set(f["global_source_id"])
    # MAPGEN-019 validated the transform AND established continuity, and
    # still digitised nothing. A validated transform authorises geometry;
    # it does not create it.
    seg = pd.read_csv(H / "brandenburg_boundary_segment_continuity.csv")
    assert len(seg) >= 6 and (seg["individually_researched"] == "YES").all()


@prod
def test_production_copy_state_claim_is_conservative():
    c = pd.read_csv(H / "historical_map_copy_registry.csv")
    b = c[c["copy_id"] == "copy_bnf_ge_dd_2987_3790"].iloc[0]
    assert b["copy_state"] == "COPY_CATALOGUED_1751_WITH_1751_PRIVILEGE"
    assert b["copy_state_confidence"] == "MEDIUM"


@prod
def test_production_canonical_untouched():
    c = pd.read_csv(SD / "territorial_control.csv")
    assert len(c) == 1614
    v = c["control_status"].value_counts().to_dict()
    assert v["CONTROLLED"] == 697 and v["UNRESOLVED"] == 917
