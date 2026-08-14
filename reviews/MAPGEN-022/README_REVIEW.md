# MAPGEN-022 Review — the same method, two harder islands

**OUTCOME: FULL.** Sicily and Sardinia main islands are historically authorised, bound on exact land intersection and promoted. Canonical control rows **29,578 → 32,193** (+2,615). Sicily CONTROLLED **1,305**, Sardinia CONTROLLED **1,308**.

Run `mediterranean_1756_20260815`, on MAPGEN-021 commit `9ad43bf966469109563d4823144146149a027726`. The baseline is read from **reviews/MAPGEN-021/summary.csv (committed)**, not from a remembered figure.

## 1. Two traps the British Isles did not contain

**Name inference.** In 1720 Savoy swapped *Sicily* for *Sardinia* with Austria; in 1738 Austria passed Naples and Sicily to a Bourbon. The same two islands changed hands between the same two powers inside eighteen years. "The Kingdom of Sardinia must hold Sardinia" is precisely the reasoning that would have put the wrong island under the wrong crown a generation earlier, so each island is authorised by its own treaty and its own surviving administration.

**Composite scope.** Before the *fusione perfetta* of 1847 the Kingdom of Sardinia legally **is** the island — Piedmont, Savoy and Nice are a separate holding of the same dynasty. Producing the mainland from this actor would be the 1847 state back-dated ninety years. Sicily has the mirror case: Naples shares its monarch in 1756 but stays a separate kingdom until **1816**.

## 2. Historical authority

| island | kind | citation | in force at snapshot |
|---|---|---|---|
| Sicily | SOVEREIGNTY_BASIS | Treaty of Vienna (18 November 1738), settlement of the War of the Polish Success | YES |
| Sicily | CONTEMPORARY_IN_ISLAND_ADMINISTRATION | Governing institutions of the Kingdom of Sicily in continuous operation across 1 | YES |
| Sardinia | SOVEREIGNTY_BASIS | Treaty of The Hague (17 February 1720), concluding the War of the Quadruple Alli | YES |
| Sardinia | CONTEMPORARY_IN_ISLAND_ADMINISTRATION | Savoyard government institutions of the Kingdom of Sardinia in continuous operat | YES |
| Sardinia | CONTEMPORARY_IN_ISLAND_LEGISLATION | Editti, pregoni ed altri provvedimenti emanati pel Regno di Sardegna dappoiche'  | YES |
| Sicily | POST_SNAPSHOT_CUTOFF | Creation of the Kingdom of the Two Sicilies | NO |
| Sardinia | POST_SNAPSHOT_CUTOFF | Fusione perfetta - the 1847 act of Charles Albert merging the island of Sardinia | NO |
| Sicily | POST_SNAPSHOT_CUTOFF | Charles of Bourbon succeeds to the Spanish throne and cedes Naples and Sicily to | NO |

**Sicily** — Treaty of Vienna, 18 Nov 1738: Austria cedes Naples and Sicily to Don Carlos for Parma and Piacenza. Government on the ground is evidenced by the island's own organs in the *Guida generale degli Archivi di Stato* (Archivio di Stato di Palermo): **Real segreteria (1611–1826)**, **Deputazione del regno (1547–1819)** — the standing organ of the Sicilian Parliament — plus the deputations for roads (1731–1819), public health (1731–1818) and hospitals (1750–1818). Every range contains 1756-08-01.

**Sardinia** — Treaty of The Hague, 17 Feb 1720: Victor Amadeus II cedes Sicily and receives Sardinia. The institutional fingerprint is sharp: SIAS (Archivio di Stato di Cagliari) records the **Segreteria di Stato e di Guerra del Regno di Sardegna as 1720–1848** — a new apparatus beginning exactly when sovereignty changed and still running at the snapshot — beside the **Reale udienza (1564–1868)** and the **Antico Archivio Regio (1323–1832)**.

Three post-snapshot cutoffs are recorded and marked not in force: **1759** (Charles leaves for Spain), **1816** (Two Sicilies), **1847** (fusione perfetta).

## 3. Landmass identity — where size would have failed

| rank | ground km² | identity | role |
|---|---|---|---|
| 0 | 139,626 | North Africa (Tunisia/Algeria) | EXCLUDED_FROM_STAGE |
| 1 | 101,262 | Italian mainland | EXCLUDED_FROM_STAGE |
| 2 | 23,833 | Cagliari;Oristano;Sassari | MAIN_LANDMASS_SARDINIA |
| 3 | 25,437 | Catania;Messina;Palermo | MAIN_LANDMASS_SICILY |

Both targets rank **below** North Africa and the Italian mainland. A rule that took the largest components would have produced Tunisia and Italy; the anchors are what identify the islands, and they are identity QA only, never an ownership source.

## 4. What was left out

| component | ground km² | reason |
|---|---|---|
| North Africa (Tunisia/Algeria) | 139,625.5 | NOT_AN_ISLAND_IN_SCOPE_MAINLAND_LANDMASS |
| Italian mainland | 101,261.5 | NOT_AN_ISLAND_IN_SCOPE_MAINLAND_LANDMASS |
| Corsica | 8,719.8 | SEPARATE_CONTESTED_POLITY_NOT_SARDINIA |
| Malta | 246.6 | HOSPITALLER_MALTA_NOT_SICILY_1756 |
| Sant'Antioco | 110.8 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Pantelleria | 83.7 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Gozo | 66.0 | HOSPITALLER_MALTA_NOT_SICILY_1756 |
| Asinara | 51.3 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| San Pietro | 50.9 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Lipari (Aeolian) | 37.1 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Salina (Aeolian) | 26.1 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| La Maddalena | 19.7 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Favignana (Egadi) | 19.9 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Ustica | 8.1 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |

…and 29 further unnamed components.

**Corsica** is the one to be careful with. In 1756 it is contested between Genoa and Paoli's republic, and MAPGEN-009R already registered `pol_corsican_republic` with a de-facto/de-jure contested audit. That audit is left exactly as it was. Corsica is **not** given to Sardinia on grounds of proximity, shared sea, or the French annexation of 1768. **Malta** is held by the Order of St John under nominal Sicilian suzerainty and is likewise excluded.

## 5. Area semantics — correcting MAPGEN-021

| landmass | ground km² | published | diff | interior rings |
|---|---|---|---|---|
| Sicily | 25,437.0 | 25,711 | -1.07% | 0 |
| Sardinia | 23,833.1 | 24,090 | -1.07% | 0 |

MAPGEN-021 said the canonical outline ran large because of "tidal ground", without measuring anything. Measured, that does not hold: Sicily **-1.07%**, Sardinia **-1.07%** and Ireland −1.03% all sit about one per cent **below** their published figures. Great Britain at **+4.47%** is the outlier, not the rule.

What *is* measured: the Mercator inflation matches 1/cos²(lat) to four decimals, and **no landmass has interior rings**, so inland water is not excluded from any of these areas. The intertidal mechanism is named but explicitly **not quantified**, and therefore not used to explain the residual. This is QA — no control row depends on it.

## 6. Membership

| basis | hexes | status |
|---|---|---|
| WHOLE_LAND_SINGLE_AUTHORISED_COMPONENT | 2,613 | CONTROLLED |
| MIXED_UNAUDITED_LAND_COMPONENT | 2 | UNRESOLVED |

The MAPGEN-021 contract is reused unchanged, including its 2% unaudited-land threshold, which was audited against this data before reuse rather than re-tuned. **2 hexes** carry unaudited offshore land beside a main island and are held UNRESOLVED. No centroid rule anywhere.

**0 hexes** see both islands — the expected answer for landmasses 200 km apart, and a non-zero count would have signalled a component error.

## 7. Geometry storage

| landmass | coordinates | WKB bytes | simplified | WKT copy |
|---|---|---|---|---|
| Sicily | 56,224 | 899,597 | NO | NO |
| Sardinia | 62,479 | 999,677 | NO | NO |
| Great Britain | 909,712 | 14,555,405 | NO | NO |
| Ireland | 288,871 | 4,621,949 | NO | NO |

Geometry lives in exactly one place — the feature parquet. It is **not** simplified and **not** duplicated as WKT into any CSV: shrinking a file must never change a membership number. The Mediterranean islands are cheap (Sicily 56k coordinates, Sardinia 62k) next to Great Britain's 910k.

## 8. Coverage

- `region_sicily_main_island_1756` → **TERRITORY_PARTIAL**
- `region_sardinia_main_island_1756` → **TERRITORY_PARTIAL**

Both `TERRITORY_PARTIAL`, never COMPLETE — the archipelagos are unassessed and, for Sardinia, so is the entire mainland composite holding.

## 9. Images

- `mediterranean_landmass_identity.png` (aspect 2.153)
- `sicily_authorised_landmass.png` (aspect 1.847)
- `sardinia_authorised_landmass.png` (aspect 1.603)
- `mediterranean_excluded_components.png` (aspect 1.592)
- `mediterranean_hex_control.png` (aspect 2.157)
- `europe_political_progress.png` (aspect 1.613)

## 10. Validation

- `validation.csv`: M22 gates, pass count 38/38.

## 11. Known issues and MAPGEN-023

- **Contemporary evidence is institutional, not a single dated act.** For both islands the in-island evidence is the surviving record series of their own governing organs, cited by fondo and date range. That is strong for continuity of government but weaker than the Sheriffs Act 1755 was for Ireland, where a clause operative from a named day could be quoted. A stage with archive access could pin an individual 1756 *prammatica* or *pregone*.
- The Sardinian **Editti, pregoni** compilation (Cagliari 1775) is recorded as supporting evidence only: its scope covers 1720–1774 but no single 1756 edict was read from it.
- **Corsica is now the obvious next target** and the most interesting one in the catalogue: it is the only registered polity with a de-facto/de-jure contested audit, so it would exercise machinery no stage has used yet — two claimants over one coast-bounded island.
- Alternatively the offshore components of all four produced islands could be swept up in one stage, since the machinery and the exclusion audits already exist.
- **Brandenburg remains blocked** on hand-tracing two boundary polylines; nothing here changes that.
