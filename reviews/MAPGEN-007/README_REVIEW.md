# MAPGEN-007 Review — REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP

Run: `human_geography_v1_20260809` — Reference Administrative & Settlement Geography Foundation.

## Semantics contract (read this first)

- Every table in this stage is `reference_semantics = CONTEMPORARY_DE_FACTO_REFERENCE` and `gameplay_authoritative = false`.
- Natural Earth admin boundaries are a contemporary de-facto snapshot — **not** historical borders, and never game ownership.
- Populations are `SOURCE_REFERENCE_ESTIMATE` (NE POP_MAX/POP_MIN) — not game populations. Capitals are reference capitals, not game capitals. Ports are reference commercial ports, not naval bases.
- Nothing was written into `geography_hexes` (SHA-proved immutable); all admin data lives in separate reference tables.
- Island OVERLAY UNITS are never admin units: admin binding is done per island COMPONENT (spec: 'overlay unitごとにcountryを1つというschemaは禁止').

## Canonical reference tables

- `reference_admin0.parquet` — 258 countries (id `adm0_<NE_ID>`; ISO codes cleaned, `-99` -> null, audited).
- `reference_admin0_hierarchy.parquet` — 298 map units with MAP_UNIT_OF_COUNTRY / MAP_UNIT_OF_DEPENDENT_TERRITORY relations as stated by the source.
- `reference_admin1.parquet` — 4596 states/provinces (id `adm1_<adm1_code>`).
- `reference_disputed_areas.parquet` — 99 disputed areas (kept verbatim as reference disputes).

## Hex x admin membership (many-to-many, ground metric)

- `reference_admin_hex_membership.parquet`: 7863 rows (3656 admin0, 4207 admin1) across regions ['border_benelux', 'fiji_dateline', 'kanto', 'malta'].
- Intersection areas are WGS84 geodesic ground km2; `share_of_hex_ground_area` and dominant flags are reference conveniences only.
- border_benelux many-to-many positive: 37 hexes carry >=2 admin0 memberships (see `human_geography_border_hex.png`).
- Coverage is AUDITED, never gated: 3377 terrestrial hexes in `admin_coverage_audit.csv`, quality={'FULL': 3337, 'PARTIAL': 40}.

## Island component -> reference admin

- `island_component_reference_admin.parquet`: all 8912 components bound; methods={'NEAREST_REFERENCE_POLYGON': 6002, 'GROUND_INTERSECTION': 2485, 'UNRESOLVED': 425}.
- Fallbacks always record ground distance (<=30 km); UNRESOLVED is a formal state, silent snapping is forbidden.

## Settlements and ports

- `reference_settlements.parquet`: 7342 settlements; admin0 binding methods={'POINT_IN_POLYGON': 7324, 'NEAREST_REFERENCE_POLYGON': 18}.
- Land bindings inside covered regions: {'TERRESTRIAL_HEX': 15}; outside coverage = OUT_OF_REGION_COVERAGE (formal, audited).
- Kanto candidate catalogue (source-checked, never assumed): 3/5 present (['Kawasaki', 'Tokyo', 'Yokohama']); absent: ['Chiba', 'Saitama'].
- `reference_ports.parquet`: 1081 ports; port_type/activity do NOT exist in NE ports 5.0.0 -> explicit nulls.
- Port land bindings in covered regions: {'TERRESTRIAL_HEX': 4, 'ISLAND_COMPONENT_OVERLAY': 2}; kanto dual land+water access positives: 5.

## Dateline

- fiji_dateline (min_lon > max_lon) is processed as two EPSG:3857 sub-boxes; bindings use ground distances with the +world-width shifted frame, so +-180 never looks like 40,000 km.
- The Fiji render uses the 006R wrap DISPLAY rule (storage stays in the original frame).

## Images

- `human_geography_kanto.png` (aspect 0.819)
- `human_geography_tokyo_bay.png` (aspect 0.981)
- `human_geography_border_hex.png` (aspect 0.946)
- `human_geography_malta.png` (aspect 1.009)
- `human_geography_fiji_dateline.png` (aspect 1.115)
- `human_geography_island_component_admin_binding.png` (aspect 0.892)

## Validation

- `human_geography_validation.csv`: **32/32** machine-checked gates (incl. 006R physical regression V01-V06 and upstream immutability V30).

## Determinism and ID scope

- Reference ids derive from NE stable ids (NE_ID / adm1_code): stable across runs for a fixed NE version; a NE version upgrade is a new reference snapshot.
- Run-level determinism is proved by a second run + normalized SHA-256 comparison (see completion report).
