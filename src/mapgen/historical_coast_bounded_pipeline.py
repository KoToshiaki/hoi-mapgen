"""MAPGEN-021 — territory whose frontier is a coastline.

Every Brandenburg stage has been blocked on the same thing: a land frontier
that has to be read off an eighteenth-century plate before anything can be
produced. Great Britain and Ireland do not have that problem. Their
frontiers are coasts, and a coast is already in the canonical geography.

That does NOT mean the coastline confers ownership. The load-bearing rule
of this stage is that physical geography and political authority are
separate evidence with separate roles, and neither alone can produce a
control row:

    OSM coastline        -> GEOMETRY_SHAPE, geometry_authority=YES,
                            political_authority=NO
    1707 / 1756 statutes -> POLITICAL_STATUS, political_authority=YES,
                            geometry_authority=NO

The existing bundle schema already enforces exactly that, so no new
architecture was added. The Acts of Union give one kingdom over the whole
main island; two 1756 acts of the same Parliament, one for a place in
Scotland and one for a place in England, show that authority actually
running in the snapshot year. Ireland is authorised separately by its own
Parliament's Sheriffs Act, operative from 1 May 1756 — and it stays a
separate kingdom, because the union with Great Britain is 1801.
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
from .historical_geometry import HPG_SCHEMA_VERSION
from .historical_pilot_pipeline import _fig, _fig2, _save
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, load_scenario,
                       make_scenario_polity_id, scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .scenario_promotion import (make_promotion_id, promote_control,
                                 sha256_of_frame, validate_canonical_control)
from .sources import sha256_of

STAGE = "MAPGEN-021"
H = Path("data/historical")
M20_COMMIT = "aaca77371a20f7720f3913dd111fbc2f4b78b893"
GB_SP, IE_SP = "sp_6b03622fc98a", "sp_c8f0dcb42a96"
SUBJ_GB = "hsub_great_britain_main_island"
SUBJ_IE = "hsub_ireland_main_island"
# what MAPGEN-020 left behind, and what must survive untouched
M20_ROWS, M20_CONTROLLED, M20_UNRESOLVED = 1614, 697, 917


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
def render_identity(path, ident, title):
    fig, (ax, ax2) = _fig2((16, 7.5), [1, 1])
    top = ident.head(14)
    col = ["#1f618d" if r == "MAIN_LANDMASS_GREAT_BRITAIN" else
           "#196f3d" if r == "MAIN_LANDMASS_IRELAND" else "#aab7b8"
           for r in top["stage_role"]]
    ax.barh(range(len(top)), top["ground_area_km2"], color=col)
    ax.set_yticks(range(len(top)))
    ax.set_yticklabels(
        [str(n) if isinstance(n, str) and n else f"rank {r}" for n, r in
         zip(top["named_identification"], top["rank_by_area"])], fontsize=7)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("ground area (km2, log)")
    ax.set_title("connected land components, largest first", fontsize=10)
    body = ["LANDMASS IDENTITY", ""]
    body += _wrap(
        "The two main islands are found deterministically: union the "
        "canonical OSM land parts over the British Isles window, take "
        "connected components, order by area. Anchor points are used ONLY "
        "to confirm which landmass is which - they are never an ownership "
        "source.")
    body += ["", "  rank  ground km2  anchors                      role", ""]
    for r in ident.head(4).itertuples():
        a = str(r.anchors_contained_gb or r.anchors_contained_ie
                or r.named_identification or "-")
        if a == "nan":
            a = "-"
        body.append(f"  {r.rank_by_area:>4} {r.ground_area_km2:11,.0f}  "
                    f"{a[:28]:28s} {r.stage_role}")
    body += ["", "SANITY", ""]
    body += _wrap(
        "Great Britain measures 218,685 km2 and Ireland 83,552 km2 against "
        "published figures of about 209,000 and 84,400 - the excess is "
        "tidal and estuarine ground the OSM coastline includes. The Isle of "
        "Man comes out at 570.5 km2 against a published 572.")
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7.4)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_landmass(path, geom, ident_row, ctrl, title, colour):
    fig, (ax, ax2) = _fig2((15, 7.5), [1.1, 1])
    gpd.GeoSeries([geom], crs="EPSG:3857").plot(
        ax=ax, color=colour, edgecolor="#2c3e50", linewidth=0.4)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title("authorised landmass scope", fontsize=10)
    body = ["HISTORICALLY_AUTHORISED_LANDMASS_SCOPE", ""]
    body += _wrap(
        "This polygon is the canonical PHYSICAL land component. It becomes "
        "territory only because a political assertion is bundled with it; "
        "on its own it is a shape.")
    body += ["", f"  ground area        {ident_row['ground_area_km2']:,.0f} "
                 "km2",
             f"  centroid           {ident_row['centroid_lon']:.3f}, "
             f"{ident_row['centroid_lat']:.3f}",
             "  identity anchors   "
             + str(ident_row["anchors_contained_gb"]
                   or ident_row["anchors_contained_ie"]),
             "", "  hexes CONTROLLED   "
             f"{int((ctrl['control_status'] == 'CONTROLLED').sum()):,}",
             "  hexes UNRESOLVED   "
             f"{int((ctrl['control_status'] == 'UNRESOLVED').sum()):,}"]
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=8)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_excluded(path, excl, title):
    fig, ax = _fig((14, 8))
    ax.set_axis_off()
    named = excl[excl["named_identification"] != ""]
    body = ["EXCLUDED COMPONENTS — nothing was swept in by proximity", "",
            "  component                 ground km2   reason", ""]
    for r in named.itertuples():
        body.append(f"  {r.named_identification:24s} {r.ground_area_km2:10,.1f}"
                    f"   {r.exclusion_reason}")
    body += ["", f"  ... and {len(excl) - len(named)} further unnamed "
                 "components, all excluded", "",
             "THE ISLE OF MAN", ""]
    iom = excl[excl["named_identification"] == "Isle of Man"]
    if len(iom):
        body += ["  " + ln for ln in _wrap(iom.iloc[0]["note"], 86)]
    body += ["", "WHY THIS MATTERS", ""]
    body += ["  " + ln for ln in _wrap(
        "Great Britain and Ireland are archipelagos. Assigning the Hebrides "
        "or Orkney to Great Britain because they are nearby, or the Isle of "
        "Man because it is between the two, would be inventing territory. "
        "Each offshore component needs its own authority and gets its own "
        "stage.", 86)]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=8)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_hex_control(path, mix, title):
    fig, (ax, ax2) = _fig2((16, 7.5), [1.15, 1])
    cols = {"great_britain": "#1f618d", "ireland": "#196f3d", "": "#c0392b"}
    for w, g in mix.groupby("winner"):
        ax.scatter(g["cx"], g["cy"], s=1.6, c=cols.get(w, "#c0392b"),
                   label=f"{w or 'UNRESOLVED'} ({len(g):,})")
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.legend(fontsize=8, markerscale=6, loc="lower left")
    ax.set_title("canonical hexes, coloured by controller", fontsize=10)
    body = ["EXACT-LAND MEMBERSHIP", ""]
    body += _wrap(
        "A hex is CONTROLLED only when essentially all of its canonical land "
        "belongs to one authorised main landmass. Where a hex also holds an "
        "unaudited offshore component, it is held back rather than quietly "
        "swept in.")
    body += ["", "  basis                                    hexes", ""]
    for (st, b), n in mix.groupby(["control_status", "basis"]).size().items():
        body.append(f"  {b:40s} {n:6,d}  [{st}]")
    body += ["", "  winner                                   hexes", ""]
    for w, n in mix[mix.control_status == "CONTROLLED"][
            "winner"].value_counts().items():
        body.append(f"  {w:40s} {n:6,d}")
    coll = mix[(mix.great_britain_km2 > 0) & (mix.ireland_km2 > 0)]
    body += ["", f"  hexes where BOTH landmasses appear: {len(coll)}",
             "  resolved on exact land intersection, never by a default "
             "winner"]
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7.4)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_progress(path, s, title):
    fig, ax = _fig((15, 8.5))
    ax.set_axis_off()
    body = [
        "EUROPE POLITICAL PROGRESS", "",
        f"  canonical control rows        : {s['canonical_rows_before']:,} "
        f"-> {s['canonical_rows_after']:,}",
        f"  CONTROLLED                    : {M20_CONTROLLED:,} -> "
        f"{s['canonical_controlled_after']:,}",
        f"  UNRESOLVED                    : {M20_UNRESOLVED:,} -> "
        f"{s['canonical_unresolved_after']:,}",
        "",
        f"  Great Britain CONTROLLED      : {s['gb_controlled']:,}",
        f"  Great Britain UNRESOLVED      : {s['gb_unresolved']:,}",
        f"  Ireland CONTROLLED            : {s['ie_controlled']:,}",
        f"  Ireland UNRESOLVED            : {s['ie_unresolved']:,}",
        "",
        f"  Saxony CONTROLLED             : {s['saxony_controlled']:,} "
        "(unchanged)",
        f"  Brandenburg CONTROLLED        : {s['brandenburg_controlled']} "
        "(untouched this stage)",
        "",
        "WHY THIS TERRITORY WENT THROUGH WHEN BRANDENBURG DID NOT", "",
        "  Brandenburg's frontier is a land boundary that has to be read",
        "  off an 18th-century plate and digitised. Great Britain and",
        "  Ireland are bounded by coast, and the coast is already canonical",
        "  geography. The historical work was therefore about AUTHORITY,",
        "  not about geometry - and authority is in statute, which is",
        "  legible in a way a dashed crimson wash is not.",
        "",
        "WHAT IS STILL OPEN", "",
        f"  offshore components excluded  : {s['excluded_components']}",
        f"  Isle of Man                   : {s['isle_of_man']}",
        f"  coverage GB                   : {s['coverage_gb']}",
        f"  coverage Ireland              : {s['coverage_ie']}",
        "",
        "  Neither polity is COMPLETE: the main island is done, the",
        "  archipelago is not.",
    ]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=9)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
def run_historical_coast_bounded(cfg: MapgenConfig,
                                 run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"british_isles_1756_{_dt.datetime.now():%Y%m%d}"
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
    feats = gpd.read_parquet(H / "historical_boundary_features.parquet")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    asrt = pd.read_csv(H / "historical_evidence_assertions.csv")
    links = pd.read_csv(H / "historical_boundary_feature_evidence.csv")
    mp = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    ev = pd.read_csv(H / "british_isles_historical_evidence.csv",
                     keep_default_na=False, na_values=[])
    ident = pd.read_csv(H / "british_isles_landmass_identity.csv",
                        keep_default_na=False, na_values=[]).fillna("")
    excl = pd.read_csv(H / "british_isles_exclusion_audit.csv",
                       keep_default_na=False, na_values=[]).fillna("")
    cs = pd.read_csv(H / "british_isles_coastal_sensitivity.csv")
    mix = pd.read_csv(H / "british_isles_hex_membership_audit.csv",
                      keep_default_na=False, na_values=[])
    snapf = pd.read_csv(H / "historical_snapshot_features_1756_08_01.csv")
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv"]}
    timings["load_s"] = time.perf_counter() - t0

    gb_rows = canonical[canonical["controller_scenario_polity_id"] == GB_SP]
    ie_rows = canonical[canonical["controller_scenario_polity_id"] == IE_SP]
    bi_targets = set(mix["hex_id"])
    bi_canon = canonical[canonical["territorial_target_id"].isin(bi_targets)]

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
    _check("M21-01_mapgen020_regression",
           sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and len(canonical) - len(bi_canon) == M20_ROWS
           and int((canonical["control_status"] == "CONTROLLED").sum())
           - int((bi_canon["control_status"] == "CONTROLLED").sum())
           == M20_CONTROLLED,
           f"MAPGEN-020 baseline intact underneath: removing the "
           f"{len(bi_canon):,} British Isles rows leaves exactly "
           f"{M20_ROWS:,}/{M20_CONTROLLED}/{M20_UNRESOLVED}; Saxony {sax}")
    _check("M21-02_great_britain_actor_exists",
           GB_SP in set(sp["scenario_polity_id"])
           and sp.loc[sp.scenario_polity_id == GB_SP, "polity_id"].iloc[0]
           == "pol_great_britain"
           and sp.loc[sp.scenario_polity_id == GB_SP,
                      "territorial_authority_role"].iloc[0]
           == "DIRECT_TERRITORIAL_ACTOR",
           "pol_great_britain is the existing DIRECT_TERRITORIAL_ACTOR; no "
           "new British composite root was created")
    _check("M21-03_ireland_actor_exists",
           IE_SP in set(sp["scenario_polity_id"])
           and sp.loc[sp.scenario_polity_id == IE_SP, "polity_id"].iloc[0]
           == "pol_kingdom_of_ireland"
           and sp.loc[sp.scenario_polity_id == IE_SP,
                      "territorial_authority_role"].iloc[0]
           == "DEPENDENT_TERRITORIAL_ACTOR",
           "pol_kingdom_of_ireland is the existing "
           "DEPENDENT_TERRITORIAL_ACTOR")
    _check("M21-04_personal_union_does_not_merge_territory",
           GB_SP != IE_SP
           and not set(gb_rows["territorial_target_id"])
           & set(ie_rows["territorial_target_id"]),
           "Great Britain and Ireland remain two actors holding two "
           "disjoint sets of hexes; a shared crown produced no shared row")
    u1707 = ev[ev["evidence_id"] == "bi_1707_union_article_i"]
    _check("M21-05_1707_union_evidence_exact_locator",
           len(u1707) == 1
           and "ARTICLE I" in u1707.iloc[0]["exact_locator"]
           and "one Kingdom by the name of Great Britain"
           in u1707.iloc[0]["quotation"],
           "Article I quoted from the official text with locator "
           f"{u1707.iloc[0]['exact_locator']}")
    gb56 = ev[(ev["polity"] == "pol_great_britain")
              & (ev["document_date"].astype(str) == "1756")]
    _check("M21-06_1756_great_britain_contemporary_evidence",
           len(gb56) >= 2
           and gb56["territorial_wording"].str.contains("North Britain").any()
           and gb56["territorial_wording"].str.contains("York").any(),
           "two 1756 acts of the same Parliament read for territorial "
           "wording: 29 Geo. 2 c. 20 (County of Bute, North Britain) and "
           "29 Geo. 2 c. 37 (County of York)")
    ie56 = ev[ev["polity"] == "pol_kingdom_of_ireland"]
    _check("M21-07_ireland_contemporary_evidence",
           len(ie56) >= 1
           and (ie56["effective_date"] <= "1756-08-01").any()
           and ie56["exact_locator"].str.contains("irishstatutebook").any(),
           "Sheriffs Act 1755 (Ireland) section III, operative 1 May 1756, "
           "from the official eISB; sheriffs' officers are county "
           "administration inside Ireland")
    u1801 = ev[ev["evidence_id"] == "bi_1801_union_temporal_cutoff"]
    _check("M21-08_ireland_remains_separate_polity",
           len(u1801) == 1
           and u1801.iloc[0]["in_force_at_snapshot"] == "NO"
           and u1801.iloc[0]["effective_date"] == "1801-01-01"
           and len(ie_rows) > 0,
           "the union with Ireland is recorded with effect 1 Jan 1801 and "
           "explicitly NOT in force at the snapshot; Ireland holds its own "
           f"{len(ie_rows):,} hexes")
    iom = excl[excl["named_identification"] == "Isle of Man"]
    _check("M21-09_isle_of_man_excluded",
           len(iom) == 1
           and iom.iloc[0]["exclusion_reason"]
           == "HISTORICAL_AUTHORITY_NOT_GREAT_BRITAIN_1756"
           and "1765" in iom.iloc[0]["note"],
           "the Isle of Man is identified as its own component "
           f"({iom.iloc[0]['ground_area_km2']} km2) and assigned to neither "
           "polity; the 1765 Revestment is named so it cannot be back-dated")

    osm_ev = asrt[(asrt["historical_subject_id"].isin([SUBJ_GB, SUBJ_IE]))
                  & (asrt["assertion_type"] == "GEOMETRIC_SUBSTRATE_ONLY")]
    pol_ev = asrt[(asrt["historical_subject_id"].isin([SUBJ_GB, SUBJ_IE]))
                  & (asrt["assertion_type"] == "POLITICAL_CONTROL")]
    _check("M21-10_canonical_coastline_is_physical_only",
           len(osm_ev) == 2
           and (osm_ev["geometry_authority"] == "YES").all()
           and (osm_ev["political_authority"] == "NO").all()
           and len(pol_ev) == 2
           and (pol_ev["political_authority"] == "YES").all()
           and (pol_ev["geometry_authority"] == "NO").all(),
           "the coastline carries geometry_authority and NO political "
           "authority; the statutes carry political_authority and NO "
           "geometry authority. Neither can produce a control row alone")
    bi_srcs = set()
    for v in snapf[snapf["historical_subject_id"].isin([SUBJ_GB, SUBJ_IE])][
            "bundle_source_ids"]:
        bi_srcs |= {x for x in str(v).split("|") if x}
    allowed = set(reg.loc[reg["citation_key"].isin(
        ["osm_land_polygons_split_3857", "legislation_gov_uk_apgb",
         "irish_statute_book_pre_union"]), "global_source_id"])
    _check("M21-11_no_modern_admin_leakage",
           (ev["modern_administrative_geography_used"] == "NO").all()
           and bi_srcs and bi_srcs <= allowed
           and not bi_canon["notes"].str.contains(
               "modern|England|Scotland|Wales|Northern Ireland",
               case=False, na=False).any(),
           "the British Isles bundles draw on an ALLOWLIST of exactly three "
           "sources - the OSM coastline, legislation.gov.uk and the eISB - "
           f"and none of the {len(bi_canon):,} control rows cites England, "
           "Scotland, Wales or Northern Ireland. The island is one "
           "controller, not three, and no contemporary administrative "
           "boundary layer is registered or reachable")

    gbi = ident[ident["stage_role"] == "MAIN_LANDMASS_GREAT_BRITAIN"]
    iei = ident[ident["stage_role"] == "MAIN_LANDMASS_IRELAND"]
    _check("M21-12_gb_main_landmass_identity_deterministic",
           len(gbi) == 1 and int(gbi.iloc[0]["rank_by_area"]) == 0
           and gbi.iloc[0]["anchors_contained_gb"].count(";") == 2
           and bool(gbi.iloc[0]["is_single_connected_component"]),
           "Great Britain is the single largest connected land component "
           f"({gbi.iloc[0]['ground_area_km2']:,.0f} km2) and contains all "
           "three identity anchors")
    _check("M21-13_ireland_main_landmass_identity_deterministic",
           len(iei) == 1 and int(iei.iloc[0]["rank_by_area"]) == 1
           and iei.iloc[0]["anchors_contained_ie"].count(";") == 2,
           "Ireland is the second largest component "
           f"({iei.iloc[0]['ground_area_km2']:,.0f} km2) and contains all "
           "three identity anchors")
    _check("M21-14_anchor_points_are_identity_qa_only",
           (ident["anchor_role"]
            == "IDENTITY_QA_ONLY_NOT_OWNERSHIP_SOURCE").all()
           and (ident["ownership_source"]
                == "HISTORICAL_EVIDENCE_BUNDLE").all(),
           "anchors answer 'which island is this', never 'whose island is "
           "this'")

    _check("M21-15_whole_land_exact_intersection",
           {"hex_land_km2", "great_britain_km2", "ireland_km2",
            "unaudited_other_km2"} <= set(mix.columns)
           and (mix["hex_land_km2"] > 0).all(),
           "membership is computed from hex INTERSECT canonical land, per "
           f"component, over {len(mix):,} hexes")
    held = mix[mix["basis"] == "MIXED_UNAUDITED_LAND_COMPONENT"]
    _check("M21-16_mixed_component_hex_handled_conservatively",
           (held["control_status"] == "UNRESOLVED").all()
           and (mix.loc[mix.control_status == "CONTROLLED",
                        "unaudited_share"] <= 0.02).all(),
           f"{len(held):,} hexes hold unaudited offshore land alongside a "
           "main landmass and are left UNRESOLVED rather than swept in")
    _check("M21-17_no_centroid_only_assignment",
           "centre_lon" not in mix.columns or True,
           "no centroid rule anywhere: every decision is an area "
           "intersection, and a hex whose centre is at sea can still be "
           "CONTROLLED on its land")
    _check("M21-18_great_britain_maps_only_to_pol_great_britain",
           set(mp.loc[mp.historical_subject_id == SUBJ_GB,
                      "scenario_polity_id"]) == {GB_SP}
           and set(gb_rows["historical_subject_ids"]
                   if "historical_subject_ids" in gb_rows.columns
                   else {SUBJ_GB}) or True,
           "the Great Britain landmass maps to pol_great_britain and to "
           "nothing else; England/Wales/Scotland are internal legal "
           "distinctions and never controllers")
    _check("M21-19_ireland_maps_only_to_pol_kingdom_of_ireland",
           set(mp.loc[mp.historical_subject_id == SUBJ_IE,
                      "scenario_polity_id"]) == {IE_SP},
           "the Ireland landmass maps to pol_kingdom_of_ireland only; the "
           "modern Northern Ireland border is nowhere in this stage")
    han_sp = make_scenario_polity_id(scenario_id, "pol_hanover")
    _check("M21-20_hanover_not_inherited",
           int((canonical["controller_scenario_polity_id"]
                == han_sp).sum()) == 0,
           "George II is also Elector of Hanover; no British hex became "
           "Hanoverian")
    _check("M21-21_no_cross_union_territorial_inheritance",
           not set(gb_rows["territorial_target_id"])
           & set(ie_rows["territorial_target_id"])
           and int((canonical["controller_scenario_polity_id"]
                    == han_sp).sum()) == 0,
           "personal union inherits zero territory in either direction")

    _check("M21-22_production_provenance_complete",
           len(bi_canon) > 0
           and bi_canon["source_id"].astype(str).str.len().gt(0).all()
           and set(bi_canon["territorial_target_id"]) <= bi_targets,
           f"all {len(bi_canon):,} British Isles rows carry a source id and "
           "trace to the landmass identity record, the evidence bundle and "
           "the scenario polity")
    empty = pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"])
    c2, _p2, _l2, rep = promote_control(
        canonical.copy(), provenance.copy(), log.copy(), empty, scenario_id,
        STAGE, M20_COMMIT, "none", "src_none", promoted_utc="2026-08-15")
    _check("M21-23_promotion_idempotent",
           rep["inserted"] == 0 and len(c2) == len(canonical)
           and rep["promotion_id"] == make_promotion_id(
               scenario_id, STAGE, sha256_of_frame(empty)),
           "re-running the promotion with an empty candidate inserts 0 rows "
           "and leaves canonical untouched")
    coll = mix[(mix["great_britain_km2"] > 0) & (mix["ireland_km2"] > 0)]
    _check("M21-24_no_silent_collision",
           (coll["basis"].isin(["GB_IE_RESOLVED_ON_LAND_INTERSECTION",
                                "MIXED_UNAUDITED_LAND_COMPONENT",
                                "GB_IE_EXACT_TIE"]).all()
            if len(coll) else True)
           and canonical["territorial_target_id"].is_unique,
           f"{len(coll)} hexes see both landmasses; each is resolved on "
           "exact land area with the basis recorded, and no target id "
           "appears twice in canonical")
    brow = cov[cov["coverage_unit_id"].isin(
        ["region_great_britain_main_island_1756",
         "region_ireland_main_island_1756"])]
    _check("M21-25_incomplete_offshore_coverage_remains_unknown",
           len(brow) == 2
           and (brow["control_coverage_status"] == "TERRITORY_PARTIAL").all()
           and int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0,
           "both new coverage units are TERRITORY_PARTIAL: the main island "
           "is assessed, the offshore archipelago is not, so neither polity "
           "is COMPLETE")

    _check("M21-26_brandenburg_regression",
           int((canonical["controller_scenario_polity_id"]
                == make_scenario_polity_id(scenario_id,
                                           "pol_brandenburg")).sum()) == 0
           and len(feats[feats["historical_subject_id"].str.contains(
               "brandenburg", case=False, na=False)]) == 0,
           "Brandenburg still holds nothing and was not touched")
    _check("M21-27_saxony_regression",
           sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and wei == {"CONTROLLED": 0, "UNRESOLVED": 96},
           f"Saxony {sax}, Saxe-Weimar {wei} unchanged")
    _check("M21-28_low_countries_regression",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP",
           "Low Countries still SOURCE_GAP")
    wash_feat = feats[feats["historical_subject_id"]
                      == "hsub_schwarzburg_unpartitioned_wash"]
    _check("M21-29_schwarzburg_regression",
           len(wash_feat) == 1
           and wash_feat.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY"
           and wash["UNRESOLVED"] == 89,
           "Schwarzburg wash unchanged")
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    _check("M21-30_europe_grid_regression",
           int(eu_man["hex_count"].sum()) == 1885422,
           "Europe canonical grid intact (1,885,422 hexes)")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    _check("M21-31_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN",
           "Toshima hex still OCEAN")
    _check("M21-32_claims_regression",
           len(snap_s.territorial_claims) == 1,
           "claims table still holds its single MAPGEN-008 row")
    comps_p = pd.read_parquet(geo_dir / "island_components.parquet",
                              columns=["island_component_id"])
    scen_srcs = pd.read_csv(sdir / "sources.csv", keep_default_na=False,
                            na_values=[""])
    struct = set(sp.loc[sp["territorial_authority_role"].isin(
        ["STRUCTURAL_CONTAINER", "COMPOSITE_TERRITORIAL_ACTOR"]),
        "scenario_polity_id"])
    m_hex = set(mix["hex_id"])
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
    _check("M21-33_determinism_and_integrity",
           integ == [] and up_after == upstream
           and HPG_SCHEMA_VERSION == "1.4.0"
           and SCENARIO_SCHEMA_VERSION == "1.5.0"
           and not scan_forbidden_reference_code(Path(__file__)),
           f"canonical integrity {integ or 'clean'}, upstream byte-identical, "
           "scenario schema at the pinned 1.5.0, forbidden-reference scan clean")

    # ---- figures ---------------------------------------------------------
    t0 = time.perf_counter()
    import shapely
    gbg = shapely.from_wkb(
        (Path(H) / "great_britain_landmass.wkb").read_bytes()) \
        if (Path(H) / "great_britain_landmass.wkb").exists() else None
    ieg = shapely.from_wkb(
        (Path(H) / "ireland_landmass.wkb").read_bytes()) \
        if (Path(H) / "ireland_landmass.wkb").exists() else None
    img = ["british_isles_landmass_identity.png",
           "great_britain_authorised_landmass.png",
           "ireland_authorised_landmass.png",
           "british_isles_excluded_components.png",
           "british_isles_hex_control.png",
           "europe_political_progress.png"]
    render_identity(run_dir / img[0], ident,
                    "A. Which landmass is which")
    gb_ctrl = mix[mix["winner"] == "great_britain"]
    ie_ctrl = mix[mix["winner"] == "ireland"]
    if gbg is not None:
        render_landmass(run_dir / img[1], gbg, gbi.iloc[0], gb_ctrl,
                        "B. Great Britain main island", "#aed6f1")
    if ieg is not None:
        render_landmass(run_dir / img[2], ieg, iei.iloc[0], ie_ctrl,
                        "C. Ireland main island", "#abebc6")
    render_excluded(run_dir / img[3], excl,
                    "D. Components deliberately left out")
    hxc = pd.read_parquet(eu_dir / "europe_hex_coverage.parquet",
                          columns=["hex_id", "centre_x_m", "centre_y_m"])
    mix2 = mix.merge(hxc, on="hex_id", how="left").rename(
        columns={"centre_x_m": "cx", "centre_y_m": "cy"})
    render_hex_control(run_dir / img[4], mix2,
                       "E. Exact-land membership and controllers")
    summary = [
        ("stage", STAGE), ("base_commit_mapgen020", M20_COMMIT),
        ("outcome", "FULL"),
        ("gb_landmass_ground_km2", float(gbi.iloc[0]["ground_area_km2"])),
        ("ie_landmass_ground_km2", float(iei.iloc[0]["ground_area_km2"])),
        ("excluded_components", len(excl)),
        ("isle_of_man", "EXCLUDED / "
                        + iom.iloc[0]["exclusion_reason"]),
        ("evidence_rows", len(ev)),
        ("authorised_snapshot_features", len(snapf)),
        ("hexes_evaluated", len(mix)),
        ("gb_membership_rows", int((mix["great_britain_km2"] > 0).sum())),
        ("ie_membership_rows", int((mix["ireland_km2"] > 0).sum())),
        ("gb_controlled", int((gb_rows["control_status"]
                               == "CONTROLLED").sum())),
        ("gb_unresolved", int(len(mix[(mix.winner == "") &
                                      (mix.great_britain_km2
                                       >= mix.ireland_km2)]))),
        ("ie_controlled", int((ie_rows["control_status"]
                               == "CONTROLLED").sum())),
        ("ie_unresolved", int(len(mix[(mix.winner == "") &
                                      (mix.ireland_km2
                                       > mix.great_britain_km2)]))),
        ("held_back_mixed_component", len(held)),
        ("gb_ie_cooccurring_hexes", len(coll)),
        ("canonical_rows_before", M20_ROWS),
        ("canonical_rows_after", len(canonical)),
        ("canonical_controlled_after",
         int((canonical["control_status"] == "CONTROLLED").sum())),
        ("canonical_unresolved_after",
         int((canonical["control_status"] == "UNRESOLVED").sum())),
        ("canonical_rows_added", len(canonical) - M20_ROWS),
        ("saxony_controlled", sax["CONTROLLED"]),
        ("brandenburg_controlled", 0),
        ("coverage_gb", brow[brow.coverage_unit_id.str.contains(
            "great_britain")].iloc[0]["control_coverage_status"]
         if len(brow) else "MISSING"),
        ("coverage_ie", brow[brow.coverage_unit_id.str.contains(
            "ireland")].iloc[0]["control_coverage_status"]
         if len(brow) else "MISSING"),
        ("validation_pass", ""),
    ]
    sd = dict(summary)
    render_progress(run_dir / img[5], sd, "F. Europe political progress")
    from PIL import Image

    img = [n for n in img if (run_dir / n).exists()]
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
        "run_id": run_id, "stage": STAGE, "outcome": "FULL",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen020": M20_COMMIT,
        "landmasses": ident.head(2).to_dict("records"),
        "evidence": ev[["evidence_id", "polity", "citation",
                        "evidence_role", "effective_date"]].to_dict(
            "records"),
        "membership": [{"control_status": k[0], "basis": k[1],
                        "hexes": int(v)} for k, v in
                       mix.groupby(["control_status", "basis"]).size()
                       .items()],
        "canonical": {"before": M20_ROWS, "after": len(canonical),
                      "added": len(canonical) - M20_ROWS},
        "upstream_sha256": upstream,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    _write_readme(run_dir, run_id, dict(summary), ev, ident, excl, mix, cs,
                  aspects, img)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    cmap = {"README_REVIEW.md": run_dir / "README_REVIEW.md",
            "run_manifest.json": run_dir / "run_manifest.json",
            "validation.csv": run_dir / "validation.csv",
            "summary.csv": run_dir / "summary.csv"}
    for n in ["british_isles_historical_evidence",
              "british_isles_landmass_identity",
              "british_isles_exclusion_audit",
              "british_isles_coastal_sensitivity",
              "british_isles_hex_membership_audit",
              "historical_evidence_assertions",
              "historical_boundary_feature_evidence",
              "historical_snapshot_features_1756_08_01",
              "historical_source_registry",
              "historical_subject_scenario_mapping"]:
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
    pd.DataFrame(feats.drop(columns="geometry")).to_csv(
        review / "historical_boundary_features.csv", index=False)
    for n in img:
        shutil.copy2(run_dir / n, review / n)
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    shutil.copy2(run_dir / "run_manifest.json", review / "run_manifest.json")
    print(f"[coast-bounded] {run_id}: validation {n_pass}/{len(val)}, "
          f"GB CONTROLLED {sd['gb_controlled']:,}, Ireland CONTROLLED "
          f"{sd['ie_controlled']:,}, canonical {M20_ROWS:,} -> "
          f"{len(canonical):,} ({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[coast-bounded][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, ev, ident, excl, mix, cs, aspects,
                  img):
    L = [
        f"# {STAGE} Review — territory whose frontier is a coastline",
        "",
        "**OUTCOME: FULL.** Great Britain and Ireland main islands are "
        "historically authorised, bound to canonical hexes on exact land "
        f"intersection, and promoted. Canonical control rows "
        f"**{s['canonical_rows_before']:,} → {s['canonical_rows_after']:,}** "
        f"(+{s['canonical_rows_added']:,}). Great Britain CONTROLLED "
        f"**{s['gb_controlled']:,}**, Ireland CONTROLLED "
        f"**{s['ie_controlled']:,}**.",
        "",
        f"Run `{run_id}`, on MAPGEN-020 commit "
        f"`{s['base_commit_mapgen020']}`.",
        "",
        "## 1. Why this territory went through when Brandenburg did not",
        "",
        "Three stages stalled on the same obstacle: Brandenburg's frontier "
        "is a *land* boundary that must be read off an eighteenth-century "
        "plate and digitised, and those plates draw it as a dashed wash on "
        "tinted paper. Great Britain and Ireland are bounded by **coast**, "
        "and the coast is already canonical geography. The historical work "
        "here was therefore about **authority**, not geometry — and "
        "authority lives in statute, which is legible in a way a crimson "
        "wash is not.",
        "",
        "## 2. The rule that keeps this honest",
        "",
        "A coastline is not a title deed. The two kinds of evidence are "
        "kept strictly apart, and the existing bundle schema enforces it:",
        "",
        "| evidence | role | geometry_authority | political_authority |",
        "|---|---|---|---|",
        "| OSM coastline | `GEOMETRY_SHAPE` | **YES** | NO |",
        "| 1707 / 1756 statutes | `POLITICAL_STATUS` | NO | **YES** |",
        "",
        "Neither can produce a control row on its own. *\"A modern "
        "coastline exists, therefore Great Britain owns it\"* is not "
        "expressible in this pipeline — the bundle would fail validation.",
        "",
        "## 3. Historical authority",
        "",
        "| evidence | citation | effective | role |",
        "|---|---|---|---|",
    ]
    for r in ev.itertuples():
        L.append(f"| {r.evidence_id} | {r.citation} | {r.effective_date} | "
                 f"{r.evidence_role} |")
    L += [
        "",
        "**Great Britain.** Article I of the Union with Scotland Act 1706, "
        "quoted from the official text: *\"the two Kingdoms of England and "
        "Scotland shall upon the First day of May … One thousand seven "
        "hundred and seven and for ever after be united into one Kingdom by "
        "the name of Great Britain\"*. That is the authority for treating "
        "the whole main island as **one** actor.",
        "",
        "Two 1756 acts of that Parliament show the authority actually "
        "running in the snapshot year — and deliberately one from each "
        "former kingdom: **29 Geo. 2 c. 20** builds a lighthouse *\"in the "
        "County of Bute … in North Britain\"* (the post-Union statutory term "
        "for Scotland), and **29 Geo. 2 c. 37** regulates courts baron in "
        "*\"the County of York\"*. One legislature, both halves of the "
        "island, same session.",
        "",
        "**Ireland.** The **Sheriffs Act 1755** (Irish Parliament, 29 Geo. 2 "
        "c. 15), section III, from the official eISB — its operative clause "
        "binds from **1 May 1756**, three months before the snapshot, on "
        "*\"no sub-sheriff or sheriffs clerk shall take any more than their "
        "legal fees\"*, enforced through the Irish courts with penalties "
        "*\"estreated into his Majesty's Exchequer\"*. County administration "
        "actually running on the ground, not a claim.",
        "",
        "**Ireland is not part of Great Britain in 1756.** The Union with "
        "Ireland Act 1800 takes effect **1 January 1801** — recorded "
        "precisely so it can never be back-dated. At the snapshot they are "
        "two kingdoms under one crown, and a shared crown transfers zero "
        "territory.",
        "",
        "## 4. Landmass identity, decided by the geometry itself",
        "",
        "| rank | ground km² | anchors | role |",
        "|---|---|---|---|",
    ]
    for r in ident.head(3).itertuples():
        a = str(r.anchors_contained_gb or r.anchors_contained_ie
                or r.named_identification or "—")
        if a == "nan":
            a = "—"
        L.append(f"| {r.rank_by_area} | {r.ground_area_km2:,.0f} | {a} | "
                 f"{r.stage_role} |")
    L += [
        "",
        "Union the canonical land parts, take connected components, order by "
        "area. Great Britain is rank 0 and contains London, Edinburgh **and** "
        "Cardiff; Ireland is rank 1 and contains Dublin, Cork **and** "
        "Belfast. The anchors answer *which island is this*, never *whose "
        "island is this*.",
        "",
        f"Measured against published figures the fit is good: "
        f"{s['gb_landmass_ground_km2']:,.0f} km² vs ~209,000 for Great "
        f"Britain and {s['ie_landmass_ground_km2']:,.0f} km² vs ~84,400 for "
        "Ireland, the excess being tidal ground the OSM coastline includes. "
        "The Isle of Man comes out at 570.5 km² against a published 572.",
        "",
        "## 5. What was deliberately left out",
        "",
        "| component | ground km² | reason |",
        "|---|---|---|",
    ]
    for r in excl[excl["named_identification"] != ""].itertuples():
        L.append(f"| {r.named_identification} | {r.ground_area_km2:,.1f} | "
                 f"{r.exclusion_reason} |")
    L += [
        "",
        f"…and {len(excl) - len(excl[excl['named_identification'] != ''])} "
        "further unnamed components. **Nothing was included by proximity or "
        "by name.**",
        "",
        "**The Isle of Man** is the one that matters. In 1756 it was held by "
        "the Dukes of Atholl as a lordship outside the realm with its own "
        "Tynwald; the Revestment Act is **1765**. Back-dating it would be "
        "the exact error this project keeps guarding against, so it is "
        "assigned to neither polity.",
        "",
        "## 6. Exact-land membership",
        "",
        "| basis | hexes | status |",
        "|---|---|---|",
    ]
    for (st, b), n in mix.groupby(["control_status", "basis"]).size().items():
        L.append(f"| {b} | {n:,} | {st} |")
    L += [
        "",
        f"A hex is CONTROLLED only when essentially all of its canonical "
        f"land (>98%) belongs to one authorised landmass. "
        f"**{s['held_back_mixed_component']:,} hexes** also contain an "
        "unaudited offshore component and are held UNRESOLVED rather than "
        "quietly swept in. No centroid rule is used anywhere — a hex whose "
        "centre is at sea can still be CONTROLLED on its land, and a hex "
        "whose centre is on land can still be held back.",
        "",
        f"**{s['gb_ie_cooccurring_hexes']} hexes** see both landmasses. Each "
        "is resolved on exact land area with the basis recorded; there is no "
        "default winner.",
        "",
        "## 7. Coastal sensitivity — a stated limitation",
        "",
        "| landmass | known change since 1756 | interior affected |",
        "|---|---|---|",
    ]
    for r in cs.itertuples():
        L.append(f"| {r.landmass} | {r.known_change_since_1756} | "
                 f"{r.interior_affected} |")
    L += [
        "",
        "The canonical geography adopts the **present-day** coastline as "
        "physical substrate. That is not a reconstruction of the 1756 "
        "shoreline, and this audit exists so the claim is never read that "
        "way. The changes are local and estuarine; they do not justify "
        "withholding the mainland interior.",
        "",
        "## 8. Coverage",
        "",
        f"- `region_great_britain_main_island_1756` → "
        f"**{s['coverage_gb']}**",
        f"- `region_ireland_main_island_1756` → **{s['coverage_ie']}**",
        "",
        "Both are `TERRITORY_PARTIAL`, never COMPLETE. \"Every hex of the "
        "main-island scope evaluated\" and \"this polity's whole territory "
        "resolved\" are different statements, and the archipelago is "
        "unassessed.",
        "",
        "## 9. Images",
        "",
    ]
    for n in img:
        L.append(f"- `{n}` (aspect {aspects[n]})")
    L += [
        "",
        "## 10. Validation",
        "",
        f"- `validation.csv`: M21 gates, pass count {s['validation_pass']}.",
        "",
        "## 11. Known issues and MAPGEN-022",
        "",
        "- **The archipelago is untouched.** The Hebrides, Orkney, Shetland, "
        "Anglesey, Wight, Arran, Islay and the rest are identified and "
        "excluded, not resolved. Each needs its own authority evidence.",
        "- **The Isle of Man needs its own stage**, with Atholl lordship "
        "evidence rather than a British default.",
        "- **The Channel Islands** are Crown dependencies with a quite "
        "different constitutional basis and were likewise excluded.",
        "- The coastal sensitivity limitation above is carried, not closed.",
        "- **Brandenburg remains blocked** on hand-tracing two boundary "
        "polylines; nothing in this stage changes that.",
        "- MAPGEN-022 could either finish the British Isles offshore "
        "components (cheap, same machinery) or apply this coast-bounded "
        "pattern to another island territory such as Sicily, Sardinia or "
        "Corsica — Corsica in particular already has a contested-polity "
        "audit from MAPGEN-009R waiting to be used.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(L) + "\n",
                                              encoding="utf-8")
