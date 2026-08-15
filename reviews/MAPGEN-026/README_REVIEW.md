# MAPGEN-026 — Iberian mainland safe-interior production

run `iberian_mainland_1756_20260816` · outcome **FULL** · validation **44/44**

## What this stage claims, and what it refuses to

The specified source could not be acquired. Every published CNIG route to the 1755 Carte
d'Espagne answered 503, 403 or NoSuchKey, so that is recorded as an upstream failure and a
bounded search found a replacement with clean reuse terms: Le Rouge's Atlas nouveau
portatif, Paris 1756, digitised by Polona from the National Library in Warsaw and marked
Public Domain Mark 1.0 with no restrictions. Neither David Rumsey nor Gallica/BnF, both
excluded up front.

The plate does not draw one Spain and one Portugal. It washes a band around every PROVINCE,
and those bands close into a cell complex over the whole peninsula, so the international
frontier falls out as the set of cell edges whose two sides are held by different crowns. A
cell is owned only when the settlements engraved inside it all belong to one crown in the
documentary record; a cell holding settlements of two crowns is a proven leak in the trace
and is written down as one.

What the plate cannot do sets the shape of the result. 34 observed correspondences put its
p95 error at 34.6 km on points the fit never saw. So only SAFE INTERIORS are claimed: ground
that stays inside one crown's cells even if the entire trace slides by that distance in any
direction. Everything else carries an explicit UNRESOLVED row, because a missing row would
read as 'nobody looked'.

## The number that matters

| | Spain | Portugal |
|---|---|---|
| hexes CONTROLLED | 5,431 | 26 |

Portugal gets 26 hexes. That is the finding, not a failure: the country is about 150 km wide
and the measured error is 34.6 km, so almost all of it lies inside its own uncertainty band.
A pocket-atlas plate cannot place a narrow country's frontier at 6 km resolution. What a
later stage needs is a larger-scale Portuguese sheet, not a looser threshold on this one.

## Georeference

- 34 observed 2D correspondences (minimum 24, target 32); 18 candidates rejected with reasons
- frozen split 21 fit / 8 model selection / 5 blind, assigned before any model was fitted
- POLYNOMIAL_2 selected: simplest model inside 10 per cent of the best holdout rms (24.67 km)
- blind rms 15.6 km, blind p95 23.3 km on 5 points; the figure everything downstream is eroded by is the p95 over ALL 13 points the fit never saw, 34.61 km, because five points in two quadrants is too thin a sample to set a production threshold
- prime meridian EMPIRICAL_PLATE_OFFSET at -18.2633 deg, read off the plate's own graduations and used ONLY as an audit finding: border ticks are never 2D control points

## Withheld by name

- **GIBRALTAR** — ceded to Great Britain by article X of the Anglo-Spanish peace of Utrecht, 13 July 1713, and British at the snapshot; the Gaceta de Madrid of 3 August 1756 reports an English war fleet of sixteen or seventeen ships anchored in the bay on 24 June. It is not Spanish ground and must never be absorbed by a Spanish interior.
- **ANDORRA** — a co-principality under the Bishop of Urgell and the French crown, registered as pol_andorra. Neither Spain nor France may swallow it.
- **LLIVIA** — Spanish exclave inside French Cerdagne: the Treaty of the Pyrenees of 1659 ceded thirty-three VILLAGES of the Cerdagne and Llivia was a TOWN, so it stayed Spanish. Neither the French surroundings nor the Spanish interior may be extended over it without its own evidence.
- **OLIVENZA** — Portuguese in 1756; it passes to Spain only in 1801. Nothing here may back-date that.
- **COUTO_MISTO** — the Couto Misto, three villages that were neither Spanish nor Portuguese until 1864 and elected their own judge. A frontier condominium, not a side of the line.
- **CEUTA** — a Spanish presidio on the African shore, outside the Iberian mainland scope of this stage.
- **Algarve** — the plate styles it a kingdom in its own right, so it is not folded into Portugal without its own evidence, on the principle that kept Naples and Sicily apart in MAPGEN-009

## Province cells

| cell | outcome | crown | zone | why |
|---|---|---|---|---|
| 0 | UNRESOLVED | — | sea and the Balearics | NOT_MAINLAND_SCOPE |
| 5 | OWNED | FRANCE | Gascogne | ONE_CROWN_ONLY_IN_CELL |
| 6 | OWNED | SPAIN | Catalonia | ONE_CROWN_ONLY_IN_CELL |
| 7 | OWNED | FRANCE | Languedoc | ONE_CROWN_ONLY_IN_CELL |
| 10 | OWNED | FRANCE | Quercy and Rouergue | ONE_CROWN_ONLY_IN_CELL |
| 13 | OWNED | PORTUGAL | Beira | ONE_CROWN_ONLY_IN_CELL |
| 15 | OWNED | SPAIN | Valencia | ONE_CROWN_ONLY_IN_CELL |
| 17 | OWNED | SPAIN | Navarre | ONE_CROWN_ONLY_IN_CELL |
| 18 | UNRESOLVED | — | Algarve | SEPARATE_KINGDOM_TITLE_UNEVALUATED |
| 19 | OWNED | PORTUGAL | Tras-os-Montes on the Douro | ONE_CROWN_ONLY_IN_CELL |
| 20 | OWNED | PORTUGAL | Estremadura | ONE_CROWN_ONLY_IN_CELL |
| 21 | UNRESOLVED | — | Mallorca | NOT_MAINLAND_SCOPE |
| 22 | OWNED | FRANCE | Roussillon | ONE_CROWN_ONLY_IN_CELL |
| 23 | OWNED | PORTUGAL | Douro near Amarante | ONE_CROWN_ONLY_IN_CELL |
| 24 | UNRESOLVED | — | lower Minho | MIXED_CROWN_LEAK |
| 25 | UNRESOLVED | — | Sanabria and Tras-os-Montes | MIXED_CROWN_LEAK |
| 26 | OWNED | PORTUGAL | Beira Alta | ONE_CROWN_ONLY_IN_CELL |

## Images

- `iberian_georeference_uncertainty.png` (aspect 3.277)
- `iberian_production.png` (aspect 2.785)
- `iberian_political_closeup.png` (aspect 1.133)
- `scenario_1756_political_map.png` (aspect 1.053)
- `scenario_1756_political_map_legend.png` (aspect 1.222)

## Determinism

The whole chain - correspondences, georeference, safe interiors, hex binding, promotion -
was re-run end to end and produced byte-identical artifacts; the promotion reported 0
inserted and 22,050 already present. Hashes are in `iberia_determinism_check.csv`.

## Gates

All 44 gates are in `validation.csv` with their evidence.
