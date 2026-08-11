# MAPGEN-009R2 Review — Review Contract Consistency + Superseded Audit Semantics

**REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP.**
**SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY WITHIN ITS SCENARIO SNAPSHOT.**

Run `scenario_catalogue_009r2_20260811` (stage MAPGEN-009R2, family MAPGEN-009 rev R2) — scenario_schema_version 1.2.0 → **1.3.0** (additive only: audit_record_status ACTIVE/SUPERSEDED + superseded_by_candidate_ids on the inclusion audit; refined-away candidates keep their rows and ids forever but are excluded from ACTIVE counts and can never register polities or control). scenario_algorithm_version stays **1.0.2** — no political-judgment algorithm changed. The historical content of MAPGEN-009R (66 polities, 46 relationships, control/claims, contested contracts) is UNCHANGED and regression-gated (R2-12..14). parent_scenario_polity_id remains a DEPRECATED convenience field — `scenario_polity_relationships` is the authority.

## MAPGEN-009R2 review-contract fixes

- README facts are now generated from the canonical tables and machine-compared against them (R2-01..03); the stale MAPGEN-009 statements (the outdated imperial-member count and the outdated unresolved-candidate list) are gone.
- Superseded-audit semantics: 81 total audit rows = 80 ACTIVE + 1 SUPERSEDED. cand_schleswig_holstein_complex is SUPERSEDED history pointing at cand_schleswig_holstein_royal | cand_holstein_gottorp (both ACTIVE); rows are never deleted and SUPERSEDED rows never contribute to active counts, polity registration or control.
- Active inclusion policy: `inclusion_policy_v2.md`; v1 is kept as SUPERSEDED history (precedence recorded in run_manifest).
- run manifest stage identity fixed: stage=MAPGEN-009R2 (family MAPGEN-009, revision R2); run_id / stage / README title consistency is machine-gated (R2-11).

## MAPGEN-009R corrections

- **Old SUBHEX bug root cause**: the political label 'microstate' was treated as a geometry finding and the hex area was never machine-computed. Withdrawn everywhere.
- **Microstates re-audited individually** (Duursma 1996; modern areas as SANITY CHECKS ONLY, admissible where extent continuity is documented): San Marino (~61 km2, stable since the 15th c.) INCLUDED/NONE; Andorra (~468 km2, 1278 pareage) INCLUDED/NONE; Liechtenstein (~160 km2, 1719 union) INCLUDED/NONE; Monaco UNRESOLVED/UNKNOWN (1756 principality included Menton and Roquebrune — geometry review required, not guessed).
- **HRE granularity**: blanket class judgments withdrawn; 17 individual audits. Münster, Würzburg, Bamberg (with Carinthian exclaves), Salzburg, Hesse-Darmstadt, Mecklenburg-Strelitz, Baden-Durlach + Baden-Baden (separate until 1771), Hamburg and Nuremberg are now INCLUDED polities; Frankfurt/Augsburg/Bremen/Lübeck/Ulm and the Nassau/Anhalt families are individually tracked AGGREGATION candidates. Aggregation is a gameplay/view concern, never historical ownership authority.
- **Corsica resolved**: the Corsican Republic (Paoli, from 1755) is registered as a de-facto polity (Thrasher 1970); Genoa keeps the de-jure claim; the contested-control contract (separate claims vs control, citadels vs interior, no whole-island fiat) is in `contested_polity_audit.csv`. Lucca resolved INCLUDED via the registered atlas. Schleswig-Holstein stays UNRESOLVED, split into royal / Gottorp sub-candidates — never collapsed into one polity.
- **Prussia terminology hardened** (Clark 2006): 'Royal Prussia' = POLISH Prussia (Commonwealth territory until 1772) and is banned as a synonym for Hohenzollern East Prussia; 1756 style is 'King IN Prussia'; polity ids unchanged. See `prussia_terminology_audit.csv`.
- **Territorial binding contract** (before any boundary work): control binds to the most specific registered polity; composite roots (now COMPOSITE_TERRITORIAL_ACTOR: Habsburg, Prussian monarchies) hold control only where no constituent covers it; containers never control; root+member duplicate control forbidden; MAPGEN-008 Tokugawa rows untouched.

## What this stage is (and is not)

- This is the WHO and HOW-RELATED catalogue of 1756 Europe: polity existence, constitutional relationships, and 6 km representability audit.
- NO historical boundary geometry was created; NO territorial control/claim rows were added (byte-proof V25). WHERE comes in the next stage after review.
- The catalogue was built from the registered historical sources; Natural Earth is not an input (AST + data audit V16/V17). It is NOT a modern country list projected backwards.

## Catalogue

- 65 Europe scenario polities + the MAPGEN-008 Tokugawa pilot (untouched). Catalogue status: **PARTIAL** — reported separately from scenario data_status=FOUNDATION_ONLY (which stays FOUNDATION_ONLY until world political geography exists).
- Constitutional relationships: 46 rows ({"IMPERIAL_MEMBER_OF": 29, "COMPOSITE_MEMBER_OF": 7, "PERSONAL_UNION": 4, "TRIBUTARY_OF": 3, "DEPENDENCY_OF": 2, "SUBJECT_OF": 1}). Diplomatic relations (alliances, wars) are deliberately OUT of this table.
- Inclusion audit: 80 ACTIVE candidates of 81 total rows (1 SUPERSEDED history). ACTIVE inclusion_status counts: {"INCLUDED": 63, "AGGREGATION_CANDIDATE": 11, "UNRESOLVED": 3, "STRUCTURAL_ONLY": 2, "EXCLUDED_WITH_REASON": 1} — 'not in the list' always means 'not yet evaluated', never silently dropped (ACTIVE policy: `inclusion_policy_v2.md`).
- 6 km representability risks (ACTIVE rows): {"NONE": 38, "UNKNOWN": 17, "MULTIPART": 13, "ENCLAVE_COMPLEX": 11, "SUBHEX_REQUIRED": 1}. SUBHEX_REQUIRED/UNKNOWN are audit findings, not failures; areas were never guessed.
- Active UNRESOLVED candidates: Duchy of Holstein-Gottorp (ducal share; duke = the Russian heir Peter); Principality of Monaco; Schleswig and Holstein: royal shares (Danish crown).

## Modeling decisions on the known trap cases

- **Great Britain / Hanover**: two territorial polities joined only by symmetric PERSONAL_UNION (George II). Never merged.
- **Saxony / Poland-Lithuania**: PERSONAL_UNION (Augustus III); territories separate.
- **Holy Roman Empire**: registered STRUCTURAL_CONTAINER; owns zero territory; 29 IMPERIAL_MEMBER_OF rows carry the structure (V13/V15 machine-check that membership creates no control).
- **Habsburg Monarchy**: composite actor + 5 COMPOSITE_MEMBER_OF constituents (Bohemia, Hungary, Archduchy of Austria, Austrian Netherlands, Milan); Hungary deliberately has NO IMPERIAL_MEMBER_OF row (outside the Empire). Not a modern Austria polygon.
- **Prussia**: 'Prussian Monarchy (Hohenzollern lands)' as the acting composite (interpretation DERIVED, per Clark), with Brandenburg (in-Empire electorate) and the Kingdom of Prussia proper (outside the Empire) as COMPOSITE_MEMBER_OF constituents. Not generated from modern Germany.
- **Tuscany**: held by Emperor Francis Stephen; its tie to the Habsburg complex is deliberately UNEVALUATED (no forced relationship).
- **Ireland**: personal union with legislative subordination noted, not modeled as annexation.
- Playability is NOT decided: every polity has playability_status=UNDECIDED. Historical structure and gameplay playability are separate concepts.

## Provenance

- Sources: 10 registered works (NCMH VII 1957, NCMH Atlas 1970, Wilson 2016, Clark 2006, Ingrao 2000, Szabo 2008 + the two MAPGEN-008 Japan sources). Wikipedia-class material was not used as an authority.
- Evidence: 68 rows; every scenario polity has POLITY_EXISTENCE evidence, every relationship carries a source. source_locator is work-level UNKNOWN (with reason) at catalogue stage — page-level pinpoint locators arrive with boundary evidence; page numbers were NOT fabricated (interpretation_level DIRECT/DERIVED recorded per row).

## ID stability

- polity_id/scenario_id permanent; sp_/src_/ev_ ids as in MAPGEN-008; NEW rel_ id = sha1(scenario|type|from|to), with participants sorted for SYMMETRIC types (PERSONAL_UNION), so symmetric rows are order-invariant.

## Images

- `scenario_political_foundation_overview.png` (aspect 0.791)
- `reference_vs_scenario_semantics.png` (aspect 1.68)
- `island_component_control_target.png` (aspect 1.147)
- `europe_1756_polity_catalogue_overview.png` (aspect 2.889)
- `constitutional_relationship_diagram.png` (aspect 1.308)
- `six_km_representability_risk_summary.png` (aspect 2.298)
- `reference_vs_scenario_ontology.png` (aspect 1.685)
- `hre_catalogue_before_after.png` (aspect 2.304)
- `six_km_representability_sanity_panel.png` (aspect 1.504)
- `corsica_1756_modeling_diagram.png` (aspect 1.566)
- `audit_contract_before_after.png` (aspect 1.803)

## Validation

- `scenario_validation.csv` lists every machine-checked gate of this run (upstream immutability, pilot regression, no-ownership-from-relationship, no-modern-admin, audit exhaustiveness, provenance, superseded-audit R2 gates, README-fact synchronisation). Any FAIL is surfaced as a run warning; the pass count lives in `scenario_summary.csv`, not in hand-written README text.

## Known limitations

- Catalogue status PARTIAL: active UNRESOLVED candidates = Duchy of Holstein-Gottorp (ducal share; duke = the Russian heir Peter); Principality of Monaco; Schleswig and Holstein: royal shares (Danish crown) (Lucca and Corsica were RESOLVED in MAPGEN-009R); class-level aggregation for minor imperial estates; Ottoman non-European lands out of scope; internal provincial structure (Dutch, PLC, Erblande) not subdivided.
- display_name_ja uses established Japanese renderings; any questionable ones are flagged REVIEW_REQUIRED rather than invented.
- Historical review welcome — every assertion is traceable to a registered source with recorded confidence.
