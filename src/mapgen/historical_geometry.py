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
# political_evidence_source_id are SEPARATE columns.
# 1.2.0 (MAPGEN-011R): additive — EVIDENCE ASSERTIONS become their own
# canonical entity (historical_evidence_assertions): a source is not an
# authority by itself; only a registered assertion (which locator, which
# subject, which dates, geometry vs political authority) can back a
# production feature via political_evidence_id. Closes the exploit where
# a cross-section source + hand-typed feature validity could smuggle a
# 1756 claim through.
# 1.3.0 (MAPGEN-011R2): additive — feature<->evidence links become their
# own many-to-many table (historical_boundary_feature_evidence) with an
# evidence_role: one feature carries a BUNDLE (geometry shape +
# political/claim status + temporal continuity). The single
# political_evidence_id / political_evidence_source_id columns remain as
# DEPRECATED aliases and are no longer production authority.
# 1.4.0 (MAPGEN-012): additive — AUTHORISED SNAPSHOT schema. The hex
# binder accepts only compiler output (production_authorised=True) whose
# confidence and provenance are BUNDLE-DERIVED; deprecated per-feature
# aliases can no longer influence anything downstream.
HPG_SCHEMA_VERSION = "1.4.0"
# 1.1.0 (MAPGEN-011R): binding semantics changed — land denominators and
# political intersections use the EXACT hex ∩ OSM-coast-authority land
# geometry (never land_fraction approximations, sea area never counts);
# same-polity multi-feature intersections are unioned before the winner
# decision (no double counting); hexification distortion is measured on
# the WINNER representation (omission/commission), separately from
# membership conservation.
# 1.2.0 (MAPGEN-011R2): production admission now evaluates the EVIDENCE
# BUNDLE against a role compatibility matrix (existence never authorises
# a boundary; de-facto needs control evidence; de-jure needs claim
# evidence; geometry evidence needs geometry_authority=YES and, when its
# represented date differs from the snapshot, an unbroken
# TERRITORIAL_CONTINUITY bridge). Confidence aggregates on an explicit
# ordinal (worst-of-bundle), component counts are measured on the
# unioned land geometry, and the land mask is a single source of truth
# shared by binding and audits.
# 1.3.0 (MAPGEN-012): the binder's ADMISSION CONTRACT changed — only
# authorised snapshot features may be bound, and membership/control
# confidence + provenance are bundle-derived. The binding METRICS
# (exact-land intersection, same-polity union, winner rule) are
# unchanged.
HPG_ALGORITHM_VERSION = "1.3.0"

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
    "political_evidence_id",
    "source_locator", "interpretation_level", "source_confidence",
    "positional_uncertainty_km", "digitisation_method", "geometry_status",
    "notes",
]

ASSERTION_TYPES = ["POLITICAL_CONTROL", "DE_JURE_CLAIM",
                   "BOUNDARY_POSITION", "TERRITORIAL_CONTINUITY",
                   "POLITY_EXISTENCE", "GEOMETRIC_SUBSTRATE_ONLY",
                   "TOPOGRAPHIC_GEOREFERENCE_ONLY"]
EVIDENCE_ASSERTION_COLUMNS = [
    "historical_evidence_id", "global_source_id",
    "historical_subject_id", "assertion_type", "valid_from", "valid_to",
    "temporal_precision", "exact_locator", "interpretation_level",
    "confidence", "geometry_authority", "political_authority", "notes",
]


# ---- MAPGEN-011R2: feature <-> evidence bundle model ---------------------
# A source is a work; an assertion is what one locator in that work
# proves; a boundary feature is drawn geometry. A feature is admitted to
# production only by a BUNDLE of assertions, each linked with the role it
# plays for that feature.
EVIDENCE_ROLES = ["GEOMETRY_SHAPE", "POLITICAL_STATUS",
                  "TEMPORAL_CONTINUITY", "CLAIM_STATUS",
                  "CONTESTED_STATUS", "SUPPORTING", "QA_ONLY"]
FEATURE_EVIDENCE_LINK_COLUMNS = [
    "boundary_feature_id", "historical_evidence_id", "evidence_role",
    "is_required", "notes",
]
# Roles that may never, on their own, admit anything to production.
NON_AUTHORISING_ROLES = {"SUPPORTING", "QA_ONLY"}

# Compatibility matrix: which evidence roles a feature_role requires,
# and which assertion_type each of those roles must carry.
# UNCERTAIN_BOUNDARY is deliberately absent: it is review/audit geometry
# and may never be converted into gameplay control.
FEATURE_ROLE_REQUIREMENTS = {
    "POLITY_EXTERNAL_BOUNDARY": {
        "GEOMETRY_SHAPE": {"BOUNDARY_POSITION", "GEOMETRIC_SUBSTRATE_ONLY"},
        "POLITICAL_STATUS": {"POLITICAL_CONTROL"},
    },
    "DE_FACTO_CONTROL_BOUNDARY": {
        "GEOMETRY_SHAPE": {"BOUNDARY_POSITION", "GEOMETRIC_SUBSTRATE_ONLY"},
        "POLITICAL_STATUS": {"POLITICAL_CONTROL"},
    },
    "DE_JURE_CLAIM_BOUNDARY": {
        "GEOMETRY_SHAPE": {"BOUNDARY_POSITION", "GEOMETRIC_SUBSTRATE_ONLY"},
        "CLAIM_STATUS": {"DE_JURE_CLAIM"},
    },
    "DISPUTED_BOUNDARY": {
        "GEOMETRY_SHAPE": {"BOUNDARY_POSITION", "GEOMETRIC_SUBSTRATE_ONLY"},
        "CONTESTED_STATUS": {"POLITICAL_CONTROL", "DE_JURE_CLAIM"},
    },
    "CONSTITUENT_INTERNAL_BOUNDARY": {
        "GEOMETRY_SHAPE": {"BOUNDARY_POSITION", "GEOMETRIC_SUBSTRATE_ONLY"},
        "POLITICAL_STATUS": {"POLITICAL_CONTROL", "DE_JURE_CLAIM"},
    },
}
GAMEPLAY_CONVERTIBLE_ROLES = set(FEATURE_ROLE_REQUIREMENTS)

# Confidence is an ORDERED enum — never compared as a string.
CONFIDENCE_ORDER = ["UNKNOWN", "LOW", "MEDIUM", "HIGH"]


def confidence_rank(value) -> int:
    v = str(value).upper() if value is not None else "UNKNOWN"
    return CONFIDENCE_ORDER.index(v) if v in CONFIDENCE_ORDER else 0


def worst_confidence(values) -> str:
    """Worst-of-bundle aggregation on the explicit ordinal.

    HIGH+MEDIUM=MEDIUM, HIGH+LOW=LOW, MEDIUM+UNKNOWN=UNKNOWN. An empty
    bundle is UNKNOWN (never optimistic)."""
    vals = list(values)
    if not vals:
        return "UNKNOWN"
    return CONFIDENCE_ORDER[min(confidence_rank(v) for v in vals)]


def make_evidence_assertion_id(citation_key_or_source: str,
                               subject: str, assertion_type: str,
                               valid_from: str, valid_to: str) -> str:
    key = (f"{citation_key_or_source}|{subject}|{assertion_type}|"
           f"{valid_from}|{valid_to}")
    return f"hev_{_h(key)}"


def load_evidence_assertions(data_dir: Path) -> pd.DataFrame:
    return pd.read_csv(Path(data_dir) / "historical"
                       / "historical_evidence_assertions.csv",
                       keep_default_na=False, na_values=[""])


def load_feature_evidence_links(data_dir: Path) -> pd.DataFrame:
    return pd.read_csv(Path(data_dir) / "historical"
                       / "historical_boundary_feature_evidence.csv",
                       keep_default_na=False, na_values=[""])


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
