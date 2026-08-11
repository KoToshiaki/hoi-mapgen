# MAPGEN-011R Review — Historical Production Gate + Land-Area Hex Binding Semantics Hardening

**HISTORICAL GEOMETRY IS SOURCE-DERIVED, NOT GENERATED FROM MODERN ADMINISTRATION.**
**MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER NEUTRAL.**

Run `historical_pilot_r_20260812`. MAPGEN-011's historical content is FROZEN (HALC v15.0 acquisition, 1500-only finding, SOURCE_GAP, zero production rows, byte-identical control/claims). This stage fixes implementation semantics only.

## Fixes

- **Fake-1756 exploit closed**: authority now lives in registered EVIDENCE ASSERTIONS (hev_), not sources. A feature must reference a political assertion whose subject matches and whose validity explicitly covers 1756-08-01; HALC's only assertion is GEOMETRIC_SUBSTRATE_ONLY (1500, political authority NO), so the 'HALC as its own evidence + hand-typed 1756 validity' path is rejected — and a negative fixture executes EVERY run so the gate can never go vacuous (R02/R03). hpg schema 1.1.0 → **1.2.0** (additive).
- **Exact-land binding**: numerators and denominators are now the exact hex ∩ OSM-coast-authority land geometry — sea area never counts as political land, land_fraction approximations are gone, share>1 raises instead of clipping. hpg algorithm 1.0.0 → **1.1.0**.
- **Same-polity union**: multi-feature coverage of one hex is unioned before the winner decision (no double counting); feature-level provenance moves to a separate `historical_hex_feature_membership` table.
- **Audit split**: membership conservation (geometry bookkeeping) vs winner hexification distortion (real omission/commission via geometry symmetric difference) — a 49/51 border loss is now visible instead of hiding behind a membership sum.
- **Provenance mandatory**: generated control rows and overlay candidates require source + evidence + feature ids (None-provenance raises). Claims still never derive from control.

## Production state (unchanged, honest)

- boundary features 0 / snapshot features 0 / membership 0 / new control 0. SOURCE_GAP is NOT resolved with synthetic data; the 3 registered real assertions are work-level (HALC substrate, Corsica existence, San Marino continuity) and none authorises production geometry.

## Images

- `source_vs_evidence_assertion_contract.png` (aspect 1.685)
- `exact_land_binding_semantics.png` (aspect 0.835)
- `membership_vs_winner_distortion.png` (aspect 1.652)

- The land-binding and winner-distortion figures are labelled SYNTHETIC SEMANTICS TEST — they demonstrate the algorithms, not production data.

## Validation

- `validation.csv` covers R01-R19 (frozen 011 outcome, non-vacuous exploit rejection + acceptance, exact-land, union, many-to-many, winner distortion, provenance, regressions, AST scans, upstream immutability). Pass count in `summary.csv`.
