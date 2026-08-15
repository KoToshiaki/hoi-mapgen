"""MAPGEN-020 — two sources, one honest answer about the Brandenburg frontier.

MAPGEN-019 left three things standing: a validated BnF transform, an
acquired but ungeoreferenced BLHA sheet, and six frontiers all marked
CONTINUOUS. This stage takes the last of those apart first, because a
single column had been doing two jobs. "Nothing was ceded" and "the drawn
line may be used as a boundary authority at six kilometres" are different
claims, and only the first had been shown.

Splitting them changes the picture. Political continuity survives on every
frontier. Boundary-position continuity does not: four local cases turn up
in the BLHA catalogue, one of them an explicit Berichtigung der
Landesgrenze with Electoral Saxony worked on 1748-1751 — closing in the
same year as the BnF represented state. A fifth correction is to the
segment list itself: Brandenburg did not border Swedish Pomerania in 1756
at all.

The BLHA sheet is then georeferenced on its own evidence, and it does not
agree with the BnF sheet about where longitude starts. Its graduations sit
about 22.5 degrees west of Greenwich, not on Ferro, which is worth more
than a footnote: two sheets that disagree about their own prime meridian
are not copies of one another.

What this stage does NOT do is digitise either boundary. The attempt is
recorded, with its failure mode, rather than forced.
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
                                 sha256_of_frame, validate_canonical_control)
from .sources import sha256_of

STAGE = "MAPGEN-020"
H = Path("data/historical")
CK_BRAND = "vaugondy_1751_haute_saxe_septentrionale_pomeranie_brandebourg"
M19_COMMIT = "5a6af5790f5f6ecd2b2bb3a345ba5f77104b37c0"
BNF_UNCERTAINTY_KM = 17.228
BLHA_FIELD = (388.0, 345.0, 7075.0, 6085.0)


def _wrap(t, w=92):
    out, line = [], ""
    for word in str(t).split():
        if len(line) + len(word) + 1 > w:
            out.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        out.append(line)
    return out


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def render_blha_points(path, pts, title):
    fig, (ax, ax2) = _fig2((17, 8), [1.2, 1])
    from matplotlib.patches import Rectangle
    ax.add_patch(Rectangle((BLHA_FIELD[0], -BLHA_FIELD[3]),
                           BLHA_FIELD[2] - BLHA_FIELD[0],
                           BLHA_FIELD[3] - BLHA_FIELD[1], fill=False,
                           ec="#2c3e50", lw=1.2))
    cols = {"NW": "#1f618d", "NE": "#b03a2e", "SW": "#196f3d",
            "SE": "#7d3c98", "centre": "#b7950b"}
    for z, g in pts.groupby("zone"):
        ax.scatter(g["pixel_x"], -g["pixel_y"], s=70, c=cols[z],
                   label=f"{z} ({len(g)})", zorder=3)
    for r in pts.itertuples():
        ax.annotate(r.historical_map_label, (r.pixel_x, -r.pixel_y),
                    fontsize=5.6, xytext=(5, 3), textcoords="offset points")
    ax.set_xlim(250, 7250)
    ax.set_ylim(-6250, 200)
    ax.set_aspect("equal")
    ax.legend(fontsize=8, loc="lower left")
    ax.set_title(f"{len(pts)} symbols observed on AKS 1145 A", fontsize=10)
    body = ["INDEPENDENT COLLECTION", ""]
    body += _wrap(
        "The Lotter plate marks Urbes with a solid red-orange fill, not with "
        "the engraved circles the BnF sheet uses. Every point here comes from "
        "a global connected-component scan of that fill over the whole "
        "engraved field of THIS sheet. No BnF transform was used and no BnF "
        "pixel was reused.")
    body += ["", "BY ZONE", ""]
    for z, g in pts.groupby("zone"):
        body.append(f"  {z:7s} {len(g):2d}   "
                    + ", ".join(sorted(g['reference_feature_name'])[:2])
                    + (" ..." if len(g) > 2 else ""))
    body += ["", "SYMBOL TYPES", ""]
    for k, v in pts["symbol_type"].value_counts().items():
        body.append(f"  {k:24s} {v}")
    body += ["", "REJECTED DURING COLLECTION", ""]
    rej = pd.read_csv(H / "brandenburg_blha_rejected_candidates.csv")
    for r in rej.itertuples():
        body.append(f"  {r.candidate}")
        body += ["    " + ln for ln in _wrap(r.reason, 84)]
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_blha_georef(path, audit, blind, cand, title):
    fig, (ax, ax2) = _fig2((16, 7), [1, 1.2])
    x = np.arange(len(audit))
    ax.bar(x - 0.2, audit["fit_rms_m"] / 1000, 0.4, label="fit RMS",
           color="#aab7b8")
    ax.bar(x + 0.2, audit["hold_rms_m"] / 1000, 0.4, label="holdout RMS",
           color="#1f618d")
    ax.set_xticks(x)
    ax.set_xticklabels(audit["model"], fontsize=9)
    ax.set_ylabel("km")
    ax.legend(fontsize=8)
    ax.set_title("BLHA model comparison (its own holdout)", fontsize=10)
    sel = audit[audit["selected"].astype(bool)].iloc[0]
    body = ["BLHA AKS 1145 A — GEOREFERENCE", "",
            "  model         fit RMS  HOLD RMS  HOLD p90  scale  cond"]
    for r in audit.itertuples():
        body.append(f"  {r.model:13s} {r.fit_rms_m/1000:7.2f} "
                    f"{r.hold_rms_m/1000:9.2f} {r.hold_p90_m/1000:9.2f} "
                    f"{r.scale_ratio:6.2f} {r.condition:8.1e}")
    body += ["", f"  SELECTED {sel['model']}   "
                 f"blind n={int(sel['blind_n'])} "
                 f"median {sel['blind_median_km']} km "
                 f"p90 {sel['blind_p90_km']} km",
             f"  positional uncertainty {sel['positional_uncertainty_km']} km",
             f"  (the BnF figure of {BNF_UNCERTAINTY_KM} km is NOT carried "
             "over)", "",
             "PRIME MERIDIAN — THE INTERESTING PART", ""]
    body.append("  candidate                 offset      median residual")
    for r in cand.itertuples():
        body.append(f"  {r.candidate:24s} {r.offset_to_greenwich_deg:9.4f}"
                    f"   {r.median_residual_km:10,.1f} km")
    body += [""] + _wrap(
        "Read off its own graduations, this plate is not on Ferro. Ferro "
        "leaves a 328 km median error; the plate's longitudes are internally "
        "consistent but sit about 22.53 degrees west of Greenwich. The BnF "
        "sheet IS on Ferro. Two sheets that disagree about where longitude "
        "starts are not copies of one another, which is worth more than a "
        "footnote when they are being used as independent witnesses.")
    body += ["", "BLIND VALIDATION", ""]
    for r in blind.sort_values("residual_m").itertuples():
        body.append(f"  {r.reference_feature_name:26s} {r.zone:7s} "
                    f"{r.residual_m/1000:6.2f} km")
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_continuity(path, seg, cases, rev, title):
    fig, (ax, ax2) = _fig2((17, 8.5), [1, 1])
    body = ["CONTINUITY, SPLIT IN TWO", ""]
    body += _wrap(
        "MAPGEN-019 reported one column: continuity_status = CONTINUOUS on "
        "all six frontiers. That column was doing two jobs.")
    body += ["", "  subsegment                          POLITICAL      "
                 "BOUNDARY POSITION"]
    for r in seg.itertuples():
        body.append(f"  {r.subsegment_id[:34]:34s} "
                    f"{r.territorial_political_continuity[:13]:13s}  "
                    f"{r.boundary_position_continuity}")
    body += ["", "WHAT SURVIVED AND WHAT DID NOT", ""]
    pol_ok = int((seg["territorial_political_continuity"]
                  == "CONTINUOUS").sum())
    bnd_ok = int((seg["boundary_position_continuity"]
                  == "CONFIRMED_WITHIN_SOURCE_UNCERTAINTY").sum())
    body += _wrap(
        f"Political continuity holds on {pol_ok} of {len(seg)} subsegments. "
        f"Boundary-position continuity is confirmed on only {bnd_ok}: the "
        "rest carry a named local case, and one segment turns out not to be "
        "a Brandenburg frontier at all.")
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=7)
    ax.set_axis_off()
    body2 = ["ARCHIVAL CASES, OPENED AT SOURCE", ""]
    for r in cases.itertuples():
        body2.append(f"  {r.archival_signature}   {r.laufzeit}   "
                     f"[{r.classification}]")
        body2 += ["    " + ln for ln in _wrap(r.title, 84)[:2]]
        body2 += ["      " + ln for ln in _wrap(r.why, 82)[:5]]
        body2.append("")
    body2 += ["REVISIONS TO MAPGEN-019", ""]
    for r in rev.itertuples():
        body2.append(f"  {r.revision_id}")
        body2 += ["    " + ln for ln in _wrap(r.defect, 84)[:3]]
        body2.append("")
    ax2.text(0.0, 0.99, "\n".join(body2), va="top", family="monospace",
             fontsize=6.6)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_components(path, comp, inset, dig, title):
    fig, (ax, ax2) = _fig2((16, 7.5), [1, 1])
    body = ["COMPONENT AUDIT — colour is a segmentation aid, never the "
            "controller", ""]
    body.append("  component                       in BB   basis")
    for r in comp.itertuples():
        body.append(f"  {r.component:30s} {r.in_brandenburg:5s}   "
                    f"{r.controller_basis}")
    body += ["", "EXCLUDED, AND WHY", ""]
    for r in comp[comp.in_brandenburg == "NO"].itertuples():
        body.append(f"  {r.component}")
        body += ["    " + ln for ln in _wrap(r.blha_1758_evidence, 82)[:3]]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=7)
    ax.set_axis_off()
    body2 = ["INSET", ""]
    i = inset.iloc[0]
    for k in ("title", "own_graticule_range", "main_transform_applied",
              "status"):
        body2 += _wrap(f"  {k}: {i[k]}", 88)
    body2 += ["  " + ln for ln in _wrap(i["resolved_by_blha_reason"], 86)]
    body2 += ["", "DIGITISATION — ATTEMPTED, NOT ACHIEVED", ""]
    for r in dig.itertuples():
        body2.append(f"  {r.sheet}: {r.conclusion}")
        if r.method:
            body2 += ["    " + ln for ln in _wrap(str(r.method), 82)[:4]]
        if r.result:
            body2 += ["    -> " + ln for ln in _wrap(str(r.result), 80)[:2]]
        if r.diagnosis:
            body2 += ["    " + ln for ln in _wrap(str(r.diagnosis), 82)[:4]]
        body2.append("")
    body2 += ["  " + ln for ln in _wrap(dig.iloc[0]["stage_decision"], 86)]
    ax2.text(0.0, 0.99, "\n".join(body2), va="top", family="monospace",
             fontsize=6.8)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_status(path, s, title):
    fig, ax = _fig((15, 9))
    ax.set_axis_off()
    body = [
        "MAPGEN-020 — BRANDENBURG, TWO SOURCES", "",
        "PHASE A  continuity semantics", "",
        f"  segments / subsegments        : {s['segments']} / "
        f"{s['subsegments']}",
        f"  political continuity holds    : {s['political_continuous']} of "
        f"{s['subsegments']}",
        f"  boundary position confirmed   : {s['boundary_confirmed']} of "
        f"{s['subsegments']}",
        f"  archival cases opened         : {s['archival_cases']}",
        f"  segment-list correction       : {s['segment_correction']}",
        "",
        "PHASE B  BLHA georeference (independent)", "",
        f"  observed symbols              : {s['blha_points']}",
        f"  fit / model / blind           : {s['blha_fit']} / "
        f"{s['blha_model']} / {s['blha_blind']}",
        f"  model selected                : {s['blha_model_selected']}",
        f"  blind median / p90 / max      : {s['blha_blind_median_km']} / "
        f"{s['blha_blind_p90_km']} / {s['blha_blind_max_km']} km",
        f"  positional uncertainty        : {s['blha_uncertainty_km']} km"
        f"   (BnF: {BNF_UNCERTAINTY_KM} km, not reused)",
        f"  prime meridian                : {s['blha_prime_meridian']}"
        f"  offset {s['blha_meridian_offset']} deg",
        f"  Ferro would give              : {s['blha_ferro_km']} km median "
        "-> rejected",
        "",
        "PHASE C  geometry", "",
        f"  components audited            : {s['components']} "
        f"({s['components_in']} in, {s['components_out']} excluded)",
        f"  BnF digitisation              : {s['bnf_digitisation']}",
        f"  BLHA digitisation             : {s['blha_digitisation']}",
        f"  inset                         : {s['inset_status']}",
        f"  cross-source comparison       : {s['cross_source']}",
        "",
        "PHASE D  production", "",
        f"  production features           : {s['new_production_features']}",
        f"  Brandenburg CONTROLLED        : {s['brandenburg_controlled']}",
        f"  canonical rows                : {s['canonical_rows_before']} -> "
        f"{s['canonical_rows_after']}",
        f"  coverage                      : {s['coverage_status']}",
        "",
        "  Production is blocked by ONE thing: neither boundary was",
        "  digitised. It is not blocked by evidence. The 1756 political",
        "  evidence and the political continuity both hold, and the safe-",
        "  interior rule of the brief needs two polygons it does not have.",
    ]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=8.8)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
def run_historical_dual_source(cfg: MapgenConfig,
                               run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"brandenburg_dual_source_{_dt.datetime.now():%Y%m%d}"
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
    sdir = scenarios_root(cfg.data_dir) / scenario_id
    snap = load_scenario(cfg.data_dir, scenario_id)
    sp = snap.scenario_polities
    canonical = pd.read_csv(sdir / "territorial_control.csv",
                            keep_default_na=False, na_values=[""])
    provenance = pd.read_csv(sdir / "territorial_control_provenance.csv",
                             keep_default_na=False, na_values=[""])
    features = gpd.read_parquet(H / "historical_boundary_features.parquet")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    assertions = pd.read_csv(H / "historical_evidence_assertions.csv")
    cov = pd.read_csv(sdir / "political_coverage.csv",
                      keep_default_na=False, na_values=[""])
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")

    seg = pd.read_csv(H / "brandenburg_boundary_segment_continuity.csv",
                      keep_default_na=False, na_values=[""])
    cases = pd.read_csv(H / "brandenburg_local_boundary_cases.csv")
    rev = pd.read_csv(H / "brandenburg_boundary_continuity_revision.csv")
    bpts = pd.read_csv(H / "brandenburg_blha_observed_points.csv")
    brej = pd.read_csv(H / "brandenburg_blha_rejected_candidates.csv")
    baud = pd.read_csv(H / "brandenburg_blha_georeference_audit.csv")
    bcand = pd.read_csv(H / "brandenburg_blha_prime_meridian_audit.csv")
    bblind = pd.read_csv(H / "brandenburg_blha_blind_validation.csv")
    btrans = json.loads((H / "brandenburg_blha_transform.json").read_text(
        encoding="utf-8"))
    bnftrans = json.loads((H / "brandenburg_bnf_transform.json").read_text(
        encoding="utf-8"))
    comp = pd.read_csv(H / "brandenburg_component_audit.csv")
    inset = pd.read_csv(H / "brandenburg_inset_audit.csv")
    dig = pd.read_csv(H / "brandenburg_source_digitisation_audit.csv",
                      keep_default_na=False, na_values=[""])
    pol = pd.read_csv(H / "brandenburg_1756_political_evidence.csv",
                      keep_default_na=False, na_values=[""])
    bnfpts = pd.read_csv(H / "brandenburg_observed_feature_points.csv")
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv"]}
    src_brand = make_global_source_id(CK_BRAND)
    bsel = baud[baud["selected"].astype(bool)].iloc[0]
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
    _check("M20-01_mapgen019_regression",
           len(canonical) == 1614
           and int((canonical["control_status"] == "CONTROLLED").sum()) == 697
           and int((canonical["control_status"] == "UNRESOLVED").sum()) == 917
           and len(features) == 3 and len(bnfpts) == 33
           and bnftrans["georeference_status"] == "GEOREFERENCED_VALIDATED"
           and abs(float(bnftrans["positional_uncertainty_km"])
                   - BNF_UNCERTAINTY_KM) < 1e-6,
           "MAPGEN-019 baseline intact: 1,614/697/917, 3 features, 33 BnF "
           "observed points, BnF GEOREFERENCED_VALIDATED at 17.228 km")
    _check("M20-02_political_and_boundary_continuity_separated",
           "territorial_political_continuity" in seg.columns
           and "boundary_position_continuity" in seg.columns
           and "continuity_status" not in seg.columns
           and seg["boundary_position_continuity"].nunique() >= 4,
           "the single continuity_status column is gone; political and "
           "boundary-position continuity are separate columns with "
           f"{seg['boundary_position_continuity'].nunique()} distinct "
           "boundary states")
    sx = cases[cases["case_id"] == "case_saxony_branitz_weissagk_groetsch"]
    _check("M20-03_saxony_1748_1751_boundary_case_audited",
           len(sx) == 1
           and sx.iloc[0]["archival_signature"] == "2 Kurmaerkische Kammer "
                                                   "F 8218"
           and sx.iloc[0]["laufzeit"] == "1748-1751"
           and sx.iloc[0]["is_international"] == "YES"
           and "Ebeling" in sx.iloc[0]["corroborating_file"],
           "F 8218 (1748-1751) verified at source, corroborated by 17B 4948 "
           "with Ebeling's 1737 plan of the disputed line; the only "
           "INTERNATIONAL correction found, and it closes in the BnF's own "
           "represented year")
    gs = cases[cases["case_id"] == "case_silesia_glauchow_sabor"]
    _check("M20-04_glauchow_sabor_1746_1757_audited",
           len(gs) == 1 and gs.iloc[0]["laufzeit"] == "1746-1757"
           and "Forstgrenzen" in gs.iloc[0]["classification_path"]
           and gs.iloc[0]["classification"]
           == "BOUNDARY_REGULATION_WITHOUT_TERRITORIAL_TRANSFER"
           and gs.iloc[0]["is_international"] == "NO",
           "3 Neumaerkische Kammer 17143 opened: it sits under Registratur "
           "des Oberforstmeisters >> Amt Zuellichau >> Forstgrenzen and both "
           "parties were Prussian after 1742, so it is a forest boundary, "
           "not a territorial transfer")
    gz = cases[cases["case_id"] == "case_pompom_gartz_vierraden"]
    _check("M20-05_pomerania_dispute_audited",
           len(gz) == 1 and gz.iloc[0]["laufzeit"] == "1743-1752"
           and gz.iloc[0]["archival_signature"] == "37 Schwedt-Vierraden 116"
           and "1770-1789" in gz.iloc[0]["corroborating_file"],
           "37 Schwedt-Vierraden 116 opened and shown NOT settled in the "
           "window: the same quarrel runs on through 117, 118 and a "
           "Regulierung of 1770-1789")
    mk = cases[cases["case_id"] == "case_mecklenburg_menow_fuerstenberg"]
    _check("M20-06_mecklenburg_regulation_audited",
           len(mk) == 1 and mk.iloc[0]["laufzeit"] == "1704-1763"
           and "Fuerstenberg" in mk.iloc[0]["counterparty"],
           "7 Lindow/M 69 (1704-1763) names the Mecklenburg Amt Fuerstenberg "
           "as counterparty; 7 Lindow/M 67 (1669-1758) corroborates")
    strong = seg[seg["segment_id"].isin(
        ["seg_magdeburg_halberstadt", "seg_commonwealth"])]
    _check("M20-07_remaining_frontiers_strengthened",
           len(strong) >= 3
           and strong["exact_locator"].str.contains("bsb11399173").any()
           and strong["exact_locator"].str.contains("BLHA").any()
           and len(cases[cases["segment_id"] == "seg_commonwealth"]) == 1,
           "Magdeburg/Halberstadt and the Commonwealth are no longer carried "
           "on Wikipedia alone: both cite the 1756 edicts by scan and column, "
           "and the Commonwealth frontier adds BLHA 3 Neumaerkische Kammer "
           "12085 (Sapieha's claim on the Drage)")
    _check("M20-08_local_changes_subsegmented",
           len(seg) > seg["segment_id"].nunique()
           and (seg.groupby("segment_id").size() > 1).sum() >= 4
           and seg["subsegment_id"].nunique() == len(seg),
           f"{len(seg)} subsegments over {seg['segment_id'].nunique()} "
           "segments: every frontier carrying a local case also carries a "
           "remainder, so one Feldmark never condemns a whole frontier")

    _check("M20-09_blha_georef_independent",
           btrans["independent_of_bnf_transform"] is True
           and (bpts["bnf_transform_used"] == "NO").all()
           and (bpts["georeference_source"] == "BLHA_AKS_1145_A_ONLY").all()
           and btrans["prime_meridian"] != bnftrans["prime_meridian"],
           "the BLHA transform was fitted only on symbols observed on AKS "
           "1145 A; it does not even share a prime meridian with the BnF "
           f"sheet ({btrans['prime_meridian']} vs "
           f"{bnftrans['prime_meridian']})")
    bnf_xy = set(zip(bnfpts["pixel_x"].round(1), bnfpts["pixel_y"].round(1)))
    blha_xy = set(zip(bpts["pixel_x"].round(1), bpts["pixel_y"].round(1)))
    _check("M20-10_blha_observed_gcp_provenance",
           (bpts["bnf_pixel_reused"] == "NO").all()
           and not (bnf_xy & blha_xy)
           and (bpts["chosen_anchor"] == "RED_SYMBOL_FILL_CENTROID").all()
           and len(bpts) >= 16,
           f"{len(bpts)} BLHA points, none sharing a pixel position with the "
           "33 BnF points, all anchored on this sheet's own red Urbes fill")
    ids = {r: set(bpts.loc[bpts.split_role == r, "point_id"])
           for r in ("FIT", "MODEL_SELECTION_HOLDOUT", "BLIND_VALIDATION")}
    _check("M20-11_blha_fit_model_blind_isolated",
           not (ids["FIT"] & ids["MODEL_SELECTION_HOLDOUT"])
           and not (ids["FIT"] & ids["BLIND_VALIDATION"])
           and not (ids["MODEL_SELECTION_HOLDOUT"] & ids["BLIND_VALIDATION"])
           and len(ids["BLIND_VALIDATION"]) >= 4,
           f"fit {len(ids['FIT'])} / model {len(ids['MODEL_SELECTION_HOLDOUT'])}"
           f" / blind {len(ids['BLIND_VALIDATION'])}, pairwise disjoint and "
           "frozen before fitting")
    bunc = float(bsel["positional_uncertainty_km"])
    _check("M20-12_blha_uncertainty_independent",
           abs(bunc - BNF_UNCERTAINTY_KM) > 1.0
           and bsel["independent_of_bnf"] == "YES"
           and bunc >= float(bsel["blind_p90_km"]),
           f"{bunc} km, built from this sheet's own blind p90 "
           f"({bsel['blind_p90_km']} km) plus its own symbol, line-width and "
           f"digitisation terms; the BnF {BNF_UNCERTAINTY_KM} km is not "
           "carried over")

    bnfdig = dig[dig["sheet"].str.contains("BnF")].iloc[0]
    blhadig = dig[dig["sheet"].str.contains("BLHA")].iloc[0]
    _check("M20-13_bnf_digitisation_not_faked",
           bnfdig["geometry_written"] == "NO"
           and bnfdig["traced_from_other_source"] == "NO"
           and bnfdig["conclusion"] == "NO_POLYGON_PRODUCED"
           and len(features) == 3,
           "the BnF digitisation was attempted and failed; the attempt and "
           "its failure mode are recorded, no polygon was written, and "
           "nothing was traced from the BLHA sheet")
    _check("M20-14_blha_digitisation_not_faked",
           blhadig["geometry_written"] == "NO"
           and blhadig["traced_from_other_source"] == "NO"
           and src_brand not in set(features["global_source_id"]),
           "no BLHA polygon was written and nothing was traced from the BnF "
           "sheet")
    _check("M20-15_colour_is_not_the_controller",
           (comp["colour_used_as_controller"] == "NO").all()
           and comp["controller_basis"].str.contains("LABEL").all(),
           "every component's controller rests on lettering, the title "
           "cartouche or a 1756 administrative record; colour was used only "
           "to segment")
    inb = comp[comp.in_brandenburg == "YES"]["component"].tolist()
    _check("M20-16_brandenburg_components_audited",
           {"Altmark", "Mittelmark", "Neumark", "Uckermark", "Prignitz"}
           <= set(inb) and (comp["audited_on_both_sheets"] == "YES").all(),
           "Altmark, Mittelmark, Neumark, Uckermark and Prignitz all audited "
           "on both sheets: " + ", ".join(sorted(inb)))
    out = set(comp[comp.in_brandenburg == "NO"]["component"])
    _check("M20-17_magdeburg_halberstadt_excluded",
           "Duchy of Magdeburg" in out
           and "Principality of Halberstadt" in out,
           "Magdeburg and Halberstadt are lettered on UNCOLOURED ground on "
           "the ca.1758 sheet and addressed by their own Regierung and "
           "Kammer in 1756; excluded")
    _check("M20-18_pomerania_excluded",
           "Pomerania" in out,
           "Pomerania is lettered DUCATUS POMERANIAE PARS on uncoloured "
           "ground and administered from Stettin and Koeslin; excluded")
    _check("M20-19_inset_isolated",
           inset.iloc[0]["main_transform_applied"] == "NO"
           and inset.iloc[0]["status"] == "INSET_GEOMETRY_GAP"
           and inset.iloc[0]["resolved_by_blha"] == "NO",
           "the Vieille Marche / Prignitz supplement keeps its own graticule "
           "and its own gap; the BLHA sheet drawing that territory does not "
           "close a gap in the BnF sheet")

    _check("M20-20_cross_source_samples_real",
           not (H / "brandenburg_cross_source_boundary_audit.csv").exists(),
           "no cross-source boundary audit was written, because there are no "
           "two polygons to measure between. An empty or zero-sample audit "
           "file would have been worse than none")
    _check("M20-21_no_average_line_synthesis",
           src_brand not in set(assertions["global_source_id"])
           and len(features) == 3,
           "no boundary assertion and no feature were written, so no line "
           "was averaged between sources")
    _check("M20-22_boundary_changes_not_hidden",
           len(cases) == 5
           and (cases["verified_at_source"] == "YES").all()
           and int((seg["boundary_position_continuity"]
                    != "CONFIRMED_WITHIN_SOURCE_UNCERTAINTY").sum()) >= 5,
           f"{len(cases)} local boundary cases are recorded with signature, "
           "Bestand, classification path and Laufzeit rather than smoothed "
           "into a frontier-level CONTINUOUS")

    _check("M20-23_1756_political_evidence_retained",
           len(pol) == 5 and (pol["status"] == "OBTAINED").all(),
           "the five MAPGEN-019 Novum Corpus entries are carried forward "
           "unchanged")
    _check("M20-24_admin_evidence_is_not_boundary_position",
           set(pol["evidence_role"]) <= {"POLITICAL_CONTROL",
                                         "ADMINISTRATIVE_SCOPE"}
           and not seg["change_evidence"].str.contains(
               "POLITICAL_CONTROL").any(),
           "the 1756 edicts stay POLITICAL_CONTROL / ADMINISTRATIVE_SCOPE "
           "and are never cited as boundary-position authority")
    brand_sp = make_scenario_polity_id(scenario_id, "pol_brandenburg")
    roots = set(sp.loc[sp["territorial_authority_role"]
                       == "COMPOSITE_TERRITORIAL_ACTOR",
                       "scenario_polity_id"])
    _check("M20-25_specific_actor_pol_brandenburg",
           brand_sp in set(sp["scenario_polity_id"]),
           "pol_brandenburg exists as a distinct scenario actor")
    _check("M20-26_prussian_root_duplicate_zero",
           not canonical["controller_scenario_polity_id"].isin(roots).any()
           and int((canonical["controller_scenario_polity_id"]
                    == brand_sp).sum()) == 0,
           "no composite root holds control and pol_brandenburg still holds "
           "nothing")
    _check("M20-27_safe_interior_not_asserted_without_geometry",
           not (H / "brandenburg_safe_interior_audit.csv").exists(),
           "the safe-interior rule needs a hex to sit inside BOTH "
           "uncertainty-buffered polygons. With no polygon there is no such "
           "test, and none was invented")
    _check("M20-28_exact_land_binding_untouched",
           len(features) == 3
           and not (H / "historical_snapshot_features_1756_08_01.csv").exists(),
           "no snapshot feature was compiled, so the exact-land binder was "
           "never invoked")
    _check("M20-29_production_provenance_complete",
           int((canonical["controller_scenario_polity_id"]
                == brand_sp).sum()) == 0,
           "no production row was written, so there is no row lacking "
           "provenance")
    empty = pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"])
    log = pd.read_csv(sdir / "scenario_control_promotion_log.csv",
                      keep_default_na=False, na_values=[""])
    c2, _p2, _l2, rep = promote_control(
        canonical.copy(), provenance.copy(), log.copy(), empty, scenario_id,
        STAGE, M19_COMMIT, "none", "src_none", promoted_utc="2026-08-14")
    _check("M20-30_promotion_idempotent",
           rep["inserted"] == 0 and len(c2) == len(canonical)
           and rep["promotion_id"] == make_promotion_id(
               scenario_id, STAGE, sha256_of_frame(empty)),
           "promotion workflow exercised with an empty candidate: 0 "
           "inserted, canonical untouched")
    _check("M20-31_no_silent_overwrite",
           len(log) == len(pd.read_csv(sdir / "scenario_control_promotion_log"
                                       ".csv", keep_default_na=False,
                                       na_values=[""])),
           "the promotion log is unchanged; nothing was overwritten")
    brow = cov[cov["coverage_unit_id"] == "region_brandenburg_1756_pilot"]
    _check("M20-32_incomplete_coverage_remains_unknown",
           len(brow) == 1
           and brow.iloc[0]["control_coverage_status"] == "UNASSESSED"
           and int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0,
           "control coverage stays UNASSESSED: a georeferenced pair of "
           "sheets is not a resolved territory")

    _check("M20-33_low_countries_regression",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP",
           "Low Countries still SOURCE_GAP")
    wash_feat = features[features["historical_subject_id"]
                         == "hsub_schwarzburg_unpartitioned_wash"]
    _check("M20-34_schwarzburg_regression",
           len(wash_feat) == 1
           and wash_feat.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY"
           and wash["UNRESOLVED"] == 89,
           "Schwarzburg wash unchanged")
    _check("M20-35_saxony_regression",
           sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and wei == {"CONTROLLED": 0, "UNRESOLVED": 96},
           f"Saxony {sax}, Saxe-Weimar {wei} unchanged")
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    _check("M20-36_europe_regression",
           int(eu_man["hex_count"].sum()) == 1885422,
           "Europe canonical grid intact (1,885,422 hexes)")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    _check("M20-37_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN",
           "Toshima hex still OCEAN")
    _check("M20-38_claims_regression",
           len(snap.territorial_claims) == 1,
           "claims table still holds its single MAPGEN-008 row")
    comps_p = pd.read_parquet(geo_dir / "island_components.parquet",
                              columns=["island_component_id"])
    scen_srcs = pd.read_csv(sdir / "sources.csv", keep_default_na=False,
                            na_values=[""])
    struct = set(sp.loc[sp["territorial_authority_role"].isin(
        ["STRUCTURAL_CONTAINER", "COMPOSITE_TERRITORIAL_ACTOR"]),
        "scenario_polity_id"])
    m_hex = set()
    for d in (cfg.output_dir / scfg.get(
                  "mapgen014_run", "central_europe_1756_revision_20260813"),
              cfg.output_dir / scfg.get(
                  "mapgen013_run", "central_europe_1756_expand_20260813")):
        p = d / "historical_hex_membership.parquet"
        if p.exists():
            m_hex |= set(pd.read_parquet(p, columns=["hex_id"])["hex_id"])
    integ = validate_canonical_control(
        canonical, provenance, sp, scen_srcs,
        set(geo.loc[geo["water_type"] == "NONE", "hex_id"]) | m_hex,
        set(comps_p["island_component_id"]), struct)
    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("M20-39_determinism_and_integrity",
           integ == [] and up_after == upstream
           and HPG_SCHEMA_VERSION == "1.4.0"
           and SCENARIO_SCHEMA_VERSION == "1.5.0"
           and not scan_forbidden_reference_code(Path(__file__)),
           f"canonical integrity {integ or 'clean'}, upstream byte-identical, "
           "scenario schema at the pinned 1.5.0, forbidden-reference scan clean")

    # ---- figures ---------------------------------------------------------
    t0 = time.perf_counter()
    img = ["brandenburg_blha_observed_points.png",
           "brandenburg_blha_georeference.png",
           "brandenburg_boundary_continuity.png",
           "brandenburg_components_and_geometry.png",
           "brandenburg_dual_source_status.png"]
    render_blha_points(run_dir / img[0], bpts,
                       "A. AKS 1145 A — symbols observed on this sheet alone")
    render_blha_georef(run_dir / img[1], baud, bblind, bcand,
                       "B. The BLHA georeference, and its prime meridian")
    render_continuity(run_dir / img[2], seg, cases, rev,
                      "C. Continuity, split into two questions")
    render_components(run_dir / img[3], comp, inset, dig,
                      "D. Components, inset and the digitisation attempt")
    ferro = float(bcand[bcand["candidate"] == "FERRO_20W_OF_PARIS"].iloc[0][
        "median_residual_km"])
    summary = [
        ("stage", STAGE), ("base_commit_mapgen019", M19_COMMIT),
        ("outcome", "PARTIAL"),
        ("segments", int(seg["segment_id"].nunique())),
        ("subsegments", len(seg)),
        ("political_continuous",
         int((seg["territorial_political_continuity"] == "CONTINUOUS").sum())),
        ("boundary_confirmed",
         int((seg["boundary_position_continuity"]
              == "CONFIRMED_WITHIN_SOURCE_UNCERTAINTY").sum())),
        ("archival_cases", len(cases)),
        ("segment_correction",
         "seg_swedish_pomerania -> NOT_A_FRONTIER_IN_1756"),
        ("blha_points", len(bpts)),
        ("blha_rejected_candidates", len(brej)),
        ("blha_fit", int((bpts.split_role == "FIT").sum())),
        ("blha_model", int((bpts.split_role
                            == "MODEL_SELECTION_HOLDOUT").sum())),
        ("blha_blind", int((bpts.split_role == "BLIND_VALIDATION").sum())),
        ("blha_model_selected", bsel["model"]),
        ("blha_blind_median_km", float(bsel["blind_median_km"])),
        ("blha_blind_p90_km", float(bsel["blind_p90_km"])),
        ("blha_blind_max_km", float(bsel["blind_max_km"])),
        ("blha_uncertainty_km", bunc),
        ("bnf_uncertainty_km", BNF_UNCERTAINTY_KM),
        ("blha_prime_meridian", btrans["prime_meridian"]),
        ("blha_meridian_offset",
         btrans["prime_meridian_offset_to_greenwich_deg"]),
        ("blha_ferro_km", ferro),
        ("bnf_prime_meridian", bnftrans["prime_meridian"]),
        ("components", len(comp)),
        ("components_in", int((comp.in_brandenburg == "YES").sum())),
        ("components_out", int((comp.in_brandenburg == "NO").sum())),
        ("bnf_digitisation", bnfdig["conclusion"]),
        ("blha_digitisation", blhadig["conclusion"]),
        ("inset_status", inset.iloc[0]["status"]),
        ("cross_source", "NOT_MEASURABLE_NO_POLYGONS"),
        ("new_production_features", 0),
        ("authorised_snapshot_features", 0),
        ("new_hex_membership_rows", 0),
        ("brandenburg_controlled", 0), ("brandenburg_unresolved", 0),
        ("saxony_controlled", sax["CONTROLLED"]),
        ("canonical_rows_before", len(canonical)),
        ("canonical_rows_after", len(canonical)),
        ("canonical_rows_changed", 0),
        ("coverage_status", brow.iloc[0]["source_evidence_status"]),
        ("coverage_control_status", brow.iloc[0]["control_coverage_status"]),
        ("validation_pass", ""),
    ]
    sd = dict(summary)
    render_status(run_dir / img[4], sd, "E. MAPGEN-020 status")
    from PIL import Image

    aspects = {n: round(Image.open(run_dir / n).size[0]
                        / Image.open(run_dir / n).size[1], 3) for n in img}
    timings["render_s"] = time.perf_counter() - t0

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(drop=True)
    val.to_csv(run_dir / "validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    summary = [(k, v) for k, v in summary if k != "validation_pass"] + [
        ("validation_pass", f"{n_pass}/{len(val)}")]
    pd.DataFrame(summary, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "summary.csv", index=False)
    manifest = {
        "run_id": run_id, "stage": STAGE, "outcome": "PARTIAL",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen019": M19_COMMIT,
        "continuity": {"segments": int(seg["segment_id"].nunique()),
                       "subsegments": len(seg),
                       "archival_cases": cases[
                           ["case_id", "archival_signature", "laufzeit",
                            "classification"]].to_dict("records")},
        "blha_georeference": {
            "points": len(bpts), "model": bsel["model"],
            "blind": {"n": int(bsel["blind_n"]),
                      "median_km": float(bsel["blind_median_km"]),
                      "p90_km": float(bsel["blind_p90_km"])},
            "uncertainty_km": bunc,
            "prime_meridian": btrans["prime_meridian"],
            "offset_deg": btrans["prime_meridian_offset_to_greenwich_deg"],
            "candidates": bcand.to_dict("records")},
        "digitisation": dig.to_dict("records"),
        "shortfalls_against_the_brief": [
            "neither source boundary was digitised, so there is no "
            "cross-source comparison, no safe-interior test and no "
            "production control",
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
    _write_readme(run_dir, run_id, dict(summary), seg, cases, rev, baud,
                  bcand, bblind, comp, dig, aspects, img)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    cmap = {"README_REVIEW.md": run_dir / "README_REVIEW.md",
            "run_manifest.json": run_dir / "run_manifest.json",
            "validation.csv": run_dir / "validation.csv",
            "summary.csv": run_dir / "summary.csv"}
    for n in ["brandenburg_boundary_segment_continuity",
              "brandenburg_boundary_continuity_revision",
              "brandenburg_local_boundary_cases",
              "brandenburg_blha_observed_points",
              "brandenburg_blha_rejected_candidates",
              "brandenburg_blha_georeference_audit",
              "brandenburg_blha_prime_meridian_audit",
              "brandenburg_blha_blind_validation",
              "brandenburg_component_audit", "brandenburg_inset_audit",
              "brandenburg_source_digitisation_audit",
              "brandenburg_1756_political_evidence",
              "brandenburg_observed_feature_points",
              "brandenburg_bnf_georeference_audit",
              "historical_evidence_assertions",
              "historical_boundary_feature_evidence",
              "historical_source_registry"]:
        cmap[n + ".csv"] = H / (n + ".csv")
    cmap["brandenburg_blha_transform.json"] = (
        H / "brandenburg_blha_transform.json")
    cmap["brandenburg_bnf_transform.json"] = (
        H / "brandenburg_bnf_transform.json")
    cmap["scenario_political_coverage.csv"] = sdir / "political_coverage.csv"
    cmap["territorial_control.csv"] = sdir / "territorial_control.csv"
    cmap["territorial_control_provenance.csv"] = (
        sdir / "territorial_control_provenance.csv")
    cmap["scenario_control_promotion_log.csv"] = (
        sdir / "scenario_control_promotion_log.csv")
    cmap["historical_hex_membership.csv"] = (
        m15_dir / "chatgpt_review" / "historical_hex_membership.csv")
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
    print(f"[dual-source] {run_id}: validation {n_pass}/{len(val)}, "
          f"{len(seg)} subsegments, {len(cases)} archival cases, "
          f"{len(bpts)} BLHA points, BLHA uncertainty {bunc} km "
          f"({btrans['prime_meridian']}), no geometry digitised, "
          f"canonical unchanged ({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[dual-source][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, seg, cases, rev, baud, cand, blind,
                  comp, dig, aspects, img):
    L = [
        f"# {STAGE} Review — two sources, and what they do not agree about",
        "",
        "**OUTCOME: PARTIAL.** The continuity claim MAPGEN-019 left standing "
        "has been taken apart and rebuilt on archival evidence, the BLHA "
        "sheet has been georeferenced entirely on its own evidence, and "
        "**neither boundary was digitised** — so there is no cross-source "
        "comparison and **no production control**. Canonical rows "
        f"{s['canonical_rows_before']:,} → {s['canonical_rows_after']:,}, "
        f"changed **{s['canonical_rows_changed']}**.",
        "",
        f"Run `{run_id}`, built on MAPGEN-019 commit "
        f"`{s['base_commit_mapgen019']}`.",
        "",
        "## 1. One column was doing two jobs",
        "",
        "MAPGEN-019 reported `continuity_status = CONTINUOUS` on all six "
        "frontiers, five of them HIGH confidence. That conflated two "
        "different claims:",
        "",
        "- **territorial/political continuity** — was this territory under "
        "the same authority in 1756? MAPGEN-019 showed this, and it survives.",
        "- **boundary-position continuity** — may the drawn line be used as "
        "an authority at 6 km? MAPGEN-019 never showed this.",
        "",
        f"Split apart: political continuity holds on "
        f"**{s['political_continuous']} of {s['subsegments']}** subsegments; "
        f"boundary-position continuity is confirmed on only "
        f"**{s['boundary_confirmed']}**.",
        "",
        "## 2. Four archival cases, opened at source",
        "",
        "| signature | Laufzeit | classification | international |",
        "|---|---|---|---|",
    ]
    for r in cases.itertuples():
        L.append(f"| `{r.archival_signature}` | {r.laufzeit} | "
                 f"{r.classification} | {r.is_international} |")
    L += [
        "",
        "The two that matter most:",
        "",
        "- **Saxony, `2 Kurmärkische Kammer F 8218` (1748–1751)** — an "
        "explicit *Berichtigung der Landesgrenze zu Kursachsen* at Branitz, "
        "Weißagk and Grötsch, corroborated by `17B 4948` in the Niederlausitz "
        "Oberamtsregierung's *Grenz-Sachen*, which contains Ebeling's **1737 "
        "plan of the disputed line**. Both files close in **1751 — the BnF "
        "sheet's own represented year**. Whether the sheet shows the old or "
        "the corrected line cannot be settled from the catalogue.",
        "- **Silesia, `3 Neumärkische Kammer 17143` (1746–1757)** — the "
        "brief flagged this as highest priority because its Laufzeit straddles "
        "the whole window. Reading the classification path settles it: "
        "*Registratur des Oberforstmeisters → Amt Züllichau → **Forstgrenzen***, "
        "and both parties were Prussian after 1742. A **forest** boundary "
        "between a domain village and a lordship, not a transfer of territory. "
        "A Laufzeit is the span of a file, not the duration of a change.",
        "",
        "The Gartz case (`37 Schwedt-Vierraden 116`, 1743–1752) is "
        "demonstrably **not** settled in the window — the same quarrel runs "
        "on through files 117, 118 and a *Regulierung* of 1770–1789.",
        "",
        "## 3. A correction to the segment list itself",
        "",
        "**Brandenburg did not border Swedish Pomerania in 1756.** By the "
        "Treaty of Stockholm (1720) Sweden had already ceded everything south "
        "of the Peene, so Swedish Pomerania bordered *Prussian* Pomerania and "
        "Mecklenburg — not the Margraviate. MAPGEN-019 carried it as one of "
        "six Brandenburg frontiers; it is now `NOT_APPLICABLE`, and the Gartz "
        "lead the brief filed under it in fact audits the **Uckermark / "
        "Prussian Pomerania** line, recorded as `seg_prussian_pomerania`.",
        "",
        "## 4. The BLHA sheet, georeferenced on its own evidence",
        "",
        f"- **{s['blha_points']} symbols** found by a global "
        "connected-component scan of the plate's own red *Urbes* fill — a "
        "different symbol convention from the BnF sheet's engraved circles. "
        "**No BnF transform was used and no BnF pixel was reused.**",
        f"- Split `{s['blha_fit']} fit / {s['blha_model']} model / "
        f"{s['blha_blind']} blind`, frozen before fitting.",
        f"- Model **{s['blha_model_selected']}**; blind median "
        f"**{s['blha_blind_median_km']} km**, p90 "
        f"**{s['blha_blind_p90_km']} km**.",
        f"- **Positional uncertainty {s['blha_uncertainty_km']} km**, derived "
        f"from this sheet alone. The BnF figure of {s['bnf_uncertainty_km']} "
        "km is **not** carried over.",
        f"- Two candidates were rejected during collection, not after: "
        "Luckenwalde (a paper stain) and Stendal (the symbol is on the Elbe "
        "and labelled **Tangermünde**).",
        "",
        "### The prime meridian is the interesting part",
        "",
        "| candidate | offset | median residual |",
        "|---|---|---|",
    ]
    for r in cand.itertuples():
        L.append(f"| {r.candidate} | {r.offset_to_greenwich_deg:.4f}° | "
                 f"{r.median_residual_km:,.1f} km |")
    L += [
        "",
        f"**This plate is not on Ferro.** Ferro leaves a "
        f"{s['blha_ferro_km']:,.0f} km median error; the plate's longitudes "
        "are internally consistent but sit about "
        f"**{abs(float(s['blha_meridian_offset'])):.2f}° west of Greenwich**. "
        f"The BnF sheet *is* on Ferro (`{s['bnf_prime_meridian']}`). Two "
        "sheets that disagree about where longitude starts are **not copies "
        "of one another** — which is exactly the independence the "
        "cross-source design assumes, now demonstrated rather than hoped for.",
        "",
        "## 5. Components — colour never decides the controller",
        "",
        "| component | in Brandenburg | basis |",
        "|---|---|---|",
    ]
    for r in comp.itertuples():
        L.append(f"| {r.component} | {r.in_brandenburg} | "
                 f"{r.controller_basis} |")
    L += [
        "",
        "Magdeburg, Halberstadt and Pomerania are excluded on lettering and "
        "on the 1756 administrative record, not on colour: all three are "
        "drawn on **uncoloured** ground on the ca. 1758 sheet.",
        "",
        "## 6. What was not done — the digitisation",
        "",
    ]
    for r in dig.itertuples():
        L.append(f"**{r.sheet} — `{r.conclusion}`**")
        if r.method:
            L.append(f"- method: {r.method}")
        if r.result:
            L.append(f"- result: {r.result}")
        if r.diagnosis:
            L.append(f"- diagnosis: {r.diagnosis}")
        if r.second_attempt:
            L.append(f"- second attempt: {r.second_attempt} → "
                     f"{r.second_result}")
        L.append("")
    L += [
        dig.iloc[0]["stage_decision"],
        "",
        "**Consequences, stated plainly:** no cross-source boundary "
        "comparison (there is nothing to measure between), no safe-interior "
        "test (it requires two buffered polygons), and **Brandenburg "
        f"CONTROLLED remains {s['brandenburg_controlled']}**. Coverage stays "
        f"`{s['coverage_control_status']}`.",
        "",
        "Production is **not** blocked by evidence. The 1756 political "
        "evidence holds, political continuity holds, and both sheets are now "
        "validated georeferences. It is blocked by the absence of geometry, "
        "and that is a narrower and more tractable gap than the one this "
        "stage started with.",
        "",
        "## 7. Images",
        "",
    ]
    for n in img:
        L.append(f"- `{n}` (aspect {aspects[n]})")
    L += [
        "",
        "There is deliberately no source-geometry figure, no cross-source "
        "figure, no safe-interior figure and no hex-control figure: none of "
        "those things exist.",
        "",
        "## 8. Validation",
        "",
        f"- `validation.csv`: M20 gates, pass count {s['validation_pass']}.",
        "",
        "## 9. Known issues and what MAPGEN-021 should do",
        "",
        "- **The digitisation is the whole remaining blocker for "
        "Brandenburg.** Both plates render their boundaries as discontinuous "
        "coloured washes on tinted paper, which defeats flood-fill "
        "segmentation. The next attempt should trace the boundary as an "
        "explicit polyline at native resolution rather than trying to fill a "
        "region, and should expect to do it by hand.",
        "- The Saxony frontier at Branitz/Weißagk/Grötsch cannot be resolved "
        "from catalogue metadata; it needs the file itself, or Ebeling's 1737 "
        "plan, which is a digitisation request rather than a search.",
        "- The BnF inset remains `INSET_GEOMETRY_GAP`, and the BLHA sheet "
        "covering the same territory does not close it.",
        "- Per the brief, MAPGEN-021 leaves Brandenburg and moves to another "
        "large territory.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(L) + "\n",
                                              encoding="utf-8")
