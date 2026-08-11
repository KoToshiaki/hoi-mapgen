"""MAPGEN-011R/011R2 — historical snapshot -> canonical hex binding.

HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM MODERN
ADMINISTRATION.

Responsibility split (never conflated):
  SOURCE            a work (book, map, GIS dataset)
  EVIDENCE ASSERTION what one locator in that work proves, for which
                    subject, for which dates, with geometry vs political
                    authority
  BOUNDARY FEATURE  drawn geometry, admitted to production only by a
                    BUNDLE of assertions linked with explicit roles

Hardened semantics (hpg algorithm 1.2.0):
- Bundle compatibility: existence evidence can never authorise a
  boundary; de-facto needs POLITICAL_CONTROL, de-jure needs
  DE_JURE_CLAIM; UNCERTAIN_BOUNDARY is never gameplay-convertible.
- GEOMETRY_SHAPE evidence needs geometry_authority=YES; when its
  represented dates do not cover the snapshot, an unbroken
  TERRITORIAL_CONTINUITY bridge is required (gaps are never
  interpolated).
- Confidence aggregates worst-of-bundle on an explicit ordinal.
- Exact hex ∩ OSM-coast-authority land geometry is the ONLY land basis,
  shared by binding and both audits (single source of truth).
- Same-polity multi-feature coverage is unioned before the winner
  decision; component counts are measured on that unioned land geometry.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import shapely

from .historical_geometry import (CONFIDENCE_ORDER, EVIDENCE_ROLES,
                                  FEATURE_ROLE_REQUIREMENTS,
                                  GAMEPLAY_CONVERTIBLE_ROLES,
                                  NON_AUTHORISING_ROLES, confidence_rank,
                                  select_features_for_snapshot,
                                  worst_confidence)
from .islands import ground_area_perimeter

BINDING_METHOD = "MAX_GROUND_LAND_SHARE"
FORBIDDEN_PRODUCTION_AUTHORITY = {"VISUAL_QA_ONLY", "METHODOLOGY_REFERENCE"}
SHARE_TOLERANCE = 1e-6
LAND_MASK_TOLERANCE_KM2 = 1e-6
REPRESENTATION_STATUSES = ["GOOD", "BORDER_COARSE", "ENCLAVE_AT_RISK",
                           "ZERO_HEX_LOSS", "OVERLAY_REQUIRED",
                           "UNRESOLVED"]
CONTROL_ROLES = ["POLITY_EXTERNAL_BOUNDARY", "DE_FACTO_CONTROL_BOUNDARY"]
ID_SEPARATOR = "|"


def _g_km2(geom) -> float:
    if geom is None or shapely.is_empty(geom):
        return 0.0
    a, _ = ground_area_perimeter(geom)
    return a


def _truthy(v) -> bool:
    return str(v).strip().upper() in {"YES", "TRUE", "1"}


def _joined(values) -> str:
    return ID_SEPARATOR.join(sorted({str(v) for v in values if v is not None
                                     and str(v) != "nan"}))


# --------------------------------------------------------------------------
# Land mask: single source of truth
# --------------------------------------------------------------------------
def land_union_from(hex_land, explicit=None):
    """Derive the coverage land union from the SAME per-hex land mask the
    binding used. An explicit union may be passed only if it is
    geometrically equivalent (symmetric difference ~ 0), otherwise this
    raises — binding and audits may never use different land masks."""
    geoms = list(hex_land.values()) if isinstance(hex_land, dict) \
        else [g for g in hex_land]
    geoms = [shapely.make_valid(g) for g in geoms
             if g is not None and not shapely.is_empty(g)]
    derived = shapely.union_all(geoms) if geoms else None
    if explicit is None:
        return derived
    if derived is None:
        raise ValueError("land mask mismatch: derived union is empty but "
                         "an explicit land_union was supplied")
    diff = _g_km2(shapely.symmetric_difference(derived, explicit))
    if diff > LAND_MASK_TOLERANCE_KM2:
        raise ValueError(
            f"land mask mismatch: explicit land_union differs from the "
            f"per-hex land mask by {diff:.6f} km2 — binding and audits "
            "must share one land authority")
    return derived


# --------------------------------------------------------------------------
# Evidence bundle evaluation (MAPGEN-011R2)
# --------------------------------------------------------------------------
def _bridge_covers(intervals, start: str, end: str) -> bool:
    """True when the merged continuity intervals cover [start, end]
    without a gap. Missing periods are NEVER interpolated."""
    if start > end:
        start, end = end, start
    ivs = sorted((a, b) for a, b in intervals
                 if a and b and a != "UNKNOWN" and b != "UNKNOWN")
    cur = start
    for a, b in ivs:
        if a > cur:
            return False  # gap
        if b > cur:
            cur = b
        if cur >= end:
            return True
    return cur >= end


def evaluate_feature_bundle(feature, links: pd.DataFrame,
                            assertions: pd.DataFrame,
                            registry: pd.DataFrame,
                            snapshot_date: str):
    """Evaluate ONE feature's evidence bundle.

    Returns (violations, info) where info carries the aggregated
    confidence and the provenance id sets actually used.
    """
    v: list[str] = []
    fid = feature["boundary_feature_id"]
    subject = feature["historical_subject_id"]
    role = feature["feature_role"]
    reg = registry.set_index("global_source_id") if len(registry) \
        else registry
    ass = assertions.set_index("historical_evidence_id") \
        if len(assertions) else assertions
    info = {"confidence": "UNKNOWN", "evidence_ids": set(),
            "source_ids": set(), "roles": set()}

    if role not in GAMEPLAY_CONVERTIBLE_ROLES:
        v.append(f"{fid}: feature_role {role} is not convertible to "
                 "production gameplay control (review/audit geometry "
                 "only)")
        return v, info
    my = links[links["boundary_feature_id"] == fid] if len(links) \
        else links
    if not len(my):
        v.append(f"{fid}: no evidence bundle linked (a feature is never "
                 "authorised by a source id alone)")
        return v, info
    bad_roles = [r for r in my["evidence_role"]
                 if r not in EVIDENCE_ROLES]
    if bad_roles:
        v.append(f"{fid}: unknown evidence_role(s) {sorted(set(bad_roles))}")

    by_role: dict[str, list] = {}
    for t in my.itertuples():
        eid = t.historical_evidence_id
        if not len(ass) or eid not in ass.index:
            v.append(f"{fid}: linked evidence {eid} is not a registered "
                     "assertion")
            continue
        a = ass.loc[eid]
        if a["historical_subject_id"] != subject:
            v.append(f"{fid}: evidence {eid} subject "
                     f"{a['historical_subject_id']} != feature subject "
                     f"{subject}")
            continue
        loc = str(a["exact_locator"])
        if not loc or loc.startswith("UNKNOWN"):
            v.append(f"{fid}: evidence {eid} lacks an exact locator")
            continue
        sid = a["global_source_id"]
        if not len(reg) or sid not in reg.index:
            v.append(f"{fid}: evidence {eid} source {sid} unregistered")
            continue
        level = reg.loc[sid, "authority_level"]
        if level in FORBIDDEN_PRODUCTION_AUTHORITY \
                and t.evidence_role not in NON_AUTHORISING_ROLES:
            v.append(f"{fid}: evidence {eid} source authority {level} is "
                     "forbidden for production")
            continue
        by_role.setdefault(t.evidence_role, []).append((eid, a, sid))

    required = FEATURE_ROLE_REQUIREMENTS[role]
    used = []
    geom_asserts = []
    for req_role, allowed_types in required.items():
        cands = by_role.get(req_role, [])
        if not cands:
            v.append(f"{fid}: feature_role {role} requires {req_role} "
                     "evidence — none linked")
            continue
        ok_any = False
        for eid, a, sid in cands:
            atype = a["assertion_type"]
            if atype not in allowed_types:
                v.append(f"{fid}: {req_role} evidence {eid} has "
                         f"assertion_type {atype}; {role} requires one "
                         f"of {sorted(allowed_types)}")
                continue
            if req_role == "GEOMETRY_SHAPE":
                if not _truthy(a["geometry_authority"]):
                    v.append(f"{fid}: GEOMETRY_SHAPE evidence {eid} has "
                             "geometry_authority != YES")
                    continue
                geom_asserts.append((eid, a))
            else:
                if not _truthy(a["political_authority"]):
                    v.append(f"{fid}: {req_role} evidence {eid} has "
                             "political_authority != YES")
                    continue
                avf, avt = str(a["valid_from"]), str(a["valid_to"])
                if not (avf != "UNKNOWN" and avt != "UNKNOWN"
                        and avf <= snapshot_date <= avt):
                    v.append(f"{fid}: {req_role} evidence {eid} validity "
                             f"[{avf}..{avt}] does not explicitly cover "
                             f"{snapshot_date}")
                    continue
            ok_any = True
            used.append((eid, a, sid))
            info["roles"].add(req_role)
        if not ok_any:
            continue

    # Temporal continuity bridge for geometry evidence off the snapshot.
    for eid, a in geom_asserts:
        gvf, gvt = str(a["valid_from"]), str(a["valid_to"])
        if gvf != "UNKNOWN" and gvt != "UNKNOWN" \
                and gvf <= snapshot_date <= gvt:
            continue  # geometry itself represents the snapshot
        cont = by_role.get("TEMPORAL_CONTINUITY", [])
        good = []
        for ceid, ca, csid in cont:
            if ca["assertion_type"] != "TERRITORIAL_CONTINUITY":
                v.append(f"{fid}: TEMPORAL_CONTINUITY evidence {ceid} "
                         f"has assertion_type {ca['assertion_type']} "
                         "(TERRITORIAL_CONTINUITY required)")
                continue
            if not (_truthy(ca["political_authority"])
                    or _truthy(ca.get("continuity_authority", "NO"))):
                v.append(f"{fid}: continuity evidence {ceid} carries no "
                         "continuity/political authority")
                continue
            good.append((ceid, ca, csid))
        if not good:
            v.append(f"{fid}: geometry evidence {eid} represents "
                     f"[{gvf}..{gvt}], not {snapshot_date}, and no "
                     "TERRITORIAL_CONTINUITY bridge is linked "
                     "(interpolation is forbidden)")
            continue
        anchor = gvt if gvt != "UNKNOWN" and gvt < snapshot_date else gvf
        if not _bridge_covers([(str(ca["valid_from"]), str(ca["valid_to"]))
                               for _, ca, _ in good], anchor,
                              snapshot_date):
            v.append(f"{fid}: continuity bridge from {anchor} to "
                     f"{snapshot_date} has a gap — the geometry cannot "
                     "be carried to the snapshot")
            continue
        for ceid, ca, csid in good:
            used.append((ceid, ca, csid))
            info["roles"].add("TEMPORAL_CONTINUITY")

    info["evidence_ids"] = {e for e, _, _ in used}
    info["source_ids"] = {s for _, _, s in used}
    info["confidence"] = worst_confidence([a["confidence"]
                                           for _, a, _ in used])
    return v, info


AUTHORISED_SNAPSHOT_COLUMNS = [
    "boundary_feature_id", "historical_subject_id", "scenario_polity_id",
    "feature_role", "snapshot_date", "bundle_confidence",
    "bundle_evidence_ids", "bundle_source_ids", "bundle_evidence_roles",
    "valid_from", "valid_to", "positional_uncertainty_km",
    "geometry_status", "production_authorised", "geometry",
]
# Deprecated per-feature aliases: kept for provenance display only, they
# can never influence the compiled snapshot or anything downstream.
DEPRECATED_FEATURE_AUTHORITY_FIELDS = (
    "political_evidence_id", "political_evidence_source_id",
    "source_confidence")


def compile_authorised_snapshot_features(features: pd.DataFrame,
                                         links: pd.DataFrame,
                                         assertions: pd.DataFrame,
                                         registry: pd.DataFrame,
                                         subject_mapping: pd.DataFrame,
                                         snapshot_date: str):
    """THE only route from raw historical features to bindable data.

    Selects temporal candidates, validates each evidence bundle, rejects
    any feature with a single violation, resolves the scenario polity
    from an EXPLICIT mapping, and compiles bundle-derived confidence and
    provenance. Deprecated per-feature alias fields are never read.

    Returns (authorised, rejected).
    """
    import geopandas as gpd

    mapping = dict(zip(subject_mapping["historical_subject_id"],
                       subject_mapping["scenario_polity_id"])) \
        if len(subject_mapping) else {}
    empty = gpd.GeoDataFrame(
        {c: pd.Series(dtype="object")
         for c in AUTHORISED_SNAPSHOT_COLUMNS if c != "geometry"},
        geometry=pd.Series(dtype="object"))
    rej_cols = ["boundary_feature_id", "historical_subject_id",
                "feature_role", "rejection_reasons"]
    if not len(features):
        return empty, pd.DataFrame(columns=rej_cols)
    cands = select_features_for_snapshot(features, snapshot_date)
    rows, rejected = [], []
    skipped = features[~features["boundary_feature_id"].isin(
        cands["boundary_feature_id"])] if len(cands) else features
    for t in skipped.itertuples():
        rejected.append({
            "boundary_feature_id": t.boundary_feature_id,
            "historical_subject_id": t.historical_subject_id,
            "feature_role": t.feature_role,
            "rejection_reasons": "feature temporal validity does not "
                                 f"cover {snapshot_date}"})
    for t in cands.itertuples():
        row = {"boundary_feature_id": t.boundary_feature_id,
               "historical_subject_id": t.historical_subject_id,
               "feature_role": t.feature_role}
        v, info = evaluate_feature_bundle(row, links, assertions,
                                          registry, snapshot_date)
        loc = getattr(t, "source_locator", None)
        if not isinstance(loc, str) or not loc or loc == "UNKNOWN":
            v.append("exact feature source_locator required")
        g = getattr(t, "geometry", None)
        if g is None or shapely.is_empty(g):
            v.append("empty geometry")
        elif not shapely.is_valid(g):
            v.append("invalid geometry")
        unc = getattr(t, "positional_uncertainty_km", None)
        if unc is None or (isinstance(unc, float) and np.isnan(unc)) \
                or float(unc) <= 0:
            v.append("positional_uncertainty_km must be measured and "
                     "> 0 for a historical map feature")
        pid = mapping.get(t.historical_subject_id)
        if not pid:
            v.append("no explicit scenario polity mapping for "
                     f"{t.historical_subject_id} (name matching is "
                     "forbidden)")
        if v:
            rejected.append({**row, "rejection_reasons": "; ".join(v)})
            continue
        rows.append({
            **row, "scenario_polity_id": pid,
            "snapshot_date": snapshot_date,
            "bundle_confidence": info["confidence"],
            "bundle_evidence_ids": _joined(info["evidence_ids"]),
            "bundle_source_ids": _joined(info["source_ids"]),
            "bundle_evidence_roles": _joined(info["roles"]),
            "valid_from": t.valid_from, "valid_to": t.valid_to,
            "positional_uncertainty_km": float(unc),
            "geometry_status": getattr(t, "geometry_status",
                                       "GEOMETRY_PRESENT"),
            "production_authorised": True,
            "geometry": t.geometry,
        })
    out = gpd.GeoDataFrame(pd.DataFrame(
        rows, columns=AUTHORISED_SNAPSHOT_COLUMNS), geometry="geometry",
        crs=getattr(features, "crs", None)) if rows else empty
    return out, pd.DataFrame(rejected, columns=rej_cols)


def validate_production_features(features: pd.DataFrame,
                                 registry: pd.DataFrame,
                                 assertions: pd.DataFrame,
                                 links: pd.DataFrame,
                                 polity_mapping: pd.DataFrame,
                                 snapshot_date: str) -> list[str]:
    """Production gates for every boundary feature (returns violations).

    Authority chain: feature -> evidence BUNDLE (role-compatible,
    authority-checked, temporally bridged) -> registered assertions ->
    registered sources. Feature-side dates or a bare source id can never
    admit a feature.
    """
    v: list[str] = []
    mapped = set(polity_mapping["historical_subject_id"]) \
        if len(polity_mapping) else set()
    for t in features.itertuples():
        row = {"boundary_feature_id": t.boundary_feature_id,
               "historical_subject_id": t.historical_subject_id,
               "feature_role": t.feature_role}
        fid = t.boundary_feature_id
        bv, _ = evaluate_feature_bundle(row, links, assertions, registry,
                                        snapshot_date)
        v.extend(bv)
        gsid = getattr(t, "geometry_source_id", None)
        if not isinstance(gsid, str) or (len(registry) and gsid not in set(
                registry["global_source_id"])):
            v.append(f"{fid}: geometry_source_id missing/unregistered "
                     f"({gsid})")
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


def validate_assertion_table(assertions: pd.DataFrame,
                             registry: pd.DataFrame) -> list[str]:
    """Integrity of the assertion table itself (MAPGEN-011R2 §15)."""
    from .historical_geometry import (ASSERTION_TYPES,
                                      make_evidence_assertion_id)

    v = []
    if not len(assertions):
        return v
    if assertions["historical_evidence_id"].duplicated().any():
        v.append("duplicate historical_evidence_id")
    known_sources = set(registry["global_source_id"]) if len(registry) \
        else set()
    seen = set()
    for t in assertions.itertuples():
        eid = t.historical_evidence_id
        if t.assertion_type not in ASSERTION_TYPES:
            v.append(f"{eid}: unknown assertion_type {t.assertion_type}")
        for col in ("geometry_authority", "political_authority"):
            val = str(getattr(t, col)).upper()
            if val not in {"YES", "NO"}:
                v.append(f"{eid}: {col}={val} is not YES/NO")
        if str(t.confidence).upper() not in CONFIDENCE_ORDER:
            v.append(f"{eid}: confidence {t.confidence} outside the "
                     "ordinal enum")
        if str(t.valid_from) != "UNKNOWN" and str(t.valid_to) != "UNKNOWN" \
                and str(t.valid_from) > str(t.valid_to):
            v.append(f"{eid}: valid_from > valid_to")
        if not str(t.historical_subject_id).strip():
            v.append(f"{eid}: empty historical_subject_id")
        if known_sources and t.global_source_id not in known_sources:
            v.append(f"{eid}: source {t.global_source_id} unregistered")
        key = (t.global_source_id, t.historical_subject_id,
               t.assertion_type, str(t.valid_from), str(t.valid_to))
        if key in seen:
            v.append(f"{eid}: duplicate semantic assertion {key}")
        seen.add(key)
    return v


def validate_feature_evidence_links(links: pd.DataFrame,
                                    features: pd.DataFrame,
                                    assertions: pd.DataFrame) -> list[str]:
    v = []
    if not len(links):
        return v
    fids = set(features["boundary_feature_id"]) if len(features) else set()
    eids = set(assertions["historical_evidence_id"]) if len(assertions) \
        else set()
    for t in links.itertuples():
        if t.evidence_role not in EVIDENCE_ROLES:
            v.append(f"link {t.boundary_feature_id}/"
                     f"{t.historical_evidence_id}: unknown evidence_role "
                     f"{t.evidence_role}")
        if fids and t.boundary_feature_id not in fids:
            v.append(f"orphan link: feature {t.boundary_feature_id} "
                     "does not exist")
        if eids and t.historical_evidence_id not in eids:
            v.append(f"orphan link: evidence {t.historical_evidence_id} "
                     "does not exist")
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
# Exact-land hex binding
# --------------------------------------------------------------------------
def bind_snapshot_to_hexes(snapshot, hex_polys: np.ndarray,
                           hex_ids: list[str],
                           hex_land_geoms: np.ndarray,
                           hex_is_terrestrial: np.ndarray,
                           scenario_id: str, snapshot_date: str):
    """Bind snapshot control footprints to canonical hexes.

    hex_land_geoms[i] MUST be the exact canonical-land geometry of hex i
    (hex ∩ OSM coast-authority land) — the ONLY admissible land basis,
    shared with the audits. Returns (feature_membership,
    polity_membership). The winner per terrestrial hex is the polity with
    the largest UNIONED land intersection (no same-polity double
    counting); exact ties break by stable scenario_polity_id order.
    Raises ValueError if a land share exceeds 1 beyond tolerance.
    """
    if len(snapshot):
        missing = [c for c in ("production_authorised",
                               "bundle_confidence", "bundle_evidence_ids",
                               "bundle_source_ids", "scenario_polity_id")
                   if c not in snapshot.columns]
        if missing:
            raise ValueError(
                "bind_snapshot_to_hexes accepts ONLY authorised snapshot "
                f"features; missing columns {missing}. Raw features must "
                "go through compile_authorised_snapshot_features()")
        if not snapshot["production_authorised"].astype(bool).all():
            raise ValueError(
                "bind_snapshot_to_hexes: every row must have "
                "production_authorised=True")
    ctrl = snapshot[snapshot["feature_role"].isin(CONTROL_ROLES)]
    fcols = ["scenario_id", "snapshot_date", "hex_id",
             "scenario_polity_id", "historical_subject_id",
             "boundary_feature_id", "bundle_evidence_ids",
             "bundle_source_ids", "intersection_ground_km2",
             "binding_method"]
    pcols = ["scenario_id", "snapshot_date", "hex_id",
             "scenario_polity_id", "intersection_ground_km2",
             "share_of_terrestrial_hex_land", "is_dominant",
             "dominance_margin", "membership_count", "border_hex",
             "contributing_boundary_feature_ids",
             "contributing_historical_subject_ids",
             "bundle_evidence_ids", "bundle_source_ids",
             "source_confidence", "positional_uncertainty_km",
             "binding_method"]
    if not len(ctrl) or not len(hex_polys):
        return (pd.DataFrame(columns=fcols), pd.DataFrame(columns=pcols))
    tree = shapely.STRtree(np.asarray(hex_polys, dtype=object))
    feat_rows = []
    pol_rows = []
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
                "bundle_evidence_ids": t.bundle_evidence_ids,
                "bundle_source_ids": t.bundle_source_ids,
                "intersection_ground_km2": round(km2, 6),
                "binding_method": BINDING_METHOD,
            })
            hex_polities.setdefault(h, {}).setdefault(
                t.scenario_polity_id, []).append(t)
    for h, pol_feats in sorted(hex_polities.items()):
        land = hex_land_geoms[h]
        lkm2 = _g_km2(land)
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
                "intersection_ground_km2": round(km2, 6),
                "share_of_terrestrial_hex_land": round(min(share, 1.0), 6),
                "contributing_boundary_feature_ids": _joined(
                    f.boundary_feature_id for f in feats),
                "contributing_historical_subject_ids": _joined(
                    f.historical_subject_id for f in feats),
                "bundle_evidence_ids": _joined(
                    p for f in feats
                    for p in str(f.bundle_evidence_ids).split(
                        ID_SEPARATOR)),
                "bundle_source_ids": _joined(
                    p for f in feats
                    for p in str(f.bundle_source_ids).split(
                        ID_SEPARATOR)),
                # ORDINAL worst-of-bundle (never string min); the
                # COMPILED bundle confidence is the only authority.
                "source_confidence": worst_confidence(
                    f.bundle_confidence for f in feats),
                "positional_uncertainty_km": max(
                    float(getattr(f, "positional_uncertainty_km", 0.0)
                          or 0.0) for f in feats),
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
# Audits: conservation (bookkeeping) vs winner distortion (gameplay)
# --------------------------------------------------------------------------
def _polity_source_land(snapshot, land_union):
    """Per polity: unioned control geometry clipped to the land mask,
    its ground area, and the connected-component count OF THAT UNION
    (overlapping/adjacent features never inflate the count)."""
    out = {}
    ctrl = snapshot[snapshot["feature_role"].isin(CONTROL_ROLES)]
    for pid, grp in ctrl.groupby("scenario_polity_id"):
        union = shapely.union_all(list(grp["geometry"]))
        clipped = shapely.intersection(union, land_union) \
            if land_union is not None else union
        if clipped is None or shapely.is_empty(clipped):
            comp = 0
        else:
            parts = shapely.get_parts(clipped) \
                if clipped.geom_type.startswith("Multi") else [clipped]
            comp = sum(1 for p in parts if not shapely.is_empty(p)
                       and p.geom_type in ("Polygon", "MultiPolygon"))
        out[pid] = (clipped, _g_km2(clipped), comp,
                    _joined(grp["historical_subject_id"]))
    return out


def membership_conservation_audit(snapshot, polity_mem, hex_land_by_id,
                                  land_union=None) -> pd.DataFrame:
    """A: geometry bookkeeping — source control land area vs the sum of
    exact membership intersections."""
    land_union = land_union_from(hex_land_by_id, land_union)
    rows = []
    src = _polity_source_land(snapshot, land_union)
    for pid, (geom, km2, comp, subjects) in sorted(src.items()):
        mine = polity_mem[polity_mem["scenario_polity_id"] == pid] \
            if len(polity_mem) else polity_mem
        s = float(mine["intersection_ground_km2"].sum()) \
            if len(mine) else 0.0
        rows.append({
            "scenario_polity_id": pid,
            "contributing_historical_subject_ids": subjects,
            "source_land_ground_km2": round(km2, 4),
            "membership_intersection_ground_km2": round(s, 4),
            "conservation_error_km2": round(s - km2, 4),
            "conservation_error_fraction": round((s - km2) / km2, 6)
            if km2 > 0 else None,
        })
    return pd.DataFrame(rows)


def hexification_audit(snapshot, polity_mem, hex_land_by_id,
                       land_union=None) -> pd.DataFrame:
    """B: gameplay distortion — WINNER hex representation vs the source
    footprint, with omission/commission from the geometry symmetric
    difference."""
    land_union = land_union_from(hex_land_by_id, land_union)
    rows = []
    src = _polity_source_land(snapshot, land_union)
    for pid, (geom, src_km2, comp, subjects) in sorted(src.items()):
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
            "contributing_historical_subject_ids": subjects,
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
    """Zero-hex features are NEVER silently dropped — every candidate
    carries full provenance (raise otherwise)."""
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
        eid = f.get("bundle_evidence_ids")
        gsid = f.get("bundle_source_ids")
        if not isinstance(eid, str) or not isinstance(gsid, str) \
                or not eid or not gsid:
            raise ValueError(
                f"overlay candidate {t.scenario_polity_id}: provenance "
                "(political_evidence_id/global_source_id) is mandatory")
        rows.append({
            "candidate_id": f"hpo_{t.scenario_polity_id}",
            "scenario_polity_id": t.scenario_polity_id,
            "source_feature_id": f["boundary_feature_id"],
            "historical_subject_ids":
                t.contributing_historical_subject_ids,
            "bundle_evidence_ids": eid,
            "bundle_source_ids": gsid,
            "source_ground_area_km2": t.source_land_ground_km2,
            "reason": "feature survives in source geometry but wins "
                      "zero hexes under MAX_GROUND_LAND_SHARE",
            "recommended_representation": "SUBHEX_POLITICAL_OVERLAY",
            "status": "REVIEW_REQUIRED",
        })
    return pd.DataFrame(rows, columns=[
        "candidate_id", "scenario_polity_id", "source_feature_id",
        "historical_subject_ids", "bundle_evidence_ids",
        "bundle_source_ids", "source_ground_area_km2", "reason",
        "recommended_representation", "status"])


def compiled_provenance_id(source_ids, evidence_ids, feature_ids) -> str:
    """Deterministic compiled provenance record id.

    scenario territorial_control keeps a SINGULAR source_id column, so a
    multi-source control row references this compiled record instead of
    pretending to have one source. The full id sets stay in the additive
    columns."""
    key = "|".join([_joined(source_ids), _joined(evidence_ids),
                    _joined(feature_ids)])
    return f"prov_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}"


def controls_from_membership(polity_mem, scenario_id: str,
                             provenance_by_polity: dict | None = None
                             ) -> pd.DataFrame:
    """Control rows from dominant winners. Provenance comes from the
    membership itself (features/evidence/sources/subjects); claims are
    never derived from control."""
    cols = ["scenario_id", "territorial_target_type",
            "territorial_target_id", "controller_scenario_polity_id",
            "control_status", "source_confidence", "source_id",
            "source_ids", "political_evidence_ids", "boundary_feature_ids",
            "historical_subject_ids", "notes"]
    if not len(polity_mem):
        return pd.DataFrame(columns=cols)
    dom = polity_mem[polity_mem["is_dominant"]]
    rows = []
    for t in dom.itertuples():
        sids = str(getattr(t, "bundle_source_ids", "") or "")
        eids = str(getattr(t, "bundle_evidence_ids", "") or "")
        fids = str(getattr(t, "contributing_boundary_feature_ids", "")
                   or "")
        extra = (provenance_by_polity or {}).get(t.scenario_polity_id, {})
        if extra.get("source_id"):
            sids = _joined(set(sids.split(ID_SEPARATOR)) - {""}
                           | {extra["source_id"]})
        if not sids or not fids:
            raise ValueError(
                f"control for {t.scenario_polity_id} on {t.hex_id} "
                "without source/feature provenance — None-provenance "
                "production rows are forbidden")
        parts = [p for p in sids.split(ID_SEPARATOR) if p]
        rows.append({
            "scenario_id": scenario_id,
            "territorial_target_type": "TERRESTRIAL_HEX",
            "territorial_target_id": t.hex_id,
            "controller_scenario_polity_id": t.scenario_polity_id,
            "control_status": "CONTROLLED",
            "source_confidence": t.source_confidence,
            "source_id": parts[0] if len(parts) == 1
            else compiled_provenance_id(parts, [eids], [fids]),
            "source_ids": sids,
            "political_evidence_ids": eids,
            "boundary_feature_ids": fids,
            "historical_subject_ids": getattr(
                t, "contributing_historical_subject_ids", ""),
            "notes": f"historical hex binding {BINDING_METHOD}; "
                     f"membership_count={t.membership_count}",
        })
    return pd.DataFrame(rows, columns=cols)
