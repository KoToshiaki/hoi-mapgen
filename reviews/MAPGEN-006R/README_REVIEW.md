# README_REVIEW — MAPGEN-006R Review Contract Hardening

Stage: MAPGEN-006R — Review Contract Hardening (on MAPGEN-006 geography)
Run ID: geography_v1_3_islands_006r_20260809
Date: 2026-08-09
geography_schema_version: 1.3.0 (previous: 1.2.0)
island_schema_version: 3.0.0
island_algorithm_version: 1.2.1 (1.2.0 dateline analysis
frame; 1.2.1 = public parameter rename only, behaviour identical)

THE FOUR-LAYER ISLAND MODEL (authoritative semantics):
1. COMPONENT — one physically contiguous OSM land polygon; individually
   addressable forever (own id, own component_primary_hex_id, own
   significance flag) — see island_components.csv.
2. GEOGRAPHIC GROUP — a ground-metric proximity cluster of lost components
   (distance <= 10 km ground, diameter cap
   20 km ground). Pure geometry.
3. OVERLAY UNIT — the aggregation that preserves and renders land which the
   6 km hex majority vote would erase. An overlay unit is NOT necessarily a
   gameplay island: multiple components inside one unit are never asserted to
   be a single political/military island.
4. GAMEPLAY LAND ENTITY — a FUTURE concept, to be decided from cities,
   ports, population, ownership and administration. NOT generated in
   MAPGEN-006/006R and never inferred from grouping or area.

overlay unit != gameplay land entity. Components can later be bound to
individual cities/ports/owners even when they share an overlay unit
(Litla Dimun / Faroe unit is the validated example: 7 components, one
overlay unit, every component individually addressable).
artificial_status = UNKNOWN means natural origin is NOT asserted (e.g.
Tokyo Bay reclaimed islands); tagged OSM data is a later stage.

Preservation semantics (unchanged from MAPGEN-006 — this run changes NO
geography): a hex keeps its water_type; lost components (no terrestrial hex,
not a clip fragment, fully hex-covered) cluster into groups; a group yields
one unit when its largest component is significant
(>= 0.05 km2 ground) AND holds
>= 20% of the group area; otherwise
coherent cores (>= 0.5 km2) become their
own units and the micro rest is dropped (AGGREGATED_MICRO_ISLETS — a real
positive case exists: Solund, 377 components / 2.60 km2 / max share 0.068).
preservation_reason values: SINGLE_COMPONENT_AREA /
MULTI_COMPONENT_ARCHIPELAGO / DISPERSED_MULTI_COMPONENT_GROUP (a
GEOMETRY-ONLY dispersion label controlled by
dispersed_group_max_land_hull_ratio = 0.45;
no atoll geomorphology is asserted anywhere) / FORCE_PRESERVE.
Thresholds were examined by the MAPGEN-006 world parameter sweep across 10
region types and RETAINED (the only variant changing catalogue accuracy —
minimum area 1.0 km2 — LOSES Buck Island); they remain provisional config.

All physical metrics are GROUND values (WGS84 geodesic); EPSG:3857 is grid
authority only; *_projected_* columns are audit-only
(latitude_invariance_validation.csv proves invariance at 0/35/60/75 deg).
Dateline: crossing regions use a shifted contiguous analysis frame for
clustering AND for rendering; stored geometry/ids stay in the original
frame (island_dateline_validation.csv: synthetic +-179.97 pairs and real
Fiji seam-split polygons).

Catalogue metrics (corrected in 006R):
- required_overlay recall = hits among places whose EXPECTED status is
  OVERLAY (mixed-expectation places are no longer in this denominator).
- exact catalogue accuracy = actual status equals expected status.
- false_overlay_count = places overlaid although their expected status is
  TERRESTRIAL_HEX or EXCLUDED_* (a guard against "preserve everything"
  scoring). See island_validation_catalogue.csv and the parameter sweep.

Area conservation (machine-checked): per region,
lost_ground = preserved_units_ground + excluded_ground exactly.
ID determinism: geometry-hash ids, identical within one OSM snapshot +
config; NOT guaranteed stable across OSM dataset updates.

Validation: 58/58 checks passed
(island_validation.csv).

Summary:
                              run_id          region  component_count  lost_component_count  lost_area_ground_km2  lost_area_projected_km2  group_count  single_component_groups  multi_component_groups  overlay_unit_count  groups_preserved  groups_split  groups_below_min_area  groups_micro_islet_excluded  preserved_area_ground_km2  preserved_area_projected_km2  excluded_area_ground_km2  area_conservation_ok  overlay_area_min_km2  overlay_area_median_km2  overlay_area_p90_km2  overlay_area_p95_km2  overlay_area_max_km2  covered_hexes_min  covered_hexes_max  hexes_with_multiple_overlays  overlays_on_non_ocean_hex  groups_over_diameter_flag  min_area_ground_km2_config
geography_v1_3_islands_006r_20260809           kanto             3768                  2464               15.5129                  23.2494           35                        1                      34                   6                 6             0                     29                            0                    13.3783                       20.0565                    2.1346                  True                0.5426                   1.0218                5.0487                5.2867                5.5247                  3                  6                             0                          0                          0                         0.5
geography_v1_3_islands_006r_20260809            wake                3                     3                7.2484                   8.1795            1                        0                       1                   1                 1             0                      0                            0                     7.2484                        8.1795                    0.0000                  True                7.2484                   7.2484                7.2484                7.2484                7.2484                  4                  4                             0                          0                          0                         0.5
geography_v1_3_islands_006r_20260809          midway                3                     3                5.9081                   7.6363            1                        0                       1                   1                 1             0                      0                            0                     5.9081                        7.6363                    0.0000                  True                5.9081                   5.9081                5.9081                5.9081                5.9081                  3                  3                             0                          0                          0                         0.5
geography_v1_3_islands_006r_20260809           malta               36                    26                3.0489                   4.6689            3                        0                       3                   1                 1             0                      2                            0                     3.0068                        4.6047                    0.0421                  True                3.0068                   3.0068                3.0068                3.0068                3.0068                  4                  4                             0                          0                          0                         0.5
geography_v1_3_islands_006r_20260809     litla_dimun               42                    18               13.7943                  61.3161            4                        1                       3                   1                 1             0                      3                            0                    13.6935                       60.8737                    0.1008                  True               13.6935                  13.6935               13.6935               13.6935               13.6935                 10                 10                             0                          0                          0                         0.5
geography_v1_3_islands_006r_20260809          bikini               24                    24                7.2478                   7.5992            4                        0                       4                   3                 3             0                      1                            0                     6.8277                        7.1588                    0.4201                  True                1.2347                   1.6837                3.4642                3.6867                3.9093                  2                  6                             0                          0                          0                         0.5
geography_v1_3_islands_006r_20260809          aegean              612                   310               20.1515                  31.9943            9                        1                       8                   3                 3             0                      6                            0                    20.0419                       31.8191                    0.1096                  True                0.6798                   1.4027               14.6481               16.3037               17.9594                  5                  8                             0                          0                          0                         0.5
geography_v1_3_islands_006r_20260809       caribbean              258                   228               60.8097                  67.9204           13                        2                      11                   9                 9             0                      4                            0                    60.3405                       67.3969                    0.4692                  True                0.7759                   3.5864               13.0895               18.3330               23.5765                  4                  8                             3                          0                          0                         0.5
geography_v1_3_islands_006r_20260809 norway_skerries             4042                  2800               63.7289                 272.6794           13                        0                      13                  18                 5             2                      4                            2                    49.7260                      213.2040                   14.0029                  True                0.5017                   1.0881                7.4903                9.0154               11.4886                  1                 18                             9                          0                          0                         0.5
geography_v1_3_islands_006r_20260809   fiji_dateline              124                    70               72.9390                  80.0261           14                        2                      12                   4                 4             0                     10                            0                    72.2038                       79.2201                    0.7352                  True                2.6768                  10.5438               37.1458               42.7926               48.4394                  5                  8                             0                          0                          0                         0.5

Warnings/errors:
- no MAPGEN-005 baseline islands run for before/after

Files in this package:
- README_REVIEW.md
- integrated_kanto_islands.png
- island_aegean.png
- island_bikini.png
- island_caribbean.png
- island_components.csv
- island_dateline_validation.csv
- island_false_merge_review.png
- island_fiji_dateline.png
- island_group_semantics_audit.csv
- island_hex_membership.csv
- island_kanto_overview.png
- island_litla_dimun.png
- island_malta.png
- island_metric_comparison.csv
- island_midway.png
- island_multicomponent_example.png
- island_norway_skerries.png
- island_overlays.csv
- island_parameter_comparison.png
- island_parameter_sweep.csv
- island_preservation_summary.csv
- island_toshima.png
- island_toshima_before_after.png
- island_validation.csv
- island_validation_catalogue.csv
- island_wake.png
- island_world_calibration_summary.csv
- latitude_invariance_validation.csv
- run_manifest.json
