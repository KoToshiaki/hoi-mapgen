import numpy as np
import pytest
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin

from mapgen.raster import (aggregate_climate_mode, aggregate_elevation,
                           aggregate_landcover, mosaic, slope_and_tri)

RES = 0.000833333333333


def test_slope_and_tri_on_tilted_plane():
    # DEM increasing eastward at 0.1 m per metre, at the equator.
    transform = from_origin(0.0, 0.05, RES, RES)
    dx_m = RES * 111320.0
    cols = np.arange(60)
    dem = np.tile(0.1 * cols * dx_m, (60, 1)).astype(np.float32)
    slope, tri = slope_and_tri(dem, transform)
    expected = np.degrees(np.arctan(0.1))
    inner = slope[5:-5, 5:-5]
    assert np.allclose(inner, expected, atol=0.05)
    # Pure east-west gradient: 6 of 8 neighbours differ by d, 2 by 0.
    d = 0.1 * dx_m
    assert np.allclose(tri[5:-5, 5:-5], 0.75 * d, rtol=1e-3)


def test_aggregate_elevation_stats():
    # Two hexes: idx 0 = values 0..99, idx 1 = constant 500.
    idx = np.concatenate([np.zeros(100, np.int32), np.ones(50, np.int32)])
    dem = np.concatenate([np.arange(100, dtype=np.float32),
                          np.full(50, 500.0, np.float32)])
    slope = np.concatenate([np.full(100, 10.0), np.full(50, 2.0)]).astype(np.float32)
    tri = np.full(150, 3.0, np.float32)
    valid = np.ones(150, bool)
    out = aggregate_elevation(idx.reshape(1, -1), dem.reshape(1, -1),
                              slope.reshape(1, -1), tri.reshape(1, -1),
                              valid.reshape(1, -1), 2)
    assert out.loc[0, "elevation_mean_m"] == pytest.approx(49.5)
    assert out.loc[0, "elevation_min_m"] == 0.0
    assert out.loc[0, "elevation_max_m"] == 99.0
    assert out.loc[0, "elevation_range_m"] == 99.0
    assert out.loc[0, "slope_mean_deg"] == pytest.approx(10.0)
    assert out.loc[1, "elevation_range_m"] == 0.0
    assert out.loc[1, "slope_mean_deg"] == pytest.approx(2.0)
    assert (out["dem_nodata_fraction"] == 0.0).all()


def test_aggregate_elevation_nodata_reported():
    idx = np.zeros(100, np.int32).reshape(1, -1)
    dem = np.zeros(100, np.float32).reshape(1, -1)
    valid = np.zeros(100, bool)
    valid[:25] = True
    out = aggregate_elevation(idx, dem, dem, dem, valid.reshape(1, -1), 1)
    assert out.loc[0, "dem_nodata_fraction"] == pytest.approx(0.75)


def test_landcover_fractions():
    # Hex 0: 100% tree (10). Hex 1: 50% tree / 50% grassland (30).
    # Hex 2: mixed with nodata (0).
    idx = np.array([0] * 40 + [1] * 40 + [2] * 40, np.int32)
    lc = np.array([10] * 40 + [10] * 20 + [30] * 20 + [40] * 20 + [0] * 20,
                  np.uint8)
    out = aggregate_landcover(idx.reshape(1, -1), lc.reshape(1, -1), 3)
    assert out.loc[0, "lc_tree_fraction"] == 1.0
    assert out.loc[1, "lc_tree_fraction"] == 0.5
    assert out.loc[1, "lc_grassland_fraction"] == 0.5
    assert out.loc[2, "lc_cropland_fraction"] == 1.0  # of valid pixels
    assert out.loc[2, "landcover_nodata_fraction"] == pytest.approx(0.5)
    # Fractions of valid pixels always sum to 1 (or 0 if no valid pixels).
    frac_cols = [c for c in out.columns if c.endswith("_fraction")
                 and c != "landcover_nodata_fraction"]
    sums = out[frac_cols].sum(axis=1)
    assert np.allclose(sums, 1.0)


def test_climate_mode():
    idx = np.array([0] * 10 + [1] * 10, np.int32)
    kg = np.array([14] * 7 + [15] * 3 + [0] * 9 + [29] * 1, np.uint8)
    mode = aggregate_climate_mode(idx.reshape(1, -1), kg.reshape(1, -1), 2)
    assert mode[0] == 14          # majority Cfa
    assert mode[1] == 29          # nodata never wins


def _write_tif(path, data, west, north, res):
    transform = from_origin(west, north, res, res)
    with rasterio.open(path, "w", driver="GTiff", height=data.shape[0],
                       width=data.shape[1], count=1, dtype=data.dtype,
                       crs="EPSG:4326", transform=transform, nodata=None) as dst:
        dst.write(data, 1)


def test_mosaic_two_tiles_and_fill(tmp_path):
    res = 0.01
    a = np.full((100, 100), 1.0, np.float32)   # 0..1 deg E, 0..1 deg N
    b = np.full((100, 100), 2.0, np.float32)   # 1..2 deg E
    pa = tmp_path / "a.tif"
    pb = tmp_path / "b.tif"
    _write_tif(pa, a, 0.0, 1.0, res)
    _write_tif(pb, b, 1.0, 1.0, res)
    grid, tf = mosaic([pa, pb], (0.0, 0.0, 3.0, 1.0), res, np.float32,
                      np.nan, Resampling.nearest)
    assert grid.shape == (100, 300)
    assert np.all(grid[:, :100] == 1.0)
    assert np.all(grid[:, 100:200] == 2.0)
    assert np.all(np.isnan(grid[:, 200:]))  # uncovered area keeps fill
