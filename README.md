# hoi-mapgen

Historical grand-strategy map generation and scenario geography pipeline.

Real geography and curated historical sources are converted **offline** into
deterministic, machine-validated game data; the game engine performs no GIS
at runtime.

```
real geography (WGS84)
   ↓ EPSG:3857 (Web Mercator, world-fixed origin)
canonical uniform 6 km hex grid  (hex_id = h6000_q±NNNNNN_r±NNNNNN)
   ↓ terrain / hydrology / islands / reference & historical layers
game data (Parquet / CSV / GeoParquet / PNG)  +  machine-checked validation
```

## Core semantics (non-negotiable)

- **REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP.**
  Modern administrative boundaries (Natural Earth etc.) are reference/QA
  data only and must never be used to generate historical political
  ownership, polities or boundaries.
- **SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY WITHIN ITS
  SCENARIO SNAPSHOT** — and only where the political coverage contract says
  so: a missing control row under incomplete coverage means **UNKNOWN,
  never neutral territory**.
- Historical geometry is temporal and scenario-independent: sources →
  dated boundary features → snapshot selection per scenario. Constitutional
  relationships (personal unions, imperial membership, composite
  monarchies) never create territorial control automatically.
- Every historical assertion carries provenance (source registry +
  evidence with locators); unknown values stay UNKNOWN instead of being
  guessed.

## Current state

- **Active scenario:** `seven_years_war_1756_08_01` (snapshot 1756-08-01,
  data_status FOUNDATION_ONLY — 66 polities / 46 constitutional
  relationships catalogued; world political geography not yet built).
- **Latest completed stage:** MAPGEN-010 — Europe canonical hex coverage
  (1,885,422 hexes in 50 deterministic chunks on the existing global grid)
  + temporal historical political geometry foundation + political coverage
  contract. Boundary production (MAPGEN-011) has not started.
- Stage history and per-stage review artifacts live in `reviews/`.

## Repository layout

```
src/mapgen/      pipeline modules (hex grid, terrain, hydro, islands,
                 reference human geography, scenario, historical geometry,
                 Europe coverage) + CLI
tests/           pytest suite (all synthetic/deterministic, no network)
config/          single YAML config (kanto.yaml) — all thresholds explicit
data/scenarios/  curated scenario political data (CSV, provenance-tracked)
data/historical/ global historical source registry + temporal geometry
data/raw/        downloaded third-party datasets — NOT tracked (see below)
output/          run outputs — NOT tracked; review copies go to reviews/
reviews/         per-stage review packages for ChatGPT review (tracked)
```

## Third-party datasets

`data/raw/` (≈7 GB: OSM land polygons, Copernicus DEM, ESA WorldCover,
Köppen-Geiger, HydroLAKES/HydroRIVERS, Natural Earth, GeoNames) is not
redistributed here. `data/source_manifest.json` records name, URL,
version, licence and SHA-256 for every dataset; `python -m mapgen
fetch-data` plus the per-stage pipelines re-download what is fetchable.

## Running

```
python -m pytest tests/ -q                 # full test suite
python -m mapgen all       --config config/kanto.yaml   # MAPGEN-001 base
python -m mapgen terrain   --config config/kanto.yaml
python -m mapgen hydro     --config config/kanto.yaml
python -m mapgen geography --config config/kanto.yaml
python -m mapgen islands   --config config/kanto.yaml
python -m mapgen humangeo  --config config/kanto.yaml
python -m mapgen scenario  --config config/kanto.yaml
python -m mapgen europe    --config config/kanto.yaml   # resumable chunks
```

Each stage writes `output/<run_id>/` with a `chatgpt_review/` package
(README_REVIEW.md, run_manifest.json, validation/summary CSVs, images).
On stage completion the package is copied to `reviews/<STAGE_NAME>/`,
committed and pushed — GitHub is the review handoff authority.
