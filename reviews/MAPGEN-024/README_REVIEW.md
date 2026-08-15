# MAPGEN-024 Review — measuring a gap instead of filling it

**OUTCOME: FULL AUDIT, NO PRODUCTION.** Canonical control is unchanged at **50,565 rows** (49,496 CONTROLLED, 1,069 UNRESOLVED) — identical to MAPGEN-023 by gate. Validation **42/42**.

**Stage conclusion: C_ARCHITECTURAL_GAP. Recommended model: C_LAND_BEARING_HEX_NEW_TARGET_TYPE.**

## 1. The number

**3,014 hexes carry historically authorised land and cannot hold a control row**, between them **5,644.3 km²**.

| landmass | produced | withheld | km² withheld | share |
|---|---|---|---|---|
| Great Britain | 20,310 | 1,094 | 2,268.2 | 1.04% |
| Ireland | 7,520 | 558 | 1,216.3 | 1.46% |
| Sicily | 1,305 | 128 | 453.2 | 1.78% |
| Sardinia | 1,308 | 130 | 463.5 | 1.95% |
| Iceland | 18,341 | 1,089 | 1,187.0 | 1.16% |
| Malta | 12 | 9 | 36.4 | 14.77% |
| Gozo | 3 | 6 | 19.6 | 29.67% |

Four of these had never been measured. MAPGEN-021 and 022 filtered on `is_terrestrial_hex` *before* computing anything, so Great Britain, Ireland, Sicily and Sardinia never counted what they were dropping. Iceland reproduces MAPGEN-023's 1,089 exactly, and Malta and Gozo reproduce 9 + 6 = 15, which is the check that this independent measurement path agrees with the production one.

The share is the finding. One to two per cent on the five large landmasses, **14.8% on Malta and 29.7% on Gozo**. The error is not a constant — it scales with coastline over area, so it grows as the islands get smaller, and every future stage will meet smaller islands.

## 2. Where the gap lives

| land fraction | hexes | km² withheld |
|---|---|---|
| 0-5% | 674 | 109.0 |
| 5-10% | 349 | 230.1 |
| 10-20% | 583 | 785.3 |
| 20-30% | 492 | 1,155.2 |
| 30-40% | 453 | 1,447.3 |
| 40-50% | 463 | 1,917.3 |

Two populations. By **count** the biggest bucket is 0–5% — slivers a hex barely clips. By **area** the mass is at the other end: the 40–50% bucket alone holds more than the bottom four together. So this is not mostly rounding dust; it is mostly hexes that are nearly half land and miss the cut.

## 3. Is it a bug? No — and the evidence is written down

`src/mapgen/scenario.py` lines 23–26, since MAPGEN-006R:

> Territorial targets are TERRESTRIAL_HEX (hex_id) or ISLAND_COMPONENT (component_id) … and an OCEAN hex is never itself a land-control target.

`scenario_pipeline.py:934` enforces it. And `land.py:80–97` already names the discarded quantity `classification_error_area_m2` — explicitly including *the land part of a water hex*. The project knew the binary class throws land away and kept `land_fraction` beside it so the loss stays recoverable.

| layer | sites | political? |
|---|---|---|
| MOVEMENT | 1 | NO |
| PHYSICAL_CLASSIFICATION | 4 | NO |
| POLITICAL_TARGETING | 6 | YES |
| TERRAIN | 1 | NO |

One usage matters more than the rest: **movement reads neither flag.** `hex_edges.py` is purely geometric. There is no movement layer yet, so nothing downstream constrains the choice of model.

## 4. Why the existing escape hatch does not reach it

The project already solved *land on an ocean hex* once: a component that touches no terrestrial hex is flagged `is_subhex_lost` and becomes an `ISLAND_COMPONENT` target — Izu-Toshima is that row. But `islands_pipeline.py:1370–1377` checks `no_duplicate_overlay_for_large_islands`: a component already represented by a terrestrial hex must not also appear as an overlay. Great Britain **is** represented. Its coastal remainder is therefore too attached to be a lost component and too seaward to be a land hex.

| aspect | island component | coastal fragment | same? |
|---|---|---|---|
| what is being represented | a whole connected land component that is too small to win any hex | the seaward remainder of a component that already owns many hexes | NO |
| underlying hex physical class | OCEAN, and deliberately kept OCEAN | OCEAN, and must also stay OCEAN | YES |
| is the land visible to the political layer | yes - via an ISLAND_COMPONENT target | no - no target type can address it | NO |
| detection flag in the existing schema | is_subhex_lost = True | none: is_subhex_lost is False because the component IS represented som | NO |
| double-count protection | no_duplicate_overlay_for_large_islands forbids overlaying a component  | that same rule forbids reusing the mechanism here | NO |
| granularity of the political target | one target per component | would need per-hex granularity, since different coastal hexes of one l | NO |
| mixed controllers on one hex | possible in principle and already separated by component id | possible: one hex can hold land of two landmasses (456 such hexes meas | PARTIALLY |
| canonical precedent in this scenario | 1 row: Izu-Toshima, isl_c_1859af1e4767 | 0 rows | NO |

## 5. Models

| model | verdict |
|---|---|
| **A** — Status quo: only TERRESTRIAL_HEX is a political land target | Keep as the default only if the scale-dependence is accepted and documented in the scenario contract. |
| **B** — Any hex with land_area > 0 becomes a political land target; phys | Historically ideal, architecturally the most expensive. Not recommended without a deliberate revision of the target contract. |
| **C** — A new LAND_BEARING_HEX / COASTAL_LAND_FRAGMENT target type, dist | RECOMMENDED. It is the same architectural move the project already made once, it keeps every existing count intact, and it makes the fragment visible  |
| **D** — Reuse the existing ISLAND_COMPONENT / overlay target | REJECTED on the evidence of the project's own anti-double-count rule. |

Model C is recommended: additive, preserves the MAPGEN-006R invariant, leaves physical geography and every existing count untouched, and keys fragments by component so a hex holding two landmasses is explicit rather than a collision. Full reasoning in `representation_recommendation.md`.

**No threshold was tuned.** Lowering `land_threshold` from 0.5 would move terrain and water class to fix a political problem, and the distribution above has no natural break to justify a new cut.

## 6. The preview

`python -m mapgen scenario-preview --config config/kanto.yaml` regenerates everything below. It is QA only — the manifest declares `authoritative: false`, and canonical control is byte-identical after rendering.

- Europe overview at 4000 px wide, 49,494 CONTROLLED hexes drawn across 7 polities
- UNKNOWN (~812,233 terrestrial hexes nobody has researched), UNRESOLVED (1,068) and the coastal gap (3,014) are three different colours, because they are three different statements
- Colours are `sha1(polity_id)` hue — stable forever, and a shared monarch never merges two polities into one colour

| closeup | gap hexes in view |
|---|---|
| british_isles | 1,587 |
| iceland | 877 |
| mediterranean | 268 |
| malta_gozo | 15 |
| saxony_brandenburg | 0 |

The Malta and Gozo closeup is the one to look at: **15 hexes controlled by the Order, 15 more outlined in magenta.** Half the archipelago's hexes hold Maltese land that the model cannot own.

## 7. Blob size

Largest tracked file: **23.44 MB**. Over 50 MB: **0**. Over 25 MB: **0**, allowlisted with a reason.

The 56 MB blob in `c12ee10` is **not** rewritten. `main` is pushed, the review chain cites commit SHAs, and every base-commit audit in MAPGEN-019…023 would be invalidated by a rewrite. It is recorded as `LEGACY_HISTORY_DEBT` and the gate above stops a repeat.

## 8. Figures

- `coastal_gap_distribution.png` (aspect 1.995)
- `europe_political_progress.png` (aspect 1.461)
- `scenario_1756_political_map.png` (aspect 1.053)
- `scenario_1756_political_map_legend.png` (aspect 1.222)
- `british_isles_political_closeup.png` (aspect 1.032)
- `iceland_political_closeup.png` (aspect 1.313)
- `mediterranean_political_closeup.png` (aspect 1.208)
- `malta_gozo_political_closeup.png` (aspect 1.462)
- `saxony_brandenburg_political_closeup.png` (aspect 1.200)

Run `coastal_audit_1756_20260815`.
