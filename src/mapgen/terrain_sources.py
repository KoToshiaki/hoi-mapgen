"""Terrain raster source management (MAPGEN-002).

Datasets:
- Copernicus DEM GLO-90 (90 m, 1x1 degree COG tiles, AWS open data, no auth).
  Licence: free use with attribution (Copernicus DEM Licence).
- ESA WorldCover 10 m v200 (2021, 3x3 degree COG tiles, AWS open data).
  Licence: CC BY 4.0.
- Koeppen-Geiger climate classification V2 (Beck et al. 2023, Nature Sci.
  Data), via the figshare API. Licence: CC BY 4.0.

All downloads are cached under data/raw/ and recorded (URL, licence,
download date, SHA-256) in data/source_manifest.json. Ocean-only DEM tiles do
not exist upstream; missing tiles are recorded and treated as sea level.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from .sources import sha256_of

DEM_URL_TEMPLATE = (
    "https://copernicus-dem-90m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_30_{lat}_00_{lon}_00_DEM/"
    "Copernicus_DSM_COG_30_{lat}_00_{lon}_00_DEM.tif"
)
WORLDCOVER_URL_TEMPLATE = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/"
    "v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
)
KOPPEN_FIGSHARE_FILE_ID = 61012822  # koppen_geiger_tif.zip (124.6 MB)
KOPPEN_URL = f"https://ndownloader.figshare.com/files/{KOPPEN_FIGSHARE_FILE_ID}"

TERRAIN_DATASET_INFO = {
    "copernicus_dem_glo90": {
        "source_name": "Copernicus DEM GLO-90 (90 m global DSM)",
        "source_url": "https://copernicus-dem-90m.s3.amazonaws.com/ (AWS Open Data)",
        "dataset_version": "2022_1",
        "licence": "Copernicus DEM Licence (free use with attribution: ESA / Airbus)",
    },
    "esa_worldcover_2021_v200": {
        "source_name": "ESA WorldCover 10 m 2021 v200",
        "source_url": "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/",
        "dataset_version": "v200 (2021)",
        "licence": "CC BY 4.0 (ESA WorldCover project)",
    },
    "koppen_geiger_v2": {
        "source_name": "Koeppen-Geiger climate classification V2 (Beck et al. 2023)",
        "source_url": KOPPEN_URL,
        "dataset_version": "V2 (figshare article 21789074)",
        "licence": "CC BY 4.0",
    },
}


def _lat_token(lat: int) -> str:
    return f"N{lat:02d}" if lat >= 0 else f"S{-lat:02d}"


def _lon_token(lon: int) -> str:
    return f"E{lon:03d}" if lon >= 0 else f"W{-lon:03d}"


def dem_tiles_for_bbox(min_lon, min_lat, max_lon, max_lat) -> list[str]:
    """1-degree DEM tile tokens ('N35_E139' style pair) covering a bbox."""
    tiles = []
    for lat in range(math.floor(min_lat), math.ceil(max_lat)):
        for lon in range(math.floor(min_lon), math.ceil(max_lon)):
            tiles.append(f"{_lat_token(lat)}_{_lon_token(lon)}")
    return tiles


def worldcover_tiles_for_bbox(min_lon, min_lat, max_lon, max_lat) -> list[str]:
    """3-degree WorldCover tile tokens ('N33E138') covering a bbox."""
    tiles = []
    lat0 = math.floor(min_lat / 3) * 3
    lon0 = math.floor(min_lon / 3) * 3
    lat = lat0
    while lat < max_lat:
        lon = lon0
        while lon < max_lon:
            tiles.append(f"{_lat_token(lat)}{_lon_token(lon)}")
            lon += 3
        lat += 3
    return tiles


def _download(url: str, dest: Path) -> bool:
    """Download url -> dest. Returns False on HTTP 404 (tile does not exist)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise
    tmp.replace(dest)
    return True


def ensure_dem_tiles(data_dir: Path, bbox_wgs84) -> tuple[list[Path], list[str]]:
    """Download DEM tiles covering the bbox. Returns (paths, missing_tokens).

    Missing (ocean-only) tiles are recorded in a sidecar file so later runs do
    not retry the download, keeping repeated runs deterministic and offline.
    """
    dem_dir = data_dir / "raw" / "copernicus_dem_glo90"
    dem_dir.mkdir(parents=True, exist_ok=True)
    missing_file = dem_dir / "missing_tiles.json"
    known_missing = set()
    if missing_file.exists():
        known_missing = set(json.loads(missing_file.read_text(encoding="utf-8")))

    paths, missing = [], []
    for token in dem_tiles_for_bbox(bbox_wgs84.min_x, bbox_wgs84.min_y,
                                    bbox_wgs84.max_x, bbox_wgs84.max_y):
        lat_tok, lon_tok = token.split("_")
        dest = dem_dir / f"Copernicus_DSM_COG_30_{lat_tok}_00_{lon_tok}_00_DEM.tif"
        if dest.exists():
            paths.append(dest)
            continue
        if token in known_missing:
            missing.append(token)
            continue
        url = DEM_URL_TEMPLATE.format(lat=lat_tok, lon=lon_tok)
        print(f"[terrain-sources] downloading DEM tile {token}")
        if _download(url, dest):
            paths.append(dest)
        else:
            missing.append(token)
            known_missing.add(token)
    missing_file.write_text(json.dumps(sorted(known_missing)), encoding="utf-8")
    return paths, missing


def ensure_worldcover_tiles(data_dir: Path, bbox_wgs84) -> tuple[list[Path], list[str]]:
    """Download WorldCover tiles covering the bbox. Missing tiles (open ocean)
    are tolerated the same way as DEM tiles."""
    wc_dir = data_dir / "raw" / "esa_worldcover_2021_v200"
    wc_dir.mkdir(parents=True, exist_ok=True)
    missing_file = wc_dir / "missing_tiles.json"
    known_missing = set()
    if missing_file.exists():
        known_missing = set(json.loads(missing_file.read_text(encoding="utf-8")))

    paths, missing = [], []
    for token in worldcover_tiles_for_bbox(bbox_wgs84.min_x, bbox_wgs84.min_y,
                                           bbox_wgs84.max_x, bbox_wgs84.max_y):
        dest = wc_dir / f"ESA_WorldCover_10m_2021_v200_{token}_Map.tif"
        if dest.exists():
            paths.append(dest)
            continue
        if token in known_missing:
            missing.append(token)
            continue
        print(f"[terrain-sources] downloading WorldCover tile {token}")
        if _download(WORLDCOVER_URL_TEMPLATE.format(tile=token), dest):
            paths.append(dest)
        else:
            missing.append(token)
            known_missing.add(token)
    missing_file.write_text(json.dumps(sorted(known_missing)), encoding="utf-8")
    return paths, missing


def ensure_koppen(data_dir: Path, period: str, resolution: str) -> Path:
    """Download the Koeppen-Geiger V2 zip and extract the requested GeoTIFF,
    e.g. period='1991_2020', resolution='0p00833' (1 km)."""
    kg_dir = data_dir / "raw" / "koppen_geiger_v2"
    kg_dir.mkdir(parents=True, exist_ok=True)
    zip_path = kg_dir / "koppen_geiger_tif.zip"
    if not zip_path.exists():
        print("[terrain-sources] downloading Koeppen-Geiger V2 (125 MB)")
        _download(KOPPEN_URL, zip_path)
    member = f"{period}/koppen_geiger_{resolution}.tif"
    dest = kg_dir / period / f"koppen_geiger_{resolution}.tif"
    if not dest.exists():
        with zipfile.ZipFile(zip_path) as zf:
            zf.extract(member, kg_dir)
    return dest


def record_terrain_sources(data_dir: Path, file_lists: dict[str, list[Path]]) -> dict:
    """Add/refresh terrain dataset entries (with per-file SHA-256) in
    data/source_manifest.json."""
    manifest_path = data_dir / "source_manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.setdefault("datasets", {})
    today = _dt.date.today().isoformat()
    for key, paths in file_lists.items():
        info = TERRAIN_DATASET_INFO[key]
        existing = entries.get(key, {})
        existing_files = {f["local_filename"]: f for f in existing.get("files", [])}
        files = []
        for p in sorted(paths):
            rel = str(p.relative_to(data_dir)).replace("\\", "/")
            prev = existing_files.get(f"data/{rel}")
            files.append({
                "local_filename": f"data/{rel}",
                "sha256": prev["sha256"] if prev else sha256_of(p),
                "download_date": prev["download_date"] if prev else today,
            })
        entries[key] = {**info, "files": files}
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest
