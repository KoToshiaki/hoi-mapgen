"""MAPGEN-011 unit tests — source discipline + hex binding machinery.
All political geometry here is SYNTHETIC and test-only."""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely

from mapgen.config import BBox
from mapgen.hex_grid import HexGrid
from mapgen.historical_binding import (bind_snapshot_to_hexes,
                                       check_contested_overlaps,
                                       controls_from_membership,
                                       hexification_audit,
                                       overlay_candidates_from_audit,
                                       validate_production_features)
from mapgen.historical_geometry import (make_boundary_feature_id,
                                        make_global_source_id,
                                        select_features_for_snapshot)
from mapgen.projection import bbox_to_mercator
from mapgen.scenario import (IncompleteCoverageError, load_scenario,
                             resolve_control_status)

GRID = HexGrid(flat_to_flat=6000.0)
DATA = Path("data")
SC = "seven_years_war_1756_08_01"
SNAP = "1756-08-01"

REGISTRY = pd.DataFrame([
    {"global_source_id": make_global_source_id("syn_atlas_1500"),
     "authority_level": "BOUNDARY_AUTHORITY_CANDIDATE"},
    {"global_source_id": make_global_source_id("syn_evidence_1756"),
     "authority_level": "ACADEMIC_REFERENCE"},
    {"global_source_id": make_global_source_id("syn_wiki_map"),
     "authority_level": "VISUAL_QA_ONLY"},
    {"global_source_id": make_global_source_id("syn_eth_16c"),
     "authority_level": "METHODOLOGY_REFERENCE"},
])
MAPPING = pd.DataFrame([{"historical_subject_id": "hsub_a",
                         "scenario_polity_id": "sp_a"},
                        {"historical_subject_id": "hsub_b",
                         "scenario_polity_id": "sp_b"}])


def _feature(**kw):
    base = {
        "boundary_feature_id": make_boundary_feature_id(
            "syn", kw.get("historical_subject_id", "hsub_a"),
            kw.get("feature_role", "POLITY_EXTERNAL_BOUNDARY"),
            kw.get("valid_from", "1748-01-01"),
            kw.get("valid_to", "1766-12-31")),
        "historical_subject_id": "hsub_a",
        "feature_role": "POLITY_EXTERNAL_BOUNDARY",
        "valid_from": "1748-01-01", "valid_to": "1766-12-31",
        "temporal_precision": "YEAR",
        "geometry_source_id": make_global_source_id("syn_atlas_1500"),
        "political_evidence_source_id":
            make_global_source_id("syn_evidence_1756"),
        "source_locator": "map plate 7",
        "interpretation_level": "DERIVED",
        "source_confidence": "MEDIUM",
        "geometry": shapely.box(0, 0, 20000, 20000),
    }
    base.update(kw)
    return base


def _gate(rows):
    return validate_production_features(pd.DataFrame(rows), REGISTRY,
                                        MAPPING, SNAP)


# 1. cross-section date mismatch cannot become 1756 automatically
def test_cross_section_alone_cannot_become_1756():
    v = _gate([_feature(valid_from="1500-01-01", valid_to="1500-12-31")])
    assert any("does not explicitly cover 1756-08-01" in x for x in v)
    # And UNKNOWN validity is equally rejected.
    v2 = _gate([_feature(valid_from="UNKNOWN", valid_to="UNKNOWN")])
    assert any("does not explicitly cover" in x for x in v2)


# 2/3. visual-QA and methodology-only sources rejected as evidence
def test_visual_qa_source_rejected_for_production():
    v = _gate([_feature(political_evidence_source_id=
                        make_global_source_id("syn_wiki_map"))])
    assert any("VISUAL_QA_ONLY" in x for x in v)


def test_methodology_source_rejected_for_production():
    v = _gate([_feature(political_evidence_source_id=
                        make_global_source_id("syn_eth_16c"))])
    assert any("METHODOLOGY_REFERENCE" in x for x in v)


# 4. exact locator required
def test_exact_locator_required():
    assert any("source_locator" in x
               for x in _gate([_feature(source_locator="UNKNOWN")]))
    assert _gate([_feature()]) == []  # fully compliant row passes


# 5. snapshot temporal selection
def test_snapshot_temporal_selection():
    feats = pd.DataFrame([
        _feature(),
        _feature(valid_from="1757-01-01", valid_to="1763-01-01"),
        _feature(valid_from="1756-08-01", valid_to="1756-08-01")])
    sel = select_features_for_snapshot(feats, SNAP)
    assert len(sel) == 2


def _hex_block(n=6):
    qs, rs = np.meshgrid(np.arange(n), np.arange(n))
    q, r = qs.ravel(), rs.ravel()
    polys = GRID.polygons(q, r)
    ids = GRID.hex_ids(q, r)
    return polys, ids


def _snapshot(geo_a, geo_b=None):
    rows = [{"boundary_feature_id": "hbf_a",
             "historical_subject_id": "hsub_a",
             "scenario_polity_id": "sp_a",
             "feature_role": "POLITY_EXTERNAL_BOUNDARY",
             "source_confidence": "MEDIUM", "snapshot_date": SNAP,
             "geometry": geo_a}]
    if geo_b is not None:
        rows.append({"boundary_feature_id": "hbf_b",
                     "historical_subject_id": "hsub_b",
                     "scenario_polity_id": "sp_b",
                     "feature_role": "POLITY_EXTERNAL_BOUNDARY",
                     "source_confidence": "MEDIUM",
                     "snapshot_date": SNAP, "geometry": geo_b})
    return gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry")


def _bind(snap, polys, ids, land=None, terr=None):
    n = len(polys)
    return bind_snapshot_to_hexes(
        snap, polys, ids,
        np.ones(n) if land is None else land,
        np.ones(n, dtype=bool) if terr is None else terr,
        SC, SNAP, GRID.area)


# 6/7. many-to-many border membership + dominant ground-area binding
def test_border_membership_and_dominant_binding():
    polys, ids = _hex_block()
    b = shapely.bounds(polys)
    xmid = (b[:, 0].min() + b[:, 2].max()) / 2
    left = shapely.box(b[:, 0].min() - 1e4, b[:, 1].min() - 1e4,
                       xmid + 1500, b[:, 3].max() + 1e4)
    right = shapely.box(xmid + 1500, b[:, 1].min() - 1e4,
                        b[:, 2].max() + 1e4, b[:, 3].max() + 1e4)
    mem = _bind(_snapshot(left, right), polys, ids)
    border = mem[mem["border_hex"]]
    assert len(border) > 0  # many-to-many preserved
    assert (border.groupby("hex_id")["scenario_polity_id"].nunique()
            == 2).all()
    dom = mem[mem["is_dominant"]]
    assert (dom.groupby("hex_id").size() == 1).all()
    # winner has the larger ground-area share on each border hex
    for hid, grp in mem.groupby("hex_id"):
        w = grp[grp["is_dominant"]].iloc[0]
        assert w["intersection_ground_km2"] \
            == grp["intersection_ground_km2"].max()


# 8. tie deterministic
def test_exact_tie_breaks_by_stable_polity_id():
    polys, ids = _hex_block(2)
    both = shapely.box(*shapely.bounds(polys).min(axis=0)[:2],
                       *shapely.bounds(polys).max(axis=0)[2:])
    mem = _bind(_snapshot(both, both), polys, ids)
    dom = mem[mem["is_dominant"]]
    assert (dom["scenario_polity_id"] == "sp_a").all()  # min id wins ties
    assert (dom["dominance_margin"] == 0.0).all()


# 9. zero-hex loss becomes overlay candidate
def test_zero_hex_loss_becomes_overlay_candidate():
    polys, ids = _hex_block()
    cx, cy = np.asarray(GRID.axial_to_xy(1, 1), dtype=float)
    big = shapely.box(cx - 2e4, cy - 2e4, cx + 2e4, cy + 2e4)
    tiny = shapely.Point(float(cx) + 2500, float(cy)).buffer(120)
    snap = _snapshot(big, tiny)
    mem = _bind(snap, polys, ids)
    audit = hexification_audit(snap, mem)
    lost = audit[audit["scenario_polity_id"] == "sp_b"]
    assert lost.iloc[0]["representation_status"] == "ZERO_HEX_LOSS"
    assert not lost.iloc[0]["zero_hex_survival"]
    cands = overlay_candidates_from_audit(audit, snap)
    assert list(cands["scenario_polity_id"]) == ["sp_b"]
    assert (cands["recommended_representation"]
            == "SUBHEX_POLITICAL_OVERLAY").all()


# 10. claims not generated from control
def test_claims_never_generated_from_control():
    polys, ids = _hex_block(3)
    mem = _bind(_snapshot(shapely.box(-1e5, -1e5, 1e5, 1e5)), polys, ids)
    ctrl = controls_from_membership(mem, SC, {}, {})
    assert len(ctrl) > 0
    assert "claimant_scenario_polity_id" not in ctrl.columns
    assert (ctrl["control_status"] == "CONTROLLED").all()
    assert (ctrl["territorial_target_type"] == "TERRESTRIAL_HEX").all()


# 11. OCEAN hex cannot become terrestrial political target
def test_ocean_hex_never_a_land_target():
    polys, ids = _hex_block(3)
    terr = np.zeros(len(polys), dtype=bool)  # all OCEAN
    mem = _bind(_snapshot(shapely.box(-1e5, -1e5, 1e5, 1e5)), polys, ids,
                terr=terr)
    assert len(mem) == 0


# 12. modern admin cannot generate historical geometry
def test_modern_admin_forbidden_in_binding_layer():
    from mapgen.scenario_pipeline import scan_forbidden_reference_code

    for mod in ("historical_binding.py", "historical_geometry.py"):
        assert scan_forbidden_reference_code(
            Path("src/mapgen") / mod) == []


# 13. missing != neutral preserved
def test_missing_not_neutral_preserved():
    empty = pd.DataFrame({"territorial_target_type": [],
                          "territorial_target_id": [],
                          "control_status": []})
    with pytest.raises(IncompleteCoverageError):
        resolve_control_status(empty, "SOURCE_IDENTIFIED",
                               "TERRESTRIAL_HEX", "h6000_q+1_r+1")


# 14. COMPLETE coverage requires explicit assessment
def test_complete_requires_explicit_statuses():
    s = load_scenario(DATA, SC)
    cov = s.political_coverage
    assert int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0
    pilot = cov[cov["coverage_unit_id"]
                == "region_low_countries_1756_pilot"]
    assert len(pilot) == 1
    assert pilot.iloc[0]["control_coverage_status"] == "SOURCE_IDENTIFIED"


# 15. 009R2 / 010 regression + real SOURCE_GAP state
def test_regressions_and_source_gap_state():
    s = load_scenario(DATA, SC)
    assert len(s.polities) == 66
    assert len(s.scenario_polity_relationships) == 46
    feats = gpd.read_parquet(DATA / "historical"
                             / "historical_boundary_features.parquet")
    assert len(feats) == 0  # SOURCE_GAP: nothing fabricated
    assert {"geometry_source_id",
            "political_evidence_source_id"} <= set(feats.columns)
    assessment = pd.read_csv(DATA / "historical"
                             / "historical_source_assessment.csv")
    halc = assessment[assessment["source_title"].str.contains("v15.0")]
    assert halc.iloc[0]["assessment_status"] \
        == "USABLE_AS_GEOMETRIC_SUBSTRATE_ONLY"
    assert halc.iloc[0]["boundary_authority_for_1756"] == "NO"
    man = pd.read_csv(
        "output/europe_foundation_20260811/europe_hex_chunk_manifest.csv")
    assert int(man["hex_count"].sum()) == 1885422


# extra: contested overlap detection + area conservation identity
def test_contested_overlap_detection_and_area_conservation():
    a = shapely.box(0, 0, 30000, 30000)
    b = shapely.box(20000, 0, 50000, 30000)
    snap = _snapshot(a, b)
    v = check_contested_overlaps(snap)
    assert len(v) == 1  # silent overlap flagged
    snap2 = snap.copy()
    snap2.loc[1, "feature_role"] = "DE_JURE_CLAIM_BOUNDARY"
    assert check_contested_overlaps(snap2) == []
    # area conservation: membership sum equals source terrestrial area
    # (hex set must fully cover the footprint — use the bbox generator)
    box = shapely.box(3000, 3000, 27000, 27000)
    q, r = GRID.hexes_covering_bbox(*box.bounds)
    polys, ids = GRID.polygons(q, r), GRID.hex_ids(q, r)
    only_a = _snapshot(box)
    mem = _bind(only_a, polys, ids)
    from mapgen.islands import ground_area_perimeter

    src_km2, _ = ground_area_perimeter(only_a.iloc[0].geometry)
    assert abs(mem["intersection_ground_km2"].sum() - src_km2) \
        <= max(1e-3, src_km2 * 1e-4)
