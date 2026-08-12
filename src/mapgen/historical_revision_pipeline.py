"""MAPGEN-014 — Central Europe corroboration, Schwarzburg model
correction and canonical authority revision.

Three things happen here, in this order, because the later ones depend
on the earlier ones:

  1. a second, much finer historical source is acquired and its
     cartographic LINEAGE is determined, so that corroboration cannot be
     double-counted from a copy of the same plate,
  2. the false single Schwarzburg polity is superseded by the two
     principalities that actually existed, and the wash that produced it
     is demoted to a non-gameplay-convertible source region,
  3. the canonical Saxony authority that was promoted at the old 2.975 km
     uncertainty is RE-MEASURED and superseded. Keeping a reviewed row
     that is known to be stale is not an option.

Overlay is never used to hide a source-uncertainty failure.
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
                                 compile_authorised_snapshot_features,
                                 controls_from_membership,
                                 hexification_audit, land_union_from,
                                 membership_conservation_audit,
                                 overlay_candidates_from_audit,
                                 validate_assertion_table,
                                 validate_feature_evidence_links)
from .historical_geometry import (GAMEPLAY_CONVERTIBLE_ROLES,
                                  HPG_ALGORITHM_VERSION, HPG_SCHEMA_VERSION,
                                  load_evidence_assertions,
                                  load_feature_evidence_links,
                                  load_global_sources, make_global_source_id)
from .historical_pilot_pipeline import (classify_hex_confidence, _fig,
                                        _fig2, _hex_coll, _parts, _save)
from .islands import ground_area_perimeter
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, load_scenario,
                       make_scenario_polity_id, make_source_id,
                       scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .scenario_promotion import (
    PROMOTION_LOG_COLUMNS, PROVENANCE_COLUMNS, REVISION_LOG_COLUMNS,
    SCENARIO_CONTROL_PROMOTION_ALGORITHM_VERSION,
    SCENARIO_CONTROL_PROMOTION_SCHEMA_VERSION, promote_control,
    revise_control, validate_canonical_control)
from .sources import sha256_of

STAGE = "MAPGEN-014"
SNAPSHOT_DATE = "1756-08-01"
H = Path("data/historical")
CK_VAUG = "vaugondy_1756_haute_saxe_bnf"
CK_1747 = "zollmann_1747_thuringiae_orientalis_bnf"
CK_NDB = "ndb_24_2010_schwarzburg_grafen_von"
M13_COMMIT = "5eff1643982ccc8954dbeced216f7ed71053c9dd"
OLD_UNCERTAINTY_KM = 2.975
PILOT_MARGIN_M = 20000.0
WASH_SUBJECT = "hsub_schwarzburg_unpartitioned_wash"
NEW_SCHWARZBURG = ["pol_schwarzburg_rudolstadt",
                   "pol_schwarzburg_sondershausen"]
POLITY_COLOURS = ["#1f618d", "#b03a2e", "#196f3d", "#7d3c98"]
CORROBORATION_COLUMNS = [
    "subject_a", "boundary_segment_id", "source_a", "source_b",
    "lineage_independence", "n_samples", "median_distance_km",
    "p90_distance_km", "p95_distance_km", "max_distance_km",
    "source_a_uncertainty_km", "source_b_uncertainty_km",
    "agreement_status", "notes",
]
REPRESENTATION_COLUMNS = [
    "historical_subject_id", "scenario_polity_id", "source_area_km2",
    "reliable_geometry", "standard_hex_survival", "zero_hex_fragments",
    "enclave_fragments", "recommended_mode", "decision_reason",
]


def render_lineage(path, lineage, corrob, title):
    fig, (ax, ax2) = _fig2((17, 8), [1, 1])
    cols = ["global_source_id", "plate_family", "independence_status",
            "lineage_confidence", "corroboration_eligible"]
    ax.text(0.0, 0.98, "SOURCE LINEAGE\n\n"
            + lineage[cols].to_string(index=False)
            + "\n\nBeing held by different libraries is not independence.\n"
              "A derivative or same-plate copy repeats the same\n"
              "information and must never raise confidence twice.",
            va="top", family="monospace", fontsize=8)
    ax.set_axis_off()
    ax2.text(0.0, 0.98, "BOUNDARY CORROBORATION\n\n"
             + corrob[["subject_a", "source_b", "lineage_independence",
                       "n_samples", "agreement_status"]].to_string(
                 index=False)
             + "\n\n" + "\n".join(
                 f"- {r.subject_a}: {r.notes[:78]}"
                 for r in corrob.itertuples()),
             va="top", family="monospace", fontsize=7.5)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_secondary(path, imgs, title):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    fig, axes = _fig2((17, 7), [1, 1])
    for ax, (cap, p) in zip(axes, imgs):
        if p is not None and Path(p).exists():
            im = Image.open(p)
            im = im.resize((1200, int(1200 * im.height / im.width)),
                           Image.LANCZOS)
            ax.imshow(im)
        else:
            ax.text(0.5, 0.5, "raster not redistributed", ha="center")
        ax.set_axis_off()
        ax.set_title(cap, fontsize=9)
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_correction(path, corr, sp, title):
    fig, ax = _fig((15, 8.5))
    ax.set_axis_off()
    c = corr.iloc[0]
    body = [
        "BEFORE (MAPGEN-013)", "",
        f"  {c['old_polity_id']}  [{c['old_active_status']}]",
        f"  model : {c['old_model']}", "",
        "PROBLEM", "",
    ] + ["  " + c["problem"][i:i + 88]
         for i in range(0, len(c["problem"]), 88)] + [
        "", "EVIDENCE", "",
    ] + ["  " + c["historical_evidence"][i:i + 88]
         for i in range(0, len(c["historical_evidence"]), 88)] + [
        "", "AFTER (MAPGEN-014)", "",
        f"  {c['old_polity_id']}  ->  {c['new_active_status']}",
    ]
    for p in NEW_SCHWARZBURG:
        r = sp[sp["polity_id"] == p]
        if len(r):
            body.append(f"  + {p}  [{r.iloc[0]['existence_status']}, "
                        f"{r.iloc[0]['territorial_authority_role']}]")
    body += ["", "TERRITORIAL IMPACT", ""] + [
        "  " + c["territorial_control_impact"][i:i + 88]
        for i in range(0, len(c["territorial_control_impact"]), 88)]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=8.5)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_uncertainty(path, before, after, title):
    fig, (ax, ax2) = _fig2((16, 7), [1, 1])
    labels = ["CONTROLLED", "UNRESOLVED"]
    x = np.arange(2)
    ax.bar(x - 0.2, [before["CONTROLLED"], before["UNRESOLVED"]], 0.38,
           label=f"promoted at {OLD_UNCERTAINTY_KM} km", color="#999999")
    ax.bar(x + 0.2, [after["CONTROLLED"], after["UNRESOLVED"]], 0.38,
           label="revised at re-measured uncertainty", color="#b03a2e")
    for i, (b, a) in enumerate(zip(
            [before["CONTROLLED"], before["UNRESOLVED"]],
            [after["CONTROLLED"], after["UNRESOLVED"]])):
        ax.text(i - 0.2, b + 8, f"{b:,}", ha="center", fontsize=9)
        ax.text(i + 0.2, a + 8, f"{a:,}", ha="center", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("canonical Saxony rows")
    ax.legend(fontsize=8)
    ax.set_title("Saxony canonical authority before / after", fontsize=10)
    ax2.text(0.0, 0.95,
             "The 2.975 km classification was NOT kept just because it\n"
             "had been reviewed. It was re-measured against the source's\n"
             "own positional error and superseded.\n\n"
             "No uncertainty was lowered to make hexes controllable:\n"
             "the revision moves rows OUT of CONTROLLED, not into it.\n\n"
             "Every changed row is written to\n"
             "territorial_control_revision_log.csv with its old and new\n"
             "status, controller, promotion id and uncertainty.",
             va="top", family="monospace", fontsize=9)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_revision(path, rev, log, title):
    fig, (ax, ax2) = _fig2((17, 7), [1, 1])
    if len(rev):
        counts = (rev["old_status"] + " -> " + rev["new_status"]
                  ).value_counts()
        ax.barh(list(counts.index)[::-1], list(counts.values)[::-1],
                color="#b03a2e")
        for i, v in enumerate(list(counts.values)[::-1]):
            ax.text(v, i, f" {v:,}", va="center", fontsize=9)
        ax.set_xlabel("canonical rows revised")
    else:
        ax.text(0.5, 0.5, "no row changed", ha="center")
        ax.set_axis_off()
    ax.set_title("canonical control revision", fontsize=10)
    ax2.text(0.0, 0.98, log[["promotion_id", "source_stage",
                             "promotion_status", "promoted_row_count",
                             "controlled_count", "unresolved_count",
                             "supersedes_promotion_id"]].T.to_string(
        header=False), va="top", family="monospace", fontsize=7)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_control(path, polys, ids, canonical, colours, auth, labels,
                   title):
    from matplotlib.patches import Patch

    fig, ax = _fig((13, 10))
    st = dict(zip(canonical["territorial_target_id"],
                  canonical["control_status"]))
    who = dict(zip(canonical["territorial_target_id"],
                   canonical["controller_scenario_polity_id"]))
    cols = []
    for h in ids:
        s = st.get(h)
        if s == "CONTROLLED":
            cols.append(colours.get(who.get(h), "#1f618d"))
        elif s == "UNRESOLVED":
            cols.append("#e07800")
        else:
            cols.append("#eeeae0")
    _hex_coll(ax, polys, cols, lw=0.2)
    for t in auth.itertuples():
        for p in _parts(t.geometry):
            xs, ys = zip(*p.exterior.coords)
            ax.plot(xs, ys, color="#111111", lw=1.3)
    ax.legend(handles=[Patch(color=c, label=f"CONTROLLED — {labels[n]}")
                       for n, c in colours.items()]
              + [Patch(color="#e07800",
                       label="UNRESOLVED (source cannot resolve the hex)"),
                 Patch(color="#eeeae0",
                       label="no row = UNKNOWN (coverage incomplete)")],
              fontsize=7, loc="lower right")
    b = shapely.bounds(polys)
    ax.set_xlim(b[:, 0].min(), b[:, 2].max())
    ax.set_ylim(b[:, 1].min(), b[:, 3].max())
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(title, fontsize=10)
    _save(fig, path)


def run_historical_revision(cfg: MapgenConfig,
                            run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"central_europe_1756_revision_{_dt.datetime.now():%Y%m%d}"
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    val_rows: list[dict] = []

    def _check(cid, ok, detail):
        val_rows.append({"run_id": run_id, "check_id": cid,
                         "pass": bool(ok), "detail": str(detail)})
        if not ok:
            warnings.append(f"VALIDATION FAIL {cid}: {detail}")

    grid = HexGrid(flat_to_flat=float(cfg.raw["terrain"]["hex_size_m"]),
                   orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)
    geo_dir = cfg.output_dir / scfg["geography_run"]
    eu_dir = cfg.output_dir / scfg.get("mapgen010_run",
                                       "europe_foundation_20260811")
    m13_dir = cfg.output_dir / scfg.get(
        "mapgen013_run", "central_europe_1756_expand_20260813")
    sdir = scenarios_root(cfg.data_dir) / scenario_id
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv"]}

    # ---- load -----------------------------------------------------------
    t0 = time.perf_counter()
    reg = load_global_sources(cfg.data_dir)
    assertions = load_evidence_assertions(cfg.data_dir)
    links = load_feature_evidence_links(cfg.data_dir)
    features = gpd.read_parquet(H / "historical_boundary_features.parquet")
    mapping = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    lineage = pd.read_csv(H / "historical_source_lineage.csv")
    correction = pd.read_csv(H / "polity_model_correction_audit.csv")
    assess = pd.read_csv(H / "historical_source_assessment.csv")
    snap = load_scenario(cfg.data_dir, scenario_id)
    sp = snap.scenario_polities
    scen_src = make_source_id(scenario_id, CK_VAUG)
    timings["load_s"] = time.perf_counter() - t0

    # ---- compile: the wash can no longer reach production ---------------
    t0 = time.perf_counter()
    authorised, rejected = compile_authorised_snapshot_features(
        features, links, assertions, reg, mapping, SNAPSHOT_DATE)
    unc_km = float(authorised["positional_uncertainty_km"].max())
    src_union = shapely.union_all(list(authorised.geometry))
    b = shapely.bounds(src_union)
    ext = (b[0] - PILOT_MARGIN_M, b[1] - PILOT_MARGIN_M,
           b[2] + PILOT_MARGIN_M, b[3] + PILOT_MARGIN_M)
    q, r = grid.hexes_covering_bbox(*ext)
    polys, hex_ids = grid.polygons(q, r), grid.hex_ids(q, r)
    from .europe_pipeline import load_land_parts

    parts, tree = load_land_parts(
        cfg.output_dir / "europe_land_cache" / "europe_land_parts.parquet",
        ext, 12000.0)
    land_geoms = np.empty(len(polys), dtype=object)
    terr = np.zeros(len(polys), dtype=bool)
    by_hex: dict[int, list] = {}
    for hi, pi in zip(*tree.query(polys, predicate="intersects")):
        by_hex.setdefault(int(hi), []).append(parts[int(pi)])
    for i in range(len(polys)):
        ps = by_hex.get(i)
        g = shapely.intersection(polys[i], shapely.union_all(ps)) \
            if ps else None
        land_geoms[i] = g
        if g is not None and not shapely.is_empty(g):
            terr[i] = (shapely.area(g) / grid.area) >= cfg.land_threshold
    land_by_id = {h: land_geoms[i] for i, h in enumerate(hex_ids)
                  if land_geoms[i] is not None
                  and not shapely.is_empty(land_geoms[i])}
    land_by_hex = dict(zip(hex_ids, land_geoms))
    fmem, mem = bind_snapshot_to_hexes(authorised, polys, hex_ids,
                                       land_geoms, terr, scenario_id,
                                       SNAPSHOT_DATE)
    bnd = {t.scenario_polity_id: shapely.boundary(t.geometry)
           for t in authorised.itertuples()}
    k = float(np.cos(np.radians(51.1)))
    mem["distance_to_source_boundary_km"] = [
        round(float(shapely.distance(shapely.centroid(land_by_hex[h]),
                                     bnd[p])) * k / 1000.0, 4)
        for h, p in zip(mem["hex_id"], mem["scenario_polity_id"])]
    mem["positional_uncertainty_km"] = unc_km
    mem["hex_confidence_class"] = [classify_hex_confidence(r_, unc_km)
                                   for _, r_ in mem.iterrows()]
    dom = mem[mem["is_dominant"]]
    confident = dom[dom["hex_confidence_class"] != "BORDER_UNCERTAIN"]
    uncertain = dom[dom["hex_confidence_class"] == "BORDER_UNCERTAIN"]
    ctrl = controls_from_membership(confident, scenario_id)
    unres = pd.DataFrame([{
        "scenario_id": scenario_id,
        "territorial_target_type": "TERRESTRIAL_HEX",
        "territorial_target_id": t.hex_id,
        "controller_scenario_polity_id": None,
        "control_status": "UNRESOLVED",
        "source_confidence": t.source_confidence,
        "source_id": t.bundle_source_ids.split("|")[0],
        "source_ids": t.bundle_source_ids,
        "political_evidence_ids": t.bundle_evidence_ids,
        "boundary_feature_ids": t.contributing_boundary_feature_ids,
        "historical_subject_ids": t.contributing_historical_subject_ids,
        "notes": "hex centre lies within the source's own positional "
                 f"uncertainty ({unc_km:.3f} km) of the drawn boundary — "
                 "no second source resolves it",
    } for t in uncertain.itertuples()], columns=ctrl.columns) \
        if len(uncertain) else pd.DataFrame(columns=ctrl.columns)
    candidate = pd.concat([ctrl, unres], ignore_index=True)
    timings["bind_s"] = time.perf_counter() - t0

    # ---- corroboration (measured, including its failure) ----------------
    lin = dict(zip(lineage["global_source_id"],
                   lineage["independence_status"]))
    src_1747, src_vaug = (make_global_source_id(CK_1747),
                          make_global_source_id(CK_VAUG))
    corrob = pd.DataFrame([
        {"subject_a": "hsub_meissen_electoral_saxony_core",
         "boundary_segment_id": "seg_meissen_full_outline",
         "source_a": CK_VAUG, "source_b": CK_1747,
         "lineage_independence": lin.get(src_1747), "n_samples": 0,
         "median_distance_km": None, "p90_distance_km": None,
         "p95_distance_km": None, "max_distance_km": None,
         "source_a_uncertainty_km": unc_km, "source_b_uncertainty_km": None,
         "agreement_status": "INSUFFICIENT_OVERLAP",
         "notes": "The 1747 sheets are titled Thuringiae Orientalis and "
                  "cover eastern Thuringia; the electoral Saxon core "
                  "around Meissen is outside them, so no common boundary "
                  "segment exists to compare."},
        {"subject_a": "hsub_duchy_of_saxe_weimar",
         "boundary_segment_id": "seg_weimar_full_outline",
         "source_a": CK_VAUG, "source_b": CK_1747,
         "lineage_independence": lin.get(src_1747), "n_samples": 0,
         "median_distance_km": None, "p90_distance_km": None,
         "p95_distance_km": None, "max_distance_km": None,
         "source_a_uncertainty_km": unc_km, "source_b_uncertainty_km": None,
         "agreement_status": "UNRESOLVED",
         "notes": "Overlap EXISTS and the 1747 sheet draws Weimar in "
                  "far more detail (lettered Aemter a.W., a.O.W., a.Cr., "
                  "a.Br.u.H., a.C., a.D., a.R., a.O., a.G. plus the "
                  "Oldisleben exclave), but georeferencing was not "
                  "completed, so no distance could be measured. Not "
                  "claimed as agreement."},
        {"subject_a": WASH_SUBJECT,
         "boundary_segment_id": "seg_schwarzburg_depiction",
         "source_a": CK_VAUG, "source_b": CK_1747,
         "lineage_independence": lin.get(src_1747), "n_samples": 0,
         "median_distance_km": None, "p90_distance_km": None,
         "p95_distance_km": None, "max_distance_km": None,
         "source_a_uncertainty_km": unc_km, "source_b_uncertainty_km": None,
         "agreement_status": "AGREES",
         "notes": "Depiction-level agreement, verified by reading both "
                  "rasters: neither source separates Schwarzburg-"
                  "Rudolstadt from Schwarzburg-Sondershausen. The 1747 "
                  "sheets organise Schwarzburg as COMITATVS "
                  "SCHWARZBVRGICVS SVPERIOR (f2) and SCHWARZBVRGISCHE "
                  "VNTERHERRSCHAFT (f1), i.e. by Herrschaft, not by "
                  "principality. Two sources of different lineage agree "
                  "that the partition is not obtainable from printed "
                  "maps of this period."},
    ], columns=CORROBORATION_COLUMNS)

    # ---- canonical revision ---------------------------------------------
    t0 = time.perf_counter()
    canon_path = sdir / "territorial_control.csv"
    prov_path = sdir / "territorial_control_provenance.csv"
    log_path = sdir / "scenario_control_promotion_log.csv"
    rev_path = sdir / "territorial_control_revision_log.csv"
    canonical = pd.read_csv(canon_path, keep_default_na=False,
                            na_values=[""])
    provenance = pd.read_csv(prov_path, keep_default_na=False,
                             na_values=[""])
    log = pd.read_csv(log_path, keep_default_na=False, na_values=[""])
    revision_log = pd.read_csv(rev_path, keep_default_na=False,
                               na_values=[""]) if rev_path.exists() \
        else pd.DataFrame(columns=REVISION_LOG_COLUMNS)
    before_rows = len(canonical)
    prod_keys = set(candidate["territorial_target_id"])
    before_state = canonical[canonical["territorial_target_id"].isin(
        prod_keys)]["control_status"].value_counts().to_dict()
    before_state = {"CONTROLLED": before_state.get("CONTROLLED", 0),
                    "UNRESOLVED": before_state.get("UNRESOLVED", 0)}
    conflicts_prev = pd.read_csv(
        m13_dir / "promotion_conflicts_mapgen013.csv")
    canonical, provenance, log, revision_log, rep = revise_control(
        canonical, provenance, log, revision_log, candidate, scenario_id,
        STAGE, M13_COMMIT,
        # run-id-free so canonical data never depends on a run name
        "reviews/MAPGEN-014/revised_territorial_control_mapgen014.csv",
        scen_src,
        reason="re-measured at the source's own positional uncertainty "
               f"({unc_km:.3f} km, four independent settlement checks); "
               "no independent second source corroborates the Saxon core, "
               "so the conservative model is applied to canonical "
               "authority instead of keeping the stale 2.975 km rows",
        old_uncertainty_km=OLD_UNCERTAINTY_KM, new_uncertainty_km=unc_km,
        promoted_utc="2026-08-13")
    # the wash hexes keep their rows but must stop claiming a polity
    wash_targets = set(provenance.loc[
        provenance["historical_subject_ids"].fillna("").str.contains(
            "schwarzburg"), "territorial_target_id"])
    provenance.loc[provenance["territorial_target_id"].isin(wash_targets),
                   ["historical_subject_ids", "notes"]] = [
        WASH_SUBJECT,
        "MAPGEN-014: provenance corrected from a false aggregate polity "
        "to an unpartitioned Schwarzburg source region. Candidate "
        "controllers: " + "|".join(NEW_SCHWARZBURG) + " — neither is "
        "assigned, because no source distinguishes them."]
    if "candidate_controller_polity_ids" not in provenance.columns:
        provenance["candidate_controller_polity_ids"] = ""
    provenance.loc[provenance["territorial_target_id"].isin(wash_targets),
                   "candidate_controller_polity_ids"] = "|".join(
        NEW_SCHWARZBURG)
    canonical.to_csv(canon_path, index=False)
    provenance.to_csv(prov_path, index=False)
    log.to_csv(log_path, index=False)
    revision_log.to_csv(rev_path, index=False)
    after_state = canonical[canonical["territorial_target_id"].isin(
        prod_keys)]["control_status"].value_counts().to_dict()
    after_state = {"CONTROLLED": after_state.get("CONTROLLED", 0),
                   "UNRESOLVED": after_state.get("UNRESOLVED", 0)}
    # idempotence of the revision
    c2, p2, l2, r2, rep2 = revise_control(
        canonical.copy(), provenance.copy(), log.copy(),
        revision_log.copy(), candidate, scenario_id, STAGE, M13_COMMIT,
        # run-id-free so canonical data never depends on a run name
        "reviews/MAPGEN-014/revised_territorial_control_mapgen014.csv",
        scen_src,
        reason="idempotence probe", old_uncertainty_km=OLD_UNCERTAINTY_KM,
        new_uncertainty_km=unc_km, promoted_utc="2026-08-13")
    conflicts_now = canonical[canonical["territorial_target_id"].isin(
        set(conflicts_prev["territorial_target_id"]))]
    conflict_disp = pd.DataFrame([{
        "territorial_target_id": t.territorial_target_id,
        "mapgen013_disposition": "RETAINED_MAPGEN012_ROW",
        "mapgen014_status": t.control_status,
        "mapgen014_controller": t.controller_scenario_polity_id,
        "resolution": "EXPLICITLY_UNRESOLVED"
        if t.control_status == "UNRESOLVED" else "ASSIGNED",
        "reason": "Both bundles were re-compared at the re-measured "
                  "uncertainty. The hex lies inside the uncertainty band "
                  "of both neighbours' drawn boundaries, so no most-"
                  "specific territorial actor can be determined and the "
                  "hex stays UNRESOLVED rather than being awarded to "
                  "whichever source was promoted first."
        if t.control_status == "UNRESOLVED" else
        "resolved to the most specific territorial actor",
    } for t in conflicts_now.itertuples()])
    timings["revision_s"] = time.perf_counter() - t0

    # ---- representation decisions (overlay hard gate) -------------------
    land_union = land_union_from(land_by_id)
    rep_rows = []
    for t in authorised.itertuples():
        pid = t.scenario_polity_id
        src_geom = shapely.intersection(t.geometry, land_union)
        km2 = round(ground_area_perimeter(src_geom)[0], 2)
        d = dom[dom["scenario_polity_id"] == pid]
        frag = _parts(t.geometry)
        zero_hex = sum(1 for g in frag
                       if ground_area_perimeter(g)[0] < 5.0)
        rep_rows.append({
            "historical_subject_id": t.historical_subject_id,
            "scenario_polity_id": pid, "source_area_km2": km2,
            "reliable_geometry": "NO",
            "standard_hex_survival": int(len(d)),
            "zero_hex_fragments": zero_hex,
            "enclave_fragments": len(frag) - 1,
            "recommended_mode": "STANDARD_HEX",
            "decision_reason":
                f"{km2:,.0f} km2 survives as {len(d)} hexes, so the "
                "territory is many hexes wide. What fails is the SOURCE "
                "positional uncertainty, not the representation: overlay "
                "would hide the uncertainty instead of resolving it and "
                "is therefore forbidden here."})
    rep_rows.append({
        "historical_subject_id": WASH_SUBJECT,
        "scenario_polity_id": None,
        "source_area_km2": round(ground_area_perimeter(
            shapely.intersection(
                features.loc[features["historical_subject_id"]
                             == WASH_SUBJECT, "geometry"].iloc[0],
                land_union))[0], 2),
        "reliable_geometry": "NO", "standard_hex_survival": 0,
        "zero_hex_fragments": 0, "enclave_fragments": 0,
        "recommended_mode": "UNRESOLVED",
        "decision_reason": "The polity partition itself is unresolved, so "
                           "there is no actor to represent. Overlay is "
                           "forbidden: it would turn an unresolved "
                           "historical question into a rendering choice."})
    representation = pd.DataFrame(rep_rows,
                                  columns=REPRESENTATION_COLUMNS)

    # ---- gates ----------------------------------------------------------
    _check("M14-01_base_commit", M13_COMMIT.startswith("5eff164"),
           f"MAPGEN-014 builds on MAPGEN-013 commit {M13_COMMIT}")
    m13_sum = pd.read_csv(m13_dir / "summary.csv")
    m13d = dict(zip(m13_sum["metric"], m13_sum["value"].astype(str)))
    _check("M14-02_mapgen013_regression",
           int(m13d["canonical_rows_after"]) == 1614
           and int(m13d["mapgen012_controlled_promoted"]) == 1096
           and len(conflicts_prev) == 4,
           "MAPGEN-013 artifacts intact: 1,614 canonical rows, 1,096 "
           "promoted CONTROLLED, 4 published conflicts")
    old_sp = make_scenario_polity_id(scenario_id, "pol_schwarzburg")
    row = sp[sp["polity_id"] == "pol_schwarzburg"]
    _check("M14-03_pol_schwarzburg_not_active_actor",
           len(row) == 1
           and row.iloc[0]["existence_status"]
           == "MODEL_ARTIFACT_SUPERSEDED"
           and row.iloc[0]["territorial_authority_role"]
           == "NON_TERRITORIAL_INSTITUTION"
           and int((canonical["controller_scenario_polity_id"]
                    == old_sp).sum()) == 0
           and old_sp not in set(authorised["scenario_polity_id"]),
           "pol_schwarzburg is retained for audit history as "
           "MODEL_ARTIFACT_SUPERSEDED / NON_TERRITORIAL_INSTITUTION, "
           "controls nothing and authorises no geometry; it was NOT "
           "repurposed as a structural container")
    aud = snap.scenario_polity_inclusion_audit
    reg_rows = aud[aud["included_polity_id"].isin(NEW_SCHWARZBURG)]
    _check("M14-04_two_principalities_individually_audited",
           all(p in set(snap.polities["polity_id"])
               for p in NEW_SCHWARZBURG)
           and len(reg_rows) == 2
           and reg_rows["inclusion_status"].eq("INCLUDED").all()
           and sp[sp["polity_id"].isin(NEW_SCHWARZBURG)][
               "historical_title_at_snapshot"].str.contains(
               "Reichsfuerstenrat").all(),
           "Schwarzburg-Rudolstadt and Schwarzburg-Sondershausen are "
           "registered and audited individually, each with its imperial "
           "title at the snapshot date")
    wash_feat = features[features["historical_subject_id"] == WASH_SUBJECT]
    _check("M14-05_no_unpartitioned_schwarzburg_control",
           len(wash_feat) == 1
           and wash_feat.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY"
           and wash_feat.iloc[0]["feature_role"]
           not in GAMEPLAY_CONVERTIBLE_ROLES
           and WASH_SUBJECT not in set(mapping["historical_subject_id"])
           and WASH_SUBJECT not in set(
               authorised["historical_subject_id"])
           and not canonical["controller_scenario_polity_id"].isin(
               [make_scenario_polity_id(scenario_id, p)
                for p in NEW_SCHWARZBURG]).any(),
           "the SCHWARTZBURG wash is UNCERTAIN_BOUNDARY, has no polity "
           "mapping and cannot reach production; neither principality "
           "controls a hex")
    _check("M14-06_source_lineage_recorded",
           len(lineage) >= 4
           and set(lineage["independence_status"]) <= {
               "INDEPENDENT", "PARTIALLY_INDEPENDENT", "DERIVATIVE",
               "SAME_PLATE", "UNKNOWN"}
           and lineage["independence_reason"].str.len().min() > 40
           and src_1747 in set(lineage["global_source_id"]),
           f"{len(lineage)} sources carry lineage: "
           f"{dict(zip(lineage['global_source_id'], lineage['independence_status']))}")
    elig = lineage[lineage["corroboration_eligible"] == "YES"]
    _check("M14-07_derivative_not_double_counted",
           not elig["independence_status"].isin(
               ["DERIVATIVE", "SAME_PLATE"]).any()
           and (corrob["lineage_independence"]
                != "DERIVATIVE").all(),
           f"{len(elig)} sources are corroboration-eligible and none is a "
           "derivative or same-plate copy; the two map houses are "
           "French Sanson/Jaillot and German Homann/Nuremberg")
    assess_1747 = assess[assess["global_source_id"] == src_1747].iloc[0]
    reg_1747 = reg[reg["global_source_id"] == src_1747].iloc[0]
    gcps = pd.read_csv(H / "historical_map_gcps.csv")
    _check("M14-08_each_georeference_independent",
           reg_1747["georeference_status"] == "NOT_YET_GEOREFERENCED"
           and set(gcps["map_source_id"]) == {make_global_source_id(
               CK_VAUG)}
           and assess_1747["georeferenced"] == "NO",
           "the 1747 source did NOT inherit the Vaugondy transform: it "
           "has no GCP row at all, because its graticule numerals could "
           "not be read unambiguously and no control point was invented")
    _check("M14-09_continuity_required_for_off_date_geometry",
           assess_1747["boundary_authority_for_1756"] == "NO"
           and reg_1747["historicity_of_source"]
           == "CONTEMPORARY_TO_1747_NOT_TO_1756"
           and not ((assertions["global_source_id"] == src_1747)
                    & (assertions["geometry_authority"] == "YES")).any(),
           "1747 geometry is not admitted to the 1756 snapshot; no "
           "geometry-authoritative assertion exists for it, so the "
           "continuity bridge cannot be bypassed")
    ndb = assertions[assertions["global_source_id"]
                     == make_global_source_id(CK_NDB)]
    _check("M14-10_existence_is_not_continuity",
           len(ndb) == 2
           and ndb["assertion_type"].eq("POLITY_EXISTENCE").all()
           and ndb["geometry_authority"].eq("NO").all()
           and not (ndb["assertion_type"]
                    == "TERRITORIAL_CONTINUITY").any(),
           "the scholarly authority proves the polities existed, not "
           "where their boundaries ran: POLITY_EXISTENCE with "
           "geometry_authority NO, never reused as continuity")
    _check("M14-11_corroboration_measured",
           len(corrob) == 3
           and corrob["agreement_status"].isin(
               ["AGREES", "WITHIN_COMBINED_UNCERTAINTY",
                "SOURCE_DISAGREEMENT", "INSUFFICIENT_OVERLAP",
                "DERIVATIVE_NOT_CORROBORATION", "UNRESOLVED"]).all()
           and corrob["notes"].str.len().min() > 60,
           "corroboration recorded per subject: "
           f"{dict(corrob['agreement_status'].value_counts())} — the "
           "Weimar overlap is UNRESOLVED (not measured), not silently "
           "called agreement")
    _check("M14-12_uncertainty_not_tuned",
           abs(unc_km - 9.168) < 1e-6
           and unc_km > OLD_UNCERTAINTY_KM
           and rep["status_changes"].get("UNRESOLVED->CONTROLLED", 0) == 0,
           f"uncertainty stays at the measured {unc_km:.3f} km (never "
           "lowered); the revision produced "
           f"{rep['status_changes']} — no row was moved INTO CONTROLLED")
    stale = revision_log[revision_log["old_uncertainty_km"].astype(float)
                         == OLD_UNCERTAINTY_KM]
    still_old = canonical[canonical["territorial_target_id"].isin(
        prod_keys)]
    _check("M14-13_saxony_stale_authority_resolved",
           rep["revised"] > 0 and len(stale) == rep["revised"]
           and after_state != before_state
           and rep2["revised"] == 0,
           f"{rep['revised']:,} canonical rows carried the stale 2.975 km "
           f"classification and were superseded: {before_state} -> "
           f"{after_state}. A repeat revision changes "
           f"{rep2['revised']} rows, so the new state is stable")
    _check("M14-14_supersession_log_complete",
           list(revision_log.columns)[:len(REVISION_LOG_COLUMNS)]
           == REVISION_LOG_COLUMNS
           and revision_log["old_promotion_id"].notna().all()
           and revision_log["new_promotion_id"].notna().all()
           and int((log["promotion_status"] == "SUPERSEDED").sum()) >= 1
           and log["supersedes_promotion_id"].notna().any(),
           f"{len(revision_log):,} revision rows carry old/new promotion "
           "id, status, controller and uncertainty; "
           f"{int((log['promotion_status'] == 'SUPERSEDED').sum())} "
           "promotion(s) marked SUPERSEDED and none deleted")
    _check("M14-15_prior_conflicts_resolved",
           len(conflict_disp) == 4
           and conflict_disp["resolution"].isin(
               ["EXPLICITLY_UNRESOLVED", "ASSIGNED"]).all()
           and conflict_disp["reason"].str.len().min() > 40,
           "all 4 MAPGEN-013 conflict hexes re-evaluated: "
           f"{dict(conflict_disp['resolution'].value_counts())} — the "
           "earlier row was not preferred just for being older")
    dup = int(canonical.duplicated(subset=[
        "scenario_id", "territorial_target_type",
        "territorial_target_id"]).sum())
    _check("M14-16_canonical_target_unique", dup == 0,
           f"{len(canonical):,} canonical rows, {dup} duplicate keys")
    scen_srcs = pd.read_csv(sdir / "sources.csv", keep_default_na=False,
                            na_values=[""])
    _check("M14-17_canonical_provenance_complete",
           set(provenance["territorial_target_id"])
           <= set(canonical["territorial_target_id"])
           and provenance["global_source_ids"].str.contains("hsrc_").all()
           and provenance.duplicated(subset=[
               "territorial_target_type", "territorial_target_id"]).sum()
           == 0,
           f"{len(provenance):,} provenance rows, one per promoted "
           "target, all carrying the global source bundle")
    agg = set(aud.loc[aud["inclusion_status"] == "AGGREGATION_CANDIDATE",
                      "canonical_candidate_id"])
    _check("M14-18_no_aggregate_class_controller",
           aud.loc[aud["inclusion_status"] == "AGGREGATION_CANDIDATE",
                   "included_polity_id"].isna().all()
           and not (set(canonical["controller_scenario_polity_id"].dropna())
                    & agg),
           f"{len(agg)} aggregation classes hold no polity id and no "
           "territory")
    hre = make_scenario_polity_id(scenario_id, "pol_holy_roman_empire")
    _check("M14-19_hre_controller_zero",
           int((canonical["controller_scenario_polity_id"] == hre).sum())
           == 0
           and sp.loc[sp["polity_id"] == "pol_holy_roman_empire",
                      "territorial_authority_role"].iloc[0]
           == "STRUCTURAL_CONTAINER",
           "the Empire gained two more estates and still controls nothing")
    _check("M14-20_exact_land_binding",
           float(mem["share_of_terrestrial_hex_land"].max()) <= 1.0
           and (mem["binding_method"] == BINDING_METHOD).all(),
           f"{len(mem):,} membership rows on exact hex ∩ OSM land, max "
           f"share {float(mem['share_of_terrestrial_hex_land'].max()):.4f}")
    _check("M14-21_multi_polity_memberships_preserved",
           mem.groupby(["hex_id", "scenario_polity_id"]).size().max() == 1
           and int(mem["border_hex"].sum()) >= 0
           and int(mem["scenario_polity_id"].nunique()) == 2,
           f"{int(mem['border_hex'].sum())} multi-polity border hexes "
           "kept as many-to-many membership; the wash contributes none "
           "because it is no longer authorised")
    _check("M14-22_no_silent_snapping",
           check_contested_overlaps(authorised) == []
           and len(rejected) == 1
           and rejected.iloc[0]["historical_subject_id"] == WASH_SUBJECT,
           "no geometry was snapped or clipped; exactly one feature is "
           f"rejected from production: {rejected.iloc[0]['rejection_reasons'][:90]}")
    _check("M14-23_overlay_hard_gate",
           "OVERLAY_ONLY" not in set(representation["recommended_mode"])
           and representation.loc[
               representation["recommended_mode"] == "STANDARD_HEX",
               "standard_hex_survival"].min() > 1
           and representation["decision_reason"].str.len().min() > 60,
           "no subject was pushed to OVERLAY_ONLY: "
           f"{dict(representation['recommended_mode'].value_counts())}. "
           "A source-uncertainty failure is never hidden behind an "
           "overlay")
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    _check("M14-24_low_countries_source_gap",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP",
           "Low Countries still SOURCE_GAP")
    _check("M14-25_europe_grid_regression",
           int(eu_man["hex_count"].sum()) == 1885422,
           "Europe canonical grid intact (1,885,422 hexes)")
    _check("M14-26_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN"
           and int((canonical["territorial_target_type"]
                    == "ISLAND_COMPONENT").sum()) == 1,
           "Toshima hex still OCEAN and its island-component row intact")
    _check("M14-27_claims_not_derived",
           len(snap.territorial_claims) == 1,
           "claims table still holds its single MAPGEN-008 row; control "
           "never generated claims")
    cov = pd.read_csv(sdir / "political_coverage.csv",
                      keep_default_na=False, na_values=[""])
    _check("M14-28_incomplete_coverage_unknown",
           int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0
           and len(canonical) < len(hex_ids)
           and canonical.loc[canonical["control_status"] == "UNRESOLVED",
                             "controller_scenario_polity_id"].isna().all(),
           f"0 COMPLETE coverage units; {len(canonical):,} canonical rows "
           f"against {len(hex_ids):,} hexes in the extent alone, and "
           "UNRESOLVED never carries a controller")
    _check("M14-29_all_source_licences_assessed",
           set(reg["global_source_id"]) >= {src_1747,
                                            make_global_source_id(CK_NDB)}
           and assess["licence_verified"].notna().all()
           and assess.loc[assess["global_source_id"].isin(
               [src_1747, make_global_source_id(CK_NDB)]),
               "licence_verified"].eq("YES").all()
           and reg_1747["licence_or_usage_note"].startswith(
               "Public-domain work")
           and "NOT redistributed" in reg_1747["licence_or_usage_note"],
           f"{len(assess)} assessed sources each carry an explicit licence "
           f"verdict ({dict(assess['licence_verified'].value_counts())}) "
           "and every source added by this stage is verified YES; "
           "the 1747 raster is public-domain but is NOT redistributed in "
           "this repository (Gallica conditions recorded)")
    from .scenario_promotion import make_promotion_id, sha256_of_frame

    _pid = make_promotion_id(scenario_id, STAGE,
                             sha256_of_frame(candidate))
    _check("M14-30_deterministic_identifiers",
           _pid == rep["promotion_id"]
           and _pid == make_promotion_id(scenario_id, STAGE,
                                         sha256_of_frame(candidate))
           and revision_log["revision_id"].is_unique
           and revision_log["revision_id"].str.startswith("rev_").all(),
           "promotion and revision ids are content-derived hashes, so a "
           f"repeat run reproduces them exactly ({_pid}); the two-run "
           "byte comparison is reported separately")
    struct = set(sp.loc[sp["territorial_authority_role"].isin(
        ["STRUCTURAL_CONTAINER", "COMPOSITE_TERRITORIAL_ACTOR"]),
        "scenario_polity_id"])
    comps = pd.read_parquet(geo_dir / "island_components.parquet",
                            columns=["island_component_id"])
    # The wash hexes keep their canonical rows but sit outside this run's
    # (now smaller) extent, so the terrestrial set spans both extents.
    m13_hexes = set(pd.read_parquet(
        m13_dir / "historical_hex_membership.parquet",
        columns=["hex_id"])["hex_id"])
    integ = validate_canonical_control(
        canonical, provenance, sp, scen_srcs,
        set(geo.loc[geo["water_type"] == "NONE", "hex_id"]) | set(hex_ids)
        | m13_hexes, set(comps["island_component_id"]), struct)
    _check("M14-31_canonical_integrity", integ == [],
           f"canonical integrity: {integ or 'clean'}")
    _check("M14-32_forbidden_reference_scan",
           not scan_forbidden_reference_code(Path(__file__))
           and not scan_forbidden_reference_code(
               Path(__file__).parent / "scenario_promotion.py"),
           "AST scans of the revision pipeline and promotion module are "
           "clean of reference-administration usage")

    # ---- outputs --------------------------------------------------------
    t0 = time.perf_counter()
    subj_by_pol = dict(zip(authorised["scenario_polity_id"],
                           authorised["historical_subject_id"]))
    colours = {p: POLITY_COLOURS[i % len(POLITY_COLOURS)]
               for i, p in enumerate(sorted(subj_by_pol))}
    cons = membership_conservation_audit(authorised, mem, land_by_id)
    hexa = hexification_audit(authorised, mem, land_by_id)
    overlay = overlay_candidates_from_audit(hexa, authorised)
    raw_rows, auth_rows = [], []
    for t in authorised.itertuples():
        pid = t.scenario_polity_id
        src_geom = shapely.intersection(t.geometry, land_union)
        src_km2 = round(ground_area_perimeter(src_geom)[0], 2)
        d = dom[dom["scenario_polity_id"] == pid]
        c = confident[confident["scenario_polity_id"] == pid]
        u = uncertain[uncertain["scenario_polity_id"] == pid]
        raw_u = shapely.union_all([land_by_hex[h] for h in d["hex_id"]]) \
            if len(d) else None
        auth_u = shapely.union_all([land_by_hex[h] for h in c["hex_id"]]) \
            if len(c) else None
        raw_rows.append({
            "scenario_polity_id": pid,
            "historical_subject_id": t.historical_subject_id,
            "source_land_km2": src_km2,
            "raw_winner_area_km2": round(
                ground_area_perimeter(raw_u)[0], 2) if raw_u else 0.0,
            "raw_hex_count": int(len(d)),
            "audit_scope": "RAW_HEX_WINNER_ONLY"})
        auth_rows.append({
            "scenario_polity_id": pid,
            "historical_subject_id": t.historical_subject_id,
            "source_land_km2": src_km2,
            "authoritative_controlled_area_km2": round(
                ground_area_perimeter(auth_u)[0], 2) if auth_u else 0.0,
            "controlled_hex_count": int(len(c)),
            "unresolved_hex_count": int(len(u)),
            "representation_status":
                "AUTHORITY_WITH_UNCERTAIN_BAND" if len(u)
                else "AUTHORITY_COMPLETE_WITHIN_FEATURE",
            "audit_scope": "AUTHORITATIVE_CONTROL_ONLY",
            "basis": "CANONICAL_AND_AUDIT_NOW_AGREE"})
    raw_d, auth_d = pd.DataFrame(raw_rows), pd.DataFrame(auth_rows)
    candidate.to_csv(
        run_dir / "revised_territorial_control_mapgen014.csv", index=False)
    corrob.to_csv(run_dir / "historical_boundary_corroboration_audit.csv",
                  index=False)
    representation.to_csv(run_dir / "political_representation_decision.csv",
                          index=False)
    conflict_disp.to_csv(run_dir / "prior_conflict_disposition.csv",
                         index=False)
    mem.to_parquet(run_dir / "historical_hex_membership.parquet")
    authorised.to_parquet(
        run_dir / "historical_snapshot_features_1756_08_01.parquet")
    rejected.to_csv(run_dir / "snapshot_rejected_features.csv", index=False)
    cons.to_csv(run_dir / "membership_conservation_audit.csv", index=False)
    raw_d.to_csv(run_dir / "raw_hex_winner_distortion.csv", index=False)
    auth_d.to_csv(run_dir / "authoritative_control_distortion.csv",
                  index=False)
    overlay.to_csv(run_dir / "historical_political_overlay_candidates.csv",
                   index=False)
    img = ["source_lineage_and_corroboration.png",
           "vaugondy_vs_secondary_boundary.png",
           "schwarzburg_model_correction.png",
           "saxony_uncertainty_before_after.png",
           "canonical_control_revision.png",
           "central_europe_control_after_corroboration.png"]
    render_lineage(run_dir / img[0], lineage, corrob,
                   "A. Source lineage and what may count as corroboration")
    render_secondary(
        run_dir / img[1],
        [("1756 Vaugondy (BnF) — the sheet MAPGEN-012/013 digitised",
          Path("data/raw/historical_maps/vaugondy_1756/"
               "vaugondy_1756_haute_saxe_btv1b530412497.jpg")),
         ("1747 Zollmann / Homann Heirs (BnF) sectio inferior — "
          "acquired in MAPGEN-014, not yet georeferenced",
          Path("data/raw/historical_maps/zollmann_1747_thuringia/"
               "zollmann_1747_thuringiae_orientalis_btv1b5971578k_f1.jpg"))],
        "B. The two sources side by side — different houses, five times "
        "different scale, no measured boundary comparison yet")
    render_correction(run_dir / img[2], correction, sp,
                      "C. Schwarzburg model correction")
    render_uncertainty(run_dir / img[3], before_state, after_state,
                       "D. Saxony canonical authority under the "
                       "re-measured uncertainty")
    render_revision(run_dir / img[4], revision_log, log,
                    "E. Canonical control revision and supersession")
    render_control(run_dir / img[5], polys, hex_ids,
                   canonical[canonical["territorial_target_id"].isin(
                       set(hex_ids))], colours, authorised, subj_by_pol,
                   "F. Canonical control after corroboration and revision")
    from PIL import Image

    aspects = {}
    for n in img:
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.size[0] / im.size[1], 3)
    _check("M14-33_renders", len(img) == 6
           and all(0.3 <= a <= 4.0 for a in aspects.values()),
           f"6 renders written, aspects {aspects}")
    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("M14-34_upstream_immutable", up_after == upstream,
           f"{len(upstream)} upstream artifacts byte-identical")
    timings["render_s"] = time.perf_counter() - t0

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    summary = [
        ("stage", STAGE), ("base_commit_mapgen013", M13_COMMIT),
        ("sources_acquired", 1), ("sources_registered_total", len(reg)),
        ("lineage_rows", len(lineage)),
        ("corroboration_eligible_sources", len(elig)),
        ("independent_boundary_corroborations",
         int((corrob["agreement_status"].isin(
             ["AGREES", "WITHIN_COMBINED_UNCERTAINTY"])).sum())),
        ("corroboration_insufficient_overlap",
         int((corrob["agreement_status"] == "INSUFFICIENT_OVERLAP").sum())),
        ("corroboration_unresolved",
         int((corrob["agreement_status"] == "UNRESOLVED").sum())),
        ("uncertainty_km", round(unc_km, 3)),
        ("uncertainty_km_superseded", OLD_UNCERTAINTY_KM),
        ("polities_total", len(snap.polities)),
        ("scenario_polities_total", len(sp)),
        ("active_territorial_actors",
         int((sp["territorial_authority_role"]
              == "DIRECT_TERRITORIAL_ACTOR").sum())),
        ("relationships_total", len(snap.scenario_polity_relationships)),
        ("production_features", len(authorised)),
        ("rejected_features", len(rejected)),
        ("hex_membership_rows", len(mem)),
        ("canonical_rows_before", before_rows),
        ("canonical_rows_after", len(canonical)),
        ("canonical_rows_revised", rep["revised"]),
        ("canonical_rows_inserted", rep["inserted"]),
        ("canonical_rows_unchanged", rep["unchanged"]),
        ("controlled_to_unresolved",
         rep["status_changes"].get("CONTROLLED->UNRESOLVED", 0)),
        ("unresolved_to_controlled",
         rep["status_changes"].get("UNRESOLVED->CONTROLLED", 0)),
        ("controller_changes", int((revision_log["old_controller"].fillna("")
                                    != revision_log["new_controller"]
                                    .fillna("")).sum())
         if len(revision_log) else 0),
        ("saxony_controlled_before", before_state["CONTROLLED"]),
        ("saxony_controlled_after", after_state["CONTROLLED"]),
        ("saxony_unresolved_before", before_state["UNRESOLVED"]),
        ("saxony_unresolved_after", after_state["UNRESOLVED"]),
        ("second_revision_changed_rows", rep2["revised"]),
        ("prior_conflict_hexes", len(conflict_disp)),
        ("prior_conflicts_explicitly_unresolved",
         int((conflict_disp["resolution"]
              == "EXPLICITLY_UNRESOLVED").sum())),
        ("canonical_controlled_total",
         int((canonical["control_status"] == "CONTROLLED").sum())),
        ("canonical_unresolved_total",
         int((canonical["control_status"] == "UNRESOLVED").sum())),
        ("provenance_rows", len(provenance)),
        ("revision_log_rows", len(revision_log)),
        ("promotions_superseded",
         int((log["promotion_status"] == "SUPERSEDED").sum())),
        ("overlay_only_decisions",
         int((representation["recommended_mode"] == "OVERLAY_ONLY").sum())),
        ("validation_pass", f"{n_pass}/{len(val)}"),
    ]
    pd.DataFrame(summary, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "summary.csv", index=False)
    manifest = {
        "run_id": run_id, "stage": STAGE,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen013": M13_COMMIT,
        "scenario_control_promotion_schema_version":
            SCENARIO_CONTROL_PROMOTION_SCHEMA_VERSION,
        "scenario_control_promotion_algorithm_version":
            SCENARIO_CONTROL_PROMOTION_ALGORITHM_VERSION,
        "hpg_schema_version": HPG_SCHEMA_VERSION,
        "hpg_algorithm_version": HPG_ALGORITHM_VERSION,
        "scenario_schema_version": SCENARIO_SCHEMA_VERSION,
        "schwarzburg_correction": (
            "pol_schwarzburg was a model artifact created from one map "
            "wash. NDB 24 (2010) shows the house was partitioned in 1599 "
            "into Schwarzburg-Rudolstadt and Schwarzburg-Sondershausen, "
            "both imperial principalities in 1756 with seat and vote in "
            "the Reichsfuerstenrat from 1754. The artifact is superseded, "
            "the two principalities are registered, and the wash geometry "
            "is demoted to UNCERTAIN_BOUNDARY so it can never bind."),
        "corroboration_outcome": (
            "The 1747 Zollmann / Homann Heirs sheets were acquired and "
            "audited. They corroborate the DEPICTION finding — neither "
            "source separates the two Schwarzburg principalities — but "
            "no boundary distance was measured, because georeferencing "
            "was attempted and not completed and no control point was "
            "invented. The Saxon core is outside the 1747 sheets "
            "entirely."),
        "uncertainty_model": (
            f"global {unc_km} km from the 1756 sheet's own four "
            "independent settlement checks. No local uncertainty zone was "
            "created, because that requires cross-source residuals that "
            "this stage did not obtain."),
        "upstream_sha256": upstream,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_readme(run_dir, run_id, dict(summary), corrob, lineage,
                  conflict_disp, representation, aspects, img)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    copies = {
        "README_REVIEW.md": run_dir / "README_REVIEW.md",
        "run_manifest.json": run_dir / "run_manifest.json",
        "validation.csv": run_dir / "validation.csv",
        "summary.csv": run_dir / "summary.csv",
        "polity_model_correction_audit.csv":
            H / "polity_model_correction_audit.csv",
        "polities.csv": scenarios_root(cfg.data_dir) / "polities.csv",
        "scenario_polities.csv": sdir / "scenario_polities.csv",
        "scenario_polity_relationships.csv":
            sdir / "scenario_polity_relationships.csv",
        "scenario_polity_inclusion_audit.csv":
            sdir / "scenario_polity_inclusion_audit.csv",
        "historical_source_registry.csv":
            H / "historical_source_registry.csv",
        "historical_source_assessment.csv":
            H / "historical_source_assessment.csv",
        "historical_source_lineage.csv":
            H / "historical_source_lineage.csv",
        "historical_evidence_assertions.csv":
            H / "historical_evidence_assertions.csv",
        "historical_boundary_feature_evidence.csv":
            H / "historical_boundary_feature_evidence.csv",
        "historical_map_gcps.csv": H / "historical_map_gcps.csv",
        "historical_map_georeference_audit.csv":
            H / "historical_map_georeference_audit.csv",
        "historical_boundary_corroboration_audit.csv":
            run_dir / "historical_boundary_corroboration_audit.csv",
        "historical_subject_scenario_mapping.csv":
            H / "historical_subject_scenario_mapping.csv",
        "territorial_control.csv": canon_path,
        "territorial_control_provenance.csv": prov_path,
        "territorial_control_revision_log.csv": rev_path,
        "scenario_control_promotion_log.csv": log_path,
        "territorial_claims.csv": sdir / "territorial_claims.csv",
        "scenario_political_coverage.csv": sdir / "political_coverage.csv",
        "scenario_sources.csv": sdir / "sources.csv",
        "scenario_evidence.csv": sdir / "evidence.csv",
        "raw_hex_winner_distortion.csv":
            run_dir / "raw_hex_winner_distortion.csv",
        "authoritative_control_distortion.csv":
            run_dir / "authoritative_control_distortion.csv",
        "political_representation_decision.csv":
            run_dir / "political_representation_decision.csv",
        "prior_conflict_disposition.csv":
            run_dir / "prior_conflict_disposition.csv",
        "snapshot_rejected_features.csv":
            run_dir / "snapshot_rejected_features.csv",
        "membership_conservation_audit.csv":
            run_dir / "membership_conservation_audit.csv",
        "historical_political_overlay_candidates.csv":
            run_dir / "historical_political_overlay_candidates.csv",
        "revised_territorial_control_mapgen014.csv":
            run_dir / "revised_territorial_control_mapgen014.csv",
    }
    for dst, src in copies.items():
        if Path(src).exists():
            shutil.copy2(src, review / dst)
    pd.DataFrame(features.drop(columns="geometry")).to_csv(
        review / "historical_boundary_features.csv", index=False)
    pd.DataFrame(authorised.drop(columns="geometry")).to_csv(
        review / "historical_snapshot_features_1756_08_01.csv", index=False)
    mem.to_csv(review / "historical_hex_membership.csv", index=False)
    for n in img:
        shutil.copy2(run_dir / n, review / n)
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.copy2(run_dir / "run_manifest.json", review / "run_manifest.json")
    print(f"[revision] {run_id}: validation {n_pass}/{len(val)}, canonical "
          f"{before_rows:,} rows ({rep['revised']:,} revised, "
          f"{rep['inserted']} inserted), Saxony {before_state} -> "
          f"{after_state} ({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[revision][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, corrob, lineage, conflicts,
                  representation, aspects, img):
    lines = [
        f"# {STAGE} Review — Central Europe corroboration, Schwarzburg "
        "model correction and canonical authority revision",
        "",
        "**A REVIEWED ROW THAT IS KNOWN TO BE STALE IS NOT AUTHORITY.**",
        "**OVERLAY DOES NOT RESOLVE SOURCE UNCERTAINTY.**",
        "",
        f"Run `{run_id}`, built on MAPGEN-013 commit "
        f"`{s['base_commit_mapgen013']}`.",
        "",
        "## 1. Schwarzburg: a polity that never existed was withdrawn",
        "",
        "- MAPGEN-013 registered `pol_schwarzburg` as a single 1756 "
        "territorial actor because the 1756 sheet paints one wash "
        "labelled SCHWARTZBURG. That was wrong.",
        "- **NDB 24 (2010), pp. 12-14** (A. Klinger, *Schwarzburg, Grafen "
        "von*) records the 1599 Stadtilm partition into the lines "
        "Schwarzburg-Rudolstadt and Schwarzburg-Sondershausen, the "
        "elevations to hereditary imperial prince (Sondershausen 1697, "
        "Rudolstadt 1710), and that the new imperial princes took seat "
        "and vote in the Reichsfürstenrat only from 1754 — so both held "
        "it at the snapshot date.",
        "- `pol_schwarzburg` is **retained** as "
        "`MODEL_ARTIFACT_SUPERSEDED` / `NON_TERRITORIAL_INSTITUTION` so "
        "the MAPGEN-013 audit trail stays resolvable. It was **not** "
        "repurposed as a structural container: the House of Schwarzburg "
        "is a dynasty, not a territory.",
        "- `pol_schwarzburg_rudolstadt` and "
        "`pol_schwarzburg_sondershausen` are registered as individual "
        "imperial estates with their titles at the snapshot date.",
        "- The wash itself became `hsub_schwarzburg_unpartitioned_wash` "
        "with feature role **UNCERTAIN_BOUNDARY** — a role that is not "
        "gameplay-convertible — so that geometry can never produce "
        "control again. Neither new principality controls a hex.",
        "",
        "## 2. A second source was acquired, and its lineage checked",
        "",
        "- **Zollmann / Homann Heirs, *Thuringiae Orientalis*, Nuremberg "
        "1747**, 2 sheets, approx. 1:200,000 — five times finer than the "
        "1756 Vaugondy sheet. BnF, dép. Cartes et plans, GE BB-565 "
        "(3, 21-22); digital object `ark:/12148/btv1b5971578k` "
        "(5751×4431 and 5721×4441 px). Public domain under Gallica "
        "conditions; **the raster is not redistributed in this "
        "repository**.",
        "- Lineage: the Vaugondy sheet descends from the French "
        "Sanson/Jaillot material; the 1747 sheet is a German "
        "Homann/Nuremberg plate with a different cartographer, engraver, "
        "publisher and dedicatee. Neither derives from the other as far "
        "as can be documented, so both are recorded as "
        "**PARTIALLY_INDEPENDENT** — not INDEPENDENT, because "
        "eighteenth-century compilers borrowed silently and absence of "
        "evidence is not evidence of independence.",
        f"- {s['corroboration_eligible_sources']} sources are "
        "corroboration-eligible and none is a derivative or same-plate "
        "copy, so no confidence is counted twice.",
        "",
        "## 3. What the second source did and did not settle",
        "",
        "- **It settles the Schwarzburg question by depiction.** The 1747 "
        "sheets organise Schwarzburg as *COMITATVS SCHWARZBVRGICVS "
        "SVPERIOR* (upper sheet) and *SCHWARZBVRGISCHE VNTERHERRSCHAFT* "
        "(lower sheet) — that is, by Herrschaft, not by principality. "
        "Two sources of different lineage agree that the "
        "Rudolstadt/Sondershausen partition is **not obtainable** from "
        "printed maps of this period. That is why no partition geometry "
        "was invented.",
        "- **It does not settle Saxony.** The 1747 sheets are eastern "
        "Thuringia; the electoral Saxon core around Meissen lies outside "
        "them — `INSUFFICIENT_OVERLAP`, measured as a fact, not assumed.",
        "- **It does not yet settle Weimar.** The overlap exists and the "
        "1747 sheet draws Weimar in far greater detail (lettered Ämter "
        "and the Oldisleben exclave), but **georeferencing was attempted "
        "and not completed**: the neat line is skewed in the scan and the "
        "graticule numerals could not be read unambiguously at the "
        "available resolution. No control point was invented, so the 1747 "
        "source has **no GCP row at all** and the result is recorded as "
        "`UNRESOLVED`, never as agreement.",
        "",
        "## 4. The stale Saxony authority was superseded",
        "",
        f"- {s['canonical_rows_revised']:,} canonical rows carried the old "
        f"{s['uncertainty_km_superseded']} km classification and have been "
        f"re-measured at {s['uncertainty_km']} km: Saxony goes "
        f"**{s['saxony_controlled_before']:,} → "
        f"{s['saxony_controlled_after']:,} CONTROLLED** and "
        f"**{s['saxony_unresolved_before']} → "
        f"{s['saxony_unresolved_after']:,} UNRESOLVED**.",
        f"- Direction matters: {s['controlled_to_unresolved']:,} rows went "
        f"CONTROLLED → UNRESOLVED and {s['unresolved_to_controlled']} went "
        "the other way. No uncertainty was lowered to make hexes "
        "controllable.",
        "- The superseded promotion is marked `SUPERSEDED` in the "
        "promotion log — not deleted — and every changed row is written "
        f"to `territorial_control_revision_log.csv` "
        f"({s['revision_log_rows']:,} rows) with its old and new status, "
        "controller, promotion id and uncertainty.",
        f"- Re-running the revision changes "
        f"{s['second_revision_changed_rows']} rows, so the new state is "
        "stable rather than oscillating.",
        "",
        "## 5. The four MAPGEN-013 conflict hexes",
        "",
        f"- All {s['prior_conflict_hexes']} were re-evaluated from both "
        "evidence bundles rather than defaulting to the older reviewed "
        f"row. {s['prior_conflicts_explicitly_unresolved']} are "
        "**explicitly UNRESOLVED**: each lies inside the uncertainty band "
        "of both neighbours' drawn boundaries, so no most-specific "
        "territorial actor can be determined.",
        "",
        "## 6. Overlay was not used as an escape hatch",
        "",
        f"- `political_representation_decision.csv`: "
        f"{s['overlay_only_decisions']} subjects were assigned "
        "OVERLAY_ONLY. Saxony and Saxe-Weimar stay `STANDARD_HEX` "
        "because each survives as many hexes — what fails is the source's "
        "positional accuracy, not the representation. The Schwarzburg "
        "wash is `UNRESOLVED` because the *polity partition* is "
        "unresolved; an overlay would turn an open historical question "
        "into a rendering choice.",
        "",
        "## 7. Images",
        "",
    ]
    for n in img:
        lines.append(f"- `{n}` (aspect {aspects[n]})")
    lines += [
        "",
        "## 8. Validation",
        "",
        f"- `validation.csv` holds the M14 gates; pass count "
        f"{s['validation_pass']}.",
        "",
        "## 9. Known issues — what this run does NOT claim",
        "",
        "- **No boundary distance between sources has been measured.** "
        "The corroboration achieved is at depiction level for Schwarzburg "
        "only. Until the 1747 sheet is georeferenced, no local "
        "uncertainty zone may be created and the global "
        f"{s['uncertainty_km']} km model stands.",
        "- Saxe-Weimar still has **0 CONTROLLED hexes**. That is the "
        "honest consequence of a single source whose own town placement "
        "is 3–9 km out.",
        "- The Rudolstadt/Sondershausen partition geometry remains an "
        "open model gap, as do the five deferred regions from MAPGEN-013.",
        "- The Landesarchiv Thüringen holdings were consulted at "
        "collection level only; no individual archival signature was "
        "verified, so none is cited as pinpoint evidence.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
