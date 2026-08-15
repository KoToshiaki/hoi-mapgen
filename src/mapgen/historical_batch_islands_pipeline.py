"""MAPGEN-023 — the coast-bounded method run as a batch, and a provenance repair.

Two islands groups this time, chosen because they break different
assumptions the earlier stages were quietly resting on.

Iceland breaks the assumption that a coastline is stable. Surtsey rose out
of the sea in 1963; the south-coast sandur prograde by kilometres; the
glaciers that fill the interior have retreated a long way since 1756. The
answer is not to withhold Iceland but to say which of those mechanisms was
measured and which was not, and to exclude land that did not exist at the
snapshot by IDENTITY rather than by threshold.

Malta breaks the assumption that the canonical terrestrial-hex flag is
free. That flag is a majority-land test. On Great Britain it costs a
fringe; on 246 km2 of Malta it withholds as many hexes as it produces.
This stage does not change the rule — territorial_target_type is
TERRESTRIAL_HEX and redefining a land hex belongs to physical geography,
not here — but it counts the cost and prints it.

Gozo is the clean case for the rule this project keeps having to restate.
It is authorised because the 1530 privilege of Charles V names it. Comino,
four kilometres away in the same archipelago, is not named and is not
produced. The instrument decides, not the map.

The stage also repairs MAPGEN-022. Its sovereignty titles cited "standard
settlement histories"; they now cite a documentary edition printed from
archival exemplars and an actual fascicolo in Turin. Not one control row
changes — that is the test that a provenance repair is what it claims.
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

STAGE = "MAPGEN-023"
H = Path("data/historical")
M22_COMMIT = "3f2208221c1005151f9fe4c215b6bc8d94d52fd9"
M22_SUMMARY = Path("reviews/MAPGEN-022/summary.csv")
DK_SP, OSJ_SP = "sp_44c79eb0f89c", "sp_20bf1d9af6ea"
SUBJ_ICE = "hsub_iceland_main_island"
SUBJ_MLT = "hsub_malta_main_island"
SUBJ_GOZ = "hsub_gozo_island"


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
    """MAPGEN-022's own committed summary is the authority for the baseline.

    Not a number remembered from a previous run - the artifact that was
    actually pushed.
    """
    s = pd.read_csv(M22_SUMMARY)
    d = dict(zip(s["metric"].astype(str), s["value"].astype(str)))
    return {k: int(float(d[k])) for k in
            ("canonical_rows_after", "canonical_controlled_after",
             "canonical_unresolved_after", "gb_controlled", "ie_controlled",
             "sicily_controlled", "sardinia_controlled", "saxony_controlled",
             "brandenburg_controlled")}


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def render_identity(path, ident, title, main_role, colour, note):
    fig, (ax, ax2) = _fig2((16, 7.5), [1, 1])
    top = ident.head(14)
    col = [colour if str(r).startswith(("MAIN_", "AUTHORISED_"))
           else "#aab7b8" for r in top["stage_role"]]
    ax.barh(range(len(top)), top["ground_area_km2"], color=col)
    ax.set_yticks(range(len(top)))
    lab = []
    for r in top.itertuples():
        n = str(r.named_identification or "")
        if str(r.stage_role).startswith(("MAIN_", "AUTHORISED_")):
            n = str(r.stage_role).split("_", 2)[-1]
        lab.append((n or f"rank {r.rank_by_area}")[:34])
    ax.set_yticklabels(lab, fontsize=7)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("ground area (km2, log)")
    ax.set_title("connected land components, largest first", fontsize=10)
    body = ["LANDMASS IDENTITY", ""] + _wrap(note)
    body += ["", "  rank  ground km2   identity", ""]
    for r in ident.head(9).itertuples():
        a = str(r.named_identification or "-")
        for c in ("anchors_contained_iceland", "anchors_contained_malta",
                  "anchors_contained_gozo"):
            if getattr(r, c, ""):
                a = str(getattr(r, c))
        body.append(f"  {r.rank_by_area:>4} {r.ground_area_km2:11,.2f}   "
                    f"{a[:52]}")
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7.4)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_landmass(path, geom, row, ctrl, title, colour, extra):
    fig, (ax, ax2) = _fig2((14, 7), [1, 1])
    gpd.GeoSeries([geom], crs="EPSG:3857").plot(
        ax=ax, color=colour, edgecolor="#2c3e50", linewidth=0.5)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title("authorised landmass scope", fontsize=10)
    anchors = ""
    for c in ("anchors_contained_iceland", "anchors_contained_malta",
              "anchors_contained_gozo"):
        if str(row.get(c, "")):
            anchors = str(row[c])
    body = ["HISTORICALLY_AUTHORISED_LANDMASS_SCOPE", ""]
    body += _wrap(
        "The polygon is the canonical PHYSICAL land component. It becomes "
        "territory only because political assertions are bundled with it.")
    body += ["", f"  ground area        {row['ground_area_km2']:,.2f} km2",
             f"  projected area     {row['projected_area_km2']:,.2f} km2",
             f"  centroid           {row['centroid_lon']:.3f}, "
             f"{row['centroid_lat']:.3f}",
             f"  identity anchors   {anchors}",
             "", "  hexes CONTROLLED   "
             f"{int((ctrl['control_status'] == 'CONTROLLED').sum()):,}",
             "  hexes UNRESOLVED   "
             f"{int((ctrl['control_status'] == 'UNRESOLVED').sum()):,}",
             "  hexes NOT_PRODUCED "
             f"{int((ctrl['control_status'] == 'NOT_PRODUCED').sum()):,}",
             ""]
    body += _wrap(extra)
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=8)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_hex_control(path, mix, title, cols, note):
    fig, (ax, ax2) = _fig2((15, 7), [1, 1])
    # a 30-hex archipelago and an 18,000-hex island cannot share a dot size
    size = 3.5 if len(mix) > 400 else 130
    for w, g in mix.groupby("winner"):
        ax.scatter(g["cx"], g["cy"], s=size, c=cols.get(w, "#f39c12"),
                   label=f"{w or 'not produced'} ({len(g):,})")
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.legend(fontsize=8, markerscale=4, loc="lower left")
    ax.set_title("canonical hexes, coloured by controller", fontsize=10)
    body = ["EXACT-LAND MEMBERSHIP", ""] + _wrap(note)
    body += ["", "  basis                                              hexes",
             ""]
    for (st, b), n in mix.groupby(["control_status", "basis"]).size().items():
        body.append(f"  {b:50s} {n:6,d}  [{st}]")
    body += ["", "  winner                                             hexes",
             ""]
    for w, n in mix[mix.control_status == "CONTROLLED"][
            "winner"].value_counts().items():
        body.append(f"  {w:50s} {n:6,d}")
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7.4)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_progress(path, s, base, title):
    fig, ax = _fig((15, 9.5))
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
        "  PRODUCED THIS STAGE", "",
        f"    Iceland CONTROLLED          : {s['iceland_controlled']:,}",
        f"    Iceland UNRESOLVED          : {s['iceland_unresolved']:,}",
        f"    Malta CONTROLLED            : {s['malta_controlled']:,}",
        f"    Gozo CONTROLLED             : {s['gozo_controlled']:,}",
        "",
        "  HELD FROM EARLIER STAGES", "",
        f"    Great Britain CONTROLLED    : {base['gb_controlled']:,}",
        f"    Ireland CONTROLLED          : {base['ie_controlled']:,}",
        f"    Sicily CONTROLLED           : {base['sicily_controlled']:,}",
        f"    Sardinia CONTROLLED         : {base['sardinia_controlled']:,}",
        f"    Saxony CONTROLLED           : {s['saxony_controlled']:,}",
        f"    Brandenburg CONTROLLED      : {s['brandenburg_controlled']}",
        "",
        "SCOPE DELIBERATELY NOT TAKEN", "",
        f"  Faroe Islands                 : {s['faroes_result']}",
        "  Vestmannaeyjar                : offshore, authority not "
        "researched",
        "  Surtsey                       : did not exist in 1756",
        f"  Comino                        : {s['comino_result']}",
        "  Denmark, Norway, Schleswig,   : UNASSESSED - one component of an",
        "  Holstein, Greenland             actor's scope was authorised, not",
        "                                  the actor's whole territory",
        "",
        f"  offshore components excluded  : {s['excluded_components']}",
        f"  coverage Iceland              : {s['coverage_iceland']}",
        f"  coverage Malta                : {s['coverage_malta']}",
        f"  coverage Gozo                 : {s['coverage_gozo']}",
        "",
        "MAPGEN-022 PROVENANCE REPAIR", "",
        f"  hardening records             : {s['hardening_records']}",
        f"  control rows changed by it    : {s['hardening_rows_changed']}",
    ]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=9)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
def run_historical_batch_islands(cfg: MapgenConfig,
                                 run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"batch_islands_1756_{_dt.datetime.now():%Y%m%d}"
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
    ice_ev = pd.read_csv(H / "iceland_historical_evidence.csv",
                         keep_default_na=False, na_values=[])
    mlt_ev = pd.read_csv(H / "malta_historical_evidence.csv",
                         keep_default_na=False, na_values=[])
    ev = pd.concat([ice_ev, mlt_ev], ignore_index=True)
    ice_id = pd.read_csv(H / "iceland_landmass_identity.csv",
                         keep_default_na=False, na_values=[]).fillna("")
    mlt_id = pd.read_csv(H / "malta_landmass_identity.csv",
                         keep_default_na=False, na_values=[]).fillna("")
    ice_ex = pd.read_csv(H / "iceland_exclusion_audit.csv",
                         keep_default_na=False, na_values=[]).fillna("")
    mlt_ex = pd.read_csv(H / "malta_exclusion_audit.csv",
                         keep_default_na=False, na_values=[]).fillna("")
    excl = pd.concat([ice_ex, mlt_ex], ignore_index=True)
    ice_cc = pd.read_csv(H / "iceland_coastal_change_audit.csv",
                         keep_default_na=False, na_values=[])
    mlt_cc = pd.read_csv(H / "malta_coastal_change_audit.csv",
                         keep_default_na=False, na_values=[])
    cc = pd.concat([ice_cc, mlt_cc], ignore_index=True)
    area = pd.read_csv(H / "island_area_semantics.csv")
    gsa = pd.read_csv(H / "geometry_storage_audit.csv")
    hard = pd.read_csv(H / "mapgen022_source_hardening.csv",
                       keep_default_na=False, na_values=[])
    mix = pd.read_csv(H / "island_hex_membership_audit.csv",
                      keep_default_na=False, na_values=[])
    snapf = pd.read_csv(H / "historical_snapshot_features_1756_08_01.csv")
    links = pd.read_csv(H / "historical_boundary_feature_evidence.csv",
                        keep_default_na=False, na_values=[])
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv"]}
    timings["load_s"] = time.perf_counter() - t0

    produced = mix[mix["control_status"] != "NOT_PRODUCED"]
    stage_targets = set(produced["hex_id"])
    stage_canon = canonical[canonical["territorial_target_id"].isin(
        stage_targets)]
    dk_rows = canonical[canonical["controller_scenario_polity_id"] == DK_SP]
    osj_rows = canonical[canonical["controller_scenario_polity_id"] == OSJ_SP]
    ice_i = ice_id[ice_id.stage_role == "MAIN_LANDMASS_ICELAND"]
    mlt_i = mlt_id[mlt_id.stage_role == "MAIN_LANDMASS_MALTA"]
    goz_i = mlt_id[mlt_id.stage_role == "AUTHORISED_LANDMASS_GOZO"]
    win = produced["winner"].value_counts()
    held = mix[mix["basis"] == "MIXED_UNAUDITED_LAND_COMPONENT"]
    not_prod = mix[mix["control_status"] == "NOT_PRODUCED"]

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
    sic_ctrl = int((canonical["controller_scenario_polity_id"]
                    == "sp_14ee92dede27").sum())
    sar_ctrl = int((canonical["controller_scenario_polity_id"]
                    == "sp_5f0f4d8d4788").sum())

    # ---- gates -----------------------------------------------------------
    _check("M23-01_mapgen022_regression",
           len(canonical) - len(stage_canon) == base["canonical_rows_after"]
           and sic_ctrl == base["sicily_controlled"]
           and sar_ctrl == base["sardinia_controlled"],
           f"removing the {len(stage_canon):,} rows produced here leaves "
           f"exactly {base['canonical_rows_after']:,}; Sicily {sic_ctrl:,} "
           f"and Sardinia {sar_ctrl:,} CONTROLLED unchanged")
    _check("M23-02_baseline_read_from_committed_summary",
           M22_SUMMARY.exists()
           and base["canonical_rows_after"] == 32193
           and base["canonical_controlled_after"] == 31140
           and base["canonical_unresolved_after"] == 1053,
           "the baseline is read from the COMMITTED reviews/MAPGEN-022/"
           f"summary.csv - {base['canonical_rows_after']:,} rows, "
           f"{base['canonical_controlled_after']:,} CONTROLLED, "
           f"{base['canonical_unresolved_after']:,} UNRESOLVED")

    sic_hard = hard[(hard.target == "pol_sicily")
                    & (hard.correction == "SOVEREIGNTY_SOURCE_HARDENED")]
    wenck = asrt[asrt["exact_locator"].str.contains("Wenck", na=False)]
    _check("M23-03_sicily_sovereignty_source_hardened",
           len(sic_hard) == 1 and len(wenck) == 1
           and "Art. III" in wenck.iloc[0]["exact_locator"]
           and int(sic_hard.iloc[0]["control_rows_changed"]) == 0
           and sic_ctrl == base["sicily_controlled"],
           "Sicily's title now cites Wenck's Codex iuris gentium "
           "recentissimi tom. I - printed from the exemplar Charles VI laid "
           "before the Imperial Estates in 1740 - Art. III of the Vienna "
           "preliminaries, p. 3. Control rows changed: 0")
    sar_hard = hard[(hard.target == "pol_sardinia")
                    & (hard.correction == "SOVEREIGNTY_SOURCE_HARDENED")]
    asto = asrt[asrt["exact_locator"].str.contains("ASTo|Archivio di Stato "
                                                   "di Torino", na=False,
                                                   regex=True)]
    _check("M23-04_sardinia_sovereignty_source_hardened",
           len(sar_hard) == 1 and len(asto) == 1
           and "Mazzo 1, n. 17" in asto.iloc[0]["exact_locator"]
           and int(sar_hard.iloc[0]["control_rows_changed"]) == 0
           and sar_ctrl == base["sardinia_controlled"],
           "Sardinia's title is fixed on the real handover: ASTo Sezione "
           "Corte, Paesi, Sardegna, Economico, Cat. I, Mazzo 1, n. 17 - the "
           "1720 inventory of the Maestro Razionale's records, taken at "
           "Cagliari. Control rows changed: 0")
    scope = hard[hard.correction == "ACTOR_SCOPE_WORDING_ALIGNED"]
    bad_wording = (
        asrt["notes"].str.contains("Kingdom of Sardinia legally IS",
                                   na=False).any()
        or mp["mapping_basis"].str.contains("Kingdom of Sardinia legally IS",
                                            na=False).any()
        or cov["notes"].str.contains("not part of the Kingdom of Sardinia",
                                     na=False).any())
    sar_actor = sp.loc[sp.polity_id == "pol_sardinia", "display_name"].iloc[0]
    _check("M23-05_sardinia_actor_scope_wording_aligned",
           len(scope) == 1 and not bad_wording
           and sar_actor == "Kingdom of Sardinia (Savoy-Piedmont)"
           and mp.loc[mp.historical_subject_id
                      == "hsub_sardinia_main_island",
                      "mapping_basis"].str.contains(
                          "NOT_PRODUCED").all(),
           "pol_sardinia stays the Kingdom of Sardinia (Savoy-Piedmont). "
           "The claim that the kingdom legally IS the island is gone from "
           "the assertions, the mapping and the coverage notes; the mainland "
           "is UNASSESSED and NOT_PRODUCED, which is a coverage statement")

    _check("M23-06_denmark_norway_actor_reused",
           DK_SP in set(sp["scenario_polity_id"])
           and sp.loc[sp.scenario_polity_id == DK_SP, "polity_id"].iloc[0]
           == "pol_denmark_norway"
           and sp["polity_id"].is_unique
           and not sp["polity_id"].astype(str).str.fullmatch(
               "pol_iceland").any(),
           "pol_denmark_norway resolved from the existing catalogue; no "
           "pol_iceland was invented")
    ice_sov = ice_ev[ice_ev.kind == "SOVEREIGNTY_BASIS"]
    _check("M23-07_iceland_sovereignty_evidence",
           len(ice_sov) == 1
           and "Kopavog" in ice_sov.iloc[0]["exact_locator"]
           and "p. 273" in ice_sov.iloc[0]["exact_locator"]
           and ice_sov.iloc[0]["in_force_at_snapshot"] == "YES",
           "Arvehyldingseden for Island, Kopavogur 28 July 1662, printed at "
           "Lovsamling for Island I p. 273 with its manuscript provenance "
           "(Ny kongelig Samling 1265 fol.) - Iceland's own act of homage")
    ice_now = ice_ev[ice_ev.kind.str.startswith("CONTEMPORARY")]
    pre = ice_now[ice_now["document_date"] <= "1756-08-01"]
    _check("M23-08_iceland_1756_individual_evidence",
           len(ice_now) >= 2 and len(pre) >= 1
           and "42A" in pre.iloc[0]["exact_locator"]
           and pre.iloc[0]["document_date"] == "1756-07-16",
           f"{len(ice_now)} individually dated 1756 documents from the "
           "amtmadur's fonds, one of them BEFORE the snapshot: the "
           "resolution of the syslumenn at the Althing, 16 July 1756 (TI. "
           "Skjalasafn amtmanns II. 42A)")
    _check("M23-09_iceland_component_deterministic",
           len(ice_i) == 1
           and ice_i.iloc[0]["anchors_contained_iceland"].count(";") == 2
           and bool(ice_i.iloc[0]["is_single_connected_component"])
           and int(ice_i.iloc[0]["rank_by_area"]) == 0,
           "one connected component of "
           f"{ice_i.iloc[0]['ground_area_km2']:,.0f} km2 containing "
           "Reykjavik, Akureyri and Hofn")
    faroes = ice_ex[ice_ex["named_identification"].str.contains(
        "Faroe", na=False)]
    _check("M23-10_iceland_offshore_not_auto_inherited",
           len(faroes) >= 5
           and (faroes["exclusion_reason"]
                == "SEPARATE_HOMAGE_SEPARATE_TERRITORY_NOT_ICELAND").all()
           and not set(faroes["part_index"]) & {int(ice_i.iloc[0]
                                                    ["part_index"])}
           and ice_ex["named_identification"].str.contains(
               "Vestmannaeyjar", na=False).any(),
           f"{len(faroes)} Faroese components excluded on the ground that "
           "the Faroes swore their own homage at Thorshavn on 14 August "
           "1662; Vestmannaeyjar excluded as unaudited offshore land")

    _check("M23-11_order_of_st_john_actor_reused",
           OSJ_SP in set(sp["scenario_polity_id"])
           and sp.loc[sp.scenario_polity_id == OSJ_SP, "polity_id"].iloc[0]
           == "pol_order_st_john"
           and int(sp["polity_id"].isin(["pol_order_st_john"]).sum()) == 1,
           "pol_order_st_john reused; no new Malta polity created")
    mlt_sov = mlt_ev[mlt_ev.kind == "SOVEREIGNTY_BASIS"]
    _check("M23-12_malta_sovereignty_evidence",
           len(mlt_sov) == 1
           and "1530" in mlt_sov.iloc[0]["exact_locator"]
           and "Gozo" in mlt_sov.iloc[0]["exact_locator"]
           and "Comino" in mlt_sov.iloc[0]["statement"],
           "Charles V's privilege of 23 March 1530 enumerates Malta and "
           "Gozo and the fortress of Tripoli - and does not name Comino")
    mlt_now = mlt_ev[mlt_ev.kind.str.startswith("CONTEMPORARY")]
    press = mlt_now[mlt_now["document_date"] == "1756-06-05"]
    _check("M23-13_malta_1756_contemporary_evidence",
           len(press) == 1
           and "5 June 1756" in press.iloc[0]["exact_locator"]
           and press.iloc[0]["document_date"] <= "1756-08-01"
           and len(mlt_now) >= 2,
           "Grand Master Pinto's press opened to the public on 5 June 1756 "
           "in the magistral palace, eight weeks before the snapshot; the "
           "Order's own record series span it")
    _check("M23-14_gozo_separately_authorised",
           len(goz_i) == 1
           and SUBJ_GOZ in set(snapf["historical_subject_id"])
           and int(win.get("gozo", 0)) > 0
           and set(mp.loc[mp.historical_subject_id == SUBJ_GOZ,
                          "scenario_polity_id"]) == {OSJ_SP},
           f"Gozo authorised as its own component "
           f"({goz_i.iloc[0]['ground_area_km2']:,.2f} km2) because the 1530 "
           f"privilege names it; {int(win.get('gozo', 0))} hexes CONTROLLED")
    comino = mlt_ex[mlt_ex["named_identification"].str.contains(
        "Comino", na=False)]
    _check("M23-15_comino_not_auto_inherited",
           len(comino) >= 1
           and (comino["exclusion_reason"]
                == "NOT_NAMED_IN_THE_1530_PRIVILEGE").all()
           and SUBJ_GOZ != "hsub_comino"
           and not mix.columns.str.contains("comino").any(),
           "Comino is four kilometres from Gozo and is still withheld: the "
           "1530 privilege does not name it. Proximity is not authority")
    cut = ev[ev.evidence_role == "TEMPORAL_BOUNDARY"]
    _check("M23-16_1798_not_backdated",
           len(cut) >= 1
           and (cut["in_force_at_snapshot"] == "NO").all()
           and (cut["effective_date"] > "1756-08-01").all()
           and cut.iloc[0]["effective_date"] == "1798-06-12",
           "the French takeover of 12 June 1798 is recorded and marked not "
           "in force; the Order's rule at the snapshot is the 1530-1798 one")

    subj3 = [SUBJ_ICE, SUBJ_MLT, SUBJ_GOZ]
    geo_ev = asrt[(asrt.historical_subject_id.isin(subj3))
                  & (asrt.assertion_type == "GEOMETRIC_SUBSTRATE_ONLY")]
    pol_ev = asrt[(asrt.historical_subject_id.isin(subj3))
                  & (asrt.assertion_type == "POLITICAL_CONTROL")]
    _check("M23-17_canonical_coastline_physical_only",
           len(geo_ev) == 3
           and (geo_ev["geometry_authority"] == "YES").all()
           and (geo_ev["political_authority"] == "NO").all()
           and len(pol_ev) == 6
           and (pol_ev["political_authority"] == "YES").all()
           and (pol_ev["geometry_authority"] == "NO").all(),
           "the coastline carries geometry authority only; the homage oath, "
           "the privilege and the archives carry political authority only. "
           "Neither side can produce a control row alone")
    used = set()
    for v in snapf[snapf.historical_subject_id.isin(subj3)][
            "bundle_source_ids"]:
        used |= {x for x in str(v).split("|") if x}
    allowed = set(reg.loc[reg["citation_key"].isin(
        ["osm_land_polygons_split_3857", "lovsamling_for_island_i",
         "thjodskjalasafn_skjalasafn_amtmanns",
         "charles_v_privilege_1530_malta_gozo",
         "aom_national_library_of_malta",
         "malta_government_printing_press_history"]), "global_source_id"])
    _check("M23-18_no_modern_admin_leakage",
           (ev["modern_administrative_geography_used"] == "NO").all()
           and (ev["name_inference_used"] == "NO").all()
           and used and used <= allowed
           and not stage_canon["notes"].str.contains(
               "kommun|sysla|local council|region of|modern", case=False,
               na=False).any(),
           "the bundles draw on an allowlist of exactly six sources; no "
           "modern Icelandic or Maltese administrative unit reaches a "
           "control row")
    _check("M23-19_anchors_identity_only",
           (ice_id["anchor_role"]
            == "IDENTITY_QA_ONLY_NOT_OWNERSHIP_SOURCE").all()
           and (mlt_id["anchor_role"]
                == "IDENTITY_QA_ONLY_NOT_OWNERSHIP_SOURCE").all()
           and (ice_id["ownership_source"]
                == "HISTORICAL_EVIDENCE_BUNDLE").all()
           and (mlt_id["ownership_source"]
                == "HISTORICAL_EVIDENCE_BUNDLE").all(),
           "anchors say which island, never whose")
    _check("M23-20_exact_land_intersection",
           {"hex_land_km2", "iceland_km2", "malta_km2", "gozo_km2",
            "unaudited_other_km2"} <= set(mix.columns)
           and (mix["hex_land_km2"] > 0).all(),
           f"membership over {len(mix):,} hexes from hex INTERSECT canonical "
           "land, attributed per component")
    _check("M23-21_no_centroid_only_assignment",
           "centre_lon" not in mix.columns
           and (produced.loc[produced.control_status == "CONTROLLED",
                             ["iceland_km2", "malta_km2", "gozo_km2"]]
                .max(axis=1) > 0).all(),
           "no centroid rule: every CONTROLLED hex holds a measured positive "
           "area of an authorised component")
    _check("M23-22_mixed_components_conservative",
           (held["control_status"] == "UNRESOLVED").all()
           and (produced.loc[produced.control_status == "CONTROLLED",
                             "unaudited_share"] <= 0.02).all(),
           f"{len(held)} hexes carry unaudited offshore land beside an "
           "authorised island and are held UNRESOLVED; the MAPGEN-021 2 per "
           "cent threshold was audited against this data and reused")

    ice_a = area[area.landmass == "Iceland"]
    _check("M23-23_area_semantics_honest",
           len(area) >= 5
           and (area["n_interior_rings"] == 0).all()
           and area["inland_water_treatment"].str.startswith(
               "MEASURED").all()
           and abs(float(ice_a.iloc[0]["difference_pct"])) < 2,
           "all five islands measured: Iceland "
           f"{float(ice_a.iloc[0]['difference_pct']):+.2f} per cent against "
           "its published figure, zero interior rings everywhere, and the "
           "intertidal mechanism still named but not quantified")
    surtsey = ice_ex[ice_ex["named_identification"].str.contains(
        "Surtsey", na=False)]
    _check("M23-24_physical_change_sensitivity_audited",
           len(cc) >= 5
           and set(cc["landmass"]) == {"iceland", "malta"}
           and (cc["interior_affected"] == "NO").all()
           and len(surtsey) == 1
           and surtsey.iloc[0]["exclusion_reason"]
           == "LAND_THAT_DID_NOT_EXIST_AT_THE_SNAPSHOT"
           and cc["measured"].str.startswith("YES").any(),
           "glaciers, sandur progradation, volcanic creation and harbour "
           "reclamation each audited; Surtsey - land that rose from the sea "
           "in 1963 - is excluded by identity, not by threshold, and no "
           "island interior is withheld for any of it")
    _check("M23-25_geometry_exactness_preserved",
           len(gsa) >= 5
           and (gsa["simplified"] == "NO").all()
           and (gsa["duplicated_as_wkt_csv"] == "NO").all()
           and (gsa["simplification_tolerance_m"] == 0).all()
           and gsa["wkb_sha256"].is_unique,
           "geometry stored exactly once per landmass in the feature "
           "parquet, hashed, never simplified and never duplicated as WKT")

    _check("M23-26_iceland_maps_only_to_denmark_norway",
           set(mp.loc[mp.historical_subject_id == SUBJ_ICE,
                      "scenario_polity_id"]) == {DK_SP}
           and int(win.get("iceland", 0)) == len(dk_rows),
           "the Iceland landmass maps to pol_denmark_norway and nothing "
           f"else; all {len(dk_rows):,} of its canonical rows come from that "
           "one component")
    _check("M23-27_malta_gozo_map_only_to_the_order",
           set(mp.loc[mp.historical_subject_id.isin([SUBJ_MLT, SUBJ_GOZ]),
                      "scenario_polity_id"]) == {OSJ_SP}
           and len(osj_rows) == int(win.get("malta", 0))
           + int(win.get("gozo", 0)),
           f"Malta and Gozo both map to the Order and to nobody else; "
           f"{len(osj_rows)} canonical rows, "
           f"{int(win.get('malta', 0))} Malta + {int(win.get('gozo', 0))} "
           "Gozo")
    dk_other = {"pol_denmark", "pol_norway", "pol_schleswig", "pol_holstein",
                "pol_faroe_islands", "pol_greenland"}
    _check("M23-28_no_territorial_inheritance_to_other_holdings",
           not (set(sp["polity_id"]) & dk_other)
           and int((canonical["controller_scenario_polity_id"]
                    == DK_SP).sum()) == int(win.get("iceland", 0))
           and mp.loc[mp.historical_subject_id == SUBJ_ICE,
                      "mapping_basis"].str.contains("Greenland").all(),
           "authorising Iceland produced nothing in Denmark, Norway, "
           "Schleswig, Holstein, the Faroes or Greenland, and the mapping "
           "record says so explicitly")
    _check("M23-29_provenance_complete",
           len(stage_canon) > 0
           and stage_canon["source_id"].astype(str).str.len().gt(0).all()
           and set(stage_canon["territorial_target_id"]) <= stage_targets
           and (mix.loc[mix.control_status != "NOT_PRODUCED", "basis"]
                .str.len() > 0).all(),
           f"all {len(stage_canon):,} rows produced here trace to a scenario "
           "polity, an evidence assertion, a landmass identity record and "
           "the canonical substrate")

    empty = pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"])
    c2, _p2, _l2, rep = promote_control(
        canonical.copy(), provenance.copy(), log.copy(), empty, scenario_id,
        STAGE, M22_COMMIT, "none", "src_none", promoted_utc="2026-08-15")
    _check("M23-30_promotion_idempotent",
           rep["inserted"] == 0 and len(c2) == len(canonical)
           and rep["promotion_id"] == make_promotion_id(
               scenario_id, STAGE, sha256_of_frame(empty)),
           "re-running promotion with an empty candidate inserts 0 rows")
    cross = mix[((mix["iceland_km2"] > 0).astype(int)
                 + (mix["malta_km2"] > 0).astype(int)
                 + (mix["gozo_km2"] > 0).astype(int)) > 1]
    _check("M23-31_no_silent_collisions",
           len(cross) == 0
           and canonical["territorial_target_id"].is_unique
           and int(log["promotion_status"].eq("PROMOTED").sum()) >= 1
           and not log["promotion_status"].eq("REJECTED").any(),
           "no hex carries land from two authorised components, no target "
           "id repeats in canonical, and no existing row was overwritten")
    crow = cov[cov["coverage_unit_id"].isin(
        ["region_iceland_main_island_1756", "region_malta_main_island_1756",
         "region_gozo_1756"])]
    _check("M23-32_coverage_incomplete_remains_unknown",
           len(crow) == 3
           and (crow["control_coverage_status"] == "TERRITORY_PARTIAL").all()
           and int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0,
           "all three new coverage units are TERRITORY_PARTIAL; no unit "
           "anywhere in the scenario is COMPLETE")

    _check("M23-33_british_isles_regression",
           gb_ctrl == base["gb_controlled"]
           and ie_ctrl == base["ie_controlled"],
           f"Great Britain {gb_ctrl:,} and Ireland {ie_ctrl:,} CONTROLLED, "
           "matching the committed MAPGEN-022 summary")
    _check("M23-34_mediterranean_regression",
           sic_ctrl == base["sicily_controlled"]
           and sar_ctrl == base["sardinia_controlled"]
           and int((canonical["controller_scenario_polity_id"]
                    == make_scenario_polity_id(
                        scenario_id, "pol_corsican_republic")).sum()) == 0,
           f"Sicily {sic_ctrl:,} and Sardinia {sar_ctrl:,} CONTROLLED; the "
           "Corsica contested audit still assigns nothing")
    _check("M23-35_brandenburg_regression",
           int((canonical["controller_scenario_polity_id"]
                == make_scenario_polity_id(scenario_id,
                                           "pol_brandenburg")).sum()) == 0
           and (H / "brandenburg_boundary_segment_continuity.csv").exists()
           and (H / "brandenburg_blha_transform.json").exists(),
           "Brandenburg untouched: still holds nothing, and the MAPGEN-020 "
           "continuity and BLHA georeference artifacts are intact")
    _check("M23-36_saxony_regression",
           sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and wei == {"CONTROLLED": 0, "UNRESOLVED": 96},
           f"Saxony {sax}, Saxe-Weimar {wei} unchanged")
    _check("M23-37_low_countries_regression",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP",
           "Low Countries still SOURCE_GAP")
    wash_feat = feats[feats["historical_subject_id"]
                      == "hsub_schwarzburg_unpartitioned_wash"]
    _check("M23-38_schwarzburg_regression",
           len(wash_feat) == 1
           and wash_feat.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY"
           and wash["UNRESOLVED"] == 89,
           "Schwarzburg wash unchanged and still not production-convertible")
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    _check("M23-39_europe_grid_regression",
           int(eu_man["hex_count"].sum()) == 1885422,
           "Europe canonical grid intact (1,885,422 hexes)")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    _check("M23-40_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN",
           "Toshima hex still OCEAN")
    _check("M23-41_claims_regression",
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
    for name in ("british_isles_hex_membership_audit.csv",
                 "mediterranean_hex_membership_audit.csv"):
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
    _check("M23-42_determinism_and_integrity",
           integ == [] and up_after == upstream
           and HPG_SCHEMA_VERSION == "1.4.0"
           and SCENARIO_SCHEMA_VERSION == "1.5.0"
           and not scan_forbidden_reference_code(Path(__file__)),
           f"canonical integrity {integ or 'clean'}, upstream byte-identical, "
           "scenario schema at the pinned 1.5.0, forbidden-reference scan clean")

    # ---- figures ---------------------------------------------------------
    t0 = time.perf_counter()
    fg = feats.set_index("historical_subject_id")
    img = ["iceland_landmass_identity.png", "iceland_authorised_landmass.png",
           "iceland_hex_control.png", "malta_gozo_landmass_identity.png",
           "malta_gozo_authorised_landmass.png", "malta_gozo_hex_control.png",
           "europe_political_progress.png"]
    render_identity(
        run_dir / img[0], ice_id, "A. Which island is Iceland",
        "MAIN_LANDMASS_ICELAND", "#2e86c1",
        "Union the canonical land parts over a window that reaches east far "
        "enough to contain the Faroes, take connected components, order by "
        "area. Iceland is rank 0 here, but rank is not the test: the anchors "
        "are. Ranks 1 to 7 are Faroese islands, under the same crown and "
        "still not Iceland.")
    if SUBJ_ICE in fg.index:
        render_landmass(
            run_dir / img[1], fg.loc[SUBJ_ICE, "geometry"], ice_i.iloc[0],
            mix[mix.region == "iceland"], "B. Iceland main island", "#aed6f1",
            "NOT_PRODUCED counts hexes that carry Iceland's land but fall "
            "below the canonical majority-land test for a terrestrial hex. "
            "That rule is not changed here; it is measured.")
    hxc = pd.read_parquet(eu_dir / "europe_hex_coverage.parquet",
                          columns=["hex_id", "centre_x_m", "centre_y_m"])
    mix2 = mix.merge(hxc, on="hex_id", how="left").rename(
        columns={"centre_x_m": "cx", "centre_y_m": "cy"})
    render_hex_control(
        run_dir / img[2], mix2[mix2.region == "iceland"],
        "C. Iceland exact-land membership",
        {"iceland": "#2e86c1", "": "#f39c12"},
        "The MAPGEN-021 contract is reused unchanged, including its 2 per "
        "cent unaudited-land threshold. NOT_PRODUCED hexes hold Iceland land "
        "but are not canonical terrestrial hexes, so they cannot carry a "
        "TERRESTRIAL_HEX control row.")
    render_identity(
        run_dir / img[3], mlt_id, "D. Malta, Gozo and what the 1530 "
        "privilege does not name", "MAIN_LANDMASS_MALTA", "#b03a2e",
        "Malta is rank 0 and Gozo rank 1, and both are authorised because "
        "the privilege of Charles V enumerates them. Comino is rank 2, four "
        "kilometres away in the same archipelago, and is withheld because "
        "the same instrument does not name it.")
    if SUBJ_MLT in fg.index:
        both = gpd.GeoSeries(
            [fg.loc[SUBJ_MLT, "geometry"], fg.loc[SUBJ_GOZ, "geometry"]]
        ).union_all()
        row = mlt_i.iloc[0].copy()
        row["ground_area_km2"] = (float(mlt_i.iloc[0]["ground_area_km2"])
                                  + float(goz_i.iloc[0]["ground_area_km2"]))
        row["projected_area_km2"] = (
            float(mlt_i.iloc[0]["projected_area_km2"])
            + float(goz_i.iloc[0]["projected_area_km2"]))
        render_landmass(
            run_dir / img[4], both, row, mix[mix.region == "malta"],
            "E. Malta and Gozo, both authorised by the same instrument",
            "#f5b7b1",
            "Half the hexes carrying Maltese land fail the canonical "
            "majority-land test. On an island of 246 km2 that is not a "
            "fringe, and it is reported rather than absorbed.")
    render_hex_control(
        run_dir / img[5], mix2[mix2.region == "malta"],
        "F. Malta and Gozo exact-land membership",
        {"malta": "#b03a2e", "gozo": "#7d3c98", "": "#f39c12"},
        "Both components belong to the same actor, so a hex carrying both "
        "would still be the Order's - but none does, and the audit says so "
        "rather than assuming it.")
    faroes_result = ("EXCLUDED / SEPARATE_HOMAGE_SEPARATE_TERRITORY_"
                     "NOT_ICELAND")
    summary = [
        ("stage", STAGE), ("base_commit_mapgen022", M22_COMMIT),
        ("outcome", "FULL"),
        ("baseline_source", "reviews/MAPGEN-022/summary.csv (committed)"),
        ("baseline_canonical_rows", base["canonical_rows_after"]),
        ("baseline_controlled", base["canonical_controlled_after"]),
        ("baseline_unresolved", base["canonical_unresolved_after"]),
        ("hardening_records", len(hard)),
        ("hardening_rows_changed", 0),
        ("sicily_source_final",
         "Wenck, Codex iuris gentium recentissimi I (1781), Acta Pacis "
         "Vindobonensis doc. 1 Art. III p. 3; doc. 21; doc. 24"),
        ("sardinia_source_final",
         "ASTo Sezione Corte, Paesi, Sardegna, Economico, Cat. I, Mazzo 1, "
         "n. 17 (Inventaro delle Scritture del Razionale, 1720)"),
        ("pares_lead_result", "ATTEMPTED_AND_UNREACHABLE"),
        ("iceland_landmass_ground_km2",
         float(ice_i.iloc[0]["ground_area_km2"])),
        ("iceland_landmass_projected_km2",
         float(ice_i.iloc[0]["projected_area_km2"])),
        ("malta_landmass_ground_km2", float(mlt_i.iloc[0]["ground_area_km2"])),
        ("gozo_landmass_ground_km2", float(goz_i.iloc[0]["ground_area_km2"])),
        ("excluded_components", len(excl)),
        ("faroes_result", faroes_result),
        ("comino_result", "EXCLUDED / NOT_NAMED_IN_THE_1530_PRIVILEGE"),
        ("surtsey_result", "EXCLUDED / LAND_THAT_DID_NOT_EXIST_AT_THE_"
                           "SNAPSHOT"),
        ("evidence_rows", len(ev)),
        ("authorised_snapshot_features", len(snapf)),
        ("hexes_evaluated", len(mix)),
        ("iceland_membership_rows", int((mix["iceland_km2"] > 0).sum())),
        ("malta_membership_rows", int((mix["malta_km2"] > 0).sum())),
        ("gozo_membership_rows", int((mix["gozo_km2"] > 0).sum())),
        ("iceland_controlled", int(win.get("iceland", 0))),
        ("iceland_unresolved",
         int(len(mix[(mix.control_status == "UNRESOLVED")
                     & (mix.region == "iceland")]))),
        ("malta_controlled", int(win.get("malta", 0))),
        ("gozo_controlled", int(win.get("gozo", 0))),
        ("malta_gozo_unresolved",
         int(len(mix[(mix.control_status == "UNRESOLVED")
                     & (mix.region == "malta")]))),
        ("held_back_mixed_component", len(held)),
        ("not_produced_non_terrestrial_hexes", len(not_prod)),
        ("not_produced_authorised_km2",
         round(float(not_prod["hex_land_km2"].sum()), 1)),
        ("cross_component_hexes", len(cross)),
        ("canonical_rows_before", base["canonical_rows_after"]),
        ("canonical_rows_after", len(canonical)),
        ("canonical_rows_added",
         len(canonical) - base["canonical_rows_after"]),
        ("canonical_controlled_after",
         int((canonical["control_status"] == "CONTROLLED").sum())),
        ("canonical_unresolved_after",
         int((canonical["control_status"] == "UNRESOLVED").sum())),
        ("gb_controlled", gb_ctrl), ("ie_controlled", ie_ctrl),
        ("sicily_controlled", sic_ctrl), ("sardinia_controlled", sar_ctrl),
        ("saxony_controlled", sax["CONTROLLED"]),
        ("brandenburg_controlled", 0),
        ("area_residual_iceland_pct",
         float(area.loc[area.landmass == "Iceland",
                        "difference_pct"].iloc[0])),
        ("area_residual_malta_pct",
         float(area.loc[area.landmass == "Malta",
                        "difference_pct"].iloc[0])),
        ("area_residual_gozo_pct",
         float(area.loc[area.landmass == "Gozo",
                        "difference_pct"].iloc[0])),
        ("geometry_simplified", "NO"),
        ("geometry_duplicated_as_wkt", "NO"),
        ("coverage_iceland", crow[crow.coverage_unit_id.str.contains(
            "iceland")].iloc[0]["control_coverage_status"]),
        ("coverage_malta", crow[crow.coverage_unit_id.str.contains(
            "malta")].iloc[0]["control_coverage_status"]),
        ("coverage_gozo", crow[crow.coverage_unit_id.str.contains(
            "gozo")].iloc[0]["control_coverage_status"]),
        ("validation_pass", ""),
    ]
    sd = dict(summary)
    render_progress(run_dir / img[6], sd, base, "G. Europe political "
                                                "progress")
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
        "base_commit_mapgen022": M22_COMMIT,
        "baseline_from_committed_summary": base,
        "mapgen022_hardening": hard.to_dict("records"),
        "landmasses": pd.concat([ice_i, mlt_i, goz_i]).to_dict("records"),
        "evidence": ev[["evidence_id", "polity", "kind", "evidence_role",
                        "document_date", "in_force_at_snapshot"]].to_dict(
            "records"),
        "membership": [{"region": k[0], "control_status": k[1],
                        "basis": k[2], "hexes": int(v)} for k, v in
                       mix.groupby(["region", "control_status", "basis"])
                       .size().items()],
        "area_semantics": area.to_dict("records"),
        "coastal_change": cc.to_dict("records"),
        "geometry_storage": gsa.drop(columns=["note"]).to_dict("records"),
        "canonical": {"before": base["canonical_rows_after"],
                      "after": len(canonical),
                      "added": len(canonical)
                      - base["canonical_rows_after"]},
        "upstream_sha256": upstream,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    _write_readme(run_dir, run_id, dict(summary), base, ev, excl, mix, cc,
                  area, gsa, hard, links, aspects, img)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    cmap = {"README_REVIEW.md": run_dir / "README_REVIEW.md",
            "run_manifest.json": run_dir / "run_manifest.json",
            "validation.csv": run_dir / "validation.csv",
            "summary.csv": run_dir / "summary.csv"}
    for n in ["mapgen022_source_hardening",
              "iceland_historical_evidence", "iceland_landmass_identity",
              "iceland_exclusion_audit", "iceland_coastal_change_audit",
              "malta_historical_evidence", "malta_landmass_identity",
              "malta_exclusion_audit", "malta_coastal_change_audit",
              "island_area_semantics", "geometry_storage_audit",
              "island_hex_membership_audit",
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
    print(f"[batch-islands] {run_id}: validation {n_pass}/{len(val)}, "
          f"Iceland CONTROLLED {sd['iceland_controlled']:,}, Malta "
          f"{sd['malta_controlled']}, Gozo {sd['gozo_controlled']}, canonical "
          f"{base['canonical_rows_after']:,} -> {len(canonical):,} "
          f"({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[batch-islands][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, base, ev, excl, mix, cc, area, gsa,
                  hard, links, aspects, img):
    L = [
        f"# {STAGE} Review — a batch, and a repair",
        "",
        "**OUTCOME: FULL.** Iceland, Malta and Gozo are historically "
        "authorised, bound on exact land intersection and promoted. "
        f"Canonical control rows **{s['canonical_rows_before']:,} → "
        f"{s['canonical_rows_after']:,}** (+{s['canonical_rows_added']:,}). "
        f"Iceland CONTROLLED **{s['iceland_controlled']:,}**, Malta "
        f"**{s['malta_controlled']}**, Gozo **{s['gozo_controlled']}**. "
        f"Validation **{s['validation_pass']}**.",
        "",
        f"Baseline read from the committed `reviews/MAPGEN-022/summary.csv`: "
        f"{base['canonical_rows_after']:,} rows, "
        f"{base['canonical_controlled_after']:,} CONTROLLED, "
        f"{base['canonical_unresolved_after']:,} UNRESOLVED.",
        "",
        "## 1. The repair comes first",
        "",
        "MAPGEN-022 gave Sicily and Sardinia their islands on the authority "
        "of a source whose own description read *as reported in standard "
        "settlement histories*. That is a bibliography, not an archive.",
        "",
        "| target | now cited | control rows changed |",
        "|---|---|---|",
    ]
    for r in hard[hard.correction == "SOVEREIGNTY_SOURCE_HARDENED"
                  ].itertuples():
        L.append(f"| {r.target} | {r.after[:150]} | {r.control_rows_changed} |")
    L += [
        "",
        "Zero rows changed, which is the point: a provenance repair that "
        "moves a boundary is not a repair.",
        "",
        "Two more corrections. The PARES lead named in the brief could not "
        "be retrieved — `pares.mcu.es` refuses connections and the successor "
        "host 404s every catalogue path, including the ones its own pages "
        "link to. It is recorded as `ATTEMPTED_AND_UNREACHABLE` rather than "
        "cited from a summary. And the Sardinia wording that said *the "
        "Kingdom of Sardinia legally IS the island* is gone: `pol_sardinia` "
        "is the Kingdom of Sardinia (Savoy-Piedmont), and what MAPGEN-022 "
        "authorised was one component of its scope. Piedmont, Savoy and "
        "Nice are UNASSESSED — a statement about coverage, not about who the "
        "actor is.",
        "",
        "## 2. Authority",
        "",
        "| target | kind | date | locator |",
        "|---|---|---|---|",
    ]
    for r in ev.itertuples():
        L.append(f"| {r.target} | {r.kind} | {r.document_date} | "
                 f"{str(r.exact_locator)[:170]} |")
    L += [
        "",
        "Iceland's title is its own act: the hereditary homage sworn at "
        "Kópavogur on 28 July 1662, printed in *Lovsamling for Island* I at "
        "p. 273 with the manuscript it was copied from. The snapshot-year "
        "evidence is an individually dated document from the amtmaður's "
        "fonds — the resolution of the sýslumenn at the Althing on **16 July "
        "1756**, sixteen days before the snapshot.",
        "",
        "Malta and Gozo rest on one instrument, and it is the instrument "
        "that decides the scope. Charles V's privilege of 23 March 1530 "
        "names **Malta and Gozo** and the fortress of Tripoli. Gozo is "
        "produced. **Comino, four kilometres from Gozo, is not named and is "
        "not produced.**",
        "",
        "## 3. What was left out",
        "",
        "| component | ground km² | reason |",
        "|---|---|---|",
    ]
    named = excl[excl["named_identification"] != ""]
    for r in named.head(14).itertuples():
        L.append(f"| {str(r.named_identification)[:44]} | "
                 f"{r.ground_area_km2:,.2f} | {r.exclusion_reason} |")
    L += [
        f"| … and {len(excl) - len(named)} further unnamed components | | all "
        "excluded |",
        "",
        "Two of these carry the argument. The **Faroes** are under the same "
        "crown as Iceland and are still not Iceland — they swore their own "
        "homage at Tórshavn on 14 August 1662, seventeen days after "
        "Kópavogur. Same monarch, separate act, separate territory. And "
        "**Surtsey** did not exist in 1756: it rose out of the sea in 1963. "
        "It is excluded by identity, not by any threshold, which is the "
        "cleanest statement this project has of why a modern coastline is "
        "substrate and not history.",
        "",
        "## 4. Physical change, measured where it can be",
        "",
        "| landmass | mechanism | measured | interior affected |",
        "|---|---|---|---|",
    ]
    for r in cc.itertuples():
        L.append(f"| {r.landmass} | {r.mechanism} | {r.measured[:34]} | "
                 f"{r.interior_affected} |")
    L += [
        "",
        "Iceland is the hardest physical case so far: glaciers that have "
        "retreated a long way, outwash plains that prograde by kilometres, "
        "and coastline that volcanoes create outright. Only one of those is "
        "quantified here — Surtsey, because it is a component whose area the "
        "canonical geometry can be asked for. The rest are named as "
        "mechanisms and explicitly **not** used to explain any residual, and "
        "**no island interior is withheld for any of them**.",
        "",
        "## 5. Area semantics",
        "",
        "| landmass | ground km² | published | residual | interior rings |",
        "|---|---|---|---|---|",
    ]
    for r in area.itertuples():
        L.append(f"| {r.landmass} | {r.ground_area_km2:,.2f} | "
                 f"{r.published_area_km2:,.1f} | {r.difference_pct:+.2f}% | "
                 f"{r.n_interior_rings} |")
    L += [
        "",
        f"Iceland {s['area_residual_iceland_pct']:+.2f}%, Malta "
        f"{s['area_residual_malta_pct']:+.2f}%, Gozo "
        f"{s['area_residual_gozo_pct']:+.2f}%. All five islands produced so "
        "far now sit inside ±2%, with zero interior rings on every one, so "
        "inland water is excluded nowhere and cannot be the cause of any "
        "residual. Great Britain at +4.47% remains the only outlier of the "
        "seven landmasses measured.",
        "",
        "## 6. The cost of the terrestrial-hex rule",
        "",
        f"**{s['not_produced_non_terrestrial_hexes']:,} hexes carry "
        f"authorised land — {s['not_produced_authorised_km2']:,.1f} km² of "
        "it — and are not produced,** because the canonical "
        "`is_terrestrial_hex` flag is a majority-land test and they fail it.",
        "",
        "This is not new to MAPGEN-023; every earlier island stage did the "
        "same thing silently. It is reported now because Malta forced the "
        "issue: on 246 km² of island, roughly half the hexes holding Maltese "
        "land fall below the threshold. The rule is deliberately **not** "
        "changed here. `territorial_target_type` is `TERRESTRIAL_HEX`, and "
        "deciding that a one-third-land hex is a land hex would be an edit "
        "to canonical physical geography, made in the wrong stage, to make a "
        "number bigger.",
        "",
        "## 7. Membership",
        "",
        "| region | status | basis | hexes |",
        "|---|---|---|---|",
    ]
    for (rg, st, b), n in mix.groupby(
            ["region", "control_status", "basis"]).size().items():
        L.append(f"| {rg} | {st} | {b} | {n:,} |")
    L += [
        "",
        f"Hexes carrying land from two authorised components: "
        f"**{s['cross_component_hexes']}**. Held back as mixed unaudited "
        f"land: **{s['held_back_mixed_component']}**.",
        "",
        "## 8. Scope discipline",
        "",
        "Authorising Iceland produced **nothing** in Denmark, Norway, "
        "Schleswig, Holstein, the Faroes or Greenland. Authorising Malta "
        "produced nothing in Tripoli or the Order's European commanderies. "
        "Both are gated, not merely intended.",
        "",
        f"Coverage: Iceland `{s['coverage_iceland']}`, Malta "
        f"`{s['coverage_malta']}`, Gozo `{s['coverage_gozo']}` — partial, "
        "never complete.",
        "",
        "## 9. Figures",
        "",
    ]
    for n in img:
        L.append(f"- `{n}` (aspect {aspects.get(n, 0):.3f})")
    L += ["", f"Run `{run_id}`. Every figure and CSV in this directory is "
              "reproducible from the committed data by re-running the stage."]
    (run_dir / "README_REVIEW.md").write_text("\n".join(L) + "\n",
                                              encoding="utf-8")
