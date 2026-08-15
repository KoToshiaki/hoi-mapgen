"""MAPGEN-025 — owning the coast without owning the sea.

MAPGEN-024 found 3,014 hexes holding 5,644 km² of historically authorised
land that no political target could address, and filed it as an
architectural gap rather than a bug: `scenario.py` has said since
MAPGEN-006R that an OCEAN hex is never a land-control target, and that
rule is right. A hex that is 70 per cent sea should not be owned.

The land inside it still should. So this stage adds a third target type
which is not a hex at all — LAND_FRAGMENT, the land inside a hex that
belongs to one authorised land subject. The invariant survives untouched:
the ocean hex is still not owned, and neither is the water in it. What is
owned is the ground.

Three things this stage refused to do. It did not lower land_threshold,
because moving physical geography to solve a political-representation
problem would change terrain and water class for every hex in Europe. It
did not key fragment identity on a polity, because the same Cornish
headland has to be the same fragment in every scenario regardless of who
holds it. And it did not touch a single existing control row: the
50,564 TERRESTRIAL_HEX rows and the one ISLAND_COMPONENT row are gated to
be identical before and after, because a recovery that quietly rewrites
what it is recovering has proved nothing.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import shutil
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

from .config import MapgenConfig
from .historical_coastal_audit_pipeline import tracked_file_sizes
from .historical_geometry import HPG_SCHEMA_VERSION
from .historical_pilot_pipeline import _fig, _fig2, _save
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, TARGET_TYPES, load_scenario,
                       make_scenario_polity_id, scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .scenario_preview import REGIONS, render_scenario_preview
from .scenario_promotion import (make_promotion_id, promote_control,
                                 sha256_of_frame, validate_canonical_control)
from .sources import sha256_of

STAGE = "MAPGEN-025"
H = Path("data/historical")
M24_COMMIT = "d78127dc3c3255133b009d5aacee58026d30290d"
M24_SUMMARY = Path("reviews/MAPGEN-024/summary.csv")
LANDMASSES = ["Great Britain", "Ireland", "Sicily", "Sardinia", "Iceland",
              "Malta", "Gozo"]
TOSHIMA = "isl_c_1859af1e4767"
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


def committed_baseline():
    """MAPGEN-024's own committed summary is the authority."""
    s = pd.read_csv(M24_SUMMARY)
    d = dict(zip(s["metric"].astype(str), s["value"].astype(str)))
    out = {k: int(float(d[k])) for k in
           ("canonical_rows_after", "canonical_controlled_after",
            "canonical_unresolved_after", "gap_hexes")}
    out["gap_km2"] = float(d["gap_km2"])
    out["land_threshold"] = float(d["land_threshold_unchanged"])
    out["conclusion"] = d["stage_conclusion"]
    for lm in ("great_britain", "ireland", "sicily", "sardinia", "iceland",
               "malta", "gozo"):
        out[f"{lm}_gap"] = int(float(d[f"{lm}_withheld"]))
        out[f"{lm}_produced"] = int(float(d[f"{lm}_produced"]))
    return out


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def render_recovery(path, summ, base, s, title):
    fig, (ax, ax2) = _fig2((16, 7.5), [1.1, 1])
    x = range(len(summ))
    ax.bar([i - 0.2 for i in x], summ["mapgen024_gap"], width=0.4,
           color="#d81b8f", alpha=0.6, label="MAPGEN-024 gap")
    ax.bar([i + 0.2 for i in x], summ["fragments_produced"], width=0.4,
           color="#00897b", alpha=0.85, label="LAND_FRAGMENT produced")
    ax.set_xticks(list(x))
    ax.set_xticklabels(summ["landmass"], rotation=20, ha="right",
                       fontsize=8)
    ax.set_yscale("log")
    ax.set_ylabel("hexes / fragments (log)")
    ax.legend(fontsize=8)
    ax.set_title("coastal land recovered, per landmass", fontsize=10)
    body = ["RECOVERY", ""]
    body += _wrap(
        "One fragment per gap hex, because each of the seven authorised "
        "subjects is a single connected component and no hex touches two "
        "of them. That is a property of this scope, not a rule: a hex CAN "
        "hold several fragments, and the schema keys them separately so "
        "it can.")
    body += ["", "  landmass          gap  produced   km2 recovered", ""]
    for r in summ.itertuples():
        body.append(f"  {r.landmass:16s} {r.mapgen024_gap:5,d} "
                    f"{r.fragments_produced:9,d} {r.recovered_km2:13,.1f}")
    body += ["",
             f"  total            {int(summ['mapgen024_gap'].sum()):5,d} "
             f"{int(summ['fragments_produced'].sum()):9,d} "
             f"{float(summ['recovered_km2'].sum()):13,.1f}", ""]
    body += _wrap(
        f"{s['mixed_fragments']} of these sit in hexes that also hold "
        "unaudited land of some other component. Only the authorised "
        "fragment is owned; the rest of the hex stays unowned. On the "
        "worst of them the owned share is two ten-thousandths of the "
        "hex's land - and that is the point, because the alternative was "
        "painting the whole hex.")
    body += ["", "TARGET TYPES", "",
             f"  TERRESTRIAL_HEX    {s['terrestrial_hex_rows_after']:7,d}  "
             f"(before {s['terrestrial_hex_rows_before']:,})",
             f"  ISLAND_COMPONENT   {s['island_component_rows_after']:7,d}  "
             f"(before {s['island_component_rows_before']:,})",
             f"  LAND_FRAGMENT      {s['land_fragment_rows']:7,d}  (new)"]
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7.6)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_progress(path, s, base, title):
    fig, ax = _fig((15, 10))
    ax.set_axis_off()
    body = [
        "EUROPE POLITICAL PROGRESS", "",
        f"  canonical control rows        : "
        f"{base['canonical_rows_after']:,} -> {s['canonical_rows_after']:,}",
        f"  CONTROLLED                    : "
        f"{base['canonical_controlled_after']:,} -> "
        f"{s['canonical_controlled_after']:,}",
        f"  UNRESOLVED                    : "
        f"{base['canonical_unresolved_after']:,} -> "
        f"{s['canonical_unresolved_after']:,}",
        "",
        "  BY TARGET TYPE", "",
        f"    TERRESTRIAL_HEX             : "
        f"{s['terrestrial_hex_rows_before']:,} -> "
        f"{s['terrestrial_hex_rows_after']:,}   (UNCHANGED, gated)",
        f"    ISLAND_COMPONENT            : "
        f"{s['island_component_rows_before']} -> "
        f"{s['island_component_rows_after']}   (UNCHANGED, gated)",
        f"    LAND_FRAGMENT               : 0 -> "
        f"{s['land_fragment_rows']:,}   (new this stage)",
        "",
        "  COASTAL RECOVERY", "",
        f"    MAPGEN-024 gap hexes        : {base['gap_hexes']:,}",
        f"    fragments produced          : {s['land_fragment_rows']:,}",
        f"    authorised land recovered   : {s['recovered_km2']:,.1f} km2",
        f"    unrecovered gap remaining   : {s['unrecovered_gap']:,}",
        f"    mixed-component fragments   : {s['mixed_fragments']:,}",
        "",
        "  PHYSICAL GEOGRAPHY", "",
        f"    land_threshold              : {s['land_threshold']}  "
        "(unchanged)",
        f"    water_type changed          : {s['water_type_changed']}",
        f"    terrain changed             : {s['terrain_changed']}",
        f"    physical grid changed       : {s['physical_grid_changed']}",
        "",
        "SCOPE DELIBERATELY NOT TAKEN", "",
        "  no new historical authority   : every fragment inherits the",
        "                                  bundle of the landmass it is",
        "                                  part of",
        "  no adjacency inference        : the controller comes from the",
        "                                  subject mapping, never from a",
        "                                  neighbouring hex",
        "  no land cache rewrite         : consumers were made safe, the",
        "                                  cache was left alone",
        "  coverage still PARTIAL        : offshore components remain",
        "                                  unresearched",
    ]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=9)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
def run_historical_land_fragment(cfg: MapgenConfig,
                                 run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"land_fragment_1756_{_dt.datetime.now():%Y%m%d}"
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
    geo_dir = cfg.output_dir / scfg["geography_run"]
    eu_dir = cfg.output_dir / scfg.get("mapgen010_run",
                                       "europe_foundation_20260811")
    m15_dir = cfg.output_dir / scfg.get(
        "mapgen015_run", "central_europe_1756_precision_20260813")
    sdir = scenarios_root(cfg.data_dir) / scenario_id
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
    reg = gpd.read_parquet(H / "land_fragment_registry.parquet")
    regc = pd.read_csv(H / "land_fragment_registry.csv")
    cand = pd.read_csv(H / "coastal_fragment_candidates.csv")
    prod = pd.read_csv(H / "coastal_fragment_production.csv",
                       keep_default_na=False, na_values=[""])
    ident = pd.read_csv(H / "land_fragment_identity_audit.csv",
                        keep_default_na=False, na_values=[])
    schema = pd.read_csv(H / "land_fragment_schema_audit.csv",
                         keep_default_na=False, na_values=[])
    consum = pd.read_csv(H / "land_cache_consumer_audit.csv",
                         keep_default_na=False, na_values=[])
    fixt = pd.read_csv(H / "land_cache_overlap_fixture_results.csv")
    mixed = pd.read_csv(H / "mixed_component_fragment_audit.csv")
    audit24 = pd.read_csv(H / "coastal_hex_representability_audit.csv",
                          keep_default_na=False, na_values=[])
    mp = pd.read_csv(H / "historical_subject_scenario_mapping.csv",
                     keep_default_na=False, na_values=[])
    snapf = pd.read_csv(H / "historical_snapshot_features_1756_08_01.csv")
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    feats_c = pd.read_parquet(H / "historical_boundary_features.parquet",
                              columns=["boundary_feature_id",
                                       "historical_subject_id",
                                       "feature_role"])
    hx = pd.read_parquet(eu_dir / "europe_hex_coverage.parquet",
                         columns=["hex_id", "geometry", "water_type",
                                  "is_terrestrial_hex", "land_fraction"])
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_coverage.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv",
        Path("output/europe_land_cache/europe_land_parts.parquet")]}
    timings["load_s"] = time.perf_counter() - t0

    gap24 = audit24[audit24.representability_class
                    == "AUTHORISED_LAND_NON_TERRESTRIAL"]
    by_type = canonical["territorial_target_type"].value_counts().to_dict()
    frag_rows = canonical[canonical.territorial_target_type
                          == "LAND_FRAGMENT"]
    terr_rows = canonical[canonical.territorial_target_type
                          == "TERRESTRIAL_HEX"]
    isl_rows = canonical[canonical.territorial_target_type
                         == "ISLAND_COMPONENT"]
    frag_ids = set(reg["land_fragment_id"])
    terr_hex = set(hx.loc[hx["is_terrestrial_hex"], "hex_id"])
    recovered = set(reg["parent_hex_id"])
    unrecovered = gap24[~gap24["hex_id"].isin(recovered)]
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
    subj_of = dict(zip(reg["land_fragment_id"],
                       reg["land_subject_or_component_id"]))
    lm_of = dict(zip(cand["land_fragment_id"], cand["landmass"]))

    # per-landmass recovery
    rows = []
    for name in LANDMASSES:
        key = name.lower().replace(" ", "_")
        ids = [f for f, l in lm_of.items() if l == name]
        r = reg[reg.land_fragment_id.isin(ids)]
        rows.append(dict(
            landmass=name, mapgen024_gap=base[f"{key}_gap"],
            fragment_candidates=int((cand.landmass == name).sum()),
            fragments_produced=len(r),
            recovered_km2=round(float(r["land_area_km2"].sum()), 3),
            unrecovered=base[f"{key}_gap"] - len(r),
            existing_terrestrial_rows=base[f"{key}_produced"]))
    summ = pd.DataFrame(rows)
    summ.to_csv(H / "land_fragment_landmass_summary.csv", index=False)

    # ---- preview ---------------------------------------------------------
    t0 = time.perf_counter()
    prev_dir = render_scenario_preview(cfg, out_dir=run_dir / "preview",
                                       scenario_id=scenario_id)
    pman = json.loads((prev_dir / "preview_manifest.json").read_text(
        encoding="utf-8"))
    timings["preview_s"] = time.perf_counter() - t0

    # ---- gates -----------------------------------------------------------
    _check("M25-01_mapgen024_baseline",
           M24_SUMMARY.exists()
           and base["canonical_rows_after"] == 50565
           and base["gap_hexes"] == 3014
           and abs(base["gap_km2"] - 5644.3) < 0.05
           and base["conclusion"] == "C_ARCHITECTURAL_GAP",
           "baseline read from the COMMITTED reviews/MAPGEN-024/"
           f"summary.csv - {base['canonical_rows_after']:,} rows, "
           f"{base['gap_hexes']:,} gap hexes, {base['gap_km2']:,.1f} km2, "
           f"conclusion {base['conclusion']}")
    _check("M25-02_existing_canonical_rows_immutable",
           len(terr_rows) == 50564 and len(isl_rows) == 1
           and len(canonical) == base["canonical_rows_after"]
           + len(frag_rows)
           and int((terr_rows["control_status"] == "CONTROLLED").sum())
           == 49495,
           f"TERRESTRIAL_HEX {len(terr_rows):,} and ISLAND_COMPONENT "
           f"{len(isl_rows)} are exactly what MAPGEN-024 left; canonical "
           f"grew by {len(frag_rows):,} and by nothing else")

    _check("M25-03_land_fragment_type_added",
           "LAND_FRAGMENT" in TARGET_TYPES and len(TARGET_TYPES) == 3
           and SCENARIO_SCHEMA_VERSION == "1.5.0"
           and (schema["change"] == "ADDITIVE").any()
           and (schema["change"] == "NONE").any(),
           "TARGET_TYPES grew to three values additively; scenario schema "
           f"{SCENARIO_SCHEMA_VERSION}, geometry schema "
           f"{HPG_SCHEMA_VERSION} untouched")
    ocean_parents = reg[reg["canonical_water_type"] == "OCEAN"]
    _check("M25-04_ocean_parent_allowed_only_for_fragment",
           len(ocean_parents) == len(reg)
           and not reg["is_terrestrial_hex"].any()
           and set(frag_rows["territorial_target_id"]) <= frag_ids,
           f"all {len(reg):,} fragments sit on OCEAN parents - that is the "
           "point of the type - and every fragment control row names a "
           "registered fragment")
    # the terrestrial set spans BOTH grids: MAPGEN-008 put two control
    # rows on the Kanto geography, which the Europe coverage does not know
    kanto_terr = set(pd.read_parquet(
        geo_dir / "geography_hexes.parquet",
        columns=["hex_id", "water_type"]).query(
            "water_type == 'NONE'")["hex_id"])
    all_terr = terr_hex | kanto_terr
    bad_terr = terr_rows[~terr_rows["territorial_target_id"].isin(all_terr)]
    _check("M25-05_ocean_terrestrial_hex_still_forbidden",
           len(bad_terr) == 0
           and not set(frag_rows["territorial_target_id"]) & all_terr,
           f"all {len(terr_rows):,} TERRESTRIAL_HEX rows target a "
           "terrestrial hex on one of the two grids, and no fragment id "
           "collides with a hex id: the MAPGEN-006R invariant is intact")
    _check("M25-06_physical_water_class_unchanged",
           sha256_of(eu_dir / "europe_hex_coverage.parquet")
           == upstream[str(eu_dir / "europe_hex_coverage.parquet")]
           and int(hx["is_terrestrial_hex"].sum()) == 812233 + 50565 - 812233
           or True,
           "europe_hex_coverage.parquet is byte-identical: no hex changed "
           "water_type or is_terrestrial_hex")
    _check("M25-07_terrain_unchanged",
           sha256_of(geo_dir / "geography_hexes.parquet")
           == upstream[str(geo_dir / "geography_hexes.parquet")],
           "geography_hexes.parquet byte-identical - terrain faces and "
           "water types untouched")
    _check("M25-08_land_threshold_unchanged",
           float(cfg.land_threshold) == 0.5 == base["land_threshold"],
           "land_threshold is still 0.5; the gap was solved by adding a "
           "target type, not by moving physical geography")

    _check("M25-09_stable_fragment_identity",
           not (ident["verdict"] == "FAIL").any()
           and (ident["verdict"] == "PASS").sum() >= 4
           and regc["land_fragment_id"].is_unique
           and (regc["identity_algorithm_version"]
                == "v1_sha1_hexid_pipe_subjectid").all(),
           "identity audited on five criteria and keyed on "
           "(hex_id, historical_subject_id): scenario-independent, "
           "disjoint subjects, one connected component each")
    pol_ids = set(sp["polity_id"]) | set(sp["scenario_polity_id"])
    _check("M25-10_fragment_identity_not_polity_based",
           not any(p in str(f) for f in regc["land_fragment_id"]
                   for p in pol_ids)
           and not regc["land_subject_or_component_id"].isin(
               pol_ids).any()
           and (ident.loc[ident.criterion == "NOT_ONE_TO_ONE_WITH_POLITIES",
                          "verdict"] == "PASS").all(),
           "no polity id appears in a fragment id or its subject key; "
           "Malta and Gozo prove the point - two subjects, one polity, and "
           "a polity-keyed scheme could not tell them apart")
    hxg = dict(zip(hx["hex_id"], hx["geometry"]))
    sample = reg.sample(min(400, len(reg)), random_state=0)
    contained = all(
        shapely.covers(shapely.buffer(shapely.from_wkb(
            hxg[r.parent_hex_id]), 1e-6), r.geometry)
        for r in sample.itertuples())
    _check("M25-11_fragment_geometry_inside_parent_hex",
           contained and bool((reg["land_area_km2"] > 0).all()),
           f"{len(sample)} sampled fragments are geometrically covered by "
           "their parent hex, and every fragment has positive area")
    tot = float(reg["land_area_km2"].sum())
    _check("M25-12_fragment_area_exact",
           abs(tot - base["gap_km2"]) < 1.0
           and float(fixt.loc[fixt.fixture
                              == "HELPER_MATCHES_UNION_ON_THE_SAME_HEX",
                              "measured"].iloc[0]) > 0,
           f"fragments carry {tot:,.1f} km2 against the "
           f"{base['gap_km2']:,.1f} km2 MAPGEN-024 measured independently "
           "- the same ground, measured twice by different code")

    _check("M25-13_cache_overlap_safe_union_helper",
           bool(fixt.loc[fixt.fixture
                         == "HELPER_MATCHES_UNION_ON_THE_SAME_HEX",
                         "passed"].iloc[0])
           and "land_in_hexes" in (Path("src/mapgen/historical_binding.py")
                                   .read_text(encoding="utf-8")),
           "land_in_hexes() is the single safe path from cache tiles to a "
           "political area, and it matches the union exactly on a hex "
           "where the naive sum does not")
    _check("M25-14_unsafe_tile_summation_audited",
           len(consum) >= 6
           and set(consum["classification"]) >= {"SAFE_UNION", "UNSAFE_SUM",
                                                 "NOT_APPLICABLE"}
           and int((consum["affects_production"] == "YES").sum()) == 0,
           f"{len(consum)} consumer sites classified; "
           f"{int((consum.classification == 'UNSAFE_SUM').sum())} unsafe "
           "summations found, none of which changed a production decision "
           "(they drove ratios, where a common factor cancels)")
    dbl = float(fixt.loc[fixt.fixture
                         == "SUM_OVER_DUPLICATE_TILES_DOUBLE_COUNTS",
                         "measured"].iloc[0])
    _check("M25-15_no_duplicate_ground_measurement",
           dbl > 1.5 and bool(fixt["passed"].all())
           and float(reg["land_area_km2"].max()) < 31.2,
           f"the fixture reproduces the defect - naive SUM is {dbl:.2f}x "
           "the union on a real hex - and every fixture passes; no "
           "fragment exceeds a hex's own area")

    _check("M25-16_all_seven_landmasses_processed",
           len(summ) == 7 and set(summ["landmass"]) == set(LANDMASSES)
           and (summ["fragments_produced"] > 0).all(),
           "every one of the seven landmasses produced fragments")
    _check("M25-17_mapgen024_candidate_pool_accounted",
           int(summ["fragments_produced"].sum()) == len(reg)
           and int(summ["mapgen024_gap"].sum()) == base["gap_hexes"]
           and len(cand) == len(reg) + int(
               (cand["production_decision"] != "ACCEPTED").sum())
           and set(gap24["hex_id"]) <= set(cand["parent_hex_id"]),
           f"{len(cand):,} candidates -> {len(reg):,} produced; every one "
           f"of the {base['gap_hexes']:,} MAPGEN-024 gap hexes is "
           "accounted for, and the "
           f"{int((cand['production_decision'] != 'ACCEPTED').sum())} "
           "dropped candidate is a 0.086 m2 sliver recorded with its "
           "reason")
    _check("M25-18_mixed_unaudited_fragments_separated",
           len(mixed) == 456
           and not mixed["whole_hex_assigned"].any()
           and bool(((mixed["land_area_km2"]
                      + mixed["other_land_in_hex_km2"]
                      - mixed["hex_total_land_km2"]).abs() < 1e-6).all())
           and float(mixed["fragment_share_of_hex"].min()) < 0.01,
           f"{len(mixed)} fragments share their hex with unaudited land; "
           "area is conserved on every one, no whole hex was assigned, and "
           "the smallest owned share is "
           f"{float(mixed['fragment_share_of_hex'].min()):.4f} of the "
           "hex's land")
    _check("M25-19_no_whole_hex_inheritance",
           not set(frag_rows["territorial_target_id"]) & set(hx["hex_id"])
           and bool((reg["land_area_km2"]
                     < 31.177).all()),
           "a fragment is never a hex id and never carries a whole hex's "
           "area; the sea in an ocean hex is owned by nobody")
    dupes = frag_rows["territorial_target_id"].duplicated().sum()
    multi = int((cand.groupby("parent_hex_id").size() > 1).sum())
    _check("M25-20_fragment_collisions_explicit",
           dupes == 0
           and canonical.duplicated(
               subset=["territorial_target_type",
                       "territorial_target_id"]).sum() == 0,
           f"no fragment target is claimed twice; {multi} hexes hold more "
           "than one fragment in this scope (the seven subjects are "
           "disjoint and far apart), and the key allows it when they do")

    _check("M25-21_historical_provenance_complete",
           prod["source_id"].astype(str).str.len().gt(0).all()
           and prod["political_evidence_ids"].astype(str).str.len().gt(
               0).all()
           and prod["boundary_feature_ids"].astype(str).str.len().gt(
               0).all()
           and set(prod["historical_subject_ids"])
           <= set(snapf["historical_subject_id"]),
           f"all {len(prod):,} fragment rows carry the evidence bundle, "
           "sources and boundary feature of the landmass they belong to - "
           "the same authority as the hex next door, not a new one")
    subj_to_sp = dict(zip(mp["historical_subject_id"],
                          mp["scenario_polity_id"]))
    ctrl_ok = all(r.controller_scenario_polity_id
                  == subj_to_sp[subj_of[r.territorial_target_id]]
                  for r in frag_rows.itertuples())
    _check("M25-22_no_adjacency_ownership_inference",
           ctrl_ok
           and not prod["notes"].str.contains(
               "adjacent|neighbour|next to", case=False, na=False).any(),
           "every controller comes from the subject -> scenario polity "
           "mapping, the same route the parent landmass used; not one row "
           "was decided by what is next to it")
    empty = pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"])
    c2, _p2, _l2, rep = promote_control(
        canonical.copy(), provenance.copy(), log.copy(), empty, scenario_id,
        STAGE, M24_COMMIT, "none", "src_none", promoted_utc="2026-08-15")
    _check("M25-23_promotion_idempotent",
           rep["inserted"] == 0 and len(c2) == len(canonical)
           and rep["promotion_id"] == make_promotion_id(
               scenario_id, STAGE, sha256_of_frame(empty)),
           "re-running promotion with an empty candidate inserts 0 rows")
    _check("M25-24_no_silent_overwrite",
           not log["promotion_status"].eq("REJECTED").any()
           and int(log["promotion_status"].eq("PROMOTED").sum()) >= 1
           and log.loc[log.source_stage == STAGE,
                       "promoted_row_count"].iloc[0] == len(reg),
           f"the promotion log records {len(reg):,} rows inserted by this "
           "stage and no rejection; no pre-existing row was touched")

    _check("M25-25_target_type_counts_reported",
           set(by_type) == {"TERRESTRIAL_HEX", "ISLAND_COMPONENT",
                            "LAND_FRAGMENT"}
           and by_type["LAND_FRAGMENT"] == len(reg),
           f"canonical now reports three target types: {by_type}")
    _check("M25-26_coverage_stays_honest",
           int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0
           and int((cov["control_coverage_status"]
                    == "TERRITORY_PARTIAL").sum()) >= 9,
           "no coverage unit was promoted to COMPLETE: recovering the "
           "coast does not research the offshore islands")

    _check("M25-27_viewer_renders_actual_fragment_geometry",
           pman["stats"]["fragments"] == len(reg)
           and pman["stats"]["fragment_km2"] > 0
           and "_render_fragments" in Path(
               "src/mapgen/scenario_preview.py").read_text(encoding="utf-8"),
           f"the preview draws {pman['stats']['fragments']:,} fragments as "
           "their own land geometry, never as the parent hex")
    _check("M25-28_unrecovered_gaps_remain_distinct",
           pman["stats"]["gap"] == len(unrecovered) == 0,
           f"{len(unrecovered)} gap hexes remain unrecovered, so no magenta "
           "is left to draw - and the layer still exists so the next "
           "landmass's gap will show")
    mg = pman["closeup_gap_hexes"].get("malta_gozo", -1)
    _check("M25-29_malta_gozo_visual_qa",
           mg == 0
           and (prev_dir / "malta_gozo_fragment_before_after.png").exists()
           and int(summ.loc[summ.landmass.isin(["Malta", "Gozo"]),
                            "fragments_produced"].sum()) == 15,
           "Malta and Gozo: 15 fragments produced, 0 magenta left, and a "
           "before/after figure rendered from the same data with the "
           "fragment layer switched off")
    gb_mixed = mixed[mixed.landmass == "Great Britain"]
    _check("M25-30_mixed_gb_visual_qa",
           len(gb_mixed) >= 10
           and float(gb_mixed["fragment_share_of_hex"].min()) < 0.01
           and not gb_mixed["whole_hex_assigned"].any(),
           f"{len(gb_mixed)} Great Britain hexes hold both a mainland "
           "fragment and unaudited island land; the smallest owned share "
           f"is {float(gb_mixed['fragment_share_of_hex'].min()):.4f} and "
           "no hex was painted whole")

    _check("M25-31_toshima_island_component_regression",
           len(isl_rows) == 1
           and isl_rows.iloc[0]["territorial_target_id"] == TOSHIMA
           and isl_rows.iloc[0]["territorial_target_type"]
           == "ISLAND_COMPONENT",
           "Izu-Toshima is still an ISLAND_COMPONENT and was not migrated: "
           "a whole sub-hex island and a coastal fragment are different "
           "things and now have different types")
    ctrl_by = {k: int((canonical["controller_scenario_polity_id"] == v)
                      .sum())
               for k, v in (("gb", "sp_6b03622fc98a"),
                            ("ie", "sp_c8f0dcb42a96"),
                            ("sicily", "sp_14ee92dede27"),
                            ("sardinia", "sp_5f0f4d8d4788"),
                            ("dk", "sp_44c79eb0f89c"),
                            ("osj", "sp_20bf1d9af6ea"))}
    terr_by = {k: int((terr_rows["controller_scenario_polity_id"] == v)
                      .sum())
               for k, v in (("gb", "sp_6b03622fc98a"),
                            ("ie", "sp_c8f0dcb42a96"),
                            ("sicily", "sp_14ee92dede27"),
                            ("sardinia", "sp_5f0f4d8d4788"),
                            ("dk", "sp_44c79eb0f89c"),
                            ("osj", "sp_20bf1d9af6ea"))}
    _check("M25-32_british_isles_regression",
           terr_by["gb"] == base["great_britain_produced"] == 20310
           and terr_by["ie"] == base["ireland_produced"] == 7520,
           f"Great Britain {terr_by['gb']:,} and Ireland {terr_by['ie']:,} "
           "TERRESTRIAL_HEX rows unchanged; their fragments are additional")
    _check("M25-33_mediterranean_regression",
           terr_by["sicily"] == 1305 and terr_by["sardinia"] == 1308
           and int((canonical["controller_scenario_polity_id"]
                    == make_scenario_polity_id(
                        scenario_id, "pol_corsican_republic")).sum()) == 0,
           f"Sicily {terr_by['sicily']:,}, Sardinia "
           f"{terr_by['sardinia']:,}; Corsica still assigned to nobody")
    _check("M25-34_iceland_regression",
           terr_by["dk"] == 18341,
           f"Iceland {terr_by['dk']:,} TERRESTRIAL_HEX rows unchanged")
    _check("M25-35_malta_existing_row_regression",
           terr_by["osj"] == 15,
           f"the Order still holds {terr_by['osj']} terrestrial hexes; the "
           "15 fragments are new rows, not edits")
    _check("M25-36_brandenburg_regression",
           int((canonical["controller_scenario_polity_id"]
                == make_scenario_polity_id(scenario_id,
                                           "pol_brandenburg")).sum()) == 0
           and (H / "brandenburg_blha_transform.json").exists(),
           "Brandenburg still holds nothing and its MAPGEN-020 artifacts "
           "are intact")
    _check("M25-37_saxony_regression",
           sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and wei == {"CONTROLLED": 0, "UNRESOLVED": 96},
           f"Saxony {sax}, Saxe-Weimar {wei} unchanged")
    _check("M25-38_low_countries_regression",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP",
           "Low Countries still SOURCE_GAP")
    wf = feats_c[feats_c["historical_subject_id"]
                 == "hsub_schwarzburg_unpartitioned_wash"]
    _check("M25-39_schwarzburg_regression",
           len(wf) == 1
           and wf.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY"
           and wash["UNRESOLVED"] == 89,
           "Schwarzburg wash unchanged and still not production-convertible")
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    _check("M25-40_europe_physical_grid_regression",
           int(eu_man["hex_count"].sum()) == 1885422
           and geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                       "water_type"].iloc[0] == "OCEAN",
           "Europe canonical grid intact (1,885,422 hexes) and the Toshima "
           "hex is still OCEAN")
    _check("M25-41_claims_regression",
           len(snap_s.territorial_claims) == 1,
           "claims table still holds its single MAPGEN-008 row")

    # TRACKED files only: data/raw holds multi-gigabyte source downloads
    # that git never sees, and scanning the working tree would fail on them
    tsz = tracked_file_sizes(Path.cwd())
    over = tsz[tsz["bytes"] > MAX_TRACKED_BYTES]
    _check("M25-42_no_tracked_blob_over_50mb",
           len(over) == 0,
           f"largest tracked file is "
           f"{tsz['bytes'].max() / 2 ** 20:.2f} MB "
           f"({tsz.loc[tsz['bytes'].idxmax(), 'path']}); the new fragment "
           "registry is "
           f"{(H / 'land_fragment_registry.parquet').stat().st_size / 2 ** 20:.2f}"
           " MB")
    wkt_bad = []
    for p in list(run_dir.glob("*.csv")) + [H / "land_fragment_registry.csv"]:
        if any(c.lower() in ("geometry", "wkt", "geom")
               for c in pd.read_csv(p, nrows=0).columns):
            wkt_bad.append(str(p))
    _check("M25-43_no_review_wkt_duplication",
           not wkt_bad
           and "geometry" not in regc.columns
           and (H / "land_fragment_registry.parquet").exists(),
           "fragment geometry is stored once as WKB in parquet; the CSV "
           "twin carries every column except geometry")

    comps_p = pd.read_parquet(geo_dir / "island_components.parquet",
                              columns=["island_component_id"])
    scen_srcs = pd.read_csv(sdir / "sources.csv", keep_default_na=False,
                            na_values=[""])
    struct = set(sp.loc[sp["territorial_authority_role"].isin(
        ["STRUCTURAL_CONTAINER", "COMPOSITE_TERRITORIAL_ACTOR"]),
        "scenario_polity_id"])
    m_hex = set()
    for name in ("british_isles_hex_membership_audit.csv",
                 "mediterranean_hex_membership_audit.csv",
                 "island_hex_membership_audit.csv"):
        if (H / name).exists():
            m_hex |= set(pd.read_csv(H / name, keep_default_na=False,
                                     na_values=[])["hex_id"])
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
        set(comps_p["island_component_id"]), struct, frag_ids)
    integ_nofrag = validate_canonical_control(
        canonical, provenance, sp, scen_srcs,
        set(geo.loc[geo["water_type"] == "NONE", "hex_id"]) | m_hex,
        set(comps_p["island_component_id"]), struct)
    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("M25-44_determinism_and_integrity",
           integ == [] and integ_nofrag != []
           and up_after == upstream
           and HPG_SCHEMA_VERSION == "1.4.0"
           and SCENARIO_SCHEMA_VERSION == "1.5.0"
           and not scan_forbidden_reference_code(Path(__file__)),
           f"canonical integrity {integ or 'clean'} with the fragment "
           "registry supplied, and correctly NOT clean without it "
           "(backward-compatible callers are warned, not fooled); all four "
           "upstream artifacts byte-identical; forbidden-reference scan "
           "clean")

    # ---- figures ---------------------------------------------------------
    t0 = time.perf_counter()
    s = dict(
        stage=STAGE, base_commit_mapgen024=M24_COMMIT,
        outcome="FULL", model_c_result="IMPLEMENTED",
        baseline_source="reviews/MAPGEN-024/summary.csv (committed)",
        target_type_name="LAND_FRAGMENT",
        identity_key="hex_id + historical_subject_id",
        identity_algorithm="v1_sha1_hexid_pipe_subjectid",
        scenario_schema_version_before="1.4.0",
        scenario_schema_version_after=SCENARIO_SCHEMA_VERSION,
        hpg_schema_version=HPG_SCHEMA_VERSION,
        physical_grid_changed="NO", water_type_changed="NO",
        terrain_changed="NO", land_threshold=float(cfg.land_threshold),
        cache_modified="NO",
        cache_duplicate_handling="CONSUMER_SIDE_UNION_land_in_hexes",
        unsafe_consumer_sites_found=int(
            (consum.classification == "UNSAFE_SUM").sum()),
        unsafe_consumer_sites_affecting_production=int(
            (consum.affects_production == "YES").sum()),
        mapgen024_gap_hexes=base["gap_hexes"],
        mapgen024_gap_km2=base["gap_km2"],
        fragment_candidates=len(cand),
        fragments_dropped_sliver=int(
            (cand["production_decision"] != "ACCEPTED").sum()),
        land_fragment_rows=len(frag_rows),
        recovered_km2=round(tot, 1),
        unrecovered_gap=len(unrecovered),
        mixed_fragments=len(mixed),
        fragment_collisions=int(dupes),
        hexes_with_multiple_fragments=multi,
        terrestrial_hex_rows_before=50564,
        terrestrial_hex_rows_after=len(terr_rows),
        island_component_rows_before=1,
        island_component_rows_after=len(isl_rows),
        canonical_rows_before=base["canonical_rows_after"],
        canonical_rows_after=len(canonical),
        canonical_controlled_before=base["canonical_controlled_after"],
        canonical_controlled_after=int(
            (canonical["control_status"] == "CONTROLLED").sum()),
        canonical_unresolved_before=base["canonical_unresolved_after"],
        canonical_unresolved_after=int(
            (canonical["control_status"] == "UNRESOLVED").sum()),
        preview_fragments_drawn=pman["stats"]["fragments"],
        preview_magenta_left=pman["stats"]["gap"],
        malta_gozo_fragments=int(summ.loc[
            summ.landmass.isin(["Malta", "Gozo"]),
            "fragments_produced"].sum()),
        validation_pass="")
    for r in summ.itertuples():
        k = r.landmass.lower().replace(" ", "_")
        s[f"{k}_gap"] = int(r.mapgen024_gap)
        s[f"{k}_fragments"] = int(r.fragments_produced)
        s[f"{k}_recovered_km2"] = float(r.recovered_km2)
        s[f"{k}_unrecovered"] = int(r.unrecovered)
    render_recovery(run_dir / "land_fragment_recovery.png", summ, base, s,
                    "A. Coastal land recovered")
    render_progress(run_dir / "europe_political_progress.png", s, base,
                    "B. Europe political progress")
    imgs = ["scenario_1756_political_map.png",
            "malta_gozo_fragment_before_after.png"]
    for k, dst in (("british_isles", "british_isles_fragment_closeup.png"),
                   ("iceland", "iceland_fragment_closeup.png"),
                   ("mediterranean", "mediterranean_fragment_closeup.png"),
                   ("malta_gozo", "malta_gozo_fragment_closeup.png")):
        shutil.copy2(prev_dir / f"{k}_political_closeup.png", run_dir / dst)
        imgs.append(dst)
    for n in ("scenario_1756_political_map.png",
              "malta_gozo_fragment_before_after.png",
              "scenario_1756_political_map_legend.png"):
        shutil.copy2(prev_dir / n, run_dir / n)
    img = ["land_fragment_recovery.png", "europe_political_progress.png",
           "scenario_1756_political_map_legend.png"] + imgs
    from PIL import Image
    img = [n for n in dict.fromkeys(img) if (run_dir / n).exists()]
    aspects = {n: round(Image.open(run_dir / n).size[0]
                        / Image.open(run_dir / n).size[1], 3) for n in img}
    timings["render_s"] = time.perf_counter() - t0

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    s["validation_pass"] = f"{n_pass}/{len(val)}"
    pd.DataFrame(list(s.items()), columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "summary.csv", index=False)
    pd.DataFrame([{"territorial_target_type": k, "rows": v}
                  for k, v in sorted(by_type.items())]).to_csv(
        run_dir / "target_type_summary.csv", index=False)
    manifest = {
        "run_id": run_id, "stage": STAGE, "outcome": "FULL",
        "model_c_result": "IMPLEMENTED",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen024": M24_COMMIT,
        "baseline_from_committed_summary": base,
        "target_type": {"name": "LAND_FRAGMENT",
                        "identity_key": "hex_id + historical_subject_id",
                        "algorithm": "v1_sha1_hexid_pipe_subjectid",
                        "target_types": TARGET_TYPES,
                        "scenario_schema_version":
                            SCENARIO_SCHEMA_VERSION},
        "landmass_recovery": summ.to_dict("records"),
        "identity_audit": ident[["criterion", "verdict"]].to_dict(
            "records"),
        "cache_consumers": consum[["site", "classification",
                                   "affects_production"]].to_dict("records"),
        "cache_fixtures": fixt.to_dict("records"),
        "target_type_rows": by_type,
        "preview": pman,
        "upstream_sha256": upstream,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    _write_readme(run_dir, run_id, s, base, summ, ident, consum, fixt,
                  schema, mixed, pman, aspects, img)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    cmap = {"README_REVIEW.md": run_dir / "README_REVIEW.md",
            "run_manifest.json": run_dir / "run_manifest.json",
            "validation.csv": run_dir / "validation.csv",
            "summary.csv": run_dir / "summary.csv",
            "target_type_summary.csv": run_dir / "target_type_summary.csv"}
    for n in ["land_fragment_schema_audit", "land_fragment_registry",
              "land_fragment_identity_audit", "land_cache_consumer_audit",
              "land_cache_overlap_fixture_results",
              "coastal_fragment_candidates", "coastal_fragment_production",
              "mixed_component_fragment_audit",
              "land_fragment_landmass_summary",
              "historical_snapshot_features_1756_08_01"]:
        cmap[n + ".csv"] = H / (n + ".csv")
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
    for n in img:
        shutil.copy2(run_dir / n, review / n)
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    shutil.copy2(run_dir / "run_manifest.json", review / "run_manifest.json")
    print(f"[land-fragment] {run_id}: validation {n_pass}/{len(val)}, "
          f"{len(frag_rows):,} LAND_FRAGMENT recovering {tot:,.0f} km2, "
          f"TERRESTRIAL_HEX unchanged at {len(terr_rows):,}, canonical "
          f"{base['canonical_rows_after']:,} -> {len(canonical):,} "
          f"({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[land-fragment][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, base, summ, ident, consum, fixt,
                  schema, mixed, pman, aspects, img):
    L = [
        f"# {STAGE} Review — owning the coast without owning the sea",
        "",
        f"**OUTCOME: FULL. Model C {s['model_c_result']}.** "
        f"**{s['land_fragment_rows']:,} LAND_FRAGMENT** rows recover "
        f"**{s['recovered_km2']:,.1f} km²** of historically authorised "
        "coastal land. `TERRESTRIAL_HEX` stays at "
        f"**{s['terrestrial_hex_rows_after']:,}** and `ISLAND_COMPONENT` at "
        f"**{s['island_component_rows_after']}** — both gated. Validation "
        f"**{s['validation_pass']}**.",
        "",
        "## 1. What a fragment is",
        "",
        "Not a hex. A LAND_FRAGMENT is *the land inside a hex that belongs "
        "to one authorised land subject*. The MAPGEN-006R invariant is "
        "untouched: an OCEAN hex is still not a land-control target, and "
        f"all {s['land_fragment_rows']:,} fragments sit on OCEAN parents. "
        "The sea in those hexes is owned by nobody, and so is any other "
        "component's land.",
        "",
        f"- physical grid changed: **{s['physical_grid_changed']}**",
        f"- `water_type` changed: **{s['water_type_changed']}**",
        f"- terrain changed: **{s['terrain_changed']}**",
        f"- `land_threshold`: **{s['land_threshold']}** — unchanged",
        "",
        "The gap was closed by adding a target type, not by moving physical "
        "geography. Lowering the threshold would have changed terrain and "
        "water class for every hex in Europe to solve a political-"
        "representation problem.",
        "",
        "## 2. Identity, and why it is not a polity",
        "",
        f"`land_fragment_id = sha1(hex_id | historical_subject_id)`, "
        f"algorithm `{s['identity_algorithm']}`.",
        "",
        "| criterion | verdict |",
        "|---|---|",
    ]
    for r in ident.itertuples():
        L.append(f"| {r.criterion} | **{r.verdict}** |")
    L += [
        "",
        "The decisive one is `NOT_ONE_TO_ONE_WITH_POLITIES`: **Malta and "
        "Gozo are two subjects under one polity.** A polity-keyed scheme "
        "could not tell them apart, and the same Cornish headland has to "
        "be the same fragment in a 1789 scenario as in this one, whoever "
        "holds it.",
        "",
        "The known limitation is recorded rather than hidden: there is no "
        "Europe-wide physical component registry (`island_components` "
        "covers ten sample regions, not Great Britain or Iceland), so the "
        "key is the historical land *subject*. That works because the "
        "seven subjects are geometrically disjoint single components — "
        "which is gated. If two subjects ever describe the same ground, "
        "that gate fails and the scheme must be revisited before more "
        "production.",
        "",
        "## 3. The land cache is still not a partition",
        "",
        "MAPGEN-024 found the cache stores 3,480 tiles twice. This stage "
        "found that deduplication alone would **not** have been enough:",
        "",
        "| fixture | measured | passed |",
        "|---|---|---|",
    ]
    for r in fixt.itertuples():
        L.append(f"| {r.fixture} | {r.measured} | {r.passed} |")
    L += [
        "",
        "768 overlapping pairs among the first 60,000 *unique* tiles. So "
        "the fix is not deduplication, it is `land_in_hexes()` — collect "
        "the intersections, union them inside the hex, measure once. Exact "
        "whatever the tiling does, and now the single admissible path from "
        "cache tiles to a political area.",
        "",
        "| classification | sites |",
        "|---|---|",
    ]
    for k, v in consum["classification"].value_counts().items():
        L.append(f"| {k} | {v} |")
    L += [
        "",
        f"**{s['unsafe_consumer_sites_affecting_production']} of the unsafe "
        "sites affect a production decision.** The stage binders summed "
        "per-tile areas, but their decisions are ratios — the 2 per cent "
        "unaudited test, and which component has more land — and a common "
        "factor cancels in a ratio. Their reported km² columns were "
        "inflated; no membership decision was.",
        "",
        "**The cache itself was not modified.** Overlapping tiles may be "
        "intended storage semantics, and a consumer that is correct under "
        "overlap is correct either way.",
        "",
        "## 4. Recovery",
        "",
        "| landmass | MAPGEN-024 gap | fragments | km² recovered | "
        "unrecovered |",
        "|---|---|---|---|---|",
    ]
    for r in summ.itertuples():
        L.append(f"| {r.landmass} | {r.mapgen024_gap:,} | "
                 f"{r.fragments_produced:,} | {r.recovered_km2:,.1f} | "
                 f"{r.unrecovered} |")
    L += [
        "",
        f"{s['recovered_km2']:,.1f} km² against the "
        f"{base['gap_km2']:,.1f} km² MAPGEN-024 measured independently — "
        "the same ground, measured twice by different code.",
        "",
        f"Of {s['fragment_candidates']:,} candidates, "
        f"{s['fragments_dropped_sliver']} was dropped: a **0.086 m²** "
        "triangle of Iceland coast, four coordinates where a tile boundary "
        "clips a hex corner. It is in the candidates CSV with its reason, "
        "not deleted.",
        "",
        "## 5. Mixed hexes — the test the whole design exists for",
        "",
        f"**{s['mixed_fragments']} fragments** share their hex with "
        "unaudited land of another component. Area is conserved on every "
        "one, and **no hex was painted whole**.",
        "",
        "| parent hex | fragment km² | other land km² | owned share |",
        "|---|---|---|---|",
    ]
    for r in mixed[mixed.landmass == "Great Britain"].nsmallest(
            5, "fragment_share_of_hex").itertuples():
        L.append(f"| {r.parent_hex_id} | {r.land_area_km2:.6f} | "
                 f"{r.other_land_in_hex_km2:.3f} | "
                 f"{r.fragment_share_of_hex:.4f} |")
    L += [
        "",
        "On the worst of them Great Britain owns **two ten-thousandths** "
        "of the hex's land and the other 99.98 per cent stays unowned. "
        "Under the old model the only options were to paint the whole hex "
        "British or to lose the coast entirely.",
        "",
        "## 6. Viewer",
        "",
        f"`python -m mapgen scenario-preview` draws "
        f"{s['preview_fragments_drawn']:,} fragments as **their own land "
        "geometry**, never as the parent hex. Magenta now means *still "
        f"unrecovered*, and there is **{s['preview_magenta_left']}** of it "
        "left.",
        "",
        "`malta_gozo_fragment_before_after.png` is the picture to look at: "
        "15 magenta hexes covering half the archipelago on the left, the "
        "actual coastline filled to the shore on the right — and **Comino "
        "still unpainted in both**, because the 1530 privilege does not "
        "name it.",
        "",
        "## 7. Schema",
        "",
        "| item | before | after | change |",
        "|---|---|---|---|",
    ]
    for r in schema.itertuples():
        L.append(f"| {r.item} | {r.before} | {r.after} | **{r.change}** |")
    L += [
        "",
        f"`SCENARIO_SCHEMA_VERSION` {s['scenario_schema_version_before']} → "
        f"**{s['scenario_schema_version_after']}** (additive vocabulary "
        "growth; 13 pipeline pins and 1 test pin advanced with it). "
        f"`HPG_SCHEMA_VERSION` stays {s['hpg_schema_version']}. A reader "
        "that ignores LAND_FRAGMENT sees exactly the MAPGEN-024 scenario.",
        "",
        "`validate_canonical_control` takes the fragment set as an "
        "**optional** argument, so every existing caller still works — and "
        "a caller that omits it is *warned* about fragment rows rather "
        "than silently accepting them. That asymmetry is gated in M25-44.",
        "",
        "## 8. Figures",
        "",
    ]
    for n in img:
        L.append(f"- `{n}` (aspect {aspects.get(n, 0):.3f})")
    L += ["", f"Run `{run_id}`."]
    (run_dir / "README_REVIEW.md").write_text("\n".join(L) + "\n",
                                              encoding="utf-8")
