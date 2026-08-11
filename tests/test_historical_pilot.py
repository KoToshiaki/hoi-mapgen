"""MAPGEN-011/011R unit tests — assertion-backed source discipline +
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
                                       controls_from_membership,
                                       hexification_audit,
                                       membership_conservation_audit,
                                       overlay_candidates_from_audit,
                                       validate_production_features)
from mapgen.historical_geometry import (make_boundary_feature_id,
                                        make_evidence_assertion_id,
                                        make_global_source_id,
                                        select_features_for_snapshot)
from mapgen.islands import ground_area_perimeter
from mapgen.scenario import (IncompleteCoverageError, load_scenario,
                             resolve_control_status)

GRID = HexGrid(flat_to_flat=6000.0)
DATA = Path("data")
SC = "seven_years_war_1756_08_01"
SNAP = "1756-08-01"

HALC = make_global_source_id("syn_halc_1500")
EVID = make_global_source_id("syn_evidence_1756")
REGISTRY = pd.DataFrame([
    {"global_source_id": HALC,
     "authority_level": "BOUNDARY_AUTHORITY_CANDIDATE"},
    {"global_source_id": EVID, "authority_level": "ACADEMIC_REFERENCE"},
    {"global_source_id": make_global_source_id("syn_wiki"),
     "authority_level": "VISUAL_QA_ONLY"},
])


def _assertion(**kw):
    base = {
        "historical_evidence_id": make_evidence_assertion_id(
            kw.get("global_source_id", EVID),
            kw.get("historical_subject_id", "hsub_a"),
            kw.get("assertion_type", "POLITICAL_CONTROL"),
            kw.get("valid_from", "1748-01-01"),
            kw.get("valid_to", "1763-12-31")),
        "global_source_id": EVID,
        "historical_subject_id": "hsub_a",
        "assertion_type": "POLITICAL_CONTROL",
        "valid_from": "1748-01-01", "valid_to": "1763-12-31",
        "temporal_precision": "YEAR", "exact_locator": "map plate 7",
        "interpretation_level": "DIRECT", "confidence": "MEDIUM",
        "geometry_authority": "NO", "political_authority": "YES",
    }
    base.update(kw)
    return base


ASSERTIONS = pd.DataFrame([
    _assertion(),
    _assertion(global_source_id=HALC, historical_subject_id="hsub_halc",
               assertion_type="GEOMETRIC_SUBSTRATE_ONLY",
               valid_from="1500-01-01", valid_to="1500-12-31",
               political_authority="NO",
               exact_locator="layer 'HALC 1500'"),
])
MAPPING = pd.DataFrame([{"historical_subject_id": "hsub_a",
                         "scenario_polity_id": "sp_a"},
                        {"historical_subject_id": "hsub_b",
                         "scenario_polity_id": "sp_b"},
                        {"historical_subject_id": "hsub_halc",
                         "scenario_polity_id": "sp_h"}])


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
        "geometry_source_id": HALC,
        "political_evidence_source_id": EVID,
        "political_evidence_id":
            ASSERTIONS.iloc[0]["historical_evidence_id"],
        "source_locator": "map plate 7",
        "interpretation_level": "DERIVED",
        "source_confidence": "MEDIUM",
        "geometry": shapely.box(0, 0, 20000, 20000),
    }
    base.update(kw)
    return base


def _gate(rows, assertions=ASSERTIONS):
    return validate_production_features(pd.DataFrame(rows), REGISTRY,
                                        assertions, MAPPING, SNAP)


# --------------------------------------------------------------------------
# Source discipline (011R hardened)
# --------------------------------------------------------------------------
def test_fake_1756_feature_exploit_rejected():
    """THE 011R regression: cross-section substrate as its own evidence
    + hand-typed 1756 feature validity must NEVER pass."""
    fake = _feature(
        historical_subject_id="hsub_halc",
        political_evidence_id=ASSERTIONS.iloc[1]["historical_evidence_id"],
        valid_from="1750-01-01", valid_to="1760-12-31")
    v = _gate([fake])
    assert any("does not explicitly cover 1756-08-01" in x for x in v)
    assert any("no political authority" in x for x in v)


def test_valid_independent_evidence_accepted():
    assert _gate([_feature()]) == []


def test_missing_or_unregistered_assertion_rejected():
    v = _gate([_feature(political_evidence_id="hev_nonexistent")])
    assert any("not a registered evidence assertion" in x for x in v)
    v2 = _gate([_feature()], assertions=ASSERTIONS.iloc[0:0])
    assert any("not a registered evidence assertion" in x for x in v2)


def test_subject_mismatch_rejected():
    v = _gate([_feature(historical_subject_id="hsub_b")])
    assert any("subject" in x for x in v)


def test_assertion_locator_required():
    a = ASSERTIONS.copy()
    a.loc[0, "exact_locator"] = "UNKNOWN (work-level)"
    v = _gate([_feature()], assertions=a)
    assert any("exact locator" in x for x in v)


def test_forbidden_authority_assertion_source_rejected():
    a = ASSERTIONS.copy()
    a.loc[0, "global_source_id"] = make_global_source_id("syn_wiki")
    v = _gate([_feature()], assertions=a)
    assert any("forbidden for production" in x for x in v)


def test_snapshot_temporal_selection():
    feats = pd.DataFrame([
        _feature(),
        _feature(valid_from="1757-01-01", valid_to="1763-01-01"),
        _feature(valid_from="1756-08-01", valid_to="1756-08-01")])
    assert len(select_features_for_snapshot(feats, SNAP)) == 2


# --------------------------------------------------------------------------
# Exact-land binding
# --------------------------------------------------------------------------
def _snap_rows(*rows):
    return gpd.GeoDataFrame(pd.DataFrame(list(rows)), geometry="geometry")


def _row(pid, geom, fid="hbf_x", subject=None, evid="hev_syn",
         gsrc="hsrc_syn"):
    return {"boundary_feature_id": fid,
            "historical_subject_id": subject or f"hsub_{pid[3:]}",
            "scenario_polity_id": pid,
            "feature_role": "POLITY_EXTERNAL_BOUNDARY",
            "political_evidence_id": evid, "global_source_id": gsrc,
            "source_confidence": "MEDIUM", "snapshot_date": SNAP,
            "geometry": geom}


def _hexes(n=5):
    qs, rs = np.meshgrid(np.arange(n), np.arange(n))
    q, r = qs.ravel(), rs.ravel()
    polys = GRID.polygons(q, r)
    return polys, GRID.hex_ids(q, r)


def _bind(snap, polys, ids, land=None, terr=None):
    n = len(polys)
    return bind_snapshot_to_hexes(
        snap, polys, ids,
        polys if land is None else land,  # default: fully-land hexes
        np.ones(n, dtype=bool) if terr is None else terr,
        SC, SNAP)


def test_coastal_exact_land_intersection():
    poly = GRID.polygon(9, 9)
    b = poly.bounds
    xmid = b[0] + (b[2] - b[0]) * 0.6
    land = shapely.intersection(poly, shapely.box(b[0] - 1e4, b[1] - 1e4,
                                                  xmid, b[3] + 1e4))
    hist = shapely.box(b[0] + (b[2] - b[0]) * 0.3, b[1] - 1e4,
                       b[2] + 5e4, b[3] + 1e4)  # juts far into the sea
    _, pmem = _bind(_snap_rows(_row("sp_a", hist)),
                    np.array([poly], dtype=object), [GRID.hex_id(9, 9)],
                    land=np.array([land], dtype=object))
    want, _ = ground_area_perimeter(shapely.intersection(hist, land))
    old_wrong, _ = ground_area_perimeter(shapely.intersection(hist, poly))
    got = float(pmem.iloc[0]["intersection_ground_km2"])
    assert abs(got - want) < 1e-3
    assert old_wrong > want * 1.3  # the sea the old method counted
    assert float(pmem.iloc[0]["share_of_terrestrial_hex_land"]) <= 1.0


def test_same_polity_overlap_unioned_not_summed():
    poly = GRID.polygon(3, 3)
    b = poly.bounds
    a = shapely.box(b[0], b[1], b[0] + (b[2] - b[0]) * 0.6, b[3])
    c = shapely.box(b[0] + (b[2] - b[0]) * 0.3, b[1], b[2], b[3])
    snap = _snap_rows(_row("sp_a", a, "hbf_A"), _row("sp_a", c, "hbf_B"))
    fmem, pmem = _bind(snap, np.array([poly], dtype=object),
                       [GRID.hex_id(3, 3)])
    union_km2, _ = ground_area_perimeter(
        shapely.intersection(shapely.union(a, c), poly))
    got = float(pmem.iloc[0]["intersection_ground_km2"])
    naive = float(fmem["intersection_ground_km2"].sum())
    assert abs(got - union_km2) < 1e-3
    assert naive > union_km2 * 1.2  # double counting eliminated
    assert pmem.iloc[0]["contributing_boundary_feature_ids"] \
        == "hbf_A|hbf_B"


def test_share_above_one_raises_never_clips(monkeypatch):
    """share = (poly ∩ land)/land is <= 1 by construction; the guard
    exists against measurement regressions. Force the abnormality via a
    corrupted area function and prove the code RAISES instead of
    silently clipping."""
    import mapgen.historical_binding as hb

    real = hb._g_km2
    poly = GRID.polygon(4, 4)
    hex_km2 = real(poly)
    half = shapely.box(poly.bounds[0], poly.bounds[1],
                       (poly.bounds[0] + poly.bounds[2]) / 2,
                       poly.bounds[3])

    def corrupted(geom):
        v = real(geom)
        # inflate the political intersection only; the hex-land
        # denominator (the full hex) is measured correctly
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
    border = pmem[pmem["border_hex"]]
    assert len(border) > 0
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
    dom = pmem[pmem["is_dominant"]]
    assert list(dom["scenario_polity_id"]) == ["sp_a"]


def test_winner_loss_distortion_visible():
    """49/51 hex: conservation keeps the loser's area, the winner audit
    shows the REAL omission (the old conflated audit said GOOD)."""
    poly = GRID.polygon(7, 7)
    b = poly.bounds
    xcut = b[0] + (b[2] - b[0]) * 0.49
    ga = shapely.box(b[0] - 1e4, b[1] - 1e4, xcut, b[3] + 1e4)
    gb = shapely.box(xcut, b[1] - 1e4, b[2] + 1e4, b[3] + 1e4)
    snap = _snap_rows(_row("sp_a", ga), _row("sp_b", gb))
    _, pmem = _bind(snap, np.array([poly], dtype=object),
                    [GRID.hex_id(7, 7)])
    cons = membership_conservation_audit(snap, pmem, poly)
    a_cons = cons[cons["scenario_polity_id"] == "sp_a"].iloc[0]
    assert abs(a_cons["conservation_error_km2"]) < 0.01
    hexa = hexification_audit(snap, pmem, {GRID.hex_id(7, 7): poly},
                              poly)
    a_row = hexa[hexa["scenario_polity_id"] == "sp_a"].iloc[0]
    b_row = hexa[hexa["scenario_polity_id"] == "sp_b"].iloc[0]
    assert a_row["winner_represented_ground_km2"] == 0.0
    assert a_row["omission_ground_km2"] \
        > a_row["source_land_ground_km2"] * 0.95
    assert a_row["representation_status"] == "ZERO_HEX_LOSS"
    # winner over-represents: commission = the loser's 49%
    assert b_row["commission_ground_km2"] \
        > b_row["source_land_ground_km2"] * 0.5


def test_membership_conservation_on_covering_hexes():
    box = shapely.box(3000, 3000, 27000, 27000)
    q, r = GRID.hexes_covering_bbox(*box.bounds)
    polys, ids = GRID.polygons(q, r), GRID.hex_ids(q, r)
    snap = _snap_rows(_row("sp_a", box))
    _, pmem = _bind(snap, polys, ids)
    land_union = shapely.union_all(polys)
    cons = membership_conservation_audit(snap, pmem, land_union)
    assert abs(cons.iloc[0]["conservation_error_km2"]) \
        <= max(1e-3, cons.iloc[0]["source_land_ground_km2"] * 1e-4)


def test_zero_hex_loss_overlay_candidate_with_provenance():
    polys, ids = _hexes(3)
    cx, cy = np.asarray(GRID.axial_to_xy(1, 1), dtype=float)
    big = shapely.box(cx - 2e4, cy - 2e4, cx + 2e4, cy + 2e4)
    tiny = shapely.Point(float(cx) + 2500, float(cy)).buffer(120)
    snap = _snap_rows(_row("sp_a", big), _row("sp_b", tiny))
    _, pmem = _bind(snap, polys, ids)
    hexa = hexification_audit(
        snap, pmem, dict(zip(ids, polys)), shapely.union_all(polys))
    cands = overlay_candidates_from_audit(hexa, snap)
    assert list(cands["scenario_polity_id"]) == ["sp_b"]
    assert cands.iloc[0]["political_evidence_id"] == "hev_syn"
    assert cands.iloc[0]["global_source_id"] == "hsrc_syn"
    # provenance mandatory: stripping it raises
    bad = snap.copy()
    bad["political_evidence_id"] = None
    with pytest.raises(ValueError, match="provenance"):
        overlay_candidates_from_audit(hexa, bad)


def test_control_provenance_required_and_claims_not_derived():
    polys, ids = _hexes(3)
    snap = _snap_rows(_row("sp_a", shapely.box(-1e5, -1e5, 1e5, 1e5)))
    _, pmem = _bind(snap, polys, ids)
    with pytest.raises(ValueError, match="provenance"):
        controls_from_membership(pmem, SC, {})
    ctrl = controls_from_membership(pmem, SC,
                                    {"sp_a": {"source_id": "hsrc_syn"}})
    assert (ctrl["source_id"] == "hsrc_syn").all()
    assert "boundary_feature_ids" in ctrl.columns
    assert "claimant_scenario_polity_id" not in ctrl.columns


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
    assert len(s.polities) == 66
    assert len(s.scenario_polity_relationships) == 46
    feats = gpd.read_parquet(DATA / "historical"
                             / "historical_boundary_features.parquet")
    assert len(feats) == 0
    assertions = pd.read_csv(
        DATA / "historical" / "historical_evidence_assertions.csv")
    halc = assertions[assertions["assertion_type"]
                      == "GEOMETRIC_SUBSTRATE_ONLY"]
    assert len(halc) == 1
    assert halc.iloc[0]["political_authority"] == "NO"
    man = pd.read_csv(
        "output/europe_foundation_20260811/europe_hex_chunk_manifest.csv")
    assert int(man["hex_count"].sum()) == 1885422
