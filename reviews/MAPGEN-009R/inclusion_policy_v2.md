# 1756 Europe polity inclusion policy v2 (MAPGEN-009R)

Supersedes v1. Everything in v1 still holds EXCEPT the blanket
representability judgments, which are withdrawn.

## Four independent axes (never conflated)

1. **Political distinctness** — was it a distinct 1756 polity?
   (decides polity registration)
2. **Territorial representability** — can its territory appear on
   the 6 km grid? Anchored to the machine-computed hex plane area
   (31.176915 km2; ground = plane x cos^2(latitude)).
   SUBHEX_REQUIRED is a GEOMETRY finding that requires explicit
   extent evidence (representability_basis column) — 'microstate'
   or any political size label is NEVER a basis.
3. **Playability** — a future gameplay decision; stays UNDECIDED.
4. **Gameplay aggregation** — a view/AI concern. AGGREGATION
   class rows have no included_polity_id and can NEVER be a
   territorial controller: aggregation is a gameplay/view concern,
   never historical ownership authority. Historically distinct
   polities keep their identity in canonical territorial control.

## Status semantics (unchanged from v1 where not stated)

- STRUCTURAL_ONLY: registered structure with territorial control
  = 0, machine-gated.
- UNRESOLVED: evaluated, deliberately deferred with reason —
  reducing the count is NOT a goal.
- 'not in the list' still means 'not yet evaluated', never
  silently dropped.

## Modern data

Modern areas/boundaries are admissible ONLY as sanity checks, and
only where extent continuity is itself documented (e.g. San
Marino since the 15th c.). They are never authority for 1756.
