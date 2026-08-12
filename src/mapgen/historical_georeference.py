"""MAPGEN-012 — historical map georeferencing (new namespace).

Historical rasters are georeferenced from the MAP'S OWN graticule, never
from modern administrative geometry. Ground control points live in a
canonical data artifact (historical_map_gcps.csv), transforms are
compared on fit AND holdout residuals, and the most complex model is
never auto-selected.

18th-century French maps do not use Greenwich: the prime meridian is
recorded per source (this pilot's Vaugondy sheet uses the Ferro / Isle
de Fer meridian, 20 degrees west of Paris) and is applied explicitly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pyproj import Geod

HISTORICAL_MAP_GEOREFERENCE_SCHEMA_VERSION = "1.0.0"
HISTORICAL_MAP_GEOREFERENCE_ALGORITHM_VERSION = "1.0.0"

GEOD = Geod(ellps="WGS84")
TRANSFORM_MODELS = ["AFFINE", "PROJECTIVE", "POLYNOMIAL_2"]
GCP_COLUMNS = ["map_source_id", "gcp_id", "historical_label",
               "historical_x", "historical_y", "reference_lon",
               "reference_lat", "reference_type", "included_in_fit",
               "holdout", "residual_m", "notes"]
REFERENCE_TYPES = ["MAP_GRATICULE", "SETTLEMENT_MODERN_REFERENCE"]

# Prime meridians expressed as degrees EAST of Greenwich.
PRIME_MERIDIANS = {
    "GREENWICH": 0.0,
    "PARIS": 2.337229,
    # Ferro as used by French cartographers = 20 deg west of Paris.
    "FERRO_20W_OF_PARIS": 2.337229 - 20.0,
}


def to_greenwich(lon_map, prime_meridian: str) -> float:
    """Convert a longitude read off a historical map to Greenwich."""
    if prime_meridian not in PRIME_MERIDIANS:
        raise KeyError(f"unknown prime meridian {prime_meridian}")
    return np.asarray(lon_map, dtype=float) + PRIME_MERIDIANS[
        prime_meridian]


def line_intersection(p1, p2, p3, p4):
    """Intersection of segment (p1,p2) with segment (p3,p4)."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(d) < 1e-12:
        raise ValueError("degenerate graticule lines")
    a = x1 * y2 - y1 * x2
    b = x3 * y4 - y3 * x4
    return ((a * (x3 - x4) - (x1 - x2) * b) / d,
            (a * (y3 - y4) - (y1 - y2) * b) / d)


def _design(model, x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    one = np.ones_like(x)
    if model == "AFFINE":
        return np.column_stack([one, x, y])
    if model == "POLYNOMIAL_2":
        return np.column_stack([one, x, y, x * x, x * y, y * y])
    raise ValueError(model)


def fit_transform(model, px, py, lon, lat):
    """Fit a pixel -> (lon, lat) transform. Returns a dict of params."""
    px = np.asarray(px, float)
    py = np.asarray(py, float)
    lon = np.asarray(lon, float)
    lat = np.asarray(lat, float)
    if model in ("AFFINE", "POLYNOMIAL_2"):
        A = _design(model, px, py)
        if A.shape[0] < A.shape[1]:
            raise ValueError(
                f"{model} needs >= {A.shape[1]} control points, got "
                f"{A.shape[0]} — an underdetermined model is never "
                "auto-selected")
        cl, *_ = np.linalg.lstsq(A, lon, rcond=None)
        ca, *_ = np.linalg.lstsq(A, lat, rcond=None)
        return {"model": model, "lon": cl.tolist(), "lat": ca.tolist()}
    if model == "PROJECTIVE":
        n = len(px)
        if n < 4:
            raise ValueError("PROJECTIVE needs >= 4 control points")
        M = np.zeros((2 * n, 8))
        b = np.zeros(2 * n)
        for i in range(n):
            M[2 * i] = [px[i], py[i], 1, 0, 0, 0,
                        -px[i] * lon[i], -py[i] * lon[i]]
            b[2 * i] = lon[i]
            M[2 * i + 1] = [0, 0, 0, px[i], py[i], 1,
                            -px[i] * lat[i], -py[i] * lat[i]]
            b[2 * i + 1] = lat[i]
        h, *_ = np.linalg.lstsq(M, b, rcond=None)
        return {"model": model, "h": h.tolist()}
    raise ValueError(model)


def apply_transform(t, px, py):
    px = np.asarray(px, float)
    py = np.asarray(py, float)
    if t["model"] in ("AFFINE", "POLYNOMIAL_2"):
        A = _design(t["model"], px, py)
        return A @ np.asarray(t["lon"]), A @ np.asarray(t["lat"])
    if t["model"] == "PROJECTIVE":
        h = np.asarray(t["h"], float)
        den = h[6] * px + h[7] * py + 1.0
        return ((h[0] * px + h[1] * py + h[2]) / den,
                (h[3] * px + h[4] * py + h[5]) / den)
    raise ValueError(t["model"])


def residuals_m(t, px, py, lon, lat) -> np.ndarray:
    plon, plat = apply_transform(t, px, py)
    _, _, d = GEOD.inv(np.asarray(lon, float), np.asarray(lat, float),
                       np.asarray(plon), np.asarray(plat))
    return np.abs(np.asarray(d, float))


def evaluate_models(gcps: pd.DataFrame, models=None) -> pd.DataFrame:
    """Fit every candidate model on the fit set and score it on BOTH the
    fit set and the held-out points. Selection never uses fit residuals
    alone."""
    models = models or TRANSFORM_MODELS
    fit = gcps[gcps["included_in_fit"].astype(bool)]
    hold = gcps[gcps["holdout"].astype(bool)]
    rows = []
    for m in models:
        try:
            t = fit_transform(m, fit["historical_x"], fit["historical_y"],
                              fit["reference_lon"], fit["reference_lat"])
        except ValueError as exc:
            rows.append({"model": m, "status": f"NOT_FITTABLE: {exc}",
                         "n_fit": len(fit), "n_holdout": len(hold),
                         "fit_rms_m": None, "holdout_rms_m": None,
                         "fit_p95_m": None, "holdout_max_m": None})
            continue
        rf = residuals_m(t, fit["historical_x"], fit["historical_y"],
                         fit["reference_lon"], fit["reference_lat"])
        rh = residuals_m(t, hold["historical_x"], hold["historical_y"],
                         hold["reference_lon"], hold["reference_lat"]) \
            if len(hold) else np.array([])
        rows.append({
            "model": m, "status": "FITTED", "n_fit": len(fit),
            "n_holdout": len(hold),
            "fit_rms_m": float(np.sqrt((rf ** 2).mean())),
            "fit_p95_m": float(np.percentile(rf, 95)),
            "fit_max_m": float(rf.max()),
            "holdout_rms_m": float(np.sqrt((rh ** 2).mean()))
            if len(rh) else None,
            "holdout_p95_m": float(np.percentile(rh, 95))
            if len(rh) else None,
            "holdout_max_m": float(rh.max()) if len(rh) else None,
        })
    return pd.DataFrame(rows)


def select_model_stable(audit: pd.DataFrame, independent_col: str,
                        max_independent_m: float = 50_000.0) -> str:
    """Select on GEOMETRIC holdout, but disqualify any model whose
    INDEPENDENT check residual explodes.

    A polynomial can snake through the graticule nodes (best geometric
    holdout) while being wildly wrong between them; only independent
    points off the grid reveal that. Complexity is therefore never
    rewarded unless the model is also globally stable.
    """
    ok = audit[(audit["status"] == "FITTED")
               & audit["holdout_rms_m"].notna()
               & (audit[independent_col] <= max_independent_m)]
    if not len(ok):
        raise ValueError("no model is both fittable and globally stable")
    best = float(ok["holdout_rms_m"].min())
    order = {m: i for i, m in enumerate(TRANSFORM_MODELS)}
    cands = ok[ok["holdout_rms_m"] <= best * 1.10]
    return sorted(cands["model"], key=lambda m: order[m])[0]


def select_model(audit: pd.DataFrame) -> str:
    """Pick the SIMPLEST model whose holdout RMS is not materially worse
    than the best (within 10%). Complexity is never rewarded by fit
    residuals alone."""
    ok = audit[(audit["status"] == "FITTED")
               & audit["holdout_rms_m"].notna()]
    if not len(ok):
        raise ValueError("no model could be scored on holdout points")
    best = float(ok["holdout_rms_m"].min())
    order = {m: i for i, m in enumerate(TRANSFORM_MODELS)}
    cands = ok[ok["holdout_rms_m"] <= best * 1.10]
    return sorted(cands["model"], key=lambda m: order[m])[0]
