"""MAPGEN-028 — a bigger plate, and the ways a bigger plate could lie.

Three tests carry this stage. The first is that Portugal's growth is a
MEASUREMENT and not a loosened threshold: the uncertainty that produced it
is the p95 over points the fit never saw, and it is the number the feature
actually carries. The second is that no anchor rests on a symbol the stated
rule excludes — a vignette, a fortification plan, a letter of the name. The
third is that Spain, which this stage was told not to touch, did not move
by a single hex, including the 1,304 hexes this binding would have given it.

The rest guard the specific ways a two-sheet georeference goes wrong:
crossing a longitude tick with a latitude tick to manufacture a pixel,
fitting one sheet to the other, averaging a line across the seam or across
two disagreeing sources, quietly overwriting the older feature, or shipping
a review package that is another copy of the canonical tables.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

H = Path("data/historical")
SD = Path("data/scenarios/seven_years_war_1756_08_01")
R = Path("reviews/MAPGEN-028")
EU = Path("output/europe_foundation_20260811/europe_hex_coverage.parquet")
SPAIN_SP, PORTUGAL_SP = "sp_b622a2799f94", "sp_fef06587fead"
V2_FEATURE, V3_FEATURE = "hbf_7ed17b927930", "hbf_60dcae454432"
GSID_1751 = "hsrc_c61726597ef3"
prod = pytest.mark.skipif(not (SD / "territorial_control.csv").exists(),
                          reason="no production data")


def _rd(p):
    return pd.read_csv(p, keep_default_na=False, na_values=[])


@pytest.fixture(scope="module")
def obs():
    return _rd(H / "portugal_1751_observations.csv")


@pytest.fixture(scope="module")
def cons():
    return _rd(H / "portugal_1751_1d_constraints.csv")


@pytest.fixture(scope="module")
def transform():
    return json.loads((H / "portugal_1751_transform.json").read_text(
        encoding="utf-8"))


@pytest.fixture(scope="module")
def canon():
    return pd.read_csv(SD / "territorial_control.csv",
                       keep_default_na=False, na_values=[""])


# ---------------------------------------------------------------------------
# the three rules everything else rests on
# ---------------------------------------------------------------------------
def test_portugals_gain_is_a_measurement_not_a_threshold(transform):
    """12.33 km is a p95 of residuals at points the fit never saw, and it
    is the number the feature carries. If a later stage ever grows Portugal
    by moving this number instead, this is where it shows."""
    import geopandas as gpd
    m = pd.read_csv(H / "portugal_1751_metric_separation.csv")
    used = m[m.used_for_production_uncertainty == "YES"]
    assert len(used) == 1
    assert used.iloc[0].metric_set == "ALL_NONFIT"
    assert used.iloc[0].statistically_blind == "NO"
    assert abs(float(used.iloc[0].p95_km)
               - transform["positional_uncertainty_km"]) < 0.01
    # strictly better than the plate MAPGEN-026 used
    assert transform["positional_uncertainty_km"] < 34.61
    f = gpd.read_parquet(H / "historical_boundary_features.parquet")
    v3 = f[f.boundary_feature_id == V3_FEATURE]
    assert len(v3) == 1
    assert abs(float(v3.iloc[0].positional_uncertainty_km)
               - transform["positional_uncertainty_km"]) < 0.01
    assert v3.iloc[0].geometry_status \
        == "SAFE_INTERIOR_SUBSET_OF_AUTHORISED_EXTENT"
    assert v3.iloc[0].notes.startswith("NOT the crown's boundary")


def test_no_anchor_rests_on_a_symbol_the_rule_excludes(obs):
    tax = _rd(H / "portugal_1751_anchor_taxonomy.csv")
    eligible = set(tax.loc[tax.eligible == "YES", "symbol_class"])
    assert eligible == {"PLAIN_CIRCLE", "CITY_SIGN_CIRCLE"}
    assert set(obs.symbol_class) <= eligible
    for banned in ("PICTORIAL_TOWN_VIGNETTE", "FORTIFICATION_PLAN",
                   "LETTERING"):
        assert (tax.loc[tax.symbol_class == banned, "eligible"]
                == "NO").all()
    # the 1762 sheet stays refused and supplies nothing
    role = _rd(H / "portugal_1751_source_role.csv")
    assert role.iloc[0].may_supply_control_points == "NO"
    assert role.iloc[0].may_supply_frontier_geometry == "NO"
    assert role.iloc[0].rule_invented_for_vignettes == "NO"


@prod
def test_spain_did_not_move(canon):
    es = canon[(canon.controller_scenario_polity_id == SPAIN_SP)
               & (canon.territorial_target_type == "TERRESTRIAL_HEX")]
    assert len(es) == 5431
    rv = pd.read_csv(SD / "territorial_control_revision_log.csv",
                     keep_default_na=False, na_values=[""])
    mine = rv[rv.reason.str.contains("Portugal safe interior v3", na=False)]
    assert len(mine) > 0
    assert not (mine.new_controller == SPAIN_SP).any()
    assert not (mine.old_controller == SPAIN_SP).any()
    # and every row it did take was unowned or already Portugal's
    assert set(mine.old_controller.fillna("")) <= {"", PORTUGAL_SP}


# ---------------------------------------------------------------------------
# the specific ways a two-sheet georeference goes wrong
# ---------------------------------------------------------------------------
def test_a_graduation_stroke_is_never_crossed_with_another(cons, transform,
                                                           obs):
    """MAPGEN-018R disqualified crossing a longitude tick with a latitude
    tick to manufacture a pixel. Nothing here revives it."""
    assert set(cons.dimensionality) == {"KNOWN_LONGITUDE_ONLY",
                                        "KNOWN_LATITUDE_ONLY"}
    assert (cons.crossed_with_another_stroke == "NO").all()
    assert transform["synthetic_graticule_intersections"] == 0
    # the three counts are reported separately and add up
    assert transform["n_true_2d_points"] == len(obs)
    assert transform["n_longitude_1d_constraints"] == int(
        (cons.axis == "lon").sum())
    assert transform["n_latitude_1d_constraints"] == int(
        (cons.axis == "lat").sum())
    # a 1D constraint is never counted as a control point
    assert transform["n_true_2d_points"] < len(cons)


def test_the_sheets_are_never_fitted_to_each_other(transform):
    assert transform["sheets_georeferenced_separately"]
    assert not transform["sheets_ever_fitted_to_each_other"]
    assert not transform["images_ever_merged_before_fitting"]
    assert set(transform["sheets"]) == {"N", "S"}
    for sh in ("N", "S"):
        s = transform["sheets"][sh]
        assert s["n_fit"] > 0 and s["n_model_selection"] > 0 \
            and s["n_blind"] > 0
        assert not s["jacobian"]["folding"]
    seam = pd.read_csv(H / "portugal_1751_sheet_overlap_validation.csv")
    assert len(seam) >= 4
    assert (seam.fitted_across_the_seam == "NO").all()
    assert (seam.averaged_line_drawn == "NO").all()
    # the two independent answers agree to within the uncertainty
    assert seam.disagreement_m.max() / 1000 <= \
        transform["positional_uncertainty_km"] + 2.5


def test_the_model_selection_holdout_is_not_called_blind():
    m = pd.read_csv(H / "portugal_1751_metric_separation.csv")
    assert set(m.metric_set) == {"FIT_CONSTRAINT",
                                 "MODEL_SELECTION_HOLDOUT",
                                 "BLIND_VALIDATION", "ALL_NONFIT"}
    assert (m[m.metric_set == "MODEL_SELECTION_HOLDOUT"]
            .statistically_blind == "NO").all()
    assert (m[m.metric_set == "BLIND_VALIDATION"]
            .statistically_blind == "YES").all()
    cmp_ = pd.read_csv(H / "portugal_1751_model_comparison.csv")
    fitted = cmp_[cmp_.status == "FITTED"]
    assert {"AFFINE", "PROJECTIVE", "POLYNOMIAL_2"} <= set(fitted.model)
    assert int(fitted.selected.sum()) == 2
    # complexity is never rewarded on fit residuals: the selected model is
    # not the one with the best FIT rms on either sheet
    for sh in ("N", "S"):
        s = fitted[fitted.sheet == sh]
        best_fit = s.loc[s.fit_rms_m.idxmin(), "model"]
        assert not bool(s.loc[s.model == best_fit, "selected"].iloc[0])


def test_a_compartment_that_spans_the_frontier_is_refused():
    """The plate's wash does not close everywhere. Where it does not, the
    compartment is refused entire rather than trimmed to taste."""
    comp = _rd(H / "portugal_1751_compartment_audit.csv")
    gaps = _rd(H / "portugal_frontier_gap_audit.csv")
    kept = comp[comp.verdict == "PORTUGAL"]
    assert len(kept) > 10
    assert (kept.spanish_places == "").all()
    assert (kept.portuguese_places != "").all()
    assert (comp.loc[comp.verdict != "PORTUGAL", "claimed"] == "NO").all()
    mixed = comp[comp.verdict == "MIXED_EVIDENCE"]
    assert len(mixed) >= 1
    assert (gaps.action == "COMPARTMENT_REFUSED").all()
    assert (gaps.trimmed_to_fit == "NO").all()
    assert (gaps.averaged_line_drawn == "NO").all()
    # a Spanish town inside it is what caught it
    assert (mixed.spanish_places.str.len() > 3).all()


def test_the_older_feature_is_retained_not_overwritten():
    """v3 need not contain v2, but v2 may not be silently dropped."""
    import geopandas as gpd
    f = gpd.read_parquet(H / "historical_boundary_features.parquet")
    assert V2_FEATURE in set(f.boundary_feature_id)
    assert V3_FEATURE in set(f.boundary_feature_id)
    v2 = f[f.boundary_feature_id == V2_FEATURE].iloc[0]
    assert abs(float(v2.positional_uncertainty_km) - 34.61) < 0.01
    snap = _rd(H / "historical_snapshot_features_1756_08_01.csv")
    both = snap[snap.boundary_feature_id.isin([V2_FEATURE, V3_FEATURE])]
    assert len(both) == 2
    assert (both.production_authorised.astype(str) == "True").all()
    s = pd.read_csv(H / "portugal_safe_interior_v3.csv")
    assert s.iloc[0].silent_overwrite == "NO"
    assert s.iloc[0].previous_version_retained == "YES"
    assert float(s.iloc[0].v2_area_lost_km2_3857) > 0
    assert float(s.iloc[0].overlap_with_spain_safe_km2_3857) < 1e-3


def test_the_two_plates_disagree_and_are_not_averaged():
    x = _rd(H / "portugal_cross_source_comparison_v2.csv")
    assert (x.status == "PERFORMED").all()
    assert (x.averaged == "NO").all()
    assert (x.source_a == GSID_1751).all()
    assert (x.source_b == "hsrc_4c13f0498990").all()
    assert (x.verdict == "SOURCES_DISAGREE").any()
    # MAPGEN-027 recorded this comparison as NOT_PERFORMED and handed it on
    old = pd.read_csv(H / "portugal_cross_source_comparison.csv")
    assert str(old.iloc[0].status) == "NOT_PERFORMED"
    assert str(old.iloc[0].handed_to) == "MAPGEN-028"


def test_the_1749_pair_does_not_inflate_the_source_count():
    v = _rd(H / "portugal_1751_state_verdict.csv")
    a = _rd(H / "portugal_1751_state_audit.csv")
    assert v.iloc[0].relation == "DERIVED"
    assert int(v.iloc[0].counts_as_independent_sources) == 1
    assert v.iloc[0].corroboration_eligible == "NO"
    assert (a.loc[a.axis == "PLATE_SIZE",
                  "consistent_with_same_plate"] == "NO").all()
    lin = _rd(H / "historical_source_lineage.csv")
    assert (lin.loc[lin.global_source_id == "hsrc_c4de194d088b",
                    "corroboration_eligible"] == "NO").all()
    reg = _rd(H / "portugal_1751_map_source_registry.csv")
    assert len(reg) == 4
    assert reg.sha256.str.len().eq(64).all()
    assert (reg.gitignored == "YES").all()
    assert reg.rights.str.contains("CC BY 4.0").all()


def test_the_prime_meridian_is_solved_for_not_assumed():
    pm = pd.read_csv(H / "portugal_1751_prime_meridian_audit.csv")
    assert len(pm) >= 5
    mean = pm[pm.estimator == "MEAN_OF_FOUR"].iloc[0]
    assert abs(float(mean.difference_deg)) < 0.05
    assert mean.applied_to_production == "NO"
    assert "graduation" in str(mean.derived_from)
    c = _rd(H / "historical_prime_meridian_contract.csv")
    row = c[c.map_source_id == GSID_1751]
    assert len(row) == 1
    assert row.iloc[0].prime_meridian_name == "EMPIRICAL_PLATE_OFFSET"


# ---------------------------------------------------------------------------
# production, and the package
# ---------------------------------------------------------------------------
@prod
def test_no_ocean_hex_is_owned_through_the_new_interior(canon):
    hx = pd.read_parquet(EU, columns=["hex_id", "is_terrestrial_hex"])
    terr = set(hx.loc[hx.is_terrestrial_hex, "hex_id"])
    pt = canon[canon.controller_scenario_polity_id == PORTUGAL_SP]
    hexes = pt[pt.territorial_target_type == "TERRESTRIAL_HEX"]
    assert set(hexes.territorial_target_id) <= terr
    frags = pt[pt.territorial_target_type == "LAND_FRAGMENT"]
    assert len(frags) >= 3
    assert not (set(frags.territorial_target_id) & terr)


@prod
def test_the_review_package_is_a_reference_not_a_copy():
    ref = json.loads((R / "canonical_snapshot_reference.json").read_text(
        encoding="utf-8"))
    assert len(ref["tables"]) >= 4
    for name, t in ref["tables"].items():
        assert len(t["sha256"]) == 64
        assert t["rows"] > 0
        assert not (R / name).exists(), \
            f"{name} is copied into the package as well as referenced"
    delta = pd.read_csv(R / "territorial_control_delta.csv")
    rv = pd.read_csv(SD / "territorial_control_revision_log.csv",
                     keep_default_na=False, na_values=[""])
    mine = rv[rv.new_promotion_id == ref["promotion_id"]]
    # the delta must carry BOTH kinds: an insert leaves no revision-log row,
    # so a delta built from the log alone would hide two fifths of the change
    assert set(delta.change) == {"INSERTED", "REVISED"}
    assert int((delta.change == "REVISED").sum()) == len(mine) > 0
    assert int((delta.change == "INSERTED").sum()) > 0
    # and the whole package stays small
    total = sum(p.stat().st_size for p in R.iterdir() if p.is_file())
    assert total < 5 * 1024 * 1024, f"review package is {total} bytes"


@prod
def test_every_gate_passed():
    v = pd.read_csv(R / "validation.csv")
    assert len(v) == 49
    assert bool(v["pass"].all()), v[~v["pass"]].to_string()


@prod
def test_the_summary_reports_what_actually_happened():
    s = pd.read_csv(R / "summary.csv")
    d = dict(zip(s.metric.astype(str), s.value.astype(str)))
    assert d["outcome"] == "FULL"
    assert int(d["portugal_controlled_before"]) == 124
    assert int(d["portugal_controlled"]) > 124
    assert int(d["spain_controlled"]) == int(d["spain_controlled_before"])
    assert float(d["positional_uncertainty_km"]) == 12.33
    assert float(d["mapgen026_uncertainty_km"]) == 34.61
    assert int(d["true_2d_points"]) >= 24
    assert int(d["synthetic_graticule_intersections"]) == 0
    assert int(d["compartments_refused_mixed"]) >= 1
    assert d["v2_feature_retained"] == "YES"
    assert int(d["review_package_canonical_copies"]) == 0
