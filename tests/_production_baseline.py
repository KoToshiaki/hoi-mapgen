"""Shared helper: canonical control as it stood before island production.

Stages MAPGEN-021 onward add large blocks of coast-bounded territory to
canonical control. Every earlier stage's regression test asserts the state
IT left behind, so each needs to compare against canonical minus everything
produced since.

Patching each test with another explicit filter per stage does not scale -
it was already done once for the British Isles and would have to be redone
for every island stage. This helper strips whatever the island stages
produced, discovered from their membership audits rather than hard-coded,
so a new stage needs no test edits at all.
"""
from pathlib import Path

import pandas as pd

H = Path("data/historical")
# every coast-bounded stage writes one of these
MEMBERSHIP_AUDITS = ("british_isles_hex_membership_audit.csv",
                     "mediterranean_hex_membership_audit.csv",
                     "island_hex_membership_audit.csv",
                     # MAPGEN-026 is the first MAINLAND batch, so the name
                     # "island production" is now too narrow; the mechanism
                     # is the same and the list is what it strips.
                     "iberia_hex_membership_audit.csv",
                     # MAPGEN-027 widened Portugal's region, bringing a few
                     # hundred more hexes into the Iberian scope.
                     "iberia_hex_membership_audit_v2.csv",
                     # MAPGEN-028 measured the Portuguese frontier again on
                     # a five-times-larger plate and the uncertainty fell
                     # from 34.61 km to 12.33, so the interior that
                     # survives erosion is twenty times bigger.
                     "iberia_hex_membership_audit_v3.csv")


def island_production_hex_ids() -> set[str]:
    """Hex ids produced by the coast-bounded island stages."""
    ids: set[str] = set()
    for name in MEMBERSHIP_AUDITS:
        p = H / name
        if p.exists():
            ids |= set(pd.read_csv(p, keep_default_na=False,
                                   na_values=[])["hex_id"])
    return ids


def strip_island_production(control: pd.DataFrame) -> pd.DataFrame:
    """Canonical control with the island stages' rows removed.

    MAPGEN-025 added LAND_FRAGMENT rows, which are island production too
    but are keyed by fragment id rather than hex id, so the membership
    audits above cannot see them. They are dropped by target type.
    """
    out = control[~control["territorial_target_id"].isin(
        island_production_hex_ids())]
    if "territorial_target_type" in out.columns:
        out = out[out["territorial_target_type"] != "LAND_FRAGMENT"]
    return out


IBERIA_AUDITS = ("iberia_hex_membership_audit.csv",
                 "iberia_hex_membership_audit_v2.csv",
                 "iberia_hex_membership_audit_v3.csv")
IBERIA_FRAGMENTS = "iberia_land_fragment_production.csv"


def iberia_production_hex_ids() -> set[str]:
    """Hex ids MAPGEN-026 and MAPGEN-027 wrote for the Iberian mainland.

    Separate from the island set because a test that pins the row count a
    2024-era stage left behind must subtract only what came AFTER it, not
    everything coast-bounded that came before.
    """
    ids: set[str] = set()
    for name in IBERIA_AUDITS:
        p = H / name
        if p.exists():
            ids |= set(pd.read_csv(p, keep_default_na=False,
                                   na_values=[])["hex_id"])
    return ids


def iberia_production_target_ids() -> set[str]:
    """Hexes AND coastal fragments produced for the Iberian mainland."""
    ids = iberia_production_hex_ids()
    p = H / IBERIA_FRAGMENTS
    if p.exists():
        ids |= set(pd.read_csv(p, keep_default_na=False,
                               na_values=[])["land_fragment_id"])
    return ids


def strip_iberia_production(control: pd.DataFrame) -> pd.DataFrame:
    return control[~control["territorial_target_id"].isin(
        iberia_production_target_ids())]


def hex_control(control: pd.DataFrame) -> pd.DataFrame:
    """Only the whole-hex rows.

    A regression test that says "this polity still holds N hexes" means
    TERRESTRIAL_HEX rows. Fragments are additional territory of a
    different kind and must not be counted into a hex total.
    """
    if "territorial_target_type" not in control.columns:
        return control
    return control[control["territorial_target_type"] == "TERRESTRIAL_HEX"]
