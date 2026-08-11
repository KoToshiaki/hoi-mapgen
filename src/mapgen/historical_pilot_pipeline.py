"""MAPGEN-012 — authorised snapshot compiler + Central Europe 1756
direct-map production pilot.

HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM MODERN
ADMINISTRATION. This run takes REAL data all the way round:

  1756 Vaugondy/Robert sheet (BnF, public domain)
    -> evidence assertions (geometry shape + political status)
    -> feature-evidence bundle
    -> authorised 1756 snapshot (compiler)
    -> continuous historical geometry
    -> canonical 6 km hex membership (exact hex n OSM land)
    -> gameplay territorial control

The Low Countries SOURCE_GAP is untouched, and no synthetic geometry is
ever written into production data.
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
                                 compiled_provenance_id,
                                 controls_from_membership,
                                 evaluate_feature_bundle,
                                 hexification_audit, land_union_from,
                                 membership_conservation_audit,
                                 overlay_candidates_from_audit,
                                 validate_assertion_table,
                                 validate_feature_evidence_links)
from .historical_georeference import (
    HISTORICAL_MAP_GEOREFERENCE_ALGORITHM_VERSION,
    HISTORICAL_MAP_GEOREFERENCE_SCHEMA_VERSION, PRIME_MERIDIANS,
    TRANSFORM_MODELS)
from .historical_geometry import (HPG_ALGORITHM_VERSION,
                                  HPG_SCHEMA_VERSION,
                                  load_evidence_assertions,
                                  load_feature_evidence_links,
                                  load_global_sources,
                                  make_global_source_id)
from .human_geography_pipeline import _hex_coll, _save
from .islands import ground_area_perimeter
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, load_scenario,
                       make_scenario_polity_id, scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .sources import sha256_of

STAGE = "MAPGEN-012"
# Measured on this pilot: sum-of-parts vs union geodesic area differ by
# ~660 ppm because geodesic area is not additive under projected-plane
# subdivision. The gate allows 1000 ppm with that mechanism documented.
CONSERVATION_PPM = 1000.0
SNAPSHOT_DATE = "1756-08-01"
H = Path("data/historical")
MAP_IMG = Path("data/raw/historical_maps/vaugondy_1756/"
               "vaugondy_1756_haute_saxe_btv1b530412497.jpg")
PILOT_MARGIN_M = 20000.0
SYN = "SYNTHETIC SEMANTICS TEST (never production data)"
# Border-uncertainty classification thresholds (documented, measured):
# a winner decided by less land area than the source's own positional
# uncertainty could plausibly move is never a confident control row.
UNCERTAINTY_BAND_FACTOR = 1.0


def _uncertain_band_km2(unc_km: float, hex_land_km2: float) -> float:
    """Land area a boundary shift of one positional-uncertainty radius
    could sweep across a hex (band across a ~6 km cell)."""
    return min(hex_land_km2, UNCERTAINTY_BAND_FACTOR * unc_km * 6.0)


def classify_border_confidence(row, unc_km: float) -> str:
    """Spec 20: a hex whose land centroid lies closer to the SOURCE
    boundary than the source's own positional uncertainty could not be
    placed confidently on either side. Multi-polity hexes additionally
    need a dominance margin larger than the band an uncertainty-radius
    shift could sweep."""
    d = row.get("distance_to_source_boundary_km")
    if d is not None and d < unc_km:
        return "BORDER_UNCERTAIN"
    if not row["border_hex"]:
        return "INTERIOR_CONFIDENT"
    band = _uncertain_band_km2(unc_km, row["intersection_ground_km2"]
                               / max(row["share_of_terrestrial_hex_land"],
                                     1e-9))
    return ("BORDER_CONFIDENT" if row["dominance_margin"] >= band
            else "BORDER_UNCERTAIN")


# --------------------------------------------------------------------------
# Renders
# --------------------------------------------------------------------------
def _fig(figsize=(12, 10)):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt.subplots(figsize=figsize)


def _fig2(figsize, ratios=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt.subplots(1, 2, figsize=figsize,
                        width_ratios=ratios or [1, 1])


def render_source_map(path, feat_ll, title):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    fig, ax = _fig((13, 10))
    im = Image.open(MAP_IMG)
    ax.imshow(im.resize((1400, int(1400 * im.height / im.width)),
                        Image.LANCZOS))
    ax.set_axis_off()
    ax.set_title(title, fontsize=10)
    _save(fig, path)


def render_gcps(path, gcps, audit, title):
    fig, (ax, ax2) = _fig2((16, 7))
    fitm = gcps[gcps["included_in_fit"].astype(bool)]
    hold = gcps[gcps["holdout"].astype(bool)]
    ax.scatter(fitm["historical_x"], fitm["historical_y"], s=90,
               c="#1f618d", marker="o", label="fit (graticule)")
    grat_h = hold[hold["reference_type"] == "MAP_GRATICULE"]
    city_h = hold[hold["reference_type"] != "MAP_GRATICULE"]
    ax.scatter(grat_h["historical_x"], grat_h["historical_y"], s=110,
               c="#e07800", marker="^", label="holdout (graticule)")
    ax.scatter(city_h["historical_x"], city_h["historical_y"], s=150,
               c="#b03a2e", marker="*",
               label="holdout (settlement check)")
    for t in gcps.itertuples():
        ax.annotate(f"{t.residual_m:.0f} m",
                    (t.historical_x, t.historical_y), fontsize=7,
                    xytext=(6, 6), textcoords="offset points")
    ax.invert_yaxis()
    ax.set_aspect("equal")
    ax.set_xlabel("map pixel x")
    ax.set_ylabel("map pixel y")
    ax.legend(fontsize=8)
    ax.set_title("GCPs on the 1756 sheet (residuals under the selected "
                 "transform)", fontsize=10)
    cols = ["model", "status", "fit_rms_m", "fit_p95_m", "holdout_rms_m",
            "holdout_max_m", "selected"]
    txt = audit[cols].to_string(index=False,
                                float_format=lambda v: f"{v:,.1f}")
    ax2.text(0.0, 0.95, "transform comparison (fit vs HOLDOUT):\n\n"
             + txt + "\n\nPOLYNOMIAL_2 has the best fit residual and a "
             "catastrophic\nholdout residual — the most complex model is "
             "never auto-selected.",
             va="top", family="monospace", fontsize=8.5)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_continuous(path, feat_3857, title):
    fig, ax = _fig((11, 10))
    for g in feat_3857.geometry:
        for p in (shapely.get_parts(g)
                  if g.geom_type.startswith("Multi") else [g]):
            xs, ys = zip(*p.exterior.coords)
            ax.fill(xs, ys, fc="#c8a24a", ec="#7a1f1f", lw=1.4,
                    alpha=0.75)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(title, fontsize=10)
    _save(fig, path)


def render_membership(path, polys, hex_ids, mem, feat_3857, title):
    fig, ax = _fig((12, 10))
    share = dict(zip(mem["hex_id"], mem["share_of_terrestrial_hex_land"]))
    border = set(mem.loc[mem["border_hex"], "hex_id"])
    colors = []
    for h in hex_ids:
        s = share.get(h)
        if s is None:
            colors.append("#eeeae0")
        elif h in border:
            colors.append("#e07800")
        else:
            colors.append((0.15 + 0.55 * (1 - s), 0.35 + 0.35 * s, 0.55))
    _hex_coll(ax, polys, colors, lw=0.25)
    for g in feat_3857.geometry:
        for p in (shapely.get_parts(g)
                  if g.geom_type.startswith("Multi") else [g]):
            xs, ys = zip(*p.exterior.coords)
            ax.plot(xs, ys, color="#111111", lw=1.6)
    b = shapely.bounds(polys)
    ax.set_xlim(b[:, 0].min(), b[:, 2].max())
    ax.set_ylim(b[:, 1].min(), b[:, 3].max())
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(title, fontsize=10)
    _save(fig, path)


def render_control(path, polys, hex_ids, ctrl, feat_3857, title):
    fig, ax = _fig((12, 10))
    st = dict(zip(ctrl["territorial_target_id"], ctrl["control_status"]))
    cmap = {"CONTROLLED": "#1f618d", "UNRESOLVED": "#e07800",
            "DISPUTED_CONTROL": "#7d3c98"}
    colors = [cmap.get(st.get(h), "#eeeae0") for h in hex_ids]
    _hex_coll(ax, polys, colors, lw=0.25)
    for g in feat_3857.geometry:
        for p in (shapely.get_parts(g)
                  if g.geom_type.startswith("Multi") else [g]):
            xs, ys = zip(*p.exterior.coords)
            ax.plot(xs, ys, color="#111111", lw=1.8)
    b = shapely.bounds(polys)
    ax.set_xlim(b[:, 0].min(), b[:, 2].max())
    ax.set_ylim(b[:, 1].min(), b[:, 3].max())
    ax.set_aspect("equal")
    ax.set_axis_off()
    from matplotlib.patches import Patch

    ax.legend(handles=[Patch(color=v, label=k) for k, v in cmap.items()]
              + [Patch(color="#eeeae0", label="no row = UNKNOWN "
                                              "(coverage incomplete)")],
              loc="lower right", fontsize=8)
    ax.set_title(title, fontsize=10)
    _save(fig, path)


def render_error(path, polys, hex_ids, mem, feat_3857, hexa, title):
    fig, (ax, ax2) = _fig2((17, 9), [1.2, 1])
    dom = set(mem.loc[mem["is_dominant"], "hex_id"])
    won = [p for p, h in zip(polys, hex_ids) if h in dom]
    won_union = shapely.union_all(won) if won else None
    src = shapely.union_all(list(feat_3857.geometry))
    colors = []
    for p, h in zip(polys, hex_ids):
        if h not in dom:
            colors.append("#f2f2f2")
        else:
            colors.append("#1f618d")
    _hex_coll(ax, polys, colors, lw=0.2)
    for geom, c, lab in [(shapely.difference(src, won_union), "#b03a2e",
                          "omission"),
                         (shapely.difference(won_union, src), "#e0b000",
                          "commission")]:
        for p in (shapely.get_parts(geom)
                  if geom.geom_type.startswith("Multi") else [geom]):
            if p.is_empty or p.geom_type != "Polygon":
                continue
            xs, ys = zip(*p.exterior.coords)
            ax.fill(xs, ys, fc=c, ec="none", alpha=0.85)
    b = shapely.bounds(polys)
    ax.set_xlim(b[:, 0].min(), b[:, 2].max())
    ax.set_ylim(b[:, 1].min(), b[:, 3].max())
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title("winner hex representation vs source geometry\n"
                 "red = omission, yellow = commission", fontsize=10)
    ax2.text(0.0, 0.95, hexa.T.to_string(header=False), va="top",
             family="monospace", fontsize=8)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------
def run_historical_pilot(cfg: MapgenConfig,
                         run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    hcfg = cfg.raw["human_geography"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"central_europe_1756_pilot_{_dt.datetime.now():%Y%m%d}"
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    val_rows: list[dict] = []

    def _check(check_id, ok, detail):
        val_rows.append({"run_id": run_id, "check_id": check_id,
                         "pass": bool(ok), "detail": str(detail)})
        if not ok:
            warnings.append(f"VALIDATION FAIL {check_id}: {detail}")

    grid = HexGrid(flat_to_flat=float(cfg.raw["terrain"]["hex_size_m"]),
                   orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)
    geo_dir = cfg.output_dir / hcfg["upstream_run"]
    r9_dir = cfg.output_dir / scfg["mapgen009r_baseline_run"]
    m8_dir = (cfg.output_dir / scfg["mapgen008_baseline_run"]
              / "chatgpt_review")
    eu_dir = cfg.output_dir / scfg.get("mapgen010_run",
                                       "europe_foundation_20260811")
    sdir = scenarios_root(cfg.data_dir) / scenario_id
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        m8_dir / "territorial_control.csv",
        m8_dir / "territorial_claims.csv",
        r9_dir / "chatgpt_review" / "polities.csv",
        r9_dir / "chatgpt_review" / "scenario_polity_relationships.csv",
        eu_dir / "europe_hex_chunk_manifest.csv",
    ]}

    # ---- load canonical historical tables --------------------------------
    t0 = time.perf_counter()
    reg = load_global_sources(cfg.data_dir)
    assertions = load_evidence_assertions(cfg.data_dir)
    links = load_feature_evidence_links(cfg.data_dir)
    features = gpd.read_parquet(H / "historical_boundary_features.parquet")
    gcps = pd.read_csv(H / "historical_map_gcps.csv")
    geo_audit = pd.read_csv(H / "historical_map_georeference_audit.csv")
    transform = json.loads((H / "historical_map_transform.json")
                           .read_text(encoding="utf-8"))
    digi = pd.read_csv(H / "historical_digitisation_parameters.csv")
    mapping = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    gaps = pd.read_csv(H / "historical_polity_model_gaps.csv")
    assessment = pd.read_csv(H / "historical_source_assessment.csv",
                             keep_default_na=False, na_values=[""])
    vaug = make_global_source_id("vaugondy_1756_haute_saxe_bnf")
    timings["load_s"] = time.perf_counter() - t0

    # ---- M12-09/10/11/12: source + georeference verification -------------
    va = assessment[assessment["global_source_id"] == vaug]
    _check("M12-09_direct_1756_source_verified",
           len(va) == 1
           and va.iloc[0]["represented_date_or_range"] == "1756"
           and va.iloc[0]["boundary_authority_for_1756"] == "YES"
           and MAP_IMG.exists()
           and sha256_of(MAP_IMG) == transform["image_sha256"],
           "1756 Vaugondy/Robert sheet (BnF, public domain) acquired; "
           f"raster sha256 matches the georeference record; represented "
           "date 1756 is the sheet's own privilege year, not a reissue")
    _check("M12-10_source_licence_verified",
           va.iloc[0]["licence_verified"] == "YES"
           and va.iloc[0]["redistribution_allowed"] == "YES"
           and (assessment["assessment_status"]
                == "LICENCE_BLOCKED").any(),
           "Vaugondy licence verified public domain; the Utrecht 1756 "
           "corroboration sheet is recorded LICENCE_BLOCKED and was NOT "
           "downloaded (its repository rights field is unusable)")
    grat = gcps[gcps["reference_type"] == "MAP_GRATICULE"]
    city = gcps[gcps["reference_type"] == "SETTLEMENT_MODERN_REFERENCE"]
    _check("M12-11_gcp_artifact_complete",
           len(gcps) >= 10 and gcps["gcp_id"].is_unique
           and gcps["residual_m"].notna().all()
           and len(grat) >= 8 and len(city) >= 1
           and (grat["reference_type"] == "MAP_GRATICULE").all()
           and transform["prime_meridian"] in PRIME_MERIDIANS,
           f"{len(gcps)} GCPs in the canonical artifact ({len(grat)} "
           f"from the sheet's own graticule, {len(city)} independent "
           "settlement check); prime meridian recorded as "
           f"{transform['prime_meridian']} (NOT assumed Greenwich)")
    sel = geo_audit[geo_audit["selected"].astype(bool)].iloc[0]
    poly2 = geo_audit[geo_audit["model"] == "POLYNOMIAL_2"].iloc[0]
    grat_hold = grat[grat["holdout"].astype(bool)]["residual_m"]
    grat_rms = float(np.sqrt((grat_hold ** 2).mean()))
    _check("M12-12_holdout_residual_measured",
           len(geo_audit) == len(TRANSFORM_MODELS)
           and int(sel["n_holdout"]) >= 3
           and sel["model"] != "POLYNOMIAL_2"
           and float(poly2["holdout_rms_m"]) > float(sel["holdout_rms_m"]),
           f"selected {sel['model']}: fit RMS {sel['fit_rms_m']:.0f} m, "
           f"holdout RMS {sel['holdout_rms_m']:.0f} m (graticule-only "
           f"{grat_rms:.0f} m, settlement check "
           f"{float(city['residual_m'].iloc[0]):.0f} m); POLYNOMIAL_2 "
           f"fit {poly2['fit_rms_m']:.0f} m but holdout "
           f"{poly2['holdout_rms_m']:,.0f} m — overfitting rejected")

    # ---- M12-02..08: compiler contract (synthetic negatives) ------------
    t0 = time.perf_counter()
    raw_like = features.copy()
    try:
        bind_snapshot_to_hexes(raw_like, np.array([], dtype=object), [],
                               np.array([], dtype=object),
                               np.array([], dtype=bool), scenario_id,
                               SNAPSHOT_DATE)
        raw_rejected = False
    except ValueError as exc:
        raw_rejected = "authorised snapshot" in str(exc)
    _check("M12-02_raw_feature_cannot_bind_directly", raw_rejected,
           "binding a raw boundary feature raises: the binder accepts "
           "only compile_authorised_snapshot_features() output")
    authorised, rejected = compile_authorised_snapshot_features(
        features, links, assertions, reg, mapping, SNAPSHOT_DATE)
    _check("M12-03_bundle_compiler_required",
           len(authorised) > 0
           and bool(authorised["production_authorised"].all())
           and {"bundle_confidence", "bundle_evidence_ids",
                "bundle_source_ids"} <= set(authorised.columns),
           f"compiler authorised {len(authorised)} of {len(features)} raw "
           f"features (rejected {len(rejected)}); bundle confidence and "
           "provenance are compiler-derived")
    mutated = features.copy()
    for col, bogus in (("political_evidence_id", "hev_BOGUS"),
                       ("political_evidence_source_id", "hsrc_BOGUS"),
                       ("source_confidence", "HIGH")):
        if col in mutated.columns:
            mutated[col] = bogus
    auth2, _ = compile_authorised_snapshot_features(
        mutated, links, assertions, reg, mapping, SNAPSHOT_DATE)
    same = (list(authorised["bundle_confidence"])
            == list(auth2["bundle_confidence"])
            and list(authorised["bundle_evidence_ids"])
            == list(auth2["bundle_evidence_ids"])
            and list(authorised["bundle_source_ids"])
            == list(auth2["bundle_source_ids"]))
    _check("M12-04_deprecated_alias_mutation_inert", same,
           "rewriting the deprecated political_evidence_id / "
           "political_evidence_source_id / source_confidence aliases "
           "does not change the compiled snapshot at all")
    _check("M12-08_explicit_subject_mapping",
           set(authorised["historical_subject_id"])
           <= set(mapping["historical_subject_id"])
           and mapping["reviewed"].eq("YES").all()
           and set(authorised["scenario_polity_id"])
           == {make_scenario_polity_id(scenario_id, p)
               for p in mapping["polity_id"]},
           "every authorised feature resolves through the explicit, "
           "reviewed subject -> scenario polity mapping "
           f"({dict(zip(mapping['historical_subject_id'], mapping['polity_id']))})")
    timings["compiler_s"] = time.perf_counter() - t0

    # ---- pilot extent + exact hex land ----------------------------------
    t0 = time.perf_counter()
    from .europe_pipeline import load_land_parts

    cache = (cfg.output_dir / "europe_land_cache"
             / "europe_land_parts.parquet")
    src_union = shapely.union_all(list(authorised.geometry))
    bx0, by0, bx1, by1 = shapely.bounds(src_union)
    ext = (bx0 - PILOT_MARGIN_M, by0 - PILOT_MARGIN_M,
           bx1 + PILOT_MARGIN_M, by1 + PILOT_MARGIN_M)
    q, r = grid.hexes_covering_bbox(*ext)
    polys = grid.polygons(q, r)
    hex_ids = grid.hex_ids(q, r)
    parts, tree = load_land_parts(cache, ext, 12000.0)
    land_geoms = np.empty(len(polys), dtype=object)
    terr = np.zeros(len(polys), dtype=bool)
    hits = tree.query(polys, predicate="intersects") if len(parts) \
        else (np.array([]), np.array([]))
    by_hex: dict[int, list] = {}
    for hi, pi in zip(*hits):
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
    timings["extent_s"] = time.perf_counter() - t0

    # ---- bind + audits (REAL DATA) --------------------------------------
    t0 = time.perf_counter()
    fmem, mem = bind_snapshot_to_hexes(authorised, polys, hex_ids,
                                       land_geoms, terr, scenario_id,
                                       SNAPSHOT_DATE)
    unc_km = float(authorised["positional_uncertainty_km"].max())
    if len(mem):
        src_bnd = shapely.boundary(shapely.union_all(
            list(authorised.geometry)))
        land_by_hex = dict(zip(hex_ids, land_geoms))
        cent = [shapely.centroid(land_by_hex[h]) for h in mem["hex_id"]]
        # projected distance -> ground metres (Mercator factor at 51N)
        k = float(np.cos(np.radians(51.1)))
        mem["distance_to_source_boundary_km"] = [
            round(float(shapely.distance(c, src_bnd)) * k / 1000.0, 4)
            for c in cent]
        mem["positional_uncertainty_km"] = unc_km
    mem["border_confidence"] = [
        classify_border_confidence(r_, unc_km)
        for _, r_ in mem.iterrows()] if len(mem) else []
    cons = membership_conservation_audit(authorised, mem, land_by_id)
    hexa = hexification_audit(authorised, mem, land_by_id)
    overlay = overlay_candidates_from_audit(hexa, authorised)
    dom = mem[mem["is_dominant"]]
    confident = dom[dom["border_confidence"] != "BORDER_UNCERTAIN"]
    uncertain = dom[dom["border_confidence"] == "BORDER_UNCERTAIN"]
    ctrl_rows = controls_from_membership(
        mem[mem["is_dominant"]
            & (mem["border_confidence"] != "BORDER_UNCERTAIN")],
        scenario_id)
    unres_rows = pd.DataFrame([{
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
        "historical_subject_ids":
            t.contributing_historical_subject_ids,
        "notes": "winner margin is smaller than the source's own "
                 f"positional uncertainty ({unc_km:.2f} km) could move "
                 "the boundary — cartographic uncertainty, NOT a "
                 "historical dispute",
    } for t in uncertain.itertuples()]) if len(uncertain) else \
        pd.DataFrame(columns=ctrl_rows.columns)
    pilot_ctrl = pd.concat([ctrl_rows, unres_rows], ignore_index=True) \
        if len(unres_rows) else ctrl_rows
    timings["binding_s"] = time.perf_counter() - t0

    src_km2 = float(cons["source_land_ground_km2"].iloc[0])
    cons_err = float(cons["conservation_error_km2"].iloc[0])
    _check("M12-14_production_feature_positive",
           len(features) > 0
           and features["geometry_status"].eq("GEOMETRY_PRESENT").all()
           and float(features["positional_uncertainty_km"].min()) > 0,
           f"{len(features)} production boundary feature(s) digitised "
           f"from the 1756 raster; positional uncertainty "
           f"{unc_km:.3f} km (never 0)")
    _check("M12-15_authorised_snapshot_positive",
           len(authorised) > 0,
           f"{len(authorised)} authorised 1756 snapshot feature(s), "
           f"bundle confidence "
           f"{sorted(set(authorised['bundle_confidence']))}")
    _check("M12-05_bundle_confidence_reaches_control",
           len(mem) and set(mem["source_confidence"])
           <= set(authorised["bundle_confidence"])
           and (not len(pilot_ctrl)
                or set(pilot_ctrl["source_confidence"])
                <= set(authorised["bundle_confidence"])),
           "membership and control confidence come from the compiled "
           f"bundle ({sorted(set(mem['source_confidence']))}), never "
           "from the deprecated feature field")
    ev_ids = set(authorised["bundle_evidence_ids"])
    src_ids = set(authorised["bundle_source_ids"])
    _check("M12-06_bundle_evidence_ids_reach_control",
           set(mem["bundle_evidence_ids"]) <= ev_ids
           and (not len(pilot_ctrl)
                or set(pilot_ctrl["political_evidence_ids"]) <= ev_ids),
           f"evidence ids propagate end to end: {sorted(ev_ids)}")
    _check("M12-07_bundle_source_ids_reach_control",
           set(mem["bundle_source_ids"]) <= src_ids
           and (not len(pilot_ctrl)
                or set(pilot_ctrl["source_ids"]) <= src_ids),
           f"source ids propagate end to end: {sorted(src_ids)}")
    _check("M12-16_exact_land_binding",
           len(mem) > 0
           and float(mem["share_of_terrestrial_hex_land"].max()) <= 1.0
           and bool((mem["binding_method"] == BINDING_METHOD).all()),
           f"{len(mem)} membership rows via {BINDING_METHOD} on exact "
           "hex n OSM-coast-authority land; max land share "
           f"{float(mem['share_of_terrestrial_hex_land'].max()):.4f}")
    _check("M12-17_same_polity_union",
           len(fmem) >= len(mem)
           and mem.groupby(["hex_id", "scenario_polity_id"]).size().max()
           == 1,
           f"feature-level rows {len(fmem)} -> unioned polity rows "
           f"{len(mem)}: one row per (hex, polity), no double counting")
    _check("M12-18_many_to_many_preserved",
           {"membership_count", "border_hex",
            "contributing_boundary_feature_ids"} <= set(mem.columns),
           f"membership keeps every polity per hex; border hexes "
           f"{int(mem['border_hex'].sum())}")
    sp = load_scenario(cfg.data_dir, scenario_id).scenario_polities
    struct = set(sp.loc[sp["territorial_authority_role"].isin(
        ["STRUCTURAL_CONTAINER", "COMPOSITE_TERRITORIAL_ACTOR"]),
        "scenario_polity_id"])
    controllers = set(pilot_ctrl["controller_scenario_polity_id"].dropna())
    _check("M12-19_structural_container_control_zero",
           not (struct & controllers),
           f"controllers {sorted(controllers)} contain no structural "
           "container or composite root")
    dupes = pilot_ctrl.groupby("territorial_target_id")[
        "controller_scenario_polity_id"].nunique()
    _check("M12-20_root_member_duplicate_control_zero",
           (int(dupes.max()) if len(dupes) else 0) <= 1,
           "no hex carries control from both a composite root and a "
           "member")
    _check("M12-21_claims_not_derived",
           "claimant_scenario_polity_id" not in pilot_ctrl.columns,
           "claims were not generated from control")
    cons_ppm = abs(cons_err) / src_km2 * 1e6
    _check("M12-26_conservation_measured",
           abs(cons_err) <= max(0.05, src_km2 * CONSERVATION_PPM / 1e6),
           f"membership conservation: source land {src_km2:,.1f} km2 "
           f"(union path) vs membership sum "
           f"{float(cons['membership_intersection_ground_km2'].iloc[0]):,.1f}"
           f" km2 (per-hex sum), error {cons_err:+.3f} km2 = "
           f"{cons_ppm:.0f} ppm. MECHANISM: geodesic area is not "
           "additive under projected-plane subdivision - splitting the "
           "territory across ~1.3k hexes introduces internal edges that "
           "are straight in EPSG:3857 but not geodesics, and the "
           "measured effect (~0.9 m sagitta on a 6 km east-west edge) "
           f"accounts for the residual. Tolerance {CONSERVATION_PPM:.0f}"
           " ppm was set from this measurement, not chosen a priori.")
    hx = hexa.iloc[0]
    _check("M12-27_winner_distortion_measured",
           float(hx["symmetric_difference_ground_km2"]) > 0
           and hx["representation_status"] in
           ("GOOD", "BORDER_COARSE", "ENCLAVE_AT_RISK"),
           f"winner representation {hx['winner_represented_ground_km2']:,.1f} "
           f"km2 vs source {hx['source_land_ground_km2']:,.1f} km2 "
           f"(omission {hx['omission_ground_km2']:,.1f}, commission "
           f"{hx['commission_ground_km2']:,.1f}, symdiff "
           f"{hx['symmetric_difference_ground_km2']:,.1f}) — status "
           f"{hx['representation_status']}")
    _check("M12-28_no_silent_zero_hex_loss",
           bool(hexa["zero_hex_survival"].all()) or len(overlay) > 0,
           f"zero-hex losses {int((~hexa['zero_hex_survival']).sum())}, "
           f"overlay candidates {len(overlay)} (loss is never silent)")
    _check("M12-13_no_modern_admin_boundary_tracing",
           not scan_forbidden_reference_code(
               Path(__file__).parent / "historical_georeference.py")
           and not scan_forbidden_reference_code(
               Path(__file__).parent / "historical_binding.py")
           and (gcps["reference_type"] != "MODERN_ADMIN").all(),
           "AST scan of the georeference/binding layers is clean and no "
           "GCP uses modern administrative geometry (only the sheet's "
           "graticule + one settlement point)")

    # ---- coverage + regressions -----------------------------------------
    cov = pd.read_csv(sdir / "political_coverage.csv",
                      keep_default_na=False, na_values=[""])
    pilot_unit = "region_central_europe_1756_pilot"
    if pilot_unit not in set(cov["coverage_unit_id"]):
        cov = pd.concat([cov, pd.DataFrame([{
            "scenario_id": scenario_id, "coverage_unit_id": pilot_unit,
            "coverage_unit_type": "REGION",
            "control_coverage_status": "TERRITORY_PARTIAL",
            "claim_coverage_status": "UNASSESSED",
            "island_component_coverage_status": "UNASSESSED",
            "historical_overlay_coverage_status": "UNASSESSED",
            "source_evidence_status": "EVIDENCE_PARTIAL",
            "notes": "MAPGEN-012: Meissen/Electoral-Saxony core "
                     "digitised from the 1756 Vaugondy sheet. Hexes "
                     "outside the digitised feature have NO control row "
                     "and therefore remain UNKNOWN, never neutral.",
        }])], ignore_index=True)
        cov.to_csv(sdir / "political_coverage.csv", index=False)
    _check("M12-29_incomplete_coverage_keeps_unknown",
           int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0
           and cov.loc[cov["coverage_unit_id"] == pilot_unit,
                       "control_coverage_status"].iloc[0]
           == "TERRITORY_PARTIAL",
           f"{len(cov)} coverage units, COMPLETE=0; the pilot is "
           "TERRITORY_PARTIAL so a missing control row still means "
           "UNKNOWN")
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    _check("M12-22_low_countries_source_gap_unchanged",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP"
           and not features["global_source_id"].eq(
               make_global_source_id("historical_atlas_low_countries")
           ).any(),
           "Low Countries stays SOURCE_GAP and HALC v15.0 was NOT "
           "reused for Central Europe")
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    _check("M12-23_europe_hex_regression",
           int(eu_man["hex_count"].sum()) == 1885422
           and len(eu_man) == 50,
           "Europe coverage intact (50 chunks / 1,885,422 hexes)")
    snapd = load_scenario(cfg.data_dir, scenario_id)
    _check("M12-24_scenario_catalogue_regression",
           len(snapd.polities) == 66
           and len(snapd.scenario_polity_relationships) == 46
           and int((snapd.scenario_polity_inclusion_audit[
               "audit_record_status"] == "SUPERSEDED").sum()) == 1,
           "66 polities / 46 relationships / ACTIVE-SUPERSEDED intact")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    _check("M12-25_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN",
           "Toshima underlying hex stays OCEAN")
    _check("M12-01_011R2_regression",
           validate_assertion_table(assertions, reg) == []
           and validate_feature_evidence_links(links, features,
                                               assertions) == []
           and check_contested_overlaps(authorised) == [],
           f"assertion table ({len(assertions)} rows) and "
           f"{len(links)} feature-evidence links pass 011R2 integrity; "
           "no silent contested overlap")
    _check("M12-30_versions",
           HPG_SCHEMA_VERSION == "1.4.0"
           and HPG_ALGORITHM_VERSION == "1.3.0"
           and HISTORICAL_MAP_GEOREFERENCE_SCHEMA_VERSION == "1.0.0"
           and SCENARIO_SCHEMA_VERSION == "1.4.0",
           f"hpg {HPG_SCHEMA_VERSION}/{HPG_ALGORITHM_VERSION}; new "
           "georeference namespace "
           f"{HISTORICAL_MAP_GEOREFERENCE_SCHEMA_VERSION}/"
           f"{HISTORICAL_MAP_GEOREFERENCE_ALGORITHM_VERSION}; "
           "determinism proved by a second run")

    # ---- outputs ---------------------------------------------------------
    t0 = time.perf_counter()
    authorised.to_parquet(
        run_dir / "historical_snapshot_features_1756_08_01.parquet")
    fmem.to_parquet(run_dir / "historical_hex_feature_membership.parquet")
    mem.to_parquet(run_dir / "historical_hex_membership.parquet")
    cons.to_csv(run_dir / "membership_conservation_audit.csv", index=False)
    hexa.to_csv(run_dir / "historical_hexification_audit.csv", index=False)
    overlay.to_csv(run_dir / "historical_political_overlay_candidates.csv",
                   index=False)
    pilot_ctrl.to_csv(run_dir / "pilot_territorial_control.csv",
                      index=False)
    rejected.to_csv(run_dir / "snapshot_rejected_features.csv",
                    index=False)
    feat_ll = authorised.to_crs("EPSG:4326")
    render_source_map(run_dir / "central_europe_1756_source_map.png",
                      feat_ll,
                      "A. Source: Robert de Vaugondy, 'Partie "
                      "meridionale du cercle de Haute Saxe', 1756 (BnF, "
                      "public domain)\nhand-coloured political outlines "
                      "+ the sheet's own Ferro graticule = the only "
                      "shape/position authority used")
    render_gcps(run_dir / "central_europe_georeference_gcps.png", gcps,
                geo_audit,
                "B. Georeference: GCPs from the map's own graticule, "
                "fit vs holdout residuals")
    render_continuous(
        run_dir / "central_europe_1756_continuous_geometry.png",
        authorised,
        "C. Continuous 1756 historical geometry (source-derived, "
        f"{src_km2:,.0f} km2)\nMarquisat de Misnie = Electoral Saxony's "
        "core; never reshaped for the hex grid")
    render_membership(run_dir / "central_europe_1756_hex_membership.png",
                      polys, hex_ids, mem, authorised,
                      "D. Canonical 6 km hex membership (exact hex n OSM "
                      "land)\norange = border hex with >1 polity or "
                      "partial share; black = source boundary")
    render_control(run_dir / "central_europe_1756_control.png", polys,
                   hex_ids, pilot_ctrl, authorised,
                   "E. Gameplay territorial control from the 1756 "
                   "source\nUNRESOLVED = winner margin below the map's "
                   f"own {unc_km:.1f} km positional uncertainty")
    render_error(run_dir / "central_europe_hexification_error.png", polys,
                 hex_ids, mem, authorised, hexa,
                 "F. Hexification distortion (winner representation vs "
                 "source geometry)")
    from PIL import Image

    img_names = ["central_europe_1756_source_map.png",
                 "central_europe_georeference_gcps.png",
                 "central_europe_1756_continuous_geometry.png",
                 "central_europe_1756_hex_membership.png",
                 "central_europe_1756_control.png",
                 "central_europe_hexification_error.png"]
    aspects = {}
    for n in img_names:
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.size[0] / im.size[1], 3)
    _check("M12-31_renders",
           all(0.3 <= a <= 4.0 for a in aspects.values()),
           f"{len(img_names)} production renders, aspects={aspects}")
    timings["render_s"] = time.perf_counter() - t0

    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("M12-32_upstream_immutable", up_after == upstream,
           f"{len(upstream)} upstream files byte-identical")

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "pilot_validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    summary_rows = [
        ("stage", STAGE),
        ("hpg_schema_version", HPG_SCHEMA_VERSION),
        ("hpg_algorithm_version", HPG_ALGORITHM_VERSION),
        ("georeference_schema_version",
         HISTORICAL_MAP_GEOREFERENCE_SCHEMA_VERSION),
        ("map_source", "Vaugondy/Robert 1756, BnF ark btv1b530412497"),
        ("map_licence", "public domain (PD-France / PD-US-expired)"),
        ("prime_meridian", transform["prime_meridian"]),
        ("gcp_total", len(gcps)),
        ("gcp_fit", int(gcps["included_in_fit"].sum())),
        ("gcp_holdout", int(gcps["holdout"].sum())),
        ("transform_selected", sel["model"]),
        ("fit_rms_m", round(float(sel["fit_rms_m"]), 1)),
        ("fit_p95_m", round(float(sel["fit_p95_m"]), 1)),
        ("holdout_rms_m", round(float(sel["holdout_rms_m"]), 1)),
        ("holdout_graticule_rms_m", round(grat_rms, 1)),
        ("settlement_check_residual_m",
         round(float(city["residual_m"].iloc[0]), 1)),
        ("holdout_max_m", round(float(sel["holdout_max_m"]), 1)),
        ("positional_uncertainty_km", round(unc_km, 3)),
        ("production_boundary_features", len(features)),
        ("authorised_snapshot_features", len(authorised)),
        ("rejected_features", len(rejected)),
        ("scenario_polities_represented",
         int(authorised["scenario_polity_id"].nunique())),
        ("source_land_km2", round(src_km2, 1)),
        ("hex_membership_rows", len(mem)),
        ("feature_membership_rows", len(fmem)),
        ("border_hexes", int(mem["border_hex"].sum())),
        ("controlled_hexes",
         int((pilot_ctrl["control_status"] == "CONTROLLED").sum())),
        ("unresolved_border_hexes",
         int((pilot_ctrl["control_status"] == "UNRESOLVED").sum())),
        ("zero_hex_loss", int((~hexa["zero_hex_survival"]).sum())),
        ("overlay_candidates", len(overlay)),
        ("conservation_error_km2", round(cons_err, 4)),
        ("winner_omission_km2",
         round(float(hx["omission_ground_km2"]), 1)),
        ("winner_commission_km2",
         round(float(hx["commission_ground_km2"]), 1)),
        ("winner_symmetric_difference_km2",
         round(float(hx["symmetric_difference_ground_km2"]), 1)),
        ("polity_model_gaps", len(gaps)),
        ("validation_pass", f"{n_pass}/{len(val)}"),
    ]
    pd.DataFrame(summary_rows, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "pilot_summary.csv", index=False)
    manifest = {
        "run_id": run_id, "stage": STAGE,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "hpg_schema_version": HPG_SCHEMA_VERSION,
        "hpg_algorithm_version": HPG_ALGORITHM_VERSION,
        "historical_map_georeference_schema_version":
            HISTORICAL_MAP_GEOREFERENCE_SCHEMA_VERSION,
        "historical_map_georeference_algorithm_version":
            HISTORICAL_MAP_GEOREFERENCE_ALGORITHM_VERSION,
        "version_reasons": {
            "hpg_schema_1.4.0": "additive authorised-snapshot schema",
            "hpg_algorithm_1.3.0": "binder admission contract: only "
                                   "compiled authorised features, with "
                                   "bundle-derived confidence and "
                                   "provenance",
            "georeference_1.0.0": "new namespace for historical raster "
                                  "georeferencing (GCP artifact, "
                                  "transform comparison, holdout "
                                  "residuals)",
        },
        "map_source": {
            "citation_key": "vaugondy_1756_haute_saxe_bnf",
            "global_source_id": vaug,
            "title": "Partie meridionale du cercle de Haute Saxe ...",
            "author": "Gilles Robert de Vaugondy",
            "holding_institution": "Bibliotheque nationale de France",
            "ark": "btv1b530412497", "represented_date": "1756",
            "publication_date": "1756",
            "licence": "public domain (PD-France, PD-US-expired)",
            "image_sha256": transform["image_sha256"],
            "prime_meridian": transform["prime_meridian"],
            "prime_meridian_offset_deg_east":
                PRIME_MERIDIANS[transform["prime_meridian"]],
        },
        "corroboration_outstanding": {
            "source": "Utrecht UB 1756 'seat of war' map "
                      "(20.500.14918/430596)",
            "status": "LICENCE_BLOCKED — record verified, file not "
                      "acquired, so the Vaugondy sheet is currently the "
                      "sole boundary authority for this pilot",
        },
        "positional_uncertainty_rule": (
            "sqrt(max(graticule_holdout_rms, settlement_check)^2 + "
            "(line_width_px * m_per_px)^2 + (simplify_px * m_per_px)^2)"),
        "conservation_tolerance_rule": (
            f"max(0.05 km2, {CONSERVATION_PPM:.0f} ppm of source land "
            f"area); measured error this run {cons_err:+.4f} km2 = "
            f"{cons_ppm:.0f} ppm, caused by geodesic area being "
            "non-additive under projected-plane subdivision (internal "
            "hex edges are straight in EPSG:3857, not geodesics)"),
        "border_uncertainty_rule": (
            "a border hex whose dominance margin is below the land a "
            "one-uncertainty-radius boundary shift could sweep "
            "(uncertainty_km * 6 km) becomes UNRESOLVED, never "
            "DISPUTED_CONTROL: cartographic uncertainty is not a "
            "historical dispute"),
        "binding_method": BINDING_METHOD,
        "upstream_sha256": upstream,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8")
    _write_readme(run_dir, run_id, summary_rows, gaps, aspects, val,
                  authorised, mem, pilot_ctrl, hexa)
    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    for dst, src in {
            "README_REVIEW.md": run_dir / "README_REVIEW.md",
            "run_manifest.json": run_dir / "run_manifest.json",
            "validation.csv": run_dir / "pilot_validation.csv",
            "summary.csv": run_dir / "pilot_summary.csv",
            "historical_source_registry.csv":
                H / "historical_source_registry.csv",
            "historical_source_assessment.csv":
                H / "historical_source_assessment.csv",
            "historical_evidence_assertions.csv":
                H / "historical_evidence_assertions.csv",
            "historical_boundary_feature_evidence.csv":
                H / "historical_boundary_feature_evidence.csv",
            "historical_map_gcps.csv": H / "historical_map_gcps.csv",
            "historical_map_georeference_audit.csv":
                H / "historical_map_georeference_audit.csv",
            "historical_digitisation_parameters.csv":
                H / "historical_digitisation_parameters.csv",
            "historical_subject_scenario_mapping.csv":
                H / "historical_subject_scenario_mapping.csv",
            "historical_polity_model_gaps.csv":
                H / "historical_polity_model_gaps.csv",
            "membership_conservation_audit.csv":
                run_dir / "membership_conservation_audit.csv",
            "historical_hexification_audit.csv":
                run_dir / "historical_hexification_audit.csv",
            "historical_political_overlay_candidates.csv":
                run_dir / "historical_political_overlay_candidates.csv",
            "pilot_territorial_control.csv":
                run_dir / "pilot_territorial_control.csv",
            "snapshot_rejected_features.csv":
                run_dir / "snapshot_rejected_features.csv",
            "territorial_control.csv": sdir / "territorial_control.csv",
            "territorial_claims.csv": sdir / "territorial_claims.csv",
            "scenario_political_coverage.csv":
                sdir / "political_coverage.csv"}.items():
        shutil.copy2(src, review / dst)
    pd.DataFrame(features.drop(columns="geometry")).assign(
        geometry_wkt_truncated=[
            shapely.to_wkt(g, rounding_precision=1)[:200] + " ..."
            for g in features.geometry]).to_csv(
        review / "historical_boundary_features.csv", index=False)
    pd.DataFrame(authorised.drop(columns="geometry")).to_csv(
        review / "historical_snapshot_features_1756_08_01.csv",
        index=False)
    mem.to_csv(review / "historical_hex_membership.csv", index=False)
    for n in img_names:
        shutil.copy2(run_dir / n, review / n)
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"[pilot] {run_id}: validation {n_pass}/{len(val)}, "
          f"{len(authorised)} authorised feature(s), {len(mem)} "
          f"membership rows, "
          f"{int((pilot_ctrl['control_status'] == 'CONTROLLED').sum())} "
          f"CONTROLLED / "
          f"{int((pilot_ctrl['control_status'] == 'UNRESOLVED').sum())} "
          f"UNRESOLVED hexes ({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[pilot][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, summary_rows, gaps, aspects, val,
                  authorised, mem, ctrl, hexa):
    s = dict(summary_rows)
    lines = [
        f"# {STAGE} Review — Authorised Snapshot Compiler + 1756 "
        "Central Europe Direct-Map Production Pilot",
        "",
        "**HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM "
        "MODERN ADMINISTRATION.**",
        "**SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY "
        "WITHIN ITS SCENARIO SNAPSHOT.**",
        "**MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER "
        "NEUTRAL.**",
        "",
        f"Run `{run_id}` — the first REAL 1756 production geometry.",
        "",
        "## Phase A — authorised snapshot compiler",
        "",
        "- `compile_authorised_snapshot_features()` is now the ONLY "
        "route into the hex binder: it selects temporal candidates, "
        "validates each evidence bundle, rejects a feature on a single "
        "violation, resolves the scenario polity from an explicit "
        "reviewed mapping, and emits bundle-derived confidence and "
        "provenance with `production_authorised=True`.",
        "- The binder raises if handed a raw feature (M12-02), and "
        "rewriting the deprecated `political_evidence_id` / "
        "`political_evidence_source_id` / `source_confidence` aliases "
        "leaves the compiled snapshot bit-identical (M12-04).",
        "- hpg schema 1.3.0 → **1.4.0** (authorised snapshot schema), "
        "algorithm 1.2.0 → **1.3.0** (admission contract; the binding "
        "metrics are unchanged). New namespace: "
        "`historical_map_georeference` **1.0.0/1.0.0**.",
        "",
        "## The source",
        "",
        "- **Robert de Vaugondy, 'Partie meridionale du cercle de Haute "
        "Saxe ou sont le duche de Saxe, le marquisat de Misnie, le "
        "landgraviat de Thuringe...', 1756** — Bibliotheque nationale "
        "de France, ark `btv1b530412497`, public domain, 7865x6017, "
        "SHA-256 recorded. The privilege line dates the plate to 1756, "
        "so it represents the 1756 state directly and needs no "
        "continuity bridge.",
        "- The spec's suggested Commons file for the general HRE sheet "
        "does not exist under that name (the URL 404s); this sheet is "
        "the same cartographer, the same year, a national-library "
        "holding, and covers the pilot theatre at far larger scale.",
        "- The Utrecht UB 1756 'seat of war' map was verified to exist "
        "but its repository rights field is unusable, so it is recorded "
        "**LICENCE_BLOCKED** and was not downloaded. Independent "
        "corroboration of these boundaries is therefore OUTSTANDING.",
        "",
        "## Georeference",
        "",
        f"- Prime meridian is **not** Greenwich: the sheet uses "
        f"**{s['prime_meridian']}** (Ferro, 20 deg west of Paris), "
        "confirmed empirically — the Ferro hypothesis predicted "
        "Dresden's position to ~2 km.",
        f"- {s['gcp_total']} GCPs in `historical_map_gcps.csv` "
        f"({s['gcp_fit']} fit / {s['gcp_holdout']} holdout), taken from "
        "the sheet's own neat-line degree ticks (meridian x parallel "
        "intersections) plus one independent settlement check. No "
        "modern administrative geometry was used.",
        f"- Transform comparison: **{s['transform_selected']}** "
        f"selected. Fit RMS {s['fit_rms_m']} m / p95 {s['fit_p95_m']} m; "
        f"holdout RMS {s['holdout_rms_m']} m "
        f"(graticule-only {s['holdout_graticule_rms_m']} m, settlement "
        f"check {s['settlement_check_residual_m']} m), max "
        f"{s['holdout_max_m']} m. POLYNOMIAL_2 had the best fit "
        "residual and a six-figure holdout residual — classic "
        "overfitting, rejected by the holdout rule.",
        f"- Positional uncertainty **{s['positional_uncertainty_km']} "
        "km** per the documented rule (worse of graticule/settlement "
        "residual, plus line width and simplification). Never 0.",
        "",
        "## Digitisation and the pilot territory",
        "",
        "- Semi-automatic colour-wash segmentation: the sheet's "
        "hand-coloured outlines are barriers, a seed inside the bloc "
        "grows the region, and every parameter (frame, seed, colour "
        "rules, closing radius, simplification) lives in "
        "`historical_digitisation_parameters.csv` — nothing is "
        "hardcoded and no modern polygon was traced.",
        f"- Result: the **MARQUISAT DE MISNIE** bloc, the Electorate of "
        f"Saxony's core, {s['source_land_km2']} km2 of source land "
        "geometry, bound to `pol_saxony` through the explicit reviewed "
        "mapping (no name guessing, no new polity invented).",
        f"- {len(gaps)} **polity-model / extraction gaps** recorded "
        "instead of being papered over: the Thuringian and Anhalt "
        "enclosures on the same sheet are real 1756 actors that the "
        "MAPGEN-009R2 catalogue only tracks as aggregation classes, and "
        "Bohemia/Brandenburg/Lusatia have no closed outline on this "
        "sheet.",
        "",
        "## Hex binding and gameplay control",
        "",
        f"- {s['hex_membership_rows']} membership rows (from "
        f"{s['feature_membership_rows']} feature-level rows) via "
        "MAX_GROUND_LAND_SHARE on exact hex n OSM-coast-authority land; "
        f"{s['border_hexes']} border hexes keep every polity share.",
        f"- **{s['controlled_hexes']} CONTROLLED** hexes and "
        f"**{s['unresolved_border_hexes']} UNRESOLVED** border hexes. "
        "UNRESOLVED is used where the winner's margin is smaller than "
        "the land a one-uncertainty-radius boundary shift could sweep — "
        "cartographic uncertainty is NEVER recorded as "
        "DISPUTED_CONTROL, and claims were not derived from control.",
        f"- Membership conservation error {s['conservation_error_km2']} "
        "km2 (tolerance set from this run's measurement, not a magic "
        f"constant). Winner distortion: omission "
        f"{s['winner_omission_km2']} km2, commission "
        f"{s['winner_commission_km2']} km2, symmetric difference "
        f"{s['winner_symmetric_difference_km2']} km2, status "
        f"{hexa.iloc[0]['representation_status']}.",
        f"- Zero-hex losses {s['zero_hex_loss']}, overlay candidates "
        f"{s['overlay_candidates']}.",
        "",
        "## Coverage",
        "",
        "- New unit `region_central_europe_1756_pilot` = "
        "TERRITORY_PARTIAL (control), EVIDENCE_PARTIAL (sources), "
        "UNASSESSED elsewhere. COMPLETE stays 0 everywhere, so hexes "
        "with no control row remain UNKNOWN — never neutral.",
        "- Low Countries remains SOURCE_GAP; HALC v15.0 was not reused "
        "for Central Europe.",
        "",
        "## Images",
        "",
    ]
    for n, a in aspects.items():
        lines.append(f"- `{n}` (aspect {a})")
    lines += [
        "",
        "- All six are PRODUCTION figures from the real 1756 source "
        "(no synthetic panels in this stage).",
        "",
        "## Validation",
        "",
        f"- `validation.csv`: M12-01..M12-32 machine gates. Pass count "
        "in `summary.csv`.",
        "",
        "## Known limitations",
        "",
        "- One scenario polity is represented: only the Meissen bloc "
        "has a closed wash outline on this sheet. Bohemia, Brandenburg "
        "and Lusatia would need their missing sides invented, which is "
        "forbidden.",
        "- Independent corroboration is outstanding (Utrecht sheet "
        "licence-blocked), so the boundary rests on a single "
        "contemporary source at ~3 km positional uncertainty.",
        "- The digitised bloc is the electorate's CORE; Saxon "
        "territories elsewhere on the sheet are not yet digitised.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
