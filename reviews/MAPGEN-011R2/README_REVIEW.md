# MAPGEN-011R2 Review — Evidence Role Compatibility + Geometry Authority + Confidence Semantics Finalisation

**HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM MODERN ADMINISTRATION.**
**MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER NEUTRAL.**

Run `historical_pilot_r2_20260812`. MAPGEN-011 / 011R content is FROZEN (HALC v15.0 acquisition, 1500-only finding, SOURCE_GAP, 0 production rows, byte-identical control/claims, exact-land binding, same-polity union, conservation/winner audit split). This is the final MAPGEN-011 hardening stage.

## What was closed

- **assertion_type vs feature_role compatibility**: a feature is admitted only by an evidence BUNDLE that satisfies the matrix. POLITY_EXISTENCE can never authorise a boundary; DE_FACTO_CONTROL_BOUNDARY requires POLITICAL_CONTROL; DE_JURE_CLAIM_BOUNDARY requires DE_JURE_CLAIM; UNCERTAIN_BOUNDARY is never gameplay-convertible.
- **geometry_authority is now enforced**: GEOMETRY_SHAPE evidence must carry geometry_authority=YES.
- **temporal continuity bridge**: when the geometry evidence represents another date, an unbroken TERRITORIAL_CONTINUITY chain from that date to the snapshot is required; gaps are rejected, never interpolated (proved on the REAL HALC 1500 assertion).
- **confidence is ordinal** (UNKNOWN < LOW < MEDIUM < HIGH), aggregated worst-of-bundle; the old string `min()` returned HIGH for HIGH+MEDIUM.
- **component counts** are measured on the unioned land geometry (overlapping features no longer inflate ENCLAVE_AT_RISK).
- **multi-subject provenance**: membership, audits and control keep every contributing historical subject, evidence, source and feature id.
- **single land-mask authority**: audits derive the land union from the same per-hex mask the binding used; a divergent explicit union raises.
- **control provenance**: single-source rows keep the real source id; multi-source rows reference a deterministic compiled provenance record (`prov_<sha1>`) with the full id sets in additive columns (design recorded in run_manifest).

## Schema / algorithm

- hpg schema 1.2.0 -> **1.3.0** (additive `historical_boundary_feature_evidence` link table with `evidence_role`; the single `political_evidence_id` / `political_evidence_source_id` columns are DEPRECATED aliases and are no longer production authority).
- hpg algorithm 1.1.0 -> **1.2.0** (bundle compatibility, geometry authority, continuity bridge, ordinal confidence, union component counting, shared land mask).

## Production state (unchanged)

- boundary features 0 · feature-evidence links 0 · snapshot features 0 · membership 0 · new control 0. The 3 registered production assertions still authorise nothing (HALC = GEOMETRIC_SUBSTRATE_ONLY; the Corsica existence assertion has no pinpoint locator). Synthetic fixtures live only inside the run.

## Images

- `feature_evidence_bundle_contract.png` (aspect 1.592)
- `assertion_role_compatibility_matrix.png` (aspect 1.988)
- `temporal_continuity_bridge.png` (aspect 2.263)

- Synthetic panels are labelled: SYNTHETIC SEMANTICS TEST (never production data).

## Validation

- `validation.csv` covers R2-01..R2-29 (frozen 011/011R content, matrix, existence rejection, geometry authority, de-facto/de-jure cross-use, continuity required + gap rejected, valid bundles, ordinal confidence, union components, multi-subject provenance, land-mask authority, control provenance, claims, SOURCE_GAP, 008/009R2/010 regressions, AST scan, renders, upstream immutability). Pass count in `summary.csv`.
