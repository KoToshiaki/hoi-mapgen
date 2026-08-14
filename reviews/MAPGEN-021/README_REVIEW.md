# MAPGEN-021 Review — territory whose frontier is a coastline

**OUTCOME: FULL.** Great Britain and Ireland main islands are historically authorised, bound to canonical hexes on exact land intersection, and promoted. Canonical control rows **1,614 → 29,578** (+27,964). Great Britain CONTROLLED **20,310**, Ireland CONTROLLED **7,520**.

Run `british_isles_1756_20260815`, on MAPGEN-020 commit `aaca77371a20f7720f3913dd111fbc2f4b78b893`.

## 1. Why this territory went through when Brandenburg did not

Three stages stalled on the same obstacle: Brandenburg's frontier is a *land* boundary that must be read off an eighteenth-century plate and digitised, and those plates draw it as a dashed wash on tinted paper. Great Britain and Ireland are bounded by **coast**, and the coast is already canonical geography. The historical work here was therefore about **authority**, not geometry — and authority lives in statute, which is legible in a way a crimson wash is not.

## 2. The rule that keeps this honest

A coastline is not a title deed. The two kinds of evidence are kept strictly apart, and the existing bundle schema enforces it:

| evidence | role | geometry_authority | political_authority |
|---|---|---|---|
| OSM coastline | `GEOMETRY_SHAPE` | **YES** | NO |
| 1707 / 1756 statutes | `POLITICAL_STATUS` | NO | **YES** |

Neither can produce a control row on its own. *"A modern coastline exists, therefore Great Britain owns it"* is not expressible in this pipeline — the bundle would fail validation.

## 3. Historical authority

| evidence | citation | effective | role |
|---|---|---|---|
| bi_1707_union_article_i | 6 Ann. c. 11 (1706 c. 11); noted in the official text as 'Chapter VIII. 5 & 6 Ann. in the Common printed Editions' | 1707-05-01 | POLITICAL_CONTROL |
| bi_1756_gb_statute_scotland | 29 Geo. 2 c. 20 (1756) | 1756 | POLITICAL_CONTROL |
| bi_1756_gb_statute_england | 29 Geo. 2 c. 37 (1756) | 1756 | POLITICAL_CONTROL |
| bi_1755_ireland_sheriffs_act | 1755 (29 Geo. 2) c. 15 [Ireland] | 1756-05-01 | POLITICAL_CONTROL |
| bi_1751_ireland_cork_infirmary | 1751 (25 Geo. 2) c. 23 [Ireland] | 1751 | ADMINISTRATIVE_SCOPE |
| bi_1801_union_temporal_cutoff | 39 & 40 Geo. 3 c. 67 (1800 c. 67) | 1801-01-01 | TEMPORAL_BOUNDARY |

**Great Britain.** Article I of the Union with Scotland Act 1706, quoted from the official text: *"the two Kingdoms of England and Scotland shall upon the First day of May … One thousand seven hundred and seven and for ever after be united into one Kingdom by the name of Great Britain"*. That is the authority for treating the whole main island as **one** actor.

Two 1756 acts of that Parliament show the authority actually running in the snapshot year — and deliberately one from each former kingdom: **29 Geo. 2 c. 20** builds a lighthouse *"in the County of Bute … in North Britain"* (the post-Union statutory term for Scotland), and **29 Geo. 2 c. 37** regulates courts baron in *"the County of York"*. One legislature, both halves of the island, same session.

**Ireland.** The **Sheriffs Act 1755** (Irish Parliament, 29 Geo. 2 c. 15), section III, from the official eISB — its operative clause binds from **1 May 1756**, three months before the snapshot, on *"no sub-sheriff or sheriffs clerk shall take any more than their legal fees"*, enforced through the Irish courts with penalties *"estreated into his Majesty's Exchequer"*. County administration actually running on the ground, not a claim.

**Ireland is not part of Great Britain in 1756.** The Union with Ireland Act 1800 takes effect **1 January 1801** — recorded precisely so it can never be back-dated. At the snapshot they are two kingdoms under one crown, and a shared crown transfers zero territory.

## 4. Landmass identity, decided by the geometry itself

| rank | ground km² | anchors | role |
|---|---|---|---|
| 0 | 218,685 | Cardiff;Edinburgh;London | MAIN_LANDMASS_GREAT_BRITAIN |
| 1 | 83,552 | Belfast;Cork;Dublin | MAIN_LANDMASS_IRELAND |
| 2 | 39,754 | Continental Europe | EXCLUDED_FROM_STAGE |

Union the canonical land parts, take connected components, order by area. Great Britain is rank 0 and contains London, Edinburgh **and** Cardiff; Ireland is rank 1 and contains Dublin, Cork **and** Belfast. The anchors answer *which island is this*, never *whose island is this*.

Measured against published figures the fit is good: 218,685 km² vs ~209,000 for Great Britain and 83,552 km² vs ~84,400 for Ireland, the excess being tidal ground the OSM coastline includes. The Isle of Man comes out at 570.5 km² against a published 572.

## 5. What was deliberately left out

| component | ground km² | reason |
|---|---|---|
| Continental Europe | 39,753.5 | NOT_BRITISH_ISLES_LANDMASS |
| Lewis and Harris | 2,149.2 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Skye | 1,636.1 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Shetland Mainland | 953.3 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Mull | 884.7 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Orkney Mainland | 580.6 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Islay | 617.6 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Anglesey | 679.8 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Isle of Man | 570.5 | HISTORICAL_AUTHORITY_NOT_GREAT_BRITAIN_1756 |
| Arran | 429.6 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Isle of Wight | 381.6 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Jersey | 120.1 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |
| Guernsey | 63.6 | OFFSHORE_COMPONENT_NOT_AUDITED_THIS_STAGE |

…and 25 further unnamed components. **Nothing was included by proximity or by name.**

**The Isle of Man** is the one that matters. In 1756 it was held by the Dukes of Atholl as a lordship outside the realm with its own Tynwald; the Revestment Act is **1765**. Back-dating it would be the exact error this project keeps guarding against, so it is assigned to neither polity.

## 6. Exact-land membership

| basis | hexes | status |
|---|---|---|
| WHOLE_LAND_SINGLE_AUTHORISED_COMPONENT | 27,830 | CONTROLLED |
| MIXED_UNAUDITED_LAND_COMPONENT | 134 | UNRESOLVED |

A hex is CONTROLLED only when essentially all of its canonical land (>98%) belongs to one authorised landmass. **134 hexes** also contain an unaudited offshore component and are held UNRESOLVED rather than quietly swept in. No centroid rule is used anywhere — a hex whose centre is at sea can still be CONTROLLED on its land, and a hex whose centre is on land can still be held back.

**0 hexes** see both landmasses. Each is resolved on exact land area with the basis recorded; there is no default winner.

## 7. Coastal sensitivity — a stated limitation

| landmass | known change since 1756 | interior affected |
|---|---|---|
| Great Britain | Fenland and Wash drainage (Lincolnshire / Cambridgeshire), Somerset Levels, local estuary reclamation on the Mersey, Tees and Humber | NO |
| Ireland | Shannon callows and turlough drainage, limited port reclamation at Dublin and Cork | NO |

The canonical geography adopts the **present-day** coastline as physical substrate. That is not a reconstruction of the 1756 shoreline, and this audit exists so the claim is never read that way. The changes are local and estuarine; they do not justify withholding the mainland interior.

## 8. Coverage

- `region_great_britain_main_island_1756` → **TERRITORY_PARTIAL**
- `region_ireland_main_island_1756` → **TERRITORY_PARTIAL**

Both are `TERRITORY_PARTIAL`, never COMPLETE. "Every hex of the main-island scope evaluated" and "this polity's whole territory resolved" are different statements, and the archipelago is unassessed.

## 9. Images

- `british_isles_landmass_identity.png` (aspect 2.153)
- `great_britain_authorised_landmass.png` (aspect 1.569)
- `ireland_authorised_landmass.png` (aspect 1.698)
- `british_isles_excluded_components.png` (aspect 1.685)
- `british_isles_hex_control.png` (aspect 1.904)
- `europe_political_progress.png` (aspect 1.703)

## 10. Validation

- `validation.csv`: M21 gates, pass count 33/33.

## 11. Known issues and MAPGEN-022

- **The archipelago is untouched.** The Hebrides, Orkney, Shetland, Anglesey, Wight, Arran, Islay and the rest are identified and excluded, not resolved. Each needs its own authority evidence.
- **The Isle of Man needs its own stage**, with Atholl lordship evidence rather than a British default.
- **The Channel Islands** are Crown dependencies with a quite different constitutional basis and were likewise excluded.
- The coastal sensitivity limitation above is carried, not closed.
- **Brandenburg remains blocked** on hand-tracing two boundary polylines; nothing in this stage changes that.
- MAPGEN-022 could either finish the British Isles offshore components (cheap, same machinery) or apply this coast-bounded pattern to another island territory such as Sicily, Sardinia or Corsica — Corsica in particular already has a contested-polity audit from MAPGEN-009R waiting to be used.
