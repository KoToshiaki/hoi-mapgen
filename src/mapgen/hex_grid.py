"""Uniform hex grid on the EPSG:3857 plane.

Definitions
-----------
- ``flat_to_flat``: distance between two opposite (parallel) edges of the hex,
  in metres on the Mercator plane. This is THE configured hex size.
- ``side``: edge length == circumradius.  side = flat_to_flat / sqrt(3)
- ``point_to_point``: distance between two opposite vertices == 2 * side.
- ``area``: (sqrt(3)/2) * flat_to_flat**2  (regular hexagon).

Coordinates are axial (q, r) following the Red Blob Games convention.
For pointy-top hexes:
    x = origin_x + flat_to_flat * (q + r/2)
    y = origin_y + 1.5 * side * r
For flat-top hexes the roles of the axes are mirrored.

The grid origin is a world-common constant (default 0,0 on EPSG:3857), so a
given (hex size, q, r) always maps to the same hex centre and the same hex_id,
regardless of the generated region.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely

SQRT3 = math.sqrt(3.0)

# Axial direction offsets shared by pointy- and flat-top layouts.
AXIAL_DIRECTIONS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]


def _size_token(flat_to_flat: float) -> str:
    if abs(flat_to_flat - round(flat_to_flat)) < 1e-9:
        return str(int(round(flat_to_flat)))
    return repr(flat_to_flat)


@dataclass(frozen=True)
class HexGrid:
    flat_to_flat: float
    orientation: str = "pointy"  # "pointy" or "flat"
    origin_x: float = 0.0
    origin_y: float = 0.0

    def __post_init__(self):
        if self.orientation not in ("pointy", "flat"):
            raise ValueError(f"bad orientation {self.orientation!r}")
        if self.flat_to_flat <= 0:
            raise ValueError("flat_to_flat must be positive")

    # --- scalar geometry ---------------------------------------------------
    @property
    def side(self) -> float:
        return self.flat_to_flat / SQRT3

    @property
    def point_to_point(self) -> float:
        return 2.0 * self.side

    @property
    def area(self) -> float:
        return (SQRT3 / 2.0) * self.flat_to_flat**2

    # --- axial <-> plane ---------------------------------------------------
    def axial_to_xy(self, q, r):
        """Axial (q, r) -> hex centre (x, y) metres. Vectorised."""
        q = np.asarray(q, dtype=float)
        r = np.asarray(r, dtype=float)
        s = self.side
        if self.orientation == "pointy":
            x = self.origin_x + self.flat_to_flat * (q + r / 2.0)
            y = self.origin_y + 1.5 * s * r
        else:
            x = self.origin_x + 1.5 * s * q
            y = self.origin_y + self.flat_to_flat * (r + q / 2.0)
        return x, y

    def xy_to_axial(self, x, y):
        """Plane (x, y) -> containing hex axial (q, r) ints. Vectorised."""
        x = np.asarray(x, dtype=float) - self.origin_x
        y = np.asarray(y, dtype=float) - self.origin_y
        s = self.side
        if self.orientation == "pointy":
            qf = (SQRT3 / 3.0 * x - y / 3.0) / s
            rf = (2.0 / 3.0 * y) / s
        else:
            qf = (2.0 / 3.0 * x) / s
            rf = (-x / 3.0 + SQRT3 / 3.0 * y) / s
        return _axial_round(qf, rf)

    def hex_id(self, q: int, r: int) -> str:
        return f"h{_size_token(self.flat_to_flat)}_q{q:+07d}_r{r:+07d}"

    def hex_ids(self, q, r) -> list[str]:
        tok = _size_token(self.flat_to_flat)
        return [f"h{tok}_q{qi:+07d}_r{ri:+07d}" for qi, ri in zip(q, r)]

    def neighbors(self, q: int, r: int) -> list[tuple[int, int]]:
        return [(q + dq, r + dr) for dq, dr in AXIAL_DIRECTIONS]

    # --- polygons ----------------------------------------------------------
    def _corner_angles(self) -> np.ndarray:
        if self.orientation == "pointy":
            start = -30.0
        else:
            start = 0.0
        return np.deg2rad(start + 60.0 * np.arange(6))

    def polygon(self, q: int, r: int) -> shapely.Polygon:
        return self.polygons(np.array([q]), np.array([r]))[0]

    def polygons(self, q, r) -> np.ndarray:
        """Shapely polygons for arrays of axial coordinates. Vectorised."""
        cx, cy = self.axial_to_xy(q, r)
        cx = np.atleast_1d(cx)
        cy = np.atleast_1d(cy)
        ang = self._corner_angles()
        s = self.side
        # (n, 6, 2) corner coordinates
        vx = cx[:, None] + s * np.cos(ang)[None, :]
        vy = cy[:, None] + s * np.sin(ang)[None, :]
        coords = np.stack([vx, vy], axis=-1)
        return shapely.polygons(coords)

    # --- coverage ----------------------------------------------------------
    def hexes_covering_bbox(self, min_x, min_y, max_x, max_y):
        """All hexes whose centre lies within the bbox expanded by one
        circumradius — a deterministic superset of every hex intersecting the
        bbox. Returns (q, r) int arrays sorted by (r, q)."""
        pad = self.side
        lo_x, hi_x = min_x - pad, max_x + pad
        lo_y, hi_y = min_y - pad, max_y + pad
        s = self.side
        f = self.flat_to_flat
        qs, rs = [], []
        if self.orientation == "pointy":
            r_min = math.floor((lo_y - self.origin_y) / (1.5 * s))
            r_max = math.ceil((hi_y - self.origin_y) / (1.5 * s))
            for r in range(r_min, r_max + 1):
                cy = self.origin_y + 1.5 * s * r
                if cy < lo_y or cy > hi_y:
                    continue
                q_min = math.floor((lo_x - self.origin_x) / f - r / 2.0)
                q_max = math.ceil((hi_x - self.origin_x) / f - r / 2.0)
                for q in range(q_min, q_max + 1):
                    cx = self.origin_x + f * (q + r / 2.0)
                    if lo_x <= cx <= hi_x:
                        qs.append(q)
                        rs.append(r)
        else:
            q_min = math.floor((lo_x - self.origin_x) / (1.5 * s))
            q_max = math.ceil((hi_x - self.origin_x) / (1.5 * s))
            for q in range(q_min, q_max + 1):
                cx = self.origin_x + 1.5 * s * q
                if cx < lo_x or cx > hi_x:
                    continue
                r_min = math.floor((lo_y - self.origin_y) / f - q / 2.0)
                r_max = math.ceil((hi_y - self.origin_y) / f - q / 2.0)
                for r in range(r_min, r_max + 1):
                    cy = self.origin_y + f * (r + q / 2.0)
                    if lo_y <= cy <= hi_y:
                        qs.append(q)
                        rs.append(r)
        return np.array(qs, dtype=np.int64), np.array(rs, dtype=np.int64)


def _axial_round(qf, rf):
    """Round fractional axial coordinates to the containing hex (cube rounding).
    Vectorised; returns int arrays (or ints for scalar input)."""
    qf = np.asarray(qf, dtype=float)
    rf = np.asarray(rf, dtype=float)
    sf = -qf - rf
    q = np.round(qf)
    r = np.round(rf)
    s = np.round(sf)
    dq = np.abs(q - qf)
    dr = np.abs(r - rf)
    ds = np.abs(s - sf)
    # Fix the component with the largest rounding error so q + r + s == 0.
    fix_q = (dq > dr) & (dq > ds)
    fix_r = (~fix_q) & (dr > ds)
    q = np.where(fix_q, -r - s, q)
    r = np.where(fix_r, -q - s, r)
    qi = q.astype(np.int64)
    ri = r.astype(np.int64)
    if qi.ndim == 0:
        return int(qi), int(ri)
    return qi, ri
