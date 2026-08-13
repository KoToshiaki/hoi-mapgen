# MAPGEN-018 Review — the Brandenburg sheet is georeferenced

**OUTCOME: PARTIAL.** The BnF Brandenburg plate now has a validated transform and its own uncertainty. The independent second source was not verified at its archive, no 1756 document was opened, and no boundary segment reached continuity — so there is still **no geometry and no control**, and no canonical row changed.

Run `brandenburg_1756_georef_20260813`, built on MAPGEN-017 commit `2761d1501f6c1f3f7c37692e90f3edd7d75cd9f3`.

## 1. Georeference — graticule first, and it worked

- The sheet carries a numbered degree graticule, so the graticule route was taken rather than falling back to feature points as Zollmann had forced.
- **6 meridians and 3 parallels** were detected on the border bands by the line detector, and **every numeral was read at ×4 magnification**. The middle parallel is in the set because its “54” was read — not because it lies halfway between the other two.
- **18 intersections**: **13 fit / 5 holdout**, spanning all four quadrants. The holdout is one *entire* meridian plus two corners of another, so a held-out point is never an interpolation between its immediate neighbours in the fit.
- **`AFFINE` selected**: fit RMS 59.9 m, **holdout RMS 60.1 m**, holdout max 77.0 m. POLYNOMIAL_2 fits better and holds out worse — complexity was not rewarded, the same rule that caught the overfit in MAPGEN-013.
- GCP residuals: p50 60.0 m, p90 74.8 m, p95 77.4 m, max 79.6 m. Quadrant maxima {'NW': 62.1, 'NE': 73.9, 'SW': 73.6, 'SE': 79.6} — no corner blows up.

## 2. The prime meridian the plate never states

- This sheet carries **no prime-meridian note**. Rather than inherit Ferro from the other Vaugondy sheets, the reading was **tested**: Berlin's town symbol was located on the raster and checked against GeoNames.
- **Residual 9.28 km** under `FERRO_20W_OF_PARIS`. That is the plate's own town-placement error at this scale, not a transform failure, and it is what makes the Ferro reading defensible. Recorded as `CORROBORATED_BY_INDEPENDENT_POINT`, never as read from the plate.

## 3. A map-specific uncertainty, earned not borrowed

- **9.282 km**, combining the holdout RMS, the independent check (9.28 km, the dominant term), the engraved line width and the digitisation tolerance at 67.3 m/px.
- Saxony's 9.168 km was **not** inherited. The two land close together because both are Vaugondy plates of similar scale — that is a finding about eighteenth-century town placement, not a copied constant.

## 4. Copy-state claim weakened

- MAPGEN-017 labelled the BnF copy `EARLY_IMPRESSION_WITH_1751_PRIVILEGE`. That asserts a plate **state** which no comparison established.
- Weakened to **`COPY_CATALOGUED_1751_WITH_1751_PRIVILEGE`** (confidence MEDIUM): a 1751 catalogue entry plus a 1751 privilege inscription is exactly that. Proving an early state needs a pixel comparison against the Rumsey and Książnica copies, which has not been done.

## 5. What still blocks production

- **The independent source.** Two BLHA leads were recorded; **0 were verified at source** and **0 acquired**. Their relation to each other (same copy / same plate / different plate / reproduction) is unresolved, so they count as **at most one** source, never two.
- **1756 political control.** 2 candidates recorded, **0 obtained**. A volume title is not evidence: only an individual dated document with its column, heading, issuing authority and named territorial scope would qualify. Each row also states that an administrative record could never serve as **boundary-position** evidence.
- **Continuity.** All 6 frontier segments remain UNRESOLVED. A georeferenced 1751 plate is still a 1751 plate.
- Therefore: 0 features, 0 membership rows, 0 CONTROLLED, and canonical rows 1,614 → 1,614 (changed 0).

## 6. Constituents kept in their place

- 7 entries audited. Altmark, Mittelmark, Neumark, Uckermark and Prignitz are **territorial constituents** of Brandenburg, not polities — a visible name on a map is not a sovereign actor.
- **Magdeburg/Halberstadt** share a monarch, not a territory, and were not absorbed. **Swedish Pomerania** is defined by the sheet's own note (Bardt, Gutzkow, Stettin) and none of Pomerania is assigned to Brandenburg.

## 7. Images

- `brandenburg_bnf_graticule_gcps.png` (aspect 1.993)
- `brandenburg_bnf_georeference.png` (aspect 2.3)
- `brandenburg_blockers.png` (aspect 2.143)
- `europe_political_progress.png` (aspect 2.301)

There is no BLHA source figure, no cross-source boundary figure, no continuous-geometry figure and no hex-control figure — none of those results exists.

## 8. Validation

- `validation.csv`: M18 gates, pass count 30/30.

## 9. Known issues

- The Brandenburg boundary has **not** been digitised. The transform exists; the wash tracing does not.
- The inset *Supplement pour le Marquisat de Brandebourg* (Vieille Marche, Prignitz) needs its **own** placement semantics — the main transform does not apply to it, and it must not be pasted into map-body coordinates by eye.
- Only one independent check point (Berlin) was used. More would sharpen the uncertainty and test it across the sheet.
- The BLHA leads remain unverified; without them there is no independent geometry and no cross-source comparison.
- No 1756 document has been read, so Brandenburg has geometry potential but no political authority at the snapshot.
