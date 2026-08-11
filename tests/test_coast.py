import numpy as np
import shapely

from mapgen.coastline import coastline_errors, sample_coastline


def test_sampling_interval_and_bbox_filter():
    line = shapely.LineString([(0, 0), (10000, 0)])
    pts = sample_coastline(line, 1000.0, (0, -100, 10000, 100))
    # Samples at 0, 1000, ..., 9000 (arange excludes the end point).
    assert len(pts) == 10
    assert np.allclose(np.diff(pts[:, 0]), 1000.0)
    # bbox filter removes points outside the core bbox.
    pts2 = sample_coastline(line, 1000.0, (2500, -100, 6500, 100))
    assert len(pts2) == 4
    assert pts2[:, 0].min() >= 2500 and pts2[:, 0].max() <= 6500


def test_known_error_against_straight_generated_coast():
    # Source coast at y = 0; generated coast at y = 700 (constant known error).
    source = shapely.LineString([(0, 0), (10000, 0)])
    generated = shapely.LineString([(-1e6, 700.0), (1e6, 700.0)])
    pts = sample_coastline(source, 500.0, (0, -1, 10000, 1))
    df = coastline_errors(pts, generated)
    assert len(df) == len(pts)
    assert np.allclose(df["coast_error_m"], 700.0)
    assert np.allclose(df["nearest_generated_coast_y_m"], 700.0)
    assert np.allclose(df["nearest_generated_coast_x_m"], df["source_x_m"])


def test_zero_error_when_coasts_match():
    source = shapely.LineString([(0, 0), (10000, 0)])
    df = coastline_errors(sample_coastline(source, 250.0, (0, -1, 10000, 1)), source)
    assert np.allclose(df["coast_error_m"], 0.0, atol=1e-9)
