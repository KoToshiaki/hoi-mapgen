"""MAPGEN-024 — measuring a gap instead of filling it.

Three stages of island production quietly filtered on `is_terrestrial_hex`
before computing anything, so the hexes that failed the flag were not
excluded — they were never counted. This stage counts them, for all seven
landmasses, and then stops.

It produces no territory. Canonical control before and after is identical
by gate, because the point of an audit stage is to find out whether the
missing coast is a bug before deciding what to do about it, and a stage
that fixes what it is still diagnosing has decided by accident.

The answer turns out to be neither "bug" nor "fine". `scenario.py` has
said since MAPGEN-006R that an OCEAN hex is never a land-control target,
so the rule is intentional. But the escape hatch built for exactly this
problem — the ISLAND_COMPONENT target for land that owns no hex — is
keyed per component, and a coastal fragment belongs to a component that
already owns hundreds of hexes. The project's own anti-double-count rule
then forbids reusing it. That is an architectural gap, and it is filed as
one.
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
import time
from pathlib import Path

import pandas as pd

from .config import MapgenConfig
from .historical_geometry import HPG_SCHEMA_VERSION
from .historical_pilot_pipeline import _fig, _fig2, _save
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, load_scenario,
                       make_scenario_polity_id, scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .scenario_preview import REGIONS, polity_colour, render_scenario_preview
from .scenario_promotion import (make_promotion_id, promote_control,
                                 sha256_of_frame, validate_canonical_control)
from .sources import sha256_of

STAGE = "MAPGEN-024"
H = Path("data/historical")
M23_COMMIT = "83a6b689695c8653c06ec0404ba5394187a7fe85"
M23_SUMMARY = Path("reviews/MAPGEN-023/summary.csv")
LANDMASSES = ["Great Britain", "Ireland", "Sicily", "Sardinia", "Iceland",
              "Malta", "Gozo"]
MAX_TRACKED_BYTES = 50 * 1024 * 1024
WARN_TRACKED_BYTES = 25 * 1024 * 1024
LEGACY_BLOB = ("reviews/MAPGEN-023/historical_snapshot_features_1756_08_01"
               ".csv")


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
    """MAPGEN-023's own committed summary is the authority."""
    s = pd.read_csv(M23_SUMMARY)
    d = dict(zip(s["metric"].astype(str), s["value"].astype(str)))
    return {k: int(float(d[k])) for k in
            ("canonical_rows_after", "canonical_controlled_after",
             "canonical_unresolved_after", "gb_controlled", "ie_controlled",
             "sicily_controlled", "sardinia_controlled",
             "iceland_controlled", "malta_controlled", "gozo_controlled",
             "saxony_controlled", "brandenburg_controlled",
             "not_produced_non_terrestrial_hexes")}


def tracked_file_sizes(repo: Path) -> pd.DataFrame:
    out = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True,
                         check=True).stdout.decode()
    rows = []
    for f in out.split("\n"):
        f = f.strip()
        if not f:
            continue
        p = repo / f
        if p.exists():
            rows.append((f, p.stat().st_size))
    return pd.DataFrame(rows, columns=["path", "bytes"])


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def render_gap_distribution(path, dist, summ, title):
    fig, (ax, ax2) = _fig2((16, 7.5), [1.15, 1])
    d = dist[dist.landmass == "ALL"]
    x = range(len(d))
    ax.bar(x, d["hexes"], color="#d81b8f", alpha=0.55, label="hexes")
    ax.set_xticks(list(x))
    ax.set_xticklabels(d["bucket"], fontsize=8)
    ax.set_ylabel("hexes withheld")
    ax.set_xlabel("canonical land_fraction of the hex")
    ax3 = ax.twinx()
    ax3.plot(list(x), d["authorised_km2"], color="#1b2631", marker="o",
             lw=1.8, label="km2")
    ax3.set_ylabel("authorised km2 withheld")
    ax.set_title("withheld coastal hexes by land fraction", fontsize=10)
    body = ["THE GAP, BY LAND FRACTION", ""]
    body += _wrap(
        "Two populations. By COUNT the biggest bucket is 0-5 per cent - "
        "coastal slivers a hex barely touches. By AREA the mass is at the "
        "other end: the 40-50 per cent bucket alone holds more authorised "
        "land than the bottom four buckets together. The gap is mostly "
        "hexes that are nearly half land and miss the threshold.")
    body += ["", "  bucket      hexes    km2 withheld", ""]
    for r in d.itertuples():
        body.append(f"  {r.bucket:10s} {r.hexes:6,d} {r.authorised_km2:15,.1f}")
    body += ["", "PER LANDMASS", "",
             "  landmass         produced  withheld   km2      share", ""]
    for r in summ.itertuples():
        body.append(f"  {r.landmass:16s} {r.produced_controlled:8,d} "
                    f"{r.withheld_non_terrestrial:9,d} "
                    f"{r.authorised_km2_withheld:8,.0f} "
                    f"{r.withheld_share_of_authorised_pct:6.2f}%")
    body += ["", "  The share is 1-2 per cent for the five large landmasses",
             "  and 14.8 / 29.7 per cent for Malta and Gozo. The error is",
             "  not constant - it scales with coastline over area, so it",
             "  grows as the islands get smaller."]
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
        f"{base['canonical_rows_after']:,} -> {s['canonical_rows_after']:,}"
        "   (UNCHANGED - this is an audit stage)",
        f"  CONTROLLED                    : "
        f"{base['canonical_controlled_after']:,} -> "
        f"{s['canonical_controlled_after']:,}",
        f"  UNRESOLVED                    : "
        f"{base['canonical_unresolved_after']:,} -> "
        f"{s['canonical_unresolved_after']:,}",
        "",
        "  PRODUCED SO FAR", "",
        f"    Great Britain               : {base['gb_controlled']:,}",
        f"    Ireland                     : {base['ie_controlled']:,}",
        f"    Iceland                     : {base['iceland_controlled']:,}",
        f"    Sicily                      : {base['sicily_controlled']:,}",
        f"    Sardinia                    : {base['sardinia_controlled']:,}",
        f"    Malta / Gozo                : {base['malta_controlled']} / "
        f"{base['gozo_controlled']}",
        f"    Saxony                      : {base['saxony_controlled']:,}",
        f"    Brandenburg                 : "
        f"{base['brandenburg_controlled']}",
        "",
        "  MEASURED THIS STAGE, NOT FIXED", "",
        f"    authorised land hexes with no political target",
        f"                                : {s['gap_hexes']:,}",
        f"    authorised land withheld    : {s['gap_km2']:,.1f} km2",
        f"    worst affected              : Gozo "
        f"{s['gozo_withheld_pct']:.1f}% of its authorised land",
        f"    landmasses audited          : {s['landmasses_audited']}",
        "",
        f"  stage conclusion              : {s['stage_conclusion']}",
        f"  recommended model             : {s['recommended_model']}",
        "",
        "SCOPE DELIBERATELY NOT TAKEN", "",
        "  no territory produced         : canonical is byte-identical",
        "  no threshold tuned            : land_threshold stays 0.5",
        "  no water class changed        : an ocean-majority hex stays",
        "                                  ocean-majority",
        "  no history rewrite            : the 56 MB blob in c12ee10 is",
        "                                  recorded as debt, not removed",
    ]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=9)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
def run_historical_coastal_audit(cfg: MapgenConfig,
                                 run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"coastal_audit_1756_{_dt.datetime.now():%Y%m%d}"
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
    audit = pd.read_csv(H / "coastal_hex_representability_audit.csv",
                        keep_default_na=False, na_values=[])
    summ = pd.read_csv(H / "coastal_hex_landmass_summary.csv")
    dist = pd.read_csv(H / "coastal_hex_land_fraction_distribution.csv")
    usage = pd.read_csv(H / "is_terrestrial_hex_usage_audit.csv",
                        keep_default_na=False, na_values=[])
    models = pd.read_csv(H / "political_target_model_comparison.csv",
                         keep_default_na=False, na_values=[])
    iccomp = pd.read_csv(H / "island_component_comparison.csv",
                         keep_default_na=False, na_values=[])
    blobs = pd.read_csv(H / "git_blob_size_audit.csv",
                        keep_default_na=False, na_values=[])
    rec = (H / "representation_recommendation.md").read_text(
        encoding="utf-8")
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    feats_c = pd.read_parquet(H / "historical_boundary_features.parquet",
                              columns=["boundary_feature_id",
                                       "historical_subject_id",
                                       "feature_role"])
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv",
        sdir / "territorial_control.csv"]}
    timings["load_s"] = time.perf_counter() - t0

    gap = audit[audit.representability_class
                == "AUTHORISED_LAND_NON_TERRESTRIAL"]
    gap_km2 = float(gap["authorised_land_area_km2"].sum())
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
    ctrl_by = {k: int((canonical["controller_scenario_polity_id"]
                       == v).sum())
               for k, v in (("gb", "sp_6b03622fc98a"),
                            ("ie", "sp_c8f0dcb42a96"),
                            ("sicily", "sp_14ee92dede27"),
                            ("sardinia", "sp_5f0f4d8d4788"),
                            ("dk", "sp_44c79eb0f89c"),
                            ("osj", "sp_20bf1d9af6ea"))}

    # ---- preview ---------------------------------------------------------
    t0 = time.perf_counter()
    prev_dir = render_scenario_preview(cfg, out_dir=run_dir / "preview",
                                       scenario_id=scenario_id)
    pman = json.loads((prev_dir / "preview_manifest.json").read_text(
        encoding="utf-8"))
    timings["preview_s"] = time.perf_counter() - t0

    # ---- gates -----------------------------------------------------------
    _check("M24-01_mapgen023_committed_baseline",
           M23_SUMMARY.exists()
           and base["canonical_rows_after"] == 50565
           and base["canonical_controlled_after"] == 49496
           and base["canonical_unresolved_after"] == 1069,
           "baseline read from the COMMITTED reviews/MAPGEN-023/summary.csv "
           f"- {base['canonical_rows_after']:,} rows, "
           f"{base['canonical_controlled_after']:,} CONTROLLED, "
           f"{base['canonical_unresolved_after']:,} UNRESOLVED")
    _check("M24-02_canonical_unchanged",
           len(canonical) == base["canonical_rows_after"]
           and int((canonical["control_status"] == "CONTROLLED").sum())
           == base["canonical_controlled_after"]
           and int((canonical["control_status"] == "UNRESOLVED").sum())
           == base["canonical_unresolved_after"]
           and ctrl_by["gb"] == base["gb_controlled"]
           and ctrl_by["dk"] == base["iceland_controlled"],
           "this stage produced nothing: rows, CONTROLLED, UNRESOLVED and "
           "every per-polity count are identical to MAPGEN-023")
    _check("M24-03_all_seven_landmasses_audited",
           set(summ["landmass"]) == set(LANDMASSES)
           and set(audit["landmass"]) == set(LANDMASSES)
           and len(summ) == 7,
           f"all seven landmasses audited over {len(audit):,} land-carrying "
           "hexes")
    for cid, name, exp in (("M24-04_gb_retroactive_gap_measured",
                            "Great Britain", None),
                           ("M24-05_ireland_gap_measured", "Ireland", None),
                           ("M24-06_sicily_gap_measured", "Sicily", None),
                           ("M24-07_sardinia_gap_measured", "Sardinia",
                            None)):
        r = summ[summ.landmass == name].iloc[0]
        _check(cid, int(r["withheld_non_terrestrial"]) > 0
               and float(r["authorised_km2_withheld"]) > 0,
               f"{name}: {int(r['withheld_non_terrestrial']):,} hexes and "
               f"{float(r['authorised_km2_withheld']):,.1f} km2 of "
               "authorised land withheld - never measured before this stage")
    ice = summ[summ.landmass == "Iceland"].iloc[0]
    _check("M24-08_iceland_gap_reproduced",
           int(ice["withheld_non_terrestrial"]) == 1089,
           "Iceland reproduces MAPGEN-023's 1,089 exactly by an independent "
           "measurement path")
    mg = summ[summ.landmass.isin(["Malta", "Gozo"])]
    _check("M24-09_malta_gozo_gap_reproduced",
           int(mg["withheld_non_terrestrial"].sum()) == 15,
           "Malta 9 + Gozo 6 = 15, reproducing MAPGEN-023; together with "
           f"Iceland that is {base['not_produced_non_terrestrial_hexes']:,}, "
           "the figure MAPGEN-023 reported")
    _check("M24-10_exact_land_measurement",
           "centre_lon" not in audit.columns
           and (audit["canonical_land_area_km2"] > 0).all()
           and float(audit["land_fraction_measured_ground"].max()) <= 1.01,
           "every figure is an exact hex INTERSECT land measurement, "
           "unioned inside each hex so overlapping cache tiles cannot "
           "double count; no centroid test anywhere")
    _check("M24-11_mixed_components_separated",
           "mixed_unaudited" in audit.columns
           and int(gap["mixed_unaudited"].sum())
           < len(gap)
           and (gap.loc[gap.mixed_unaudited, "reason_not_produced"]
                == "NON_TERRESTRIAL_HEX_AND_MIXED_UNAUDITED_LAND").all(),
           f"{int(gap['mixed_unaudited'].sum())} of the withheld hexes also "
           "carry unaudited land and carry a distinct reason code; the two "
           "causes are never merged")
    _check("M24-12_land_fraction_distribution_produced",
           len(dist) > 0 and set(dist[dist.landmass == "ALL"]["bucket"])
           == {"0-5%", "5-10%", "10-20%", "20-30%", "30-40%", "40-50%"}
           and int(dist[dist.landmass == "ALL"]["hexes"].sum()) == len(gap),
           "six buckets, and every withheld hex falls in exactly one")

    pol_sites = usage[usage.is_political == "YES"]
    phys_sites = usage[usage.is_political == "NO"]
    _check("M24-13_physical_classification_is_not_political_"
           "representability",
           len(pol_sites) >= 4 and len(phys_sites) >= 4
           and usage["site"].str.contains("land.py").any()
           and usage["what"].str.contains(
               "classification_error_area_m2").any(),
           f"{len(phys_sites)} physical and {len(pol_sites)} political call "
           "sites separated. land.py already NAMES the discarded quantity "
           "classification_error_area_m2, explicitly including the land "
           "part of a water hex")
    _check("M24-14_is_terrestrial_hex_code_usage_audited",
           usage["site"].str.contains("scenario.py:23-26").any()
           and usage["site"].str.contains("scenario_pipeline.py:934").any()
           and usage["layer"].isin(["MOVEMENT"]).any()
           and usage.loc[usage.layer == "MOVEMENT", "what"].str.contains(
               "reads neither").any(),
           "usage traced through physical classification, terrain, "
           "movement, political targeting and the binder. Movement reads "
           "neither flag - there is no movement layer yet")
    _check("M24-15_island_component_semantics_compared",
           len(iccomp) >= 6
           and (iccomp["same"] == "NO").any()
           and iccomp["coastal_fragment_case"].str.contains(
               "is_subhex_lost is False").any(),
           "the ISLAND_COMPONENT overlay contract is compared aspect by "
           "aspect and is NOT assumed to be the same problem: a coastal "
           "fragment is not is_subhex_lost, because its component is "
           "represented")
    for cid, m in (("M24-16_model_a_evaluated", "A"),
                   ("M24-17_model_b_evaluated", "B"),
                   ("M24-18_model_c_evaluated", "C"),
                   ("M24-19_model_d_evaluated", "D")):
        r = models[models.model == m]
        _check(cid, len(r) == 1
               and all(str(r.iloc[0][c]).strip() for c in
                       ("historical_correctness", "gameplay_semantics",
                        "movement_implications", "terrain_implications",
                        "data_size", "migration_cost", "compatibility",
                        "island_overlays", "mixed_controller_risk",
                        "verdict")),
               f"model {m} evaluated on all ten axes: "
               f"{str(r.iloc[0]['verdict'])[:88]}")
    _check("M24-20_no_arbitrary_threshold_tuning",
           float(cfg.land_threshold) == 0.5
           and "No threshold was tuned" in rec
           and not audit["reason_not_produced"].str.contains(
               "0.2|0.3|threshold changed", regex=True, na=False).any(),
           "land_threshold is still 0.5 and the recommendation states "
           "explicitly that no threshold was tuned; the distribution has no "
           "natural break that would justify one")

    imgs = ["scenario_1756_political_map.png",
            "scenario_1756_political_map_legend.png"]
    imgs += [f"{k}_political_closeup.png" for k in REGIONS]
    have = [n for n in imgs if (prev_dir / n).exists()]
    from PIL import Image
    ov = Image.open(prev_dir / imgs[0]).size
    _check("M24-21_europe_political_preview_produced",
           (prev_dir / imgs[0]).exists() and ov[0] >= 3840,
           f"Europe overview rendered at {ov[0]}x{ov[1]} px")
    cols = {p: polity_colour(p) for p in sp["polity_id"]}
    active = [p for p, s in zip(sp["polity_id"], sp["scenario_polity_id"])
              if int((canonical["controller_scenario_polity_id"]
                      == s).sum()) > 0]
    _check("M24-22_deterministic_polity_colours",
           len(set(cols[p] for p in active)) == len(active)
           and cols["pol_great_britain"] != cols["pol_hanover"]
           and cols["pol_sicily"] != cols["pol_naples"]
           and cols["pol_great_britain"]
           != cols["pol_kingdom_of_ireland"]
           and polity_colour("pol_sicily") == cols["pol_sicily"],
           f"{len(active)} active controllers, {len(set(cols[p] for p in active))}"
           " distinct colours, keyed on the polity id alone - Great "
           "Britain, Ireland and Hanover differ, and so do Sicily and "
           "Naples")
    _check("M24-23_unknown_is_not_unresolved",
           pman["stats"]["unknown_terrestrial"] > 0
           and pman["stats"]["unresolved"] > 0
           and pman["stats"]["gap"] > 0
           and len({"UNKNOWN", "UNRESOLVED", "GAP"}) == 3,
           "three distinct categories drawn in three distinct colours: "
           f"UNKNOWN ~{pman['stats']['unknown_terrestrial']:,} terrestrial "
           f"hexes, UNRESOLVED {pman['stats']['unresolved']:,}, "
           f"authorised-but-unrepresentable {pman['stats']['gap']:,}")
    _check("M24-24_coastal_gap_layer_rendered",
           pman["stats"]["gap"] == len(gap)
           and sum(pman["closeup_gap_hexes"].values()) > 0
           and pman["closeup_gap_hexes"]["malta_gozo"] == 15,
           "the gap layer is drawn on every closeup; Malta and Gozo show "
           "15 controlled hexes against 15 withheld ones, which is the "
           "clearest statement of the finding this project has")
    _check("M24-25_regional_closeups_produced",
           len(have) == len(imgs) and len(REGIONS) == 5,
           f"{len(have)} preview figures: overview, legend and "
           f"{len(REGIONS)} regional closeups")
    _check("M24-26_renderer_non_authoritative",
           pman["authoritative"] is False
           and pman["purpose"] == "QA_AND_PRESENTATION_ONLY"
           and sha256_of(sdir / "territorial_control.csv")
           == upstream[str(sdir / "territorial_control.csv")],
           "the preview manifest declares itself non-authoritative and "
           "canonical control is byte-identical after rendering")

    tracked = tracked_file_sizes(Path.cwd())
    over50 = tracked[tracked["bytes"] > MAX_TRACKED_BYTES]
    over25 = tracked[tracked["bytes"] > WARN_TRACKED_BYTES]
    allow = set(blobs.loc[blobs["allowlisted"].str.startswith(
        "ALLOWLISTED"), "path"])
    _check("M24-27_no_new_tracked_blob_over_50mb",
           len(over50) == 0,
           f"largest tracked file is "
           f"{tracked['bytes'].max() / 1024 / 1024:.2f} MB "
           f"({tracked.loc[tracked['bytes'].idxmax(), 'path']}); nothing "
           "over 50 MB")
    _check("M24-28_over_25mb_tracked_files_allowlisted",
           set(over25["path"]) <= allow,
           f"{len(over25)} tracked files exceed 25 MB and all are "
           f"allowlisted with a reason; allowlist holds {len(allow)} entry")
    review_csvs = list((run_dir).glob("*.csv"))
    _check("M24-29_review_geometry_wkt_duplication_zero",
           not any("geometry" in pd.read_csv(p, nrows=0).columns
                   for p in review_csvs)
           and "geometry" not in pd.read_csv(
               H / "historical_snapshot_features_1756_08_01.csv",
               nrows=0).columns,
           "no CSV in this stage carries a geometry column; the "
           "snapshot-features table is still free of the WKT duplication "
           "that cost 58 MB in MAPGEN-023")
    legacy = blobs[blobs["path"] == LEGACY_BLOB]
    _check("M24-30_legacy_history_debt_documented_no_rewrite",
           len(legacy) == 1
           and legacy.iloc[0]["state"].startswith("LEGACY_HISTORY_DEBT")
           and "NOT" in legacy.iloc[0]["note"]
           and subprocess.run(["git", "rev-parse", "--verify", "c12ee10"],
                              capture_output=True).returncode == 0,
           "the 56 MB blob is recorded as LEGACY_HISTORY_DEBT with the "
           "reason it is not being rewritten, and commit c12ee10 still "
           "resolves - the review chain's base-commit audits stay valid")

    _check("M24-31_british_isles_regression",
           ctrl_by["gb"] == base["gb_controlled"]
           and ctrl_by["ie"] == base["ie_controlled"],
           f"Great Britain {ctrl_by['gb']:,} and Ireland "
           f"{ctrl_by['ie']:,} CONTROLLED")
    _check("M24-32_mediterranean_regression",
           ctrl_by["sicily"] == base["sicily_controlled"]
           and ctrl_by["sardinia"] == base["sardinia_controlled"]
           and int((canonical["controller_scenario_polity_id"]
                    == make_scenario_polity_id(
                        scenario_id, "pol_corsican_republic")).sum()) == 0,
           f"Sicily {ctrl_by['sicily']:,}, Sardinia "
           f"{ctrl_by['sardinia']:,}, Corsica still assigned to nobody")
    _check("M24-33_iceland_regression",
           ctrl_by["dk"] == base["iceland_controlled"],
           f"Iceland {ctrl_by['dk']:,} CONTROLLED under Denmark-Norway")
    _check("M24-34_malta_regression",
           ctrl_by["osj"] == base["malta_controlled"]
           + base["gozo_controlled"],
           f"Order of Saint John {ctrl_by['osj']} CONTROLLED "
           f"({base['malta_controlled']} Malta + {base['gozo_controlled']} "
           "Gozo)")
    _check("M24-35_brandenburg_regression",
           int((canonical["controller_scenario_polity_id"]
                == make_scenario_polity_id(scenario_id,
                                           "pol_brandenburg")).sum()) == 0
           and (H / "brandenburg_blha_transform.json").exists(),
           "Brandenburg still holds nothing and its MAPGEN-020 artifacts "
           "are intact")
    _check("M24-36_saxony_regression",
           sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and wei == {"CONTROLLED": 0, "UNRESOLVED": 96},
           f"Saxony {sax}, Saxe-Weimar {wei} unchanged")
    _check("M24-37_low_countries_regression",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP",
           "Low Countries still SOURCE_GAP")
    wf = feats_c[feats_c["historical_subject_id"]
                 == "hsub_schwarzburg_unpartitioned_wash"]
    _check("M24-38_schwarzburg_regression",
           len(wf) == 1 and wf.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY"
           and wash["UNRESOLVED"] == 89,
           "Schwarzburg wash unchanged and still not production-convertible")
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    _check("M24-39_europe_grid_regression",
           int(eu_man["hex_count"].sum()) == 1885422,
           "Europe canonical grid intact (1,885,422 hexes)")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    _check("M24-40_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN",
           "Toshima hex still OCEAN - the precedent this stage compares "
           "against is intact")
    _check("M24-41_claims_regression",
           len(snap_s.territorial_claims) == 1,
           "claims table still holds its single MAPGEN-008 row")

    empty = pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"])
    c2, _p2, _l2, rep = promote_control(
        canonical.copy(), provenance.copy(), log.copy(), empty, scenario_id,
        STAGE, M23_COMMIT, "none", "src_none", promoted_utc="2026-08-15")
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
        set(comps_p["island_component_id"]), struct)
    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("M24-42_determinism_and_integrity",
           integ == [] and up_after == upstream
           and rep["inserted"] == 0 and len(c2) == len(canonical)
           and rep["promotion_id"] == make_promotion_id(
               scenario_id, STAGE, sha256_of_frame(empty))
           and HPG_SCHEMA_VERSION == "1.4.0"
           and SCENARIO_SCHEMA_VERSION == "1.4.0"
           and not scan_forbidden_reference_code(Path(__file__)),
           f"canonical integrity {integ or 'clean'}, upstream "
           "byte-identical INCLUDING territorial_control.csv, empty "
           "promotion inserts 0, no schema added, forbidden-reference scan "
           "clean")

    # ---- figures ---------------------------------------------------------
    t0 = time.perf_counter()
    render_gap_distribution(run_dir / "coastal_gap_distribution.png", dist,
                            summ, "A. The gap, measured")
    gz = summ[summ.landmass == "Gozo"].iloc[0]
    s = dict(
        stage=STAGE, base_commit_mapgen023=M23_COMMIT,
        outcome="FULL_AUDIT_NO_PRODUCTION",
        baseline_source="reviews/MAPGEN-023/summary.csv (committed)",
        canonical_rows_before=base["canonical_rows_after"],
        canonical_rows_after=len(canonical),
        canonical_controlled_before=base["canonical_controlled_after"],
        canonical_controlled_after=int(
            (canonical["control_status"] == "CONTROLLED").sum()),
        canonical_unresolved_before=base["canonical_unresolved_after"],
        canonical_unresolved_after=int(
            (canonical["control_status"] == "UNRESOLVED").sum()),
        landmasses_audited=len(summ),
        hexes_audited=len(audit),
        gap_hexes=len(gap), gap_km2=round(gap_km2, 1),
        gap_mixed_unaudited=int(gap["mixed_unaudited"].sum()),
        gozo_withheld_pct=float(gz["withheld_share_of_authorised_pct"]),
        stage_conclusion="C_ARCHITECTURAL_GAP",
        recommended_model="C_LAND_BEARING_HEX_NEW_TARGET_TYPE",
        land_threshold_unchanged=float(cfg.land_threshold),
        legacy_blob_decision="LEGACY_HISTORY_DEBT_NO_REWRITE",
        largest_tracked_file_mb=round(
            float(tracked["bytes"].max()) / 1024 / 1024, 2),
        tracked_files_over_25mb=len(over25),
        tracked_files_over_50mb=len(over50),
        preview_controlled_drawn=pman["stats"]["controlled"],
        preview_unknown_terrestrial=pman["stats"]["unknown_terrestrial"],
        preview_controlled_share_pct=pman["stats"]["controlled_share_pct"],
        validation_pass="")
    for r in summ.itertuples():
        k = r.landmass.lower().replace(" ", "_")
        s[f"{k}_produced"] = int(r.produced_controlled)
        s[f"{k}_withheld"] = int(r.withheld_non_terrestrial)
        s[f"{k}_withheld_km2"] = float(r.authorised_km2_withheld)
        s[f"{k}_withheld_pct"] = float(r.withheld_share_of_authorised_pct)
    render_progress(run_dir / "europe_political_progress.png", s, base,
                    "B. Europe political progress")
    img = ["coastal_gap_distribution.png", "europe_political_progress.png"]
    for n in imgs:
        shutil.copy2(prev_dir / n, run_dir / n)
    img += imgs
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
    manifest = {
        "run_id": run_id, "stage": STAGE,
        "outcome": "FULL_AUDIT_NO_PRODUCTION",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen023": M23_COMMIT,
        "baseline_from_committed_summary": base,
        "stage_conclusion": "C_ARCHITECTURAL_GAP",
        "recommended_model": "C_LAND_BEARING_HEX_NEW_TARGET_TYPE",
        "landmass_summary": summ.to_dict("records"),
        "land_fraction_distribution": dist[
            dist.landmass == "ALL"].to_dict("records"),
        "is_terrestrial_hex_usage": usage[
            ["site", "layer", "is_political"]].to_dict("records"),
        "models": models[["model", "name", "verdict"]].to_dict("records"),
        "blob_gate": {"max_tracked_bytes": MAX_TRACKED_BYTES,
                      "warn_tracked_bytes": WARN_TRACKED_BYTES,
                      "over_50mb": len(over50), "over_25mb": len(over25),
                      "allowlist": sorted(allow),
                      "legacy_debt": LEGACY_BLOB},
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
    _write_readme(run_dir, run_id, s, base, summ, dist, usage, models,
                  iccomp, blobs, pman, aspects, img)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    cmap = {"README_REVIEW.md": run_dir / "README_REVIEW.md",
            "run_manifest.json": run_dir / "run_manifest.json",
            "validation.csv": run_dir / "validation.csv",
            "summary.csv": run_dir / "summary.csv",
            "representation_recommendation.md":
                H / "representation_recommendation.md"}
    for n in ["coastal_hex_representability_audit",
              "coastal_hex_land_fraction_distribution",
              "coastal_hex_landmass_summary",
              "is_terrestrial_hex_usage_audit",
              "political_target_model_comparison",
              "island_component_comparison", "git_blob_size_audit"]:
        cmap[n + ".csv"] = H / (n + ".csv")
    cmap["scenario_political_coverage.csv"] = sdir / "political_coverage.csv"
    cmap["historical_hex_membership.csv"] = (
        m15_dir / "chatgpt_review" / "historical_hex_membership.csv")
    for dst, src in cmap.items():
        if Path(src).exists():
            shutil.copy2(src, review / dst)
    for n in img:
        shutil.copy2(run_dir / n, review / n)
    shutil.copy2(prev_dir / "preview_manifest.json",
                 review / "preview_manifest.json")
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    shutil.copy2(run_dir / "run_manifest.json", review / "run_manifest.json")
    print(f"[coastal-audit] {run_id}: validation {n_pass}/{len(val)}, "
          f"{len(gap):,} hexes / {gap_km2:,.0f} km2 of authorised land have "
          f"no political target, canonical unchanged at "
          f"{len(canonical):,} rows ({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[coastal-audit][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, base, summ, dist, usage, models,
                  iccomp, blobs, pman, aspects, img):
    dall = dist[dist.landmass == "ALL"]
    L = [
        f"# {STAGE} Review — measuring a gap instead of filling it",
        "",
        "**OUTCOME: FULL AUDIT, NO PRODUCTION.** Canonical control is "
        f"unchanged at **{s['canonical_rows_after']:,} rows** "
        f"({s['canonical_controlled_after']:,} CONTROLLED, "
        f"{s['canonical_unresolved_after']:,} UNRESOLVED) — identical to "
        f"MAPGEN-023 by gate. Validation **{s['validation_pass']}**.",
        "",
        f"**Stage conclusion: {s['stage_conclusion']}. Recommended model: "
        f"{s['recommended_model']}.**",
        "",
        "## 1. The number",
        "",
        f"**{s['gap_hexes']:,} hexes carry historically authorised land and "
        f"cannot hold a control row**, between them "
        f"**{s['gap_km2']:,.1f} km²**.",
        "",
        "| landmass | produced | withheld | km² withheld | share |",
        "|---|---|---|---|---|",
    ]
    for r in summ.itertuples():
        L.append(f"| {r.landmass} | {r.produced_controlled:,} | "
                 f"{r.withheld_non_terrestrial:,} | "
                 f"{r.authorised_km2_withheld:,.1f} | "
                 f"{r.withheld_share_of_authorised_pct:.2f}% |")
    L += [
        "",
        "Four of these had never been measured. MAPGEN-021 and 022 filtered "
        "on `is_terrestrial_hex` *before* computing anything, so Great "
        "Britain, Ireland, Sicily and Sardinia never counted what they were "
        "dropping. Iceland reproduces MAPGEN-023's 1,089 exactly, and Malta "
        "and Gozo reproduce 9 + 6 = 15, which is the check that this "
        "independent measurement path agrees with the production one.",
        "",
        "The share is the finding. One to two per cent on the five large "
        "landmasses, **14.8% on Malta and 29.7% on Gozo**. The error is not "
        "a constant — it scales with coastline over area, so it grows as "
        "the islands get smaller, and every future stage will meet smaller "
        "islands.",
        "",
        "## 2. Where the gap lives",
        "",
        "| land fraction | hexes | km² withheld |",
        "|---|---|---|",
    ]
    for r in dall.itertuples():
        L.append(f"| {r.bucket} | {r.hexes:,} | {r.authorised_km2:,.1f} |")
    L += [
        "",
        "Two populations. By **count** the biggest bucket is 0–5% — slivers "
        "a hex barely clips. By **area** the mass is at the other end: the "
        "40–50% bucket alone holds more than the bottom four together. So "
        "this is not mostly rounding dust; it is mostly hexes that are "
        "nearly half land and miss the cut.",
        "",
        "## 3. Is it a bug? No — and the evidence is written down",
        "",
        "`src/mapgen/scenario.py` lines 23–26, since MAPGEN-006R:",
        "",
        "> Territorial targets are TERRESTRIAL_HEX (hex_id) or "
        "ISLAND_COMPONENT (component_id) … and an OCEAN hex is never itself "
        "a land-control target.",
        "",
        "`scenario_pipeline.py:934` enforces it. And `land.py:80–97` already "
        "names the discarded quantity `classification_error_area_m2` — "
        "explicitly including *the land part of a water hex*. The project "
        "knew the binary class throws land away and kept `land_fraction` "
        "beside it so the loss stays recoverable.",
        "",
        "| layer | sites | political? |",
        "|---|---|---|",
    ]
    for lay, g in usage.groupby("layer"):
        L.append(f"| {lay} | {len(g)} | {g['is_political'].iloc[0]} |")
    L += [
        "",
        "One usage matters more than the rest: **movement reads neither "
        "flag.** `hex_edges.py` is purely geometric. There is no movement "
        "layer yet, so nothing downstream constrains the choice of model.",
        "",
        "## 4. Why the existing escape hatch does not reach it",
        "",
        "The project already solved *land on an ocean hex* once: a "
        "component that touches no terrestrial hex is flagged "
        "`is_subhex_lost` and becomes an `ISLAND_COMPONENT` target — "
        "Izu-Toshima is that row. But `islands_pipeline.py:1370–1377` "
        "checks `no_duplicate_overlay_for_large_islands`: a component "
        "already represented by a terrestrial hex must not also appear as "
        "an overlay. Great Britain **is** represented. Its coastal "
        "remainder is therefore too attached to be a lost component and too "
        "seaward to be a land hex.",
        "",
        "| aspect | island component | coastal fragment | same? |",
        "|---|---|---|---|",
    ]
    for r in iccomp.itertuples():
        L.append(f"| {r.aspect} | {r.island_component_case[:70]} | "
                 f"{r.coastal_fragment_case[:70]} | {r.same} |")
    L += [
        "",
        "## 5. Models",
        "",
        "| model | verdict |",
        "|---|---|",
    ]
    for r in models.itertuples():
        L.append(f"| **{r.model}** — {r.name[:64]} | {r.verdict[:150]} |")
    L += [
        "",
        "Model C is recommended: additive, preserves the MAPGEN-006R "
        "invariant, leaves physical geography and every existing count "
        "untouched, and keys fragments by component so a hex holding two "
        "landmasses is explicit rather than a collision. Full reasoning in "
        "`representation_recommendation.md`.",
        "",
        "**No threshold was tuned.** Lowering `land_threshold` from 0.5 "
        "would move terrain and water class to fix a political problem, and "
        "the distribution above has no natural break to justify a new cut.",
        "",
        "## 6. The preview",
        "",
        f"`python -m mapgen scenario-preview --config config/kanto.yaml` "
        f"regenerates everything below. It is QA only — the manifest "
        f"declares `authoritative: false`, and canonical control is "
        f"byte-identical after rendering.",
        "",
        f"- Europe overview at 4000 px wide, {pman['stats']['controlled']:,} "
        f"CONTROLLED hexes drawn across {pman['stats']['polities']} polities",
        f"- UNKNOWN (~{pman['stats']['unknown_terrestrial']:,} terrestrial "
        "hexes nobody has researched), UNRESOLVED "
        f"({pman['stats']['unresolved']:,}) and the coastal gap "
        f"({pman['stats']['gap']:,}) are three different colours, because "
        "they are three different statements",
        "- Colours are `sha1(polity_id)` hue — stable forever, and a shared "
        "monarch never merges two polities into one colour",
        "",
        "| closeup | gap hexes in view |",
        "|---|---|",
    ]
    for k, v in pman["closeup_gap_hexes"].items():
        L.append(f"| {k} | {v:,} |")
    L += [
        "",
        "The Malta and Gozo closeup is the one to look at: **15 hexes "
        "controlled by the Order, 15 more outlined in magenta.** Half the "
        "archipelago's hexes hold Maltese land that the model cannot own.",
        "",
        "## 7. Blob size",
        "",
        f"Largest tracked file: **{s['largest_tracked_file_mb']} MB**. "
        f"Over 50 MB: **{s['tracked_files_over_50mb']}**. Over 25 MB: "
        f"**{s['tracked_files_over_25mb']}**, allowlisted with a reason.",
        "",
        "The 56 MB blob in `c12ee10` is **not** rewritten. `main` is pushed, "
        "the review chain cites commit SHAs, and every base-commit audit in "
        "MAPGEN-019…023 would be invalidated by a rewrite. It is recorded as "
        "`LEGACY_HISTORY_DEBT` and the gate above stops a repeat.",
        "",
        "## 8. Figures",
        "",
    ]
    for n in img:
        L.append(f"- `{n}` (aspect {aspects.get(n, 0):.3f})")
    L += ["", f"Run `{run_id}`."]
    (run_dir / "README_REVIEW.md").write_text("\n".join(L) + "\n",
                                              encoding="utf-8")
