# MAPGEN-011 Review — Historical Boundary Source Acquisition + Low Countries Pilot (outcome: SOURCE_GAP)

**REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP.**
**SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY WITHIN ITS SCENARIO SNAPSHOT.**
**MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER NEUTRAL.**
**HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM MODERN ADMINISTRATION.**

## What actually happened

- The MAPGEN-010 SOURCE_GAP was re-investigated for real: the **Historical Atlas of the Low Countries** was located on the IISH Dataverse (hdl:10622/PGFYTM), and **version 15.0 (released 2026-01-01) was downloaded and verified** — 5 files, SHA-256 recorded, licence **CC BY-SA 4.0** confirmed via the Dataverse API, data paper DOI 10.1163/24523666-bja10033.
- Contents verified by inspection: layer `HALC 1500` with **14,863 locality polygons** (EPSG:4326) and an ADM0..ADM9 administrative hierarchy **for the year 1500**. The published dataset contains **only the 1500 cross-section**; 1350/1650/1800 are planned upstream but NOT yet released, and no 1756 sovereignty attributes exist.
- **1650/1800/1500 ≠ 1756 rule**: with no 1756-applicable geometry or per-subject political evidence, production 1756 features CANNOT be created without fabrication. Per spec §30 the pilot therefore stops formally at **SOURCE_GAP** with every candidate recorded in `historical_source_assessment.csv` (8 candidates, per-axis verdicts, none qualifying as 1756 boundary authority).
- Production rows: boundary features **0**, snapshot features **0**, hex membership **0**, new control rows **0**, overlay candidates **0**. `territorial_control/claims` are byte-identical to MAPGEN-008.

## What was built anyway (and proven by tests)

- hpg schema 1.0.0 → **1.1.0** (additive): `geometry_source_id` (substrate) and `political_evidence_source_id` are separate columns — a cross-section substrate alone can never carry a 1756 assertion (machine gate + dedicated tests).
- `historical_binding.py`: MAX_GROUND_LAND_SHARE hex binding (many-to-many preserved, ground-area winner, deterministic ties, border/dominance metrics), hexification distortion audit, zero-hex-loss → overlay candidates, control generation (claims NEVER derived from control), contested-overlap detection. All synthetic-tested; production-gated by the source-discipline validator.
- Coverage: `region_low_countries_1756_pilot` added (control/evidence = SOURCE_IDENTIFIED, other dimensions independent); 51 existing units untouched; COMPLETE = 0.

## Unblock paths for a real 1756 pilot (MAPGEN-012 candidate)

1. Upstream publishes the 1650/1800 HALC cross-sections → use as substrate + per-subject 1756 continuity evidence (priority-4 path of §5).
2. Build a locality-level 1756 sovereignty evidence table on the acquired 1500 substrate from scholarly territorial studies (large curation effort, locator-level citations).
3. Georeferenced near-contemporary maps (Ferraris 1771-78, Fricx 1704-12 — both registered) as georeference aids only.

## Images

- `low_countries_historical_sources.png` (aspect 1.588)
- `low_countries_source_gap_status.png` (aspect 1.685)
- `low_countries_coverage_status.png` (aspect 2.008)

- The spec's 1756 continuous-geometry / hex-control / hexification-error images are impossible without production geometry and were deliberately NOT faked.

## Validation

- `validation.csv` lists every gate (acquisition verification, assessment completeness, source discipline, zero-fabrication, coverage contract, 008/009R2/010 regressions, AST scans, upstream immutability). Pass count in `summary.csv`.
