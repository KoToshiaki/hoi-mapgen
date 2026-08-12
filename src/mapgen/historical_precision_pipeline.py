"""MAPGEN-015 — Zollmann 1747 precision georeference attempt,
Saxe-Weimar/Eisenach model audit and MAPGEN-014 metric correction.

Three phases, and only the first two succeeded:

  A. MAPGEN-014's review metrics were named after Saxony but computed
     over the whole authorised candidate, so Saxe-Weimar's rows leaked
     into "saxony_unresolved". Metrics are now polity-specific and the
     corroboration count is split into depiction-level and MEASURED.
  B. The 1756 Saxe-Weimar / Saxe-Eisenach constitutional model was
     audited from archival, biographical, cartographic and library
     authorities, which disagree — and the disagreement is recorded.
  C. The 1747 raster was confirmed to be at IIIF native maximum, its
     page skew measured, and its graticule numerals attacked at high
     magnification. One numeral was read. That is not enough for a
     defensible transform, so NO GCP was invented and no control
     changed.

An invented precision would be worse than a recorded failure.
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
from .historical_geometry import (GAMEPLAY_CONVERTIBLE_ROLES,
                                  HPG_ALGORITHM_VERSION, HPG_SCHEMA_VERSION,
                                  make_global_source_id)
from .historical_pilot_pipeline import _fig, _fig2, _save
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, load_scenario,
                       make_scenario_polity_id, scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .scenario_promotion import validate_canonical_control
from .sources import sha256_of

STAGE = "MAPGEN-015"
H = Path("data/historical")
CK_1747 = "zollmann_1747_thuringiae_orientalis_bnf"
CK_VAUG = "vaugondy_1756_haute_saxe_bnf"
M14_COMMIT = "d8745d017e6bfc98c746f93d9c5143b9ca005349"
GLOBAL_UNCERTAINTY_KM = 9.168
WASH_SUBJECT = "hsub_schwarzburg_unpartitioned_wash"
LOCAL_UNCERTAINTY_COLUMNS = [
    "zone_id", "subject_id", "segment_reference", "uncertainty_km",
    "basis_sources", "n_samples", "statistic_used", "confidence", "notes",
]
SEAM_COLUMNS = [
    "sheet_a", "sheet_b", "overlap_feature", "n_samples",
    "median_offset_km", "p95_offset_km", "max_offset_km", "status", "notes",
]
CORROBORATION_COLUMNS = [
    "subject_a", "boundary_segment_id", "source_a", "source_b",
    "lineage_independence", "corroboration_level", "n_samples",
    "median_distance_km", "p75_distance_km", "p90_distance_km",
    "p95_distance_km", "max_distance_km", "segment_length_km",
    "source_a_uncertainty_km", "source_b_uncertainty_km",
    "agreement_status", "notes",
]


def _wrap(text, w=96):
    return [text[i:i + w] for i in range(0, len(text), w)]


def render_native(path, iiif, title):
    fig, ax = _fig((15, 7))
    ax.set_axis_off()
    body = ["IIIF NATIVE RESOLUTION AUDIT", "",
            iiif.T.to_string(header=False), "",
            "The locally held raster IS the maximum Gallica serves, so no",
            "sharper scan can be fetched. Magnification adds no",
            "information; only local contrast enhancement can help a",
            "reading, and a reading that still fails stays UNREADABLE."]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=8)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_rectification(path, rect, title):
    fig, (ax, ax2) = _fig2((16, 7), [1.15, 1])
    ok = rect[rect["detection_status"] == "RELIABLE"]
    bad = rect[rect["detection_status"] != "RELIABLE"]
    ax.barh([f"{r.view_id} {r.edge}" for r in rect.itertuples()],
            rect["line_fit_rms_px"],
            color=["#196f3d" if s == "RELIABLE" else "#b03a2e"
                   for s in rect["detection_status"]])
    ax.set_xlabel("neat-line fit RMS (px)  — green = reliable")
    ax.set_title("border-band line detection", fontsize=10)
    ax2.text(0.0, 0.98,
             "MEASURED\n\n"
             + "\n".join(f"  {r.view_id} {r.edge:<7} "
                         f"angle {r.fitted_angle_deg:+.4f} deg  "
                         f"rms {r.line_fit_rms_px:7.2f} px  "
                         f"{r.detection_status}"
                         for r in rect.itertuples())
             + "\n\nOnly the TOP neat line is measurable: the sheets are\n"
               "rotated by about 0.41 and 0.20 degrees in the scan.\n"
               "The other three bands contain title lettering, the legend\n"
               "cartouche and the dedication cartouche, so the detector\n"
               "locks onto map content and its residual describes THAT,\n"
               "not page distortion.\n\n"
               "NO rectification transform was applied. One reliable edge\n"
               "cannot define a projective correction, and rectification\n"
               "is in any case a separate transform from georeferencing.",
             va="top", family="monospace", fontsize=7.5)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_anchors(path, anchors, view, title):
    fig, ax = _fig((15, 8))
    ax.set_axis_off()
    a = anchors[anchors["view_id"] == view]
    counts = a["reading_status"].value_counts().to_dict()
    body = [f"GEOREFERENCE ATTEMPT — sheet {view}", "",
            f"accepted GCPs: 0        candidate text anchors: {len(a)}",
            f"reading status: {counts}", ""]
    for r in a.itertuples():
        body.append(f"  {r.candidate_id}  {r.anchor_type}")
        body.append(f"    bbox {r.pixel_bbox}  status {r.reading_status}"
                    f"  accepted {r.accepted}")
        if r.raw_reading:
            body.append(f"    read: {str(r.raw_reading)[:88]}")
    body += ["", "RESULT: NOT GEOREFERENCED.",
             "",
             "One longitude numeral was read unambiguously on sheet f2",
             "('2|9 deg' = the 29th meridian from the sheet's own Ferro",
             "prime meridian). A single value, with no traced graticule",
             "line and no second axis, cannot place a sheet.",
             "",
             "No control point was invented to close the gap."]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=8)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_seam(path, seam, title):
    fig, ax = _fig((14, 6))
    ax.set_axis_off()
    ax.text(0.0, 0.95,
            "TWO-SHEET SEAM AUDIT\n\n" + seam.T.to_string(header=False)
            + "\n\nThe seam offset is measured in kilometres between two\n"
              "georeferenced sheets. Neither sheet is georeferenced, so\n"
              "there is nothing to measure yet and the status says so\n"
              "rather than reporting a zero.",
            va="top", family="monospace", fontsize=8.5)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_model(path, audit, title):
    fig, ax = _fig((16, 9))
    ax.set_axis_off()
    body = []
    for r in audit.itertuples():
        body.append(f"Q: {r.question}")
        body.append(f"   locator : {str(r.exact_locator)[:88]}")
        for ln in _wrap(f"   evidence: {r.evidence_text_summary}", 96):
            body.append(ln)
        body.append(f"   unified={r.supports_unified_polity}  "
                    f"constituent={r.supports_distinct_constituent}  "
                    f"union={r.supports_personal_union}  "
                    f"confidence={r.confidence}")
        for ln in _wrap(f"   reading : {r.interpretation}", 96):
            body.append(ln)
        body.append("")
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=7)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_metrics(path, corr, title):
    fig, ax = _fig((15, 7))
    ax.set_axis_off()
    ax.text(0.0, 0.98,
            "MAPGEN-014 REVIEW METRIC CORRECTION\n\n"
            + corr[["metric", "mapgen014_value", "corrected_value",
                    "corrected_metric_name"]].to_string(index=False)
            + "\n\nThe canonical data was never wrong; the SUMMARY was.\n"
              "MAPGEN-014's 'saxony_*' counts were computed over the whole\n"
              "authorised candidate, so Saxe-Weimar's 100 unresolved hexes\n"
              "were counted as Saxony's. Counts are now filtered by\n"
              "scenario_polity_id and recomputed from canonical data.",
            va="top", family="monospace", fontsize=8)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def run_historical_precision(cfg: MapgenConfig,
                             run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"central_europe_1756_precision_{_dt.datetime.now():%Y%m%d}"
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
    sdir = scenarios_root(cfg.data_dir) / scenario_id
    snap = load_scenario(cfg.data_dir, scenario_id)
    sp = snap.scenario_polities
    canonical = pd.read_csv(sdir / "territorial_control.csv",
                            keep_default_na=False, na_values=[""])
    provenance = pd.read_csv(sdir / "territorial_control_provenance.csv",
                             keep_default_na=False, na_values=[""])
    revlog = pd.read_csv(sdir / "territorial_control_revision_log.csv",
                         keep_default_na=False, na_values=[""])
    features = gpd.read_parquet(H / "historical_boundary_features.parquet")
    lineage = pd.read_csv(H / "historical_source_lineage.csv")
    anchors = pd.read_csv(H / "historical_map_text_anchor_candidates.csv",
                          keep_default_na=False, na_values=[""])
    rect = pd.read_csv(H / "historical_scan_rectification.csv")
    iiif = pd.read_csv(H / "historical_iiif_acquisition_audit.csv")
    meridian = pd.read_csv(H / "historical_prime_meridian_contract.csv")
    model_audit = pd.read_csv(H / "saxe_weimar_eisenach_model_audit.csv",
                              keep_default_na=False, na_values=[""])
    gcps = pd.read_csv(H / "historical_map_gcps.csv")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv"]}
    timings["load_s"] = time.perf_counter() - t0

    # ---- Phase A: polity-specific metrics -------------------------------
    sp_sax = make_scenario_polity_id(scenario_id, "pol_saxony")
    sp_wei = make_scenario_polity_id(scenario_id, "pol_saxe_weimar")
    prov_by_target = dict(zip(provenance["territorial_target_id"],
                              provenance["historical_subject_ids"].fillna("")))
    rev_by_target = dict(zip(revlog["territorial_target_id"],
                             revlog["old_status"]))

    def _polity_counts(subject_key):
        """Counts for ONE polity, keyed on the subject its provenance
        names — never on 'whatever was in the candidate'."""
        ids = [t for t, s in prov_by_target.items() if subject_key in s]
        cur = canonical[canonical["territorial_target_id"].isin(ids)]
        after = cur["control_status"].value_counts().to_dict()
        before = {"CONTROLLED": 0, "UNRESOLVED": 0}
        for t in cur.itertuples():
            old = rev_by_target.get(t.territorial_target_id,
                                    t.control_status)
            before[old] = before.get(old, 0) + 1
        return ({"CONTROLLED": before.get("CONTROLLED", 0),
                 "UNRESOLVED": before.get("UNRESOLVED", 0)},
                {"CONTROLLED": after.get("CONTROLLED", 0),
                 "UNRESOLVED": after.get("UNRESOLVED", 0)},
                len(ids))

    sax_before, sax_after, n_sax = _polity_counts("meissen_electoral_saxony")
    wei_before, wei_after, n_wei = _polity_counts("duchy_of_saxe_weimar")
    wash_before, wash_after, n_wash = _polity_counts("schwarzburg")
    m14_sum = pd.read_csv(m14_dir / "summary.csv")
    m14 = dict(zip(m14_sum["metric"], m14_sum["value"].astype(str)))
    cand_before = {"CONTROLLED": int(m14["saxony_controlled_before"]),
                   "UNRESOLVED": int(m14["saxony_unresolved_before"])}
    cand_after = {"CONTROLLED": int(m14["saxony_controlled_after"]),
                  "UNRESOLVED": int(m14["saxony_unresolved_after"])}
    metric_corr = pd.DataFrame([
        {"metric": "saxony_controlled_before",
         "mapgen014_value": cand_before["CONTROLLED"],
         "corrected_value": sax_before["CONTROLLED"],
         "corrected_metric_name": "saxony_controlled_before",
         "problem": "computed over the whole authorised candidate",
         "fix": "filtered to the Saxony subject via provenance"},
        {"metric": "saxony_controlled_after",
         "mapgen014_value": cand_after["CONTROLLED"],
         "corrected_value": sax_after["CONTROLLED"],
         "corrected_metric_name": "saxony_controlled_after",
         "problem": "same", "fix": "same"},
        {"metric": "saxony_unresolved_before",
         "mapgen014_value": cand_before["UNRESOLVED"],
         "corrected_value": sax_before["UNRESOLVED"],
         "corrected_metric_name": "saxony_unresolved_before",
         "problem": "Saxe-Weimar's 100 unresolved hexes were counted as "
                    "Saxony's",
         "fix": "filtered to the Saxony subject via provenance"},
        {"metric": "saxony_unresolved_after",
         "mapgen014_value": cand_after["UNRESOLVED"],
         "corrected_value": sax_after["UNRESOLVED"],
         "corrected_metric_name": "saxony_unresolved_after",
         "problem": "same", "fix": "same"},
        {"metric": "(candidate-scope aggregate, kept but renamed)",
         "mapgen014_value": f"{cand_before} -> {cand_after}",
         "corrected_value": f"{cand_before} -> {cand_after}",
         "corrected_metric_name":
             "authorised_candidate_scope_controlled/unresolved_before/after",
         "problem": "carried the Saxony name",
         "fix": "renamed; the value itself was correct for its scope"},
        {"metric": "independent_boundary_corroborations",
         "mapgen014_value": m14.get(
             "independent_boundary_corroborations", "1"),
         "corrected_value": "depiction 1 / measured 0",
         "corrected_metric_name":
             "depiction_level_corroborations + "
             "measured_boundary_corroborations",
         "problem": "an AGREES row with n_samples=0 was counted as a "
                    "boundary corroboration",
         "fix": "a measured corroboration now requires n_samples > 0 and "
                "real distance statistics"},
    ])
    _check("M15-01_mapgen014_canonical_regression",
           len(canonical) == 1614
           and int((canonical["control_status"] == "CONTROLLED").sum())
           == 697
           and int((canonical["control_status"] == "UNRESOLVED").sum())
           == 917
           and len(revlog) == 401,
           "MAPGEN-014 canonical authority intact: 1,614 rows, 697 "
           "CONTROLLED, 917 UNRESOLVED, 401 revision rows")
    _check("M15-02_saxony_metrics_polity_specific",
           n_sax == 1426 and sax_before == {"CONTROLLED": 1096,
                                            "UNRESOLVED": 330}
           and sax_after == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and sax_before["CONTROLLED"] - sax_after["CONTROLLED"] == 401,
           f"Saxony alone ({n_sax:,} targets): CONTROLLED "
           f"{sax_before['CONTROLLED']:,} -> {sax_after['CONTROLLED']:,}, "
           f"UNRESOLVED {sax_before['UNRESOLVED']} -> "
           f"{sax_after['UNRESOLVED']:,}; all recomputed from canonical "
           "data, none hard-coded")
    _check("M15-03_candidate_scope_metrics_renamed",
           set(metric_corr["corrected_metric_name"]).issuperset(
               {"authorised_candidate_scope_controlled/unresolved_before/"
                "after"})
           and cand_after["UNRESOLVED"] - sax_after["UNRESOLVED"]
           == wei_after["UNRESOLVED"],
           "the candidate-scope aggregate is retained under a name that "
           f"does not say Saxony; the {cand_after['UNRESOLVED'] - sax_after['UNRESOLVED']}"
           " row difference is exactly Saxe-Weimar's unresolved hexes")
    _check("M15-04_saxe_weimar_reported_separately",
           wei_after["CONTROLLED"] == 0
           and wei_after["UNRESOLVED"] > 0
           and sax_after["UNRESOLVED"] + wei_after["UNRESOLVED"]
           == cand_after["UNRESOLVED"]
           and sax_after["CONTROLLED"] + wei_after["CONTROLLED"]
           == cand_after["CONTROLLED"],
           f"Saxe-Weimar reported as its own metric: {wei_after}. Saxony "
           f"{sax_after} plus Saxe-Weimar {wei_after} reconstructs the "
           f"candidate-scope aggregate {cand_after} exactly, so the split "
           "loses nothing. (The four MAPGEN-013 conflict hexes count "
           "under Saxony, whose promoted provenance names them.)")

    # ---- corroboration split --------------------------------------------
    prev = pd.read_csv(
        m14_dir / "historical_boundary_corroboration_audit.csv")
    lin = dict(zip(lineage["global_source_id"],
                   lineage["independence_status"]))
    src_1747 = make_global_source_id(CK_1747)
    corrob = pd.DataFrame([{
        "subject_a": r.subject_a,
        "boundary_segment_id": r.boundary_segment_id,
        "source_a": r.source_a, "source_b": r.source_b,
        "lineage_independence": lin.get(src_1747),
        "corroboration_level":
            "DEPICTION_LEVEL" if r.agreement_status == "AGREES"
            else "NOT_CORROBORATED",
        "n_samples": 0, "median_distance_km": None,
        "p75_distance_km": None, "p90_distance_km": None,
        "p95_distance_km": None, "max_distance_km": None,
        "segment_length_km": None,
        "source_a_uncertainty_km": GLOBAL_UNCERTAINTY_KM,
        "source_b_uncertainty_km": None,
        "agreement_status": r.agreement_status,
        "notes": r.notes + " | MAPGEN-015: still 0 samples — the 1747 "
                 "sheet is not georeferenced, so no distance exists to "
                 "measure. Depiction-level agreement is NOT a measured "
                 "boundary corroboration."}
        for r in prev.itertuples()], columns=CORROBORATION_COLUMNS)
    depiction = int((corrob["corroboration_level"]
                     == "DEPICTION_LEVEL").sum())
    measured = int(((corrob["corroboration_level"] == "MEASURED")
                    & (corrob["n_samples"] > 0)).sum())
    _check("M15-05_depiction_vs_measured_split",
           depiction == 1 and measured == 0
           and "corroboration_level" in corrob.columns
           and int(corrob["n_samples"].sum()) == 0,
           f"depiction_level_corroborations={depiction}, "
           f"measured_boundary_corroborations={measured}, "
           f"measured_boundary_sample_count={int(corrob['n_samples'].sum())}"
           " — MAPGEN-014's single 'independent boundary corroboration' "
           "was a depiction-level agreement with zero samples")
    _check("M15-06_measured_requires_samples",
           not ((corrob["corroboration_level"] == "MEASURED")
                & (corrob["n_samples"] <= 0)).any()
           and corrob.loc[corrob["n_samples"] == 0,
                          "median_distance_km"].isna().all(),
           "no row may be MEASURED with 0 samples, and a 0-sample row "
           "carries no distance statistics at all")

    # ---- Phase B gates ---------------------------------------------------
    decision = model_audit[model_audit["evidence_type"] == "DECISION"]
    sp_eis = make_scenario_polity_id(scenario_id, "pol_saxe_eisenach")
    rel = snap.scenario_polity_relationships
    _check("M15-07_weimar_eisenach_model_audited",
           len(model_audit) >= 5 and len(decision) == 1
           and model_audit["exact_locator"].str.len().where(
               model_audit["evidence_type"] != "DECISION", 99).min() > 20
           and set(model_audit["supports_unified_polity"]) & {"WEAK_YES"}
           and set(model_audit["supports_distinct_constituent"]) &
           {"STRONG_YES"},
           f"{len(model_audit)} audit rows from four authorities that do "
           "NOT agree: a BnF cataloguing heading supports one entity, "
           "while the Eisenach archival record, the biography and the "
           "1747 sheet all support two. The disagreement is recorded, "
           "not resolved by preference")
    _check("M15-08_no_name_only_polity_inference",
           "TWO_DISTINCT_ACTORS_IN_PERSONAL_UNION"
           in decision.iloc[0]["notes"]
           and "pol_saxe_weimar_eisenach" not in set(
               snap.polities["polity_id"])
           and sp_eis in set(sp["scenario_polity_id"])
           and ((rel["relationship_type"] == "PERSONAL_UNION")
                & (rel["from_scenario_polity_id"].isin([sp_wei, sp_eis]))
                & (rel["to_scenario_polity_id"].isin([sp_wei, sp_eis]))
                ).any(),
           "the composite ducal style did NOT create a merged polity: "
           "Saxe-Eisenach is registered as its own actor and the union is "
           "modelled as a PERSONAL_UNION relationship")
    _check("M15-09_weimar_not_superseded",
           sp.loc[sp["polity_id"] == "pol_saxe_weimar",
                  "existence_status"].iloc[0]
           != "MODEL_ARTIFACT_SUPERSEDED"
           and int((canonical["controller_scenario_polity_id"]
                    == sp_eis).sum()) == 0,
           "pol_saxe_weimar was incomplete, not wrong, so it is not "
           "superseded; Saxe-Eisenach holds no geometry and controls "
           "nothing")

    # ---- Phase C gates ---------------------------------------------------
    _check("M15-10_iiif_native_dimensions_checked",
           len(iiif) == 2
           and (iiif["local_is_native_maximum"] == "YES").all()
           and (iiif["info_json_native_width"]
                == iiif["local_raster_width"]).all()
           and (iiif["info_json_native_height"]
                == iiif["local_raster_height"]).all(),
           "info.json native size equals the manifest canvas and the "
           f"local raster for both views "
           f"({', '.join(f'{r.view_id} {r.info_json_native_width}x{r.info_json_native_height}' for r in iiif.itertuples())})"
           " — there is no sharper scan to fetch")
    unread = anchors[anchors["reading_status"] == "UNREADABLE"]
    clear = anchors[anchors["reading_status"] == "CLEAR"]
    _check("M15-11_no_invented_numeral",
           (unread["raw_reading"].fillna("") == "").all()
           and (unread["accepted"] == "NO").all()
           and set(anchors["reading_status"]) <= {"CLEAR", "AMBIGUOUS",
                                                  "UNREADABLE"},
           f"{len(anchors)} text anchors attempted: "
           f"{dict(anchors['reading_status'].value_counts())}. Every "
           "UNREADABLE row has an EMPTY reading — no numeral was filled "
           "in by inference, and no unlabelled tick was given a degree")
    lon_clear = clear[clear["anchor_type"]
                      == "GRATICULE_LONGITUDE_NUMERAL"]
    _check("M15-12_one_numeral_actually_read",
           len(lon_clear) == 1 and "9" in str(lon_clear.iloc[0]["raw_reading"]),
           "one longitude numeral was read unambiguously on sheet f2 "
           f"({lon_clear.iloc[0]['raw_reading']} at "
           f"{lon_clear.iloc[0]['pixel_bbox']}) — real progress over "
           "MAPGEN-014, and still not a transform")
    reliable = rect[rect["detection_status"] == "RELIABLE"]
    _check("M15-13_rectification_separate_from_georeference",
           len(rect) == 8 and len(reliable) == 2
           and rect["rotation_deg_applied"].isna().all()
           and rect["projective_parameters"].isna().all()
           and float(reliable["line_fit_rms_px"].max()) < 20.0,
           "scan rectification measured in IMAGE space only: the top neat "
           f"line fits at {float(reliable['line_fit_rms_px'].max()):.1f} px"
           " on both sheets (rotation about 0.41 and 0.20 degrees); the "
           "other six edge fits are recorded as DETECTOR_FAILED. No "
           "transform was applied, and none was promoted to a geographic "
           "transform")
    _check("M15-14_each_sheet_treated_independently",
           set(anchors["view_id"]) == {"f1", "f2"}
           and set(rect["view_id"]) == {"f1", "f2"}
           and len(iiif) == 2,
           "both sheets audited separately at every step; they were never "
           "stitched into one image to share a transform")
    _check("M15-15_no_gcp_invented",
           set(gcps["map_source_id"]) == {make_global_source_id(CK_VAUG)}
           and int((anchors["accepted"] == "YES").sum())
           == len(anchors[anchors["anchor_type"].isin(
               ["PRIME_MERIDIAN_NOTE", "SCALE_BAR", "LEGEND",
                "GRATICULE_LONGITUDE_NUMERAL"])
               & (anchors["reading_status"] == "CLEAR")]),
           "the 1747 source still has ZERO rows in historical_map_gcps.csv"
           f"; only {int((anchors['accepted'] == 'YES').sum())} textual "
           "readings are accepted, and a textual reading is not a control "
           "point")
    _check("M15-16_no_modern_admin_gcp",
           gcps["reference_type"].isin(
               ["MAP_GRATICULE", "SETTLEMENT_MODERN_REFERENCE"]).all()
           and not scan_forbidden_reference_code(Path(__file__)),
           "no modern administrative geometry is used as a control "
           "reference, and this module passes the forbidden-reference AST "
           "scan")
    mer = meridian[meridian["map_source_id"] == make_global_source_id(
        CK_1747)].iloc[0]
    _check("M15-17_ferro_conversion_provenance",
           abs(float(mer["conversion_to_greenwich_deg"])
               - (2.337229 - 20.0)) < 1e-9
           and len(str(mer["source_text"])) > 40
           and len(str(mer["conversion_source"])) > 40,
           "the Ferro relation is stored as data with the sheet's own "
           "wording, the Paris longitude used and where that value comes "
           f"from ({float(mer['conversion_to_greenwich_deg']):.6f} deg E "
           "of Greenwich) — not as a bare constant")
    seam = pd.DataFrame([{
        "sheet_a": "f1", "sheet_b": "f2",
        "overlap_feature": "not established",
        "n_samples": 0, "median_offset_km": None, "p95_offset_km": None,
        "max_offset_km": None, "status": "NOT_MEASURABLE_NO_GEOREFERENCE",
        "notes": "A seam offset is a distance between two georeferenced "
                 "sheets. Neither sheet is georeferenced, so this is "
                 "recorded as not measurable rather than as agreement. "
                 "The sheets are also sections (inferior/superior) that "
                 "join along a stated line rather than overlapping "
                 "broadly, which the next stage must confirm on the "
                 "raster."}], columns=SEAM_COLUMNS)
    _check("M15-18_sheet_seam_audited",
           len(seam) == 1
           and seam.iloc[0]["status"] == "NOT_MEASURABLE_NO_GEOREFERENCE"
           and int(seam["n_samples"].iloc[0]) == 0,
           "the two-sheet seam is audited and honestly reported as not "
           "measurable, not as a zero offset")

    # ---- Phase D/E gates: nothing was promoted ---------------------------
    a_1747 = pd.read_csv(H / "historical_evidence_assertions.csv",
                         keep_default_na=False, na_values=[""])
    a_1747 = a_1747[a_1747["global_source_id"] == src_1747]
    _check("M15-19_continuity_required_and_absent",
           len(a_1747) == 0
           and reg.loc[reg["global_source_id"] == src_1747,
                       "georeference_status"].iloc[0]
           == "NOT_YET_GEOREFERENCED",
           "the 1747 source still carries NO evidence assertion of any "
           "kind, so its geometry cannot reach the 1756 snapshot: a "
           "TERRITORIAL_CONTINUITY bridge would be required and none was "
           "made")
    ndb = pd.read_csv(H / "historical_evidence_assertions.csv")
    _check("M15-20_existence_is_not_continuity",
           not (ndb["assertion_type"] == "TERRITORIAL_CONTINUITY").any()
           or (ndb.loc[ndb["assertion_type"] == "TERRITORIAL_CONTINUITY",
                       "global_source_id"] != src_1747).all(),
           "no POLITY_EXISTENCE assertion was reused as continuity; the "
           "Saxe-Eisenach registration proves the polity existed, not "
           "where any boundary ran")
    wash = features[features["historical_subject_id"] == WASH_SUBJECT]
    _check("M15-21_schwarzburg_wash_still_nonconvertible",
           len(wash) == 1
           and wash.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY"
           and wash.iloc[0]["feature_role"] not in GAMEPLAY_CONVERTIBLE_ROLES
           and wash_after == {"CONTROLLED": 0, "UNRESOLVED": n_wash},
           f"the Schwarzburg wash stays UNCERTAIN_BOUNDARY with "
           f"{n_wash} hexes all UNRESOLVED; georeferencing was not "
           "achieved and no partition was manufactured from image "
           "processing")
    local_zones = pd.DataFrame(columns=LOCAL_UNCERTAINTY_COLUMNS)
    _check("M15-22_no_cross_source_distance_without_georeference",
           int(corrob["n_samples"].sum()) == 0
           and corrob["median_distance_km"].isna().all(),
           "no cross-source distance was computed, because computing one "
           "would require a transform that does not exist")
    _check("M15-23_local_uncertainty_evidence_derived",
           len(local_zones) == 0,
           "0 local uncertainty zones: a zone needs cross-source "
           "residuals, and none were measured")
    _check("M15-24_uncertainty_not_tuned_for_control",
           float(features["positional_uncertainty_km"].max())
           == GLOBAL_UNCERTAINTY_KM
           and int((canonical["control_status"] == "CONTROLLED").sum())
           == 697,
           f"the global uncertainty stays at {GLOBAL_UNCERTAINTY_KM} km "
           "and CONTROLLED stays at 697 — a 1:200,000 scale is not by "
           "itself evidence of accuracy, and nothing was relaxed to gain "
           "hexes")
    representation = pd.read_csv(
        m14_dir / "political_representation_decision.csv")
    _check("M15-25_overlay_hard_gate",
           int((representation["recommended_mode"]
                == "OVERLAY_ONLY").sum()) == 0,
           "still 0 OVERLAY_ONLY decisions: the failure is the source's "
           "positional accuracy, which an overlay cannot fix")

    # ---- standing regressions -------------------------------------------
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    comps = pd.read_parquet(geo_dir / "island_components.parquet",
                            columns=["island_component_id"])
    scen_srcs = pd.read_csv(sdir / "sources.csv", keep_default_na=False,
                            na_values=[""])
    m14_mem = set(pd.read_parquet(
        m14_dir / "historical_hex_membership.parquet",
        columns=["hex_id"])["hex_id"])
    m13_mem = set(pd.read_parquet(
        cfg.output_dir / scfg.get(
            "mapgen013_run", "central_europe_1756_expand_20260813")
        / "historical_hex_membership.parquet",
        columns=["hex_id"])["hex_id"])
    struct = set(sp.loc[sp["territorial_authority_role"].isin(
        ["STRUCTURAL_CONTAINER", "COMPOSITE_TERRITORIAL_ACTOR"]),
        "scenario_polity_id"])
    integ = validate_canonical_control(
        canonical, provenance, sp, scen_srcs,
        set(geo.loc[geo["water_type"] == "NONE", "hex_id"]) | m13_mem
        | m14_mem, set(comps["island_component_id"]), struct)
    _check("M15-26_canonical_target_unique_and_intact",
           not canonical.duplicated(subset=[
               "scenario_id", "territorial_target_type",
               "territorial_target_id"]).any() and integ == [],
           f"{len(canonical):,} canonical rows, no duplicate key, "
           f"integrity {integ or 'clean'}")
    _check("M15-27_low_countries_regression",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP",
           "Low Countries still SOURCE_GAP")
    _check("M15-28_europe_regression",
           int(eu_man["hex_count"].sum()) == 1885422,
           "Europe canonical grid intact (1,885,422 hexes)")
    _check("M15-29_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN"
           and int((canonical["territorial_target_type"]
                    == "ISLAND_COMPONENT").sum()) == 1,
           "Toshima hex still OCEAN with its island-component row intact")
    _check("M15-30_claims_not_derived",
           len(snap.territorial_claims) == 1,
           "claims table still holds its single MAPGEN-008 row")
    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("M15-31_upstream_immutable", up_after == upstream,
           f"{len(upstream)} upstream artifacts byte-identical")
    _check("M15-32_versions_unchanged",
           HPG_SCHEMA_VERSION == "1.4.0"
           and SCENARIO_SCHEMA_VERSION == "1.4.0",
           f"hpg {HPG_SCHEMA_VERSION}/{HPG_ALGORITHM_VERSION}, scenario "
           f"{SCENARIO_SCHEMA_VERSION} — this stage adds data and audits, "
           "not schema")

    # ---- outputs ---------------------------------------------------------
    t0 = time.perf_counter()
    metric_corr.to_csv(run_dir / "mapgen014_metric_correction.csv",
                       index=False)
    corrob.to_csv(run_dir / "historical_boundary_corroboration_audit.csv",
                  index=False)
    local_zones.to_csv(run_dir / "historical_local_uncertainty_zones.csv",
                       index=False)
    seam.to_csv(run_dir / "historical_map_sheet_seam_audit.csv",
                index=False)
    img = ["zollmann_native_resolution_audit.png",
           "zollmann_scan_rectification.png",
           "zollmann_georeference_attempt_sheet1.png",
           "zollmann_georeference_attempt_sheet2.png",
           "zollmann_sheet_seam.png",
           "saxe_weimar_eisenach_model_audit.png",
           "mapgen014_metric_correction.png"]
    render_native(run_dir / img[0], iiif,
                  "A. Zollmann 1747 — IIIF native resolution audit")
    render_rectification(run_dir / img[1], rect,
                         "B. Scan rectification measured in image space "
                         "(no transform applied)")
    render_anchors(run_dir / img[2], anchors, "f1",
                   "C. Georeference ATTEMPT, sheet f1 — 0 GCPs accepted")
    render_anchors(run_dir / img[3], anchors, "f2",
                   "D. Georeference ATTEMPT, sheet f2 — 0 GCPs accepted")
    render_seam(run_dir / img[4], seam,
                "E. Two-sheet seam — not measurable without a transform")
    render_model(run_dir / img[5], model_audit,
                 "F. Saxe-Weimar / Saxe-Eisenach constitutional model "
                 "audit")
    render_metrics(run_dir / img[6], metric_corr,
                   "G. MAPGEN-014 review metric correction")
    from PIL import Image

    aspects = {}
    for n in img:
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.size[0] / im.size[1], 3)
    _check("M15-33_no_failed_result_shown_as_success",
           "weimar_cross_source_boundary_residual.png" not in img
           and all("attempt" in n or "audit" in n or "seam" in n
                   or "rectification" in n or "correction" in n
                   for n in img),
           "the cross-source residual figure is NOT produced, because "
           "there is no residual; the georeference figures are named "
           "'attempt' and state 0 accepted GCPs")
    timings["render_s"] = time.perf_counter() - t0

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    summary = [
        ("stage", STAGE), ("base_commit_mapgen014", M14_COMMIT),
        ("outcome", "PARTIAL_B"),
        ("saxony_targets", n_sax),
        ("saxony_controlled_before", sax_before["CONTROLLED"]),
        ("saxony_controlled_after", sax_after["CONTROLLED"]),
        ("saxony_unresolved_before", sax_before["UNRESOLVED"]),
        ("saxony_unresolved_after", sax_after["UNRESOLVED"]),
        ("saxe_weimar_controlled", wei_after["CONTROLLED"]),
        ("saxe_weimar_unresolved", wei_after["UNRESOLVED"]),
        ("schwarzburg_wash_unresolved", wash_after["UNRESOLVED"]),
        ("authorised_candidate_scope_controlled_before",
         cand_before["CONTROLLED"]),
        ("authorised_candidate_scope_controlled_after",
         cand_after["CONTROLLED"]),
        ("authorised_candidate_scope_unresolved_before",
         cand_before["UNRESOLVED"]),
        ("authorised_candidate_scope_unresolved_after",
         cand_after["UNRESOLVED"]),
        ("depiction_level_corroborations", depiction),
        ("measured_boundary_corroborations", measured),
        ("measured_boundary_sample_count",
         int(corrob["n_samples"].sum())),
        ("measured_boundary_pairs", 0),
        ("local_uncertainty_zones", len(local_zones)),
        ("global_uncertainty_km", GLOBAL_UNCERTAINTY_KM),
        ("iiif_views_audited", len(iiif)),
        ("iiif_native_f1", "5751x4431"), ("iiif_native_f2", "5721x4441"),
        ("local_raster_is_native_maximum", "YES"),
        ("text_anchor_candidates", len(anchors)),
        ("text_anchors_clear", int((anchors["reading_status"]
                                    == "CLEAR").sum())),
        ("text_anchors_ambiguous", int((anchors["reading_status"]
                                        == "AMBIGUOUS").sum())),
        ("text_anchors_unreadable", int((anchors["reading_status"]
                                         == "UNREADABLE").sum())),
        ("graticule_numerals_read", len(lon_clear)),
        ("rectification_edges_measured", len(rect)),
        ("rectification_edges_reliable", len(reliable)),
        ("scan_rotation_deg_f1", -0.4102),
        ("scan_rotation_deg_f2", -0.1994),
        ("rectification_transform_applied", "NONE"),
        ("georeference_route", "A_ATTEMPTED_THEN_ABANDONED"),
        ("gcps_accepted_1747", 0), ("gcps_rejected_1747", 0),
        ("sheets_georeferenced", 0),
        ("sheet_seam_status", "NOT_MEASURABLE_NO_GEOREFERENCE"),
        ("polities_total", len(snap.polities)),
        ("scenario_polities_total", len(sp)),
        ("relationships_total", len(rel)),
        ("weimar_eisenach_model",
         "TWO_DISTINCT_ACTORS_IN_PERSONAL_UNION"),
        ("canonical_rows", len(canonical)),
        ("canonical_controlled",
         int((canonical["control_status"] == "CONTROLLED").sum())),
        ("canonical_unresolved",
         int((canonical["control_status"] == "UNRESOLVED").sum())),
        ("canonical_rows_changed_this_stage", 0),
        ("validation_pass", f"{n_pass}/{len(val)}"),
    ]
    pd.DataFrame(summary, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "summary.csv", index=False)
    manifest = {
        "run_id": run_id, "stage": STAGE, "outcome": "PARTIAL_B",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen014": M14_COMMIT,
        "hpg_schema_version": HPG_SCHEMA_VERSION,
        "hpg_algorithm_version": HPG_ALGORITHM_VERSION,
        "scenario_schema_version": SCENARIO_SCHEMA_VERSION,
        "phase_a_metric_correction": (
            "MAPGEN-014's saxony_* counts were computed over the whole "
            "authorised candidate, so Saxe-Weimar's 100 unresolved hexes "
            "were reported as Saxony's. Saxony alone went CONTROLLED "
            "1,096 -> 695 and UNRESOLVED 330 -> 731. The canonical data "
            "was correct throughout; only the summary was wrong."),
        "phase_b_model_audit": (
            "Four authorities disagree. A BnF cataloguing heading treats "
            "Saxe-Weimar-Eisenach as one entity from 1741; the Eisenach "
            "archival record (own Regierung, Kammer and Oberkonsistorium "
            "until 1849/50), the ruler's biography and the 1747 sheet's "
            "own title all treat Weimar and Eisenach separately. Modelled "
            "as two distinct actors in personal union."),
        "phase_c_georeference_outcome": (
            "PARTIAL-B. The local raster is the IIIF native maximum, so "
            "no sharper scan exists. Page rotation was measured on the "
            "top neat line (0.41 and 0.20 degrees); the other edges could "
            "not be detected. High-magnification, contrast-enhanced crops "
            "produced ONE unambiguous longitude numeral on sheet f2 "
            "('2|9 deg') plus the prime-meridian note and scale bar. That "
            "is not enough for a transform, and no control point was "
            "invented, so both sheets remain NOT_GEOREFERENCED."),
        "what_did_not_happen": [
            "no GCP row was created for the 1747 source",
            "no rectification transform was applied",
            "no cross-source boundary distance was measured",
            "no local uncertainty zone was created",
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
    _write_readme(run_dir, run_id, dict(summary), metric_corr, model_audit,
                  anchors, rect, aspects, img)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    copies = {
        "README_REVIEW.md": run_dir / "README_REVIEW.md",
        "run_manifest.json": run_dir / "run_manifest.json",
        "validation.csv": run_dir / "validation.csv",
        "summary.csv": run_dir / "summary.csv",
        "mapgen014_metric_correction.csv":
            run_dir / "mapgen014_metric_correction.csv",
        "saxe_weimar_eisenach_model_audit.csv":
            H / "saxe_weimar_eisenach_model_audit.csv",
        "polity_model_correction_audit.csv":
            H / "polity_model_correction_audit.csv",
        "polities.csv": scenarios_root(cfg.data_dir) / "polities.csv",
        "scenario_polities.csv": sdir / "scenario_polities.csv",
        "scenario_polity_relationships.csv":
            sdir / "scenario_polity_relationships.csv",
        "scenario_polity_inclusion_audit.csv":
            sdir / "scenario_polity_inclusion_audit.csv",
        "scenario_evidence.csv": sdir / "evidence.csv",
        "scenario_sources.csv": sdir / "sources.csv",
        "historical_source_registry.csv":
            H / "historical_source_registry.csv",
        "historical_source_assessment.csv":
            H / "historical_source_assessment.csv",
        "historical_source_lineage.csv":
            H / "historical_source_lineage.csv",
        "historical_evidence_assertions.csv":
            H / "historical_evidence_assertions.csv",
        "historical_iiif_acquisition_audit.csv":
            H / "historical_iiif_acquisition_audit.csv",
        "historical_map_text_anchor_candidates.csv":
            H / "historical_map_text_anchor_candidates.csv",
        "historical_scan_rectification.csv":
            H / "historical_scan_rectification.csv",
        "historical_prime_meridian_contract.csv":
            H / "historical_prime_meridian_contract.csv",
        "historical_map_gcps.csv": H / "historical_map_gcps.csv",
        "historical_map_georeference_audit.csv":
            H / "historical_map_georeference_audit.csv",
        "historical_map_sheet_seam_audit.csv":
            run_dir / "historical_map_sheet_seam_audit.csv",
        "historical_boundary_corroboration_audit.csv":
            run_dir / "historical_boundary_corroboration_audit.csv",
        "historical_local_uncertainty_zones.csv":
            run_dir / "historical_local_uncertainty_zones.csv",
        "territorial_control.csv": sdir / "territorial_control.csv",
        "territorial_control_provenance.csv":
            sdir / "territorial_control_provenance.csv",
        "territorial_control_revision_log.csv":
            sdir / "territorial_control_revision_log.csv",
        "scenario_control_promotion_log.csv":
            sdir / "scenario_control_promotion_log.csv",
        "political_representation_decision.csv":
            m14_dir / "political_representation_decision.csv",
        "historical_hex_membership.csv": None,
    }
    for dst, src in copies.items():
        if src is not None and Path(src).exists():
            shutil.copy2(src, review / dst)
    pd.DataFrame(features.drop(columns="geometry")).to_csv(
        review / "historical_boundary_features.csv", index=False)
    shutil.copy2(m14_dir / "chatgpt_review"
                 / "historical_snapshot_features_1756_08_01.csv",
                 review / "historical_snapshot_features_1756_08_01.csv")
    shutil.copy2(m14_dir / "chatgpt_review"
                 / "historical_hex_membership.csv",
                 review / "historical_hex_membership.csv")
    for n in img:
        shutil.copy2(run_dir / n, review / n)
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.copy2(run_dir / "run_manifest.json", review / "run_manifest.json")
    print(f"[precision] {run_id}: validation {n_pass}/{len(val)}, outcome "
          f"PARTIAL_B, Saxony {sax_before} -> {sax_after}, sheets "
          f"georeferenced 0/2, canonical unchanged "
          f"({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[precision][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, metric_corr, model_audit, anchors,
                  rect, aspects, img):
    lines = [
        f"# {STAGE} Review — Zollmann 1747 precision georeference attempt, "
        "Saxe-Weimar/Eisenach model audit and MAPGEN-014 metric correction",
        "",
        "**OUTCOME: PARTIAL-B.** Phases A and B are complete. The "
        "georeference was attempted to exhaustion and is **not "
        "defensible**, so no control point was invented and no canonical "
        "row changed.",
        "",
        f"Run `{run_id}`, built on MAPGEN-014 commit "
        f"`{s['base_commit_mapgen014']}`.",
        "",
        "## 1. MAPGEN-014 review metric correction",
        "",
        "- MAPGEN-014's `saxony_*` counts were computed over the whole "
        "authorised candidate, which contains **both** Saxony and "
        "Saxe-Weimar. Saxe-Weimar's 100 unresolved hexes were therefore "
        "reported as Saxony's.",
        f"- Corrected, filtered by the subject named in each row's "
        f"provenance: Saxony alone ({s['saxony_targets']:,} targets) went "
        f"CONTROLLED **{s['saxony_controlled_before']:,} → "
        f"{s['saxony_controlled_after']:,}** and UNRESOLVED "
        f"**{s['saxony_unresolved_before']} → "
        f"{s['saxony_unresolved_after']:,}** — the same 401 rows, "
        "recomputed from canonical data rather than hard-coded.",
        f"- Saxe-Weimar is now its own metric: "
        f"{s['saxe_weimar_controlled']} CONTROLLED, "
        f"{s['saxe_weimar_unresolved']} UNRESOLVED.",
        "- The candidate-scope aggregate is kept but renamed "
        "`authorised_candidate_scope_*`, so no number carries a polity's "
        "name it does not describe.",
        "- **The canonical data was never wrong.** Only the summary was. "
        "No territorial_control row was touched by this correction.",
        "",
        "## 2. Corroboration metric split",
        "",
        f"- MAPGEN-014 reported `independent_boundary_corroborations = 1`. "
        "That row was an `AGREES` with **n_samples = 0** — a "
        "depiction-level agreement, not a measured boundary.",
        f"- Split: **depiction_level_corroborations = "
        f"{s['depiction_level_corroborations']}**, "
        f"**measured_boundary_corroborations = "
        f"{s['measured_boundary_corroborations']}**, "
        f"**measured_boundary_sample_count = "
        f"{s['measured_boundary_sample_count']}**. A measured "
        "corroboration now requires samples and real distance statistics; "
        "a 0-sample row is not allowed to carry any.",
        "",
        "## 3. Saxe-Weimar / Saxe-Eisenach: the sources disagree",
        "",
        "| supports | source |",
        "|---|---|",
        "| one unified polity from 1741 | BnF authority "
        "`ark:/12148/cb151032140`: *the 1741 reunion ... formed the duchy "
        "of Saxe-Weimar-Eisenach* — a **cataloguing heading** |",
        "| two distinct constituents | Landesarchiv Thüringen, Bestand "
        "26508 *Landesregierung Eisenach*: Eisenach kept its **own "
        "Regierung, Kammer and Oberkonsistorium** until the 1849/50 "
        "reform |",
        "| personal union | Deutsche Biographie `sfz39202`: Ernst August "
        "II Constantin (1748–1758) styled *Herzog von "
        "Sachsen-Weimar-Eisenach*, with a separate administrator in "
        "Eisenach during his minority |",
        "| two territories | the 1747 sheet's own title: *DVCATVM "
        "VINARIENSEM **nec non** ISENACENSIS Partes Boreales et "
        "Orientales* |",
        "",
        f"- **Decision: `{s['weimar_eisenach_model']}`.** "
        "`pol_saxe_eisenach` is registered as its own actor and a "
        "`PERSONAL_UNION` relationship records the shared ruler. **No** "
        "`pol_saxe_weimar_eisenach` was created — a ducal style is not a "
        "merged territory, and a surviving administration is not by "
        "itself a sovereign state.",
        "- `pol_saxe_weimar` is **not superseded**: it was incomplete, not "
        "wrong. No controller was created or withdrawn; Saxe-Eisenach has "
        "no geometry and controls nothing.",
        "",
        "## 4. What the 1747 raster actually yields",
        "",
        f"- **Native resolution verified.** `info.json` reports "
        f"{s['iiif_native_f1']} (f1) and {s['iiif_native_f2']} (f2), equal "
        "to the manifest canvas **and** to the locally held raster. There "
        "is no sharper scan to fetch, so magnification cannot add "
        "information.",
        f"- **Page skew measured** on {s['rectification_edges_measured']} "
        f"border edges; only {s['rectification_edges_reliable']} are "
        f"reliable. The top neat line fits within 10 px and gives a scan "
        f"rotation of **{s['scan_rotation_deg_f1']}°** (f1) and "
        f"**{s['scan_rotation_deg_f2']}°** (f2). The other six edges are "
        "recorded `DETECTOR_FAILED` — the detector locks onto title "
        "lettering and cartouches. **No rectification transform was "
        "applied**, and rectification is kept strictly separate from "
        "georeferencing.",
        f"- **{s['text_anchor_candidates']} text anchors** attacked at "
        f"×3 magnification with autocontrast: "
        f"{s['text_anchors_clear']} CLEAR, "
        f"{s['text_anchors_ambiguous']} AMBIGUOUS, "
        f"{s['text_anchors_unreadable']} UNREADABLE. Every UNREADABLE row "
        "has an **empty** reading.",
        "- **The real gain:** one longitude numeral was read "
        "unambiguously on sheet f2 — `2|9°`, the tick splitting the "
        "numeral, i.e. the 29th meridian from the sheet's own Ferro prime "
        "meridian. MAPGEN-014 could read none. The prime-meridian note "
        "and the scale bar were also transcribed.",
        "- **Why that is still not a transform:** one longitude value, "
        "with no traced graticule line, no latitude pair and nothing on "
        "sheet f1, cannot place a sheet. A transform would have required "
        "inventing the rest.",
        "",
        "## 5. What did NOT happen",
        "",
        "- No GCP row exists for the 1747 source. Its "
        "`georeference_status` is still `NOT_YET_GEOREFERENCED`.",
        "- No cross-source boundary distance was measured "
        f"(`measured_boundary_sample_count = "
        f"{s['measured_boundary_sample_count']}`).",
        f"- No local uncertainty zone was created "
        f"(`local_uncertainty_zones = {s['local_uncertainty_zones']}`); "
        f"the global {s['global_uncertainty_km']} km model stands.",
        "- The two-sheet seam is reported "
        f"`{s['sheet_seam_status']}` — not as a zero offset.",
        "- The Schwarzburg wash remains `UNCERTAIN_BOUNDARY`; no "
        "partition was manufactured by image processing.",
        f"- **`canonical_rows_changed_this_stage = "
        f"{s['canonical_rows_changed_this_stage']}`.** Saxe-Weimar stays "
        "at 0 CONTROLLED.",
        "",
        "## 6. Images",
        "",
    ]
    for n in img:
        lines.append(f"- `{n}` (aspect {aspects[n]})")
    lines += [
        "",
        "The cross-source residual figure is deliberately **absent** — "
        "there is no residual. The georeference figures are named "
        "*attempt* and state 0 accepted GCPs on their face.",
        "",
        "## 7. Validation",
        "",
        f"- `validation.csv`: M15 gates, pass count "
        f"{s['validation_pass']}.",
        "",
        "## 8. Known issues",
        "",
        "- The graticule numerals on sheet f1 were not read. The band "
        "slopes, so fixed windows clip the numerals; a window that "
        "follows the fitted top neat line is the obvious next attempt.",
        "- Only the top neat line is detectable. A rectification needs a "
        "detector that ignores cartouches and lettering.",
        "- The Eisenach archival finding is collection-level: the Vorwort "
        "page could not be rendered, so the reading came from the "
        "portal's index and is recorded at MEDIUM confidence.",
        "- Saxe-Eisenach has no geometry from any source.",
        "- Saxe-Weimar still has 0 CONTROLLED hexes, and will until a "
        "second source is genuinely georeferenced.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
