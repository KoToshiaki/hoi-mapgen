# MAPGEN-023 Review — a batch, and a repair

**OUTCOME: FULL.** Iceland, Malta and Gozo are historically authorised, bound on exact land intersection and promoted. Canonical control rows **32,193 → 50,565** (+18,372). Iceland CONTROLLED **18,341**, Malta **12**, Gozo **3**. Validation **42/42**.

Baseline read from the committed `reviews/MAPGEN-022/summary.csv`: 32,193 rows, 31,140 CONTROLLED, 1,053 UNRESOLVED.

## 1. The repair comes first

MAPGEN-022 gave Sicily and Sardinia their islands on the authority of a source whose own description read *as reported in standard settlement histories*. That is a bibliography, not an archive.

| target | now cited | control rows changed |
|---|---|---|
| pol_sicily | Wenck, Codex iuris gentium recentissimi, tom. I (Lipsiae 1781), Acta Pacis Vindobonensis: doc. 1, Articles preliminaires signez a Vienne le 3 Octobre  | 0 |
| pol_sardinia | Archivio di Stato di Torino, Sezione Corte, Paesi, Sardegna, Economico, Cat. I, Mazzo 1, n. 17 - 'Inventaro delle Scritture del Razionale', a parchmen | 0 |

Zero rows changed, which is the point: a provenance repair that moves a boundary is not a repair.

Two more corrections. The PARES lead named in the brief could not be retrieved — `pares.mcu.es` refuses connections and the successor host 404s every catalogue path, including the ones its own pages link to. It is recorded as `ATTEMPTED_AND_UNREACHABLE` rather than cited from a summary. And the Sardinia wording that said *the Kingdom of Sardinia legally IS the island* is gone: `pol_sardinia` is the Kingdom of Sardinia (Savoy-Piedmont), and what MAPGEN-022 authorised was one component of its scope. Piedmont, Savoy and Nice are UNASSESSED — a statement about coverage, not about who the actor is.

## 2. Authority

| target | kind | date | locator |
|---|---|---|---|
| Iceland | SOVEREIGNTY_BASIS | 1662-07-28 | Lovsamling for Island I (1096-1720), Copenhagen 1853, p. 273: 'Arvehyldingseden for Island. Kopavog 28. Juli 1662'; the edition's own provenance note reads 'Afskrift i de |
| Iceland | CONTEMPORARY_IN_ISLAND_ADMINISTRATION | 1756-07-16 | TI. Skjalasafn amtmanns. II. 42A. Bref ur Mulasyslu 1724-1756. Bref ur Mulathingi 1724-1756 (Bref til konungs d. 20. jan. 1755 og alyktun syslumanna d. 16. juli 1756) |
| Iceland | CONTEMPORARY_IN_ISLAND_ADMINISTRATION | 1756-08-04 | TI. Skjalasafn amtmanns. I. 11. Brefabok 1756-1757, bls. 63-65 (Bref d. 4. agust 1756) |
| Iceland | CONTEMPORARY_IN_ISLAND_ADMINISTRATION | 1756-12-05 | TI. Skjalasafn amtmanns. I. 11. Brefabok 1756-1757, bls. 254-264 (Bref d. 5.-27. des. 1756); see also the box 'Skjol um gjafakornid 1756-1758' |
| Malta and Gozo | SOVEREIGNTY_BASIS | 1530-03-23 | The privilege enumerates the islands of Malta and Gozo, held as fiefs of the Kingdom of Sicily, together with the fortress of Tripoli; studied with Latin extracts by Alek |
| Malta and Gozo | CONTEMPORARY_IN_ISLAND_ADMINISTRATION | 1756-06-05 | Government of Malta, Government Printing Press, 'Press History', Development of Printing: Don Nicolo Capaci commissioned by Grand Master Pinto in 1756; the press opened t |
| Malta and Gozo | CONTEMPORARY_IN_ISLAND_ADMINISTRATION | 1756 | Archives of the Order of Malta, National Library of Malta: Section 2 Libri Conciliorum, AOM 73-254 (1459-1798); Section 5 Libri Bullarum, AOM 316-633 (1346-1798); Section |
| Malta and Gozo | POST_SNAPSHOT_CUTOFF | 1798-06-12 | Capitulation of the Maltese islands to the French expedition, 12 June 1798; the Order's printer stayed in post 'until the end of the French rule of the Maltese Islands in |

Iceland's title is its own act: the hereditary homage sworn at Kópavogur on 28 July 1662, printed in *Lovsamling for Island* I at p. 273 with the manuscript it was copied from. The snapshot-year evidence is an individually dated document from the amtmaður's fonds — the resolution of the sýslumenn at the Althing on **16 July 1756**, sixteen days before the snapshot.

Malta and Gozo rest on one instrument, and it is the instrument that decides the scope. Charles V's privilege of 23 March 1530 names **Malta and Gozo** and the fortress of Tripoli. Gozo is produced. **Comino, four kilometres from Gozo, is not named and is not produced.**

## 3. What was left out

| component | ground km² | reason |
|---|---|---|
| Faroe Islands;Faroe Islands (Streymoy) | 375.38 | SEPARATE_HOMAGE_SEPARATE_TERRITORY_NOT_ICELAND |
| Faroe Islands | 286.69 | SEPARATE_HOMAGE_SEPARATE_TERRITORY_NOT_ICELAND |
| Faroe Islands | 176.73 | SEPARATE_HOMAGE_SEPARATE_TERRITORY_NOT_ICELAND |
| Faroe Islands | 171.35 | SEPARATE_HOMAGE_SEPARATE_TERRITORY_NOT_ICELAND |
| Faroe Islands | 111.21 | SEPARATE_HOMAGE_SEPARATE_TERRITORY_NOT_ICELAND |
| Faroe Islands | 30.46 | SEPARATE_HOMAGE_SEPARATE_TERRITORY_NOT_ICELAND |
| Faroe Islands | 27.26 | SEPARATE_HOMAGE_SEPARATE_TERRITORY_NOT_ICELAND |
| Vestmannaeyjar (Heimaey);Vestmannaeyjar arch | 13.15 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Faroe Islands | 10.99 | SEPARATE_HOMAGE_SEPARATE_TERRITORY_NOT_ICELAND |
| Faroe Islands | 10.27 | SEPARATE_HOMAGE_SEPARATE_TERRITORY_NOT_ICELAND |
| Faroe Islands | 10.17 | SEPARATE_HOMAGE_SEPARATE_TERRITORY_NOT_ICELAND |
| Hrisey | 7.51 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Faroe Islands | 9.70 | SEPARATE_HOMAGE_SEPARATE_TERRITORY_NOT_ICELAND |
| Grimsey | 4.39 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| … and 54 further unnamed components | | all excluded |

Two of these carry the argument. The **Faroes** are under the same crown as Iceland and are still not Iceland — they swore their own homage at Tórshavn on 14 August 1662, seventeen days after Kópavogur. Same monarch, separate act, separate territory. And **Surtsey** did not exist in 1756: it rose out of the sea in 1963. It is excluded by identity, not by any threshold, which is the cleanest statement this project has of why a modern coastline is substrate and not history.

## 4. Physical change, measured where it can be

| landmass | mechanism | measured | interior affected |
|---|---|---|---|
| iceland | VOLCANIC_COASTLINE_CREATION | YES - Surtsey's area is computed f | NO |
| iceland | GLACIER_MARGIN | NO - stated as a mechanism and exp | NO |
| iceland | JOKULHLAUP_AND_SANDUR_PROGRADATION | NO - explicitly not quantified | NO |
| iceland | ERUPTION_RECORDED_AT_THE_SNAPSHOT | NO | NO |
| malta | HARBOUR_RECLAMATION_AND_FORTIFICATION | NO | NO |
| malta | TIDAL_RANGE | NO | NO |

Iceland is the hardest physical case so far: glaciers that have retreated a long way, outwash plains that prograde by kilometres, and coastline that volcanoes create outright. Only one of those is quantified here — Surtsey, because it is a component whose area the canonical geometry can be asked for. The rest are named as mechanisms and explicitly **not** used to explain any residual, and **no island interior is withheld for any of them**.

## 5. Area semantics

| landmass | ground km² | published | residual | interior rings |
|---|---|---|---|---|
| Iceland | 102,663.08 | 103,000.0 | -0.33% | 0 |
| Malta | 246.61 | 246.0 | +0.25% | 0 |
| Gozo | 66.03 | 67.0 | -1.45% | 0 |
| Sicily | 25,437.00 | 25,711.0 | -1.07% | 0 |
| Sardinia | 23,833.10 | 24,090.0 | -1.07% | 0 |

Iceland -0.33%, Malta +0.25%, Gozo -1.45%. All five islands produced so far now sit inside ±2%, with zero interior rings on every one, so inland water is excluded nowhere and cannot be the cause of any residual. Great Britain at +4.47% remains the only outlier of the seven landmasses measured.

## 6. The cost of the terrestrial-hex rule

**1,104 hexes carry authorised land — 1,427.7 km² of it — and are not produced,** because the canonical `is_terrestrial_hex` flag is a majority-land test and they fail it.

This is not new to MAPGEN-023; every earlier island stage did the same thing silently. It is reported now because Malta forced the issue: on 246 km² of island, roughly half the hexes holding Maltese land fall below the threshold. The rule is deliberately **not** changed here. `territorial_target_type` is `TERRESTRIAL_HEX`, and deciding that a one-third-land hex is a land hex would be an edit to canonical physical geography, made in the wrong stage, to make a number bigger.

## 7. Membership

| region | status | basis | hexes |
|---|---|---|---|
| iceland | CONTROLLED | WHOLE_LAND_SINGLE_AUTHORISED_COMPONENT | 18,341 |
| iceland | NOT_PRODUCED | NOT_A_CANONICAL_TERRESTRIAL_HEX | 1,089 |
| iceland | UNRESOLVED | MIXED_UNAUDITED_LAND_COMPONENT | 16 |
| malta | CONTROLLED | WHOLE_LAND_SINGLE_AUTHORISED_COMPONENT | 15 |
| malta | NOT_PRODUCED | NOT_A_CANONICAL_TERRESTRIAL_HEX | 15 |

Hexes carrying land from two authorised components: **0**. Held back as mixed unaudited land: **16**.

## 8. Scope discipline

Authorising Iceland produced **nothing** in Denmark, Norway, Schleswig, Holstein, the Faroes or Greenland. Authorising Malta produced nothing in Tripoli or the Order's European commanderies. Both are gated, not merely intended.

Coverage: Iceland `TERRITORY_PARTIAL`, Malta `TERRITORY_PARTIAL`, Gozo `TERRITORY_PARTIAL` — partial, never complete.

## 9. Figures

- `iceland_landmass_identity.png` (aspect 2.154)
- `iceland_authorised_landmass.png` (aspect 1.852)
- `iceland_hex_control.png` (aspect 2.131)
- `malta_gozo_landmass_identity.png` (aspect 2.150)
- `malta_gozo_authorised_landmass.png` (aspect 1.868)
- `malta_gozo_hex_control.png` (aspect 2.131)
- `europe_political_progress.png` (aspect 1.532)

Run `batch_islands_1756_20260815`. Every figure and CSV in this directory is reproducible from the committed data by re-running the stage.
