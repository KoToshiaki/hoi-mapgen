"""Hydrography source management (MAPGEN-003).

Datasets:
- OSM land polygons (osmdata.openstreetmap.de, split, pre-projected EPSG:3857).
  Licence: ODbL 1.0 (c) OpenStreetMap contributors. OSM-derived data is kept
  strictly under data/raw/osm_land_polygons/ and flagged ``odbl: true`` in the
  source manifest so the OSM-derived database remains separable from code,
  game logic and assets. Final distribution decisions are deferred.
- HydroLAKES v1.0 (lake polygons, global).
- HydroRIVERS v1.0 (global river network with topology, discharge, orders),
  downloaded per continent.
  HydroLAKES/HydroRIVERS licence: HydroSHEDS Licence Agreement v1 (free use
  incl. commercial, attribution required: Lehner et al.).
"""
from __future__ import annotations

import datetime as _dt
import json
import zipfile
from pathlib import Path

from .sources import sha256_of

HYDRO_DATASETS = {
    "osm_land_polygons": {
        "source_name": "OSM land polygons (split, EPSG:3857)",
        "source_url": "https://osmdata.openstreetmap.de/download/land-polygons-split-3857.zip",
        "dataset_version": "daily build (see download_date)",
        "licence": "ODbL 1.0",
        "attribution": "(c) OpenStreetMap contributors",
        "odbl": True,
        "filename": "land-polygons-split-3857.zip",
        "member_glob": "land-polygons-split-3857/land_polygons.shp",
    },
    "hydrolakes": {
        "source_name": "HydroLAKES v1.0 polygons",
        "source_url": "https://data.hydrosheds.org/file/hydrolakes/HydroLAKES_polys_v10_shp.zip",
        "dataset_version": "v1.0",
        "licence": "HydroSHEDS Licence Agreement v1 (attribution: Messager et al. 2016)",
        "odbl": False,
        "filename": "HydroLAKES_polys_v10_shp.zip",
        "member_glob": "HydroLAKES_polys_v10_shp/HydroLAKES_polys_v10.shp",
    },
    "hydrorivers": {
        "source_name": "HydroRIVERS v1.0 (per continent)",
        "source_url": "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_{cont}_shp.zip",
        "dataset_version": "v1.0",
        "licence": "HydroSHEDS Licence Agreement v1 (attribution: Lehner & Grill 2013)",
        "odbl": False,
        "filename": "HydroRIVERS_v10_{cont}_shp.zip",
        "member_glob": "HydroRIVERS_v10_{cont}_shp/HydroRIVERS_v10_{cont}.shp",
    },
}


def _extract_all(zip_path: Path, dest_dir: Path, marker_member: str) -> Path:
    """Extract a zip if its marker member is not yet present."""
    target = dest_dir / marker_member
    if not target.exists():
        print(f"[hydro-sources] extracting {zip_path.name}")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest_dir)
    return target


def osm_land_shp(data_dir: Path) -> Path:
    d = data_dir / "raw" / "osm_land_polygons"
    spec = HYDRO_DATASETS["osm_land_polygons"]
    return _extract_all(d / spec["filename"], d, spec["member_glob"])


def hydrolakes_shp(data_dir: Path) -> Path:
    d = data_dir / "raw" / "hydrolakes"
    spec = HYDRO_DATASETS["hydrolakes"]
    return _extract_all(d / spec["filename"], d, spec["member_glob"])


def hydrorivers_shp(data_dir: Path, continent: str) -> Path:
    d = data_dir / "raw" / "hydrorivers"
    spec = HYDRO_DATASETS["hydrorivers"]
    return _extract_all(
        d / spec["filename"].format(cont=continent), d,
        spec["member_glob"].format(cont=continent),
    )


def record_hydro_sources(data_dir: Path, continents: list[str]) -> dict:
    manifest_path = data_dir / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) \
        if manifest_path.exists() else {}
    entries = manifest.setdefault("datasets", {})
    today = _dt.date.today().isoformat()

    def _entry(key: str, zip_paths: list[Path]) -> None:
        spec = HYDRO_DATASETS[key]
        existing = entries.get(key, {})
        prev = {f["local_filename"]: f for f in existing.get("files", [])}
        files = []
        for p in zip_paths:
            rel = "data/" + str(p.relative_to(data_dir)).replace("\\", "/")
            old = prev.get(rel)
            files.append({
                "local_filename": rel,
                "sha256": old["sha256"] if old else sha256_of(p),
                "download_date": old["download_date"] if old else today,
            })
        entries[key] = {
            k: v for k, v in spec.items()
            if k not in ("filename", "member_glob")
        } | {"files": files}

    _entry("osm_land_polygons",
           [data_dir / "raw" / "osm_land_polygons" / "land-polygons-split-3857.zip"])
    _entry("hydrolakes",
           [data_dir / "raw" / "hydrolakes" / "HydroLAKES_polys_v10_shp.zip"])
    _entry("hydrorivers",
           [data_dir / "raw" / "hydrorivers" / f"HydroRIVERS_v10_{c}_shp.zip"
            for c in continents])
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest
