# MAPGEN-020 Review — two sources, and what they do not agree about

**OUTCOME: PARTIAL.** The continuity claim MAPGEN-019 left standing has been taken apart and rebuilt on archival evidence, the BLHA sheet has been georeferenced entirely on its own evidence, and **neither boundary was digitised** — so there is no cross-source comparison and **no production control**. Canonical rows 1,614 → 1,614, changed **0**.

Run `brandenburg_dual_source_20260814`, built on MAPGEN-019 commit `5a6af5790f5f6ecd2b2bb3a345ba5f77104b37c0`.

## 1. One column was doing two jobs

MAPGEN-019 reported `continuity_status = CONTINUOUS` on all six frontiers, five of them HIGH confidence. That conflated two different claims:

- **territorial/political continuity** — was this territory under the same authority in 1756? MAPGEN-019 showed this, and it survives.
- **boundary-position continuity** — may the drawn line be used as an authority at 6 km? MAPGEN-019 never showed this.

Split apart: political continuity holds on **11 of 12** subsegments; boundary-position continuity is confirmed on only **6**.

## 2. Four archival cases, opened at source

| signature | Laufzeit | classification | international |
|---|---|---|---|
| `2 Kurmaerkische Kammer F 8218` | 1748-1751 | LOCAL_CORRECTION | YES |
| `3 Neumaerkische Kammer 17143` | 1746-1757 | BOUNDARY_REGULATION_WITHOUT_TERRITORIAL_TRANSFER | NO |
| `37 Schwedt-Vierraden 116` | 1743-1752 | LOCAL_CORRECTION | NO |
| `7 Lindow/M 69` | 1704-1763 | LOCAL_CORRECTION | YES |
| `3 Neumaerkische Kammer 12085` | 1251-1775 | CLAIM_WITHOUT_EFFECTED_CHANGE | YES |

The two that matter most:

- **Saxony, `2 Kurmärkische Kammer F 8218` (1748–1751)** — an explicit *Berichtigung der Landesgrenze zu Kursachsen* at Branitz, Weißagk and Grötsch, corroborated by `17B 4948` in the Niederlausitz Oberamtsregierung's *Grenz-Sachen*, which contains Ebeling's **1737 plan of the disputed line**. Both files close in **1751 — the BnF sheet's own represented year**. Whether the sheet shows the old or the corrected line cannot be settled from the catalogue.
- **Silesia, `3 Neumärkische Kammer 17143` (1746–1757)** — the brief flagged this as highest priority because its Laufzeit straddles the whole window. Reading the classification path settles it: *Registratur des Oberforstmeisters → Amt Züllichau → **Forstgrenzen***, and both parties were Prussian after 1742. A **forest** boundary between a domain village and a lordship, not a transfer of territory. A Laufzeit is the span of a file, not the duration of a change.

The Gartz case (`37 Schwedt-Vierraden 116`, 1743–1752) is demonstrably **not** settled in the window — the same quarrel runs on through files 117, 118 and a *Regulierung* of 1770–1789.

## 3. A correction to the segment list itself

**Brandenburg did not border Swedish Pomerania in 1756.** By the Treaty of Stockholm (1720) Sweden had already ceded everything south of the Peene, so Swedish Pomerania bordered *Prussian* Pomerania and Mecklenburg — not the Margraviate. MAPGEN-019 carried it as one of six Brandenburg frontiers; it is now `NOT_APPLICABLE`, and the Gartz lead the brief filed under it in fact audits the **Uckermark / Prussian Pomerania** line, recorded as `seg_prussian_pomerania`.

## 4. The BLHA sheet, georeferenced on its own evidence

- **24 symbols** found by a global connected-component scan of the plate's own red *Urbes* fill — a different symbol convention from the BnF sheet's engraved circles. **No BnF transform was used and no BnF pixel was reused.**
- Split `15 fit / 5 model / 4 blind`, frozen before fitting.
- Model **AFFINE**; blind median **9.119 km**, p90 **12.551 km**.
- **Positional uncertainty 12.555 km**, derived from this sheet alone. The BnF figure of 17.228 km is **not** carried over.
- Two candidates were rejected during collection, not after: Luckenwalde (a paper stain) and Stendal (the symbol is on the Elbe and labelled **Tangermünde**).

### The prime meridian is the interesting part

| candidate | offset | median residual |
|---|---|---|
| EMPIRICAL_PLATE_OFFSET | -22.5284° | 12.7 km |
| FERRO_20W_OF_PARIS | -17.6628° | 328.0 km |
| GREENWICH | 0.0000° | 1,516.6 km |
| PARIS | 2.3372° | 1,672.7 km |

**This plate is not on Ferro.** Ferro leaves a 328 km median error; the plate's longitudes are internally consistent but sit about **22.53° west of Greenwich**. The BnF sheet *is* on Ferro (`FERRO_20W_OF_PARIS`). Two sheets that disagree about where longitude starts are **not copies of one another** — which is exactly the independence the cross-source design assumes, now demonstrated rather than hoped for.

## 5. Components — colour never decides the controller

| component | in Brandenburg | basis |
|---|---|---|
| Altmark | YES | LABEL_AND_TITLE |
| Mittelmark | YES | LABEL_AND_TITLE |
| Neumark | YES | LABEL_TITLE_AND_1756_EDICT |
| Uckermark | YES | LABEL_TITLE_AND_1756_EDICT |
| Prignitz | YES | LABEL |
| Ruppin | YES | LABEL |
| Duchy of Magdeburg | NO | LABEL_AND_1756_ADMINISTRATIVE_RECORD |
| Principality of Halberstadt | NO | LABEL_AND_1756_ADMINISTRATIVE_RECORD |
| Pomerania | NO | LABEL_AND_1756_ADMINISTRATIVE_RECORD |
| Cottbus (Kreis) | YES | LABEL_AND_1756_EDICT |

Magdeburg, Halberstadt and Pomerania are excluded on lettering and on the 1756 administrative record, not on colour: all three are drawn on **uncoloured** ground on the ca. 1758 sheet.

## 6. What was not done — the digitisation

**BnF Vaugondy 1751 — `NO_POLYGON_PRODUCED`**
- method: crimson boundary wash extracted as a barrier mask (R-G>28, R-B>34, R>120), dilated to close gaps, then a 4-connected flood fill seeded on the Berlin symbol inside the engraved field
- result: the fill escaped and covered 97.7% of the field
- diagnosis: the Brandenburg boundary on this plate is drawn as a DASHED crimson line with a discontinuous wash; a 7-px dilation does not close every gap, and larger dilations begin to swallow the boundary's own neighbourhood
- second attempt: all saturated colour treated as barrier, at four threshold/dilation combinations → the aged paper is itself tinted, so every threshold that closed the dashes also walled off the interior (fill collapsed to 33-362 px)

**BLHA Lotter ca.1758 — `NOT_ATTEMPTED`**
- method: not attempted: the BnF attempt was the cheaper of the two and its failure mode (discontinuous boundary rendering plus a tinted ground) applies at least as strongly here, where the Kreis washes are pastel and the neighbours carry thin coloured edge stripes of similar hue
- result: nan
- diagnosis: nan
- second attempt: nan → nan

Digitisation was stopped rather than forced. Producing a polygon by relaxing the colour rule, or by tracing one sheet from the other, would have violated the stage's own constraints; producing one by hand within the remaining budget would have put the rest of the stage at risk.

**Consequences, stated plainly:** no cross-source boundary comparison (there is nothing to measure between), no safe-interior test (it requires two buffered polygons), and **Brandenburg CONTROLLED remains 0**. Coverage stays `UNASSESSED`.

Production is **not** blocked by evidence. The 1756 political evidence holds, political continuity holds, and both sheets are now validated georeferences. It is blocked by the absence of geometry, and that is a narrower and more tractable gap than the one this stage started with.

## 7. Images

- `brandenburg_blha_observed_points.png` (aspect 2.051)
- `brandenburg_blha_georeference.png` (aspect 2.3)
- `brandenburg_boundary_continuity.png` (aspect 2.143)
- `brandenburg_components_and_geometry.png` (aspect 2.149)
- `brandenburg_dual_source_status.png` (aspect 1.613)

There is deliberately no source-geometry figure, no cross-source figure, no safe-interior figure and no hex-control figure: none of those things exist.

## 8. Validation

- `validation.csv`: M20 gates, pass count 39/39.

## 9. Known issues and what MAPGEN-021 should do

- **The digitisation is the whole remaining blocker for Brandenburg.** Both plates render their boundaries as discontinuous coloured washes on tinted paper, which defeats flood-fill segmentation. The next attempt should trace the boundary as an explicit polyline at native resolution rather than trying to fill a region, and should expect to do it by hand.
- The Saxony frontier at Branitz/Weißagk/Grötsch cannot be resolved from catalogue metadata; it needs the file itself, or Ebeling's 1737 plan, which is a digitisation request rather than a search.
- The BnF inset remains `INSET_GEOMETRY_GAP`, and the BLHA sheet covering the same territory does not close it.
- Per the brief, MAPGEN-021 leaves Brandenburg and moves to another large territory.
