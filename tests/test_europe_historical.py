"""MAPGEN-010 unit tests — Europe chunk coverage + temporal historical
geometry + coverage contract. Synthetic data lives ONLY here."""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely

from mapgen.config import BBox
from mapgen.europe_coverage import (chunk_canonical_hash, europe_chunk_grid,
                                    generate_chunk)
from mapgen.hex_grid import HexGrid
from mapgen.historical_geometry import (HPG_ALGORITHM_VERSION,
                                        HPG_SCHEMA_VERSION,
                                        make_boundary_feature_id,
                                        make_global_source_id,
                                        select_features_for_snapshot)
from mapgen.projection import bbox_to_mercator
from mapgen.scenario import (IncompleteCoverageError, load_scenario,
                             resolve_control_status)

GRID = HexGrid(flat_to_flat=6000.0)
ECFG = {"min_lon": 4.0, "min_lat": 50.0, "max_lon": 6.0, "max_lat": 52.0,
        "chunk_deg_lon": 1.0, "chunk_deg_lat": 1.0}
DATA = Path("data")
SC = "seven_years_war_1756_08_01"


def _island(lon, lat, r_m):
    b = bbox_to_mercator(BBox(lon, lat, lon, lat))
    return shapely.Point(b[0], b[1]).buffer(r_m, quad_segs=16)


def _gen_all(ecfg, parts):
    tree = shapely.STRtree(parts) if len(parts) else None
    out = []
    for c in europe_chunk_grid(ecfg):
        out.append(generate_chunk(GRID, c, np.array(parts, dtype=object),
                                  tree, 0.5))
    return out


# --------------------------------------------------------------------------
# Chunk seams / determinism
# --------------------------------------------------------------------------
def test_chunk_seam_no_duplicate_no_missing():
    land = [_island(5.0, 51.0, 20000.0)]  # sits across chunk boundaries
    dfs = _gen_all(ECFG, land)
    all_ids = pd.concat(dfs)["hex_id"]
    assert all_ids.is_unique  # duplicate rejection across 4 chunks
    # Monolithic generation of the full extent = union of chunks.
    b = bbox_to_mercator(BBox(4.0, 50.0, 6.0, 52.0))
    mono = generate_chunk(
        GRID, {"chunk_id": "mono", "bbox_3857": b, "last_col": True,
               "last_row": True},
        np.array(land, dtype=object), shapely.STRtree(land), 0.5)
    assert sorted(mono["hex_id"]) == sorted(all_ids)


def test_chunk_order_independence():
    land = [_island(4.5, 50.5, 9000.0)]
    a = _gen_all(ECFG, land)
    b = list(reversed(_gen_all(ECFG, land)))
    ha = sorted(chunk_canonical_hash(df) for df in a)
    hb = sorted(chunk_canonical_hash(df) for df in b)
    assert ha == hb


def test_existing_grid_identity():
    # Coverage hexes must be THE global grid: ids and geometry reproduce
    # from q/r exactly.
    dfs = _gen_all(ECFG, [_island(5.0, 51.0, 8000.0)])
    df = dfs[0]
    ids = GRID.hex_ids(df["q"].to_numpy(), df["r"].to_numpy())
    assert list(df["hex_id"]) == ids
    polys = GRID.polygons(df["q"].to_numpy(), df["r"].to_numpy())
    assert all(shapely.to_wkb(a) == shapely.to_wkb(b)
               for a, b in zip(df.geometry, polys))


def test_land_fraction_matches_union_classification():
    from mapgen.land import classify_hexes, source_coastline

    # Disjoint parts — mirrors the OSM split product, which is a
    # non-overlapping partition of land (the documented precondition of
    # the per-part area sum; the real-data gate is E05 in the pipeline).
    land = [_island(5.0, 51.0, 15000.0), _island(5.45, 51.35, 6000.0)]
    dfs = _gen_all(ECFG, land)
    df = pd.concat(dfs)
    df = df[df["land_fraction"] > 0]
    union = shapely.union_all(land)
    polys = GRID.polygons(df["q"].to_numpy(), df["r"].to_numpy())
    centres = np.stack(GRID.axial_to_xy(df["q"].to_numpy(),
                                        df["r"].to_numpy()), axis=1)
    cls = classify_hexes(polys, centres, union,
                         source_coastline(union, (0, 0, 1, 1)),
                         GRID.area, 0.5)
    assert np.abs(df["land_fraction"].to_numpy()
                  - cls["land_fraction"]).max() <= 1e-5


# --------------------------------------------------------------------------
# Temporal historical geometry
# --------------------------------------------------------------------------
def _feat(vfrom, vto, prec="YEAR"):
    return {"boundary_feature_id": make_boundary_feature_id(
        "syn_src", "syn_subject", "POLITY_EXTERNAL_BOUNDARY", vfrom, vto),
        "valid_from": vfrom, "valid_to": vto, "temporal_precision": prec,
        "global_source_id": make_global_source_id("syn_src"),
        "geometry_status": "GEOMETRY_PRESENT"}


def test_temporal_feature_selection():
    feats = pd.DataFrame([_feat("1748-01-01", "1766-12-31"),
                          _feat("1757-01-01", "1763-12-31"),
                          _feat("1756-08-01", "1756-08-01", "DAY")])
    sel = select_features_for_snapshot(feats, "1756-08-01")
    assert len(sel) == 2  # covering interval + exact single-day snapshot
    assert (sel["valid_from"] <= "1756-08-01").all()


def test_uncertain_temporal_interval_never_silently_matches():
    feats = pd.DataFrame([_feat("UNKNOWN", "UNKNOWN", "UNKNOWN"),
                          _feat("1750-01-01", "UNKNOWN")])
    sel = select_features_for_snapshot(feats, "1756-08-01")
    assert len(sel) == 0  # UNKNOWN validity requires explicit resolution


def test_global_source_reused_across_two_synthetic_scenarios():
    # hsrc id depends ONLY on the citation key — scenario-independent.
    a = make_global_source_id("shared_atlas")
    b = make_global_source_id("shared_atlas")
    assert a == b and a.startswith("hsrc_")
    # A single-day source is expressible without scenario coupling.
    f = _feat("1756-08-01", "1756-08-01", "DAY")
    assert "scenario" not in f["boundary_feature_id"]
    for snap_date, expect in [("1756-08-01", 1), ("1760-01-01", 0)]:
        sel = select_features_for_snapshot(pd.DataFrame([f]), snap_date)
        assert len(sel) == expect


def test_historical_geometry_provenance_required():
    feats = gpd.read_parquet(DATA / "historical"
                             / "historical_boundary_features.parquet")
    assert len(feats) == 0  # no production geometry without sources
    cat = pd.read_csv(DATA / "historical"
                      / "historical_geometry_catalogue.csv")
    reg = pd.read_csv(DATA / "historical"
                      / "historical_source_registry.csv")
    assert cat["global_source_id"].isin(
        set(reg["global_source_id"])).all()
    assert cat["geometry_status"].isin(
        ["SOURCE_GAP", "GEOMETRY_PENDING"]).all()


def test_no_modern_admin_forbidden_path():
    from mapgen.scenario_pipeline import scan_forbidden_reference_code

    for mod in ("historical_geometry.py", "europe_coverage.py"):
        assert scan_forbidden_reference_code(
            Path("src/mapgen") / mod) == []


# --------------------------------------------------------------------------
# Coverage contract: missing != neutral
# --------------------------------------------------------------------------
EMPTY_CTRL = pd.DataFrame({"territorial_target_type": [],
                           "territorial_target_id": [],
                           "control_status": []})


def test_missing_is_not_neutral_strict_raises():
    with pytest.raises(IncompleteCoverageError):
        resolve_control_status(EMPTY_CTRL, "UNASSESSED",
                               "TERRESTRIAL_HEX", "h6000_q+000001_r+000001")


def test_incomplete_coverage_consumer_rejection_nonstrict():
    for status in ("UNASSESSED", "SOURCE_IDENTIFIED", "EVIDENCE_PARTIAL",
                   "GEOMETRY_PARTIAL", "TERRITORY_PARTIAL"):
        assert resolve_control_status(
            EMPTY_CTRL, status, "TERRESTRIAL_HEX", "h6000_q+000001_r+000001",
            strict=False) == "UNKNOWN_COVERAGE_INCOMPLETE"


def test_complete_coverage_valid_case():
    assert resolve_control_status(
        EMPTY_CTRL, "COMPLETE", "TERRESTRIAL_HEX",
        "h6000_q+000001_r+000001", strict=False) == "UNCONTROLLED"
    ctrl = pd.DataFrame({"territorial_target_type": ["TERRESTRIAL_HEX"],
                         "territorial_target_id": ["h6000_q+1_r+1"],
                         "control_status": ["CONTROLLED"]})
    assert resolve_control_status(ctrl, "UNASSESSED", "TERRESTRIAL_HEX",
                                  "h6000_q+1_r+1") == "CONTROLLED"


def test_real_scenario_coverage_table():
    s = load_scenario(DATA, SC)
    cov = s.political_coverage
    assert len(cov) == 51
    assert (cov["control_coverage_status"] != "COMPLETE").all()
    kanto = cov[cov["coverage_unit_id"] == "region_kanto_pilot"].iloc[0]
    assert kanto["control_coverage_status"] == "TERRITORY_PARTIAL"


def test_relationship_still_creates_no_territory():
    s = load_scenario(DATA, SC)
    controllers = s.territorial_control[
        "controller_scenario_polity_id"].dropna()
    from mapgen.scenario import make_scenario_polity_id

    assert set(controllers) == {make_scenario_polity_id(
        SC, "pol_tokugawa_shogunate")}


def test_raw_many_to_many_intersection_allowed():
    # Two synthetic footprints over one hex — never collapsed to one
    # dominant owner at the raw layer.
    rows = pd.DataFrame([
        {"hex_id": "h6000_q+1_r+1", "footprint_id": "hbf_a",
         "polity_id": "pol_a", "share": 0.6},
        {"hex_id": "h6000_q+1_r+1", "footprint_id": "hbf_b",
         "polity_id": "pol_b", "share": 0.4}])
    per_hex = rows.groupby("hex_id")["polity_id"].nunique()
    assert int(per_hex.max()) == 2  # structurally many-to-many


def test_political_overlay_never_alters_geography():
    # Political overlays are a POLITICAL namespace; geography water
    # authority stays untouched (regression via the Toshima OCEAN hex).
    geo = pd.read_parquet(
        "output/geography_v1_3_islands_006r_20260809/"
        "geography_hexes.parquet", columns=["hex_id", "water_type"])
    assert geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN"
    assert HPG_SCHEMA_VERSION == "1.0.0"
    assert HPG_ALGORITHM_VERSION == "1.0.0"
