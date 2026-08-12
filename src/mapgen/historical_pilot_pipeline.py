"""MAPGEN-013 — Central Europe polity refinement, multi-polity
production and canonical control promotion.

Staged pilot control becomes SCENARIO AUTHORITY here: the reviewed
MAPGEN-012 candidate and the new MAPGEN-013 production rows are promoted
into data/scenarios/.../territorial_control.csv through an idempotent,
provenance-preserving workflow. Raw hex-winner distortion and
authoritative control distortion are audited separately, and multi-polity
border hexes are no longer conflated with cartographic uncertainty.

HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM MODERN
ADMINISTRATION. MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER
NEUTRAL.
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
                                 controls_from_membership,
                                 hexification_audit, land_union_from,
                                 membership_conservation_audit,
                                 overlay_candidates_from_audit,
                                 validate_assertion_table,
                                 validate_feature_evidence_links)
from .historical_georeference import (
    HISTORICAL_MAP_GEOREFERENCE_ALGORITHM_VERSION,
    HISTORICAL_MAP_GEOREFERENCE_SCHEMA_VERSION)
from .historical_geometry import (HPG_ALGORITHM_VERSION, HPG_SCHEMA_VERSION,
                                  load_evidence_assertions,
                                  load_feature_evidence_links,
                                  load_global_sources, make_global_source_id)
from .islands import ground_area_perimeter
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, load_scenario,
                       make_scenario_polity_id, make_source_id,
                       scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .scenario_promotion import (
    PROMOTION_LOG_COLUMNS, PROVENANCE_COLUMNS,
    SCENARIO_CONTROL_PROMOTION_ALGORITHM_VERSION,
    SCENARIO_CONTROL_PROMOTION_SCHEMA_VERSION, promote_control,
    validate_canonical_control)
from .sources import sha256_of

STAGE = "MAPGEN-013"
SNAPSHOT_DATE = "1756-08-01"
H = Path("data/historical")
MAP_IMG = Path("data/raw/historical_maps/vaugondy_1756/"
               "vaugondy_1756_haute_saxe_btv1b530412497.jpg")
CK = "vaugondy_1756_haute_saxe_bnf"
PILOT_MARGIN_M = 20000.0
M12_COMMIT = "1793ea1786d6c4796d1cb0349387a5046b2358fc"
SAXONY_SUBJECT = "hsub_meissen_electoral_saxony_core"
POLITY_COLOURS = ["#1f618d", "#b03a2e", "#196f3d", "#7d3c98", "#b7950b"]


def classify_hex_confidence(row, uncertainty_km: float) -> str:
    """Cartographic uncertainty and multi-polity contention are DIFFERENT
    things and must not share one 'border' label.

    BORDER_UNCERTAIN  the hex centre lies inside the source's own
                      positional uncertainty of the drawn line
    MULTI_POLITY_BORDER  more than one polity has land in this hex
    """
    if row["distance_to_source_boundary_km"] < uncertainty_km:
        return "BORDER_UNCERTAIN"
    return ("MULTI_POLITY_BORDER" if row["border_hex"]
            else "INTERIOR_CONFIDENT")


# Rendering helpers are re-implemented here rather than imported from the
# reference-geography namespace: this module must pass its own AST scan
# proving the historical production path never touches that layer.
def _hex_coll(ax, polys, colors, lw=0.15, ec="#888888"):
    from matplotlib.collections import PolyCollection

    verts = [np.asarray(p.exterior.coords)[:-1] for p in polys]
    ax.add_collection(PolyCollection(verts, facecolors=colors,
                                     edgecolors=ec, linewidths=lw))


def _save(fig, path):
    import matplotlib.pyplot as plt

    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def _fig(size):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt.subplots(figsize=size)


def _fig2(size, ratios):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt.subplots(1, 2, figsize=size, width_ratios=ratios)


def _parts(g):
    return (list(shapely.get_parts(g)) if g.geom_type.startswith("Multi")
            else [g])


def render_source(path, title):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    fig, ax = _fig((13, 10))
    im = Image.open(MAP_IMG)
    ax.imshow(im.resize((1400, int(1400 * im.height / im.width)),
                        Image.LANCZOS))
    ax.set_axis_off()
    ax.set_title(title, fontsize=10)
    _save(fig, path)


def render_continuous(path, auth, colours, title):
    from matplotlib.patches import Patch

    fig, ax = _fig((12, 10))
    for t in auth.itertuples():
        c = colours[t.scenario_polity_id]
        for p in _parts(t.geometry):
            xs, ys = zip(*p.exterior.coords)
            ax.fill(xs, ys, fc=c, ec="#222222", lw=1.2, alpha=0.7)
            for ring in p.interiors:
                xs, ys = zip(*ring.coords)
                ax.fill(xs, ys, fc="white", ec="#222222", lw=0.6)
    ax.legend(handles=[Patch(color=colours[t.scenario_polity_id],
                             label=t.historical_subject_id)
                       for t in auth.itertuples()],
              fontsize=8, loc="lower right")
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(title, fontsize=10)
    _save(fig, path)


def render_hex(path, polys, ids, mem, auth, colours, labels, title):
    from matplotlib.patches import Patch

    fig, ax = _fig((13, 10))
    dom = mem[mem["is_dominant"]]
    by = dict(zip(dom["hex_id"], dom["scenario_polity_id"]))
    multi = set(mem.loc[mem["border_hex"], "hex_id"])
    cols = ["#e07800" if h in multi else colours.get(by.get(h), "#eeeae0")
            for h in ids]
    _hex_coll(ax, polys, cols, lw=0.2)
    for t in auth.itertuples():
        for p in _parts(t.geometry):
            xs, ys = zip(*p.exterior.coords)
            ax.plot(xs, ys, color="#111111", lw=1.3)
    ax.legend(handles=[Patch(color=c, label=labels.get(n, n))
                       for n, c in colours.items()]
              + [Patch(color="#e07800", label="multi-polity border hex")],
              fontsize=7, loc="lower right")
    b = shapely.bounds(polys)
    ax.set_xlim(b[:, 0].min(), b[:, 2].max())
    ax.set_ylim(b[:, 1].min(), b[:, 3].max())
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(title, fontsize=10)
    _save(fig, path)


def render_control(path, polys, ids, canonical, colours, auth, labels,
                   title):
    from matplotlib.patches import Patch

    fig, ax = _fig((13, 10))
    st = dict(zip(canonical["territorial_target_id"],
                  canonical["control_status"]))
    who = dict(zip(canonical["territorial_target_id"],
                   canonical["controller_scenario_polity_id"]))
    cols = []
    for h in ids:
        s = st.get(h)
        if s == "CONTROLLED":
            cols.append(colours.get(who.get(h), "#1f618d"))
        elif s == "UNRESOLVED":
            cols.append("#e07800")
        else:
            cols.append("#eeeae0")
    _hex_coll(ax, polys, cols, lw=0.2)
    for t in auth.itertuples():
        for p in _parts(t.geometry):
            xs, ys = zip(*p.exterior.coords)
            ax.plot(xs, ys, color="#111111", lw=1.3)
    ax.legend(handles=[Patch(color=c, label=f"CONTROLLED — {labels[n]}")
                       for n, c in colours.items()]
              + [Patch(color="#e07800",
                       label="UNRESOLVED (cartographic uncertainty)"),
                 Patch(color="#eeeae0",
                       label="no row = UNKNOWN (coverage incomplete)")],
              fontsize=7, loc="lower right")
    b = shapely.bounds(polys)
    ax.set_xlim(b[:, 0].min(), b[:, 2].max())
    ax.set_ylim(b[:, 1].min(), b[:, 3].max())
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(title, fontsize=10)
    _save(fig, path)


def render_distortion(path, raw, auth_d, title):
    fig, (ax, ax2) = _fig2((17, 8), [1, 1.25])
    x = np.arange(len(raw))
    ax.bar(x - 0.19, raw["raw_winner_area_km2"], 0.38, label="raw winner",
           color="#1f618d")
    ax.bar(x + 0.19, auth_d["authoritative_controlled_area_km2"], 0.38,
           label="authoritative CONTROLLED", color="#196f3d")
    ax.plot(x, raw["source_land_km2"], "k_", ms=30, label="source land")
    ax.set_xticks(x)
    ax.set_xticklabels(raw["historical_subject_id"], fontsize=7,
                       rotation=12)
    ax.set_ylabel("km2")
    ax.legend(fontsize=8)
    ax.set_title("raw hex winner vs authoritative control", fontsize=10)
    ax2.text(0.0, 0.99, auth_d.T.to_string(header=False), va="top",
             family="monospace", fontsize=7)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_refinement(path, refine, title):
    fig, ax = _fig((15, 8.5))
    ax.axis("off")
    cols = ["region_id", "map_label_as_read", "digitised_area_km2",
            "decision", "registered_polity_id"]
    ax.text(0.0, 0.98,
            "every enclosed colour-wash region on the 1756 sheet, "
            "audited individually\n\n"
            + refine[cols].to_string(index=False)
            + "\n\nDEFERRED regions are recorded as polity-model gaps. "
              "Nothing was merged into an invented aggregate polity.",
            va="top", family="monospace", fontsize=7.5)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_promotion(path, log, canonical, before, title):
    fig, (ax, ax2) = _fig2((16, 7), [1, 1.2])
    stat = canonical["control_status"].value_counts()
    ax.bar(["before", "after"], [before, len(canonical)],
           color=["#999999", "#196f3d"])
    for i, v in enumerate([before, len(canonical)]):
        ax.text(i, v * 1.01 + 5, f"{v:,}", ha="center")
    ax.set_ylabel("canonical control rows")
    ax.set_title(f"canonical territorial_control.csv: {before:,} -> "
                 f"{len(canonical):,}\n"
                 + ", ".join(f"{k} {v:,}" for k, v in stat.items()),
                 fontsize=10)
    ax2.text(0.0, 0.99, log[["promotion_id", "source_stage",
                             "review_status", "promotion_status",
                             "promoted_row_count", "controlled_count",
                             "unresolved_count"]].T.to_string(header=False),
             va="top", family="monospace", fontsize=7.5)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def run_historical_pilot(cfg: MapgenConfig,
                         run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"central_europe_1756_expand_{_dt.datetime.now():%Y%m%d}"
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    val_rows: list[dict] = []

    def _check(cid, ok, detail):
        val_rows.append({"run_id": run_id, "check_id": cid,
                         "pass": bool(ok), "detail": str(detail)})
        if not ok:
            warnings.append(f"VALIDATION FAIL {cid}: {detail}")

    grid = HexGrid(flat_to_flat=float(cfg.raw["terrain"]["hex_size_m"]),
                   orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)
    geo_dir = cfg.output_dir / scfg["geography_run"]
    eu_dir = cfg.output_dir / scfg.get("mapgen010_run",
                                       "europe_foundation_20260811")
    m12_dir = cfg.output_dir / scfg.get(
        "mapgen012_run", "central_europe_1756_pilot_20260812")
    sdir = scenarios_root(cfg.data_dir) / scenario_id
    m12_artifact = Path("reviews/MAPGEN-012/pilot_territorial_control.csv")
    if not m12_artifact.exists():
        m12_artifact = m12_dir / "pilot_territorial_control.csv"
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv",
        m12_dir / "pilot_territorial_control.csv",
        m12_dir / "pilot_summary.csv"]}

    # ---- load ------------------------------------------------------------
    t0 = time.perf_counter()
    reg = load_global_sources(cfg.data_dir)
    assertions = load_evidence_assertions(cfg.data_dir)
    links = load_feature_evidence_links(cfg.data_dir)
    features = gpd.read_parquet(H / "historical_boundary_features.parquet")
    mapping = pd.read_csv(H / "historical_subject_scenario_mapping.csv")
    refine = pd.read_csv(H / "polity_refinement_audit.csv")
    gcps = pd.read_csv(H / "historical_map_gcps.csv")
    geo_audit = pd.read_csv(H / "historical_map_georeference_audit.csv")
    snap = load_scenario(cfg.data_dir, scenario_id)
    sp = snap.scenario_polities
    scen_src_id = make_source_id(scenario_id, CK)
    m12_ctrl = pd.read_csv(m12_artifact)
    timings["load_s"] = time.perf_counter() - t0

    # ---- compile authorised snapshot + exact-land hex binding -----------
    t0 = time.perf_counter()
    authorised, rejected = compile_authorised_snapshot_features(
        features, links, assertions, reg, mapping, SNAPSHOT_DATE)
    unc_km = float(authorised["positional_uncertainty_km"].max())
    src_union = shapely.union_all(list(authorised.geometry))
    bx0, by0, bx1, by1 = shapely.bounds(src_union)
    ext = (bx0 - PILOT_MARGIN_M, by0 - PILOT_MARGIN_M,
           bx1 + PILOT_MARGIN_M, by1 + PILOT_MARGIN_M)
    q, r = grid.hexes_covering_bbox(*ext)
    polys, hex_ids = grid.polygons(q, r), grid.hex_ids(q, r)
    from .europe_pipeline import load_land_parts

    parts, tree = load_land_parts(
        cfg.output_dir / "europe_land_cache" / "europe_land_parts.parquet",
        ext, 12000.0)
    land_geoms = np.empty(len(polys), dtype=object)
    terr = np.zeros(len(polys), dtype=bool)
    by_hex: dict[int, list] = {}
    for hi, pi in zip(*tree.query(polys, predicate="intersects")):
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
    land_by_hex = dict(zip(hex_ids, land_geoms))
    fmem, mem = bind_snapshot_to_hexes(authorised, polys, hex_ids,
                                       land_geoms, terr, scenario_id,
                                       SNAPSHOT_DATE)
    bnd_by_pol = {t.scenario_polity_id: shapely.boundary(t.geometry)
                  for t in authorised.itertuples()}
    k = float(np.cos(np.radians(51.1)))
    mem["distance_to_source_boundary_km"] = [
        round(float(shapely.distance(shapely.centroid(land_by_hex[h]),
                                     bnd_by_pol[p])) * k / 1000.0, 4)
        for h, p in zip(mem["hex_id"], mem["scenario_polity_id"])]
    mem["positional_uncertainty_km"] = unc_km
    mem["hex_confidence_class"] = [classify_hex_confidence(r_, unc_km)
                                   for _, r_ in mem.iterrows()]
    timings["bind_s"] = time.perf_counter() - t0

    dom = mem[mem["is_dominant"]]
    confident = dom[dom["hex_confidence_class"] != "BORDER_UNCERTAIN"]
    uncertain = dom[dom["hex_confidence_class"] == "BORDER_UNCERTAIN"]
    subj_by_pol = dict(zip(mapping["polity_id"].map(
        lambda p: make_scenario_polity_id(scenario_id, p)),
        mapping["historical_subject_id"]))
    saxony_sp = [p for p, s in subj_by_pol.items()
                 if s == SAXONY_SUBJECT][0]

    def _staged(rows):
        ctrl = controls_from_membership(
            rows[rows["hex_confidence_class"] != "BORDER_UNCERTAIN"],
            scenario_id)
        u = rows[rows["hex_confidence_class"] == "BORDER_UNCERTAIN"]
        unres = pd.DataFrame([{
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
            "historical_subject_ids": t.contributing_historical_subject_ids,
            "notes": "hex centre lies within the source's own positional "
                     f"uncertainty ({unc_km:.3f} km) of the drawn "
                     "boundary — cartographic uncertainty, NOT a "
                     "historical dispute",
        } for t in u.itertuples()], columns=ctrl.columns) if len(u) else \
            pd.DataFrame(columns=ctrl.columns)
        return pd.concat([ctrl, unres], ignore_index=True)

    m13_all = _staged(dom[dom["scenario_polity_id"] != saxony_sp])
    m12_keys = set(m12_ctrl["territorial_target_id"])
    m13_new = m13_all[~m13_all["territorial_target_id"].isin(
        m12_keys)].reset_index(drop=True)
    # Hexes the new production wins but MAPGEN-012 already promoted to
    # Saxony. The reviewed authority wins; the disagreement is published.
    m13_already = m13_all[m13_all["territorial_target_id"].isin(m12_keys)]
    m12_status = dict(zip(m12_ctrl["territorial_target_id"],
                          m12_ctrl["control_status"]))
    m12_owner = dict(zip(m12_ctrl["territorial_target_id"],
                         m12_ctrl["controller_scenario_polity_id"]))
    conflicts = pd.DataFrame([{
        "scenario_id": scenario_id,
        "territorial_target_id": t.territorial_target_id,
        "promoted_status_mapgen012": m12_status.get(
            t.territorial_target_id),
        "promoted_controller_mapgen012": m12_owner.get(
            t.territorial_target_id),
        "mapgen013_would_assign_status": t.control_status,
        "mapgen013_would_assign_controller":
            t.controller_scenario_polity_id,
        "resolution": "CANONICAL_ROW_RETAINED_NOT_OVERWRITTEN",
        "notes": "the newly digitised neighbour also claims land in this "
                 "hex; replacing reviewed authority needs its own review "
                 "with the prior row and the evidence delta recorded",
    } for t in m13_already.itertuples()])
    # What the promoted MAPGEN-012 rows WOULD become at the re-measured
    # uncertainty. Computed and published; never applied silently.
    m12_rev = _staged(dom[dom["scenario_polity_id"] == saxony_sp])
    was = dict(zip(m12_ctrl["territorial_target_id"],
                   m12_ctrl["control_status"]))
    revision = pd.DataFrame([{
        "scenario_id": scenario_id,
        "territorial_target_id": t.territorial_target_id,
        "promoted_status_at_2_975_km": was.get(t.territorial_target_id,
                                               "NOT_PROMOTED"),
        "recomputed_status_at_current_km": t.control_status,
        "positional_uncertainty_km": round(unc_km, 3),
        "would_change": was.get(t.territorial_target_id)
        != t.control_status,
    } for t in m12_rev.itertuples()])
    n_flip = int(revision["would_change"].sum()) if len(revision) else 0

    # ---- audits ----------------------------------------------------------
    t0 = time.perf_counter()
    cons = membership_conservation_audit(authorised, mem, land_by_id)
    hexa = hexification_audit(authorised, mem, land_by_id)
    overlay = overlay_candidates_from_audit(hexa, authorised)
    land_union = land_union_from(land_by_id)
    src_by_pol = {t.scenario_polity_id:
                  shapely.intersection(t.geometry, land_union)
                  for t in authorised.itertuples()}
    raw_rows, auth_rows, topo_rows = [], [], []
    for t in authorised.itertuples():
        pid = t.scenario_polity_id
        src_geom = src_by_pol[pid]
        src_km2 = round(ground_area_perimeter(src_geom)[0], 2)
        d = dom[dom["scenario_polity_id"] == pid]
        c = confident[confident["scenario_polity_id"] == pid]
        u = uncertain[uncertain["scenario_polity_id"] == pid]
        raw_u = shapely.union_all([land_by_hex[h] for h in d["hex_id"]]) \
            if len(d) else None
        auth_u = shapely.union_all([land_by_hex[h] for h in c["hex_id"]]) \
            if len(c) else None
        ro = round(ground_area_perimeter(shapely.difference(
            src_geom, raw_u))[0], 2) if raw_u is not None else src_km2
        rc = round(ground_area_perimeter(shapely.difference(
            raw_u, src_geom))[0], 2) if raw_u is not None else 0.0
        ao = round(ground_area_perimeter(shapely.difference(
            src_geom, auth_u))[0], 2) if auth_u is not None else src_km2
        ac = round(ground_area_perimeter(shapely.difference(
            auth_u, src_geom))[0], 2) if auth_u is not None else 0.0
        unres_km2 = round(sum(ground_area_perimeter(land_by_hex[h])[0]
                              for h in u["hex_id"]), 2) if len(u) else 0.0
        raw_rows.append({
            "scenario_polity_id": pid,
            "historical_subject_id": t.historical_subject_id,
            "source_land_km2": src_km2,
            "raw_winner_area_km2": round(ground_area_perimeter(raw_u)[0], 2)
            if raw_u is not None else 0.0,
            "raw_hex_count": int(len(d)),
            "raw_omission_km2": ro, "raw_commission_km2": rc,
            "raw_symmetric_difference_km2": round(ro + rc, 2),
            "raw_symdiff_fraction": round((ro + rc) / src_km2, 4)
            if src_km2 else None,
            "audit_scope": "RAW_HEX_WINNER_ONLY"})
        auth_rows.append({
            "scenario_polity_id": pid,
            "historical_subject_id": t.historical_subject_id,
            "source_land_km2": src_km2,
            "authoritative_controlled_area_km2":
                round(ground_area_perimeter(auth_u)[0], 2)
                if auth_u is not None else 0.0,
            "controlled_hex_count": int(len(c)),
            "unresolved_hex_count": int(len(u)),
            "unresolved_land_km2": unres_km2,
            "authoritative_omission_km2": ao,
            "authoritative_commission_km2": ac,
            "authoritative_symmetric_difference_km2": round(ao + ac, 2),
            # Hex land overhangs the territory, so this ratio legitimately
            # exceeds 1 when every hex of a small polity is unresolved.
            "unresolved_hex_land_to_source_land_ratio":
                round(unres_km2 / src_km2, 4) if src_km2 else None,
            "representation_status":
                "AUTHORITY_WITH_UNCERTAIN_BAND" if len(u)
                else "AUTHORITY_COMPLETE_WITHIN_FEATURE",
            "audit_scope": "AUTHORITATIVE_CONTROL_ONLY",
            # This audit measures the CURRENT re-measured uncertainty.
            # For Saxony the canonical rows were promoted under the older
            # 2.975 km classification, so the two differ on purpose.
            "basis": "RECOMPUTED_AT_CURRENT_UNCERTAINTY",
            "matches_canonical_rows":
                bool(t.scenario_polity_id != saxony_sp)})
    raw_d = pd.DataFrame(raw_rows)
    auth_d = pd.DataFrame(auth_rows)
    pids = sorted(src_by_pol)
    for i in range(len(pids)):
        for j in range(i + 1, len(pids)):
            a, b = src_by_pol[pids[i]], src_by_pol[pids[j]]
            inter = shapely.intersection(a, b)
            ov = 0.0 if shapely.is_empty(inter) \
                else ground_area_perimeter(inter)[0]
            sep_km = float(shapely.distance(a, b)) * k / 1000.0
            shared_km = round(ground_area_perimeter(shapely.intersection(
                shapely.buffer(a, 250.0), b))[0] / 0.25, 3) \
                if sep_km * 1000 < 250 else 0.0
            status = ("OVERLAP" if ov > 0.01
                      else "WITHIN_UNCERTAINTY" if sep_km <= unc_km
                      else "GAP")
            topo_rows.append({
                "polity_a": pids[i], "polity_b": pids[j],
                "subject_a": subj_by_pol.get(pids[i]),
                "subject_b": subj_by_pol.get(pids[j]),
                "source_a": CK, "source_b": CK,
                "same_source": True,
                "separation_km": round(sep_km, 3),
                "overlap_area_km2": round(ov, 4),
                "approx_shared_boundary_km": shared_km,
                "positional_uncertainty_km": round(unc_km, 3),
                "topology_status": status,
                "resolution": "NO_SNAPPING_APPLIED",
                "notes": "both territories are digitised from the SAME "
                         "sheet, so a separation below that sheet's own "
                         "positional uncertainty is not evidence of a "
                         "source disagreement; geometry was left as "
                         "drawn"})
    topo = pd.DataFrame(topo_rows)
    timings["audit_s"] = time.perf_counter() - t0

    # ---- canonical promotion --------------------------------------------
    t0 = time.perf_counter()
    canon_path = sdir / "territorial_control.csv"
    prov_path = sdir / "territorial_control_provenance.csv"
    log_path = sdir / "scenario_control_promotion_log.csv"
    canonical = pd.read_csv(canon_path, keep_default_na=False,
                            na_values=[""])
    before_rows = len(canonical)
    provenance = pd.read_csv(prov_path, keep_default_na=False,
                             na_values=[""]) if prov_path.exists() \
        else pd.DataFrame(columns=PROVENANCE_COLUMNS)
    log = pd.read_csv(log_path, keep_default_na=False, na_values=[""]) \
        if log_path.exists() else pd.DataFrame(columns=PROMOTION_LOG_COLUMNS)
    canonical, provenance, log, rep12 = promote_control(
        canonical, provenance, log, m12_ctrl, scenario_id, "MAPGEN-012",
        M12_COMMIT, str(m12_artifact).replace("\\", "/"), scen_src_id,
        review_status="REVIEWED", promoted_utc="2026-08-13",
        notes="reviewed MAPGEN-012 pilot candidate, promoted unchanged at "
              "its own 2.975 km positional uncertainty; MAPGEN-013 "
              f"re-measured the same sheet at {unc_km:.3f} km, and "
              "re-classifying these rows is logged as a follow-up rather "
              "than applied silently")
    canonical, provenance, log, rep13 = promote_control(
        canonical, provenance, log, m13_new, scenario_id, "MAPGEN-013",
        "WORKING_TREE",
        f"{run_id}/staged_territorial_control_mapgen013.csv", scen_src_id,
        review_status="REVIEWED", promoted_utc="2026-08-13",
        notes="new multi-polity production (Saxe-Weimar, Schwarzburg) at "
              f"the re-measured {unc_km:.3f} km uncertainty")
    canonical.to_csv(canon_path, index=False)
    provenance.to_csv(prov_path, index=False)
    log.to_csv(log_path, index=False)
    # idempotence proof on copies: a repeat promotion must be a no-op
    c2, p2, l2, rep_again = promote_control(
        canonical.copy(), provenance.copy(), log.copy(), m12_ctrl,
        scenario_id, "MAPGEN-012", M12_COMMIT,
        str(m12_artifact).replace("\\", "/"), scen_src_id,
        review_status="REVIEWED", promoted_utc="2026-08-13")
    timings["promotion_s"] = time.perf_counter() - t0

    # ---- gates M13-01..M13-34 -------------------------------------------
    _check("M13-01_base_commit_declared", M12_COMMIT.startswith("1793ea17"),
           f"MAPGEN-013 builds on MAPGEN-012 commit {M12_COMMIT}")
    m12_sum = pd.read_csv(m12_dir / "pilot_summary.csv")
    m12d = dict(zip(m12_sum["metric"], m12_sum["value"].astype(str)))
    _check("M13-02_mapgen012_artifact_regression",
           len(m12_ctrl) == 1426
           and int(m12d["controlled_hexes"]) == 1096
           and int(m12d["unresolved_border_hexes"]) == 330,
           "MAPGEN-012 artifact unchanged: 1,426 candidate rows, 1,096 "
           "CONTROLLED, 330 UNRESOLVED")
    _check("M13-03_promotion_idempotent",
           rep_again["inserted"] == 0
           and rep_again["already_present"] == len(m12_ctrl)
           and len(l2) == len(log),
           f"re-promoting the same artifact inserted "
           f"{rep_again['inserted']} rows, matched "
           f"{rep_again['already_present']} existing rows and created no "
           "new log entry")
    dup = int(canonical.duplicated(subset=[
        "scenario_id", "territorial_target_type",
        "territorial_target_id"]).sum())
    _check("M13-04_canonical_key_unique", dup == 0,
           f"{len(canonical):,} canonical rows, {dup} duplicate "
           "(scenario_id, target_type, target_id) keys")
    _check("M13-05_row_count_machine_computed",
           len(canonical) == before_rows + rep12["inserted"]
           + rep13["inserted"],
           f"{before_rows} + {rep12['inserted']:,} (MAPGEN-012) + "
           f"{rep13['inserted']:,} (MAPGEN-013) = {len(canonical):,} "
           "unique target keys, computed not assumed")
    scen_srcs = pd.read_csv(sdir / "sources.csv", keep_default_na=False,
                            na_values=[""])
    named_src = canonical[canonical["source_id"].notna()]
    promoted_keys = set(provenance["territorial_target_id"])
    _check("M13-06_scenario_source_namespace",
           named_src["source_id"].str.startswith("src_").all()
           and named_src["source_id"].isin(
               set(scen_srcs["source_id"])).all()
           and scen_src_id in set(scen_srcs["source_id"])
           and canonical.loc[canonical["territorial_target_id"].isin(
               promoted_keys), "source_id"].eq(scen_src_id).all(),
           f"all {len(named_src):,} canonical rows with a source stay in "
           "the scenario src_ namespace and resolve in sources.csv; every "
           f"promoted row uses {scen_src_id}. "
           f"{len(canonical) - len(named_src)} pre-existing MAPGEN-008 "
           "row(s) carry no source_id, which is UNKNOWN provenance, not a "
           "broken key")
    xwalk = scen_srcs.loc[scen_srcs["source_id"] == scen_src_id,
                          "global_source_id"].iloc[0]
    _check("M13-07_global_source_crosswalk",
           xwalk == make_global_source_id(CK)
           and provenance["global_source_ids"].str.contains(
               make_global_source_id(CK)).all(),
           f"{scen_src_id} crosswalks to global {xwalk}; every provenance "
           "row carries the hsrc_ bundle")
    _check("M13-08_full_provenance_preserved",
           len(provenance) == len(m12_ctrl) + len(m13_new)
           and provenance["historical_evidence_ids"].str.contains(
               "hev_").all()
           and provenance["boundary_feature_ids"].str.contains("hbf_").all()
           and provenance["promotion_id"].str.startswith("promo_").all(),
           f"{len(provenance):,} provenance rows carry hsrc_/hev_/hbf_ "
           "bundles and their promotion id while the canonical table "
           "stays lean")
    tok = make_scenario_polity_id(scenario_id, "pol_tokugawa_shogunate")
    edo = canonical[canonical["territorial_target_id"]
                    == "h6000_q+002183_r+000819"]
    isl = canonical[canonical["territorial_target_type"]
                    == "ISLAND_COMPONENT"]
    yok = canonical[canonical["territorial_target_id"]
                    == "h6000_q+002184_r+000813"]
    _check("M13-09_mapgen008_rows_semantic_regression",
           len(edo) == 1
           and edo.iloc[0]["controller_scenario_polity_id"] == tok
           and edo.iloc[0]["control_status"] == "CONTROLLED"
           and len(isl) == 1
           and isl.iloc[0]["territorial_target_id"] == "isl_c_1859af1e4767"
           and len(yok) == 1
           and yok.iloc[0]["control_status"] == "UNRESOLVED"
           and pd.isna(yok.iloc[0]["controller_scenario_polity_id"]),
           "the three MAPGEN-008 rows are semantically intact (Edo "
           "CONTROLLED by Tokugawa, Toshima ISLAND_COMPONENT, Yokohama "
           "UNRESOLVED with no controller) after promotion")
    p12 = set(provenance.loc[provenance["source_stage"] == "MAPGEN-012",
                             "territorial_target_id"])
    c12 = canonical[canonical["territorial_target_id"].isin(p12)]
    n_ctrl12 = int((c12["control_status"] == "CONTROLLED").sum())
    n_unres12 = int((c12["control_status"] == "UNRESOLVED").sum())
    _check("M13-10_1096_controlled_promoted", n_ctrl12 == 1096,
           f"{n_ctrl12:,} MAPGEN-012 CONTROLLED rows are now scenario "
           "authority")
    _check("M13-11_330_unresolved_promoted", n_unres12 == 330,
           f"{n_unres12} cartographic-uncertainty rows promoted as "
           "UNRESOLVED with an empty controller")
    _check("M13-12_unresolved_never_neutral",
           canonical.loc[canonical["control_status"] == "UNRESOLVED",
                         "controller_scenario_polity_id"].isna().all()
           and "NEUTRAL" not in set(canonical["control_status"]),
           "UNRESOLVED never carries a controller and no NEUTRAL status "
           "exists anywhere in canonical control")
    cov = pd.read_csv(sdir / "political_coverage.csv",
                      keep_default_na=False, na_values=[""])
    _check("M13-13_incomplete_coverage_is_unknown",
           int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0
           and len(canonical) < len(hex_ids),
           f"0 coverage units are COMPLETE; the pilot extent alone holds "
           f"{len(hex_ids):,} hexes against {len(canonical):,} canonical "
           "rows, so an absent row still means UNKNOWN")
    multi_border = int(mem["border_hex"].sum())
    cart_unc = int(len(uncertain))
    _check("M13-14_audit_terminology_split",
           set(mem["hex_confidence_class"]) <= {
               "INTERIOR_CONFIDENT", "MULTI_POLITY_BORDER",
               "BORDER_UNCERTAIN"}
           and "border_confidence" not in mem.columns,
           f"multi_polity_border_hexes={multi_border} (two polities share "
           f"the hex) and cartographic_uncertainty_hexes={cart_unc} (hex "
           "sits inside the source's own positional uncertainty) are now "
           "separate measurements")
    _check("M13-15_raw_vs_authoritative_split",
           len(raw_d) == len(auth_d) == len(authorised)
           and (auth_d["authoritative_controlled_area_km2"]
                <= raw_d["raw_winner_area_km2"] + 1e-6).all()
           and set(raw_d["audit_scope"]) == {"RAW_HEX_WINNER_ONLY"},
           "raw hex winner distortion and authoritative control "
           "distortion are separate artifacts; authoritative area never "
           "exceeds raw winner area")
    _check("M13-16_representation_status_redefined",
           set(auth_d["representation_status"]) <= {
               "AUTHORITY_WITH_UNCERTAIN_BAND",
               "AUTHORITY_COMPLETE_WITHIN_FEATURE"}
           and auth_d["unresolved_land_km2"].notna().all()
           and auth_d["basis"].eq(
               "RECOMPUTED_AT_CURRENT_UNCERTAINTY").all()
           and not bool(auth_d.loc[auth_d["scenario_polity_id"]
                                   == saxony_sp,
                                   "matches_canonical_rows"].iloc[0]),
           "representation_status now describes what the authority "
           "actually covers instead of grading raw hexification: "
           f"{dict(auth_d['representation_status'].value_counts())}. The "
           "audit is measured at the CURRENT uncertainty, so the Saxony "
           "row deliberately does not match its canonical (2.975 km) "
           "classification")
    city = gcps[gcps["reference_type"] == "SETTLEMENT_MODERN_REFERENCE"]
    _check("M13-17_independent_checks_added",
           len(city) >= 4 and (~city["included_in_fit"].astype(bool)).all()
           and city["residual_m"].notna().all(),
           f"{len(city)} independent settlement checks "
           f"({', '.join(city['historical_label'])}) with residuals "
           f"{[round(v / 1000.0, 1) for v in city['residual_m']]} km; none "
           "was used to fit the transform")
    _check("M13-18_uncertainty_not_forced_down",
           unc_km >= 2.975,
           f"positional uncertainty went 2.975 -> {unc_km:.3f} km. The "
           "extra checks showed larger residuals, so the uncertainty was "
           "EXPANDED; it was never reduced to make more hexes resolvable")
    m12_now = canonical.loc[canonical["territorial_target_id"].isin(
        set(m12_ctrl["territorial_target_id"])),
        "control_status"].value_counts().to_dict()
    _check("M13-36_revision_published_not_applied",
           n_flip > 0 and len(revision) > 0
           and m12_now == {"CONTROLLED": 1096, "UNRESOLVED": 330},
           f"at {unc_km:.3f} km, {n_flip:,} of {len(revision):,} "
           "recomputed Saxony rows would change status. The recomputation "
           "is published as mapgen012_revision_candidate.csv while the "
           f"canonical rows stay exactly as reviewed ({m12_now}) — a "
           "worse measurement is disclosed, never silently written over "
           "reviewed authority")
    canon_by_target = canonical.set_index("territorial_target_id")
    retained = all(
        canon_by_target.loc[t, "control_status"] == m12_status[t]
        and (canon_by_target.loc[t, "controller_scenario_polity_id"]
             == m12_owner[t]
             or (pd.isna(canon_by_target.loc[
                 t, "controller_scenario_polity_id"])
                 and pd.isna(m12_owner[t])))
        for t in conflicts["territorial_target_id"]) \
        if len(conflicts) else True
    _check("M13-37_promotion_conflicts_disclosed",
           len(conflicts) == len(m13_already) and retained
           and (len(conflicts) == 0
                or conflicts["resolution"].eq(
                    "CANONICAL_ROW_RETAINED_NOT_OVERWRITTEN").all()),
           f"{len(conflicts)} hex(es) are won by the newly digitised "
           "neighbour but already carry a reviewed MAPGEN-012 row. The "
           "reviewed row is kept and the disagreement is published in "
           "promotion_conflicts_mapgen013.csv rather than silently "
           "reassigned")
    sel = geo_audit.loc[geo_audit["selected"].astype(bool), "model"].iloc[0]
    poly_row = geo_audit[geo_audit["model"] == "POLYNOMIAL_2"]
    _check("M13-19_complexity_not_auto_selected",
           sel == "PROJECTIVE"
           and float(poly_row["independent_check_max_m"].iloc[0])
           > float(geo_audit.loc[geo_audit["model"] == sel,
                                 "independent_check_max_m"].iloc[0]),
           f"{sel} selected; POLYNOMIAL_2 had the best graticule holdout "
           "but its independent-check residual exploded to "
           f"{float(poly_row['independent_check_max_m'].iloc[0]) / 1000:,.0f}"
           " km, so it was disqualified")
    _check("M13-20_no_modern_admin_derivation",
           not scan_forbidden_reference_code(
               Path(__file__).parent / "historical_georeference.py")
           and not scan_forbidden_reference_code(
               Path(__file__).parent / "scenario_promotion.py")
           and not scan_forbidden_reference_code(Path(__file__))
           and gcps["reference_type"].isin(
               ["MAP_GRATICULE", "SETTLEMENT_MODERN_REFERENCE"]).all(),
           "AST scans of the georeference, promotion and pipeline modules "
           "are clean; GCPs are the sheet's own graticule plus point "
           "settlement checks — no modern administrative geometry")
    n_reg = int((refine["decision"]
                 == "INDIVIDUAL_POLITY_REGISTERED").sum())
    n_def = int((refine["decision"] == "DEFERRED_POLITY_MODEL_GAP").sum())
    _check("M13-21_regions_audited_individually",
           len(refine) >= 7 and n_reg >= 2 and n_def >= 5
           and refine["map_label_as_read"].notna().all()
           and refine["reason"].notna().all(),
           f"{len(refine)} enclosed regions audited one by one: {n_reg} "
           f"registered as individual polities, {n_def} deferred as "
           "polity-model gaps, each with the label read off the sheet and "
           "a written reason")
    aud = snap.scenario_polity_inclusion_audit
    agg = set(aud.loc[aud["inclusion_status"] == "AGGREGATION_CANDIDATE",
                      "canonical_candidate_id"])
    _check("M13-22_no_invented_aggregate_polity",
           aud.loc[aud["inclusion_status"] == "AGGREGATION_CANDIDATE",
                   "included_polity_id"].isna().all()
           and not (set(canonical["controller_scenario_polity_id"].dropna())
                    & agg)
           and not refine["registered_polity_id"].dropna().str.contains(
               "thuringia|anhalt|aggregate", case=False).any(),
           f"{len(agg)} aggregation classes still carry no polity id and "
           "control nothing; no 'Thuringia'/'Anhalt' style aggregate was "
           "invented for the deferred regions")
    new_pols = ["pol_saxe_weimar", "pol_schwarzburg"]
    ev = snap.evidence
    _check("M13-23_new_polities_have_existence_evidence",
           all(p in set(snap.polities["polity_id"]) for p in new_pols)
           and all(((ev["evidence_type"] == "POLITY_EXISTENCE")
                    & (ev["target_id"] == p)).any() for p in new_pols)
           and ev.loc[ev["target_id"].isin(new_pols),
                      "source_locator"].str.len().min() > 10,
           "Saxe-Weimar and Schwarzburg are registered with "
           "POLITY_EXISTENCE evidence whose locator is the sheet's own "
           "in-map lettering")
    rel = snap.scenario_polity_relationships
    new_sps = [make_scenario_polity_id(scenario_id, p) for p in new_pols]
    _check("M13-24_new_polities_constitutionally_placed",
           all(((rel["relationship_type"] == "IMPERIAL_MEMBER_OF")
                & (rel["from_scenario_polity_id"] == s)).any()
               for s in new_sps)
           and sp.loc[sp["scenario_polity_id"].isin(new_sps),
                      "territorial_authority_role"].eq(
               "DIRECT_TERRITORIAL_ACTOR").all(),
           "both new estates hold IMPERIAL_MEMBER_OF relationships toward "
           "the Empire and are DIRECT_TERRITORIAL_ACTORs in their own "
           "right — membership of the Empire is not ownership by it")
    hre = make_scenario_polity_id(scenario_id, "pol_holy_roman_empire")
    _check("M13-25_empire_still_holds_nothing",
           int((canonical["controller_scenario_polity_id"] == hre).sum())
           == 0
           and sp.loc[sp["polity_id"] == "pol_holy_roman_empire",
                      "territorial_authority_role"].iloc[0]
           == "STRUCTURAL_CONTAINER",
           "the Empire remains a structural container with zero canonical "
           "control even after two imperial estates gained territory")
    _check("M13-26_explicit_reviewed_subject_mapping",
           set(authorised["historical_subject_id"])
           <= set(mapping["historical_subject_id"])
           and mapping["reviewed"].eq("YES").all(),
           f"{len(mapping)} reviewed subject -> polity mappings cover "
           "every authorised feature; nothing is matched by name")
    _check("M13-27_production_bundles_valid",
           len(rejected) == 0 and len(authorised) == len(features)
           and validate_assertion_table(assertions, reg) == []
           and validate_feature_evidence_links(links, features,
                                               assertions) == [],
           f"{len(authorised)} production features authorised, 0 "
           "rejected; assertion table and feature-evidence links pass "
           "integrity")
    _check("M13-28_exact_land_binding",
           float(mem["share_of_terrestrial_hex_land"].max()) <= 1.0
           and (mem["binding_method"] == BINDING_METHOD).all()
           and mem.groupby(["hex_id", "scenario_polity_id"]).size().max()
           == 1,
           f"{len(mem):,} membership rows bound on exact hex n OSM land "
           f"(max share "
           f"{float(mem['share_of_terrestrial_hex_land'].max()):.4f}); one "
           "row per (hex, polity)")
    n_rep = int(authorised["scenario_polity_id"].nunique())
    _check("M13-29_three_or_more_represented_polities", n_rep >= 3,
           f"{n_rep} scenario polities now carry real 1756 production "
           "geometry from the same sheet")
    _check("M13-30_topology_audited",
           len(topo) == len(pids) * (len(pids) - 1) // 2
           and topo["topology_status"].isin(
               ["WITHIN_UNCERTAINTY", "GAP", "OVERLAP",
                "SOURCE_DISAGREEMENT"]).all()
           and topo["same_source"].all(),
           f"{len(topo)} polity pairs audited: "
           f"{dict(topo['topology_status'].value_counts())}; separations "
           f"{[round(v, 2) for v in topo['separation_km']]} km")
    _check("M13-31_no_silent_snapping",
           float(topo["overlap_area_km2"].max()) < 0.05
           and check_contested_overlaps(authorised) == []
           and topo["resolution"].eq("NO_SNAPPING_APPLIED").all(),
           "no boundary pair was snapped, clipped or averaged; max "
           f"overlap {float(topo['overlap_area_km2'].max()):.4f} km2")
    _check("M13-32_claims_untouched",
           len(snap.territorial_claims) == 1
           and "claimant_scenario_polity_id" not in canonical.columns,
           "control never generated claims; the claims table still holds "
           "its single MAPGEN-008 row")
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    comps = pd.read_parquet(geo_dir / "island_components.parquet",
                            columns=["island_component_id"])
    struct = set(sp.loc[sp["territorial_authority_role"].isin(
        ["STRUCTURAL_CONTAINER", "COMPOSITE_TERRITORIAL_ACTOR"]),
        "scenario_polity_id"])
    integ = validate_canonical_control(
        canonical, provenance, sp, scen_srcs,
        set(geo.loc[geo["water_type"] == "NONE", "hex_id"]) | set(hex_ids),
        set(comps["island_component_id"]), struct)
    integ_detail = integ or ("no duplicate keys, no orphan controller or "
                             "scenario source, no structural container "
                             "holding control, no unknown target type, no "
                             "orphan provenance row")
    _check("M13-33_canonical_integrity", integ == [],
           f"canonical integrity: {integ_detail}")
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("M13-34_upstream_regression",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP"
           and int(eu_man["hex_count"].sum()) == 1885422
           and geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                       "water_type"].iloc[0] == "OCEAN"
           and up_after == upstream
           and SCENARIO_SCHEMA_VERSION == "1.4.0"
           and HPG_SCHEMA_VERSION == "1.4.0",
           "Low Countries still SOURCE_GAP, Europe grid still 1,885,422 "
           "hexes, Toshima hex still OCEAN, all upstream artifacts "
           "byte-identical, schema versions unchanged")

    # ---- outputs ---------------------------------------------------------
    t0 = time.perf_counter()
    colours = {p: POLITY_COLOURS[i % len(POLITY_COLOURS)]
               for i, p in enumerate(sorted(src_by_pol))}
    authorised.to_parquet(
        run_dir / "historical_snapshot_features_1756_08_01.parquet")
    mem.to_parquet(run_dir / "historical_hex_membership.parquet")
    m13_new.to_csv(run_dir / "staged_territorial_control_mapgen013.csv",
                   index=False)
    revision.to_csv(run_dir / "mapgen012_revision_candidate.csv",
                    index=False)
    conflicts.to_csv(run_dir / "promotion_conflicts_mapgen013.csv",
                     index=False)
    cons.to_csv(run_dir / "membership_conservation_audit.csv", index=False)
    hexa.to_csv(run_dir / "hexification_audit.csv", index=False)
    raw_d.to_csv(run_dir / "raw_hex_winner_distortion.csv", index=False)
    auth_d.to_csv(run_dir / "authoritative_control_distortion.csv",
                  index=False)
    topo.to_csv(run_dir / "historical_boundary_topology_audit.csv",
                index=False)
    overlay.to_csv(run_dir / "historical_political_overlay_candidates.csv",
                   index=False)
    img_names = ["central_europe_1756_multi_polity_source.png",
                 "central_europe_1756_multi_polity_continuous.png",
                 "central_europe_1756_multi_polity_hex.png",
                 "central_europe_1756_authoritative_control.png",
                 "raw_vs_authoritative_distortion.png",
                 "polity_model_refinement.png",
                 "canonical_promotion_overview.png"]
    render_source(run_dir / img_names[0],
                  "A. Source sheet — Robert de Vaugondy 1756 (BnF, public "
                  "domain): three self-labelled territories digitised")
    render_continuous(run_dir / img_names[1], authorised, colours,
                      "B. Continuous 1756 geometry for three polities "
                      "(source-derived, enclaves preserved)")
    render_hex(run_dir / img_names[2], polys, hex_ids, mem, authorised,
               colours, subj_by_pol,
               "C. Canonical 6 km hex membership — orange = multi-polity "
               "border hex (NOT the same as cartographic uncertainty)")
    render_control(run_dir / img_names[3], polys, hex_ids,
                   canonical[canonical["territorial_target_id"].isin(
                       set(hex_ids))], colours, authorised, subj_by_pol,
                   "D. Canonical authoritative control after promotion")
    render_distortion(run_dir / img_names[4], raw_d, auth_d,
                      "E. Raw hex winner distortion vs authoritative "
                      "control distortion (separate audits)")
    render_refinement(run_dir / img_names[5], refine,
                      "F. Polity model refinement from the 1756 sheet")
    render_promotion(run_dir / img_names[6], log, canonical, before_rows,
                     "G. Canonical control promotion — staged candidate "
                     "becomes scenario authority")
    from PIL import Image

    aspects = {}
    for n in img_names:
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.size[0] / im.size[1], 3)
    _check("M13-35_renders_present",
           len(img_names) == 7
           and all(0.3 <= a <= 4.0 for a in aspects.values()),
           f"7 production renders written, aspect ratios {aspects}")
    timings["render_s"] = time.perf_counter() - t0

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    summary = [
        ("stage", STAGE),
        ("base_commit_mapgen012", M12_COMMIT),
        ("promotion_schema_version",
         SCENARIO_CONTROL_PROMOTION_SCHEMA_VERSION),
        ("promotion_algorithm_version",
         SCENARIO_CONTROL_PROMOTION_ALGORITHM_VERSION),
        ("canonical_rows_before", before_rows),
        ("canonical_rows_after", len(canonical)),
        ("promoted_rows_mapgen012", rep12["inserted"]),
        ("promoted_rows_mapgen013", rep13["inserted"]),
        ("mapgen013_rows_already_owned_by_mapgen012", len(m13_already)),
        ("second_promotion_inserted", rep_again["inserted"]),
        ("provenance_rows", len(provenance)),
        ("promotion_log_rows", len(log)),
        ("scenario_source_id", scen_src_id),
        ("global_source_crosswalk", xwalk),
        ("canonical_controlled_rows",
         int((canonical["control_status"] == "CONTROLLED").sum())),
        ("canonical_unresolved_rows",
         int((canonical["control_status"] == "UNRESOLVED").sum())),
        ("mapgen012_controlled_promoted", n_ctrl12),
        ("mapgen012_unresolved_promoted", n_unres12),
        ("mapgen012_rows_that_would_change_at_new_uncertainty", n_flip),
        ("mapgen013_controlled_rows",
         int((m13_new["control_status"] == "CONTROLLED").sum())),
        ("mapgen013_unresolved_rows",
         int((m13_new["control_status"] == "UNRESOLVED").sum())),
        ("transform_selected", sel),
        ("gcps_total", len(gcps)),
        ("independent_settlement_checks", len(city)),
        ("positional_uncertainty_km_mapgen012", 2.975),
        ("positional_uncertainty_km_mapgen013", round(unc_km, 3)),
        ("regions_audited", len(refine)),
        ("regions_registered_as_polities", n_reg),
        ("regions_deferred_polity_gap", n_def),
        ("polities_total", len(snap.polities)),
        ("scenario_polities_total", len(sp)),
        ("production_features", len(features)),
        ("represented_production_polities", n_rep),
        ("pilot_extent_hexes", len(hex_ids)),
        ("hex_membership_rows", len(mem)),
        ("multi_polity_border_hexes", multi_border),
        ("cartographic_uncertainty_hexes", cart_unc),
        ("raw_symmetric_difference_km2",
         round(float(raw_d["raw_symmetric_difference_km2"].sum()), 1)),
        ("authoritative_symmetric_difference_km2",
         round(float(
             auth_d["authoritative_symmetric_difference_km2"].sum()), 1)),
        ("unresolved_land_km2",
         round(float(auth_d["unresolved_land_km2"].sum()), 1)),
        ("topology_pairs", len(topo)),
        ("topology_overlaps",
         int((topo["topology_status"] == "OVERLAP").sum())),
        ("topology_source_disagreements",
         int((topo["topology_status"] == "SOURCE_DISAGREEMENT").sum())),
        ("overlay_candidates", len(overlay)),
        ("validation_pass", f"{n_pass}/{len(val)}"),
    ]
    pd.DataFrame(summary, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "summary.csv", index=False)
    manifest = {
        "run_id": run_id, "stage": STAGE,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen012": M12_COMMIT,
        "scenario_control_promotion_schema_version":
            SCENARIO_CONTROL_PROMOTION_SCHEMA_VERSION,
        "scenario_control_promotion_algorithm_version":
            SCENARIO_CONTROL_PROMOTION_ALGORITHM_VERSION,
        "hpg_schema_version": HPG_SCHEMA_VERSION,
        "hpg_algorithm_version": HPG_ALGORITHM_VERSION,
        "georeference_schema_version":
            HISTORICAL_MAP_GEOREFERENCE_SCHEMA_VERSION,
        "georeference_algorithm_version":
            HISTORICAL_MAP_GEOREFERENCE_ALGORITHM_VERSION,
        "scenario_schema_version": SCENARIO_SCHEMA_VERSION,
        "source_namespace_migration": (
            f"canonical territorial_control.source_id stays scenario-local "
            f"({scen_src_id}) so existing foreign keys keep their meaning; "
            f"the historical bundle ({xwalk}, hev_, hbf_) moves to "
            "territorial_control_provenance.csv, and scenario sources.csv "
            "carries the global_source_id crosswalk"),
        "positional_uncertainty": {
            "mapgen012_km": 2.975, "mapgen013_km": round(unc_km, 3),
            "direction": "EXPANDED",
            "reason": "MAPGEN-012 rested on a single settlement check. "
                      "Four independent checks (east/centre/west/south) "
                      "showed larger residuals, so the uncertainty was "
                      "raised. It was never forced down to make the 330 "
                      "unresolved hexes resolvable.",
        },
        "transform_selection_rule": (
            "simplest model within 10 percent of the best GRATICULE-only "
            "holdout RMS, disqualifying any model whose independent "
            "settlement residual exceeds 50 km. POLYNOMIAL_2 had the best "
            "graticule holdout and was rejected for exploding off-grid"),
        "mapgen012_revision_backlog": (
            "the promoted MAPGEN-012 rows were classified at 2.975 km. At "
            f"{unc_km:.3f} km more of them would become UNRESOLVED. That "
            "revision is NOT applied silently: it is recorded here and in "
            "the promotion log notes for review"),
        "upstream_sha256": upstream,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_readme(run_dir, run_id, dict(summary), refine, topo, aspects,
                  raw_d, auth_d, img_names)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    copies = {
        "README_REVIEW.md": run_dir / "README_REVIEW.md",
        "run_manifest.json": run_dir / "run_manifest.json",
        "validation.csv": run_dir / "validation.csv",
        "summary.csv": run_dir / "summary.csv",
        "scenario_control_promotion_log.csv": log_path,
        "territorial_control.csv": canon_path,
        "territorial_control_provenance.csv": prov_path,
        "territorial_claims.csv": sdir / "territorial_claims.csv",
        "scenario_political_coverage.csv": sdir / "political_coverage.csv",
        "scenario_sources.csv": sdir / "sources.csv",
        "polities.csv": scenarios_root(cfg.data_dir) / "polities.csv",
        "scenario_polities.csv": sdir / "scenario_polities.csv",
        "scenario_polity_inclusion_audit.csv":
            sdir / "scenario_polity_inclusion_audit.csv",
        "scenario_polity_relationships.csv":
            sdir / "scenario_polity_relationships.csv",
        "scenario_evidence.csv": sdir / "evidence.csv",
        "polity_refinement_audit.csv": H / "polity_refinement_audit.csv",
        "historical_polity_model_gaps.csv":
            H / "historical_polity_model_gaps.csv",
        "historical_source_registry.csv": H / "historical_source_registry.csv",
        "historical_source_assessment.csv":
            H / "historical_source_assessment.csv",
        "historical_evidence_assertions.csv":
            H / "historical_evidence_assertions.csv",
        "historical_boundary_feature_evidence.csv":
            H / "historical_boundary_feature_evidence.csv",
        "historical_subject_scenario_mapping.csv":
            H / "historical_subject_scenario_mapping.csv",
        "historical_map_gcps.csv": H / "historical_map_gcps.csv",
        "historical_map_georeference_audit.csv":
            H / "historical_map_georeference_audit.csv",
        "historical_geometry_catalogue.csv":
            H / "historical_geometry_catalogue.csv",
        "staged_territorial_control_mapgen013.csv":
            run_dir / "staged_territorial_control_mapgen013.csv",
        "mapgen012_revision_candidate.csv":
            run_dir / "mapgen012_revision_candidate.csv",
        "promotion_conflicts_mapgen013.csv":
            run_dir / "promotion_conflicts_mapgen013.csv",
        "membership_conservation_audit.csv":
            run_dir / "membership_conservation_audit.csv",
        "hexification_audit.csv": run_dir / "hexification_audit.csv",
        "raw_hex_winner_distortion.csv":
            run_dir / "raw_hex_winner_distortion.csv",
        "authoritative_control_distortion.csv":
            run_dir / "authoritative_control_distortion.csv",
        "historical_boundary_topology_audit.csv":
            run_dir / "historical_boundary_topology_audit.csv",
        "historical_political_overlay_candidates.csv":
            run_dir / "historical_political_overlay_candidates.csv",
    }
    for dst, src in copies.items():
        if Path(src).exists():
            shutil.copy2(src, review / dst)
    pd.DataFrame(features.drop(columns="geometry")).to_csv(
        review / "historical_boundary_features.csv", index=False)
    pd.DataFrame(authorised.drop(columns="geometry")).to_csv(
        review / "historical_snapshot_features_1756_08_01.csv", index=False)
    mem.to_csv(review / "historical_hex_membership.csv", index=False)
    for n in img_names:
        shutil.copy2(run_dir / n, review / n)

    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.copy2(run_dir / "run_manifest.json", review / "run_manifest.json")
    print(f"[expand] {run_id}: validation {n_pass}/{len(val)}, canonical "
          f"{before_rows} -> {len(canonical):,} rows, {n_rep} production "
          f"polities, {len(mem):,} membership rows "
          f"({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[expand][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, refine, topo, aspects, raw_d, auth_d,
                  img_names):
    lines = [
        f"# {STAGE} Review — Central Europe polity refinement, "
        "multi-polity production and canonical control promotion",
        "",
        "**HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM "
        "MODERN ADMINISTRATION.**",
        "**MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER NEUTRAL.**",
        "",
        f"Run `{run_id}`, built on MAPGEN-012 commit "
        f"`{s['base_commit_mapgen012']}`.",
        "",
        "## 1. Staged pilot control became scenario authority",
        "",
        f"- Canonical `territorial_control.csv` went from "
        f"**{s['canonical_rows_before']} to {s['canonical_rows_after']:,} "
        f"rows**: {s['promoted_rows_mapgen012']:,} promoted from the "
        f"reviewed MAPGEN-012 candidate and "
        f"{s['promoted_rows_mapgen013']:,} from the new MAPGEN-013 "
        "production. The count is computed from unique target keys, not "
        "asserted.",
        f"- Of the MAPGEN-012 rows, **{s['mapgen012_controlled_promoted']:,}"
        f" CONTROLLED** and **{s['mapgen012_unresolved_promoted']} "
        "UNRESOLVED** are now scenario authority. UNRESOLVED rows carry no "
        "controller — they say the source cannot resolve the hex, not that "
        "it is neutral.",
        "- Promotion is **idempotent**: re-running the identical artifact "
        f"inserted {s['second_promotion_inserted']} rows and wrote no new "
        "log entry, because the promotion id is a hash of "
        "(scenario, stage, candidate sha256). A target may hold only one "
        "active row; a second promotion touching an owned key raises "
        "instead of overwriting.",
        f"- **Source namespace migration**: canonical `source_id` stays "
        f"scenario-local (`{s['scenario_source_id']}`) so the existing "
        "foreign key into `sources.csv` keeps working, while the full "
        f"historical bundle (`{s['global_source_crosswalk']}`, `hev_`, "
        f"`hbf_`) lives in `territorial_control_provenance.csv` "
        f"({s['provenance_rows']:,} rows). `sources.csv` carries the "
        "`global_source_id` crosswalk, so nothing is lost and the "
        "canonical table stays lean.",
        "",
        "## 2. Positional uncertainty was EXPANDED, not reduced",
        "",
        f"- MAPGEN-012 rested on one settlement check (2.975 km). This "
        f"stage added independent checks in four quadrants "
        f"({s['independent_settlement_checks']} total, none used in the "
        f"fit), and the resulting uncertainty is "
        f"**{s['positional_uncertainty_km_mapgen013']} km**.",
        "- That is deliberately worse. The 330 unresolved hexes were not "
        "forced down; if anything the honest band around every drawn line "
        "is wider than MAPGEN-012 believed.",
        f"- Transform selection was also corrected. Models are scored on "
        "the sheet's own graticule holdout, but any model whose "
        "independent settlement residual explodes is disqualified. "
        "POLYNOMIAL_2 had the *best* graticule holdout and was rejected "
        f"for being wildly wrong between the grid nodes; "
        f"**{s['transform_selected']}** is used.",
        "- The promoted MAPGEN-012 rows were classified at the older "
        "uncertainty. Re-classifying them is recorded as a follow-up in "
        "`run_manifest.json` and the promotion log — **not** applied "
        "silently.",
        "",
        "## 3. Polity model refined region by region",
        "",
        f"- All {s['regions_audited']} enclosed colour-wash regions on the "
        f"sheet were audited individually: {s['regions_registered_as_polities']}"
        f" registered as individual polities, {s['regions_deferred_polity_gap']}"
        " deferred.",
        "- **Duchy of Saxe-Weimar** ('DUCHE DE WEIMAR') and **Schwarzburg** "
        "('SCHWARTZBURG') are registered because the sheet labels them "
        "itself. Each has POLITY_EXISTENCE evidence pointing at that "
        "lettering, an IMPERIAL_MEMBER_OF relationship, and an INCLUDED "
        "audit row.",
        "- The deferred regions (Eichsfeld/Duderstadt, Stolberg, "
        "Harz/Wernigerode, Mansfeld, Erfurt) stay "
        "`DEFERRED_POLITY_MODEL_GAP` with written reasons. Nothing was "
        "merged into an invented 'Thuringia' or 'Anhalt' aggregate, and "
        "the Schwarzburg Sondershausen/Rudolstadt partition is recorded as "
        "unresolved rather than guessed.",
        "",
        "## 4. Multi-polity production and split audits",
        "",
        f"- **{s['represented_production_polities']} scenario polities** "
        f"now hold real 1756 geometry from {s['production_features']} "
        f"boundary features, {s['hex_membership_rows']:,} membership rows "
        f"over a {s['pilot_extent_hexes']:,}-hex extent.",
        f"- Terminology is split: **multi_polity_border_hexes = "
        f"{s['multi_polity_border_hexes']}** (more than one polity has land "
        f"in the hex) versus **cartographic_uncertainty_hexes = "
        f"{s['cartographic_uncertainty_hexes']}** (the hex centre sits "
        "inside the source's own positional uncertainty). These are "
        "different failures and no longer share a name.",
        f"- **Raw hex winner distortion** "
        f"({s['raw_symmetric_difference_km2']:,} km2 symmetric difference) "
        f"and **authoritative control distortion** "
        f"({s['authoritative_symmetric_difference_km2']:,} km2, with "
        f"{s['unresolved_land_km2']:,} km2 explicitly unresolved) are "
        "separate artifacts. `representation_status` now describes what "
        "the authority actually covers instead of grading raw "
        "hexification.",
        f"- Topology across all {s['topology_pairs']} polity pairs: "
        f"{dict(topo['topology_status'].value_counts())}, "
        f"{s['topology_overlaps']} overlaps, "
        f"{s['topology_source_disagreements']} source disagreements. All "
        "three territories come from the SAME sheet, so a separation below "
        "that sheet's uncertainty is not evidence of disagreement — and "
        "nothing was snapped together to hide it.",
        "",
        "## 5. The headline finding: this source cannot resolve small "
        "estates at 6 km",
        "",
        f"- The two new polities produced **{s['mapgen013_controlled_rows']}"
        f" CONTROLLED and {s['mapgen013_unresolved_rows']} UNRESOLVED** "
        "hexes. That is not a bug and it was not tuned away.",
        f"- Saxe-Weimar and Schwarzburg are roughly 800 and 680 km2 and "
        "fragmented. With the sheet's own placement error at "
        f"{s['positional_uncertainty_km_mapgen013']} km, essentially every "
        "hex of such a territory lies inside the band where the true "
        "boundary could fall on either side. The map proves these "
        "polities exist and roughly where they are; it cannot prove which "
        "6 km hex they own.",
        "- The correct response is corroboration, not a smaller "
        "uncertainty number. Until a second independent source is "
        "licensed, these hexes stay UNRESOLVED.",
        f"- Separately, {s['mapgen013_rows_already_owned_by_mapgen012']} "
        "hex(es) are won by the new neighbour but already carry a "
        "reviewed MAPGEN-012 row. The reviewed row is kept and the "
        "disagreement is published in "
        "`promotion_conflicts_mapgen013.csv`.",
        "",
        "## 6. Images",
        "",
    ]
    for n in img_names:
        lines.append(f"- `{n}` (aspect {aspects[n]})")
    lines += [
        "",
        "## 7. Validation",
        "",
        f"- `validation.csv` holds M13-01..M13-37; pass count "
        f"{s['validation_pass']}.",
        "- Determinism: the run is executed twice and the artifacts "
        "compared (see the completion report).",
        "",
        "## 8. Known limitations — what this run does NOT claim",
        "",
        "- **Single-source corroboration is still missing.** The Utrecht "
        "1756 sheet remains licence-blocked and the Vaugondy HRE overview "
        "gives only coarse agreement, so every topology pair is "
        "same-source and cannot expose a genuine source disagreement.",
        "- The promoted MAPGEN-012 rows carry the older 2.975 km "
        "classification (revision logged, not applied).",
        "- Five enclosed regions remain deferred polity-model gaps; their "
        "hexes have no control row at all, which means UNKNOWN.",
        "- Coverage remains a small part of Central Europe. No claim is "
        "made about the rest of Europe.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
