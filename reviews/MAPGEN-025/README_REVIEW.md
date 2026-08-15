# MAPGEN-025 Review — owning the coast without owning the sea

**OUTCOME: FULL. Model C IMPLEMENTED.** **3,014 LAND_FRAGMENT** rows recover **5,644.3 km²** of historically authorised coastal land. `TERRESTRIAL_HEX` stays at **50,564** and `ISLAND_COMPONENT` at **1** — both gated. Validation **44/44**.

## 1. What a fragment is

Not a hex. A LAND_FRAGMENT is *the land inside a hex that belongs to one authorised land subject*. The MAPGEN-006R invariant is untouched: an OCEAN hex is still not a land-control target, and all 3,014 fragments sit on OCEAN parents. The sea in those hexes is owned by nobody, and so is any other component's land.

- physical grid changed: **NO**
- `water_type` changed: **NO**
- terrain changed: **NO**
- `land_threshold`: **0.5** — unchanged

The gap was closed by adding a target type, not by moving physical geography. Lowering the threshold would have changed terrain and water class for every hex in Europe to solve a political-representation problem.

## 2. Identity, and why it is not a polity

`land_fragment_id = sha1(hex_id | historical_subject_id)`, algorithm `v1_sha1_hexid_pipe_subjectid`.

| criterion | verdict |
|---|---|
| SCENARIO_INDEPENDENT | **PASS** |
| NOT_DERIVED_FROM_A_POLITY_ID | **PASS** |
| NOT_ONE_TO_ONE_WITH_POLITIES | **PASS** |
| GEOMETRICALLY_DISJOINT | **PASS** |
| ONE_SUBJECT_IS_ONE_CONNECTED_COMPONENT | **PASS** |
| EUROPE_WIDE_PHYSICAL_COMPONENT_REGISTRY_EXISTS | **ABSENT** |

The decisive one is `NOT_ONE_TO_ONE_WITH_POLITIES`: **Malta and Gozo are two subjects under one polity.** A polity-keyed scheme could not tell them apart, and the same Cornish headland has to be the same fragment in a 1789 scenario as in this one, whoever holds it.

The known limitation is recorded rather than hidden: there is no Europe-wide physical component registry (`island_components` covers ten sample regions, not Great Britain or Iceland), so the key is the historical land *subject*. That works because the seven subjects are geometrically disjoint single components — which is gated. If two subjects ever describe the same ground, that gate fails and the scheme must be revisited before more production.

## 3. The land cache is still not a partition

MAPGEN-024 found the cache stores 3,480 tiles twice. This stage found that deduplication alone would **not** have been enough:

| fixture | measured | passed |
|---|---|---|
| CACHE_HOLDS_BYTE_IDENTICAL_DUPLICATES | 3480.0 | True |
| SUM_OVER_DUPLICATE_TILES_DOUBLE_COUNTS | 2.0 | True |
| HELPER_MATCHES_UNION_ON_THE_SAME_HEX | 17.191302 | True |
| CACHE_HOLDS_NON_IDENTICAL_OVERLAPPING_TILES | 768.0 | True |
| NO_FRAGMENT_EXCEEDS_ITS_PARENT_HEX | 0.0 | True |

768 overlapping pairs among the first 60,000 *unique* tiles. So the fix is not deduplication, it is `land_in_hexes()` — collect the intersections, union them inside the hex, measure once. Exact whatever the tiling does, and now the single admissible path from cache tiles to a political area.

| classification | sites |
|---|---|
| SAFE_UNION | 4 |
| UNSAFE_SUM | 2 |
| SAFE_BY_SOURCE | 1 |
| NOT_APPLICABLE | 1 |

**0 of the unsafe sites affect a production decision.** The stage binders summed per-tile areas, but their decisions are ratios — the 2 per cent unaudited test, and which component has more land — and a common factor cancels in a ratio. Their reported km² columns were inflated; no membership decision was.

**The cache itself was not modified.** Overlapping tiles may be intended storage semantics, and a consumer that is correct under overlap is correct either way.

## 4. Recovery

| landmass | MAPGEN-024 gap | fragments | km² recovered | unrecovered |
|---|---|---|---|---|
| Great Britain | 1,094 | 1,094 | 2,268.2 | 0 |
| Ireland | 558 | 558 | 1,216.3 | 0 |
| Sicily | 128 | 128 | 453.2 | 0 |
| Sardinia | 130 | 130 | 463.5 | 0 |
| Iceland | 1,089 | 1,089 | 1,187.0 | 0 |
| Malta | 9 | 9 | 36.4 | 0 |
| Gozo | 6 | 6 | 19.6 | 0 |

5,644.3 km² against the 5,644.3 km² MAPGEN-024 measured independently — the same ground, measured twice by different code.

Of 3,015 candidates, 1 was dropped: a **0.086 m²** triangle of Iceland coast, four coordinates where a tile boundary clips a hex corner. It is in the candidates CSV with its reason, not deleted.

## 5. Mixed hexes — the test the whole design exists for

**456 fragments** share their hex with unaudited land of another component. Area is conserved on every one, and **no hex was painted whole**.

| parent hex | fragment km² | other land km² | owned share |
|---|---|---|---|
| h6000_q-000651_r+001267 | 0.000733 | 3.108 | 0.0002 |
| h6000_q-000866_r+001533 | 0.000497 | 0.805 | 0.0006 |
| h6000_q-000832_r+001452 | 0.002229 | 1.303 | 0.0017 |
| h6000_q-000664_r+001338 | 0.000303 | 0.036 | 0.0084 |
| h6000_q-000750_r+001382 | 0.017968 | 1.498 | 0.0119 |

On the worst of them Great Britain owns **two ten-thousandths** of the hex's land and the other 99.98 per cent stays unowned. Under the old model the only options were to paint the whole hex British or to lose the coast entirely.

## 6. Viewer

`python -m mapgen scenario-preview` draws 3,014 fragments as **their own land geometry**, never as the parent hex. Magenta now means *still unrecovered*, and there is **0** of it left.

`malta_gozo_fragment_before_after.png` is the picture to look at: 15 magenta hexes covering half the archipelago on the left, the actual coastline filled to the shore on the right — and **Comino still unpainted in both**, because the 1530 privilege does not name it.

## 7. Schema

| item | before | after | change |
|---|---|---|---|
| TARGET_TYPES | TERRESTRIAL_HEX, ISLAND_COMPONENT | TERRESTRIAL_HEX, ISLAND_COMPONENT, LAND_FRAGMENT | **ADDITIVE** |
| SCENARIO_SCHEMA_VERSION | 1.4.0 | 1.5.0 | **MINOR_BUMP** |
| HPG_SCHEMA_VERSION | 1.4.0 | 1.4.0 | **NONE** |
| territorial_control.csv columns | 8 columns | 8 columns | **NONE** |
| land_fragment_registry.parquet | absent | present | **NEW_ARTIFACT** |
| validate_canonical_control signature | 7 positional args | 7 positional args + optional land_fragments | **BACKWARD_COMPATIBLE** |
| old scenario rows | 50564 TERRESTRIAL_HEX + 1 ISLAND_COMPONENT | 50564 TERRESTRIAL_HEX + 1 ISLAND_COMPONENT | **NONE** |

`SCENARIO_SCHEMA_VERSION` 1.4.0 → **1.5.0** (additive vocabulary growth; 13 pipeline pins and 1 test pin advanced with it). `HPG_SCHEMA_VERSION` stays 1.4.0. A reader that ignores LAND_FRAGMENT sees exactly the MAPGEN-024 scenario.

`validate_canonical_control` takes the fragment set as an **optional** argument, so every existing caller still works — and a caller that omits it is *warned* about fragment rows rather than silently accepting them. That asymmetry is gated in M25-44.

## 8. Figures

- `land_fragment_recovery.png` (aspect 2.013)
- `europe_political_progress.png` (aspect 1.461)
- `scenario_1756_political_map_legend.png` (aspect 1.222)
- `scenario_1756_political_map.png` (aspect 1.053)
- `malta_gozo_fragment_before_after.png` (aspect 2.924)
- `british_isles_fragment_closeup.png` (aspect 1.032)
- `iceland_fragment_closeup.png` (aspect 1.313)
- `mediterranean_fragment_closeup.png` (aspect 1.208)
- `malta_gozo_fragment_closeup.png` (aspect 1.462)

Run `land_fragment_1756_20260815`.
