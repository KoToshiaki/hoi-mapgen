"""MAPGEN-013 — canonical control promotion workflow.

Staged pilot control is not scenario authority. A candidate artifact
moves STAGED -> REVIEWED -> PROMOTED through this module, which:

- keys canonical control on (scenario_id, target_type, target_id) and
  refuses to create a second active row for one target,
- never silently overwrites: a replacement records the prior row, the
  reason and the evidence delta,
- keeps the canonical table lean by putting the full historical bundle
  (hsrc_/hev_/hbf_ ids) in a separate provenance table, while
  territorial_control.source_id stays in the SCENARIO source namespace
  (src_) so existing foreign-key semantics survive,
- is idempotent: promoting the same artifact twice changes nothing.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
from pathlib import Path

import pandas as pd

SCENARIO_CONTROL_PROMOTION_SCHEMA_VERSION = "1.0.0"
SCENARIO_CONTROL_PROMOTION_ALGORITHM_VERSION = "1.0.0"

REVIEW_STATUSES = ["STAGED", "REVIEWED", "PROMOTED", "SUPERSEDED",
                   "REJECTED"]
CONTROL_KEY = ["scenario_id", "territorial_target_type",
               "territorial_target_id"]
PROMOTION_LOG_COLUMNS = [
    "promotion_id", "scenario_id", "source_stage", "source_commit_sha",
    "candidate_artifact", "candidate_sha256", "review_status",
    "promotion_status", "promoted_utc", "promoted_row_count",
    "controlled_count", "unresolved_count", "supersedes_promotion_id",
    "notes",
]
PROVENANCE_COLUMNS = [
    "scenario_id", "territorial_target_type", "territorial_target_id",
    "scenario_source_id", "global_source_ids", "historical_evidence_ids",
    "boundary_feature_ids", "historical_subject_ids", "bundle_confidence",
    "promotion_id", "source_stage", "notes",
]


def make_promotion_id(scenario_id: str, stage: str,
                      candidate_sha256: str) -> str:
    """Deterministic: the same artifact from the same stage always maps
    to the same promotion id, which is what makes promotion idempotent."""
    key = f"{scenario_id}|{stage}|{candidate_sha256}"
    return f"promo_{hashlib.sha1(key.encode()).hexdigest()[:12]}"


def sha256_of_frame(df: pd.DataFrame) -> str:
    return hashlib.sha256(
        df.to_csv(index=False).encode("utf-8")).hexdigest()


def promote_control(canonical: pd.DataFrame,
                    provenance: pd.DataFrame,
                    log: pd.DataFrame,
                    candidate: pd.DataFrame,
                    scenario_id: str,
                    stage: str,
                    source_commit_sha: str,
                    candidate_artifact: str,
                    scenario_source_id: str,
                    review_status: str = "REVIEWED",
                    promoted_utc: str | None = None,
                    notes: str = ""):
    """Promote a reviewed candidate into canonical control.

    Returns (canonical, provenance, log, report). Idempotent: if this
    promotion id is already PROMOTED and its rows are present, nothing
    changes. Collisions with rows from a different promotion raise.
    """
    if review_status not in REVIEW_STATUSES:
        raise ValueError(f"unknown review_status {review_status}")
    if review_status not in ("REVIEWED", "PROMOTED"):
        raise ValueError("only REVIEWED candidates may be promoted; "
                         f"got {review_status}")
    cand_sha = sha256_of_frame(candidate)
    pid = make_promotion_id(scenario_id, stage, cand_sha)
    report = {"promotion_id": pid, "candidate_rows": len(candidate),
              "inserted": 0, "already_present": 0, "collisions": []}
    if len(candidate) and candidate.duplicated(
            subset=["territorial_target_type",
                    "territorial_target_id"]).any():
        raise ValueError("candidate contains duplicate target keys — a "
                         "target may hold only one control row")
    existing_keys = set(map(tuple, canonical[CONTROL_KEY].values)) \
        if len(canonical) else set()
    mine = set()
    if len(provenance):
        mine = set(map(tuple, provenance.loc[
            provenance["promotion_id"] == pid, CONTROL_KEY].values))
    new_rows, new_prov = [], []
    for t in candidate.itertuples():
        key = (scenario_id, t.territorial_target_type,
               t.territorial_target_id)
        if key in existing_keys:
            if key in mine:
                report["already_present"] += 1
            else:
                report["collisions"].append(t.territorial_target_id)
            continue
        row = {
            "scenario_id": scenario_id,
            "territorial_target_type": t.territorial_target_type,
            "territorial_target_id": t.territorial_target_id,
            "controller_scenario_polity_id":
                getattr(t, "controller_scenario_polity_id", None),
            "control_status": t.control_status,
            "source_confidence": t.source_confidence,
            "source_id": scenario_source_id,
            "notes": getattr(t, "notes", ""),
        }
        new_rows.append(row)
        new_prov.append({
            "scenario_id": scenario_id,
            "territorial_target_type": t.territorial_target_type,
            "territorial_target_id": t.territorial_target_id,
            "scenario_source_id": scenario_source_id,
            "global_source_ids": getattr(t, "source_ids", ""),
            "historical_evidence_ids":
                getattr(t, "political_evidence_ids", ""),
            "boundary_feature_ids":
                getattr(t, "boundary_feature_ids", ""),
            "historical_subject_ids":
                getattr(t, "historical_subject_ids", ""),
            "bundle_confidence": t.source_confidence,
            "promotion_id": pid, "source_stage": stage,
            "notes": "promoted from a reviewed staged candidate",
        })
    if report["collisions"]:
        raise ValueError(
            f"{len(report['collisions'])} target(s) already carry a "
            "control row from a different promotion; a replacement must "
            "record the prior row, the reason and the evidence delta "
            f"(first: {report['collisions'][0]})")
    if new_rows:
        canonical = pd.concat([canonical, pd.DataFrame(new_rows)],
                              ignore_index=True)
        provenance = pd.concat(
            [provenance, pd.DataFrame(new_prov, columns=PROVENANCE_COLUMNS)],
            ignore_index=True)
        report["inserted"] = len(new_rows)
    entry = {
        "promotion_id": pid, "scenario_id": scenario_id,
        "source_stage": stage, "source_commit_sha": source_commit_sha,
        "candidate_artifact": candidate_artifact,
        "candidate_sha256": cand_sha, "review_status": review_status,
        "promotion_status": "PROMOTED",
        "promoted_utc": promoted_utc or _dt.datetime.now(
            _dt.timezone.utc).strftime("%Y-%m-%d"),
        "promoted_row_count": len(candidate),
        "controlled_count": int(
            (candidate["control_status"] == "CONTROLLED").sum()),
        "unresolved_count": int(
            (candidate["control_status"] == "UNRESOLVED").sum()),
        "supersedes_promotion_id": None, "notes": notes,
    }
    if len(log) and (log["promotion_id"] == pid).any():
        log = log.copy()
        for k, v in entry.items():
            log.loc[log["promotion_id"] == pid, k] = v
    else:
        log = pd.concat([log, pd.DataFrame([entry],
                                           columns=PROMOTION_LOG_COLUMNS)],
                        ignore_index=True)
    return canonical, provenance, log, report


def validate_canonical_control(canonical: pd.DataFrame,
                               provenance: pd.DataFrame,
                               scenario_polities: pd.DataFrame,
                               scenario_sources: pd.DataFrame,
                               terrestrial_hexes: set,
                               island_components: set,
                               structural_polities: set) -> list[str]:
    """Integrity of the canonical table after promotion (spec 32)."""
    v = []
    if canonical.duplicated(subset=CONTROL_KEY).any():
        v.append("duplicate canonical target key")
    sp = set(scenario_polities["scenario_polity_id"])
    bad = canonical.loc[canonical["controller_scenario_polity_id"].notna()
                        & ~canonical["controller_scenario_polity_id"]
                        .isin(sp), "controller_scenario_polity_id"]
    if len(bad):
        v.append(f"orphan controller(s): {sorted(set(bad))[:3]}")
    src = set(scenario_sources["source_id"])
    bad_src = canonical.loc[canonical["source_id"].notna()
                            & ~canonical["source_id"].isin(src),
                            "source_id"]
    if len(bad_src):
        v.append(f"orphan scenario source(s): {sorted(set(bad_src))[:3]}")
    if canonical["controller_scenario_polity_id"].isin(
            structural_polities).any():
        v.append("a structural container / composite root holds control")
    for t in canonical.itertuples():
        if t.territorial_target_type == "TERRESTRIAL_HEX":
            if t.territorial_target_id not in terrestrial_hexes:
                v.append(f"non-terrestrial hex target "
                         f"{t.territorial_target_id}")
                break
        elif t.territorial_target_type == "ISLAND_COMPONENT":
            if t.territorial_target_id not in island_components:
                v.append(f"unknown island component "
                         f"{t.territorial_target_id}")
                break
        else:
            v.append(f"unknown target type {t.territorial_target_type}")
            break
    prov_keys = set(map(tuple, provenance[CONTROL_KEY].values)) \
        if len(provenance) else set()
    if len(prov_keys - set(map(tuple, canonical[CONTROL_KEY].values))):
        v.append("provenance rows without a canonical control row")
    return v
