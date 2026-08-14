"""mapgen command line interface.

Usage:
    python -m mapgen all --config config/kanto.yaml
    python -m mapgen generate --config config/kanto.yaml      # no PNG rendering
    python -m mapgen render --config config/kanto.yaml --run-id <run_id>
    python -m mapgen fetch-data --config config/kanto.yaml
"""
from __future__ import annotations

import argparse
import sys

from .config import load_config


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", required=True, help="path to YAML config")
    p.add_argument("--run-id", default=None,
                   help="override run id (default: <region>_<timestamp>)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mapgen")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("all", "full pipeline: sources, hexes, land, cities, evaluation, "
                "renders, exports, manifest, review package"),
        ("generate", "full pipeline without PNG rendering"),
        ("render", "re-run the full pipeline including rendering (alias of all)"),
        ("evaluate", "re-run the pipeline and refresh evaluation outputs"),
        ("fetch-data", "download source datasets and write source_manifest.json"),
        ("terrain", "MAPGEN-002: terrain data + terrain face classification "
                    "(6000 m reference hexes, Kanto + validation regions)"),
        ("hydro", "MAPGEN-003: OSM coastline, HydroLAKES lakes, HydroRIVERS "
                  "selection and river-to-hex-edge snapping"),
        ("geography", "MAPGEN-004: integrate terrain + hydro into the "
                      "canonical geography_hexes / game_river_edges dataset"),
        ("islands", "MAPGEN-005: strategic island preservation overlays "
                   "on the authoritative geography"),
        ("humangeo", "MAPGEN-007: reference administrative & settlement "
                     "geography (REFERENCE layer, not gameplay ownership)"),
        ("scenario", "MAPGEN-008: scenario political geography foundation "
                     "(validate + review the active scenario snapshot)"),
        ("europe", "MAPGEN-010: Europe canonical hex coverage + temporal "
                   "historical political geometry foundation (resumable)"),
        ("pilot", "MAPGEN-011: historical boundary source acquisition + "
                  "Low Countries production pilot"),
        ("revision", "MAPGEN-014: source corroboration, polity model "
                     "correction and canonical authority revision"),
        ("precision", "MAPGEN-015: 1747 precision georeference attempt, "
                      "Weimar/Eisenach model audit, metric correction"),
        ("expansion", "MAPGEN-016: Zollmann feature-point final attempt "
                      "and the Brandenburg production front"),
        ("copyaudit", "MAPGEN-017: Brandenburg copy-specific source "
                      "acquisition and segment continuity"),
        ("georef", "MAPGEN-018: Brandenburg graticule georeference"),
        ("georefreview", "MAPGEN-018R: observed-control validation of "
                         "the Brandenburg georeference"),
        ("georefrebuild", "MAPGEN-019: rebuild the Brandenburg "
                          "georeference from observed feature points"),
        ("dualsource", "MAPGEN-020: Brandenburg continuity audit and "
                       "independent BLHA georeference"),
        ("coastbound", "MAPGEN-021: British Isles coast-bounded "
                       "territorial production"),
    ):
        p = sub.add_parser(name, help=help_text)
        _add_common(p)

    args = parser.parse_args(argv)
    cfg = load_config(args.config)

    if args.command == "fetch-data":
        from .sources import ensure_dataset, update_source_manifest

        for key in ("ne_10m_land", "geonames_cities15000"):
            path = ensure_dataset(key, cfg.data_dir)
            print(f"[fetch-data] {key}: {path}")
        update_source_manifest(cfg.data_dir, ["ne_10m_land", "geonames_cities15000"])
        print(f"[fetch-data] manifest: {cfg.data_dir / 'source_manifest.json'}")
        return 0

    if args.command == "terrain":
        from .terrain_pipeline import run_terrain

        run_terrain(cfg, run_id=args.run_id)
        return 0

    if args.command == "hydro":
        from .hydro_pipeline import run_hydro

        run_hydro(cfg, run_id=args.run_id)
        return 0

    if args.command == "geography":
        from .geography_pipeline import run_geography

        run_geography(cfg, run_id=args.run_id)
        return 0

    if args.command == "islands":
        from .islands_pipeline import run_islands

        run_islands(cfg, run_id=args.run_id)
        return 0

    if args.command == "humangeo":
        from .human_geography_pipeline import run_human_geography

        run_human_geography(cfg, run_id=args.run_id)
        return 0

    if args.command == "scenario":
        from .scenario_pipeline import run_scenario

        run_scenario(cfg, run_id=args.run_id)
        return 0

    if args.command == "europe":
        from .europe_pipeline import run_europe_foundation

        run_europe_foundation(cfg, run_id=args.run_id)
        return 0

    if args.command == "coastbound":
        from .historical_coast_bounded_pipeline import (
            run_historical_coast_bounded)

        run_historical_coast_bounded(cfg, run_id=args.run_id)
        return 0

    if args.command == "dualsource":
        from .historical_dual_source_pipeline import (
            run_historical_dual_source)

        run_historical_dual_source(cfg, run_id=args.run_id)
        return 0

    if args.command == "georefrebuild":
        from .historical_georef_rebuild_pipeline import (
            run_historical_georef_rebuild)

        run_historical_georef_rebuild(cfg, run_id=args.run_id)
        return 0

    if args.command == "georefreview":
        from .historical_georef_review_pipeline import (
            run_historical_georef_review)

        run_historical_georef_review(cfg, run_id=args.run_id)
        return 0

    if args.command == "georef":
        from .historical_georef_pipeline import run_historical_georef

        run_historical_georef(cfg, run_id=args.run_id)
        return 0

    if args.command == "copyaudit":
        from .historical_copy_pipeline import run_historical_copy

        run_historical_copy(cfg, run_id=args.run_id)
        return 0

    if args.command == "expansion":
        from .historical_expansion_pipeline import run_historical_expansion

        run_historical_expansion(cfg, run_id=args.run_id)
        return 0

    if args.command == "precision":
        from .historical_precision_pipeline import run_historical_precision

        run_historical_precision(cfg, run_id=args.run_id)
        return 0

    if args.command == "revision":
        from .historical_revision_pipeline import run_historical_revision

        run_historical_revision(cfg, run_id=args.run_id)
        return 0

    if args.command == "pilot":
        from .historical_pilot_pipeline import run_historical_pilot

        run_historical_pilot(cfg, run_id=args.run_id)
        return 0

    from .pipeline import run_all

    do_render = args.command in ("all", "render")
    run_all(cfg, run_id=args.run_id, do_render=do_render)
    return 0


if __name__ == "__main__":
    sys.exit(main())

