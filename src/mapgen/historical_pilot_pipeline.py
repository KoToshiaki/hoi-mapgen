"""MAPGEN-011/011R/011R2 — historical production gate + Low Countries pilot.

HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM MODERN
ADMINISTRATION. The MAPGEN-011 outcome (HALC v15.0 acquired, 1500-only,
SOURCE_GAP, zero production rows) is FROZEN. MAPGEN-011R hardened the
binding semantics; MAPGEN-011R2 finalises evidence semantics: bundle
compatibility (existence never authorises a boundary), geometry
authority, temporal continuity bridges, ordinal confidence, union-based
component counting, multi-subject provenance and a single land-mask
authority. Every gate is proven each run by synthetic fixtures — never
by an empty table.
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from .config import MapgenConfig
from .hex_grid import HexGrid
from .historical_binding import (BINDING_METHOD, bind_snapshot_to_hexes,
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
from .historical_geometry import (BOUNDARY_FEATURE_COLUMNS,
                                  CONFIDENCE_ORDER, EVIDENCE_ROLES,
                                  FEATURE_EVIDENCE_LINK_COLUMNS,
                                  FEATURE_ROLE_REQUIREMENTS,
                                  GAMEPLAY_CONVERTIBLE_ROLES,
                                  HPG_ALGORITHM_VERSION,
                                  HPG_SCHEMA_VERSION,
                                  load_evidence_assertions,
                                  load_feature_evidence_links,
                                  load_global_sources,
                                  make_evidence_assertion_id,
                                  make_global_source_id,
                                  select_features_for_snapshot,
                                  worst_confidence)
from .human_geography_pipeline import _save
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, load_scenario,
                       make_scenario_polity_id, scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .sources import sha256_of

STAGE = "MAPGEN-011R2"
SNAPSHOT_DATE = "1756-08-01"
HALC_DIR = Path("data/raw/historical_atlas_low_countries")
HALC_FILES = ["HALC_1500.gpkg", "HALC_Localities.gpkg",
              "HALC_Codebook.xlsx", "HALC_Unidentified.gpkg",
              "HALC_Unidentified_Localities.gpkg"]
SYN = "SYNTHETIC SEMANTICS TEST (never production data)"
HALC_SUBJECT = "low_countries_localities"


# --------------------------------------------------------------------------
# In-run synthetic fixtures — the gates must never be vacuous
# --------------------------------------------------------------------------
def _syn_sources():
    return pd.DataFrame([
        {"global_source_id": make_global_source_id("SYN_geom"),
         "citation_key": "SYN_geom",
         "authority_level": "BOUNDARY_AUTHORITY_CANDIDATE"},
        {"global_source_id": make_global_source_id("SYN_pol"),
         "citation_key": "SYN_pol",
         "authority_level": "ACADEMIC_REFERENCE"},
    ])


def _assertion(key, subject, atype, vf, vt, geom_auth, pol_auth, conf,
               locator="plate 3"):
    return {
        "historical_evidence_id": make_evidence_assertion_id(
            make_global_source_id(key), subject, atype, vf, vt),
        "global_source_id": make_global_source_id(key),
        "historical_subject_id": subject, "assertion_type": atype,
        "valid_from": vf, "valid_to": vt, "temporal_precision": "YEAR",
        "exact_locator": locator, "interpretation_level": "DIRECT",
        "confidence": conf, "geometry_authority": geom_auth,
        "political_authority": pol_auth, "notes": SYN,
    }


def _syn_assertions():
    S = "hsub_syn"
    rows = [
        _assertion("SYN_geom", S, "BOUNDARY_POSITION", "1756-01-01",
                   "1756-12-31", "YES", "NO", "HIGH"),
        _assertion("SYN_geom", S, "BOUNDARY_POSITION", "1750-01-01",
                   "1750-12-31", "YES", "NO", "HIGH"),
        _assertion("SYN_geom", S, "BOUNDARY_POSITION", "1756-02-01",
                   "1756-11-30", "NO", "NO", "HIGH"),   # no geom auth
        _assertion("SYN_pol", S, "POLITICAL_CONTROL", "1748-01-01",
                   "1763-12-31", "NO", "YES", "MEDIUM"),
        _assertion("SYN_pol", S, "DE_JURE_CLAIM", "1748-01-01",
                   "1763-12-31", "NO", "YES", "MEDIUM"),
        _assertion("SYN_pol", S, "POLITY_EXISTENCE", "1748-01-01",
                   "1763-12-31", "NO", "YES", "HIGH"),
        _assertion("SYN_pol", S, "TERRITORIAL_CONTINUITY", "1750-01-01",
                   "1760-12-31", "NO", "YES", "LOW"),
        _assertion("SYN_pol", HALC_SUBJECT, "POLITICAL_CONTROL",
                   "1748-01-01", "1763-12-31", "NO", "YES", "MEDIUM"),
        _assertion("SYN_pol", HALC_SUBJECT, "TERRITORIAL_CONTINUITY",
                   "1500-01-01", "1700-12-31", "NO", "YES", "LOW"),
    ]
    return pd.DataFrame(rows)


def _aid(assertions, subject, atype, vf):
    m = assertions[(assertions["historical_subject_id"] == subject)
                   & (assertions["assertion_type"] == atype)
                   & (assertions["valid_from"] == vf)]
    return m.iloc[0]["historical_evidence_id"]


def _feature(fid, subject, role):
    return {"boundary_feature_id": fid, "historical_subject_id": subject,
            "feature_role": role}


def _links(fid, pairs):
    return pd.DataFrame([
        {"boundary_feature_id": fid, "historical_evidence_id": eid,
         "evidence_role": role, "is_required": "YES", "notes": SYN}
        for role, eid in pairs], columns=FEATURE_EVIDENCE_LINK_COLUMNS)


def _hexfix(grid, q=500, r=500):
    """One fully-terrestrial hex + its land mask (single authority)."""
    poly = grid.polygon(q, r)
    return poly, {grid.hex_id(q, r): poly}


def _snap_row(pid, geom, fid, subject="hsub_syn", conf="MEDIUM",
              evid="hev_syn", gsrc="hsrc_syn",
              role="POLITY_EXTERNAL_BOUNDARY"):
    return {"boundary_feature_id": fid, "historical_subject_id": subject,
            "scenario_polity_id": pid, "feature_role": role,
            "political_evidence_id": evid, "global_source_id": gsrc,
            "source_confidence": conf, "snapshot_date": SNAPSHOT_DATE,
            "geometry": geom}


def _snap(rows):
    return gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry")


def run_historical_pilot(cfg: MapgenConfig,
                         run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    hcfg = cfg.raw["human_geography"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"historical_pilot_r2_{_dt.datetime.now():%Y%m%d}"
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    val_rows: list[dict] = []

    def _check(check_id, ok, detail):
        val_rows.append({"run_id": run_id, "check_id": check_id,
                         "pass": bool(ok), "detail": str(detail)})
        if not ok:
            warnings.append(f"VALIDATION FAIL {check_id}: {detail}")

    grid = HexGrid(flat_to_flat=float(cfg.raw["terrain"]["hex_size_m"]),
                   orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)

    # ---- upstream SHA (before) ------------------------------------------
    geo_dir = cfg.output_dir / hcfg["upstream_run"]
    r9_dir = cfg.output_dir / scfg["mapgen009r_baseline_run"]
    m8_dir = (cfg.output_dir / scfg["mapgen008_baseline_run"]
              / "chatgpt_review")
    eu_dir = cfg.output_dir / scfg.get("mapgen010_run",
                                       "europe_foundation_20260811")
    sdir = scenarios_root(cfg.data_dir) / scenario_id
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        m8_dir / "territorial_control.csv",
        m8_dir / "territorial_claims.csv",
        r9_dir / "chatgpt_review" / "polities.csv",
        r9_dir / "chatgpt_review" / "scenario_polity_relationships.csv",
        eu_dir / "europe_hex_chunk_manifest.csv",
        sdir / "territorial_control.csv",
        sdir / "territorial_claims.csv",
    ]}

    # ---- load canonical historical tables --------------------------------
    t0 = time.perf_counter()
    from pyogrio import read_info

    info = read_info(HALC_DIR / "HALC_1500.gpkg")
    features = gpd.read_parquet(cfg.data_dir / "historical"
                                / "historical_boundary_features.parquet")
    reg = load_global_sources(cfg.data_dir)
    assertions = load_evidence_assertions(cfg.data_dir)
    links = load_feature_evidence_links(cfg.data_dir)
    assessment = pd.read_csv(cfg.data_dir / "historical"
                             / "historical_source_assessment.csv",
                             keep_default_na=False, na_values=[""])
    halc_src = make_global_source_id("historical_atlas_low_countries")
    halc_ass = assertions[assertions["global_source_id"] == halc_src]
    _check("R2-01_011R_regression",
           info["features"] == 14863 and len(features) == 0
           and (assessment["boundary_authority_for_1756"] == "NO").all()
           and all((HALC_DIR / f).exists() for f in HALC_FILES)
           and len(halc_ass) == 1
           and halc_ass.iloc[0]["assertion_type"]
           == "GEOMETRIC_SUBSTRATE_ONLY"
           and halc_ass.iloc[0]["political_authority"] == "NO",
           "MAPGEN-011/011R frozen: HALC v15.0 (14,863 localities, "
           "1500-only), SOURCE_GAP, 0 production features, HALC "
           "assertion still GEOMETRIC_SUBSTRATE_ONLY / political NO")
    _check("R2-02_assertion_type_compatibility",
           set(FEATURE_ROLE_REQUIREMENTS) == GAMEPLAY_CONVERTIBLE_ROLES
           and "UNCERTAIN_BOUNDARY" not in GAMEPLAY_CONVERTIBLE_ROLES
           and FEATURE_ROLE_REQUIREMENTS[
               "DE_FACTO_CONTROL_BOUNDARY"]["POLITICAL_STATUS"]
           == {"POLITICAL_CONTROL"}
           and FEATURE_ROLE_REQUIREMENTS[
               "DE_JURE_CLAIM_BOUNDARY"]["CLAIM_STATUS"]
           == {"DE_JURE_CLAIM"}
           and set(EVIDENCE_ROLES) >= {"GEOMETRY_SHAPE",
                                       "POLITICAL_STATUS",
                                       "TEMPORAL_CONTINUITY",
                                       "CLAIM_STATUS",
                                       "CONTESTED_STATUS"},
           f"compatibility matrix defined for "
           f"{len(FEATURE_ROLE_REQUIREMENTS)} convertible feature roles; "
           "UNCERTAIN_BOUNDARY is review/audit geometry only")
    timings["load_s"] = time.perf_counter() - t0

    # ---- bundle gate fixtures (executed EVERY run) ----------------------
    t0 = time.perf_counter()
    reg_fx = pd.concat([reg, _syn_sources()], ignore_index=True)
    ass_fx = pd.concat([assertions, _syn_assertions()], ignore_index=True)
    S = "hsub_syn"
    A_geom56 = _aid(ass_fx, S, "BOUNDARY_POSITION", "1756-01-01")
    A_geom50 = _aid(ass_fx, S, "BOUNDARY_POSITION", "1750-01-01")
    A_geom_noauth = _aid(ass_fx, S, "BOUNDARY_POSITION", "1756-02-01")
    A_pol = _aid(ass_fx, S, "POLITICAL_CONTROL", "1748-01-01")
    A_claim = _aid(ass_fx, S, "DE_JURE_CLAIM", "1748-01-01")
    A_exist = _aid(ass_fx, S, "POLITY_EXISTENCE", "1748-01-01")
    A_cont = _aid(ass_fx, S, "TERRITORIAL_CONTINUITY", "1750-01-01")
    A_halc = halc_ass.iloc[0]["historical_evidence_id"]
    A_pol_lc = _aid(ass_fx, HALC_SUBJECT, "POLITICAL_CONTROL",
                    "1748-01-01")
    A_cont_gap = _aid(ass_fx, HALC_SUBJECT, "TERRITORIAL_CONTINUITY",
                      "1500-01-01")

    def _bundle(fid, subject, role, pairs):
        return evaluate_feature_bundle(
            _feature(fid, subject, role), _links(fid, pairs), ass_fx,
            reg_fx, SNAPSHOT_DATE)

    v_exist, _ = _bundle("f_exist", S, "POLITY_EXTERNAL_BOUNDARY",
                         [("GEOMETRY_SHAPE", A_exist),
                          ("POLITICAL_STATUS", A_exist)])
    _check("R2-03_polity_existence_cannot_authorise_boundary",
           any("assertion_type POLITY_EXISTENCE" in x for x in v_exist)
           and len(v_exist) >= 2,
           f"POLITY_EXISTENCE (political_authority=YES, exact locator, "
           f"1756 validity) rejected for both required roles: "
           f"{len(v_exist)} violations — existence is not boundary "
           "authority")
    v_noauth, _ = _bundle("f_noauth", S, "POLITY_EXTERNAL_BOUNDARY",
                          [("GEOMETRY_SHAPE", A_geom_noauth),
                           ("POLITICAL_STATUS", A_pol)])
    _check("R2-04_geometry_authority_required",
           any("geometry_authority != YES" in x for x in v_noauth),
           "GEOMETRY_SHAPE evidence with geometry_authority=NO rejected")
    v_df, _ = _bundle("f_df", S, "DE_FACTO_CONTROL_BOUNDARY",
                      [("GEOMETRY_SHAPE", A_geom56),
                       ("POLITICAL_STATUS", A_claim)])
    _check("R2-05_de_facto_requires_control_evidence",
           any("requires one of ['POLITICAL_CONTROL']" in x
               for x in v_df),
           "DE_FACTO_CONTROL_BOUNDARY backed by DE_JURE_CLAIM rejected")
    v_dj, _ = _bundle("f_dj", S, "DE_JURE_CLAIM_BOUNDARY",
                      [("GEOMETRY_SHAPE", A_geom56),
                       ("CLAIM_STATUS", A_pol)])
    _check("R2-06_de_jure_requires_claim_evidence",
           any("requires one of ['DE_JURE_CLAIM']" in x for x in v_dj),
           "DE_JURE_CLAIM_BOUNDARY backed by POLITICAL_CONTROL rejected")
    v_nocont, _ = _bundle("f_halc", HALC_SUBJECT,
                          "POLITY_EXTERNAL_BOUNDARY",
                          [("GEOMETRY_SHAPE", A_halc),
                           ("POLITICAL_STATUS", A_pol_lc)])
    _check("R2-07_temporal_continuity_bridge_required",
           any("no TERRITORIAL_CONTINUITY bridge" in x
               for x in v_nocont),
           "REAL HALC 1500 geometry + 1756 political control, without a "
           "continuity bridge, is rejected (interpolation forbidden)")
    v_gap, _ = _bundle("f_halc2", HALC_SUBJECT,
                       "POLITY_EXTERNAL_BOUNDARY",
                       [("GEOMETRY_SHAPE", A_halc),
                        ("TEMPORAL_CONTINUITY", A_cont_gap),
                        ("POLITICAL_STATUS", A_pol_lc)])
    _check("R2-08_continuity_gap_rejected",
           any("has a gap" in x for x in v_gap),
           "continuity bridge 1500-1700 leaves a 1700->1756 gap and is "
           "rejected")
    v_ok1, i_ok1 = _bundle("f_ok1", S, "DE_FACTO_CONTROL_BOUNDARY",
                           [("GEOMETRY_SHAPE", A_geom56),
                            ("POLITICAL_STATUS", A_pol)])
    v_ok2, i_ok2 = _bundle("f_ok2", S, "DE_FACTO_CONTROL_BOUNDARY",
                           [("GEOMETRY_SHAPE", A_geom50),
                            ("TEMPORAL_CONTINUITY", A_cont),
                            ("POLITICAL_STATUS", A_pol)])
    _check("R2-09_valid_multi_evidence_bundle_passes",
           v_ok1 == [] and v_ok2 == []
           and i_ok1["confidence"] == "MEDIUM"
           and i_ok2["confidence"] == "LOW"
           and "TEMPORAL_CONTINUITY" in i_ok2["roles"],
           "direct-1756 bundle PASSES (confidence HIGH+MEDIUM=MEDIUM); "
           "1750-geometry + 1750-1760 continuity + 1756 control also "
           "PASSES (HIGH+LOW+MEDIUM=LOW)")
    _check("R2-10_confidence_ordinal",
           worst_confidence(["HIGH", "MEDIUM"]) == "MEDIUM"
           and worst_confidence(["HIGH", "LOW"]) == "LOW"
           and worst_confidence(["MEDIUM", "UNKNOWN"]) == "UNKNOWN"
           and worst_confidence([]) == "UNKNOWN"
           and min(["HIGH", "MEDIUM"]) == "HIGH"
           and CONFIDENCE_ORDER == ["UNKNOWN", "LOW", "MEDIUM", "HIGH"],
           "worst-of-bundle on the explicit ordinal; the old string "
           "min() would have returned HIGH for HIGH+MEDIUM")
    a_int = validate_assertion_table(ass_fx, reg_fx)
    l_int = validate_feature_evidence_links(links, features, assertions)
    _check("R2-21_assertion_table_integrity",
           a_int == [] and l_int == []
           and assertions["historical_evidence_id"].is_unique,
           f"{len(assertions)} production assertions + fixtures pass "
           "integrity (enums, date order, registered sources, duplicate "
           "semantics, orphan links)")
    timings["bundle_gates_s"] = time.perf_counter() - t0

    # ---- binding / audit semantics fixtures ------------------------------
    t0 = time.perf_counter()
    poly, land_by_id = _hexfix(grid)
    hid = list(land_by_id)[0]
    b = poly.bounds
    from .islands import ground_area_perimeter as _gap

    # exact-land retention (011R proof, coastal hex)
    xmid = b[0] + (b[2] - b[0]) * 0.6
    coast_land = shapely.intersection(
        poly, shapely.box(b[0] - 1e4, b[1] - 1e4, xmid, b[3] + 1e4))
    hist = shapely.box(b[0] + (b[2] - b[0]) * 0.3, b[1] - 1e4,
                       b[2] + 5e4, b[3] + 1e4)
    _, pm_coast = bind_snapshot_to_hexes(
        _snap([_snap_row("sp_syn", hist, "hbf_coast")]),
        np.array([poly], dtype=object), [hid],
        np.array([coast_land], dtype=object), np.array([True]),
        scenario_id, SNAPSHOT_DATE)
    exact_km2 = _gap(shapely.intersection(hist, coast_land))[0]
    fullhex_km2 = _gap(shapely.intersection(hist, poly))[0]
    _check("R2-24_exact_land_binding_retained",
           abs(float(pm_coast.iloc[0]["intersection_ground_km2"])
               - exact_km2) < 1e-3
           and float(pm_coast.iloc[0]["share_of_terrestrial_hex_land"])
           <= 1.0 and fullhex_km2 > exact_km2 * 1.3,
           f"coastal hex: counted {exact_km2:.2f} km2 (polygon ∩ land); "
           f"the pre-011R full-hex numerator would have counted "
           f"{fullhex_km2:.2f} km2 including sea")
    # same-polity union + union component count + multi-subject
    a_geom = shapely.box(b[0], b[1], b[0] + (b[2] - b[0]) * 0.6, b[3])
    c_geom = shapely.box(b[0] + (b[2] - b[0]) * 0.3, b[1], b[2], b[3])
    snap_u = _snap([
        _snap_row("sp_syn", a_geom, "hbf_A", subject="hsub_north",
                  conf="HIGH", evid="hev_a", gsrc="hsrc_a"),
        _snap_row("sp_syn", c_geom, "hbf_B", subject="hsub_south",
                  conf="LOW", evid="hev_b", gsrc="hsrc_b")])
    fm_u, pm_u = bind_snapshot_to_hexes(
        snap_u, np.array([poly], dtype=object), [hid],
        np.array([poly], dtype=object), np.array([True]),
        scenario_id, SNAPSHOT_DATE)
    union_km2 = _gap(shapely.intersection(
        shapely.union(a_geom, c_geom), poly))[0]
    naive_km2 = float(fm_u["intersection_ground_km2"].sum())
    _check("R2-25_same_polity_union_retained",
           abs(float(pm_u.iloc[0]["intersection_ground_km2"])
               - union_km2) < 1e-3 and naive_km2 > union_km2 * 1.2,
           f"overlapping same-polity features unioned to "
           f"{union_km2:.2f} km2; naive per-feature sum would be "
           f"{naive_km2:.2f} km2")
    hexa_u = hexification_audit(snap_u, pm_u, land_by_id)
    _check("R2-11_union_component_count",
           int(hexa_u.iloc[0]["source_component_count"]) == 1,
           "two overlapping/adjacent features union to ONE connected "
           "component (per-feature part counting would have said 2 and "
           "falsely raised ENCLAVE_AT_RISK)")
    _check("R2-12_multi_subject_provenance",
           pm_u.iloc[0]["contributing_historical_subject_ids"]
           == "hsub_north|hsub_south"
           and hexa_u.iloc[0]["contributing_historical_subject_ids"]
           == "hsub_north|hsub_south"
           and pm_u.iloc[0]["source_confidence"] == "LOW",
           "membership and audit keep ALL contributing historical "
           "subjects (not feats[0] only); confidence is the ordinal "
           "worst (HIGH+LOW=LOW)")
    # winner distortion retained (49/51)
    xcut = b[0] + (b[2] - b[0]) * 0.49
    ga = shapely.box(b[0] - 1e4, b[1] - 1e4, xcut, b[3] + 1e4)
    gb = shapely.box(xcut, b[1] - 1e4, b[2] + 1e4, b[3] + 1e4)
    snap_w = _snap([
        _snap_row("sp_a", ga, "hbf_A49", subject="hsub_a"),
        _snap_row("sp_b", gb, "hbf_B51", subject="hsub_b")])
    _, pm_w = bind_snapshot_to_hexes(
        snap_w, np.array([poly], dtype=object), [hid],
        np.array([poly], dtype=object), np.array([True]),
        scenario_id, SNAPSHOT_DATE)
    cons_w = membership_conservation_audit(snap_w, pm_w, land_by_id)
    hexa_w = hexification_audit(snap_w, pm_w, land_by_id)
    a_cons = cons_w[cons_w["scenario_polity_id"] == "sp_a"].iloc[0]
    a_row = hexa_w[hexa_w["scenario_polity_id"] == "sp_a"].iloc[0]
    _check("R2-26_winner_distortion_retained",
           abs(a_cons["conservation_error_km2"]) < 0.01
           and a_row["winner_represented_ground_km2"] == 0.0
           and a_row["representation_status"] == "ZERO_HEX_LOSS",
           f"49/51 hex: conservation error "
           f"{a_cons['conservation_error_km2']} km2 (bookkeeping OK) "
           f"but winner omission {a_row['omission_ground_km2']} km2 "
           "(real gameplay loss)")
    try:
        membership_conservation_audit(
            snap_w, pm_w, land_by_id,
            land_union=shapely.buffer(poly, -1000.0))
        mask_ok = False
    except ValueError:
        mask_ok = True
    _check("R2-13_land_union_single_authority",
           mask_ok
           and land_union_from(land_by_id).equals(
               shapely.union_all(list(land_by_id.values()))),
           "audits derive the land union from the SAME per-hex mask the "
           "binding used; a divergent explicit union raises instead of "
           "being silently accepted")
    ov_w = overlay_candidates_from_audit(hexa_w, snap_w)
    _check("R2-09b_zero_hex_provenance",
           len(ov_w) == 1 and ov_w.iloc[0]["political_evidence_id"]
           == "hev_syn" and ov_w.iloc[0]["global_source_id"]
           == "hsrc_syn"
           and ov_w.iloc[0]["historical_subject_ids"] == "hsub_a",
           "zero-hex loss becomes an overlay candidate with evidence, "
           "source and subject provenance")
    ctrl_fx = controls_from_membership(pm_u, scenario_id)
    single = controls_from_membership(pm_w, scenario_id)
    try:
        bad = pm_w.copy()
        bad["contributing_global_source_ids"] = ""
        controls_from_membership(bad, scenario_id)
        prov_raises = False
    except ValueError:
        prov_raises = True
    _check("R2-14_control_provenance_bundle",
           prov_raises
           and ctrl_fx.iloc[0]["source_ids"] == "hsrc_a|hsrc_b"
           and ctrl_fx.iloc[0]["source_id"] == compiled_provenance_id(
               ["hsrc_a", "hsrc_b"],
               [ctrl_fx.iloc[0]["political_evidence_ids"]],
               [ctrl_fx.iloc[0]["boundary_feature_ids"]])
           and single.iloc[0]["source_id"] == "hsrc_syn"
           and set(["source_ids", "political_evidence_ids",
                    "boundary_feature_ids", "historical_subject_ids"])
           <= set(ctrl_fx.columns),
           "multi-source control rows reference a deterministic "
           "compiled provenance record (source_id) and keep the full id "
           "sets in additive columns; single-source rows keep the real "
           "source id; missing provenance raises")
    _check("R2-15_claims_not_derived",
           "claimant_scenario_polity_id" not in ctrl_fx.columns
           and (ctrl_fx["control_status"] == "CONTROLLED").all(),
           "claims are never generated from control")
    _, pm_ocean = bind_snapshot_to_hexes(
        snap_w, np.array([poly], dtype=object), [hid],
        np.array([poly], dtype=object), np.array([False]),
        scenario_id, SNAPSHOT_DATE)
    _check("R2-22_ocean_never_terrestrial_target", len(pm_ocean) == 0,
           "OCEAN hexes produce zero terrestrial membership")
    timings["binding_semantics_s"] = time.perf_counter() - t0

    # ---- production state (still SOURCE_GAP) ----------------------------
    t0 = time.perf_counter()
    prod_violations = validate_production_features(
        features, reg, assertions, links,
        pd.DataFrame(columns=["historical_subject_id",
                              "scenario_polity_id"]), SNAPSHOT_DATE)
    snap_prod = gpd.GeoDataFrame(
        {c: pd.Series(dtype="object") for c in
         ["boundary_feature_id", "historical_subject_id",
          "scenario_polity_id", "feature_role", "political_evidence_id",
          "global_source_id", "source_confidence", "snapshot_date"]},
        geometry=gpd.GeoSeries([], crs="EPSG:3857"))
    snap_prod.to_parquet(
        run_dir / "historical_snapshot_features_1756_08_01.parquet")
    sel = select_features_for_snapshot(features, SNAPSHOT_DATE)
    fmem_p, pmem_p = bind_snapshot_to_hexes(
        snap_prod, np.array([], dtype=object), [],
        np.array([], dtype=object), np.array([], dtype=bool),
        scenario_id, SNAPSHOT_DATE)
    fmem_p.to_parquet(run_dir
                      / "historical_hex_feature_membership.parquet")
    pmem_p.to_parquet(run_dir / "historical_hex_membership.parquet")
    cons_p = membership_conservation_audit(snap_prod, pmem_p, {})
    cons_p.to_csv(run_dir / "membership_conservation_audit.csv",
                  index=False)
    hexa_p = hexification_audit(snap_prod, pmem_p, {})
    hexa_p.to_csv(run_dir / "historical_hexification_audit.csv",
                  index=False)
    ov_p = overlay_candidates_from_audit(hexa_p, snap_prod)
    ov_p.to_csv(run_dir / "historical_political_overlay_candidates.csv",
                index=False)
    _check("R2-16_SOURCE_GAP_still_zero",
           len(features) == 0 and len(links) == 0 and len(sel) == 0
           and len(pmem_p) == 0 and len(hexa_p) == 0 and len(ov_p) == 0
           and prod_violations == [],
           "production: 0 features / 0 evidence links / 0 snapshot / 0 "
           "membership / 0 audits — synthetic fixtures were never "
           "written into production data")
    snap_ov = _snap([
        _snap_row("sp_a", a_geom, "hbf_OV_A", subject="hsub_a"),
        _snap_row("sp_b", c_geom, "hbf_OV_B", subject="hsub_b")])
    snap_ov_ok = snap_ov.copy()
    snap_ov_ok.loc[1, "feature_role"] = "DE_JURE_CLAIM_BOUNDARY"
    _check("R2-23_no_silent_contested_overlap",
           check_contested_overlaps(snap_prod) == []
           and len(check_contested_overlaps(snap_ov)) == 1
           and check_contested_overlaps(snap_ov_ok) == [],
           "two independent polities overlapping the same area without "
           "contested semantics is detected; the same pair passes once "
           "one side is DE_JURE_CLAIM_BOUNDARY (silent clipping stays "
           "forbidden)")
    timings["production_s"] = time.perf_counter() - t0

    # ---- regressions -----------------------------------------------------
    snapd = load_scenario(cfg.data_dir, scenario_id)
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    _check("R2-17_010_europe_regression",
           len(eu_man) == 50
           and int(eu_man["hex_count"].sum()) == 1885422
           and int(eu_man["terrestrial_count"].sum()) == 862795,
           "Europe coverage intact (50 chunks / 1,885,422 hexes / "
           "862,795 terrestrial)")
    tokugawa_sp = make_scenario_polity_id(scenario_id,
                                          "pol_tokugawa_shogunate")
    controllers = set(snapd.territorial_control[
        "controller_scenario_polity_id"].dropna())
    _check("R2-18_009r2_scenario_regression",
           len(snapd.polities) == 66
           and len(snapd.scenario_polity_relationships) == 46
           and controllers == {tokugawa_sp}
           and int((snapd.scenario_polity_inclusion_audit[
               "audit_record_status"] == "SUPERSEDED").sum()) == 1,
           "66 polities / 46 relationships / Tokugawa-only control / "
           "ACTIVE-SUPERSEDED audit intact")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    _check("R2-19_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN",
           "Toshima underlying hex stays OCEAN")
    forb = (scan_forbidden_reference_code(
        Path(__file__).parent / "historical_binding.py")
        + scan_forbidden_reference_code(
            Path(__file__).parent / "historical_geometry.py"))
    _check("R2-27_modern_admin_generation_forbidden", not forb,
           f"AST scan of the binding/geometry data layers clean "
           f"(hits={forb or 0})")
    _check("R2-20_versions",
           HPG_SCHEMA_VERSION == "1.3.0"
           and HPG_ALGORITHM_VERSION == "1.2.0"
           and SCENARIO_SCHEMA_VERSION == "1.4.0",
           f"hpg schema {HPG_SCHEMA_VERSION} (feature-evidence link "
           f"table), algorithm {HPG_ALGORITHM_VERSION} (bundle "
           "compatibility + continuity + ordinal confidence + union "
           "components); determinism proved by a second run")

    # ---- renders ---------------------------------------------------------
    t0 = time.perf_counter()
    _render_bundle_contract(
        run_dir / "feature_evidence_bundle_contract.png", assertions,
        len(links))
    _render_matrix(run_dir / "assertion_role_compatibility_matrix.png")
    _render_continuity(run_dir / "temporal_continuity_bridge.png")
    from PIL import Image

    img_names = ["feature_evidence_bundle_contract.png",
                 "assertion_role_compatibility_matrix.png",
                 "temporal_continuity_bridge.png"]
    aspects = {}
    for n in img_names:
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.size[0] / im.size[1], 3)
    _check("R2-28_renders",
           all(0.3 <= a <= 4.0 for a in aspects.values()),
           f"{len(img_names)} renders, aspects={aspects} (synthetic "
           "panels labelled SYNTHETIC SEMANTICS TEST)")
    timings["render_s"] = time.perf_counter() - t0

    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("R2-29_upstream_immutable", up_after == upstream,
           f"{len(upstream)} upstream files byte-identical before/after")

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "pilot_validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    summary_rows = [
        ("stage", STAGE),
        ("outcome", "evidence semantics finalisation — MAPGEN-011 "
                    "SOURCE_GAP frozen"),
        ("hpg_schema_version", HPG_SCHEMA_VERSION),
        ("hpg_algorithm_version", HPG_ALGORITHM_VERSION),
        ("evidence_assertions_registered", len(assertions)),
        ("feature_evidence_links", len(links)),
        ("convertible_feature_roles", len(FEATURE_ROLE_REQUIREMENTS)),
        ("evidence_roles", len(EVIDENCE_ROLES)),
        ("confidence_order", "|".join(CONFIDENCE_ORDER)),
        ("production_boundary_features", 0),
        ("snapshot_features_1756_08_01", 0),
        ("hex_membership_rows", 0),
        ("new_control_rows", 0),
        ("existence_authorises_boundary", "REJECTED"),
        ("continuity_bridge_required", "YES (gaps rejected)"),
        ("control_provenance", "compiled provenance record + additive "
                               "id sets"),
        ("validation_pass", f"{n_pass}/{len(val)}"),
    ]
    pd.DataFrame(summary_rows, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "pilot_summary.csv", index=False)
    manifest = {
        "run_id": run_id, "stage": STAGE,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "hpg_schema_version": HPG_SCHEMA_VERSION,
        "hpg_algorithm_version": HPG_ALGORITHM_VERSION,
        "version_reasons": {
            "hpg_schema_1.3.0": "additive feature<->evidence link table "
                                "(many-to-many with evidence_role); the "
                                "single political_evidence_id columns "
                                "become deprecated aliases",
            "hpg_algorithm_1.2.0": "production admission evaluates the "
                                   "evidence BUNDLE against a role "
                                   "compatibility matrix, requires "
                                   "geometry_authority and an unbroken "
                                   "continuity bridge, aggregates "
                                   "confidence on an ordinal, counts "
                                   "components on the unioned land "
                                   "geometry and shares one land mask "
                                   "between binding and audits",
        },
        "control_provenance_design": (
            "scenario territorial_control keeps a SINGULAR source_id; "
            "single-source rows carry the real source id, multi-source "
            "rows carry a deterministic compiled provenance record id "
            "(prov_<sha1>) while source_ids / political_evidence_ids / "
            "boundary_feature_ids / historical_subject_ids keep the "
            "full sets"),
        "binding_method": BINDING_METHOD,
        "upstream_sha256": upstream,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8")
    _write_readme(run_dir, run_id, assertions, links, val, aspects)
    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    hdir = cfg.data_dir / "historical"
    copies = {
        "README_REVIEW.md": run_dir / "README_REVIEW.md",
        "run_manifest.json": run_dir / "run_manifest.json",
        "validation.csv": run_dir / "pilot_validation.csv",
        "summary.csv": run_dir / "pilot_summary.csv",
        "historical_evidence_assertions.csv":
            hdir / "historical_evidence_assertions.csv",
        "historical_boundary_feature_evidence.csv":
            hdir / "historical_boundary_feature_evidence.csv",
        "historical_source_assessment.csv":
            hdir / "historical_source_assessment.csv",
        "historical_source_registry.csv":
            hdir / "historical_source_registry.csv",
        "membership_conservation_audit.csv":
            run_dir / "membership_conservation_audit.csv",
        "historical_hexification_audit.csv":
            run_dir / "historical_hexification_audit.csv",
        "historical_political_overlay_candidates.csv":
            run_dir / "historical_political_overlay_candidates.csv",
        "scenario_political_coverage.csv": sdir / "political_coverage.csv",
    }
    for dst, src in copies.items():
        shutil.copy2(src, review / dst)
    pd.DataFrame(gpd.read_parquet(
        hdir / "historical_boundary_features.parquet").drop(
        columns="geometry")).to_csv(
        review / "historical_boundary_features.csv", index=False)
    pd.read_parquet(run_dir / "historical_hex_membership.parquet").to_csv(
        review / "historical_hex_membership.csv", index=False)
    for n in img_names:
        shutil.copy2(run_dir / n, review / n)
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"[pilot] {run_id}: validation {n_pass}/{len(val)}, evidence "
          "bundle contract enforced, production rows still 0 "
          f"({timings['total_s']:.0f}s)")
    for w in warnings:
        print(f"[pilot][WARN] {w}")
    return run_dir


# --------------------------------------------------------------------------
# Renders
# --------------------------------------------------------------------------
def _render_bundle_contract(path, assertions, n_links):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(14, 8.5))

    def box(x, y, w, h, text, fc, fs=9):
        ax.add_patch(plt.Rectangle((x, y), w, h, fc=fc, ec="#333333",
                                   lw=1.2, zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, zorder=3)

    box(0.02, 0.66, 0.22, 0.26,
        "SOURCE (hsrc_)\n\nwhat a work IS:\nauthority level,\nlicence, "
        "dates", "#efe9d6")
    box(0.28, 0.66, 0.30, 0.26,
        "EVIDENCE ASSERTION (hev_)\n\nwhat ONE LOCATOR proves:\nsubject "
        "· dates · locator\ngeometry_authority\npolitical_authority\n"
        "confidence", "#dce7f2")
    box(0.62, 0.66, 0.36, 0.26,
        "FEATURE-EVIDENCE LINK (many-to-many)\n\nevidence_role:\n"
        "GEOMETRY_SHAPE · POLITICAL_STATUS\nTEMPORAL_CONTINUITY · "
        "CLAIM_STATUS\nCONTESTED_STATUS · SUPPORTING · QA_ONLY",
        "#e8dff0")
    for x0, x1 in ((0.24, 0.28), (0.58, 0.62)):
        ax.annotate("", xy=(x1, 0.79), xytext=(x0, 0.79),
                    arrowprops={"arrowstyle": "->", "lw": 2})
    box(0.20, 0.40, 0.60, 0.18,
        "BOUNDARY FEATURE (hbf_) — admitted only by a COMPLETE BUNDLE\n"
        "role-compatible assertions + geometry authority + continuity "
        "bridge + snapshot coverage", "#f7dcd7", 10)
    ax.annotate("", xy=(0.5, 0.58), xytext=(0.5, 0.66),
                arrowprops={"arrowstyle": "->", "lw": 2.5})
    box(0.06, 0.06, 0.88, 0.28,
        "REJECTED EVERY RUN (synthetic negative fixtures):\n"
        "  POLITY_EXISTENCE as boundary authority · DE_FACTO backed by "
        "DE_JURE_CLAIM · DE_JURE backed by POLITICAL_CONTROL\n"
        "  geometry_authority=NO · HALC-1500 geometry without a "
        "continuity bridge · continuity bridge with a 1700-1756 gap\n\n"
        "ACCEPTED: 1756 geometry + 1756 control  ·  1750 geometry + "
        "1750-1760 continuity + 1756 control\n\n"
        f"production assertions: {len(assertions)}   production "
        f"feature-evidence links: {n_links} (SOURCE_GAP)", "#ddead9", 9)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_title("MAPGEN-011R2: source -> assertion -> bundle -> feature",
                 fontsize=11)
    _save(fig, path)


def _render_matrix(path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    roles = list(FEATURE_ROLE_REQUIREMENTS) + ["UNCERTAIN_BOUNDARY"]
    cols = ["GEOMETRY_SHAPE", "POLITICAL_STATUS", "CLAIM_STATUS",
            "CONTESTED_STATUS", "TEMPORAL_CONTINUITY"]
    fig, ax = plt.subplots(figsize=(13, 6.5))
    for j, c in enumerate(cols):
        ax.text(j + 0.5, len(roles) + 0.15, c.replace("_", "\n"),
                ha="center", va="bottom", fontsize=8)
    for i, r in enumerate(roles):
        y = len(roles) - 1 - i
        ax.text(-0.12, y + 0.5, r.replace("_", " "), ha="right",
                va="center", fontsize=8)
        req = FEATURE_ROLE_REQUIREMENTS.get(r)
        for j, c in enumerate(cols):
            if req is None:
                fc, txt = "#d9d9d9", "n/a"
            elif c in req:
                fc = "#ddead9"
                txt = "\n".join(sorted(req[c])).replace(
                    "GEOMETRIC_SUBSTRATE_ONLY",
                    "GEOM. SUBSTRATE").replace("_", " ")
            elif c == "TEMPORAL_CONTINUITY":
                fc, txt = "#fdf1d6", "required\nif geometry\noff-date"
            else:
                fc, txt = "#f2f2f2", "—"
            ax.add_patch(plt.Rectangle((j, y), 1, 1, fc=fc,
                                       ec="#666666", lw=0.8))
            ax.text(j + 0.5, y + 0.5, txt, ha="center", va="center",
                    fontsize=6.2)
    ax.text(len(cols) / 2, -0.55,
            "UNCERTAIN_BOUNDARY is review/audit geometry only — never "
            "convertible to gameplay control.\n"
            "POLITY_EXISTENCE and TOPOGRAPHIC_GEOREFERENCE_ONLY never "
            "authorise any boundary.",
            ha="center", fontsize=9)
    ax.set_xlim(-4.6, len(cols))
    ax.set_ylim(-1.0, len(roles) + 0.9)
    ax.set_axis_off()
    ax.set_title("Assertion-type compatibility matrix "
                 "(feature_role x evidence_role -> required "
                 "assertion_type)", fontsize=11)
    _save(fig, path)


def _render_continuity(path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(14, 7))
    x0, x1 = 1480, 1790
    snap_x = 1756.6

    def year(v):
        return (v - x0) / (x1 - x0)

    def bar(y, a, b, color, label, hatch=None):
        ax.add_patch(plt.Rectangle((year(a), y), year(b) - year(a), 0.07,
                                   fc=color, ec="#333333", lw=0.8,
                                   hatch=hatch))
        ax.text(year(a), y + 0.085, label, fontsize=8.5)

    ax.axvline(year(snap_x), color="#b03a2e", lw=2, ls="--")
    ax.text(year(snap_x) + 0.005, 0.95, "snapshot 1756-08-01",
            color="#b03a2e", fontsize=9)
    bar(0.80, 1500, 1501, "#dce7f2", "REJECTED: HALC 1500 geometry alone")
    bar(0.62, 1500, 1501, "#dce7f2", "REJECTED: geometry 1500 + "
        "continuity 1500-1700 (gap 1700 -> 1756)")
    bar(0.62, 1500, 1700, "#f7dcd7", "")
    ax.annotate("", xy=(year(snap_x), 0.655), xytext=(year(1700), 0.655),
                arrowprops={"arrowstyle": "<->", "color": "#b03a2e",
                            "lw": 1.5})
    ax.text(year(1720), 0.68, "GAP — never interpolated", fontsize=8.5,
            color="#b03a2e")
    bar(0.40, 1750, 1751, "#dce7f2", "ACCEPTED: geometry 1750")
    bar(0.40, 1750, 1761, "#ddead9", "")
    ax.text(year(1762), 0.405, "TERRITORIAL_CONTINUITY 1750-1760 covers "
            "the snapshot", fontsize=8.5)
    bar(0.22, 1748, 1764, "#ddead9", "POLITICAL_CONTROL 1748-1763 "
        "(covers the snapshot)")
    for v in (1500, 1600, 1700, 1750, 1780):
        ax.text(year(v), 0.10, str(v), fontsize=8, ha="center")
        ax.plot([year(v), year(v)], [0.13, 0.15], color="#333333", lw=1)
    ax.plot([0, 1], [0.14, 0.14], color="#333333", lw=1)
    ax.set_xlim(-0.02, 1.06)
    ax.set_ylim(0.05, 1.02)
    ax.set_axis_off()
    ax.set_title("Temporal continuity bridge contract — "
                 f"{SYN}", fontsize=11)
    _save(fig, path)


def _write_readme(run_dir, run_id, assertions, links, val, aspects):
    lines = [
        f"# {STAGE} Review — Evidence Role Compatibility + Geometry "
        "Authority + Confidence Semantics Finalisation",
        "",
        "**HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM "
        "MODERN ADMINISTRATION.**",
        "**MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER "
        "NEUTRAL.**",
        "",
        f"Run `{run_id}`. MAPGEN-011 / 011R content is FROZEN (HALC "
        "v15.0 acquisition, 1500-only finding, SOURCE_GAP, 0 production "
        "rows, byte-identical control/claims, exact-land binding, "
        "same-polity union, conservation/winner audit split). This is "
        "the final MAPGEN-011 hardening stage.",
        "",
        "## What was closed",
        "",
        "- **assertion_type vs feature_role compatibility**: a feature "
        "is admitted only by an evidence BUNDLE that satisfies the "
        "matrix. POLITY_EXISTENCE can never authorise a boundary; "
        "DE_FACTO_CONTROL_BOUNDARY requires POLITICAL_CONTROL; "
        "DE_JURE_CLAIM_BOUNDARY requires DE_JURE_CLAIM; "
        "UNCERTAIN_BOUNDARY is never gameplay-convertible.",
        "- **geometry_authority is now enforced**: GEOMETRY_SHAPE "
        "evidence must carry geometry_authority=YES.",
        "- **temporal continuity bridge**: when the geometry evidence "
        "represents another date, an unbroken TERRITORIAL_CONTINUITY "
        "chain from that date to the snapshot is required; gaps are "
        "rejected, never interpolated (proved on the REAL HALC 1500 "
        "assertion).",
        "- **confidence is ordinal** (UNKNOWN < LOW < MEDIUM < HIGH), "
        "aggregated worst-of-bundle; the old string `min()` returned "
        "HIGH for HIGH+MEDIUM.",
        "- **component counts** are measured on the unioned land "
        "geometry (overlapping features no longer inflate "
        "ENCLAVE_AT_RISK).",
        "- **multi-subject provenance**: membership, audits and control "
        "keep every contributing historical subject, evidence, source "
        "and feature id.",
        "- **single land-mask authority**: audits derive the land union "
        "from the same per-hex mask the binding used; a divergent "
        "explicit union raises.",
        "- **control provenance**: single-source rows keep the real "
        "source id; multi-source rows reference a deterministic "
        "compiled provenance record (`prov_<sha1>`) with the full id "
        "sets in additive columns (design recorded in run_manifest).",
        "",
        "## Schema / algorithm",
        "",
        "- hpg schema 1.2.0 -> **1.3.0** (additive "
        "`historical_boundary_feature_evidence` link table with "
        "`evidence_role`; the single `political_evidence_id` / "
        "`political_evidence_source_id` columns are DEPRECATED aliases "
        "and are no longer production authority).",
        "- hpg algorithm 1.1.0 -> **1.2.0** (bundle compatibility, "
        "geometry authority, continuity bridge, ordinal confidence, "
        "union component counting, shared land mask).",
        "",
        "## Production state (unchanged)",
        "",
        f"- boundary features 0 · feature-evidence links {len(links)} · "
        f"snapshot features 0 · membership 0 · new control 0. The "
        f"{len(assertions)} registered production assertions still "
        "authorise nothing (HALC = GEOMETRIC_SUBSTRATE_ONLY; the "
        "Corsica existence assertion has no pinpoint locator). "
        "Synthetic fixtures live only inside the run.",
        "",
        "## Images",
        "",
    ]
    for n, a in aspects.items():
        lines.append(f"- `{n}` (aspect {a})")
    lines += [
        "",
        f"- Synthetic panels are labelled: {SYN}.",
        "",
        "## Validation",
        "",
        "- `validation.csv` covers R2-01..R2-29 (frozen 011/011R "
        "content, matrix, existence rejection, geometry authority, "
        "de-facto/de-jure cross-use, continuity required + gap "
        "rejected, valid bundles, ordinal confidence, union components, "
        "multi-subject provenance, land-mask authority, control "
        "provenance, claims, SOURCE_GAP, 008/009R2/010 regressions, AST "
        "scan, renders, upstream immutability). Pass count in "
        "`summary.csv`.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
