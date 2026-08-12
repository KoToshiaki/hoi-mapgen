# MAPGEN-013 Review — Central Europe polity refinement, multi-polity production and canonical control promotion

**HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM MODERN ADMINISTRATION.**
**MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER NEUTRAL.**

Run `central_europe_1756_expand_20260813`, built on MAPGEN-012 commit `1793ea1786d6c4796d1cb0349387a5046b2358fc`.

## 1. Staged pilot control became scenario authority

- Canonical `territorial_control.csv` went from **3 to 1,614 rows**: 1,426 promoted from the reviewed MAPGEN-012 candidate and 185 from the new MAPGEN-013 production. The count is computed from unique target keys, not asserted.
- Of the MAPGEN-012 rows, **1,096 CONTROLLED** and **330 UNRESOLVED** are now scenario authority. UNRESOLVED rows carry no controller — they say the source cannot resolve the hex, not that it is neutral.
- Promotion is **idempotent**: re-running the identical artifact inserted 0 rows and wrote no new log entry, because the promotion id is a hash of (scenario, stage, candidate sha256). A target may hold only one active row; a second promotion touching an owned key raises instead of overwriting.
- **Source namespace migration**: canonical `source_id` stays scenario-local (`src_9d6f03b5c85f`) so the existing foreign key into `sources.csv` keeps working, while the full historical bundle (`hsrc_34735c52ef0d`, `hev_`, `hbf_`) lives in `territorial_control_provenance.csv` (1,611 rows). `sources.csv` carries the `global_source_id` crosswalk, so nothing is lost and the canonical table stays lean.

## 2. Positional uncertainty was EXPANDED, not reduced

- MAPGEN-012 rested on one settlement check (2.975 km). This stage added independent checks in four quadrants (4 total, none used in the fit), and the resulting uncertainty is **9.168 km**.
- That is deliberately worse. The 330 unresolved hexes were not forced down; if anything the honest band around every drawn line is wider than MAPGEN-012 believed.
- Transform selection was also corrected. Models are scored on the sheet's own graticule holdout, but any model whose independent settlement residual explodes is disqualified. POLYNOMIAL_2 had the *best* graticule holdout and was rejected for being wildly wrong between the grid nodes; **PROJECTIVE** is used.
- The promoted MAPGEN-012 rows were classified at the older uncertainty. Re-classifying them is recorded as a follow-up in `run_manifest.json` and the promotion log — **not** applied silently.

## 3. Polity model refined region by region

- All 7 enclosed colour-wash regions on the sheet were audited individually: 2 registered as individual polities, 5 deferred.
- **Duchy of Saxe-Weimar** ('DUCHE DE WEIMAR') and **Schwarzburg** ('SCHWARTZBURG') are registered because the sheet labels them itself. Each has POLITY_EXISTENCE evidence pointing at that lettering, an IMPERIAL_MEMBER_OF relationship, and an INCLUDED audit row.
- The deferred regions (Eichsfeld/Duderstadt, Stolberg, Harz/Wernigerode, Mansfeld, Erfurt) stay `DEFERRED_POLITY_MODEL_GAP` with written reasons. Nothing was merged into an invented 'Thuringia' or 'Anhalt' aggregate, and the Schwarzburg Sondershausen/Rudolstadt partition is recorded as unresolved rather than guessed.

## 4. Multi-polity production and split audits

- **3 scenario polities** now hold real 1756 geometry from 3 boundary features, 1,619 membership rows over a 4,553-hex extent.
- Terminology is split: **multi_polity_border_hexes = 16** (more than one polity has land in the hex) versus **cartographic_uncertainty_hexes = 916** (the hex centre sits inside the source's own positional uncertainty). These are different failures and no longer share a name.
- **Raw hex winner distortion** (2,457.0 km2 symmetric difference) and **authoritative control distortion** (8,896.4 km2, with 11,335.8 km2 explicitly unresolved) are separate artifacts. `representation_status` now describes what the authority actually covers instead of grading raw hexification.
- Topology across all 3 polity pairs: {'GAP': np.int64(2), 'WITHIN_UNCERTAINTY': np.int64(1)}, 0 overlaps, 0 source disagreements. All three territories come from the SAME sheet, so a separation below that sheet's uncertainty is not evidence of disagreement — and nothing was snapped together to hide it.

## 5. The headline finding: this source cannot resolve small estates at 6 km

- The two new polities produced **0 CONTROLLED and 185 UNRESOLVED** hexes. That is not a bug and it was not tuned away.
- Saxe-Weimar and Schwarzburg are roughly 800 and 680 km2 and fragmented. With the sheet's own placement error at 9.168 km, essentially every hex of such a territory lies inside the band where the true boundary could fall on either side. The map proves these polities exist and roughly where they are; it cannot prove which 6 km hex they own.
- The correct response is corroboration, not a smaller uncertainty number. Until a second independent source is licensed, these hexes stay UNRESOLVED.
- Separately, 4 hex(es) are won by the new neighbour but already carry a reviewed MAPGEN-012 row. The reviewed row is kept and the disagreement is published in `promotion_conflicts_mapgen013.csv`.

## 6. Images

- `central_europe_1756_multi_polity_source.png` (aspect 1.269)
- `central_europe_1756_multi_polity_continuous.png` (aspect 1.578)
- `central_europe_1756_multi_polity_hex.png` (aspect 1.504)
- `central_europe_1756_authoritative_control.png` (aspect 1.504)
- `raw_vs_authoritative_distortion.png` (aspect 1.964)
- `polity_model_refinement.png` (aspect 1.703)
- `canonical_promotion_overview.png` (aspect 2.3)

## 7. Validation

- `validation.csv` holds M13-01..M13-38; pass count 37/37.
- Determinism: the run is executed twice and the artifacts compared (see the completion report).

## 8. Known limitations — what this run does NOT claim

- **Single-source corroboration is still missing.** The Utrecht 1756 sheet remains licence-blocked and the Vaugondy HRE overview gives only coarse agreement, so every topology pair is same-source and cannot expose a genuine source disagreement.
- The promoted MAPGEN-012 rows carry the older 2.975 km classification (revision logged, not applied).
- Five enclosed regions remain deferred polity-model gaps; their hexes have no control row at all, which means UNKNOWN.
- Coverage remains a small part of Central Europe. No claim is made about the rest of Europe.
