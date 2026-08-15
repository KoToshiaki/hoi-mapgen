"""MAPGEN-018R — the Brandenburg georeference does not survive review.

MAPGEN-018 reported eighteen graticule control points. They were not
eighteen observations: six meridian ticks measured on the top border and
three parallel ticks measured on the left border were crossed into a
Cartesian product, so nine primitive measurements became eighteen rows.
Every held-out point drew its y from a parallel that was also in the fit,
which is why the "holdout RMS" came out at 60 m — an affine model
reproduces a rectangle it was handed, and that says nothing about
geography.

One independent check hid the problem. Five now expose it: the windows
predicted for Frankfurt an der Oder, Neuruppin and Schwedt turned out to
contain Fuerstenwalde, Fehrbellin and Angermuende. The error is
systematic and grows toward the east and north-east.

The transform is therefore downgraded, not repaired. No geometry, no
control.
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

from .config import MapgenConfig
from .historical_geometry import HPG_SCHEMA_VERSION, make_global_source_id
from .historical_pilot_pipeline import _fig, _fig2, _save
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, load_scenario,
                       make_scenario_polity_id, scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .scenario_promotion import (make_promotion_id, promote_control,
                                 sha256_of_frame,
                                 validate_canonical_control)
from .sources import sha256_of

STAGE = "MAPGEN-018R"
H = Path("data/historical")
CK_BRAND = "vaugondy_1751_haute_saxe_septentrionale_pomeranie_brandebourg"
M18_COMMIT = "56e8a3bb753abe6a592b4ada2808d64f40636cdf"
PROVISIONAL = "GEOREFERENCE_PROVISIONAL_RECONSTRUCTED_GRID"


def _wrap(t, w=88):
    return [t[i:i + w] for i in range(0, len(t), w)]


def render_reconstructed(path, grid, prim, corr, title):
    fig, (ax, ax2) = _fig2((17, 8), [1, 1.15])
    xs = sorted(set(grid["pixel_x"]))
    ys = sorted(set(grid["pixel_y"]))
    for x in xs:
        ax.axvline(x, color="#b03a2e", lw=1.0)
    for y in ys:
        ax.axhline(-y, color="#1f618d", lw=1.0)
    ax.scatter(grid["pixel_x"], -grid["pixel_y"], s=55, c="#b03a2e",
               marker="x", label=f"reconstructed rows ({len(grid)})")
    ax.set_xlim(0, 7941)
    ax.set_ylim(-6135, 0)
    ax.set_aspect("equal")
    ax.legend(fontsize=8, loc="lower right")
    ax.set_title(f"{len(xs)} meridian + {len(ys)} parallel observations "
                 f"= {len(xs) * len(ys)} rows", fontsize=10)
    c = corr.iloc[0]
    body = ["WHAT WENT WRONG", ""]
    for k in ("detail", "consequence", "second_finding",
              "what_the_checks_show", "action"):
        for ln in _wrap(str(c[k]), 86):
            body.append("  " + ln)
        body.append("")
    body += ["PRIMITIVE OBSERVATIONS", ""]
    for r in prim.itertuples():
        body.append(f"  {r.observation_id:<26} {r.kind:<14} "
                    f"{r.pixel_axis}={r.pixel_value:.1f}  "
                    f"{int(r.degree_value_raw)}deg")
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=6.6)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_checks(path, chk, title):
    fig, (ax, ax2) = _fig2((16, 7), [1, 1])
    acc = chk[chk["accepted"] == "YES"]
    sc = ax.scatter(acc["pixel_x"], -acc["pixel_y"],
                    s=90 + acc["residual_km"] * 8,
                    c=acc["residual_km"], cmap="autumn_r", vmin=0, vmax=30)
    for r in acc.itertuples():
        ax.annotate(f"{r.reference_feature_name}\n{r.residual_km:.1f} km",
                    (r.pixel_x, -r.pixel_y), fontsize=7,
                    xytext=(6, 4), textcoords="offset points")
    fig.colorbar(sc, ax=ax, label="residual (km)")
    ax.set_xlim(0, 7941)
    ax.set_ylim(-6135, 0)
    ax.set_aspect("equal")
    ax.set_title("independent feature checks (pixel space)", fontsize=10)
    body = ["OBSERVED FEATURE CHECKS", ""]
    for r in chk.itertuples():
        body.append(f"  {r.reference_feature_name} [{r.quadrant}]  "
                    f"accepted={r.accepted}  "
                    f"residual="
                    f"{'' if pd.isna(r.residual_km) else f'{r.residual_km:.2f} km'}")
        body.append(f"    map label read: {r.historical_map_label}")
        for ln in _wrap("    " + str(r.notes), 84):
            body.append(ln)
        body.append("")
    body += ["THE POINT", "",
             "  Berlin alone gave 9.3 km and looked like ordinary",
             "  18th-century placement error. The eastern and",
             "  north-eastern checks are near 27-29 km, and the windows",
             "  predicted for Frankfurt, Neuruppin and Schwedt contained",
             "  Fuerstenwalde, Fehrbellin and Angermuende instead.",
             "",
             "  That is a systematic, position-dependent error, which is",
             "  exactly what a single check cannot reveal."]
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_meridian(path, cand, title):
    fig, (ax, ax2) = _fig2((15, 6), [1, 1])
    ax.bar(cand["candidate"], cand["median_residual_km"], color="#1f618d")
    ax.set_yscale("log")
    ax.set_ylabel("median independent residual (km, log)")
    for i, v in enumerate(cand["median_residual_km"]):
        ax.text(i, v * 1.1, f"{v:,.1f}", ha="center", fontsize=9)
    ax.set_title("prime-meridian candidates", fontsize=10)
    ax2.text(0.0, 0.97,
             "PRIME MERIDIAN\n\n"
             + cand.to_string(index=False)
             + "\n\n  The sheet states no prime meridian. Rather than\n"
               "  inherit Ferro from the other Vaugondy plates, three\n"
               "  candidates were scored against the SAME independent\n"
               "  checks. Ferro wins by two orders of magnitude, so the\n"
               "  reading is corroborated by multiple points now, not by\n"
               "  one.\n\n"
               "  That settles the MERIDIAN. It does not validate the\n"
               "  transform: even under Ferro the residuals reach 29 km\n"
               "  and grow with position.",
             va="top", family="monospace", fontsize=8)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_status(path, s, title):
    fig, ax = _fig((15, 8))
    ax.set_axis_off()
    body = [
        "BRANDENBURG GEOREFERENCE — STATUS AFTER REVIEW", "",
        f"  MAPGEN-018 claimed          : GEOREFERENCED",
        f"  MAPGEN-018R status          : {s['georeference_status']}",
        "",
        f"  reconstructed grid rows     : {s['reconstructed_grid_points']}"
        f"  (production GCPs: {s['production_gcps']})",
        f"  primitive observations      : {s['primitive_observations']}"
        f"  ({s['meridian_observations']} meridian + "
        f"{s['parallel_observations']} parallel)",
        f"  directly observed 2-D GCPs  : {s['directly_observed_gcps']}",
        "",
        f"  independent feature checks  : {s['independent_checks']}",
        f"  median / p90 / max residual : {s['independent_median_km']} / "
        f"{s['independent_p90_km']} / {s['independent_max_km']} km",
        f"  quadrants covered           : {s['check_quadrants']}",
        f"  prime meridian              : {s['prime_meridian']} "
        f"({s['prime_meridian_status']})",
        "",
        f"  corrected uncertainty       : {s['corrected_uncertainty_km']}"
        f" km   (was {s['mapgen018_uncertainty_km']} km)",
        f"  coverage status             : {s['coverage_status']}",
        "",
        f"  production features         : {s['new_production_features']}",
        f"  Brandenburg CONTROLLED      : {s['brandenburg_controlled']}",
        f"  canonical rows              : {s['canonical_rows_before']} -> "
        f"{s['canonical_rows_after']}",
        "", "NOT DONE IN THIS STAGE", "",
        f"  BLHA AKS 1132 A             : {s['blha_1132_result']}",
        f"  BLHA AKS 1145 A             : {s['blha_1145_result']}",
        f"  1756 political documents    : {s['political_documents_read']} "
        "read",
        f"  continuity segments researched: "
        f"{s['continuity_segments_researched']} of "
        f"{s['continuity_segments']}",
        "",
        "  These are shortfalls against the stage brief, not findings.",
        "  They are reported as shortfalls.",
    ]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=9)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def run_historical_georef_review(cfg: MapgenConfig,
                                 run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"brandenburg_georef_review_{_dt.datetime.now():%Y%m%d}"
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    val_rows: list[dict] = []

    def _check(cid, ok, detail):
        val_rows.append({"run_id": run_id, "check_id": cid,
                         "pass": bool(ok), "detail": str(detail)})
        if not ok:
            warnings.append(f"VALIDATION FAIL {cid}: {detail}")

    t0 = time.perf_counter()
    geo_dir = cfg.output_dir / scfg["geography_run"]
    eu_dir = cfg.output_dir / scfg.get("mapgen010_run",
                                       "europe_foundation_20260811")
    m14_dir = cfg.output_dir / scfg.get(
        "mapgen014_run", "central_europe_1756_revision_20260813")
    m15_dir = cfg.output_dir / scfg.get(
        "mapgen015_run", "central_europe_1756_precision_20260813")
    sdir = scenarios_root(cfg.data_dir) / scenario_id
    snap = load_scenario(cfg.data_dir, scenario_id)
    sp = snap.scenario_polities
    canonical = pd.read_csv(sdir / "territorial_control.csv",
                            keep_default_na=False, na_values=[""])
    provenance = pd.read_csv(sdir / "territorial_control_provenance.csv",
                             keep_default_na=False, na_values=[""])
    features = gpd.read_parquet(
        H / "historical_boundary_features.parquet")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    assertions = pd.read_csv(H / "historical_evidence_assertions.csv")
    grid = pd.read_csv(H / "brandenburg_reconstructed_grid_points.csv")
    prim = pd.read_csv(H / "brandenburg_border_observations.csv")
    chk = pd.read_csv(H / "brandenburg_independent_feature_checks.csv",
                      keep_default_na=False, na_values=[""])
    cand = pd.read_csv(H / "brandenburg_prime_meridian_candidate_audit.csv")
    gaudit = pd.read_csv(H / "brandenburg_bnf_georeference_audit.csv")
    corr = pd.read_csv(H / "brandenburg_mapgen018_georef_correction.csv")
    blha = pd.read_csv(H / "brandenburg_blha_copy_audit.csv")
    pol = pd.read_csv(H / "brandenburg_1756_political_evidence.csv",
                      keep_default_na=False, na_values=[""])
    seg = pd.read_csv(H / "brandenburg_boundary_segment_continuity.csv")
    cov = pd.read_csv(sdir / "political_coverage.csv",
                      keep_default_na=False, na_values=[""])
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv"]}
    src_brand = make_global_source_id(CK_BRAND)
    sel = gaudit[gaudit["selected"].astype(bool)].iloc[0]
    acc = chk[chk["accepted"] == "YES"]
    timings["load_s"] = time.perf_counter() - t0

    prov_subj = dict(zip(provenance["territorial_target_id"],
                         provenance["historical_subject_ids"].fillna("")))

    def counts(key):
        ids = [t for t, s in prov_subj.items() if key in s]
        v = canonical[canonical["territorial_target_id"].isin(ids)][
            "control_status"].value_counts().to_dict()
        return {"CONTROLLED": v.get("CONTROLLED", 0),
                "UNRESOLVED": v.get("UNRESOLVED", 0)}

    sax, wei, wash = (counts("meissen_electoral_saxony"),
                      counts("duchy_of_saxe_weimar"), counts("schwarzburg"))

    # ---- gates -----------------------------------------------------------
    _check("R18-01_mapgen018_canonical_regression",
           len(canonical) == 1614
           and int((canonical["control_status"] == "CONTROLLED").sum())
           == 697
           and sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and len(features) == 3,
           f"canonical unchanged: 1,614 rows, Saxony {sax}, 3 features")
    n_mer = int((prim["kind"] == "MERIDIAN_TICK").sum())
    n_par = int((prim["kind"] == "PARALLEL_TICK").sum())
    _check("R18-02_reconstructed_points_identified",
           len(grid) == 18 and n_mer == 6 and n_par == 3
           and len(grid) == n_mer * n_par
           and (grid["observation_type"]
                == "CARTESIAN_PRODUCT_OF_BORDER_OBSERVATIONS").all(),
           f"{len(grid)} MAPGEN-018 rows are the Cartesian product of "
           f"{n_mer} meridian and {n_par} parallel border observations - "
           f"{n_mer + n_par} primitive measurements, not {len(grid)}")
    _check("R18-03_reconstructed_not_counted_as_gcp",
           (grid["classification"] == "RECONSTRUCTED_GRID_POINT").all()
           and (grid["counts_as_production_gcp"] == "NO").all()
           and (grid["pixel_coordinate_directly_observed"] == "NO").all()
           and len(grid) == 18,
           "all 18 rows are retained as audit history but reclassified "
           "RECONSTRUCTED_GRID_POINT and count as 0 production GCPs")
    _check("R18-04_no_cartesian_product_accepted",
           "reconstructed_grid_fit_residual_m" in grid.columns
           and "residual_m" not in grid.columns
           and "reconstructed_grid_holdout_residual_m" in gaudit.columns
           and "holdout_rms_m" not in gaudit.columns,
           "the 60 m figure is renamed reconstructed_grid_* everywhere; "
           "it is not a geographic holdout accuracy and is no longer "
           "recorded under a name that would suggest it is")
    _check("R18-05_primitive_observations_are_one_dimensional",
           (prim["second_coordinate_known"] == "NO").all()
           and (prim["numeral_read"] == "YES").all(),
           f"each of the {len(prim)} border ticks fixes ONE coordinate "
           "and its numeral was read; none is a two-dimensional control "
           "point on its own")
    _check("R18-06_independent_checks_minimum",
           len(acc) >= 5,
           f"{len(acc)} independent feature checks accepted, each located "
           "by cropping its predicted window at native resolution and "
           "reading what is actually printed there")
    quads = set(acc["quadrant"])
    _check("R18-07_checks_spatially_distributed",
           len(quads) >= 3 and "centre" in quads,
           f"checks span {sorted(quads)} - not clustered around Berlin")
    ferro = cand[cand["candidate"] == "FERRO_20W_OF_PARIS"].iloc[0]
    others = cand[cand["candidate"] != "FERRO_20W_OF_PARIS"]
    _check("R18-08_prime_meridian_candidates_compared",
           len(cand) == 3
           and float(ferro["median_residual_km"])
           < float(others["median_residual_km"].min()) / 50
           and int(ferro["n_checks"]) == len(acc),
           f"three candidates scored on the same {len(acc)} checks: Ferro "
           f"{float(ferro['median_residual_km']):.1f} km median against "
           f"{float(others['median_residual_km'].min()):,.0f} km for the "
           "next best, so the meridian is corroborated by multiple points "
           "rather than by one")
    _check("R18-09_georeference_status_downgraded",
           sel["status"] == PROVISIONAL
           and reg.loc[reg["global_source_id"] == src_brand,
                       "georeference_status"].iloc[0]
           != "GEOREFERENCED_VALIDATED",
           f"status is {PROVISIONAL}: the transform was not repaired, it "
           "was demoted")
    med = float(sel["independent_median_km"])
    p90 = float(sel["independent_p90_km"])
    mx = float(sel["independent_max_km"])
    unc = float(sel["positional_uncertainty_km"])
    _check("R18-10_uncertainty_from_multiple_checks",
           int(sel["independent_checks"]) == len(acc)
           and unc > 9.282 and abs(unc - 27.657) < 1e-3,
           f"uncertainty recomputed from {len(acc)} checks (median {med} "
           f"km, p90 {p90} km, max {mx} km) = {unc} km, replacing the "
           "9.282 km that one Berlin point had produced")
    east = acc[acc["quadrant"].isin(["SE", "NE"])]
    centre = acc[acc["quadrant"].isin(["centre", "SW"])]
    _check("R18-11_systematic_error_documented",
           len(east) >= 2 and len(centre) >= 2
           and float(east["residual_km"].min())
           > float(centre["residual_km"].max()) * 2,
           f"the error is systematic, not scatter: centre/SW checks are "
           f"{float(centre['residual_km'].min()):.1f}-"
           f"{float(centre['residual_km'].max()):.1f} km while E/NE checks "
           f"are {float(east['residual_km'].min()):.1f}-"
           f"{float(east['residual_km'].max()):.1f} km. A single check "
           "point could not have revealed this")
    _check("R18-12_no_production_from_provisional_transform",
           len(features) == 3
           and src_brand not in set(features["global_source_id"])
           and src_brand not in set(assertions["global_source_id"]),
           "no boundary was digitised, no assertion written and no "
           "snapshot feature created from a provisional transform")
    brow = cov[cov["coverage_unit_id"] == "region_brandenburg_1756_pilot"]
    _check("R18-13_coverage_downgraded",
           len(brow) == 1
           and brow.iloc[0]["source_evidence_status"]
           == "GEOREFERENCE_PROVISIONAL"
           and brow.iloc[0]["control_coverage_status"] == "UNASSESSED"
           and int((cov["control_coverage_status"] == "COMPLETE").sum())
           == 0,
           "coverage rolled back GEOREFERENCED -> GEOREFERENCE_PROVISIONAL")
    _check("R18-14_blha_shortfall_reported_not_hidden",
           len(blha) == 2
           and (blha["verified_at_source"] == "NO").all()
           and (blha["raster_acquired"] == "NO").all(),
           "SHORTFALL: the stage brief required acquiring AKS 1145 A. "
           "Neither BLHA object was verified at source and neither raster "
           "was acquired in this stage. Reported as a shortfall, not as a "
           "finding")
    _check("R18-15_political_evidence_shortfall_reported",
           len(pol) == 2 and (pol["status"] == "NOT_OBTAINED").all(),
           "SHORTFALL: the brief required opening an individual 1756 "
           "entry of the Novum Corpus. No document was read, so "
           "pinpoint evidence remains 0")
    _check("R18-16_continuity_shortfall_reported",
           len(seg) == 6
           and (seg["continuity_status"] == "UNRESOLVED").all(),
           "SHORTFALL: per-frontier documented search results were "
           "required; the six segments still carry only their original "
           "outstanding questions")
    brand_sp = make_scenario_polity_id(scenario_id, "pol_brandenburg")
    roots = set(sp.loc[sp["territorial_authority_role"]
                       == "COMPOSITE_TERRITORIAL_ACTOR",
                       "scenario_polity_id"])
    _check("R18-17_controller_discipline",
           int((canonical["controller_scenario_polity_id"]
                == brand_sp).sum()) == 0
           and not canonical["controller_scenario_polity_id"].isin(
               roots).any(),
           "pol_brandenburg still holds nothing and no composite root "
           "holds duplicate control")
    empty = pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"])
    log = pd.read_csv(sdir / "scenario_control_promotion_log.csv",
                      keep_default_na=False, na_values=[""])
    c2, p2, l2, rep = promote_control(
        canonical.copy(), provenance.copy(), log.copy(), empty,
        scenario_id, STAGE, M18_COMMIT, "none", "src_none",
        promoted_utc="2026-08-13")
    _check("R18-18_promotion_idempotent",
           rep["inserted"] == 0 and len(c2) == len(canonical)
           and rep["promotion_id"] == make_promotion_id(
               scenario_id, STAGE, sha256_of_frame(empty)),
           "promotion workflow exercised with an empty candidate: 0 "
           "inserted, canonical untouched")
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    wash_feat = features[features["historical_subject_id"]
                         == "hsub_schwarzburg_unpartitioned_wash"]
    _check("R18-19_low_countries_regression",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP",
           "Low Countries still SOURCE_GAP")
    _check("R18-20_schwarzburg_regression",
           len(wash_feat) == 1
           and wash_feat.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY"
           and wash["UNRESOLVED"] == 89,
           "Schwarzburg wash unchanged")
    _check("R18-21_saxony_regression",
           sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and wei == {"CONTROLLED": 0, "UNRESOLVED": 96},
           f"Saxony {sax}, Saxe-Weimar {wei} unchanged")
    _check("R18-22_europe_regression",
           int(eu_man["hex_count"].sum()) == 1885422,
           "Europe canonical grid intact (1,885,422 hexes)")
    _check("R18-23_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN",
           "Toshima hex still OCEAN")
    _check("R18-24_claims_not_derived",
           len(snap.territorial_claims) == 1,
           "claims table still holds its single MAPGEN-008 row")
    comps = pd.read_parquet(geo_dir / "island_components.parquet",
                            columns=["island_component_id"])
    scen_srcs = pd.read_csv(sdir / "sources.csv", keep_default_na=False,
                            na_values=[""])
    struct = set(sp.loc[sp["territorial_authority_role"].isin(
        ["STRUCTURAL_CONTAINER", "COMPOSITE_TERRITORIAL_ACTOR"]),
        "scenario_polity_id"])
    m_hex = set()
    for d in (m14_dir, cfg.output_dir / scfg.get(
            "mapgen013_run", "central_europe_1756_expand_20260813")):
        p = d / "historical_hex_membership.parquet"
        if p.exists():
            m_hex |= set(pd.read_parquet(p, columns=["hex_id"])["hex_id"])
    integ = validate_canonical_control(
        canonical, provenance, sp, scen_srcs,
        set(geo.loc[geo["water_type"] == "NONE", "hex_id"]) | m_hex,
        set(comps["island_component_id"]), struct)
    _check("R18-25_canonical_integrity", integ == [],
           f"canonical integrity: {integ or 'clean'}")
    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("R18-26_upstream_immutable", up_after == upstream,
           f"{len(upstream)} upstream artifacts byte-identical")
    _check("R18-27_no_new_schema",
           HPG_SCHEMA_VERSION == "1.4.0"
           and SCENARIO_SCHEMA_VERSION == "1.5.0"
           and not scan_forbidden_reference_code(Path(__file__)),
           "scenario schema at the pinned 1.5.0; module passes the forbidden-reference scan")

    # ---- outputs ---------------------------------------------------------
    t0 = time.perf_counter()
    img = ["reconstructed_vs_observed_gcps.png",
           "brandenburg_independent_checks.png",
           "prime_meridian_candidate_comparison.png",
           "brandenburg_georef_status_after_review.png"]
    render_reconstructed(run_dir / img[0], grid, prim, corr,
                         "A. What MAPGEN-018 called 18 control points")
    render_checks(run_dir / img[1], chk,
                  "B. Independent feature checks — the systematic error")
    render_meridian(run_dir / img[2], cand,
                    "C. Prime-meridian candidates on the same checks")
    summary = [
        ("stage", STAGE), ("base_commit_mapgen018", M18_COMMIT),
        ("outcome", "PARTIAL"),
        ("georeference_status", PROVISIONAL),
        ("reconstructed_grid_points", len(grid)),
        ("production_gcps", 0),
        ("primitive_observations", len(prim)),
        ("meridian_observations", n_mer),
        ("parallel_observations", n_par),
        ("directly_observed_gcps", 0),
        ("independent_checks", len(acc)),
        ("check_quadrants", ", ".join(sorted(quads))),
        ("independent_median_km", med),
        ("independent_p90_km", p90),
        ("independent_p95_km", float(sel["independent_p95_km"])),
        ("independent_max_km", mx),
        ("prime_meridian", "FERRO_20W_OF_PARIS"),
        ("prime_meridian_status", ferro["status"]),
        ("prime_meridian_next_best_km",
         float(others["median_residual_km"].min())),
        ("mapgen018_uncertainty_km", 9.282),
        ("corrected_uncertainty_km", unc),
        ("reconstructed_grid_residual_m",
         round(float(sel["reconstructed_grid_holdout_residual_m"]), 1)),
        ("coverage_status", brow.iloc[0]["source_evidence_status"]),
        ("blha_1132_result", "NOT_VERIFIED_AT_SOURCE (shortfall)"),
        ("blha_1145_result", "NOT_ACQUIRED (shortfall)"),
        ("political_documents_read", 0),
        ("continuity_segments", len(seg)),
        ("continuity_segments_researched", 0),
        ("new_production_features", 0),
        ("authorised_snapshot_features", 0),
        ("new_hex_membership_rows", 0),
        ("brandenburg_controlled", 0), ("brandenburg_unresolved", 0),
        ("saxony_controlled", sax["CONTROLLED"]),
        ("saxony_unresolved", sax["UNRESOLVED"]),
        ("canonical_rows_before", len(canonical)),
        ("canonical_rows_after", len(canonical)),
        ("canonical_rows_changed", 0),
        ("validation_pass", ""),
    ]
    sd = dict(summary)
    render_status(run_dir / img[3], sd,
                  "D. Brandenburg georeference status after review")
    from PIL import Image

    aspects = {}
    for n in img:
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.size[0] / im.size[1], 3)
    _check("R18-28_no_fake_validation_shown",
           "brandenburg_blha_source.png" not in img
           and "brandenburg_blha_georef.png" not in img
           and "brandenburg_bnf_georef_corrected.png" not in img,
           "no BLHA figure and no 'corrected georeference' figure was "
           "produced: the transform was not corrected, it was downgraded")
    timings["render_s"] = time.perf_counter() - t0

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    summary = [(k, v) for k, v in summary if k != "validation_pass"] + [
        ("validation_pass", f"{n_pass}/{len(val)}")]
    pd.DataFrame(summary, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "summary.csv", index=False)
    manifest = {
        "run_id": run_id, "stage": STAGE, "outcome": "PARTIAL",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen018": M18_COMMIT,
        "diagnosis": dict(corr.iloc[0]),
        "georeference_status": PROVISIONAL,
        "independent_checks": {
            "n": len(acc), "median_km": med, "p90_km": p90, "max_km": mx,
            "quadrants": sorted(quads)},
        "prime_meridian": {
            "selected": "FERRO_20W_OF_PARIS",
            "status": ferro["status"],
            "candidates": cand.to_dict("records")},
        "shortfalls_against_the_brief": [
            "BLHA AKS 1145 A was not acquired and neither BLHA object was "
            "verified at source",
            "no individual 1756 Novum Corpus entry was opened",
            "the six continuity segments were not individually researched",
        ],
        "upstream_sha256": upstream,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    _write_readme(run_dir, run_id, dict(summary), chk, cand, aspects, img)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    cmap = {
        "README_REVIEW.md": run_dir / "README_REVIEW.md",
        "run_manifest.json": run_dir / "run_manifest.json",
        "validation.csv": run_dir / "validation.csv",
        "summary.csv": run_dir / "summary.csv",
        "brandenburg_mapgen018_georef_correction.csv":
            H / "brandenburg_mapgen018_georef_correction.csv",
        "brandenburg_reconstructed_grid_points.csv":
            H / "brandenburg_reconstructed_grid_points.csv",
        "brandenburg_border_observations.csv":
            H / "brandenburg_border_observations.csv",
        "brandenburg_independent_feature_checks.csv":
            H / "brandenburg_independent_feature_checks.csv",
        "brandenburg_prime_meridian_candidate_audit.csv":
            H / "brandenburg_prime_meridian_candidate_audit.csv",
        "brandenburg_bnf_georeference_audit.csv":
            H / "brandenburg_bnf_georeference_audit.csv",
        "brandenburg_blha_copy_audit.csv":
            H / "brandenburg_blha_copy_audit.csv",
        "brandenburg_blha_gcps.csv": H / "brandenburg_blha_gcps.csv",
        "brandenburg_blha_georeference_audit.csv":
            H / "brandenburg_blha_georeference_audit.csv",
        "brandenburg_1756_political_evidence.csv":
            H / "brandenburg_1756_political_evidence.csv",
        "brandenburg_boundary_segment_continuity.csv":
            H / "brandenburg_boundary_segment_continuity.csv",
        "historical_map_copy_registry.csv":
            H / "historical_map_copy_registry.csv",
        "historical_source_lineage.csv":
            H / "historical_source_lineage.csv",
        "scenario_political_coverage.csv": sdir / "political_coverage.csv",
        "territorial_control.csv": sdir / "territorial_control.csv",
        "territorial_control_provenance.csv":
            sdir / "territorial_control_provenance.csv",
        "scenario_control_promotion_log.csv":
            sdir / "scenario_control_promotion_log.csv",
        "historical_hex_membership.csv":
            m15_dir / "chatgpt_review" / "historical_hex_membership.csv",
    }
    for dst, src in cmap.items():
        if Path(src).exists():
            shutil.copy2(src, review / dst)
    pd.DataFrame(features.drop(columns="geometry")).to_csv(
        review / "historical_boundary_features.csv", index=False)
    for n in img:
        shutil.copy2(run_dir / n, review / n)
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    shutil.copy2(run_dir / "run_manifest.json", review / "run_manifest.json")
    print(f"[georef-review] {run_id}: validation {n_pass}/{len(val)}, "
          f"status {PROVISIONAL}, {len(acc)} checks median {med} km max "
          f"{mx} km, uncertainty {unc} km, canonical unchanged "
          f"({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[georef-review][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, chk, cand, aspects, img):
    acc = chk[chk["accepted"] == "YES"]
    lines = [
        f"# {STAGE} Review — the Brandenburg georeference does not "
        "survive review",
        "",
        "**OUTCOME: PARTIAL.** The MAPGEN-018 transform is **downgraded, "
        "not repaired**. The prime meridian is now corroborated by five "
        "independent points instead of one, and the real positional error "
        "turns out to be far larger and systematic. No geometry, no "
        "control, no canonical row changed.",
        "",
        f"Run `{run_id}`, built on MAPGEN-018 commit "
        f"`{s['base_commit_mapgen018']}`.",
        "",
        "## 1. The flaw, stated plainly",
        "",
        f"- MAPGEN-018 reported **{s['reconstructed_grid_points']} "
        "graticule control points**. They were not eighteen "
        f"observations. **{s['meridian_observations']} meridian ticks** "
        "were measured on the top border and "
        f"**{s['parallel_observations']} parallel ticks** on the left "
        f"border — **{s['primitive_observations']} primitive "
        "measurements** — and the pairs were formed by crossing them.",
        "- Each longitude therefore reused one `pixel_x` three times and "
        "each latitude reused one `pixel_y` six times.",
        "- **The fit/holdout split shared primitive observations.** Every "
        "held-out point drew its *y* from a parallel that was also in the "
        f"fit. That is why the \"holdout RMS\" came out at "
        f"{s['reconstructed_grid_residual_m']} m: an affine model "
        "reproduces a rectangle it was handed. It measured **nothing** "
        "about geography.",
        "- A meridian tick on the top border fixes a longitude and an *x*. "
        "It does **not** fix a latitude. It is not a two-dimensional "
        "control point on its own, and crossing it with a parallel tick "
        "does not make one.",
        "",
        "## 2. What one check point hid",
        "",
        f"- MAPGEN-018 validated with **one** point. Berlin came out at "
        "9.3 km, which reads as ordinary eighteenth-century placement "
        "error.",
        f"- **{s['independent_checks']} checks** were located this time by "
        "cropping each predicted window at native resolution and reading "
        "what is actually printed there. Three of those windows contained "
        "**the wrong town**: the window predicted for Frankfurt an der "
        "Oder held **Fürstenwalde**, Neuruppin's held **Fehrbellin**, and "
        "Schwedt's held **Angermünde**.",
        "",
        "| check | quadrant | residual |",
        "|---|---|---|",
    ]
    for r in acc.itertuples():
        lines.append(f"| {r.reference_feature_name} | {r.quadrant} | "
                     f"{r.residual_km:.2f} km |")
    lines += [
        "",
        f"- Median **{s['independent_median_km']} km**, p90 "
        f"**{s['independent_p90_km']} km**, max "
        f"**{s['independent_max_km']} km**. Centre and south-west sit "
        "near 8–9 km; east and north-east near 26–29 km.",
        "- **That is systematic, not scatter** — and it is precisely what "
        "a single check cannot reveal. The likely cause is that the plate "
        "is not on a rectangular graticule, so a border-derived "
        "axis-by-axis model degrades away from the centre.",
        "",
        "## 3. The prime meridian, settled properly",
        "",
        "- The sheet states no prime meridian. Rather than inherit Ferro "
        "from the other Vaugondy plates, three candidates were scored "
        "against the **same** independent checks:",
        "",
        "| candidate | median residual |",
        "|---|---|",
    ]
    for r in cand.itertuples():
        lines.append(f"| {r.candidate} | {r.median_residual_km:,.2f} km |")
    lines += [
        "",
        f"- Ferro wins by more than two orders of magnitude "
        f"(`{s['prime_meridian_status']}`). **That settles the meridian. "
        "It does not validate the transform** — even under Ferro the "
        f"residuals reach {s['independent_max_km']} km.",
        "",
        "## 4. What changed in the data",
        "",
        f"- Status: `GEOREFERENCED` → **`{s['georeference_status']}`**. "
        f"Coverage: `GEOREFERENCED` → **`{s['coverage_status']}`**.",
        f"- The 18 rows are **retained** as audit history, reclassified "
        "`RECONSTRUCTED_GRID_POINT` with "
        "`pixel_coordinate_directly_observed = NO` and "
        f"`counts_as_production_gcp = NO`. **Production GCPs: "
        f"{s['production_gcps']}. Directly observed 2-D GCPs: "
        f"{s['directly_observed_gcps']}.**",
        f"- The 60 m figure is renamed `reconstructed_grid_*` everywhere "
        "so it can never again be quoted as a holdout accuracy.",
        f"- Uncertainty: **{s['mapgen018_uncertainty_km']} km → "
        f"{s['corrected_uncertainty_km']} km**, now derived from the p90 "
        "of multiple checks rather than from one Berlin residual.",
        f"- Canonical rows {s['canonical_rows_before']:,} → "
        f"{s['canonical_rows_after']:,}, changed "
        f"**{s['canonical_rows_changed']}**. Brandenburg CONTROLLED "
        f"**{s['brandenburg_controlled']}**.",
        "",
        "## 5. Shortfalls against the brief — reported as shortfalls",
        "",
        "These were required by the stage brief and **were not done**. "
        "They are not findings:",
        "",
        f"- **BLHA AKS 1132 A**: {s['blha_1132_result']}.",
        f"- **BLHA AKS 1145 A**: {s['blha_1145_result']}. The brief made "
        "acquisition mandatory and required an HTTP/rights blocker to be "
        "recorded if it failed; neither happened.",
        f"- **1756 political documents read: "
        f"{s['political_documents_read']}.** No individual Novum Corpus "
        "entry was opened.",
        f"- **Continuity segments individually researched: "
        f"{s['continuity_segments_researched']} of "
        f"{s['continuity_segments']}.**",
        "",
        "The georeference review consumed the stage. That is the honest "
        "reason, not a justification.",
        "",
        "## 6. Images",
        "",
    ]
    for n in img:
        lines.append(f"- `{n}` (aspect {aspects[n]})")
    lines += [
        "",
        "There is deliberately no “corrected georeference” figure and no "
        "BLHA figure — the transform was not corrected and no BLHA raster "
        "exists.",
        "",
        "## 7. Validation",
        "",
        f"- `validation.csv`: R18 gates, pass count "
        f"{s['validation_pass']}.",
        "",
        "## 8. Known issues",
        "",
        "- **No directly observed two-dimensional control point exists "
        "yet.** The next attempt must either trace interior graticule "
        "lines to real intersections, or build the control set from "
        "identified feature points with their own fit/holdout.",
        "- The residual pattern suggests a non-rectangular plate "
        "graticule. A projective or trapezoidal model fitted to *observed* "
        "points may absorb it; an axis-by-axis border model cannot.",
        "- Only five checks, and one (Brandenburg an der Havel) is the "
        "Neustadt rather than the modern centre, so its residual carries "
        "an identification offset of its own.",
        "- BLHA, the 1756 documents and the continuity research all "
        "remain outstanding.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
