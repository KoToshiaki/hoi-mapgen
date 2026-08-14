# MAPGEN-019 Review — the Brandenburg georeference, rebuilt from the image

**OUTCOME: SUBSTANTIAL.** The disqualified transform was **not repaired — it was replaced**. Thirty-three two-dimensional correspondences were read off the plate itself, split three ways before any model was fitted, and the result is **`GEOREFERENCED_VALIDATED`** with a positional uncertainty of **17.228 km**, down from the 27.657 km provisional figure. BLHA AKS 1145 A was acquired, five 1756 documents were opened and all six frontiers were researched. **No geometry was digitised and no control was promoted** — that is a scope decision and it is reported as a shortfall.

Run `brandenburg_georef_rebuild_20260813`, built on MAPGEN-018R commit `bdc3f8868292e5634e20d7a98d50dab6868cc9e3`. Canonical rows 1,614 → 1,614, changed **0**.

## 1. Why the old transform failed — now with the mechanism

MAPGEN-018R proved the transform was wrong. It could not say *why*. Re-measuring **all four** border graduations does:

- one degree of longitude spans **972.5 px** on the top border and **1058.8 px** on the bottom;
- extended, the six meridians meet at latitude **91.5°** — the pole, within engraving tolerance.

The plate is a **converging-meridian (conic) construction, not a plate carrée**. MAPGEN-018 built its grid from the top border alone and so imposed the top-border x-scale over the whole sheet; that alone produces an east–west error growing southward of roughly 4% of the distance from the sheet centre — about 9 km at the corners. That is the systematic pattern MAPGEN-018R measured.

The interior carries **no graticule lines** (`NO`), checked at native resolution over open sea and open land. Nothing was interpolated.

## 2. Map-first collection

The sheet was cut into sixteen tiles covering the whole engraved field and read at native resolution. **Symbols printed on the plate were found first**; identity and reference coordinate were resolved only afterwards. The anchor is the engraved settlement circle — located by an annulus template and refined to the ring's darkness-weighted centroid — never the centre of the label text.

- **33 directly observed 2-D correspondences** (MAPGEN-018R had 5, all found by cropping windows the old transform predicted).
- Zones: `NE:8, NW:6, SE:4, SW:10, centre:5` — every zone carries at least three.
- The five MAPGEN-018R points are **retained and re-measured on their symbols**, and are barred from blind validation because they were discovered through the old transform.

**Semantics fixed.** `directly_observed_2d_correspondences` and `production_fit_gcps` are now separate: 20 points carry the fit role, but all 33 are observations. "No production GCP" can never again be written as "no observation".

## 3. The split, frozen before fitting

`FIT 20 / MODEL_SELECTION_HOLDOUT 6 / BLIND_VALIDATION 6`, plus 1 excluded. Pairwise disjoint, deterministic, stratified by zone.

- `ofp_berlin` left blind validation (`PRIOR_TRANSFORM_POINT_CANNOT_BE_BLIND`); `ofp_frankfurt_oder` took its place in zone SW. Applied **before** any fit.
- `ofp_potsdam` left blind validation (`PRIOR_TRANSFORM_POINT_CANNOT_BE_BLIND`); `ofp_gorzow_wielkopolski` took its place in zone SW. Applied **before** any fit.

Brandenburg an der Havel is **excluded from every set**: the plate draws *New Brandeburg* (the Neustadt) and *Alt Brandeburg* separately, and the reference coordinate is the modern city centre, so the pairing carries an identification offset of about a kilometre. It is kept as an observed point and used by nothing.

## 4. Prime meridian, settled properly this time

MAPGEN-018R scored three candidates *through a fitted transform* — which absorbs any constant longitude offset and therefore cannot separate them at all. Here longitudes are read straight off the engraved graduations and compared with the observed features:

| candidate | n | median | p90 | max |
|---|---|---|---|---|
| FERRO_20W_OF_PARIS | 26 | 28.61 km | 79.38 km | 102.46 km |
| GREENWICH | 26 | 1,197.17 km | 1,213.65 km | 1,255.88 km |
| PARIS | 26 | 1,350.80 km | 1,370.05 km | 1,411.91 km |

Ferro wins by a factor of ~40 → `CORROBORATED_BY_MULTIPLE_OBSERVED_FEATURES`. The blind points took no part.

## 5. Model selection

Rule fixed before fitting: **the simplest model whose model-selection-holdout RMS is within 10% of the best, with no Jacobian folding**.

| model | fit RMS | holdout RMS | holdout p90 | scale ratio | folding | cond |
|---|---|---|---|---|---|---|
| **AFFINE** | 10.45 km | 9.57 km | 13.30 km | 1.075 | False | 2.1e+04 |
| PROJECTIVE | 10.10 km | 9.00 km | 11.81 km | 1.252 | False | 3.0e+06 |
| POLYNOMIAL_2 | 6.79 km | 10.93 km | 14.34 km | 1.485 | False | 3.2e+08 |

- **POLYNOMIAL_2 has the best fit residual and the worst holdout residual.** That is what over-fitting looks like, and it is exactly the failure mode the brief warns about: a rubber sheet ironing the plate's own historical distortion into a fictitiously accurate boundary. Rejected.
- AFFINE and PROJECTIVE are not separable at this plate's noise level, so the simpler one is taken. A converging-meridian plate *ought* to favour a projective; it does not, because the sheet's own placement error (~8 km) is larger than the convergence left over after a least-squares affine absorbs the average. The projective solve is also ill-conditioned on raw pixel coordinates — **the same model is selected either way**, which is why this is reported as a robust choice rather than a marginal one.

## 6. Blind validation — the headline number

Evaluated **once**, after the model was fixed. n=6.

| point | zone | residual |
|---|---|---|
| Koszalin | NE | 4.48 km |
| Frankfurt (Oder) | SW | 7.39 km |
| Guestrow | NW | 10.27 km |
| Stargard | centre | 11.86 km |
| Gorzow Wielkopolski | SW | 13.72 km |
| Miedzyrzecz | SE | 20.72 km |

median **11.064 km**, p75 13.256 km, p90 **17.223 km**, p95 18.973 km, max 20.724 km. Worst zone median 11.265 km (NW) — no catastrophic quadrant. No Jacobian folding; scale ratio 1.0746.

### Uncertainty budget (map-specific, nothing borrowed from Saxony)

| term | value |
|---|---|
| blind_validation_p90_m | 17,223 m |
| symbol_placement_m | 389 m |
| boundary_line_width_m | 162 m |
| digitisation_m | 130 m |
| positional_uncertainty_m | 17,228 m |

→ **17.228 km**. The 27.657 km MAPGEN-018R figure is retained under the name `provisional_validation_p90_km` and is **not** a final accuracy.

## 7. BLHA — acquired

- **AKS 1145 A** (internal id 1266626), *ca.* 1758, **CC0 1.0**, acquired at **7582×6436**. The DDB derivative caps at 800×646; the archival master comes from the BLHA's own IIIF endpoint. Sheet reads *Cura et Impensis Conrad Lotter, Aug. Vind.* — an administrative map of the Kurmark and Neumark drawn by *Circulus*.
- **AKS 1132 A** (internal id 1264164), 1758 — **verified at source**, but no digitisation is offered. An absence, not a rights blocker.
- **Relation: same work, impression `UNRESOLVED`** — it cannot be settled without an image of 1132. **They count as one source, not two.** A third DDB record, *1220 LGB K 422 A* (1267037, 1758–2012), is explicitly a `(Nachdruck)`; that note belongs to **that** object and not to AKS 1145 A.

## 8. 1756 political evidence — individual entries, opened

From *Novum Corpus Constitutionum Prussico-Brandenburgensium* II (BSB `bsb11399173`):

| no. | date | scan | col. | territory | role |
|---|---|---|---|---|---|
| No. XII | 1756-02-02 | 0015 | 25-26 | Kurmark | POLITICAL_CONTROL |
| No. XVIII | 1756-02-11 | 0017 | 29-30 | Altmark; Uckermark | ADMINISTRATIVE_SCOPE |
| No. XXVI | 1756-02-26 | 0023 | 41-42 | Neumark; Altmark; Uckermark | ADMINISTRATIVE_SCOPE |
| No. XXXIII | 1756-03-08 | 0025 | 45-48 | Neumark; Kreis Sternberg; Kreis Crossen; Kreis Zuellichau; Kreis Cottbus | POLITICAL_CONTROL |
| No. XXXII | 1756-03-06 | 0025 | 45-46 | Pomerania (Koeslin; Stettin) | ADMINISTRATIVE_SCOPE |

The strongest is **No. XXXIII, 8 March 1756**: Frederick legislates for *die Neumarck und denen 4. Neumarckschen incorporirten Creisen* — **Sternberg, Crossen, Züllichau and Cottbus**. Those same four appear as *Circulus Sternbergensis, Crossensis, Zullichaviensis* and *Cottbus* on the ca. 1758 BLHA sheet: a direct 1756→1758 bracket on administrative composition.

**No row is `BOUNDARY_POSITION`.** An edict tells you who governed a province, never where its line ran.

**Pomerania separation** is documented rather than assumed: No. XXXII (6 March 1756) addresses the *Pommersche/Stettinsche Regierung* and the *Cößlinisches Hofgericht* — bodies entirely separate from the Kurmark and Neumark ones.

## 9. Six frontiers — each individually researched

| segment | 1751→1756 | 1756→1758 | status | confidence |
|---|---|---|---|---|
| Brandenburg (Kurmark/Niederlausitz side) - Electoral Saxony | NONE_FOUND | NONE_FOUND_DE_JURE | CONTINUOUS | HIGH |
| Brandenburg (Prignitz/Ruppin/Uckermark side) - Mecklenburg-Schwerin and Mecklenburg-Strelitz | NONE_FOUND | NONE_FOUND | CONTINUOUS | MEDIUM |
| Brandenburg (Uckermark) - Swedish Pomerania | NONE_FOUND | OCCUPATION_ONLY_NO_CESSION | CONTINUOUS | HIGH |
| Brandenburg (Altmark/Zauche side) - Duchy of Magdeburg and Principality of Halberstadt | NONE_FOUND | NONE_FOUND | CONTINUOUS | HIGH |
| Brandenburg (Neumark/Netze side) - Polish-Lithuanian Commonwealth | NONE_FOUND | OCCUPATION_ONLY_NO_CESSION | CONTINUOUS | HIGH |
| Brandenburg (Crossen/Zuellichau side) - Silesia | NONE_FOUND | NONE_FOUND_DE_JURE | CONTINUOUS | HIGH |

**The decisive fact:** the scenario instant is **1 August 1756**. Prussian troops entered Saxony on **29 August 1756**, Sweden joined in September 1757, Russian columns reached the Neumark in 1758. *Every* wartime change post-dates the snapshot, so the 1751 sheet's geometry needs no wartime correction to stand for 1 August 1756. Where later occupation did occur it moved armies, not frontiers, and Hubertusburg (1763) restored the status quo ante.

This is a **searched** result, not an unsearched one: every segment carries the sources consulted and the locators found.

## 10. Shortfalls against the brief — reported as shortfalls

- **No BLHA independent georeference was attempted.** The raster is in hand and the brief required an independent georeference of it. Nothing was inherited from the BnF transform, because nothing was computed.
- **No `SOURCE_DATE_1751` geometry was digitised.** The gate is now open — the transform is validated — but the boundary was not traced, so there is no cross-source comparison against the ca. 1758 sheet and **no control was promoted**. Brandenburg CONTROLLED remains **0**.

The reason is scope: the georeference rebuild and the three evidence phases consumed the stage. That is the honest reason, not a justification. Note in particular that production is **not** blocked by an evidence gap — the political evidence and the continuity research both came out positive.

## 11. Images

- `brandenburg_observed_points.png` (aspect 2.031)
- `brandenburg_train_holdout_blind.png` (aspect 2.017)
- `brandenburg_model_comparison.png` (aspect 2.477)
- `brandenburg_blind_validation_residuals.png` (aspect 2.471)
- `brandenburg_georeference_validated.png` (aspect 1.566)
- `brandenburg_blha_source.png` (aspect 2.125)
- `brandenburg_1756_evidence.png` (aspect 2.147)
- `brandenburg_prime_meridian.png` (aspect 4.589)

There is deliberately no BLHA georeference figure and no digitised boundary figure: neither was produced.

## 12. Validation

- `validation.csv`: M19 gates, pass count 39/39.

## 13. Known issues

- **The plate's own placement error is ~8–11 km** and that, not the model, now dominates. No transform can do better on this sheet; a better number needs a better source.
- Kartuzy (23 km) and Lauenburg (18 km) sit in Pomerelia, the worst-surveyed corner of the plate. They were kept: dropping points because they are inconvenient after the split was frozen is exactly what the brief forbids.
- Küstrin was **rejected during collection**, not after: its symbol could not be isolated in the marsh hatching and the modern town centre sits ~1 km from the destroyed fortress.
- The Vieille Marche / Prignitz supplement carries its own graticule; it is excluded from the transform and remains `INSET_GEOMETRY_GAP`.
- BLHA georeference and the 1751 digitisation remain outstanding.
