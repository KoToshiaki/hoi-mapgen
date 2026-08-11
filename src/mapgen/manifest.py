"""Run manifest: full provenance record for every generation run."""
from __future__ import annotations

import datetime as _dt
import json
import platform
import subprocess
import sys
from importlib import metadata as _im
from pathlib import Path

from . import ALGORITHM_VERSION, SCHEMA_VERSION

_PACKAGES = ["numpy", "pandas", "pyproj", "shapely", "geopandas", "pyogrio",
             "pyarrow", "matplotlib", "PyYAML", "psutil"]


def _git_commit(cwd: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
            text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except OSError:
        return None


def package_versions() -> dict[str, str]:
    versions = {}
    for pkg in _PACKAGES:
        try:
            versions[pkg] = _im.version(pkg)
        except _im.PackageNotFoundError:
            versions[pkg] = "not installed"
    return versions


def write_run_manifest(out_dir: Path, cfg, run_id: str, source_manifest: dict,
                       generation_duration_s: float, peak_memory_mb: float,
                       per_size_stats: list[dict], warnings: list[str]) -> dict:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "run_id": run_id,
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "git_commit": _git_commit(out_dir),
        "projection": {
            "source_crs": "EPSG:4326",
            "map_crs": "EPSG:3857",
        },
        "region_name": cfg.region_name,
        "bbox_wgs84": {
            "min_lon": cfg.bbox_wgs84.min_x,
            "min_lat": cfg.bbox_wgs84.min_y,
            "max_lon": cfg.bbox_wgs84.max_x,
            "max_lat": cfg.bbox_wgs84.max_y,
        },
        "hex_orientation": cfg.hex_orientation,
        "hex_flat_to_flat_m": cfg.hex_sizes_m,
        "grid_origin_x": cfg.grid_origin_x,
        "grid_origin_y": cfg.grid_origin_y,
        "land_threshold": cfg.land_threshold,
        "coast_sample_interval_m": cfg.coast_sample_interval_m,
        "margin_m": cfg.margin_m,
        "source_datasets": source_manifest.get("datasets", {}),
        "python_version": sys.version,
        "platform": platform.platform(),
        "package_versions": package_versions(),
        "generation_duration_s": generation_duration_s,
        "peak_memory_mb": peak_memory_mb,
        "per_size_stats": per_size_stats,
        "warnings": warnings,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest
