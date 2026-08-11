"""Configuration loading for mapgen."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class BBox:
    """Axis-aligned bounding box. Units depend on context (degrees or metres)."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @classmethod
    def from_lonlat_dict(cls, d: dict) -> "BBox":
        return cls(
            min_x=float(d["min_lon"]),
            min_y=float(d["min_lat"]),
            max_x=float(d["max_lon"]),
            max_y=float(d["max_lat"]),
        )


@dataclass
class MapgenConfig:
    region_name: str
    bbox_wgs84: BBox
    hex_sizes_m: list[float]
    hex_orientation: str
    grid_origin_x: float
    grid_origin_y: float
    land_threshold: float
    coast_sample_interval_m: float
    margin_m: float
    label_min_population: int
    population_thresholds: list[int]
    zooms: dict[str, BBox]
    data_dir: Path
    output_dir: Path
    config_path: Path | None = None
    raw: dict = field(default_factory=dict)


def load_config(path: str | Path) -> MapgenConfig:
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    orientation = raw.get("hex_orientation", "pointy")
    if orientation not in ("pointy", "flat"):
        raise ValueError(f"hex_orientation must be 'pointy' or 'flat', got {orientation!r}")

    # data/output dirs are resolved relative to the project root (parent of config/).
    root = path.resolve().parent.parent

    return MapgenConfig(
        region_name=raw.get("region_name", "region"),
        bbox_wgs84=BBox.from_lonlat_dict(raw["bbox_wgs84"]),
        hex_sizes_m=[float(v) for v in raw["hex_sizes_m"]],
        hex_orientation=orientation,
        grid_origin_x=float(raw.get("grid_origin_x", 0.0)),
        grid_origin_y=float(raw.get("grid_origin_y", 0.0)),
        land_threshold=float(raw.get("land_threshold", 0.5)),
        coast_sample_interval_m=float(raw.get("coast_sample_interval_m", 1000.0)),
        margin_m=float(raw.get("margin_m", 15000.0)),
        label_min_population=int(raw.get("label_min_population", 200000)),
        population_thresholds=[int(v) for v in raw.get("population_thresholds", [])],
        zooms={
            name: BBox.from_lonlat_dict(d) for name, d in (raw.get("zooms") or {}).items()
        },
        data_dir=root / raw.get("data_dir", "data"),
        output_dir=root / raw.get("output_dir", "output"),
        config_path=path.resolve(),
        raw=raw,
    )
