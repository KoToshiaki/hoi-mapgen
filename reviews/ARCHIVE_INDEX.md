# Review archive index

`reviews/<STAGE_NAME>/` holds the review package of each stage that is
still part of the current formal contract chain. Earlier stages are fully
superseded by later hardening stages; their packages remain available in
the local run outputs listed below and are not duplicated on GitHub.

| Stage | Local historical path (output/) | Status | Superseded by | On GitHub |
|---|---|---|---|---|
| MAPGEN-001 | kanto_20260807/chatgpt_review | complete | MAPGEN-002+ (6 km fixed) | no (index only) |
| MAPGEN-002 | kanto_terrain_20260807/chatgpt_review | complete | MAPGEN-002A | no (index only) |
| MAPGEN-002A | kanto_terrain_v3_20260808/chatgpt_review | complete | MAPGEN-004 integration | no (index only) |
| MAPGEN-003 | kanto_hydro_20260808/chatgpt_review | complete | MAPGEN-003A | no (index only) |
| MAPGEN-003A | kanto_hydro_v2_20260808/chatgpt_review | complete | MAPGEN-004 integration | no (index only) |
| MAPGEN-004 | geography_v1_20260808/chatgpt_review | complete | MAPGEN-005/005A/006 | no (index only) |
| MAPGEN-005 | geography_v1_1_islands_20260809/chatgpt_review | complete | MAPGEN-005A | no (index only) |
| MAPGEN-005A | geography_v1_2_islands_20260809/chatgpt_review | complete | MAPGEN-006 | no (index only) |
| MAPGEN-006 | geography_v1_3_islands_20260809/chatgpt_review | complete | MAPGEN-006R | no (index only) |
| MAPGEN-006R | geography_v1_3_islands_006r_20260809/chatgpt_review | **canonical physical geography** | — | reviews/MAPGEN-006R/ |
| MAPGEN-007 | human_geography_v1_20260809/chatgpt_review | complete | MAPGEN-007R | reviews/MAPGEN-007/ |
| MAPGEN-007R | human_geography_v1_1_20260811/chatgpt_review | **canonical reference human geography** | — | reviews/MAPGEN-007R/ |
| MAPGEN-008 | scenario_foundation_20260811/chatgpt_review | complete | MAPGEN-009+ | reviews/MAPGEN-008/ |
| MAPGEN-009 | scenario_catalogue_20260811/chatgpt_review | complete | MAPGEN-009R | reviews/MAPGEN-009/ |
| MAPGEN-009R | scenario_catalogue_009r_20260811/chatgpt_review | complete | MAPGEN-009R2 | reviews/MAPGEN-009R/ |
| MAPGEN-009R2 | scenario_catalogue_009r2_20260811/chatgpt_review | **canonical scenario catalogue** | — | reviews/MAPGEN-009R2/ |
| MAPGEN-010 | europe_foundation_20260811/chatgpt_review | complete | MAPGEN-011+ | reviews/MAPGEN-010/ |
| MAPGEN-018R | brandenburg_georef_review_20260813/chatgpt_review | disqualified the MAPGEN-018 transform | MAPGEN-019 | reviews/MAPGEN-018R/ |
| MAPGEN-019 | brandenburg_georef_rebuild_20260813/chatgpt_review | Brandenburg georeference rebuilt from 33 observed feature points and validated | MAPGEN-020 | reviews/MAPGEN-019/ |
| MAPGEN-020 | brandenburg_dual_source_20260814/chatgpt_review | continuity split into political vs boundary-position, four archival cases, independent BLHA georeference; no geometry digitised | MAPGEN-021 | reviews/MAPGEN-020/ |
| MAPGEN-021 | british_isles_1756_20260815/chatgpt_review | first large territorial production: Great Britain 20,310 and Ireland 7,520 hexes, coast-bounded, canonical 1,614 → 29,578 | MAPGEN-022 | reviews/MAPGEN-021/ |
| MAPGEN-022 | mediterranean_1756_20260815/chatgpt_review | same coast-bounded method applied to the Mediterranean islands: Sicily 1,305 and Sardinia 1,308 hexes, canonical 29,578 → 32,193; area semantics measured rather than asserted. Its sovereignty sources were later hardened by MAPGEN-023 | MAPGEN-023 | reviews/MAPGEN-022/ |
| MAPGEN-023 | batch_islands_1756_20260815/chatgpt_review | batch production: Iceland 18,341, Malta 12 and Gozo 3 hexes, canonical 32,193 → 50,565; MAPGEN-022's sovereignty titles re-sourced to archival provenance with zero control rows changed; the cost of the canonical majority-land hex rule measured for the first time | MAPGEN-024 | reviews/MAPGEN-023/ |
| MAPGEN-024 | coastal_audit_1756_20260815/chatgpt_review | audit only, canonical unchanged at 50,565 rows: 3,014 hexes holding 5,644 km² of authorised land have no political target, retroactively measured for all seven landmasses (1–2% of the large islands but 14.8% of Malta and 29.7% of Gozo). Conclusion **C_ARCHITECTURAL_GAP**, recommended model C. Also the first scenario political map preview, `python -m mapgen scenario-preview` | MAPGEN-025 | reviews/MAPGEN-024/ |
| MAPGEN-025 | land_fragment_1756_20260815/chatgpt_review | **latest completed stage** — LAND_FRAGMENT target type added additively (scenario schema 1.4.0 → 1.5.0): 3,014 fragments recover 5,644 km² of coastal land, canonical 50,565 → 53,579 with TERRESTRIAL_HEX and ISLAND_COMPONENT gated unchanged. Physical geography untouched; `land_in_hexes()` becomes the only overlap-safe path from land tiles to a political area | — | reviews/MAPGEN-025/ |

Run timestamps live inside each package's `run_manifest.json`; stage
directory names stay stable.
