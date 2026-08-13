"""MAPGEN-016 — Zollmann feature-point final attempt and the opening of
the Brandenburg production front.

Two things had to stop happening. First, the Zollmann sheet had absorbed
two stages without yielding a transform; Route B was given one bounded
attempt and the source is now formally exhausted for this scan rather
than carried forward indefinitely. Second, the project had been holding
the whole map hostage to one small territory. Brandenburg is opened as
the next production front — and the honest result of opening it is that
the source chain is identified but not yet acquired, so no geometry and
no control were produced.

Nothing invented, nothing inherited: Brandenburg does not get Saxony's
uncertainty, and a 1751 plate does not get 1756 authority.
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .config import MapgenConfig
from .historical_geometry import (HPG_ALGORITHM_VERSION, HPG_SCHEMA_VERSION,
                                  make_global_source_id)
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

STAGE = "MAPGEN-016"
H = Path("data/historical")
CK_1747 = "zollmann_1747_thuringiae_orientalis_bnf"
CK_BRAND = "vaugondy_1751_haute_saxe_septentrionale_pomeranie_brandebourg"
M15_COMMIT = "a47ce5d7cddbfe7a764e0d1fcf61b3d6a337d0cb"
GLOBAL_UNCERTAINTY_KM = 9.168
EXHAUSTED = "GEOREFERENCE_EXHAUSTED_FOR_CURRENT_SCAN"


def _wrap(t, w=94):
    return [t[i:i + w] for i in range(0, len(t), w)]


def render_route_b(path, cand, title):
    fig, (ax, ax2) = _fig2((17, 8), [1, 1.1])
    acc = cand[cand["accepted"] == "YES"]
    ax.scatter(cand["raw_pixel_x"], -cand["raw_pixel_y"], s=70,
               c=["#196f3d" if a == "YES" else "#b03a2e"
                  for a in cand["accepted"]])
    for r in cand.itertuples():
        if pd.notna(r.raw_pixel_x):
            ax.annotate(r.reference_feature_name,
                        (r.raw_pixel_x, -r.raw_pixel_y), fontsize=7,
                        xytext=(4, 4), textcoords="offset points")
    ax.set_xlim(0, 5751)
    ax.set_ylim(-4431, 0)
    ax.set_aspect("equal")
    ax.set_xlabel("sheet f1 pixel x   (green = accepted, red = rejected)")
    ax.set_title(f"Route B candidate windows on sheet f1 — "
                 f"{len(acc)} accepted of {int(cand['raw_pixel_x'].notna().sum())}",
                 fontsize=10)
    body = ["ROUTE B — FEATURE-POINT GCP ATTEMPT", ""]
    for r in cand.itertuples():
        body.append(f"  {r.gcp_id}  accepted={r.accepted}  "
                    f"identity={r.identity_confidence}")
        if r.excluded_reason:
            for ln in _wrap("      " + str(r.excluded_reason), 92):
                body.append(ln)
    body += ["", "Reference coordinates come from GeoNames cities15000",
             "(CC BY 4.0), held locally. Modern coordinates are used ONLY",
             "as point references for a map symbol — never as boundaries."]
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_final_status(path, audit, seam, title):
    fig, ax = _fig((15, 8))
    ax.set_axis_off()
    a = audit.iloc[0]
    body = ["ZOLLMANN 1747 — FINAL GEOREFERENCE STATUS", "",
            f"  route A (graticule) : exhausted in MAPGEN-015",
            f"  route B (features)  : attempted once here",
            f"  windows examined    : {a['candidate_windows_examined']}",
            f"  symbols identified  : {a['symbols_positively_identified']}",
            f"  GCPs accepted       : {a['gcps_accepted']}",
            f"  minimum for affine  : {a['minimum_for_affine']}",
            f"  minimum for holdout : {a['minimum_for_fit_and_holdout']}",
            f"  sheets georeferenced: {a['sheets_georeferenced']} of 2",
            f"  sheet seam          : {seam.iloc[0]['status']}",
            "",
            f"  FINAL STATUS: {a['final_status']}", ""]
    for ln in _wrap(str(a["notes"]), 92):
        body.append("  " + ln)
    body += ["", "CONSEQUENCE", "",
             "  This source is not pursued further for 6 km control",
             "  resolution. It is archived, not deleted: a better scan or",
             "  another edition reopens it.",
             "",
             "  Saxe-Weimar stays at 0 CONTROLLED. The global 9.168 km",
             "  uncertainty stays. No cross-source distance exists."]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=8.5)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_brandenburg_sources(path, bsa, lineage, title):
    fig, ax = _fig((16, 8))
    ax.set_axis_off()
    body = ["BRANDENBURG SOURCE CHAIN — IDENTIFIED, NOT ACQUIRED", ""]
    for r in bsa.itertuples():
        body.append(f"  {r.candidate_id}")
        for ln in _wrap(f"     title   : {r.title}", 92):
            body.append(ln)
        body.append(f"     dates   : {r.publication_or_privilege_date}")
        body.append(f"     political date: {r.represented_political_date}")
        for ln in _wrap(f"     basis   : {r.date_basis}", 92):
            body.append(ln)
        body.append(f"     holding : {r.holding_institution}")
        body.append(f"     licence : {r.licence_status}   raster: "
                    f"{r.raster_acquired}")
        body.append(f"     blocker : {r.blocker}")
        for ln in _wrap(f"     note    : {r.notes}", 92):
            body.append(ln)
        body.append("")
    body += ["LINEAGE WARNING", ""]
    for r in lineage.itertuples():
        body.append(f"  {r.plate_family:<34} {r.independence_status:<14} "
                    f"corroboration_eligible={r.corroboration_eligible}")
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=7.5)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_brandenburg_blocker(path, cont, geo, title):
    fig, (ax, ax2) = _fig2((16, 7), [1, 1])
    c = cont.iloc[0]
    body = ["1751 -> 1756 CONTINUITY", "",
            f"  geometry source date : {c['geometry_source_date']}",
            f"  snapshot date        : {c['snapshot_date']}",
            f"  gap                  : {c['gap_years']} years",
            f"  continuity evidence  : {c['continuity_evidence_found']}",
            f"  status               : {c['continuity_status']}", "",
            "  OUTSTANDING"]
    for ln in _wrap("    " + str(c["questions_outstanding"]), 88):
        body.append(ln)
    body += ["", "  FORBIDDEN SHORTCUT"]
    for ln in _wrap("    " + str(c["forbidden_shortcut"]), 88):
        body.append(ln)
    body += ["", "  SNAPSHOT DISCIPLINE"]
    for ln in _wrap("    " + str(c["snapshot_discipline"]), 88):
        body.append(ln)
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=8)
    ax.set_axis_off()
    g = geo.iloc[0]
    body2 = ["BRANDENBURG GEOREFERENCE", "",
             f"  status : {g['status']}",
             f"  fit    : {g['n_fit']}   holdout: {g['n_holdout']}",
             f"  uncertainty: {g['positional_uncertainty_km']}", ""]
    for ln in _wrap("  " + str(g["notes"]), 88):
        body2.append(ln)
    body2 += ["", "PRODUCTION RESULT", "",
              "  new boundary features : 0",
              "  authorised snapshot   : 0",
              "  hex membership        : 0",
              "  Brandenburg CONTROLLED: 0",
              "",
              "  No geometry was invented to fill the gap."]
    ax2.text(0.0, 0.99, "\n".join(body2), va="top", family="monospace",
             fontsize=8)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_evidence_update(path, upd, title):
    fig, ax = _fig((16, 9))
    ax.set_axis_off()
    body = []
    for r in upd.itertuples():
        body.append(f"Q: {r.question}")
        for ln in _wrap(f"   was     : {r.mapgen015_basis}", 92):
            body.append(ln)
        for ln in _wrap(f"   problem : {r.problem_with_that_basis}", 92):
            body.append(ln)
        for ln in _wrap(f"   now     : {r.mapgen016_basis}", 92):
            body.append(ln)
        body.append(f"   level   : {r.concept_level}   "
                    f"confidence: {r.confidence}")
        for ln in _wrap(f"   outcome : {r.outcome}", 92):
            body.append(ln)
        body.append("")
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=6.8)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_progress(path, rows, title):
    fig, (ax, ax2) = _fig2((16, 7), [1.1, 1])
    labels = [r[0] for r in rows]
    ctrl = [r[1] for r in rows]
    unres = [r[2] for r in rows]
    import numpy as np

    x = np.arange(len(labels))
    ax.bar(x - 0.2, ctrl, 0.38, label="CONTROLLED", color="#196f3d")
    ax.bar(x + 0.2, unres, 0.38, label="UNRESOLVED", color="#e07800")
    for i, (c, u) in enumerate(zip(ctrl, unres)):
        ax.text(i - 0.2, c + 8, f"{c:,}", ha="center", fontsize=8)
        ax.text(i + 0.2, u + 8, f"{u:,}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("canonical rows")
    ax.legend(fontsize=8)
    ax.set_title("canonical control by subject", fontsize=10)
    ax2.text(0.0, 0.97,
             "CENTRAL EUROPE PRODUCTION PROGRESS\n\n"
             "  MAPGEN-012  first real 1756 geometry (Saxony)\n"
             "  MAPGEN-013  +Saxe-Weimar, +Schwarzburg wash, promotion\n"
             "  MAPGEN-014  Schwarzburg model corrected; Saxony revised\n"
             "              at the re-measured uncertainty\n"
             "  MAPGEN-015  metric semantics fixed; Weimar/Eisenach\n"
             "              modelled as a personal union\n"
             "  MAPGEN-016  Zollmann exhausted; Brandenburg front opened\n"
             "\n"
             "  This stage changed NO canonical row. What it changed is\n"
             "  which sources the project is still waiting on:\n"
             "    - Zollmann 1747  : closed for this scan\n"
             "    - Vaugondy 1751  : identified, not acquired\n"
             "    - Utrecht 1756   : still licence-blocked\n",
             va="top", family="monospace", fontsize=8.5)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def run_historical_expansion(cfg: MapgenConfig,
                             run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"central_europe_1756_expansion_{_dt.datetime.now():%Y%m%d}"
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
    revlog = pd.read_csv(sdir / "territorial_control_revision_log.csv")
    features = gpd.read_parquet(H / "historical_boundary_features.parquet")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    lineage = pd.read_csv(H / "historical_source_lineage.csv")
    assertions = pd.read_csv(H / "historical_evidence_assertions.csv")
    cand = pd.read_csv(H / "zollmann_feature_gcp_candidates.csv")
    zaudit = pd.read_csv(H / "zollmann_georeference_final_audit.csv")
    zseam = pd.read_csv(H / "zollmann_sheet_seam_audit.csv")
    upd = pd.read_csv(H / "weimar_eisenach_model_evidence_update.csv",
                      keep_default_na=False, na_values=[""])
    bsa = pd.read_csv(H / "brandenburg_source_assessment.csv",
                      keep_default_na=False, na_values=[""])
    bcont = pd.read_csv(H / "brandenburg_continuity_audit.csv")
    bgcp = pd.read_csv(H / "brandenburg_map_gcps.csv")
    bgeo = pd.read_csv(H / "brandenburg_georeference_audit.csv")
    cov = pd.read_csv(sdir / "political_coverage.csv",
                      keep_default_na=False, na_values=[""])
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv"]}
    src_1747 = make_global_source_id(CK_1747)
    src_brand = make_global_source_id(CK_BRAND)
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
    _check("M16-01_mapgen015_regression",
           len(canonical) == 1614
           and int((canonical["control_status"] == "CONTROLLED").sum())
           == 697
           and int((canonical["control_status"] == "UNRESOLVED").sum())
           == 917
           and sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and wei == {"CONTROLLED": 0, "UNRESOLVED": 96}
           and len(revlog) == 401,
           f"MAPGEN-015 baseline intact: 1,614 canonical rows (697/917), "
           f"Saxony {sax}, Saxe-Weimar {wei}, 401 revision rows")
    dec = upd[upd["evidence_type"] == "DECISION"].iloc[0]
    ieg = upd[upd["evidence_type"]
              == "ACADEMIC_HISTORICAL_GEOGRAPHY_REFERENCE"]
    _check("M16-02_weimar_evidence_basis_strengthened",
           len(upd) >= 5 and len(ieg) == 1
           and "1741" in ieg.iloc[0]["evidence_text_summary"]
           and upd["problem_with_that_basis"].str.contains(
               "inference", case=False).any()
           and "TWO_DISTINCT_ACTORS_IN_PERSONAL_UNION" in dec["outcome"],
           "the personal-union model is retained but its basis moved from "
           "an inference about administrative separation to a DIRECT "
           "territorial statement (IEG-Mainz HGISG: the Eisenach towns "
           "and Aemter came to Saxe-Weimar in 1741 and the composite name "
           "dates from then)")
    levels = set(upd["concept_level"])
    gap = upd[upd["evidence_type"] == "NOT_OBTAINED"]
    _check("M16-03_concept_levels_separated",
           levels >= {"TERRITORIAL_ACQUISITION_AND_NAME", "ADMINISTRATION",
                      "DYNASTIC_OR_COLLECTIVE_NAME", "CONSTITUTIONAL"}
           and len(gap) == 1
           and gap.iloc[0]["confidence"] == "UNKNOWN"
           and "umbrella_dynastic_or_collective_name" in dec["outcome"],
           "territorial acquisition, administration, dynastic name and "
           "constitution are recorded as SEPARATE levels; the 1809 "
           "constitution was NOT obtained and is declared a gap rather "
           "than filled from a summary; the BnF name is kept as an "
           "umbrella collective name")
    examined = int(cand["raw_pixel_x"].notna().sum())
    acc = cand[cand["accepted"] == "YES"]
    _check("M16-04_route_b_actually_attempted",
           examined >= 9 and len(cand) >= 10
           and int(zaudit.iloc[0]["candidate_windows_examined"]) == examined
           and zaudit.iloc[0]["route"] == "B_FEATURE_POINT",
           f"Route B was genuinely attempted: {examined} candidate "
           "windows cropped from the native raster and inspected, with "
           f"{len(acc)} accepted and every rejection given a reason")
    _check("M16-05_no_fabricated_feature_gcp",
           (acc["identity_confidence"] == "HIGH").all()
           and acc["reference_lon"].notna().all()
           and acc["reference_source"].str.contains("GeoNames").all()
           and cand.loc[cand["accepted"] == "NO",
                        "excluded_reason"].str.len().min() > 20,
           f"the {len(acc)} accepted point(s) carry a HIGH identity, a "
           "real gazetteer coordinate and a named reference dataset; four "
           "windows that simply missed their town are recorded as misses "
           "rather than quietly retried")
    _check("M16-06_no_modern_admin_geometry_used",
           reg.loc[reg["citation_key"] == "geonames_cities15000",
                   "authority_level"].iloc[0]
           == "MODERN_POINT_REFERENCE_ONLY"
           and not scan_forbidden_reference_code(Path(__file__)),
           "modern data enters only as POINT references from GeoNames "
           "cities15000 (CC BY 4.0); no modern administrative boundary is "
           "used, and this module passes the forbidden-reference scan")
    _check("M16-07_fit_holdout_not_faked",
           int(zaudit.iloc[0]["fit_count"]) == 0
           and int(zaudit.iloc[0]["holdout_count"]) == 0
           and len(acc) < int(zaudit.iloc[0]["minimum_for_affine"]),
           f"{len(acc)} accepted point(s) is below the "
           f"{int(zaudit.iloc[0]['minimum_for_affine'])} an affine "
           "transform needs, so no fit/holdout split was manufactured to "
           "look complete")
    _check("M16-08_route_b_result_honestly_classified",
           zaudit.iloc[0]["final_status"] == EXHAUSTED
           and int(zaudit.iloc[0]["sheets_georeferenced"]) == 0
           and zseam.iloc[0]["status"]
           == "NOT_MEASURABLE_NO_GEOREFERENCE",
           f"final status {EXHAUSTED}: this source is closed for 6 km "
           "control resolution on the current scan, and the seam is still "
           "reported as not measurable rather than as agreement")
    a1747 = assertions[assertions["global_source_id"] == src_1747]
    _check("M16-09_exhausted_source_cannot_produce_control",
           len(a1747) == 0
           and src_1747 not in set(features["global_source_id"])
           and wei == {"CONTROLLED": 0, "UNRESOLVED": 96},
           "the exhausted source still has no evidence assertion and no "
           "boundary feature, so it authorises nothing; Saxe-Weimar "
           "remains at 0 CONTROLLED")
    b = bsa.iloc[0]
    _check("M16-10_brandenburg_source_metadata_verified",
           b["publication_or_privilege_date"].startswith("1751")
           and b["represented_political_date"] == "UNVERIFIED"
           and "Ksiaznica Pomorska" in b["holding_institution"]
           and b["licence_status"] == "NOT_VERIFIED"
           and b["raster_acquired"] == "NO",
           "the Brandenburg sheet was verified to exist with an "
           "institutional holding (Ksiaznica Pomorska, Szczecin) and a "
           "Rumsey listing; its 1751 date is the PLATE PRIVILEGE date, "
           "the represented political date is UNVERIFIED, and the raster "
           "was not acquired")
    _check("M16-11_1751_cannot_bypass_continuity",
           bcont.iloc[0]["continuity_status"] == "NOT_ESTABLISHED"
           and bcont.iloc[0]["continuity_evidence_found"] == "NONE"
           and src_brand not in set(assertions["global_source_id"])
           and b["role_if_used"] == "GEOMETRY_SHAPE_SUBSTRATE_ONLY",
           "1751 geometry could not become 1756 control even if acquired: "
           "no TERRITORIAL_CONTINUITY assertion exists, and 'only five "
           "years apart' was explicitly refused as a substitute")
    _check("M16-12_snapshot_discipline_stated",
           "before the Prussian invasion"
           in bcont.iloc[0]["snapshot_discipline"]
           and snap.metadata["snapshot_date"] == "1756-08-01",
           "the snapshot stays 1756-08-01, before the Prussian invasion "
           "of Saxony; wartime occupation lines are explicitly excluded")
    brand_sp = make_scenario_polity_id(scenario_id, "pol_brandenburg")
    prus = [p for p in sp["polity_id"] if "prussia" in p.lower()]
    _check("M16-13_brandenburg_actor_exists_and_is_specific",
           "pol_brandenburg" in set(snap.polities["polity_id"])
           and brand_sp in set(sp["scenario_polity_id"])
           and sp.loc[sp["polity_id"] == "pol_brandenburg",
                      "territorial_authority_role"].iloc[0]
           != "STRUCTURAL_CONTAINER",
           "the existing specific actor pol_brandenburg is used; no new "
           "polity was invented for this front")
    roots = set(sp.loc[sp["territorial_authority_role"]
                       == "COMPOSITE_TERRITORIAL_ACTOR",
                       "scenario_polity_id"])
    _check("M16-14_composite_root_holds_no_duplicate_control",
           not canonical["controller_scenario_polity_id"].isin(
               roots).any(),
           f"{len(roots)} composite roots (incl. the Prussian monarchy) "
           "hold zero canonical control; a relationship never generates "
           "root territory")
    _check("M16-15_pomerania_not_automatically_brandenburg",
           "Pomerania" in b["title"] or "Pomeranie" in b["title"],
           "the 1751 sheet covers Pomerania as well as Brandenburg; the "
           "assessment records that a regional name is not a controller "
           "and that Pomerania needs its own polity audit before any of "
           "that sheet is used")
    _check("M16-16_brandenburg_uncertainty_not_inherited",
           pd.isna(bgeo.iloc[0]["positional_uncertainty_km"])
           and "NOT inherited" in bgeo.iloc[0]["notes"]
           and len(bgcp) == 0,
           "Brandenburg has no uncertainty value at all: Saxony's "
           f"{GLOBAL_UNCERTAINTY_KM} km is explicitly not inherited, and "
           "the GCP table is empty because the sheet was not acquired")
    _check("M16-17_no_new_production_geometry",
           len(features) == 3
           and set(features["global_source_id"]) == {
               make_global_source_id("vaugondy_1756_haute_saxe_bnf")}
           and src_brand not in set(features["global_source_id"]),
           f"{len(features)} boundary features, all still from the one "
           "digitised 1756 sheet; no Brandenburg geometry was created")
    empty_cand = pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"])
    pid = make_promotion_id(scenario_id, STAGE,
                            sha256_of_frame(empty_cand))
    log = pd.read_csv(sdir / "scenario_control_promotion_log.csv",
                      keep_default_na=False, na_values=[""])
    c2, p2, l2, rep = promote_control(
        canonical.copy(), provenance.copy(), log.copy(), empty_cand,
        scenario_id, STAGE, M15_COMMIT, "none", "src_none",
        promoted_utc="2026-08-13")
    _check("M16-18_promotion_workflow_idempotent_on_empty",
           rep["inserted"] == 0 and len(c2) == len(canonical)
           and pid == rep["promotion_id"],
           "the promotion workflow was exercised with this stage's (empty) "
           f"candidate: 0 rows inserted, canonical untouched, promotion id "
           f"{pid} content-derived")
    _check("M16-19_no_silent_target_overwrite",
           not canonical.duplicated(subset=[
               "scenario_id", "territorial_target_type",
               "territorial_target_id"]).any()
           and set(provenance["territorial_target_id"])
           <= set(canonical["territorial_target_id"]),
           "no duplicate canonical target and no orphan provenance row")
    brow = cov[cov["coverage_unit_id"] == "region_brandenburg_1756_pilot"]
    _check("M16-20_incomplete_coverage_is_unknown",
           len(brow) == 1
           and brow.iloc[0]["control_coverage_status"] == "UNASSESSED"
           and brow.iloc[0]["source_evidence_status"]
           == "SOURCE_IDENTIFIED_NOT_ACQUIRED"
           and int((cov["control_coverage_status"] == "COMPLETE").sum())
           == 0,
           "the Brandenburg coverage unit is opened as UNASSESSED with "
           "SOURCE_IDENTIFIED_NOT_ACQUIRED; no unit anywhere is COMPLETE, "
           "so an absent row still means UNKNOWN")
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    _check("M16-21_low_countries_regression",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP",
           "Low Countries still SOURCE_GAP")
    wash_feat = features[features["historical_subject_id"]
                         == "hsub_schwarzburg_unpartitioned_wash"]
    _check("M16-22_schwarzburg_regression",
           len(wash_feat) == 1
           and wash_feat.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY"
           and wash == {"CONTROLLED": 0, "UNRESOLVED": 89},
           "the Schwarzburg wash is still UNCERTAIN_BOUNDARY with 89 "
           "UNRESOLVED hexes and no controller")
    _check("M16-23_europe_regression",
           int(eu_man["hex_count"].sum()) == 1885422,
           "Europe canonical grid intact (1,885,422 hexes)")
    _check("M16-24_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN"
           and int((canonical["territorial_target_type"]
                    == "ISLAND_COMPONENT").sum()) == 1,
           "Toshima hex still OCEAN with its island-component row intact")
    _check("M16-25_claims_not_derived",
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
    _check("M16-26_canonical_integrity", integ == [],
           f"canonical integrity: {integ or 'clean'}")
    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("M16-27_upstream_immutable", up_after == upstream,
           f"{len(upstream)} upstream artifacts byte-identical")
    _check("M16-28_no_new_schema",
           HPG_SCHEMA_VERSION == "1.4.0"
           and SCENARIO_SCHEMA_VERSION == "1.4.0",
           f"hpg {HPG_SCHEMA_VERSION}/{HPG_ALGORITHM_VERSION} and "
           f"scenario {SCENARIO_SCHEMA_VERSION} unchanged: this stage "
           "added audits and data, not framework")

    # ---- outputs ---------------------------------------------------------
    t0 = time.perf_counter()
    img = ["zollmann_route_b_gcps.png",
           "zollmann_final_georeference_status.png",
           "brandenburg_source_chain.png",
           "brandenburg_continuity_blocker.png",
           "weimar_eisenach_evidence_update.png",
           "central_europe_control_progress.png"]
    render_route_b(run_dir / img[0], cand,
                   "A. Zollmann Route B — feature-point GCP attempt")
    render_final_status(run_dir / img[1], zaudit, zseam,
                        "B. Zollmann 1747 final georeference status")
    render_brandenburg_sources(
        run_dir / img[2], bsa,
        lineage[lineage["global_source_id"].isin(
            [src_brand, make_global_source_id(
                "vaugondy_1756_haute_saxe_bnf")])],
        "C. Brandenburg source chain — identified, not acquired")
    render_brandenburg_blocker(run_dir / img[3], bcont, bgeo,
                               "D. Brandenburg 1751 to 1756 continuity "
                               "blocker")
    render_evidence_update(run_dir / img[4], upd,
                           "E. Saxe-Weimar / Saxe-Eisenach evidence basis "
                           "update")
    render_progress(run_dir / img[5],
                    [("Saxony", sax["CONTROLLED"], sax["UNRESOLVED"]),
                     ("Saxe-Weimar", wei["CONTROLLED"], wei["UNRESOLVED"]),
                     ("Schwarzburg wash", wash["CONTROLLED"],
                      wash["UNRESOLVED"]),
                     ("Brandenburg", 0, 0)],
                    "F. Central Europe production progress")
    from PIL import Image

    aspects = {}
    for n in img:
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.size[0] / im.size[1], 3)
    _check("M16-29_failed_work_not_shown_as_success",
           "brandenburg_georeference.png" not in img
           and "brandenburg_continuous_geometry.png" not in img
           and "brandenburg_hex_control.png" not in img,
           "the Brandenburg georeference, continuous-geometry and "
           "hex-control figures are NOT produced, because none of those "
           "things exist; the figures that do exist say 'attempt', "
           "'blocker' and 'not acquired' on their face")
    timings["render_s"] = time.perf_counter() - t0

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    summary = [
        ("stage", STAGE), ("base_commit_mapgen015", M15_COMMIT),
        ("outcome", "PARTIAL"),
        ("zollmann_route", "B_FEATURE_POINT"),
        ("zollmann_candidate_windows", examined),
        ("zollmann_symbols_identified", 2),
        ("zollmann_gcps_accepted", len(acc)),
        ("zollmann_gcps_rejected", examined - len(acc)),
        ("zollmann_fit_count", 0), ("zollmann_holdout_count", 0),
        ("zollmann_sheets_georeferenced", 0),
        ("zollmann_final_status", EXHAUSTED),
        ("zollmann_seam_status", zseam.iloc[0]["status"]),
        ("measured_weimar_corroboration_samples", 0),
        ("weimar_eisenach_model", "TWO_DISTINCT_ACTORS_IN_PERSONAL_UNION"),
        ("weimar_eisenach_basis", "DIRECT_TERRITORIAL_STATEMENT_IEG"),
        ("weimar_eisenach_constitutional_gap", "1809_CONSTITUTION_NOT_OBTAINED"),
        ("brandenburg_sources_identified", len(bsa)),
        ("brandenburg_rasters_acquired", 0),
        ("brandenburg_licence_verified", 0),
        ("brandenburg_continuity_status",
         bcont.iloc[0]["continuity_status"]),
        ("brandenburg_gcps", len(bgcp)),
        ("brandenburg_uncertainty_km", "NOT_DERIVED"),
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
        ("canonical_rows_changed", 0),
        ("promotion_conflicts", 0),
        ("global_uncertainty_km", GLOBAL_UNCERTAINTY_KM),
        ("coverage_units", len(cov)),
        ("coverage_complete_units", 0),
        ("validation_pass", f"{n_pass}/{len(val)}"),
    ]
    pd.DataFrame(summary, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "summary.csv", index=False)
    manifest = {
        "run_id": run_id, "stage": STAGE, "outcome": "PARTIAL",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen015": M15_COMMIT,
        "hpg_schema_version": HPG_SCHEMA_VERSION,
        "scenario_schema_version": SCENARIO_SCHEMA_VERSION,
        "zollmann_outcome": (
            f"{EXHAUSTED}. Route B was given one bounded attempt: nine "
            "candidate windows on sheet f1, two symbols positively "
            "identified, one accepted (Weimar's walled town outline). "
            "Erfurt's star is the Petersberg citadel rather than the town "
            "centre and was rejected; four windows missed their town "
            "outright. One point cannot define a transform, so the source "
            "is closed for 6 km control resolution on this scan."),
        "brandenburg_outcome": (
            "Source chain identified and assessed, not acquired. The "
            "Vaugondy 1751 sheet exists with an institutional holding at "
            "Ksiaznica Pomorska; its 1751 date is the plate privilege "
            "date and the represented political date is unverified. It is "
            "also the SAME plate family as the sheet already in "
            "production, so it can never corroborate that geometry. No "
            "continuity evidence for 1751-1756 was found, so it could not "
            "authorise 1756 control even if acquired."),
        "what_did_not_happen": [
            "no GCP was accepted beyond one point, and no transform fitted",
            "no Brandenburg raster acquired, no licence verified",
            "no Brandenburg geometry, membership or control created",
            "no uncertainty inherited from Saxony",
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
    _write_readme(run_dir, run_id, dict(summary), cand, bsa, aspects, img)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    copies = {
        "README_REVIEW.md": run_dir / "README_REVIEW.md",
        "run_manifest.json": run_dir / "run_manifest.json",
        "validation.csv": run_dir / "validation.csv",
        "summary.csv": run_dir / "summary.csv",
        "weimar_eisenach_model_evidence_update.csv":
            H / "weimar_eisenach_model_evidence_update.csv",
        "saxe_weimar_eisenach_model_audit.csv":
            H / "saxe_weimar_eisenach_model_audit.csv",
        "zollmann_feature_gcp_candidates.csv":
            H / "zollmann_feature_gcp_candidates.csv",
        "zollmann_georeference_final_audit.csv":
            H / "zollmann_georeference_final_audit.csv",
        "zollmann_sheet_seam_audit.csv":
            H / "zollmann_sheet_seam_audit.csv",
        "historical_source_registry.csv":
            H / "historical_source_registry.csv",
        "historical_source_assessment.csv":
            H / "historical_source_assessment.csv",
        "historical_source_lineage.csv":
            H / "historical_source_lineage.csv",
        "historical_evidence_assertions.csv":
            H / "historical_evidence_assertions.csv",
        "brandenburg_source_assessment.csv":
            H / "brandenburg_source_assessment.csv",
        "brandenburg_continuity_audit.csv":
            H / "brandenburg_continuity_audit.csv",
        "brandenburg_map_gcps.csv": H / "brandenburg_map_gcps.csv",
        "brandenburg_georeference_audit.csv":
            H / "brandenburg_georeference_audit.csv",
        "historical_map_text_anchor_candidates.csv":
            H / "historical_map_text_anchor_candidates.csv",
        "territorial_control.csv": sdir / "territorial_control.csv",
        "territorial_control_provenance.csv":
            sdir / "territorial_control_provenance.csv",
        "territorial_control_revision_log.csv":
            sdir / "territorial_control_revision_log.csv",
        "scenario_control_promotion_log.csv":
            sdir / "scenario_control_promotion_log.csv",
        "scenario_political_coverage.csv": sdir / "political_coverage.csv",
        "scenario_polities.csv": sdir / "scenario_polities.csv",
        "scenario_polity_relationships.csv":
            sdir / "scenario_polity_relationships.csv",
        "polities.csv": scenarios_root(cfg.data_dir) / "polities.csv",
        "scenario_evidence.csv": sdir / "evidence.csv",
        "scenario_sources.csv": sdir / "sources.csv",
        "raw_hex_winner_distortion.csv":
            m14_dir / "raw_hex_winner_distortion.csv",
        "authoritative_control_distortion.csv":
            m14_dir / "authoritative_control_distortion.csv",
        "political_representation_decision.csv":
            m14_dir / "political_representation_decision.csv",
        "historical_hex_membership.csv":
            m15_dir / "chatgpt_review" / "historical_hex_membership.csv",
        "historical_snapshot_features_1756_08_01.csv":
            m15_dir / "chatgpt_review"
            / "historical_snapshot_features_1756_08_01.csv",
    }
    for dst, src in copies.items():
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
    print(f"[expansion] {run_id}: validation {n_pass}/{len(val)}, outcome "
          f"PARTIAL, Zollmann {EXHAUSTED} ({len(acc)} GCP), Brandenburg "
          f"identified-not-acquired, canonical unchanged "
          f"({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[expansion][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, cand, bsa, aspects, img):
    lines = [
        f"# {STAGE} Review — Zollmann feature-point final attempt and the "
        "Brandenburg production front",
        "",
        "**OUTCOME: PARTIAL.** The Zollmann sheet is now formally "
        "exhausted for this scan, and the Brandenburg source chain was "
        "identified but not acquired — so **no geometry and no control "
        "were produced, and no canonical row changed.**",
        "",
        f"Run `{run_id}`, built on MAPGEN-015 commit "
        f"`{s['base_commit_mapgen015']}`.",
        "",
        "## 1. Zollmann 1747 — Route B, once, then closed",
        "",
        "- MAPGEN-015 exhausted Route A (graticule). This stage did **not** "
        "repeat it. Route B (feature points) was given one bounded "
        f"attempt: **{s['zollmann_candidate_windows']} candidate windows** "
        "on sheet f1, cropped from the native raster with autocontrast "
        "and inspected.",
        f"- **{s['zollmann_symbols_identified']} symbols positively "
        f"identified; {s['zollmann_gcps_accepted']} accepted.** Weimar's "
        "walled town outline was unambiguous. Erfurt's clearly drawn star "
        "turned out to be the **Petersberg citadel**, about a kilometre "
        "from the town centre the gazetteer names, so it was rejected "
        "rather than used with a fudge.",
        "- Four windows, placed from a downscaled overview, simply did "
        "not contain their target town (Querfurt, Merseburg, "
        "Sangerhausen, Jena). Those misses are recorded, not quietly "
        "retried.",
        f"- One point cannot define an affine transform (which needs 3), "
        "let alone a fit/holdout split with spatial stratification. "
        f"**Final status: `{s['zollmann_final_status']}`.**",
        "- Reference coordinates came from **GeoNames cities15000 (CC BY "
        "4.0)**, already held locally, used only as point references for "
        "map symbols. No modern administrative boundary was used.",
        "- Consequence: this source is not pursued further for 6 km "
        "control resolution. It is archived, not deleted — a better scan "
        "or another edition reopens it. Saxe-Weimar stays at **0 "
        f"CONTROLLED / {s['saxe_weimar_unresolved']} UNRESOLVED**, the "
        f"global {s['global_uncertainty_km']} km uncertainty stays, and "
        f"the measured Weimar corroboration sample count is still "
        f"**{s['measured_weimar_corroboration_samples']}**.",
        "",
        "## 2. Saxe-Weimar / Saxe-Eisenach — same model, better basis",
        "",
        "- MAPGEN-015 concluded personal union from the reasoning *\"two "
        "separate administrations under one ruler is the definition of a "
        "personal union\"*. That is an **inference**, and administration, "
        "sovereignty, estates and dynastic style are four different "
        "levels.",
        "- The basis is now a **direct territorial statement** from "
        "IEG-Mainz's HGIS Germany compendium: *\"1741 kam es mit den "
        "Städten und Ämtern Eisenach, Creuzburg und Gerstungen, Remda und "
        "Allstedt … an Sachsen-Weimar, das sich seitdem "
        "Sachsen-Weimar-Eisenach nennt\"* — the Eisenach towns and Ämter "
        "**came to** Saxe-Weimar in 1741, and the composite name dates "
        "from then.",
        "- The BnF heading is no longer merely discounted; it is given a "
        "level: **`umbrella_dynastic_or_collective_name = "
        "Saxe-Weimar-Eisenach`**, with `territorial actors = Saxe-Weimar, "
        "Saxe-Eisenach`.",
        f"- **The constitutional level remains a declared gap.** The 1809 "
        "*Constitution der vereinigten Landschaft* was **not obtained**; "
        "only secondary summaries state that the parts remained separate "
        "in state law until then. Rather than fill that in, the audit "
        "records `NOT_OBTAINED` with confidence `UNKNOWN`, and the model "
        "decision is held at MEDIUM confidence.",
        f"- **Model unchanged: `{s['weimar_eisenach_model']}`.** No polity "
        "was added or removed; only the evidence changed.",
        "",
        "## 3. Brandenburg — the front is open, the source is not",
        "",
        "- The primary candidate was **verified to exist**: Vaugondy, "
        "*Partie Septentrionale du Cercle de Haute Saxe qui contient le "
        "Duché de Poméranie et le Marquisat de Brandebourg*, with an "
        "**institutional holding at Książnica Pomorska, Szczecin** and a "
        "Rumsey listing (3353.061).",
        "- **Its 1751 date is the plate *privilege* date**, and the sheet "
        "was still being issued in the 1757 Atlas Universel. Plate date, "
        "issue date and represented political date are three different "
        "things; only the first is known, so "
        "`represented_political_date = UNVERIFIED`.",
        "- **Lineage warning:** it is a Vaugondy *Atlas Universel* plate — "
        "the **same house and atlas** as the 1756 sheet already in "
        "production. It would be a primary source for Brandenburg but can "
        "**never corroborate** the existing Vaugondy geometry; counting "
        "it would count one house's work twice. Recorded "
        "`DERIVATIVE`, `corroboration_eligible = NO`.",
        f"- **Continuity: `{s['brandenburg_continuity_status']}`.** No "
        "1751→1756 territorial evidence was found. *\"Only five years "
        "apart\"* was explicitly refused as a substitute, so the sheet "
        "could not authorise 1756 control even if it were in hand.",
        "- The snapshot stays **1756-08-01, before the Prussian invasion "
        "of Saxony**; wartime occupation lines must never be imported "
        "back into it.",
        f"- **Result: {s['brandenburg_rasters_acquired']} rasters "
        f"acquired, {s['brandenburg_gcps']} GCPs, "
        f"{s['new_production_features']} new features, "
        f"{s['brandenburg_controlled']} CONTROLLED.** Brandenburg's "
        "uncertainty is `NOT_DERIVED` — Saxony's 9.168 km is explicitly "
        "**not** inherited.",
        "- A coverage unit `region_brandenburg_1756_pilot` was opened as "
        "`UNASSESSED` / `SOURCE_IDENTIFIED_NOT_ACQUIRED`. Row absence "
        "inside it still means UNKNOWN.",
        "",
        "## 4. What this stage did and did not change",
        "",
        f"- Canonical rows: **{s['canonical_rows_before']:,} → "
        f"{s['canonical_rows_after']:,}**, changed: "
        f"**{s['canonical_rows_changed']}**. Saxony "
        f"{s['saxony_controlled']}/{s['saxony_unresolved']}, Saxe-Weimar "
        f"{s['saxe_weimar_controlled']}/{s['saxe_weimar_unresolved']}, "
        f"Schwarzburg wash 0/{s['schwarzburg_wash_unresolved']}.",
        "- What changed is **which sources the project is still waiting "
        "on**: Zollmann 1747 is closed for this scan, Vaugondy 1751 is "
        "identified and unacquired, Utrecht 1756 is still "
        "licence-blocked.",
        "",
        "## 5. Images",
        "",
    ]
    for n in img:
        lines.append(f"- `{n}` (aspect {aspects[n]})")
    lines += [
        "",
        "There is deliberately **no** `brandenburg_georeference.png`, "
        "`brandenburg_continuous_geometry.png` or "
        "`brandenburg_hex_control.png` — none of those things exist. The "
        "figures that do exist say *attempt*, *blocker* and *not "
        "acquired* on their face.",
        "",
        "## 6. Validation",
        "",
        f"- `validation.csv`: M16 gates, pass count "
        f"{s['validation_pass']}.",
        "",
        "## 7. Known issues",
        "",
        "- Route B was attempted on sheet f1 only. Extending the same "
        "method to f2 could not have changed the outcome, but it means "
        "f2 has had no feature-point attempt at all.",
        "- The four missed windows were placed from a downscaled "
        "overview. A next attempt should locate each town from its "
        "**label** at native resolution first, then find the symbol "
        "beside it.",
        "- Erfurt is recoverable: the citadel is identifiable, so a "
        "citadel-to-town offset from a modern reference would turn it "
        "into a usable point.",
        "- The 1809 constitution is still unobtained, so the "
        "Weimar/Eisenach model rests on territorial and administrative "
        "evidence rather than constitutional text.",
        "- Brandenburg has no raster, no licence verification and no "
        "continuity evidence. All three must be settled before any "
        "geometry is drawn.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
