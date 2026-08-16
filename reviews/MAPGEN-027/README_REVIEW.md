# MAPGEN-027 — Portugal mainland recovery, Iberian LAND_FRAGMENT completion, Algarve constitutional audit

run `portugal_recovery_1756_20260816` · outcome **ACCEPTABLE** · validation **46/46**

## MAPGEN-026, re-filed

MAPGEN-026 called itself FULL. Not one of its rows is withdrawn here, but its outcome is
re-filed as **ACCEPTABLE_PRODUCTION_WITH_FOLLOWUP_GAPS**: Iberian LAND_FRAGMENT production
was zero, the Algarve was withheld on the strength of a map title, and the individual
political evidence for both crowns was dated after the snapshot. Its own review files are
left untouched; this is the correction note.

## The number that matters

| | MAPGEN-026 | MAPGEN-027 |
|---|---|---|
| Spain CONTROLLED | 5,431 | 5,431 (frozen) |
| Portugal CONTROLLED | 26 | 124 |
| LAND_FRAGMENT rows | 3,014 | 3,359 |
| canonical rows | 75,629 | 76,576 |

Portugal went from 26 to 124 without a single new measurement. The uncertainty is unchanged
at 34.61 km. What changed was the evidence: the Algarve is Portuguese on institutional
grounds, and the unowned strips between Portugal's own traced cells are Portuguese where the
corridor between them contains no cell of another crown.

## The Algarve

A map title is not evidence about an actor, in either direction. Seven institutional axes
were examined against the crown's own printed legislation, the archival finding aid for the
Tavira corregedoria, and a University of Lisbon study.

| axis | verdict |
|---|---|
| ROYAL_TITULATURE | NOT_A_SEPARATE_ACTOR |
| CROWN_IDENTITY | NOT_A_SEPARATE_ACTOR |
| LEGISLATIVE_AUTHORITY | NOT_A_SEPARATE_ACTOR |
| ADMINISTRATION | NOT_A_SEPARATE_ACTOR |
| JUDICIAL_STRUCTURE | NOT_A_SEPARATE_ACTOR |
| TAXATION | NOT_A_SEPARATE_ACTOR |
| REPRESENTATION | NOT_A_SEPARATE_ACTOR |
| CARTOGRAPHIC_TITLE_ONLY | TITLE_IS_NOT_ACTOR_EVIDENCE |

**Decision: PART_OF_POL_PORTUGAL.** MAPGEN-009 kept Naples and Sicily apart because each had its own parliament, its own council and its own viceroy. The Algarve has none of the three, and its ground is run by corregedores of two ordinary comarcas under the same Ordenações as Beira or Alentejo.

## The coast

345 hexes carry Iberian mainland land but are not canonical terrestrial hexes. MAPGEN-026
gave them no row at all. They now carry that land as fragments: 9 CONTROLLED and 336
explicitly UNRESOLVED. The OCEAN parent hexes are still not owned.

139 of those hexes hold land of more than one physical component - one of them 103 - and in
the worst case the islet is four times larger than the mainland fragment. That is the first
real proof in this project that a whole-hex winner would have been wrong. The islets' 18.879
km2 is measured and left unowned.

## Corridors

| cells | gap km | decision |
|---|---|---|
| 13–14 | 42.2 | BRIDGED |
| 13–19 | 31.6 | BRIDGED |
| 13–23 | 42.4 | BRIDGED |
| 13–26 | 29.7 | BRIDGED |
| 14–18 | 41.8 | BRIDGED |
| 14–20 | 22.5 | BRIDGED |
| 19–23 | 19.2 | BRIDGED |
| 19–26 | 4.0 | BRIDGED |
| 23–26 | 21.0 | BRIDGED |

## Georeference wording, corrected

MAPGEN-026 quoted 'every point the fit never saw' next to a blind figure. The
model-selection holdout is NOT statistically blind: it chose POLYNOMIAL_2. The four sets are
now reported separately.

| set | n | rms km | p95 km | blind? | used for production |
|---|---|---|---|---|---|
| FIT | 21 | 16.71 | 26.91 | NO | NO |
| MODEL_SELECTION_HOLDOUT | 8 | 24.67 | 34.66 | NO | NO |
| BLIND_VALIDATION | 5 | 15.6 | 23.3 | YES | NO |
| ALL_NONFIT | 13 | 21.64 | 34.61 | PARTLY | YES |

## The larger-scale source, and why it is not used yet

Sanson/Vaugondy, *Carte du Royaume de Portugal*, Paris 1762, two sheets of 41 × 52 cm, CC BY
4.0 from the Universidade de Coimbra. Five times the scale of the Le Rouge plate, and its
cartouche claims it is 'corrigée et assujettie aux observations astronomiques'.

the plate draws every town of consequence as a pictorial vignette rather than a circle, and
a vignette has no defensible single point - the same reason MAPGEN-026 rejected Cuenca and
Cordoba. Producing 24 correspondences would have required inventing an anchor rule for
vignettes.

Its graduations are measured and recorded, and a three-point check puts the plate's meridian
within six hundredths of a degree and its latitudes within eight hundredths — promising, and
labelled PRELIMINARY_NOT_A_GEOREFERENCE, because three points identified by eye are not a
georeference. Handed to MAPGEN-028.

## Images

- `portugal_recovery_before_after.png` (aspect 3.263)
- `iberian_land_fragment_completion.png` (aspect 2.907)
- `iberian_political_closeup.png` (aspect 1.133)
- `scenario_1756_political_map.png` (aspect 1.053)
- `scenario_1756_political_map_legend.png` (aspect 1.222)

## Gates

All 46 gates are in `validation.csv` with their evidence. Gates M27-17 to M27-25 test the DEFERRAL discipline, not a georeference: they assert that no control point, no split, no frontier and no averaged boundary was manufactured from a source that has not been georeferenced.
