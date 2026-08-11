# MAPGEN-012 Review — Authorised Snapshot Compiler + 1756 Central Europe Direct-Map Production Pilot

**HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM MODERN ADMINISTRATION.**
**SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY WITHIN ITS SCENARIO SNAPSHOT.**
**MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER NEUTRAL.**

Run `central_europe_1756_pilot_20260812` — the first REAL 1756 production geometry.

## Phase A — authorised snapshot compiler

- `compile_authorised_snapshot_features()` is now the ONLY route into the hex binder: it selects temporal candidates, validates each evidence bundle, rejects a feature on a single violation, resolves the scenario polity from an explicit reviewed mapping, and emits bundle-derived confidence and provenance with `production_authorised=True`.
- The binder raises if handed a raw feature (M12-02), and rewriting the deprecated `political_evidence_id` / `political_evidence_source_id` / `source_confidence` aliases leaves the compiled snapshot bit-identical (M12-04).
- hpg schema 1.3.0 → **1.4.0** (authorised snapshot schema), algorithm 1.2.0 → **1.3.0** (admission contract; the binding metrics are unchanged). New namespace: `historical_map_georeference` **1.0.0/1.0.0**.

## The source

- **Robert de Vaugondy, 'Partie meridionale du cercle de Haute Saxe ou sont le duche de Saxe, le marquisat de Misnie, le landgraviat de Thuringe...', 1756** — Bibliotheque nationale de France, ark `btv1b530412497`, public domain, 7865x6017, SHA-256 recorded. The privilege line dates the plate to 1756, so it represents the 1756 state directly and needs no continuity bridge.
- The spec's suggested Commons file for the general HRE sheet does not exist under that name (the URL 404s); this sheet is the same cartographer, the same year, a national-library holding, and covers the pilot theatre at far larger scale.
- The Utrecht UB 1756 'seat of war' map was verified to exist but its repository rights field is unusable, so it is recorded **LICENCE_BLOCKED** and was not downloaded. Independent corroboration of these boundaries is therefore OUTSTANDING.

## Georeference

- Prime meridian is **not** Greenwich: the sheet uses **FERRO_20W_OF_PARIS** (Ferro, 20 deg west of Paris), confirmed empirically — the Ferro hypothesis predicted Dresden's position to ~2 km.
- 11 GCPs in `historical_map_gcps.csv` (7 fit / 4 holdout), taken from the sheet's own neat-line degree ticks (meridian x parallel intersections) plus one independent settlement check. No modern administrative geometry was used.
- Transform comparison: **PROJECTIVE** selected. Fit RMS 50.2 m / p95 72.6 m; holdout RMS 1453.2 m (graticule-only 87.9 m, settlement check 2902.5 m), max 2902.5 m. POLYNOMIAL_2 had the best fit residual and a six-figure holdout residual — classic overfitting, rejected by the holdout rule.
- Positional uncertainty **2.975 km** per the documented rule (worse of graticule/settlement residual, plus line width and simplification). Never 0.

## Digitisation and the pilot territory

- Semi-automatic colour-wash segmentation: the sheet's hand-coloured outlines are barriers, a seed inside the bloc grows the region, and every parameter (frame, seed, colour rules, closing radius, simplification) lives in `historical_digitisation_parameters.csv` — nothing is hardcoded and no modern polygon was traced.
- Result: the **MARQUISAT DE MISNIE** bloc, the Electorate of Saxony's core, 16035.1 km2 of source land geometry, bound to `pol_saxony` through the explicit reviewed mapping (no name guessing, no new polity invented).
- 3 **polity-model / extraction gaps** recorded instead of being papered over: the Thuringian and Anhalt enclosures on the same sheet are real 1756 actors that the MAPGEN-009R2 catalogue only tracks as aggregation classes, and Bohemia/Brandenburg/Lusatia have no closed outline on this sheet.

## Hex binding and gameplay control

- 1426 membership rows (from 1426 feature-level rows) via MAX_GROUND_LAND_SHARE on exact hex n OSM-coast-authority land; 0 border hexes keep every polity share.
- **1096 CONTROLLED** hexes and **330 UNRESOLVED** border hexes. UNRESOLVED is used where the winner's margin is smaller than the land a one-uncertainty-radius boundary shift could sweep — cartographic uncertainty is NEVER recorded as DISPUTED_CONTROL, and claims were not derived from control.
- Membership conservation error -0.003 km2 (tolerance set from this run's measurement, not a magic constant). Winner distortion: omission 0.0 km2, commission 1667.5 km2, symmetric difference 1667.5 km2, status GOOD.
- Zero-hex losses 0, overlay candidates 0.

## Coverage

- New unit `region_central_europe_1756_pilot` = TERRITORY_PARTIAL (control), EVIDENCE_PARTIAL (sources), UNASSESSED elsewhere. COMPLETE stays 0 everywhere, so hexes with no control row remain UNKNOWN — never neutral.
- Low Countries remains SOURCE_GAP; HALC v15.0 was not reused for Central Europe.

## Images

- `central_europe_1756_source_map.png` (aspect 1.242)
- `central_europe_georeference_gcps.png` (aspect 2.294)
- `central_europe_1756_continuous_geometry.png` (aspect 1.203)
- `central_europe_1756_hex_membership.png` (aspect 1.184)
- `central_europe_1756_control.png` (aspect 1.184)
- `central_europe_hexification_error.png` (aspect 1.907)

- All six are PRODUCTION figures from the real 1756 source (no synthetic panels in this stage).

## Validation

- `validation.csv`: M12-01..M12-32 machine gates. Pass count in `summary.csv`.

## Known limitations

- One scenario polity is represented: only the Meissen bloc has a closed wash outline on this sheet. Bohemia, Brandenburg and Lusatia would need their missing sides invented, which is forbidden.
- Independent corroboration is outstanding (Utrecht sheet licence-blocked), so the boundary rests on a single contemporary source at ~3 km positional uncertainty.
- The digitised bloc is the electorate's CORE; Saxon territories elsewhere on the sheet are not yet digitised.
