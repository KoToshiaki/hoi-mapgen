# MAPGEN-008 Review — Scenario Political Geography Foundation

**REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP.**
**SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY WITHIN ITS SCENARIO SNAPSHOT.**

Run `scenario_foundation_20260811` — scenario namespace schema 1.0.0 (scenario_schema_version=1.0.0 / scenario_algorithm_version=1.0.0), fully separate from geography 1.3.0 / island 3.0.0 / human_geography 1.1.0 (all unchanged).

## Concept separation

- SCENARIO (start snapshot) / POLITY (timeless concept) / SCENARIO POLITY (that polity's state at one snapshot) are three distinct tables — one polity can differ per scenario.
- TERRITORIAL CONTROL (de-facto, gameplay) and TERRITORIAL CLAIM (asserted rights, many-to-many) are separate tables, never one column.
- Territorial targets: TERRESTRIAL_HEX (hex_id) or ISLAND_COMPONENT (component_id). An OCEAN hex is never itself a land-control target; an overlay unit is never a political unit — components inside one overlay unit can have different controllers.
- REFERENCE MAPPING to MAPGEN-007R is QA/source-discovery only and is never territory authority. Natural Earth polygons are NEVER copied into scenario territory (machine-checked V19).

## Registered scenario

- `seven_years_war_1756_08_01` — snapshot 1756-08-01, 七年戦争前夜, historicity HISTORICAL, data_status **FOUNDATION_ONLY**, political_geography_complete=false.
- Registry presence does NOT mean completion; this scenario's historical political geography is deliberately NOT built yet. No second scenario exists (V23).

## Real-data pilot (schema/provenance proof, NOT completion)

- Polity: Tokugawa Shogunate (pol_tokugawa_shogunate), the de-facto government of Japan at the snapshot date (Horeki 6).
- CONTROLLED terrestrial hex: the Edo-castle hex h6000_q+002183_r+000819 (HIGH confidence, Cambridge History of Japan Vol.4).
- CONTROLLED island component: Izu-Toshima isl_c_1859af1e4767 on an OCEAN hex — the Izu Islands were shogunal direct territory (tenryo) under the Nirayama intendancy (MEDIUM confidence, Kokushi Daijiten). The hex stays OCEAN; only the component is the target.
- UNRESOLVED terrestrial hex: h6000_q+002184_r+000813 (Musashi, later Yokohama) — the 1756 domain patchwork is not yet researched; UNRESOLVED is the formal state, never filled from reference admin.
- Pilot region is Kanto because canonical hex geography covers Kanto only — a Prussia/France point cannot satisfy TERRESTRIAL_HEX referential integrity yet. Documented, not hidden.

## Provenance contract

- Every CONTROLLED row and every evidence row traces to a registered source (V21). Untraceable hand-drawn boundaries are forbidden; Wikipedia-class material may aid discovery but never serves as boundary authority.
- Interpretation steps (geocoding Edo castle to a hex; island statement -> component) are recorded in evidence interpretation_notes.

## ID stability (README contract)

- scenario_id / polity_id: permanent, assigned once, never derived from display names (display names may change freely).
- scenario_polity_id / source_id / evidence_id: deterministic SHA-1 of stable keys (rules in run_manifest.id_rules). Changing a defining key IS a data version change; editing notes/display fields is not.

## Images

- `scenario_political_foundation_overview.png` (aspect 0.791)
- `reference_vs_scenario_semantics.png` (aspect 1.68)
- `island_component_control_target.png` (aspect 1.147)

## Validation

- `scenario_validation.csv`: **27/27** gates, including upstream SHA immutability (006R+007R+scenario inputs), referential integrity, semantics separation, target-type positives {"TERRESTRIAL_HEX": 2, "ISLAND_COMPONENT": 1}, and 1 formal UNRESOLVED rows.

## Known limitations

- FOUNDATION_ONLY: no world political geography, no diplomacy/war/economy systems, no second scenario, no scenario UI.
- Historical review of the pilot rows (esp. component-level Izu administration) is welcome; confidence is recorded honestly (HIGH/MEDIUM/UNKNOWN).
