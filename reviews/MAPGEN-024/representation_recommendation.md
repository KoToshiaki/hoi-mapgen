# MAPGEN-024 - representation recommendation

**Stage conclusion: C. ARCHITECTURAL_GAP**

## What was measured

Across the seven landmasses produced so far, **3,014 hexes carry
historically authorised land and cannot hold a political control row**,
because the canonical `is_terrestrial_hex` flag is false for them. Between
them they hold **5,644.3 km2** of authorised land.

| landmass | produced | withheld | km2 withheld | share of authorised |
|---|---|---|---|---|
| Great Britain | 20,310 | 1,094 | 2,268.2 | 1.04% |
| Ireland | 7,520 | 558 | 1,216.3 | 1.46% |
| Sicily | 1,305 | 128 | 453.2 | 1.78% |
| Sardinia | 1,308 | 130 | 463.5 | 1.95% |
| Iceland | 18,341 | 1,089 | 1,187.0 | 1.16% |
| Malta | 12 | 9 | 36.4 | 14.77% |
| Gozo | 3 | 6 | 19.6 | 29.67% |

The share is roughly one to two per cent for the five large landmasses and
**14.8% for Malta and 29.7% for Gozo**. That is the
finding that matters. The error is not a constant; it scales with the ratio
of coastline to area, so it grows as the islands get smaller. A rule that
loses one per cent of Great Britain loses nearly a third of Gozo.

The land-fraction distribution shows the two populations that make it up:

| land fraction | hexes | km2 withheld |
|---|---|---|
| 0-5% | 674 | 109.0 |
| 5-10% | 349 | 230.1 |
| 10-20% | 583 | 785.3 |
| 20-30% | 492 | 1,155.2 |
| 30-40% | 453 | 1,447.3 |
| 40-50% | 463 | 1,917.3 |

By hex count the largest bucket is 0-5% - coastal slivers. By **area** the
mass sits at the top: the 40-50% bucket alone holds 1,917 km2, and
30-50% together hold 3,365 km2, 60% of everything
withheld. So the gap is not mostly slivers; it is mostly hexes that are
nearly half land and miss the threshold.

## Is it a bug?

No, and the evidence is explicit rather than inferred. `src/mapgen/scenario.py`
lines 23-26 state the rule in the module docstring:

> Territorial targets are TERRESTRIAL_HEX (hex_id) or ISLAND_COMPONENT
> (component_id). An overlay unit is NEVER a political unit
> (MAPGEN-006R: OVERLAY UNIT != GAMEPLAY LAND ENTITY), and an OCEAN hex is
> never itself a land-control target.

That predates every island stage. `scenario_pipeline.py:934` enforces it: a
`TERRESTRIAL_HEX` control row whose target is not in the terrestrial set
fails canonical validation. And `land.py:80-97` already names the discarded
quantity `classification_error_area_m2`, explicitly including *the land part
of a water hex*. The project knew the binary class throws land away and kept
the continuous `land_fraction` beside it precisely so the loss stays
recoverable.

So the behaviour is intentional **as a hex-targeting rule**. What is *not*
intentional is the consequence, because the escape hatch the project built
for exactly this problem cannot reach it.

## Why the existing escape hatch does not fit

`islands.py:174-189` flags a component as `is_subhex_lost` when it touches
no terrestrial hex, and such components become `ISLAND_COMPONENT` control
targets - the Izu-Toshima row in this scenario is one. That is the same
problem solved once already: land on an ocean hex, made politically visible
without touching the water class.

It cannot be reused here for one reason, and it is the project's own rule:
`islands_pipeline.py:1370-1377` checks `no_duplicate_overlay_for_large_islands`
- a component already represented by a terrestrial hex must not also appear
as an overlay. Great Britain is represented. Its coastal remainder therefore
falls between the two contracts: too attached to be a lost component, too
seaward to be a land hex.

That is an **architectural gap**, not a defect in either mechanism.

## Recommendation: Model C

Add a distinct political target type - `LAND_BEARING_HEX` or
`COASTAL_LAND_FRAGMENT` - keyed by (hex, landmass component).

- It preserves the MAPGEN-006R invariant. The ocean hex still is not a
  land-control target; a named fragment sitting on it is. This is the same
  move the project already made for sub-hex islands, so it needs no new
  philosophy.
- It is purely additive. Every existing `TERRESTRIAL_HEX` count survives
  untouched, which means every regression figure in MAPGEN-019 to 023 stays
  valid.
- It leaves physical geography alone. `water_type` does not move, so terrain
  faces do not move.
- Keying by component makes the 456 withheld hexes that also carry
  unaudited land explicit rather than a collision to be resolved.
- There is **no movement layer yet** (`hex_edges.py` is purely geometric and
  reads neither flag), so the future movement model is free to treat
  fragments differently from full land hexes rather than inheriting a
  decision made now.

Model B - making any hex with land a political target - recovers the same
area but breaks the documented invariant and would silently give a
99-per-cent-sea hex a land owner. Model D is rejected by the project's own
anti-double-count check. Model A remains defensible only if the
scale-dependence above is accepted and written into the scenario contract,
which it currently is not.

## What was deliberately NOT done

No threshold was tuned. Lowering `land_threshold` from 0.5 would change
physical geography - terrain, water class, the meaning of every existing hex
- in order to fix a political-representation problem. It would also still be
arbitrary: the distribution above has no natural break to justify a new cut.
Any future threshold change must be argued as a physical or gameplay model,
not as a way to reach a historical number.

No production changed. Canonical control rows, CONTROLLED and UNRESOLVED
counts are identical to MAPGEN-023.

## Correction carried by this stage

MAPGEN-023 reported 1,104 withheld hexes holding 1,427.7 km2. The count
reproduces exactly (1,104). The area does not: it was computed by summing
per-tile intersections, and the canonical land cache stores 3,480 tiles
twice, plus further tiles that overlap without being byte-identical. Summing
double-counts the shared ground. Measuring by unioning the pieces inside each
hex gives **1,243.0 km2** for the same three landmasses. Every
published landmass area is unaffected, because those were computed from
`union_all` of the tiles, which absorbs duplicates.
