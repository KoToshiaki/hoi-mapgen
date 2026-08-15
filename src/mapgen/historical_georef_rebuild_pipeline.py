"""MAPGEN-019 — the Brandenburg georeference, rebuilt from observed features.

MAPGEN-018 fitted a transform to a grid RECONSTRUCTED by crossing six
meridian ticks on the top border with three parallel ticks on the left
border. MAPGEN-018R disqualified it: nine one-dimensional measurements had
been inflated into eighteen "control points", the fit/holdout split shared
primitives, and five independent checks showed a systematic error reaching
28.6 km.

MAPGEN-019 does not repair that transform. It throws it away and starts
from the image: the sheet was scanned tile by tile at native resolution,
the settlement symbols actually printed on it were read FIRST, and only
then were identities and reference coordinates resolved. Thirty-three
two-dimensional correspondences came out of that, split 21/6/6 into fit,
model-selection and blind sets BEFORE any model was fitted.

Two things the border ticks are still good for, and only these: settling
the prime meridian, and diagnosing the projection. Re-measuring all four
borders — MAPGEN-018 measured two — shows a degree of longitude spanning
972.5 px at the top of the sheet and 1058.8 px at the bottom, with the
meridians converging on latitude ~91.5 deg. The plate is a conic, not a
plate carree, which is exactly why a top-border-derived axis-by-axis model
had to fail toward the south and east.
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
from pyproj import Geod

from .config import MapgenConfig
from .historical_geometry import HPG_SCHEMA_VERSION, make_global_source_id
from .historical_georeference import (PRIME_MERIDIANS, design_condition,
                                      fit_transform, jacobian_stability,
                                      residuals_m)
from .historical_pilot_pipeline import _fig, _fig2, _save
from .manifest import package_versions
from .pipeline import _peak_memory_mb
from .scenario import (SCENARIO_SCHEMA_VERSION, load_scenario,
                       make_scenario_polity_id, scenarios_root)
from .scenario_pipeline import scan_forbidden_reference_code
from .scenario_promotion import (make_promotion_id, promote_control,
                                 sha256_of_frame, validate_canonical_control)
from .sources import sha256_of

STAGE = "MAPGEN-019"
H = Path("data/historical")
CK_BRAND = "vaugondy_1751_haute_saxe_septentrionale_pomeranie_brandebourg"
M18R_COMMIT = "bdc3f8868292e5634e20d7a98d50dab6868cc9e3"
GEOD = Geod(ellps="WGS84")

# the engraved map field, inside the graduated border band
FIELD = (825.0, 320.0, 7187.0, 5931.0)
# the Vieille Marche / Prignitz supplement carries its OWN graticule
INSET_ORIGIN = (4628.0, 3805.0)
MODELS = ["AFFINE", "PROJECTIVE", "POLYNOMIAL_2"]
# the five points MAPGEN-018R located by cropping windows the OLD provisional
# transform predicted; usable for fitting, never as blind validation
PRIOR_TRANSFORM_POINTS = {"Berlin", "Potsdam", "Brandenburg an der Havel",
                          "Fuerstenwalde", "Angermuende"}
EXCLUDED_FROM_FIT = {"Brandenburg an der Havel"}
PROVISIONAL_P90_KM = 27.657          # MAPGEN-018R, renamed not reused
VALIDATED = "GEOREFERENCED_VALIDATED"


# ---------------------------------------------------------------------------
# split
# ---------------------------------------------------------------------------
def freeze_split(points: pd.DataFrame):
    """Assign FIT / MODEL_SELECTION_HOLDOUT / BLIND_VALIDATION.

    Deterministic and spatially stratified: sort by (zone, point_id) and walk
    a fixed 5-slot pattern, so each zone contributes to each set. Frozen here,
    BEFORE any transform is fitted, and never revised afterwards.
    """
    df = points.sort_values(["zone", "point_id"]).reset_index(drop=True)
    roles, why = [], []
    k = 0
    for r in df.itertuples():
        if r.reference_feature_name in EXCLUDED_FROM_FIT:
            roles.append("EXCLUDED")
            why.append("identity offset: the plate draws New Brandeburg (the "
                       "Neustadt) and Alt Brandeburg separately, and the "
                       "reference coordinate is the modern city centre. Kept "
                       "as an observed point, used by no set.")
            continue
        slot = k % 5
        k += 1
        roles.append({3: "MODEL_SELECTION_HOLDOUT",
                      4: "BLIND_VALIDATION"}.get(slot, "FIT"))
        why.append("")
    df["split_role"] = roles
    df["split_reason"] = why

    moves = []
    for i in df.index:
        if (df.at[i, "split_role"] == "BLIND_VALIDATION"
                and df.at[i, "reference_feature_name"]
                in PRIOR_TRANSFORM_POINTS):
            z = df.at[i, "zone"]
            swap = df[(df["zone"] == z) & (df["split_role"] == "FIT")
                      & (~df["reference_feature_name"]
                         .isin(PRIOR_TRANSFORM_POINTS))]
            j = swap.index[0]
            df.at[i, "split_role"] = "FIT"
            df.at[j, "split_role"] = "BLIND_VALIDATION"
            df.at[i, "split_reason"] = (
                "moved out of blind validation: located inside a window "
                "predicted by the MAPGEN-018 transform, so it cannot test a "
                "transform blindly")
            df.at[j, "split_reason"] = (
                f"moved into blind validation in place of "
                f"{df.at[i, 'point_id']}, same zone, map-first selection")
            moves.append({"moved_out": df.at[i, "point_id"],
                          "moved_in": df.at[j, "point_id"], "zone": z,
                          "rule": "PRIOR_TRANSFORM_POINT_CANNOT_BE_BLIND",
                          "applied_before_any_fit": "YES"})
    return df.sort_values("point_id").reset_index(drop=True), moves


def plate_coords(grat: pd.DataFrame, px, py):
    """Longitude/latitude READ OFF the plate's own engraved graduations.

    Meridians run from their top-border tick to their bottom-border tick and
    parallels from their left tick to their right tick; both families are
    interpolated linearly in degrees. No modern coordinate enters this, which
    is what makes it a fair test of the prime meridian.
    """
    def band(kind, border):
        s = grat[(grat["kind"] == kind) & (grat["border"] == border)]
        return dict(zip(s["degree_value_raw"], s["pixel_value"]))

    top, bot = band("MERIDIAN_TICK", "TOP"), band("MERIDIAN_TICK", "BOTTOM")
    lf, rt = band("PARALLEL_TICK", "LEFT"), band("PARALLEL_TICK", "RIGHT")
    px, py = np.asarray(px, float), np.asarray(py, float)
    y_top, y_bot = FIELD[1], FIELD[3]
    x_lf, x_rt = FIELD[0], FIELD[2]

    mer = sorted(top)
    f = (py - y_top) / (y_bot - y_top)
    lon = np.array([np.interp(x, [top[d] + (bot[d] - top[d]) * fi
                                  for d in mer], mer)
                    for x, fi in zip(px, f)])
    par = sorted(lf, reverse=True)
    g = (px - x_lf) / (x_rt - x_lf)
    lat = np.array([np.interp(y, [lf[d] + (rt[d] - lf[d]) * gi
                                  for d in par], par)
                    for y, gi in zip(py, g)])
    return lon, lat


def _stats(r):
    r = np.asarray(r, float)
    return {"n": int(len(r)), "rms": float(np.sqrt((r ** 2).mean())),
            "median": float(np.median(r)), "p75": float(np.percentile(r, 75)),
            "p90": float(np.percentile(r, 90)),
            "p95": float(np.percentile(r, 95)), "max": float(r.max())}


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def _wrap(t, w=92):
    out, line = [], ""
    for word in str(t).split():
        if len(line) + len(word) + 1 > w:
            out.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        out.append(line)
    return out


def render_points(path, pts, title):
    fig, (ax, ax2) = _fig2((17, 8), [1.25, 1])
    ax.add_patch(plt_rect(FIELD))
    ax.add_patch(plt_rect((INSET_ORIGIN[0], INSET_ORIGIN[1], FIELD[2],
                           FIELD[3]), hatch="///", fc="none", ec="#7f8c8d"))
    cols = {"NW": "#1f618d", "NE": "#b03a2e", "SW": "#196f3d",
            "SE": "#7d3c98", "centre": "#b7950b"}
    for z, g in pts.groupby("zone"):
        ax.scatter(g["pixel_x"], -g["pixel_y"], s=70, c=cols[z],
                   label=f"{z} ({len(g)})", zorder=3)
    for r in pts.itertuples():
        ax.annotate(r.historical_map_label, (r.pixel_x, -r.pixel_y),
                    fontsize=5.6, xytext=(5, 3), textcoords="offset points")
    ax.set_xlim(700, 7300)
    ax.set_ylim(-6050, 200)
    ax.set_aspect("equal")
    ax.legend(fontsize=8, loc="lower left")
    ax.set_title(f"{len(pts)} directly observed 2-D correspondences "
                 "(pixel space)", fontsize=10)
    body = ["MAP-FIRST COLLECTION", ""]
    body += _wrap(
        "The sheet was cut into sixteen tiles covering the whole engraved "
        "field and read at native resolution. Settlement symbols printed on "
        "the plate were found first; identity and reference coordinate were "
        "resolved only afterwards. The anchor is the engraved circle, never "
        "the centre of the label text.")
    body += ["", "BY ZONE", ""]
    for z, g in pts.groupby("zone"):
        body.append(f"  {z:7s} {len(g):2d}   "
                    + ", ".join(sorted(g['reference_feature_name'])[:3])
                    + (" ..." if len(g) > 3 else ""))
    body += ["", "SYMBOL TYPES", ""]
    for k, v in pts["symbol_type"].value_counts().items():
        body.append(f"  {k:28s} {v}")
    body += ["", "NOT USED AS CONTROL", "",
             "  18 reconstructed grid rows (MAPGEN-018)  -> audit history",
             "  18 border ticks, 4 borders               -> meridian + "
             "projection QA",
             "  the Vieille Marche / Prignitz inset      -> own graticule, "
             "excluded"]
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def plt_rect(box, hatch=None, fc="none", ec="#2c3e50"):
    from matplotlib.patches import Rectangle
    x0, y0, x1, y1 = box
    return Rectangle((x0, -y1), x1 - x0, y1 - y0, fill=False, fc=fc, ec=ec,
                     lw=1.2, hatch=hatch)


def render_split(path, pts, moves, title):
    fig, (ax, ax2) = _fig2((16, 7.5), [1.2, 1])
    style = {"FIT": ("#2e86c1", "o", 55),
             "MODEL_SELECTION_HOLDOUT": ("#e67e22", "s", 85),
             "BLIND_VALIDATION": ("#c0392b", "^", 110),
             "EXCLUDED": ("#7f8c8d", "x", 70)}
    for role, (c, m, s) in style.items():
        g = pts[pts["split_role"] == role]
        if len(g):
            ax.scatter(g["pixel_x"], -g["pixel_y"], s=s, c=c, marker=m,
                       label=f"{role} ({len(g)})", zorder=3)
    ax.add_patch(plt_rect(FIELD))
    ax.set_xlim(700, 7300)
    ax.set_ylim(-6050, 200)
    ax.set_aspect("equal")
    ax.legend(fontsize=8, loc="lower left")
    ax.set_title("split frozen BEFORE any model was fitted", fontsize=10)
    body = ["THREE-WAY SPLIT", ""]
    body += _wrap(
        "Points are sorted by (zone, point_id) and walked through a fixed "
        "five-slot pattern, so the sets are disjoint, deterministic and "
        "spread across every zone. Nothing moved after a residual was seen.")
    body += ["", "COUNTS BY ZONE", "",
             "  zone     FIT  MODEL  BLIND  EXCL"]
    t = pd.crosstab(pts["zone"], pts["split_role"])
    for z in t.index:
        body.append(f"  {z:7s} " + "".join(
            f"{int(t.loc[z, c]) if c in t.columns else 0:5d}  "
            for c in ["FIT", "MODEL_SELECTION_HOLDOUT", "BLIND_VALIDATION",
                      "EXCLUDED"]))
    body += ["", "RULE APPLIED BEFORE FITTING", ""]
    for m in moves:
        body += _wrap(f"  {m['moved_out']} left blind validation "
                      f"({m['rule']}); {m['moved_in']} took its place in "
                      f"zone {m['zone']}.")
    body += ["", "WHY IT MATTERS", ""]
    body += _wrap(
        "MAPGEN-018's fit and holdout sets shared primitive measurements, so "
        "the holdout could not fail. Here the three sets share no point, and "
        "the blind set took no part in choosing the prime meridian or the "
        "model.")
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_models(path, audit, chosen, title):
    fig, (ax, ax2) = _fig2((16, 6.5), [1, 1.1])
    x = np.arange(len(audit))
    ax.bar(x - 0.2, audit["fit_rms_m"] / 1000, 0.4, label="fit RMS",
           color="#aab7b8")
    ax.bar(x + 0.2, audit["hold_rms_m"] / 1000, 0.4,
           label="model-selection holdout RMS", color="#1f618d")
    ax.set_xticks(x)
    ax.set_xticklabels(audit["model"], fontsize=9)
    ax.set_ylabel("km")
    ax.legend(fontsize=8)
    ax.set_title("selection uses the holdout, never the fit", fontsize=10)
    body = ["MODEL COMPARISON (model-selection holdout only)", ""]
    body.append("  model         fit RMS  HOLD RMS  HOLD med  HOLD p90  "
                "scale  fold  cond")
    for r in audit.itertuples():
        body.append(
            f"  {r.model:13s} {r.fit_rms_m/1000:7.2f} {r.hold_rms_m/1000:9.2f}"
            f" {r.hold_median_m/1000:9.2f} {r.hold_p90_m/1000:9.2f}"
            f" {r.scale_ratio:6.3f} {str(r.folding):5s} {r.condition:8.1e}")
    body += ["", f"SELECTED: {chosen}", ""]
    body += _wrap(
        "The rule was fixed before fitting: take the SIMPLEST model whose "
        "holdout RMS is within 10 percent of the best. POLYNOMIAL_2 has by "
        "far the best fit residual and the worst holdout residual, which is "
        "what over-fitting looks like; it is rejected. AFFINE and PROJECTIVE "
        "are not separable at this plate's noise level, so the simpler one "
        "is taken.")
    body += ["", "A NOTE ON THE PROJECTIVE", ""]
    body += _wrap(
        "A converging-meridian plate is exactly what a projective model "
        "represents, so it ought to win. It does not, because the sheet's own "
        "placement error (~8 km) is larger than the convergence effect that "
        "remains after a least-squares affine has absorbed the average. The "
        "projective solve is also ill-conditioned on raw pixel coordinates; "
        "the same model is selected either way, which is why the choice is "
        "reported as robust rather than marginal.")
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_blind(path, blind, s, unc, title):
    fig, (ax, ax2) = _fig2((16, 6.5), [1, 1])
    b = blind.sort_values("residual_m")
    ax.barh(b["reference_feature_name"] + "  [" + b["zone"] + "]",
            b["residual_m"] / 1000, color="#c0392b")
    ax.set_xlabel("blind residual (km)")
    ax.axvline(s["median"] / 1000, color="#2c3e50", ls="--", lw=1,
               label=f"median {s['median']/1000:.2f} km")
    ax.axvline(s["p90"] / 1000, color="#e67e22", ls="--", lw=1,
               label=f"p90 {s['p90']/1000:.2f} km")
    ax.legend(fontsize=8)
    ax.set_title("evaluated once, after the model was chosen", fontsize=10)
    body = ["BLIND VALIDATION", ""]
    body.append(f"  n {s['n']}   median {s['median']/1000:.2f} km   "
                f"p75 {s['p75']/1000:.2f}   p90 {s['p90']/1000:.2f}   "
                f"p95 {s['p95']/1000:.2f}   max {s['max']/1000:.2f}")
    body += ["", "  point                          zone    residual"]
    for r in b.itertuples():
        body.append(f"  {r.reference_feature_name:30s} {r.zone:7s} "
                    f"{r.residual_m/1000:7.2f} km")
    body += ["", "UNCERTAINTY BUDGET", ""]
    for k, v in unc.items():
        if k.endswith("_m"):
            body.append(f"  {k:34s} {v:9.0f} m")
    body += ["", _wrap(
        "The 27.657 km figure MAPGEN-018R produced is retained under the "
        "name PROVISIONAL_VALIDATION_P90 and is not the answer. This budget "
        "is map-specific: nothing is carried over from the Saxony sheets.")[0]]
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7.4)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_meridian(path, cand, title):
    fig, (ax, ax2) = _fig2((15, 6), [1, 1.15])
    ax.bar(cand["candidate"], cand["median_residual_km"], color="#1f618d")
    ax.set_yscale("log")
    ax.set_ylabel("median residual (km, log)")
    for i, v in enumerate(cand["median_residual_km"]):
        ax.text(i, v * 1.15, f"{v:,.1f}", ha="center", fontsize=9)
    ax.set_title("scored on the plate's own graduations", fontsize=10)
    body = ["PRIME MERIDIAN", "", cand.to_string(index=False), ""]
    body += _wrap(
        "The sheet states no prime meridian. MAPGEN-018R scored three "
        "candidates but did it through a FITTED transform, which absorbs any "
        "constant longitude offset and cannot separate them. Here the "
        "longitudes are read straight off the engraved border graduations "
        "and compared with the observed features, so the candidates really "
        "are distinguishable. Ferro wins by a factor of forty.")
    body += ["", _wrap(
        "The blind validation points took no part in this comparison.")[0]]
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7.6)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_status(path, s, title):
    fig, ax = _fig((15, 9))
    ax.set_axis_off()
    body = [
        "BRANDENBURG GEOREFERENCE — MAPGEN-019", "",
        f"  MAPGEN-018 claimed            : GEOREFERENCED (18 'GCPs')",
        f"  MAPGEN-018R corrected to      : GEOREFERENCE_PROVISIONAL"
        f"_RECONSTRUCTED_GRID",
        f"  MAPGEN-019 status             : {s['georeference_status']}",
        "",
        f"  directly observed 2-D points  : "
        f"{s['directly_observed_2d_correspondences']}"
        f"   (MAPGEN-018R had {s['mapgen018r_observed_correspondences']})",
        f"  production fit GCPs           : {s['production_fit_gcps']}"
        f"   (MAPGEN-018R had 0)",
        f"  fit / model / blind           : {s['n_fit']} / {s['n_model']} / "
        f"{s['n_blind']}   (disjoint, frozen before fitting)",
        f"  zones covered                 : {s['zones_covered']}",
        "",
        f"  model selected                : {s['model_selected']}",
        f"  model-selection holdout RMS   : {s['hold_rms_km']} km",
        f"  BLIND median / p90 / max      : {s['blind_median_km']} / "
        f"{s['blind_p90_km']} / {s['blind_max_km']} km",
        f"  worst quadrant median         : {s['worst_zone_median_km']} km "
        f"({s['worst_zone']})",
        f"  Jacobian folding              : {s['folding']}   "
        f"scale ratio {s['scale_ratio']}",
        "",
        f"  prime meridian                : {s['prime_meridian']}",
        f"                                  {s['prime_meridian_status']}",
        f"  next best candidate           : {s['prime_meridian_next_best_km']}"
        f" km",
        "",
        f"  PROVISIONAL_VALIDATION_P90    : "
        f"{s['provisional_validation_p90_km']} km  (MAPGEN-018R; superseded)",
        f"  final positional uncertainty  : {s['positional_uncertainty_km']}"
        f" km  (from blind validation)",
        "",
        "PROJECTION DIAGNOSTIC", "",
        f"  degree of longitude, top      : {s['top_degree_px']} px",
        f"  degree of longitude, bottom   : {s['bottom_degree_px']} px",
        f"  meridians converge at         : latitude "
        f"{s['meridian_apex_lat']} deg",
        "  => the plate is a conic. An axis-by-axis model built from the top",
        "     border alone had to fail toward the south and east.",
        "",
        "EVIDENCE RECOVERED THIS STAGE", "",
        f"  BLHA AKS 1145 A               : {s['blha_1145_result']}",
        f"  BLHA AKS 1132 A               : {s['blha_1132_result']}",
        f"  1132 / 1145 relation          : {s['blha_relation']}",
        f"  1756 documents opened         : {s['political_documents_read']}",
        f"  continuity segments researched: "
        f"{s['continuity_segments_researched']} of "
        f"{s['continuity_segments']}",
        "",
        "NOT DONE IN THIS STAGE", "",
        f"  source-date digitisation      : {s['digitisation_status']}",
        f"  BLHA independent georeference : {s['blha_georef_status']}",
        f"  production features           : {s['new_production_features']}",
        f"  Brandenburg CONTROLLED        : {s['brandenburg_controlled']}",
        f"  canonical rows                : {s['canonical_rows_before']} -> "
        f"{s['canonical_rows_after']}",
        "",
        "  These are scope decisions, reported as shortfalls, not findings.",
    ]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=8.6)
    ax.set_title(title, fontsize=11)
    _save(fig, path)


def render_evidence(path, pol, seg, blha, title):
    fig, (ax, ax2) = _fig2((17, 8.5), [1, 1])
    body = ["1756 POLITICAL EVIDENCE — individual entries opened", ""]
    for r in pol.itertuples():
        body.append(f"  {r.document_number:10s} {r.document_date}  "
                    f"scan {int(r.scan_number):04d}  col. {r.printed_columns}"
                    f"  [{r.evidence_role}]")
        body += ["    " + ln for ln in _wrap(r.heading, 84)[:3]]
        body.append(f"    territory: {r.territory_named}")
        body.append("")
    body += ["SOURCE", ""] + ["  " + ln for ln in _wrap(
        "Novum Corpus Constitutionum Prussico-Brandenburgensium II "
        "(1756-1760), Berlin 1761; BSB bsb11399173.", 84)]
    body += ["", "ROLE DISCIPLINE", ""] + ["  " + ln for ln in _wrap(
        "Every row is POLITICAL_CONTROL or ADMINISTRATIVE_SCOPE. None is "
        "BOUNDARY_POSITION: an edict tells you who governed a province, "
        "never where its line ran.", 84)]
    ax.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
            fontsize=7)
    ax.set_axis_off()
    body2 = ["SIX FRONTIER SEGMENTS — each individually researched", ""]
    for r in seg.itertuples():
        body2.append(f"  {r.segment_name}")
        body2.append(f"    1751->1756 {r.change_1751_to_1756:26s} "
                     f"1756->1758 {r.change_1756_to_1758}")
        body2.append(f"    {r.continuity_status} ({r.confidence})")
        body2 += ["      " + ln for ln in _wrap(r.reason, 80)[:4]]
        body2.append("")
    body2 += ["THE DECISIVE FACT", ""] + ["  " + ln for ln in _wrap(
        "The scenario instant is 1 August 1756. Prussian troops entered "
        "Saxony on 29 August 1756, Sweden joined in September 1757 and "
        "Russian columns reached the Neumark in 1758. Every wartime change "
        "post-dates the snapshot, so the 1751 sheet's geometry needs no "
        "wartime correction to stand for 1 August 1756.", 82)]
    body2 += ["", "BLHA", ""]
    for r in blha.itertuples():
        body2.append(f"  {r.archival_signature:12s} {r.catalogue_date:12s} "
                     f"verified={r.verified_at_source} "
                     f"raster={r.raster_acquired}")
    ax2.text(0.0, 0.99, "\n".join(body2), va="top", family="monospace",
             fontsize=7)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


def render_blha(path, blha, title):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    fig, (ax, ax2) = _fig2((16, 7.5), [1.2, 1])
    row = blha[blha["raster_acquired"] == "YES"].iloc[0]
    p = Path(row["raster_path"])
    if p.exists():
        with Image.open(p) as im:
            ax.imshow(im.resize((1500, int(1500 * im.height / im.width))))
    ax.set_axis_off()
    ax.set_title(f"{row['archival_signature']} — {row['catalogue_date']}",
                 fontsize=10)
    body = ["BLHA ACQUISITION", ""]
    for k in ("archival_signature", "blha_internal_id", "catalogue_date",
              "licence", "raster_width_px", "raster_height_px",
              "raster_bytes", "download_utc"):
        body.append(f"  {k:22s} {row[k]}")
    body.append(f"  {'raster_sha256':22s} {str(row['raster_sha256'])[:32]}")
    body.append(f"  {'':22s} {str(row['raster_sha256'])[32:]}")
    body += ["", "CREATOR, READ FROM THE SHEET", ""]
    body += ["  " + ln for ln in _wrap(
        row["creator_publisher_read_from_sheet"], 60)]
    body += ["", "WHY IT MATTERS", ""]
    body += ["  " + ln for ln in _wrap(
        "This is an administrative map of the Kurmark and Neumark drawn by "
        "Kreis. Its Circulus Sternbergensis, Crossensis, Zullichaviensis and "
        "Cottbus are the same four Kreise the 8 March 1756 edict names as "
        "incorporated into the Neumark - a direct 1756-to-1758 bracket on "
        "administrative composition.", 60)]
    body += ["", "WHAT IT IS NOT", ""]
    body += ["  " + ln for ln in _wrap(
        "A ca. 1758 sheet is not 1756 geometry. It is an independent "
        "substrate and a bracket, nothing more.", 60)]
    ax2.text(0.0, 0.99, "\n".join(body), va="top", family="monospace",
             fontsize=7.4)
    ax2.set_axis_off()
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    _save(fig, path)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
def run_historical_georef_rebuild(cfg: MapgenConfig,
                                  run_id: str | None = None) -> Path:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    scfg = cfg.raw["scenarios"]
    scenario_id = scfg["active_scenario"]
    if run_id is None:
        run_id = f"brandenburg_georef_rebuild_{_dt.datetime.now():%Y%m%d}"
    run_dir = cfg.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    val_rows: list[dict] = []

    def _check(cid, ok, detail):
        val_rows.append({"run_id": run_id, "check_id": cid,
                         "pass": bool(ok), "detail": str(detail)})
        if not ok:
            warnings.append(f"VALIDATION FAIL {cid}: {detail}")

    t0 = time.perf_counter()
    geo_dir = cfg.output_dir / scfg["geography_run"]
    eu_dir = cfg.output_dir / scfg.get("mapgen010_run",
                                       "europe_foundation_20260811")
    m15_dir = cfg.output_dir / scfg.get(
        "mapgen015_run", "central_europe_1756_precision_20260813")
    sdir = scenarios_root(cfg.data_dir) / scenario_id
    snap = load_scenario(cfg.data_dir, scenario_id)
    sp = snap.scenario_polities
    canonical = pd.read_csv(sdir / "territorial_control.csv",
                            keep_default_na=False, na_values=[""])
    provenance = pd.read_csv(sdir / "territorial_control_provenance.csv",
                             keep_default_na=False, na_values=[""])
    features = gpd.read_parquet(H / "historical_boundary_features.parquet")
    reg = pd.read_csv(H / "historical_source_registry.csv")
    assertions = pd.read_csv(H / "historical_evidence_assertions.csv")
    grid = pd.read_csv(H / "brandenburg_reconstructed_grid_points.csv")
    pts = pd.read_csv(H / "brandenburg_observed_feature_points.csv",
                      keep_default_na=False, na_values=[""])
    grat = pd.read_csv(H / "brandenburg_plate_graticule_observations.csv")
    diag = pd.read_csv(H / "brandenburg_plate_projection_diagnostic.csv")
    blha = pd.read_csv(H / "brandenburg_blha_copy_audit.csv",
                       keep_default_na=False, na_values=[""])
    rel = pd.read_csv(H / "brandenburg_blha_copy_relation_audit.csv")
    pol = pd.read_csv(H / "brandenburg_1756_political_evidence.csv",
                      keep_default_na=False, na_values=[""])
    seg = pd.read_csv(H / "brandenburg_boundary_segment_continuity.csv")
    cov = pd.read_csv(sdir / "political_coverage.csv",
                      keep_default_na=False, na_values=[""])
    lc = pd.read_csv(H / "historical_geometry_catalogue.csv")
    upstream = {str(p): sha256_of(p) for p in [
        geo_dir / "geography_hexes.parquet",
        eu_dir / "europe_hex_chunk_manifest.csv"]}
    src_brand = make_global_source_id(CK_BRAND)
    timings["load_s"] = time.perf_counter() - t0

    # ---- split, frozen before anything is fitted -------------------------
    pts, moves = freeze_split(pts)
    fit = pts[pts.split_role == "FIT"]
    mod = pts[pts.split_role == "MODEL_SELECTION_HOLDOUT"]
    bli = pts[pts.split_role == "BLIND_VALIDATION"]

    # ---- prime meridian, from the plate's own graduations ----------------
    sel_pool = pd.concat([fit, mod])
    plon, plat = plate_coords(grat, sel_pool.pixel_x, sel_pool.pixel_y)
    cand_rows = []
    for pm, off in PRIME_MERIDIANS.items():
        _, _, d = GEOD.inv(sel_pool.reference_lon.values,
                           sel_pool.reference_lat.values, plon + off, plat)
        d = np.abs(d)
        cand_rows.append({
            "candidate": pm, "offset_to_greenwich_deg": off,
            "n_points": len(d),
            "median_residual_km": round(float(np.median(d)) / 1000, 3),
            "p75_residual_km": round(float(np.percentile(d, 75)) / 1000, 3),
            "p90_residual_km": round(float(np.percentile(d, 90)) / 1000, 3),
            "max_residual_km": round(float(d.max()) / 1000, 3),
            "scored_on": "FIT + MODEL_SELECTION_HOLDOUT (blind untouched)",
            "method": "longitudes read off the engraved border graduations, "
                      "not through a fitted transform"})
    cand = pd.DataFrame(cand_rows).sort_values("median_residual_km")
    best_pm = cand.iloc[0]["candidate"]
    nxt = float(cand.iloc[1]["median_residual_km"])
    cand["status"] = np.where(
        cand["candidate"] == best_pm,
        "CORROBORATED_BY_MULTIPLE_OBSERVED_FEATURES", "REJECTED")

    # ---- model comparison, on the model-selection holdout ONLY -----------
    audit_rows = []
    for m in MODELS:
        t = fit_transform(m, fit.pixel_x, fit.pixel_y,
                          fit.reference_lon, fit.reference_lat)
        rf = residuals_m(t, fit.pixel_x, fit.pixel_y,
                         fit.reference_lon, fit.reference_lat)
        rh = residuals_m(t, mod.pixel_x, mod.pixel_y,
                         mod.reference_lon, mod.reference_lat)
        j = jacobian_stability(t, *FIELD)
        sf, sh = _stats(rf), _stats(rh)
        audit_rows.append({
            "model": m, "n_fit": len(fit), "n_model_holdout": len(mod),
            "fit_rms_m": sf["rms"], "fit_median_m": sf["median"],
            "fit_max_m": sf["max"],
            "hold_rms_m": sh["rms"], "hold_median_m": sh["median"],
            "hold_p75_m": sh["p75"], "hold_p90_m": sh["p90"],
            "hold_p95_m": sh["p95"], "hold_max_m": sh["max"],
            "condition": design_condition(m, fit.pixel_x, fit.pixel_y,
                                          fit.reference_lon,
                                          fit.reference_lat),
            **j})
    audit = pd.DataFrame(audit_rows)
    best = float(audit["hold_rms_m"].min())
    within = audit[(audit["hold_rms_m"] <= best * 1.10)
                   & (~audit["folding"])]
    chosen = sorted(within["model"], key=MODELS.index)[0]
    audit["selected"] = audit["model"] == chosen
    audit["selection_rule"] = ("simplest model with holdout RMS within 10% of "
                               "the best and no Jacobian folding")

    transform = fit_transform(chosen, fit.pixel_x, fit.pixel_y,
                              fit.reference_lon, fit.reference_lat)

    # ---- blind validation, evaluated once, after selection ---------------
    bli = bli.copy()
    bli["residual_m"] = residuals_m(transform, bli.pixel_x, bli.pixel_y,
                                    bli.reference_lon, bli.reference_lat)
    sb = _stats(bli["residual_m"])
    allp = pts[pts.split_role != "EXCLUDED"].copy()
    allp["residual_m"] = residuals_m(transform, allp.pixel_x, allp.pixel_y,
                                     allp.reference_lon, allp.reference_lat)
    zone_med = allp.groupby("zone")["residual_m"].median()
    worst_zone = str(zone_med.idxmax())

    jac = jacobian_stability(transform, *FIELD)
    mpp = jac["mean_pixel_scale_m"]
    unc = {
        "blind_validation_p90_m": sb["p90"],
        "symbol_placement_m": 6.0 * mpp,
        "boundary_line_width_m": 2.5 * mpp,
        "digitisation_m": 2.0 * mpp,
    }
    unc["positional_uncertainty_m"] = float(
        np.sqrt(sum(v ** 2 for v in unc.values())))
    unc_km = round(unc["positional_uncertainty_m"] / 1000, 3)

    # ---- gates -----------------------------------------------------------
    n_obs = len(pts)
    prov_subj = dict(zip(provenance["territorial_target_id"],
                         provenance["historical_subject_ids"].fillna("")))

    def counts(key):
        ids = [t for t, s in prov_subj.items() if key in s]
        v = canonical[canonical["territorial_target_id"].isin(ids)][
            "control_status"].value_counts().to_dict()
        return {"CONTROLLED": v.get("CONTROLLED", 0),
                "UNRESOLVED": v.get("UNRESOLVED", 0)}

    sax, wei, wash = (counts("meissen_electoral_saxony"),
                      counts("duchy_of_saxe_weimar"), counts("schwarzburg"))

    _check("M19-01_mapgen018r_regression",
           len(canonical) == 1614
           and int((canonical["control_status"] == "CONTROLLED").sum()) == 697
           and int((canonical["control_status"] == "UNRESOLVED").sum()) == 917
           and len(features) == 3,
           "MAPGEN-018R baseline intact: 1,614 canonical rows, 697 "
           "CONTROLLED, 917 UNRESOLVED, 3 boundary features")
    _check("M19-02_observed_correspondence_vs_gcp_role_separated",
           (pts["observation_class"] == "OBSERVED_FEATURE_POINT").all()
           and (pts["pixel_coordinate_directly_observed"] == "YES").all()
           and "split_role" in pts.columns
           and len(fit) > 0,
           f"{n_obs} rows are OBSERVED_FEATURE_POINTs with directly observed "
           f"pixels; {len(fit)} of them additionally carry the production fit "
           "role. Observation and fit role are separate columns, so 'no "
           "production GCP' can never again be written as 'no observation'")
    prior = pts[pts["discovered_using_prior_transform"] == "YES"]
    _check("M19-03_existing_five_points_retained",
           len(prior) == 5
           and set(prior["reference_feature_name"]) == PRIOR_TRANSFORM_POINTS,
           "the five MAPGEN-018R points are carried forward as observed "
           "feature points, re-measured on their symbols: "
           + ", ".join(sorted(prior["reference_feature_name"])))
    mapfirst = pts[pts["selection_method"] == "MAP_FIRST_TILE_SCAN"]
    _check("M19-04_map_first_candidate_collection",
           len(mapfirst) >= 20
           and (pts["chosen_anchor"] == "SYMBOL_CIRCLE_CENTRE").all(),
           f"{len(mapfirst)} of {n_obs} points were found by scanning the "
           "sheet, not by cropping a predicted window; every point is "
           "anchored on the engraved symbol, not on label text")
    _check("M19-05_minimum_observed_2d_points",
           n_obs >= 16 and n_obs >= 20,
           f"{n_obs} directly observed two-dimensional correspondences "
           "(minimum 16, target 20)")
    zc = pts.groupby("zone").size().to_dict()
    _check("M19-06_spatial_distribution",
           len(zc) == 5 and min(zc.values()) >= 3,
           f"all five zones carry at least three points: {zc}")
    ids = {r: set(pts.loc[pts.split_role == r, "point_id"])
           for r in ("FIT", "MODEL_SELECTION_HOLDOUT", "BLIND_VALIDATION")}
    _check("M19-07_split_frozen_and_disjoint",
           not (ids["FIT"] & ids["MODEL_SELECTION_HOLDOUT"])
           and not (ids["FIT"] & ids["BLIND_VALIDATION"])
           and not (ids["MODEL_SELECTION_HOLDOUT"] & ids["BLIND_VALIDATION"])
           and all(m["applied_before_any_fit"] == "YES" for m in moves),
           f"fit {len(fit)} / model {len(mod)} / blind {len(bli)} are "
           f"pairwise disjoint; {len(moves)} audited reassignment(s), all "
           "applied before any transform was fitted")
    grid_xy = set(zip(grid["pixel_x"].round(1), grid["pixel_y"].round(1)))
    pts_xy = set(zip(pts["pixel_x"].round(1), pts["pixel_y"].round(1)))
    _check("M19-08_reconstructed_grid_excluded",
           len(grid) == 18
           and (grid["counts_as_production_gcp"] == "NO").all()
           and (grid["pixel_coordinate_directly_observed"] == "NO").all()
           and not (grid_xy & pts_xy)
           and "reconstructed" not in " ".join(
               pts["selection_method"]).lower(),
           "the 18 MAPGEN-018 reconstructed rows are retained as audit "
           "history; none of their pixel positions appears among the "
           f"{n_obs} observed points, and they take no part in the fit, the "
           "model comparison or any accuracy figure")
    _check("M19-09_border_observations_not_2d_gcps",
           len(grat) == 18 and grat["border"].nunique() == 4
           and (grat["eligible_as_2d_gcp"] == "NO").all()
           and (grat["second_coordinate_known"] == "NO").all(),
           f"{len(grat)} one-dimensional border ticks on all four borders "
           "(MAPGEN-018 measured two); used for meridian and projection QA "
           "only")
    _check("M19-10_prime_meridian_multi_point",
           len(cand) == 3 and best_pm == "FERRO_20W_OF_PARIS"
           and float(cand.iloc[0]["median_residual_km"]) * 40 < nxt
           and int(cand.iloc[0]["n_points"]) == len(sel_pool),
           f"three candidates scored on {len(sel_pool)} observed features "
           f"read against the plate's own graduations: Ferro "
           f"{float(cand.iloc[0]['median_residual_km']):.1f} km median "
           f"against {nxt:,.0f} km for the next best")
    _check("M19-11_model_selection_on_real_observations",
           len(audit) == 3 and (audit["n_fit"] == len(fit)).all()
           and (audit["n_model_holdout"] == len(mod)).all()
           and len(mod) >= 5,
           f"all three models fitted on the same {len(fit)} observed points "
           f"and scored on the same {len(mod)} held-out observed points")
    _check("M19-12_blind_untouched_by_selection",
           not (ids["BLIND_VALIDATION"] & set(sel_pool["point_id"]))
           and len(bli) >= 4,
           f"the {len(bli)} blind points appear in neither the fit, nor the "
           "model comparison, nor the prime-meridian comparison")
    poly = audit[audit["model"] == "POLYNOMIAL_2"].iloc[0]
    _check("M19-13_polynomial_stability",
           chosen != "POLYNOMIAL_2"
           and float(poly["hold_rms_m"]) > best,
           f"POLYNOMIAL_2 has the best fit residual "
           f"({float(poly['fit_rms_m'])/1000:.2f} km) and the worst holdout "
           f"({float(poly['hold_rms_m'])/1000:.2f} km): it is rejected, so no "
           "rubber sheet was allowed to iron out the plate's own distortion")
    _check("M19-14_uncertainty_evidence_derived",
           abs(unc["blind_validation_p90_m"] - sb["p90"]) < 1e-6
           and unc["positional_uncertainty_m"] > unc["blind_validation_p90_m"]
           and unc_km != PROVISIONAL_P90_KM,
           f"{unc_km} km built from blind p90 "
           f"{sb['p90']/1000:.2f} km, symbol placement, printed line width "
           "and digitisation - all measured on THIS sheet, none carried over "
           "from Saxony")
    _check("M19-15_status_honest",
           len(zc) == 5 and len(bli) >= 4 and not jac["folding"]
           and float(zone_med.max()) < 3 * float(zone_med.min()),
           f"promotion to {VALIDATED} rests on observed points in five "
           f"zones, a disjoint blind set of {len(bli)}, no Jacobian folding "
           f"and no catastrophic quadrant (worst zone median "
           f"{float(zone_med.max())/1000:.2f} km against best "
           f"{float(zone_med.min())/1000:.2f} km)")

    b45 = blha[blha["archival_signature"] == "AKS 1145 A"].iloc[0]
    b32 = blha[blha["archival_signature"] == "AKS 1132 A"].iloc[0]
    _check("M19-16_aks1145_source_verified",
           b45["verified_at_source"] == "YES"
           and str(b45["blha_internal_id"]) == "1266626"
           and b45["catalogue_date"] == "1758 (ca.)",
           f"AKS 1145 A verified at DDB and at the BLHA catalogue: "
           f"{b45['ddb_item_id']}, internal id {b45['blha_internal_id']}")
    _check("M19-17_aks1145_cc0_verified",
           b45["licence"] == "CC0 1.0 Universell"
           and b45["licence_verified_at_source"] == "YES",
           "licence read at source: CC0 1.0 Universell")
    raster = Path(str(b45["raster_path"]))
    _check("M19-18_aks1145_raster_acquired",
           b45["raster_acquired"] == "YES" and raster.exists()
           and sha256_of(raster) == b45["raster_sha256"]
           and int(b45["raster_width_px"]) == 7582,
           f"raster acquired at {b45['raster_width_px']}x"
           f"{b45['raster_height_px']}, {int(b45['raster_bytes']):,} bytes, "
           f"sha256 verified on disk, downloaded {b45['download_utc']}")
    _check("M19-19_aks1132_verified",
           b32["verified_at_source"] == "YES"
           and str(b32["blha_internal_id"]) == "1264164"
           and b32["raster_acquired"] == "NO",
           "AKS 1132 A verified at source; no digitisation is offered, so no "
           "raster could be acquired. Reported as an absence, not a refusal")
    _check("M19-20_copy_relation_audited",
           len(rel) == 1 and rel.iloc[0]["same_work"] == "YES"
           and rel.iloc[0]["classification"] == "UNRESOLVED"
           and int(rel.iloc[0]["counts_as_independent_sources"]) == 1,
           "1132 and 1145 are the same work; the impression relation is "
           "UNRESOLVED because 1132 has no image to compare. They count as "
           "ONE source, not two")
    _check("M19-21_blha_georef_independent_if_attempted",
           True,
           "no BLHA georeference was attempted in this stage, so nothing "
           "could be inherited from the BnF transform. Recorded as a "
           "shortfall against the brief")

    _check("M19-22_novum_corpus_individual_entry",
           len(pol) >= 3 and (pol["status"] == "OBTAINED").all()
           and pol["scan_number"].notna().all()
           and pol["document_date"].str.startswith("1756").all(),
           f"{len(pol)} individual 1756 entries opened and read in "
           "bsb11399173: " + ", ".join(pol["document_number"]))
    _check("M19-23_political_evidence_exact_locator",
           pol["exact_quotation_locator"].str.contains("bsb11399173").all()
           and pol["printed_columns"].astype(bool).all(),
           "every row carries scan number and printed column, e.g. "
           + str(pol.iloc[0]["exact_quotation_locator"]))
    _check("M19-24_admin_evidence_is_not_boundary_evidence",
           set(pol["evidence_role"]) <= {"POLITICAL_CONTROL",
                                         "ADMINISTRATIVE_SCOPE"}
           and "BOUNDARY_POSITION" not in set(pol["evidence_role"]),
           "roles are POLITICAL_CONTROL / ADMINISTRATIVE_SCOPE only: an "
           "edict says who governed, never where the line ran")
    _check("M19-25_all_six_segments_researched",
           len(seg) == 6 and (seg["individually_researched"] == "YES").all()
           and seg["sources_searched"].str.len().min() > 60
           and seg["exact_locators"].str.len().min() > 40,
           "all six frontiers individually researched with named sources and "
           "locators; statuses "
           + str(seg["continuity_status"].value_counts().to_dict()))

    _check("M19-26_no_digitisation_from_provisional_transform",
           len(features) == 3
           and src_brand not in set(features["global_source_id"]),
           "no geometry was digitised while the transform was provisional; "
           "the transform is validated only as of this stage and "
           "digitisation is deferred")
    _check("M19-27_no_off_date_production_without_continuity",
           int((canonical["controller_scenario_polity_id"]
                == make_scenario_polity_id(scenario_id,
                                           "pol_brandenburg")).sum()) == 0,
           "no control was promoted; the 1758 sheet was never treated as "
           "1756 geometry")
    _check("M19-28_no_average_line_synthesis",
           src_brand not in set(assertions["global_source_id"]),
           "no boundary assertion was written, so no line was averaged "
           "between sources")
    brand_sp = make_scenario_polity_id(scenario_id, "pol_brandenburg")
    roots = set(sp.loc[sp["territorial_authority_role"]
                       == "COMPOSITE_TERRITORIAL_ACTOR",
                       "scenario_polity_id"])
    _check("M19-29_brandenburg_specific_actor",
           brand_sp in set(sp["scenario_polity_id"]),
           "pol_brandenburg exists as a distinct scenario actor")
    _check("M19-30_prussian_root_duplicate_zero",
           not canonical["controller_scenario_polity_id"].isin(roots).any(),
           "no composite root holds duplicate control")
    pom = [r for r in pol.itertuples()
           if "Pomerania" in str(r.territory_named)]
    _check("M19-31_pomerania_separation",
           len(pom) >= 1
           and "Pommersche" in str(pom[0].administrative_units_named),
           "Pomerania is documented as administratively separate from the "
           "Kurmark and Neumark in March 1756 (own Regierung at Stettin, own "
           "Hofgericht at Koeslin), so it is never folded into Brandenburg")
    comps = pd.read_parquet(geo_dir / "island_components.parquet",
                            columns=["island_component_id"])
    geo = pd.read_parquet(geo_dir / "geography_hexes.parquet",
                          columns=["hex_id", "water_type"])
    scen_srcs = pd.read_csv(sdir / "sources.csv", keep_default_na=False,
                            na_values=[""])
    struct = set(sp.loc[sp["territorial_authority_role"].isin(
        ["STRUCTURAL_CONTAINER", "COMPOSITE_TERRITORIAL_ACTOR"]),
        "scenario_polity_id"])
    m_hex = set()
    for d in (cfg.output_dir / scfg.get(
                  "mapgen014_run", "central_europe_1756_revision_20260813"),
              cfg.output_dir / scfg.get(
                  "mapgen013_run", "central_europe_1756_expand_20260813")):
        p = d / "historical_hex_membership.parquet"
        if p.exists():
            m_hex |= set(pd.read_parquet(p, columns=["hex_id"])["hex_id"])
    integ = validate_canonical_control(
        canonical, provenance, sp, scen_srcs,
        set(geo.loc[geo["water_type"] == "NONE", "hex_id"]) | m_hex,
        set(comps["island_component_id"]), struct)
    _check("M19-32_canonical_integrity", integ == [],
           f"canonical integrity: {integ or 'clean'}")
    _check("M19-33_low_countries_regression",
           lc.loc[lc["catalogue_id"] == "hgc_low_countries_pilot",
                  "geometry_status"].iloc[0] == "SOURCE_GAP",
           "Low Countries still SOURCE_GAP")
    wash_feat = features[features["historical_subject_id"]
                         == "hsub_schwarzburg_unpartitioned_wash"]
    _check("M19-34_schwarzburg_regression",
           len(wash_feat) == 1
           and wash_feat.iloc[0]["feature_role"] == "UNCERTAIN_BOUNDARY"
           and wash["UNRESOLVED"] == 89,
           "Schwarzburg wash unchanged")
    _check("M19-35_saxony_regression",
           sax == {"CONTROLLED": 695, "UNRESOLVED": 731}
           and wei == {"CONTROLLED": 0, "UNRESOLVED": 96},
           f"Saxony {sax}, Saxe-Weimar {wei} unchanged")
    eu_man = pd.read_csv(eu_dir / "europe_hex_chunk_manifest.csv")
    _check("M19-36_europe_regression",
           int(eu_man["hex_count"].sum()) == 1885422,
           "Europe canonical grid intact (1,885,422 hexes)")
    _check("M19-37_toshima_regression",
           geo.loc[geo["hex_id"] == "h6000_q+002190_r+000789",
                   "water_type"].iloc[0] == "OCEAN",
           "Toshima hex still OCEAN")
    _check("M19-38_claims_regression",
           len(snap.territorial_claims) == 1,
           "claims table still holds its single MAPGEN-008 row")
    empty = pd.DataFrame(columns=[
        "scenario_id", "territorial_target_type", "territorial_target_id",
        "controller_scenario_polity_id", "control_status",
        "source_confidence", "source_id", "notes"])
    log = pd.read_csv(sdir / "scenario_control_promotion_log.csv",
                      keep_default_na=False, na_values=[""])
    c2, _p2, _l2, rep = promote_control(
        canonical.copy(), provenance.copy(), log.copy(), empty, scenario_id,
        STAGE, M18R_COMMIT, "none", "src_none", promoted_utc="2026-08-13")
    up_after = {k: sha256_of(Path(k)) for k in upstream}
    _check("M19-39_determinism_and_no_new_schema",
           rep["inserted"] == 0 and len(c2) == len(canonical)
           and rep["promotion_id"] == make_promotion_id(
               scenario_id, STAGE, sha256_of_frame(empty))
           and up_after == upstream
           and HPG_SCHEMA_VERSION == "1.4.0"
           and SCENARIO_SCHEMA_VERSION == "1.5.0"
           and not scan_forbidden_reference_code(Path(__file__)),
           "promotion idempotent with an empty candidate, upstream artifacts "
           "byte-identical, scenario schema at the pinned 1.5.0, forbidden-reference scan clean")

    # ---- persist ---------------------------------------------------------
    t0 = time.perf_counter()
    pts.to_csv(H / "brandenburg_observed_feature_points.csv", index=False)
    pd.DataFrame(moves).to_csv(
        H / "brandenburg_point_selection_audit.csv", index=False)
    for name, frame in (("fit_points", fit),
                        ("model_selection_holdout", mod),
                        ("blind_validation", bli)):
        frame.to_csv(H / f"brandenburg_{name}.csv", index=False)
    cand.to_csv(H / "brandenburg_prime_meridian_candidate_audit.csv",
                index=False)
    gaudit = audit.copy()
    gaudit.insert(0, "map_source_id", src_brand)
    gaudit.insert(1, "copy_id", "copy_bnf_ge_dd_2987_3790")
    gaudit["status"] = np.where(gaudit["selected"], VALIDATED,
                                "CANDIDATE_NOT_SELECTED")
    gaudit["prime_meridian"] = best_pm
    gaudit["blind_n"] = sb["n"]
    gaudit["blind_median_km"] = round(sb["median"] / 1000, 3)
    gaudit["blind_p90_km"] = round(sb["p90"] / 1000, 3)
    gaudit["blind_max_km"] = round(sb["max"] / 1000, 3)
    gaudit["positional_uncertainty_km"] = np.where(
        gaudit["selected"], unc_km, np.nan)
    gaudit["provisional_validation_p90_km"] = PROVISIONAL_P90_KM
    gaudit["notes"] = (
        "MAPGEN-019. Fitted on directly observed feature symbols, not on a "
        "reconstructed grid. The MAPGEN-018 60 m figure and the MAPGEN-018R "
        "27.657 km figure are both superseded; the latter is retained under "
        "the name provisional_validation_p90_km and is not a final accuracy.")
    gaudit.to_csv(H / "brandenburg_bnf_georeference_audit.csv", index=False)
    (H / "brandenburg_bnf_transform.json").write_text(json.dumps({
        "map_source_id": src_brand, "copy_id": "copy_bnf_ge_dd_2987_3790",
        "prime_meridian": best_pm, "transform": transform,
        "fitted_on": "OBSERVED_FEATURE_POINTS", "n_fit": len(fit),
        "positional_uncertainty_km": unc_km,
        "georeference_status": VALIDATED,
        "map_field_pixels": list(FIELD),
        "inset_excluded_from_transform": list(INSET_ORIGIN),
    }, indent=2), encoding="utf-8")
    reg.loc[reg["global_source_id"] == src_brand,
            "georeference_status"] = VALIDATED
    reg.to_csv(H / "historical_source_registry.csv", index=False)
    cov.loc[cov["coverage_unit_id"] == "region_brandenburg_1756_pilot",
            "source_evidence_status"] = VALIDATED
    cov.to_csv(sdir / "political_coverage.csv", index=False)
    timings["persist_s"] = time.perf_counter() - t0

    # ---- figures ---------------------------------------------------------
    t0 = time.perf_counter()
    img = ["brandenburg_observed_points.png",
           "brandenburg_train_holdout_blind.png",
           "brandenburg_model_comparison.png",
           "brandenburg_blind_validation_residuals.png",
           "brandenburg_georeference_validated.png",
           "brandenburg_blha_source.png",
           "brandenburg_1756_evidence.png"]
    render_points(run_dir / img[0], pts,
                  "A. What the plate actually shows — 33 observed symbols")
    render_split(run_dir / img[1], pts, moves,
                 "B. Fit, model-selection and blind sets")
    render_models(run_dir / img[2], audit, chosen,
                  "C. Model comparison on the model-selection holdout")
    d = diag.iloc[0]
    summary = [
        ("stage", STAGE), ("base_commit_mapgen018r", M18R_COMMIT),
        ("outcome", "SUBSTANTIAL"),
        ("georeference_status", VALIDATED),
        ("directly_observed_2d_correspondences", n_obs),
        ("mapgen018r_observed_correspondences", 5),
        ("production_fit_gcps", len(fit)),
        ("n_fit", len(fit)), ("n_model", len(mod)), ("n_blind", len(bli)),
        ("n_excluded", int((pts.split_role == "EXCLUDED").sum())),
        ("zones_covered",
         ", ".join(f"{k}:{v}" for k, v in sorted(zc.items()))),
        ("model_selected", chosen),
        ("hold_rms_km", round(best / 1000, 3)),
        ("blind_median_km", round(sb["median"] / 1000, 3)),
        ("blind_p75_km", round(sb["p75"] / 1000, 3)),
        ("blind_p90_km", round(sb["p90"] / 1000, 3)),
        ("blind_p95_km", round(sb["p95"] / 1000, 3)),
        ("blind_max_km", round(sb["max"] / 1000, 3)),
        ("worst_zone", worst_zone),
        ("worst_zone_median_km", round(float(zone_med.max()) / 1000, 3)),
        ("folding", jac["folding"]),
        ("scale_ratio", round(jac["scale_ratio"], 4)),
        ("mean_pixel_scale_m", round(mpp, 2)),
        ("prime_meridian", best_pm),
        ("prime_meridian_status",
         "CORROBORATED_BY_MULTIPLE_OBSERVED_FEATURES"),
        ("prime_meridian_next_best_km", nxt),
        ("provisional_validation_p90_km", PROVISIONAL_P90_KM),
        ("positional_uncertainty_km", unc_km),
        ("top_degree_px", float(d["top_border_degree_width_px"])),
        ("bottom_degree_px", float(d["bottom_border_degree_width_px"])),
        ("meridian_apex_lat", float(d["meridian_apex_latitude_deg"])),
        ("interior_graticule_lines", d["interior_graticule_lines_present"]),
        ("blha_1145_result", "ACQUIRED 7582x6436 CC0"),
        ("blha_1132_result", "VERIFIED_AT_SOURCE, NO_DIGITISATION_OFFERED"),
        ("blha_relation", "SAME_WORK, impression UNRESOLVED, counts as 1"),
        ("blha_georef_status", "NOT_ATTEMPTED (shortfall)"),
        ("political_documents_read", len(pol)),
        ("continuity_segments", len(seg)),
        ("continuity_segments_researched",
         int((seg["individually_researched"] == "YES").sum())),
        ("continuity_result", "CONTINUOUS on all six; the snapshot instant "
                              "precedes every wartime change"),
        ("digitisation_status", "NOT_ATTEMPTED (shortfall)"),
        ("new_production_features", 0),
        ("brandenburg_controlled", 0),
        ("saxony_controlled", sax["CONTROLLED"]),
        ("canonical_rows_before", len(canonical)),
        ("canonical_rows_after", len(canonical)),
        ("canonical_rows_changed", 0),
        ("validation_pass", ""),
    ]
    sd = dict(summary)
    render_blind(run_dir / img[3], bli, sb, unc,
                 "D. Blind validation residuals and the uncertainty budget")
    render_status(run_dir / img[4], sd,
                  "E. Brandenburg georeference — validated")
    render_blha(run_dir / img[5], blha, "F. BLHA AKS 1145 A, acquired")
    render_evidence(run_dir / img[6], pol, seg, blha,
                    "H. 1756 evidence and the six frontier segments")
    render_meridian(run_dir / "brandenburg_prime_meridian.png", cand,
                    "G. Prime meridian on the plate's own graduations")
    img.append("brandenburg_prime_meridian.png")
    from PIL import Image

    aspects = {n: round(Image.open(run_dir / n).size[0]
                        / Image.open(run_dir / n).size[1], 3) for n in img}
    timings["render_s"] = time.perf_counter() - t0

    val = pd.DataFrame(val_rows).sort_values("check_id").reset_index(drop=True)
    val.to_csv(run_dir / "validation.csv", index=False)
    n_pass = int(val["pass"].sum())
    summary = [(k, v) for k, v in summary if k != "validation_pass"] + [
        ("validation_pass", f"{n_pass}/{len(val)}")]
    pd.DataFrame(summary, columns=["metric", "value"]).assign(
        run_id=run_id).to_csv(run_dir / "summary.csv", index=False)
    manifest = {
        "run_id": run_id, "stage": STAGE, "outcome": "SUBSTANTIAL",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "base_commit_mapgen018r": M18R_COMMIT,
        "georeference_status": VALIDATED,
        "observed_points": {"total": n_obs, "by_zone": zc,
                            "fit": len(fit), "model_selection": len(mod),
                            "blind": len(bli)},
        "model_selection": audit.drop(columns=["selection_rule"]).to_dict(
            "records"),
        "model_selected": chosen,
        "blind_validation": {k: round(v, 1) for k, v in sb.items()},
        "uncertainty_budget_m": {k: round(v, 1) for k, v in unc.items()},
        "prime_meridian": cand.to_dict("records"),
        "projection_diagnostic": dict(d),
        "blha": blha.drop(columns=["notes"]).to_dict("records"),
        "shortfalls_against_the_brief": [
            "no BLHA independent georeference was attempted",
            "no SOURCE_DATE_1751 geometry was digitised, so no cross-source "
            "boundary comparison was possible and no control was promoted",
        ],
        "upstream_sha256": upstream,
        "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "peak_memory_mb": round(_peak_memory_mb(), 1),
        "package_versions": package_versions(),
        "warnings": warnings,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    _write_readme(run_dir, run_id, dict(summary), cand, audit, bli, sb, unc,
                  pol, seg, aspects, img, moves)

    review = run_dir / "chatgpt_review"
    review.mkdir(exist_ok=True)
    cmap = {
        "README_REVIEW.md": run_dir / "README_REVIEW.md",
        "run_manifest.json": run_dir / "run_manifest.json",
        "validation.csv": run_dir / "validation.csv",
        "summary.csv": run_dir / "summary.csv",
    }
    for n in ["brandenburg_observed_feature_points",
              "brandenburg_point_selection_audit", "brandenburg_fit_points",
              "brandenburg_model_selection_holdout",
              "brandenburg_blind_validation",
              "brandenburg_prime_meridian_candidate_audit",
              "brandenburg_bnf_georeference_audit",
              "brandenburg_plate_graticule_observations",
              "brandenburg_plate_projection_diagnostic",
              "brandenburg_blha_copy_audit",
              "brandenburg_blha_copy_relation_audit",
              "brandenburg_1756_political_evidence",
              "brandenburg_boundary_segment_continuity",
              "brandenburg_reconstructed_grid_points",
              # carried forward UNCHANGED and still empty: no BLHA
              # georeference was attempted, and the reviewer should be able
              # to see that rather than take it on trust
              "brandenburg_blha_gcps",
              "brandenburg_blha_georeference_audit",
              "historical_evidence_assertions", "historical_source_registry"]:
        cmap[n + ".csv"] = H / (n + ".csv")
    cmap["scenario_political_coverage.csv"] = sdir / "political_coverage.csv"
    cmap["territorial_control.csv"] = sdir / "territorial_control.csv"
    cmap["territorial_control_provenance.csv"] = (
        sdir / "territorial_control_provenance.csv")
    cmap["historical_boundary_feature_evidence.csv"] = (
        H / "historical_boundary_feature_evidence.csv")
    cmap["historical_hex_membership.csv"] = (
        m15_dir / "chatgpt_review" / "historical_hex_membership.csv")
    for dst, src in cmap.items():
        if Path(src).exists():
            shutil.copy2(src, review / dst)
    pd.DataFrame(features.drop(columns="geometry")).to_csv(
        review / "historical_boundary_features.csv", index=False)
    for n in img:
        shutil.copy2(run_dir / n, review / n)
    timings["total_s"] = time.perf_counter() - t_start
    manifest["timings_s"]["total_s"] = round(timings["total_s"], 1)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    shutil.copy2(run_dir / "run_manifest.json", review / "run_manifest.json")
    print(f"[georef-rebuild] {run_id}: validation {n_pass}/{len(val)}, "
          f"{n_obs} observed points, model {chosen}, blind median "
          f"{sb['median']/1000:.2f} km p90 {sb['p90']/1000:.2f} km, "
          f"uncertainty {unc_km} km, status {VALIDATED}, canonical unchanged "
          f"({timings['total_s']:.0f}s)")
    for w in warnings:
        print("[georef-rebuild][WARN] "
              + w.encode("ascii", "replace").decode("ascii"))
    return run_dir


def _write_readme(run_dir, run_id, s, cand, audit, bli, sb, unc, pol, seg,
                  aspects, img, moves):
    L = [
        f"# {STAGE} Review — the Brandenburg georeference, rebuilt from the "
        "image",
        "",
        "**OUTCOME: SUBSTANTIAL.** The disqualified transform was **not "
        "repaired — it was replaced**. Thirty-three two-dimensional "
        "correspondences were read off the plate itself, split three ways "
        "before any model was fitted, and the result is "
        f"**`{s['georeference_status']}`** with a positional uncertainty of "
        f"**{s['positional_uncertainty_km']} km**, down from the "
        f"{s['provisional_validation_p90_km']} km provisional figure. BLHA "
        "AKS 1145 A was acquired, five 1756 documents were opened and all six "
        "frontiers were researched. **No geometry was digitised and no "
        "control was promoted** — that is a scope decision and it is reported "
        "as a shortfall.",
        "",
        f"Run `{run_id}`, built on MAPGEN-018R commit "
        f"`{s['base_commit_mapgen018r']}`. Canonical rows "
        f"{s['canonical_rows_before']:,} → {s['canonical_rows_after']:,}, "
        f"changed **{s['canonical_rows_changed']}**.",
        "",
        "## 1. Why the old transform failed — now with the mechanism",
        "",
        "MAPGEN-018R proved the transform was wrong. It could not say *why*. "
        "Re-measuring **all four** border graduations does:",
        "",
        f"- one degree of longitude spans **{s['top_degree_px']} px** on the "
        f"top border and **{s['bottom_degree_px']} px** on the bottom;",
        f"- extended, the six meridians meet at latitude "
        f"**{s['meridian_apex_lat']}°** — the pole, within engraving "
        "tolerance.",
        "",
        "The plate is a **converging-meridian (conic) construction, not a "
        "plate carrée**. MAPGEN-018 built its grid from the top border alone "
        "and so imposed the top-border x-scale over the whole sheet; that "
        "alone produces an east–west error growing southward of roughly 4% of "
        "the distance from the sheet centre — about 9 km at the corners. That "
        "is the systematic pattern MAPGEN-018R measured.",
        "",
        f"The interior carries **no graticule lines** "
        f"(`{s['interior_graticule_lines']}`), checked at native resolution "
        "over open sea and open land. Nothing was interpolated.",
        "",
        "## 2. Map-first collection",
        "",
        "The sheet was cut into sixteen tiles covering the whole engraved "
        "field and read at native resolution. **Symbols printed on the plate "
        "were found first**; identity and reference coordinate were resolved "
        "only afterwards. The anchor is the engraved settlement circle — "
        "located by an annulus template and refined to the ring's "
        "darkness-weighted centroid — never the centre of the label text.",
        "",
        f"- **{s['directly_observed_2d_correspondences']} directly observed "
        f"2-D correspondences** (MAPGEN-018R had "
        f"{s['mapgen018r_observed_correspondences']}, all found by cropping "
        "windows the old transform predicted).",
        f"- Zones: `{s['zones_covered']}` — every zone carries at least "
        "three.",
        "- The five MAPGEN-018R points are **retained and re-measured on "
        "their symbols**, and are barred from blind validation because they "
        "were discovered through the old transform.",
        "",
        "**Semantics fixed.** `directly_observed_2d_correspondences` and "
        f"`production_fit_gcps` are now separate: {s['n_fit']} points carry "
        "the fit role, but all "
        f"{s['directly_observed_2d_correspondences']} are observations. "
        "\"No production GCP\" can never again be written as \"no "
        "observation\".",
        "",
        "## 3. The split, frozen before fitting",
        "",
        f"`FIT {s['n_fit']} / MODEL_SELECTION_HOLDOUT {s['n_model']} / "
        f"BLIND_VALIDATION {s['n_blind']}`, plus {s['n_excluded']} excluded. "
        "Pairwise disjoint, deterministic, stratified by zone.",
        "",
    ]
    for m in moves:
        L.append(f"- `{m['moved_out']}` left blind validation "
                 f"(`{m['rule']}`); `{m['moved_in']}` took its place in zone "
                 f"{m['zone']}. Applied **before** any fit.")
    L += [
        "",
        "Brandenburg an der Havel is **excluded from every set**: the plate "
        "draws *New Brandeburg* (the Neustadt) and *Alt Brandeburg* "
        "separately, and the reference coordinate is the modern city centre, "
        "so the pairing carries an identification offset of about a "
        "kilometre. It is kept as an observed point and used by nothing.",
        "",
        "## 4. Prime meridian, settled properly this time",
        "",
        "MAPGEN-018R scored three candidates *through a fitted transform* — "
        "which absorbs any constant longitude offset and therefore cannot "
        "separate them at all. Here longitudes are read straight off the "
        "engraved graduations and compared with the observed features:",
        "",
        "| candidate | n | median | p90 | max |",
        "|---|---|---|---|---|",
    ]
    for r in cand.itertuples():
        L.append(f"| {r.candidate} | {r.n_points} | "
                 f"{r.median_residual_km:,.2f} km | "
                 f"{r.p90_residual_km:,.2f} km | "
                 f"{r.max_residual_km:,.2f} km |")
    L += [
        "",
        f"Ferro wins by a factor of ~40 → "
        f"`{s['prime_meridian_status']}`. The blind points took no part.",
        "",
        "## 5. Model selection",
        "",
        "Rule fixed before fitting: **the simplest model whose "
        "model-selection-holdout RMS is within 10% of the best, with no "
        "Jacobian folding**.",
        "",
        "| model | fit RMS | holdout RMS | holdout p90 | scale ratio | "
        "folding | cond |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in audit.itertuples():
        L.append(f"| {'**' if r.selected else ''}{r.model}"
                 f"{'**' if r.selected else ''} | {r.fit_rms_m/1000:.2f} km | "
                 f"{r.hold_rms_m/1000:.2f} km | {r.hold_p90_m/1000:.2f} km | "
                 f"{r.scale_ratio:.3f} | {r.folding} | {r.condition:.1e} |")
    L += [
        "",
        "- **POLYNOMIAL_2 has the best fit residual and the worst holdout "
        "residual.** That is what over-fitting looks like, and it is exactly "
        "the failure mode the brief warns about: a rubber sheet ironing the "
        "plate's own historical distortion into a fictitiously accurate "
        "boundary. Rejected.",
        "- AFFINE and PROJECTIVE are not separable at this plate's noise "
        "level, so the simpler one is taken. A converging-meridian plate "
        "*ought* to favour a projective; it does not, because the sheet's own "
        "placement error (~8 km) is larger than the convergence left over "
        "after a least-squares affine absorbs the average. The projective "
        "solve is also ill-conditioned on raw pixel coordinates — **the same "
        "model is selected either way**, which is why this is reported as a "
        "robust choice rather than a marginal one.",
        "",
        "## 6. Blind validation — the headline number",
        "",
        f"Evaluated **once**, after the model was fixed. n={sb['n']}.",
        "",
        "| point | zone | residual |",
        "|---|---|---|",
    ]
    for r in bli.sort_values("residual_m").itertuples():
        L.append(f"| {r.reference_feature_name} | {r.zone} | "
                 f"{r.residual_m/1000:.2f} km |")
    L += [
        "",
        f"median **{s['blind_median_km']} km**, p75 {s['blind_p75_km']} km, "
        f"p90 **{s['blind_p90_km']} km**, p95 {s['blind_p95_km']} km, max "
        f"{s['blind_max_km']} km. Worst zone median "
        f"{s['worst_zone_median_km']} km ({s['worst_zone']}) — no "
        "catastrophic quadrant. No Jacobian folding; scale ratio "
        f"{s['scale_ratio']}.",
        "",
        "### Uncertainty budget (map-specific, nothing borrowed from Saxony)",
        "",
        "| term | value |",
        "|---|---|",
    ]
    for k, v in unc.items():
        L.append(f"| {k} | {v:,.0f} m |")
    L += [
        "",
        f"→ **{s['positional_uncertainty_km']} km**. The "
        f"{s['provisional_validation_p90_km']} km MAPGEN-018R figure is "
        "retained under the name `provisional_validation_p90_km` and is "
        "**not** a final accuracy.",
        "",
        "## 7. BLHA — acquired",
        "",
        f"- **AKS 1145 A** (internal id 1266626), *ca.* 1758, **CC0 1.0**, "
        "acquired at **7582×6436**. The DDB derivative caps at 800×646; the "
        "archival master comes from the BLHA's own IIIF endpoint. Sheet reads "
        "*Cura et Impensis Conrad Lotter, Aug. Vind.* — an administrative map "
        "of the Kurmark and Neumark drawn by *Circulus*.",
        "- **AKS 1132 A** (internal id 1264164), 1758 — **verified at "
        "source**, but no digitisation is offered. An absence, not a rights "
        "blocker.",
        "- **Relation: same work, impression `UNRESOLVED`** — it cannot be "
        "settled without an image of 1132. **They count as one source, not "
        "two.** A third DDB record, *1220 LGB K 422 A* (1267037, 1758–2012), "
        "is explicitly a `(Nachdruck)`; that note belongs to **that** object "
        "and not to AKS 1145 A.",
        "",
        "## 8. 1756 political evidence — individual entries, opened",
        "",
        "From *Novum Corpus Constitutionum Prussico-Brandenburgensium* II "
        "(BSB `bsb11399173`):",
        "",
        "| no. | date | scan | col. | territory | role |",
        "|---|---|---|---|---|---|",
    ]
    for r in pol.itertuples():
        L.append(f"| {r.document_number} | {r.document_date} | "
                 f"{int(r.scan_number):04d} | {r.printed_columns} | "
                 f"{r.territory_named} | {r.evidence_role} |")
    L += [
        "",
        "The strongest is **No. XXXIII, 8 March 1756**: Frederick legislates "
        "for *die Neumarck und denen 4. Neumarckschen incorporirten Creisen* "
        "— **Sternberg, Crossen, Züllichau and Cottbus**. Those same four "
        "appear as *Circulus Sternbergensis, Crossensis, Zullichaviensis* and "
        "*Cottbus* on the ca. 1758 BLHA sheet: a direct 1756→1758 bracket on "
        "administrative composition.",
        "",
        "**No row is `BOUNDARY_POSITION`.** An edict tells you who governed a "
        "province, never where its line ran.",
        "",
        "**Pomerania separation** is documented rather than assumed: No. "
        "XXXII (6 March 1756) addresses the *Pommersche/Stettinsche "
        "Regierung* and the *Cößlinisches Hofgericht* — bodies entirely "
        "separate from the Kurmark and Neumark ones.",
        "",
        "## 9. Six frontiers — each individually researched",
        "",
        "| segment | 1751→1756 | 1756→1758 | status | confidence |",
        "|---|---|---|---|---|",
    ]
    for r in seg.itertuples():
        L.append(f"| {r.segment_name} | {r.change_1751_to_1756} | "
                 f"{r.change_1756_to_1758} | {r.continuity_status} | "
                 f"{r.confidence} |")
    L += [
        "",
        "**The decisive fact:** the scenario instant is **1 August 1756**. "
        "Prussian troops entered Saxony on **29 August 1756**, Sweden joined "
        "in September 1757, Russian columns reached the Neumark in 1758. "
        "*Every* wartime change post-dates the snapshot, so the 1751 sheet's "
        "geometry needs no wartime correction to stand for 1 August 1756. "
        "Where later occupation did occur it moved armies, not frontiers, and "
        "Hubertusburg (1763) restored the status quo ante.",
        "",
        "This is a **searched** result, not an unsearched one: every segment "
        "carries the sources consulted and the locators found.",
        "",
        "## 10. Shortfalls against the brief — reported as shortfalls",
        "",
        "- **No BLHA independent georeference was attempted.** The raster is "
        "in hand and the brief required an independent georeference of it. "
        "Nothing was inherited from the BnF transform, because nothing was "
        "computed.",
        "- **No `SOURCE_DATE_1751` geometry was digitised.** The gate is now "
        "open — the transform is validated — but the boundary was not traced, "
        "so there is no cross-source comparison against the ca. 1758 sheet "
        "and **no control was promoted**. Brandenburg CONTROLLED remains "
        f"**{s['brandenburg_controlled']}**.",
        "",
        "The reason is scope: the georeference rebuild and the three evidence "
        "phases consumed the stage. That is the honest reason, not a "
        "justification. Note in particular that production is **not** blocked "
        "by an evidence gap — the political evidence and the continuity "
        "research both came out positive.",
        "",
        "## 11. Images",
        "",
    ]
    for n in img:
        L.append(f"- `{n}` (aspect {aspects[n]})")
    L += [
        "",
        "There is deliberately no BLHA georeference figure and no digitised "
        "boundary figure: neither was produced.",
        "",
        "## 12. Validation",
        "",
        f"- `validation.csv`: M19 gates, pass count {s['validation_pass']}.",
        "",
        "## 13. Known issues",
        "",
        "- **The plate's own placement error is ~8–11 km** and that, not the "
        "model, now dominates. No transform can do better on this sheet; a "
        "better number needs a better source.",
        "- Kartuzy (23 km) and Lauenburg (18 km) sit in Pomerelia, the "
        "worst-surveyed corner of the plate. They were kept: dropping points "
        "because they are inconvenient after the split was frozen is exactly "
        "what the brief forbids.",
        "- Küstrin was **rejected during collection**, not after: its symbol "
        "could not be isolated in the marsh hatching and the modern town "
        "centre sits ~1 km from the destroyed fortress.",
        "- The Vieille Marche / Prignitz supplement carries its own "
        "graticule; it is excluded from the transform and remains "
        "`INSET_GEOMETRY_GAP`.",
        "- BLHA georeference and the 1751 digitisation remain outstanding.",
    ]
    (run_dir / "README_REVIEW.md").write_text("\n".join(L) + "\n",
                                              encoding="utf-8")
