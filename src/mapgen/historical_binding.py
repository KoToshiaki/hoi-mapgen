"""MAPGEN-011 — historical snapshot -> canonical hex binding machinery.

HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM MODERN
ADMINISTRATION. Source-level continuous geometry is NEVER rewritten to
suit the hex discretisation; hexification distortion is measured and
reported, and zero-hex features become overlay candidates instead of
silently disappearing.

All functions are pure and synthetic-testable; production use is gated
by validate_production_features (source discipline).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import shapely

from .islands import ground_area_perimeter

BINDING_METHOD = "MAX_GROUND_LAND_SHARE"
FORBIDDEN_PRODUCTION_AUTHORITY = {"VISUAL_QA_ONLY", "METHODOLOGY_REFERENCE"}
REPRESENTATION_STATUSES = ["GOOD", "BORDER_COARSE", "ENCLAVE_AT_RISK",
                           "ZERO_HEX_LOSS", "OVERLAY_REQUIRED",
                           "UNRESOLVED"]


def validate_production_features(features: pd.DataFrame,
                                 registry: pd.DataFrame,
                                 polity_mapping: pd.DataFrame,
                                 snapshot_date: str) -> list[str]:
    """Source-discipline gates for EVERY production boundary feature.

    Returns a list of violations (empty = pass). Notably enforces that a
    cross-section-only substrate (e.g. HALC 1500/1650/1800) can never
    become a 1756 feature without a separate political evidence source
    whose validity covers the snapshot date.
    """
    v: list[str] = []
    reg = registry.set_index("global_source_id")
    mapped = set(polity_mapping["historical_subject_id"])
    for t in features.itertuples():
        fid = t.boundary_feature_id
        for col in ("geometry_source_id", "political_evidence_source_id"):
            sid = getattr(t, col, None)
            if not isinstance(sid, str) or sid not in reg.index:
                v.append(f"{fid}: {col} missing/unregistered ({sid})")
                continue
            level = reg.loc[sid, "authority_level"]
            if col == "political_evidence_source_id" \
                    and level in FORBIDDEN_PRODUCTION_AUTHORITY:
                v.append(f"{fid}: political evidence authority {level} "
                         "is forbidden for production")
        loc = getattr(t, "source_locator", None)
        if not isinstance(loc, str) or not loc or loc == "UNKNOWN":
            v.append(f"{fid}: exact source_locator required for "
                     "production geometry")
        vf, vt = t.valid_from, t.valid_to
        if not (isinstance(vf, str) and isinstance(vt, str)
                and vf != "UNKNOWN" and vt != "UNKNOWN"
                and vf <= snapshot_date <= vt):
            v.append(f"{fid}: temporal validity [{vf}..{vt}] does not "
                     f"explicitly cover {snapshot_date} (interpolation "
                     "forbidden)")
        g = getattr(t, "geometry", None)
        if g is None or shapely.is_empty(g):
            v.append(f"{fid}: empty geometry")
        elif not shapely.is_valid(g):
            v.append(f"{fid}: invalid geometry")
        if t.historical_subject_id not in mapped:
            v.append(f"{fid}: no explicit scenario polity mapping for "
                     f"{t.historical_subject_id} (name-guessing is "
                     "forbidden)")
    if features["boundary_feature_id"].duplicated().any():
        v.append("duplicate boundary_feature_id present")
    return v


def check_contested_overlaps(snapshot: pd.DataFrame,
                             min_overlap_km2: float = 0.01) -> list[str]:
    """Independent polities occupying the same area must be explicitly
    contested (DISPUTED/DE_FACTO vs DE_JURE roles) — silent overlap or
    silent clipping is forbidden."""
    v = []
    rows = list(snapshot.itertuples())
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            if a.scenario_polity_id == b.scenario_polity_id:
                continue
            inter = shapely.intersection(a.geometry, b.geometry)
            if shapely.is_empty(inter):
                continue
            km2, _ = ground_area_perimeter(inter)
            if km2 < min_overlap_km2:
                continue
            roles = {a.feature_role, b.feature_role}
            contested = ("DISPUTED_BOUNDARY" in roles
                         or {"DE_FACTO_CONTROL_BOUNDARY",
                             "DE_JURE_CLAIM_BOUNDARY"} <= roles
                         or "DE_JURE_CLAIM_BOUNDARY" in roles)
            if not contested:
                v.append(f"{a.boundary_feature_id} vs "
                         f"{b.boundary_feature_id}: {km2:.2f} km2 "
                         "overlap between independent polities without "
                         "explicit contested semantics")
    return v


def bind_snapshot_to_hexes(snapshot, hex_polys: np.ndarray,
                           hex_ids: list[str], hex_land_fraction: np.ndarray,
                           hex_is_terrestrial: np.ndarray,
                           scenario_id: str, snapshot_date: str,
                           hex_plane_area_m2: float) -> pd.DataFrame:
    """Bind 1756 snapshot control footprints to canonical hexes.

    Official method MAX_GROUND_LAND_SHARE: many-to-many ground-area
    intersections are all preserved; the gameplay winner per terrestrial
    hex is the polity with the largest intersection_ground_km2 (exact
    ties broken by stable scenario_polity_id order). Hex centres are
    NEVER a political authority. OCEAN hexes are never land targets.
    """
    ctrl = snapshot[snapshot["feature_role"].isin(
        ["POLITY_EXTERNAL_BOUNDARY", "DE_FACTO_CONTROL_BOUNDARY"])]
    rows = []
    if len(ctrl):
        geoms = np.array(list(ctrl["geometry"]), dtype=object)
        tree = shapely.STRtree(geoms)
        hi, fi = tree.query(hex_polys, predicate="intersects")
        for h, f in zip(hi, fi):
            if not hex_is_terrestrial[h]:
                continue  # OCEAN hex: never a terrestrial target
            inter = shapely.intersection(hex_polys[int(h)], geoms[int(f)])
            if shapely.is_empty(inter):
                continue
            km2, _ = ground_area_perimeter(inter)
            if km2 <= 1e-9:
                continue
            hex_ground, _ = ground_area_perimeter(hex_polys[int(h)])
            land_km2 = hex_ground * float(hex_land_fraction[h])
            frow = ctrl.iloc[int(f)]
            rows.append({
                "scenario_id": scenario_id,
                "snapshot_date": snapshot_date,
                "hex_id": hex_ids[int(h)],
                "scenario_polity_id": frow["scenario_polity_id"],
                "historical_subject_id": frow["historical_subject_id"],
                "boundary_feature_id": frow["boundary_feature_id"],
                "intersection_ground_km2": round(km2, 6),
                "share_of_terrestrial_hex_land":
                    round(min(km2 / land_km2, 1.0), 6)
                    if land_km2 > 0 else None,
                "source_confidence": frow["source_confidence"],
                "binding_method": BINDING_METHOD,
            })
    mem = pd.DataFrame(rows, columns=[
        "scenario_id", "snapshot_date", "hex_id", "scenario_polity_id",
        "historical_subject_id", "boundary_feature_id",
        "intersection_ground_km2", "share_of_terrestrial_hex_land",
        "source_confidence", "binding_method"])
    if not len(mem):
        for c in ("is_dominant", "dominance_margin", "membership_count",
                  "border_hex"):
            mem[c] = pd.Series(dtype="object")
        return mem
    # Aggregate per hex+polity (a polity may touch a hex via several
    # features), then decide the winner per hex.
    agg = mem.groupby(["hex_id", "scenario_polity_id"], as_index=False) \
        .agg(intersection_ground_km2=("intersection_ground_km2", "sum"),
             share_of_terrestrial_hex_land=(
                 "share_of_terrestrial_hex_land", "sum"),
             historical_subject_id=("historical_subject_id", "first"),
             boundary_feature_id=("boundary_feature_id", "first"),
             source_confidence=("source_confidence", "min"))
    agg["scenario_id"] = scenario_id
    agg["snapshot_date"] = snapshot_date
    agg["binding_method"] = BINDING_METHOD
    out = []
    for hid, grp in agg.groupby("hex_id"):
        # Deterministic: sort by (-area, polity_id) — exact ties fall
        # back to stable id order.
        grp = grp.sort_values(
            ["intersection_ground_km2", "scenario_polity_id"],
            ascending=[False, True]).reset_index(drop=True)
        top = float(grp.loc[0, "intersection_ground_km2"])
        second = float(grp.loc[1, "intersection_ground_km2"]) \
            if len(grp) > 1 else 0.0
        for i, r in grp.iterrows():
            d = dict(r)
            d["is_dominant"] = i == 0
            d["dominance_margin"] = round(top - second, 6) if i == 0 \
                else round(float(r["intersection_ground_km2"]) - top, 6)
            d["membership_count"] = len(grp)
            d["border_hex"] = len(grp) > 1
            out.append(d)
    return pd.DataFrame(out)


def hexification_audit(snapshot: pd.DataFrame,
                       membership: pd.DataFrame) -> pd.DataFrame:
    """Per-polity distortion audit: the hex map is a representation of
    the source geometry, and its error is measured, never hidden."""
    rows = []
    for pid, grp in snapshot.groupby("scenario_polity_id"):
        ctrl = grp[grp["feature_role"].isin(
            ["POLITY_EXTERNAL_BOUNDARY", "DE_FACTO_CONTROL_BOUNDARY"])]
        if not len(ctrl):
            continue
        src_km2 = 0.0
        comp_count = 0
        for g in ctrl["geometry"]:
            km2, _ = ground_area_perimeter(g)
            src_km2 += km2
            comp_count += len(shapely.get_parts(g)) \
                if g.geom_type.startswith("Multi") else 1
        mine = membership[membership["scenario_polity_id"] == pid] \
            if len(membership) else membership
        dom = mine[mine["is_dominant"]] if len(mine) else mine
        hex_km2 = float(mine["intersection_ground_km2"].sum()) \
            if len(mine) else 0.0
        dom_hexes = len(dom)
        border = int(mine["border_hex"].sum()) if len(mine) else 0
        err = hex_km2 - src_km2
        zero_loss = dom_hexes == 0 and src_km2 > 0
        if zero_loss:
            status = "ZERO_HEX_LOSS"
        elif src_km2 > 0 and abs(err) / src_km2 > 0.10:
            status = "BORDER_COARSE"
        elif comp_count > dom_hexes:
            status = "ENCLAVE_AT_RISK"
        else:
            status = "GOOD"
        rows.append({
            "scenario_polity_id": pid,
            "source_ground_area_km2": round(src_km2, 4),
            "hex_represented_ground_area_km2": round(hex_km2, 4),
            "area_error_km2": round(err, 4),
            "area_error_fraction": round(err / src_km2, 6)
            if src_km2 > 0 else None,
            "source_component_count": comp_count,
            "represented_hex_count": dom_hexes,
            "zero_hex_survival": not zero_loss,
            "border_hex_count": border,
            "mean_dominance_margin": round(
                float(dom["dominance_margin"].mean()), 6)
            if len(dom) else None,
            "max_boundary_displacement_or_proxy": None,
            "representation_status": status,
        })
    return pd.DataFrame(rows)


def overlay_candidates_from_audit(audit: pd.DataFrame,
                                  snapshot: pd.DataFrame) -> pd.DataFrame:
    """Zero-hex features are NEVER silently dropped: they become formal
    overlay candidates for the future political overlay mechanism."""
    rows = []
    lost = audit[audit["representation_status"] == "ZERO_HEX_LOSS"] \
        if len(audit) else audit
    for t in lost.itertuples():
        src = snapshot[snapshot["scenario_polity_id"]
                       == t.scenario_polity_id]
        fid = src.iloc[0]["boundary_feature_id"] if len(src) else None
        rows.append({
            "candidate_id": f"hpo_{t.scenario_polity_id}",
            "scenario_polity_id": t.scenario_polity_id,
            "source_feature_id": fid,
            "source_ground_area_km2": t.source_ground_area_km2,
            "reason": "feature survives in source geometry but wins "
                      "zero hexes under MAX_GROUND_LAND_SHARE",
            "recommended_representation": "SUBHEX_POLITICAL_OVERLAY",
            "source_id": None,
            "status": "REVIEW_REQUIRED",
        })
    return pd.DataFrame(rows, columns=[
        "candidate_id", "scenario_polity_id", "source_feature_id",
        "source_ground_area_km2", "reason",
        "recommended_representation", "source_id", "status"])


def controls_from_membership(membership: pd.DataFrame, scenario_id: str,
                             source_id_by_polity: dict,
                             confidence_by_polity: dict) -> pd.DataFrame:
    """Gameplay control rows from dominant hex winners. Claims are NEVER
    generated here — claims require their own historical evidence."""
    if not len(membership):
        return pd.DataFrame(columns=[
            "scenario_id", "territorial_target_type",
            "territorial_target_id", "controller_scenario_polity_id",
            "control_status", "source_confidence", "source_id", "notes"])
    dom = membership[membership["is_dominant"]]
    rows = []
    for t in dom.itertuples():
        rows.append({
            "scenario_id": scenario_id,
            "territorial_target_type": "TERRESTRIAL_HEX",
            "territorial_target_id": t.hex_id,
            "controller_scenario_polity_id": t.scenario_polity_id,
            "control_status": "CONTROLLED",
            "source_confidence": t.source_confidence,
            "source_id": source_id_by_polity.get(t.scenario_polity_id),
            "notes": f"historical hex binding {BINDING_METHOD}; "
                     f"membership_count={t.membership_count}",
        })
    return pd.DataFrame(rows)
