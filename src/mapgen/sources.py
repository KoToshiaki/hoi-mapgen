"""Source dataset management: download, checksum, extraction, source manifest.

Large geodata files live under data/raw/ and are NOT tracked by git; only
data/source_manifest.json (metadata + SHA-256) is tracked.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

# Natural Earth is public domain: https://www.naturalearthdata.com/about/terms-of-use/
DATASETS = {
    "ne_10m_land": {
        "source_name": "Natural Earth 1:10m Physical Vectors - Land",
        "url": "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip",
        "version": "5.1.1",
        "licence": "Public Domain (Natural Earth terms of use)",
        "filename": "ne_10m_land.zip",
        "shapefile": "ne_10m_land.shp",
    },
    "ne_10m_populated_places": {
        "source_name": "Natural Earth 1:10m Cultural Vectors - Populated Places",
        "url": "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_populated_places.zip",
        "version": "5.1.1",
        "licence": "Public Domain (Natural Earth terms of use)",
        "filename": "ne_10m_populated_places.zip",
        "shapefile": "ne_10m_populated_places.shp",
    },
    # ---- MAPGEN-007 reference human geography (REFERENCE, not gameplay) ----
    "ne_10m_admin_0_countries": {
        "source_name": "Natural Earth 1:10m Cultural Vectors - Admin 0 Countries",
        "url": "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_countries.zip",
        "version": "5.1.1",
        "licence": "Public Domain (Natural Earth terms of use)",
        "filename": "ne_10m_admin_0_countries.zip",
        "shapefile": "ne_10m_admin_0_countries.shp",
    },
    "ne_10m_admin_0_map_units": {
        "source_name": "Natural Earth 1:10m Cultural Vectors - Admin 0 Map Units",
        "url": "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_map_units.zip",
        "version": "5.1.1",
        "licence": "Public Domain (Natural Earth terms of use)",
        "filename": "ne_10m_admin_0_map_units.zip",
        "shapefile": "ne_10m_admin_0_map_units.shp",
    },
    "ne_10m_admin_1_states_provinces": {
        "source_name": "Natural Earth 1:10m Cultural Vectors - Admin 1 States and Provinces",
        "url": "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_1_states_provinces.zip",
        "version": "5.1.1",
        "licence": "Public Domain (Natural Earth terms of use)",
        "filename": "ne_10m_admin_1_states_provinces.zip",
        "shapefile": "ne_10m_admin_1_states_provinces.shp",
    },
    # NOTE: the historical "breakaway_disputed_areas" file name 404s on the
    # NE S3 mirror; the current dataset name is admin_0_disputed_areas.
    "ne_10m_admin_0_disputed_areas": {
        "source_name": "Natural Earth 1:10m Cultural Vectors - Admin 0 Breakaway, Disputed Areas",
        "url": "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_disputed_areas.zip",
        "version": "5.1.1",
        "licence": "Public Domain (Natural Earth terms of use)",
        "filename": "ne_10m_admin_0_disputed_areas.zip",
        "shapefile": "ne_10m_admin_0_disputed_areas.shp",
    },
    "ne_10m_ports": {
        "source_name": "Natural Earth 1:10m Cultural Vectors - Ports",
        "url": "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_ports.zip",
        "version": "5.0.0",
        "licence": "Public Domain (Natural Earth terms of use)",
        "filename": "ne_10m_ports.zip",
        "shapefile": "ne_10m_ports.shp",
    },
    # GeoNames is used for cities instead of Natural Earth populated places:
    # NE 10m only carries ~prefecture-capital density (no Chiba, Funabashi,
    # Ichikawa, ...), which makes the city-collision metric meaningless.
    # cities15000 = every place with population >= 15,000, with population.
    "geonames_cities15000": {
        "source_name": "GeoNames cities15000 (all cities with population >= 15000)",
        "url": "https://download.geonames.org/export/dump/cities15000.zip",
        "version": "daily dump (see download_date)",
        "licence": "CC BY 4.0 (https://www.geonames.org/about.html)",
        "filename": "cities15000.zip",
        "shapefile": "cities15000.txt",
    },
}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_dataset(key: str, data_dir: Path) -> Path:
    """Ensure a dataset is downloaded and extracted. Returns path to the .shp."""
    spec = DATASETS[key]
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = raw_dir / spec["filename"]
    if not zip_path.exists():
        print(f"[sources] downloading {spec['url']}")
        urllib.request.urlretrieve(spec["url"], zip_path)
    extract_dir = raw_dir / key
    shp_path = extract_dir / spec["shapefile"]
    if not shp_path.exists():
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
    return shp_path


def update_source_manifest(data_dir: Path, keys: list[str]) -> dict:
    """Write/refresh data/source_manifest.json for the given datasets."""
    manifest_path = data_dir / "source_manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.setdefault("datasets", {})
    for key in keys:
        spec = DATASETS[key]
        zip_path = data_dir / "raw" / spec["filename"]
        existing = entries.get(key, {})
        entries[key] = {
            "source_name": spec["source_name"],
            "source_url": spec["url"],
            "dataset_version": spec["version"],
            "licence": spec["licence"],
            "download_date": existing.get(
                "download_date", _dt.date.today().isoformat()
            ),
            "sha256": sha256_of(zip_path),
            "local_filename": f"data/raw/{spec['filename']}",
        }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest
