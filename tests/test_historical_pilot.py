"""MAPGEN-011/011R/011R2 unit tests — evidence bundle discipline +
exact-land hex binding. All political geometry here is SYNTHETIC."""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely

from mapgen.hex_grid import HexGrid
from mapgen.historical_binding import (bind_snapshot_to_hexes,
                                       check_contested_overlaps,
                                       compiled_provenance_id,
                                       controls_from_membership,
                                       evaluate_feature_bundle,
                                       hexification_audit, land_union_from,
                                       membership_conservation_audit,
                                       overlay_candidates_from_audit,
                                       validate_assertion_table,
                                       validate_feature_evidence_links,
                                       validate_production_features)
from mapgen.historical_geometry import (CONFIDENCE_ORDER,
                                        FEATURE_EVIDENCE_LINK_COLUMNS,
                                        FEATURE_ROLE_REQUIREMENTS,
                                        GAMEPLAY_CONVERTIBLE_ROLES,
                                        HPG_ALGORITHM_VERSION,
                                        HPG_SCHEMA_VERSION,
                                        confidence_rank,
                                        make_boundary_feature_id,
                                        make_evidence_assertion_id,
                                        make_global_source_id,
                                        select_features_for_snapshot,
                                        worst_confidence)
from mapgen.islands import ground_area_perimeter
from mapgen.scenario import (IncompleteCoverageError, load_scenario,
                             resolve_control_status)

GRID = HexGrid(flat_to_flat=6000.0)
DATA = Path("data")
SC = "seven_years_war_1756_08_01"
SNAP = "1756-08-01"
SUBJ = "hsub_a"

GEOM_SRC = make_global_source_id("syn_geom")
POL_SRC = make_global_source_id("syn_pol")
WIKI_SRC = make_global_source_id("syn_wiki")
REGISTRY = pd.DataFrame([
    {"global_source_id": GEOM_SRC,
     "authority_level": "BOUNDARY_AUTHORITY_CANDIDATE"},
    {"global_source_id": POL_SRC, "authority_level": "ACADEMIC_REFERENCE"},
    {"global_source_id": WIKI_SRC, "authority_level": "VISUAL_QA_ONLY"},
])


def _a(src, atype, vf, vt, geom_auth, pol_auth, conf,
       subject=SUBJ, locator="plate 3"):
    return {
        "historical_evidence_id": make_evidence_assertion_id(
            src, subject, atype, vf, vt),
        "global_source_id": src, "historical_subject_id": subject,
        "assertion_type": atype, "valid_from": vf, "valid_to": vt,
        "temporal_precision": "YEAR", "exact_locator": locator,
        "interpretation_level": "DIRECT", "confidence": conf,
        "geometry_authority": geom_auth, "political_authority": pol_auth,
        "notes": "TEST ONLY",
    }


GEOM56 = _a(GEOM_SRC, "BOUNDARY_POSITION", "1756-01-01", "1756-12-31",
            "YES", "NO", "HIGH")
GEOM50 = _a(GEOM_SRC, "BOUNDARY_POSITION", "1750-01-01", "1750-12-31",
            "YES", "NO", "HIGH")
GEOM_NOAUTH = _a(GEOM_SRC, "BOUNDARY_POSITION", "1756-02-01",
                 "1756-11-30", "NO", "NO", "HIGH")
GEOM_NOLOC = _a(GEOM_SRC, "BOUNDARY_POSITION", "1756-03-01",
                "1756-10-31", "YES", "NO", "HIGH",
                locator="UNKNOWN (work-level)")
POL = _a(POL_SRC, "POLITICAL_CONTROL", "1748-01-01", "1763-12-31",
         "NO", "YES", "MEDIUM")
CLAIM = _a(POL_SRC, "DE_JURE_CLAIM", "1748-01-01", "1763-12-31",
           "NO", "YES", "MEDIUM")
EXIST = _a(POL_SRC, "POLITY_EXISTENCE", "1748-01-01", "1763-12-31",
           "NO", "YES", "HIGH")
CONT_OK = _a(POL_SRC, "TERRITORIAL_CONTINUITY", "1750-01-01",
             "1760-12-31", "NO", "YES", "LOW")
CONT_GAP = _a(POL_SRC, "TERRITORIAL_CONTINUITY", "1500-01-01",
              "1700-12-31", "NO", "YES", "LOW")
POL_LATE = _a(POL_SRC, "POLITICAL_CONTROL", "1770-01-01", "1780-12-31",
              "NO", "YES", "HIGH")
WIKI_POL = _a(WIKI_SRC, "POLITICAL_CONTROL", "1748-01-01", "1763-12-31",
              "NO", "YES", "LOW")
ASSERTIONS = pd.DataFrame([GEOM56, GEOM50, GEOM_NOAUTH, GEOM_NOLOC, POL,
                           CLAIM, EXIST, CONT_OK, CONT_GAP, POL_LATE,
                           WIKI_POL])
MAPPING = pd.DataFrame([{"historical_subject_id": SUBJ,
                         "scenario_polity_id": "sp_a"},
                        {"historical_subject_id": "hsub_b",
                         "scenario_polity_id": "sp_b"}])


def _links(fid, pairs):
    return pd.DataFrame(
        [{"boundary_feature_id": fid,
          "historical_evidence_id": a["historical_evidence_id"],
          "evidence_role": role, "is_required": "YES",
          "notes": "TEST ONLY"} for role, a in pairs],
        columns=FEATURE_EVIDENCE_LINK_COLUMNS)


def _bundle(role, pairs, subject=SUBJ, fid="hbf_t"):
    return evaluate_feature_bundle(
        {"boundary_feature_id": fid, "historical_subject_id": subject,
         "feature_role": role}, _links(fid, pairs), ASSERTIONS,
        REGISTRY, SNAP)


# --------------------------------------------------------------------------
# MAPGEN-011R2: bundle compatibility
# --------------------------------------------------------------------------
def test_polity_existence_cannot_authorise_boundary():
    v, _ = _bundle("POLITY_EXTERNAL_BOUNDARY",
                   [("GEOMETRY_SHAPE", EXIST), ("POLITICAL_STATUS", EXIST)])
    assert any("assertion_type POLITY_EXISTENCE" in x for x in v)
    assert len(v) >= 2  # rejected for BOTH required roles


def test_de_facto_requires_political_control_evidence():
    v, _ = _bundle("DE_FACTO_CONTROL_BOUNDARY",
                   [("GEOMETRY_SHAPE", GEOM56),
                    ("POLITICAL_STATUS", CLAIM)])
    assert any("requires one of ['POLITICAL_CONTROL']" in x for x in v)


def test_de_jure_requires_claim_evidence():
    v, _ = _bundle("DE_JURE_CLAIM_BOUNDARY",
                   [("GEOMETRY_SHAPE", GEOM56), ("CLAIM_STATUS", POL)])
    assert any("requires one of ['DE_JURE_CLAIM']" in x for x in v)


def test_geometry_authority_required():
    v, _ = _bundle("POLITY_EXTERNAL_BOUNDARY",
                   [("GEOMETRY_SHAPE", GEOM_NOAUTH),
                    ("POLITICAL_STATUS", POL)])
    assert any("geometry_authority != YES" in x for x in v)


def test_uncertain_boundary_never_gameplay_convertible():
    v, _ = _bundle("UNCERTAIN_BOUNDARY",
                   [("GEOMETRY_SHAPE", GEOM56),
                    ("POLITICAL_STATUS", POL)])
    assert any("not convertible to production gameplay control" in x
               for x in v)
    assert "UNCERTAIN_BOUNDARY" not in GAMEPLAY_CONVERTIBLE_ROLES


def test_missing_required_role_rejected():
    v, _ = _bundle("POLITY_EXTERNAL_BOUNDARY",
                   [("GEOMETRY_SHAPE", GEOM56)])
    assert any("requires POLITICAL_STATUS evidence" in x for x in v)
    v2, _ = _bundle("POLITY_EXTERNAL_BOUNDARY", [])
    assert any("no evidence bundle linked" in x for x in v2)


def test_political_evidence_must_cover_snapshot():
    v, _ = _bundle("POLITY_EXTERNAL_BOUNDARY",
                   [("GEOMETRY_SHAPE", GEOM56),
                    ("POLITICAL_STATUS", POL_LATE)])
    assert any("does not explicitly cover 1756-08-01" in x for x in v)


def test_forbidden_authority_source_rejected():
    v, _ = _bundle("POLITY_EXTERNAL_BOUNDARY",
                   [("GEOMETRY_SHAPE", GEOM56),
                    ("POLITICAL_STATUS", WIKI_POL)])
    assert any("forbidden for production" in x for x in v)


def test_assertion_locator_required():
    v, _ = _bundle("POLITY_EXTERNAL_BOUNDARY",
                   [("GEOMETRY_SHAPE", GEOM_NOLOC),
                    ("POLITICAL_STATUS", POL)])
    assert any("lacks an exact locator" in x for x in v)


def test_subject_mismatch_rejected():
    v, _ = _bundle("POLITY_EXTERNAL_BOUNDARY",
                   [("GEOMETRY_SHAPE", GEOM56),
                    ("POLITICAL_STATUS", POL)], subject="hsub_b")
    assert any("subject" in x for x in v)


# --------------------------------------------------------------------------
# Temporal continuity bridge
# --------------------------------------------------------------------------
def test_continuity_bridge_required_when_geometry_off_date():
    v, _ = _bundle("POLITY_EXTERNAL_BOUNDARY",
                   [("GEOMETRY_SHAPE", GEOM50),
                    ("POLITICAL_STATUS", POL)])
    assert any("no TERRITORIAL_CONTINUITY bridge" in x for x in v)


def test_continuity_gap_rejected():
    v, _ = _bundle("POLITY_EXTERNAL_BOUNDARY",
                   [("GEOMETRY_SHAPE", GEOM50),
                    ("TEMPORAL_CONTINUITY", CONT_GAP),
                    ("POLITICAL_STATUS", POL)])
    assert any("has a gap" in x for x in v)


def test_valid_bundles_accepted_with_ordinal_confidence():
    # direct 1756 geometry
    v1, i1 = _bundle("DE_FACTO_CONTROL_BOUNDARY",
                     [("GEOMETRY_SHAPE", GEOM56),
                      ("POLITICAL_STATUS", POL)])
    assert v1 == []
    assert i1["confidence"] == "MEDIUM"  # HIGH + MEDIUM
    # 1750 geometry carried by a continuity bridge
    v2, i2 = _bundle("DE_FACTO_CONTROL_BOUNDARY",
                     [("GEOMETRY_SHAPE", GEOM50),
                      ("TEMPORAL_CONTINUITY", CONT_OK),
                      ("POLITICAL_STATUS", POL)])
    assert v2 == []
    assert i2["confidence"] == "LOW"  # HIGH + LOW + MEDIUM
    assert "TEMPORAL_CONTINUITY" in i2["roles"]
    assert i2["source_ids"] == {GEOM_SRC, POL_SRC}


def test_continuity_assertion_type_enforced():
    v, _ = _bundle("POLITY_EXTERNAL_BOUNDARY",
                   [("GEOMETRY_SHAPE", GEOM50),
                    ("TEMPORAL_CONTINUITY", EXIST),
                    ("POLITICAL_STATUS", POL)])
    assert any("TERRITORIAL_CONTINUITY required" in x for x in v)


# --------------------------------------------------------------------------
# Confidence ordinal
# --------------------------------------------------------------------------
def test_confidence_ordinal_aggregation():
    assert CONFIDENCE_ORDER == ["UNKNOWN", "LOW", "MEDIUM", "HIGH"]
    assert worst_confidence(["HIGH", "MEDIUM"]) == "MEDIUM"
    assert worst_confidence(["HIGH", "LOW"]) == "LOW"
    assert worst_confidence(["MEDIUM", "UNKNOWN"]) == "UNKNOWN"
    assert worst_confidence([]) == "UNKNOWN"
    assert confidence_rank("nonsense") == 0
    # the old string min() was wrong in exactly this case
    assert min(["HIGH", "MEDIUM"]) == "HIGH"


# --------------------------------------------------------------------------
# Feature-level production gate + table integrity
# --------------------------------------------------------------------------
def _feature_row(**kw):
    base = {
        "boundary_feature_id": make_boundary_feature_id(
            "syn", SUBJ, "POLITY_EXTERNAL_BOUNDARY", "1748-01-01",
            "1766-12-31"),
        "historical_subject_id": SUBJ,
        "feature_role": "POLITY_EXTERNAL_BOUNDARY",
        "valid_from": "1748-01-01", "valid_to": "1766-12-31",
        "temporal_precision": "YEAR", "geometry_source_id": GEOM_SRC,
        "political_evidence_source_id": POL_SRC,
        "political_evidence_id": POL["historical_evidence_id"],
        "source_locator": "map plate 7",
        "interpretation_level": "DERIVED", "source_confidence": "MEDIUM",
        "geometry": shapely.box(0, 0, 20000, 20000),
    }
    base.update(kw)
    return base


def test_production_feature_gate_end_to_end():
    row = _feature_row()
    fid = row["boundary_feature_id"]
    good = _links(fid, [("GEOMETRY_SHAPE", GEOM56),
                        ("POLITICAL_STATUS", POL)])
    assert validate_production_features(
        pd.DataFrame([row]), REGISTRY, ASSERTIONS, good, MAPPING,
        SNAP) == []
    # a bare source id is not authority: no links at all
    v = validate_production_features(
        pd.DataFrame([row]), REGISTRY, ASSERTIONS,
        good.iloc[0:0], MAPPING, SNAP)
    assert any("no evidence bundle linked" in x for x in v)
    # feature validity must still cover the snapshot
    bad = _feature_row(valid_from="1700-01-01", valid_to="1710-12-31")
    v2 = validate_production_features(
        pd.DataFrame([bad]), REGISTRY, ASSERTIONS,
        _links(bad["boundary_feature_id"],
               [("GEOMETRY_SHAPE", GEOM56), ("POLITICAL_STATUS", POL)]),
        MAPPING, SNAP)
    assert any("feature validity" in x for x in v2)


def test_assertion_and_link_table_integrity():
    assert validate_assertion_table(ASSERTIONS, REGISTRY) == []
    dup = pd.concat([ASSERTIONS, ASSERTIONS.iloc[[0]]],
                    ignore_index=True)
    assert any("duplicate" in x
               for x in validate_assertion_table(dup, REGISTRY))
    bad = ASSERTIONS.copy()
    bad.loc[0, "valid_from"] = "1799-01-01"
    assert any("valid_from > valid_to" in x
               for x in validate_assertion_table(bad, REGISTRY))
    orphan = pd.DataFrame([{
        "boundary_feature_id": "hbf_ghost",
        "historical_evidence_id": "hev_ghost",
        "evidence_role": "GEOMETRY_SHAPE", "is_required": "YES",
        "notes": ""}], columns=FEATURE_EVIDENCE_LINK_COLUMNS)
    v = validate_feature_evidence_links(
        orphan, pd.DataFrame({"boundary_feature_id": ["hbf_real"]}),
        ASSERTIONS)
    assert len([x for x in v if "orphan" in x]) == 2


def test_snapshot_temporal_selection():
    feats = pd.DataFrame([
        _feature_row(),
        _feature_row(valid_from="1757-01-01", valid_to="1763-01-01"),
        _feature_row(valid_from="1756-08-01", valid_to="1756-08-01")])
    assert len(select_features_for_snapshot(feats, SNAP)) == 2


# --------------------------------------------------------------------------
# Exact-land binding + audits
# --------------------------------------------------------------------------
def _snap_rows(*rows):
    return gpd.GeoDataFrame(pd.DataFrame(list(rows)), geometry="geometry")


def _row(pid, geom, fid="hbf_x", subject=None, evid="hev_syn",
         gsrc="hsrc_syn", conf="MEDIUM"):
    """AUTHORISED snapshot row (same schema the compiler emits)."""
    return {"boundary_feature_id": fid,
            "historical_subject_id": subject or f"hsub_{pid[3:]}",
            "scenario_polity_id": pid,
            "feature_role": "POLITY_EXTERNAL_BOUNDARY",
            "snapshot_date": SNAP, "bundle_confidence": conf,
            "bundle_evidence_ids": evid, "bundle_source_ids": gsrc,
            "bundle_evidence_roles": "GEOMETRY_SHAPE|POLITICAL_STATUS",
            "valid_from": "1748-01-01", "valid_to": "1763-12-31",
            "positional_uncertainty_km": 5.0,
            "geometry_status": "GEOMETRY_PRESENT",
            "production_authorised": True,
            # deprecated aliases retained to prove they are ignored
            "political_evidence_id": "hev_DEPRECATED",
            "global_source_id": "hsrc_DEPRECATED",
            "source_confidence": "HIGH",
            "geometry": geom}


def _hexes(n=5):
    qs, rs = np.meshgrid(np.arange(n), np.arange(n))
    q, r = qs.ravel(), rs.ravel()
    polys = GRID.polygons(q, r)
    return polys, GRID.hex_ids(q, r)


def _bind(snap, polys, ids, land=None, terr=None):
    n = len(polys)
    return bind_snapshot_to_hexes(
        snap, polys, ids, polys if land is None else land,
        np.ones(n, dtype=bool) if terr is None else terr, SC, SNAP)


def test_coastal_exact_land_intersection():
    poly = GRID.polygon(9, 9)
    b = poly.bounds
    xmid = b[0] + (b[2] - b[0]) * 0.6
    land = shapely.intersection(poly, shapely.box(b[0] - 1e4, b[1] - 1e4,
                                                  xmid, b[3] + 1e4))
    hist = shapely.box(b[0] + (b[2] - b[0]) * 0.3, b[1] - 1e4,
                       b[2] + 5e4, b[3] + 1e4)
    _, pmem = _bind(_snap_rows(_row("sp_a", hist)),
                    np.array([poly], dtype=object), [GRID.hex_id(9, 9)],
                    land=np.array([land], dtype=object))
    want, _ = ground_area_perimeter(shapely.intersection(hist, land))
    old_wrong, _ = ground_area_perimeter(shapely.intersection(hist, poly))
    assert abs(float(pmem.iloc[0]["intersection_ground_km2"])
               - want) < 1e-3
    assert old_wrong > want * 1.3
    assert float(pmem.iloc[0]["share_of_terrestrial_hex_land"]) <= 1.0


def test_same_polity_overlap_unioned_not_summed():
    poly = GRID.polygon(3, 3)
    b = poly.bounds
    a = shapely.box(b[0], b[1], b[0] + (b[2] - b[0]) * 0.6, b[3])
    c = shapely.box(b[0] + (b[2] - b[0]) * 0.3, b[1], b[2], b[3])
    snap = _snap_rows(_row("sp_a", a, "hbf_A", subject="hsub_north",
                           conf="HIGH"),
                      _row("sp_a", c, "hbf_B", subject="hsub_south",
                           conf="LOW"))
    fmem, pmem = _bind(snap, np.array([poly], dtype=object),
                       [GRID.hex_id(3, 3)])
    union_km2, _ = ground_area_perimeter(
        shapely.intersection(shapely.union(a, c), poly))
    assert abs(float(pmem.iloc[0]["intersection_ground_km2"])
               - union_km2) < 1e-3
    assert float(fmem["intersection_ground_km2"].sum()) > union_km2 * 1.2
    assert pmem.iloc[0]["contributing_boundary_feature_ids"] \
        == "hbf_A|hbf_B"
    # multi-subject provenance kept, ordinal worst confidence
    assert pmem.iloc[0]["contributing_historical_subject_ids"] \
        == "hsub_north|hsub_south"
    assert pmem.iloc[0]["source_confidence"] == "LOW"


def test_union_component_count_not_inflated():
    poly = GRID.polygon(3, 3)
    b = poly.bounds
    a = shapely.box(b[0], b[1], b[0] + (b[2] - b[0]) * 0.6, b[3])
    c = shapely.box(b[0] + (b[2] - b[0]) * 0.3, b[1], b[2], b[3])
    snap = _snap_rows(_row("sp_a", a, "hbf_A"), _row("sp_a", c, "hbf_B"))
    _, pmem = _bind(snap, np.array([poly], dtype=object),
                    [GRID.hex_id(3, 3)])
    audit = hexification_audit(snap, pmem, {GRID.hex_id(3, 3): poly})
    assert int(audit.iloc[0]["source_component_count"]) == 1


def test_share_above_one_raises_never_clips(monkeypatch):
    import mapgen.historical_binding as hb

    real = hb._g_km2
    poly = GRID.polygon(4, 4)
    hex_km2 = real(poly)
    half = shapely.box(poly.bounds[0], poly.bounds[1],
                       (poly.bounds[0] + poly.bounds[2]) / 2,
                       poly.bounds[3])

    def corrupted(geom):
        v = real(geom)
        return v if abs(v - hex_km2) < 1e-9 else v * 3.0

    monkeypatch.setattr(hb, "_g_km2", corrupted)
    with pytest.raises(ValueError, match="share"):
        hb.bind_snapshot_to_hexes(
            _snap_rows(_row("sp_a", half)),
            np.array([poly], dtype=object), [GRID.hex_id(4, 4)],
            np.array([poly], dtype=object),
            np.ones(1, dtype=bool), SC, SNAP)


def test_border_many_to_many_and_winner():
    polys, ids = _hexes()
    b = shapely.bounds(polys)
    xmid = (b[:, 0].min() + b[:, 2].max()) / 2
    left = shapely.box(b[:, 0].min() - 1e4, b[:, 1].min() - 1e4,
                       xmid + 1500, b[:, 3].max() + 1e4)
    right = shapely.box(xmid + 1500, b[:, 1].min() - 1e4,
                        b[:, 2].max() + 1e4, b[:, 3].max() + 1e4)
    _, pmem = _bind(_snap_rows(_row("sp_a", left), _row("sp_b", right)),
                    polys, ids)
    assert len(pmem[pmem["border_hex"]]) > 0
    dom = pmem[pmem["is_dominant"]]
    assert (dom.groupby("hex_id").size() == 1).all()
    for hid, grp in pmem.groupby("hex_id"):
        w = grp[grp["is_dominant"]].iloc[0]
        assert w["intersection_ground_km2"] \
            == grp["intersection_ground_km2"].max()


def test_exact_tie_stable_id_order():
    poly = GRID.polygon(2, 2)
    _, pmem = _bind(_snap_rows(_row("sp_b", poly), _row("sp_a", poly)),
                    np.array([poly], dtype=object), [GRID.hex_id(2, 2)])
    assert list(pmem[pmem["is_dominant"]]["scenario_polity_id"]) == ["sp_a"]


def test_winner_loss_distortion_visible():
    poly = GRID.polygon(7, 7)
    b = poly.bounds
    xcut = b[0] + (b[2] - b[0]) * 0.49
    ga = shapely.box(b[0] - 1e4, b[1] - 1e4, xcut, b[3] + 1e4)
    gb = shapely.box(xcut, b[1] - 1e4, b[2] + 1e4, b[3] + 1e4)
    snap = _snap_rows(_row("sp_a", ga), _row("sp_b", gb))
    _, pmem = _bind(snap, np.array([poly], dtype=object),
                    [GRID.hex_id(7, 7)])
    land_by_id = {GRID.hex_id(7, 7): poly}
    cons = membership_conservation_audit(snap, pmem, land_by_id)
    a_cons = cons[cons["scenario_polity_id"] == "sp_a"].iloc[0]
    assert abs(a_cons["conservation_error_km2"]) < 0.01
    hexa = hexification_audit(snap, pmem, land_by_id)
    a_row = hexa[hexa["scenario_polity_id"] == "sp_a"].iloc[0]
    b_row = hexa[hexa["scenario_polity_id"] == "sp_b"].iloc[0]
    assert a_row["winner_represented_ground_km2"] == 0.0
    assert a_row["omission_ground_km2"] \
        > a_row["source_land_ground_km2"] * 0.95
    assert a_row["representation_status"] == "ZERO_HEX_LOSS"
    assert b_row["commission_ground_km2"] \
        > b_row["source_land_ground_km2"] * 0.5


def test_land_mask_single_authority():
    poly = GRID.polygon(6, 6)
    land_by_id = {GRID.hex_id(6, 6): poly}
    assert land_union_from(land_by_id).equals(poly)
    with pytest.raises(ValueError, match="land mask mismatch"):
        land_union_from(land_by_id, shapely.buffer(poly, -1000.0))
    snap = _snap_rows(_row("sp_a", poly))
    _, pmem = _bind(snap, np.array([poly], dtype=object),
                    [GRID.hex_id(6, 6)])
    with pytest.raises(ValueError, match="land mask mismatch"):
        hexification_audit(snap, pmem, land_by_id,
                           land_union=shapely.buffer(poly, -1000.0))


def test_membership_conservation_on_covering_hexes():
    box = shapely.box(3000, 3000, 27000, 27000)
    q, r = GRID.hexes_covering_bbox(*box.bounds)
    polys, ids = GRID.polygons(q, r), GRID.hex_ids(q, r)
    snap = _snap_rows(_row("sp_a", box))
    _, pmem = _bind(snap, polys, ids)
    cons = membership_conservation_audit(snap, pmem, dict(zip(ids, polys)))
    assert abs(cons.iloc[0]["conservation_error_km2"]) \
        <= max(1e-3, cons.iloc[0]["source_land_ground_km2"] * 1e-4)


def test_zero_hex_loss_overlay_candidate_with_provenance():
    polys, ids = _hexes(3)
    cx, cy = np.asarray(GRID.axial_to_xy(1, 1), dtype=float)
    big = shapely.box(cx - 2e4, cy - 2e4, cx + 2e4, cy + 2e4)
    tiny = shapely.Point(float(cx) + 2500, float(cy)).buffer(120)
    snap = _snap_rows(_row("sp_a", big), _row("sp_b", tiny))
    _, pmem = _bind(snap, polys, ids)
    hexa = hexification_audit(snap, pmem, dict(zip(ids, polys)))
    cands = overlay_candidates_from_audit(hexa, snap)
    assert list(cands["scenario_polity_id"]) == ["sp_b"]
    assert cands.iloc[0]["bundle_evidence_ids"] == "hev_syn"
    assert cands.iloc[0]["bundle_source_ids"] == "hsrc_syn"
    assert cands.iloc[0]["historical_subject_ids"] == "hsub_b"
    bad = snap.copy()
    bad["bundle_evidence_ids"] = None
    with pytest.raises(ValueError, match="provenance"):
        overlay_candidates_from_audit(hexa, bad)


def test_control_provenance_bundle_and_no_claims():
    poly = GRID.polygon(8, 8)
    b = poly.bounds
    a = shapely.box(b[0], b[1], b[0] + (b[2] - b[0]) * 0.6, b[3])
    c = shapely.box(b[0] + (b[2] - b[0]) * 0.3, b[1], b[2], b[3])
    multi = _snap_rows(
        _row("sp_a", a, "hbf_A", subject="hsub_n", evid="hev_a",
             gsrc="hsrc_a"),
        _row("sp_a", c, "hbf_B", subject="hsub_s", evid="hev_b",
             gsrc="hsrc_b"))
    _, pm_multi = _bind(multi, np.array([poly], dtype=object),
                        [GRID.hex_id(8, 8)])
    ctrl = controls_from_membership(pm_multi, SC)
    assert ctrl.iloc[0]["source_ids"] == "hsrc_a|hsrc_b"
    assert ctrl.iloc[0]["source_id"] == compiled_provenance_id(
        ["hsrc_a", "hsrc_b"], [ctrl.iloc[0]["political_evidence_ids"]],
        [ctrl.iloc[0]["boundary_feature_ids"]])
    assert ctrl.iloc[0]["historical_subject_ids"] == "hsub_n|hsub_s"
    assert "claimant_scenario_polity_id" not in ctrl.columns
    # single source keeps the real id
    _, pm_one = _bind(_snap_rows(_row("sp_a", poly, gsrc="hsrc_only")),
                      np.array([poly], dtype=object),
                      [GRID.hex_id(8, 8)])
    assert controls_from_membership(pm_one, SC).iloc[0]["source_id"] \
        == "hsrc_only"
    # provenance is mandatory
    stripped = pm_one.copy()
    stripped["bundle_source_ids"] = ""
    with pytest.raises(ValueError, match="provenance"):
        controls_from_membership(stripped, SC)


def test_ocean_hex_never_terrestrial_target():
    polys, ids = _hexes(3)
    _, pmem = _bind(_snap_rows(_row("sp_a",
                                    shapely.box(-1e5, -1e5, 1e5, 1e5))),
                    polys, ids, terr=np.zeros(len(polys), dtype=bool))
    assert len(pmem) == 0


def test_contested_overlap_detection():
    a = shapely.box(0, 0, 30000, 30000)
    b = shapely.box(20000, 0, 50000, 30000)
    snap = _snap_rows(_row("sp_a", a), _row("sp_b", b))
    assert len(check_contested_overlaps(snap)) == 1
    snap2 = snap.copy()
    snap2.loc[1, "feature_role"] = "DE_JURE_CLAIM_BOUNDARY"
    assert check_contested_overlaps(snap2) == []


def test_modern_admin_forbidden_in_binding_layer():
    from mapgen.scenario_pipeline import scan_forbidden_reference_code

    for mod in ("historical_binding.py", "historical_geometry.py"):
        assert scan_forbidden_reference_code(
            Path("src/mapgen") / mod) == []


def test_missing_not_neutral_preserved():
    empty = pd.DataFrame({"territorial_target_type": [],
                          "territorial_target_id": [],
                          "control_status": []})
    with pytest.raises(IncompleteCoverageError):
        resolve_control_status(empty, "SOURCE_IDENTIFIED",
                               "TERRESTRIAL_HEX", "h6000_q+1_r+1")


def test_regressions_and_source_gap_state():
    s = load_scenario(DATA, SC)
    # MAPGEN-013 added the two self-labelled estates and their imperial
    # membership; nothing else in the catalogue moved.
    assert len(s.polities) == 71
    assert len(s.scenario_polity_relationships) == 51
    feats = gpd.read_parquet(DATA / "historical"
                             / "historical_boundary_features.parquet")
    links = pd.read_csv(DATA / "historical"
                        / "historical_boundary_feature_evidence.csv")
    # MAPGEN-012: the Central Europe pilot added real production
    # geometry; every feature still carries a complete evidence bundle
    assert list(links.columns) == FEATURE_EVIDENCE_LINK_COLUMNS
    assert set(links["boundary_feature_id"])         == set(feats["boundary_feature_id"])
    assertions = pd.read_csv(
        DATA / "historical" / "historical_evidence_assertions.csv")
    halc = assertions[assertions["assertion_type"]
                      == "GEOMETRIC_SUBSTRATE_ONLY"]
    # MAPGEN-021 added the OSM coastline as a second geometric substrate.
    # The rule being protected is that NO geometric substrate ever carries
    # political authority, which is now checked across all of them, and the
    # HALC assertion specifically is still present and still powerless.
    assert (halc["political_authority"] == "NO").all()
    hs = halc[halc["historical_subject_id"] == "low_countries_localities"]
    assert len(hs) == 1
    assert hs.iloc[0]["political_authority"] == "NO"
    man = pd.read_csv(
        "output/europe_foundation_20260811/europe_hex_chunk_manifest.csv")
    assert int(man["hex_count"].sum()) == 1885422
    assert HPG_SCHEMA_VERSION == "1.4.0"
    assert HPG_ALGORITHM_VERSION == "1.3.0"
