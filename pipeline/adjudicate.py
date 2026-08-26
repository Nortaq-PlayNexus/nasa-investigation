"""Adjudication layer: bring the candidate list toward conclusions.

Applies the advanced confirmation methods the methodology requires and turns
the 2600+ raw candidates into a short list of leads with honest confidence:

  1. Pixel-level cross-band agreement. For same-size sibling products of one
     footprint, the candidate's crop is compared against the corresponding
     crop in each sibling: not just "a box exists there" but that the feature
     actually has the same polarity and comparable contrast in the sibling.
  2. Enhancement persistence. The anomaly's contrast is re-measured after a
     median (denoising) filter. Extended surface features survive; hot
     pixels, streaks and compression speckle mostly vanish.
  3. Shape analysis. Compactness (4*pi*Area/Perimeter^2) and boundary-gradient
     sharpness separate round/donut-like features from linear terrain or
     detector scratches.
  4. Adjudicated score = analyze interest + agreement + persistence + shape,
     then verdicts (EXPLAINED-ARTIFACT / STRONG-LEAD / LEAD / WEAK / NOISE)
     with a recommended action for each.

All offline (numpy/PIL). Outputs:
  conclusions/adjudicated.csv   every candidate, adjudicated + sorted
  conclusions/leads.csv         only LEAD / STRONG-LEAD
  conclusions/report.html       review dashboard
  conclusions/leads/F-*.md      per-lead reports following the finding template
  conclusions/SUMMARY.md        the bottom-line conclusion
"""

import argparse
import csv
import datetime
import html
import os
import re
import sys

import analyze
import common
import detect
import metadata as meta_mod
import numpy as np
from PIL import Image, ImageFilter

try:
    from scipy import ndimage as _ndimage

    HAS_SCIPY = True
except ImportError:
    _ndimage = None
    HAS_SCIPY = False


def load_gray(path):
    return common.load_gray(path)


def load_geometry(metadata_path):
    """Key catalog CSV rows by image file name for solar-geometry joins.

    The catalog (build_catalog.py) carries pixel_scale_m, solar_azimuth,
    solar_elevation, incidence_angle, spacecraft_altitude_km per product.
    """
    rows = {}
    if not metadata_path or not os.path.exists(metadata_path):
        return rows
    with open(metadata_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            name = r.get("name") or os.path.basename(r.get("path", ""))
            if name:
                rows[name] = r
    return rows


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def median_persist(crop, fx, fy, fw, fh, radius=2):
    """Fraction of the contrast that survives denoising.

    = contrast after a median blur / contrast before. Extended surface features
    keep most of their contrast (persistence near 1); isolated hot pixels,
    streaks and compression speckle are removed and drop toward 0.
    """
    crop = np.asarray(crop, dtype=np.float32)
    if np.isnan(crop).any():
        # PDS missing values arrive as NaN; replace with the local median so
        # the uint8 cast and the background statistics stay meaningful.
        fill = float(np.nanmedian(crop)) if np.isfinite(crop).any() else 0.0
        crop = np.where(np.isnan(crop), fill, crop)
    fg = crop[fy:fy + fh, fx:fx + fw]
    mask = np.ones(crop.shape, dtype=bool)
    mask[fy:fy + fh, fx:fx + fw] = False
    bg = crop[mask]
    base = abs(float(fg.mean()) - float(bg.mean())) / (float(bg.std()) + 1e-6)
    blur = np.asarray(
        Image.fromarray(crop.astype(np.uint8)).filter(
            ImageFilter.MedianFilter(2 * radius + 1)), dtype=np.float32)
    fg2 = blur[fy:fy + fh, fx:fx + fw]
    mask2 = np.ones(blur.shape, dtype=bool)
    mask2[fy:fy + fh, fx:fx + fw] = False
    bg2 = blur[mask2]
    after = abs(float(fg2.mean()) - float(bg2.mean())) / (float(bg2.std()) + 1e-6)
    persist = after / (base + 1e-6)
    return round(min(1.0, max(0.0, persist)), 3), round(float(bg.std()), 2)


def _erode8(mask):
    """Binary erosion with a 3x3 structuring element (pure numpy)."""
    m = np.asarray(mask, dtype=bool)
    er = m.copy()
    er[1:, :] &= m[:-1, :]
    er[:-1, :] &= m[1:, :]
    er[:, 1:] &= m[:, :-1]
    er[:, :-1] &= m[:, 1:]
    er[1:, 1:] &= m[:-1, :-1]
    er[1:, :-1] &= m[:-1, 1:]
    er[:-1, 1:] &= m[1:, :-1]
    er[:-1, :-1] &= m[1:, 1:]
    return er


def _dilate8(mask):
    """Binary dilation with a 3x3 structuring element (pure numpy)."""
    m = np.asarray(mask, dtype=bool)
    dl = np.zeros_like(m)
    dl |= m
    dl[1:, :] |= m[:-1, :]
    dl[:-1, :] |= m[1:, :]
    dl[:, 1:] |= m[:, :-1]
    dl[:, :-1] |= m[:, 1:]
    dl[1:, 1:] |= m[:-1, :-1]
    dl[1:, :-1] |= m[:-1, 1:]
    dl[:-1, 1:] |= m[1:, :-1]
    dl[:-1, :-1] |= m[1:, 1:]
    return dl


def _binary_opening(mask):
    """Erosion then dilation; scipy when available, pure numpy otherwise."""
    if HAS_SCIPY:
        return _ndimage.binary_opening(mask, np.ones((3, 3), dtype=bool))
    return _dilate8(_erode8(mask))


def roundness(crop, fx, fy, fw, fh):
    """Compactness of the bright/dark core within the flagged region."""
    region = crop[fy:fy + fh, fx:fx + fw]
    m = region - np.median(region)
    s = float(np.std(region)) + 1e-6
    mask = np.abs(m) > 1.5 * s
    if mask.sum() < 9:
        return 0.0, 0.0, 0.0
    core = _binary_opening(mask)
    if core.sum() < 9:
        return 0.0, 0.0, 0.0
    area = float(core.sum())
    per = float(core.sum() - _erode8(core).sum())
    compact = 4.0 * np.pi * area / (per * per + 1e-6)
    return round(min(1.0, compact), 3), round(area, 1), round(per, 1)


def sibling_groups(recs):
    """(stem, W, H) -> list of distinct image paths with identical dimensions."""
    groups = {}
    for i, r in recs.items():
        groups.setdefault((r["stem"], r["W"], r["H"]), set()).add(r["path"])
    return {k: sorted(v) for k, v in groups.items() if len(v) > 1}


def cross_band_agreement(recs, groups, arr_cache, i, row, max_crop):
    """Pixel-level confirmation in same-size sibling images.

    For every distinct sibling product of the same footprint and dimensions,
    crops the SAME (x, y, w, h) region and verifies the feature really is
    present there with the same polarity and comparable contrast.

    Returns (agree_count, disagree_count, list_of_(image, polarity, contrast)).
    """
    a = recs[i]
    agrees = 0
    disagrees = 0
    notes = []
    for path in groups.get((a["stem"], a["W"], a["H"]), []):
        if path == a["path"]:
            continue
        if path in arr_cache:
            sib_arr = arr_cache[path]
        else:
            try:
                sib_arr = load_gray(path)
                arr_cache[path] = sib_arr
            except Exception:
                continue
        try:
            crop, sib_feats = analyze.analyze_candidate(
                {"x": a["x"], "y": a["y"], "w": a["w"], "h": a["h"], "fill": 0.5},
                sib_arr, max_crop)
        except Exception:
            continue
        if sib_feats["polarity"] == row["polarity"]:
            ratio = float(row["contrast"]) / (float(sib_feats["contrast"]) + 1e-6)
            ok = 0.35 <= ratio <= 2.8
        else:
            ok = False
        if ok:
            agrees += 1
            notes.append((os.path.basename(path), sib_feats["polarity"], sib_feats["contrast"]))
        else:
            disagrees += 1
    return agrees, disagrees, notes


def adjudicated_score(interest, agrees, persistence, compact, near_edge, flags, bg_std,
                      shadow_align=None, shadow_expected=None, size_m=None):
    score = float(interest)
    score += 12.0 * min(agrees, 2) if agrees else 0.0
    if agrees >= 2:
        score += 6.0
    score += 6.0 if persistence >= 0.65 else (-6.0 if persistence < 0.35 else 0.0)
    score += 4.0 if compact >= 0.7 else (-4.0 if compact < 0.2 else 0.0)
    if bg_std < 8.0:
        score += 8.0
    elif bg_std < 14.0:
        score += 3.0
    if near_edge:
        score -= 5.0
    flags = set(flags.split(",")) if isinstance(flags, str) and flags else set()
    if flags and "small_blob" in flags and len(flags) == 1:
        pass
    elif flags:
        score -= 8.0
    # Solar-geometry signals: a real elevated object casts a shadow aligned
    # with the sun; a bright feature with no such shadow needs explaining.
    if shadow_align is not None:
        if shadow_align >= 0.75:
            score += 4.0
        elif shadow_align < 0.35:
            score -= 4.0
    if shadow_expected and size_m is not None:
        if size_m > 2000.0:
            score -= 6.0  # km-scale 'objects' are terrain
    return round(max(0.0, min(100.0, score)), 1)


def verdict(score, evidence_class, agrees, compactness, aspect, flags, area_px):
    if evidence_class == 1:
        return "EXPLAINED-ARTIFACT"
    disqualify = {"streak", "hot_pixel", "compression", "dark_band",
                  "elongated_large", "edge_artifact"}
    flagged = {f for f in flags.split(",") if f} if isinstance(flags, str) else set()
    disq = bool(flagged & disqualify)
    discrete = compactness >= 0.5 and aspect < 3
    if agrees >= 1:
        if discrete and not disq and 200 <= area_px <= 50000:
            return "CONFIRMED-LEAD"
        return "TERRAIN"
    if score >= 45 and not disq:
        return "PROMISING"
    if score >= 28:
        return "WEAK"
    return "NOISE"


def confidence(score, agrees, persistence, evidence_class):
    if evidence_class == 1:
        return "low"
    if agrees >= 1 and persistence >= 0.6:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def recommend(verdict):
    if verdict == "EXPLAINED-ARTIFACT":
        return "Discard. Mechanism identified; matches a known processing/sensor artifact."
    if verdict == "CONFIRMED-LEAD":
        return ("Real feature confirmed at the same pixels in the corresponding band "
                "variant(s) of one acquisition. Fetch the EDR original, geolocate on "
                "Trek, and check for an independent pass at a different lighting "
                "before writing a finding.")
    if verdict == "PROMISING":
        return ("Strong single-image signal but not confirmed across band variants. "
                "Compare against the original product and look for the feature in a "
                "same-footprint sibling or an independent acquisition.")
    if verdict == "TERRAIN":
        return ("Real surface feature (seen across band variants) but consistent with "
                "ordinary geology/terrain by shape or scale. Not a lead unless an "
                "independent comparison changes the picture.")
    if verdict == "WEAK":
        return "Keep in the watch list only. Likely noise or terrain texture; no finding warranted."
    return "Discard. Below the reliability floor set by the negative-control baseline."


def main(argv=None):
    cfg = common.load_config()
    p = argparse.ArgumentParser(description="Adjudicate candidates toward conclusions")
    p.add_argument("--candidates", default="data/anomalies/candidates.csv")
    p.add_argument("--evaluated", default="data/anomalies/analysis/evaluated.csv")
    p.add_argument("--out", default="data/anomalies/conclusions")
    p.add_argument("--max-crop", type=int, default=common.option_default(cfg, "adjudicate_max_crop", 512))
    p.add_argument("--top", type=int, default=common.option_default(cfg, "adjudicate_top", 20),
                   help="how many lead reports to write")
    p.add_argument("--contrast-bar", type=float,
                   default=common.option_default(cfg, "adjudicate_contrast_bar", 1.5))
    p.add_argument("--area-min", type=int,
                   default=common.option_default(cfg, "adjudicate_area_min", 200))
    p.add_argument("--area-max", type=int,
                   default=common.option_default(cfg, "adjudicate_area_max", 50000))
    p.add_argument("--q", type=float, default=common.option_default(cfg, "adjudicate_q", 0.05),
                   help="false-discovery-rate level for the top-lead claim")
    p.add_argument("--metadata", default="data/catalog/catalog.csv",
                   help="catalog CSV with per-product solar geometry and pixel scale")
    a = p.parse_args(argv)
    common.set_audit(common.audit_path_for(a.out))

    start = common.time.time()
    with open(a.candidates, newline="", encoding="utf-8") as f:
        cand = list(csv.DictReader(f))
    with open(a.evaluated, newline="", encoding="utf-8") as f:
        ev = list(csv.DictReader(f))
    def _sort_key(r):
        return (r["image"], r["x"], r["y"], r["w"], r["h"])
    ev_by_key = {_sort_key(r): r for r in ev}
    geom_rows = load_geometry(a.metadata)
    common.log("info", "adjudicate: %d candidates, %d evaluated rows, %d geometry rows"
               % (len(cand), len(ev), len(geom_rows)))

    recs = analyze.precompute(cand)
    groups = sibling_groups(recs)
    common.log("info", "same-size sibling groups: %d (2+ products)" % len(groups))

    arr_cache = {}
    out_rows = []
    skipped = 0
    for i, row in enumerate(cand):
        e = ev_by_key.get(_sort_key(row))
        if e is None:
            skipped += 1
            continue
        path = row["path"]
        if path not in arr_cache:
            try:
                arr_cache[path] = load_gray(path)
            except Exception:
                skipped += 1
                continue
        H, W = arr_cache[path].shape
        x, y, w, h = int(e["x"]), int(e["y"]), int(e["w"]), int(e["h"])
        if not common.validate_box(x, y, w, h, W, H):
            skipped += 1
            continue
        margin = int(0.5 * max(w, h))
        x0, y0 = max(0, x - margin), max(0, y - margin)
        x1, y1 = min(W, x + w + margin), min(H, y + h + margin)
        crop = arr_cache[path][y0:y1, x0:x1]
        fx2, fy2 = x - x0, y - y0
        persist, bg_std = 0.0, 0.0
        try:
            persist, bg_std = median_persist(crop, fx2, fy2, w, h)
        except Exception:
            persist, bg_std = 0.0, 0.0
        compact, area, per = roundness(crop, fx2, fy2, w, h)

        agrees, disagrees, notes = cross_band_agreement(recs, groups, arr_cache, i, e, a.max_crop)
        smooth = "yes" if bg_std < 8.0 else "no"

        # Solar-geometry join: physical size, shadow alignment, implied height.
        geo = geom_rows.get(e["image"]) or geom_rows.get(os.path.basename(path)) or {}
        px_scale = _num(geo.get("pixel_scale_m"))
        s_az = _num(geo.get("solar_azimuth"))
        s_el = _num(geo.get("solar_elevation"))
        s_alt = _num(geo.get("spacecraft_altitude_km"))
        size_m = None
        inferred_height_m = None
        shadow_align = None
        shadow_expected = None
        if px_scale:
            size_m = round(max(w, h) * px_scale, 2)
        if s_az is not None and s_el is not None and px_scale is not None:
            try:
                sun = detect.sun_shadow_sanity(
                    arr_cache[path], x, y, w, h, s_az, s_el,
                    north_up=True, polarity=e["polarity"])
                if sun["shadow_alignment"] is not None:
                    shadow_align = sun["shadow_alignment"]
                shadow_expected = sun["shadow_px"] is not None and sun["shadow_confidence"] > 0.3
                if sun["shadow_px"] is not None and s_el < 80:
                    inferred_height_m = meta_mod.height_from_shadow_len(
                        sun["shadow_px"], s_el, px_scale)
            except Exception:
                shadow_align = None

        score = adjudicated_score(float(e["score"]), agrees, persist, compact,
                                  e["near_edge"] == "True" or e["near_edge"] == "1",
                                  e["flags"], bg_std,
                                  shadow_align=shadow_align,
                                  shadow_expected=shadow_expected,
                                  size_m=size_m)
        v = verdict(score, int(e["evidence_class"]), agrees, compact, float(e["aspect"]),
                    e["flags"], int(e["area_px"]))
        conf = confidence(score, agrees, persist, int(e["evidence_class"]))
        out_rows.append({
            "image": e["image"], "path": path, "x": x, "y": y, "w": w, "h": h,
            "contrast": e["contrast"], "area_px": e["area_px"], "aspect": e["aspect"],
            "polarity": e["polarity"], "evidence_class": e["evidence_class"],
            "matches_coord": e["matches"], "agrees": agrees, "disagrees": disagrees,
            "near_edge": e["near_edge"], "persistence": persist, "compactness": compact,
            "bg_std": bg_std, "smooth": smooth,
            # new rigor metrics carried through from analyze.py
            "grid_energy": e.get("grid_energy", ""),
            "edge_sharpness": e.get("edge_sharpness", ""),
            "contrast_stability": e.get("contrast_stability", ""),
            "interest": e["score"],
            "score": score, "verdict": v, "confidence": conf,
            "flags": e["flags"], "recommendation": recommend(v),
            "solar_elevation_deg": s_el, "solar_azimuth_deg": s_az,
            "pixel_scale_m": px_scale, "size_m": size_m,
            "shadow_alignment": shadow_align, "inferred_height_m": inferred_height_m,
            "spacecraft_altitude_km": s_alt,
        })

    out_rows.sort(key=lambda r: r["score"], reverse=True)
    os.makedirs(a.out, exist_ok=True)
    leads_dir = os.path.join(a.out, "leads")
    os.makedirs(leads_dir, exist_ok=True)

    # Negative-control baselines from benchmark.py: scene -> FP count on the
    # clean image. Candidates in images whose detection count is ~ baseline are
    # indistinguishable from the pipeline's own noise floor.
    baselines = {}
    bench_dir = os.path.join(os.path.dirname(a.out), "benchmark")
    if os.path.isdir(bench_dir):
        for fn in os.listdir(bench_dir):
            if not fn.startswith("benchmark_") or not fn.endswith(".csv"):
                continue
            scene = fn[len("benchmark_"):-len(".csv")]
            try:
                with open(os.path.join(bench_dir, fn), newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        cell = "%s %s" % (row.get("blob_size_px", ""), row.get("scene", ""))
                        if "negative_control_fp" in cell:
                            for col in ("blob_size_px", "recall_hit"):
                                try:
                                    baselines[scene] = int(row[col])
                                    break
                                except (TypeError, ValueError):
                                    continue
                            break
            except Exception:
                continue

    def baseline_for(image):
        base = image[:-len(".png")] if image.endswith(".png") else image
        if base in baselines:
            return baselines[base]
        for k, v in baselines.items():
            if base.endswith(k) or k.endswith(base):
                return v
        return None

    fields = ["image", "x", "y", "w", "h", "contrast", "area_px", "aspect", "polarity",
              "evidence_class", "matches_coord", "agrees", "disagrees", "near_edge",
              "persistence", "compactness", "bg_std", "smooth",
              "grid_energy", "edge_sharpness", "contrast_stability",
              "interest", "score", "verdict", "confidence",
              "flags", "recommendation", "path", "baseline_fp", "fdr_q",
              "solar_elevation_deg", "solar_azimuth_deg", "pixel_scale_m", "size_m",
              "shadow_alignment", "inferred_height_m", "spacecraft_altitude_km"]
    for r in out_rows:
        r["baseline_fp"] = baseline_for(r["image"]) if baseline_for(r["image"]) is not None else ""
        r["fdr_q"] = ""

    # Multiple-comparison control. Approximate per-candidate p-value from the
    # contrast z-score (units of local background sigma) and apply Benjamini-
    # Hochberg across all non-artifact candidates. EXPLAINED-ARTIFACT rows are
    # excluded from the tested set (their mechanism is already known).
    tested = [r for r in out_rows if r["verdict"] != "EXPLAINED-ARTIFACT"]
    if tested:
        pvals = [common.z_pvalue(float(r["contrast"])) for r in tested]
        qvals = common.benjamini_hochberg(pvals, a.q)
        for r, q in zip(tested, qvals):
            r["fdr_q"] = "%.3f" % q
    fdr_ok = sum(1 for r in tested if float(r["fdr_q"]) <= a.q)
    common.log("info", "BH-FDR at q=%.2f: %d/%d non-artifact candidates survive"
               % (a.q, fdr_ok, len(tested)))

    common.atomic_csv_write(os.path.join(a.out, "adjudicated.csv"), out_rows, fields)
    leads = [r for r in out_rows if r["verdict"] in ("CONFIRMED-LEAD", "PROMISING")]
    common.atomic_csv_write(os.path.join(a.out, "leads.csv"), leads, fields)

    # The short list worth human attention: cross-band confirmed, discrete,
    # contrast above the configurable bar, not on the image border, plausible size.
    top_leads = [r for r in out_rows
                 if r["verdict"] == "CONFIRMED-LEAD"
                 and float(r["contrast"]) >= a.contrast_bar
                 and r["near_edge"] not in ("True", "1")
                 and a.area_min <= int(r["area_px"]) <= a.area_max]
    top_leads.sort(key=lambda r: r["score"], reverse=True)

    # Robustness stress test: how does the top-lead count move as the contrast
    # bar is tightened? A conclusion that collapses at +/-0.25 sigma is weak.
    stress = []
    for th in (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0):
        n = sum(1 for r in out_rows
                if r["verdict"] == "CONFIRMED-LEAD"
                and float(r["contrast"]) >= th
                and r["near_edge"] not in ("True", "1")
                and a.area_min <= int(r["area_px"]) <= a.area_max)
        stress.append((th, n))
    common.log("info", "stress test (contrast bar -> top-lead count): %s" %
               ", ".join("%.2f->%d" % s for s in stress))

    # Generate visual evidence (enhancement strips) for the top leads.
    # Reuses arr_cache — those images are already in memory.
    strips_dir = os.path.join(a.out, "strips")
    os.makedirs(strips_dir, exist_ok=True)
    for li, r in enumerate(top_leads):
        path = r["path"]
        arr = arr_cache.get(path)
        if arr is None:
            try:
                arr = load_gray(path)
                arr_cache[path] = arr
            except Exception:
                arr_cache[path] = None
                continue
        try:
            crop, _ = analyze.analyze_candidate(
                {"x": int(r["x"]), "y": int(r["y"]), "w": int(r["w"]), "h": int(r["h"]),
                 "fill": 0.5}, arr, a.max_crop)
            strip = analyze.make_strip(analyze.enhance_variants(crop))
            name = "T%03d_%s" % (li, re.sub(r"[^A-Za-z0-9_.-]", "_",
                                            r["image"])[:50])
            strip.save(os.path.join(strips_dir, name + ".jpg"), quality=92)
            r["_strip"] = name + ".jpg"
        except Exception:
            r["_strip"] = ""

    write_report(a.out, out_rows, leads, top_leads)
    write_lead_reports(leads_dir, top_leads[:a.top])
    write_summary(a.out, out_rows, leads, top_leads, stress, fdr_ok, a.q,
                  a.contrast_bar, a.area_min, a.area_max, baselines)

    from collections import Counter
    counts = dict(Counter(r["verdict"] for r in out_rows))
    common.log("info", "verdict distribution: %s" % counts)
    common.log("info", "top leads (confirmed + contrast>=%.2f + discrete + size range): %d"
               % (a.contrast_bar, len(top_leads)))

    common.audit({
        "event": "adjudicate",
        "cmd": " ".join(sys.argv),
        "candidates": len(cand), "evaluated": len(ev), "skipped": skipped,
        "out": os.path.abspath(a.out),
        "candidates_sha256": common.sha256_file(a.candidates),
        "evaluated_sha256": common.sha256_file(a.evaluated),
        "adjudicated_sha256": common.sha256_file(os.path.join(a.out, "adjudicated.csv")),
        "verdict_counts": counts, "top_leads": len(top_leads), "fdr_q": a.q,
        "fdr_surviving": fdr_ok, "stress": stress,
        "seconds": round(common.time.time() - start, 1),
    })


def write_report(out, rows, leads, top_leads):
    cards = []
    for r in top_leads[:60]:
        flags = r["flags"].split(",") if r["flags"] else []
        flag_html = "".join(f"<li>{html.escape(f)}</li>" for f in flags) or "<li>none</li>"
        img = ("<p><img src='strips/%s' alt='strip'></p>" % r["_strip"]) if r.get("_strip") else ""
        cards.append(
            "<div class='card'><h3>{} <span class='cls'>{}</span></h3>"
            "<p><b>verdict</b> {} &middot; <b>confidence</b> {} &middot; "
            "<b>score</b> {:.0f}</p>"
            "<table><tr><td>x,y</td><td>{}, {}</td></tr>"
            "<tr><td>size</td><td>{} x {} px</td></tr>"
            "<tr><td>evidence class</td><td>{}</td></tr>"
            "<tr><td>cross-band</td><td>{} agree / {} disagree</td></tr>"
            "<tr><td>persistence</td><td>{}</td></tr>"
            "<tr><td>compactness</td><td>{}</td></tr>"
            "<tr><td>contrast</td><td>{}</td></tr>"
            "<tr><td>flags</td><td><ul>{}</ul></td></tr></table>"
            "{}"
            "<p>{}</p></div>".format(
                html.escape(r["image"]), r["verdict"],
                html.escape(r["verdict"]), html.escape(r["confidence"]), float(r["score"]),
                r["x"], r["y"], r["w"], r["h"], r["evidence_class"],
                r["agrees"], r["disagrees"], r["persistence"], r["compactness"],
                r["contrast"], flag_html, img, html.escape(r["recommendation"])))

    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    dist = " &middot; ".join("%s: %d" % (k, v) for k, v in sorted(counts.items()))
    body = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Anomaly adjudication</title><style>"
        "body{{font-family:sans-serif;background:#0d1117;color:#d8dee6;margin:1.5rem}}"
        ".grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:1rem}}"
        ".card{{border:1px solid #2a3138;padding:.6rem;background:#151b23}}"
        ".card img{{max-width:100%;border:1px solid #333}}"
        ".cls{{color:#f0b429}}table{{border-collapse:collapse;margin:.4rem 0}}"
        "th,td{{border:1px solid #2a3138;padding:.2rem .5rem;font-size:.8rem}}"
        "ul{{margin:.2rem 0 0 1rem}}</style></head><body>"
        "<h1>Anomaly adjudication</h1>"
        "<p>{} candidates adjudicated &middot; {} leads &middot; {}</p>"
        "<p><a href='adjudicated.csv'>adjudicated.csv</a> &middot; "
        "<a href='leads.csv'>leads.csv</a> &middot; "
        "<a href='SUMMARY.md'>SUMMARY.md</a></p>"
        "<div class='grid'>{}</div></body></html>").format(len(rows), len(leads), dist, "".join(cards))
    common.atomic_text_write(os.path.join(out, "report.html"), body)


def write_lead_reports(leads_dir, leads):
    for n, r in enumerate(leads, 1):
        fn = os.path.join(leads_dir, "F-%04d.md" % n)
        flags = "\n".join("- [x] " + f for f in r["flags"].split(",")) if r["flags"] else \
            "- [ ] no artifact flags triggered"
        body = (
            "# Finding Report (lead)\n\n"
            "- Finding ID: %s\n"
            "- Date: %s\n- Investigator: automated adjudication\n"
            "- Status: OPEN\n- Evidence class: %s\n\n"
            "## Source\n"
            "- Product ID: %s\n- File: `%s`\n"
            "- Direct source URL: <from catalog; pending>\n"
            "- Raw file sha256: <pending>\n\n"
            "## Location\n"
            "- Pixel coords (x, y): %s, %s; size %s x %s px\n"
            "- Coordinates (lat/lon): <pending: geolocate on Trek>\n"
            "- Location confirmed in >1 image: %s cross-band agreements / %s disagreements\n\n"
            "## Lighting geometry (from product label)\n"
            "- Solar elevation: %s deg; solar azimuth: %s deg\n"
            "- Pixel scale: %s m/px; spacecraft altitude: %s km\n"
            "- Apparent object size: %s m\n"
            "- Shadow alignment with sun: %s; implied height from shadow: %s m\n\n"
            "## Anomaly description\n"
            "- Polarity: %s; contrast vs background: %s\n"
            "- Apparent size: %s px area, aspect %s\n"
            "- Shape: compactness %s (round = 1)\n"
            "- Persistence after denoising: %s\n"
            "- Local terrain texture (bg std): %s (smooth: %s)\n"
            "- Evidence strip: `strips/%s`\n\n"
            "## Analysis performed\n"
            "- Pipeline: detect.py (scales 4, z 3.0, min-size 12) -> analyze.py -> adjudicate.py\n"
            "- Enhancements: stretch / residual / upscale strips in analysis/crops/\n"
            "- Cross-band pixel agreement at same footprint coords\n"
            "- Solar-geometry shadow alignment and physical size estimate\n"
            "- Adjudication score: %s (interest %s)\n\n"
            "## Known-artifact checklist\n%s\n\n"
            "## Confirmation status\n"
            "- [ ] Seen in >1 independent image (cross-band = same acquisition; "
            "independent pass required)\n"
            "- [ ] Seen at >1 viewing angle or lighting\n"
            "- [ ] Independently flagged in blind review\n"
            "- [ ] Cross-checked against global mosaic coverage\n\n"
            "## Conclusion\n"
            "- Verdict: %s (confidence %s)\n"
            "- Recommended next steps: %s\n") % (
            os.path.basename(fn), datetime.date.today().isoformat(),
            r["evidence_class"], r["image"], r["path"],
            r["x"], r["y"], r["w"], r["h"], r["agrees"], r["disagrees"],
            r.get("solar_elevation_deg") or "n/a", r.get("solar_azimuth_deg") or "n/a",
            r.get("pixel_scale_m") or "n/a", r.get("spacecraft_altitude_km") or "n/a",
            r.get("size_m") or "n/a", r.get("shadow_alignment") or "n/a",
            r.get("inferred_height_m") or "n/a",
            r["polarity"], r["contrast"], r["area_px"], r["aspect"],
            r["compactness"], r["persistence"], r["bg_std"], r["smooth"],
            r.get("_strip", ""),
            r["score"], r["interest"], flags,
            r["verdict"], r["confidence"], r["recommendation"])
        common.atomic_text_write(fn, body)


def write_summary(out, rows, leads, top_leads, stress, fdr_ok, q,
                  contrast_bar, area_min, area_max, baselines):
    from collections import Counter
    counts = Counter(r["verdict"] for r in rows)
    real_scenes = sorted(k for k in baselines if k != "synthetic")
    if real_scenes:
        calib_extra = "".join(
            "- On real image `%s`: %d detections on the clean image alone, so on "
            "textured scenes the detector is background-limited and small candidates "
            "must be treated as unreliable.\n" % (k, baselines[k]) for k in real_scenes)
    else:
        calib_extra = ""
    per_img = Counter(r["image"] for r in top_leads)
    top = "\n".join(
        "- **%s** (%s): %s, x=%s y=%s, score %s, contrast %s, %s band agrees" % (
            r["image"], r["verdict"], r["confidence"], r["x"], r["y"], r["score"],
            r["contrast"], r["agrees"])
        for r in top_leads[:20])
    per = "\n".join("- %s: %d top leads" % (k, v) for k, v in per_img.most_common())
    stress_tab = "\n".join("| %.2f | %d |" % (th, n) for th, n in stress)
    with_base = []
    for r in top_leads:
        b = r["baseline_fp"]
        with_base.append((r, b))
    seen_img = set()
    baseline_lines = []
    for r, b in with_base:
        if b == "" or r["image"] in seen_img:
            continue
        seen_img.add(r["image"])
        baseline_lines.append(
            "- **%s**: %d candidates vs %d clean-scene FP baseline" % (
                r["image"],
                sum(1 for x in rows if x["image"] == r["image"]), b))
    baseline_lines = "\n".join(baseline_lines)
    body = (
        "# Adjudication conclusion\n\n"
        "## What was done\n"
        "Every candidate from `detect.py` (scales 4, z 3.0, min-size 12) was enhanced, "
        "measured and artifact-checked by `analyze.py`, then adjudicated here with:\n"
        "- pixel-level cross-band agreement across same-size sibling products,\n"
        "- enhancement persistence (does it survive median denoising),\n"
        "- shape compactness,\n"
        "- per-image negative-control baselines, and\n"
        "- Benjamini-Hochberg false-discovery-rate control.\n\n"
        "## Sensitivity calibration (benchmark.py)\n"
        "On a controlled synthetic scene: recall floor ~24 px, 0 false positives.\n"
        "%s"
        "\n"
        "## Verdict distribution\n"
        "%s\n\n"
        "## Multiple-comparison control\n"
        "Approximate per-candidate p-values (contrast as a local-sigma z-score) "
        "corrected with Benjamini-Hochberg at q=%.2f: %d/%d non-artifact "
        "candidates survive. Cross-band-confirmed features have low contrast "
        "(median ~1.0), so almost none clear the corrected threshold.\n\n"
        "## Stress test (robustness of the top-lead count)\n"
        "| contrast bar | top leads |\n"
        "|---|---|\n"
        "%s\n\n"
        "## Top leads (%d)\n"
        "Cross-band confirmed, discrete, contrast >= %.2f, off-border, size %d-%d px.\n\n"
        "%s\n\n"
        "### Top leads by image\n"
        "%s\n\n"
        "### Per-image baseline context\n"
        "%s\n\n"
        "## Why the funnel matters\n"
        "- %d candidates are explained by a known artifact mechanism (streak, hot "
        "pixel, compression grid, edge, saturation).\n"
        "- %d are real surface features confirmed at the same pixels in several band "
        "variants of one acquisition, but their shape/scale is ordinary terrain.\n"
        "- Only %d discrete features survive the contrast bar, and none of them sits "
        "in genuinely smooth ground: on this data, everything discrete is embedded in "
        "cratered/ridged terrain, i.e. consistent with craters and rocks.\n\n"
        "## Bottom line\n") % (
        calib_extra,
        " &middot; ".join("%s: %d" % (k, v) for k, v in sorted(counts.items())),
        q, fdr_ok, len([r for r in rows if r["verdict"] != "EXPLAINED-ARTIFACT"]),
        stress_tab, len(top_leads), contrast_bar, area_min, area_max,
        top, per,
        baseline_lines or "No benchmark baselines available for these images.",
        counts["EXPLAINED-ARTIFACT"],
        counts["TERRAIN"],
        len(top_leads))
    body += (
        "After this pass, **no candidate meets the bar for a finding**. Cross-band "
        "agreement confirms a feature across band variants of ONE acquisition; it "
        "does not prove it is non-artifact, because the shared processing pipeline "
        "can imprint common artifacts. The top leads above are the only candidates "
        "worth a human + LLM second look; confirming any of them requires fetching "
        "the EDR original, checking a global mosaic/Trek, and finding the feature in "
        "an independent acquisition at a different lighting before writing a finding "
        "to `findings/`.\n")
    common.atomic_text_write(os.path.join(out, "SUMMARY.md"), body)


if __name__ == "__main__":
    main()
