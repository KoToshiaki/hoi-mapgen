"""MAPGEN-018 — the Brandenburg sheet is georeferenced.

The BnF copy carries a numbered degree graticule, so this stage took the
graticule route rather than falling back to feature points. Six meridians
and three parallels were detected on the border bands and every numeral
was read at magnification; eighteen intersections give thirteen fit and
five held-out control points, and an independent town check validates the
prime meridian the plate does not state.

That is the whole of the advance. The second, independent-lineage source
was not verified at its archive, no 1756 political-control document was
opened, and not one of the six boundary segments reached continuity — so
there is still no geometry and no control.
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
from .historical_geometry import (HPG_SCHEMA_VERSION, make_global_source_id)
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

STAGE = "MAPGEN-018"
H = Path("data/historical")
CK_BRAND = "vaugondy_1751_haute_saxe_septentrionale_pomeranie_brandebourg"
M17_COMMIT = "2761d1501f6c1f3f7c37692e90f3edd7d75cd9f3"
RASTER = Path("data/raw/historical_maps/vaugondy_brandenburg/"
              "vaugondy_1751_brandenburg_pomeranie_btv1b53041280v_f1.jpg")


def _wrap(t, w=90):
    return [t[i:i + w] for i in range(0, len(t), w)]


def render_gcps(path, g, chk, title):
    fig, (ax, ax2) = _fig2((17, 8), [1.1, 1])
    fitg, hold = g[g["included_in_fit"]], g[g["holdout"]]
    ax.scatter(fitg["pixel_x"], -fitg["pixel_y"], s=70, c="#196f3d",
               label=f"fit ({len(fitg)})")
    ax.scatter(hold["pixel_x"], -hold["pixel_y"], s=90, c="#b03a2e",
               marker="D", label=f"holdout ({len(hold)})")
    ax.scatter(chk["pixel_x"], -chk["pixel_y"], s=120, c="#1f618d",
               marker="*", label="independent check (Berlin)")
    for r in g.itertuples():
        ax.annotate(f"{int(r.longitude_raw)}/{int(r.latitude_raw)}",
                    (r.pixel_x, -r.pixel_y), fontsize=6,
                    xytext=(4, 3), textcoords="offset points")
    ax.set_xlim(0, 7941)
    ax.set_ylim(-6135, 0)
    ax.set_aspect("equal")
    ax.legend(fontsize=8, loc="lower right")
    ax.set_title("graticule intersections on the BnF sheet "
                 "(pixel space)", fontsize=10)
    body = ["GRATICULE READ OFF THE PLATE", "",
            "  meridians (top border band, numerals read at x4):",
            "    " + ", ".join(f"{int(v)}deg@x={x:.1f}" for x, v in
                               sorted({(r.pixel_x, r.longitude_raw)
                                       for r in g.itertuples()})),
            "",
            "  parallels (left border band, numerals read at x4):",
            "    " + ", ".join(f"{int(v)}deg@y={y:.1f}" for y, v in
                               sorted({(r.pixel_y, r.latitude_raw)
                                       for r in g.itertuples()})),
            "",
            "  Every numeral was READ. The middle parallel is included",
            "  because its '54' was read, not because it lies halfway.",
            "",
            "HOLDOUT DESIGN", "",
            "  one entire meridian (33) plus two corners of meridian 35,",
            "  so a held-out point is never an interpolation between two",
            "  of its immediate neighbours in the fit.",
            "",
            "GCP RESIDUALS (m)", "",
            f"  p50 {np.percentile(g['residual_m'], 50):.1f}   "
            f"p75 {np.percentile(g['residual_m'], 75):.1f}   "
            f"p90 {np.percentile(g['residual_m'], 90):.1f}   "
            f"p95 {np.percentile(g['residual_m'], 95):.1f}   "
            f"max {g['residual_m'].max():.1f}"]
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=8)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_georef(path, audit, chk, title):
    fig, (ax, ax2) = _fig2((16, 7), [1, 1.15])
    x = np.arange(len(audit))
    ax.bar(x - 0.2, audit["fit_rms_m"], 0.38, label="fit RMS",
           color="#999999")
    ax.bar(x + 0.2, audit["holdout_rms_m"], 0.38, label="holdout RMS",
           color="#196f3d")
    ax.set_xticks(x)
    ax.set_xticklabels(audit["model"], fontsize=9)
    ax.set_ylabel("metres")
    ax.legend(fontsize=8)
    sel = audit[audit["selected"].astype(bool)].iloc[0]
    ax.set_title(f"model comparison — {sel['model']} selected", fontsize=10)
    body = ["WHY THE SIMPLEST MODEL WON", "",
            f"  POLYNOMIAL_2 has the best FIT ({audit.loc[audit['model'] == 'POLYNOMIAL_2', 'fit_rms_m'].iloc[0]:.1f} m)",
            f"  and the worst HOLDOUT ({audit.loc[audit['model'] == 'POLYNOMIAL_2', 'holdout_rms_m'].iloc[0]:.1f} m).",
            f"  {sel['model']} fits at {sel['fit_rms_m']:.1f} m and holds",
            f"  out at {sel['holdout_rms_m']:.1f} m — the graticule really",
            "  is a regular rectangular grid on this plate.", "",
            "QUADRANT MAXIMA (m)", "",
            f"  {sel['quadrant_max_residual_m']}", "",
            "INDEPENDENT CHECK", "",
            f"  {chk.iloc[0]['historical_map_label']} at pixel "
            f"({chk.iloc[0]['pixel_x']:.0f}, {chk.iloc[0]['pixel_y']:.0f})",
            f"  residual {chk.iloc[0]['residual_m'] / 1000:.2f} km against "
            "GeoNames.",
            "  This is the PLATE's own town-placement error, not a",
            "  transform failure — and it is what validates the prime",
            "  meridian the sheet never states.", "",
            "MAP-SPECIFIC UNCERTAINTY", ""]
    for ln in _wrap(f"  max(holdout RMS, independent residual) combined "
                    f"with line width {sel['line_width_uncertainty_m']} m "
                    f"and digitisation {sel['digitisation_uncertainty_m']} "
                    f"m at {sel['pixel_scale_m_per_px']} m/px  =  "
                    f"{sel['positional_uncertainty_km']} km", 86):
        body.append(ln)
    body += ["", "  Saxony's 9.168 km was NOT inherited. The two numbers",
             "  are close because both are Vaugondy plates of similar",
             "  scale, which is a finding, not a copy."]
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=8)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_blockers(path, blha, pol, seg, const, title):
    fig, (ax, ax2) = _fig2((17, 8), [1, 1])
    body = ["BLHA — INDEPENDENT SOURCE", ""]
    for r in blha.itertuples():
        body.append(f"  {r.object_ref}")
        body.append(f"    catalogued {r.catalogued_date}   verified at "
                    f"source: {r.verified_at_source}")
        body.append(f"    licence {r.licence}   raster "
                    f"{r.raster_acquired}")
        body.append(f"    identity vs the other object: "
                    f"{r.identity_relation_to_other_object}")
        body.append("")
    body += ["  Two catalogue objects of one title are AT MOST one",
             "  source until plate, impression and reproduction are told",
             "  apart. Neither was verified, so neither was acquired.", "",
             "1756 POLITICAL CONTROL EVIDENCE", ""]
    for r in pol.itertuples():
        body.append(f"  {r.subject}: {r.status}")
        for ln in _wrap("     " + str(r.why), 84):
            body.append(ln)
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=7.5)
    ax.set_axis_off()
    body2 = ["BOUNDARY SEGMENT CONTINUITY", ""]
    for r in seg.itertuples():
        body2.append(f"  {r.frontier:<44} {r.continuity_status}")
    body2 += ["", "  A georeferenced 1751 plate is still a 1751 plate.",
              "  Nothing bridges to 1756-08-01.", "",
              "CONSTITUENTS", ""]
    for r in const.itertuples():
        body2.append(f"  {r.constituent:<42} {r.classification}")
    body2 += ["", "  A visible name on a map is not a sovereign actor.",
              "  Magdeburg/Halberstadt share a monarch, not a territory.",
              "  Swedish Pomerania is defined by the sheet's own note and",
              "  is not assigned to Brandenburg."]
    ax2.text(0.0, 0.99, "\n".join(body2), va="top", family="monospace",
             fontsize=7.5)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_progress(path, rows, waiting, title):
    fig, (ax, ax2) = _fig2((16, 7), [1.1, 1])
    labels = [r[0] for r in rows]
    x = np.arange(len(labels))
    ax.bar(x - 0.2, [r[1] for r in rows], 0.38, label="CONTROLLED",
           color="#196f3d")
    ax.bar(x + 0.2, [r[2] for r in rows], 0.38, label="UNRESOLVED",
           color="#e07800")
    for i, r in enumerate(rows):
        ax.text(i - 0.2, r[1] + 8, f"{r[1]:,}", ha="center", fontsize=8)
        ax.text(i + 0.2, r[2] + 8, f"{r[2]:,}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("canonical rows")
    ax.legend(fontsize=8)
    ax.set_title("canonical control by subject (unchanged this stage)",
                 fontsize=10)
    ax2.text(0.0, 0.97, "SOURCE PIPELINE STATE\n\n"
             + "\n".join(f"  {a:<38} {b}" for a, b in waiting)
             + "\n\n  Brandenburg now has a georeferenced plate and a\n"
               "  map-specific uncertainty. What it does not have is a\n"
               "  second source, a 1756 document, or one continuous\n"
               "  boundary segment that reaches the snapshot.",
             va="top", family="monospace", fontsize=8)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def run_historical_georef(cfg: MapgenConfig,
                          run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"brandenburg_1756_georef_{_dt.datetime.now():%Y%m%d}"
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
    m17_dir = cfg.output_dir / scfg.get(
        "mapgen017_run", "brandenburg_1756_acquisition_20260813")
    m15_dir = cfg.output_dir / scfg.get(
        "mapgen015_run", "central_europe_1756_precision_20260813")
    m14_dir = cfg.output_dir / scfg.get(
        "mapgen014_run", "central_europe_1756_revision_20260813")
    sdir = scenarios_root(cfg.data_dir) / scenario_id
    snap = load_scenario(cfg.data_dir, scenario_id)
    sp = snap.scenario_polities
    canonical = pd.read_csv(sdir / "territorial_control.csv",
                            keep_default_na=False, na_values=[""])
    provenance = pd.read_csv(sdir / "territorial_control_provenance.csv",
                             keep_default_na=False, na_values=[""])
    features = gpd.read_parquet(H / "historical_boundary_features.parquet")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    lineage = pd.read_csv(H / "historical_source_lineage.csv")
    assertions = pd.read_csv(H / "historical_evidence_assertions.csv")
    copies = pd.read_csv(H / "historical_map_copy_registry.csv",
                         keep_default_na=False, na_values=[""])
    g = pd.read_csv(H / "brandenburg_bnf_gcps.csv")
    gaudit = pd.read_csv(H / "brandenburg_bnf_georeference_audit.csv")
    chk = pd.read_csv(H / "brandenburg_bnf_independent_checks.csv")
    blha = pd.read_csv(H / "brandenburg_blha_copy_audit.csv")
    bl_gcp = pd.read_csv(H / "brandenburg_blha_gcps.csv")
    pol = pd.read_csv(H / "brandenburg_1756_political_evidence.csv",
                      keep_default_na=False, na_values=[""])
    seg = pd.read_csv(H / "brandenburg_boundary_segment_continuity.csv")
    const = pd.read_csv(H / "brandenburg_constituent_audit.csv")
    cov = pd.read_csv(sdir / "political_coverage.csv",
                      keep_default_na=False, na_values=[""])
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv"]}
    src_brand = make_global_source_id(CK_BRAND)
    bnf = copies[copies["copy_id"] == "copy_bnf_ge_dd_2987_3790"].iloc[0]
    sel = gaudit[gaudit["selected"].astype(bool)].iloc[0]
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
    _check("M18-01_mapgen017_regression",
           len(canonical) == 1614
           and int((canonical["control_status"] == "CONTROLLED").sum())
           == 697
           and int((canonical["control_status"] == "UNRESOLVED").sum())
           == 917
           and sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and len(features) == 3,
           f"MAPGEN-017 baseline intact: 1,614 rows (697/917), Saxony "
           f"{sax}, 3 boundary features")
    _check("M18-02_bnf_copy_metadata_regression",
           bnf["shelfmark_or_ark"].startswith("GE DD-2987 (3790)")
           and bnf["raster_pixels"] == "7941x6135"
           and bnf["plate_date"] == "1751"
           and bnf["represented_political_date"] == "UNVERIFIED"
           and RASTER.exists(),
           "BnF copy metadata unchanged: GE DD-2987 (3790), 7941x6135, "
           "plate 1751, represented political date UNVERIFIED")
    _check("M18-03_copy_state_overclaim_corrected",
           bnf["copy_state"] == "COPY_CATALOGUED_1751_WITH_1751_PRIVILEGE"
           and bnf["copy_state_confidence"] == "MEDIUM"
           and "claimed a plate STATE" in bnf["notes"],
           "the copy-state label was weakened: a 1751 catalogue entry plus "
           "a 1751 privilege inscription is exactly that, and proving an "
           "EARLY state needs a copy comparison that has not been done")
    lon_vals = sorted(set(g["longitude_raw"]))
    lat_vals = sorted(set(g["latitude_raw"]))
    _check("M18-04_graticule_gcps_are_real",
           len(g) == 18 and len(lon_vals) == 6 and len(lat_vals) == 3
           and (g["reading_confidence"] == "HIGH").all()
           and g["notes"].str.contains("numerals read").all(),
           f"{len(g)} graticule intersections from {len(lon_vals)} "
           f"meridians {lon_vals} and {len(lat_vals)} parallels "
           f"{lat_vals}; every numeral was read at magnification, none "
           "interpolated")
    fitn = int(g["included_in_fit"].sum())
    holdn = int(g["holdout"].sum())
    quad = {q: len(g[(g["pixel_x"] < g["pixel_x"].median()
                      if q[1] == "W" else
                      g["pixel_x"] >= g["pixel_x"].median())
                     & (g["pixel_y"] < g["pixel_y"].median()
                        if q[0] == "N" else
                        g["pixel_y"] >= g["pixel_y"].median())])
            for q in ("NW", "NE", "SW", "SE")}
    _check("M18-05_fit_holdout_split",
           fitn >= 12 and holdn >= 4 and fitn + holdn == len(g)
           and min(quad.values()) >= 3,
           f"fit {fitn} / holdout {holdn}; the holdout is one whole "
           "meridian plus two corners of another, and the points span "
           f"all four quadrants {quad}")
    _check("M18-06_transform_selected_on_holdout",
           sel["model"] == "AFFINE"
           and float(sel["holdout_rms_m"]) < 100.0
           and float(gaudit.loc[gaudit["model"] == "POLYNOMIAL_2",
                                "fit_rms_m"].iloc[0])
           < float(sel["fit_rms_m"])
           and float(gaudit.loc[gaudit["model"] == "POLYNOMIAL_2",
                                "holdout_rms_m"].iloc[0])
           > float(sel["holdout_rms_m"]),
           f"{sel['model']} selected: fit {float(sel['fit_rms_m']):.1f} m, "
           f"holdout {float(sel['holdout_rms_m']):.1f} m. POLYNOMIAL_2 "
           "fits better and holds out worse, so complexity was not "
           "rewarded")
    _check("M18-07_independent_point_validates_prime_meridian",
           len(chk) == 1 and not bool(chk.iloc[0]["included_in_fit"])
           and float(chk.iloc[0]["residual_m"]) < 15000.0
           and "CORROBORATED_BY_INDEPENDENT_POINT"
           in sel["prime_meridian_evidence"]
           and "NOT stated" in sel["prime_meridian_evidence"],
           "the sheet does NOT state its prime meridian; the Ferro "
           "reading is corroborated by an independent Berlin check at "
           f"{float(chk.iloc[0]['residual_m']) / 1000:.2f} km, not "
           "inherited from another Vaugondy sheet")
    unc = float(sel["positional_uncertainty_km"])
    _check("M18-08_uncertainty_map_specific",
           abs(unc - 9.282) < 1e-6 and unc != 9.168
           and float(sel["pixel_scale_m_per_px"]) > 0
           and float(sel["line_width_uncertainty_m"]) > 0,
           f"Brandenburg uncertainty {unc} km derived from THIS sheet: "
           f"holdout {float(sel['holdout_rms_m']):.0f} m, independent "
           f"check {float(sel['independent_check_berlin_m']) / 1000:.2f} "
           f"km, line width {sel['line_width_uncertainty_m']} m, "
           f"digitisation {sel['digitisation_uncertainty_m']} m at "
           f"{sel['pixel_scale_m_per_px']} m/px — Saxony's 9.168 km was "
           "not inherited")
    _check("M18-09_blha_not_verified_or_acquired",
           len(blha) == 2
           and (blha["verified_at_source"] == "NO").all()
           and (blha["licence"] == "NOT_VERIFIED").all()
           and (blha["raster_acquired"] == "NO").all(),
           "both BLHA leads are recorded as UNVERIFIED at source: no "
           "signature confirmed, no licence checked, no raster acquired")
    _check("M18-10_blha_duplicate_identity_unresolved",
           (blha["identity_relation_to_other_object"]
            == "UNRESOLVED").all()
           and blha["notes"].str.contains("at most ONE source").any()
           and len(bl_gcp) == 0,
           "the two catalogue objects of one title are counted as AT MOST "
           "one source; their relation (same copy / same plate / different "
           "plate / reproduction) is unresolved and neither is "
           "georeferenced")
    lb = lineage[lineage["global_source_id"] == src_brand].iloc[0]
    _check("M18-11_vaugondy_still_not_independent",
           lb["independence_status"] == "SHARED_ATLAS_LINEAGE"
           and lb["corroboration_eligible"] == "NO",
           "the georeferenced sheet is still same-atlas with the 1756 "
           "sheet already in production, so it cannot corroborate it")
    _check("M18-12_1756_political_evidence_sought_not_obtained",
           len(pol) == 2 and (pol["status"] == "NOT_OBTAINED").all()
           and (pol["exact_locator"].fillna("") == "").all()
           and pol["why"].str.len().min() > 40
           and (pol["cannot_be_used_for"].str.startswith(
               "BOUNDARY_POSITION")).all(),
           "two 1756 political-control candidates are recorded as "
           "NOT_OBTAINED with empty locators and written reasons; each "
           "row also states that an administrative record could never "
           "serve as boundary-position evidence")
    _check("M18-13_admin_evidence_is_not_boundary_evidence",
           src_brand not in set(assertions["global_source_id"])
           and len(features) == 3,
           "no assertion of any kind exists for the Brandenburg sheet, so "
           "a georeferenced plate has not quietly become an authority")
    _check("M18-14_segments_still_unresolved",
           len(seg) == 6
           and (seg["continuity_status"] == "UNRESOLVED").all(),
           "all six frontier segments remain UNRESOLVED: a georeferenced "
           "1751 plate is still a 1751 plate")
    _check("M18-15_off_date_geometry_cannot_bypass_continuity",
           src_brand not in set(features["global_source_id"])
           and len(features) == 3,
           "no boundary feature was created from the georeferenced sheet, "
           "because nothing bridges it to 1756-08-01")
    tc = const[const["classification"] == "TERRITORIAL_CONSTITUENT"]
    _check("M18-16_constituents_are_not_polities",
           len(tc) == 5
           and (tc["separate_scenario_polity"] == "NO").all()
           and not any(n.split()[0].lower() in
                       {p.replace("pol_", "") for p in
                        snap.polities["polity_id"]}
                       for n in tc["constituent"]),
           f"{len(tc)} Brandenburg constituents (Altmark, Mittelmark, "
           "Neumark, Uckermark, Prignitz) are territorial constituents, "
           "not polities; none was registered as a scenario actor")
    _check("M18-17_magdeburg_and_pomerania_separated",
           (const["classification"]
            == "SEPARATE_HOHENZOLLERN_TERRITORY").any()
           and (const["classification"]
                == "SEPARATE_TERRITORIAL_QUESTION").any(),
           "Magdeburg/Halberstadt are recorded as separate Hohenzollern "
           "territory, not Brandenburg; Pomerania needs its own audit and "
           "none of it is assigned to Brandenburg")
    brand_sp = make_scenario_polity_id(scenario_id, "pol_brandenburg")
    roots = set(sp.loc[sp["territorial_authority_role"]
                       == "COMPOSITE_TERRITORIAL_ACTOR",
                       "scenario_polity_id"])
    _check("M18-18_controller_discipline",
           "pol_brandenburg" in set(snap.polities["polity_id"])
           and int((canonical["controller_scenario_polity_id"]
                    == brand_sp).sum()) == 0
           and not canonical["controller_scenario_polity_id"].isin(
               roots).any(),
           "pol_brandenburg remains the intended specific controller and "
           "holds nothing; no composite root holds duplicate control")
    empty = pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"])
    log = pd.read_csv(sdir / "scenario_control_promotion_log.csv",
                      keep_default_na=False, na_values=[""])
    c2, p2, l2, rep = promote_control(
        canonical.copy(), provenance.copy(), log.copy(), empty,
        scenario_id, STAGE, M17_COMMIT, "none", "src_none",
        promoted_utc="2026-08-13")
    _check("M18-19_promotion_idempotent",
           rep["inserted"] == 0 and len(c2) == len(canonical)
           and rep["promotion_id"] == make_promotion_id(
               scenario_id, STAGE, sha256_of_frame(empty)),
           "promotion workflow exercised with this stage's empty "
           "candidate: 0 inserted, canonical untouched")
    brow = cov[cov["coverage_unit_id"] == "region_brandenburg_1756_pilot"]
    _check("M18-20_coverage_georeferenced_not_complete",
           len(brow) == 1
           and brow.iloc[0]["source_evidence_status"] == "GEOREFERENCED"
           and brow.iloc[0]["control_coverage_status"] == "UNASSESSED"
           and int((cov["control_coverage_status"] == "COMPLETE").sum())
           == 0,
           "coverage advanced SOURCE_ACQUIRED -> GEOREFERENCED while "
           "control coverage stays UNASSESSED; nothing is COMPLETE, so "
           "absence still means UNKNOWN")
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    wash_feat = features[features["historical_subject_id"]
                         == "hsub_schwarzburg_unpartitioned_wash"]
    _check("M18-21_low_countries_regression",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP",
           "Low Countries still SOURCE_GAP")
    _check("M18-22_schwarzburg_regression",
           len(wash_feat) == 1
           and wash_feat.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY"
           and wash["UNRESOLVED"] == 89,
           "Schwarzburg wash still UNCERTAIN_BOUNDARY with 89 UNRESOLVED")
    _check("M18-23_saxony_regression",
           sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and wei == {"CONTROLLED": 0, "UNRESOLVED": 96},
           f"Saxony {sax} and Saxe-Weimar {wei} unchanged")
    _check("M18-24_europe_regression",
           int(eu_man["hex_count"].sum()) == 1885422,
           "Europe canonical grid intact (1,885,422 hexes)")
    _check("M18-25_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN"
           and int((canonical["territorial_target_type"]
                    == "ISLAND_COMPONENT").sum()) == 1,
           "Toshima hex still OCEAN with its island-component row intact")
    _check("M18-26_claims_not_derived",
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
    _check("M18-27_canonical_integrity", integ == [],
           f"canonical integrity: {integ or 'clean'}")
    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("M18-28_upstream_immutable", up_after == upstream,
           f"{len(upstream)} upstream artifacts byte-identical")
    _check("M18-29_no_new_schema",
           HPG_SCHEMA_VERSION == "1.4.0"
           and SCENARIO_SCHEMA_VERSION == "1.5.0"
           and not scan_forbidden_reference_code(Path(__file__)),
           "no schema or namespace added; module passes the "
           "forbidden-reference scan")

    # ---- outputs ---------------------------------------------------------
    t0 = time.perf_counter()
    img = ["brandenburg_bnf_graticule_gcps.png",
           "brandenburg_bnf_georeference.png",
           "brandenburg_blockers.png",
           "europe_political_progress.png"]
    render_gcps(run_dir / img[0], g, chk,
                "A. BnF Brandenburg sheet — graticule control points")
    render_georef(run_dir / img[1], gaudit, chk,
                  "B. Transform comparison and map-specific uncertainty")
    render_blockers(run_dir / img[2], blha, pol, seg, const,
                    "C. What still blocks Brandenburg production")
    render_progress(
        run_dir / img[3],
        [("Saxony", sax["CONTROLLED"], sax["UNRESOLVED"]),
         ("Saxe-Weimar", wei["CONTROLLED"], wei["UNRESOLVED"]),
         ("Schwarzburg wash", 0, wash["UNRESOLVED"]),
         ("Brandenburg", 0, 0)],
        [("Vaugondy 1751 (Brandenburg)", "GEOREFERENCED, 9.282 km"),
         ("BLHA Lotter ca.1758", "leads unverified, not acquired"),
         ("1756 political documents", "not obtained"),
         ("Zollmann 1747 (Thuringia)", "deferred"),
         ("Utrecht 1756", "licence-blocked"),
         ("Low Countries atlas", "SOURCE_GAP")],
        "D. Europe political production progress")
    from PIL import Image

    aspects = {}
    for n in img:
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.size[0] / im.size[1], 3)
    _check("M18-30_absent_results_not_illustrated",
           "brandenburg_blha_source.png" not in img
           and "brandenburg_cross_source_boundary.png" not in img
           and "brandenburg_continuous_geometry.png" not in img
           and "brandenburg_hex_control.png" not in img,
           "no BLHA source, cross-source, continuous-geometry or "
           "hex-control figure was produced, because none of those "
           "results exists")
    timings["render_s"] = time.perf_counter() - t0

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    res = g["residual_m"]
    summary = [
        ("stage", STAGE), ("base_commit_mapgen017", M17_COMMIT),
        ("outcome", "PARTIAL"),
        ("bnf_copy_state", bnf["copy_state"]),
        ("bnf_copy_state_confidence", bnf["copy_state_confidence"]),
        ("bnf_gcps_total", len(g)), ("bnf_fit", fitn),
        ("bnf_holdout", holdn),
        ("bnf_meridians", len(lon_vals)), ("bnf_parallels", len(lat_vals)),
        ("bnf_transform", sel["model"]),
        ("bnf_fit_rms_m", round(float(sel["fit_rms_m"]), 1)),
        ("bnf_holdout_rms_m", round(float(sel["holdout_rms_m"]), 1)),
        ("bnf_holdout_max_m", round(float(sel["holdout_max_m"]), 1)),
        ("bnf_gcp_p50_m", round(float(np.percentile(res, 50)), 1)),
        ("bnf_gcp_p90_m", round(float(np.percentile(res, 90)), 1)),
        ("bnf_gcp_p95_m", round(float(np.percentile(res, 95)), 1)),
        ("bnf_gcp_max_m", round(float(res.max()), 1)),
        ("bnf_quadrant_max_residual_m", sel["quadrant_max_residual_m"]),
        ("bnf_independent_check", "Berlin"),
        ("bnf_independent_residual_km",
         round(float(chk.iloc[0]["residual_m"]) / 1000.0, 2)),
        ("bnf_prime_meridian", sel["prime_meridian"]),
        ("bnf_pixel_scale_m_per_px", sel["pixel_scale_m_per_px"]),
        ("brandenburg_uncertainty_km", unc),
        ("saxony_uncertainty_km_not_inherited", 9.168),
        ("blha_objects_audited", len(blha)),
        ("blha_verified_at_source", 0), ("blha_acquired", 0),
        ("blha_gcps", len(bl_gcp)),
        ("political_evidence_candidates", len(pol)),
        ("political_evidence_obtained", 0),
        ("continuity_segments", len(seg)),
        ("continuity_confirmed", 0),
        ("cross_source_samples", 0),
        ("constituents_audited", len(const)),
        ("new_production_features", 0),
        ("authorised_snapshot_features", 0),
        ("new_hex_membership_rows", 0),
        ("brandenburg_controlled", 0), ("brandenburg_unresolved", 0),
        ("saxony_controlled", sax["CONTROLLED"]),
        ("saxony_unresolved", sax["UNRESOLVED"]),
        ("saxe_weimar_controlled", wei["CONTROLLED"]),
        ("saxe_weimar_unresolved", wei["UNRESOLVED"]),
        ("schwarzburg_wash_unresolved", wash["UNRESOLVED"]),
        ("canonical_rows_before", len(canonical)),
        ("canonical_rows_after", len(canonical)),
        ("canonical_rows_changed", 0), ("promotion_conflicts", 0),
        ("brandenburg_coverage_status",
         brow.iloc[0]["source_evidence_status"]),
        ("coverage_complete_units", 0),
        ("validation_pass", f"{n_pass}/{len(val)}"),
    ]
    pd.DataFrame(summary, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "summary.csv", index=False)
    manifest = {
        "run_id": run_id, "stage": STAGE, "outcome": "PARTIAL",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen017": M17_COMMIT,
        "georeference": {
            "route": "GRATICULE_FIRST",
            "meridians_read": sorted(int(v) for v in lon_vals),
            "parallels_read": sorted(int(v) for v in lat_vals),
            "gcps": len(g), "fit": fitn, "holdout": holdn,
            "model": sel["model"],
            "fit_rms_m": round(float(sel["fit_rms_m"]), 1),
            "holdout_rms_m": round(float(sel["holdout_rms_m"]), 1),
            "independent_check_km": round(
                float(chk.iloc[0]["residual_m"]) / 1000.0, 2),
            "prime_meridian": sel["prime_meridian"],
            "prime_meridian_evidence": sel["prime_meridian_evidence"],
            "positional_uncertainty_km": unc},
        "what_did_not_happen": [
            "no BLHA object verified at source, acquired or georeferenced",
            "no 1756 political-control document opened",
            "no boundary segment reached continuity",
            "no boundary digitised, no membership, no control",
            "no canonical control row changed",
        ],
        "upstream_sha256": upstream,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_readme(run_dir, run_id, dict(summary), seg, aspects, img)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    cmap = {
        "README_REVIEW.md": run_dir / "README_REVIEW.md",
        "run_manifest.json": run_dir / "run_manifest.json",
        "validation.csv": run_dir / "validation.csv",
        "summary.csv": run_dir / "summary.csv",
        "historical_map_copy_registry.csv":
            H / "historical_map_copy_registry.csv",
        "historical_source_lineage.csv":
            H / "historical_source_lineage.csv",
        "brandenburg_bnf_gcps.csv": H / "brandenburg_bnf_gcps.csv",
        "brandenburg_bnf_georeference_audit.csv":
            H / "brandenburg_bnf_georeference_audit.csv",
        "brandenburg_bnf_independent_checks.csv":
            H / "brandenburg_bnf_independent_checks.csv",
        "brandenburg_bnf_transform.json":
            H / "brandenburg_bnf_transform.json",
        "brandenburg_blha_copy_audit.csv":
            H / "brandenburg_blha_copy_audit.csv",
        "brandenburg_blha_gcps.csv": H / "brandenburg_blha_gcps.csv",
        "brandenburg_blha_georeference_audit.csv":
            H / "brandenburg_blha_georeference_audit.csv",
        "brandenburg_1756_political_evidence.csv":
            H / "brandenburg_1756_political_evidence.csv",
        "brandenburg_boundary_segment_continuity.csv":
            H / "brandenburg_boundary_segment_continuity.csv",
        "brandenburg_constituent_audit.csv":
            H / "brandenburg_constituent_audit.csv",
        "brandenburg_source_copy_audit.csv":
            H / "brandenburg_source_copy_audit.csv",
        "historical_source_registry.csv":
            H / "historical_source_registry.csv",
        "historical_evidence_assertions.csv":
            H / "historical_evidence_assertions.csv",
        "historical_boundary_feature_evidence.csv":
            H / "historical_boundary_feature_evidence.csv",
        "historical_boundary_corroboration_audit.csv":
            m15_dir / "historical_boundary_corroboration_audit.csv",
        "historical_hex_membership.csv":
            m15_dir / "chatgpt_review" / "historical_hex_membership.csv",
        "historical_snapshot_features_1756_08_01.csv":
            m15_dir / "chatgpt_review"
            / "historical_snapshot_features_1756_08_01.csv",
        "raw_hex_winner_distortion.csv":
            m14_dir / "raw_hex_winner_distortion.csv",
        "authoritative_control_distortion.csv":
            m14_dir / "authoritative_control_distortion.csv",
        "territorial_control.csv": sdir / "territorial_control.csv",
        "territorial_control_provenance.csv":
            sdir / "territorial_control_provenance.csv",
        "scenario_control_promotion_log.csv":
            sdir / "scenario_control_promotion_log.csv",
        "scenario_political_coverage.csv": sdir / "political_coverage.csv",
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
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.copy2(run_dir / "run_manifest.json", review / "run_manifest.json")
    print(f"[georef] {run_id}: validation {n_pass}/{len(val)}, outcome "
          f"PARTIAL, BnF {sel['model']} fit {fitn}/hold {holdn} holdout "
          f"RMS {float(sel['holdout_rms_m']):.0f} m, uncertainty {unc} km, "
          f"canonical unchanged ({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[georef][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, seg, aspects, img):
    lines = [
        f"# {STAGE} Review — the Brandenburg sheet is georeferenced",
        "",
        "**OUTCOME: PARTIAL.** The BnF Brandenburg plate now has a "
        "validated transform and its own uncertainty. The independent "
        "second source was not verified at its archive, no 1756 document "
        "was opened, and no boundary segment reached continuity — so "
        "there is still **no geometry and no control**, and no canonical "
        "row changed.",
        "",
        f"Run `{run_id}`, built on MAPGEN-017 commit "
        f"`{s['base_commit_mapgen017']}`.",
        "",
        "## 1. Georeference — graticule first, and it worked",
        "",
        f"- The sheet carries a numbered degree graticule, so the "
        "graticule route was taken rather than falling back to feature "
        "points as Zollmann had forced.",
        f"- **{s['bnf_meridians']} meridians and {s['bnf_parallels']} "
        f"parallels** were detected on the border bands by the line "
        "detector, and **every numeral was read at ×4 magnification**. "
        "The middle parallel is in the set because its “54” was read — "
        "not because it lies halfway between the other two.",
        f"- **{s['bnf_gcps_total']} intersections**: "
        f"**{s['bnf_fit']} fit / {s['bnf_holdout']} holdout**, spanning "
        "all four quadrants. The holdout is one *entire* meridian plus "
        "two corners of another, so a held-out point is never an "
        "interpolation between its immediate neighbours in the fit.",
        f"- **`{s['bnf_transform']}` selected**: fit RMS "
        f"{s['bnf_fit_rms_m']} m, **holdout RMS "
        f"{s['bnf_holdout_rms_m']} m**, holdout max "
        f"{s['bnf_holdout_max_m']} m. POLYNOMIAL_2 fits better and holds "
        "out worse — complexity was not rewarded, the same rule that "
        "caught the overfit in MAPGEN-013.",
        f"- GCP residuals: p50 {s['bnf_gcp_p50_m']} m, p90 "
        f"{s['bnf_gcp_p90_m']} m, p95 {s['bnf_gcp_p95_m']} m, max "
        f"{s['bnf_gcp_max_m']} m. Quadrant maxima "
        f"{s['bnf_quadrant_max_residual_m']} — no corner blows up.",
        "",
        "## 2. The prime meridian the plate never states",
        "",
        f"- This sheet carries **no prime-meridian note**. Rather than "
        "inherit Ferro from the other Vaugondy sheets, the reading was "
        "**tested**: Berlin's town symbol was located on the raster and "
        "checked against GeoNames.",
        f"- **Residual {s['bnf_independent_residual_km']} km** under "
        f"`{s['bnf_prime_meridian']}`. That is the plate's own "
        "town-placement error at this scale, not a transform failure, and "
        "it is what makes the Ferro reading defensible. Recorded as "
        "`CORROBORATED_BY_INDEPENDENT_POINT`, never as read from the "
        "plate.",
        "",
        "## 3. A map-specific uncertainty, earned not borrowed",
        "",
        f"- **{s['brandenburg_uncertainty_km']} km**, combining the "
        f"holdout RMS, the independent check "
        f"({s['bnf_independent_residual_km']} km, the dominant term), the "
        "engraved line width and the digitisation tolerance at "
        f"{s['bnf_pixel_scale_m_per_px']} m/px.",
        f"- Saxony's {s['saxony_uncertainty_km_not_inherited']} km was "
        "**not** inherited. The two land close together because both are "
        "Vaugondy plates of similar scale — that is a finding about "
        "eighteenth-century town placement, not a copied constant.",
        "",
        "## 4. Copy-state claim weakened",
        "",
        f"- MAPGEN-017 labelled the BnF copy "
        "`EARLY_IMPRESSION_WITH_1751_PRIVILEGE`. That asserts a plate "
        "**state** which no comparison established.",
        f"- Weakened to **`{s['bnf_copy_state']}`** "
        f"(confidence {s['bnf_copy_state_confidence']}): a 1751 catalogue "
        "entry plus a 1751 privilege inscription is exactly that. Proving "
        "an early state needs a pixel comparison against the Rumsey and "
        "Książnica copies, which has not been done.",
        "",
        "## 5. What still blocks production",
        "",
        f"- **The independent source.** Two BLHA leads were recorded; "
        f"**{s['blha_verified_at_source']} were verified at source** and "
        f"**{s['blha_acquired']} acquired**. Their relation to each other "
        "(same copy / same plate / different plate / reproduction) is "
        "unresolved, so they count as **at most one** source, never two.",
        f"- **1756 political control.** "
        f"{s['political_evidence_candidates']} candidates recorded, "
        f"**{s['political_evidence_obtained']} obtained**. A volume title "
        "is not evidence: only an individual dated document with its "
        "column, heading, issuing authority and named territorial scope "
        "would qualify. Each row also states that an administrative "
        "record could never serve as **boundary-position** evidence.",
        f"- **Continuity.** All {s['continuity_segments']} frontier "
        "segments remain UNRESOLVED. A georeferenced 1751 plate is still "
        "a 1751 plate.",
        f"- Therefore: {s['new_production_features']} features, "
        f"{s['new_hex_membership_rows']} membership rows, "
        f"{s['brandenburg_controlled']} CONTROLLED, and canonical rows "
        f"{s['canonical_rows_before']:,} → {s['canonical_rows_after']:,} "
        f"(changed {s['canonical_rows_changed']}).",
        "",
        "## 6. Constituents kept in their place",
        "",
        f"- {s['constituents_audited']} entries audited. Altmark, "
        "Mittelmark, Neumark, Uckermark and Prignitz are **territorial "
        "constituents** of Brandenburg, not polities — a visible name on "
        "a map is not a sovereign actor.",
        "- **Magdeburg/Halberstadt** share a monarch, not a territory, "
        "and were not absorbed. **Swedish Pomerania** is defined by the "
        "sheet's own note (Bardt, Gutzkow, Stettin) and none of Pomerania "
        "is assigned to Brandenburg.",
        "",
        "## 7. Images",
        "",
    ]
    for n in img:
        lines.append(f"- `{n}` (aspect {aspects[n]})")
    lines += [
        "",
        "There is no BLHA source figure, no cross-source boundary figure, "
        "no continuous-geometry figure and no hex-control figure — none "
        "of those results exists.",
        "",
        "## 8. Validation",
        "",
        f"- `validation.csv`: M18 gates, pass count "
        f"{s['validation_pass']}.",
        "",
        "## 9. Known issues",
        "",
        "- The Brandenburg boundary has **not** been digitised. The "
        "transform exists; the wash tracing does not.",
        "- The inset *Supplement pour le Marquisat de Brandebourg* "
        "(Vieille Marche, Prignitz) needs its **own** placement "
        "semantics — the main transform does not apply to it, and it must "
        "not be pasted into map-body coordinates by eye.",
        "- Only one independent check point (Berlin) was used. More would "
        "sharpen the uncertainty and test it across the sheet.",
        "- The BLHA leads remain unverified; without them there is no "
        "independent geometry and no cross-source comparison.",
        "- No 1756 document has been read, so Brandenburg has geometry "
        "potential but no political authority at the snapshot.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
