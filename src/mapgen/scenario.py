"""MAPGEN-008 — Scenario Political Geography Foundation (data layer).

SEMANTICS CONTRACT
------------------
REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP.
SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY WITHIN ITS
SCENARIO SNAPSHOT.

This module is the ONLY loader for scenario political data. It is fully
decoupled from the contemporary reference layer by design: it never reads
Natural Earth data or any reference_admin table, so no code path can copy
a contemporary admin polygon into a scenario polity. (Machine-checked by
the V19 source-scan gate in the pipeline.)

Concepts (kept strictly separate):
- SCENARIO          : a start snapshot (scenario_id, snapshot_date).
- POLITY            : the timeless concept of a political entity.
- SCENARIO POLITY   : that polity's state at one scenario snapshot.
- TERRITORIAL CONTROL: who de-facto controls a territorial target
  (gameplay-authoritative, per scenario).
- TERRITORIAL CLAIM : who asserts rights over a target (many-to-many,
  ALWAYS a separate table from control).
- Territorial targets are TERRESTRIAL_HEX (hex_id) or ISLAND_COMPONENT
  (component_id). An overlay unit is NEVER a political unit
  (MAPGEN-006R: OVERLAY UNIT != GAMEPLAY LAND ENTITY), and an OCEAN hex
  is never itself a land-control target.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# 1.1.0 (MAPGEN-009): additive — scenario_polity_relationships +
# scenario_polity_inclusion_audit tables; territorial_authority_role /
# playability_status / display_name_ja columns on scenario_polities;
# source_locator / fact_summary / interpretation_level on evidence.
# 1.2.0 (MAPGEN-009R): additive — COMPOSITE_TERRITORIAL_ACTOR authority
# role (composite roots whose registered constituents carry territory);
# historical_title_at_snapshot column on scenario_polities;
# representability_basis column on the inclusion audit.
# 1.3.0 (MAPGEN-009R2): additive — audit_record_status (ACTIVE/
# SUPERSEDED) + superseded_by_candidate_ids on the inclusion audit:
# refined-away candidates keep their rows and ids forever but are
# excluded from ACTIVE counts and can never register polities or
# control.
# 1.4.0 (MAPGEN-010): additive — political_coverage table (per stable
# coverage unit): distinguishes "political data not built yet" from
# "verified no controller". A missing control row under incomplete
# coverage means UNKNOWN, NEVER unowned/neutral (enforced by
# resolve_control_status + tests). No existing semantics changed.
SCENARIO_SCHEMA_VERSION = "1.4.0"
# 1.0.1: symmetric relationship id canonicalisation.
# 1.0.2 (MAPGEN-009R): representability audit is now anchored to the
# machine-computed 6 km hex area (HEX_PLANE_AREA_KM2 + per-latitude
# ground factor) instead of political-size labels; id rules unchanged.
SCENARIO_ALGORITHM_VERSION = "1.0.2"
SCENARIO_SEMANTICS = "SCENARIO_SNAPSHOT_GAMEPLAY_AUTHORITATIVE"

# Completion states: existing in the registry NEVER implies finished.
COMPLETION_STATES = ["FOUNDATION_ONLY", "POLITIES_DEFINED",
                     "TERRITORY_PARTIAL", "TERRITORY_COMPLETE",
                     "VALIDATED", "PLAYABLE"]
CONTROL_STATUSES = ["CONTROLLED", "DISPUTED_CONTROL", "UNCONTROLLED",
                    "UNRESOLVED"]
TARGET_TYPES = ["TERRESTRIAL_HEX", "ISLAND_COMPONENT"]
SUBJECT_STATUSES = ["INDEPENDENT", "PERSONAL_UNION_MEMBER", "VASSAL",
                    "COLONIAL_DEPENDENCY", "COMPOSITE_MONARCHY_MEMBER",
                    "CONFEDERATION_MEMBER", "UNEVALUATED"]
SOURCE_TYPES = ["PRIMARY_MAP", "HISTORICAL_ATLAS", "ACADEMIC_REFERENCE",
                "OFFICIAL_ARCHIVE", "CURATED_DATASET",
                "SECONDARY_REFERENCE"]

# ---- MAPGEN-009 constitutional relationship model ------------------------
# Structural/constitutional relations only. Diplomatic relations
# (alliances, wars, guarantees) are OUT OF SCOPE for this table.
RELATIONSHIP_TYPES = ["PERSONAL_UNION", "IMPERIAL_MEMBER_OF",
                      "COMPOSITE_MEMBER_OF", "SUBJECT_OF",
                      "DEPENDENCY_OF", "PROTECTORATE_OF",
                      "CONFEDERATION_MEMBER_OF", "TRIBUTARY_OF",
                      "CHARTERED_BY"]
# Symmetric types have no from/to direction: participants are sorted
# before hashing so the id (and the row) is order-invariant.
SYMMETRIC_RELATIONSHIP_TYPES = {"PERSONAL_UNION"}
# A structural container existing is NOT the same as it owning member
# land: territorial control is NEVER derived from relationships.
# Territorial binding contract (MAPGEN-009R): control binds to the MOST
# SPECIFIC registered scenario polity with territorial identity;
# COMPOSITE_TERRITORIAL_ACTOR roots (e.g. composite monarchies whose
# constituents are registered) hold control only where no registered
# constituent covers the territory; STRUCTURAL_CONTAINER never holds
# control; root+member duplicate control on one target is forbidden.
TERRITORIAL_AUTHORITY_ROLES = ["DIRECT_TERRITORIAL_ACTOR",
                               "COMPOSITE_TERRITORIAL_ACTOR",
                               "STRUCTURAL_CONTAINER",
                               "DEPENDENT_TERRITORIAL_ACTOR",
                               "NON_TERRITORIAL_INSTITUTION",
                               "UNEVALUATED"]

# 6 km hex plane area, machine-computed from the grid definition —
# the OFFICIAL representability anchor (ground area at latitude phi is
# plane * cos^2(phi) under the EPSG:3857 grid contract). "Microstate"
# is a political label and NEVER a representability finding by itself.
HEX_FLAT_TO_FLAT_M = 6000.0
HEX_PLANE_AREA_KM2 = round(
    (3.0 ** 0.5) / 2.0 * HEX_FLAT_TO_FLAT_M ** 2 / 1e6, 6)


def hex_ground_area_km2_at_lat(lat_deg: float) -> float:
    """Approx. ground area of one 6 km grid hex at a given latitude."""
    import math

    return round(HEX_PLANE_AREA_KM2
                 * math.cos(math.radians(lat_deg)) ** 2, 6)
PLAYABILITY_STATUSES = ["UNDECIDED", "PLAYABLE", "NON_PLAYABLE",
                        "STRUCTURAL_ONLY"]
INCLUSION_STATUSES = ["INCLUDED", "STRUCTURAL_ONLY",
                      "AGGREGATION_CANDIDATE", "SUBHEX_REQUIRED",
                      "EXCLUDED_WITH_REASON", "UNRESOLVED"]
REPRESENTATION_RISKS = ["NONE", "MULTIPART", "ENCLAVE_COMPLEX",
                        "SUBHEX_LIKELY", "SUBHEX_REQUIRED", "UNKNOWN"]
INTERPRETATION_LEVELS = ["DIRECT", "DERIVED", "RECONSTRUCTED", "UNCERTAIN"]
# Audit rows are never deleted: a refined-away candidate becomes
# SUPERSEDED and points at its successors via superseded_by_candidate_ids
# (multiple ids joined with "|", a stable explicit format).
AUDIT_RECORD_STATUSES = ["ACTIVE", "SUPERSEDED"]
SUPERSEDED_BY_SEPARATOR = "|"

# ---- MAPGEN-010: scenario political coverage contract --------------------
# Progression of political data construction per stable coverage unit
# (e.g. a Europe chunk). Registry gameplay_authoritative=true means
# "existing scenario political rows are authority", NEVER "the world is
# complete" — completeness lives HERE, per unit.
COVERAGE_STATUSES = ["UNASSESSED", "SOURCE_IDENTIFIED",
                     "EVIDENCE_PARTIAL", "GEOMETRY_PARTIAL",
                     "TERRITORY_PARTIAL", "COMPLETE"]
COVERAGE_UNIT_TYPES = ["EUROPE_CHUNK", "REGION"]


class IncompleteCoverageError(RuntimeError):
    """Raised when a consumer asks for a definitive controller in a
    coverage unit that is not COMPLETE — missing rows there are UNKNOWN,
    never neutral."""


def resolve_control_status(control_rows: pd.DataFrame,
                           coverage_status: str,
                           target_type: str, target_id: str,
                           strict: bool = True):
    """THE missing != neutral rule.

    - If a control row exists for the target, it is authoritative.
    - If none exists and the unit's control coverage is COMPLETE, the
      target is genuinely UNCONTROLLED.
    - If none exists and coverage is NOT COMPLETE, the answer is
      UNKNOWN_COVERAGE_INCOMPLETE; strict consumers get an exception so
      gameplay code can never silently treat it as neutral territory.
    """
    m = control_rows[
        (control_rows["territorial_target_type"] == target_type)
        & (control_rows["territorial_target_id"] == target_id)]
    if len(m):
        return m.iloc[0]["control_status"]
    if coverage_status == "COMPLETE":
        return "UNCONTROLLED"
    if strict:
        raise IncompleteCoverageError(
            f"no control row for {target_type}:{target_id} and coverage "
            f"is {coverage_status} — this is UNKNOWN, not neutral")
    return "UNKNOWN_COVERAGE_INCOMPLETE"

# Per-scenario data files (canonical curated CSVs).
SCENARIO_FILES = {
    "scenario_polities": "scenario_polities.csv",
    "scenario_polity_relationships": "scenario_polity_relationships.csv",
    "scenario_polity_inclusion_audit":
        "scenario_polity_inclusion_audit.csv",
    "territorial_control": "territorial_control.csv",
    "territorial_claims": "territorial_claims.csv",
    "political_coverage": "political_coverage.csv",
    "sources": "sources.csv",
    "evidence": "evidence.csv",
}


class ScenarioNotFoundError(KeyError):
    """Unknown scenario_id. There is deliberately NO default-scenario
    fallback: political data must always be requested explicitly."""


# --------------------------------------------------------------------------
# Deterministic IDs (README: what is stable vs what versions)
# --------------------------------------------------------------------------
# - scenario_id: permanent handle, assigned once (never from display
#   names; display_name_* may change freely).
# - polity_id  : permanent curated slug assigned at first registration
#   (pol_...). Never regenerated from mutable display fields.
# - scenario_polity_id / source_id / evidence_id: deterministic SHA-1 of
#   the stable keys below — reproducible from content, stable across
#   reruns; they change only if their defining keys change (which IS a
#   data version change).
def _h(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def make_scenario_polity_id(scenario_id: str, polity_id: str) -> str:
    return f"sp_{_h(f'{scenario_id}|{polity_id}')}"


def make_source_id(scenario_id: str, citation_key: str) -> str:
    """citation_key = stable curated citation slug (NOT the title)."""
    return f"src_{_h(f'{scenario_id}|{citation_key}')}"


def make_evidence_id(scenario_id: str, source_id: str, evidence_type: str,
                     target_type: str, target_id: str) -> str:
    key = f"{scenario_id}|{source_id}|{evidence_type}|{target_type}|{target_id}"
    return f"ev_{_h(key)}"


def make_relationship_id(scenario_id: str, from_sp: str, to_sp: str,
                         relationship_type: str) -> str:
    """Deterministic relationship id. For SYMMETRIC types (e.g.
    PERSONAL_UNION) the participants are sorted first, so the id is
    identical regardless of argument order (algorithm 1.0.1 rule)."""
    a, b = ((min(from_sp, to_sp), max(from_sp, to_sp))
            if relationship_type in SYMMETRIC_RELATIONSHIP_TYPES
            else (from_sp, to_sp))
    return f"rel_{_h(f'{scenario_id}|{relationship_type}|{a}|{b}')}"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def scenarios_root(data_dir: Path) -> Path:
    return Path(data_dir) / "scenarios"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"scenario data file missing: {path}")
    # Empty cells are null; the literal strings 'None'/'NaN' etc. are
    # never silently converted (curated data must be explicit).
    return pd.read_csv(path, keep_default_na=False, na_values=[""])


def load_scenario_registry(data_dir: Path) -> pd.DataFrame:
    return _read_csv(scenarios_root(data_dir) / "scenario_registry.csv")


def load_polities(data_dir: Path) -> pd.DataFrame:
    return _read_csv(scenarios_root(data_dir) / "polities.csv")


@dataclass
class ScenarioSnapshot:
    scenario_id: str
    metadata: dict
    polities: pd.DataFrame
    scenario_polities: pd.DataFrame
    scenario_polity_relationships: pd.DataFrame
    scenario_polity_inclusion_audit: pd.DataFrame
    territorial_control: pd.DataFrame
    territorial_claims: pd.DataFrame
    political_coverage: pd.DataFrame
    sources: pd.DataFrame
    evidence: pd.DataFrame
    scenario_dir: Path = field(default=None)


def load_scenario(data_dir: Path, scenario_id: str) -> ScenarioSnapshot:
    """Load one scenario snapshot by explicit id.

    Raises ScenarioNotFoundError for unknown ids — never falls back."""
    registry = load_scenario_registry(data_dir)
    row = registry[registry["scenario_id"] == scenario_id]
    if not len(row):
        raise ScenarioNotFoundError(
            f"unknown scenario_id: {scenario_id!r} (registered: "
            f"{sorted(registry['scenario_id'])})")
    sdir = scenarios_root(data_dir) / scenario_id
    tables = {k: _read_csv(sdir / f) for k, f in SCENARIO_FILES.items()}
    return ScenarioSnapshot(
        scenario_id=scenario_id,
        metadata=row.iloc[0].to_dict(),
        polities=load_polities(data_dir),
        scenario_polities=tables["scenario_polities"],
        scenario_polity_relationships=tables[
            "scenario_polity_relationships"],
        scenario_polity_inclusion_audit=tables[
            "scenario_polity_inclusion_audit"],
        territorial_control=tables["territorial_control"],
        territorial_claims=tables["territorial_claims"],
        political_coverage=tables["political_coverage"],
        sources=tables["sources"],
        evidence=tables["evidence"],
        scenario_dir=sdir,
    )
