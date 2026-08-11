# MAPGEN-010 Review — Europe Canonical Hex Coverage + Temporal Historical Political Geometry Foundation

**REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP.**
**SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY WITHIN ITS SCENARIO SNAPSHOT.**
**MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER NEUTRAL.**

Run `europe_foundation_20260811`. New namespace: historical_political_geometry 1.0.0/1.0.0. scenario schema 1.3.0 → **1.4.0** (additive political_coverage contract only).

## Europe coverage

- Extent lon -25.0..45.0 / lat 34.0..71.5 — chosen to cover every catalogue polity's European territory (incl. Iceland, Malta, North Cape, Moscow/Crimea); exclusions documented in config.
- 50 deterministic chunks on the EXISTING global 6 km grid: 1,885,422 hexes (862,795 terrestrial / 1,022,627 ocean, OSM coast authority).
- Coverage rows are GEOMETRY_COVERAGE_ONLY (water authority OSM_COAST_ONLY): terrain/lake/river layers are absent and explicitly marked — never faked as complete.
- Seam gates: duplicates=0, seam missing=0, monolithic sub-extent equality (ids/geometry/classification), and benelux/malta patch hexes identical to the existing grid.

## Historical political geometry (new namespace)

- Global source registry: 14 hsrc_ entries — the 10 existing scenario sources (src_ ids UNCHANGED, additive crosswalk) + 4 geometry-source candidates with UNEQUAL authority levels: Wikimedia 1748-1766 map = VISUAL_QA_ONLY; ETH HRE dataset = METHODOLOGY_REFERENCE (16th century — FORBIDDEN as 1756 authority); Historical Atlas of the Low Countries = BOUNDARY_AUTHORITY_CANDIDATE (cross-section dates must be verified first); Cassini = TOPOGRAPHIC_GEOREFERENCE_ONLY (no political authority).
- Boundary feature schema: temporal validity (valid_from/valid_to/precision, publication ≠ represented date), provenance, uncertainty, geometry_status. Production rows: **0** — the geometry catalogue tracks 3 planned items as SOURCE_GAP/GEOMETRY_PENDING.
- **Pilot: NOT performed (SOURCE_GAP).** The priority-1 Low Countries pilot stops formally because the candidate academic GIS is not acquired/date-verified; drawing polygons without it is forbidden. Corsica keeps its 009R contested contract WITHOUT fiat geometry expansion.
- Geometry is scenario-independent: one temporal feature serves every future scenario via snapshot-date selection (single-day sources use valid_from == valid_to); scenario_id is never part of geometry identity.

## Coverage contract

- 51 coverage units (50 Europe chunks UNASSESSED + the Kanto pilot TERRITORY_PARTIAL). COMPLETE count: 0 — COMPLETE requires the explicit conditions in run_manifest.
- `resolve_control_status`: a missing control row is authoritative ONLY under COMPLETE coverage (-> UNCONTROLLED); otherwise it is UNKNOWN and strict consumers raise IncompleteCoverageError. gameplay_authoritative=true means existing rows are authority, NOT that the world is complete (political_geography_complete stays false, data_status FOUNDATION_ONLY).

## Regression

- 009R2 polities/relationships byte-equal; territorial_control/claims byte-identical to MAPGEN-008; Tokugawa pilot + Toshima OCEAN unchanged; ACTIVE/SUPERSEDED audit intact; zero control from relationships/containers; no modern-admin leakage (AST).

## Images

- `europe_hex_coverage_overview.png` (aspect 0.993)
- `europe_chunk_seam_zoom.png` (aspect 0.956)
- `temporal_architecture_diagram.png` (aspect 1.31)
- `political_coverage_semantics.png` (aspect 1.566)

## Validation

- `validation.csv` lists every machine gate of this run; the pass count lives in `summary.csv`.

## Known limitations

- Europe rows carry no terrain/lake/river data yet (GEOMETRY_COVERAGE_ONLY); Ladoga-class lakes currently follow the OSM coast authority (land) until the hydro layer arrives.
- Pilot deferred at SOURCE_GAP; boundary production is MAPGEN-011 scope after source acquisition.
