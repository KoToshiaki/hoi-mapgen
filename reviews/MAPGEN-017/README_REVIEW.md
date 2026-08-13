# MAPGEN-017 Review — Brandenburg copy-specific source acquisition

**OUTCOME: PARTIAL.** Every copy, date and licence question is now settled for the primary sheet and **the raster is in hand**. Georeferencing, digitisation and segment-level continuity remain, so there is still **no geometry and no control** — and no production row was manufactured to show progress.

Run `brandenburg_1756_acquisition_20260813`, built on MAPGEN-016 commit `ff9bfed8899cade9ae5b696a6e1f5c78d0f5effb`.

## 1. A map work is not a plate, and a plate is not a copy

- MAPGEN-016 read a holding record for one copy of the Brandenburg sheet and treated it as if it dated the **source**. A holding record names a **copy**. The same plate can be pulled in 1751 and again in 1757, and a later impression may carry revisions.
- A copy registry now records **4 copies of 2 works**, each with its own `catalogued_copy_date`, `plate_date`, `issue_date`, `represented_political_date`, `copy_state` and state confidence.
- The **Książnica copy is demoted** to `COPY_STATE_NOT_ESTABLISHED` / plate-state comparison until its catalogue entry is read at copy level; the **Rumsey copy** is recorded as a `1757 Atlas Universel` issue of the same plate. A pixel-level state comparison between copies was **not** carried out.

## 2. The BnF copy — acquired, and dated from the plate itself

- **GE DD-2987 (3790); ark:/12148/btv1b53041280v**, Collection d'Anville 03790, `ark:/12148/btv1b53041280v`, single view **7941x6135** at IIIF native maximum, sha256 `485bc0a430837879…`. Physical sheet 49.5 × 65 cm, contours coloured.
- **Licence verified**: public-domain work under Gallica conditions. The raster lives under `data/raw` (git-ignored) and is **not redistributed**.
- **`plate_date = 1751`, read off the plate**: the title cartouche ends *“Avec Privilège. 1751”*. That is this impression's engraved privilege date — not a catalogue inference.
- **`represented_political_date = UNVERIFIED`.** The plate date is not allowed to stand in for the political state depicted.
- The sheet carries a **numbered degree graticule on all four borders** — the precondition the Zollmann sheets lacked — plus an inset *Supplement pour le Marquisat de Brandebourg* covering the Vieille Marche and Quartier de Pregnitz at the same scale.
- The map states in its own note that **Swedish Pomerania comprises the duchy of Bardt, the county of Gutzkow and the duchy of Stettin** — the source itself warns against assigning Pomerania to Brandenburg.

## 3. Lineage — a correction that does not weaken the rule

- MAPGEN-016 labelled the northern Vaugondy sheet `DERIVATIVE`. Sharing a house and an atlas does **not** prove that one sheet was derived from the other, in either direction. Corrected to **`SHARED_ATLAS_LINEAGE`**.
- The rule itself stands: `corroboration_eligible = NO`. One house's work is never counted twice.
- An **independent-lineage candidate** was found: *Lotter ca.1758, Mappa Geographica exhibens Electoratum Brandenburgensem (BLHA)*, engraved by Matthäus Albrecht Lotter and published by Tobias Conrad Lotter in Augsburg, ~1:550,000, held as an original copper engraving at the BLHA. Plate family `GERMAN_SEUTTER_LOTTER_AUGSBURG`, `PARTIALLY_INDEPENDENT`, corroboration-eligible.
- **Not acquired** (`NO`): the archival signature was not confirmed at BLHA and the licence was not checked. Multiple catalogue objects with this title must not be counted as multiple independent sources until plate, impression and reproduction are told apart.

## 4. The temporal problem, stated six times instead of once

- A single continuity assertion over the whole Brandenburg outline would hide the fact that its frontiers face six different neighbours with six different histories. So the question is split into **6 named segments** — Saxony, Mecklenburg, Swedish Pomerania, Magdeburg/Halberstadt, the Polish-Lithuanian Commonwealth, and Silesia/Neumark.
- **0 confirmed, 6 UNRESOLVED.** Only `CONTINUITY_CONFIRMED` may bridge off-date geometry to the snapshot, so nothing bridges.
- Both candidate sheets sit **off** the snapshot: 1751 before it and ca. 1758 after it. Each would need its own bridge, in its own direction.
- **No `POLITICAL_CONTROL` assertion valid at 1756-08-01** was obtained for Brandenburg. The snapshot stays **before the Prussian invasion of Saxony**; wartime occupation is not a legal boundary and is not importable.

## 5. What this stage produced, and did not

- Production features **0**, authorised snapshot **0**, membership **0**, Brandenburg CONTROLLED **0**.
- Brandenburg uncertainty is **`NOT_DERIVED`** — Saxony's 9.168 km is explicitly not inherited; this sheet must earn its own from its own holdout, line width and symbol residual.
- Canonical rows **1,614 → 1,614**, changed **0**. Saxony 695/731, Saxe-Weimar 0/96, Schwarzburg wash 0/89.
- Coverage: `region_brandenburg_1756_pilot` moved `SOURCE_IDENTIFIED_NOT_ACQUIRED` → **`SOURCE_ACQUIRED`**, with control coverage still `UNASSESSED`.

## 6. Zollmann relabelled

- `GEOREFERENCE_EXHAUSTED_FOR_CURRENT_SCAN` → **`DEFERRED_AFTER_BOUNDED_ATTEMPT`**. The earlier label claimed more than the evidence supported: sheet f2 was never attempted and the four failed windows were **placement misses from a downscaled overview**, not scan limits. Zollmann has not been shown to be ungeoreferenceable — it is parked at the current production priority.
- The relabelling changed **no** evidence assertion, boundary feature or control row.

## 7. Images

- `brandenburg_copy_provenance.png` (aspect 1.907)
- `brandenburg_bnf_source_map.png` (aspect 1.258)
- `brandenburg_segment_continuity.png` (aspect 2.436)
- `brandenburg_production_status.png` (aspect 1.803)
- `europe_political_progress.png` (aspect 2.301)

There is deliberately **no** BnF georeference figure, no cross-source boundary figure, no continuous-geometry figure, no hex-control figure and no BLHA source map — none of those results exists.

## 8. Validation

- `validation.csv`: M17 gates, pass count 33/33.

## 9. Known issues

- The BnF sheet is acquired but **not georeferenced**. Its graticule is numbered and legible, so the graticule route is the obvious next step — unlike Zollmann.
- No copy-state comparison was made between the BnF, Książnica and Rumsey copies (border colour, labels, cartouche, plate wear, annotations, boundary lines, inset, engraved date).
- The BLHA signature and licence are unverified and the raster is not in hand, so no independent geometry exists.
- All six continuity segments are unresolved, and no 1756 political-control evidence has been gathered for Brandenburg.
- Brandenburg's internal constituents (Altmark, Mittelmark, Neumark, Uckermark, Prignitz) are visible on the sheet but were not audited; a visible constituent name is not a separate polity.
