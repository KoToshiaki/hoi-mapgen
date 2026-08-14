"""MAPGEN-019 — rebuilding the Brandenburg georeference from observations.

These tests protect the distinctions the MAPGEN-018 failure turned on:
an observation is not a fit role, a reconstructed grid point is not an
observation, a provisional p90 is not a final accuracy, and a model that
fits better is not thereby a better model.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mapgen.historical_georef_rebuild_pipeline import (
    EXCLUDED_FROM_FIT, FIELD, INSET_ORIGIN, MODELS, PRIOR_TRANSFORM_POINTS,
    PROVISIONAL_P90_KM, VALIDATED, freeze_split, plate_coords)
from mapgen.historical_georeference import (PRIME_MERIDIANS,
                                            design_condition, fit_transform,
                                            jacobian_stability, residuals_m)

H = Path("data/historical")


@pytest.fixture(scope="module")
def points():
    return pd.read_csv(H / "brandenburg_observed_feature_points.csv",
                       keep_default_na=False, na_values=[""])


@pytest.fixture(scope="module")
def graticule():
    return pd.read_csv(H / "brandenburg_plate_graticule_observations.csv")


@pytest.fixture(scope="module")
def split(points):
    df, moves = freeze_split(points.drop(
        columns=[c for c in ("split_role", "split_reason")
                 if c in points.columns]))
    return df, moves


# ---------------------------------------------------------------------------
# observation semantics
# ---------------------------------------------------------------------------
def test_observed_correspondence_is_not_a_fit_role(split):
    """An observation and a production fit role are different facts.

    MAPGEN-018R correctly reported zero production GCPs. Writing that as
    'zero observed points' would have been false: five 2-D correspondences
    already existed. The columns must stay separable.
    """
    df, _ = split
    assert (df["observation_class"] == "OBSERVED_FEATURE_POINT").all()
    assert (df["pixel_coordinate_directly_observed"] == "YES").all()
    fit = df[df["split_role"] == "FIT"]
    assert 0 < len(fit) < len(df)


def test_the_five_prior_points_are_retained_and_re_measured(points):
    prior = points[points["discovered_using_prior_transform"] == "YES"]
    assert set(prior["reference_feature_name"]) == PRIOR_TRANSFORM_POINTS
    assert (prior["selection_method"]
            == "PRIOR_TRANSFORM_WINDOW_MAPGEN018R").all()
    assert (prior["chosen_anchor"] == "SYMBOL_CIRCLE_CENTRE").all()


def test_map_first_selection_is_recorded_and_dominant(points):
    mapfirst = points[points["selection_method"] == "MAP_FIRST_TILE_SCAN"]
    assert len(mapfirst) >= 20
    assert len(mapfirst) > len(points) - len(mapfirst)


def test_every_point_is_anchored_on_a_symbol_not_on_label_text(points):
    assert (points["chosen_anchor"] == "SYMBOL_CIRCLE_CENTRE").all()
    assert points["symbol_bbox"].str.startswith("[").all()
    assert (points["symbol_position_uncertainty_m"] > 0).all()


def test_no_point_lies_inside_the_supplement_inset(points):
    """The Vieille Marche / Prignitz supplement has its own graticule."""
    inside = points[(points["pixel_x"] >= INSET_ORIGIN[0])
                    & (points["pixel_y"] >= INSET_ORIGIN[1])]
    assert inside.empty
    assert (points["inside_inset"] == "NO").all()


def test_points_lie_inside_the_engraved_map_field(points):
    assert points["pixel_x"].between(FIELD[0], FIELD[2]).all()
    assert points["pixel_y"].between(FIELD[1], FIELD[3]).all()


def test_minimum_count_and_spatial_distribution(points):
    assert len(points) >= 20
    by_zone = points.groupby("zone").size()
    assert set(by_zone.index) == {"NW", "NE", "SW", "SE", "centre"}
    assert by_zone.min() >= 3


# ---------------------------------------------------------------------------
# the split
# ---------------------------------------------------------------------------
def test_three_way_split_is_disjoint(split):
    df, _ = split
    sets = {r: set(df.loc[df["split_role"] == r, "point_id"])
            for r in ("FIT", "MODEL_SELECTION_HOLDOUT", "BLIND_VALIDATION")}
    assert not sets["FIT"] & sets["MODEL_SELECTION_HOLDOUT"]
    assert not sets["FIT"] & sets["BLIND_VALIDATION"]
    assert not sets["MODEL_SELECTION_HOLDOUT"] & sets["BLIND_VALIDATION"]
    assert len(sets["BLIND_VALIDATION"]) >= 4


def test_split_is_deterministic(points):
    a, _ = freeze_split(points)
    b, _ = freeze_split(points.sample(frac=1.0, random_state=7))
    pd.testing.assert_series_equal(
        a.set_index("point_id")["split_role"].sort_index(),
        b.set_index("point_id")["split_role"].sort_index())


def test_split_covers_every_zone(split):
    df, _ = split
    t = pd.crosstab(df["zone"], df["split_role"])
    assert (t.get("FIT", pd.Series(dtype=int)) > 0).all()
    blind = df[df["split_role"] == "BLIND_VALIDATION"]
    assert blind["zone"].nunique() >= 4


def test_prior_transform_points_can_never_be_blind_validation(split):
    """A point found inside a window the old transform predicted cannot
    blindly test a new transform."""
    df, moves = split
    blind = df[df["split_role"] == "BLIND_VALIDATION"]
    assert not set(blind["reference_feature_name"]) & PRIOR_TRANSFORM_POINTS
    for m in moves:
        assert m["applied_before_any_fit"] == "YES"
        assert m["rule"] == "PRIOR_TRANSFORM_POINT_CANNOT_BE_BLIND"


def test_identity_offset_point_is_excluded_from_every_set(split):
    df, _ = split
    row = df[df["reference_feature_name"].isin(EXCLUDED_FROM_FIT)]
    assert len(row) == 1
    assert row.iloc[0]["split_role"] == "EXCLUDED"
    assert "Neustadt" in row.iloc[0]["split_reason"]


# ---------------------------------------------------------------------------
# the reconstructed grid stays out
# ---------------------------------------------------------------------------
def test_reconstructed_grid_points_are_not_observations(points):
    grid = pd.read_csv(H / "brandenburg_reconstructed_grid_points.csv")
    assert len(grid) == 18
    assert (grid["counts_as_production_gcp"] == "NO").all()
    assert (grid["pixel_coordinate_directly_observed"] == "NO").all()
    shared = (set(zip(grid["pixel_x"].round(1), grid["pixel_y"].round(1)))
              & set(zip(points["pixel_x"].round(1),
                        points["pixel_y"].round(1))))
    assert not shared


def test_border_ticks_are_one_dimensional_only(graticule):
    assert len(graticule) == 18
    assert graticule["border"].nunique() == 4
    assert (graticule["eligible_as_2d_gcp"] == "NO").all()
    assert (graticule["second_coordinate_known"] == "NO").all()


def test_all_four_borders_were_measured_and_meridians_converge(graticule):
    """MAPGEN-018 measured two borders and could not see the projection."""
    top = graticule[(graticule.kind == "MERIDIAN_TICK")
                    & (graticule.border == "TOP")]["pixel_value"]
    bot = graticule[(graticule.kind == "MERIDIAN_TICK")
                    & (graticule.border == "BOTTOM")]["pixel_value"]
    tw = np.diff(np.sort(top.values)).mean()
    bw = np.diff(np.sort(bot.values)).mean()
    assert bw > tw * 1.05, "meridians must be shown to converge northward"


# ---------------------------------------------------------------------------
# prime meridian
# ---------------------------------------------------------------------------
def test_prime_meridian_is_separable_off_the_plate_graticule(split,
                                                             graticule):
    """Scored through a FITTED transform the candidates are identical,
    because an affine absorbs a constant longitude offset. Read off the
    engraved graduations they are not.

    Scored on the same pool the pipeline uses: fit + model-selection, so the
    blind set stays untouched.
    """
    from pyproj import Geod
    df, _ = split
    pool = df[df["split_role"].isin(["FIT", "MODEL_SELECTION_HOLDOUT"])]
    geod = Geod(ellps="WGS84")
    plon, plat = plate_coords(graticule, pool.pixel_x, pool.pixel_y)
    med = {}
    for pm, off in PRIME_MERIDIANS.items():
        _, _, d = geod.inv(pool.reference_lon.values,
                           pool.reference_lat.values, plon + off, plat)
        med[pm] = float(np.median(np.abs(d)))
    best = min(med, key=med.get)
    assert best == "FERRO_20W_OF_PARIS"
    other = min(v for k, v in med.items() if k != best)
    assert other > med[best] * 40


def test_blind_points_took_no_part_in_meridian_selection(split):
    df, _ = split
    pool = df[df["split_role"].isin(["FIT", "MODEL_SELECTION_HOLDOUT"])]
    blind = df[df["split_role"] == "BLIND_VALIDATION"]
    assert not set(pool["point_id"]) & set(blind["point_id"])


# ---------------------------------------------------------------------------
# model selection
# ---------------------------------------------------------------------------
def test_polynomial_fits_best_and_generalises_worst(split):
    """The whole point of a holdout. A rubber sheet must not be allowed to
    iron the plate's historical distortion into a fictitious accuracy."""
    df, _ = split
    fit = df[df["split_role"] == "FIT"]
    hold = df[df["split_role"] == "MODEL_SELECTION_HOLDOUT"]
    fit_rms, hold_rms = {}, {}
    for m in MODELS:
        t = fit_transform(m, fit.pixel_x, fit.pixel_y,
                          fit.reference_lon, fit.reference_lat)
        fit_rms[m] = residuals_m(t, fit.pixel_x, fit.pixel_y,
                                 fit.reference_lon, fit.reference_lat)
        fit_rms[m] = float(np.sqrt((fit_rms[m] ** 2).mean()))
        r = residuals_m(t, hold.pixel_x, hold.pixel_y,
                        hold.reference_lon, hold.reference_lat)
        hold_rms[m] = float(np.sqrt((r ** 2).mean()))
    assert fit_rms["POLYNOMIAL_2"] == min(fit_rms.values())
    assert hold_rms["POLYNOMIAL_2"] == max(hold_rms.values())


def test_selection_rule_picks_the_simplest_sufficient_model(split):
    df, _ = split
    fit = df[df["split_role"] == "FIT"]
    hold = df[df["split_role"] == "MODEL_SELECTION_HOLDOUT"]
    rms = {}
    for m in MODELS:
        t = fit_transform(m, fit.pixel_x, fit.pixel_y,
                          fit.reference_lon, fit.reference_lat)
        r = residuals_m(t, hold.pixel_x, hold.pixel_y,
                        hold.reference_lon, hold.reference_lat)
        rms[m] = float(np.sqrt((r ** 2).mean()))
    best = min(rms.values())
    within = [m for m in MODELS if rms[m] <= best * 1.10]
    assert within[0] == "AFFINE"


def test_projective_conditioning_is_reported(split):
    """An ill-conditioned solve must never pass as a better model."""
    df, _ = split
    fit = df[df["split_role"] == "FIT"]
    cond = {m: design_condition(m, fit.pixel_x, fit.pixel_y,
                                fit.reference_lon, fit.reference_lat)
            for m in MODELS}
    assert cond["AFFINE"] < cond["PROJECTIVE"] < cond["POLYNOMIAL_2"]


def test_selected_transform_does_not_fold_the_map(split):
    df, _ = split
    fit = df[df["split_role"] == "FIT"]
    t = fit_transform("AFFINE", fit.pixel_x, fit.pixel_y,
                      fit.reference_lon, fit.reference_lat)
    j = jacobian_stability(t, *FIELD)
    assert not j["folding"]
    assert j["scale_ratio"] < 1.5


# ---------------------------------------------------------------------------
# uncertainty and status
# ---------------------------------------------------------------------------
def test_provisional_p90_cannot_masquerade_as_final_uncertainty():
    audit = pd.read_csv(H / "brandenburg_bnf_georeference_audit.csv")
    sel = audit[audit["selected"].astype(bool)].iloc[0]
    assert float(sel["provisional_validation_p90_km"]) == PROVISIONAL_P90_KM
    assert float(sel["positional_uncertainty_km"]) != PROVISIONAL_P90_KM
    assert "provisional_validation_p90_km" in audit.columns
    assert "corrected_uncertainty_km" not in audit.columns


def test_final_uncertainty_is_built_from_blind_validation():
    audit = pd.read_csv(H / "brandenburg_bnf_georeference_audit.csv")
    sel = audit[audit["selected"].astype(bool)].iloc[0]
    unc = float(sel["positional_uncertainty_km"])
    assert unc >= float(sel["blind_p90_km"])
    assert int(sel["blind_n"]) >= 4


def test_georeference_status_is_validated_in_registry_and_transform():
    import json
    t = json.loads((H / "brandenburg_bnf_transform.json").read_text(
        encoding="utf-8"))
    assert t["georeference_status"] == VALIDATED
    assert t["fitted_on"] == "OBSERVED_FEATURE_POINTS"
    assert t["prime_meridian"] == "FERRO_20W_OF_PARIS"
    reg = pd.read_csv(H / "historical_source_registry.csv")
    row = reg[reg["global_source_id"] == "hsrc_d22d155bbd4a"].iloc[0]
    assert row["georeference_status"] == VALIDATED


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------
def test_blha_acquisition_metadata_is_complete_and_on_disk():
    blha = pd.read_csv(H / "brandenburg_blha_copy_audit.csv",
                       keep_default_na=False, na_values=[""])
    got = blha[blha["raster_acquired"] == "YES"]
    assert len(got) == 1
    r = got.iloc[0]
    assert r["licence"] == "CC0 1.0 Universell"
    assert r["licence_verified_at_source"] == "YES"
    assert int(r["raster_width_px"]) == 7582
    assert int(r["raster_height_px"]) == 6436
    assert len(str(r["raster_sha256"])) == 64
    assert str(r["download_utc"]).endswith("Z")


def test_blha_duplicate_relation_counts_one_source_not_two():
    rel = pd.read_csv(H / "brandenburg_blha_copy_relation_audit.csv")
    assert len(rel) == 1
    r = rel.iloc[0]
    assert r["same_work"] == "YES"
    assert r["classification"] == "UNRESOLVED"
    assert r["pixel_comparison_performed"] == "NO"
    assert int(r["counts_as_independent_sources"]) == 1


def test_unverified_copy_is_reported_as_absence_not_as_refusal():
    blha = pd.read_csv(H / "brandenburg_blha_copy_audit.csv",
                       keep_default_na=False, na_values=[""])
    row = blha[blha["archival_signature"] == "AKS 1132 A"].iloc[0]
    assert row["verified_at_source"] == "YES"
    assert row["raster_acquired"] == "NO"
    assert "no digitisation" in str(row["notes"]).lower()


def test_novum_corpus_entries_are_pinpointed():
    pol = pd.read_csv(H / "brandenburg_1756_political_evidence.csv",
                      keep_default_na=False, na_values=[""])
    assert len(pol) >= 3
    assert (pol["status"] == "OBTAINED").all()
    assert pol["document_date"].str.startswith("1756").all()
    assert pol["scan_number"].notna().all()
    assert (pol["printed_columns"].str.len() > 0).all()
    assert pol["exact_quotation_locator"].str.contains("bsb11399173").all()


def test_administrative_evidence_is_never_boundary_evidence():
    pol = pd.read_csv(H / "brandenburg_1756_political_evidence.csv")
    assert set(pol["evidence_role"]) <= {"POLITICAL_CONTROL",
                                         "ADMINISTRATIVE_SCOPE"}


def test_pomerania_is_documented_as_separate_from_brandenburg():
    pol = pd.read_csv(H / "brandenburg_1756_political_evidence.csv")
    pom = pol[pol["territory_named"].str.contains("Pomerania")]
    assert len(pom) >= 1
    assert "Pommersche" in pom.iloc[0]["administrative_units_named"]


def test_all_six_segments_were_individually_researched():
    seg = pd.read_csv(H / "brandenburg_boundary_segment_continuity.csv")
    # MAPGEN-020 split each frontier into named subsegments and renamed the
    # locator column; the requirement that every frontier be researched on
    # its own is unchanged.
    assert seg["segment_id"].nunique() >= 6
    assert (seg["individually_researched"] == "YES").all()
    assert (seg["change_evidence"].str.len() > 40).all()
    assert (seg["exact_locator"].str.len() > 10).all()


def test_searched_but_unresolved_is_distinguishable_from_unsearched():
    seg = pd.read_csv(H / "brandenburg_boundary_segment_continuity.csv",
                      keep_default_na=False, na_values=[""])
    for r in seg.itertuples():
        assert r.territorial_political_continuity
        assert r.boundary_position_continuity
        assert r.change_evidence and len(r.change_evidence) > 40
        assert r.confidence in {"HIGH", "MEDIUM", "LOW"}


# ---------------------------------------------------------------------------
# what must NOT have happened
# ---------------------------------------------------------------------------
def test_no_geometry_was_digitised_and_no_control_promoted():
    import geopandas as gpd
    feats = gpd.read_parquet(H / "historical_boundary_features.parquet")
    assert not feats["historical_subject_id"].str.contains(
        "brandenburg", case=False, na=False).any()
    assert "hsrc_d22d155bbd4a" not in set(feats["global_source_id"])
    ass = pd.read_csv(H / "historical_evidence_assertions.csv")
    assert "hsrc_d22d155bbd4a" not in set(ass["global_source_id"])


def test_canonical_control_is_untouched():
    c = pd.read_csv("data/scenarios/seven_years_war_1756_08_01/"
                    "territorial_control.csv",
                    keep_default_na=False, na_values=[""])
    bi = set(pd.read_csv(
        "data/historical/british_isles_hex_membership_audit.csv",
        keep_default_na=False, na_values=[])["hex_id"])
    c = c[~c["territorial_target_id"].isin(bi)]
    assert len(c) == 1614
    assert int((c["control_status"] == "CONTROLLED").sum()) == 697
    assert int((c["control_status"] == "UNRESOLVED").sum()) == 917
