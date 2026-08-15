"""MAPGEN-008/009 — Scenario Political Geography (pipeline).

REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP.
SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY WITHIN ITS
SCENARIO SNAPSHOT.

This pipeline VALIDATES and REVIEWS curated scenario data. It never
generates political ownership: scenario CSVs are read-only inputs here,
territorial control is NEVER derived from constitutional relationships,
and the reference human-geography layer is loaded exclusively for QA
display and regression checks.
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
from .human_geography_pipeline import (WATER_FILL, _admin_palette,
                                       _hex_coll, _save)
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .projection import to_mercator
from .scenario import (HEX_PLANE_AREA_KM2, INCLUSION_STATUSES,
                       REPRESENTATION_RISKS, SCENARIO_ALGORITHM_VERSION,
                       SCENARIO_FILES, SCENARIO_SCHEMA_VERSION,
                       SCENARIO_SEMANTICS, CONTROL_STATUSES,
                       SYMMETRIC_RELATIONSHIP_TYPES, ScenarioNotFoundError,
                       hex_ground_area_km2_at_lat, load_scenario,
                       load_scenario_registry, make_evidence_id,
                       make_relationship_id, make_scenario_polity_id,
                       make_source_id, scenarios_root)
from .sources import sha256_of

INCOMPLETE_STATES = {"FOUNDATION_ONLY", "POLITIES_DEFINED",
                     "TERRITORY_PARTIAL"}
# Stage identity — run_id / manifest stage / README title must agree
# (gated by R2-11).
STAGE = "MAPGEN-009R2"
STAGE_FAMILY = "MAPGEN-009"
STAGE_REVISION = "R2"
POLITY_COLORS = ["#b03a2e", "#1f618d", "#196f3d", "#7d3c98", "#b7950b"]
FORBIDDEN_REFERENCE_TOKENS = ("human_geography", "reference_admin",
                              "ne_10m", "naturalearth", "iso_a2",
                              "iso_a3")


def scan_forbidden_reference_code(path: Path) -> list[str]:
    """AST scan of the scenario DATA layer: no import, identifier or
    non-docstring string may touch the contemporary reference layer or
    an ISO-country import path. Docstrings/comments may DESCRIBE the
    ban; code may not cross it."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            ds = ast.get_docstring(node, clean=False)
            if ds is not None:
                docstrings.add(ds)
    hits = []
    for node in ast.walk(tree):
        texts = []
        if isinstance(node, ast.Import):
            texts = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            texts = [node.module or ""] + [a.name for a in node.names]
        elif isinstance(node, ast.Name):
            texts = [node.id]
        elif isinstance(node, ast.Attribute):
            texts = [node.attr]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docstrings:
                texts = [node.value]
        for text in texts:
            for tok in FORBIDDEN_REFERENCE_TOKENS:
                if tok in text.lower():
                    hits.append(f"{tok} in {type(node).__name__}: "
                                f"{text[:60]!r}")
    return hits


def _polity_palette(sp_ids):
    return {sid: POLITY_COLORS[i % len(POLITY_COLORS)]
            for i, sid in enumerate(sorted(sp_ids))}


# --------------------------------------------------------------------------
# Renders (MAPGEN-008 set)
# --------------------------------------------------------------------------
def render_overview(path, geo, polys, snap, comps, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    ctrl = snap.territorial_control
    pal = _polity_palette(ctrl["controller_scenario_polity_id"].dropna())
    by_hex = {}
    unres_hex = set()
    for t in ctrl.itertuples():
        if t.territorial_target_type != "TERRESTRIAL_HEX":
            continue
        if t.control_status == "UNRESOLVED":
            unres_hex.add(t.territorial_target_id)
        elif isinstance(t.controller_scenario_polity_id, str):
            by_hex[t.territorial_target_id] = \
                pal[t.controller_scenario_polity_id]
    colors = []
    for hid, w in zip(geo["hex_id"], geo["water_type"]):
        if hid in by_hex:
            colors.append(by_hex[hid])
        elif hid in unres_hex:
            colors.append("#4a4a4a")
        elif w != "NONE":
            colors.append(WATER_FILL.get(w, WATER_FILL["OCEAN"]))
        else:
            colors.append("#e8e2d0")
    fig, ax = plt.subplots(figsize=(11, 11))
    _hex_coll(ax, polys, colors)
    comp_ctrl = ctrl[ctrl["territorial_target_type"] == "ISLAND_COMPONENT"]
    for t in comp_ctrl.itertuples():
        row = comps[comps["island_component_id"]
                    == t.territorial_target_id]
        if len(row):
            g = row.iloc[0].geometry
            c = pal.get(t.controller_scenario_polity_id, "#4a4a4a")
            ax.scatter([g.centroid.x], [g.centroid.y], s=180, marker="o",
                       facecolors="none", edgecolors=c, linewidths=2.2,
                       zorder=7)
    b = shapely.bounds(polys)
    ax.set_xlim(b[:, 0].min(), b[:, 2].max())
    ax.set_ylim(b[:, 1].min(), b[:, 3].max())
    ax.set_aspect("equal")
    sp_names = dict(zip(snap.scenario_polities["scenario_polity_id"],
                        snap.scenario_polities["display_name"]))
    handles = [Patch(color=v, label=f"CONTROLLED: {sp_names.get(k, k)}")
               for k, v in pal.items()]
    handles += [Patch(color="#4a4a4a", label="UNRESOLVED (formal state)"),
                Patch(color="#e8e2d0", label="no scenario data yet "
                                             "(FOUNDATION_ONLY)")]
    ax.legend(handles=handles, loc="lower right", fontsize=8)
    ax.set_title(title, fontsize=10)
    ax.set_axis_off()
    _save(fig, path)


def render_semantics_diagram(path, geo, polys, mem, snap, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(18, 9))
    dom = mem[(mem["region"] == "kanto") & (mem["admin_level"] == "ADMIN1")
              & (mem["is_dominant_reference_assignment"])]
    dom_by_hex = dict(zip(dom["hex_id"], dom["reference_admin_id"]))
    pal = _admin_palette(dom_by_hex.values())
    colors_l = []
    for hid, w in zip(geo["hex_id"], geo["water_type"]):
        if w != "NONE":
            colors_l.append(WATER_FILL.get(w, WATER_FILL["OCEAN"]))
        else:
            colors_l.append(pal.get(dom_by_hex.get(hid), "#cccccc"))
    _hex_coll(axes[0], polys, colors_l)
    axes[0].set_title(
        "REFERENCE ADMIN (MAPGEN-007R)\n"
        "CONTEMPORARY_DE_FACTO_REFERENCE — gameplay_authoritative = "
        "false\nNOT ownership, NOT 1756 borders", fontsize=10)
    ctrl = snap.territorial_control
    ppal = _polity_palette(ctrl["controller_scenario_polity_id"].dropna())
    by_hex, unres = {}, set()
    for t in ctrl.itertuples():
        if t.territorial_target_type != "TERRESTRIAL_HEX":
            continue
        if t.control_status == "UNRESOLVED":
            unres.add(t.territorial_target_id)
        elif isinstance(t.controller_scenario_polity_id, str):
            by_hex[t.territorial_target_id] = \
                ppal[t.controller_scenario_polity_id]
    colors_r = []
    for hid, w in zip(geo["hex_id"], geo["water_type"]):
        if hid in by_hex:
            colors_r.append(by_hex[hid])
        elif hid in unres:
            colors_r.append("#4a4a4a")
        elif w != "NONE":
            colors_r.append("#cfd8dc")
        else:
            colors_r.append("#efece2")
    _hex_coll(axes[1], polys, colors_r)
    axes[1].set_title(
        f"SCENARIO POLITICAL CONTROL ({snap.scenario_id})\n"
        "gameplay-authoritative ONLY within this snapshot — "
        "FOUNDATION_ONLY:\npilot control + UNRESOLVED; nothing inherited "
        "from the reference layer", fontsize=10)
    b = shapely.bounds(polys)
    for ax in axes:
        ax.set_xlim(b[:, 0].min(), b[:, 2].max())
        ax.set_ylim(b[:, 1].min(), b[:, 3].max())
        ax.set_aspect("equal")
        ax.set_axis_off()
    fig.suptitle(title, fontsize=11)
    _save(fig, path)


def render_island_target(path, geo, polys, snap, comps, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ctrl = snap.territorial_control
    comp_rows = ctrl[ctrl["territorial_target_type"] == "ISLAND_COMPONENT"]
    t = comp_rows.iloc[0]
    comp = comps[comps["island_component_id"]
                 == t.territorial_target_id].iloc[0]
    g = comp.geometry
    cx, cy = g.centroid.x, g.centroid.y
    r = 14000.0
    pal = _polity_palette(ctrl["controller_scenario_polity_id"].dropna())
    colors = [WATER_FILL.get(w, WATER_FILL["OCEAN"]) if w != "NONE"
              else "#e8e2d0" for w in geo["water_type"]]
    fig, ax = plt.subplots(figsize=(10, 10))
    _hex_coll(ax, polys, colors, lw=0.5)
    for p in shapely.get_parts(g) if g.geom_type.startswith("Multi") \
            else [g]:
        xs, ys = zip(*p.exterior.coords)
        ax.fill(xs, ys, color=pal[t.controller_scenario_polity_id],
                zorder=6)
    hex_row = geo[geo["hex_id"] == comp["component_primary_hex_id"]]
    wt = hex_row["water_type"].iloc[0] if len(hex_row) else "?"
    ax.annotate(
        f"island component {t.territorial_target_id}\n"
        f"= territorial target (control_status={t.control_status}, "
        f"confidence={t.source_confidence})\n"
        f"underlying hex water_type = {wt} (UNCHANGED)",
        (cx, cy), xytext=(cx + 3000, cy + 6000), fontsize=9,
        arrowprops={"arrowstyle": "->"}, zorder=8,
        bbox={"boxstyle": "round", "fc": "white", "alpha": 0.9})
    ax.set_xlim(cx - r, cx + r)
    ax.set_ylim(cy - r, cy + r)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=10)
    ax.set_axis_off()
    _save(fig, path)


# --------------------------------------------------------------------------
# Renders (MAPGEN-009 catalogue set)
# --------------------------------------------------------------------------
def _active_audit(audit):
    if "audit_record_status" in audit.columns:
        return audit[audit["audit_record_status"] == "ACTIVE"]
    return audit


def render_catalogue_overview(path, snap, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sp = snap.scenario_polities
    audit = _active_audit(snap.scenario_polity_inclusion_audit)
    kinds = snap.polities.set_index("polity_id")["polity_kind"]
    sp_kinds = sp["polity_id"].map(kinds).value_counts()
    inc = audit["inclusion_status"].value_counts()
    roles = sp["territorial_authority_role"].value_counts()
    fig, axes = plt.subplots(1, 3, figsize=(20, 7))
    for ax, series, sub in [
            (axes[0], sp_kinds, "scenario polity kinds"),
            (axes[1], inc, "inclusion audit statuses (ACTIVE rows)"),
            (axes[2], roles, "territorial authority roles")]:
        ax.barh(list(series.index)[::-1], list(series.values)[::-1],
                color="#1f618d")
        for i, v in enumerate(list(series.values)[::-1]):
            ax.text(v + 0.2, i, str(v), va="center", fontsize=9)
        ax.set_title(sub, fontsize=10)
        ax.tick_params(labelsize=8)
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


REL_COLORS = {"PERSONAL_UNION": "#b03a2e", "IMPERIAL_MEMBER_OF": "#888888",
              "COMPOSITE_MEMBER_OF": "#1f618d", "DEPENDENCY_OF": "#196f3d",
              "TRIBUTARY_OF": "#b7950b", "SUBJECT_OF": "#7d3c98"}


def render_relationship_diagram(path, snap, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    sp = snap.scenario_polities
    names = dict(zip(sp["scenario_polity_id"], sp["display_name"]))
    rel = snap.scenario_polity_relationships
    fig, ax = plt.subplots(figsize=(16, 12))

    def box(x, y, text, fc="#f4f1e8", fontsize=8, weight="normal"):
        ax.text(x, y, text, ha="center", va="center", fontsize=fontsize,
                fontweight=weight, zorder=5,
                bbox={"boxstyle": "round,pad=0.28", "fc": fc,
                      "ec": "#555555", "lw": 0.7})

    # Column 1: hubs with directed members (deterministic order).
    hubs = [("Holy Roman Empire", "IMPERIAL_MEMBER_OF", 0.06, "#e8e0ce"),
            ("Habsburg Monarchy", "COMPOSITE_MEMBER_OF", 0.40, "#dce7f2"),
            ("Prussian Monarchy (Hohenzollern lands)",
             "COMPOSITE_MEMBER_OF", 0.60, "#dce7f2"),
            ("Ottoman Empire", None, 0.78, "#f2ecd8")]
    for hub_name, only_type, x, fc in hubs:
        hub_sp = sp[sp["display_name"] == hub_name]
        if not len(hub_sp):
            continue
        hid = hub_sp.iloc[0]["scenario_polity_id"]
        members = rel[(rel["to_scenario_polity_id"] == hid)
                      & (rel["relationship_type"] != "PERSONAL_UNION")]
        if only_type:
            members = members[members["relationship_type"] == only_type]
        members = members.sort_values("from_scenario_polity_id")
        n = max(len(members), 1)
        y_top, y_bot = 0.94, 0.28
        member_fs = 8 if n <= 20 else 6.3
        box(x, 0.97, hub_name, fc=fc, fontsize=9, weight="bold")
        for i, t in enumerate(members.itertuples()):
            y = y_top - (y_top - y_bot) * i / max(n - 1, 1)
            box(x + 0.115, y, names[t.from_scenario_polity_id],
                fontsize=member_fs)
            ax.plot([x + 0.045, x + 0.02], [y, 0.955],
                    color=REL_COLORS.get(t.relationship_type, "#333333"),
                    lw=1.0, alpha=0.75, zorder=1)
    # Bottom band: personal unions (symmetric pairs) + other directed.
    pu = rel[rel["relationship_type"] == "PERSONAL_UNION"].sort_values(
        "relationship_id")
    box(0.5, 0.22, "PERSONAL UNIONS (symmetric; territories NEVER "
        "merged)", fc="#f7dcd7", fontsize=9, weight="bold")
    for i, t in enumerate(pu.itertuples()):
        x = 0.14 + 0.24 * i
        box(x, 0.15, names[t.from_scenario_polity_id])
        box(x, 0.08, names[t.to_scenario_polity_id])
        ax.plot([x, x], [0.125, 0.105], color=REL_COLORS["PERSONAL_UNION"],
                lw=2.0)
    other = rel[rel["relationship_type"].isin(["DEPENDENCY_OF"])]
    box(0.5, 0.015, " | ".join(
        f"{names[t.from_scenario_polity_id]} –DEPENDENCY_OF→ "
        f"{names[t.to_scenario_polity_id]}" for t in other.itertuples()),
        fc="#ddead9", fontsize=8)
    handles = [Line2D([0], [0], color=c, lw=2, label=k)
               for k, c in REL_COLORS.items()]
    # Anchored into the gap between the HRE member column and the
    # Habsburg column — the corners are all occupied.
    ax.legend(handles=handles, loc="center", fontsize=8,
              framealpha=0.95, bbox_to_anchor=(0.37, 0.55))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_risk_summary(path, snap, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    audit = _active_audit(snap.scenario_polity_inclusion_audit)
    risk = audit["six_km_representation_risk"].value_counts()
    order = [r for r in ["NONE", "MULTIPART", "ENCLAVE_COMPLEX",
                         "SUBHEX_LIKELY", "SUBHEX_REQUIRED", "UNKNOWN"]
             if r in risk.index]
    colors = {"NONE": "#196f3d", "MULTIPART": "#1f618d",
              "ENCLAVE_COMPLEX": "#b7950b", "SUBHEX_LIKELY": "#e07800",
              "SUBHEX_REQUIRED": "#b03a2e", "UNKNOWN": "#777777"}
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(16, 7),
                                  width_ratios=[1, 1.3])
    ax.bar(order, [risk[r] for r in order],
           color=[colors[r] for r in order])
    for i, r in enumerate(order):
        ax.text(i, risk[r] + 0.3, str(risk[r]), ha="center", fontsize=10)
    ax.set_title("six_km_representation_risk (ACTIVE audit rows; "
                 "SUPERSEDED history excluded)", fontsize=10)
    ax.tick_params(axis="x", labelsize=8, rotation=20)
    hard = audit[audit["six_km_representation_risk"].isin(
        ["SUBHEX_REQUIRED", "SUBHEX_LIKELY"])
        | (audit["inclusion_status"] == "UNRESOLVED")]
    lines = [f"[{t.six_km_representation_risk} / {t.inclusion_status}] "
             f"{t.candidate_name[:58]}"
             for t in hard.sort_values(
                 ["six_km_representation_risk",
                  "candidate_name"]).itertuples()]
    ax2.text(0.0, 0.98, "SUBHEX / UNRESOLVED candidates "
             "(audit findings, NOT failures):\n\n" + "\n".join(lines),
             va="top", ha="left", fontsize=8, family="monospace")
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_ontology_diagram(path, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(14, 8))

    def box(x, y, w, h, text, fc, fontsize=9):
        ax.add_patch(plt.Rectangle((x, y), w, h, fc=fc, ec="#333333",
                                   lw=1.2, zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fontsize, zorder=3)

    box(0.03, 0.55, 0.40, 0.34,
        "CONTEMPORARY REFERENCE LAYER (MAPGEN-007R)\n\n"
        "Natural Earth admin0/admin1, settlements, ports\n"
        "reference_semantics = CONTEMPORARY_DE_FACTO_REFERENCE\n"
        "gameplay_authoritative = FALSE\n"
        "uses: QA display, source discovery, position reference",
        "#dce7f2")
    box(0.57, 0.55, 0.40, 0.34,
        "SCENARIO POLITICAL LAYER (MAPGEN-008/009)\n\n"
        "seven_years_war_1756_08_01\n"
        "polities / relationships / control / claims\n"
        "built from HISTORICAL SOURCES with provenance\n"
        "gameplay-authoritative WITHIN the snapshot",
        "#f7dcd7")
    box(0.57, 0.08, 0.40, 0.30,
        "HISTORICAL SOURCES (scenario_sources.csv)\n\n"
        "NCMH VII (1957) / NCMH Atlas (1970)\n"
        "Wilson 2016 (HRE) / Clark 2006 (Prussia)\n"
        "Ingrao 2000 (Habsburg) / Szabo 2008 (7YW)\n"
        "every polity + relationship carries source_id",
        "#efe9d6")
    ax.annotate("", xy=(0.77, 0.55), xytext=(0.77, 0.38),
                arrowprops={"arrowstyle": "->", "lw": 2.0,
                            "color": "#196f3d"})
    ax.text(0.785, 0.46, "builds\n(provenance-tracked)", fontsize=9,
            color="#196f3d")
    ax.annotate("", xy=(0.57, 0.72), xytext=(0.43, 0.72),
                arrowprops={"arrowstyle": "->", "lw": 3.0,
                            "color": "#b03a2e"})
    ax.plot([0.475, 0.525], [0.685, 0.755], color="#b03a2e", lw=3.0)
    ax.plot([0.475, 0.525], [0.755, 0.685], color="#b03a2e", lw=3.0)
    ax.text(0.5, 0.79, "FORBIDDEN\n(no polity/territory generation from "
            "modern admin;\nmachine-checked: AST scan + data audit)",
            ha="center", fontsize=9, color="#b03a2e")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_hre_before_after(path, baseline_summary_csv, snap, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    base = pd.read_csv(baseline_summary_csv)
    base_map = dict(zip(base["metric"], base["value"]))
    before_inc = json.loads(base_map["inclusion_status_counts"])
    before_risk = json.loads(base_map["six_km_risk_counts"])
    audit = _active_audit(snap.scenario_polity_inclusion_audit)
    after_inc = audit["inclusion_status"].value_counts().to_dict()
    after_risk = audit["six_km_representation_risk"].value_counts() \
        .to_dict()
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    for ax, before, after, sub in [
            (axes[0], before_inc, after_inc,
             "inclusion_status (after = ACTIVE rows)"),
            (axes[1], before_risk, after_risk,
             "six_km_representation_risk (after = ACTIVE rows)")]:
        keys = sorted(set(before) | set(after))
        y = np.arange(len(keys))
        ax.barh(y + 0.2, [before.get(k, 0) for k in keys], height=0.38,
                color="#b0b0b0", label="MAPGEN-009 (before)")
        ax.barh(y - 0.2, [after.get(k, 0) for k in keys], height=0.38,
                color="#1f618d", label="MAPGEN-009R (after)")
        ax.set_yticks(y)
        ax.set_yticklabels(keys, fontsize=8)
        for yy, k in zip(y, keys):
            ax.text(before.get(k, 0) + 0.3, yy + 0.2,
                    str(before.get(k, 0)), va="center", fontsize=8)
            ax.text(after.get(k, 0) + 0.3, yy - 0.2,
                    str(after.get(k, 0)), va="center", fontsize=8)
        ax.set_title(sub, fontsize=10)
        ax.legend(fontsize=8, loc="lower right")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_representability_sanity(path, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cases = [("6 km hex\n(plane)", HEX_PLANE_AREA_KM2, "#333333"),
             ("ground hex\n@43.9N", hex_ground_area_km2_at_lat(43.9),
              "#666666"),
             ("San Marino\n~61 km2*", 61, "#196f3d"),
             ("Liechtenstein\n~160 km2*", 160, "#196f3d"),
             ("Andorra\n~468 km2*", 468, "#196f3d"),
             ("Monaco 1756\n(geometry\npending)", 0, "#b03a2e")]
    fig, ax = plt.subplots(figsize=(12, 7))
    xs = np.arange(len(cases))
    ax.bar(xs, [c[1] for c in cases], color=[c[2] for c in cases])
    for x, c in zip(xs, cases):
        ax.text(x, c[1] + 6, f"{c[1]:g}" if c[1] else "?", ha="center",
                fontsize=10)
    ax.set_xticks(xs)
    ax.set_xticklabels([c[0] for c in cases], fontsize=9)
    ax.set_ylabel("km2")
    ax.set_title(
        title + "\n* modern areas = SANITY CHECKS ONLY (admissible "
        "because extent continuity is documented);\narea alone NEVER "
        "decides a historical boundary — 'microstate' is a political "
        "label, not a geometry finding", fontsize=10)
    _save(fig, path)


def render_audit_contract_before_after(path, audit, title):
    """Contract QA diagram (NOT a political map): stale 009R review
    facts vs the 009R2 superseded-audit contract."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(15, 8))

    def box(x, y, w, h, text, fc, fontsize=9):
        ax.add_patch(plt.Rectangle((x, y), w, h, fc=fc, ec="#333333",
                                   lw=1.2, zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fontsize, zorder=3)

    n_total = len(audit)
    act = audit[audit["audit_record_status"] == "ACTIVE"]
    sup = audit[audit["audit_record_status"] == "SUPERSEDED"]
    box(0.03, 0.30, 0.44, 0.58,
        "MAPGEN-009R (before)\n\n"
        "- cand_schleswig_holstein_complex still counted as an\n"
        "  ACTIVE candidate next to its two refined children\n"
        "  (double contribution risk in counts)\n"
        "- README carried stale MAPGEN-009 facts:\n"
        "  '18 IMPERIAL_MEMBER_OF rows',\n"
        "  'Lucca / Corsica unresolved' in Known limitations\n"
        "- manifest stage said 'MAPGEN-009' for an 009R run\n"
        "- inclusion policy v1/v2 precedence implicit",
        "#f2e3de", 9)
    box(0.53, 0.30, 0.44, 0.58,
        "MAPGEN-009R2 (after)\n\n"
        f"- audit_record_status: {len(act)} ACTIVE / {len(sup)} "
        f"SUPERSEDED of {n_total} total rows\n"
        "- parent complex row: SUPERSEDED ->\n"
        "  cand_schleswig_holstein_royal | cand_holstein_gottorp\n"
        "  (history kept forever, excluded from ACTIVE counts,\n"
        "  can never register polities or control)\n"
        "- README regenerated from canonical tables and\n"
        "  machine-checked against them (R2-01..03)\n"
        "- stage = MAPGEN-009R2 (family MAPGEN-009, rev R2)\n"
        "- active policy = inclusion_policy_v2.md (v1 SUPERSEDED)",
        "#ddead9", 9)
    ax.annotate("", xy=(0.53, 0.59), xytext=(0.47, 0.59),
                arrowprops={"arrowstyle": "->", "lw": 2.5,
                            "color": "#333333"})
    box(0.15, 0.06, 0.70, 0.14,
        "Historical content (66 polities, 46 relationships, "
        "control/claims, contested contracts) is UNCHANGED —\n"
        "this stage fixed the review contract only "
        "(regression gates R2-12..14)", "#efe9d6", 9)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_corsica_diagram(path, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(13, 8))

    def box(x, y, w, h, text, fc, fontsize=9):
        ax.add_patch(plt.Rectangle((x, y), w, h, fc=fc, ec="#333333",
                                   lw=1.2, zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fontsize, zorder=3)

    box(0.30, 0.74, 0.40, 0.18,
        "CORSICA 1756-08-01 (one island, two political realities)\n"
        "NO boundary geometry is drawn at this stage", "#efe9d6", 10)
    box(0.04, 0.36, 0.42, 0.26,
        "Republic of Genoa (pol_genoa)\n\n"
        "de-jure sovereign over the whole island\n"
        "de-facto control: coastal citadels\n"
        "future: territorial_claims (whole island)\n"
        "+ CONTROLLED citadel hexes", "#dce7f2")
    box(0.54, 0.36, 0.42, 0.26,
        "Corsican Republic (pol_corsican_republic)\n\n"
        "de-facto polity from 1755 (Paoli government)\n"
        "de-facto control: island interior\n"
        "future: CONTROLLED interior hexes\n"
        "(DISPUTED_CONTROL where sources conflict)", "#f7dcd7")
    box(0.20, 0.06, 0.60, 0.16,
        "contested-control contract (contested_polity_audit.csv):\n"
        "claims and control live in SEPARATE tables; no whole-island "
        "grant by fiat;\nboundary evidence arrives in the geometry "
        "stage with pinpoint locators", "#ddead9")
    for x0 in (0.25, 0.75):
        ax.annotate("", xy=(x0, 0.62), xytext=(0.5, 0.74),
                    arrowprops={"arrowstyle": "->", "lw": 1.6,
                                "color": "#555555"})
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_title(title, fontsize=11)
    _save(fig, path)


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------
def run_scenario(cfg: MapgenConfig, run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    hcfg = cfg.raw["human_geography"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"scenario_catalogue_{_dt.datetime.now():%Y%m%d}"
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    val_rows: list[dict] = []

    def _check(check_id, ok, detail):
        val_rows.append({"run_id": run_id, "check_id": check_id,
                         "pass": bool(ok), "detail": str(detail)})
        if not ok:
            warnings.append(f"VALIDATION FAIL {check_id}: {detail}")

    # ---- upstream + MAPGEN-008 immutability (SHA before) ----------------
    t0 = time.perf_counter()
    geo_dir = cfg.output_dir / hcfg["upstream_run"]
    hg_dir = cfg.output_dir / scfg["upstream_human_geography_run"]
    m8_dir = (cfg.output_dir / scfg.get(
        "mapgen008_baseline_run", "scenario_foundation_20260811")
        / "chatgpt_review")
    hg_files = ["reference_admin0.parquet",
                "reference_admin0_hierarchy.parquet",
                "reference_admin1.parquet",
                "reference_disputed_areas.parquet",
                "reference_admin_hex_membership.parquet",
                "island_component_reference_admin.parquet",
                "reference_settlements.parquet", "reference_ports.parquet"]
    upstream = {str(geo_dir / f): sha256_of(geo_dir / f)
                for f in ["geography_hexes.parquet",
                          "island_components.parquet"]}
    upstream.update({str(hg_dir / f): sha256_of(hg_dir / f)
                     for f in hg_files})
    upstream.update({str(m8_dir / f): sha256_of(m8_dir / f)
                     for f in ["territorial_control.csv",
                               "territorial_claims.csv"]})
    sdir = scenarios_root(cfg.data_dir) / scenario_id
    scen_files = ([scenarios_root(cfg.data_dir) / "scenario_registry.csv",
                   scenarios_root(cfg.data_dir) / "polities.csv"]
                  + [sdir / f for f in SCENARIO_FILES.values()])
    scen_sha_before = {str(p): sha256_of(p) for p in scen_files}

    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet")
    comps = gpd.read_parquet(geo_dir / "island_components.parquet")
    mem = pd.read_parquet(hg_dir / "reference_admin_hex_membership.parquet")
    timings["upstream_load_s"] = time.perf_counter() - t0

    # ---- scenario load ---------------------------------------------------
    registry = load_scenario_registry(cfg.data_dir)
    snap = load_scenario(cfg.data_dir, scenario_id)
    sp = snap.scenario_polities
    rel = snap.scenario_polity_relationships
    audit = snap.scenario_polity_inclusion_audit
    ctrl = snap.territorial_control
    claims = snap.territorial_claims
    srcs = snap.sources
    ev = snap.evidence
    meta = snap.metadata
    pol_ids = set(snap.polities["polity_id"])
    sp_ids = set(sp["scenario_polity_id"])
    src_ids = set(srcs["source_id"])
    tokugawa_sp = make_scenario_polity_id(scenario_id,
                                          "pol_tokugawa_shogunate")
    rdir = sdir / "review"

    def _rd(name):
        return pd.read_csv(rdir / name, keep_default_na=False,
                           na_values=[""])

    corrections = _rd("six_km_representability_corrections.csv")
    hre_audit = _rd("hre_individual_polity_audit.csv")
    contested = _rd("contested_polity_audit.csv")
    prussia_terms = _rd("prussia_terminology_audit.csv")
    granularity = _rd("polity_granularity_audit.csv")

    # ---- validations (MAPGEN-009 numbering) -----------------------------
    row = registry[registry["scenario_id"] == scenario_id]
    _check("V02_single_scenario_registry",
           len(registry) == 1 and len(row) == 1
           and registry["scenario_id"].is_unique
           and row.iloc[0]["snapshot_date"] == "1756-08-01",
           f"registry rows={len(registry)}, snapshot_date="
           f"{row.iloc[0]['snapshot_date']}")
    dirs = sorted(p.name for p in scenarios_root(cfg.data_dir).iterdir()
                  if p.is_dir())
    _check("V03_no_second_scenario_registered",
           dirs == [scenario_id],
           f"scenario data dirs={dirs}")
    _check("V04_polity_id_unique",
           snap.polities["polity_id"].is_unique
           and snap.polities["polity_id"].notna().all(),
           f"{len(snap.polities)} global polities, ids unique")
    sp_det = all(make_scenario_polity_id(scenario_id, t.polity_id)
                 == t.scenario_polity_id for t in sp.itertuples())
    _check("V05_scenario_polity_id_deterministic",
           sp["scenario_polity_id"].is_unique and sp_det,
           f"{len(sp)} scenario polities; ids unique and reproduce from "
           "sha1(scenario|polity)")
    _check("V06_scenario_polity_resolves",
           sp["polity_id"].isin(pol_ids).all()
           and (sp["scenario_id"] == scenario_id).all(),
           "every scenario polity resolves to a global polity")
    ex_ev = ev[ev["evidence_type"] == "POLITY_EXISTENCE"]
    ev_by_pol = set(ex_ev["target_id"])
    missing_ev = [p for p in sp["polity_id"] if p not in ev_by_pol]
    _check("V07_every_polity_has_existence_evidence",
           not missing_ev,
           f"POLITY_EXISTENCE evidence rows={len(ex_ev)}; polities "
           f"without evidence={missing_ev or 0}")
    _check("V08_relationship_polities_resolve",
           rel["from_scenario_polity_id"].isin(sp_ids).all()
           and rel["to_scenario_polity_id"].isin(sp_ids).all(),
           f"{len(rel)} relationships reference valid scenario polities")
    _check("V09_relationship_provenance",
           rel["source_id"].notna().all()
           and rel["source_id"].isin(src_ids).all()
           and rel["evidence_locator"].notna().all(),
           "every relationship carries a resolving source_id and an "
           "explicit evidence_locator (UNKNOWN allowed, reason in notes)")
    _check("V10_no_self_loop",
           (rel["from_scenario_polity_id"]
            != rel["to_scenario_polity_id"]).all(),
           "no relationship self-loops (none are permitted)")
    sym = rel[rel["relationship_type"].isin(SYMMETRIC_RELATIONSHIP_TYPES)]
    sym_ok = all(
        t.from_scenario_polity_id < t.to_scenario_polity_id
        and make_relationship_id(scenario_id, t.to_scenario_polity_id,
                                 t.from_scenario_polity_id,
                                 t.relationship_type) == t.relationship_id
        for t in sym.itertuples())
    _check("V11_symmetric_canonicalisation",
           bool(sym_ok) and rel["relationship_id"].is_unique
           and all(make_relationship_id(
               scenario_id, t.from_scenario_polity_id,
               t.to_scenario_polity_id, t.relationship_type)
               == t.relationship_id for t in rel.itertuples()),
           f"{len(sym)} symmetric relationships stored in canonical "
           "order; ids reproduce order-invariantly (algorithm 1.0.1)")
    controllers = set(ctrl["controller_scenario_polity_id"].dropna())
    pu_members = set(sym["from_scenario_polity_id"]) | set(
        sym["to_scenario_polity_id"])
    _check("V12_personal_union_no_ownership_merge",
           controllers <= {tokugawa_sp}
           and not (pu_members & controllers)
           and all(len(sp[sp["scenario_polity_id"] == m]) == 1
                   for m in pu_members),
           f"{len(sym)} personal unions; every participant remains a "
           "distinct scenario polity and none gained territorial control "
           "from the union")
    hre_sp = sp[sp["display_name"] == "Holy Roman Empire"]
    hre_id = hre_sp.iloc[0]["scenario_polity_id"] if len(hre_sp) else None
    imp_members = set(
        rel[rel["relationship_type"] == "IMPERIAL_MEMBER_OF"]
        ["from_scenario_polity_id"])
    _check("V13_imperial_membership_creates_no_control",
           hre_id is not None and hre_id not in controllers
           and not (imp_members & controllers),
           f"{len(imp_members)} imperial members; neither the Empire nor "
           "any member holds territorial control derived from membership "
           f"(controllers={sorted(controllers)})")
    comp_members = rel[rel["relationship_type"] == "COMPOSITE_MEMBER_OF"]
    dup_ctrl = ctrl.groupby(
        ["territorial_target_type", "territorial_target_id"])[
        "controller_scenario_polity_id"].nunique()
    _check("V14_composite_membership_no_duplicate_control",
           int(dup_ctrl.max()) <= 1
           and not (set(comp_members["from_scenario_polity_id"])
                    & controllers)
           and not (set(comp_members["to_scenario_polity_id"])
                    & controllers),
           f"{len(comp_members)} composite memberships; no territorial "
           "target has more than one controller and no composite "
           "container/member gained control from the relation")
    _check("V15_hre_structural_not_owner",
           len(hre_sp) == 1
           and hre_sp.iloc[0]["territorial_authority_role"]
           == "STRUCTURAL_CONTAINER"
           and hre_id not in controllers
           and int((ctrl["controller_scenario_polity_id"]
                    == hre_id).sum()) == 0,
           "Holy Roman Empire registered as STRUCTURAL_CONTAINER with "
           "zero territorial control rows")
    forbidden = scan_forbidden_reference_code(
        Path(__file__).parent / "scenario.py")
    ne_srcs = srcs[srcs["title"].str.contains("Natural Earth", case=False,
                                              na=False)]
    _check("V16_no_modern_admin_generator",
           not forbidden and not len(ne_srcs),
           f"scenario data layer AST scan clean (hits={forbidden or 0}); "
           "no Natural Earth entry in the historical source registry")
    iso_cols = [c for df in (snap.polities, sp, rel, audit, ctrl, claims)
                for c in df.columns if "iso" in c.lower()]
    _check("V17_no_iso_country_import_path",
           not iso_cols,
           f"no ISO-code columns anywhere in scenario tables "
           f"(found={iso_cols or 0})")
    europe_sp = sp[sp["scenario_polity_id"] != tokugawa_sp]
    audit_by_pol = audit.dropna(subset=["included_polity_id"]).set_index(
        "included_polity_id")
    not_audited = [p for p in europe_sp["polity_id"]
                   if p not in audit_by_pol.index]
    bad_audit_refs = [p for p in audit_by_pol.index if p not in pol_ids]
    _check("V18_inclusion_audit_exhaustive",
           not not_audited and not bad_audit_refs
           and audit["canonical_candidate_id"].is_unique,
           f"{len(audit)} audit rows cover all {len(europe_sp)} Europe "
           f"scenario polities (missing={not_audited or 0}); all "
           f"included_polity_id resolve (bad={bad_audit_refs or 0})")
    _check("V19_inclusion_status_enum",
           audit["inclusion_status"].isin(INCLUSION_STATUSES).all(),
           f"statuses={audit['inclusion_status'].value_counts().to_dict()}")
    _check("V20_representation_risk_populated",
           audit["six_km_representation_risk"].notna().all()
           and audit["six_km_representation_risk"].isin(
               REPRESENTATION_RISKS).all(),
           f"risk={audit['six_km_representation_risk'].value_counts().to_dict()}"
           " (UNKNOWN is an explicit value, never a blank)")
    unk = ev[ev["source_locator"] == "UNKNOWN"]
    _check("V21_evidence_locator_or_reasoned_unknown",
           ev["source_locator"].notna().all()
           and unk["notes"].notna().all(),
           f"evidence rows={len(ev)}, locator UNKNOWN={len(unk)} (all "
           "with reason; no fabricated page numbers), pinpoint locators="
           f"{len(ev) - len(unk)}")
    tok = sp[sp["scenario_polity_id"] == tokugawa_sp]
    _check("V22_tokugawa_pilot_unchanged",
           len(tok) == 1 and tok.iloc[0]["polity_id"]
           == "pol_tokugawa_shogunate"
           and float(tok.iloc[0]["capital_lat"]) == 35.6877
           and float(tok.iloc[0]["capital_lon"]) == 139.7528
           and tok.iloc[0]["existence_status"] == "EXISTS",
           "MAPGEN-008 Tokugawa scenario polity intact (additive columns "
           "only)")
    toshima = ctrl[(ctrl["territorial_target_type"] == "ISLAND_COMPONENT")
                   & (ctrl["territorial_target_id"]
                      == "isl_c_1859af1e4767")]
    _check("V23_toshima_component_control_intact",
           len(toshima) == 1
           and toshima.iloc[0]["control_status"] == "CONTROLLED"
           and toshima.iloc[0]["controller_scenario_polity_id"]
           == tokugawa_sp,
           "Toshima remains an ISLAND_COMPONENT control target of the "
           "Tokugawa scenario polity")
    tosh_hex = comps.loc[comps["island_component_id"]
                         == "isl_c_1859af1e4767",
                         "component_primary_hex_id"].iloc[0]
    wt = geo.loc[geo["hex_id"] == tosh_hex, "water_type"].iloc[0]
    _check("V24_toshima_hex_still_ocean", wt == "OCEAN",
           f"underlying hex {tosh_hex} water_type={wt}")
    ctrl_sha = sha256_of(sdir / "territorial_control.csv")
    claims_sha = sha256_of(sdir / "territorial_claims.csv")
    _check("V25_control_claims_unchanged_from_008",
           ctrl_sha == sha256_of(m8_dir / "territorial_control.csv")
           and claims_sha == sha256_of(m8_dir / "territorial_claims.csv"),
           "territorial_control/claims byte-identical to the MAPGEN-008 "
           "review copies — the Europe catalogue added NO territory")
    _check("V26_catalogue_status_separate",
           "europe_polity_catalogue_status" in registry.columns
           and row.iloc[0]["europe_polity_catalogue_status"]
           in ("PARTIAL", "COMPLETE")
           and row.iloc[0]["europe_polity_catalogue_status"]
           != row.iloc[0]["data_status"],
           f"europe_polity_catalogue_status="
           f"{row.iloc[0]['europe_polity_catalogue_status']} reported "
           "separately from scenario data_status")
    _check("V27_scenario_still_foundation_only",
           meta["data_status"] == "FOUNDATION_ONLY"
           and meta["political_geography_complete"] in (False, "False"),
           f"data_status={meta['data_status']}")
    ref_flags = []
    for f in ["reference_admin0.parquet", "reference_settlements.parquet",
              "reference_ports.parquet"]:
        df = pd.read_parquet(hg_dir / f,
                             columns=["gameplay_authoritative"])
        ref_flags.append(bool((~df["gameplay_authoritative"]).all()))
    _check("V28_reference_layer_not_gameplay", all(ref_flags),
           "reference human geography gameplay_authoritative=false "
           "maintained")
    _check("V29_no_second_scenario_directory",
           len(registry) == 1 and dirs == [scenario_id],
           f"registry={len(registry)} scenario, dirs={dirs}")
    terr_hex = set(geo.loc[geo["is_terrestrial_hex"], "hex_id"])
    comp_ids = set(comps["island_component_id"])
    broken = 0
    broken += int((~ctrl["controller_scenario_polity_id"].dropna()
                   .isin(sp_ids)).sum())
    broken += int((~claims["claimant_scenario_polity_id"]
                   .isin(sp_ids)).sum())
    broken += int((~ctrl["source_id"].dropna().isin(src_ids)).sum())
    broken += int((~claims["source_id"].dropna().isin(src_ids)).sum())
    broken += int((~ev["source_id"].isin(src_ids)).sum())
    broken += int((~audit["source_id"].isin(src_ids)).sum())
    frag_ids = set()
    frp = Path("data/historical/land_fragment_registry.csv")
    if frp.exists():
        frag_ids = set(pd.read_csv(frp)["land_fragment_id"])
    for t in ctrl.itertuples():
        if t.territorial_target_type == "TERRESTRIAL_HEX":
            broken += t.territorial_target_id not in terr_hex
        elif t.territorial_target_type == "LAND_FRAGMENT":
            # the land inside a hex, not the hex: an OCEAN parent is legal
            broken += t.territorial_target_id not in frag_ids
        else:
            broken += t.territorial_target_id not in comp_ids
    for t in ev.itertuples():
        if t.target_type == "TERRESTRIAL_HEX":
            broken += t.target_id not in terr_hex
        elif t.target_type == "ISLAND_COMPONENT":
            broken += t.target_id not in comp_ids
        elif t.target_type == "POLITY":
            broken += t.target_id not in pol_ids
        else:
            broken += 1
    _check("V30_referential_integrity", broken == 0,
           f"broken cross-table references={broken}")
    ids_ok = (all(make_source_id(scenario_id, t.citation_key)
                  == t.source_id for t in srcs.itertuples())
              and all(make_evidence_id(scenario_id, t.source_id,
                                       t.evidence_type, t.target_type,
                                       t.target_id) == t.evidence_id
                      for t in ev.itertuples())
              and ev["evidence_id"].is_unique)
    _check("V31_deterministic_ids", bool(ids_ok) and sp_det,
           "source/evidence/scenario-polity/relationship ids all "
           "reproduce from the documented rules (run-level determinism "
           "proved by second run)")
    try:
        load_scenario(cfg.data_dir, "no_such_scenario_id")
        unknown_ok = False
    except ScenarioNotFoundError:
        unknown_ok = True
    _check("V33_unknown_scenario_errors", unknown_ok,
           "unknown scenario_id raises ScenarioNotFoundError "
           "(no default fallback)")

    # ---- MAPGEN-009R gates (mapping to 009R spec V## in the report) -----
    struct_ids = set(sp.loc[sp["territorial_authority_role"]
                            == "STRUCTURAL_CONTAINER",
                            "scenario_polity_id"])
    _check("R05_structural_containers_zero_control",
           not (struct_ids & controllers),
           f"{len(struct_ids)} structural containers (incl. HRE, Swiss "
           "Confederacy) hold zero territorial control rows")
    agg = audit[audit["inclusion_status"] == "AGGREGATION_CANDIDATE"]
    _check("R06_aggregation_never_controller",
           agg["included_polity_id"].isna().all(),
           f"{len(agg)} aggregation-class audit rows carry no polity id "
           "and therefore can never appear as territorial controllers — "
           "aggregation is a gameplay/view concern, never ownership")
    subhex_rows = audit[
        (audit["six_km_representation_risk"] == "SUBHEX_REQUIRED")
        | (audit["inclusion_status"] == "SUBHEX_REQUIRED")]
    basis_ok = (subhex_rows["representability_basis"].notna().all()
                and not subhex_rows["representability_basis"]
                .str.startswith("UNKNOWN").any()) if len(subhex_rows) \
        else True
    _check("R11_subhex_requires_explicit_basis", bool(basis_ok),
           f"SUBHEX_REQUIRED rows={len(subhex_rows)}; every one carries "
           "an explicit geometric/evidence representability_basis")
    micro = ["cand_san_marino", "cand_monaco", "cand_andorra",
             "cand_liechtenstein"]
    ms = audit[audit["canonical_candidate_id"].isin(micro)]
    _check("R12_no_name_based_subhex_rule",
           len(ms) == 4
           and not (ms["six_km_representation_risk"]
                    == "SUBHEX_REQUIRED").any()
           and not (ms["inclusion_status"] == "SUBHEX_REQUIRED").any(),
           "the four microstates are no longer SUBHEX by label; "
           f"statuses={dict(zip(ms['canonical_candidate_id'], ms['inclusion_status']))}")
    _check("R13_microstates_individually_reaudited",
           sorted(corrections["canonical_candidate_id"]) == sorted(micro)
           and (corrections["hex_plane_area_km2"]
                == HEX_PLANE_AREA_KM2).all()
           and corrections["modern_area_km2_SANITY_CHECK_ONLY"]
           .notna().all(),
           f"corrections file covers all 4 microstates with before/after "
           f"+ machine-computed hex plane area {HEX_PLANE_AREA_KM2} km2 "
           "(modern figures marked SANITY_CHECK_ONLY)")
    required_hre = ["Münster", "Würzburg", "Bamberg", "Salzburg",
                    "Hesse-Darmstadt", "Mecklenburg-Strelitz",
                    "Baden-Durlach", "Baden-Baden", "Nassau", "Anhalt"]
    hre_names = " | ".join(hre_audit["candidate_name"])
    missing_hre = [n for n in required_hre if n not in hre_names]
    _check("R14_hre_sample_individually_audited",
           not missing_hre and len(hre_audit) >= 15
           and hre_audit["source_id"].isin(src_ids).all(),
           f"{len(hre_audit)} individual HRE audit rows with a-e "
           f"criteria; required candidates missing={missing_hre or 0}")
    majors = ["cand_muenster", "cand_wuerzburg", "cand_bamberg",
              "cand_salzburg"]
    mj = audit[audit["canonical_candidate_id"].isin(majors)]
    _check("R15_major_bishoprics_not_hidden_in_class",
           len(mj) == 4 and (mj["inclusion_status"] == "INCLUDED").all()
           and mj["included_polity_id"].notna().all(),
           "Münster/Würzburg/Bamberg/Salzburg have individual INCLUDED "
           "audit rows and registered polities")
    cors = audit[audit["canonical_candidate_id"] == "cand_corsica"]
    cors_case = contested[contested["case"] == "corsica_1756"]
    _check("R16_corsica_explicitly_resolved",
           len(cors) == 1
           and cors.iloc[0]["inclusion_status"] == "INCLUDED"
           and cors.iloc[0]["included_polity_id"]
           == "pol_corsican_republic"
           and "pol_corsican_republic" in pol_ids
           and len(cors_case) == 1
           and "genoa" in cors_case.iloc[0]["de_jure_side"].lower()
           and "corsican" in cors_case.iloc[0]["de_facto_side"].lower(),
           "Corsican Republic (Paoli) registered as de-facto polity; "
           "Genoese de-jure claim preserved; contested-control contract "
           "recorded; no whole-island grant by fiat")
    names_all = pd.concat([sp["display_name"],
                           snap.polities["canonical_name"]])
    pk = snap.polities[snap.polities["polity_id"]
                       == "pol_prussia_kingdom_proper"]
    _check("R17_no_royal_prussia_conflation",
           not names_all.str.contains("Royal Prussia", case=False).any()
           and len(prussia_terms) >= 4
           and prussia_terms["term"].str.contains("Royal Prussia").any()
           and "Commonwealth" in pk.iloc[0]["notes"],
           "no polity name uses 'Royal Prussia'; terminology audit "
           f"rows={len(prussia_terms)}; Ducal/East-Prussia vs Polish "
           "Royal Prussia distinction documented on the polity")
    roots = sp[sp["territorial_authority_role"]
               == "COMPOSITE_TERRITORIAL_ACTOR"]
    _check("R19_composite_binding_contract",
           len(roots) == 2
           and not (set(roots["scenario_polity_id"]) & controllers)
           and set(roots["polity_id"])
           == {"pol_habsburg_monarchy", "pol_prussia_monarchy"},
           "composite roots (Habsburg, Prussian monarchies) carry role "
           "COMPOSITE_TERRITORIAL_ACTOR and hold no control rows; "
           "territory binds to the most specific registered constituent "
           "(contract in scenario.py + README)")
    review_src_ok = all(
        df["source_id"].isin(src_ids).all()
        for df in (corrections, hre_audit, contested, prussia_terms,
                   granularity))
    _check("R10_audit_decisions_sourced", bool(review_src_ok),
           f"all decision rows in the 5 review audit CSVs (corrections/"
           f"hre/{len(contested)} contested/terminology/"
           f"{len(granularity)} granularity) trace to registered "
           "sources")
    _check("R29_hex_area_machine_anchor",
           HEX_PLANE_AREA_KM2 == round(
               HexGrid(flat_to_flat=6000.0).area / 1e6, 6),
           f"representability anchor {HEX_PLANE_AREA_KM2} km2 equals the "
           "grid-code hex area (machine-computed, recorded in manifest)")

    # ---- MAPGEN-009R2: superseded audit + review-contract gates ---------
    audit_active = _active_audit(audit)
    audit_sup = audit[audit.get("audit_record_status", "ACTIVE")
                      == "SUPERSEDED"]
    active_inc = audit_active["inclusion_status"].value_counts().to_dict()
    active_risk = audit_active["six_km_representation_risk"] \
        .value_counts().to_dict()
    active_unres = sorted(
        audit_active.loc[audit_active["inclusion_status"] == "UNRESOLVED",
                         "candidate_name"])
    _check("R2-05_no_active_row_superseded",
           audit["audit_record_status"].isin(["ACTIVE",
                                              "SUPERSEDED"]).all()
           and audit.loc[audit["audit_record_status"] == "ACTIVE",
                         "superseded_by_candidate_ids"].isna().all(),
           f"{len(audit_active)} ACTIVE rows carry no superseded_by; "
           "statuses within enum")
    all_cands = set(audit["canonical_candidate_id"])
    sup_targets = []
    for t in audit_sup.itertuples():
        sup_targets.extend(str(
            t.superseded_by_candidate_ids).split("|"))
    _check("R2-06_superseded_targets_exist",
           audit_sup["superseded_by_candidate_ids"].notna().all()
           and all(x in all_cands for x in sup_targets),
           f"{len(audit_sup)} SUPERSEDED rows -> targets {sup_targets} "
           "all exist ('|'-joined stable format)")
    tgt_status = audit.set_index("canonical_candidate_id")[
        "audit_record_status"]
    _check("R2-07_superseded_targets_active",
           all(tgt_status.get(x) == "ACTIVE" for x in sup_targets),
           "every supersession target is itself ACTIVE")
    _check("R2-08_09_superseded_excluded_from_active_counts",
           len(audit_active) + len(audit_sup) == len(audit)
           and sum(active_inc.values()) == len(audit_active)
           and sum(active_risk.values()) == len(audit_active),
           f"total={len(audit)} = active {len(audit_active)} + "
           f"superseded {len(audit_sup)}; active inclusion/risk counts "
           "computed from ACTIVE rows only")
    sh = audit[audit["canonical_candidate_id"]
               == "cand_schleswig_holstein_complex"]
    sh_children_active = (
        tgt_status.get("cand_schleswig_holstein_royal") == "ACTIVE"
        and tgt_status.get("cand_holstein_gottorp") == "ACTIVE")
    _check("R2-10_schleswig_parent_historical_only",
           len(sh) == 1
           and sh.iloc[0]["audit_record_status"] == "SUPERSEDED"
           and sh.iloc[0]["superseded_by_candidate_ids"]
           == "cand_schleswig_holstein_royal|cand_holstein_gottorp"
           and sh_children_active
           and len([n for n in active_unres if "royal" in n.lower()
                    or "gottorp" in n.lower()]) == 2,
           "old complex candidate is SUPERSEDED history; the two "
           "refined children are the ACTIVE candidates — no double "
           "contribution to UNRESOLVED counts")
    _check("R2-04_active_policy_is_v2",
           (sdir / "review" / "inclusion_policy_v2.md").exists()
           and (sdir / "review" / "inclusion_policy_v1.md").exists(),
           "inclusion_policy_v2.md is the ACTIVE policy; v1 kept as "
           "SUPERSEDED history (recorded in manifest)")
    r9_dir = cfg.output_dir / scfg.get(
        "mapgen009r_baseline_run", "scenario_catalogue_009r_20260811")
    hist_same = []
    for fname, cur in [("polities.csv",
                        scenarios_root(cfg.data_dir) / "polities.csv"),
                       ("scenario_polities.csv",
                        sdir / "scenario_polities.csv"),
                       ("scenario_polity_relationships.csv",
                        sdir / "scenario_polity_relationships.csv")]:
        a = pd.read_csv(r9_dir / "chatgpt_review" / fname,
                        keep_default_na=False, na_values=[""])
        b = pd.read_csv(cur, keep_default_na=False, na_values=[""])
        hist_same.append(a.equals(b))
    _check("R2-14_historical_content_unchanged",
           all(hist_same)
           and len(snap.polities) == 66 and len(sp) == 66
           and len(rel) == 46,
           f"polities/scenario_polities/relationships byte-content "
           f"equal to {r9_dir.name} (equal={hist_same}); 66 polities, "
           "46 relationships — this stage changed the review contract "
           "only")
    _check("R2-12_13_control_claims_unchanged",
           ctrl_sha == sha256_of(r9_dir / "chatgpt_review"
                                 / "territorial_control.csv")
           and claims_sha == sha256_of(r9_dir / "chatgpt_review"
                                       / "territorial_claims.csv"),
           "territorial_control/claims byte-identical to the 009R "
           "baseline as well as to MAPGEN-008 (V25)")

    # ---- renders ---------------------------------------------------------
    t0 = time.perf_counter()
    tcfg = cfg.raw["terrain"]
    grid = HexGrid(flat_to_flat=float(tcfg["hex_size_m"]),
                   orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)
    polys = grid.polygons(geo["q"].to_numpy(), geo["r"].to_numpy())
    kanto_comps = comps[comps["region"] == "kanto"]
    render_overview(
        run_dir / "scenario_political_foundation_overview.png", geo, polys,
        snap, kanto_comps,
        f"{scenario_id} — political foundation layer over canonical "
        "geography hexes\n(separate layer; geography untouched; "
        "FOUNDATION_ONLY pilot data)")
    render_semantics_diagram(
        run_dir / "reference_vs_scenario_semantics.png", geo, polys, mem,
        snap, "REFERENCE ADMIN vs SCENARIO POLITICAL CONTROL — two "
        "independent namespaces (left is NEVER copied into right)")
    render_island_target(
        run_dir / "island_component_control_target.png", geo, polys, snap,
        kanto_comps,
        "Izu-Toshima: island component as territorial control target "
        "(real pilot data)\nhex water authority unchanged — "
        "OVERLAY UNIT is never the political unit")
    render_catalogue_overview(
        run_dir / "europe_1756_polity_catalogue_overview.png", snap,
        "1756 Europe polity catalogue (MAPGEN-009) — entity kinds, "
        "inclusion statuses, authority roles")
    render_relationship_diagram(
        run_dir / "constitutional_relationship_diagram.png", snap,
        "1756 constitutional relationships — imperial membership / "
        "composite monarchies / personal unions (NO relationship creates "
        "territorial control)")
    render_risk_summary(
        run_dir / "six_km_representability_risk_summary.png", snap,
        "6 km representability audit — risks are findings for the future "
        "historical overlay decision, not failures")
    render_ontology_diagram(
        run_dir / "reference_vs_scenario_ontology.png",
        "Ontology separation: contemporary reference layer vs scenario "
        "political layer (generation from modern admin is FORBIDDEN)")
    base_summary = (cfg.output_dir
                    / scfg.get("mapgen009_baseline_run",
                               "scenario_catalogue_20260811")
                    / "scenario_summary.csv")
    render_hre_before_after(
        run_dir / "hre_catalogue_before_after.png", base_summary, snap,
        "MAPGEN-009R: from class aggregation to individual audit — "
        "inclusion + representability, before vs after")
    render_representability_sanity(
        run_dir / "six_km_representability_sanity_panel.png",
        "6 km representability sanity panel (machine-computed hex area "
        "vs the four re-audited microstates)")
    render_corsica_diagram(
        run_dir / "corsica_1756_modeling_diagram.png",
        "Corsica 1756: Genoese de-jure claim vs Corsican de-facto "
        "polity — separated concepts, geometry NOT yet drawn")
    render_audit_contract_before_after(
        run_dir / "audit_contract_before_after.png", audit,
        "MAPGEN-009R2: review-contract QA — superseded audit semantics "
        "+ README/manifest synchronisation (historical content "
        "unchanged)")
    from PIL import Image

    img_names = ["scenario_political_foundation_overview.png",
                 "reference_vs_scenario_semantics.png",
                 "island_component_control_target.png",
                 "europe_1756_polity_catalogue_overview.png",
                 "constitutional_relationship_diagram.png",
                 "six_km_representability_risk_summary.png",
                 "reference_vs_scenario_ontology.png",
                 "hre_catalogue_before_after.png",
                 "six_km_representability_sanity_panel.png",
                 "corsica_1756_modeling_diagram.png",
                 "audit_contract_before_after.png"]
    aspects = {}
    for n in img_names:
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.size[0] / im.size[1], 3)
    _check("V32_renders",
           all((run_dir / n).exists() for n in img_names)
           and all(0.3 <= a <= 4.0 for a in aspects.values()),
           f"{len(img_names)} renders, aspects={aspects}")
    timings["render_s"] = time.perf_counter() - t0

    # ---- immutability (SHA after) ---------------------------------------
    up_after = {k: sha256_of(Path(k)) for k in upstream}
    scen_after = {k: sha256_of(Path(k)) for k in scen_sha_before}
    _check("V01_upstream_immutable",
           up_after == upstream and scen_after == scen_sha_before,
           f"{len(upstream)} upstream files (006R geography, 007R human "
           "geography, 008 control/claims baselines) and "
           f"{len(scen_after)} scenario input CSVs byte-identical "
           "before/after — this pipeline generated no political data")

    # ---- README first, then the R2 fact-sync gates ----------------------
    _write_readme(run_dir, run_id, scenario_id, meta, snap, aspects,
                  row.iloc[0]["europe_polity_catalogue_status"], europe_sp)
    readme = (run_dir / "README_REVIEW.md").read_text(encoding="utf-8")
    rel_counts = rel["relationship_type"].value_counts().to_dict()
    imp = int(rel_counts.get("IMPERIAL_MEMBER_OF", 0))
    _check("R2-01_readme_facts_match_canonical",
           f"{len(rel)} rows" in readme
           and f'"IMPERIAL_MEMBER_OF": {imp}' in readme
           and f"{len(audit_active)} ACTIVE" in readme
           and "18 IMPERIAL_MEMBER_OF" not in readme,
           "README relationship/audit counts are generated from and "
           "match the canonical tables; stale '18 IMPERIAL_MEMBER_OF' "
           "removed")
    _check("R2-02_readme_hre_member_count",
           imp == 29 and f"{imp} IMPERIAL_MEMBER_OF rows" in readme,
           f"actual IMPERIAL_MEMBER_OF={imp}; README states the same")
    unres_line_ok = (f"Active UNRESOLVED candidates: "
                     f"{'; '.join(sorted(audit_active.loc[audit_active['inclusion_status'] == 'UNRESOLVED', 'candidate_name']))}."
                     in readme)
    _check("R2-03_readme_unresolved_matches_active",
           unres_line_ok
           and "Lucca and Corsica were RESOLVED" in readme
           and "3 UNRESOLVED candidates (Lucca" not in readme,
           f"README lists exactly the {len(active_unres)} ACTIVE "
           "UNRESOLVED candidates; stale Lucca/Corsica-unresolved "
           "statements removed")
    _check("R2-11_run_stage_readme_consistent",
           STAGE == "MAPGEN-009R2"
           and readme.splitlines()[0].startswith(f"# {STAGE} ")
           and ("009r2" in run_id.lower()
                or "009r" not in run_id.lower()),
           f"run_id={run_id}, manifest stage={STAGE}, README title "
           "agree (no 009-vs-009R identity mismatch)")

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "scenario_validation.csv", index=False)

    # ---- summary / manifest / review package ----------------------------
    n_pass = int(val["pass"].sum())
    kinds = snap.polities.set_index("polity_id")["polity_kind"]
    summary_rows = [
        ("scenario_schema_version", SCENARIO_SCHEMA_VERSION),
        ("scenario_algorithm_version", SCENARIO_ALGORITHM_VERSION),
        ("scenario_semantics", SCENARIO_SEMANTICS),
        ("scenario_id", scenario_id),
        ("snapshot_date", meta["snapshot_date"]),
        ("data_status", meta["data_status"]),
        ("europe_polity_catalogue_status",
         row.iloc[0]["europe_polity_catalogue_status"]),
        ("political_geography_complete",
         meta["political_geography_complete"]),
        ("polities_global", len(snap.polities)),
        ("scenario_polities", len(sp)),
        ("europe_scenario_polities", len(europe_sp)),
        ("polity_kind_counts", json.dumps(
            sp["polity_id"].map(kinds).value_counts().to_dict())),
        ("territorial_authority_role_counts", json.dumps(
            sp["territorial_authority_role"].value_counts().to_dict())),
        ("relationships", len(rel)),
        ("relationship_type_counts", json.dumps(rel_counts)),
        ("audit_rows_total", len(audit)),
        ("audit_rows_active", len(audit_active)),
        ("audit_rows_superseded", len(audit_sup)),
        ("inclusion_status_counts_active", json.dumps(active_inc)),
        ("six_km_risk_counts_active", json.dumps(active_risk)),
        ("active_unresolved_candidates", "; ".join(active_unres)),
        ("territorial_control_rows", len(ctrl)),
        ("territorial_claims_rows", len(claims)),
        ("sources", len(srcs)),
        ("evidence_rows", len(ev)),
        ("evidence_pinpoint_locators",
         int((ev["source_locator"] != "UNKNOWN").sum())),
        ("hex_plane_area_km2_machine_computed", HEX_PLANE_AREA_KM2),
        ("representability_corrections", len(corrections)),
        ("hre_individual_audit_rows", len(hre_audit)),
        ("contested_polity_cases", len(contested)),
        ("validation_pass", f"{n_pass}/{len(val)}"),
    ]
    pd.DataFrame(summary_rows, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "scenario_summary.csv", index=False)
    manifest = {
        "run_id": run_id,
        "stage": STAGE,
        "stage_family": STAGE_FAMILY,
        "revision": STAGE_REVISION,
        "inclusion_policy": {
            "active": "inclusion_policy_v2.md",
            "superseded": [{"file": "inclusion_policy_v1.md",
                            "policy_status": "SUPERSEDED",
                            "superseded_by": "inclusion_policy_v2.md"}],
        },
        "audit_record_contract": {
            "statuses": ["ACTIVE", "SUPERSEDED"],
            "superseded_by_format": "candidate ids joined with '|'",
            "rules": "SUPERSEDED rows are permanent history: excluded "
                     "from active counts, never a polity registration "
                     "or control source; deletion is forbidden",
        },
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "scenario_schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_algorithm_version": SCENARIO_ALGORITHM_VERSION,
        "version_reasons": {
            "schema_1.1.0": "additive: relationship + inclusion-audit "
                            "tables; authority-role/playability/ja-name "
                            "columns; evidence locator precision columns",
            "algorithm_1.0.1": "one new rule: symmetric relationship ids "
                               "canonicalise participant order before "
                               "hashing; all 1.0.0 rules unchanged",
            "schema_1.2.0": "additive (MAPGEN-009R): "
                            "COMPOSITE_TERRITORIAL_ACTOR role value, "
                            "historical_title_at_snapshot column, "
                            "representability_basis column; no existing "
                            "semantics changed — data corrections alone "
                            "did NOT drive the bump",
            "algorithm_1.0.2": "representability audit anchored to the "
                               "machine-computed hex area instead of "
                               "political-size labels; id rules "
                               "unchanged",
            "schema_1.3.0": "additive (MAPGEN-009R2): audit_record_"
                            "status + superseded_by_candidate_ids — "
                            "history-preserving supersession, active "
                            "counts exclude superseded rows; algorithm "
                            "stays 1.0.2 (no political judgment "
                            "changed)",
        },
        "hex_plane_area_km2": HEX_PLANE_AREA_KM2,
        "territorial_binding_contract": [
            "control binds to the MOST SPECIFIC registered scenario "
            "polity with territorial identity",
            "COMPOSITE_MEMBER_OF expresses upward structure only",
            "no automatic control from any relationship",
            "STRUCTURAL_CONTAINER holds zero control (hard gate)",
            "COMPOSITE_TERRITORIAL_ACTOR roots hold control only where "
            "no registered constituent covers the territory",
            "root+member duplicate control on one target is forbidden",
            "gameplay faction grouping/aggregation is a future separate "
            "layer, never historical ownership authority",
        ],
        "explicitly_revised_scenario_inputs_MAPGEN_009R": [
            "polities.csv", "scenario_polities.csv",
            "scenario_polity_relationships.csv",
            "scenario_polity_inclusion_audit.csv", "sources.csv",
            "evidence.csv", "scenario_registry.csv",
            "review/*.csv", "review/inclusion_policy_v2.md",
        ],
        "scenario_semantics": SCENARIO_SEMANTICS,
        "scenario_id": scenario_id,
        "data_status": meta["data_status"],
        "europe_polity_catalogue_status":
            row.iloc[0]["europe_polity_catalogue_status"],
        "upstream_sha256": upstream,
        "scenario_input_sha256": scen_sha_before,
        "id_rules": {
            "scenario_id": "permanent handle, assigned once",
            "polity_id": "permanent curated slug (pol_...)",
            "scenario_polity_id": "sp_ + sha1(scenario_id|polity_id)[:12]",
            "source_id": "src_ + sha1(scenario_id|citation_key)[:12]",
            "evidence_id": "ev_ + sha1(scenario|source|type|target)[:12]",
            "relationship_id": "rel_ + sha1(scenario|type|from|to)[:12]; "
                               "SYMMETRIC types sort participants first",
            "version_semantics": "changing a defining key IS a data "
                                 "version change; display fields are "
                                 "freely editable",
        },
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8")
    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    copies = {
        "scenario_registry.csv":
            scenarios_root(cfg.data_dir) / "scenario_registry.csv",
        "polities.csv": scenarios_root(cfg.data_dir) / "polities.csv",
        "scenario_polities.csv": sdir / "scenario_polities.csv",
        "scenario_polity_relationships.csv":
            sdir / "scenario_polity_relationships.csv",
        "scenario_polity_inclusion_audit.csv":
            sdir / "scenario_polity_inclusion_audit.csv",
        "territorial_control.csv": sdir / "territorial_control.csv",
        "territorial_claims.csv": sdir / "territorial_claims.csv",
        "scenario_sources.csv": sdir / "sources.csv",
        "scenario_evidence.csv": sdir / "evidence.csv",
        "inclusion_policy_v1.md":
            sdir / "review" / "inclusion_policy_v1.md",
        "inclusion_policy_v2.md":
            sdir / "review" / "inclusion_policy_v2.md",
        "polity_granularity_audit.csv":
            sdir / "review" / "polity_granularity_audit.csv",
        "six_km_representability_corrections.csv":
            sdir / "review" / "six_km_representability_corrections.csv",
        "hre_individual_polity_audit.csv":
            sdir / "review" / "hre_individual_polity_audit.csv",
        "contested_polity_audit.csv":
            sdir / "review" / "contested_polity_audit.csv",
        "prussia_terminology_audit.csv":
            sdir / "review" / "prussia_terminology_audit.csv",
    }
    for dst, src in copies.items():
        shutil.copy2(src, review / dst)
    for f in (["README_REVIEW.md", "scenario_validation.csv",
               "scenario_summary.csv", "run_manifest.json"] + img_names):
        shutil.copy2(run_dir / f, review / f)
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"[scenario] {run_id}: validation {n_pass}/{len(val)}, "
          f"{len(sp)} scenario polities ({len(europe_sp)} Europe), "
          f"{len(rel)} relationships, {len(audit)} audit rows, "
          f"catalogue={row.iloc[0]['europe_polity_catalogue_status']} "
          f"({timings['total_s']:.0f}s)")
    for w in warnings:
        print(f"[scenario][WARN] {w}")
    return run_dir


def _write_readme(run_dir, run_id, scenario_id, meta, snap, aspects,
                  catalogue_status, europe_sp):
    """README facts are GENERATED from the canonical tables (never hand
    written) and machine-checked against them by the R2-01..03/11 gates
    after this file is written."""
    sp = snap.scenario_polities
    rel = snap.scenario_polity_relationships
    audit_all = snap.scenario_polity_inclusion_audit
    audit = _active_audit(audit_all)
    n_sup = len(audit_all) - len(audit)
    rel_counts = rel["relationship_type"].value_counts().to_dict()
    imp = int(rel_counts.get("IMPERIAL_MEMBER_OF", 0))
    n_habsburg = int((
        (rel["relationship_type"] == "COMPOSITE_MEMBER_OF")
        & rel["to_scenario_polity_id"].isin(
            sp.loc[sp["polity_id"] == "pol_habsburg_monarchy",
                   "scenario_polity_id"])).sum())
    inc_counts = audit["inclusion_status"].value_counts().to_dict()
    risk_counts = audit["six_km_representation_risk"].value_counts() \
        .to_dict()
    active_unres = sorted(
        audit.loc[audit["inclusion_status"] == "UNRESOLVED",
                  "candidate_name"])
    lines = [
        f"# {STAGE} Review — Review Contract Consistency + Superseded "
        "Audit Semantics",
        "",
        "**REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP.**",
        "**SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY "
        "WITHIN ITS SCENARIO SNAPSHOT.**",
        "",
        f"Run `{run_id}` (stage {STAGE}, family {STAGE_FAMILY} rev "
        f"{STAGE_REVISION}) — scenario_schema_version 1.2.0 → **1.3.0** "
        "(additive only: audit_record_status ACTIVE/SUPERSEDED + "
        "superseded_by_candidate_ids on the inclusion audit; refined-"
        "away candidates keep their rows and ids forever but are "
        "excluded from ACTIVE counts and can never register polities or "
        "control). scenario_algorithm_version stays **1.0.2** — no "
        "political-judgment algorithm changed. The historical content "
        "of MAPGEN-009R (66 polities, 46 relationships, control/claims, "
        "contested contracts) is UNCHANGED and regression-gated "
        "(R2-12..14). parent_scenario_polity_id remains a DEPRECATED "
        "convenience field — `scenario_polity_relationships` is the "
        "authority.",
        "",
        "## MAPGEN-009R2 review-contract fixes",
        "",
        "- README facts are now generated from the canonical tables and "
        "machine-compared against them (R2-01..03); the stale "
        "MAPGEN-009 statements (the outdated imperial-member count and "
        "the outdated unresolved-candidate list) are gone.",
        "- Superseded-audit semantics: "
        f"{len(audit_all)} total audit rows = {len(audit)} ACTIVE + "
        f"{n_sup} SUPERSEDED. cand_schleswig_holstein_complex is "
        "SUPERSEDED history pointing at cand_schleswig_holstein_royal | "
        "cand_holstein_gottorp (both ACTIVE); rows are never deleted "
        "and SUPERSEDED rows never contribute to active counts, polity "
        "registration or control.",
        f"- Active inclusion policy: `inclusion_policy_v2.md`; v1 is "
        "kept as SUPERSEDED history (precedence recorded in "
        "run_manifest).",
        f"- run manifest stage identity fixed: stage={STAGE} "
        f"(family {STAGE_FAMILY}, revision {STAGE_REVISION}); run_id / "
        "stage / README title consistency is machine-gated (R2-11).",
        "",
        "## MAPGEN-009R corrections",
        "",
        "- **Old SUBHEX bug root cause**: the political label "
        "'microstate' was treated as a geometry finding and the hex "
        "area was never machine-computed. Withdrawn everywhere.",
        "- **Microstates re-audited individually** (Duursma 1996; "
        "modern areas as SANITY CHECKS ONLY, admissible where extent "
        "continuity is documented): San Marino (~61 km2, stable since "
        "the 15th c.) INCLUDED/NONE; Andorra (~468 km2, 1278 pareage) "
        "INCLUDED/NONE; Liechtenstein (~160 km2, 1719 union) "
        "INCLUDED/NONE; Monaco UNRESOLVED/UNKNOWN (1756 principality "
        "included Menton and Roquebrune — geometry review required, "
        "not guessed).",
        "- **HRE granularity**: blanket class judgments withdrawn; "
        "17 individual audits. Münster, Würzburg, Bamberg (with "
        "Carinthian exclaves), Salzburg, Hesse-Darmstadt, Mecklenburg-"
        "Strelitz, Baden-Durlach + Baden-Baden (separate until 1771), "
        "Hamburg and Nuremberg are now INCLUDED polities; Frankfurt/"
        "Augsburg/Bremen/Lübeck/Ulm and the Nassau/Anhalt families are "
        "individually tracked AGGREGATION candidates. Aggregation is a "
        "gameplay/view concern, never historical ownership authority.",
        "- **Corsica resolved**: the Corsican Republic (Paoli, from "
        "1755) is registered as a de-facto polity (Thrasher 1970); "
        "Genoa keeps the de-jure claim; the contested-control contract "
        "(separate claims vs control, citadels vs interior, no whole-"
        "island fiat) is in `contested_polity_audit.csv`. Lucca "
        "resolved INCLUDED via the registered atlas. Schleswig-"
        "Holstein stays UNRESOLVED, split into royal / Gottorp "
        "sub-candidates — never collapsed into one polity.",
        "- **Prussia terminology hardened** (Clark 2006): 'Royal "
        "Prussia' = POLISH Prussia (Commonwealth territory until "
        "1772) and is banned as a synonym for Hohenzollern East "
        "Prussia; 1756 style is 'King IN Prussia'; "
        "polity ids unchanged. See `prussia_terminology_audit.csv`.",
        "- **Territorial binding contract** (before any boundary "
        "work): control binds to the most specific registered polity; "
        "composite roots (now COMPOSITE_TERRITORIAL_ACTOR: Habsburg, "
        "Prussian monarchies) hold control only where no constituent "
        "covers it; containers never control; root+member duplicate "
        "control forbidden; MAPGEN-008 Tokugawa rows untouched.",
        "",
        "## What this stage is (and is not)",
        "",
        "- This is the WHO and HOW-RELATED catalogue of 1756 Europe: "
        "polity existence, constitutional relationships, and 6 km "
        "representability audit.",
        "- NO historical boundary geometry was created; NO territorial "
        "control/claim rows were added (byte-proof V25). WHERE comes in "
        "the next stage after review.",
        "- The catalogue was built from the registered historical "
        "sources; Natural Earth is not an input (AST + data audit V16/"
        "V17). It is NOT a modern country list projected backwards.",
        "",
        "## Catalogue",
        "",
        f"- {len(europe_sp)} Europe scenario polities + the MAPGEN-008 "
        "Tokugawa pilot (untouched). Catalogue status: "
        f"**{catalogue_status}** — reported separately from scenario "
        f"data_status={meta['data_status']} (which stays FOUNDATION_ONLY "
        "until world political geography exists).",
        f"- Constitutional relationships: {len(rel)} rows "
        f"({json.dumps(rel_counts)}). Diplomatic relations (alliances, "
        "wars) are deliberately OUT of this table.",
        f"- Inclusion audit: {len(audit)} ACTIVE candidates of "
        f"{len(audit_all)} total rows ({n_sup} SUPERSEDED history). "
        f"ACTIVE inclusion_status counts: {json.dumps(inc_counts)} — "
        "'not in the list' always means 'not yet evaluated', never "
        "silently dropped (ACTIVE policy: `inclusion_policy_v2.md`).",
        f"- 6 km representability risks (ACTIVE rows): "
        f"{json.dumps(risk_counts)}. SUBHEX_REQUIRED/UNKNOWN are audit "
        "findings, not failures; areas were never guessed.",
        f"- Active UNRESOLVED candidates: {'; '.join(active_unres)}.",
        "",
        "## Modeling decisions on the known trap cases",
        "",
        "- **Great Britain / Hanover**: two territorial polities joined "
        "only by symmetric PERSONAL_UNION (George II). Never merged.",
        "- **Saxony / Poland-Lithuania**: PERSONAL_UNION (Augustus III); "
        "territories separate.",
        "- **Holy Roman Empire**: registered STRUCTURAL_CONTAINER; owns "
        f"zero territory; {imp} IMPERIAL_MEMBER_OF rows carry the "
        "structure (V13/V15 machine-check that membership creates no "
        "control).",
        f"- **Habsburg Monarchy**: composite actor + {n_habsburg} "
        "COMPOSITE_MEMBER_OF constituents (Bohemia, Hungary, Archduchy "
        "of Austria, Austrian Netherlands, Milan); Hungary deliberately "
        "has NO IMPERIAL_MEMBER_OF row (outside the Empire). Not a "
        "modern Austria polygon.",
        "- **Prussia**: 'Prussian Monarchy (Hohenzollern lands)' as the "
        "acting composite (interpretation DERIVED, per Clark), with "
        "Brandenburg (in-Empire electorate) and the Kingdom of Prussia "
        "proper (outside the Empire) as COMPOSITE_MEMBER_OF "
        "constituents. Not generated from modern Germany.",
        "- **Tuscany**: held by Emperor Francis Stephen; its tie to the "
        "Habsburg complex is deliberately UNEVALUATED (no forced "
        "relationship).",
        "- **Ireland**: personal union with legislative subordination "
        "noted, not modeled as annexation.",
        "- Playability is NOT decided: every polity has "
        "playability_status=UNDECIDED. Historical structure and gameplay "
        "playability are separate concepts.",
        "",
        "## Provenance",
        "",
        f"- Sources: {len(snap.sources)} registered works (NCMH VII "
        "1957, NCMH Atlas 1970, Wilson 2016, Clark 2006, Ingrao 2000, "
        "Szabo 2008 + the two MAPGEN-008 Japan sources). Wikipedia-class "
        "material was not used as an authority.",
        f"- Evidence: {len(snap.evidence)} rows; every scenario polity "
        "has POLITY_EXISTENCE evidence, every relationship carries a "
        "source. source_locator is work-level UNKNOWN (with reason) at "
        "catalogue stage — page-level pinpoint locators arrive with "
        "boundary evidence; page numbers were NOT fabricated "
        "(interpretation_level DIRECT/DERIVED recorded per row).",
        "",
        "## ID stability",
        "",
        "- polity_id/scenario_id permanent; sp_/src_/ev_ ids as in "
        "MAPGEN-008; NEW rel_ id = sha1(scenario|type|from|to), with "
        "participants sorted for SYMMETRIC types (PERSONAL_UNION), so "
        "symmetric rows are order-invariant.",
        "",
        "## Images",
        "",
    ]
    for n, a in aspects.items():
        lines.append(f"- `{n}` (aspect {a})")
    lines += [
        "",
        "## Validation",
        "",
        "- `scenario_validation.csv` lists every machine-checked gate "
        "of this run (upstream immutability, pilot regression, "
        "no-ownership-from-relationship, no-modern-admin, audit "
        "exhaustiveness, provenance, superseded-audit R2 gates, "
        "README-fact synchronisation). Any FAIL is surfaced as a run "
        "warning; the pass count lives in `scenario_summary.csv`, not "
        "in hand-written README text.",
        "",
        "## Known limitations",
        "",
        f"- Catalogue status {catalogue_status}: active UNRESOLVED "
        f"candidates = {'; '.join(active_unres)} (Lucca and Corsica "
        "were RESOLVED in MAPGEN-009R); class-level aggregation for "
        "minor imperial estates; Ottoman non-European lands out of "
        "scope; internal provincial structure (Dutch, PLC, Erblande) "
        "not subdivided.",
        "- display_name_ja uses established Japanese renderings; any "
        "questionable ones are flagged REVIEW_REQUIRED rather than "
        "invented.",
        "- Historical review welcome — every assertion is traceable to "
        "a registered source with recorded confidence.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
