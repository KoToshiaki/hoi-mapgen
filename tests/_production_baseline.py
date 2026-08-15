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
                     "island_hex_membership_audit.csv")


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
    """Canonical control with the island stages' rows removed."""
    return control[~control["territorial_target_id"].isin(
        island_production_hex_ids())]
