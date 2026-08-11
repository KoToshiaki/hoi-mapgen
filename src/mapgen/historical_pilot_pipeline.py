"""MAPGEN-011 — Historical boundary source acquisition + Low Countries
production pilot (pipeline).

HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM MODERN
ADMINISTRATION. This run's outcome is honest: the candidate dataset was
ACQUIRED AND VERIFIED (HALC v15.0), and it publishes only the 1500
cross-section — so production 1756 geometry remains at SOURCE_GAP and
every binding/audit mechanism is proven by synthetic tests instead of
fabricated polygons.
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
from .historical_binding import (BINDING_METHOD, bind_snapshot_to_hexes,
                                 check_contested_overlaps,
                                 controls_from_membership,
                                 hexification_audit,
                                 overlay_candidates_from_audit,
                                 validate_production_features)
from .historical_geometry import (BOUNDARY_FEATURE_COLUMNS,
                                  HPG_ALGORITHM_VERSION,
                                  HPG_SCHEMA_VERSION, load_global_sources,
                                  select_features_for_snapshot)
from .human_geography_pipeline import _save
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, load_scenario,
                       make_scenario_polity_id, scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .sources import sha256_of

STAGE = "MAPGEN-011"
SNAPSHOT_DATE = "1756-08-01"
HALC_DIR = Path("data/raw/historical_atlas_low_countries")
HALC_FILES = ["HALC_1500.gpkg", "HALC_Localities.gpkg",
              "HALC_Codebook.xlsx", "HALC_Unidentified.gpkg",
              "HALC_Unidentified_Localities.gpkg"]


def render_halc_sources(path, halc_path, assessment, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    gdf = gpd.read_file(halc_path, columns=["ADM0"])
    gdf["geometry"] = shapely.simplify(gdf.geometry.values, 0.004)
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(17, 10),
                                  width_ratios=[1.1, 1])
    gdf.plot(ax=ax, column="ADM0", cmap="tab20", linewidth=0, alpha=0.9)
    ax.set_title(
        "HALC v15.0 'HALC 1500' layer — 14,863 locality polygons "
        "coloured by ADM0\n*** 1500 CROSS-SECTION: geometric substrate "
        "candidate, NOT 1756 political authority ***", fontsize=10)
    ax.set_aspect(1.55)  # ~1/cos(50N) display compensation
    ax.set_axis_off()
    lines = ["Source assessment (historical_source_assessment.csv):", ""]
    for t in assessment.itertuples():
        lines.append(f"[{t.assessment_status}] "
                     f"{t.source_title[:52]}")
    ax2.text(0.0, 0.98, "\n".join(lines), va="top", ha="left",
             fontsize=9, family="monospace")
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_source_gap(path, catalogue, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(14, 8))

    def box(x, y, w, h, text, fc, fs=9):
        ax.add_patch(plt.Rectangle((x, y), w, h, fc=fc, ec="#333333",
                                   lw=1.2, zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, zorder=3)

    box(0.04, 0.55, 0.44, 0.36,
        "ACQUIRED + VERIFIED\n\nHALC v15.0 (IISH, CC BY-SA 4.0)\n"
        "14,863 locality polygons, EPSG:4326\nADM0..ADM9 hierarchy "
        "— FOR THE YEAR 1500\nSHA-256 recorded; codebook read", "#ddead9")
    box(0.52, 0.55, 0.44, 0.36,
        "MISSING FOR 1756 PRODUCTION\n\nno 1650 / 1800 cross-sections "
        "published yet\nno 1756 sovereignty attributes\nno acquirable "
        "scholarly 1756 GIS found\n(assessment table lists every "
        "candidate + reason)", "#f7dcd7")
    box(0.15, 0.10, 0.70, 0.34,
        "FORMAL RESULT: SOURCE_GAP (per MAPGEN-011 §30)\n\n"
        "production boundary features = 0 — polygons are NEVER invented\n"
        "1500 != 1756 and interpolation is forbidden (machine-gated + "
        "unit-tested)\nbinding/hexification/overlay machinery is "
        "implemented and synthetic-proven\nunblock: upstream 1650/1800 "
        "release + per-subject 1756 continuity evidence,\nor a "
        "locality-level 1756 sovereignty evidence table on the HALC "
        "substrate", "#efe9d6")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_coverage(path, cov, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    counts = cov["control_coverage_status"].value_counts()
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(14, 7))
    ax.bar(counts.index, counts.values,
           color=["#777777" if s == "UNASSESSED" else "#1f618d"
                  for s in counts.index])
    for i, v in enumerate(counts.values):
        ax.text(i, v + 0.4, str(v), ha="center")
    ax.set_title("control_coverage_status per coverage unit", fontsize=10)
    ax.tick_params(axis="x", rotation=20, labelsize=8)
    ax2.text(0.0, 0.95,
             "COMPLETE units: 0\n\n"
             "missing control row semantics:\n"
             "  coverage != COMPLETE  ->  UNKNOWN (never neutral)\n"
             "  coverage == COMPLETE  ->  UNCONTROLLED\n\n"
             "region_low_countries_1756_pilot:\n"
             "  control  = SOURCE_IDENTIFIED\n"
             "  evidence = SOURCE_IDENTIFIED (HALC acquired,\n"
             "  1756 political evidence still missing)",
             va="top", family="monospace", fontsize=10)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def run_historical_pilot(cfg: MapgenConfig,
                         run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    hcfg = cfg.raw["human_geography"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"historical_pilot_{_dt.datetime.now():%Y%m%d}"
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    val_rows: list[dict] = []

    def _check(check_id, ok, detail):
        val_rows.append({"run_id": run_id, "check_id": check_id,
                         "pass": bool(ok), "detail": str(detail)})
        if not ok:
            warnings.append(f"VALIDATION FAIL {check_id}: {detail}")

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

    # ---- HALC acquisition verification ----------------------------------
    t0 = time.perf_counter()
    from pyogrio import read_info

    halc = HALC_DIR / "HALC_1500.gpkg"
    halc_shas = {f: sha256_of(HALC_DIR / f) for f in HALC_FILES}
    info = read_info(halc)
    _check("H01_halc_acquired_and_verified",
           info["features"] == 14863
           and str(info["crs"]) == "EPSG:4326"
           and {"ADM0", "ADM1", "HIGH_JURISD"} <= set(info["fields"])
           and all((HALC_DIR / f).exists() for f in HALC_FILES),
           f"HALC v15.0 acquired: {info['features']} locality polygons, "
           f"CRS {info['crs']}, {len(HALC_FILES)} files with SHA-256 "
           "recorded (CC BY-SA 4.0 via Dataverse API)")
    reg = load_global_sources(cfg.data_dir)
    halc_row = reg[reg["citation_key"] == "historical_atlas_low_countries"]
    _check("H02_halc_registry_updated",
           len(halc_row) == 1
           and "15.0" in halc_row.iloc[0]["title"]
           and "CC BY-SA 4.0" in halc_row.iloc[0]["licence_or_usage_note"]
           and "1500 ONLY" in halc_row.iloc[0]["represented_date_range"],
           "registry records the ACTUAL acquired version, licence and "
           "the 1500-only cross-section finding")
    assessment = pd.read_csv(cfg.data_dir / "historical"
                             / "historical_source_assessment.csv",
                             keep_default_na=False, na_values=[""])
    _check("H03_assessment_table_complete",
           len(assessment) >= 8
           and assessment["global_source_id"].isin(
               set(reg["global_source_id"])).all()
           and assessment["assessment_status"].notna().all()
           and (assessment["boundary_authority_for_1756"] == "NO").all(),
           f"{len(assessment)} candidates assessed with per-axis "
           "verdicts; NO source qualifies as 1756 boundary authority "
           "(multi-axis, never one boolean)")
    timings["acquisition_s"] = time.perf_counter() - t0

    # ---- production features + snapshot (honest: SOURCE_GAP) ------------
    t0 = time.perf_counter()
    features = gpd.read_parquet(cfg.data_dir / "historical"
                                / "historical_boundary_features.parquet")
    catalogue = pd.read_csv(cfg.data_dir / "historical"
                            / "historical_geometry_catalogue.csv",
                            keep_default_na=False, na_values=[""])
    polity_map = pd.DataFrame(columns=["historical_subject_id",
                                       "scenario_polity_id"])
    violations = validate_production_features(features, reg, polity_map,
                                              SNAPSHOT_DATE) \
        if len(features) else []
    _check("H04_source_discipline_gates",
           not violations and len(features) == 0,
           f"production features={len(features)} (SOURCE_GAP), "
           f"discipline violations={violations or 0}; the "
           "1500-cross-section->1756 path is impossible by gate + test")
    snap_feats = select_features_for_snapshot(features, SNAPSHOT_DATE)
    snap = gpd.GeoDataFrame(
        {c: pd.Series(dtype="object") for c in
         ["boundary_feature_id", "historical_subject_id",
          "scenario_polity_id", "feature_role", "source_confidence",
          "snapshot_date"]},
        geometry=gpd.GeoSeries([], crs="EPSG:3857"))
    snap.to_parquet(run_dir
                    / "historical_snapshot_features_1756_08_01.parquet")
    _check("H05_snapshot_compiled",
           len(snap_feats) == 0 and len(snap) == 0,
           f"snapshot {SNAPSHOT_DATE}: {len(snap)} features (temporal "
           "selection ran on the real feature table; UNKNOWN validity "
           "never auto-matches)")
    overlaps = check_contested_overlaps(snap) if len(snap) else []
    _check("H06_no_silent_contested_overlap", not overlaps,
           f"independent-polity overlaps without contested semantics="
           f"{overlaps or 0}")
    # Binding machinery runs (empty in production, proven by tests).
    mem = bind_snapshot_to_hexes(
        snap, np.array([], dtype=object), [], np.array([]),
        np.array([], dtype=bool), scenario_id, SNAPSHOT_DATE, 0.0)
    mem.to_parquet(run_dir / "historical_hex_membership.parquet")
    audit = hexification_audit(snap, mem)
    audit.to_csv(run_dir / "historical_hexification_audit.csv",
                 index=False)
    overlay = overlay_candidates_from_audit(audit, snap)
    overlay.to_csv(run_dir / "historical_political_overlay_candidates.csv",
                   index=False)
    ctrl_new = controls_from_membership(mem, scenario_id, {}, {})
    _check("H07_binding_machinery_zero_production",
           len(mem) == 0 and len(audit) == 0 and len(overlay) == 0
           and len(ctrl_new) == 0,
           f"membership={len(mem)}, audit rows={len(audit)}, overlay "
           f"candidates={len(overlay)}, new control rows={len(ctrl_new)} "
           f"— method {BINDING_METHOD} implemented and synthetic-tested; "
           "no fabricated production rows")
    timings["snapshot_s"] = time.perf_counter() - t0

    # ---- scenario + regression gates ------------------------------------
    snapd = load_scenario(cfg.data_dir, scenario_id)
    cov = snapd.political_coverage
    pilot = cov[cov["coverage_unit_id"]
                == "region_low_countries_1756_pilot"]
    _check("H08_pilot_coverage_unit",
           len(pilot) == 1
           and pilot.iloc[0]["control_coverage_status"]
           == "SOURCE_IDENTIFIED"
           and int((cov["control_coverage_status"]
                    == "COMPLETE").sum()) == 0
           and len(cov) == 52,
           "pilot REGION unit added (control=SOURCE_IDENTIFIED, other "
           "dimensions independent); existing 51 units kept; COMPLETE=0 "
           "— absence still means UNKNOWN, never neutral")
    ctrl_sha = sha256_of(sdir / "territorial_control.csv")
    _check("H09_control_claims_bytes_unchanged",
           ctrl_sha == sha256_of(m8_dir / "territorial_control.csv")
           and sha256_of(sdir / "territorial_claims.csv")
           == sha256_of(m8_dir / "territorial_claims.csv"),
           "territorial_control/claims byte-identical to MAPGEN-008 — "
           "SOURCE_GAP added no control and claims were never derived "
           "from control")
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    _check("H10_europe_coverage_regression",
           len(eu_man) == 50
           and int(eu_man["hex_count"].sum()) == 1885422
           and int(eu_man["terrestrial_count"].sum()) == 862795
           and int(eu_man["ocean_count"].sum()) == 1022627,
           "Europe coverage intact: 50 chunks, 1,885,422 hexes "
           "(862,795 terrestrial / 1,022,627 ocean)")
    tokugawa_sp = make_scenario_polity_id(scenario_id,
                                          "pol_tokugawa_shogunate")
    controllers = set(snapd.territorial_control[
        "controller_scenario_polity_id"].dropna())
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    tosh_wt = geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                      "water_type"].iloc[0]
    aud = snapd.scenario_polity_inclusion_audit
    _check("H11_scenario_regression",
           len(snapd.polities) == 66
           and len(snapd.scenario_polity_relationships) == 46
           and controllers == {tokugawa_sp}
           and tosh_wt == "OCEAN"
           and int((aud["audit_record_status"]
                    == "SUPERSEDED").sum()) == 1,
           "009R2 (66 polities/46 relationships, ACTIVE/SUPERSEDED) and "
           "MAPGEN-008 (Tokugawa, Toshima OCEAN) intact")
    forb = (scan_forbidden_reference_code(
        Path(__file__).parent / "historical_binding.py")
        + scan_forbidden_reference_code(
            Path(__file__).parent / "historical_geometry.py"))
    _check("H12_no_modern_admin_generation", not forb,
           f"AST scan of binding+geometry data layers clean "
           f"(hits={forb or 0}); HALC (scholarly historical GIS) is the "
           "only geometry substrate candidate, never Natural Earth")
    _check("H13_namespace_versions",
           HPG_SCHEMA_VERSION == "1.1.0"
           and HPG_ALGORITHM_VERSION == "1.0.0"
           and SCENARIO_SCHEMA_VERSION == "1.4.0"
           and "geometry_source_id" in BOUNDARY_FEATURE_COLUMNS
           and "political_evidence_source_id"
           in BOUNDARY_FEATURE_COLUMNS,
           f"hpg schema {HPG_SCHEMA_VERSION} (additive substrate/"
           "evidence separation), scenario schema unchanged 1.4.0")
    _check("H14_area_conservation_na",
           len(mem) == 0,
           "area conservation gate N/A at 0 production features; the "
           "identity (source area == membership sum) is enforced by "
           "synthetic tests and will gate real data in MAPGEN-012+")

    # ---- renders ---------------------------------------------------------
    t0 = time.perf_counter()
    render_halc_sources(
        run_dir / "low_countries_historical_sources.png", halc,
        assessment,
        "MAPGEN-011: acquired historical sources + assessment "
        "(HALC v15.0 = 1500 substrate, NOT 1756 authority)")
    render_source_gap(
        run_dir / "low_countries_source_gap_status.png", catalogue,
        "MAPGEN-011 pilot outcome: SOURCE_GAP — verified acquisition, "
        "zero fabricated 1756 polygons")
    render_coverage(
        run_dir / "low_countries_coverage_status.png", cov,
        "Political coverage after MAPGEN-011 — UNKNOWN vs COMPLETE "
        "distinction preserved")
    from PIL import Image

    img_names = ["low_countries_historical_sources.png",
                 "low_countries_source_gap_status.png",
                 "low_countries_coverage_status.png"]
    aspects = {}
    for n in img_names:
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.size[0] / im.size[1], 3)
    _check("H15_renders",
           all((run_dir / n).exists() for n in img_names)
           and all(0.3 <= a <= 4.0 for a in aspects.values()),
           f"{len(img_names)} renders, aspects={aspects}; the 1756 "
           "continuous-geometry/hex-control/hexification images are "
           "IMPOSSIBLE without production geometry and are deliberately "
           "not faked (documented in README)")
    timings["render_s"] = time.perf_counter() - t0

    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("H16_upstream_immutable", up_after == upstream,
           f"{len(upstream)} upstream/scenario files byte-identical "
           "before/after")

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "pilot_validation.csv", index=False)
    n_pass = int(val["pass"].sum())

    summary_rows = [
        ("stage", STAGE),
        ("outcome", "SOURCE_GAP (formal stop per spec §30 — dataset "
                    "acquired+verified, no 1756 geometry exists yet)"),
        ("hpg_schema_version", HPG_SCHEMA_VERSION),
        ("dataset_acquired", "HALC v15.0 hdl:10622/PGFYTM"),
        ("dataset_licence", "CC BY-SA 4.0"),
        ("dataset_cross_sections", "1500 only (1350/1650/1800 pending "
                                   "upstream)"),
        ("halc_locality_polygons", 14863),
        ("production_boundary_features", 0),
        ("snapshot_features_1756_08_01", 0),
        ("hex_membership_rows", 0),
        ("new_control_rows", 0),
        ("overlay_candidates", 0),
        ("sources_assessed", len(assessment)),
        ("global_sources_registered", len(reg)),
        ("coverage_units", len(cov)),
        ("coverage_complete_units", 0),
        ("validation_pass", f"{n_pass}/{len(val)}"),
    ]
    pd.DataFrame(summary_rows, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "pilot_summary.csv", index=False)
    manifest = {
        "run_id": run_id, "stage": STAGE,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "outcome": "SOURCE_GAP",
        "hpg_schema_version": HPG_SCHEMA_VERSION,
        "version_reasons": {
            "hpg_1.1.0": "additive geometry_source_id + "
                         "political_evidence_source_id columns: "
                         "substrate and 1756 political authority are "
                         "separate by schema",
        },
        "halc_acquisition": {
            "handle": "hdl:10622/PGFYTM", "version": "15.0",
            "release_date": "2026-01-01",
            "licence": "CC BY-SA 4.0 (verified via Dataverse API)",
            "download_date_utc": "2026-08-11",
            "data_paper_doi": "10.1163/24523666-bja10033",
            "files_sha256": halc_shas,
            "crs": "EPSG:4326", "locality_polygons": 14863,
            "cross_sections_published": ["1500"],
            "redistribution": "permitted (BY-SA) but kept out of git by "
                              "data/raw policy",
        },
        "binding_method": BINDING_METHOD,
        "area_conservation_tolerance_note": "to be measured from real "
        "data when production geometry exists; no magic tolerance set",
        "upstream_sha256": upstream,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8")
    _write_readme(run_dir, run_id, assessment, reg, cov, aspects)
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
        "historical_source_registry.csv":
            hdir / "historical_source_registry.csv",
        "historical_geometry_catalogue.csv":
            hdir / "historical_geometry_catalogue.csv",
        "historical_hexification_audit.csv":
            run_dir / "historical_hexification_audit.csv",
        "historical_political_overlay_candidates.csv":
            run_dir / "historical_political_overlay_candidates.csv",
        "scenario_political_coverage.csv": sdir / "political_coverage.csv",
        "territorial_control.csv": sdir / "territorial_control.csv",
        "territorial_claims.csv": sdir / "territorial_claims.csv",
    }
    for dst, src in copies.items():
        shutil.copy2(src, review / dst)
    pd.DataFrame(gpd.read_parquet(
        hdir / "historical_boundary_features.parquet").drop(
        columns="geometry")).to_csv(
        review / "historical_boundary_features.csv", index=False)
    pd.DataFrame(gpd.read_parquet(
        run_dir / "historical_snapshot_features_1756_08_01.parquet").drop(
        columns="geometry")).to_csv(
        review / "historical_snapshot_features_1756_08_01.csv",
        index=False)
    pd.read_parquet(run_dir / "historical_hex_membership.parquet").to_csv(
        review / "historical_hex_membership.csv", index=False)
    for n in img_names:
        shutil.copy2(run_dir / n, review / n)
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"[pilot] {run_id}: validation {n_pass}/{len(val)}, outcome="
          f"SOURCE_GAP (HALC v15.0 acquired, 1500-only), production "
          f"features=0 ({timings['total_s']:.0f}s)")
    for w in warnings:
        print(f"[pilot][WARN] {w}")
    return run_dir


def _write_readme(run_dir, run_id, assessment, reg, cov, aspects):
    lines = [
        f"# {STAGE} Review — Historical Boundary Source Acquisition + "
        "Low Countries Pilot (outcome: SOURCE_GAP)",
        "",
        "**REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP.**",
        "**SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY "
        "WITHIN ITS SCENARIO SNAPSHOT.**",
        "**MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER "
        "NEUTRAL.**",
        "**HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM "
        "MODERN ADMINISTRATION.**",
        "",
        "## What actually happened",
        "",
        "- The MAPGEN-010 SOURCE_GAP was re-investigated for real: the "
        "**Historical Atlas of the Low Countries** was located on the "
        "IISH Dataverse (hdl:10622/PGFYTM), and **version 15.0 "
        "(released 2026-01-01) was downloaded and verified** — 5 files, "
        "SHA-256 recorded, licence **CC BY-SA 4.0** confirmed via the "
        "Dataverse API, data paper DOI 10.1163/24523666-bja10033.",
        "- Contents verified by inspection: layer `HALC 1500` with "
        "**14,863 locality polygons** (EPSG:4326) and an ADM0..ADM9 "
        "administrative hierarchy **for the year 1500**. The published "
        "dataset contains **only the 1500 cross-section**; 1350/1650/"
        "1800 are planned upstream but NOT yet released, and no "
        "1756 sovereignty attributes exist.",
        "- **1650/1800/1500 ≠ 1756 rule**: with no 1756-applicable "
        "geometry or per-subject political evidence, production 1756 "
        "features CANNOT be created without fabrication. Per spec §30 "
        "the pilot therefore stops formally at **SOURCE_GAP** with "
        "every candidate recorded in "
        "`historical_source_assessment.csv` "
        f"({len(assessment)} candidates, per-axis verdicts, none "
        "qualifying as 1756 boundary authority).",
        "- Production rows: boundary features **0**, snapshot features "
        "**0**, hex membership **0**, new control rows **0**, overlay "
        "candidates **0**. `territorial_control/claims` are "
        "byte-identical to MAPGEN-008.",
        "",
        "## What was built anyway (and proven by tests)",
        "",
        "- hpg schema 1.0.0 → **1.1.0** (additive): "
        "`geometry_source_id` (substrate) and "
        "`political_evidence_source_id` are separate columns — a "
        "cross-section substrate alone can never carry a 1756 "
        "assertion (machine gate + dedicated tests).",
        "- `historical_binding.py`: MAX_GROUND_LAND_SHARE hex binding "
        "(many-to-many preserved, ground-area winner, deterministic "
        "ties, border/dominance metrics), hexification distortion "
        "audit, zero-hex-loss → overlay candidates, control generation "
        "(claims NEVER derived from control), contested-overlap "
        "detection. All synthetic-tested; production-gated by the "
        "source-discipline validator.",
        "- Coverage: `region_low_countries_1756_pilot` added "
        "(control/evidence = SOURCE_IDENTIFIED, other dimensions "
        "independent); 51 existing units untouched; COMPLETE = 0.",
        "",
        "## Unblock paths for a real 1756 pilot (MAPGEN-012 candidate)",
        "",
        "1. Upstream publishes the 1650/1800 HALC cross-sections → use "
        "as substrate + per-subject 1756 continuity evidence "
        "(priority-4 path of §5).",
        "2. Build a locality-level 1756 sovereignty evidence table on "
        "the acquired 1500 substrate from scholarly territorial "
        "studies (large curation effort, locator-level citations).",
        "3. Georeferenced near-contemporary maps (Ferraris 1771-78, "
        "Fricx 1704-12 — both registered) as georeference aids only.",
        "",
        "## Images",
        "",
    ]
    for n, a in aspects.items():
        lines.append(f"- `{n}` (aspect {a})")
    lines += [
        "",
        "- The spec's 1756 continuous-geometry / hex-control / "
        "hexification-error images are impossible without production "
        "geometry and were deliberately NOT faked.",
        "",
        "## Validation",
        "",
        "- `validation.csv` lists every gate (acquisition verification, "
        "assessment completeness, source discipline, zero-fabrication, "
        "coverage contract, 008/009R2/010 regressions, AST scans, "
        "upstream immutability). Pass count in `summary.csv`.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
