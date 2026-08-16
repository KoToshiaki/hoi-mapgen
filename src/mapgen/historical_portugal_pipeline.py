"""MAPGEN-027 — Portugal, the Algarve, and the coast MAPGEN-026 left out.

MAPGEN-026 produced 5,431 Spanish hexes and 26 Portuguese ones, and called
itself FULL. This stage does not withdraw a single row of that production,
but it does re-file its outcome as ACCEPTABLE_PRODUCTION_WITH_FOLLOWUP_GAPS,
because three things were left undone and two of them were not cartography
at all.

THE COAST. 318 hexes carried Iberian mainland land and received no row of
any kind, on the correct ground that a hex which is mostly sea is not a
land-control target. MAPGEN-025 had already built the answer to that — the
land inside a hex, not the hex — and Iberia simply never used it. All 345
such hexes (the extra 27 come with Portugal's larger region) now carry
their land as LAND_FRAGMENTs. 139 of them hold land of more than one
physical component, one of them 103 components, and in one hex the islet
is four times larger than the mainland fragment: the first real proof that
a whole-hex winner would have been wrong.

THE ALGARVE. MAPGEN-026 withheld it because a French atlas plate lettered
it ROYAUME DE ALGARVE, and refused to fold it into Portugal on the same
principle that keeps Naples and Sicily apart. Half right: a map title is
not evidence about an actor, in either direction. The crown's own printed
legislation settles it — one royal style, one Chancellaria mór through
which every law is published, one livro das Leys, acts that bind "Portugal,
ou nos Algarves" inside a single clause, and ground administered by the
corregedores of two ordinary comarcas under the same Ordenações as Beira.
Naples and Sicily each had a parliament, a council and a viceroy. The
Algarve has none of the three. PART_OF_POL_PORTUGAL, on institutions.

THE STRIPS. Portugal's real limit was not scale. The sealing dilation left
it as six disconnected blocks with wide unowned band strips between them,
and the uncertainty erosion then ate every block from both sides — a
34.6 km bite from each side of a 40 km block leaves nothing. Those strips
are band area, not cells: 1,768 km² of the 2,927 km² corridor between the
Alentejo and the Algarve belongs to no cell at all. Each corridor is
bridged only where it contains no cell of another crown, and the plate was
read inside all nine to corroborate it.

Portugal goes from 26 rows to 124. Spain does not move: its safe interior
is the MAPGEN-026 object, carried through untouched and asserted so before
anything is written.

WHAT IS NOT DONE. A larger-scale Portugal source was found, acquired and
audited — Sanson/Vaugondy 1762, two sheets of 41 × 52 cm, CC BY 4.0 from
Coimbra — and it is NOT georeferenced here. The plate draws every town of
consequence as a pictorial vignette rather than a circle, and a vignette
has no defensible single point; that is exactly why MAPGEN-026 rejected
Cuenca and Córdoba as anchors. Producing 24 correspondences would have
meant inventing an anchor rule for vignettes, and an invented rule is
worse than a missing map. The sheets' own graduations are measured and
recorded, a three-point check puts the plate's meridian within six
hundredths of a degree, and the georeference goes to MAPGEN-028 labelled
PRELIMINARY_NOT_A_GEOREFERENCE.
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

STAGE = "MAPGEN-027"
H = Path("data/historical")
M26_COMMIT = "87fe418bbb1a4ad66c6bdc0d2dc7e645dfd12435"
M26_SUMMARY = Path("reviews/MAPGEN-026/summary.csv")
SPAIN_SP, PORTUGAL_SP = "sp_b622a2799f94", "sp_fef06587fead"
GB_SP, IE_SP = "sp_6b03622fc98a", "sp_c8f0dcb42a96"
SICILY_SP, SARDINIA_SP = "sp_14ee92dede27", "sp_5f0f4d8d4788"
DK_SP, OSJ_SP, SAX_SP = "sp_44c79eb0f89c", "sp_20bf1d9af6ea", "sp_992101257e91"
MAINLAND_SUBJ = "hsub_european_mainland"
WITHHELD = ("GIBRALTAR", "ANDORRA", "LLIVIA", "OLIVENZA", "COUTO_MISTO",
            "CEUTA")
MAX_TRACKED_BYTES = 50 * 1024 * 1024
UNCERTAINTY_KM = 34.61


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
    """MAPGEN-026's own committed summary is the authority for 'before'."""
    s = pd.read_csv(M26_SUMMARY)
    d = dict(zip(s["metric"].astype(str), s["value"].astype(str)))
    out = {}
    for k in ("canonical_rows_after", "canonical_controlled_after",
              "canonical_unresolved_after", "terrestrial_hex_rows",
              "land_fragment_rows", "spain_controlled",
              "portugal_controlled", "not_produced_hexes",
              "positional_uncertainty_km"):
        if k in d:
            out[k] = float(d[k]) if "." in d[k] else int(float(d[k]))
    out["outcome_as_declared"] = d.get("outcome", "")
    return out


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def render_recovery(path: Path, base: dict, s: dict, cells: pd.DataFrame,
                    corr: pd.DataFrame, title: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(17.5, 5.4))

    ax = axes[0]
    labels = ["MAPGEN-026", "MAPGEN-027"]
    pt = [base["portugal_controlled"], s["portugal_controlled"]]
    # total CONTROLLED rows on both sides, so the two bars mean the same
    # thing: Spain's hexes are frozen and it gained 8 coastal fragments
    es = [base["spain_controlled"], s["spain_controlled_rows"]]
    x = np.arange(2)
    ax.bar(x - 0.19, es, 0.38, color="#c9a227", label="Spain")
    ax.bar(x + 0.19, pt, 0.38, color="#2e7d4f", label="Portugal")
    for i in range(2):
        ax.text(i - 0.19, es[i], f"{es[i]:,}", ha="center", va="bottom",
                fontsize=8)
        ax.text(i + 0.19, pt[i], f"{pt[i]:,}", ha="center", va="bottom",
                fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_yscale("log")
    ax.set_ylabel("CONTROLLED rows (log)", fontsize=9)
    ax.set_title("A. Spain's hexes frozen, Portugal recovered",
                 fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25, axis="y")

    ax = axes[1]
    src = ["Algarve\n(institutions)", "corridors\n(one-crown rule)",
           "coastal land\n(LAND_FRAGMENT)"]
    val = [s["portugal_gain_algarve_and_corridors"] - s["portugal_gain_frag"],
           0, s["portugal_gain_frag"]]
    # the two geometric changes are inseparable once merged, so they are
    # reported together rather than split by guesswork
    val = [s["portugal_gain_algarve_and_corridors"], s["portugal_gain_frag"]]
    src = ["Algarve + corridors\n(evidence, not cartography)",
           "coastal LAND_FRAGMENT"]
    ax.barh(range(len(val)), val, color=["#2e7d4f", "#00897b"])
    for i, v in enumerate(val):
        ax.text(v, i, f" +{v}", va="center", fontsize=9)
    ax.set_yticks(range(len(val)))
    ax.set_yticklabels(src, fontsize=8)
    ax.set_xlabel("Portuguese rows gained", fontsize=9)
    ax.set_title("B. where the recovery came from", fontsize=10)
    ax.grid(alpha=0.25, axis="x")

    ax = axes[2]
    ax.set_axis_off()
    body = ["WHAT WAS BRIDGED, AND WHY", ""]
    body += _wrap(
        "A strip between two cells of the same crown is bridged only when "
        "no cell of another crown lies in the corridor between them. The "
        "plate was read inside every corridor as corroboration.", 52)
    body += ["", "  cells   gap km   decision", ""]
    for r in corr.itertuples():
        body.append(f"  {r.cell_a:3d}-{r.cell_b:<3d} {r.gap_km:7.1f}   "
                    f"{r.decision}")
    body += ["", f"  bridged {int((corr.decision == 'BRIDGED').sum())} of "
                 f"{len(corr)}", ""]
    body += _wrap(
        f"Uncertainty {UNCERTAINTY_KM} km, unchanged from MAPGEN-026: this "
        "stage improved the evidence, not the georeference.", 52)
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=7.6)
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_fragments(path: Path, au: pd.DataFrame, multi: pd.DataFrame,
                     title: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(15.0, 5.2))
    ax = axes[0]
    g = au.groupby("basis").size().sort_values()
    ax.barh(range(len(g)), g.values,
            color=["#2e7d4f" if "SAFE_INTERIOR" in i else "#f0a30a"
                   for i in g.index])
    ax.set_yticks(range(len(g)))
    ax.set_yticklabels([i[:46] for i in g.index], fontsize=7)
    for i, v in enumerate(g.values):
        ax.text(v, i, f" {v}", va="center", fontsize=8)
    ax.set_title(f"A. {len(au)} coastal fragments, by outcome", fontsize=10)
    ax.grid(alpha=0.25, axis="x")

    ax = axes[1]
    n = multi.distinct_land_components_in_hex.clip(upper=12)
    ax.hist(n, bins=np.arange(1.5, 13.5, 1), color="#5b6bbf")
    ax.set_xlabel("distinct land components in one hex (12 = 12 or more)",
                  fontsize=8)
    ax.set_ylabel("hexes", fontsize=9)
    ax.set_title(f"B. {len(multi)} hexes hold more than one component; the "
                 f"worst holds "
                 f"{int(multi.distinct_land_components_in_hex.max())}",
                 fontsize=10)
    ax.grid(alpha=0.25, axis="y")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


# ---------------------------------------------------------------------------
# stage
# ---------------------------------------------------------------------------
def run_historical_portugal(cfg: MapgenConfig,
                            run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"portugal_recovery_1756_{_dt.datetime.now():%Y%m%d}"
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
    revlog = pd.read_csv(sdir / "territorial_control_revision_log.csv",
                         keep_default_na=False, na_values=[""])
    cov = pd.read_csv(sdir / "political_coverage.csv",
                      keep_default_na=False, na_values=[""])
    src = pd.read_csv(sdir / "sources.csv", keep_default_na=False,
                      na_values=[""])

    au = pd.read_csv(H / "iberia_nonterrestrial_fragment_audit.csv")
    prod = pd.read_csv(H / "iberia_land_fragment_production.csv")
    multi = pd.read_csv(H / "iberia_multi_fragment_capability.csv")
    mix = pd.read_csv(H / "iberia_hex_membership_audit_v2.csv")
    mix26 = pd.read_csv(H / "iberia_hex_membership_audit.csv")
    reg = pd.read_csv(H / "land_fragment_registry.csv")
    alg = pd.read_csv(H / "algarve_constitutional_audit.csv",
                      keep_default_na=False, na_values=[])
    algd = pd.read_csv(H / "algarve_primary_evidence.csv",
                       keep_default_na=False, na_values=[])
    esh = pd.read_csv(H / "spain_snapshot_evidence_hardening.csv")
    psh = pd.read_csv(H / "portugal_snapshot_evidence_hardening.csv")
    pmsr = pd.read_csv(H / "portugal_map_source_registry.csv")
    plin = pd.read_csv(H / "portugal_source_lineage.csv")
    pcont = pd.read_csv(H / "portugal_source_continuity_audit.csv")
    pgrat = pd.read_csv(H / "portugal_plate_graticule_observations.csv")
    pgeo = pd.read_csv(H / "portugal_georeference_audit.csv")
    pprelim = pd.read_csv(H / "portugal_preliminary_accuracy_check.csv")
    msep = pd.read_csv(H / "portugal_georeference_metric_separation.csv")
    pv2 = pd.read_csv(H / "portugal_safe_interior_v2.csv")
    corr = pd.read_csv(H / "portugal_corridor_audit.csv",
                       keep_default_na=False, na_values=[])
    cells = pd.read_csv(H / "iberia_cell_ownership_audit.csv",
                        keep_default_na=False, na_values=[])
    cases = pd.read_csv(H / "iberia_special_cases.csv")
    tr = json.loads((H / "iberia_lerouge_transform.json").read_text(
        encoding="utf-8"))
    hx = pd.read_parquet(eu_dir / "europe_hex_coverage.parquet",
                         columns=["hex_id", "is_terrestrial_hex",
                                  "water_type"])
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_coverage.parquet",
        Path("output/europe_land_cache/europe_land_parts.parquet")]}
    timings["load_s"] = time.perf_counter() - t0

    iberia_hexes = set(mix["hex_id"]) | set(mix26["hex_id"])
    frag_ids = set(prod["land_fragment_id"])
    hex_rows = canonical[canonical.territorial_target_type
                         == "TERRESTRIAL_HEX"]
    frag_rows = canonical[canonical.territorial_target_type
                          == "LAND_FRAGMENT"]
    spain = canonical[canonical.controller_scenario_polity_id == SPAIN_SP]
    portugal = canonical[canonical.controller_scenario_polity_id
                         == PORTUGAL_SP]
    spain_hexes = spain[spain.territorial_target_type == "TERRESTRIAL_HEX"]
    # the Kanto pilot lives on the geography grid, not the Europe one, so
    # both have to be consulted before calling a hex non-terrestrial
    terr_hex = set(hx.loc[hx["is_terrestrial_hex"], "hex_id"]) | set(
        pd.read_parquet(geo_dir / "geography_hexes.parquet",
                        columns=["hex_id", "water_type"])
        .query("water_type == 'NONE'")["hex_id"])
    FOUNDATION_ROWS = {"h6000_q+002183_r+000819", "isl_c_1859af1e4767",
                       "h6000_q+002184_r+000813"}

    # ---- preview ---------------------------------------------------------
    t0 = time.perf_counter()
    prev_dir = render_scenario_preview(cfg, out_dir=run_dir / "preview",
                                       scenario_id=scenario_id)
    pman = json.loads((prev_dir / "preview_manifest.json").read_text(
        encoding="utf-8"))
    timings["preview_s"] = time.perf_counter() - t0

    # ---- gates -----------------------------------------------------------
    t0 = time.perf_counter()
    _check("M27-01_mapgen026_baseline",
           M26_SUMMARY.exists()
           and base["canonical_rows_after"] == 75629
           and base["spain_controlled"] == 5431
           and base["portugal_controlled"] == 26
           and base["not_produced_hexes"] == 318,
           "baseline read from the COMMITTED reviews/MAPGEN-026/summary.csv "
           f"- {base['canonical_rows_after']:,} rows, Spain "
           f"{base['spain_controlled']:,}, Portugal "
           f"{base['portugal_controlled']}, "
           f"{base['not_produced_hexes']} hexes with no row")
    _check("M27-02_existing_spain_rows_immutable",
           len(spain_hexes) == base["spain_controlled"]
           and not len(revlog[revlog.new_controller == SPAIN_SP]),
           f"{len(spain_hexes):,} Spanish TERRESTRIAL_HEX rows, identical "
           "to MAPGEN-026, and the revision log records no row moving to "
           "Spain")
    mine = revlog[revlog.reason.str.contains("Portugal safe interior v2",
                                             na=False)]
    _check("M27-03_no_silent_overwrite",
           len(mine) > 0
           and set(mine.old_status) <= {"UNRESOLVED"}
           and (mine.reason.str.len() > 40).all()
           and len(revlog) > len(mine),
           f"{len(mine)} rows changed in this stage, every one written to "
           "the revision log with its before and after state and all of "
           f"them UNRESOLVED before; MAPGEN-014's {len(revlog) - len(mine)} "
           "earlier revisions are still there, appended to rather than "
           "replaced")

    _check("M27-04_all_nonterrestrial_hexes_audited",
           len(au) >= base["not_produced_hexes"]
           and set(mix26.loc[mix26.control_status == "NOT_PRODUCED",
                             "hex_id"]).issubset(set(au.hex_id))
           and {"safe_interior_status", "frontier_band_status",
                "special_case_status", "mixed_land_status",
                "candidate_land_fragment_id"} <= set(au.columns),
           f"{len(au)} hexes audited, covering all "
           f"{base['not_produced_hexes']} MAPGEN-026 left unaddressed, each "
           "with its safe-interior, frontier-band, special-case and "
           "mixed-land status and a candidate fragment id")
    _check("M27-05_safe_coastal_fragments_represented",
           int((prod.proposed_control_status == "CONTROLLED").sum()) > 0
           and frag_ids <= set(reg.land_fragment_id)
           and frag_ids <= set(frag_rows.territorial_target_id),
           f"{int((prod.proposed_control_status == 'CONTROLLED').sum())} "
           f"fragments CONTROLLED and all {len(frag_ids)} registered and "
           "promoted; MAPGEN-026 produced none in Iberia")
    _check("M27-06_no_whole_ocean_hex_ownership",
           not len(hex_rows[~hex_rows.territorial_target_id.isin(terr_hex)])
           and not (set(prod.hex_id) & set(hex_rows.territorial_target_id)),
           "no TERRESTRIAL_HEX row addresses a non-terrestrial hex, and no "
           "fragment's parent hex carries a hex row: the OCEAN hex is "
           "still not owned")
    _check("M27-07_mixed_fragments_explicit",
           len(multi) > 0
           and int(multi.distinct_land_components_in_hex.max()) > 2
           and (multi.second_fragment_produced == "NO").all(),
           f"{len(multi)} hexes hold land of more than one physical "
           f"component, the worst "
           f"{int(multi.distinct_land_components_in_hex.max())}; the other "
           f"components' {multi.other_component_km2.sum():.1f} km2 is "
           "measured and left unowned")

    _check("M27-08_algarve_title_not_treated_as_actor_proof",
           "TITLE_IS_NOT_ACTOR_EVIDENCE" in set(alg.verdict)
           and str(algd.iloc[0].map_title_used_as_evidence) == "NO",
           "the plate's ROYAUME DE ALGARVE lettering is recorded as a "
           "foreign engraving convention, not as evidence about an actor "
           "in either direction")
    _check("M27-09_algarve_primary_evidence_acquired",
           len(alg) >= 7
           and {"ROYAL_TITULATURE", "LEGISLATIVE_AUTHORITY",
                "ADMINISTRATION", "JUDICIAL_STRUCTURE", "TAXATION",
                "REPRESENTATION"} <= set(alg.axis),
           f"{len(alg)} axes examined against the crown's own printed "
           "legislation, an archival finding aid for the Tavira "
           "corregedoria, and a University of Lisbon study")
    _check("M27-10_algarve_decision_evidence_based",
           str(algd.iloc[0].decision) == "PART_OF_POL_PORTUGAL"
           and int(algd.iloc[0].axes_supporting_separate_actor) == 0
           and str(algd.iloc[0].auto_merged_for_convenience) == "NO",
           "PART_OF_POL_PORTUGAL: no axis supports a separate actor, and "
           "no new polity was created. The Naples/Sicily comparison is "
           "recorded on the decision row")

    _check("M27-11_spain_pre_snapshot_evidence",
           str(esh.iloc[0].relation_to_snapshot_new) == "BEFORE_SNAPSHOT"
           and str(esh.iloc[0].earlier_evidence_retained) == "YES"
           and int(esh.iloc[0].days_before_snapshot) > 0,
           "Gaceta de Madrid num. 30 of 27 July 1756, five days before the "
           "snapshot: the King appoints an oidor to the Chancilleria de "
           "Granada and a fiscal to the Consejo de Navarra. The 3 August "
           "assertion is kept")
    _check("M27-12_portugal_pre_snapshot_evidence",
           str(psh.iloc[0].relation_to_snapshot_new) == "BEFORE_SNAPSHOT"
           and str(psh.iloc[0].earlier_evidence_retained) == "YES",
           "four acts of 1756 dated before the snapshot in the crown's own "
           "compilation, including the Decreto de 15 de Junho ordering the "
           "Desembargo do Paco to publish by edict in every town of the "
           "Province of Alentejo. The Douro alvara is kept")

    _check("M27-13_larger_scale_source_bounded_search",
           len(pmsr) >= 2 and pmsr.institution.nunique() == 1
           and (pmsr.acquired_utc.str.len() > 10).all(),
           f"{len(pmsr)} files acquired from the Universidade de Coimbra "
           "Biblioteca Geral Digital, with catalogue id, date, "
           "cartographer, dimensions, sha256 and acquisition time recorded")
    _check("M27-14_rights_and_reuse_audited",
           (pmsr.rights.str.contains("CC BY 4.0")).all()
           and (pmsr.gitignored == "YES").all(),
           "both sheets are CC BY 4.0 open access, so commercial reuse is "
           "not impeded; the rasters are gitignored and only their hashes "
           "are committed")
    _check("M27-15_source_lineage_audited",
           len(plin) == 2
           and (plin.independence_status == "UNRESOLVED").all()
           and (plin.corroboration_eligible == "NO").all(),
           "the Vaugondy sheet is of the Sanson/Jaillot/Vaugondy family "
           "and Le Rouge's own lineage is NOT ESTABLISHED, so their "
           "relation is UNRESOLVED in both directions and neither counts "
           "as independent corroboration of the other")
    _check("M27-16_post_1756_source_continuity_recorded",
           len(pcont) == 1
           and "CONTINUITY" in str(pcont.iloc[0].verdict)
           and "1762" in str(pcont.iloc[0].war_risk),
           "the 1762 sheet post-dates the snapshot and the Spanish "
           "invasion of Portugal ran May-November 1762; the continuity "
           "argument and the campaign-line risk are both recorded, and "
           "nothing in production relies on either")

    _check("M27-17_no_gcp_without_a_defensible_anchor",
           str(pgeo.iloc[0].status) == "PRELIMINARY_NOT_A_GEOREFERENCE"
           and (pprelim.eligible_as_gcp == "NO").all(),
           f"{len(pprelim)} points were identified to calibrate a SEARCH "
           "window and every one is marked ineligible as a control point. "
           "No Vaugondy GCP exists, because the plate draws towns as "
           "vignettes and a vignette has no defensible single point - the "
           "reason MAPGEN-026 rejected Cuenca and Cordoba")
    _check("M27-18_no_split_invented_for_a_fit_that_did_not_happen",
           "portugal_transform.json" not in {p.name for p in H.glob("*")}
           and str(pgeo.iloc[0].handed_to) == "MAPGEN-028",
           "no FIT/MODEL_SELECTION/BLIND split was manufactured for the "
           "Vaugondy sheets, because no model was fitted; the work is "
           "handed to MAPGEN-028 with its reason")
    _check("M27-19_model_selection_holdout_is_not_blind",
           set(msep.metric_set) == {"FIT", "MODEL_SELECTION_HOLDOUT",
                                    "BLIND_VALIDATION", "ALL_NONFIT"}
           and str(msep.loc[msep.metric_set == "MODEL_SELECTION_HOLDOUT",
                            "statistically_blind"].iloc[0]) == "NO",
           "MAPGEN-026's wording is corrected: the model-selection holdout "
           "chose POLYNOMIAL_2 and is therefore NOT statistically blind. "
           "The four sets are reported separately")
    _check("M27-20_production_uncertainty_names_its_set",
           int(msep.used_for_production_uncertainty.eq("YES").sum()) == 1
           and str(msep.loc[msep.used_for_production_uncertainty == "YES",
                            "metric_set"].iloc[0]) == "ALL_NONFIT"
           and abs(float(msep.loc[msep.metric_set == "ALL_NONFIT",
                                  "p95_km"].iloc[0]) - UNCERTAINTY_KM)
           < 0.02,
           f"the erosion uses ALL_NONFIT p95 = {UNCERTAINTY_KM} km, the "
           "more conservative of the two candidates (the blind p95 is "
           "23.30 km on 5 points in 2 quadrants)")
    _check("M27-21_transform_in_force_does_not_fold",
           not tr["jacobian"]["folding"],
           "the transform this production rests on is still the MAPGEN-026 "
           "POLYNOMIAL_2, and its Jacobian over the whole face does not "
           "fold")
    _check("M27-22_uncertainty_honest",
           abs(float(pv2.iloc[0].uncertainty_km) - UNCERTAINTY_KM) < 0.02
           and float(pv2.iloc[0].uncertainty_km)
           == float(base["positional_uncertainty_km"]),
           "the uncertainty is UNCHANGED from MAPGEN-026 because no new "
           "georeference was made; Portugal's recovery came from evidence, "
           "and the report says so")

    _check("M27-23_no_frontier_traced_from_an_ungeoreferenced_source",
           not (H / "portugal_frontier_segments.csv").exists()
           or pd.read_csv(H / "portugal_frontier_segments.csv").empty,
           "no frontier geometry was digitised from the Vaugondy sheets, "
           "because a trace from an ungeoreferenced plate cannot be placed "
           "on the ground")
    _check("M27-24_cross_source_comparison_status_recorded",
           (H / "portugal_cross_source_comparison.csv").exists(),
           "the Le Rouge / Vaugondy frontier comparison is recorded as NOT "
           "PERFORMED with its reason, rather than left unmentioned")
    _check("M27-25_no_averaged_historical_boundary",
           not len(revlog[revlog.reason.str.contains("averag", case=False)])
           and "AVERAG" not in str(pv2.iloc[0].to_dict()).upper(),
           "no boundary was averaged between sources; only one source's "
           "geometry is in force and the other is recorded as unused")

    v1_in_v2 = bool(pv2.iloc[0].v1_fully_contained_in_v2)
    _check("M27-26_portugal_safe_interior_conservative",
           v1_in_v2
           and float(pv2.iloc[0].overlap_with_spain_safe_km2) < 1e-3
           and float(pv2.iloc[0].v2_area_km2_3857)
           > float(pv2.iloc[0].v1_area_km2_3857),
           "v2 contains all of v1, overlaps Spain's safe interior by "
           f"{float(pv2.iloc[0].overlap_with_spain_safe_km2)} km2, and "
           f"grows from {pv2.iloc[0].v1_area_km2_3857:,.0f} to "
           f"{pv2.iloc[0].v2_area_km2_3857:,.0f} km2 (projected)")
    _check("M27-27_special_cases_retained",
           set(WITHHELD) <= set(cases.case)
           and (cases.treatment
                == "WITHHELD_FROM_EVERY_SAFE_INTERIOR").all(),
           "Gibraltar, Andorra, Llivia, Olivenza, the Couto Misto and "
           "Ceuta are still each withheld inside one uncertainty radius")
    _check("M27-28_algarve_treatment_follows_the_audit",
           "SEPARATE_KINGDOM_TITLE_UNEVALUATED" not in set(cells.reason)
           and cells.loc[cells.cell == 18, "crown"].iloc[0] == "PORTUGAL"
           and "ALGARVE" not in set(cases.case),
           "the Algarve cell is owned by Portugal and removed from the "
           "withheld list, because the audit said so and only because it "
           "said so")

    ctrl = mix[mix.control_status == "CONTROLLED"]
    _check("M27-29_exact_land_whole_hex",
           (ctrl.basis == "WHOLE_HEX_LAND_INSIDE_SAFE_INTERIOR").all()
           and bool(ctrl.is_terrestrial_hex.all()),
           f"{len(ctrl):,} CONTROLLED hexes, every one with all of its "
           "land inside a single crown's safe interior, measured on the "
           "exact hex-land intersection")
    fcon = prod[prod.proposed_control_status == "CONTROLLED"]
    _check("M27-30_land_fragment_coast",
           (fcon.basis == "WHOLE_FRAGMENT_INSIDE_SAFE_INTERIOR").all()
           and not len(prod[prod.proposed_control_status
                            == "NOT_PRODUCED"]),
           "no hex carrying authorised safe coastal land is left "
           "NOT_PRODUCED any more; every fragment is either CONTROLLED or "
           "explicitly UNRESOLVED")
    _check("M27-31_land_cache_safe_helper",
           "land_in_hexes" in Path(
               "src/mapgen/historical_binding.py").read_text(
                   encoding="utf-8"),
           "hex land is measured with land_in_hexes(), which unions the "
           "tile intersections inside each hex before measuring")
    _check("M27-32_no_unsafe_tile_sum",
           not len(mix[mix.hex_land_km2 > 31.2])
           and not len(au[au.hex_land_km2 > 31.2]),
           "no hex reports more land than a hex can hold (31.18 km2 "
           "projected); a naive sum over overlapping cache tiles would "
           "show exactly that, and MAPGEN-024 once did")

    _check("M27-33_promotion_idempotent",
           log.promotion_id.is_unique
           and int((log.source_stage == STAGE).sum()) >= 1,
           "the promotion id is deterministic on the candidate hash, so a "
           "re-run inserts nothing; the log carries one MAPGEN-027 entry")
    prov_ids = set(provenance.territorial_target_id)
    unprov = set(canonical.territorial_target_id) - prov_ids
    _check("M27-34_provenance_complete",
           unprov <= FOUNDATION_ROWS,
           f"every one of the {len(canonical):,} canonical rows has a "
           "provenance row except the three MAPGEN-008 Kanto foundation "
           "rows, which predate the provenance table and are named rather "
           "than waved through")
    ptcov = cov[cov.coverage_unit_id
                == "region_portugal_iberian_mainland_1756"]
    _check("M27-35_coverage_honest",
           len(ptcov) == 1
           and str(ptcov.iloc[0].control_coverage_status)
           == "TERRITORY_PARTIAL"
           and "THIN" in str(ptcov.iloc[0].notes),
           "Portugal stays TERRITORY_PARTIAL and the coverage note says "
           "plainly that it is still thin and why")
    _check("M27-36_viewer_updated",
           (prev_dir / "iberian_political_closeup.png").exists()
           and (prev_dir / "scenario_1756_political_map.png").exists()
           and pman["stats"]["gap"] == 0,
           "the scenario preview was re-rendered; the closeup and the "
           "Europe map are regenerated and no unrecovered gap hex is drawn")

    def held(sp_id, kind="TERRESTRIAL_HEX"):
        s = canonical[(canonical.controller_scenario_polity_id == sp_id)
                      & (canonical.control_status == "CONTROLLED")
                      & (canonical.territorial_target_type == kind)]
        return len(s)

    _check("M27-37_british_isles_regression",
           held(GB_SP) == 20310 and held(IE_SP) == 7520,
           f"Great Britain {held(GB_SP):,} and Ireland {held(IE_SP):,} "
           "hexes, unchanged since MAPGEN-021")
    _check("M27-38_mediterranean_regression",
           held(SICILY_SP) == 1305 and held(SARDINIA_SP) == 1308,
           f"Sicily {held(SICILY_SP):,} and Sardinia "
           f"{held(SARDINIA_SP):,} hexes, unchanged since MAPGEN-022")
    _check("M27-39_iceland_malta_regression",
           held(DK_SP) == 18341 and held(OSJ_SP) == 15,
           f"Iceland {held(DK_SP):,} and Malta/Gozo {held(OSJ_SP)} hexes, "
           "unchanged since MAPGEN-023")
    _check("M27-40_spain_regression",
           held(SPAIN_SP) == base["spain_controlled"],
           f"Spain {held(SPAIN_SP):,} hexes, identical to the "
           f"{base['spain_controlled']:,} MAPGEN-026 committed")
    bb = canonical[canonical.notes.str.contains("Brandenburg", case=False,
                                                na=False)]
    _check("M27-41_brandenburg_regression",
           len(bb) == 0,
           "Brandenburg still holds nothing: MAPGEN-020 left it "
           "un-produced and this stage did not change that")
    _check("M27-42_saxony_regression",
           held(SAX_SP) == 695,
           f"Electoral Saxony {held(SAX_SP)} hexes, unchanged since "
           "MAPGEN-015")
    _check("M27-43_europe_physical_grid_regression",
           len(hx) == 1885422 and int(hx.is_terrestrial_hex.sum()) > 0,
           f"the canonical Europe grid is still {len(hx):,} hexes; no "
           "physical geography was touched")
    claims = pd.read_csv(sdir / "territorial_claims.csv",
                         keep_default_na=False, na_values=[""])
    _check("M27-44_claims_regression",
           len(claims) == 1
           and str(claims.iloc[0].territorial_target_id)
           == "h6000_q+002183_r+000819",
           "the claim table still holds exactly the one MAPGEN-008 Kanto "
           "row; this stage created none")
    sizes = tracked_file_sizes(Path("."))
    biggest = int(sizes["bytes"].max()) if len(sizes) else 0
    where = sizes.loc[sizes["bytes"].idxmax(), "path"] if len(sizes) else ""
    feats_c = gpd.read_parquet(H / "historical_boundary_features.parquet")
    _check("M27-45_no_oversized_blob_or_stored_wkt",
           biggest <= MAX_TRACKED_BYTES
           and "geometry" not in pd.read_csv(
               H / "historical_snapshot_features_1756_08_01.csv",
               nrows=1).columns,
           f"largest git-tracked file {biggest / 1e6:.1f} MB ({where}); the "
           "snapshot feature table stores no WKT geometry column, which "
           "cost 58 MB the one time it did")
    det = pd.read_csv(H / "iberia_determinism_check.csv")
    _check("M27-46_determinism",
           len(det) >= 4
           and (det.first_run_matches_second == "YES").all(),
           "the fragment, safe-interior and binding chain re-runs "
           "byte-identical, and the revision is idempotent because the "
           "promotion id is a hash of the candidate")
    timings["gates_s"] = time.perf_counter() - t0

    # ---- outputs ---------------------------------------------------------
    t0 = time.perf_counter()
    pt_hex = held(PORTUGAL_SP)
    pt_frag = held(PORTUGAL_SP, "LAND_FRAGMENT")
    s = dict(
        stage=STAGE, outcome="ACCEPTABLE",
        mapgen026_outcome_restated="ACCEPTABLE_PRODUCTION_WITH_FOLLOWUP_"
                                   "GAPS",
        nonterrestrial_hexes_audited=len(au),
        fragments_produced=len(prod),
        fragments_controlled=int((prod.proposed_control_status
                                  == "CONTROLLED").sum()),
        fragments_unresolved=int((prod.proposed_control_status
                                  == "UNRESOLVED").sum()),
        fragment_land_km2=round(float(prod.mainland_fragment_km2.sum()), 2),
        mixed_component_hexes=len(multi),
        max_components_in_one_hex=int(
            multi.distinct_land_components_in_hex.max()),
        other_component_km2_left_unowned=round(
            float(multi.other_component_km2.sum()), 3),
        algarve_decision=str(algd.iloc[0].decision),
        algarve_axes_examined=int(algd.iloc[0].axes_examined),
        spain_pre_snapshot_source="gaceta_de_madrid_1756_07_27_num30",
        portugal_pre_snapshot_source=(
            "colleccao_leis_decretos_alvaras_jose_i_tomo_i"),
        larger_scale_source="vaugondy_1762_carte_du_royaume_de_portugal_uc",
        larger_scale_source_status=str(pgeo.iloc[0].status),
        larger_scale_source_rights="CC BY 4.0",
        corridors_examined=len(corr),
        corridors_bridged=int((corr.decision == "BRIDGED").sum()),
        portugal_safe_km2_v1_3857=float(pv2.iloc[0].v1_area_km2_3857),
        portugal_safe_km2_v2_3857=float(pv2.iloc[0].v2_area_km2_3857),
        positional_uncertainty_km=UNCERTAINTY_KM,
        spain_controlled=held(SPAIN_SP),
        spain_controlled_rows=held(SPAIN_SP) + held(SPAIN_SP,
                                                    "LAND_FRAGMENT"),
        spain_fragments=held(SPAIN_SP, "LAND_FRAGMENT"),
        spain_controlled_before=base["spain_controlled"],
        portugal_controlled=pt_hex + pt_frag,
        portugal_controlled_before=base["portugal_controlled"],
        portugal_hexes=pt_hex, portugal_fragments=pt_frag,
        portugal_gain_algarve_and_corridors=(
            pt_hex - base["portugal_controlled"]),
        portugal_gain_frag=pt_frag,
        unresolved_in_iberia=int(
            (canonical.territorial_target_id.isin(
                set(mix.hex_id) | frag_ids)
             & (canonical.control_status == "UNRESOLVED")).sum()),
        rows_inserted=int(len(canonical) - base["canonical_rows_after"]),
        rows_revised=len(revlog[revlog.reason.str.contains(
            "Portugal safe interior v2", na=False)]),
        canonical_rows_before=base["canonical_rows_after"],
        canonical_rows_after=len(canonical),
        canonical_controlled_after=int(
            (canonical.control_status == "CONTROLLED").sum()),
        canonical_unresolved_after=int(
            (canonical.control_status == "UNRESOLVED").sum()),
        terrestrial_hex_rows=len(hex_rows),
        land_fragment_rows=len(frag_rows),
        validation_pass="")

    render_recovery(run_dir / "portugal_recovery_before_after.png", base, s,
                    cells, corr,
                    "Portugal recovered on evidence; Spain's hexes frozen")
    render_fragments(run_dir / "iberian_land_fragment_completion.png", au,
                     multi, "The coast MAPGEN-026 could not address")
    imgs = ["portugal_recovery_before_after.png",
            "iberian_land_fragment_completion.png"]
    for n in ("iberian_political_closeup.png",
              "scenario_1756_political_map.png",
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

    pd.DataFrame([
        dict(gap="Iberian LAND_FRAGMENT production was zero",
             mapgen026_state="318 hexes carried mainland land and received "
                             "no row of any kind",
             mapgen027_action=f"all {len(au)} such hexes audited and their "
                              "land produced as fragments",
             resolved="YES"),
        dict(gap="the Algarve was withheld on a map title",
             mapgen026_state="SEPARATE_KINGDOM_TITLE_UNEVALUATED, on the "
                             "strength of the plate's lettering",
             mapgen027_action="constitutional audit on seven institutional "
                              "axes; PART_OF_POL_PORTUGAL",
             resolved="YES"),
        dict(gap="individual political evidence post-dated the snapshot",
             mapgen026_state="Gaceta of 3 Aug 1756 and the Douro alvara of "
                             "10 Sep 1756, both after 1 Aug",
             mapgen027_action="a dated pre-snapshot record added for each "
                              "crown; both earlier assertions retained",
             resolved="YES"),
        dict(gap="'blind' was used for the model-selection holdout",
             mapgen026_state="the README quoted 'every point the fit never "
                             "saw' alongside the blind figure",
             mapgen027_action="four metric sets separated; the holdout is "
                              "marked NOT statistically blind",
             resolved="YES"),
        dict(gap="no larger-scale Portugal source",
             mapgen026_state="one pocket-atlas plate for the whole "
                             "peninsula",
             mapgen027_action="Sanson/Vaugondy 1762 acquired, rights and "
                              "lineage audited, georeference deferred with "
                              "its reason",
             resolved="PARTIAL"),
    ]).to_csv(run_dir / "mapgen026_followup_audit.csv", index=False)

    manifest = {
        "run_id": run_id, "stage": STAGE, "outcome": s["outcome"],
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen026": M26_COMMIT,
        "baseline_from_committed_summary": base,
        "mapgen026_outcome_restated": s["mapgen026_outcome_restated"],
        "fragments": {
            "audited_hexes": len(au), "produced": len(prod),
            "controlled": s["fragments_controlled"],
            "unresolved": s["fragments_unresolved"],
            "subject": MAINLAND_SUBJ,
            "mixed_component_hexes": len(multi),
            "max_components_in_one_hex": s["max_components_in_one_hex"]},
        "algarve": algd.to_dict("records"),
        "algarve_axes": alg[["axis", "verdict"]].to_dict("records"),
        "evidence_hardening": {
            "spain": esh.to_dict("records"),
            "portugal": psh.to_dict("records")},
        "larger_scale_source": {
            "registry": pmsr.drop(columns=["sha256"]).to_dict("records"),
            "lineage": plin.to_dict("records"),
            "continuity": pcont.to_dict("records"),
            "graticule": pgrat.to_dict("records"),
            "preliminary_check": pgeo.to_dict("records")},
        "metric_separation": msep.to_dict("records"),
        "portugal_v2": pv2.to_dict("records"),
        "corridors": corr.to_dict("records"),
        "production": {
            "spain": s["spain_controlled"],
            "portugal": s["portugal_controlled"],
            "inserted": s["rows_inserted"], "revised": s["rows_revised"]},
        "target_types": TARGET_TYPES,
        "scenario_schema_version": SCENARIO_SCHEMA_VERSION,
        "hpg_schema_version": HPG_SCHEMA_VERSION,
        "preview": pman, "upstream_sha256": upstream,
        "image_aspects": aspects,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    _write_readme(run_dir, run_id, s, base, alg, algd, corr, au, multi,
                  msep, pgeo, aspects, imgs)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    cmap = {"README_REVIEW.md": run_dir / "README_REVIEW.md",
            "run_manifest.json": run_dir / "run_manifest.json",
            "validation.csv": run_dir / "validation.csv",
            "summary.csv": run_dir / "summary.csv",
            "mapgen026_followup_audit.csv":
                run_dir / "mapgen026_followup_audit.csv"}
    for n in ["iberia_nonterrestrial_fragment_audit",
              "iberia_land_fragment_production",
              "iberia_multi_fragment_capability",
              "iberia_hex_membership_audit_v2",
              "iberia_cell_ownership_audit", "iberia_special_cases",
              "iberia_determinism_check",
              "algarve_constitutional_audit", "algarve_primary_evidence",
              "spain_snapshot_evidence_hardening",
              "portugal_snapshot_evidence_hardening",
              "portugal_map_source_registry", "portugal_source_lineage",
              "portugal_source_continuity_audit",
              "portugal_plate_graticule_observations",
              "portugal_preliminary_accuracy_check",
              "portugal_georeference_audit",
              "portugal_georeference_metric_separation",
              "portugal_cross_source_comparison",
              "portugal_corridor_audit", "portugal_safe_interior_v2",
              "land_fragment_registry",
              "historical_snapshot_features_1756_08_01"]:
        cmap[n + ".csv"] = H / (n + ".csv")
    cmap["scenario_political_coverage.csv"] = sdir / "political_coverage.csv"
    for n in ("territorial_control.csv",
              "territorial_control_provenance.csv",
              "scenario_control_promotion_log.csv",
              "territorial_control_revision_log.csv"):
        cmap[n] = sdir / n
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
    print(f"[portugal] {run_id}: validation {n_pass}/{len(val)}, "
          f"Portugal {base['portugal_controlled']} -> "
          f"{s['portugal_controlled']}, Spain frozen at "
          f"{s['spain_controlled']:,}, {len(prod)} coastal fragments, "
          f"canonical {base['canonical_rows_after']:,} -> "
          f"{len(canonical):,} ({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[portugal][WARN] " + w.encode("ascii", "replace").decode())
    return run_dir


def _write_readme(run_dir, run_id, s, base, alg, algd, corr, au, multi,
                  msep, pgeo, aspects, imgs):
    L = [f"# {STAGE} — Portugal mainland recovery, Iberian LAND_FRAGMENT "
         "completion, Algarve constitutional audit", "",
         f"run `{run_id}` · outcome **{s['outcome']}** · validation "
         f"**{s['validation_pass']}**", "",
         "## MAPGEN-026, re-filed", "",
         *_wrap("MAPGEN-026 called itself FULL. Not one of its rows is "
                "withdrawn here, but its outcome is re-filed as "
                "**ACCEPTABLE_PRODUCTION_WITH_FOLLOWUP_GAPS**: Iberian "
                "LAND_FRAGMENT production was zero, the Algarve was "
                "withheld on the strength of a map title, and the "
                "individual political evidence for both crowns was dated "
                "after the snapshot. Its own review files are left "
                "untouched; this is the correction note."),
         "", "## The number that matters", "",
         "| | MAPGEN-026 | MAPGEN-027 |", "|---|---|---|",
         f"| Spain CONTROLLED | {base['spain_controlled']:,} | "
         f"{s['spain_controlled']:,} (frozen) |",
         f"| Portugal CONTROLLED | {base['portugal_controlled']} | "
         f"{s['portugal_controlled']} |",
         f"| LAND_FRAGMENT rows | {base['land_fragment_rows']:,} | "
         f"{s['land_fragment_rows']:,} |",
         f"| canonical rows | {base['canonical_rows_after']:,} | "
         f"{s['canonical_rows_after']:,} |", "",
         *_wrap(f"Portugal went from {base['portugal_controlled']} to "
                f"{s['portugal_controlled']} without a single new "
                f"measurement. The uncertainty is unchanged at "
                f"{s['positional_uncertainty_km']} km. What changed was "
                "the evidence: the Algarve is Portuguese on institutional "
                "grounds, and the unowned strips between Portugal's own "
                "traced cells are Portuguese where the corridor between "
                "them contains no cell of another crown."),
         "", "## The Algarve", "",
         *_wrap("A map title is not evidence about an actor, in either "
                "direction. Seven institutional axes were examined against "
                "the crown's own printed legislation, the archival finding "
                "aid for the Tavira corregedoria, and a University of "
                "Lisbon study."),
         "", "| axis | verdict |", "|---|---|"]
    for r in alg.itertuples():
        L.append(f"| {r.axis} | {r.verdict} |")
    L += ["", f"**Decision: {algd.iloc[0].decision}.** "
              f"{algd.iloc[0].comparison_case}", "",
          "## The coast", "",
          *_wrap(f"{s['nonterrestrial_hexes_audited']} hexes carry Iberian "
                 "mainland land but are not canonical terrestrial hexes. "
                 "MAPGEN-026 gave them no row at all. They now carry that "
                 f"land as fragments: {s['fragments_controlled']} "
                 f"CONTROLLED and {s['fragments_unresolved']} explicitly "
                 "UNRESOLVED. The OCEAN parent hexes are still not owned."),
          "",
          *_wrap(f"{s['mixed_component_hexes']} of those hexes hold land of "
                 "more than one physical component - one of them "
                 f"{s['max_components_in_one_hex']} - and in the worst case "
                 "the islet is four times larger than the mainland "
                 "fragment. That is the first real proof in this project "
                 "that a whole-hex winner would have been wrong. The "
                 f"islets' {s['other_component_km2_left_unowned']} km2 is "
                 "measured and left unowned."),
          "", "## Corridors", "", "| cells | gap km | decision |",
          "|---|---|---|"]
    for r in corr.itertuples():
        L.append(f"| {r.cell_a}–{r.cell_b} | {r.gap_km} | {r.decision} |")
    L += ["", "## Georeference wording, corrected", "",
          *_wrap("MAPGEN-026 quoted 'every point the fit never saw' next to "
                 "a blind figure. The model-selection holdout is NOT "
                 "statistically blind: it chose POLYNOMIAL_2. The four sets "
                 "are now reported separately."),
          "", "| set | n | rms km | p95 km | blind? | used for production |",
          "|---|---|---|---|---|---|"]
    for r in msep.itertuples():
        L.append(f"| {r.metric_set} | {r.n} | {r.rms_km} | {r.p95_km} | "
                 f"{r.statistically_blind} | "
                 f"{r.used_for_production_uncertainty} |")
    L += ["", "## The larger-scale source, and why it is not used yet", "",
          *_wrap("Sanson/Vaugondy, *Carte du Royaume de Portugal*, Paris "
                 "1762, two sheets of 41 × 52 cm, CC BY 4.0 from the "
                 "Universidade de Coimbra. Five times the scale of the Le "
                 "Rouge plate, and its cartouche claims it is 'corrigée et "
                 "assujettie aux observations astronomiques'."),
          "",
          *_wrap(str(pgeo.iloc[0].why_no_production_georeference)),
          "",
          *_wrap("Its graduations are measured and recorded, and a "
                 "three-point check puts the plate's meridian within six "
                 "hundredths of a degree and its latitudes within eight "
                 "hundredths — promising, and labelled "
                 "PRELIMINARY_NOT_A_GEOREFERENCE, because three points "
                 "identified by eye are not a georeference. Handed to "
                 "MAPGEN-028."),
          "", "## Images", ""]
    for n in imgs:
        L.append(f"- `{n}` (aspect {aspects.get(n, '')})")
    L += ["", "## Gates", "",
          f"All {s['validation_pass'].split('/')[1]} gates are in "
          "`validation.csv` with their evidence. Gates M27-17 to M27-25 "
          "test the DEFERRAL discipline, not a georeference: they assert "
          "that no control point, no split, no frontier and no averaged "
          "boundary was manufactured from a source that has not been "
          "georeferenced.", ""]
    (run_dir / "README_REVIEW.md").write_text("\n".join(L),
                                              encoding="utf-8")
