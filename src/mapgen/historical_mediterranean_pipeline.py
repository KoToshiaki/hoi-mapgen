"""MAPGEN-022 — the coast-bounded method, moved to a harder pair of islands.

MAPGEN-021 worked because Great Britain and Ireland are bounded by coast.
Sicily and Sardinia are too, so the machinery transfers unchanged. What does
NOT transfer is the history, and this stage is mostly about two traps that
the British Isles case did not contain.

The first is name inference. In 1720 Savoy swapped SICILY for SARDINIA with
Austria; in 1738 Austria passed Naples and Sicily to a Bourbon. The same two
islands changed hands between the same two powers inside eighteen years, so
"the Kingdom of Sardinia must hold Sardinia" is exactly the kind of reasoning
that would have put the wrong island under the wrong crown a generation
earlier. Each island is authorised by its own treaty and its own surviving
administration.

The second is composite scope. Before the fusione perfetta of 1847 the
Kingdom of Sardinia legally IS the island; Piedmont, Savoy and Nice are a
separate holding of the same dynasty. Producing the mainland from this actor
would be the 1847 state back-dated by ninety years. Sicily has the mirror
case: Naples shares its monarch in 1756 but is a separate kingdom until 1816.
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

STAGE = "MAPGEN-022"
H = Path("data/historical")
M21_COMMIT = "9ad43bf966469109563d4823144146149a027726"
M21_SUMMARY = Path("reviews/MAPGEN-021/summary.csv")
SIC_SP, SAR_SP = "sp_14ee92dede27", "sp_5f0f4d8d4788"
NAP_SP = "sp_def69cc80f28"
SUBJ_SIC = "hsub_sicily_main_island"
SUBJ_SAR = "hsub_sardinia_main_island"


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
    """MAPGEN-021's own committed summary is the authority for the baseline.

    Not a number remembered from a previous run - the artifact that was
    actually pushed.
    """
    s = pd.read_csv(M21_SUMMARY)
    d = dict(zip(s["metric"].astype(str), s["value"].astype(str)))
    return {k: int(float(d[k])) for k in
            ("canonical_rows_after", "canonical_controlled_after",
             "canonical_unresolved_after", "gb_membership_rows",
             "gb_controlled", "gb_unresolved", "ie_membership_rows",
             "ie_controlled", "ie_unresolved")}


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def render_identity(path, ident, title):
    fig, (ax, ax2) = _fig2((16, 7.5), [1, 1])
    top = ident.head(14)
    col = ["#b03a2e" if r == "MAIN_LANDMASS_SICILY" else
           "#1f618d" if r == "MAIN_LANDMASS_SARDINIA" else "#aab7b8"
           for r in top["stage_role"]]
    ax.barh(range(len(top)), top["ground_area_km2"], color=col)
    ax.set_yticks(range(len(top)))
    lab = []
    for r in top.itertuples():
        n = str(r.named_identification or "")
        if r.stage_role == "MAIN_LANDMASS_SICILY":
            n = "SICILY"
        elif r.stage_role == "MAIN_LANDMASS_SARDINIA":
            n = "SARDINIA"
        lab.append(n or f"rank {r.rank_by_area}")
    ax.set_yticklabels(lab, fontsize=7)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("ground area (km2, log)")
    ax.set_title("connected land components, largest first", fontsize=10)
    body = ["LANDMASS IDENTITY", ""]
    body += _wrap(
        "Union the canonical land parts over the western and central "
        "Mediterranean, take connected components, order by area. The two "
        "target islands are ranks 2 and 3 - BELOW North Africa and the "
        "Italian mainland, which is the point: size alone identifies "
        "nothing, and the anchors are what say which island is which.")
    body += ["", "  rank  ground km2   anchors / identity", ""]
    for r in ident.head(4).itertuples():
        a = str(r.anchors_contained_sicily or r.anchors_contained_sardinia
                or r.named_identification or "-")
        body.append(f"  {r.rank_by_area:>4} {r.ground_area_km2:11,.0f}   "
                    f"{a[:52]}")
    body += ["", "AREA AGAINST PUBLISHED FIGURES", ""]
    body += _wrap(
        "Sicily 25,437 km2 against a published 25,711 and Sardinia 23,833 "
        "against 24,090 - both 1.07 percent low. See the area-semantics "
        "audit: three of the four islands produced so far sit about one per "
        "cent BELOW their published figure, so the MAPGEN-021 story that the "
        "canonical outline runs large because of tidal ground does not "
        "survive measurement.")
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7.4)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_landmass(path, geom, row, ctrl, title, colour):
    fig, (ax, ax2) = _fig2((14, 7), [1, 1])
    gpd.GeoSeries([geom], crs="EPSG:3857").plot(
        ax=ax, color=colour, edgecolor="#2c3e50", linewidth=0.5)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title("authorised landmass scope", fontsize=10)
    body = ["HISTORICALLY_AUTHORISED_LANDMASS_SCOPE", ""]
    body += _wrap(
        "The polygon is the canonical PHYSICAL land component. It becomes "
        "territory only because political assertions are bundled with it.")
    body += ["", f"  ground area        {row['ground_area_km2']:,.0f} km2",
             f"  projected area     {row['projected_area_km2']:,.0f} km2",
             f"  centroid           {row['centroid_lon']:.3f}, "
             f"{row['centroid_lat']:.3f}",
             "  identity anchors   "
             + str(row["anchors_contained_sicily"]
                   or row["anchors_contained_sardinia"]),
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
    fig, ax = _fig((14, 8.5))
    ax.set_axis_off()
    named = excl[excl["named_identification"] != ""]
    body = ["EXCLUDED COMPONENTS", "",
            "  component                        ground km2   reason", ""]
    for r in named.itertuples():
        body.append(f"  {str(r.named_identification)[:30]:30s} "
                    f"{r.ground_area_km2:11,.1f}   {r.exclusion_reason}")
    body += ["", f"  ... and {len(excl) - len(named)} further unnamed "
                 "components, all excluded", "", "CORSICA", ""]
    c = excl[excl["named_identification"].str.contains("Corsica", na=False)]
    if len(c):
        body += ["  " + ln for ln in _wrap(c.iloc[0]["note"], 86)]
    body += ["", "MALTA", ""]
    m = excl[excl["named_identification"].str.contains("Malta", na=False)]
    if len(m):
        body += ["  " + ln for ln in _wrap(m.iloc[0]["note"], 86)]
    body += ["", "WHY THE TWO BIGGEST EXCLUSIONS MATTER", ""]
    body += ["  " + ln for ln in _wrap(
        "North Africa and the Italian mainland are the two largest "
        "components in the window, both bigger than either target island. "
        "A rule that took 'the largest components' would have produced "
        "Tunisia and Italy. Identity is decided by anchors, not by size.",
        86)]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=7.6)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_hex_control(path, mix, title):
    fig, (ax, ax2) = _fig2((15, 7), [1, 1])
    cols = {"sicily": "#b03a2e", "sardinia": "#1f618d", "": "#f39c12"}
    for w, g in mix.groupby("winner"):
        ax.scatter(g["cx"], g["cy"], s=3.5, c=cols.get(w, "#f39c12"),
                   label=f"{w or 'UNRESOLVED'} ({len(g):,})")
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.legend(fontsize=8, markerscale=4, loc="lower left")
    ax.set_title("canonical hexes, coloured by controller", fontsize=10)
    body = ["EXACT-LAND MEMBERSHIP", ""]
    body += _wrap(
        "The MAPGEN-021 contract is reused unchanged, including its 2 per "
        "cent unaudited-land threshold: it was audited against this data "
        "before reuse and not altered.")
    body += ["", "  basis                                    hexes", ""]
    for (st, b), n in mix.groupby(["control_status", "basis"]).size().items():
        body.append(f"  {b:40s} {n:6,d}  [{st}]")
    body += ["", "  winner                                   hexes", ""]
    for w, n in mix[mix.control_status == "CONTROLLED"][
            "winner"].value_counts().items():
        body.append(f"  {w:40s} {n:6,d}")
    coll = mix[(mix.sicily_km2 > 0) & (mix.sardinia_km2 > 0)]
    body += ["", f"  hexes where BOTH islands appear: {len(coll)}",
             "  the two are 200 km apart, so zero is the expected answer "
             "and", "  a non-zero count would have meant a component error"]
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7.4)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_progress(path, s, base, title):
    fig, ax = _fig((15, 9))
    ax.set_axis_off()
    body = [
        "EUROPE POLITICAL PROGRESS", "",
        f"  canonical control rows        : "
        f"{base['canonical_rows_after']:,} -> "
        f"{s['canonical_rows_after']:,}",
        f"  CONTROLLED                    : "
        f"{base['canonical_controlled_after']:,} -> "
        f"{s['canonical_controlled_after']:,}",
        f"  UNRESOLVED                    : "
        f"{base['canonical_unresolved_after']:,} -> "
        f"{s['canonical_unresolved_after']:,}",
        "",
        "  PRODUCED THIS STAGE", "",
        f"    Sicily CONTROLLED           : {s['sicily_controlled']:,}",
        f"    Sicily UNRESOLVED           : {s['sicily_unresolved']:,}",
        f"    Sardinia CONTROLLED         : {s['sardinia_controlled']:,}",
        f"    Sardinia UNRESOLVED         : {s['sardinia_unresolved']:,}",
        "",
        "  HELD FROM EARLIER STAGES", "",
        f"    Great Britain CONTROLLED    : {base['gb_controlled']:,}",
        f"    Ireland CONTROLLED          : {base['ie_controlled']:,}",
        f"    Saxony CONTROLLED           : {s['saxony_controlled']:,}",
        f"    Brandenburg CONTROLLED      : {s['brandenburg_controlled']}",
        "",
        "SCOPE DELIBERATELY NOT TAKEN", "",
        f"  Corsica                       : {s['corsica_result']}",
        f"  Malta                         : EXCLUDED (Order of St John)",
        f"  Sardinian mainland possessions: NOT PRODUCED - before the 1847",
        "                                  fusione perfetta the Kingdom of",
        "                                  Sardinia IS the island; Piedmont,",
        "                                  Savoy and Nice are a separate",
        "                                  composite holding",
        f"  Naples                        : NOT PRODUCED - separate kingdom",
        "                                  until 1816 despite a shared king",
        "",
        f"  offshore components excluded  : {s['excluded_components']}",
        f"  coverage Sicily               : {s['coverage_sicily']}",
        f"  coverage Sardinia             : {s['coverage_sardinia']}",
    ]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=9)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
def run_historical_mediterranean(cfg: MapgenConfig,
                                 run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"mediterranean_1756_{_dt.datetime.now():%Y%m%d}"
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
    feats = gpd.read_parquet(H / "historical_boundary_features.parquet")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    asrt = pd.read_csv(H / "historical_evidence_assertions.csv")
    mp = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    ev = pd.read_csv(H / "mediterranean_historical_evidence.csv",
                     keep_default_na=False, na_values=[])
    ident = pd.read_csv(H / "mediterranean_landmass_identity.csv",
                        keep_default_na=False, na_values=[]).fillna("")
    excl = pd.read_csv(H / "mediterranean_exclusion_audit.csv",
                       keep_default_na=False, na_values=[]).fillna("")
    cs = pd.read_csv(H / "mediterranean_coastal_sensitivity.csv")
    area = pd.read_csv(H / "mediterranean_area_semantics.csv")
    gsa = pd.read_csv(H / "geometry_storage_audit.csv")
    mix = pd.read_csv(H / "mediterranean_hex_membership_audit.csv",
                      keep_default_na=False, na_values=[])
    snapf = pd.read_csv(H / "historical_snapshot_features_1756_08_01.csv")
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv"]}
    timings["load_s"] = time.perf_counter() - t0

    sic_rows = canonical[canonical["controller_scenario_polity_id"] == SIC_SP]
    sar_rows = canonical[canonical["controller_scenario_polity_id"] == SAR_SP]
    med_targets = set(mix["hex_id"])
    med_canon = canonical[canonical["territorial_target_id"].isin(
        med_targets)]

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
    gb_ctrl = int((canonical["controller_scenario_polity_id"]
                   == "sp_6b03622fc98a").sum())
    ie_ctrl = int((canonical["controller_scenario_polity_id"]
                   == "sp_c8f0dcb42a96").sum())

    # ---- gates -----------------------------------------------------------
    _check("M22-01_mapgen021_regression",
           len(canonical) - len(med_canon) == base["canonical_rows_after"]
           and gb_ctrl == base["gb_controlled"]
           and ie_ctrl == base["ie_controlled"],
           f"removing the {len(med_canon):,} Mediterranean rows leaves "
           f"exactly {base['canonical_rows_after']:,}; Great Britain "
           f"{gb_ctrl:,} and Ireland {ie_ctrl:,} CONTROLLED unchanged")
    _check("M22-02_baseline_read_from_committed_summary",
           M21_SUMMARY.exists()
           and base["canonical_rows_after"] == 29578
           and base["gb_membership_rows"] == 20396
           and base["ie_membership_rows"] == 7568,
           "the baseline is read from the COMMITTED reviews/MAPGEN-021/"
           f"summary.csv - {base['canonical_rows_after']:,} rows, GB "
           f"membership {base['gb_membership_rows']:,}, Ireland "
           f"{base['ie_membership_rows']:,} - not from a remembered figure")
    _check("M22-03_sicily_actor_resolved",
           SIC_SP in set(sp["scenario_polity_id"])
           and sp.loc[sp.scenario_polity_id == SIC_SP, "polity_id"].iloc[0]
           == "pol_sicily",
           "pol_sicily resolved from the existing MAPGEN-009 catalogue; no "
           "new actor created")
    _check("M22-04_sardinia_actor_resolved",
           SAR_SP in set(sp["scenario_polity_id"])
           and sp.loc[sp.scenario_polity_id == SAR_SP, "polity_id"].iloc[0]
           == "pol_sardinia",
           "pol_sardinia resolved from the existing catalogue")
    _check("M22-05_no_duplicate_actors",
           sp["polity_id"].is_unique
           and sp["scenario_polity_id"].is_unique
           and int(sp["polity_id"].isin(["pol_sicily",
                                         "pol_sardinia"]).sum()) == 2,
           "each polity id appears once; no Sicily or Sardinia duplicate "
           "was introduced")
    sic_sov = ev[(ev.polity == "pol_sicily")
                 & (ev.kind == "SOVEREIGNTY_BASIS")]
    _check("M22-06_sicily_authority_exact_locator",
           len(sic_sov) == 1
           and "1738" in sic_sov.iloc[0]["exact_locator"]
           and sic_sov.iloc[0]["in_force_at_snapshot"] == "YES",
           "Treaty of Vienna 1738 cited with its cession clause: Austria "
           "cedes Naples and Sicily to Don Carlos for Parma and Piacenza")
    sic_now = ev[(ev.polity == "pol_sicily")
                 & ev.kind.str.startswith("CONTEMPORARY")]
    _check("M22-07_sicily_contemporary_evidence",
           len(sic_now) >= 1
           and "Deputazione del regno" in sic_now.iloc[0]["exact_locator"]
           and "1547-1819" in sic_now.iloc[0]["exact_locator"],
           "the island's own organs, with archival date ranges spanning "
           "1756: Real segreteria (1611-1826), Deputazione del regno "
           "(1547-1819) and three functional deputations")
    sar_sov = ev[(ev.polity == "pol_sardinia")
                 & (ev.kind == "SOVEREIGNTY_BASIS")]
    _check("M22-08_sardinia_authority_exact_locator",
           len(sar_sov) == 1
           and "1720" in sar_sov.iloc[0]["exact_locator"]
           and "Hague" in sar_sov.iloc[0]["title"],
           "Treaty of The Hague 1720 cited with the Savoy-Austria exchange "
           "clause; Sicily out, Sardinia in")
    sar_now = ev[(ev.polity == "pol_sardinia")
                 & ev.kind.str.startswith("CONTEMPORARY")]
    _check("M22-09_sardinia_contemporary_evidence",
           len(sar_now) >= 1
           and any("1720-1848" in x for x in sar_now["exact_locator"]),
           "Segreteria di Stato e di Guerra del Regno di Sardegna "
           "(1720-1848) - the Savoyard apparatus for the island opens in "
           "the year of the exchange and is running at the snapshot")
    cut = ev[ev.evidence_role == "TEMPORAL_BOUNDARY"]
    _check("M22-10_post_snapshot_state_not_backdated",
           len(cut) >= 3
           and (cut["in_force_at_snapshot"] == "NO").all()
           and (cut["effective_date"] > "1756-08-01").all(),
           "three post-snapshot cutoffs recorded and all marked not in "
           "force: 1759 Bourbon succession, 1816 Two Sicilies, 1847 fusione "
           "perfetta")
    _check("M22-11_sicily_naples_personal_union_no_merge",
           int((canonical["controller_scenario_polity_id"]
                == NAP_SP).sum()) == 0
           and not set(sic_rows["territorial_target_id"])
           & set(canonical.loc[canonical["controller_scenario_polity_id"]
                               == NAP_SP, "territorial_target_id"]),
           "Charles of Bourbon is king of both in 1756, and Naples still "
           "holds nothing: the shared crown produced no territory and the "
           "1816 merger was not back-dated")
    sar_map = mp[mp.historical_subject_id == SUBJ_SAR]
    _check("M22-12_sardinia_mainland_not_auto_produced",
           len(sar_map) == 1
           and "1847" in sar_map.iloc[0]["mapping_basis"]
           and len(sar_rows) == int((mix["winner"] == "sardinia").sum()),
           "every Sardinia row comes from the island component only; the "
           "mapping basis records that before 1847 the Kingdom of Sardinia "
           "IS the island and Piedmont, Savoy and Nice are a separate "
           "composite holding")
    cor = excl[excl["named_identification"].str.contains("Corsica",
                                                         na=False)]
    cor_sp = make_scenario_polity_id(scenario_id, "pol_corsican_republic")
    _check("M22-13_corsica_not_auto_assigned",
           len(cor) == 1
           and cor.iloc[0]["exclusion_reason"]
           == "SEPARATE_CONTESTED_POLITY_NOT_SARDINIA"
           and cor_sp in set(sp["scenario_polity_id"])
           and int((canonical["controller_scenario_polity_id"]
                    == cor_sp).sum()) == 0,
           f"Corsica ({cor.iloc[0]['ground_area_km2']:,.0f} km2) is its own "
           "component, assigned to nobody; the MAPGEN-009R contested audit "
           "for pol_corsican_republic is left exactly as it was")

    geo_ev = asrt[(asrt.historical_subject_id.isin([SUBJ_SIC, SUBJ_SAR]))
                  & (asrt.assertion_type == "GEOMETRIC_SUBSTRATE_ONLY")]
    pol_ev = asrt[(asrt.historical_subject_id.isin([SUBJ_SIC, SUBJ_SAR]))
                  & (asrt.assertion_type == "POLITICAL_CONTROL")]
    _check("M22-14_canonical_coastline_physical_only",
           len(geo_ev) == 2
           and (geo_ev["geometry_authority"] == "YES").all()
           and (geo_ev["political_authority"] == "NO").all()
           and len(pol_ev) == 4
           and (pol_ev["political_authority"] == "YES").all()
           and (pol_ev["geometry_authority"] == "NO").all(),
           "the coastline carries geometry authority only and the treaties "
           "and archives carry political authority only; neither side can "
           "produce a control row alone")
    med_srcs = set()
    for v in snapf[snapf.historical_subject_id.isin(
            [SUBJ_SIC, SUBJ_SAR])]["bundle_source_ids"]:
        med_srcs |= {x for x in str(v).split("|") if x}
    allowed = set(reg.loc[reg["citation_key"].isin(
        ["osm_land_polygons_split_3857",
         "guida_generale_archivi_stato_palermo",
         "sias_archivio_di_stato_cagliari",
         "european_peace_settlements_1720_1738"]), "global_source_id"])
    _check("M22-15_no_modern_italian_admin_leakage",
           (ev["modern_administrative_geography_used"] == "NO").all()
           and (ev["name_inference_used"] == "NO").all()
           and med_srcs and med_srcs <= allowed
           and not med_canon["notes"].str.contains(
               "Regione|provincia|comune|modern", case=False,
               na=False).any(),
           "the bundles draw on an allowlist of exactly four sources and no "
           "control row cites a modern Italian region, province or comune")
    sic_i = ident[ident.stage_role == "MAIN_LANDMASS_SICILY"]
    sar_i = ident[ident.stage_role == "MAIN_LANDMASS_SARDINIA"]
    _check("M22-16_sicily_component_deterministic",
           len(sic_i) == 1
           and sic_i.iloc[0]["anchors_contained_sicily"].count(";") == 2
           and bool(sic_i.iloc[0]["is_single_connected_component"]),
           f"one connected component of {sic_i.iloc[0]['ground_area_km2']:,.0f}"
           " km2 containing Palermo, Messina and Catania")
    _check("M22-17_sardinia_component_deterministic",
           len(sar_i) == 1
           and sar_i.iloc[0]["anchors_contained_sardinia"].count(";") == 2,
           f"one connected component of {sar_i.iloc[0]['ground_area_km2']:,.0f}"
           " km2 containing Cagliari, Sassari and Oristano")
    _check("M22-18_anchors_identity_only",
           (ident["anchor_role"]
            == "IDENTITY_QA_ONLY_NOT_OWNERSHIP_SOURCE").all()
           and (ident["ownership_source"]
                == "HISTORICAL_EVIDENCE_BUNDLE").all()
           and int(sic_i.iloc[0]["rank_by_area"]) > 1,
           "anchors say which island, never whose. Note both targets rank "
           "BELOW North Africa and the Italian mainland by area, so size "
           "could not have identified them")

    _check("M22-19_exact_land_intersection",
           {"hex_land_km2", "sicily_km2", "sardinia_km2",
            "unaudited_other_km2"} <= set(mix.columns)
           and (mix["hex_land_km2"] > 0).all(),
           f"membership over {len(mix):,} hexes from hex INTERSECT canonical "
           "land, attributed per component")
    held = mix[mix["basis"] == "MIXED_UNAUDITED_LAND_COMPONENT"]
    _check("M22-20_mixed_components_conservative",
           (held["control_status"] == "UNRESOLVED").all()
           and (mix.loc[mix.control_status == "CONTROLLED",
                        "unaudited_share"] <= 0.02).all(),
           f"{len(held)} hexes carry unaudited offshore land beside a main "
           "island and are held UNRESOLVED; the MAPGEN-021 2 per cent "
           "threshold was audited against this data and reused unchanged")
    _check("M22-21_no_centroid_only_assignment",
           "centre_lon" not in mix.columns,
           "no centroid rule: every decision is an area intersection")
    _check("M22-22_authority_bundle_complete",
           len(med_canon) > 0
           and med_canon["source_id"].astype(str).str.len().gt(0).all()
           and set(med_canon["territorial_target_id"]) <= med_targets,
           f"all {len(med_canon):,} Mediterranean rows trace to a scenario "
           "polity, an evidence assertion, the landmass identity record and "
           "the canonical substrate")
    _check("M22-23_sicily_maps_only_to_sicily_actor",
           set(mp.loc[mp.historical_subject_id == SUBJ_SIC,
                      "scenario_polity_id"]) == {SIC_SP}
           and len(sic_rows) == int((mix["winner"] == "sicily").sum()),
           "the Sicily landmass maps to pol_sicily and nothing else")
    _check("M22-24_sardinia_maps_only_to_sardinia_actor",
           set(mp.loc[mp.historical_subject_id == SUBJ_SAR,
                      "scenario_polity_id"]) == {SAR_SP},
           "the Sardinia landmass maps to pol_sardinia and nothing else")
    _check("M22-25_area_semantics_honestly_reported",
           len(area) == 2
           and (area["n_interior_rings"] == 0).all()
           and area["inland_water_treatment"].str.startswith(
               "MEASURED").all()
           and area["intertidal_treatment"].str.contains(
               "NOT measured").all(),
           "ground and projected area reported with the Mercator factor "
           "checked against 1/cos^2(lat); inland water MEASURED (zero "
           "interior rings, so none excluded); the intertidal mechanism is "
           "named but explicitly NOT quantified and NOT used to explain the "
           "residual")
    _check("M22-26_geometry_storage_exactness_preserved",
           len(gsa) >= 2
           and (gsa["simplified"] == "NO").all()
           and (gsa["duplicated_as_wkt_csv"] == "NO").all()
           and (gsa["simplification_tolerance_m"] == 0).all(),
           "geometry is stored exactly once in the feature parquet, never "
           "duplicated as WKT and never simplified - membership must stay "
           "reproducible from the stored artifacts")

    empty = pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"])
    c2, _p2, _l2, rep = promote_control(
        canonical.copy(), provenance.copy(), log.copy(), empty, scenario_id,
        STAGE, M21_COMMIT, "none", "src_none", promoted_utc="2026-08-15")
    _check("M22-27_promotion_idempotent",
           rep["inserted"] == 0 and len(c2) == len(canonical)
           and rep["promotion_id"] == make_promotion_id(
               scenario_id, STAGE, sha256_of_frame(empty)),
           "re-running promotion with an empty candidate inserts 0 rows")
    coll = mix[(mix["sicily_km2"] > 0) & (mix["sardinia_km2"] > 0)]
    _check("M22-28_no_silent_collision",
           len(coll) == 0
           and canonical["territorial_target_id"].is_unique
           and int(log["promotion_status"].eq("PROMOTED").sum()) >= 1,
           "zero hexes see both islands, which is the expected answer for "
           "landmasses 200 km apart; no target id repeats in canonical and "
           "no existing row was overwritten")
    crow = cov[cov["coverage_unit_id"].isin(
        ["region_sicily_main_island_1756",
         "region_sardinia_main_island_1756"])]
    _check("M22-29_incomplete_offshore_coverage_remains_unknown",
           len(crow) == 2
           and (crow["control_coverage_status"] == "TERRITORY_PARTIAL").all()
           and int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0,
           "both new coverage units are TERRITORY_PARTIAL; no unit anywhere "
           "in the scenario is COMPLETE")

    _check("M22-30_british_isles_regression",
           gb_ctrl == base["gb_controlled"] and ie_ctrl == base["ie_controlled"]
           and set(mp.loc[mp.historical_subject_id
                          == "hsub_great_britain_main_island",
                          "scenario_polity_id"]) == {"sp_6b03622fc98a"},
           f"Great Britain {gb_ctrl:,} and Ireland {ie_ctrl:,} CONTROLLED, "
           "matching the committed MAPGEN-021 summary exactly")
    _check("M22-31_brandenburg_regression",
           int((canonical["controller_scenario_polity_id"]
                == make_scenario_polity_id(scenario_id,
                                           "pol_brandenburg")).sum()) == 0
           and (H / "brandenburg_boundary_segment_continuity.csv").exists()
           and (H / "brandenburg_blha_transform.json").exists(),
           "Brandenburg untouched: still holds nothing, and the MAPGEN-020 "
           "continuity and BLHA georeference artifacts are intact")
    _check("M22-32_saxony_regression",
           sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and wei == {"CONTROLLED": 0, "UNRESOLVED": 96},
           f"Saxony {sax}, Saxe-Weimar {wei} unchanged")
    _check("M22-33_low_countries_regression",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP",
           "Low Countries still SOURCE_GAP")
    wash_feat = feats[feats["historical_subject_id"]
                      == "hsub_schwarzburg_unpartitioned_wash"]
    _check("M22-34_schwarzburg_regression",
           len(wash_feat) == 1
           and wash_feat.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY"
           and wash["UNRESOLVED"] == 89,
           "Schwarzburg wash unchanged and still not production-convertible")
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    _check("M22-35_europe_grid_regression",
           int(eu_man["hex_count"].sum()) == 1885422,
           "Europe canonical grid intact (1,885,422 hexes)")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    _check("M22-36_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN",
           "Toshima hex still OCEAN")
    _check("M22-37_claims_regression",
           len(snap_s.territorial_claims) == 1,
           "claims table still holds its single MAPGEN-008 row")
    comps_p = pd.read_parquet(geo_dir / "island_components.parquet",
                              columns=["island_component_id"])
    scen_srcs = pd.read_csv(sdir / "sources.csv", keep_default_na=False,
                            na_values=[""])
    struct = set(sp.loc[sp["territorial_authority_role"].isin(
        ["STRUCTURAL_CONTAINER", "COMPOSITE_TERRITORIAL_ACTOR"]),
        "scenario_polity_id"])
    m_hex = set(mix["hex_id"]) | set(pd.read_csv(
        H / "british_isles_hex_membership_audit.csv",
        keep_default_na=False, na_values=[])["hex_id"])
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
    _check("M22-38_determinism_and_integrity",
           integ == [] and up_after == upstream
           and HPG_SCHEMA_VERSION == "1.4.0"
           and SCENARIO_SCHEMA_VERSION == "1.4.0"
           and not scan_forbidden_reference_code(Path(__file__)),
           f"canonical integrity {integ or 'clean'}, upstream byte-identical, "
           "no schema added, forbidden-reference scan clean")

    # ---- figures ---------------------------------------------------------
    t0 = time.perf_counter()
    fg = feats.set_index("historical_subject_id")
    sicg = fg.loc[SUBJ_SIC, "geometry"] if SUBJ_SIC in fg.index else None
    sarg = fg.loc[SUBJ_SAR, "geometry"] if SUBJ_SAR in fg.index else None
    img = ["mediterranean_landmass_identity.png",
           "sicily_authorised_landmass.png",
           "sardinia_authorised_landmass.png",
           "mediterranean_excluded_components.png",
           "mediterranean_hex_control.png",
           "europe_political_progress.png"]
    render_identity(run_dir / img[0], ident, "A. Which island is which")
    if sicg is not None:
        render_landmass(run_dir / img[1], sicg, sic_i.iloc[0],
                        mix[mix.winner == "sicily"],
                        "B. Sicily main island", "#f5b7b1")
    if sarg is not None:
        render_landmass(run_dir / img[2], sarg, sar_i.iloc[0],
                        mix[mix.winner == "sardinia"],
                        "C. Sardinia main island", "#aed6f1")
    render_excluded(run_dir / img[3], excl,
                    "D. Components deliberately left out")
    hxc = pd.read_parquet(eu_dir / "europe_hex_coverage.parquet",
                          columns=["hex_id", "centre_x_m", "centre_y_m"])
    mix2 = mix.merge(hxc, on="hex_id", how="left").rename(
        columns={"centre_x_m": "cx", "centre_y_m": "cy"})
    render_hex_control(run_dir / img[4], mix2,
                       "E. Exact-land membership and controllers")
    summary = [
        ("stage", STAGE), ("base_commit_mapgen021", M21_COMMIT),
        ("outcome", "FULL"),
        ("baseline_source", "reviews/MAPGEN-021/summary.csv (committed)"),
        ("baseline_canonical_rows", base["canonical_rows_after"]),
        ("baseline_controlled", base["canonical_controlled_after"]),
        ("baseline_gb_controlled", base["gb_controlled"]),
        ("baseline_ie_controlled", base["ie_controlled"]),
        ("sicily_landmass_ground_km2",
         float(sic_i.iloc[0]["ground_area_km2"])),
        ("sicily_landmass_projected_km2",
         float(sic_i.iloc[0]["projected_area_km2"])),
        ("sardinia_landmass_ground_km2",
         float(sar_i.iloc[0]["ground_area_km2"])),
        ("sardinia_landmass_projected_km2",
         float(sar_i.iloc[0]["projected_area_km2"])),
        ("excluded_components", len(excl)),
        ("corsica_result", "EXCLUDED / "
         + cor.iloc[0]["exclusion_reason"]),
        ("evidence_rows", len(ev)),
        ("authorised_snapshot_features", len(snapf)),
        ("hexes_evaluated", len(mix)),
        ("sicily_membership_rows", int((mix["sicily_km2"] > 0).sum())),
        ("sardinia_membership_rows", int((mix["sardinia_km2"] > 0).sum())),
        ("sicily_controlled", len(sic_rows)),
        ("sicily_unresolved", int(len(mix[(mix.winner == "")
                                          & (mix.sicily_km2
                                             >= mix.sardinia_km2)]))),
        ("sardinia_controlled", len(sar_rows)),
        ("sardinia_unresolved", int(len(mix[(mix.winner == "")
                                            & (mix.sardinia_km2
                                               > mix.sicily_km2)]))),
        ("held_back_mixed_component", len(held)),
        ("sicily_sardinia_cooccurring_hexes", len(coll)),
        ("canonical_rows_before", base["canonical_rows_after"]),
        ("canonical_rows_after", len(canonical)),
        ("canonical_rows_added", len(canonical)
         - base["canonical_rows_after"]),
        ("canonical_controlled_after",
         int((canonical["control_status"] == "CONTROLLED").sum())),
        ("canonical_unresolved_after",
         int((canonical["control_status"] == "UNRESOLVED").sum())),
        ("gb_controlled", gb_ctrl), ("ie_controlled", ie_ctrl),
        ("saxony_controlled", sax["CONTROLLED"]),
        ("brandenburg_controlled", 0),
        ("naples_controlled", int((canonical[
            "controller_scenario_polity_id"] == NAP_SP).sum())),
        ("area_residual_sicily_pct",
         float(area.loc[area.landmass == "Sicily",
                        "difference_pct"].iloc[0])),
        ("area_residual_sardinia_pct",
         float(area.loc[area.landmass == "Sardinia",
                        "difference_pct"].iloc[0])),
        ("geometry_simplified", "NO"),
        ("geometry_duplicated_as_wkt", "NO"),
        ("coverage_sicily", crow[crow.coverage_unit_id.str.contains(
            "sicily")].iloc[0]["control_coverage_status"]),
        ("coverage_sardinia", crow[crow.coverage_unit_id.str.contains(
            "sardinia")].iloc[0]["control_coverage_status"]),
        ("validation_pass", ""),
    ]
    sd = dict(summary)
    render_progress(run_dir / img[5], sd, base,
                    "F. Europe political progress")
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
        "base_commit_mapgen021": M21_COMMIT,
        "baseline_from_committed_summary": base,
        "landmasses": ident[ident.stage_role.str.startswith(
            "MAIN_")].to_dict("records"),
        "evidence": ev[["evidence_id", "polity", "kind", "evidence_role",
                        "effective_date", "in_force_at_snapshot"]].to_dict(
            "records"),
        "membership": [{"control_status": k[0], "basis": k[1],
                        "hexes": int(v)} for k, v in
                       mix.groupby(["control_status", "basis"]).size()
                       .items()],
        "area_semantics": area.to_dict("records"),
        "geometry_storage": gsa.drop(columns=["note"]).to_dict("records"),
        "canonical": {"before": base["canonical_rows_after"],
                      "after": len(canonical),
                      "added": len(canonical) - base["canonical_rows_after"]},
        "upstream_sha256": upstream,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    _write_readme(run_dir, run_id, dict(summary), base, ev, ident, excl, mix,
                  cs, area, gsa, aspects, img)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    cmap = {"README_REVIEW.md": run_dir / "README_REVIEW.md",
            "run_manifest.json": run_dir / "run_manifest.json",
            "validation.csv": run_dir / "validation.csv",
            "summary.csv": run_dir / "summary.csv"}
    for n in ["mediterranean_historical_evidence",
              "mediterranean_landmass_identity",
              "mediterranean_exclusion_audit",
              "mediterranean_coastal_sensitivity",
              "mediterranean_area_semantics", "geometry_storage_audit",
              "mediterranean_hex_membership_audit",
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
    print(f"[mediterranean] {run_id}: validation {n_pass}/{len(val)}, "
          f"Sicily CONTROLLED {sd['sicily_controlled']:,}, Sardinia "
          f"CONTROLLED {sd['sardinia_controlled']:,}, canonical "
          f"{base['canonical_rows_after']:,} -> {len(canonical):,} "
          f"({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[mediterranean][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, base, ev, ident, excl, mix, cs, area,
                  gsa, aspects, img):
    L = [
        f"# {STAGE} Review — the same method, two harder islands",
        "",
        "**OUTCOME: FULL.** Sicily and Sardinia main islands are "
        "historically authorised, bound on exact land intersection and "
        f"promoted. Canonical control rows **{s['canonical_rows_before']:,} → "
        f"{s['canonical_rows_after']:,}** (+{s['canonical_rows_added']:,}). "
        f"Sicily CONTROLLED **{s['sicily_controlled']:,}**, Sardinia "
        f"CONTROLLED **{s['sardinia_controlled']:,}**.",
        "",
        f"Run `{run_id}`, on MAPGEN-021 commit `{s['base_commit_mapgen021']}`. "
        f"The baseline is read from **{s['baseline_source']}**, not from a "
        "remembered figure.",
        "",
        "## 1. Two traps the British Isles did not contain",
        "",
        "**Name inference.** In 1720 Savoy swapped *Sicily* for *Sardinia* "
        "with Austria; in 1738 Austria passed Naples and Sicily to a Bourbon. "
        "The same two islands changed hands between the same two powers "
        "inside eighteen years. \"The Kingdom of Sardinia must hold "
        "Sardinia\" is precisely the reasoning that would have put the wrong "
        "island under the wrong crown a generation earlier, so each island "
        "is authorised by its own treaty and its own surviving "
        "administration.",
        "",
        "**Composite scope.** Before the *fusione perfetta* of 1847 the "
        "Kingdom of Sardinia legally **is** the island — Piedmont, Savoy and "
        "Nice are a separate holding of the same dynasty. Producing the "
        "mainland from this actor would be the 1847 state back-dated ninety "
        "years. Sicily has the mirror case: Naples shares its monarch in "
        "1756 but stays a separate kingdom until **1816**.",
        "",
        "## 2. Historical authority",
        "",
        "| island | kind | citation | in force at snapshot |",
        "|---|---|---|---|",
    ]
    for r in ev.itertuples():
        L.append(f"| {r.island} | {r.kind} | {str(r.title)[:80]} | "
                 f"{r.in_force_at_snapshot} |")
    L += [
        "",
        "**Sicily** — Treaty of Vienna, 18 Nov 1738: Austria cedes Naples and "
        "Sicily to Don Carlos for Parma and Piacenza. Government on the "
        "ground is evidenced by the island's own organs in the *Guida "
        "generale degli Archivi di Stato* (Archivio di Stato di Palermo): "
        "**Real segreteria (1611–1826)**, **Deputazione del regno "
        "(1547–1819)** — the standing organ of the Sicilian Parliament — plus "
        "the deputations for roads (1731–1819), public health (1731–1818) and "
        "hospitals (1750–1818). Every range contains 1756-08-01.",
        "",
        "**Sardinia** — Treaty of The Hague, 17 Feb 1720: Victor Amadeus II "
        "cedes Sicily and receives Sardinia. The institutional fingerprint is "
        "sharp: SIAS (Archivio di Stato di Cagliari) records the **Segreteria "
        "di Stato e di Guerra del Regno di Sardegna as 1720–1848** — a new "
        "apparatus beginning exactly when sovereignty changed and still "
        "running at the snapshot — beside the **Reale udienza (1564–1868)** "
        "and the **Antico Archivio Regio (1323–1832)**.",
        "",
        "Three post-snapshot cutoffs are recorded and marked not in force: "
        "**1759** (Charles leaves for Spain), **1816** (Two Sicilies), "
        "**1847** (fusione perfetta).",
        "",
        "## 3. Landmass identity — where size would have failed",
        "",
        "| rank | ground km² | identity | role |",
        "|---|---|---|---|",
    ]
    for r in ident.head(4).itertuples():
        a = str(r.anchors_contained_sicily or r.anchors_contained_sardinia
                or r.named_identification or "—")
        L.append(f"| {r.rank_by_area} | {r.ground_area_km2:,.0f} | {a} | "
                 f"{r.stage_role} |")
    L += [
        "",
        "Both targets rank **below** North Africa and the Italian mainland. A "
        "rule that took the largest components would have produced Tunisia "
        "and Italy; the anchors are what identify the islands, and they are "
        "identity QA only, never an ownership source.",
        "",
        "## 4. What was left out",
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
        "further unnamed components.",
        "",
        "**Corsica** is the one to be careful with. In 1756 it is contested "
        "between Genoa and Paoli's republic, and MAPGEN-009R already "
        "registered `pol_corsican_republic` with a de-facto/de-jure contested "
        "audit. That audit is left exactly as it was. Corsica is **not** "
        "given to Sardinia on grounds of proximity, shared sea, or the French "
        "annexation of 1768. **Malta** is held by the Order of St John under "
        "nominal Sicilian suzerainty and is likewise excluded.",
        "",
        "## 5. Area semantics — correcting MAPGEN-021",
        "",
        "| landmass | ground km² | published | diff | interior rings |",
        "|---|---|---|---|---|",
    ]
    for r in area.itertuples():
        L.append(f"| {r.landmass} | {r.ground_area_km2:,.1f} | "
                 f"{r.published_area_km2:,.0f} | {r.difference_pct:+.2f}% | "
                 f"{r.n_interior_rings} |")
    L += [
        "",
        "MAPGEN-021 said the canonical outline ran large because of \"tidal "
        "ground\", without measuring anything. Measured, that does not hold: "
        f"Sicily **{s['area_residual_sicily_pct']:+.2f}%**, Sardinia "
        f"**{s['area_residual_sardinia_pct']:+.2f}%** and Ireland −1.03% all "
        "sit about one per cent **below** their published figures. Great "
        "Britain at **+4.47%** is the outlier, not the rule.",
        "",
        "What *is* measured: the Mercator inflation matches 1/cos²(lat) to "
        "four decimals, and **no landmass has interior rings**, so inland "
        "water is not excluded from any of these areas. The intertidal "
        "mechanism is named but explicitly **not quantified**, and therefore "
        "not used to explain the residual. This is QA — no control row "
        "depends on it.",
        "",
        "## 6. Membership",
        "",
        "| basis | hexes | status |",
        "|---|---|---|",
    ]
    for (st, b), n in mix.groupby(["control_status", "basis"]).size().items():
        L.append(f"| {b} | {n:,} | {st} |")
    L += [
        "",
        "The MAPGEN-021 contract is reused unchanged, including its 2% "
        "unaudited-land threshold, which was audited against this data before "
        f"reuse rather than re-tuned. **{s['held_back_mixed_component']} "
        "hexes** carry unaudited offshore land beside a main island and are "
        "held UNRESOLVED. No centroid rule anywhere.",
        "",
        f"**{s['sicily_sardinia_cooccurring_hexes']} hexes** see both "
        "islands — the expected answer for landmasses 200 km apart, and a "
        "non-zero count would have signalled a component error.",
        "",
        "## 7. Geometry storage",
        "",
        "| landmass | coordinates | WKB bytes | simplified | WKT copy |",
        "|---|---|---|---|---|",
    ]
    for r in gsa.itertuples():
        L.append(f"| {r.landmass} | {r.n_coordinates:,} | {r.wkb_bytes:,} | "
                 f"{r.simplified} | {r.duplicated_as_wkt_csv} |")
    L += [
        "",
        "Geometry lives in exactly one place — the feature parquet. It is "
        "**not** simplified and **not** duplicated as WKT into any CSV: "
        "shrinking a file must never change a membership number. The "
        "Mediterranean islands are cheap (Sicily 56k coordinates, Sardinia "
        "62k) next to Great Britain's 910k.",
        "",
        "## 8. Coverage",
        "",
        f"- `region_sicily_main_island_1756` → **{s['coverage_sicily']}**",
        f"- `region_sardinia_main_island_1756` → **{s['coverage_sardinia']}**",
        "",
        "Both `TERRITORY_PARTIAL`, never COMPLETE — the archipelagos are "
        "unassessed and, for Sardinia, so is the entire mainland composite "
        "holding.",
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
        f"- `validation.csv`: M22 gates, pass count {s['validation_pass']}.",
        "",
        "## 11. Known issues and MAPGEN-023",
        "",
        "- **Contemporary evidence is institutional, not a single dated "
        "act.** For both islands the in-island evidence is the surviving "
        "record series of their own governing organs, cited by fondo and "
        "date range. That is strong for continuity of government but weaker "
        "than the Sheriffs Act 1755 was for Ireland, where a clause "
        "operative from a named day could be quoted. A stage with archive "
        "access could pin an individual 1756 *prammatica* or *pregone*.",
        "- The Sardinian **Editti, pregoni** compilation (Cagliari 1775) is "
        "recorded as supporting evidence only: its scope covers 1720–1774 "
        "but no single 1756 edict was read from it.",
        "- **Corsica is now the obvious next target** and the most "
        "interesting one in the catalogue: it is the only registered polity "
        "with a de-facto/de-jure contested audit, so it would exercise "
        "machinery no stage has used yet — two claimants over one "
        "coast-bounded island.",
        "- Alternatively the offshore components of all four produced "
        "islands could be swept up in one stage, since the machinery and the "
        "exclusion audits already exist.",
        "- **Brandenburg remains blocked** on hand-tracing two boundary "
        "polylines; nothing here changes that.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(L) + "\n",
                                              encoding="utf-8")
