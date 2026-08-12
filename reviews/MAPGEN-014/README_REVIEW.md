# MAPGEN-014 Review — Central Europe corroboration, Schwarzburg model correction and canonical authority revision

**A REVIEWED ROW THAT IS KNOWN TO BE STALE IS NOT AUTHORITY.**
**OVERLAY DOES NOT RESOLVE SOURCE UNCERTAINTY.**

Run `central_europe_1756_revision_20260813`, built on MAPGEN-013 commit `5eff1643982ccc8954dbeced216f7ed71053c9dd`.

## 1. Schwarzburg: a polity that never existed was withdrawn

- MAPGEN-013 registered `pol_schwarzburg` as a single 1756 territorial actor because the 1756 sheet paints one wash labelled SCHWARTZBURG. That was wrong.
- **NDB 24 (2010), pp. 12-14** (A. Klinger, *Schwarzburg, Grafen von*) records the 1599 Stadtilm partition into the lines Schwarzburg-Rudolstadt and Schwarzburg-Sondershausen, the elevations to hereditary imperial prince (Sondershausen 1697, Rudolstadt 1710), and that the new imperial princes took seat and vote in the Reichsfürstenrat only from 1754 — so both held it at the snapshot date.
- `pol_schwarzburg` is **retained** as `MODEL_ARTIFACT_SUPERSEDED` / `NON_TERRITORIAL_INSTITUTION` so the MAPGEN-013 audit trail stays resolvable. It was **not** repurposed as a structural container: the House of Schwarzburg is a dynasty, not a territory.
- `pol_schwarzburg_rudolstadt` and `pol_schwarzburg_sondershausen` are registered as individual imperial estates with their titles at the snapshot date.
- The wash itself became `hsub_schwarzburg_unpartitioned_wash` with feature role **UNCERTAIN_BOUNDARY** — a role that is not gameplay-convertible — so that geometry can never produce control again. Neither new principality controls a hex.

## 2. A second source was acquired, and its lineage checked

- **Zollmann / Homann Heirs, *Thuringiae Orientalis*, Nuremberg 1747**, 2 sheets, approx. 1:200,000 — five times finer than the 1756 Vaugondy sheet. BnF, dép. Cartes et plans, GE BB-565 (3, 21-22); digital object `ark:/12148/btv1b5971578k` (5751×4431 and 5721×4441 px). Public domain under Gallica conditions; **the raster is not redistributed in this repository**.
- Lineage: the Vaugondy sheet descends from the French Sanson/Jaillot material; the 1747 sheet is a German Homann/Nuremberg plate with a different cartographer, engraver, publisher and dedicatee. Neither derives from the other as far as can be documented, so both are recorded as **PARTIALLY_INDEPENDENT** — not INDEPENDENT, because eighteenth-century compilers borrowed silently and absence of evidence is not evidence of independence.
- 2 sources are corroboration-eligible and none is a derivative or same-plate copy, so no confidence is counted twice.

## 3. What the second source did and did not settle

- **It settles the Schwarzburg question by depiction.** The 1747 sheets organise Schwarzburg as *COMITATVS SCHWARZBVRGICVS SVPERIOR* (upper sheet) and *SCHWARZBVRGISCHE VNTERHERRSCHAFT* (lower sheet) — that is, by Herrschaft, not by principality. Two sources of different lineage agree that the Rudolstadt/Sondershausen partition is **not obtainable** from printed maps of this period. That is why no partition geometry was invented.
- **It does not settle Saxony.** The 1747 sheets are eastern Thuringia; the electoral Saxon core around Meissen lies outside them — `INSUFFICIENT_OVERLAP`, measured as a fact, not assumed.
- **It does not yet settle Weimar.** The overlap exists and the 1747 sheet draws Weimar in far greater detail (lettered Ämter and the Oldisleben exclave), but **georeferencing was attempted and not completed**: the neat line is skewed in the scan and the graticule numerals could not be read unambiguously at the available resolution. No control point was invented, so the 1747 source has **no GCP row at all** and the result is recorded as `UNRESOLVED`, never as agreement.

## 4. The stale Saxony authority was superseded

- 401 canonical rows carried the old 2.975 km classification and have been re-measured at 9.168 km: Saxony goes **1,096 → 695 CONTROLLED** and **426 → 827 UNRESOLVED**.
- Direction matters: 401 rows went CONTROLLED → UNRESOLVED and 0 went the other way. No uncertainty was lowered to make hexes controllable.
- The superseded promotion is marked `SUPERSEDED` in the promotion log — not deleted — and every changed row is written to `territorial_control_revision_log.csv` (401 rows) with its old and new status, controller, promotion id and uncertainty.
- Re-running the revision changes 0 rows, so the new state is stable rather than oscillating.

## 5. The four MAPGEN-013 conflict hexes

- All 4 were re-evaluated from both evidence bundles rather than defaulting to the older reviewed row. 4 are **explicitly UNRESOLVED**: each lies inside the uncertainty band of both neighbours' drawn boundaries, so no most-specific territorial actor can be determined.

## 6. Overlay was not used as an escape hatch

- `political_representation_decision.csv`: 0 subjects were assigned OVERLAY_ONLY. Saxony and Saxe-Weimar stay `STANDARD_HEX` because each survives as many hexes — what fails is the source's positional accuracy, not the representation. The Schwarzburg wash is `UNRESOLVED` because the *polity partition* is unresolved; an overlay would turn an open historical question into a rendering choice.

## 7. Images

- `source_lineage_and_corroboration.png` (aspect 2.151)
- `vaugondy_vs_secondary_boundary.png` (aspect 2.452)
- `schwarzburg_model_correction.png` (aspect 1.703)
- `saxony_uncertainty_before_after.png` (aspect 2.298)
- `canonical_control_revision.png` (aspect 2.439)
- `central_europe_control_after_corroboration.png` (aspect 1.278)

## 8. Validation

- `validation.csv` holds the M14 gates; pass count 34/34.

## 9. Known issues — what this run does NOT claim

- **No boundary distance between sources has been measured.** The corroboration achieved is at depiction level for Schwarzburg only. Until the 1747 sheet is georeferenced, no local uncertainty zone may be created and the global 9.168 km model stands.
- Saxe-Weimar still has **0 CONTROLLED hexes**. That is the honest consequence of a single source whose own town placement is 3–9 km out.
- The Rudolstadt/Sondershausen partition geometry remains an open model gap, as do the five deferred regions from MAPGEN-013.
- The Landesarchiv Thüringen holdings were consulted at collection level only; no individual archival signature was verified, so none is cited as pinpoint evidence.
