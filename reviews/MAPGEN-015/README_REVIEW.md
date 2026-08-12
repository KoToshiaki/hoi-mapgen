# MAPGEN-015 Review — Zollmann 1747 precision georeference attempt, Saxe-Weimar/Eisenach model audit and MAPGEN-014 metric correction

**OUTCOME: PARTIAL-B.** Phases A and B are complete. The georeference was attempted to exhaustion and is **not defensible**, so no control point was invented and no canonical row changed.

Run `central_europe_1756_precision_20260813`, built on MAPGEN-014 commit `d8745d017e6bfc98c746f93d9c5143b9ca005349`.

## 1. MAPGEN-014 review metric correction

- MAPGEN-014's `saxony_*` counts were computed over the whole authorised candidate, which contains **both** Saxony and Saxe-Weimar. Saxe-Weimar's 100 unresolved hexes were therefore reported as Saxony's.
- Corrected, filtered by the subject named in each row's provenance: Saxony alone (1,426 targets) went CONTROLLED **1,096 → 695** and UNRESOLVED **330 → 731** — the same 401 rows, recomputed from canonical data rather than hard-coded.
- Saxe-Weimar is now its own metric: 0 CONTROLLED, 96 UNRESOLVED.
- The candidate-scope aggregate is kept but renamed `authorised_candidate_scope_*`, so no number carries a polity's name it does not describe.
- **The canonical data was never wrong.** Only the summary was. No territorial_control row was touched by this correction.

## 2. Corroboration metric split

- MAPGEN-014 reported `independent_boundary_corroborations = 1`. That row was an `AGREES` with **n_samples = 0** — a depiction-level agreement, not a measured boundary.
- Split: **depiction_level_corroborations = 1**, **measured_boundary_corroborations = 0**, **measured_boundary_sample_count = 0**. A measured corroboration now requires samples and real distance statistics; a 0-sample row is not allowed to carry any.

## 3. Saxe-Weimar / Saxe-Eisenach: the sources disagree

| supports | source |
|---|---|
| one unified polity from 1741 | BnF authority `ark:/12148/cb151032140`: *the 1741 reunion ... formed the duchy of Saxe-Weimar-Eisenach* — a **cataloguing heading** |
| two distinct constituents | Landesarchiv Thüringen, Bestand 26508 *Landesregierung Eisenach*: Eisenach kept its **own Regierung, Kammer and Oberkonsistorium** until the 1849/50 reform |
| personal union | Deutsche Biographie `sfz39202`: Ernst August II Constantin (1748–1758) styled *Herzog von Sachsen-Weimar-Eisenach*, with a separate administrator in Eisenach during his minority |
| two territories | the 1747 sheet's own title: *DVCATVM VINARIENSEM **nec non** ISENACENSIS Partes Boreales et Orientales* |

- **Decision: `TWO_DISTINCT_ACTORS_IN_PERSONAL_UNION`.** `pol_saxe_eisenach` is registered as its own actor and a `PERSONAL_UNION` relationship records the shared ruler. **No** `pol_saxe_weimar_eisenach` was created — a ducal style is not a merged territory, and a surviving administration is not by itself a sovereign state.
- `pol_saxe_weimar` is **not superseded**: it was incomplete, not wrong. No controller was created or withdrawn; Saxe-Eisenach has no geometry and controls nothing.

## 4. What the 1747 raster actually yields

- **Native resolution verified.** `info.json` reports 5751x4431 (f1) and 5721x4441 (f2), equal to the manifest canvas **and** to the locally held raster. There is no sharper scan to fetch, so magnification cannot add information.
- **Page skew measured** on 8 border edges; only 2 are reliable. The top neat line fits within 10 px and gives a scan rotation of **-0.4102°** (f1) and **-0.1994°** (f2). The other six edges are recorded `DETECTOR_FAILED` — the detector locks onto title lettering and cartouches. **No rectification transform was applied**, and rectification is kept strictly separate from georeferencing.
- **14 text anchors** attacked at ×3 magnification with autocontrast: 5 CLEAR, 3 AMBIGUOUS, 6 UNREADABLE. Every UNREADABLE row has an **empty** reading.
- **The real gain:** one longitude numeral was read unambiguously on sheet f2 — `2|9°`, the tick splitting the numeral, i.e. the 29th meridian from the sheet's own Ferro prime meridian. MAPGEN-014 could read none. The prime-meridian note and the scale bar were also transcribed.
- **Why that is still not a transform:** one longitude value, with no traced graticule line, no latitude pair and nothing on sheet f1, cannot place a sheet. A transform would have required inventing the rest.

## 5. What did NOT happen

- No GCP row exists for the 1747 source. Its `georeference_status` is still `NOT_YET_GEOREFERENCED`.
- No cross-source boundary distance was measured (`measured_boundary_sample_count = 0`).
- No local uncertainty zone was created (`local_uncertainty_zones = 0`); the global 9.168 km model stands.
- The two-sheet seam is reported `NOT_MEASURABLE_NO_GEOREFERENCE` — not as a zero offset.
- The Schwarzburg wash remains `UNCERTAIN_BOUNDARY`; no partition was manufactured by image processing.
- **`canonical_rows_changed_this_stage = 0`.** Saxe-Weimar stays at 0 CONTROLLED.

## 6. Images

- `zollmann_native_resolution_audit.png` (aspect 5.701)
- `zollmann_scan_rectification.png` (aspect 2.301)
- `zollmann_georeference_attempt_sheet1.png` (aspect 1.803)
- `zollmann_georeference_attempt_sheet2.png` (aspect 1.803)
- `zollmann_sheet_seam.png` (aspect 4.826)
- `saxe_weimar_eisenach_model_audit.png` (aspect 1.719)
- `mapgen014_metric_correction.png` (aspect 3.43)

The cross-source residual figure is deliberately **absent** — there is no residual. The georeference figures are named *attempt* and state 0 accepted GCPs on their face.

## 7. Validation

- `validation.csv`: M15 gates, pass count 33/33.

## 8. Known issues

- The graticule numerals on sheet f1 were not read. The band slopes, so fixed windows clip the numerals; a window that follows the fitted top neat line is the obvious next attempt.
- Only the top neat line is detectable. A rectification needs a detector that ignores cartouches and lettering.
- The Eisenach archival finding is collection-level: the Vorwort page could not be rendered, so the reading came from the portal's index and is recorded at MEDIUM confidence.
- Saxe-Eisenach has no geometry from any source.
- Saxe-Weimar still has 0 CONTROLLED hexes, and will until a second source is genuinely georeferenced.
