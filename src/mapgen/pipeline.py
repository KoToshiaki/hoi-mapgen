"""End-to-end mapgen pipeline orchestration.

Stages: sources -> hex grid -> land classification -> city assignment
      -> coastline evaluation -> exports -> renders -> manifest -> review package.

Generation and evaluation are strictly separated: evaluation only reads
generated data and never influences generation parameters.
"""
from __future__ import annotations

import datetime as _dt
import gzip
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
import shapely

from . import SCHEMA_VERSION
from .cities import (add_collision_stats, assign_cities, collision_summary,
                     load_cities_geonames)
from .coastline import coastline_errors, sample_coastline
from .config import MapgenConfig
from .evaluate import summarize
from .export import (dir_size_mb, write_city_outputs, write_coast_outputs,
                     write_hex_outputs)
from .hex_grid import HexGrid
from .land import classify_hexes, generated_coastline, load_land_mercator, source_coastline
from .manifest import write_run_manifest
from .projection import bbox_to_mercator, to_wgs84
from .render import render_coast_error, render_contact_sheet, render_preview
from .sources import ensure_dataset, update_source_manifest


def _peak_memory_mb() -> float:
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None) or info.rss
    return peak / (1024 * 1024)


def make_run_id(cfg: MapgenConfig, override: str | None = None) -> str:
    if override:
        return override
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{cfg.region_name}_{stamp}"


def run_all(cfg: MapgenConfig, run_id: str | None = None,
            do_render: bool = True) -> Path:
    t_start = time.perf_counter()
    run_id = make_run_id(cfg, run_id)
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    # ---- sources ---------------------------------------------------------
    land_shp = ensure_dataset("ne_10m_land", cfg.data_dir)
    cities_txt = ensure_dataset("geonames_cities15000", cfg.data_dir)
    source_manifest = update_source_manifest(
        cfg.data_dir, ["ne_10m_land", "geonames_cities15000"]
    )

    # ---- shared inputs ---------------------------------------------------
    bbox_3857 = bbox_to_mercator(cfg.bbox_wgs84)
    min_x, min_y, max_x, max_y = bbox_3857
    grid_extent = (min_x - cfg.margin_m, min_y - cfg.margin_m,
                   max_x + cfg.margin_m, max_y + cfg.margin_m)
    land_clip_margin = cfg.margin_m + 10000.0
    clip_bbox = (min_x - land_clip_margin, min_y - land_clip_margin,
                 max_x + land_clip_margin, max_y + land_clip_margin)

    print(f"[pipeline] run_id={run_id}")
    print("[pipeline] loading land polygons ...")
    land = load_land_mercator(land_shp, bbox_3857, land_clip_margin)
    coast = source_coastline(land, clip_bbox)
    print(f"[pipeline] land area (clipped): {shapely.area(land) / 1e6:,.0f} km2, "
          f"coastline length: {shapely.length(coast) / 1000:,.0f} km")

    print("[pipeline] loading cities ...")
    cities_base = load_cities_geonames(cities_txt, cfg.bbox_wgs84)
    print(f"[pipeline] {len(cities_base)} cities in bbox")

    # Source coastline samples are hex-size independent: sample once.
    sample_xy = sample_coastline(coast, cfg.coast_sample_interval_m, bbox_3857)
    print(f"[pipeline] {len(sample_xy)} coastline sample points")

    summary_rows = []
    per_size_stats = []
    render_items = []

    for size in cfg.hex_sizes_m:
        t_gen = time.perf_counter()
        size_label = f"{size:.0f}m"
        size_dir = run_dir / size_label
        size_dir.mkdir(parents=True, exist_ok=True)
        print(f"[pipeline] === hex size {size_label} ===")

        grid = HexGrid(flat_to_flat=size, orientation=cfg.hex_orientation,
                       origin_x=cfg.grid_origin_x, origin_y=cfg.grid_origin_y)
        q, r = grid.hexes_covering_bbox(*grid_extent)
        polys = grid.polygons(q, r)
        cx, cy = grid.axial_to_xy(q, r)
        centres = np.stack([cx, cy], axis=1)
        lon, lat = to_wgs84(cx, cy)
        print(f"[pipeline] {len(q)} hexes")

        cls = classify_hexes(polys, centres, land, coast, grid.area, cfg.land_threshold)

        # ---- cities ------------------------------------------------------
        cities_df = assign_cities(cities_base, grid)
        cities_df = add_collision_stats(cities_df)

        hex_df = pd.DataFrame({
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "hex_size_m": size,
            "hex_flat_to_flat_m": size,
            "hex_id": grid.hex_ids(q, r),
            "q": q,
            "r": r,
            "centre_x_m": cx,
            "centre_y_m": cy,
            "centre_lon": lon,
            "centre_lat": lat,
            "hex_area_m2": grid.area,
            "land_intersection_m2": cls["land_intersection_m2"],
            "water_intersection_m2": cls["water_intersection_m2"],
            "land_fraction": cls["land_fraction"],
            "water_fraction": cls["water_fraction"],
            "land_class": cls["land_class"],
            "is_coastal": cls["is_coastal"],
            "coastline_intersection_m": cls["coastline_intersection_m"],
            "distance_centre_to_coast_m": cls["distance_centre_to_source_coast_m"],
            "source_land_area_m2": cls["land_intersection_m2"],
            "classification_error_area_m2": cls["classification_error_area_m2"],
        })
        # Per-hex city aggregation.
        if len(cities_df):
            grp = cities_df.sort_values("population", ascending=False).groupby("assigned_hex_id")
            agg = grp.agg(
                city_count=("city_id", "count"),
                primary_city_id=("city_id", "first"),
                primary_city_name=("city_name", "first"),
            )
            hex_df = hex_df.merge(agg, left_on="hex_id", right_index=True, how="left")
            hex_df["city_count"] = hex_df["city_count"].fillna(0).astype(np.int64)
            hex_df["primary_city_id"] = hex_df["primary_city_id"].astype("Int64")
        else:
            hex_df["city_count"] = 0
            hex_df["primary_city_id"] = pd.array([None] * len(hex_df), dtype="Int64")
            hex_df["primary_city_name"] = None
        hex_df["same_hex_city_count"] = np.where(
            hex_df["city_count"] >= 2, hex_df["city_count"], 0
        ).astype(np.int64)
        # Future administrative hierarchy — not implemented yet, kept in schema.
        for col in ("country_id", "state_id", "region_id", "city_area_id"):
            hex_df[col] = pd.array([None] * len(hex_df), dtype="Int64")

        # Cities need the land info of their assigned hex.
        hex_lookup = hex_df.set_index("hex_id")[["land_fraction", "land_class"]]
        cities_df = cities_df.merge(
            hex_lookup, left_on="assigned_hex_id", right_index=True, how="left"
        ).rename(columns={
            "land_fraction": "assigned_hex_land_fraction",
            "land_class": "assigned_hex_land_class",
        })
        cities_df["run_id"] = run_id
        cities_df["hex_size_m"] = size

        gen_coast = generated_coastline(polys, hex_df["land_class"].to_numpy() == "land")

        # Reference land area over the SAME domain the hexes cover, so the
        # binary-vs-source comparison measures pure quantisation error.
        hex_union = shapely.union_all(polys)
        source_land_area_m2 = float(shapely.area(shapely.intersection(land, hex_union)))
        fractional_sum = float(hex_df["land_intersection_m2"].sum())
        if source_land_area_m2 > 0 and abs(fractional_sum - source_land_area_m2) > 0.001 * source_land_area_m2:
            warnings.append(
                f"{size_label}: fractional land sum {fractional_sum:.0f} m2 deviates "
                f"from source land area {source_land_area_m2:.0f} m2"
            )
        gen_time = time.perf_counter() - t_gen

        # ---- evaluation --------------------------------------------------
        t_eval = time.perf_counter()
        coast_df = coastline_errors(sample_xy, gen_coast)
        coast_df["run_id"] = run_id
        coast_df["hex_size_m"] = size
        collision = collision_summary(cities_df, cfg.population_thresholds)
        eval_time = time.perf_counter() - t_eval

        # ---- exports -----------------------------------------------------
        write_hex_outputs(size_dir, hex_df, polys)
        write_city_outputs(size_dir, cities_df)
        write_coast_outputs(size_dir, coast_df, gen_coast)

        # ---- renders -----------------------------------------------------
        t_render = time.perf_counter()
        if do_render:
            render_preview(
                size_dir / f"preview_{size_label}.png",
                f"{cfg.region_name} — {size_label} flat-to-flat "
                f"({len(q)} hexes, EPSG:3857)",
                hex_df, polys, coast, cities_df, bbox_3857,
                cfg.label_min_population,
            )
            for zoom_name, zbox in cfg.zooms.items():
                zext = bbox_to_mercator(zbox)
                render_preview(
                    size_dir / f"zoom_{zoom_name}_{size_label}.png",
                    f"{zoom_name} — {size_label}",
                    hex_df, polys, coast, cities_df, zext,
                    cfg.label_min_population, hex_lw=0.6,
                )
            render_coast_error(
                size_dir / f"coastline_error_{size_label}.png",
                f"coastline error — {size_label} "
                f"(mean {coast_df['coast_error_m'].mean():.0f} m)",
                coast_df, gen_coast, coast, bbox_3857,
            )
        render_time = time.perf_counter() - t_render

        peak_mb = _peak_memory_mb()
        size_mb = dir_size_mb(size_dir)
        row = summarize(
            run_id, size, hex_df, cities_df, coast_df, source_land_area_m2,
            grid.area, collision, size_mb, gen_time, eval_time, peak_mb,
        )
        summary_rows.append(row)
        per_size_stats.append({
            "hex_size_m": size,
            "hex_count": int(len(q)),
            "generation_time_s": round(gen_time, 3),
            "evaluation_time_s": round(eval_time, 3),
            "render_time_s": round(render_time, 3),
            "output_size_mb": round(size_mb, 3),
            "peak_memory_mb_so_far": round(peak_mb, 1),
        })
        render_items.append({
            "hex_size_m": size, "hex_df": hex_df, "hex_polys": polys,
            "coastline": coast, "cities_df": cities_df, "coast_df": coast_df,
            "gen_coast": gen_coast,
        })
        print(f"[pipeline] {size_label}: gen {gen_time:.1f}s, eval {eval_time:.1f}s, "
              f"render {render_time:.1f}s, {size_mb:.1f} MB")

    # ---- run-level outputs ----------------------------------------------
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(run_dir / "evaluation_summary.csv", index=False,
                      float_format="%.4f")

    if do_render:
        render_contact_sheet(
            run_dir / "comparison_contact_sheet.png", render_items, bbox_3857,
            cfg.label_min_population,
        )

    total_s = time.perf_counter() - t_start
    peak_mb = _peak_memory_mb()
    write_run_manifest(run_dir, cfg, run_id, source_manifest, total_s, peak_mb,
                       per_size_stats, warnings)

    build_review_package(cfg, run_dir, run_id, summary_df, warnings)
    print(f"[pipeline] done in {total_s:.1f}s, peak memory {peak_mb:.0f} MB")
    print(f"[pipeline] output: {run_dir}")
    return run_dir


# --------------------------------------------------------------------------
def build_review_package(cfg: MapgenConfig, run_dir: Path, run_id: str,
                         summary_df: pd.DataFrame, warnings: list[str]) -> Path:
    """Assemble output/<run_id>/chatgpt_review/ for machine review."""
    review = run_dir / "chatgpt_review"
    review.mkdir(parents=True, exist_ok=True)

    shutil.copy2(run_dir / "evaluation_summary.csv", review / "evaluation_summary.csv")
    shutil.copy2(run_dir / "run_manifest.json", review / "run_manifest.json")
    for name in ("comparison_contact_sheet.png",):
        src = run_dir / name
        if src.exists():
            shutil.copy2(src, review / name)

    size_labels = [f"{s:.0f}m" for s in cfg.hex_sizes_m]
    for label in size_labels:
        size_dir = run_dir / label
        shutil.copy2(size_dir / "cities.csv", review / f"cities_{label}.csv")
        shutil.copy2(size_dir / "coastline_samples.csv",
                     review / f"coastline_samples_{label}.csv")
        # hex_cells may be large: gzip the CSV for the review package.
        with open(size_dir / "hex_cells.csv", "rb") as fin, \
                gzip.open(review / f"hex_cells_{label}.csv.gz", "wb") as fout:
            shutil.copyfileobj(fin, fout)
        shutil.copy2(size_dir / "hex_cells.parquet", review / f"hex_cells_{label}.parquet")
        for png in (f"preview_{label}.png", f"zoom_tokyo_bay_{label}.png",
                    f"zoom_miura_boso_{label}.png"):
            src = size_dir / png
            if src.exists():
                shutil.copy2(src, review / png)

    _write_review_readme(cfg, review, run_id, summary_df, warnings)
    return review


def _write_review_readme(cfg: MapgenConfig, review: Path, run_id: str,
                         summary_df: pd.DataFrame, warnings: list[str]) -> None:
    files = "\n".join(f"- {p.name}" for p in sorted(review.glob("*")) if p.is_file())
    warn_text = "\n".join(f"- {w}" for w in warnings) if warnings else "None."
    text = f"""# README_REVIEW

Project: mapgen — Mercator uniform hex map prototype (pre-engine offline GIS pipeline)
Run ID: {run_id}
Date: {_dt.date.today().isoformat()}

Test region: {cfg.region_name} (WGS84 bbox lon {cfg.bbox_wgs84.min_x}..{cfg.bbox_wgs84.max_x}, lat {cfg.bbox_wgs84.min_y}..{cfg.bbox_wgs84.max_y})
Projection: EPSG:4326 -> EPSG:3857 (Web Mercator). All hex geometry, areas and distances are measured on the EPSG:3857 plane (projected metres, NOT ground metres; at ~35.5N ground distance is roughly 0.81x the projected value).
Hex orientation: {cfg.hex_orientation}-top
Hex sizes: {", ".join(f"{s:.0f} m" for s in cfg.hex_sizes_m)} — the size value is the FLAT-TO-FLAT distance (distance between opposite parallel edges) on the EPSG:3857 plane.
Grid origin: world-fixed at EPSG:3857 ({cfg.grid_origin_x}, {cfg.grid_origin_y}); hex (q=0, r=0) is centred there for every size, so hex IDs are globally reproducible.

Source datasets:
- Natural Earth 1:10m Physical Vectors — Land (ne_10m_land), public domain. Used for land polygons and the source coastline.
- GeoNames cities15000 (all places with population >= 15,000), CC BY 4.0. Used for cities (Natural Earth populated places was rejected: it only carries ~prefecture-capital density in Japan, which would make the city-collision metric meaningless).
See run_manifest.json for URLs, versions and SHA-256.

Important implementation decisions:
- Uniform hex grid on the Mercator plane; high-latitude distance/area distortion is accepted by design.
- Axial coordinates (q, r), pointy-top, Red Blob Games convention. hex_id = h<size>_q<+/-......>_r<+/-......> and is deterministic.
- Hexes were generated over the bbox expanded by {cfg.margin_m:.0f} m so edge hexes are classified correctly; hex counts therefore include this margin ring. All error metrics only use samples inside the core bbox.
- Land threshold: land_fraction >= {cfg.land_threshold} -> "land", else "water". Fractions are always preserved alongside the binary class.

Known limitations:
- Natural Earth 1:10m coastline is generalized (small islands and fine coastal detail are missing); coastline error is measured against this source, not against reality.
- GeoNames cities15000 only includes places with population >= 15,000; collisions among smaller towns are not measured. GeoNames "cities" include wards/suburbs of larger cities, so some collisions are between a city and its own suburb rather than two independent towns. GeoNames naming quirks exist (e.g. Funabashi appears as "Honchō", geonameid 1863905, population 644,668).
- Islands smaller than roughly half a hex are classified fully water and vanish; their source-coastline samples then measure the distance to the nearest surviving coast, which dominates coast_error_max (18-31 km here, caused by small Izu islands). Mean/median/p90/p95 are the meaningful comparison metrics; max mostly reports island loss.
- All CSVs are UTF-8 (city names contain macrons / Japanese-derived characters).
- No rivers, elevation, administrative boundaries yet (country/state/region/city_area IDs are null placeholders).
- peak_memory_mb is the process lifetime peak at the time each size finished (monotonically increasing across sizes), not an isolated per-size peak.

Generated file list:
{files}

How land classification works:
Every hex polygon is intersected with the (clipped, unioned) source land polygons on EPSG:3857. land_fraction = intersection_area / hex_area; water_fraction = 1 - land_fraction. Binary class applies the {cfg.land_threshold} threshold. classification_error_area_m2 is the area discarded by the binary decision (water part of a land hex, land part of a water hex). A hex is coastal if 0 < land_fraction < 1 or the source coastline crosses it.

How coastline error is measured:
The source coastline (boundary of the land polygons, clip edges removed) is sampled every {cfg.coast_sample_interval_m:.0f} m on the EPSG:3857 plane. The generated coastline is the boundary of the union of all binary-land hexes. coast_error_m = distance from each source sample point to the nearest point of the generated coastline. Summary stats: mean / median / p90 / p95 / max.

How city collision is measured:
Each city point is projected to EPSG:3857 and assigned to the hex containing it. cities_in_same_hex counts cities assigned to the same hex; a "collision" is a hex containing >= 2 cities. evaluation_summary.csv reports the number of cities involved in collisions, the number of collided hexes, the summed population involved, the collided city name groups, and the same counts restricted to population thresholds ({", ".join(str(t) for t in cfg.population_thresholds)}).

Any warnings/errors encountered:
{warn_text}

Note from the generator (Claude): this run intentionally does NOT choose a hex size. All four sizes are generated under identical conditions; the decision is left to this review. Broad observation only: smaller hexes reproduce the coastline better and separate cities better at the cost of ~2.6x (5 km vs 8 km) to 4x (5 km vs 10 km) hex count and file size — see evaluation_summary.csv for the actual numbers.
"""
    (review / "README_REVIEW.md").write_text(text, encoding="utf-8")
