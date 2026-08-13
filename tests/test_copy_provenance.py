# -*- coding: utf-8 -*-
"""MAPGEN-017 — map work / plate / copy identity and segment continuity.

The rules defended here: a holding record names a copy and not a source,
a later impression may not inherit an earlier represented date, sharing
an atlas is not a derivation but is still not independence, off-date
geometry needs continuity in the right direction, and a duplicated
catalogue object is not a second source.
"""
from pathlib import Path

import pandas as pd
import pytest

DATA = Path("data")
H = DATA / "historical"
SD = DATA / "scenarios" / "seven_years_war_1756_08_01"
PROD = (H / "historical_map_copy_registry.csv").exists()
prod = pytest.mark.skipif(not PROD, reason="MAPGEN-017 data not built")
DEFERRED = "DEFERRED_AFTER_BOUNDED_ATTEMPT"


# ---- semantics ----------------------------------------------------------
def _source_date_from(copy_row):
    """A copy's catalogue entry dates the COPY. Only a date read from the
    plate dates the plate, and neither dates the politics."""
    if "READ FROM THE PLATE" in copy_row.get("plate_date_basis", ""):
        return copy_row["plate_date"]
    return "UNVERIFIED"


def test_holding_record_dates_the_copy_not_the_plate():
    catalogued_only = {"plate_date": "1751",
                       "plate_date_basis": "catalogue statement"}
    from_plate = {"plate_date": "1751",
                  "plate_date_basis": "READ FROM THE PLATE: 'Avec "
                                      "Privilege. 1751'"}
    assert _source_date_from(catalogued_only) == "UNVERIFIED"
    assert _source_date_from(from_plate) == "1751"


def _represented_date(copy_state, plate_date):
    if copy_state == "LATER_IMPRESSION_OF_EARLIER_PLATE":
        raise ValueError("a later impression may not inherit the earlier "
                         "plate's represented political date")
    return "UNVERIFIED"


def test_later_impression_cannot_inherit_earlier_date():
    with pytest.raises(ValueError):
        _represented_date("LATER_IMPRESSION_OF_EARLIER_PLATE", "1751")
    assert _represented_date("EARLY_IMPRESSION_WITH_1751_PRIVILEGE",
                             "1751") == "UNVERIFIED"


def test_plate_date_never_becomes_political_date():
    assert _represented_date("EARLY_IMPRESSION_WITH_1751_PRIVILEGE",
                             "1751") != "1751"


def _lineage(same_house, derivation_evidence):
    if derivation_evidence:
        return "DERIVATIVE"
    if same_house:
        return "SHARED_ATLAS_LINEAGE"
    return "PARTIALLY_INDEPENDENT"


def test_same_atlas_is_shared_lineage_not_derivation():
    assert _lineage(True, None) == "SHARED_ATLAS_LINEAGE"
    assert _lineage(True, "plate B re-engraved from plate A") \
        == "DERIVATIVE"
    assert _lineage(False, None) == "PARTIALLY_INDEPENDENT"


def _eligible(status):
    return status not in ("DERIVATIVE", "SAME_PLATE",
                          "SHARED_ATLAS_LINEAGE")


def test_shared_lineage_still_cannot_corroborate():
    assert not _eligible("SHARED_ATLAS_LINEAGE")
    assert not _eligible("DERIVATIVE")
    assert _eligible("PARTIALLY_INDEPENDENT")
    assert _eligible("INDEPENDENT")


def _count_independent(objects):
    """Duplicate catalogue objects of one plate are one source."""
    return len({(o["plate_id"], o["impression"]) for o in objects
                if not o.get("is_reproduction")})


def test_duplicate_catalogue_objects_are_not_two_sources():
    objs = [{"plate_id": "p1", "impression": "i1"},
            {"plate_id": "p1", "impression": "i1"},
            {"plate_id": "p1", "impression": "i1",
             "is_reproduction": True}]
    assert _count_independent(objs) == 1
    objs.append({"plate_id": "p2", "impression": "i1"})
    assert _count_independent(objs) == 2


def _bridge(source_date, snapshot_date, status):
    if status != "CONTINUITY_CONFIRMED":
        raise ValueError(f"segment status {status} cannot bridge "
                         f"{source_date} geometry to {snapshot_date}")
    return True


def test_unresolved_segment_cannot_bridge_either_direction():
    for d in ("1751", "1758"):
        with pytest.raises(ValueError):
            _bridge(d, "1756-08-01", "UNRESOLVED")
        with pytest.raises(ValueError):
            _bridge(d, "1756-08-01", "BOUNDARY_CHANGED")
    assert _bridge("1751", "1756-08-01", "CONTINUITY_CONFIRMED")


def test_later_geometry_also_needs_a_bridge():
    """A ca. 1758 plate is off-date too — being closer is not being on
    the date."""
    with pytest.raises(ValueError):
        _bridge("1758", "1756-08-01", "CONTINUITY_PARTIAL")


def _uncertainty(own_holdout_m, inherited_km=None):
    if own_holdout_m is None:
        if inherited_km is not None:
            raise ValueError("a map may not inherit another map's "
                             "uncertainty")
        return None
    return round(own_holdout_m / 1000.0, 3)


def test_map_specific_uncertainty_is_not_inherited():
    with pytest.raises(ValueError):
        _uncertainty(None, inherited_km=9.168)
    assert _uncertainty(None) is None
    assert _uncertainty(2400.0) == 2.4


def _classify(distance_km, uncertainty_km):
    return ("BORDER_UNCERTAIN" if distance_km < uncertainty_km
            else "INTERIOR_CONFIDENT")


def test_large_polity_interior_survives_a_coarse_border():
    assert _classify(80.0, 12.0) == "INTERIOR_CONFIDENT"
    assert _classify(5.0, 12.0) == "BORDER_UNCERTAIN"


def _assign(region_label, audited):
    if not audited:
        raise ValueError(f"{region_label} needs its own territorial audit "
                         "before any controller is assigned")
    return audited


def test_pomerania_is_not_auto_assigned_to_brandenburg():
    with pytest.raises(ValueError):
        _assign("Pomerania", None)
    assert _assign("Brandenburg", "pol_brandenburg") == "pol_brandenburg"


def _constituent_is_polity(name, registered):
    return name in registered


def test_visible_constituent_is_not_a_polity():
    registered = {"pol_brandenburg"}
    for name in ("Altmark", "Mittelmark", "Neumark", "Uckermark",
                 "Prignitz"):
        assert not _constituent_is_polity(name, registered)


# ---- production ---------------------------------------------------------
@prod
def test_production_copy_registry_separates_work_plate_copy():
    c = pd.read_csv(H / "historical_map_copy_registry.csv",
                    keep_default_na=False, na_values=[""])
    assert len(c) >= 4
    assert c["copy_id"].is_unique
    assert c["map_work_id"].nunique() == 2
    assert {"map_work_id", "plate_id", "copy_id", "catalogued_copy_date",
            "plate_date", "issue_date", "represented_political_date",
            "copy_state", "copy_state_confidence"} <= set(c.columns)
    assert (c["represented_political_date"] == "UNVERIFIED").all()


@prod
def test_production_bnf_copy_acquired_and_dated_from_the_plate():
    c = pd.read_csv(H / "historical_map_copy_registry.csv")
    b = c[c["copy_id"] == "copy_bnf_ge_dd_2987_3790"].iloc[0]
    assert b["raster_acquired"] == "YES"
    assert b["raster_pixels"] == "7941x6135"
    assert "READ FROM THE PLATE" in b["plate_date_basis"]
    assert "PUBLIC_DOMAIN" in b["licence_status"]
    raster = Path("data/raw/historical_maps/vaugondy_brandenburg")
    assert (raster / "acquisition.json").exists()


@prod
def test_production_other_copies_are_demoted_not_used():
    c = pd.read_csv(H / "historical_map_copy_registry.csv")
    others = c[c["copy_id"] != "copy_bnf_ge_dd_2987_3790"]
    assert (others["raster_acquired"] == "NO").all()
    assert others["role"].isin(["PLATE_STATE_COMPARISON_ONLY",
                                "INDEPENDENT_GEOMETRY_SUBSTRATE_CANDIDATE"
                                ]).all()


@prod
def test_production_zollmann_is_deferred_not_exhausted():
    z = pd.read_csv(H / "zollmann_georeference_final_audit.csv")
    assert z.iloc[0]["final_status"] == DEFERRED
    reg = pd.read_csv(H / "historical_source_registry.csv")
    assert reg.loc[reg["citation_key"].str.contains("zollmann_1747"),
                   "georeference_status"].iloc[0] == DEFERRED


@prod
def test_production_segments_are_stated_individually():
    s = pd.read_csv(H / "brandenburg_boundary_segment_continuity.csv")
    assert len(s) == 6
    assert (s["continuity_status"] == "UNRESOLVED").all()
    assert s["outstanding_question"].str.len().min() > 40
    c = pd.read_csv(H / "brandenburg_temporal_continuity_audit.csv")
    assert c.iloc[0]["single_global_assertion_written"] == "NO"


@prod
def test_production_brandenburg_authorises_nothing():
    import geopandas as gpd

    reg = pd.read_csv(H / "historical_source_registry.csv")
    sids = set(reg.loc[reg["citation_key"].str.contains(
        "vaugondy_1751|lotter_c1758"), "global_source_id"])
    assert len(sids) == 2
    ev = pd.read_csv(H / "historical_evidence_assertions.csv")
    assert not (sids & set(ev["global_source_id"]))
    f = gpd.read_parquet(H / "historical_boundary_features.parquet")
    assert len(f) == 3
    assert not (sids & set(f["global_source_id"]))
    # MAPGEN-018 georeferenced the BnF sheet, so GCPs now exist. What
    # must remain true is that a transform is not an authority.
    assert len(pd.read_csv(H / "brandenburg_blha_gcps.csv")) == 0


@prod
def test_production_canonical_untouched():
    c = pd.read_csv(SD / "territorial_control.csv")
    assert len(c) == 1614
    v = c["control_status"].value_counts().to_dict()
    assert v["CONTROLLED"] == 697 and v["UNRESOLVED"] == 917


@prod
def test_production_coverage_moved_to_source_acquired():
    cov = pd.read_csv(SD / "political_coverage.csv")
    row = cov[cov["coverage_unit_id"] == "region_brandenburg_1756_pilot"]
    assert len(row) == 1
    assert row.iloc[0]["source_evidence_status"] in (
        "SOURCE_ACQUIRED", "GEOREFERENCED")
    assert row.iloc[0]["control_coverage_status"] == "UNASSESSED"
    assert (cov["control_coverage_status"] == "COMPLETE").sum() == 0
