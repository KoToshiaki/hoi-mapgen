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
| MAPGEN-019 | brandenburg_georef_rebuild_20260813/chatgpt_review | **latest completed stage** — Brandenburg georeference rebuilt from 33 observed feature points and validated | — | reviews/MAPGEN-019/ |

Run timestamps live inside each package's `run_manifest.json`; stage
directory names stay stable.
