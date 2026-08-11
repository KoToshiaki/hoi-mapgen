# 1756 Europe polity inclusion policy v1 (MAPGEN-009)

Basis: the political landscape of Europe on 1756-08-01 as documented in
the registered scholarly sources (see `sources.csv`) — NEVER the modern
state system. Natural Earth admin data is not an input to this catalogue.

## Evaluation universe

All of: sovereign / de-facto sovereign polities; composite monarchies and
their constituents; imperial member states; personal-union participants;
dependent territorial polities (fiefs, tributaries, vassals);
confederated polities; city-states / free cities; microstates, enclaves
and fragmented territories; territorial corporate actors where
historically necessary (Order of St John). Regions swept: British Isles,
France, Iberia, Italian states, Holy Roman Empire, Habsburg lands,
Hohenzollern lands, Poland-Lithuania, Russia, Scandinavia, Swiss
Confederacy, Dutch Republic, European Ottoman sphere, Balkans, Baltic.

## Decision rules

1. **INCLUDED** — politically distinct 1756 actor documented in the
   sources, plausibly representable in future territory data. Historical
   existence alone is NOT sufficient; the entity must be a distinct
   political actor at European scale.
2. **STRUCTURAL_ONLY** — real constitutional structure that is not a
   direct territorial owner (Holy Roman Empire, Swiss Confederacy).
   Registered as scenario polity with role STRUCTURAL_CONTAINER.
3. **AGGREGATION_CANDIDATE** — classes of many small real polities
   (free imperial cities, minor secular/ecclesiastical estates, Swiss
   cantons) tracked as classes; individual promotion possible later.
4. **SUBHEX_REQUIRED** — real polity far below 6 km hex scale
   (San Marino, Monaco, Andorra, Liechtenstein); requires the future
   historical political overlay mechanism.
5. **EXCLUDED_WITH_REASON** — recorded and rejected with reason
   (imperial knights' estates: non-state noble estates).
6. **UNRESOLVED** — evaluated, decision deliberately deferred
   (Lucca, Schleswig-Holstein condominium, contested Corsica).

Every evaluated candidate appears in
`scenario_polity_inclusion_audit.csv`, so "not in the list" always means
"not yet evaluated", never "silently dropped".

## Representation risk

`six_km_representation_risk` is assessed from the registered atlas/
monograph descriptions only; where no geographic statement was consulted
the value is UNKNOWN (areas are never guessed). SUBHEX_REQUIRED findings
are an audit result, not a failure.
