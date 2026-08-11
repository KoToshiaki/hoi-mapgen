"""MAPGEN-011R — hardened historical snapshot -> canonical hex binding.

HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM MODERN
ADMINISTRATION.

Hardened semantics (hpg algorithm 1.1.0):
- Production authority lives in EVIDENCE ASSERTIONS, not in sources:
  a feature must reference a registered assertion whose subject matches,
  whose validity explicitly covers the snapshot date, and whose
  political_authority is YES. A cross-section geometry source can never
  back a snapshot political claim by itself (fake-1756 exploit closed).
- Land denominators/numerators use the EXACT hex ∩ OSM-coast-authority
  land geometry — sea area never counts as political land, and
  land_fraction approximations are forbidden.
- Same-polity multi-feature coverage is UNIONED before areas are
  computed: no double counting; feature-level provenance is kept in a
  separate membership table.
- Membership conservation (geometry bookkeeping) and gameplay
  hexification distortion (winner omission/commission) are separate
  audits.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import shapely

from .islands import ground_area_perimeter

BINDING_METHOD = "MAX_GROUND_LAND_SHARE"
FORBIDDEN_PRODUCTION_AUTHORITY = {"VISUAL_QA_ONLY", "METHODOLOGY_REFERENCE"}
SHARE_TOLERANCE = 1e-6
REPRESENTATION_STATUSES = ["GOOD", "BORDER_COARSE", "ENCLAVE_AT_RISK",
                           "ZERO_HEX_LOSS", "OVERLAY_REQUIRED",
                           "UNRESOLVED"]
CONTROL_ROLES = ["POLITY_EXTERNAL_BOUNDARY", "DE_FACTO_CONTROL_BOUNDARY"]


def _g_km2(geom) -> float:
    if geom is None or shapely.is_empty(geom):
        return 0.0
    a, _ = ground_area_perimeter(geom)
    return a


# --------------------------------------------------------------------------
# Source discipline (MAPGEN-011R: assertion-backed, never vacuous)
# --------------------------------------------------------------------------
def validate_production_features(features: pd.DataFrame,
                                 registry: pd.DataFrame,
                                 assertions: pd.DataFrame,
                                 polity_mapping: pd.DataFrame,
                                 snapshot_date: str) -> list[str]:
    """Production gates for every boundary feature. Returns violations.

    The political authority chain is: feature.political_evidence_id ->
    registered evidence ASSERTION (subject match + explicit snapshot
    coverage + political_authority=YES + exact locator) -> registered
    source with non-forbidden authority. Feature-side validity alone can
    never admit a feature.
    """
    v: list[str] = []
    reg = registry.set_index("global_source_id")
    ass = assertions.set_index("historical_evidence_id") \
        if len(assertions) else assertions
    mapped = set(polity_mapping["historical_subject_id"])
    for t in features.itertuples():
        fid = t.boundary_feature_id
        gsid = getattr(t, "geometry_source_id", None)
        if not isinstance(gsid, str) or gsid not in reg.index:
            v.append(f"{fid}: geometry_source_id missing/unregistered "
                     f"({gsid})")
        eid = getattr(t, "political_evidence_id", None)
        if not isinstance(eid, str) or not len(assertions) \
                or eid not in ass.index:
            v.append(f"{fid}: political_evidence_id missing or not a "
                     f"registered evidence assertion ({eid}) — a source "
                     "id alone is NOT political authority")
        else:
            a = ass.loc[eid]
            if a["historical_subject_id"] != t.historical_subject_id:
                v.append(f"{fid}: evidence assertion subject "
                         f"{a['historical_subject_id']} != feature "
                         f"subject {t.historical_subject_id}")
            avf, avt = str(a["valid_from"]), str(a["valid_to"])
            if not (avf != "UNKNOWN" and avt != "UNKNOWN"
                    and avf <= snapshot_date <= avt):
                v.append(f"{fid}: evidence assertion validity "
                         f"[{avf}..{avt}] does not explicitly cover "
                         f"{snapshot_date} — feature-side dates cannot "
                         "substitute (fake-snapshot exploit)")
            if str(a["political_authority"]).upper() != "YES":
                v.append(f"{fid}: evidence assertion has no political "
                         "authority (e.g. GEOMETRIC_SUBSTRATE_ONLY)")
            loc = str(a["exact_locator"])
            if not loc or loc.startswith("UNKNOWN"):
                v.append(f"{fid}: evidence assertion lacks an exact "
                         "locator")
            esid = a["global_source_id"]
            if esid not in reg.index:
                v.append(f"{fid}: assertion source {esid} unregistered")
            elif reg.loc[esid, "authority_level"] \
                    in FORBIDDEN_PRODUCTION_AUTHORITY:
                v.append(f"{fid}: assertion source authority "
                         f"{reg.loc[esid, 'authority_level']} is "
                         "forbidden for production")
        loc = getattr(t, "source_locator", None)
        if not isinstance(loc, str) or not loc or loc == "UNKNOWN":
            v.append(f"{fid}: exact feature source_locator required")
        vf, vt = str(t.valid_from), str(t.valid_to)
        if not (vf != "UNKNOWN" and vt != "UNKNOWN"
                and vf <= snapshot_date <= vt):
            v.append(f"{fid}: feature validity [{vf}..{vt}] does not "
                     f"explicitly cover {snapshot_date}")
        g = getattr(t, "geometry", None)
        if g is None or shapely.is_empty(g):
            v.append(f"{fid}: empty geometry")
        elif not shapely.is_valid(g):
            v.append(f"{fid}: invalid geometry")
        if t.historical_subject_id not in mapped:
            v.append(f"{fid}: no explicit scenario polity mapping for "
                     f"{t.historical_subject_id}")
    if len(features) and features["boundary_feature_id"].duplicated().any():
        v.append("duplicate boundary_feature_id present")
    return v


def check_contested_overlaps(snapshot: pd.DataFrame,
                             min_overlap_km2: float = 0.01) -> list[str]:
    """Independent polities on the same area must be explicitly
    contested — silent overlap/clipping is forbidden."""
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
            km2 = _g_km2(inter)
            if km2 < min_overlap_km2:
                continue
            roles = {a.feature_role, b.feature_role}
            contested = ("DISPUTED_BOUNDARY" in roles
                         or "DE_JURE_CLAIM_BOUNDARY" in roles)
            if not contested:
                v.append(f"{a.boundary_feature_id} vs "
                         f"{b.boundary_feature_id}: {km2:.2f} km2 "
                         "overlap between independent polities without "
                         "explicit contested semantics")
    return v


# --------------------------------------------------------------------------
# Exact-land hex binding (feature-level + unioned polity-level)
# --------------------------------------------------------------------------
def bind_snapshot_to_hexes(snapshot, hex_polys: np.ndarray,
                           hex_ids: list[str],
                           hex_land_geoms: np.ndarray,
                           hex_is_terrestrial: np.ndarray,
                           scenario_id: str, snapshot_date: str):
    """Bind snapshot control footprints to canonical hexes.

    hex_land_geoms[i] MUST be the exact canonical-land geometry of hex i
    (hex ∩ OSM coast-authority land) — the ONLY admissible denominator.
    Returns (feature_membership, polity_membership). The winner per
    terrestrial hex is decided on the UNION of each polity's control
    geometry clipped to the hex land (no same-polity double counting);
    exact ties break by stable scenario_polity_id order.
    Raises ValueError if any land share exceeds 1 beyond float
    tolerance (silent clipping is forbidden).
    """
    ctrl = snapshot[snapshot["feature_role"].isin(CONTROL_ROLES)]
    fcols = ["scenario_id", "snapshot_date", "hex_id",
             "scenario_polity_id", "historical_subject_id",
             "boundary_feature_id", "political_evidence_id",
             "intersection_ground_km2", "binding_method"]
    pcols = ["scenario_id", "snapshot_date", "hex_id",
             "scenario_polity_id", "historical_subject_id",
             "intersection_ground_km2", "share_of_terrestrial_hex_land",
             "is_dominant", "dominance_margin", "membership_count",
             "border_hex", "contributing_boundary_feature_ids",
             "political_evidence_ids", "source_confidence",
             "binding_method"]
    if not len(ctrl) or not len(hex_polys):
        return (pd.DataFrame(columns=fcols), pd.DataFrame(columns=pcols))
    tree = shapely.STRtree(np.asarray(hex_polys, dtype=object))
    feat_rows = []
    pol_rows = []
    land_km2_cache: dict[int, float] = {}

    def land_km2(h):
        if h not in land_km2_cache:
            land_km2_cache[h] = _g_km2(hex_land_geoms[h])
        return land_km2_cache[h]

    # Feature-level provenance membership (exact land intersections).
    hex_polities: dict[int, dict] = {}
    for t in ctrl.itertuples():
        for h in np.sort(tree.query(t.geometry, predicate="intersects")):
            h = int(h)
            if not hex_is_terrestrial[h]:
                continue  # OCEAN hex: never a terrestrial target
            land = hex_land_geoms[h]
            if land is None or shapely.is_empty(land):
                continue
            inter = shapely.intersection(t.geometry, land)
            km2 = _g_km2(inter)
            if km2 <= 1e-9:
                continue
            feat_rows.append({
                "scenario_id": scenario_id,
                "snapshot_date": snapshot_date,
                "hex_id": hex_ids[h],
                "scenario_polity_id": t.scenario_polity_id,
                "historical_subject_id": t.historical_subject_id,
                "boundary_feature_id": t.boundary_feature_id,
                "political_evidence_id": getattr(
                    t, "political_evidence_id", None),
                "intersection_ground_km2": round(km2, 6),
                "binding_method": BINDING_METHOD,
            })
            hex_polities.setdefault(h, {}).setdefault(
                t.scenario_polity_id, []).append(t)
    # Polity-level UNION membership + winner decision.
    for h, pol_feats in sorted(hex_polities.items()):
        land = hex_land_geoms[h]
        lkm2 = land_km2(h)
        entries = []
        for pid in sorted(pol_feats):
            feats = pol_feats[pid]
            union = shapely.union_all([f.geometry for f in feats])
            km2 = _g_km2(shapely.intersection(union, land))
            if km2 <= 1e-9:
                continue
            share = km2 / lkm2 if lkm2 > 0 else 0.0
            if share > 1.0 + SHARE_TOLERANCE:
                raise ValueError(
                    f"land share {share:.9f} > 1 on hex {hex_ids[h]} "
                    f"for {pid} — exact-land contract violated (silent "
                    "clipping is forbidden)")
            entries.append({
                "scenario_id": scenario_id,
                "snapshot_date": snapshot_date,
                "hex_id": hex_ids[h], "scenario_polity_id": pid,
                "historical_subject_id":
                    feats[0].historical_subject_id,
                "intersection_ground_km2": round(km2, 6),
                "share_of_terrestrial_hex_land": round(min(share, 1.0), 6),
                "contributing_boundary_feature_ids": "|".join(
                    sorted({f.boundary_feature_id for f in feats})),
                "political_evidence_ids": "|".join(sorted(
                    {str(getattr(f, "political_evidence_id", None))
                     for f in feats})),
                "source_confidence": min(
                    str(f.source_confidence) for f in feats),
                "binding_method": BINDING_METHOD,
            })
        if not entries:
            continue
        entries.sort(key=lambda e: (-e["intersection_ground_km2"],
                                    e["scenario_polity_id"]))
        top = entries[0]["intersection_ground_km2"]
        second = entries[1]["intersection_ground_km2"] \
            if len(entries) > 1 else 0.0
        for i, e in enumerate(entries):
            e["is_dominant"] = i == 0
            e["dominance_margin"] = round(top - second, 6) if i == 0 \
                else round(e["intersection_ground_km2"] - top, 6)
            e["membership_count"] = len(entries)
            e["border_hex"] = len(entries) > 1
        pol_rows.extend(entries)
    return (pd.DataFrame(feat_rows, columns=fcols),
            pd.DataFrame(pol_rows, columns=pcols))


# --------------------------------------------------------------------------
# Audits: conservation (geometry bookkeeping) vs winner distortion
# --------------------------------------------------------------------------
def _polity_source_land(snapshot, land_union):
    out = {}
    ctrl = snapshot[snapshot["feature_role"].isin(CONTROL_ROLES)]
    for pid, grp in ctrl.groupby("scenario_polity_id"):
        union = shapely.union_all(list(grp["geometry"]))
        clipped = shapely.intersection(union, land_union) \
            if land_union is not None else union
        comp = sum(len(shapely.get_parts(g))
                   if g.geom_type.startswith("Multi") else 1
                   for g in grp["geometry"])
        out[pid] = (clipped, _g_km2(clipped), comp)
    return out


def membership_conservation_audit(snapshot, polity_mem,
                                  land_union) -> pd.DataFrame:
    """A: geometry bookkeeping — source control land area must equal the
    sum of exact membership intersections (hex set must cover the
    footprint; any gap is a real conservation error, never hidden)."""
    rows = []
    src = _polity_source_land(snapshot, land_union)
    for pid, (geom, km2, comp) in sorted(src.items()):
        mine = polity_mem[polity_mem["scenario_polity_id"] == pid] \
            if len(polity_mem) else polity_mem
        s = float(mine["intersection_ground_km2"].sum()) \
            if len(mine) else 0.0
        rows.append({
            "scenario_polity_id": pid,
            "source_land_ground_km2": round(km2, 4),
            "membership_intersection_ground_km2": round(s, 4),
            "conservation_error_km2": round(s - km2, 4),
            "conservation_error_fraction": round((s - km2) / km2, 6)
            if km2 > 0 else None,
        })
    return pd.DataFrame(rows)


def hexification_audit(snapshot, polity_mem, hex_land_by_id: dict,
                       land_union) -> pd.DataFrame:
    """B: gameplay distortion — the WINNER hex representation vs the
    source footprint, with real omission/commission computed from the
    geometry symmetric difference."""
    rows = []
    src = _polity_source_land(snapshot, land_union)
    for pid, (geom, src_km2, comp) in sorted(src.items()):
        mine = polity_mem[polity_mem["scenario_polity_id"] == pid] \
            if len(polity_mem) else polity_mem
        dom = mine[mine["is_dominant"]] if len(mine) else mine
        won = [hex_land_by_id[h] for h in dom["hex_id"]
               if h in hex_land_by_id] if len(dom) else []
        won_union = shapely.union_all(won) if won else None
        winner_km2 = _g_km2(won_union)
        omission = _g_km2(shapely.difference(geom, won_union)) \
            if won_union is not None else src_km2
        commission = _g_km2(shapely.difference(won_union, geom)) \
            if won_union is not None else 0.0
        zero_loss = len(dom) == 0 and src_km2 > 0
        symdiff = omission + commission
        if zero_loss:
            status = "ZERO_HEX_LOSS"
        elif src_km2 > 0 and symdiff / src_km2 > 0.5:
            status = "BORDER_COARSE"
        elif comp > len(dom):
            status = "ENCLAVE_AT_RISK"
        else:
            status = "GOOD"
        rows.append({
            "scenario_polity_id": pid,
            "source_land_ground_km2": round(src_km2, 4),
            "winner_represented_ground_km2": round(winner_km2, 4),
            "winner_area_error_km2": round(winner_km2 - src_km2, 4),
            "winner_area_error_fraction":
                round((winner_km2 - src_km2) / src_km2, 6)
                if src_km2 > 0 else None,
            "omission_ground_km2": round(omission, 4),
            "commission_ground_km2": round(commission, 4),
            "symmetric_difference_ground_km2": round(symdiff, 4),
            "source_component_count": comp,
            "represented_hex_count": int(len(dom)),
            "zero_hex_survival": not zero_loss,
            "border_hex_count": int(mine["border_hex"].sum())
            if len(mine) else 0,
            "mean_dominance_margin": round(
                float(dom["dominance_margin"].mean()), 6)
            if len(dom) else None,
            "representation_status": status,
        })
    return pd.DataFrame(rows)


def overlay_candidates_from_audit(audit, snapshot) -> pd.DataFrame:
    """Zero-hex features are NEVER silently dropped — and every
    candidate must carry full provenance (raise otherwise)."""
    rows = []
    lost = audit[audit["representation_status"] == "ZERO_HEX_LOSS"] \
        if len(audit) else audit
    for t in lost.itertuples():
        src = snapshot[snapshot["scenario_polity_id"]
                       == t.scenario_polity_id]
        if not len(src):
            raise ValueError(f"overlay candidate {t.scenario_polity_id} "
                             "without source feature provenance")
        f = src.iloc[0]
        eid = f.get("political_evidence_id")
        gsid = f.get("global_source_id")
        if not isinstance(eid, str) or not isinstance(gsid, str):
            raise ValueError(
                f"overlay candidate {t.scenario_polity_id}: provenance "
                "(political_evidence_id/global_source_id) is mandatory")
        rows.append({
            "candidate_id": f"hpo_{t.scenario_polity_id}",
            "scenario_polity_id": t.scenario_polity_id,
            "source_feature_id": f["boundary_feature_id"],
            "political_evidence_id": eid,
            "global_source_id": gsid,
            "source_ground_area_km2": t.source_land_ground_km2,
            "reason": "feature survives in source geometry but wins "
                      "zero hexes under MAX_GROUND_LAND_SHARE",
            "recommended_representation": "SUBHEX_POLITICAL_OVERLAY",
            "status": "REVIEW_REQUIRED",
        })
    return pd.DataFrame(rows, columns=[
        "candidate_id", "scenario_polity_id", "source_feature_id",
        "political_evidence_id", "global_source_id",
        "source_ground_area_km2", "reason",
        "recommended_representation", "status"])


def controls_from_membership(polity_mem, scenario_id: str,
                             provenance_by_polity: dict) -> pd.DataFrame:
    """Control rows from dominant winners — provenance is MANDATORY
    (source_id + evidence ids per polity); claims are never derived."""
    cols = ["scenario_id", "territorial_target_type",
            "territorial_target_id", "controller_scenario_polity_id",
            "control_status", "source_confidence", "source_id",
            "political_evidence_ids", "boundary_feature_ids", "notes"]
    if not len(polity_mem):
        return pd.DataFrame(columns=cols)
    dom = polity_mem[polity_mem["is_dominant"]]
    rows = []
    for t in dom.itertuples():
        prov = provenance_by_polity.get(t.scenario_polity_id)
        if not prov or not prov.get("source_id"):
            raise ValueError(
                f"control for {t.scenario_polity_id} without provenance "
                "— None-provenance production rows are forbidden")
        rows.append({
            "scenario_id": scenario_id,
            "territorial_target_type": "TERRESTRIAL_HEX",
            "territorial_target_id": t.hex_id,
            "controller_scenario_polity_id": t.scenario_polity_id,
            "control_status": "CONTROLLED",
            "source_confidence": t.source_confidence,
            "source_id": prov["source_id"],
            "political_evidence_ids": t.political_evidence_ids,
            "boundary_feature_ids": t.contributing_boundary_feature_ids,
            "notes": f"historical hex binding {BINDING_METHOD}; "
                     f"membership_count={t.membership_count}",
        })
    return pd.DataFrame(rows)
