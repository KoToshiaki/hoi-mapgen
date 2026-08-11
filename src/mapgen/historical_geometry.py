"""MAPGEN-010 — Temporal historical political geometry (data layer).

NEW NAMESPACE, independent of any single scenario:

    historical sources  ->  temporal boundary features  -> (snapshot date)
        ->  scenario snapshot candidates  ->  gameplay control (LATER)

Contracts:
- Source-derived geometry and gameplay-authoritative scenario control are
  NEVER the same table.
- Geometry carries explicit temporal validity; a source's PUBLICATION
  date and the political state it REPRESENTS are separate fields.
- Historical boundaries are never generated from modern admin data
  (machine-gated by an AST scan of this module).
- One historical source / geometry serves MANY scenarios: scenario_id is
  never part of a geometry's primary identity. A single-day snapshot is
  expressed as valid_from == valid_to.
- Missing coverage means UNKNOWN, never neutral (see scenario coverage
  contract in scenario.py).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

# 1.1.0 (MAPGEN-011): additive — geometry_source_id (substrate) and
# political_evidence_source_id are SEPARATE columns: a cross-section
# geometry source alone can never carry a snapshot-date political
# assertion. No existing column changed meaning.
HPG_SCHEMA_VERSION = "1.1.0"
HPG_ALGORITHM_VERSION = "1.0.0"

# Authority levels — deliberately unequal; never flattened.
SOURCE_AUTHORITY_LEVELS = [
    "BOUNDARY_AUTHORITY_CANDIDATE",   # scholarly historical GIS/atlas
    "ACADEMIC_REFERENCE",             # scholarly text, non-geometric
    "TOPOGRAPHIC_GEOREFERENCE_ONLY",  # e.g. Cassini: places, not politics
    "METHODOLOGY_REFERENCE",          # e.g. wrong-period datasets
    "VISUAL_QA_ONLY",                 # informal reconstructions
]
GEOREFERENCE_STATUSES = ["GEOREFERENCED", "NOT_GEOREFERENCED", "UNKNOWN"]
TEMPORAL_PRECISIONS = ["DAY", "MONTH", "YEAR", "DECADE", "APPROXIMATE",
                       "UNKNOWN"]
FEATURE_ROLES = ["POLITY_EXTERNAL_BOUNDARY",
                 "CONSTITUENT_INTERNAL_BOUNDARY",
                 "DE_FACTO_CONTROL_BOUNDARY", "DE_JURE_CLAIM_BOUNDARY",
                 "DISPUTED_BOUNDARY", "UNCERTAIN_BOUNDARY"]
GEOMETRY_STATUSES = ["GEOMETRY_PRESENT", "GEOMETRY_PENDING", "SOURCE_GAP"]

BOUNDARY_FEATURE_COLUMNS = [
    "boundary_feature_id", "historical_subject_id", "feature_role",
    "valid_from", "valid_to", "temporal_precision", "global_source_id",
    "geometry_source_id", "political_evidence_source_id",
    "source_locator", "interpretation_level", "source_confidence",
    "positional_uncertainty_km", "digitisation_method", "geometry_status",
    "notes",
]


def _h(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def make_global_source_id(citation_key: str) -> str:
    """Global (scenario-independent) source id — reusable by every
    scenario. Existing per-scenario src_ ids are NEVER changed; scenario
    sources may reference an hsrc_ via a crosswalk column."""
    return f"hsrc_{_h(citation_key)}"


def make_boundary_feature_id(citation_key: str, subject_key: str,
                             feature_role: str, valid_from: str,
                             valid_to: str) -> str:
    key = f"{citation_key}|{subject_key}|{feature_role}|{valid_from}|{valid_to}"
    return f"hbf_{_h(key)}"


def load_global_sources(data_dir: Path) -> pd.DataFrame:
    return pd.read_csv(Path(data_dir) / "historical"
                       / "historical_source_registry.csv",
                       keep_default_na=False, na_values=[""])


def select_features_for_snapshot(features: pd.DataFrame,
                                 snapshot_date: str) -> pd.DataFrame:
    """Snapshot compiler CONTRACT (selection step only).

    Returns the features whose temporal validity covers snapshot_date.
    UNKNOWN validity NEVER silently matches: such features are excluded
    here and must be resolved explicitly by a human/scenario decision.
    Downstream conversion into scenario control is a SEPARATE, later,
    per-scenario interpretation step — never automatic.
    """
    if not len(features):
        return features
    ok_from = (features["valid_from"].notna()
               & (features["valid_from"] != "UNKNOWN")
               & (features["valid_from"] <= snapshot_date))
    ok_to = (features["valid_to"].notna()
             & (features["valid_to"] != "UNKNOWN")
             & (features["valid_to"] >= snapshot_date))
    return features[ok_from & ok_to]
