# MAPGEN-016 Review — Zollmann feature-point final attempt and the Brandenburg production front

**OUTCOME: PARTIAL.** The Zollmann sheet is now formally exhausted for this scan, and the Brandenburg source chain was identified but not acquired — so **no geometry and no control were produced, and no canonical row changed.**

Run `central_europe_1756_expansion_20260813`, built on MAPGEN-015 commit `a47ce5d7cddbfe7a764e0d1fcf61b3d6a337d0cb`.

## 1. Zollmann 1747 — Route B, once, then closed

- MAPGEN-015 exhausted Route A (graticule). This stage did **not** repeat it. Route B (feature points) was given one bounded attempt: **9 candidate windows** on sheet f1, cropped from the native raster with autocontrast and inspected.
- **2 symbols positively identified; 1 accepted.** Weimar's walled town outline was unambiguous. Erfurt's clearly drawn star turned out to be the **Petersberg citadel**, about a kilometre from the town centre the gazetteer names, so it was rejected rather than used with a fudge.
- Four windows, placed from a downscaled overview, simply did not contain their target town (Querfurt, Merseburg, Sangerhausen, Jena). Those misses are recorded, not quietly retried.
- One point cannot define an affine transform (which needs 3), let alone a fit/holdout split with spatial stratification. **Final status: `GEOREFERENCE_EXHAUSTED_FOR_CURRENT_SCAN`.**
- Reference coordinates came from **GeoNames cities15000 (CC BY 4.0)**, already held locally, used only as point references for map symbols. No modern administrative boundary was used.
- Consequence: this source is not pursued further for 6 km control resolution. It is archived, not deleted — a better scan or another edition reopens it. Saxe-Weimar stays at **0 CONTROLLED / 96 UNRESOLVED**, the global 9.168 km uncertainty stays, and the measured Weimar corroboration sample count is still **0**.

## 2. Saxe-Weimar / Saxe-Eisenach — same model, better basis

- MAPGEN-015 concluded personal union from the reasoning *"two separate administrations under one ruler is the definition of a personal union"*. That is an **inference**, and administration, sovereignty, estates and dynastic style are four different levels.
- The basis is now a **direct territorial statement** from IEG-Mainz's HGIS Germany compendium: *"1741 kam es mit den Städten und Ämtern Eisenach, Creuzburg und Gerstungen, Remda und Allstedt … an Sachsen-Weimar, das sich seitdem Sachsen-Weimar-Eisenach nennt"* — the Eisenach towns and Ämter **came to** Saxe-Weimar in 1741, and the composite name dates from then.
- The BnF heading is no longer merely discounted; it is given a level: **`umbrella_dynastic_or_collective_name = Saxe-Weimar-Eisenach`**, with `territorial actors = Saxe-Weimar, Saxe-Eisenach`.
- **The constitutional level remains a declared gap.** The 1809 *Constitution der vereinigten Landschaft* was **not obtained**; only secondary summaries state that the parts remained separate in state law until then. Rather than fill that in, the audit records `NOT_OBTAINED` with confidence `UNKNOWN`, and the model decision is held at MEDIUM confidence.
- **Model unchanged: `TWO_DISTINCT_ACTORS_IN_PERSONAL_UNION`.** No polity was added or removed; only the evidence changed.

## 3. Brandenburg — the front is open, the source is not

- The primary candidate was **verified to exist**: Vaugondy, *Partie Septentrionale du Cercle de Haute Saxe qui contient le Duché de Poméranie et le Marquisat de Brandebourg*, with an **institutional holding at Książnica Pomorska, Szczecin** and a Rumsey listing (3353.061).
- **Its 1751 date is the plate *privilege* date**, and the sheet was still being issued in the 1757 Atlas Universel. Plate date, issue date and represented political date are three different things; only the first is known, so `represented_political_date = UNVERIFIED`.
- **Lineage warning:** it is a Vaugondy *Atlas Universel* plate — the **same house and atlas** as the 1756 sheet already in production. It would be a primary source for Brandenburg but can **never corroborate** the existing Vaugondy geometry; counting it would count one house's work twice. Recorded `DERIVATIVE`, `corroboration_eligible = NO`.
- **Continuity: `NOT_ESTABLISHED`.** No 1751→1756 territorial evidence was found. *"Only five years apart"* was explicitly refused as a substitute, so the sheet could not authorise 1756 control even if it were in hand.
- The snapshot stays **1756-08-01, before the Prussian invasion of Saxony**; wartime occupation lines must never be imported back into it.
- **Result: 0 rasters acquired, 0 GCPs, 0 new features, 0 CONTROLLED.** Brandenburg's uncertainty is `NOT_DERIVED` — Saxony's 9.168 km is explicitly **not** inherited.
- A coverage unit `region_brandenburg_1756_pilot` was opened as `UNASSESSED` / `SOURCE_IDENTIFIED_NOT_ACQUIRED`. Row absence inside it still means UNKNOWN.

## 4. What this stage did and did not change

- Canonical rows: **1,614 → 1,614**, changed: **0**. Saxony 695/731, Saxe-Weimar 0/96, Schwarzburg wash 0/89.
- What changed is **which sources the project is still waiting on**: Zollmann 1747 is closed for this scan, Vaugondy 1751 is identified and unacquired, Utrecht 1756 is still licence-blocked.

## 5. Images

- `zollmann_route_b_gcps.png` (aspect 2.139)
- `zollmann_final_georeference_status.png` (aspect 1.803)
- `brandenburg_source_chain.png` (aspect 1.922)
- `brandenburg_continuity_blocker.png` (aspect 2.225)
- `weimar_eisenach_evidence_update.png` (aspect 1.719)
- `central_europe_control_progress.png` (aspect 2.301)

There is deliberately **no** `brandenburg_georeference.png`, `brandenburg_continuous_geometry.png` or `brandenburg_hex_control.png` — none of those things exist. The figures that do exist say *attempt*, *blocker* and *not acquired* on their face.

## 6. Validation

- `validation.csv`: M16 gates, pass count 29/29.

## 7. Known issues

- Route B was attempted on sheet f1 only. Extending the same method to f2 could not have changed the outcome, but it means f2 has had no feature-point attempt at all.
- The four missed windows were placed from a downscaled overview. A next attempt should locate each town from its **label** at native resolution first, then find the symbol beside it.
- Erfurt is recoverable: the citadel is identifiable, so a citadel-to-town offset from a modern reference would turn it into a usable point.
- The 1809 constitution is still unobtained, so the Weimar/Eisenach model rests on territorial and administrative evidence rather than constitutional text.
- Brandenburg has no raster, no licence verification and no continuity evidence. All three must be settled before any geometry is drawn.
