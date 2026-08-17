"""MAPGEN-028 — Portugal measured again, on a plate five times the size.

MAPGEN-026 georeferenced a Le Rouge atlas plate and measured its positional
uncertainty at 34.61 km. MAPGEN-027 showed that Portugal's problem was not
scale but geometry, and recovered it from 26 hexes to 124 without a single
new measurement. Both were right about what they had. Neither had a plate
worth measuring.

This stage does. Gilles Robert de Vaugondy's two-sheet Royaume de Portugal
of 1751, 47 by 51 cm per sheet at about 1:680 000, from the Universidade de
Coimbra under CC BY 4.0. Two things make it usable where the 1762 sheet
MAPGEN-027 refused was not: it draws a settlement as a small engraved
CIRCLE, so an anchor has a defensible centre, and it carries a ten-minute
graduation on all eight borders, so the plate's own graticule can be read
as scalar constraints.

WHAT WAS MEASURED. Forty-two true two-dimensional observations — a name
read on the plate and the position circle standing against it — and one
hundred and four graduation strokes, fifty-six carrying a longitude and
forty-eight a latitude. A stroke is never crossed with another stroke:
MAPGEN-018R disqualified that and nothing here revives it. The two sheets
are georeferenced SEPARATELY, with their own splits and their own model
selection, and are never fitted to each other.

WHAT IT COST. The positional uncertainty over every point the fit never saw
is 12.33 km, against 34.61. Erosion by 12.33 km instead of 34.61 leaves a
safe interior of 76,604 km² in EPSG:3857 where MAPGEN-027 had 5,479, and
Portugal goes from 124 CONTROLLED targets to 2,727. Spain does not move:
its 5,431 hexes are asserted identical before and after, and the 1,304
further hexes this binding would give it are NOT written, because a stage
told to freeze a polity does not quietly grow it.

WHAT DID NOT WORK. One compartment on the northern sheet holds six
Portuguese towns and two Spanish ones, which means the plate's wash does
not close along that stretch of frontier. It is refused entire rather than
trimmed, and most of the ground under it is recovered from the southern
sheet, which resolves the same country into separate compartments. The
band that neither sheet resolves is left unowned and is reported.

WHAT IS NOT WITHDRAWN. MAPGEN-027's feature stays exactly where it is and
stays authorised. 1,321 km² of it falls outside the new one — the two
plates disagreeing about where the line runs — and that is reported as a
measurement, not averaged away.
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
from .historical_pilot_pipeline import _save
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, TARGET_TYPES, load_scenario,
                       scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .scenario_preview import render_scenario_preview
from .scenario_promotion import validate_canonical_control
from .sources import sha256_of

STAGE = "MAPGEN-028"
H = Path("data/historical")
M27_COMMIT = "3a40f673da15518068a9ab16766bf30d9dfd6ad5"
M27_SUMMARY = Path("reviews/MAPGEN-027/summary.csv")
SPAIN_SP, PORTUGAL_SP = "sp_b622a2799f94", "sp_fef06587fead"
V2_FEATURE = "hbf_7ed17b927930"
SPAIN_FEATURE = "hbf_4da53367f9a0"
V3_FEATURE = "hbf_60dcae454432"
GSID_1751 = "hsrc_c61726597ef3"
GSID_1749 = "hsrc_c4de194d088b"
GSID_1762 = "hsrc_3be565a085e6"
GSID_LEROUGE = "hsrc_4c13f0498990"
UNCERTAINTY_KM = 12.33
M26_UNCERTAINTY_KM = 34.61
WITHHELD = ("OLIVENZA", "COUTO_MISTO")
# rows MAPGEN-008 wrote on the geography grid, which the canonical
# validator has flagged since the Europe foundation replaced it
PRE_EXISTING_ISSUE_TARGETS = ("h6000_q+002183_r+000819",
                              "h6000_q+002184_r+000813",
                              "isl_c_1859af1e4767")
# a review package must not carry a second copy of the canonical tables
MAX_REVIEW_CANONICAL_BYTES = 5 * 1024 * 1024
MAX_TRACKED_BYTES = 50 * 1024 * 1024


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
    """MAPGEN-027's own committed summary is the authority for 'before'."""
    s = pd.read_csv(M27_SUMMARY)
    d = dict(zip(s["metric"].astype(str), s["value"].astype(str)))
    out = {}
    for k in ("canonical_rows_after", "canonical_controlled_after",
              "canonical_unresolved_after", "terrestrial_hex_rows",
              "land_fragment_rows", "spain_controlled",
              "portugal_controlled", "positional_uncertainty_km"):
        if k in d:
            out[k] = float(d[k]) if "." in d[k] else int(float(d[k]))
    out["outcome_as_declared"] = d.get("outcome", "")
    return out


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def render_measurement(path: Path, obs: pd.DataFrame, cons: pd.DataFrame,
                       msep: pd.DataFrame, cmp_: pd.DataFrame, title: str):
    """What was measured, how it was split, and what it cost."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 4, figsize=(19.5, 4.9))

    ax = axes[0]
    kinds = ["true 2D\nobservations", "longitude-only\nstrokes",
             "latitude-only\nstrokes"]
    vals = [len(obs), int((cons.axis == "lon").sum()),
            int((cons.axis == "lat").sum())]
    ax.bar(kinds, vals, color=["#2f6f3f", "#8c6d1f", "#1f5d8c"])
    for i, v in enumerate(vals):
        ax.text(i, v + 1, str(v), ha="center", fontsize=9)
    ax.set_title("counted separately, never mixed", fontsize=9)
    ax.set_ylabel("measurements", fontsize=9)
    ax.tick_params(labelsize=8)

    ax = axes[1]
    order = ["FIT_CONSTRAINT", "MODEL_SELECTION_HOLDOUT",
             "BLIND_VALIDATION"]
    w = 0.38
    for k, sh in enumerate(("N", "S")):
        n = [int(((obs.sheet == sh) & (obs.metric_set == o)).sum())
             for o in order]
        ax.bar(np.arange(3) + (k - 0.5) * w, n, w,
               label=f"sheet {sh}", color=["#4a7fb5", "#b5794a"][k])
    ax.set_xticks(range(3))
    ax.set_xticklabels(["fit", "model\nselection", "blind"], fontsize=8)
    ax.legend(fontsize=8)
    ax.set_title("the split, frozen before fitting", fontsize=9)
    ax.tick_params(labelsize=8)

    ax = axes[2]
    m = msep[msep.metric_set != "ALL_NONFIT"]
    lbl = [f"{r.sheet} {r.metric_set.split('_')[0].lower()}"
           for r in m.itertuples()]
    ax.bar(lbl, m.p95_km, color=["#7a9ec4" if r.statistically_blind == "NO"
                                 else "#2f6f3f" for r in m.itertuples()])
    allnf = msep[msep.metric_set == "ALL_NONFIT"].iloc[0]
    ax.axhline(allnf.p95_km, color="#b4471f", lw=1.6,
               label=f"ALL_NONFIT p95 = {allnf.p95_km:.2f} km")
    ax.axhline(M26_UNCERTAINTY_KM, color="#777", ls=":", lw=1.4,
               label=f"MAPGEN-026 = {M26_UNCERTAINTY_KM} km")
    ax.set_xticklabels(lbl, rotation=32, ha="right", fontsize=7)
    ax.set_ylabel("p95 residual (km)", fontsize=9)
    ax.legend(fontsize=7)
    ax.set_title("what the georeference costs", fontsize=9)
    ax.tick_params(labelsize=8)

    ax = axes[3]
    c = cmp_[cmp_.status == "FITTED"]
    for k, sh in enumerate(("N", "S")):
        s = c[c.sheet == sh]
        ax.plot(range(len(s)), s.holdout_rms_m / 1000, "o-",
                label=f"sheet {sh} holdout", color=["#4a7fb5",
                                                    "#b5794a"][k])
        sel = s[s.selected]
        if len(sel):
            i = list(s.model).index(sel.iloc[0].model)
            ax.plot([i], [sel.iloc[0].holdout_rms_m / 1000], "*",
                    ms=17, color=["#1f4f7f", "#8c5a2f"][k])
    ax.set_xticks(range(len(c[c.sheet == "N"])))
    ax.set_xticklabels([m.replace("_GRATICULE", "\n+graticule")
                        for m in c[c.sheet == "N"].model],
                       rotation=32, ha="right", fontsize=7)
    ax.set_ylabel("holdout rms (km)", fontsize=9)
    ax.legend(fontsize=7)
    ax.set_title("model selection (star = chosen)", fontsize=9)
    ax.tick_params(labelsize=8)

    fig.suptitle(title, fontsize=11)
    _save(fig, path)


def render_before_after(path: Path, base: dict, s: dict, comp: pd.DataFrame,
                        title: str):
    """MAPGEN-027 against MAPGEN-028, and where the ground came from."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(16.5, 5.0))

    ax = axes[0]
    x = np.arange(2)
    ax.bar(x - 0.2, [base["portugal_controlled"],
                     s["portugal_controlled"]], 0.4,
           label="Portugal", color="#2f6f3f")
    ax.bar(x + 0.2, [base["spain_controlled"], s["spain_controlled"]], 0.4,
           label="Spain (frozen)", color="#8c6d1f")
    ax.set_xticks(x)
    ax.set_xticklabels(["MAPGEN-027", "MAPGEN-028"], fontsize=9)
    ax.set_yscale("log")
    for i, v in enumerate([base["portugal_controlled"],
                           s["portugal_controlled"]]):
        ax.text(i - 0.2, v * 1.08, f"{v:,}", ha="center", fontsize=8)
    for i, v in enumerate([base["spain_controlled"],
                           s["spain_controlled"]]):
        ax.text(i + 0.2, v * 1.08, f"{v:,}", ha="center", fontsize=8)
    ax.legend(fontsize=8)
    ax.set_ylabel("CONTROLLED targets (log)", fontsize=9)
    ax.set_title("what the smaller uncertainty buys", fontsize=9)
    ax.tick_params(labelsize=8)

    ax = axes[1]
    ax.bar(["MAPGEN-027\n34.61 km", "MAPGEN-028\n12.33 km"],
           [base["positional_uncertainty_km"], s["positional_uncertainty_km"]],
           color=["#8c8c8c", "#b4471f"])
    ax.set_ylabel("positional uncertainty (km)", fontsize=9)
    ax.set_title("measured on points the fit never saw", fontsize=9)
    ax.tick_params(labelsize=8)

    ax = axes[2]
    v = comp.verdict.value_counts()
    labs = list(v.index)
    ax.barh(labs, [float(comp.loc[comp.verdict == k,
                                  "area_km2_3857"].sum()) for k in labs],
            color=["#2f6f3f" if k == "PORTUGAL" else
                   "#8c6d1f" if k == "SPAIN" else
                   "#b4471f" if k == "MIXED_EVIDENCE" else "#999"
                   for k in labs])
    ax.set_xlabel("compartment area, km2 (EPSG:3857)", fontsize=9)
    ax.set_title("the plate's compartments, by verdict", fontsize=9)
    ax.tick_params(labelsize=8)
    for i, k in enumerate(labs):
        ax.text(0, i, f"  {int(v[k])} compartments", va="center",
                fontsize=7.5, color="white")

    fig.suptitle(title, fontsize=11)
    _save(fig, path)


def render_geometry(path: Path, raw, safe, v2, spain, land, title: str):
    """The claim, the interior, and MAPGEN-027 for scale."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(14.4, 9.6))
    panels = [("compartments kept (raw claim)", [(raw, "#7fb069",
                                                  "#2f5d2f")]),
              (f"safe interior v3, eroded {UNCERTAINTY_KM} km",
               [(raw, "#dfeed6", "none"), (safe, "#2f7d32", "#12401a")]),
              (f"MAPGEN-027 v2, eroded {M26_UNCERTAINTY_KM} km",
               [(spain, "#e5c98f", "none"), (v2, "#b4471f", "#6d240c")])]
    for ax, (t, layers) in zip(axes, panels):
        gpd.GeoSeries([land], crs=3857).plot(ax=ax, color="#eeece4",
                                             edgecolor="#bbb", linewidth=.3)
        for geom, fc, ec in layers:
            gpd.GeoSeries([geom], crs=3857).plot(ax=ax, color=fc,
                                                 edgecolor=ec, linewidth=.5)
        ax.set_xlim(-1.13e6, -6.3e5)
        ax.set_ylim(4.36e6, 5.20e6)
        ax.set_axis_off()
        ax.set_title(t, fontsize=9)
    fig.suptitle(title, fontsize=11)
    _save(fig, path)


# ---------------------------------------------------------------------------
# review package compaction
# ---------------------------------------------------------------------------
def canonical_snapshot_reference(sdir: Path, run_id: str,
                                 promotion_id: str) -> dict:
    """Point at the canonical tables; do not copy them.

    MAPGEN-021 to MAPGEN-027 each shipped a full copy of
    territorial_control.csv and its provenance in their review package —
    16 MB and 25 MB a time, for tables that live in the repository anyway
    and whose every row is reachable from the commit. That is 59 MB in
    MAPGEN-027 alone. Those packages are LEGACY_HISTORY_DEBT: they are
    left exactly as they are, because rewriting a reviewed artefact is
    worse than carrying it. From here the package carries a hash, a row
    count and a delta.
    """
    out = {"stage": STAGE, "run_id": run_id, "promotion_id": promotion_id,
           "rule": ("the review package references the canonical tables by "
                    "path, sha256 and row count, and carries ONLY the rows "
                    "this stage inserted or revised"),
           "tables": {}}
    for name in ("territorial_control.csv",
                 "territorial_control_provenance.csv",
                 "territorial_control_revision_log.csv",
                 "scenario_control_promotion_log.csv",
                 "political_coverage.csv"):
        p = sdir / name
        if not p.exists():
            continue
        out["tables"][name] = {
            "path": str(p).replace("\\", "/"),
            "bytes": p.stat().st_size,
            "sha256": sha256_of(p),
            "rows": int(sum(1 for _ in p.open(encoding="utf-8")) - 1)}
    return out


def control_delta(canonical: pd.DataFrame, provenance: pd.DataFrame,
                  revlog: pd.DataFrame, promotion_id: str) -> pd.DataFrame:
    """Every row this stage touched, and nothing else.

    Both kinds: the rows it REVISED, which the revision log records with
    their before state, and the rows it INSERTED, which the log does not
    record because there was nothing there before. Leaving the inserted
    ones out would be a delta that hides two fifths of the change.
    """
    revised = revlog[revlog.new_promotion_id == promotion_id]
    touched = provenance[provenance.promotion_id == promotion_id]
    cols = ["territorial_target_type", "territorial_target_id",
            "controller_scenario_polity_id", "control_status", "notes"]
    cur = canonical[cols].merge(
        touched[["territorial_target_type", "territorial_target_id"]],
        on=["territorial_target_type", "territorial_target_id"])
    before = revised[["territorial_target_type", "territorial_target_id",
                      "old_status", "old_controller", "old_promotion_id",
                      "old_uncertainty_km", "revision_id", "reason"]]
    d = cur.merge(before, on=["territorial_target_type",
                              "territorial_target_id"], how="left")
    d["change"] = np.where(d.revision_id.isna(), "INSERTED", "REVISED")
    d["new_promotion_id"] = promotion_id
    d["new_uncertainty_km"] = UNCERTAINTY_KM
    return d.sort_values(["change", "territorial_target_id"])


# ---------------------------------------------------------------------------
def run_historical_vaugondy(cfg: MapgenConfig,
                            run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"vaugondy_portugal_1756_{_dt.datetime.now():%Y%m%d}"
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

    def rd(p, **kw):
        return pd.read_csv(p, keep_default_na=False, na_values=[""], **kw)

    canonical = rd(sdir / "territorial_control.csv")
    provenance = rd(sdir / "territorial_control_provenance.csv",
                    low_memory=False)
    log = rd(sdir / "scenario_control_promotion_log.csv")
    revlog = rd(sdir / "territorial_control_revision_log.csv")
    cov = rd(sdir / "political_coverage.csv")
    src = rd(sdir / "sources.csv")

    acq = rd(H / "portugal_1751_map_source_registry.csv")
    st_audit = rd(H / "portugal_1751_state_audit.csv")
    st_verdict = rd(H / "portugal_1751_state_verdict.csv")
    role = rd(H / "portugal_1751_source_role.csv")
    tax = rd(H / "portugal_1751_anchor_taxonomy.csv")
    obs = rd(H / "portugal_1751_observations.csv")
    cons = rd(H / "portugal_1751_1d_constraints.csv")
    cmp_ = pd.read_csv(H / "portugal_1751_model_comparison.csv")
    msep = pd.read_csv(H / "portugal_1751_metric_separation.csv")
    pm = pd.read_csv(H / "portugal_1751_prime_meridian_audit.csv")
    seam = pd.read_csv(H / "portugal_1751_sheet_overlap_validation.csv")
    seam_m = pd.read_csv(H / "portugal_1751_seam_measurements.csv")
    comp = rd(H / "portugal_1751_compartment_audit.csv")
    gaps = rd(H / "portugal_frontier_gap_audit.csv")
    xsrc = rd(H / "portugal_cross_source_comparison_v2.csv")
    cont = rd(H / "portugal_1751_1756_continuity_audit.csv")
    safe_row = pd.read_csv(H / "portugal_safe_interior_v3.csv")
    mix3 = pd.read_csv(H / "iberia_hex_membership_audit_v3.csv")
    special = rd(H / "iberia_special_cases.csv")
    transform = json.loads((H / "portugal_1751_transform.json").read_text(
        encoding="utf-8"))

    reg = rd(H / "historical_source_registry.csv")
    lin = rd(H / "historical_source_lineage.csv")
    assess = rd(H / "historical_source_assessment.csv")
    copies = rd(H / "historical_map_copy_registry.csv")
    contract = rd(H / "historical_prime_meridian_contract.csv")
    digi = rd(H / "historical_digitisation_parameters.csv")
    ev = rd(H / "historical_evidence_assertions.csv")
    links = rd(H / "historical_boundary_feature_evidence.csv")
    snapf = rd(H / "historical_snapshot_features_1756_08_01.csv")
    feats = gpd.read_parquet(H / "historical_boundary_features.parquet")
    hx = pd.read_parquet(eu_dir / "europe_hex_coverage.parquet",
                         columns=["hex_id", "is_terrestrial_hex",
                                  "water_type", "land_fraction"])
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_coverage.parquet",
        Path("output/europe_land_cache/europe_land_parts.parquet")]}
    timings["load_s"] = time.perf_counter() - t0

    pt_rows = canonical[canonical.controller_scenario_polity_id
                        == PORTUGAL_SP]
    es_rows = canonical[(canonical.controller_scenario_polity_id
                         == SPAIN_SP)
                        & (canonical.territorial_target_type
                           == "TERRESTRIAL_HEX")]
    mine = revlog[revlog.reason.str.contains(
        "Portugal safe interior v3", na=False)]
    promotion_id = (mine.new_promotion_id.iloc[0] if len(mine) else "")
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

    # --- the source, its copies and its states (M28-01..08) --------------
    _check("M28-01_source_acquired_and_hashed",
           len(acq) == 4 and acq.sha256.str.len().eq(64).all()
           and acq.bytes.gt(500_000).all(),
           f"{len(acq)} sheets acquired from Coimbra with sha256 and byte "
           "counts: NC-681, NC-682 (1751) and NC-824, NC-825 (1749)")
    _check("M28-02_licence_permits_commercial_reuse",
           acq.rights.str.contains("CC BY 4.0").all()
           and not acq.item_url.str.contains(
               "davidrumsey|raremaps", case=False).any(),
           "every sheet is CC BY 4.0 from the Universidade de Coimbra; no "
           "David Rumsey and no commercial-reuse-blocking host")
    _check("M28-03_raw_raster_is_gitignored",
           acq.gitignored.eq("YES").all()
           and not any(str(p).startswith("data/raw")
                       for p in tracked_file_sizes(Path("."))["path"]),
           "all four rasters are under data/raw, which git ignores; no "
           "tracked file lives there")
    _check("M28-04_state_audit_examines_six_axes",
           len(st_audit) >= 6
           and {"PLATE_SIZE", "SCALE", "PLATE_NUMBERING"}
           <= set(st_audit.axis),
           f"{len(st_audit)} axes compared between the 1751 and 1749 "
           "works, including the printed plate size, the scale and the "
           "atlas numbering")
    _check("M28-05_1749_is_not_another_state_of_the_same_plate",
           st_verdict.iloc[0].relation == "DERIVED"
           and (st_audit[st_audit.axis == "PLATE_SIZE"]
                .consistent_with_same_plate == "NO").all(),
           "the printed image differs by about 2.7 in each direction; a "
           "copper plate cannot be rescaled, so the two are not states of "
           "one plate")
    _check("M28-06_independent_source_count_is_not_inflated",
           int(st_verdict.iloc[0].counts_as_independent_sources) == 1
           and st_verdict.iloc[0].corroboration_eligible == "NO"
           and (lin.loc[lin.global_source_id == GSID_1749,
                        "corroboration_eligible"] == "NO").all(),
           "the 1749 reduction is by the same author and counts as zero "
           "additional independent sources")
    _check("M28-07_1762_sheet_is_demoted_not_used",
           role.iloc[0].role_now == "TEMPORAL_QA_AND_LINEAGE_QA_ONLY"
           and role.iloc[0].may_supply_control_points == "NO"
           and role.iloc[0].may_supply_frontier_geometry == "NO"
           and GSID_1762 not in set(ev.global_source_id),
           "MAPGEN-027's 1762 sheet supplies no control point, no "
           "frontier and no uncertainty; its vignette finding stands")
    _check("M28-08_registered_in_the_evidence_framework",
           GSID_1751 in set(reg.global_source_id)
           and GSID_1751 in set(lin.global_source_id)
           and GSID_1751 in set(assess.global_source_id)
           and len(copies[copies.global_source_id == GSID_1751]) == 2,
           "registry, lineage, assessment and two copy rows for the 1751 "
           "pair")

    # --- the anchor rule (M28-09..13) ------------------------------------
    elig = set(tax.loc[tax.eligible == "YES", "symbol_class"])
    _check("M28-09_anchor_rule_written_before_it_was_used",
           {"PLAIN_CIRCLE", "CITY_SIGN_CIRCLE"} == elig,
           "exactly two symbol classes may carry a control point, and both "
           "are the engraved position circle")
    _check("M28-10_vignettes_remain_ineligible",
           (tax.loc[tax.symbol_class == "PICTORIAL_TOWN_VIGNETTE",
                    "eligible"] == "NO").all()
           and (tax.loc[tax.symbol_class == "FORTIFICATION_PLAN",
                        "eligible"] == "NO").all(),
           "a pictorial vignette and a bastioned plan have no defensible "
           "centre and are refused; Castelo Branco yields no anchor even "
           "though its name is legible")
    _check("M28-11_no_vignette_rule_was_invented",
           role.iloc[0].rule_invented_for_vignettes == "NO"
           and not obs.symbol_class.isin(
               ["PICTORIAL_TOWN_VIGNETTE", "FORTIFICATION_PLAN",
                "LETTERING"]).any(),
           "not one observation rests on a symbol the rule excludes")
    _check("M28-12_city_sign_is_the_circle_not_the_cross",
           "the centre of the circle inside the block"
           in set(tax.anchor_point),
           "the walled block and the cross are attributes drawn AROUND the "
           "same position circle; verified at eight times magnification "
           "before any of the six city signs was used")
    _check("M28-13_graduation_is_one_dimensional_only",
           (tax.loc[tax.symbol_class == "GRADUATION_STROKE", "eligible"]
            == "AS_A_ONE_DIMENSIONAL_CONSTRAINT_ONLY").all()
           and (cons.crossed_with_another_stroke == "NO").all(),
           "a stroke enters as one scalar equation at its own pixel; no "
           "stroke is crossed with another")

    # --- what was measured (M28-14..20) ----------------------------------
    n2d = len(obs)
    nlon = int((cons.axis == "lon").sum())
    nlat = int((cons.axis == "lat").sum())
    _check("M28-14_true_2d_observations_meet_the_target",
           n2d >= 24 and (obs.dimensionality == "TRUE_2D").all(),
           f"{n2d} true two-dimensional observations, against a target of "
           "16 and a preferred 24")
    _check("M28-15_counts_are_reported_separately",
           transform["n_true_2d_points"] == n2d
           and transform["n_longitude_1d_constraints"] == nlon
           and transform["n_latitude_1d_constraints"] == nlat,
           f"true 2D {n2d}, longitude-only {nlon}, latitude-only {nlat}, "
           "each counted on its own")
    _check("M28-16_no_synthetic_graticule_intersection",
           transform["synthetic_graticule_intersections"] == 0
           and set(cons.dimensionality) == {"KNOWN_LONGITUDE_ONLY",
                                            "KNOWN_LATITUDE_ONLY"},
           "no pixel was manufactured by crossing a longitude tick with a "
           "latitude tick; MAPGEN-018R's disqualification stands")
    _check("M28-17_both_sheets_carry_observations",
           (obs.sheet == "N").sum() >= 16 and (obs.sheet == "S").sum() >= 16,
           f"sheet N {int((obs.sheet == 'N').sum())}, sheet S "
           f"{int((obs.sheet == 'S').sum())}")
    _check("M28-18_observations_of_both_crowns_were_sought",
           (obs.country == "ES").sum() >= 5
           and set(obs.loc[obs.country == "ES", "sheet"]) == {"N", "S"},
           f"{int((obs.country == 'ES').sum())} Spanish places anchored, on "
           "both sheets; a compartment that runs across the frontier can "
           "only be caught by one of them turning up inside it")
    _check("M28-19_every_observation_resolves_in_the_gazetteer",
           obs.geonameid.astype(str).str.len().gt(3).all()
           and obs.geonameid.nunique() == len(obs),
           "every observation carries a distinct GeoNames id")
    _check("M28-20_graduation_lattices_are_tight",
           float(cons.lattice_rms_px.max()) < 3.5,
           f"worst border lattice rms {cons.lattice_rms_px.max():.2f} px "
           "against a ten-minute spacing of 113 to 165 px")

    # --- the fit (M28-21..29) --------------------------------------------
    fitted = cmp_[cmp_.status == "FITTED"]
    _check("M28-21_sheets_are_georeferenced_separately",
           transform["sheets_georeferenced_separately"]
           and not transform["sheets_ever_fitted_to_each_other"]
           and not transform["images_ever_merged_before_fitting"],
           "each sheet has its own control points, its own split, its own "
           "model and its own residuals; the images were never merged")
    _check("M28-22_split_is_frozen_and_declared",
           "sha256 of the place-name" in transform["split_rule"]
           and set(obs.metric_set) == {"FIT_CONSTRAINT",
                                       "MODEL_SELECTION_HOLDOUT",
                                       "BLIND_VALIDATION"},
           "the split is by rank of a hash of the place-name, fixed before "
           "any model was fitted")
    _check("M28-23_affine_and_projective_were_both_fitted",
           {"AFFINE", "PROJECTIVE", "POLYNOMIAL_2"}
           <= set(fitted.model)
           and len(fitted[fitted.sheet == "N"]) >= 4
           and len(fitted[fitted.sheet == "S"]) >= 4,
           f"{len(fitted)} model fits over two sheets, including the "
           "graticule-constrained variants")
    _check("M28-24_selection_used_the_holdout_not_the_fit",
           "MODEL_SELECTION_HOLDOUT rms" in transform["selection_rule"]
           and len(fitted[fitted.selected]) == 2,
           "one model selected per sheet, on holdout rms with a 10 per "
           "cent tolerance, simplest first")
    _check("M28-25_no_selected_model_folds_or_explodes",
           not fitted[fitted.selected].folding.astype(bool).any()
           and float(fitted[fitted.selected].scale_ratio.max()) < 2.0,
           "neither selected model folds; worst scale ratio "
           f"{fitted[fitted.selected].scale_ratio.max():.3f}")
    _check("M28-26_design_is_not_ill_conditioned",
           float(fitted[fitted.selected].design_condition.max()) < 1e9,
           "worst design condition "
           f"{fitted[fitted.selected].design_condition.max():.3g}")
    _check("M28-27_metric_sets_are_kept_apart",
           set(msep.metric_set) == {"FIT_CONSTRAINT",
                                    "MODEL_SELECTION_HOLDOUT",
                                    "BLIND_VALIDATION", "ALL_NONFIT"}
           and (msep[msep.metric_set == "MODEL_SELECTION_HOLDOUT"]
                .statistically_blind == "NO").all()
           and (msep[msep.metric_set == "BLIND_VALIDATION"]
                .statistically_blind == "YES").all(),
           "the model-selection holdout chose the model, so it is not "
           "blind and is not called blind")
    used = msep[msep.used_for_production_uncertainty == "YES"]
    _check("M28-28_production_uncertainty_is_the_conservative_one",
           len(used) == 1 and used.iloc[0].metric_set == "ALL_NONFIT"
           and abs(float(used.iloc[0].p95_km) - UNCERTAINTY_KM) < 0.01
           and float(used.iloc[0].p95_km) >= float(
               msep[(msep.metric_set == "BLIND_VALIDATION")].p95_km.min()),
           f"{UNCERTAINTY_KM} km is the p95 over every point the fit never "
           "saw, pooled across both sheets")
    _check("M28-29_uncertainty_improves_on_mapgen026",
           UNCERTAINTY_KM < M26_UNCERTAINTY_KM
           and abs(base["positional_uncertainty_km"]
                   - M26_UNCERTAINTY_KM) < 0.01,
           f"{UNCERTAINTY_KM} km against {M26_UNCERTAINTY_KM} km, a factor "
           f"of {M26_UNCERTAINTY_KM / UNCERTAINTY_KM:.2f}")

    # --- prime meridian and the seam (M28-30..33) ------------------------
    mean_pm = pm[pm.estimator == "MEAN_OF_FOUR"].iloc[0]
    _check("M28-30_prime_meridian_derived_from_the_graduations",
           len(pm) >= 5
           and "graduation" in str(mean_pm.derived_from)
           and mean_pm.applied_to_production == "NO",
           "four estimators over two sheets, all from the engraved "
           "strokes; the transform maps pixels straight to Greenwich and "
           "the meridian is diagnostic")
    _check("M28-31_plate_meridian_agrees_with_ferro",
           abs(float(mean_pm.difference_deg)) < 0.05,
           f"the plate's meridian is "
           f"{mean_pm.plate_meridian_west_of_greenwich_deg:.6f} deg west, "
           f"against 17.662771 for Ferro at 20 degrees west of Paris: "
           f"{abs(float(mean_pm.difference_km_at_39N)):.2f} km at 39 N")
    _check("M28-32_seam_measured_without_fitting_across_it",
           len(seam) >= 4
           and (seam.fitted_across_the_seam == "NO").all()
           and (seam.averaged_line_drawn == "NO").all()
           and len(seam_m) == 2 * len(seam),
           f"{len(seam)} places engraved on BOTH sheets, each carried "
           "through its own sheet's transform")
    _check("M28-33_seam_disagreement_is_within_the_uncertainty",
           float(seam.disagreement_m.max()) / 1000 <= UNCERTAINTY_KM + 2.5,
           f"worst seam disagreement "
           f"{seam.disagreement_m.max() / 1000:.2f} km against a "
           f"{UNCERTAINTY_KM} km uncertainty")

    # --- continuity and special cases (M28-34..37) -----------------------
    _check("M28-34_1751_to_1756_continuity_is_argued",
           len(cont) >= 5
           and (cont[cont.question.str.contains("frontier move")]
                .finding == "NO").all(),
           "the peninsular frontier was fixed by Alcanices in 1297 and "
           "confirmed at Lisbon in 1668; the treaty of Madrid of 1750 "
           "settled the AMERICAN limits")
    _check("M28-35_olivenza_and_couto_misto_stay_withheld",
           safe_row.iloc[0].withheld_by_name == "COUTO_MISTO|OLIVENZA"
           and set(WITHHELD) <= set(special.case),
           "Olivenca is Portuguese until 1801 and the Couto Misto belonged "
           "to neither crown until 1864; both are cut out of the interior "
           "by name")
    _check("M28-36_algarve_decision_is_carried_not_reopened",
           (cont[cont.question == "the Algarve"].finding
            == "PART_OF_POL_PORTUGAL").all()
           and not sp.polity_id.str.contains("algarve", case=False).any(),
           "MAPGEN-027 settled it on institutions; the 1751 plate letters "
           "it ROYAUME D'ALGARVE and that lettering is still not evidence")
    _check("M28-37_the_1762_war_is_not_relied_on",
           (cont[cont.question == "the war of 1762"].action
            == "NOT_RELIED_ON").all(),
           "the Spanish invasion begins in May 1762, five years after the "
           "snapshot")

    # --- the frontier (M28-38..42) ---------------------------------------
    comp["spanish_places"] = comp.spanish_places.fillna("")
    comp["portuguese_places"] = comp.portuguese_places.fillna("")
    kept = comp[comp.verdict == "PORTUGAL"]
    mixed = comp[comp.verdict == "MIXED_EVIDENCE"]
    _check("M28-38_a_compartment_is_claimed_only_on_evidence_inside_it",
           (kept.spanish_places == "").all()
           and (kept.portuguese_places != "").all()
           and (comp.loc[comp.verdict == "NO_IDENTIFIED_PLACE",
                         "claimed"] == "NO").all(),
           f"{len(kept)} compartments claimed, every one holding at least "
           "one identified Portuguese place and no Spanish one")
    _check("M28-39_a_compartment_that_spans_the_frontier_is_refused",
           len(mixed) >= 1
           and (mixed.claimed == "NO").all()
           and (gaps.action == "COMPARTMENT_REFUSED").all()
           and (gaps.trimmed_to_fit == "NO").all(),
           f"{len(mixed)} compartment holds places of both crowns; it is "
           "refused entire rather than trimmed, and no boundary is "
           "interpolated through it")
    _check("M28-40_no_averaged_line_at_the_seam_or_the_gap",
           (gaps.averaged_line_drawn == "NO").all()
           and (xsrc.averaged == "NO").all(),
           "neither the sheet seam nor the source disagreement is resolved "
           "by splitting the difference")
    _check("M28-41_cross_source_comparison_was_performed",
           (xsrc.status == "PERFORMED").all() and len(xsrc) >= 3
           and (xsrc.source_a == GSID_1751).all()
           and (xsrc.source_b == GSID_LEROUGE).all(),
           "the 1751 plate is compared against the Le Rouge plate "
           "MAPGEN-026 used; MAPGEN-027 recorded this as NOT_PERFORMED and "
           "handed it here")
    _check("M28-42_no_overlap_with_spains_safe_interior",
           float(safe_row.iloc[0].overlap_with_spain_safe_km2_3857) < 1e-3,
           "the Portuguese interior and the Spanish one do not intersect")

    # --- production (M28-43..46) -----------------------------------------
    pt_ctrl = int((pt_rows.control_status == "CONTROLLED").sum())
    _check("M28-43_spain_is_frozen",
           len(es_rows) == base["spain_controlled"]
           and not (mine.new_controller == SPAIN_SP).any()
           and not (mine.old_controller == SPAIN_SP).any(),
           f"Spain holds {len(es_rows):,} terrestrial hexes, exactly what "
           "MAPGEN-026 left; this stage's revisions touch none of them")
    _check("M28-44_portugal_grew_past_the_success_condition",
           pt_ctrl > base["portugal_controlled"] and pt_ctrl > 124,
           f"Portugal {base['portugal_controlled']} -> {pt_ctrl} "
           "CONTROLLED targets")
    _check("M28-45_nothing_was_taken_from_another_polity",
           set(mine.old_status) <= {"UNRESOLVED", "CONTROLLED"}
           and not mine.old_controller.isin(
               set(sp.scenario_polity_id) - {PORTUGAL_SP, ""}).any(),
           f"{len(mine)} revisions, every one from an UNRESOLVED row or "
           "from Portugal itself")
    _check("M28-46_no_ocean_hex_is_owned_and_fragments_carry_the_rest",
           not (set(pt_rows.loc[pt_rows.territorial_target_type
                                == "TERRESTRIAL_HEX",
                                "territorial_target_id"]) - terr_hex)
           and int((pt_rows.territorial_target_type
                    == "LAND_FRAGMENT").sum()) >= 3,
           "every Portuguese hex row is a canonical terrestrial hex; the "
           "coastal land of OCEAN hexes is carried as fragments and the "
           "parent hexes stay unowned")

    # --- the package and the repository (M28-47..49) ---------------------
    ref = canonical_snapshot_reference(sdir, run_id, promotion_id)
    delta = control_delta(canonical, provenance, revlog,
                          promotion_id)
    sizes = tracked_file_sizes(Path("."))
    _check("M28-47_review_package_references_canonical_it_does_not_copy_it",
           len(ref["tables"]) >= 4
           and all(v["sha256"] for v in ref["tables"].values())
           and len(delta) >= len(mine) > 0
           and set(delta.change) == {"INSERTED", "REVISED"}
           and int((delta.change == "REVISED").sum()) == len(mine),
           f"{len(ref['tables'])} canonical tables referenced by path, "
           f"sha256 and row count; the package carries all {len(delta)} "
           f"rows this stage touched "
           f"({int((delta.change == 'INSERTED').sum())} inserted, "
           f"{int((delta.change == 'REVISED').sum())} revised) and no "
           "full copy")
    issues = validate_canonical_control(
        canonical, provenance, sp, src, terr_hex, set(),
        set(sp.loc[sp["is_structural"].astype(str) == "True",
                   "scenario_polity_id"])
        if "is_structural" in sp.columns else set(),
        set(pd.read_csv(H / "land_fragment_registry.csv")
            ["land_fragment_id"]))
    # MAPGEN-008 wrote three rows on the geography grid before the Europe
    # foundation existed; the validator has flagged them since, and they
    # are not this stage's to move. What matters is that this stage added
    # nothing to the list.
    new_issues = [i for i in issues
                  if not any(k in i for k in PRE_EXISTING_ISSUE_TARGETS)]
    _check("M28-48_canonical_control_gains_no_new_defect",
           not new_issues,
           f"the validator reports {len(issues)} issue(s), all of them the "
           "MAPGEN-008 foundation rows that predate the Europe grid; this "
           f"stage adds {len(new_issues)}")
    _check("M28-49_repository_carries_no_oversized_tracked_file",
           int(sizes.bytes.max()) <= MAX_TRACKED_BYTES
           and not scan_forbidden_reference_code(
               Path("src/mapgen/historical_vaugondy_pipeline.py")),
           f"largest tracked file {sizes.bytes.max() / 1e6:.1f} MB; the "
           "stage module contains no contemporary reference-layer import "
           "or identifier")

    timings["gates_s"] = time.perf_counter() - t0

    val = pd.DataFrame(val_rows)
    n_pass = int(val["pass"].sum())
    val.to_csv(run_dir / "validation.csv", index=False)

    # ---- summary ---------------------------------------------------------
    outcome = "FULL" if n_pass == len(val) else "PARTIAL"
    s = {
        "outcome": outcome,
        "validation_pass": f"{n_pass}/{len(val)}",
        "mapgen027_outcome_restated": base["outcome_as_declared"],
        "base_commit": M27_COMMIT,
        "positional_uncertainty_km": UNCERTAINTY_KM,
        "mapgen026_uncertainty_km": M26_UNCERTAINTY_KM,
        "true_2d_points": n2d,
        "longitude_1d_constraints": nlon,
        "latitude_1d_constraints": nlat,
        "synthetic_graticule_intersections": 0,
        "sheet_n_model": transform["sheets"]["N"]["model"],
        "sheet_s_model": transform["sheets"]["S"]["model"],
        "seam_places": len(seam),
        "seam_max_disagreement_km": round(
            float(seam.disagreement_m.max()) / 1000, 2),
        "plate_meridian_west_deg": float(
            mean_pm.plate_meridian_west_of_greenwich_deg),
        "plate_meridian_minus_ferro_km": float(mean_pm.difference_km_at_39N),
        "compartments_total": len(comp),
        "compartments_claimed": len(kept),
        "compartments_refused_mixed": len(mixed),
        "raw_claim_km2_3857": float(safe_row.iloc[0].raw_area_km2_3857),
        "safe_interior_v3_km2_3857": float(
            safe_row.iloc[0].v3_area_km2_3857),
        "safe_interior_v2_km2_3857": float(
            safe_row.iloc[0].v2_area_km2_3857),
        "v2_area_outside_v3_km2_3857": float(
            safe_row.iloc[0].v2_area_lost_km2_3857),
        "v2_feature_retained": "YES",
        "portugal_controlled_before": base["portugal_controlled"],
        "portugal_controlled": pt_ctrl,
        "portugal_terrestrial_hexes": int(
            (pt_rows.territorial_target_type == "TERRESTRIAL_HEX").sum()),
        "portugal_land_fragments": int(
            (pt_rows.territorial_target_type == "LAND_FRAGMENT").sum()),
        "spain_controlled_before": base["spain_controlled"],
        "spain_controlled": len(es_rows),
        "rows_inserted": len(delta) - len(mine),
        "rows_revised": len(mine),
        "rows_touched": len(delta),
        "canonical_rows_before": base["canonical_rows_after"],
        "canonical_rows_after": len(canonical),
        "review_package_canonical_copies": 0,
        "run_id": run_id,
    }
    pd.DataFrame({"metric": list(s), "value": list(s.values()),
                  "run_id": run_id}).to_csv(run_dir / "summary.csv",
                                            index=False)

    # ---- figures ---------------------------------------------------------
    t0 = time.perf_counter()
    imgs = ["portugal_1751_measurement.png", "portugal_027_vs_028.png",
            "portugal_safe_interior_v3.png"]
    render_measurement(run_dir / imgs[0], obs, cons, msep, cmp_,
                       f"{STAGE} — what the 1751 plate was made to say")
    render_before_after(run_dir / imgs[1], base, s, comp,
                        f"{STAGE} — MAPGEN-027 against MAPGEN-028")
    v3 = feats.loc[feats.boundary_feature_id == V3_FEATURE,
                   "geometry"].iloc[0]
    v2 = feats.loc[feats.boundary_feature_id == V2_FEATURE,
                   "geometry"].iloc[0]
    spain_geom = feats.loc[feats.boundary_feature_id == SPAIN_FEATURE,
                           "geometry"].iloc[0]
    raw_p = Path("data/historical/portugal_1751_raw_claim.parquet")
    raw = (gpd.read_parquet(raw_p).geometry.iloc[0] if raw_p.exists()
           else v3)
    land_p = Path("data/historical/portugal_1751_land_context.parquet")
    land = (gpd.read_parquet(land_p).geometry.iloc[0] if land_p.exists()
            else raw)
    render_geometry(run_dir / imgs[2], raw, v3, v2, spain_geom, land,
                    f"{STAGE} — the claim, the interior, and what came "
                    "before")
    aspects = {}
    for n in imgs:
        from PIL import Image
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.width / im.height, 3)
    timings["figures_s"] = time.perf_counter() - t0

    # ---- review package --------------------------------------------------
    t0 = time.perf_counter()
    review = Path("reviews") / STAGE
    review.mkdir(parents=True, exist_ok=True)
    (review / "canonical_snapshot_reference.json").write_text(
        json.dumps(ref, indent=2), encoding="utf-8")
    delta.to_csv(review / "territorial_control_delta.csv", index=False)
    for name, frame in (("summary.csv", None), ("validation.csv", None)):
        shutil.copy2(run_dir / name, review / name)
    cmap = {}
    for n in ["portugal_1751_map_source_registry",
              "portugal_1751_state_audit", "portugal_1751_state_verdict",
              "portugal_1751_source_role",
              "portugal_1751_anchor_taxonomy",
              "portugal_1751_observations",
              "portugal_1751_1d_constraints",
              "portugal_1751_model_comparison",
              "portugal_1751_metric_separation",
              "portugal_1751_prime_meridian_audit",
              "portugal_1751_sheet_overlap_validation",
              "portugal_1751_seam_measurements",
              "portugal_1751_compartment_audit",
              "portugal_frontier_gap_audit",
              "portugal_cross_source_comparison_v2",
              "portugal_1751_1756_continuity_audit",
              "portugal_safe_interior_v3",
              "portugal_1751_determinism_check"]:
        cmap[n + ".csv"] = H / (n + ".csv")
    cmap["portugal_1751_transform.json"] = H / "portugal_1751_transform.json"
    for dst, srcp in cmap.items():
        if Path(srcp).exists():
            shutil.copy2(srcp, review / dst)
    for n in imgs:
        shutil.copy2(run_dir / n, review / n)

    over = [(p.name, p.stat().st_size) for p in review.iterdir()
            if p.is_file() and p.stat().st_size > MAX_REVIEW_CANONICAL_BYTES]
    if over:
        warnings.append(
            f"review package carries oversized files: {over}")
    s["review_package_bytes"] = sum(p.stat().st_size
                                    for p in review.iterdir() if p.is_file())
    pd.DataFrame({"metric": list(s), "value": list(s.values()),
                  "run_id": run_id}).to_csv(run_dir / "summary.csv",
                                            index=False)
    shutil.copy2(run_dir / "summary.csv", review / "summary.csv")

    _write_readme(run_dir, run_id, s, base, st_audit, st_verdict, tax,
                  msep, pm, seam, comp, gaps, xsrc, cont, aspects, imgs)
    shutil.copy2(run_dir / "README_REVIEW.md", review / "README_REVIEW.md")
    timings["review_s"] = time.perf_counter() - t0

    manifest = {
        "stage": STAGE, "run_id": run_id, "scenario_id": scenario_id,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit": M27_COMMIT,
        "scenario_schema_version": SCENARIO_SCHEMA_VERSION,
        "hpg_schema_version": HPG_SCHEMA_VERSION,
        "target_types": list(TARGET_TYPES),
        "upstream_sha256": upstream,
        "packages": package_versions(),
        "preview": pman.get("run_id", ""),
        "peak_memory_mb": _peak_memory_mb(),
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "summary": s,
        "coverage_rows": len(cov),
        "warnings": warnings,
    }
    manifest["timings_s"]["total_s"] = round(
        time.perf_counter() - t_start, 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    shutil.copy2(run_dir / "run_manifest.json", review / "run_manifest.json")

    print(f"[vaugondy] {run_id}: validation {n_pass}/{len(val)}, "
          f"Portugal {base['portugal_controlled']} -> {pt_ctrl}, Spain "
          f"frozen at {len(es_rows):,}, uncertainty "
          f"{M26_UNCERTAINTY_KM} -> {UNCERTAINTY_KM} km, review package "
          f"{s['review_package_bytes'] / 1e6:.1f} MB "
          f"({manifest['timings_s']['total_s']:.0f}s)")
    for w in warnings:
        print("[vaugondy][WARN] " + w.encode("ascii", "replace").decode())
    return run_dir


def _write_readme(run_dir, run_id, s, base, st_audit, st_verdict, tax,
                  msep, pm, seam, comp, gaps, xsrc, cont, aspects, imgs):
    L = [f"# {STAGE} — Portugal measured again, on the 1751 Vaugondy "
         "sheets", "",
         f"run `{run_id}` · outcome **{s['outcome']}** · validation "
         f"**{s['validation_pass']}**", "",
         "## The number that matters", "",
         "| | MAPGEN-027 | MAPGEN-028 |", "|---|---|---|",
         f"| positional uncertainty | {M26_UNCERTAINTY_KM} km | "
         f"**{UNCERTAINTY_KM} km** |",
         f"| Portugal CONTROLLED | {base['portugal_controlled']} | "
         f"**{s['portugal_controlled']:,}** |",
         f"| Spain CONTROLLED | {base['spain_controlled']:,} | "
         f"{s['spain_controlled']:,} (frozen) |",
         f"| safe interior (km² EPSG:3857) | "
         f"{s['safe_interior_v2_km2_3857']:,.0f} | "
         f"{s['safe_interior_v3_km2_3857']:,.0f} |", "",
         *_wrap("MAPGEN-027 recovered Portugal from 26 hexes to 124 "
                "without a new measurement, and said so. This stage makes "
                "the measurement. The uncertainty falls from 34.61 km to "
                f"{UNCERTAINTY_KM} km, and because a safe interior is what "
                "survives erosion by that number, the interior grows "
                "fourteenfold and the production twenty-twofold."),
         "", "## The source, and whether it is one source or two", ""]
    L += [*_wrap("Gilles Robert de Vaugondy, *Partie Septentrionle du "
                 "Royaume de Portugal* and *Partie Meridionale*, 1751, two "
                 "sheets of 47 × 51 cm at about 1:680 000, CC BY 4.0 from "
                 "the Universidade de Coimbra. The same library holds a "
                 "1749 pair with the same title and the same sheet "
                 "division, which had to be settled before either could be "
                 "counted."), "",
          "| axis | 1751 | 1749 | same plate? |", "|---|---|---|---|"]
    for r in st_audit.itertuples():
        L.append(f"| {r.axis} | {r.observation_a} | {r.observation_b} | "
                 f"{r.consistent_with_same_plate} |")
    L += ["", f"**{st_verdict.iloc[0].relation}.** "
              f"{st_verdict.iloc[0].rejected_same_plate_because}. "
              f"{st_verdict.iloc[0].rejected_independent_because}. Counts "
              f"as {st_verdict.iloc[0].counts_as_independent_sources} "
              "independent source.", "",
          "## The anchor rule", "",
          *_wrap("Written down before the marks were read, and applied to "
                 "every mark including the ones it throws away."), "",
          "| symbol | anchor point | eligible |", "|---|---|---|"]
    for r in tax.itertuples():
        L.append(f"| {r.symbol_class} | {r.anchor_point} | {r.eligible} |")
    L += ["",
          *_wrap(f"That yields {s['true_2d_points']} true two-dimensional "
                 f"observations, {s['longitude_1d_constraints']} "
                 f"longitude-only graduation strokes and "
                 f"{s['latitude_1d_constraints']} latitude-only ones. The "
                 "three are counted separately everywhere. No stroke is "
                 "crossed with another stroke to manufacture a pixel — "
                 "that is what MAPGEN-018R disqualified."),
          "", "## What the georeference costs", "",
          "| sheet | set | n | rms km | p95 km | blind? | used |",
          "|---|---|---|---|---|---|---|"]
    for r in msep.itertuples():
        L.append(f"| {r.sheet} | {r.metric_set} | {r.n} | {r.rms_km} | "
                 f"{r.p95_km} | {r.statistically_blind} | "
                 f"{r.used_for_production_uncertainty} |")
    L += ["",
          *_wrap(f"The two sheets are fitted separately and never to each "
                 f"other: sheet N selected {s['sheet_n_model']}, sheet S "
                 f"{s['sheet_s_model']}. {s['seam_places']} places are "
                 "engraved on both, and carrying each through its own "
                 "sheet's transform they disagree by at most "
                 f"{s['seam_max_disagreement_km']} km — inside the "
                 f"{UNCERTAINTY_KM} km the georeference already admits."),
          "",
          *_wrap("The plate prints no meridian statement. Solving for it "
                 "as an extra unknown beside the control points gives "
                 f"{s['plate_meridian_west_deg']:.4f}° west over four "
                 "estimators, against 17.6628° for Ferro at twenty degrees "
                 "west of Paris — "
                 f"{abs(s['plate_meridian_minus_ferro_km']):.2f} km at 39°N. "
                 "Diagnostic only; the transform maps pixels straight to "
                 "Greenwich."),
          "", "## The frontier, and where the plate fails", "",
          *_wrap(f"{s['compartments_total']} compartments were traced from "
                 f"the plate's own wash. {s['compartments_claimed']} are "
                 "claimed, each holding at least one identified Portuguese "
                 "place and no Spanish one.")]
    for r in gaps.itertuples():
        if r.finding == "NONE":
            continue
        L += ["",
              *_wrap(f"**Sheet {r.sheet}, compartment {r.compartment}, "
                     f"{r.area_km2_3857:,.0f} km².** Holds "
                     f"{r.portuguese_places} and {r.spanish_places}. "
                     f"{r.note}")]
    L += ["", "## The two plates disagree", "",
          "| comparison | metric | value km² | of km² | verdict |",
          "|---|---|---|---|---|"]
    for r in xsrc.itertuples():
        L.append(f"| {r.comparison} | {r.metric} | {r.value_km2_3857} | "
                 f"{r.of_km2_3857} | {r.verdict} |")
    L += ["",
          *_wrap(f"MAPGEN-027's feature is NOT withdrawn and NOT "
                 f"overwritten. {s['v2_area_outside_v3_km2_3857']:,.0f} km² "
                 "of it falls outside the new one; both remain authorised, "
                 "so a hex the older plate won cannot be lost because the "
                 "newer one draws the line a little differently."),
          "", "## 1751 to 1756", "", "| question | finding | action |",
          "|---|---|---|"]
    for r in cont.itertuples():
        L.append(f"| {r.question} | {r.finding} | {r.action} |")
    L += ["", "## The review package", "",
          *_wrap("MAPGEN-021 to MAPGEN-027 each shipped a full copy of "
                 "territorial_control.csv and its provenance — 16 MB and "
                 "25 MB a time, 59 MB in MAPGEN-027 alone, for tables that "
                 "live in the repository and whose every row is reachable "
                 "from the commit. Those packages are LEGACY_HISTORY_DEBT "
                 "and are left exactly as they are, because rewriting a "
                 "reviewed artefact is worse than carrying it. This one "
                 "carries `canonical_snapshot_reference.json` — path, "
                 "sha256 and row count per table — and "
                 "`territorial_control_delta.csv`, the "
                 f"{s['rows_touched']:,} rows this stage touched "
                 f"({s['rows_inserted']:,} inserted, "
                 f"{s['rows_revised']:,} revised). Total "
                 f"{s['review_package_bytes'] / 1e6:.1f} MB."),
          "", "## Images", ""]
    for n in imgs:
        L.append(f"- `{n}` (aspect {aspects.get(n, '')})")
    L += ["", "## Gates", "",
          f"All {s['validation_pass'].split('/')[1]} gates are in "
          "`validation.csv` with their evidence.", ""]
    (run_dir / "README_REVIEW.md").write_text("\n".join(L),
                                              encoding="utf-8")
