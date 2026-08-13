# MAPGEN-018R Review — the Brandenburg georeference does not survive review

**OUTCOME: PARTIAL.** The MAPGEN-018 transform is **downgraded, not repaired**. The prime meridian is now corroborated by five independent points instead of one, and the real positional error turns out to be far larger and systematic. No geometry, no control, no canonical row changed.

Run `brandenburg_georef_review_20260813`, built on MAPGEN-018 commit `56e8a3bb753abe6a592b4ada2808d64f40636cdf`.

## 1. The flaw, stated plainly

- MAPGEN-018 reported **18 graticule control points**. They were not eighteen observations. **6 meridian ticks** were measured on the top border and **3 parallel ticks** on the left border — **9 primitive measurements** — and the pairs were formed by crossing them.
- Each longitude therefore reused one `pixel_x` three times and each latitude reused one `pixel_y` six times.
- **The fit/holdout split shared primitive observations.** Every held-out point drew its *y* from a parallel that was also in the fit. That is why the "holdout RMS" came out at 60.1 m: an affine model reproduces a rectangle it was handed. It measured **nothing** about geography.
- A meridian tick on the top border fixes a longitude and an *x*. It does **not** fix a latitude. It is not a two-dimensional control point on its own, and crossing it with a parallel tick does not make one.

## 2. What one check point hid

- MAPGEN-018 validated with **one** point. Berlin came out at 9.3 km, which reads as ordinary eighteenth-century placement error.
- **5 checks** were located this time by cropping each predicted window at native resolution and reading what is actually printed there. Three of those windows contained **the wrong town**: the window predicted for Frankfurt an der Oder held **Fürstenwalde**, Neuruppin's held **Fehrbellin**, and Schwedt's held **Angermünde**.

| check | quadrant | residual |
|---|---|---|
| Berlin | centre | 9.27 km |
| Potsdam | centre | 8.66 km |
| Brandenburg an der Havel | SW | 7.57 km |
| Fuerstenwalde | SE | 26.24 km |
| Angermuende | NE | 28.60 km |

- Median **9.27 km**, p90 **27.66 km**, max **28.6 km**. Centre and south-west sit near 8–9 km; east and north-east near 26–29 km.
- **That is systematic, not scatter** — and it is precisely what a single check cannot reveal. The likely cause is that the plate is not on a rectangular graticule, so a border-derived axis-by-axis model degrades away from the centre.

## 3. The prime meridian, settled properly

- The sheet states no prime meridian. Rather than inherit Ferro from the other Vaugondy plates, three candidates were scored against the **same** independent checks:

| candidate | median residual |
|---|---|
| FERRO_20W_OF_PARIS | 9.27 km |
| PARIS | 1,362.78 km |
| GREENWICH | 1,206.75 km |

- Ferro wins by more than two orders of magnitude (`CORROBORATED_BY_MULTIPLE_INDEPENDENT_POINTS`). **That settles the meridian. It does not validate the transform** — even under Ferro the residuals reach 28.6 km.

## 4. What changed in the data

- Status: `GEOREFERENCED` → **`GEOREFERENCE_PROVISIONAL_RECONSTRUCTED_GRID`**. Coverage: `GEOREFERENCED` → **`GEOREFERENCE_PROVISIONAL`**.
- The 18 rows are **retained** as audit history, reclassified `RECONSTRUCTED_GRID_POINT` with `pixel_coordinate_directly_observed = NO` and `counts_as_production_gcp = NO`. **Production GCPs: 0. Directly observed 2-D GCPs: 0.**
- The 60 m figure is renamed `reconstructed_grid_*` everywhere so it can never again be quoted as a holdout accuracy.
- Uncertainty: **9.282 km → 27.657 km**, now derived from the p90 of multiple checks rather than from one Berlin residual.
- Canonical rows 1,614 → 1,614, changed **0**. Brandenburg CONTROLLED **0**.

## 5. Shortfalls against the brief — reported as shortfalls

These were required by the stage brief and **were not done**. They are not findings:

- **BLHA AKS 1132 A**: NOT_VERIFIED_AT_SOURCE (shortfall).
- **BLHA AKS 1145 A**: NOT_ACQUIRED (shortfall). The brief made acquisition mandatory and required an HTTP/rights blocker to be recorded if it failed; neither happened.
- **1756 political documents read: 0.** No individual Novum Corpus entry was opened.
- **Continuity segments individually researched: 0 of 6.**

The georeference review consumed the stage. That is the honest reason, not a justification.

## 6. Images

- `reconstructed_vs_observed_gcps.png` (aspect 2.139)
- `brandenburg_independent_checks.png` (aspect 2.298)
- `prime_meridian_candidate_comparison.png` (aspect 2.705)
- `brandenburg_georef_status_after_review.png` (aspect 1.803)

There is deliberately no “corrected georeference” figure and no BLHA figure — the transform was not corrected and no BLHA raster exists.

## 7. Validation

- `validation.csv`: R18 gates, pass count 28/28.

## 8. Known issues

- **No directly observed two-dimensional control point exists yet.** The next attempt must either trace interior graticule lines to real intersections, or build the control set from identified feature points with their own fit/holdout.
- The residual pattern suggests a non-rectangular plate graticule. A projective or trapezoidal model fitted to *observed* points may absorb it; an axis-by-axis border model cannot.
- Only five checks, and one (Brandenburg an der Havel) is the Neustadt rather than the modern centre, so its residual carries an identification offset of its own.
- BLHA, the 1756 documents and the continuity research all remain outstanding.
