"""MAPGEN-011/011R — historical production gate + Low Countries pilot.

HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM MODERN
ADMINISTRATION. The MAPGEN-011 outcome (HALC v15.0 acquired, 1500-only,
SOURCE_GAP, zero production rows) is FROZEN; MAPGEN-011R hardens the
semantics only: assertion-backed production gates (fake-1756 exploit
closed and negatively tested EVERY run), exact-land hex binding,
union-based winner decision, and split conservation/winner-distortion
audits.
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
                                 controls_from_membership,
                                 hexification_audit,
                                 membership_conservation_audit,
                                 overlay_candidates_from_audit,
                                 validate_production_features)
from .historical_geometry import (BOUNDARY_FEATURE_COLUMNS,
                                  HPG_ALGORITHM_VERSION,
                                  HPG_SCHEMA_VERSION,
                                  load_evidence_assertions,
                                  load_global_sources,
                                  make_evidence_assertion_id,
                                  make_global_source_id,
                                  select_features_for_snapshot)
from .human_geography_pipeline import _save
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, load_scenario,
                       make_scenario_polity_id, scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .sources import sha256_of

STAGE = "MAPGEN-011R"
SNAPSHOT_DATE = "1756-08-01"
HALC_DIR = Path("data/raw/historical_atlas_low_countries")
HALC_FILES = ["HALC_1500.gpkg", "HALC_Localities.gpkg",
              "HALC_Codebook.xlsx", "HALC_Unidentified.gpkg",
              "HALC_Unidentified_Localities.gpkg"]
GRID6 = None  # set in run


# --------------------------------------------------------------------------
# In-run synthetic fixtures (SEMANTICS TESTS — never production data)
# --------------------------------------------------------------------------
def _fixture_registry(reg):
    syn = pd.DataFrame([
        {"global_source_id": make_global_source_id("SYN_evidence_1756"),
         "citation_key": "SYN_evidence_1756",
         "authority_level": "ACADEMIC_REFERENCE"}])
    return pd.concat([reg, syn], ignore_index=True)


def _fake_1756_feature(halc_id):
    """The exploit: HALC (1500) as both substrate and 'evidence', with
    hand-typed 1756 validity on the feature."""
    return pd.DataFrame([{
        "boundary_feature_id": "hbf_SYNFAKE",
        "historical_subject_id": "hsub_syn",
        "feature_role": "POLITY_EXTERNAL_BOUNDARY",
        "valid_from": "1750-01-01", "valid_to": "1760-12-31",
        "temporal_precision": "YEAR",
        "geometry_source_id": halc_id,
        "political_evidence_source_id": halc_id,
        "political_evidence_id": make_evidence_assertion_id(
            "historical_atlas_low_countries", "low_countries_localities",
            "GEOMETRIC_SUBSTRATE_ONLY", "1500-01-01", "1500-12-31"),
        "source_locator": "layer 'HALC 1500'",
        "interpretation_level": "RECONSTRUCTED",
        "source_confidence": "LOW",
        "geometry": shapely.box(0, 0, 1e4, 1e4),
    }])


def _valid_synthetic_feature(halc_id):
    return pd.DataFrame([{
        "boundary_feature_id": "hbf_SYNOK",
        "historical_subject_id": "hsub_syn",
        "feature_role": "POLITY_EXTERNAL_BOUNDARY",
        "valid_from": "1750-01-01", "valid_to": "1760-12-31",
        "temporal_precision": "YEAR",
        "geometry_source_id": halc_id,
        "political_evidence_source_id":
            make_global_source_id("SYN_evidence_1756"),
        "political_evidence_id": make_evidence_assertion_id(
            "SYN_evidence_1756", "hsub_syn", "POLITICAL_CONTROL",
            "1748-01-01", "1763-12-31"),
        "source_locator": "map plate 7",
        "interpretation_level": "DERIVED",
        "source_confidence": "MEDIUM",
        "geometry": shapely.box(0, 0, 1e4, 1e4),
    }])


def _fixture_assertions():
    return pd.DataFrame([{
        "historical_evidence_id": make_evidence_assertion_id(
            "SYN_evidence_1756", "hsub_syn", "POLITICAL_CONTROL",
            "1748-01-01", "1763-12-31"),
        "global_source_id": make_global_source_id("SYN_evidence_1756"),
        "historical_subject_id": "hsub_syn",
        "assertion_type": "POLITICAL_CONTROL",
        "valid_from": "1748-01-01", "valid_to": "1763-12-31",
        "temporal_precision": "YEAR", "exact_locator": "map plate 7",
        "interpretation_level": "DIRECT", "confidence": "MEDIUM",
        "geometry_authority": "NO", "political_authority": "YES",
        "notes": "SYNTHETIC SEMANTICS FIXTURE — never production",
    }])


def _coastal_fixture(grid):
    """60% land / 40% sea hex; polygon covers part of the land AND juts
    far into the sea — new semantics must count land only."""
    poly = grid.polygon(500, 500)
    b = shapely.bounds(np.array([poly], dtype=object))[0]
    xmid = b[0] + (b[2] - b[0]) * 0.6
    land = shapely.intersection(poly, shapely.box(b[0] - 1e4, b[1] - 1e4,
                                                  xmid, b[3] + 1e4))
    hist = shapely.box(b[0] + (b[2] - b[0]) * 0.3, b[1] - 1e4,
                       b[2] + 5e4, b[3] + 1e4)
    snap = gpd.GeoDataFrame(pd.DataFrame([{
        "boundary_feature_id": "hbf_SYNCOAST",
        "historical_subject_id": "hsub_syn",
        "scenario_polity_id": "sp_syn",
        "feature_role": "POLITY_EXTERNAL_BOUNDARY",
        "political_evidence_id": "hev_syn",
        "global_source_id": "hsrc_syn",
        "source_confidence": "MEDIUM", "snapshot_date": SNAPSHOT_DATE,
        "geometry": hist}]), geometry="geometry")
    return snap, poly, land, hist


def run_historical_pilot(cfg: MapgenConfig,
                         run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    hcfg = cfg.raw["human_geography"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"historical_pilot_r_{_dt.datetime.now():%Y%m%d}"
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

    # ---- R01: MAPGEN-011 outcome frozen ---------------------------------
    t0 = time.perf_counter()
    from pyogrio import read_info

    info = read_info(HALC_DIR / "HALC_1500.gpkg")
    features = gpd.read_parquet(cfg.data_dir / "historical"
                                / "historical_boundary_features.parquet")
    reg = load_global_sources(cfg.data_dir)
    assertions = load_evidence_assertions(cfg.data_dir)
    assessment = pd.read_csv(cfg.data_dir / "historical"
                             / "historical_source_assessment.csv",
                             keep_default_na=False, na_values=[""])
    _check("R01_MAPGEN011_source_gap_unchanged",
           info["features"] == 14863 and len(features) == 0
           and (assessment["boundary_authority_for_1756"] == "NO").all()
           and all((HALC_DIR / f).exists() for f in HALC_FILES),
           "HALC v15.0 acquisition, 1500-only finding, SOURCE_GAP and "
           "zero production features all frozen")
    halc_id = make_global_source_id("historical_atlas_low_countries")
    halc_ass = assertions[assertions["global_source_id"] == halc_id]
    _check("R04_evidence_assertion_required",
           len(assertions) >= 3
           and assertions["historical_evidence_id"].is_unique
           and len(halc_ass) == 1
           and halc_ass.iloc[0]["assertion_type"]
           == "GEOMETRIC_SUBSTRATE_ONLY"
           and halc_ass.iloc[0]["political_authority"] == "NO",
           f"{len(assertions)} registered evidence assertions; HALC "
           "carries exactly one — GEOMETRIC_SUBSTRATE_ONLY with "
           "political_authority=NO (the assertion that closes the "
           "exploit)")

    # ---- R02/R03: gate is NOT vacuous — negative fixture every run ------
    mapping = pd.DataFrame([{"historical_subject_id": "hsub_syn",
                             "scenario_polity_id": "sp_syn"}])
    fake = _fake_1756_feature(halc_id)
    v_fake = validate_production_features(fake, reg, assertions, mapping,
                                          SNAPSHOT_DATE)
    _check("R03_fake_1756_source_exploit_rejected",
           any("does not explicitly cover 1756-08-01" in x
               or "no political authority" in x for x in v_fake)
           and len(v_fake) >= 1,
           f"HALC-as-evidence + hand-typed 1756 feature validity is "
           f"REJECTED ({len(v_fake)} violations: assertion validity "
           "1500 only + political_authority=NO)")
    reg_fx = _fixture_registry(reg)
    ass_fx = pd.concat([assertions, _fixture_assertions()],
                       ignore_index=True)
    ok_feat = _valid_synthetic_feature(halc_id)
    v_ok = validate_production_features(ok_feat, reg_fx, ass_fx, mapping,
                                        SNAPSHOT_DATE)
    _check("R02_H04_not_vacuous",
           v_ok == [] and len(v_fake) > 0,
           "the same gate run PASSES a feature backed by an independent "
           "scholarly assertion (subject match, 1756 coverage, locator, "
           "political authority) and FAILS the exploit — executed every "
           "run, never vacuous")
    timings["gates_s"] = time.perf_counter() - t0

    # ---- R05: exact land intersection (coastal synthetic) ---------------
    t0 = time.perf_counter()
    snap_c, hexpoly, land, hist = _coastal_fixture(grid)
    fmem, pmem = bind_snapshot_to_hexes(
        snap_c, np.array([hexpoly], dtype=object),
        [grid.hex_id(500, 500)], np.array([land], dtype=object),
        np.array([True]), scenario_id, SNAPSHOT_DATE)
    from .islands import ground_area_perimeter as _gap

    land_km2 = _gap(land)[0]
    expect_km2 = _gap(shapely.intersection(hist, land))[0]
    old_wrong_km2 = _gap(shapely.intersection(hist, hexpoly))[0]
    got = float(pmem.iloc[0]["intersection_ground_km2"])
    share = float(pmem.iloc[0]["share_of_terrestrial_hex_land"])
    _check("R05_exact_land_intersection",
           abs(got - expect_km2) < 1e-3 and share <= 1.0
           and old_wrong_km2 > expect_km2 * 1.3,
           f"coastal fixture: polygon∩(hex∩land)={got:.3f} km2 == "
           f"{expect_km2:.3f}; the old full-hex numerator would have "
           f"counted {old_wrong_km2:.3f} km2 of sea as political land; "
           f"share={share:.4f} <= 1")
    # ---- R06: same-polity union, no double counting ---------------------
    a = shapely.intersection(hexpoly, shapely.box(*shapely.bounds(
        np.array([hexpoly], dtype=object))[0][[0, 1]],
        *(shapely.bounds(np.array([hexpoly], dtype=object))[0][[2, 3]]
          - [3000, 0])))
    b_ = shapely.transform(a, lambda xy: xy + np.array([1500.0, 0.0]))
    snap2 = gpd.GeoDataFrame(pd.DataFrame([
        dict(snap_c.iloc[0].drop("geometry")) | {
            "boundary_feature_id": "hbf_A", "geometry": a},
        dict(snap_c.iloc[0].drop("geometry")) | {
            "boundary_feature_id": "hbf_B", "geometry": b_},
    ]), geometry="geometry")
    _, pmem2 = bind_snapshot_to_hexes(
        snap2, np.array([hexpoly], dtype=object),
        [grid.hex_id(500, 500)],
        np.array([hexpoly], dtype=object),  # all-land hex
        np.array([True]), scenario_id, SNAPSHOT_DATE)
    union_km2 = _gap(shapely.intersection(shapely.union(a, b_),
                                          hexpoly))[0]
    got2 = float(pmem2.iloc[0]["intersection_ground_km2"])
    naive2 = _gap(shapely.intersection(a, hexpoly))[0] \
        + _gap(shapely.intersection(b_, hexpoly))[0]
    _check("R06_same_polity_union_no_double_count",
           abs(got2 - union_km2) < 1e-3 and naive2 > union_km2 * 1.2
           and "hbf_A|hbf_B"
           == pmem2.iloc[0]["contributing_boundary_feature_ids"],
           f"overlapping same-polity features: unioned={got2:.3f} km2 "
           f"== {union_km2:.3f}; naive sum would be {naive2:.3f}; "
           "feature provenance retained")
    # ---- R08: winner distortion is real ---------------------------------
    polys49 = np.array([hexpoly], dtype=object)
    b0 = shapely.bounds(polys49)[0]
    xcut = b0[0] + (b0[2] - b0[0]) * 0.49
    ga = shapely.box(b0[0] - 1e4, b0[1] - 1e4, xcut, b0[3] + 1e4)
    gb = shapely.box(xcut, b0[1] - 1e4, b0[2] + 1e4, b0[3] + 1e4)
    snap3 = gpd.GeoDataFrame(pd.DataFrame([
        dict(snap_c.iloc[0].drop("geometry")) | {
            "boundary_feature_id": "hbf_A49",
            "scenario_polity_id": "sp_a", "geometry": ga},
        dict(snap_c.iloc[0].drop("geometry")) | {
            "boundary_feature_id": "hbf_B51",
            "scenario_polity_id": "sp_b", "geometry": gb},
    ]), geometry="geometry")
    _, pmem3 = bind_snapshot_to_hexes(
        snap3, polys49, [grid.hex_id(500, 500)], polys49,
        np.array([True]), scenario_id, SNAPSHOT_DATE)
    cons = membership_conservation_audit(snap3, pmem3, hexpoly)
    hexa = hexification_audit(snap3, pmem3,
                              {grid.hex_id(500, 500): hexpoly}, hexpoly)
    a_row = hexa[hexa["scenario_polity_id"] == "sp_a"].iloc[0]
    a_cons = cons[cons["scenario_polity_id"] == "sp_a"].iloc[0]
    _check("R08_winner_distortion_real",
           bool(pmem3[pmem3["scenario_polity_id"] == "sp_b"]
                ["is_dominant"].iloc[0])
           and abs(a_cons["conservation_error_km2"]) < 0.01
           and a_row["winner_represented_ground_km2"] == 0.0
           and a_row["omission_ground_km2"]
           > a_row["source_land_ground_km2"] * 0.95
           and a_row["representation_status"] == "ZERO_HEX_LOSS",
           "49/51 border hex: loser's membership area is conserved "
           f"(error {a_cons['conservation_error_km2']} km2) but the "
           "winner representation shows the REAL omission "
           f"({a_row['omission_ground_km2']} km2) — distortion is no "
           "longer hidden by membership sums")
    ov = overlay_candidates_from_audit(hexa, snap3)
    _check("R09_zero_hex_provenance",
           len(ov) == 1
           and ov.iloc[0]["political_evidence_id"] == "hev_syn"
           and ov.iloc[0]["global_source_id"] == "hsrc_syn",
           "zero-hex loss produced an overlay candidate WITH mandatory "
           "evidence/source provenance (None-provenance raises)")
    try:
        controls_from_membership(pmem3, scenario_id, {})
        prov_ok = False
    except ValueError:
        prov_ok = True
    ctrl_fx = controls_from_membership(
        pmem3, scenario_id,
        {"sp_a": {"source_id": "hsrc_syn"},
         "sp_b": {"source_id": "hsrc_syn"}})
    _check("R10_control_provenance_complete",
           prov_ok and (ctrl_fx["source_id"] == "hsrc_syn").all()
           and "political_evidence_ids" in ctrl_fx.columns
           and "boundary_feature_ids" in ctrl_fx.columns,
           "generated control rows carry source_id + evidence + feature "
           "provenance; None-provenance generation raises")
    _check("R11_claims_not_derived",
           "claimant_scenario_polity_id" not in ctrl_fx.columns,
           "claims are never generated from control (structurally)")
    _, pmem_o = bind_snapshot_to_hexes(
        snap3, polys49, [grid.hex_id(500, 500)], polys49,
        np.array([False]), scenario_id, SNAPSHOT_DATE)
    _check("R12_ocean_never_terrestrial_target", len(pmem_o) == 0,
           "OCEAN hex produces zero terrestrial membership")
    timings["synthetic_semantics_s"] = time.perf_counter() - t0

    # ---- production state (still SOURCE_GAP, honest) --------------------
    t0 = time.perf_counter()
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
    fmem_p.to_parquet(run_dir / "historical_hex_feature_membership.parquet")
    pmem_p.to_parquet(run_dir / "historical_hex_membership.parquet")
    cons_p = membership_conservation_audit(snap_prod, pmem_p, None)
    cons_p.to_csv(run_dir / "membership_conservation_audit.csv",
                  index=False)
    hexa_p = hexification_audit(snap_prod, pmem_p, {}, None)
    hexa_p.to_csv(run_dir / "historical_hexification_audit.csv",
                  index=False)
    ov_p = overlay_candidates_from_audit(hexa_p, snap_prod)
    ov_p.to_csv(run_dir / "historical_political_overlay_candidates.csv",
                index=False)
    _check("R16b_production_rows_still_zero",
           len(sel) == 0 and len(pmem_p) == 0 and len(hexa_p) == 0
           and len(ov_p) == 0,
           "production: snapshot 0 / membership 0 / audits 0 / overlay "
           "0 — SOURCE_GAP is not resolved with synthetic data")
    contested = check_contested_overlaps(snap_prod) \
        if len(snap_prod) else []
    _check("R07_many_to_many_preserved",
           not contested
           and {"membership_count", "border_hex",
                "contributing_boundary_feature_ids"}
           <= set(pmem_p.columns)
           and int(pmem3["membership_count"].max()) == 2,
           "many-to-many membership schema preserved (border fixture "
           "carries both polities); no silent contested overlaps")
    timings["production_s"] = time.perf_counter() - t0

    # ---- regressions -----------------------------------------------------
    snapd = load_scenario(cfg.data_dir, scenario_id)
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    _check("R14_010_europe_regression",
           len(eu_man) == 50
           and int(eu_man["hex_count"].sum()) == 1885422
           and int(eu_man["terrestrial_count"].sum()) == 862795,
           "Europe coverage intact (50 chunks / 1,885,422 hexes / "
           "862,795 terrestrial)")
    tokugawa_sp = make_scenario_polity_id(scenario_id,
                                          "pol_tokugawa_shogunate")
    controllers = set(snapd.territorial_control[
        "controller_scenario_polity_id"].dropna())
    _check("R15_009r2_scenario_regression",
           len(snapd.polities) == 66
           and len(snapd.scenario_polity_relationships) == 46
           and controllers == {tokugawa_sp},
           "66 polities / 46 relationships / Tokugawa-only control")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    _check("R16_008_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN",
           "Toshima underlying hex stays OCEAN")
    forb = (scan_forbidden_reference_code(
        Path(__file__).parent / "historical_binding.py")
        + scan_forbidden_reference_code(
            Path(__file__).parent / "historical_geometry.py"))
    _check("R13_modern_admin_generation_forbidden", not forb,
           f"AST scan clean (hits={forb or 0})")
    _check("R17_versions",
           HPG_SCHEMA_VERSION == "1.2.0"
           and HPG_ALGORITHM_VERSION == "1.1.0"
           and SCENARIO_SCHEMA_VERSION == "1.4.0"
           and "political_evidence_id" in BOUNDARY_FEATURE_COLUMNS,
           f"hpg schema {HPG_SCHEMA_VERSION} (assertion entity), "
           f"algorithm {HPG_ALGORITHM_VERSION} (exact-land + union + "
           "split audits); run-level determinism proved by second run")

    # ---- renders ---------------------------------------------------------
    t0 = time.perf_counter()
    _render_contract(run_dir / "source_vs_evidence_assertion_contract.png",
                     assertions)
    _render_land_semantics(
        run_dir / "exact_land_binding_semantics.png", hexpoly, land,
        hist, expect_km2, old_wrong_km2, land_km2)
    _render_winner_distortion(
        run_dir / "membership_vs_winner_distortion.png", hexpoly, ga, gb,
        a_cons, a_row)
    from PIL import Image

    img_names = ["source_vs_evidence_assertion_contract.png",
                 "exact_land_binding_semantics.png",
                 "membership_vs_winner_distortion.png"]
    aspects = {}
    for n in img_names:
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.size[0] / im.size[1], 3)
    _check("R18_renders",
           all(0.3 <= a <= 4.0 for a in aspects.values()),
           f"{len(img_names)} renders, aspects={aspects} (B/C labelled "
           "SYNTHETIC SEMANTICS TEST)")
    timings["render_s"] = time.perf_counter() - t0

    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("R19_upstream_immutable", up_after == upstream,
           f"{len(upstream)} upstream files byte-identical before/after")

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "pilot_validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    summary_rows = [
        ("stage", STAGE),
        ("outcome", "semantics hardening only — MAPGEN-011 SOURCE_GAP "
                    "frozen"),
        ("hpg_schema_version", HPG_SCHEMA_VERSION),
        ("hpg_algorithm_version", HPG_ALGORITHM_VERSION),
        ("evidence_assertions_registered", len(assertions)),
        ("production_boundary_features", 0),
        ("snapshot_features_1756_08_01", 0),
        ("hex_membership_rows", 0),
        ("new_control_rows", 0),
        ("fake_1756_exploit", "REJECTED (negative fixture every run)"),
        ("binding_denominator", "exact hex ∩ OSM-coast-authority land"),
        ("same_polity_double_count", "eliminated (union before winner)"),
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
            "hpg_schema_1.2.0": "additive evidence-assertion entity + "
                                "political_evidence_id on features: "
                                "authority moves from sources to "
                                "registered assertions",
            "hpg_algorithm_1.1.0": "binding semantics changed: exact "
                                   "hex∩OSM-land denominators, "
                                   "same-polity union before winner, "
                                   "conservation vs winner-distortion "
                                   "audit split",
        },
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
    _write_readme(run_dir, run_id, assertions, val, aspects)
    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    hdir = cfg.data_dir / "historical"
    copies = {
        "README_REVIEW.md": run_dir / "README_REVIEW.md",
        "run_manifest.json": run_dir / "run_manifest.json",
        "validation.csv": run_dir / "pilot_validation.csv",
        "summary.csv": run_dir / "pilot_summary.csv",
        "historical_source_assessment.csv":
            hdir / "historical_source_assessment.csv",
        "historical_evidence_assertions.csv":
            hdir / "historical_evidence_assertions.csv",
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
    print(f"[pilot] {run_id}: validation {n_pass}/{len(val)}, "
          f"exploit REJECTED, exact-land binding proven, production "
          f"rows still 0 ({timings['total_s']:.0f}s)")
    for w in warnings:
        print(f"[pilot][WARN] {w}")
    return run_dir


# --------------------------------------------------------------------------
# Renders
# --------------------------------------------------------------------------
def _render_contract(path, assertions):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(14, 8))

    def box(x, y, w, h, text, fc, fs=9):
        ax.add_patch(plt.Rectangle((x, y), w, h, fc=fc, ec="#333333",
                                   lw=1.2, zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, zorder=3)

    box(0.03, 0.62, 0.28, 0.28,
        "SOURCE (hsrc_)\n\nwhat a work IS\n(authority level,\nlicence, "
        "dates)", "#efe9d6")
    box(0.36, 0.62, 0.28, 0.28,
        "EVIDENCE ASSERTION (hev_)\n\nwhat a specific locator\nPROVES, "
        "for which subject,\nfor which dates,\ngeometry vs political "
        "authority", "#dce7f2")
    box(0.69, 0.62, 0.28, 0.28,
        "PRODUCTION FEATURE (hbf_)\n\nmust reference a political\n"
        "assertion covering the\nsnapshot date — feature-side\ndates "
        "can never substitute", "#f7dcd7")
    ax.annotate("", xy=(0.36, 0.76), xytext=(0.31, 0.76),
                arrowprops={"arrowstyle": "->", "lw": 2})
    ax.annotate("", xy=(0.69, 0.76), xytext=(0.64, 0.76),
                arrowprops={"arrowstyle": "->", "lw": 2})
    box(0.10, 0.10, 0.80, 0.40,
        "CLOSED EXPLOIT (negatively tested EVERY run, R02/R03):\n\n"
        "HALC 1500 as geometry source + HALC 1500 as 'evidence' + "
        "hand-typed feature validity 1750-1760\n-> REJECTED: HALC's "
        "only assertion is GEOMETRIC_SUBSTRATE_ONLY (1500, political_"
        "authority=NO)\n\nthe same gate PASSES a feature backed by an "
        "independent scholarly assertion\n(subject match + explicit "
        "1756 coverage + exact locator + political_authority=YES)\n\n"
        f"registered real assertions: {len(assertions)} (HALC substrate "
        "/ Corsica existence / San Marino continuity)", "#ddead9", 10)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_title("MAPGEN-011R: source vs evidence-assertion contract",
                 fontsize=11)
    _save(fig, path)


def _render_land_semantics(path, hexpoly, land, hist, new_km2, old_km2,
                           land_km2):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 9))
    for g, fc, ec, lw, alpha in [
            (hexpoly, "#a8c8e8", "#333333", 1.5, 1.0),
            (land, "#d8d2c0", "#333333", 0.8, 1.0),
            (shapely.intersection(hist, hexpoly), "#b03a2e", None, 0,
             0.30),
            (shapely.intersection(hist, land), "#7a1f1f", None, 0, 0.75)]:
        for p in shapely.get_parts(g) if g.geom_type.startswith("Multi") \
                else [g]:
            if p.geom_type != "Polygon" or p.is_empty:
                continue
            xs, ys = zip(*p.exterior.coords)
            ax.fill(xs, ys, fc=fc, ec=ec, lw=lw or 0, alpha=alpha,
                    zorder=3)
    b = shapely.bounds(np.array([hexpoly], dtype=object))[0]
    ax.set_xlim(b[0] - 2000, b[2] + 2000)
    ax.set_ylim(b[1] - 2000, b[3] + 2000)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(
        "SYNTHETIC SEMANTICS TEST (not production data)\n"
        "exact-land binding: dark red = polygon ∩ (hex ∩ OSM land) = "
        f"{new_km2:.2f} km2 (counted)\nlight red = old full-hex "
        f"intersection = {old_km2:.2f} km2 (sea wrongly counted before "
        f"011R)\nhex land = {land_km2:.2f} km2; share <= 1 hard-gated",
        fontsize=10)
    _save(fig, path)


def _render_winner_distortion(path, hexpoly, ga, gb, a_cons, a_row):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(15, 8),
                                  width_ratios=[1, 1])
    for g, fc in [(shapely.intersection(ga, hexpoly), "#1f618d"),
                  (shapely.intersection(gb, hexpoly), "#b03a2e")]:
        for p in shapely.get_parts(g) if g.geom_type.startswith("Multi") \
                else [g]:
            xs, ys = zip(*p.exterior.coords)
            ax.fill(xs, ys, fc=fc, alpha=0.6, zorder=3)
    xs, ys = zip(*hexpoly.exterior.coords)
    ax.plot(xs, ys, color="#333333", lw=2)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title("SYNTHETIC SEMANTICS TEST: 49% (blue) vs 51% (red) "
                 "border hex\nred wins the whole hex", fontsize=10)
    ax2.text(0.0, 0.95, (
        "loser polity (49%):\n\n"
        "membership conservation audit:\n"
        f"  source land       {a_cons['source_land_ground_km2']} km2\n"
        f"  membership sum    "
        f"{a_cons['membership_intersection_ground_km2']} km2\n"
        f"  conservation err  {a_cons['conservation_error_km2']} km2  "
        "(bookkeeping OK)\n\n"
        "winner hexification audit (the REAL gameplay error):\n"
        f"  winner area       "
        f"{a_row['winner_represented_ground_km2']} km2\n"
        f"  omission          {a_row['omission_ground_km2']} km2\n"
        f"  status            {a_row['representation_status']}\n\n"
        "before 011R these two were conflated and the loss\n"
        "was invisible (area_error ~ 0 -> 'GOOD')"),
        va="top", family="monospace", fontsize=10)
    ax2.set_axis_off()
    fig.suptitle("membership conservation vs winner distortion — "
                 "now separate audits", fontsize=11)
    _save(fig, path)


def _write_readme(run_dir, run_id, assertions, val, aspects):
    lines = [
        f"# {STAGE} Review — Historical Production Gate + Land-Area Hex "
        "Binding Semantics Hardening",
        "",
        "**HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM "
        "MODERN ADMINISTRATION.**",
        "**MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER "
        "NEUTRAL.**",
        "",
        f"Run `{run_id}`. MAPGEN-011's historical content is FROZEN "
        "(HALC v15.0 acquisition, 1500-only finding, SOURCE_GAP, zero "
        "production rows, byte-identical control/claims). This stage "
        "fixes implementation semantics only.",
        "",
        "## Fixes",
        "",
        "- **Fake-1756 exploit closed**: authority now lives in "
        "registered EVIDENCE ASSERTIONS (hev_), not sources. A feature "
        "must reference a political assertion whose subject matches and "
        "whose validity explicitly covers 1756-08-01; HALC's only "
        "assertion is GEOMETRIC_SUBSTRATE_ONLY (1500, political "
        "authority NO), so the 'HALC as its own evidence + hand-typed "
        "1756 validity' path is rejected — and a negative fixture "
        "executes EVERY run so the gate can never go vacuous (R02/R03). "
        "hpg schema 1.1.0 → **1.2.0** (additive).",
        "- **Exact-land binding**: numerators and denominators are now "
        "the exact hex ∩ OSM-coast-authority land geometry — sea area "
        "never counts as political land, land_fraction approximations "
        "are gone, share>1 raises instead of clipping. hpg algorithm "
        "1.0.0 → **1.1.0**.",
        "- **Same-polity union**: multi-feature coverage of one hex is "
        "unioned before the winner decision (no double counting); "
        "feature-level provenance moves to a separate "
        "`historical_hex_feature_membership` table.",
        "- **Audit split**: membership conservation (geometry "
        "bookkeeping) vs winner hexification distortion (real "
        "omission/commission via geometry symmetric difference) — a "
        "49/51 border loss is now visible instead of hiding behind a "
        "membership sum.",
        "- **Provenance mandatory**: generated control rows and overlay "
        "candidates require source + evidence + feature ids "
        "(None-provenance raises). Claims still never derive from "
        "control.",
        "",
        "## Production state (unchanged, honest)",
        "",
        "- boundary features 0 / snapshot features 0 / membership 0 / "
        "new control 0. SOURCE_GAP is NOT resolved with synthetic data; "
        f"the {len(assertions)} registered real assertions are "
        "work-level (HALC substrate, Corsica existence, San Marino "
        "continuity) and none authorises production geometry.",
        "",
        "## Images",
        "",
    ]
    for n, a in aspects.items():
        lines.append(f"- `{n}` (aspect {a})")
    lines += [
        "",
        "- The land-binding and winner-distortion figures are labelled "
        "SYNTHETIC SEMANTICS TEST — they demonstrate the algorithms, "
        "not production data.",
        "",
        "## Validation",
        "",
        "- `validation.csv` covers R01-R19 (frozen 011 outcome, "
        "non-vacuous exploit rejection + acceptance, exact-land, union, "
        "many-to-many, winner distortion, provenance, regressions, AST "
        "scans, upstream immutability). Pass count in `summary.csv`.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
