"""MAPGEN-017 — copy-specific source acquisition for Brandenburg.

The advance in this stage is a distinction the project had been eliding:
a map WORK is not a PLATE, and a plate is not the physical COPY in front
of you. MAPGEN-016 read a holding record for one copy and treated it as
if it dated the source. Here the BnF copy of the Vaugondy Brandenburg
sheet is acquired, its privilege date is read OFF THE PLATE, and every
other known copy is recorded as a copy rather than as the source.

The Brandenburg temporal problem is stated segment by segment instead of
as one convenient assertion, and none of the six segments is resolved.
So there is still no geometry and no control — but the blockers are now
specific enough to be worked one at a time.
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

STAGE = "MAPGEN-017"
H = Path("data/historical")
CK_BRAND = "vaugondy_1751_haute_saxe_septentrionale_pomeranie_brandebourg"
CK_BLHA = "lotter_c1758_mappa_electoratum_brandenburgensem_blha"
CK_1747 = "zollmann_1747_thuringiae_orientalis_bnf"
M16_COMMIT = "ff9bfed8899cade9ae5b696a6e1f5c78d0f5effb"
DEFERRED = "DEFERRED_AFTER_BOUNDED_ATTEMPT"
BRAND_RASTER = Path("data/raw/historical_maps/vaugondy_brandenburg/"
                    "vaugondy_1751_brandenburg_pomeranie_"
                    "btv1b53041280v_f1.jpg")


def _wrap(t, w=92):
    return [t[i:i + w] for i in range(0, len(t), w)]


def render_provenance(path, copies, lineage, title):
    fig, (ax, ax2) = _fig2((17, 9), [1.25, 1])
    ax.set_axis_off()
    body = ["MAP WORK  ->  PLATE  ->  PHYSICAL / DIGITISED COPY", ""]
    work = None
    for r in copies.itertuples():
        if r.map_work_id != work:
            work = r.map_work_id
            body += [f"WORK {work}", ""]
        body.append(f"  COPY {r.copy_id}")
        body.append(f"    holding   : {r.holding_institution[:74]}")
        body.append(f"    shelfmark : {r.shelfmark_or_ark[:74]}")
        body.append(f"    copy date : {r.catalogued_copy_date}   "
                    f"plate: {r.plate_date}   issue: {r.issue_date}")
        body.append(f"    political : {r.represented_political_date}")
        body.append(f"    state     : {r.copy_state} "
                    f"({r.copy_state_confidence})")
        body.append(f"    raster    : {r.raster_acquired}  "
                    f"{r.raster_pixels}   licence: {r.licence_status[:34]}")
        body.append(f"    role      : {r.role}")
        body.append("")
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=7.2)
    ax2.text(0.0, 0.99,
             "WHY THIS MATTERS\n\n"
             "MAPGEN-016 read a holding record for one copy and treated\n"
             "it as if it dated the SOURCE. A holding record names a\n"
             "COPY. The same plate can be pulled in 1751 and again in\n"
             "1757, and a later impression may carry revisions.\n\n"
             "The BnF copy's privilege date was read OFF THE PLATE\n"
             "('Avec Privilege. 1751' in the title cartouche), not\n"
             "inferred from a catalogue.\n\n"
             "LINEAGE\n\n"
             + "\n".join(f"  {r.plate_family:<32} {r.independence_status}"
                         f"  eligible={r.corroboration_eligible}"
                         for r in lineage.itertuples())
             + "\n\nMAPGEN-016 called the northern Vaugondy sheet\n"
               "DERIVATIVE. 'Same house, same atlas' does not prove that\n"
               "one sheet came FROM the other. Corrected to\n"
               "SHARED_ATLAS_LINEAGE: not independent for corroboration,\n"
               "but not asserted to be a derivation either.",
             va="top", family="monospace", fontsize=7.5)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_source_map(path, title):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    fig, ax = _fig((13, 10))
    im = Image.open(BRAND_RASTER)
    ax.imshow(im.resize((1500, int(1500 * im.height / im.width)),
                        Image.LANCZOS))
    ax.set_axis_off()
    ax.set_title(title, fontsize=10)
    _save(fig, path)


def render_continuity(path, seg, cont, title):
    fig, (ax, ax2) = _fig2((17, 7), [1, 1.1])
    ax.barh([r.segment_id.replace("seg_", "") for r in seg.itertuples()],
            [1] * len(seg), color="#b03a2e")
    for i, r in enumerate(seg.itertuples()):
        ax.text(0.02, i, f" {r.continuity_status}", va="center",
                fontsize=9, color="white")
    ax.set_xlim(0, 1)
    ax.set_xticks([])
    ax.set_title("boundary segment continuity, 1751 -> 1756-08-01",
                 fontsize=10)
    c = cont.iloc[0]
    body = ["WHY SEGMENT BY SEGMENT", ""]
    for ln in _wrap(str(c["why_not"]), 88):
        body.append("  " + ln)
    body += ["", "OUTSTANDING PER SEGMENT", ""]
    for r in seg.itertuples():
        body.append(f"  {r.frontier}")
        for ln in _wrap("     " + str(r.outstanding_question), 88):
            body.append(ln)
    body += ["", "SNAPSHOT DISCIPLINE", ""]
    for ln in _wrap(str(c["snapshot_discipline"]), 88):
        body.append("  " + ln)
    body += ["", "POLITICAL CONTROL AT THE SNAPSHOT", ""]
    for ln in _wrap(str(c["political_control_evidence_at_snapshot"]), 88):
        body.append("  " + ln)
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_status(path, s, title):
    fig, ax = _fig((15, 8))
    ax.set_axis_off()
    body = [
        "BRANDENBURG PRODUCTION STATUS", "",
        f"  BnF copy acquired      : {s['bnf_raster_acquired']}  "
        f"({s['bnf_raster_pixels']})",
        f"  BnF licence verified   : {s['bnf_licence_verified']}",
        f"  plate date, from plate : {s['bnf_plate_date']}",
        f"  represented political  : {s['bnf_represented_political_date']}",
        f"  graticule present      : {s['bnf_graticule_present']}",
        f"  georeferenced          : {s['bnf_georeferenced']}",
        f"  GCPs                   : {s['bnf_gcps']}",
        f"  uncertainty            : {s['brandenburg_uncertainty_km']}",
        "",
        f"  independent candidate  : {s['blha_source']}",
        f"  BLHA acquired          : {s['blha_acquired']}",
        f"  BLHA lineage           : {s['blha_lineage']}",
        "",
        f"  segments defined       : {s['continuity_segments_defined']}",
        f"  segments confirmed     : {s['continuity_segments_confirmed']}",
        f"  cross-source samples   : {s['cross_source_samples']}",
        "",
        f"  production features    : {s['new_production_features']}",
        f"  authorised snapshot    : {s['authorised_snapshot_features']}",
        f"  membership rows        : {s['new_hex_membership_rows']}",
        f"  Brandenburg CONTROLLED : {s['brandenburg_controlled']}",
        f"  Brandenburg UNRESOLVED : {s['brandenburg_unresolved']}",
        "",
        f"  canonical rows         : {s['canonical_rows_before']} -> "
        f"{s['canonical_rows_after']} (changed "
        f"{s['canonical_rows_changed']})",
        "", "OUTCOME: PARTIAL.", "",
        "  Every copy, date and licence question is now settled for the",
        "  primary sheet, and the raster is in hand with a graticule.",
        "  Georeferencing, digitisation and segment continuity remain.",
        "",
        "  No production row was manufactured to show progress.",
    ]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=9)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_progress(path, rows, waiting, title):
    fig, (ax, ax2) = _fig2((16, 7), [1.1, 1])
    import numpy as np

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
    ax2.text(0.0, 0.97, "SOURCES THE PROJECT IS WAITING ON\n\n"
             + "\n".join(f"  {a:<40} {b}" for a, b in waiting)
             + "\n\n  A deferred small-polity problem is no longer a\n"
               "  Europe-wide production blocker: Zollmann is parked and\n"
               "  Brandenburg proceeds on its own timetable.",
             va="top", family="monospace", fontsize=8)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def run_historical_copy(cfg: MapgenConfig,
                        run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"brandenburg_1756_acquisition_{_dt.datetime.now():%Y%m%d}"
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
    m16_dir = cfg.output_dir / scfg.get(
        "mapgen016_run", "central_europe_1756_expansion_20260813")
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
    features = gpd.read_parquet(H / "historical_boundary_features.parquet")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    lineage = pd.read_csv(H / "historical_source_lineage.csv")
    assertions = pd.read_csv(H / "historical_evidence_assertions.csv")
    copies = pd.read_csv(H / "historical_map_copy_registry.csv",
                         keep_default_na=False, na_values=[""])
    seg = pd.read_csv(H / "brandenburg_boundary_segment_continuity.csv")
    cont = pd.read_csv(H / "brandenburg_temporal_continuity_audit.csv")
    bgeo = pd.read_csv(H / "brandenburg_georeference_audit.csv")
    bnf_gcp = pd.read_csv(H / "brandenburg_bnf_gcps.csv")
    blha_gcp = pd.read_csv(H / "brandenburg_blha_gcps.csv")
    zaudit = pd.read_csv(H / "zollmann_georeference_final_audit.csv")
    cov = pd.read_csv(sdir / "political_coverage.csv",
                      keep_default_na=False, na_values=[""])
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv"]}
    src_brand = make_global_source_id(CK_BRAND)
    src_blha = make_global_source_id(CK_BLHA)
    src_1747 = make_global_source_id(CK_1747)
    acq = json.loads((BRAND_RASTER.parent / "acquisition.json")
                     .read_text(encoding="utf-8"))
    bnf = copies[copies["copy_id"] == "copy_bnf_ge_dd_2987_3790"].iloc[0]
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
    _check("M17-01_mapgen016_regression",
           len(canonical) == 1614
           and int((canonical["control_status"] == "CONTROLLED").sum())
           == 697
           and int((canonical["control_status"] == "UNRESOLVED").sum())
           == 917
           and sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and wei == {"CONTROLLED": 0, "UNRESOLVED": 96}
           and wash["UNRESOLVED"] == 89,
           f"MAPGEN-016 baseline intact: 1,614 rows (697/917), Saxony "
           f"{sax}, Saxe-Weimar {wei}, Schwarzburg wash {wash}")
    _check("M17-02_zollmann_status_semantics_corrected",
           zaudit.iloc[0]["final_status"] == DEFERRED
           and reg.loc[reg["global_source_id"] == src_1747,
                       "georeference_status"].iloc[0] == DEFERRED
           and "not been shown to be"
           in str(zaudit.iloc[0]["notes"]).lower(),
           f"Zollmann relabelled {DEFERRED}: MAPGEN-016's 'exhausted' "
           "claimed more than the evidence supported (f2 was never "
           "attempted and the failed windows were placement misses, not "
           "scan limits). Reopen on a better scan, another edition or "
           "dedicated manual work")
    _check("M17-03_zollmann_relabel_changed_no_data",
           len(assertions[assertions["global_source_id"] == src_1747]) == 0
           and src_1747 not in set(features["global_source_id"])
           and wei == {"CONTROLLED": 0, "UNRESOLVED": 96},
           "the relabelling touched no evidence assertion, no boundary "
           "feature and no control row")
    rel = snap.scenario_polity_relationships
    sp_wei = make_scenario_polity_id(scenario_id, "pol_saxe_weimar")
    sp_eis = make_scenario_polity_id(scenario_id, "pol_saxe_eisenach")
    _check("M17-04_weimar_eisenach_model_frozen",
           "pol_saxe_eisenach" in set(snap.polities["polity_id"])
           and "pol_saxe_weimar_eisenach" not in set(
               snap.polities["polity_id"])
           and ((rel["relationship_type"] == "PERSONAL_UNION")
                & rel["from_scenario_polity_id"].isin([sp_wei, sp_eis])
                & rel["to_scenario_polity_id"].isin([sp_wei, sp_eis])
                ).any(),
           "the personal-union model is frozen and Weimar/Eisenach "
           "geometry was not revisited in this stage")
    _check("M17-05_work_plate_copy_separated",
           len(copies) >= 4
           and copies["map_work_id"].nunique() == 2
           and copies["copy_id"].nunique() == len(copies)
           and set(copies.columns) >= {"map_work_id", "plate_id",
                                       "copy_id", "catalogued_copy_date",
                                       "plate_date", "issue_date",
                                       "represented_political_date",
                                       "copy_state",
                                       "copy_state_confidence"},
           f"{len(copies)} physical/digitised copies of "
           f"{copies['map_work_id'].nunique()} works are registered "
           "separately, each with its own copy date, plate date, issue "
           "date and state")
    ksi = copies[copies["copy_id"] == "copy_ksiaznica_pomorska_szczecin"] \
        .iloc[0]
    rum = copies[copies["copy_id"] == "copy_david_rumsey_3353_061"].iloc[0]
    _check("M17-06_ksiaznica_copy_demoted",
           ksi["copy_state"] == "COPY_STATE_NOT_ESTABLISHED"
           and ksi["role"] == "PLATE_STATE_COMPARISON_ONLY"
           and ksi["represented_political_date"] == "UNVERIFIED"
           and rum["issue_date"].startswith("1757"),
           "the Ksiaznica copy is demoted to plate-state comparison until "
           "its catalogue entry is read at COPY level; the Rumsey copy is "
           "recorded as a 1757 atlas issue of the same plate")
    _check("M17-07_bnf_raster_acquired",
           BRAND_RASTER.exists()
           and bnf["raster_acquired"] == "YES"
           and bnf["raster_pixels"] == "7941x6135"
           and bnf["raster_sha256"] == acq["sha256"]
           and acq["ark"] == "ark:/12148/btv1b53041280v",
           f"BnF copy acquired at IIIF native maximum "
           f"{bnf['raster_pixels']}, sha256 {acq['sha256'][:16]}..., "
           f"shelfmark {bnf['shelfmark_or_ark']}")
    _check("M17-08_bnf_licence_verified",
           "PUBLIC_DOMAIN" in bnf["licence_status"]
           and "VERIFIED" in bnf["licence_status"]
           and "NOT redistributed" in reg.loc[
               reg["global_source_id"] == src_brand,
               "licence_or_usage_note"].iloc[0],
           "licence verified as a public-domain work under Gallica "
           "conditions; the raster lives under data/raw and is NOT "
           "redistributed in this repository")
    _check("M17-09_copy_specific_dates_recorded",
           bnf["plate_date"] == "1751"
           and "READ FROM THE PLATE" in bnf["plate_date_basis"]
           and "Avec Privilege. 1751" in bnf["plate_date_basis"]
           and bnf["represented_political_date"] == "UNVERIFIED",
           "the 1751 date is read from the title cartouche of THIS "
           "impression, not from a catalogue; the represented political "
           "date remains UNVERIFIED and is not conflated with it")
    lb = lineage[lineage["global_source_id"] == src_brand].iloc[0]
    _check("M17-10_shared_atlas_not_asserted_as_derivation",
           lb["independence_status"] == "SHARED_ATLAS_LINEAGE"
           and lb["independence_status"] != "DERIVATIVE"
           and "does not prove" in lb["independence_reason"],
           "MAPGEN-016's DERIVATIVE label is corrected: sharing a house "
           "and an atlas does not prove that one sheet was derived from "
           "the other, in either direction")
    _check("M17-11_same_atlas_not_independent_corroboration",
           lb["corroboration_eligible"] == "NO",
           "the correction does not weaken the rule: a same-atlas sheet "
           "is still not eligible to corroborate, so one house's work is "
           "never counted twice")
    bl = lineage[lineage["global_source_id"] == src_blha].iloc[0]
    _check("M17-12_independent_candidate_searched",
           src_blha in set(reg["global_source_id"])
           and bl["plate_family"] == "GERMAN_SEUTTER_LOTTER_AUGSBURG"
           and bl["independence_status"] == "PARTIALLY_INDEPENDENT"
           and bl["corroboration_eligible"] == "YES",
           "an independent-lineage candidate was found and audited: the "
           "Lotter/Augsburg plate held by the Brandenburgisches "
           "Landeshauptarchiv, a different house from the French "
           "Vaugondy line")
    blha_copy = copies[copies["copy_id"]
                       == "copy_blha_original_copper_engraving"].iloc[0]
    _check("M17-13_blha_blocker_explicit",
           blha_copy["raster_acquired"] == "NO"
           and blha_copy["licence_status"] == "NOT_VERIFIED"
           and "signature was not confirmed" in blha_copy["notes"]
           and "must NOT be counted as multiple independent sources"
           in blha_copy["notes"],
           "the BLHA blocker is explicit: archival signature unconfirmed, "
           "licence unchecked, raster not acquired, and duplicate "
           "catalogue objects of the same title are not to be counted as "
           "separate sources")
    _check("M17-14_off_date_geometry_requires_continuity",
           src_brand not in set(assertions["global_source_id"])
           and src_blha not in set(assertions["global_source_id"])
           and bnf["role"] == "GEOMETRY_SHAPE_SUBSTRATE_CANDIDATE",
           "neither Brandenburg sheet carries any evidence assertion, so "
           "neither can reach the snapshot; a 1751 plate and a ca. 1758 "
           "plate both sit off the snapshot date and would each need "
           "their own continuity bridge")
    _check("M17-15_segment_continuity_explicit",
           len(seg) == 6
           and (seg["continuity_status"] == "UNRESOLVED").all()
           and seg["outstanding_question"].str.len().min() > 40
           and cont.iloc[0]["single_global_assertion_written"] == "NO",
           f"the temporal problem is stated across {len(seg)} named "
           "frontiers (Saxony, Mecklenburg, Swedish Pomerania, "
           "Magdeburg/Halberstadt, the Commonwealth, Silesia/Neumark), "
           "all UNRESOLVED; no single convenient assertion was written "
           "over the whole outline")
    _check("M17-16_snapshot_political_control_absent",
           "NONE" in cont.iloc[0]["political_control_evidence_at_snapshot"]
           and "before the Prussian invasion"
           in cont.iloc[0]["snapshot_discipline"]
           and snap.metadata["snapshot_date"] == "1756-08-01",
           "no POLITICAL_CONTROL assertion valid at 1756-08-01 was "
           "obtained for Brandenburg, and the pre-invasion snapshot "
           "discipline is restated: wartime occupation is not a legal "
           "boundary")
    _check("M17-17_georeference_not_faked",
           len(bnf_gcp) == 0 and len(blha_gcp) == 0
           and (bgeo["n_fit"] == 0).all()
           and bgeo["positional_uncertainty_km"].isna().all(),
           "no GCP and no transform exist for either Brandenburg sheet; "
           "the BnF sheet is acquired and inspected but not yet "
           "georeferenced")
    _check("M17-18_uncertainty_not_inherited",
           bgeo["positional_uncertainty_km"].isna().all()
           and "NOT inherited" in bgeo.iloc[0]["notes"],
           "Brandenburg has no uncertainty value: Saxony's 9.168 km is "
           "explicitly not inherited and this sheet must earn its own "
           "from its own holdout, line width and symbol residual")
    _check("M17-19_measured_corroboration_requires_samples",
           len(bnf_gcp) == 0 and len(blha_gcp) == 0,
           "cross-source boundary comparison sample count is 0; with "
           "neither sheet georeferenced there is nothing to measure, and "
           "no average line was synthesised from disagreeing sources")
    brand_sp = make_scenario_polity_id(scenario_id, "pol_brandenburg")
    roots = set(sp.loc[sp["territorial_authority_role"]
                       == "COMPOSITE_TERRITORIAL_ACTOR",
                       "scenario_polity_id"])
    _check("M17-20_brandenburg_actor_and_root_discipline",
           "pol_brandenburg" in set(snap.polities["polity_id"])
           and int((canonical["controller_scenario_polity_id"]
                    == brand_sp).sum()) == 0
           and not canonical["controller_scenario_polity_id"].isin(
               roots).any(),
           "the specific actor pol_brandenburg is the intended "
           "controller; it holds nothing yet, and no composite root "
           "(incl. the Prussian monarchy) holds duplicate control")
    _check("M17-21_pomerania_not_auto_assigned",
           "Swedish Pomerania" in reg.loc[
               reg["global_source_id"] == src_brand, "notes"].iloc[0]
           or "Swedish Pomerania" in seg.loc[
               seg["segment_id"] == "seg_swedish_pomerania",
               "outstanding_question"].iloc[0],
           "the sheet's own note (Swedish Pomerania comprises the duchy "
           "of Bardt, the county of Gutzkow and the duchy of Stettin) is "
           "recorded, and Pomerania is treated as a separate territorial "
           "question rather than assigned to Brandenburg")
    _check("M17-22_no_new_production_geometry",
           len(features) == 3
           and src_brand not in set(features["global_source_id"]),
           f"{len(features)} boundary features, all still from the 1756 "
           "sheet; no Brandenburg geometry was drawn")
    empty = pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"])
    log = pd.read_csv(sdir / "scenario_control_promotion_log.csv",
                      keep_default_na=False, na_values=[""])
    c2, p2, l2, rep = promote_control(
        canonical.copy(), provenance.copy(), log.copy(), empty,
        scenario_id, STAGE, M16_COMMIT, "none", "src_none",
        promoted_utc="2026-08-13")
    _check("M17-23_promotion_idempotent",
           rep["inserted"] == 0 and len(c2) == len(canonical)
           and rep["promotion_id"] == make_promotion_id(
               scenario_id, STAGE, sha256_of_frame(empty)),
           "the promotion workflow was exercised with this stage's empty "
           "candidate: 0 inserted, canonical untouched, promotion id "
           "content-derived")
    brow = cov[cov["coverage_unit_id"] == "region_brandenburg_1756_pilot"]
    _check("M17-24_coverage_transitioned_honestly",
           len(brow) == 1
           and brow.iloc[0]["source_evidence_status"] == "SOURCE_ACQUIRED"
           and brow.iloc[0]["control_coverage_status"] == "UNASSESSED"
           and int((cov["control_coverage_status"] == "COMPLETE").sum())
           == 0,
           "the Brandenburg coverage unit moved "
           "SOURCE_IDENTIFIED_NOT_ACQUIRED -> SOURCE_ACQUIRED while "
           "control coverage stays UNASSESSED; no unit anywhere is "
           "COMPLETE, so absence still means UNKNOWN")
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    wash_feat = features[features["historical_subject_id"]
                         == "hsub_schwarzburg_unpartitioned_wash"]
    _check("M17-25_low_countries_regression",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP",
           "Low Countries still SOURCE_GAP")
    _check("M17-26_schwarzburg_regression",
           len(wash_feat) == 1
           and wash_feat.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY",
           "the Schwarzburg wash is still UNCERTAIN_BOUNDARY with 89 "
           "UNRESOLVED hexes")
    _check("M17-27_europe_regression",
           int(eu_man["hex_count"].sum()) == 1885422,
           "Europe canonical grid intact (1,885,422 hexes)")
    _check("M17-28_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN"
           and int((canonical["territorial_target_type"]
                    == "ISLAND_COMPONENT").sum()) == 1,
           "Toshima hex still OCEAN with its island-component row intact")
    _check("M17-29_claims_not_derived",
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
    _check("M17-30_canonical_integrity", integ == [],
           f"canonical integrity: {integ or 'clean'}")
    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("M17-31_upstream_immutable", up_after == upstream,
           f"{len(upstream)} upstream artifacts byte-identical")
    _check("M17-32_no_new_schema",
           HPG_SCHEMA_VERSION == "1.4.0"
           and SCENARIO_SCHEMA_VERSION == "1.4.0"
           and not scan_forbidden_reference_code(Path(__file__)),
           "no schema or namespace was added: the copy registry is a new "
           "data table using existing conventions, and this module passes "
           "the forbidden-reference scan")

    # ---- outputs ---------------------------------------------------------
    t0 = time.perf_counter()
    img = ["brandenburg_copy_provenance.png",
           "brandenburg_bnf_source_map.png",
           "brandenburg_segment_continuity.png",
           "brandenburg_production_status.png",
           "europe_political_progress.png"]
    render_provenance(run_dir / img[0], copies,
                      lineage[lineage["global_source_id"].isin(
                          [src_brand, src_blha,
                           make_global_source_id(
                               "vaugondy_1756_haute_saxe_bnf")])],
                      "A. Map work, plate and physical copy")
    render_source_map(
        run_dir / img[1],
        "B. Acquired source — Vaugondy 1751, BnF GE DD-2987 (3790), "
        "Collection d'Anville (public domain; not redistributed)")
    render_continuity(run_dir / img[2], seg, cont,
                      "C. Brandenburg boundary segment continuity")
    summary_for_img = {}
    timings["render_s"] = 0.0

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    summary = [
        ("stage", STAGE), ("base_commit_mapgen016", M16_COMMIT),
        ("outcome", "PARTIAL"),
        ("zollmann_final_status", DEFERRED),
        ("map_works_registered", int(copies["map_work_id"].nunique())),
        ("physical_copies_registered", len(copies)),
        ("bnf_copy_id", "copy_bnf_ge_dd_2987_3790"),
        ("bnf_shelfmark", bnf["shelfmark_or_ark"]),
        ("bnf_catalogued_copy_date", bnf["catalogued_copy_date"]),
        ("bnf_plate_date", bnf["plate_date"]),
        ("bnf_represented_political_date",
         bnf["represented_political_date"]),
        ("bnf_copy_state", bnf["copy_state"]),
        ("bnf_raster_acquired", "YES"),
        ("bnf_raster_pixels", bnf["raster_pixels"]),
        ("bnf_raster_sha256", acq["sha256"]),
        ("bnf_licence_verified", "YES"),
        ("bnf_graticule_present", "YES"),
        ("bnf_georeferenced", "NO"), ("bnf_gcps", len(bnf_gcp)),
        ("ksiaznica_copy_state", ksi["copy_state"]),
        ("rumsey_copy_issue", rum["issue_date"]),
        ("vaugondy_lineage_status", lb["independence_status"]),
        ("vaugondy_corroboration_eligible", lb["corroboration_eligible"]),
        ("blha_source", "Lotter ca.1758, Mappa Geographica exhibens "
                        "Electoratum Brandenburgensem (BLHA)"),
        ("blha_acquired", "NO"),
        ("blha_lineage", bl["independence_status"]),
        ("blha_plate_family", bl["plate_family"]),
        ("continuity_segments_defined", len(seg)),
        ("continuity_segments_confirmed", 0),
        ("continuity_segments_unresolved", len(seg)),
        ("cross_source_samples", 0),
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
        ("canonical_rows_changed", 0), ("promotion_conflicts", 0),
        ("coverage_units", len(cov)), ("coverage_complete_units", 0),
        ("brandenburg_coverage_source_status",
         brow.iloc[0]["source_evidence_status"]),
        ("validation_pass", f"{n_pass}/{len(val)}"),
    ]
    sdict = dict(summary)
    render_status(run_dir / img[3], sdict,
                  "D. Brandenburg production status")
    render_progress(
        run_dir / img[4],
        [("Saxony", sax["CONTROLLED"], sax["UNRESOLVED"]),
         ("Saxe-Weimar", wei["CONTROLLED"], wei["UNRESOLVED"]),
         ("Schwarzburg wash", 0, wash["UNRESOLVED"]),
         ("Brandenburg", 0, 0)],
        [("Zollmann 1747 (Thuringia)", DEFERRED),
         ("Vaugondy 1751 (Brandenburg)", "ACQUIRED, not georeferenced"),
         ("Lotter ca.1758 (Brandenburg)", "identified, not acquired"),
         ("Utrecht 1756", "licence-blocked"),
         ("Low Countries atlas", "SOURCE_GAP")],
        "E. Europe political production progress")
    from PIL import Image

    aspects = {}
    for n in img:
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.size[0] / im.size[1], 3)
    _check("M17-33_absent_results_not_illustrated",
           "brandenburg_bnf_georeference.png" not in img
           and "brandenburg_cross_source_boundary.png" not in img
           and "brandenburg_continuous_geometry.png" not in img
           and "brandenburg_hex_control.png" not in img
           and "brandenburg_blha_source_map.png" not in img,
           "the georeference, cross-source, continuous-geometry, "
           "hex-control and BLHA figures are NOT produced, because none "
           "of those results exists")
    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    summary = [(k, v) for k, v in summary
               if k != "validation_pass"] + [
        ("validation_pass", f"{n_pass}/{len(val)}")]
    pd.DataFrame(summary, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "summary.csv", index=False)
    timings["render_s"] = time.perf_counter() - t0
    manifest = {
        "run_id": run_id, "stage": STAGE, "outcome": "PARTIAL",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen016": M16_COMMIT,
        "copy_model": (
            "map WORK -> PLATE -> physical/digitised COPY. MAPGEN-016 "
            "read a holding record for one copy and treated it as if it "
            "dated the source; four copies of two works are now "
            "registered separately, each with its own copy, plate and "
            "issue dates and its own state confidence."),
        "bnf_acquisition": {
            "ark": acq["ark"], "shelfmark": acq["shelfmark"],
            "collection": acq.get("collection"),
            "pixels": acq["pixels"], "sha256": acq["sha256"],
            "plate_date_read_from_plate": "Avec Privilege. 1751",
            "graticule": "numbered degree graticule on all four borders",
            "inset": "Supplement pour le Marquisat de Brandebourg "
                     "(Vieille Marche and Quartier de Pregnitz), same "
                     "scale",
            "map_own_note": "La Pomeranie Suedoise comprend le Duche de "
                            "Bardt, le Comte de Gutzkow et le Duche de "
                            "Stettin"},
        "zollmann_status_change": (
            f"GEOREFERENCE_EXHAUSTED_FOR_CURRENT_SCAN -> {DEFERRED}. The "
            "earlier label claimed more than the evidence supported. No "
            "data changed with the relabelling."),
        "what_did_not_happen": [
            "no georeference, no GCP, no transform for either sheet",
            "no BLHA raster acquired and no licence verified",
            "no continuity segment confirmed",
            "no Brandenburg geometry, membership or control",
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
    _write_readme(run_dir, run_id, dict(summary), copies, seg, aspects, img)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    copies_map = {
        "README_REVIEW.md": run_dir / "README_REVIEW.md",
        "run_manifest.json": run_dir / "run_manifest.json",
        "validation.csv": run_dir / "validation.csv",
        "summary.csv": run_dir / "summary.csv",
        "historical_map_copy_registry.csv":
            H / "historical_map_copy_registry.csv",
        "historical_source_lineage.csv":
            H / "historical_source_lineage.csv",
        "historical_source_assessment.csv":
            H / "historical_source_assessment.csv",
        "historical_source_registry.csv":
            H / "historical_source_registry.csv",
        "brandenburg_source_copy_audit.csv":
            H / "brandenburg_source_copy_audit.csv",
        "brandenburg_temporal_continuity_audit.csv":
            H / "brandenburg_temporal_continuity_audit.csv",
        "brandenburg_boundary_segment_continuity.csv":
            H / "brandenburg_boundary_segment_continuity.csv",
        "brandenburg_bnf_gcps.csv": H / "brandenburg_bnf_gcps.csv",
        "brandenburg_bnf_georeference_audit.csv":
            H / "brandenburg_bnf_georeference_audit.csv",
        "brandenburg_blha_gcps.csv": H / "brandenburg_blha_gcps.csv",
        "brandenburg_blha_georeference_audit.csv":
            H / "brandenburg_blha_georeference_audit.csv",
        "zollmann_georeference_final_audit.csv":
            H / "zollmann_georeference_final_audit.csv",
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
        "scenario_polities.csv": sdir / "scenario_polities.csv",
        "scenario_polity_relationships.csv":
            sdir / "scenario_polity_relationships.csv",
    }
    for dst, src in copies_map.items():
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
    print(f"[copy] {run_id}: validation {n_pass}/{len(val)}, outcome "
          f"PARTIAL, BnF raster acquired {bnf['raster_pixels']}, "
          f"{len(seg)} continuity segments all UNRESOLVED, canonical "
          f"unchanged ({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[copy][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, copies, seg, aspects, img):
    lines = [
        f"# {STAGE} Review — Brandenburg copy-specific source acquisition",
        "",
        "**OUTCOME: PARTIAL.** Every copy, date and licence question is "
        "now settled for the primary sheet and **the raster is in hand**. "
        "Georeferencing, digitisation and segment-level continuity "
        "remain, so there is still **no geometry and no control** — and "
        "no production row was manufactured to show progress.",
        "",
        f"Run `{run_id}`, built on MAPGEN-016 commit "
        f"`{s['base_commit_mapgen016']}`.",
        "",
        "## 1. A map work is not a plate, and a plate is not a copy",
        "",
        "- MAPGEN-016 read a holding record for one copy of the "
        "Brandenburg sheet and treated it as if it dated the **source**. "
        "A holding record names a **copy**. The same plate can be pulled "
        "in 1751 and again in 1757, and a later impression may carry "
        "revisions.",
        f"- A copy registry now records "
        f"**{s['physical_copies_registered']} copies of "
        f"{s['map_works_registered']} works**, each with its own "
        "`catalogued_copy_date`, `plate_date`, `issue_date`, "
        "`represented_political_date`, `copy_state` and state confidence.",
        f"- The **Książnica copy is demoted** to "
        f"`{s['ksiaznica_copy_state']}` / plate-state comparison until "
        "its catalogue entry is read at copy level; the **Rumsey copy** "
        f"is recorded as a `{s['rumsey_copy_issue']}` issue of the same "
        "plate. A pixel-level state comparison between copies was **not** "
        "carried out.",
        "",
        "## 2. The BnF copy — acquired, and dated from the plate itself",
        "",
        f"- **{s['bnf_shelfmark']}**, Collection d'Anville 03790, "
        f"`ark:/12148/btv1b53041280v`, single view **"
        f"{s['bnf_raster_pixels']}** at IIIF native maximum, sha256 "
        f"`{s['bnf_raster_sha256'][:16]}…`. Physical sheet 49.5 × 65 cm, "
        "contours coloured.",
        f"- **Licence verified**: public-domain work under Gallica "
        "conditions. The raster lives under `data/raw` (git-ignored) and "
        "is **not redistributed**.",
        f"- **`plate_date = {s['bnf_plate_date']}`, read off the plate**: "
        "the title cartouche ends *“Avec Privilège. 1751”*. That is this "
        "impression's engraved privilege date — not a catalogue "
        "inference.",
        f"- **`represented_political_date = "
        f"{s['bnf_represented_political_date']}`.** The plate date is not "
        "allowed to stand in for the political state depicted.",
        "- The sheet carries a **numbered degree graticule on all four "
        "borders** — the precondition the Zollmann sheets lacked — plus "
        "an inset *Supplement pour le Marquisat de Brandebourg* covering "
        "the Vieille Marche and Quartier de Pregnitz at the same scale.",
        "- The map states in its own note that **Swedish Pomerania "
        "comprises the duchy of Bardt, the county of Gutzkow and the "
        "duchy of Stettin** — the source itself warns against assigning "
        "Pomerania to Brandenburg.",
        "",
        "## 3. Lineage — a correction that does not weaken the rule",
        "",
        f"- MAPGEN-016 labelled the northern Vaugondy sheet `DERIVATIVE`. "
        "Sharing a house and an atlas does **not** prove that one sheet "
        "was derived from the other, in either direction. Corrected to "
        f"**`{s['vaugondy_lineage_status']}`**.",
        f"- The rule itself stands: "
        f"`corroboration_eligible = "
        f"{s['vaugondy_corroboration_eligible']}`. One house's work is "
        "never counted twice.",
        f"- An **independent-lineage candidate** was found: "
        f"*{s['blha_source']}*, engraved by Matthäus Albrecht Lotter and "
        "published by Tobias Conrad Lotter in Augsburg, ~1:550,000, held "
        f"as an original copper engraving at the BLHA. Plate family "
        f"`{s['blha_plate_family']}`, "
        f"`{s['blha_lineage']}`, corroboration-eligible.",
        f"- **Not acquired** (`{s['blha_acquired']}`): the archival "
        "signature was not confirmed at BLHA and the licence was not "
        "checked. Multiple catalogue objects with this title must not be "
        "counted as multiple independent sources until plate, impression "
        "and reproduction are told apart.",
        "",
        "## 4. The temporal problem, stated six times instead of once",
        "",
        f"- A single continuity assertion over the whole Brandenburg "
        "outline would hide the fact that its frontiers face six "
        "different neighbours with six different histories. So the "
        f"question is split into **{s['continuity_segments_defined']} "
        "named segments** — Saxony, Mecklenburg, Swedish Pomerania, "
        "Magdeburg/Halberstadt, the Polish-Lithuanian Commonwealth, and "
        "Silesia/Neumark.",
        f"- **{s['continuity_segments_confirmed']} confirmed, "
        f"{s['continuity_segments_unresolved']} UNRESOLVED.** Only "
        "`CONTINUITY_CONFIRMED` may bridge off-date geometry to the "
        "snapshot, so nothing bridges.",
        "- Both candidate sheets sit **off** the snapshot: 1751 before it "
        "and ca. 1758 after it. Each would need its own bridge, in its "
        "own direction.",
        "- **No `POLITICAL_CONTROL` assertion valid at 1756-08-01** was "
        "obtained for Brandenburg. The snapshot stays **before the "
        "Prussian invasion of Saxony**; wartime occupation is not a legal "
        "boundary and is not importable.",
        "",
        "## 5. What this stage produced, and did not",
        "",
        f"- Production features **{s['new_production_features']}**, "
        f"authorised snapshot **{s['authorised_snapshot_features']}**, "
        f"membership **{s['new_hex_membership_rows']}**, Brandenburg "
        f"CONTROLLED **{s['brandenburg_controlled']}**.",
        f"- Brandenburg uncertainty is **`"
        f"{s['brandenburg_uncertainty_km']}`** — Saxony's 9.168 km is "
        "explicitly not inherited; this sheet must earn its own from its "
        "own holdout, line width and symbol residual.",
        f"- Canonical rows **{s['canonical_rows_before']:,} → "
        f"{s['canonical_rows_after']:,}**, changed "
        f"**{s['canonical_rows_changed']}**. Saxony "
        f"{s['saxony_controlled']}/{s['saxony_unresolved']}, Saxe-Weimar "
        f"{s['saxe_weimar_controlled']}/{s['saxe_weimar_unresolved']}, "
        f"Schwarzburg wash 0/{s['schwarzburg_wash_unresolved']}.",
        f"- Coverage: `region_brandenburg_1756_pilot` moved "
        f"`SOURCE_IDENTIFIED_NOT_ACQUIRED` → "
        f"**`{s['brandenburg_coverage_source_status']}`**, with control "
        "coverage still `UNASSESSED`.",
        "",
        "## 6. Zollmann relabelled",
        "",
        f"- `GEOREFERENCE_EXHAUSTED_FOR_CURRENT_SCAN` → "
        f"**`{s['zollmann_final_status']}`**. The earlier label claimed "
        "more than the evidence supported: sheet f2 was never attempted "
        "and the four failed windows were **placement misses from a "
        "downscaled overview**, not scan limits. Zollmann has not been "
        "shown to be ungeoreferenceable — it is parked at the current "
        "production priority.",
        "- The relabelling changed **no** evidence assertion, boundary "
        "feature or control row.",
        "",
        "## 7. Images",
        "",
    ]
    for n in img:
        lines.append(f"- `{n}` (aspect {aspects[n]})")
    lines += [
        "",
        "There is deliberately **no** BnF georeference figure, no "
        "cross-source boundary figure, no continuous-geometry figure, no "
        "hex-control figure and no BLHA source map — none of those "
        "results exists.",
        "",
        "## 8. Validation",
        "",
        f"- `validation.csv`: M17 gates, pass count "
        f"{s['validation_pass']}.",
        "",
        "## 9. Known issues",
        "",
        "- The BnF sheet is acquired but **not georeferenced**. Its "
        "graticule is numbered and legible, so the graticule route is "
        "the obvious next step — unlike Zollmann.",
        "- No copy-state comparison was made between the BnF, Książnica "
        "and Rumsey copies (border colour, labels, cartouche, plate wear, "
        "annotations, boundary lines, inset, engraved date).",
        "- The BLHA signature and licence are unverified and the raster "
        "is not in hand, so no independent geometry exists.",
        "- All six continuity segments are unresolved, and no 1756 "
        "political-control evidence has been gathered for Brandenburg.",
        "- Brandenburg's internal constituents (Altmark, Mittelmark, "
        "Neumark, Uckermark, Prignitz) are visible on the sheet but were "
        "not audited; a visible constituent name is not a separate "
        "polity.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
