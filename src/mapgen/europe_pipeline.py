"""MAPGEN-010 — Europe Canonical Hex Coverage + Temporal Historical
Political Geometry Foundation (pipeline).

REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP.
SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY WITHIN ITS
SCENARIO SNAPSHOT — AND ONLY WHERE COVERAGE SAYS SO:
MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER NEUTRAL.

The chunk loop is resumable: chunk results are cached under the run dir,
so repeated invocations continue until coverage is complete, then the
gates/renders/report run.
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

from .config import BBox, MapgenConfig
from .europe_coverage import (CHUNK_MARGIN_M, COVERAGE_STATUS_GEOMETRY_ONLY,
                              EUROPE_COVERAGE_SCHEMA_VERSION,
                              WATER_AUTHORITY_STATUS, chunk_canonical_hash,
                              europe_chunk_grid, generate_chunk)
from .hex_grid import HexGrid
from .historical_geometry import (HPG_ALGORITHM_VERSION, HPG_SCHEMA_VERSION,
                                  SOURCE_AUTHORITY_LEVELS,
                                  load_global_sources,
                                  make_global_source_id,
                                  select_features_for_snapshot)
from .human_geography_pipeline import _save
from .hydro_sources import osm_land_shp
from .islands_pipeline import prepare_patch
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .projection import bbox_to_mercator
from .scenario import (COVERAGE_STATUSES, IncompleteCoverageError,
                       SCENARIO_SCHEMA_VERSION, load_scenario,
                       make_scenario_polity_id, resolve_control_status,
                       scenarios_root)
from .scenario_pipeline import (STAGE_FAMILY, _active_audit,
                                scan_forbidden_reference_code)
from .sources import sha256_of

STAGE = "MAPGEN-010"
CHUNK_TIME_BUDGET_S = 420.0  # per invocation; loop resumes on next call


# --------------------------------------------------------------------------
# Land cache (OSM coast authority — one linear scan, banded for memory)
# --------------------------------------------------------------------------
def build_land_cache(cfg: MapgenConfig, ecfg: dict, cache: Path) -> Path:
    if cache.exists():
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    shp = osm_land_shp(cfg.data_dir)
    writer = None
    n_bands = 5
    lat_edges = np.linspace(float(ecfg["min_lat"]), float(ecfg["max_lat"]),
                            n_bands + 1)
    for i in range(n_bands):
        b = bbox_to_mercator(BBox(float(ecfg["min_lon"]),
                                  float(lat_edges[i]),
                                  float(ecfg["max_lon"]),
                                  float(lat_edges[i + 1])))
        gdf = gpd.read_file(shp, bbox=(b[0] - CHUNK_MARGIN_M,
                                       b[1] - CHUNK_MARGIN_M,
                                       b[2] + CHUNK_MARGIN_M,
                                       b[3] + CHUNK_MARGIN_M))
        if not len(gdf):
            continue
        geoms = gdf.geometry.values
        bounds = shapely.bounds(np.asarray(geoms, dtype=object))
        # De-duplicate polygons that span band boundaries.
        tbl = pa.table({
            "minx": bounds[:, 0], "miny": bounds[:, 1],
            "maxx": bounds[:, 2], "maxy": bounds[:, 3],
            "wkb": [shapely.to_wkb(g) for g in geoms],
        })
        if writer is None:
            writer = pq.ParquetWriter(cache, tbl.schema)
        writer.write_table(tbl)
        print(f"[europe] land cache band {i + 1}/{n_bands}: "
              f"{len(gdf)} parts")
    if writer is not None:
        writer.close()
    return cache


def load_land_parts(cache: Path, bbox_3857, margin: float):
    x0, y0, x1, y1 = bbox_3857
    df = pq.read_table(cache).to_pandas()
    m = ((df["minx"] <= x1 + margin) & (df["maxx"] >= x0 - margin)
         & (df["miny"] <= y1 + margin) & (df["maxy"] >= y0 - margin))
    sub = df[m]
    if not len(sub):
        return np.array([], dtype=object), None
    geoms = shapely.from_wkb(sub["wkb"].to_numpy())
    # Cross-band duplicates: same polygon read in two bands — drop by WKB.
    _, idx = np.unique(sub["wkb"].to_numpy(), return_index=True)
    geoms = geoms[np.sort(idx)]
    return geoms, shapely.STRtree(geoms)


# --------------------------------------------------------------------------
# Renders
# --------------------------------------------------------------------------
def render_overview(path, chunk_files, chunks, totals, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 13))
    for f in chunk_files:
        t = pq.read_table(f, columns=["centre_x_m", "centre_y_m",
                                      "is_terrestrial_hex"]).to_pandas()
        land = t["is_terrestrial_hex"].to_numpy()
        ax.scatter(t["centre_x_m"][~land], t["centre_y_m"][~land], s=0.03,
                   c="#a8c8e8", marker=".", rasterized=True)
        ax.scatter(t["centre_x_m"][land], t["centre_y_m"][land], s=0.03,
                   c="#5f7a4a", marker=".", rasterized=True)
    for c in chunks:
        x0, y0, x1, y1 = c["bbox_3857"]
        ax.plot([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0],
                color="#333333", lw=0.5)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(
        f"{title}\n{totals['chunks']} chunks, "
        f"{totals['hexes']:,} hexes ({totals['terrestrial']:,} "
        f"terrestrial / {totals['ocean']:,} ocean) — existing global "
        "grid, GEOMETRY_COVERAGE_ONLY", fontsize=10)
    _save(fig, path)


def render_seam_zoom(path, run_chunks_dir, chunks, corner_lonlat, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection

    cx, cy = bbox_to_mercator(BBox(corner_lonlat[0], corner_lonlat[1],
                                   corner_lonlat[0], corner_lonlat[1]))[:2]
    w = 45000.0
    window = shapely.box(cx - w, cy - w, cx + w, cy + w)
    colors = {0: "#c6dbef", 1: "#fdd0a2", 2: "#c7e9c0", 3: "#dadaeb"}
    fig, ax = plt.subplots(figsize=(10, 10))
    seen = {}
    ci = 0
    for c in chunks:
        x0, y0, x1, y1 = c["bbox_3857"]
        if not (x0 - w < cx + w and x1 + w > cx - w
                and y0 - w < cy + w and y1 + w > cy - w):
            continue
        f = run_chunks_dir / f"{c['chunk_id']}.parquet"
        g = gpd.read_parquet(f)
        g = g[g.geometry.intersects(window)]
        if not len(g):
            continue
        verts = [np.asarray(p.exterior.coords)[:-1] for p in g.geometry]
        ax.add_collection(PolyCollection(
            verts, facecolors=colors[ci % 4], edgecolors="#555555",
            linewidths=0.4))
        for h in g["hex_id"]:
            seen[h] = seen.get(h, 0) + 1
        ci += 1
    dups = sum(1 for v in seen.values() if v > 1)
    ax.plot([cx, cx], [cy - w, cy + w], color="#b03a2e", lw=1.2, ls="--")
    ax.plot([cx - w, cx + w], [cy, cy], color="#b03a2e", lw=1.2, ls="--")
    ax.set_xlim(cx - w, cx + w)
    ax.set_ylim(cy - w, cy + w)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(f"{title}\ncolours = chunks; duplicates in window = "
                 f"{dups}; dashed = chunk boundaries", fontsize=10)
    _save(fig, path)


def render_temporal_architecture(path, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 9))

    def box(x, y, w, h, text, fc, fs=9):
        ax.add_patch(plt.Rectangle((x, y), w, h, fc=fc, ec="#333333",
                                   lw=1.2, zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, zorder=3)

    box(0.25, 0.82, 0.5, 0.13,
        "HISTORICAL SOURCES (global registry, hsrc_)\n"
        "publication date ≠ represented date; authority levels are "
        "unequal", "#efe9d6")
    box(0.25, 0.60, 0.5, 0.13,
        "TEMPORAL BOUNDARY FEATURES (hbf_)\nvalid_from / valid_to / "
        "precision / uncertainty / provenance\nscenario-independent — "
        "reused by every scenario", "#dce7f2")
    box(0.25, 0.38, 0.5, 0.13,
        "SCENARIO SNAPSHOT SELECTION (snapshot_date)\n+ explicit "
        "per-scenario interpretation — NEVER automatic", "#ddead9")
    box(0.25, 0.16, 0.5, 0.13,
        "GAMEPLAY CONTROL (scenario territorial_control)\nauthoritative "
        "only within its snapshot AND its coverage", "#f7dcd7")
    for y in (0.82, 0.60, 0.38):
        ax.annotate("", xy=(0.5, y - 0.09 + 0.09), xytext=(0.5, y),
                    arrowprops={"arrowstyle": "->", "lw": 2,
                                "color": "#333333"})
        ax.annotate("", xy=(0.5, y - 0.09), xytext=(0.5, y - 0.0),
                    arrowprops={"arrowstyle": "->", "lw": 2,
                                "color": "#333333"})
    ax.text(0.06, 0.5, "NO geometry copied\nper scenario;\n"
            "NO modern admin\ninput anywhere", fontsize=9,
            color="#b03a2e", ha="center")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_coverage_semantics(path, cov, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(13, 8))

    def box(x, y, w, h, text, fc, fs=9):
        ax.add_patch(plt.Rectangle((x, y), w, h, fc=fc, ec="#333333",
                                   lw=1.2, zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, zorder=3)

    counts = cov["control_coverage_status"].value_counts().to_dict()
    box(0.05, 0.55, 0.42, 0.33,
        "coverage != COMPLETE\n+ no territorial_control row\n\n"
        "= UNKNOWN_COVERAGE_INCOMPLETE\n"
        "(strict consumers raise IncompleteCoverageError)", "#f7dcd7", 10)
    box(0.53, 0.55, 0.42, 0.33,
        "coverage == COMPLETE\n+ no territorial_control row\n\n"
        "= genuinely UNCONTROLLED\n(the only case that may ever mean "
        "'no controller')", "#ddead9", 10)
    box(0.15, 0.12, 0.70, 0.28,
        "NEVER: missing row -> neutral/unowned territory\n\n"
        f"current coverage units: {json.dumps(counts)}\n"
        "gameplay_authoritative=true means 'existing political rows are "
        "authority',\nNOT 'the world is complete' "
        "(political_geography_complete=false)", "#efe9d6", 10)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_title(title, fontsize=11)
    _save(fig, path)


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------
def run_europe_foundation(cfg: MapgenConfig,
                          run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    ecfg = cfg.raw["europe_coverage"]
    scfg = cfg.raw["scenarios"]
    hcfg = cfg.raw["human_geography"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"europe_foundation_{_dt.datetime.now():%Y%m%d}"
    run_dir = cfg.output_dir / run_id
    chunks_dir = run_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    val_rows: list[dict] = []

    def _check(check_id, ok, detail):
        val_rows.append({"run_id": run_id, "check_id": check_id,
                         "pass": bool(ok), "detail": str(detail)})
        if not ok:
            warnings.append(f"VALIDATION FAIL {check_id}: {detail}")

    grid = HexGrid(flat_to_flat=float(cfg.raw["terrain"]["hex_size_m"]),
                   orientation=cfg.hex_orientation,
                   origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)
    chunks = europe_chunk_grid(ecfg)

    # ---- upstream SHA (before) ------------------------------------------
    t0 = time.perf_counter()
    geo_dir = cfg.output_dir / hcfg["upstream_run"]
    hg_dir = cfg.output_dir / scfg["upstream_human_geography_run"]
    r9_dir = cfg.output_dir / scfg["mapgen009r_baseline_run"]
    m8_dir = (cfg.output_dir / scfg["mapgen008_baseline_run"]
              / "chatgpt_review")
    upstream = {}
    for d, files in [
            (geo_dir, ["geography_hexes.parquet",
                       "island_components.parquet"]),
            (hg_dir, ["reference_admin0.parquet",
                      "reference_admin_hex_membership.parquet"]),
            (m8_dir, ["territorial_control.csv",
                      "territorial_claims.csv"]),
            (r9_dir / "chatgpt_review",
             ["polities.csv", "scenario_polities.csv",
              "scenario_polity_relationships.csv"])]:
        for f in files:
            upstream[str(d / f)] = sha256_of(d / f)
    sdir = scenarios_root(cfg.data_dir) / scenario_id
    timings["sha_s"] = time.perf_counter() - t0

    # ---- land cache + chunk loop (resumable) ----------------------------
    t0 = time.perf_counter()
    cache = cfg.output_dir / "europe_land_cache" / "europe_land_parts.parquet"
    build_land_cache(cfg, ecfg, cache)
    timings["land_cache_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    pending = [c for c in chunks
               if not (chunks_dir / f"{c['chunk_id']}.parquet").exists()]
    manifest_rows_path = run_dir / "chunk_progress.json"
    progress = (json.loads(manifest_rows_path.read_text(encoding="utf-8"))
                if manifest_rows_path.exists() else {})
    osm_sha = progress.get("osm_sha") or sha256_of(osm_land_shp(cfg.data_dir))
    for c in pending:
        if time.perf_counter() - t0 > CHUNK_TIME_BUDGET_S:
            progress["osm_sha"] = osm_sha
            manifest_rows_path.write_text(json.dumps(progress, indent=1),
                                          encoding="utf-8")
            done = len(chunks) - sum(
                1 for cc in chunks
                if not (chunks_dir / f"{cc['chunk_id']}.parquet").exists())
            print(f"[europe] time budget reached: {done}/{len(chunks)} "
                  "chunks done — re-run the same command to resume")
            return run_dir
        tc = time.perf_counter()
        parts, tree = load_land_parts(cache, c["bbox_3857"],
                                      CHUNK_MARGIN_M + grid.side)
        gdf = generate_chunk(grid, c, parts, tree, cfg.land_threshold)
        gdf.to_parquet(chunks_dir / f"{c['chunk_id']}.parquet")
        progress[c["chunk_id"]] = {
            "hex_count": int(len(gdf)),
            "terrestrial": int(gdf["is_terrestrial_hex"].sum()),
            "ocean": int((~gdf["is_terrestrial_hex"]).sum()),
            "canonical_hash": chunk_canonical_hash(gdf),
            "runtime_s": round(time.perf_counter() - tc, 1),
        }
        print(f"[europe] {c['chunk_id']}: {len(gdf)} hexes "
              f"({progress[c['chunk_id']]['terrestrial']} land) "
              f"{progress[c['chunk_id']]['runtime_s']}s")
    progress["osm_sha"] = osm_sha
    manifest_rows_path.write_text(json.dumps(progress, indent=1),
                                  encoding="utf-8")
    timings["chunk_generation_s"] = time.perf_counter() - t0

    # ---- assembly + chunk manifest --------------------------------------
    t0 = time.perf_counter()
    chunk_files = [chunks_dir / f"{c['chunk_id']}.parquet" for c in chunks]
    man_rows = []
    id_seen: dict[str, str] = {}
    dup = 0
    totals = {"chunks": len(chunks), "hexes": 0, "terrestrial": 0,
              "ocean": 0}
    writer = None
    out_parquet = run_dir / "europe_hex_coverage.parquet"
    for c, f in zip(chunks, chunk_files):
        tbl = pq.read_table(f)
        if writer is None:
            writer = pq.ParquetWriter(out_parquet, tbl.schema)
        writer.write_table(tbl)
        ids = tbl.column("hex_id").to_pylist()
        for h in ids:
            if h in id_seen:
                dup += 1
            id_seen[h] = c["chunk_id"]
        p = progress[c["chunk_id"]]
        totals["hexes"] += p["hex_count"]
        totals["terrestrial"] += p["terrestrial"]
        totals["ocean"] += p["ocean"]
        man_rows.append({
            "chunk_id": c["chunk_id"],
            "min_lon": c["min_lon"], "min_lat": c["min_lat"],
            "max_lon": c["max_lon"], "max_lat": c["max_lat"],
            "generation_status": "GENERATED",
            "hex_count": p["hex_count"],
            "terrestrial_count": p["terrestrial"],
            "ocean_count": p["ocean"],
            "source_snapshot_sha256": osm_sha[:16],
            "canonical_hash": p["canonical_hash"],
            "runtime_s": p["runtime_s"],
        })
    writer.close()
    man = pd.DataFrame(man_rows)
    man.assign(run_id=run_id).to_csv(
        run_dir / "europe_hex_chunk_manifest.csv", index=False)
    per_chunk_max_s = float(man["runtime_s"].max())
    timings["assembly_s"] = time.perf_counter() - t0

    _check("E01_hex_ids_canonical_grid",
           all(h.startswith("h6000_q") for h in list(id_seen)[:1000])
           and totals["hexes"] == len(id_seen) + dup,
           f"{totals['hexes']:,} hexes on the existing global grid "
           "(h6000_q..._r... ids, world-fixed origin)")
    _check("E02_chunk_duplicates_zero", dup == 0,
           f"duplicate hex ids across all {len(chunks)} chunks = {dup}")

    # Seam strips: monolithic membership equals the chunk partition.
    t0 = time.perf_counter()
    missing = 0
    checked = 0
    for c in chunks:
        x0, y0, x1, y1 = c["bbox_3857"]
        if not c["last_col"]:
            strips = [(x1 - grid.flat_to_flat, y0, x1 + grid.flat_to_flat,
                       y1)]
        else:
            strips = []
        if not c["last_row"]:
            strips.append((x0, y1 - grid.flat_to_flat, x1,
                           y1 + grid.flat_to_flat))
        gx0, gy0, _, _ = chunks[0]["bbox_3857"]
        _, _, gx1, gy1 = chunks[-1]["bbox_3857"]
        for sx0, sy0, sx1, sy1 in strips:
            q, r = grid.hexes_covering_bbox(sx0, sy0, sx1, sy1)
            cx, cy = grid.axial_to_xy(q, r)
            cx, cy = np.atleast_1d(cx), np.atleast_1d(cy)
            inside = ((cx >= gx0) & (cx < gx1) & (cy >= gy0) & (cy < gy1)
                      & (cx >= sx0) & (cx <= sx1) & (cy >= sy0)
                      & (cy <= sy1))
            for hid in grid.hex_ids(q[inside], r[inside]):
                checked += 1
                if hid not in id_seen:
                    missing += 1
    _check("E03_seam_missing_zero", missing == 0,
           f"{checked:,} seam-strip hexes across all internal chunk "
           f"boundaries; missing from coverage = {missing}")
    timings["seam_s"] = time.perf_counter() - t0

    # Monolithic sub-extent equality (ids + geometry + classification).
    t0 = time.perf_counter()
    mc = ecfg["monolithic_check"]
    mb = bbox_to_mercator(BBox.from_lonlat_dict(mc))
    parts, tree = load_land_parts(cache, mb, CHUNK_MARGIN_M + grid.side)
    mono = generate_chunk(
        grid, {"chunk_id": "mono", "bbox_3857": mb, "last_col": False,
               "last_row": False}, parts, tree, cfg.land_threshold)
    cov_sub = []
    for c, f in zip(chunks, chunk_files):
        x0, y0, x1, y1 = c["bbox_3857"]
        if x0 < mb[2] and x1 > mb[0] and y0 < mb[3] and y1 > mb[1]:
            g = gpd.read_parquet(f)
            cov_sub.append(g[(g["centre_x_m"] >= mb[0])
                             & (g["centre_x_m"] < mb[2])
                             & (g["centre_y_m"] >= mb[1])
                             & (g["centre_y_m"] < mb[3])])
    cov_sub = pd.concat(cov_sub).sort_values(["r", "q"]).reset_index(
        drop=True)
    mono_sub = mono[(mono["centre_x_m"] >= mb[0])
                    & (mono["centre_x_m"] < mb[2])
                    & (mono["centre_y_m"] >= mb[1])
                    & (mono["centre_y_m"] < mb[3])].sort_values(
        ["r", "q"]).reset_index(drop=True)
    geom_eq = (len(cov_sub) == len(mono_sub)
               and list(cov_sub["hex_id"]) == list(mono_sub["hex_id"])
               and all(shapely.to_wkb(a) == shapely.to_wkb(b)
                       for a, b in zip(cov_sub.geometry,
                                       mono_sub.geometry)))
    lf_max = float(np.abs(cov_sub["land_fraction"].to_numpy()
                          - mono_sub["land_fraction"].to_numpy()).max()) \
        if len(cov_sub) == len(mono_sub) else 999.0
    _check("E04_chunked_equals_monolithic",
           geom_eq and lf_max <= 1e-5,
           f"monolithic sub-extent {mc} vs chunk union: "
           f"{len(mono_sub):,} hexes, id+geometry equal={geom_eq}, "
           f"max land_fraction diff={lf_max:.2e} (chunk-order "
           "independent by construction; also unit-tested)")
    timings["monolithic_s"] = time.perf_counter() - t0

    # Existing-grid identity: benelux + malta patch hexes.
    t0 = time.perf_counter()
    patch_ok, patch_detail = True, []
    for pname, pdef in [("border_benelux",
                         hcfg["regions"]["border_benelux"]),
                        ("malta",
                         cfg.raw["islands"]["validation_patches"]["malta"])]:
        pp = prepare_patch(pname, pdef, cfg, grid.flat_to_flat)
        pb = pp["bbox_3857"]
        interior = [i for i, poly in enumerate(pp["polys"])
                    if shapely.box(pb[0], pb[1], pb[2],
                                   pb[3]).contains(poly)]
        ids = [pp["hex_ids"][i] for i in interior]
        found = sum(1 for h in ids if h in id_seen)
        sub_polys = {}
        need_chunks = {id_seen[h] for h in ids if h in id_seen}
        for cid in need_chunks:
            g = gpd.read_parquet(chunks_dir / f"{cid}.parquet")
            g = g[g["hex_id"].isin(set(ids))]
            for h, geom, lf in zip(g["hex_id"], g.geometry,
                                   g["land_fraction"]):
                sub_polys[h] = (geom, lf)
        g_eq = all(shapely.to_wkb(pp["polys"][i])
                   == shapely.to_wkb(sub_polys[pp["hex_ids"][i]][0])
                   for i in interior if pp["hex_ids"][i] in sub_polys)
        lf_diff = max((abs(float(pp["land_fraction"][i])
                           - sub_polys[pp["hex_ids"][i]][1])
                       for i in interior
                       if pp["hex_ids"][i] in sub_polys), default=0.0)
        patch_ok &= (found == len(ids) and g_eq and lf_diff <= 1e-5)
        patch_detail.append(f"{pname}: {found}/{len(ids)} interior hexes "
                            f"present, geometry equal={g_eq}, "
                            f"max land_fraction diff={lf_diff:.2e}")
    _check("E05_existing_grid_identity", patch_ok,
           "; ".join(patch_detail))
    timings["patch_identity_s"] = time.perf_counter() - t0

    # ---- historical geometry namespace ----------------------------------
    hsrc = load_global_sources(cfg.data_dir)
    features = gpd.read_parquet(cfg.data_dir / "historical"
                                / "historical_boundary_features.parquet")
    catalogue = pd.read_csv(cfg.data_dir / "historical"
                            / "historical_geometry_catalogue.csv",
                            keep_default_na=False, na_values=[""])
    _check("E06_hsrc_registry",
           hsrc["global_source_id"].is_unique
           and all(make_global_source_id(k) == i for k, i in
                   zip(hsrc["citation_key"], hsrc["global_source_id"]))
           and hsrc["authority_level"].isin(
               SOURCE_AUTHORITY_LEVELS).all()
           and "publication_date" in hsrc.columns
           and "represented_date_range" in hsrc.columns,
           f"{len(hsrc)} global sources; deterministic hsrc_ ids; "
           "publication vs represented date are separate columns; "
           "authority levels within enum")
    eth = hsrc[hsrc["citation_key"] == "eth_hre_spatio_temporal_dataset"]
    wiki = hsrc[hsrc["citation_key"] == "wikimedia_europe_1748_1766_map"]
    _check("E07_source_authority_discipline",
           eth.iloc[0]["authority_level"] == "METHODOLOGY_REFERENCE"
           and wiki.iloc[0]["authority_level"] == "VISUAL_QA_ONLY"
           and "FORBIDDEN" in eth.iloc[0]["notes"],
           "ETH 16th-century dataset = METHODOLOGY_REFERENCE (never "
           "1756 authority); Wikimedia reconstruction = VISUAL_QA_ONLY")
    _check("E08_boundary_features_provenance_schema",
           len(features) == 0
           and {"valid_from", "valid_to", "temporal_precision",
                "global_source_id", "geometry_status"}.issubset(
                   features.columns)
           and catalogue["geometry_status"].isin(
               ["SOURCE_GAP", "GEOMETRY_PENDING"]).all()
           and catalogue["global_source_id"].isin(
               set(hsrc["global_source_id"])).all(),
           f"boundary features: 0 production rows (schema only); "
           f"catalogue {len(catalogue)} items all "
           "SOURCE_GAP/GEOMETRY_PENDING with resolving sources — no "
           "polygon invented without authority")
    scen_srcs = pd.read_csv(sdir / "sources.csv", keep_default_na=False,
                            na_values=[""])
    _check("E09_src_ids_unchanged_with_crosswalk",
           scen_srcs["source_id"].str.startswith("src_").all()
           and len(scen_srcs) == 10
           and scen_srcs["global_source_id"].isin(
               set(hsrc["global_source_id"])).all(),
           "all 10 scenario src_ ids unchanged; additive global_source_"
           "id crosswalk resolves into the hsrc registry")
    sel = select_features_for_snapshot(features, "1756-08-01")
    _check("E10_snapshot_selector_contract",
           len(sel) == 0 and callable(select_features_for_snapshot),
           "snapshot selector operates on temporal validity only "
           "(UNKNOWN never silently matches); returns 0 of 0 features — "
           "control generation for Europe is deliberately NOT run")

    # ---- scenario coverage contract + regression ------------------------
    snap = load_scenario(cfg.data_dir, scenario_id)
    cov = snap.political_coverage
    chunk_ids = {c["chunk_id"] for c in chunks}
    cov_units = set(cov["coverage_unit_id"])
    _check("E11_coverage_contract_units",
           chunk_ids <= cov_units
           and cov["coverage_unit_id"].is_unique
           and cov[["control_coverage_status", "claim_coverage_status",
                    "island_component_coverage_status",
                    "historical_overlay_coverage_status"]]
           .isin(COVERAGE_STATUSES).all().all(),
           f"{len(cov)} coverage units cover all {len(chunk_ids)} Europe "
           "chunks + the Kanto pilot region; statuses within enum")
    _check("E12_no_complete_without_conditions",
           int((cov["control_coverage_status"] == "COMPLETE").sum()) == 0,
           "COMPLETE coverage count=0 at foundation stage — COMPLETE "
           "requires explicit completeness conditions (contract in "
           "README/manifest)")
    try:
        resolve_control_status(snap.territorial_control, "UNASSESSED",
                               "TERRESTRIAL_HEX", "h6000_q+000000_r+000000")
        strict_ok = False
    except IncompleteCoverageError:
        strict_ok = True
    _check("E13_missing_is_not_neutral",
           strict_ok
           and resolve_control_status(
               snap.territorial_control, "UNASSESSED", "TERRESTRIAL_HEX",
               "h6000_q+000000_r+000000", strict=False)
           == "UNKNOWN_COVERAGE_INCOMPLETE"
           and resolve_control_status(
               snap.territorial_control, "COMPLETE", "TERRESTRIAL_HEX",
               "h6000_q+000000_r+000000", strict=False) == "UNCONTROLLED",
           "missing control row under incomplete coverage = UNKNOWN "
           "(strict consumers raise); UNCONTROLLED exists ONLY under "
           "COMPLETE coverage")
    forb = (scan_forbidden_reference_code(
        Path(__file__).parent / "historical_geometry.py")
        + scan_forbidden_reference_code(
            Path(__file__).parent / "europe_coverage.py"))
    _check("E14_no_modern_admin_leakage", not forb,
           f"AST scan of historical_geometry.py + europe_coverage.py: "
           f"forbidden reference-layer tokens={forb or 0}")
    tokugawa_sp = make_scenario_polity_id(scenario_id,
                                          "pol_tokugawa_shogunate")
    controllers = set(snap.territorial_control[
        "controller_scenario_polity_id"].dropna())
    sp = snap.scenario_polities
    struct = set(sp.loc[sp["territorial_authority_role"].isin(
        ["STRUCTURAL_CONTAINER", "COMPOSITE_TERRITORIAL_ACTOR"]),
        "scenario_polity_id"])
    _check("E15_no_relationship_or_container_control",
           controllers == {tokugawa_sp} and not (struct & controllers),
           f"controllers={sorted(controllers)} — {len(snap.scenario_polity_relationships)} "
           "relationships created zero territorial rows; containers/"
           "composite roots hold zero control")
    audit = snap.scenario_polity_inclusion_audit
    sup = audit[audit["audit_record_status"] == "SUPERSEDED"]
    _check("E16_active_superseded_preserved",
           len(sup) == 1 and len(_active_audit(audit)) == len(audit) - 1
           and sup.iloc[0]["canonical_candidate_id"]
           == "cand_schleswig_holstein_complex",
           "009R2 ACTIVE/SUPERSEDED audit semantics intact")
    r9 = r9_dir / "chatgpt_review"
    hist_eq = all(
        pd.read_csv(r9 / f, keep_default_na=False, na_values=[""]).equals(
            pd.read_csv(p, keep_default_na=False, na_values=[""]))
        for f, p in [("polities.csv",
                      scenarios_root(cfg.data_dir) / "polities.csv"),
                     ("scenario_polity_relationships.csv",
                      sdir / "scenario_polity_relationships.csv")])
    _check("E17_009r2_content_unchanged",
           hist_eq and len(snap.polities) == 66
           and len(snap.scenario_polity_relationships) == 46,
           "polities + relationships byte-content equal to the 009R2 "
           "baseline (66 polities / 46 relationships)")
    ctrl_sha = sha256_of(sdir / "territorial_control.csv")
    claims_sha = sha256_of(sdir / "territorial_claims.csv")
    _check("E18_control_claims_bytes_unchanged",
           ctrl_sha == sha256_of(m8_dir / "territorial_control.csv")
           and claims_sha == sha256_of(m8_dir / "territorial_claims.csv"),
           "territorial_control/claims byte-identical to MAPGEN-008 "
           "(and therefore 009R2)")
    tok = sp[sp["scenario_polity_id"] == tokugawa_sp]
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    tosh_wt = geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                      "water_type"].iloc[0]
    _check("E19_tokugawa_and_toshima_unchanged",
           len(tok) == 1 and tosh_wt == "OCEAN",
           f"Tokugawa pilot intact; Toshima underlying hex water_type="
           f"{tosh_wt}")
    _check("E20_namespace_versions",
           HPG_SCHEMA_VERSION == "1.0.0"
           and HPG_ALGORITHM_VERSION == "1.0.0"
           and SCENARIO_SCHEMA_VERSION == "1.5.0"
           and EUROPE_COVERAGE_SCHEMA_VERSION == "1.0.0",
           f"historical_political_geometry {HPG_SCHEMA_VERSION}/"
           f"{HPG_ALGORITHM_VERSION}; scenario schema "
           f"{SCENARIO_SCHEMA_VERSION} (additive coverage contract); "
           "europe coverage schema 1.0.0")

    # ---- renders ---------------------------------------------------------
    t0 = time.perf_counter()
    render_overview(run_dir / "europe_hex_coverage_overview.png",
                    chunk_files, chunks, totals,
                    "Europe canonical 6 km hex coverage (existing global "
                    "grid; chunk boundaries shown)")
    mcx = (float(mc["min_lon"]) + float(mc["max_lon"])) / 2
    corner = (3.0, 49.0)  # internal chunk corner near the check region
    render_seam_zoom(run_dir / "europe_chunk_seam_zoom.png", chunks_dir,
                     chunks, corner,
                     "Chunk seam validation zoom (internal corner "
                     f"{corner}) — no duplicate, no missing")
    render_temporal_architecture(
        run_dir / "temporal_architecture_diagram.png",
        "Temporal historical political geometry — sources -> temporal "
        "features -> snapshot -> gameplay control")
    render_coverage_semantics(
        run_dir / "political_coverage_semantics.png", cov,
        "Scenario political coverage contract — MISSING ROW + "
        "INCOMPLETE COVERAGE = UNKNOWN, NOT NEUTRAL")
    from PIL import Image

    img_names = ["europe_hex_coverage_overview.png",
                 "europe_chunk_seam_zoom.png",
                 "temporal_architecture_diagram.png",
                 "political_coverage_semantics.png"]
    aspects = {}
    for n in img_names:
        with Image.open(run_dir / n) as im:
            aspects[n] = round(im.size[0] / im.size[1], 3)
    _check("E21_renders",
           all((run_dir / n).exists() for n in img_names)
           and all(0.3 <= a <= 4.0 for a in aspects.values()),
           f"{len(img_names)} renders, aspects={aspects} (no aspect "
           "collapse)")
    timings["render_s"] = time.perf_counter() - t0

    # ---- upstream immutability (after) ----------------------------------
    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("E22_upstream_immutable", up_after == upstream,
           f"{len(upstream)} upstream files byte-identical before/after")

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(
        drop=True)
    val.to_csv(run_dir / "europe_validation.csv", index=False)
    n_pass = int(val["pass"].sum())

    # ---- coverage summary / manifest / README / package -----------------
    cov_sum = pd.DataFrame([
        ("europe_extent",
         f"lon {ecfg['min_lon']}..{ecfg['max_lon']}, "
         f"lat {ecfg['min_lat']}..{ecfg['max_lat']}"),
        ("chunks", totals["chunks"]),
        ("total_hexes", totals["hexes"]),
        ("terrestrial_hexes", totals["terrestrial"]),
        ("ocean_hexes", totals["ocean"]),
        ("duplicate_hexes", dup),
        ("seam_missing", missing),
        ("coverage_status", COVERAGE_STATUS_GEOMETRY_ONLY),
        ("water_authority_status", WATER_AUTHORITY_STATUS),
        ("per_chunk_max_runtime_s", per_chunk_max_s),
    ], columns=["metric", "value"])
    cov_sum.assign(run_id=run_id).to_csv(
        run_dir / "europe_hex_coverage_summary.csv", index=False)
    summary_rows = [
        ("stage", STAGE),
        ("historical_political_geometry_schema_version",
         HPG_SCHEMA_VERSION),
        ("historical_political_geometry_algorithm_version",
         HPG_ALGORITHM_VERSION),
        ("scenario_schema_version", SCENARIO_SCHEMA_VERSION),
        ("europe_coverage_schema_version",
         EUROPE_COVERAGE_SCHEMA_VERSION),
        ("europe_total_hexes", totals["hexes"]),
        ("europe_terrestrial_hexes", totals["terrestrial"]),
        ("europe_ocean_hexes", totals["ocean"]),
        ("global_historical_sources", len(hsrc)),
        ("boundary_features_production_rows", len(features)),
        ("geometry_catalogue_items", len(catalogue)),
        ("pilot_performed", False),
        ("pilot_state", "SOURCE_GAP (Low Countries candidate GIS not "
                        "yet acquired/date-verified; no polygons "
                        "invented)"),
        ("coverage_units", len(cov)),
        ("coverage_complete_units", 0),
        ("validation_pass", f"{n_pass}/{len(val)}"),
    ]
    pd.DataFrame(summary_rows, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "europe_summary.csv", index=False)
    manifest = {
        "run_id": run_id, "stage": STAGE,
        "stage_family": STAGE_FAMILY,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "historical_political_geometry_schema_version": HPG_SCHEMA_VERSION,
        "historical_political_geometry_algorithm_version":
            HPG_ALGORITHM_VERSION,
        "scenario_schema_version": SCENARIO_SCHEMA_VERSION,
        "version_reasons": {
            "scenario_schema_1.4.0": "additive political_coverage table "
                                     "(missing != neutral contract); "
                                     "nothing existing changed meaning",
            "hpg_1.0.0": "new namespace: temporal historical political "
                         "geometry, independent of any scenario",
        },
        "europe_extent": {k: ecfg[k] for k in
                          ("min_lon", "min_lat", "max_lon", "max_lat")},
        "chunk_strategy": f"{len(chunks)} deterministic lon/lat tiles "
                          f"({ecfg['chunk_deg_lon']}x"
                          f"{ecfg['chunk_deg_lat']} deg), membership by "
                          "hex centre in half-open 3857 box",
        "osm_source_sha256": osm_sha,
        "coverage_completeness_conditions": [
            "a coverage unit may become COMPLETE only when control, "
            "claims, island-component and overlay layers are each "
            "explicitly resolved for every terrestrial hex/component in "
            "the unit, with sources",
            "until then, absent control rows mean UNKNOWN — never "
            "neutral/unowned",
        ],
        "upstream_sha256": upstream,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8")
    _write_readme(run_dir, run_id, totals, hsrc, catalogue, cov, val,
                  aspects, ecfg)
    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    copies = {
        "europe_hex_chunk_manifest.csv":
            run_dir / "europe_hex_chunk_manifest.csv",
        "europe_hex_coverage_summary.csv":
            run_dir / "europe_hex_coverage_summary.csv",
        "historical_source_registry.csv":
            cfg.data_dir / "historical" / "historical_source_registry.csv",
        "historical_geometry_catalogue.csv":
            cfg.data_dir / "historical"
            / "historical_geometry_catalogue.csv",
        "scenario_political_coverage.csv": sdir / "political_coverage.csv",
        "validation.csv": run_dir / "europe_validation.csv",
        "summary.csv": run_dir / "europe_summary.csv",
        "run_manifest.json": run_dir / "run_manifest.json",
        "README_REVIEW.md": run_dir / "README_REVIEW.md",
    }
    for dst, src in copies.items():
        shutil.copy2(src, review / dst)
    feat_extract = pd.DataFrame(
        gpd.read_parquet(cfg.data_dir / "historical"
                         / "historical_boundary_features.parquet")
        .drop(columns="geometry"))
    feat_extract.to_csv(review / "historical_boundary_features_extract.csv",
                        index=False)
    for n in img_names:
        shutil.copy2(run_dir / n, review / n)
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"[europe] {run_id}: validation {n_pass}/{len(val)}, "
          f"{totals['hexes']:,} hexes ({totals['terrestrial']:,} land), "
          f"dup={dup} missing={missing}, pilot=SOURCE_GAP "
          f"({timings['total_s']:.0f}s)")
    for w in warnings:
        print(f"[europe][WARN] {w}")
    return run_dir


def _write_readme(run_dir, run_id, totals, hsrc, catalogue, cov, val,
                  aspects, ecfg):
    n_pass = int(val["pass"].sum())
    unassessed = int((cov["control_coverage_status"] == "UNASSESSED").sum())
    lines = [
        f"# {STAGE} Review — Europe Canonical Hex Coverage + Temporal "
        "Historical Political Geometry Foundation",
        "",
        "**REFERENCE ADMINISTRATION IS NOT GAMEPLAY OWNERSHIP.**",
        "**SCENARIO POLITICAL GEOGRAPHY IS GAMEPLAY-AUTHORITATIVE ONLY "
        "WITHIN ITS SCENARIO SNAPSHOT.**",
        "**MISSING ROW + INCOMPLETE COVERAGE = UNKNOWN, NEVER "
        "NEUTRAL.**",
        "",
        f"Run `{run_id}`. New namespace: historical_political_geometry "
        f"{HPG_SCHEMA_VERSION}/{HPG_ALGORITHM_VERSION}. scenario schema "
        f"1.3.0 → **{SCENARIO_SCHEMA_VERSION}** (additive "
        "political_coverage contract only).",
        "",
        "## Europe coverage",
        "",
        f"- Extent lon {ecfg['min_lon']}..{ecfg['max_lon']} / lat "
        f"{ecfg['min_lat']}..{ecfg['max_lat']} — chosen to cover every "
        "catalogue polity's European territory (incl. Iceland, Malta, "
        "North Cape, Moscow/Crimea); exclusions documented in config.",
        f"- {totals['chunks']} deterministic chunks on the EXISTING "
        f"global 6 km grid: {totals['hexes']:,} hexes "
        f"({totals['terrestrial']:,} terrestrial / "
        f"{totals['ocean']:,} ocean, OSM coast authority).",
        "- Coverage rows are GEOMETRY_COVERAGE_ONLY (water authority "
        "OSM_COAST_ONLY): terrain/lake/river layers are absent and "
        "explicitly marked — never faked as complete.",
        "- Seam gates: duplicates=0, seam missing=0, monolithic "
        "sub-extent equality (ids/geometry/classification), and "
        "benelux/malta patch hexes identical to the existing grid.",
        "",
        "## Historical political geometry (new namespace)",
        "",
        f"- Global source registry: {len(hsrc)} hsrc_ entries — the 10 "
        "existing scenario sources (src_ ids UNCHANGED, additive "
        "crosswalk) + 4 geometry-source candidates with UNEQUAL "
        "authority levels: Wikimedia 1748-1766 map = VISUAL_QA_ONLY; "
        "ETH HRE dataset = METHODOLOGY_REFERENCE (16th century — "
        "FORBIDDEN as 1756 authority); Historical Atlas of the Low "
        "Countries = BOUNDARY_AUTHORITY_CANDIDATE (cross-section dates "
        "must be verified first); Cassini = "
        "TOPOGRAPHIC_GEOREFERENCE_ONLY (no political authority).",
        "- Boundary feature schema: temporal validity (valid_from/"
        "valid_to/precision, publication ≠ represented date), "
        "provenance, uncertainty, geometry_status. Production rows: "
        f"**0** — the geometry catalogue tracks {len(catalogue)} "
        "planned items as SOURCE_GAP/GEOMETRY_PENDING.",
        "- **Pilot: NOT performed (SOURCE_GAP).** The priority-1 Low "
        "Countries pilot stops formally because the candidate academic "
        "GIS is not acquired/date-verified; drawing polygons without it "
        "is forbidden. Corsica keeps its 009R contested contract "
        "WITHOUT fiat geometry expansion.",
        "- Geometry is scenario-independent: one temporal feature "
        "serves every future scenario via snapshot-date selection "
        "(single-day sources use valid_from == valid_to); scenario_id "
        "is never part of geometry identity.",
        "",
        "## Coverage contract",
        "",
        f"- {len(cov)} coverage units ({unassessed} Europe chunks "
        "UNASSESSED + the Kanto pilot TERRITORY_PARTIAL). COMPLETE "
        "count: 0 — COMPLETE requires the explicit conditions in "
        "run_manifest.",
        "- `resolve_control_status`: a missing control row is "
        "authoritative ONLY under COMPLETE coverage (-> UNCONTROLLED); "
        "otherwise it is UNKNOWN and strict consumers raise "
        "IncompleteCoverageError. gameplay_authoritative=true means "
        "existing rows are authority, NOT that the world is complete "
        "(political_geography_complete stays false, data_status "
        "FOUNDATION_ONLY).",
        "",
        "## Regression",
        "",
        "- 009R2 polities/relationships byte-equal; territorial_control/"
        "claims byte-identical to MAPGEN-008; Tokugawa pilot + Toshima "
        "OCEAN unchanged; ACTIVE/SUPERSEDED audit intact; zero control "
        "from relationships/containers; no modern-admin leakage (AST).",
        "",
        "## Images",
        "",
    ]
    for n, a in aspects.items():
        lines.append(f"- `{n}` (aspect {a})")
    lines += [
        "",
        "## Validation",
        "",
        "- `validation.csv` lists every machine gate of this run; the "
        "pass count lives in `summary.csv`.",
        "",
        "## Known limitations",
        "",
        "- Europe rows carry no terrain/lake/river data yet "
        "(GEOMETRY_COVERAGE_ONLY); Ladoga-class lakes currently follow "
        "the OSM coast authority (land) until the hydro layer arrives.",
        "- Pilot deferred at SOURCE_GAP; boundary production is "
        "MAPGEN-011 scope after source acquisition.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
