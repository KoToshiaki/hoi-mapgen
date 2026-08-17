# MAPGEN-028 — Portugal measured again, on the 1751 Vaugondy sheets

run `vaugondy_portugal_1756_20260817` · outcome **FULL** · validation **49/49**

## The number that matters

| | MAPGEN-027 | MAPGEN-028 |
|---|---|---|
| positional uncertainty | 34.61 km | **12.33 km** |
| Portugal CONTROLLED | 124 | **2,727** |
| Spain CONTROLLED | 5,431 | 5,431 (frozen) |
| safe interior (km² EPSG:3857) | 5,480 | 76,604 |

MAPGEN-027 recovered Portugal from 26 hexes to 124 without a new measurement, and said so.
This stage makes the measurement. The uncertainty falls from 34.61 km to 12.33 km, and
because a safe interior is what survives erosion by that number, the interior grows
fourteenfold and the production twenty-twofold.

## The source, and whether it is one source or two

Gilles Robert de Vaugondy, *Partie Septentrionle du Royaume de Portugal* and *Partie
Meridionale*, 1751, two sheets of 47 × 51 cm at about 1:680 000, CC BY 4.0 from the
Universidade de Coimbra. The same library holds a 1749 pair with the same title and the same
sheet division, which had to be settled before either could be counted.

| axis | 1751 | 1749 | same plate? |
|---|---|---|---|
| PLATE_SIZE | face 3005 x 2801 px at 150 dpi = 50.9 x 47.4 cm | face 1123 x 912 px at 150 dpi = 19.0 x 15.4 cm | NO |
| CATALOGUED_SHEET_SIZE | 47 x 51 cm each sheet | 18 x 21 cm or smaller, 1 map on 2 sheets | NO |
| SCALE | ca. 1:680 000 | ca. 1:2 100 000 | NO |
| PLATE_NUMBERING | no atlas plate number recorded | numbered 132 and 32 at the upper right | NO |
| AUTHOR_AND_HOUSE | Gilles Robert de Vaugondy | Gilles Robert de Vaugondy | NOT_DECISIVE |
| SUBJECT_AND_SHEET_DIVISION | north and south halves of the kingdom | north and south halves of the kingdom | NOT_DECISIVE |

**DERIVED.** the printed image differs by a factor of about 2.7 in each direction; a plate cannot be rescaled. the same cartographer, the same sheet division and the same subject; a reduction by its own author is not an independent witness. Counts as 1 independent source.

## The anchor rule

Written down before the marks were read, and applied to every mark including the ones it
throws away.

| symbol | anchor point | eligible |
|---|---|---|
| PLAIN_CIRCLE | the centre of the circle | YES |
| CITY_SIGN_CIRCLE | the centre of the circle inside the block | YES |
| PICTORIAL_TOWN_VIGNETTE | none | NO |
| FORTIFICATION_PLAN | none | NO |
| LETTERING | none | NO |
| GRADUATION_STROKE | the stroke, in ONE coordinate only | AS_A_ONE_DIMENSIONAL_CONSTRAINT_ONLY |

That yields 42 true two-dimensional observations, 56 longitude-only graduation strokes and
48 latitude-only ones. The three are counted separately everywhere. No stroke is crossed
with another stroke to manufacture a pixel — that is what MAPGEN-018R disqualified.

## What the georeference costs

| sheet | set | n | rms km | p95 km | blind? | used |
|---|---|---|---|---|---|---|
| N | FIT_CONSTRAINT | 13 | 10.269 | 17.612 | NO | NO |
| N | MODEL_SELECTION_HOLDOUT | 4 | 6.066 | 7.567 | NO | NO |
| N | BLIND_VALIDATION | 5 | 7.385 | 9.679 | YES | NO |
| S | FIT_CONSTRAINT | 12 | 6.611 | 11.014 | NO | NO |
| S | MODEL_SELECTION_HOLDOUT | 4 | 9.598 | 11.659 | NO | NO |
| S | BLIND_VALIDATION | 4 | 7.959 | 13.133 | YES | NO |
| BOTH | ALL_NONFIT | 17 | 7.828 | 12.331 | NO | YES |

The two sheets are fitted separately and never to each other: sheet N selected AFFINE, sheet
S PROJECTIVE. 4 places are engraved on both, and carrying each through its own sheet's
transform they disagree by at most 8.14 km — inside the 12.33 km the georeference already
admits.

The plate prints no meridian statement. Solving for it as an extra unknown beside the
control points gives 17.6820° west over four estimators, against 17.6628° for Ferro at
twenty degrees west of Paris — 1.66 km at 39°N. Diagnostic only; the transform maps pixels
straight to Greenwich.

## The frontier, and where the plate fails

41 compartments were traced from the plate's own wash. 20 are claimed, each holding at least
one identified Portuguese place and no Spanish one.

**Sheet N, compartment 0, 41,921 km².** Holds Alcobaca|Leiria|Nisa|Pombal|Portalegre|Tomar
and Alburquerque|Valencia de Alcantara. the compartment spans the frontier, so the plate's
own wash cannot be closed along it on this sheet. It is not claimed for either crown and no
boundary is interpolated through it. Most of the ground under it is recovered from the other
sheet, which resolves the same country into separate compartments.

## The two plates disagree

| comparison | metric | value km² | of km² | verdict |
|---|---|---|---|---|
| v2 (Le Rouge 1756, eroded 34.61 km) inside the 1751 raw compartments | area of v2 outside the 1751 claim | 530.1 | 5479.5 | SOURCES_DISAGREE |
| v2 inside the 1751 safe interior v3 | area of v2 outside v3 | 1321.1 | 5479.5 | EXPECTED_v3_NEED_NOT_CONTAIN_v2 |
| v3 against Spain's MAPGEN-026 safe interior | overlap | 0.0 | 76604.3 | NO_OVERLAP |
| the 1751 claim against Spain's safe interior | overlap of the raw 1751 compartments with Spain | 0.0 | 114412.1 | CHECK_ONLY_RAW_IS_NOT_PRODUCED |

MAPGEN-027's feature is NOT withdrawn and NOT overwritten. 1,321 km² of it falls outside the
new one; both remain authorised, so a hex the older plate won cannot be lost because the
newer one draws the line a little differently.

## 1751 to 1756

| question | finding | action |
|---|---|---|
| does the peninsular frontier move between the plate's date and the snapshot? | NO | 1751 GEOMETRY APPLIED TO THE 1756 SNAPSHOT |
| Olivenza | PORTUGUESE_IN_1756 | WITHHELD_BY_NAME_FROM_THE_SAFE_INTERIOR |
| the Couto Misto | NEITHER_CROWN | WITHHELD_BY_NAME_FROM_THE_SAFE_INTERIOR |
| the Algarve | PART_OF_POL_PORTUGAL | CARRIED_FORWARD_UNCHANGED |
| the war of 1762 | AFTER_THE_SNAPSHOT | NOT_RELIED_ON |

## The review package

MAPGEN-021 to MAPGEN-027 each shipped a full copy of territorial_control.csv and its
provenance — 16 MB and 25 MB a time, 59 MB in MAPGEN-027 alone, for tables that live in the
repository and whose every row is reachable from the commit. Those packages are
LEGACY_HISTORY_DEBT and are left exactly as they are, because rewriting a reviewed artefact
is worse than carrying it. This one carries `canonical_snapshot_reference.json` — path,
sha256 and row count per table — and `territorial_control_delta.csv`, the 2,603 rows this
stage touched (883 inserted, 1,720 revised). Total 1.3 MB.

## Images

- `portugal_1751_measurement.png` (aspect 2.996)
- `portugal_027_vs_028.png` (aspect 2.793)
- `portugal_safe_interior_v3.png` (aspect 1.493)

## Gates

All 49 gates are in `validation.csv` with their evidence.
