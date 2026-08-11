# MAPGEN-009 Review — 1756 Europe Polity Catalogue + Constitutional Relationship Model

**REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP.**
**SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY WITHIN ITS SCENARIO SNAPSHOT.**

Run `scenario_catalogue_20260811` — scenario_schema_version 1.0.0 → **1.1.0** (additive: relationship + inclusion-audit tables, authority role / playability / Japanese display-name columns, evidence locator precision). scenario_algorithm_version 1.0.0 → **1.0.1** (one new rule: symmetric relationship ids sort their participants before hashing; nothing else changed). No existing column changed meaning; parent_scenario_polity_id is now a DEPRECATED convenience field — `scenario_polity_relationships` is the authority for all constitutional structure.

## What this stage is (and is not)

- This is the WHO and HOW-RELATED catalogue of 1756 Europe: polity existence, constitutional relationships, and 6 km representability audit.
- NO historical boundary geometry was created; NO territorial control/claim rows were added (byte-proof V25). WHERE comes in the next stage after review.
- The catalogue was built from the registered historical sources; Natural Earth is not an input (AST + data audit V16/V17). It is NOT a modern country list projected backwards.

## Catalogue

- 50 Europe scenario polities + the MAPGEN-008 Tokugawa pilot (untouched). Catalogue status: **PARTIAL** — reported separately from scenario data_status=FOUNDATION_ONLY (which stays FOUNDATION_ONLY until world political geography exists).
- Constitutional relationships: 35 rows ({"IMPERIAL_MEMBER_OF": 18, "COMPOSITE_MEMBER_OF": 7, "PERSONAL_UNION": 4, "TRIBUTARY_OF": 3, "DEPENDENCY_OF": 2, "SUBJECT_OF": 1}). Diplomatic relations (alliances, wars) are deliberately OUT of this table.
- Inclusion audit: 62 candidates ({"INCLUDED": 48, "AGGREGATION_CANDIDATE": 4, "SUBHEX_REQUIRED": 4, "UNRESOLVED": 3, "STRUCTURAL_ONLY": 2, "EXCLUDED_WITH_REASON": 1}) — 'not in the list' always means 'not yet evaluated', never silently dropped (policy: `inclusion_policy_v1.md`).
- 6 km representability risks: {"NONE": 29, "MULTIPART": 12, "ENCLAVE_COMPLEX": 8, "SUBHEX_REQUIRED": 7, "UNKNOWN": 3, "SUBHEX_LIKELY": 3}. SUBHEX_REQUIRED/UNKNOWN are audit findings, not failures; areas were never guessed.

## Modeling decisions on the known trap cases

- **Great Britain / Hanover**: two territorial polities joined only by symmetric PERSONAL_UNION (George II). Never merged.
- **Saxony / Poland-Lithuania**: PERSONAL_UNION (Augustus III); territories separate.
- **Holy Roman Empire**: registered STRUCTURAL_CONTAINER; owns zero territory; 18 IMPERIAL_MEMBER_OF rows carry the structure (V13/V15 machine-check that membership creates no control).
- **Habsburg Monarchy**: composite actor + 5 COMPOSITE_MEMBER_OF constituents (Bohemia, Hungary, Archduchy of Austria, Austrian Netherlands, Milan); Hungary deliberately has NO IMPERIAL_MEMBER_OF row (outside the Empire). Not a modern Austria polygon.
- **Prussia**: 'Prussian Monarchy (Hohenzollern lands)' as the acting composite (interpretation DERIVED, per Clark), with Brandenburg (in-Empire electorate) and the Kingdom of Prussia proper (outside the Empire) as COMPOSITE_MEMBER_OF constituents. Not generated from modern Germany.
- **Tuscany**: held by Emperor Francis Stephen; its tie to the Habsburg complex is deliberately UNEVALUATED (no forced relationship).
- **Ireland**: personal union with legislative subordination noted, not modeled as annexation.
- Playability is NOT decided: every polity has playability_status=UNDECIDED. Historical structure and gameplay playability are separate concepts.

## Provenance

- Sources: 8 registered works (NCMH VII 1957, NCMH Atlas 1970, Wilson 2016, Clark 2006, Ingrao 2000, Szabo 2008 + the two MAPGEN-008 Japan sources). Wikipedia-class material was not used as an authority.
- Evidence: 53 rows; every scenario polity has POLITY_EXISTENCE evidence, every relationship carries a source. source_locator is work-level UNKNOWN (with reason) at catalogue stage — page-level pinpoint locators arrive with boundary evidence; page numbers were NOT fabricated (interpretation_level DIRECT/DERIVED recorded per row).

## ID stability

- polity_id/scenario_id permanent; sp_/src_/ev_ ids as in MAPGEN-008; NEW rel_ id = sha1(scenario|type|from|to), with participants sorted for SYMMETRIC types (PERSONAL_UNION), so symmetric rows are order-invariant.

## Images

- `scenario_political_foundation_overview.png` (aspect 0.791)
- `reference_vs_scenario_semantics.png` (aspect 1.68)
- `island_component_control_target.png` (aspect 1.147)
- `europe_1756_polity_catalogue_overview.png` (aspect 2.889)
- `constitutional_relationship_diagram.png` (aspect 1.308)
- `six_km_representability_risk_summary.png` (aspect 2.207)
- `reference_vs_scenario_ontology.png` (aspect 1.685)

## Validation

- `scenario_validation.csv`: **33/33** gates (upstream immutability, pilot regression V22-V25, no-ownership-from-relationship gates V12-V15, no-modern-admin gates V16/V17, audit exhaustiveness V18-V20, provenance V07/V09/V21/V30, determinism V05/V11/V31).

## Known limitations

- Catalogue status PARTIAL: 3 UNRESOLVED candidates (Lucca, Schleswig-Holstein condominium, contested Corsica), class-level aggregation for minor imperial estates, Ottoman non-European lands out of scope, internal provincial structure (Dutch, PLC, Erblande) not subdivided.
- display_name_ja uses established Japanese renderings; any questionable ones are flagged REVIEW_REQUIRED rather than invented.
- Historical review welcome — every assertion is traceable to a registered source with recorded confidence.
