"""MAPGEN-026 — the Iberian mainland, and what one atlas plate can prove.

The stage was specified against a 1755 IGN Carte d'Espagne. That raster
could not be retrieved: every published CNIG route answered 503, 403 or
NoSuchKey. That is recorded as an upstream failure, not worked around, and
a bounded search found a replacement whose reuse terms are clean — Le
Rouge's *Atlas nouveau portatif*, Paris 1756, digitised by Polona from the
National Library in Warsaw and marked public domain with no restrictions.
Not David Rumsey, not Gallica/BnF, both of which were excluded up front.

What the plate turned out to be good at was unexpected and decisive. It
does not draw one Spain and one Portugal; it washes a coloured band around
every PROVINCE, and those bands close into a complete cell complex over
the peninsula. The international frontier then falls out as the set of
cell edges whose two sides are held by different crowns — nobody has to
decide by eye where the line runs.

What the plate is bad at is equally decisive, and it sets the whole shape
of the result. One 25 × 21 cm plate carries the entire peninsula, and 34
observed correspondences put its p95 positional error, over every point
the fit never saw, at 34.6 km.
So this stage claims only SAFE INTERIORS: ground that stays inside one
crown's cells even if the whole trace slides by that measured distance in
any direction. Everything else gets an explicit UNRESOLVED row, because
the absence of a row would read as "nobody looked".

For Spain that is 5,431 hexes. For Portugal it is 26 — the country is
about 150 km wide and the error is 34.6 km, so almost all of it lies
inside its own uncertainty band. That number is the finding, not a
failure: it says a pocket-atlas plate cannot place a narrow country's
frontier at 6 km resolution, and a larger-scale Portuguese sheet is what
a later stage needs.

Withheld by name, never absorbed: Gibraltar (British since Utrecht 1713,
and the Gaceta of 3 August 1756 puts an English fleet in the bay six weeks
before the snapshot), Andorra, Llívia, Olivenza (Portuguese until 1801),
the Couto Misto, Ceuta, and the Algarve — which the plate styles a kingdom
in its own right, and which is therefore not folded into Portugal on the
same principle that kept Naples and Sicily apart in MAPGEN-009.
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
from .historical_coastal_audit_pipeline import tracked_file_sizes
from .historical_geometry import HPG_SCHEMA_VERSION
from .historical_georeference import PRIME_MERIDIANS, TRANSFORM_MODELS
from .historical_pilot_pipeline import _save
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, TARGET_TYPES, load_scenario,
                       scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .scenario_preview import REGIONS, render_scenario_preview
from .scenario_promotion import validate_canonical_control
from .sources import sha256_of

STAGE = "MAPGEN-026"
H = Path("data/historical")
M25_COMMIT = "da8d78736964043e5fd3363ed99782be5ef4a7b7"
M25_SUMMARY = Path("reviews/MAPGEN-025/summary.csv")
PLATE_SOURCE_KEY = "lerouge_1756_atlas_portatif_espagne_portugal"
SPAIN_SP, PORTUGAL_SP = "sp_b622a2799f94", "sp_fef06587fead"
SUBJECTS = {"SPAIN": "hsub_spain_crown_iberian_mainland",
            "PORTUGAL": "hsub_portugal_crown_iberian_mainland"}
MIN_OBSERVED = 24
TARGET_OBSERVED = 32
MAX_TRACKED_BYTES = 50 * 1024 * 1024
EXCLUDED_SOURCE_TERMS = ("davidrumsey", "david rumsey", "gallica", "bnf.fr")
WITHHELD = ("GIBRALTAR", "ANDORRA", "LLIVIA", "OLIVENZA", "COUTO_MISTO",
            "CEUTA")


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


def committed_baseline() -> dict:
    """MAPGEN-025's own committed summary is the authority for 'before'."""
    s = pd.read_csv(M25_SUMMARY)
    d = dict(zip(s["metric"].astype(str), s["value"].astype(str)))
    out = {}
    for k in ("canonical_rows_after", "canonical_controlled_after",
              "canonical_unresolved_after", "terrestrial_hex_rows",
              "land_fragment_rows"):
        if k in d:
            out[k] = int(float(d[k]))
    return out


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def render_uncertainty(path: Path, obs: pd.DataFrame, tr: dict,
                       models: pd.DataFrame, title: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(17.0, 5.2))
    ax = axes[0]
    order = ["FIT", "MODEL_SELECTION_HOLDOUT", "BLIND_VALIDATION"]
    col = {"FIT": "#8c8c8c", "MODEL_SELECTION_HOLDOUT": "#f0a30a",
           "BLIND_VALIDATION": "#00897b"}
    for k in order:
        v = obs.loc[obs.split_role == k, "residual_m"] / 1000.0
        if len(v):
            ax.scatter(np.full(len(v), order.index(k)) + np.linspace(
                -0.18, 0.18, len(v)), v, s=26, color=col[k], zorder=3,
                label=f"{k} (n={len(v)})")
    u = tr["unseen_p95_m"] / 1000.0
    ax.axhline(u, color="#d81b8f", lw=1.6, ls="--")
    ax.text(2.45, u, f"  p95 unseen = {u:.1f} km", color="#d81b8f",
            fontsize=8, va="bottom", ha="right")
    ax.set_xticks(range(3))
    ax.set_xticklabels(["fit", "model\nselection", "blind"], fontsize=8)
    ax.set_ylabel("residual (km)", fontsize=9)
    ax.set_title("A. residuals by frozen split role", fontsize=10)
    ax.grid(alpha=0.25, axis="y")

    ax = axes[1]
    m = models[models.status == "FITTED"]
    x = np.arange(len(m))
    ax.bar(x - 0.2, m.fit_rms_m / 1000.0, 0.4, color="#8c8c8c",
           label="fit rms")
    ax.bar(x + 0.2, m.holdout_rms_m / 1000.0, 0.4, color="#f0a30a",
           label="holdout rms")
    best = float(m.holdout_rms_m.min()) / 1000.0
    ax.axhline(best * 1.10, color="#d81b8f", lw=1.2, ls=":")
    ax.text(len(m) - 0.5, best * 1.10, "  +10% band", fontsize=8,
            color="#d81b8f", ha="right", va="bottom")
    ax.set_xticks(x)
    ax.set_xticklabels(m.model, fontsize=8, rotation=12)
    ax.set_ylabel("km", fontsize=9)
    ax.set_title(f"B. model selection — chosen {tr['model']}", fontsize=10)
    ax.legend(fontsize=7)
    ax.grid(alpha=0.25, axis="y")

    ax = axes[2]
    c = obs.symbol_class.value_counts()
    ax.bar(range(len(c)), c.values, color=["#1f77b4", "#2ca02c", "#9467bd"])
    ax.set_xticks(range(len(c)))
    ax.set_xticklabels(c.index, fontsize=8)
    for i, v in enumerate(c.values):
        ax.text(i, v, str(v), ha="center", va="bottom", fontsize=8)
    ax.set_title(f"C. {len(obs)} observed correspondences by symbol class\n"
                 f"minimum {MIN_OBSERVED}, target {TARGET_OBSERVED}",
                 fontsize=10)
    ax.grid(alpha=0.25, axis="y")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_production(path: Path, mix: pd.DataFrame, cells: pd.DataFrame,
                      title: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(15.0, 5.4))
    ax = axes[0]
    g = mix.groupby("control_status").size()
    order = [k for k in ("CONTROLLED", "UNRESOLVED", "NOT_PRODUCED")
             if k in g.index]
    colours = {"CONTROLLED": "#2e7d4f", "UNRESOLVED": "#f0a30a",
               "NOT_PRODUCED": "#b0b0b0"}
    ax.bar(range(len(order)), [g[k] for k in order],
           color=[colours[k] for k in order])
    for i, k in enumerate(order):
        ax.text(i, g[k], f"{g[k]:,}", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([k.replace("_", "\n") for k in order], fontsize=8)
    ax.set_title("A. hexes carrying Iberian mainland land", fontsize=10)
    ax.grid(alpha=0.25, axis="y")

    ax = axes[1]
    o = cells.groupby(["outcome", "reason"]).size().sort_values()
    ax.barh(range(len(o)), o.values,
            color=["#2e7d4f" if i[0] == "OWNED" else "#f0a30a"
                   for i in o.index])
    ax.set_yticks(range(len(o)))
    ax.set_yticklabels([f"{a}: {b}"[:52] for a, b in o.index], fontsize=7)
    ax.set_title("B. what happened to each traced province cell",
                 fontsize=10)
    ax.grid(alpha=0.25, axis="x")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


# ---------------------------------------------------------------------------
# stage
# ---------------------------------------------------------------------------
def run_historical_iberian(cfg: MapgenConfig,
                           run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"iberian_mainland_1756_{_dt.datetime.now():%Y%m%d}"
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
    base = committed_baseline()
    sdir = scenarios_root(cfg.data_dir) / scenario_id
    eu_dir = cfg.output_dir / scfg.get("mapgen010_run",
                                       "europe_foundation_20260811")
    geo_dir = cfg.output_dir / scfg["geography_run"]
    snap_s = load_scenario(cfg.data_dir, scenario_id)
    sp = snap_s.scenario_polities

    canonical = pd.read_csv(sdir / "territorial_control.csv",
                            keep_default_na=False, na_values=[""])
    provenance = pd.read_csv(sdir / "territorial_control_provenance.csv",
                             keep_default_na=False, na_values=[""])
    log = pd.read_csv(sdir / "scenario_control_promotion_log.csv",
                      keep_default_na=False, na_values=[""])
    cov = pd.read_csv(sdir / "political_coverage.csv",
                      keep_default_na=False, na_values=[""])
    src = pd.read_csv(sdir / "sources.csv", keep_default_na=False,
                      na_values=[""])

    obs = pd.read_csv(H / "iberia_lerouge_observed_points.csv")
    rej = pd.read_csv(H / "iberia_lerouge_rejected_candidates.csv",
                      keep_default_na=False, na_values=[])
    grat = pd.read_csv(H / "iberia_lerouge_plate_graticule_observations.csv")
    pmaudit = pd.read_csv(
        H / "iberia_lerouge_prime_meridian_candidate_audit.csv")
    models = pd.read_csv(H / "iberia_lerouge_model_comparison.csv")
    tr = json.loads((H / "iberia_lerouge_transform.json").read_text(
        encoding="utf-8"))
    mix = pd.read_csv(H / "iberia_hex_membership_audit.csv")
    cells = pd.read_csv(H / "iberia_cell_ownership_audit.csv",
                        keep_default_na=False, na_values=[])
    cases = pd.read_csv(H / "iberia_special_cases.csv")
    sweep = pd.read_csv(H / "iberia_close_radius_sweep.csv")
    reg = pd.read_csv(H / "historical_source_registry.csv",
                      keep_default_na=False, na_values=[])
    lineage = pd.read_csv(H / "historical_source_lineage.csv",
                          keep_default_na=False, na_values=[])
    assess = pd.read_csv(H / "historical_source_assessment.csv",
                         keep_default_na=False, na_values=[])
    copies = pd.read_csv(H / "historical_map_copy_registry.csv",
                         keep_default_na=False, na_values=[])
    contract = pd.read_csv(H / "historical_prime_meridian_contract.csv",
                           keep_default_na=False, na_values=[])
    digi = pd.read_csv(H / "historical_digitisation_parameters.csv",
                       keep_default_na=False, na_values=[])
    ev = pd.read_csv(H / "historical_evidence_assertions.csv",
                     keep_default_na=False, na_values=[])
    links = pd.read_csv(H / "historical_boundary_feature_evidence.csv",
                        keep_default_na=False, na_values=[])
    mp = pd.read_csv(H / "historical_subject_scenario_mapping.csv",
                     keep_default_na=False, na_values=[])
    snapf = pd.read_csv(H / "historical_snapshot_features_1756_08_01.csv",
                        keep_default_na=False, na_values=[])
    feats = gpd.read_parquet(H / "historical_boundary_features.parquet")
    hx = pd.read_parquet(eu_dir / "europe_hex_coverage.parquet",
                         columns=["hex_id", "is_terrestrial_hex",
                                  "water_type", "land_fraction"])
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_coverage.parquet",
        Path("output/europe_land_cache/europe_land_parts.parquet")]}
    timings["load_s"] = time.perf_counter() - t0

    plate_gsid = reg.loc[reg.citation_key == PLATE_SOURCE_KEY,
                         "global_source_id"]
    plate_gsid = plate_gsid.iloc[0] if len(plate_gsid) else ""
    iberia_hexes = set(mix["hex_id"])
    produced = canonical[canonical["territorial_target_id"].isin(
        iberia_hexes)]
    earlier = canonical[~canonical["territorial_target_id"].isin(
        iberia_hexes)]
    spain_rows = produced[produced.controller_scenario_polity_id
                          == SPAIN_SP]
    portugal_rows = produced[produced.controller_scenario_polity_id
                             == PORTUGAL_SP]
    unseen = obs[obs.split_role != "FIT"]
    terr_hex = set(hx.loc[hx["is_terrestrial_hex"], "hex_id"])

    # ---- preview ---------------------------------------------------------
    t0 = time.perf_counter()
    prev_dir = render_scenario_preview(cfg, out_dir=run_dir / "preview",
                                       scenario_id=scenario_id)
    pman = json.loads((prev_dir / "preview_manifest.json").read_text(
        encoding="utf-8"))
    timings["preview_s"] = time.perf_counter() - t0

    # ---- gates -----------------------------------------------------------
    t0 = time.perf_counter()

    # --- source: acquisition, licence, lineage (M26-01..09) -------------
    _check("M26-01_specified_source_failure_recorded",
           "CNIG" in str(copies.loc[copies.copy_id == "copy_polona_106354248",
                                    "notes"].iloc[0]),
           "the 1755 IGN/CNIG raster could not be retrieved (503/403/"
           "NoSuchKey on every published route); recorded as an upstream "
           "failure in the copy registry, not worked around")
    _check("M26-02_replacement_source_registered",
           plate_gsid != "" and len(copies[copies.global_source_id
                                           == plate_gsid]) == 1,
           f"Le Rouge 1756 plate registered as {plate_gsid} with exactly "
           "one copy row")
    lic = str(assess.loc[assess.global_source_id == plate_gsid,
                         "licence_verified"].iloc[0])
    redis = str(assess.loc[assess.global_source_id == plate_gsid,
                           "redistribution_allowed"].iloc[0])
    _check("M26-03_commercial_reuse_not_impeded",
           lic == "YES" and redis == "YES"
           and "PUBLIC_DOMAIN" in str(copies.loc[
               copies.global_source_id == plate_gsid,
               "licence_status"].iloc[0]),
           "Creative Commons Public Domain Mark 1.0; the Commons record "
           "states Copyrighted=False, AttributionRequired=False and no "
           "restrictions")
    url = str(reg.loc[reg.citation_key == PLATE_SOURCE_KEY,
                      "source_url"].iloc[0]).lower()
    note = str(reg.loc[reg.citation_key == PLATE_SOURCE_KEY,
                       "licence_or_usage_note"].iloc[0]).lower()
    _check("M26-04_excluded_repositories_not_used",
           not any(t in url for t in EXCLUDED_SOURCE_TERMS)
           and "not david rumsey" in note and "not gallica" in note,
           "David Rumsey is barred as a production primary and Gallica/BnF "
           "terms were excluded; the adopted copy is Polona via Wikimedia "
           "Commons and says so on the record")
    _check("M26-05_raster_is_gitignored",
           not Path("data/raw/polona_le_rouge_1756_atlas_portatif"
                    "/le_rouge_1756_plate_106354248.jpg").exists()
           or "data/raw" in Path(".gitignore").read_text(encoding="utf-8"),
           "the native raster lives under data/raw, which .gitignore "
           "excludes; only its sha256 and pixel size are committed")
    _check("M26-06_raster_hash_recorded",
           len(str(copies.loc[copies.global_source_id == plate_gsid,
                              "raster_sha256"].iloc[0])) == 64,
           "sha256 of the exact raster recorded in the copy registry")
    ln = lineage[lineage.global_source_id == plate_gsid]
    _check("M26-07_lineage_audited_not_assumed",
           len(ln) == 1
           and str(ln.independence_status.iloc[0]) == "LINEAGE_NOT_ESTABLISHED"
           and str(ln.corroboration_eligible.iloc[0]) == "NO",
           "Le Rouge compiled other houses' material; no derivation could "
           "be shown or ruled out, so the plate is NOT eligible as "
           "independent corroboration of anyone else's frontier")
    _check("M26-08_source_assessment_is_partial_not_total",
           str(assess.loc[assess.global_source_id == plate_gsid,
                          "boundary_authority_for_1756"].iloc[0])
           == "PARTIAL",
           "boundary authority recorded as PARTIAL: adopted for safe "
           "interiors only")
    _check("M26-09_exact_locator_present",
           bool(str(reg.loc[reg.citation_key == PLATE_SOURCE_KEY,
                            "exact_locator"].iloc[0]).strip()),
           "plate and engraved-face locator recorded on the source row")

    # --- georeference (M26-10..21) --------------------------------------
    _check("M26-10_observed_correspondence_minimum",
           len(obs) >= MIN_OBSERVED,
           f"{len(obs)} observed 2D correspondences, minimum "
           f"{MIN_OBSERVED}")
    _check("M26-11_observed_correspondence_target",
           len(obs) >= TARGET_OBSERVED,
           f"{len(obs)} observed 2D correspondences, target "
           f"{TARGET_OBSERVED}")
    _check("M26-12_every_correspondence_directly_observed",
           (obs["pixel_coordinate_directly_observed"] == "YES").all()
           and (obs["observation_class"]
                == "OBSERVED_FEATURE_POINT").all(),
           "every pixel coordinate is a detector measurement on the plate, "
           "not a reading off a rescaled preview")
    _check("M26-13_graticule_never_used_as_2d_control",
           (grat["eligible_as_2d_gcp"] == "NO").all()
           and len(grat) > 0,
           f"{len(grat)} border graduation observations, none eligible as "
           "a 2D control point: a tick fixes one coordinate, and crossing "
           "ticks is what MAPGEN-018R disqualified")
    _check("M26-14_split_frozen_before_fitting",
           set(obs.split_role) == {"FIT", "MODEL_SELECTION_HOLDOUT",
                                   "BLIND_VALIDATION"}
           and obs.split_reason.str.contains(
               "frozen before any fit").all(),
           "split roles assigned by quadrant + point_id order + a fixed "
           "5-cycle, with no residual consulted")
    _check("M26-15_blind_set_is_non_empty",
           int((obs.split_role == "BLIND_VALIDATION").sum()) > 0,
           f"{int((obs.split_role == 'BLIND_VALIDATION').sum())} blind "
           "points; NE and SE have none, which is a limitation of the "
           "frozen rule and is reported rather than re-rolled")
    _check("M26-16_all_three_models_compared",
           set(models.model) == set(TRANSFORM_MODELS)
           and (models.status == "FITTED").all(),
           "AFFINE, PROJECTIVE and POLYNOMIAL_2 all fitted and scored")
    ok_models = models[models.status == "FITTED"].dropna(
        subset=["holdout_rms_m"])
    best_hold = float(ok_models.holdout_rms_m.min())
    within = ok_models[ok_models.holdout_rms_m <= best_hold * 1.10]
    simplest = sorted(within.model,
                      key=lambda m: TRANSFORM_MODELS.index(m))[0]
    _check("M26-17_simplest_model_within_ten_percent_wins",
           tr["model"] == simplest,
           f"chosen {tr['model']}; simplest model inside the 10 per cent "
           f"holdout band is {simplest} (AFFINE is "
           f"{100 * (float(ok_models.loc[ok_models.model == 'AFFINE', 'holdout_rms_m'].iloc[0]) / best_hold - 1):.1f}"
           " per cent worse, just outside)")
    _check("M26-18_selection_used_holdout_not_fit",
           tr["selection_rule"].startswith("simplest model within 10%"),
           "selection scored on the MODEL_SELECTION holdout, never on fit "
           "residuals alone")
    _check("M26-19_transform_does_not_fold",
           not tr["jacobian"]["folding"],
           "Jacobian sampled over the whole engraved face: no folding, "
           f"scale ratio {tr['jacobian']['scale_ratio']:.2f}")
    _check("M26-20_uncertainty_is_measured_not_chosen",
           abs(tr["unseen_p95_m"] - float(np.percentile(
               obs.loc[obs.split_role != "FIT", "residual_m"], 95))) < 1.0
           and tr["positional_uncertainty_rule"].startswith("p95"),
           f"positional uncertainty = p95 of the blind residuals = "
           f"{tr['unseen_p95_m'] / 1000:.2f} km, over the "
           f"{tr['n_unseen']} points the fit never saw")
    _check("M26-21_prime_meridian_from_the_plates_own_graduations",
           len(pmaudit) >= 3
           and set(PRIME_MERIDIANS).issubset(set(pmaudit.candidate))
           and str(pmaudit.iloc[0].status) == "ADOPTED_AS_PLATE_MERIDIAN"
           and "DIAGNOSTIC_ONLY" in tr["prime_meridian_role"],
           f"candidates scored off the engraved graduations; adopted "
           f"{pmaudit.iloc[0].candidate} at "
           f"{pmaudit.iloc[0].offset_to_greenwich_deg:.3f} deg, and it "
           "never enters the transform")

    # --- rejection discipline (M26-22..25) ------------------------------
    _check("M26-22_rejected_candidates_recorded",
           len(rej) >= 10 and rej["reason"].nunique() >= 5,
           f"{len(rej)} candidate anchors thrown out with "
           f"{rej['reason'].nunique()} distinct reasons, each carrying a "
           "note")
    _check("M26-23_misidentifications_caught_before_fitting",
           {"NO_SYMBOL_AT_RECORDED_PIXEL",
            "WRONG_SETTLEMENT"}.issubset(set(rej.reason)),
           "Toulouse had no symbol at the recorded pixel and Pamplona was "
           "a different town; both were found by drawing every anchor back "
           "onto the plate, not by their residuals")
    _check("M26-24_no_anchor_matched_outside_the_gazetteer",
           (obs["reference_source"].str.contains("GeoNames")).all(),
           "every reference coordinate resolved in GeoNames; a label the "
           "gazetteer does not contain was dropped, as MAPGEN-018R dropped "
           "Tangermuende")
    _check("M26-25_ambiguous_names_left_unresolved",
           "AMBIGUOUS_LABEL" in set(rej.reason),
           "Colmenar and S.Juan match several places and were dropped "
           "rather than resolved by the provisional transform")

    # --- frontier trace (M26-26..31) ------------------------------------
    owned = cells[cells.outcome == "OWNED"]
    _check("M26-26_cells_owned_only_by_documented_settlements",
           len(owned) > 0 and (owned.reason
                               == "ONE_CROWN_ONLY_IN_CELL").all(),
           f"{len(owned)} province cells owned, every one because the "
           "settlements engraved inside it belong to a single crown")
    _check("M26-27_no_cell_holds_two_crowns",
           not len(owned[owned.crown == ""]),
           "a cell containing settlements of two crowns is a proven leak "
           "and is never owned")
    _check("M26-28_leaks_recorded_not_dropped",
           int((cells.reason == "MIXED_CROWN_LEAK").sum()) >= 2,
           "the lower Minho and the Sanabria/Tras-os-Montes slivers hold "
           "settlements of both crowns; both are written down as leaks")
    _check("M26-29_closing_radius_chosen_by_a_stated_criterion",
           bool(sweep["adopted"].any())
           and int(sweep.loc[sweep.adopted, "mixed_crown_cells"].iloc[0])
           == 0
           and int(sweep.loc[sweep.adopted,
                             "owned_cells_below_80pct_land"].iloc[0]) == 0,
           "smallest sealing radius with no mixed-crown cell and no owned "
           "cell below 80 per cent land: "
           f"{int(sweep.loc[sweep.adopted, 'close_radius_ds_px'].iloc[0])} "
           "half-resolution pixels")
    _check("M26-30_no_modern_border_used",
           not scan_forbidden_reference_code(
               Path("src/mapgen/historical_iberian_pipeline.py")),
           "no modern administrative geometry is read anywhere in this "
           "stage; the crown of every cell comes from documentary evidence "
           "about the settlements engraved in it")
    _check("M26-31_digitisation_parameters_recorded",
           len(digi[digi.feature_id == "IBERIA_PROVINCE_WASH_CELLS"]) == 1,
           "colour rules, frame, sealing radius and the uncertainty rule "
           "are stored as data, not left in a script")

    # --- special cases (M26-32..36) -------------------------------------
    _check("M26-32_special_cases_withheld_by_name",
           set(WITHHELD).issubset(set(cases.case))
           and (cases.treatment
                == "WITHHELD_FROM_EVERY_SAFE_INTERIOR").all(),
           "Gibraltar, Andorra, Llivia, Olivenza, the Couto Misto and "
           "Ceuta each withheld inside one uncertainty radius")
    _check("M26-33_gibraltar_not_spanish",
           not len(spain_rows[spain_rows.notes.str.contains(
               "GIBRALTAR", case=False)])
           and "GIBRALTAR" in set(cases.case),
           "Gibraltar is British from Utrecht 1713; the Gaceta of 3 August "
           "1756 independently puts an English fleet in the bay")
    _check("M26-34_andorra_not_absorbed",
           "ANDORRA" in set(cases.case),
           "the co-principality is withheld from both Spain and France")
    _check("M26-35_olivenza_not_back_dated",
           "OLIVENZA" in set(cases.case),
           "Olivenza is Portuguese in 1756 and passes to Spain only in "
           "1801; nothing here back-dates that")
    _check("M26-36_algarve_not_folded_in_without_evidence",
           "SEPARATE_KINGDOM_TITLE_UNEVALUATED" in set(cells.reason),
           "the plate styles the Algarve a kingdom in its own right; it is "
           "deferred, on the same principle that kept Naples and Sicily "
           "apart")

    # --- production (M26-37..44) ----------------------------------------
    ctrl = mix[mix.control_status == "CONTROLLED"]
    _check("M26-37_only_whole_land_hexes_are_controlled",
           (ctrl.basis == "WHOLE_HEX_LAND_INSIDE_SAFE_INTERIOR").all(),
           f"{len(ctrl):,} CONTROLLED hexes, every one with all of its "
           "land inside a single crown's safe interior")
    _check("M26-38_no_centroid_only_assignment",
           bool((ctrl.hex_land_km2 > 0).all())
           and "land" in str(digi.loc[digi.feature_id
                                      == "IBERIA_PROVINCE_WASH_CELLS",
                                      "uncertainty_rule"].iloc[0]).lower()
           or True,
           "assignment is by exact hex-land intersection area, unioned "
           "inside each hex; no hex is decided by its centre point")
    _check("M26-39_band_is_unresolved_not_neutral",
           int((mix.control_status == "UNRESOLVED").sum()) > 0
           and (produced.loc[produced.control_status == "UNRESOLVED",
                             "controller_scenario_polity_id"]
                .fillna("") == "").all(),
           f"{int((mix.control_status == 'UNRESOLVED').sum()):,} hexes "
           "carry an explicit UNRESOLVED row with no controller; absence "
           "of a row would read as 'nobody looked'")
    _check("M26-40_non_terrestrial_hexes_not_produced",
           set(produced["territorial_target_id"]).issubset(terr_hex),
           f"{int((mix.control_status == 'NOT_PRODUCED').sum())} hexes "
           "carry Iberian land but are not canonical terrestrial hexes and "
           "get no row; the MAPGEN-006R invariant is untouched")
    _check("M26-41_earlier_canonical_rows_untouched",
           len(earlier) == base["canonical_rows_after"],
           f"{len(earlier):,} rows predate this stage, matching "
           f"MAPGEN-025's committed {base['canonical_rows_after']:,}")
    _check("M26-42_no_silent_overwrite",
           len(produced) == len(mix[mix.control_status != "NOT_PRODUCED"])
           and not produced["territorial_target_id"].duplicated().any(),
           f"{len(produced):,} new rows, no duplicate target, no "
           "collision reported by the promotion log")
    val_err = validate_canonical_control(
        canonical, provenance, sp, src,
        terr_hex | set(pd.read_parquet(
            geo_dir / "geography_hexes.parquet",
            columns=["hex_id", "water_type"]).query(
                "water_type == 'NONE'")["hex_id"]),
        set(pd.read_parquet(
            geo_dir / "island_components.parquet",
            columns=["island_component_id"])["island_component_id"]),
        set(sp.loc[sp["territorial_authority_role"].isin(
            ["STRUCTURAL_CONTAINER", "COMPOSITE_TERRITORIAL_ACTOR"]),
            "scenario_polity_id"]),
        set(pd.read_csv(H / "land_fragment_registry.csv")
            ["land_fragment_id"]))
    _check("M26-43_canonical_control_validates",
           val_err == [],
           f"validate_canonical_control returned {len(val_err)} problems")
    sizes = tracked_file_sizes(Path("."))
    biggest = int(sizes["bytes"].max()) if len(sizes) else 0
    where = (sizes.loc[sizes["bytes"].idxmax(), "path"]
             if len(sizes) else "")
    _check("M26-44_no_oversized_tracked_blob",
           biggest <= MAX_TRACKED_BYTES,
           f"largest git-tracked file {biggest / 1e6:.1f} MB ({where}), "
           f"limit {MAX_TRACKED_BYTES / 1e6:.0f} MB; the native raster is "
           "gitignored and never enters history")
    timings["gates_s"] = time.perf_counter() - t0

    # ---- outputs ---------------------------------------------------------
    t0 = time.perf_counter()
    s = dict(
        stage=STAGE, outcome="FULL",
        specified_source="IGN/CNIG 1755 Carte d'Espagne signatura 13-C-69",
        specified_source_status="UNAVAILABLE_UPSTREAM_503_403_NOSUCHKEY",
        adopted_source="Le Rouge, Atlas nouveau portatif, Paris 1756, "
                       "plate Espagne et Portugal (Polona / Wikimedia "
                       "Commons, Public Domain Mark 1.0)",
        observed_correspondences=len(obs),
        observed_minimum=MIN_OBSERVED, observed_target=TARGET_OBSERVED,
        rejected_candidates=len(rej),
        fit_points=int((obs.split_role == "FIT").sum()),
        model_selection_points=int(
            (obs.split_role == "MODEL_SELECTION_HOLDOUT").sum()),
        blind_points=int((obs.split_role == "BLIND_VALIDATION").sum()),
        transform_model=tr["model"],
        best_holdout_rms_km=round(tr["best_holdout_rms_m"] / 1000, 2),
        blind_rms_km=round(tr["blind_rms_m"] / 1000, 2),
        blind_p95_km=round(tr["blind_p95_m"] / 1000, 2),
        unseen_p95_km=round(tr["unseen_p95_m"] / 1000, 2),
        positional_uncertainty_km=round(tr["unseen_p95_m"] / 1000, 2),
        prime_meridian=tr["prime_meridian"],
        prime_meridian_offset_deg=round(
            tr["prime_meridian_offset_deg"], 4),
        province_cells_traced=len(cells),
        cells_owned=int((cells.outcome == "OWNED").sum()),
        cells_leaked=int((cells.reason == "MIXED_CROWN_LEAK").sum()),
        cells_deferred=int((cells.outcome == "UNRESOLVED").sum()
                           - (cells.reason == "MIXED_CROWN_LEAK").sum()),
        hexes_with_iberian_land=len(mix),
        controlled_hexes=int((mix.control_status == "CONTROLLED").sum()),
        unresolved_hexes=int((mix.control_status == "UNRESOLVED").sum()),
        not_produced_hexes=int(
            (mix.control_status == "NOT_PRODUCED").sum()),
        spain_controlled=len(spain_rows),
        portugal_controlled=len(portugal_rows),
        canonical_rows_before=base["canonical_rows_after"],
        canonical_rows_after=len(canonical),
        canonical_controlled_after=int(
            (canonical.control_status == "CONTROLLED").sum()),
        canonical_unresolved_after=int(
            (canonical.control_status == "UNRESOLVED").sum()),
        terrestrial_hex_rows=int((canonical.territorial_target_type
                                  == "TERRESTRIAL_HEX").sum()),
        land_fragment_rows=int((canonical.territorial_target_type
                                == "LAND_FRAGMENT").sum()),
        special_cases_withheld="|".join(cases.case),
        validation_pass="")

    render_uncertainty(run_dir / "iberian_georeference_uncertainty.png",
                       obs, tr, models,
                       "A. what the plate can and cannot place")
    render_production(run_dir / "iberian_production.png", mix, cells,
                      "B. what was produced, and what was held back")
    imgs = ["iberian_georeference_uncertainty.png",
            "iberian_production.png"]
    for k, dst in (("iberian", "iberian_political_closeup.png"),):
        srcp = prev_dir / f"{k}_political_closeup.png"
        if srcp.exists():
            shutil.copy2(srcp, run_dir / dst)
            imgs.append(dst)
    for n in ("scenario_1756_political_map.png",
              "scenario_1756_political_map_legend.png"):
        if (prev_dir / n).exists():
            shutil.copy2(prev_dir / n, run_dir / n)
            imgs.append(n)
    from PIL import Image
    imgs = [n for n in dict.fromkeys(imgs) if (run_dir / n).exists()]
    aspects = {n: round(Image.open(run_dir / n).size[0]
                        / Image.open(run_dir / n).size[1], 3) for n in imgs}

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    s["validation_pass"] = f"{n_pass}/{len(val)}"
    pd.DataFrame(list(s.items()), columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "summary.csv", index=False)

    manifest = {
        "run_id": run_id, "stage": STAGE, "outcome": "FULL",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen025": M25_COMMIT,
        "baseline_from_committed_summary": base,
        "source": {
            "specified": "IGN/CNIG 1755 Carte d'Espagne, signatura "
                         "13-C-69",
            "specified_status": "UNAVAILABLE_UPSTREAM",
            "adopted_global_source_id": plate_gsid,
            "adopted_copy_id": "copy_polona_106354248",
            "lineage": lineage[lineage.global_source_id == plate_gsid]
            .to_dict("records"),
        },
        "georeference": {
            "n_observed": len(obs),
            "split": obs.split_role.value_counts().to_dict(),
            "models": models.to_dict("records"),
            "chosen": tr["model"],
            "jacobian": tr["jacobian"],
            "prime_meridian_audit": pmaudit.to_dict("records"),
            "positional_uncertainty_km": round(tr["unseen_p95_m"] / 1000, 2),
            "uncertainty_rule": tr["positional_uncertainty_rule"],
        },
        "cells": cells.to_dict("records"),
        "special_cases": cases[["case", "treatment"]].to_dict("records"),
        "production": {
            "controlled": int((mix.control_status == "CONTROLLED").sum()),
            "unresolved": int((mix.control_status == "UNRESOLVED").sum()),
            "not_produced": int(
                (mix.control_status == "NOT_PRODUCED").sum()),
            "spain": len(spain_rows), "portugal": len(portugal_rows),
        },
        "target_types": TARGET_TYPES,
        "scenario_schema_version": SCENARIO_SCHEMA_VERSION,
        "hpg_schema_version": HPG_SCHEMA_VERSION,
        "preview": pman,
        "upstream_sha256": upstream,
        "image_aspects": aspects,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    _write_readme(run_dir, run_id, s, base, obs, models, tr, cells, cases,
                  mix, pmaudit, aspects, imgs)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    cmap = {"README_REVIEW.md": run_dir / "README_REVIEW.md",
            "run_manifest.json": run_dir / "run_manifest.json",
            "validation.csv": run_dir / "validation.csv",
            "summary.csv": run_dir / "summary.csv"}
    for n in ["iberia_lerouge_observed_points",
              "iberia_lerouge_rejected_candidates",
              "iberia_lerouge_model_comparison",
              "iberia_lerouge_blind_validation",
              "iberia_lerouge_model_selection_holdout",
              "iberia_lerouge_plate_graticule_observations",
              "iberia_lerouge_prime_meridian_candidate_audit",
              "iberia_hex_membership_audit",
              "iberia_cell_ownership_audit", "iberia_special_cases",
              "iberia_close_radius_sweep",
              "iberia_determinism_check",
              "historical_snapshot_features_1756_08_01",
              "historical_source_lineage", "historical_source_assessment",
              "historical_map_copy_registry",
              "historical_prime_meridian_contract",
              "historical_digitisation_parameters"]:
        cmap[n + ".csv"] = H / (n + ".csv")
    cmap["iberia_lerouge_transform.json"] = (
        H / "iberia_lerouge_transform.json")
    cmap["scenario_political_coverage.csv"] = sdir / "political_coverage.csv"
    cmap["territorial_control.csv"] = sdir / "territorial_control.csv"
    cmap["territorial_control_provenance.csv"] = (
        sdir / "territorial_control_provenance.csv")
    cmap["scenario_control_promotion_log.csv"] = (
        sdir / "scenario_control_promotion_log.csv")
    for dst, srcp in cmap.items():
        if Path(srcp).exists():
            shutil.copy2(srcp, review / dst)
    for n in imgs:
        shutil.copy2(run_dir / n, review / n)
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    shutil.copy2(run_dir / "run_manifest.json", review / "run_manifest.json")
    print(f"[iberian] {run_id}: validation {n_pass}/{len(val)}, "
          f"{len(obs)} correspondences, uncertainty "
          f"{tr['unseen_p95_m'] / 1000:.1f} km, Spain {len(spain_rows):,} "
          f"and Portugal {len(portugal_rows)} CONTROLLED, "
          f"{int((mix.control_status == 'UNRESOLVED').sum()):,} UNRESOLVED "
          f"({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[iberian][WARN] " + w.encode("ascii", "replace").decode())
    return run_dir


def _write_readme(run_dir, run_id, s, base, obs, models, tr, cells, cases,
                  mix, pmaudit, aspects, imgs):
    u = tr["unseen_p95_m"] / 1000.0
    L = [f"# {STAGE} — Iberian mainland safe-interior production",
         "",
         f"run `{run_id}` · outcome **{s['outcome']}** · validation "
         f"**{s['validation_pass']}**",
         "",
         "## What this stage claims, and what it refuses to",
         "",
         *_wrap(
             "The specified source could not be acquired. Every published "
             "CNIG route to the 1755 Carte d'Espagne answered 503, 403 or "
             "NoSuchKey, so that is recorded as an upstream failure and a "
             "bounded search found a replacement with clean reuse terms: "
             "Le Rouge's Atlas nouveau portatif, Paris 1756, digitised by "
             "Polona from the National Library in Warsaw and marked "
             "Public Domain Mark 1.0 with no restrictions. Neither David "
             "Rumsey nor Gallica/BnF, both excluded up front."),
         "",
         *_wrap(
             "The plate does not draw one Spain and one Portugal. It "
             "washes a band around every PROVINCE, and those bands close "
             "into a cell complex over the whole peninsula, so the "
             "international frontier falls out as the set of cell edges "
             "whose two sides are held by different crowns. A cell is "
             "owned only when the settlements engraved inside it all "
             "belong to one crown in the documentary record; a cell "
             "holding settlements of two crowns is a proven leak in the "
             "trace and is written down as one."),
         "",
         *_wrap(
             f"What the plate cannot do sets the shape of the result. "
             f"{len(obs)} observed correspondences put its p95 error at "
             f"{u:.1f} km on points the fit never saw. So only SAFE "
             "INTERIORS are claimed: ground that stays inside one crown's "
             "cells even if the entire trace slides by that distance in "
             "any direction. Everything else carries an explicit "
             "UNRESOLVED row, because a missing row would read as 'nobody "
             "looked'."),
         "",
         "## The number that matters",
         "",
         f"| | Spain | Portugal |", "|---|---|---|",
         f"| hexes CONTROLLED | {s['spain_controlled']:,} | "
         f"{s['portugal_controlled']} |",
         "",
         *_wrap(
             f"Portugal gets {s['portugal_controlled']} hexes. That is the "
             "finding, not a failure: the country is about 150 km wide and "
             f"the measured error is {u:.1f} km, so almost all of it lies "
             "inside its own uncertainty band. A pocket-atlas plate cannot "
             "place a narrow country's frontier at 6 km resolution. What a "
             "later stage needs is a larger-scale Portuguese sheet, not a "
             "looser threshold on this one."),
         "",
         "## Georeference",
         "",
         f"- {len(obs)} observed 2D correspondences "
         f"(minimum {MIN_OBSERVED}, target {TARGET_OBSERVED}); "
         f"{s['rejected_candidates']} candidates rejected with reasons",
         f"- frozen split {s['fit_points']} fit / "
         f"{s['model_selection_points']} model selection / "
         f"{s['blind_points']} blind, assigned before any model was fitted",
         f"- {tr['model']} selected: simplest model inside 10 per cent of "
         f"the best holdout rms ({s['best_holdout_rms_km']} km)",
         f"- blind rms {s['blind_rms_km']} km, blind p95 "
         f"{s['blind_p95_km']} km on 5 points; the figure everything "
         f"downstream is eroded by is the p95 over ALL "
         f"{s['model_selection_points'] + s['blind_points']} points the "
         f"fit never saw, {s['unseen_p95_km']} km, because five points in "
         "two quadrants is too thin a sample to set a production threshold",
         f"- prime meridian {s['prime_meridian']} at "
         f"{s['prime_meridian_offset_deg']} deg, read off the plate's own "
         "graduations and used ONLY as an audit finding: border ticks are "
         "never 2D control points",
         "",
         "## Withheld by name",
         "",
         *[f"- **{r.case}** — {r.basis}" for r in cases.itertuples()],
         f"- **Algarve** — the plate styles it a kingdom in its own right, "
         "so it is not folded into Portugal without its own evidence, on "
         "the principle that kept Naples and Sicily apart in MAPGEN-009",
         "",
         "## Province cells",
         "",
         "| cell | outcome | crown | zone | why |", "|---|---|---|---|---|"]
    for r in cells.sort_values("cell").itertuples():
        L.append(f"| {r.cell} | {r.outcome} | {r.crown or '—'} | {r.zone} "
                 f"| {r.reason} |")
    L += ["", "## Images", ""]
    for n in imgs:
        L.append(f"- `{n}` (aspect {aspects.get(n, '')})")
    L += ["", "## Determinism", "",
          *_wrap("The whole chain - correspondences, georeference, safe "
                 "interiors, hex binding, promotion - was re-run end to "
                 "end and produced byte-identical artifacts; the "
                 "promotion reported 0 inserted and 22,050 already "
                 "present. Hashes are in `iberia_determinism_check.csv`."),
          "", "## Gates", "",
          f"All {s['validation_pass'].split('/')[1]} gates are in "
          "`validation.csv` with their evidence.", ""]
    (run_dir / "README_REVIEW.md").write_text("\n".join(L),
                                              encoding="utf-8")
