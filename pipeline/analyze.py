"""AI-assisted anomaly analysis.

After `detect.py` flags candidates and `mark.py` draws them, this step:
  1. enhances each candidate crop several independent ways,
  2. measures physical/image features with numpy,
  3. evaluates it against the known-artifact checklist (docs/ARTIFACTS.md),
  4. checks for matching features in related frames of the same scene,
  5. ranks candidates and writes an HTML investigation report,
  optionally asking a vision LLM for a second opinion (env AI_LLM_KEY etc.).

Only the LLM path needs a network/API key; everything else is offline.
"""

import argparse
import base64
import csv
import html
import json
import math
import os
import re
import sys
import urllib.request

import common
import detect
import numpy as np
import overlay
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Border-touching candidates are only kept when they are exceptionally
# strong: image edges host calibration strips, trailing dark bands and
# vignetting, which masquerade as anomalies.
EDGE_CONTRAST_FLOOR = 5.0


def box_blur(arr, size):
    return detect.box_blur(arr, size)


def load_gray(path):
    return common.load_gray(path)


def enhance_variants(crop):
    """Independent enhancements of the crop array (float 0-255)."""
    out = {}
    lo, hi = np.percentile(crop, (0.5, 99.5))
    if hi - lo < 1:
        hi = lo + 1
    out["stretch"] = np.clip((crop - lo) * (255.0 / (hi - lo)), 0, 255)
    bg = box_blur(crop, max(5, min(65, int(min(crop.shape) / 2))))
    res = crop - bg
    lo2, hi2 = np.percentile(res, (2, 98))
    if hi2 - lo2 < 1:
        hi2 = lo2 + 1
    out["residual"] = np.clip((res - lo2) * (255.0 / (hi2 - lo2)), 0, 255)
    im = Image.fromarray(out["stretch"].astype(np.uint8))
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=1))
    out["upscale"] = np.asarray(im, dtype=np.float32)
    return out


def make_strip(variants, height=256, box=None):
    """Tile stretch|residual|upscale variants into one RGB strip image.

    box=(fx, fy, fw, fh) draws a red rectangle around the flagged feature on
    every tile so the anomaly is clearly marked in the zoomed view.
    """
    tiles = []
    for key in ("stretch", "residual", "upscale"):
        a = variants[key]
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGB")
        s = height / float(im.height)
        im = im.resize((max(1, int(im.width * s)), height), Image.LANCZOS)
        tiles.append(im)
    w = sum(t.width for t in tiles)
    strip = Image.new("RGB", (w, height), (20, 20, 20))
    x = 0
    for t in tiles:
        strip.paste(t, (x, 0))
        x += t.width
    if box is not None:
        d = ImageDraw.Draw(strip)
        # box coords are in pre-resize crop pixel space; tiles were scaled by
        # s = height/crop_h, so scale the box by the same factor or it lands
        # offset from the feature on any crop that is not `height` px tall.
        s = height / float(variants["stretch"].shape[0])
        fx, fy, fw, fh = (max(0, int(round(v * s))) for v in box)
        lw = 2 if min(fw, fh) >= 8 else 1
        for k in range(len(tiles)):
            tx = k * tiles[0].width
            for o in (-lw, 0):  # double stroke stays visible on any background
                d.rectangle([tx + fx - lw + o, fy - lw + o,
                             tx + fx + fw + lw - 1 + o, fy + fh + lw - 1 + o],
                            outline=(255, 40, 40))
    return strip


def make_overview(arr, boxes, max_side=1600):
    """One 'zoomed out' full-frame view per source image with every candidate
    boxed in red and numbered (boxes: list of (x, y, w, h, label))."""
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGB")
    H, W = arr.shape
    s = min(1.0, max_side / float(max(W, H)))
    if s < 1.0:
        im = im.resize((max(1, int(W * s)), max(1, int(H * s))), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(22)
    except TypeError:
        font = ImageFont.load_default()
    lw = max(1, int(round(2 * s)))
    for x, y, w, h, label in boxes:
        bx0, by0, bx1, by1 = x * s, y * s, (x + w) * s, (y + h) * s
        d.rectangle([bx0, by0, bx1, by1], outline=(255, 40, 40), width=lw)
        txt = str(label)
        tb = d.textbbox((0, 0), txt, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        px, py = bx0 + 2, by0 - th - 6
        if py < 2:
            py = by1 + 4
        px = min(max(2, px), max(2, im.width - tw - 4))
        py = min(max(2, py), max(2, im.height - th - 4))
        d.rectangle([px - 3, py - 3, px + tw + 3, py + th + 3], fill=(10, 10, 10))
        d.text((px, py), txt, fill=(255, 210, 60), font=font)
    return im


def measure(crop, fx, fy, fw, fh):
    fg = crop[fy:fy + fh, fx:fx + fw]
    mask = np.ones(crop.shape, dtype=bool)
    mask[fy:fy + fh, fx:fx + fw] = False
    bg = crop[mask]
    fg_mean, bg_mean = float(fg.mean()), float(bg.mean())
    bg_std = float(bg.std()) + 1e-6

    # Column-smear probe (docs/ARTIFACTS.md: blooming/smear, bad columns):
    # do the box's columns keep the feature's bright/dark deviation well
    # above/below the box? A discrete object does not; CCD smear and dead
    # columns do. Probe = the box's columns outside the box; reference =
    # background excluding both the box and its columns.
    smear = 0.0
    smear_narrow = False
    probe = np.concatenate([crop[:fy, fx:fx + fw].ravel(),
                            crop[fy + fh:, fx:fx + fw].ravel()])
    ref_mask = np.ones(crop.shape, dtype=bool)
    ref_mask[:, fx:fx + fw] = False
    ref_mask[fy:fy + fh, :] = False
    ref = crop[ref_mask]
    if probe.size >= 16 and ref.size >= 16:
        smear = round(abs(float(probe.mean()) - float(ref.mean())) /
                      (float(ref.std()) + 1e-6), 2)
        # Only *narrow* boxes count as candidate smear/dead-column: a wide
        # box whose columns continue beyond it is more likely linear terrain
        # (rille, ridge), which must not be auto-debunked.
        smear_narrow = bool(fw <= max(6, int(0.1 * crop.shape[1])))

    feats = {
        "polarity": "bright" if fg_mean >= bg_mean else "dark",
        "contrast": round(abs(fg_mean - bg_mean) / bg_std, 2),
        "fg_mean": round(fg_mean, 1),
        "bg_mean": round(bg_mean, 1),
        "bg_std": round(bg_std, 2),
        "sat_frac": round(float((fg >= 253).mean()), 3),
        "dark_frac": round(float((fg <= 2).mean()), 3),
        "texture": round(float(fg.std()), 1),
        "column_smear": smear,
        "smear_narrow": smear_narrow,
    }
    return feats


def grid_energy(crop):
    """Spectral concentration: fraction of non-DC power in the top ~1% of bins.

    A 2D FFT power spectrum that is concentrated in a few sharp peaks is the
    signature of a periodic sensor/compression structure (CCD grid, JPEG/JP2
    block lattice). Natural surface texture spreads power across many
    frequencies, so its spectrum is diffuse and this ratio stays low. Returns
    0-1; higher = more periodic/grid-like.
    """
    a = np.asarray(crop, dtype=np.float32)
    if a.size < 64:
        return 0.0
    a = a - a.mean()
    # Bound the FFT size for speed + robustness (grid artifacts survive at any
    # size, so downscaling a large crop keeps the discriminator valid).
    H, W = a.shape
    maxd = 256
    if H > maxd or W > maxd:
        s = maxd / float(max(H, W))
        im = Image.fromarray(a).convert("L")
        a = np.asarray(im.resize((max(8, int(W * s)), max(8, int(H * s))),
                                 Image.BILINEAR), dtype=np.float32)
    power = np.abs(np.fft.rfft2(a)) ** 2
    power[0, 0] = 0.0  # remove DC
    total = float(power.sum())
    if total <= 1e-9:
        return 0.0
    flat = power.ravel()
    k = max(1, int(round(flat.size * 0.01)))
    top = float(np.partition(flat, -k)[-k:].sum())
    return round(top / total, 4)


def edge_sharpness(crop, fx, fy, fw, fh):
    """Mean gradient magnitude inside the feature box, normalised by scene noise.

    A genuine discrete object has a sharp boundary (high local gradient); a
    blurred/aliased feature or defocus smear has a weak boundary. Measured as
    mean |gx|+|gy| over the flagged box divided by the image's global std so
    the score is contrast-independent.
    """
    a = np.asarray(crop, dtype=np.float32)
    H, W = a.shape
    fx0, fy0 = max(0, fx), max(0, fy)
    fx1, fy1 = min(W, fx + fw), min(H, fy + fh)
    if fx1 <= fx0 or fy1 <= fy0:
        return 0.0
    gy, gx = np.gradient(a)
    g = np.abs(gx) + np.abs(gy)
    region = g[fy0:fy1, fx0:fx1]
    if region.size == 0:
        return 0.0
    # Peak boundary gradient (95th percentile inside the box), normalized by
    # the scene noise level so the score is contrast-independent. A sharp edge
    # has a thin, intense gradient peak; a blurred/defocus edge has a weaker,
    # spread one.
    norm = float(a.std()) + 1e-6
    return round(float(np.percentile(region, 95)) / norm, 4)


def contrast_stability(crop, fx, fy, fw, fh):
    """Robustness of a feature's contrast as the measurement window is resized.

    Measures local contrast (|fg-bg|/bg_std) at 0.8x, 1.0x and 1.25x the box
    around the feature centre. A real extended surface feature keeps roughly
    the same contrast at every window (stability near 1); an isolated hot pixel
    or speckle loses contrast the moment the window grows (stability drops).
    Returns 1 - coefficient of variation.
    """
    a = np.asarray(crop, dtype=np.float32)
    H, W = a.shape
    cx, cy = fx + fw / 2.0, fy + fh / 2.0
    vals = []
    for sc in (0.8, 1.0, 1.25):
        w = max(1, int(round(fw * sc)))
        h = max(1, int(round(fh * sc)))
        x0 = max(0, int(round(cx - w / 2.0)))
        y0 = max(0, int(round(cy - h / 2.0)))
        x0 = min(x0, W - w)
        y0 = min(y0, H - h)
        fg = a[y0:y0 + h, x0:x0 + w]
        mask = np.ones(a.shape, dtype=bool)
        mask[y0:y0 + h, x0:x0 + w] = False
        bg = a[mask]
        if fg.size < 4 or bg.size < 4 or float(bg.std()) <= 1e-9:
            continue
        vals.append(abs(float(fg.mean()) - float(bg.mean())) / (float(bg.std()) + 1e-6))
    if len(vals) < 2:
        return 0.0
    mean = float(np.mean(vals))
    if mean <= 1e-9:
        return 0.0
    cv = float(np.std(vals)) / mean
    return round(max(0.0, 1.0 - cv), 4)


def analyze_candidate(row, arr, max_crop):
    H, W = arr.shape
    x, y, w, h = int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"])
    margin = int(0.5 * max(w, h))
    x0, y0 = max(0, x - margin), max(0, y - margin)
    x1, y1 = min(W, x + w + margin), min(H, y + h + margin)
    crop = arr[y0:y1, x0:x1]
    scale = 1.0
    if crop.shape[0] > max_crop or crop.shape[1] > max_crop:
        scale = max_crop / float(max(crop.shape))
        crop = np.asarray(
            Image.fromarray(crop.astype(np.uint8)).resize(
                (max(8, int(crop.shape[1] * scale)), max(8, int(crop.shape[0] * scale))),
                Image.BILINEAR), dtype=np.float32)
    fx = int((x - x0) * scale)
    fy = int((y - y0) * scale)
    fw = max(1, int(w * scale))
    fh = max(1, int(h * scale))
    fx = min(fx, crop.shape[1] - 2)
    fy = min(fy, crop.shape[0] - 2)
    fw = min(fw, crop.shape[1] - fx)
    fh = min(fh, crop.shape[0] - fy)

    feats = measure(crop, fx, fy, fw, fh)
    feats.update({
        "area_px": int(w) * int(h),
        "aspect": round(max(w, h) / float(max(1, min(w, h))), 2),
        "fill": float(row["fill"]),
        "x": int(x), "y": int(y), "w": int(w), "h": int(h),
        # box position within the analysis crop (for marking the strip)
        "fx": fx, "fy": fy, "fw": fw, "fh": fh,
    })
    xdist = min(x % 8, 8 - (x % 8))
    ydist = min(y % 8, 8 - (y % 8))
    feats["on_grid8"] = xdist <= 2 and ydist <= 2
    # New rigor metrics: spectral grid-energy, boundary sharpness, and
    # contrast stability across window sizes (see their docstrings).
    feats["grid_energy"] = grid_energy(crop)
    feats["edge_sharpness"] = edge_sharpness(crop, fx, fy, fw, fh)
    feats["contrast_stability"] = contrast_stability(crop, fx, fy, fw, fh)
    feats["near_edge"] = bool(x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1)
    feats["dark_band"] = bool(feats["dark_frac"] >= 0.9 and (y <= 0.02 * H or y + h >= 0.98 * H))
    # Corner probe (docs/ARTIFACTS.md: vignetting): box center close to an
    # image corner is prime territory for lens falloff / calibration corners.
    cx, cy = x + w / 2.0, y + h / 2.0
    corner_dist = min(math.hypot(cx - px, cy - py)
                      for px, py in ((0.0, 0.0), (W, 0.0), (0.0, H), (W, H)))
    feats["in_corner"] = bool(corner_dist <= 0.07 * math.hypot(W, H))
    return crop, feats


def artifact_flags(feats):
    flags = {}
    aspect = feats["aspect"]
    if aspect >= 4 and (feats["w"] <= 12 or feats["h"] <= 12):
        flags["streak"] = "thin, elongated: likely bad column/row, seam, or cosmic-ray trail"
    if feats["area_px"] <= 800 and feats["sat_frac"] >= 0.3 and feats["contrast"] >= 3:
        flags["hot_pixel"] = "tiny, saturated, high contrast: likely hot pixel / cosmic ray hit"
    if feats["area_px"] < 1500 and aspect < 3:
        flags["small_blob"] = "small, isolated: too few pixels to distinguish surface feature from sensor noise"
    if (feats["on_grid8"] and feats["fill"] <= 0.3) or (feats["fill"] <= 0.12 and aspect < 3):
        flags["compression"] = "sparse/boxy, aligned to 8px grid: likely JPEG/JP2 compression artifact"
    if feats["sat_frac"] >= 0.5:
        flags["saturation"] = "more than half the region is blown out: highlight clipping, not structure"
    if feats["near_edge"]:
        flags["edge_artifact"] = "touches image border: possible calibration strip / edge effect"
    if feats["dark_band"]:
        flags["dark_band"] = "near-dark at top/bottom edge: HiRISE trailing-edge dark band artifact"
    if aspect >= 4 and feats["area_px"] >= 50000:
        flags["elongated_large"] = "large thin region: likely ridgeline/scan artifact rather than discrete object"
    if feats.get("smear_narrow") and feats.get("column_smear", 0.0) >= 2.0:
        flags["column_smear"] = ("narrow column stays bright/dark beyond the box: "
                                 "CCD smear/blooming or a dead column, not an object")
    if feats.get("in_corner"):
        flags["corner"] = "in image corner: vignetting / calibration corner territory"
    return flags


def interest_score(feats, flags, matches):
    score = 35.0 * min(feats["contrast"] / 4.0, 1.0)
    score += 15.0 * min(feats["area_px"] / 30000.0, 1.0)
    score += 15.0 * (1.0 - min((feats["aspect"] - 1) / 9.0, 1.0))
    if not feats["near_edge"]:
        score += 10.0
    if feats["sat_frac"] < 0.3:
        score += 10.0
    score += 15.0 * min(matches / 3.0, 1.0)
    for flag in flags:
        score -= 30.0 if flag == "streak" else (15.0 if flag == "small_blob" else 20.0)
    return round(max(0.0, min(100.0, score)), 1)


def evidence_class(flags, matches):
    if set(flags) - {"small_blob"}:
        return 1
    if matches >= 2:
        return 3
    return 2


def verdict_text(flags, cls, matches):
    if flags:
        reasons = "; ".join(flags.values())
        return "Artifact: " + reasons
    base = "Candidate surface feature"
    if matches >= 1:
        base += " (corresponding feature found in %d related frame%s)" % (
            matches, "" if matches == 1 else "s")
    return base + " - evidence class %d (weak, single acquisition)" % cls


def sibling_stem(path):
    base = os.path.basename(path)
    m = re.match(r"^(ESP_\d+_\d+|PIA\d+)", base)
    return m.group(1) if m else os.path.splitext(base)[0]


def precompute(candidates):
    """Cache image sizes and absolute geometry for candidate matching."""
    size_cache = {}
    recs = {}
    for i, row in enumerate(candidates):
        path = row["path"]
        if path not in size_cache:
            try:
                size_cache[path] = load_size(path)
            except Exception:
                size_cache[path] = None
        size = size_cache[path]
        if not size:
            continue
        W, H = size
        recs[i] = {
            "stem": sibling_stem(path),
            "path": path,
            "W": W, "H": H,
            "x": int(row["x"]), "y": int(row["y"]),
            "w": int(row["w"]), "h": int(row["h"]),
        }
    return recs


def sibling_index(recs):
    """(stem, W, H) -> candidate indices in that same-size sibling group."""
    groups = {}
    for i, r in recs.items():
        groups.setdefault((r["stem"], r["W"], r["H"]), []).append(i)
    return groups


def find_matches(recs, idx, groups=None):
    """Count distinct same-size sibling images with a candidate at ~the same location.

    Only sibling products with identical dimensions (e.g. HiRISE MIRB/MRGB band
    variants of one footprint) are compared, using absolute pixel coordinates.
    This is an honest 'same feature in a related frame' signal.

    groups: optional precomputed sibling_index(recs) for O(group) lookups;
    without it the index is built on the fly (kept for backward compatibility).
    """
    a = recs[idx]
    if groups is None:
        groups = sibling_index(recs)
    seen = set()
    for j in groups.get((a["stem"], a["W"], a["H"]), ()):
        if j == idx:
            continue
        b = recs[j]
        if b["path"] == a["path"]:
            continue
        tx = 0.02 * a["W"] + 4
        ty = 0.02 * a["H"] + 4
        if abs(a["x"] - b["x"]) <= tx and abs(a["y"] - b["y"]) <= ty:
            if abs(a["w"] / max(1e-6, b["w"])) < 3.0 and abs(a["h"] / max(1e-6, b["h"])) < 3.0:
                seen.add(b["path"])
    return len(seen)


def load_size(path):
    """(width, height) via common.image_dims so PDS products work too."""
    try:
        return common.image_dims(path)
    except Exception:
        with Image.open(path) as im:
            return im.size


def llm_verdict(strip_path, feats, flags, cls):
    key = os.environ.get("AI_LLM_KEY")
    endpoint = os.environ.get("AI_LLM_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions")
    model = os.environ.get("AI_LLM_MODEL", "meta-llama/llama-3.2-90b-vision-instruct")
    if not key:
        return ""
    with open(strip_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    prompt = (
        "You are a rigorous NASA planetary imagery analyst. An anomaly detector "
        "flagged the boxed region in this enhancement strip (stretch | residual | upscale) "
        "from a Moon/Mars image. Features: %s. Heuristic artifact flags: %s. "
        "Answer in 2-3 sentences: is this a real surface feature or a known artifact "
        "(compression, cosmic ray, sensor defect, shadow, optics)? Give a confidence." %
        (json.dumps(feats), json.dumps(flags)))
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ]}],
        "max_tokens": 300,
    }
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return "LLM error: %s" % e


def main(argv=None):
    p = argparse.ArgumentParser(description="Enhance, evaluate and investigate anomaly candidates")
    p.add_argument("--candidates", required=True)
    p.add_argument("--out", default="data/anomalies/analysis")
    p.add_argument("--max-crop", type=int, default=512, help="analysis crop cap per side")
    p.add_argument("--top", type=int, default=12, help="how many top candidates to ask the LLM about")
    p.add_argument("--llm", action="store_true", help="ask vision LLM for top candidates (requires env AI_LLM_KEY)")
    a = p.parse_args(argv)
    common.set_audit(common.audit_path_for(a.out))
    start = common.time.time()

    with open(a.candidates, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    common.log("info", "analyze: %d candidates" % len(rows))

    crops_dir = os.path.join(a.out, "crops")
    os.makedirs(crops_dir, exist_ok=True)
    overviews_dir = os.path.join(a.out, "overviews")
    os.makedirs(overviews_dir, exist_ok=True)

    evaluated = []
    recs = precompute(rows)
    groups = sibling_index(recs)
    by_image = {}
    for i, row in enumerate(rows):
        by_image.setdefault(row["path"], []).append((i, row))
    done = 0
    skipped = 0
    skipped_overlays = 0
    dropped_edge = 0
    for path, group in sorted(by_image.items()):
        if not os.path.exists(path):
            skipped += len(group)
            continue
        try:
            arr = load_gray(path)
        except Exception:
            skipped += len(group)
            continue
        H, W = arr.shape
        ov = overlay.text_overlay_score(arr)
        if ov["flagged"]:
            skipped_overlays += len(group)
            continue
        valid = []
        for i, row in group:
            if not common.validate_box(int(row["x"]), int(row["y"]),
                                       int(row["w"]), int(row["h"]), W, H):
                skipped += 1
                continue
            if ov["boxes"] and overlay.box_overlaps_any(
                    (int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"])),
                    ov["boxes"], 0.3):
                skipped += 1
                continue
            valid.append((i, row))
        # analyze everything first so the edge rule can see the measured
        # contrast, then number and render only the survivors
        analyzed = []
        for i, row in valid:
            crop, feats = analyze_candidate(row, arr, a.max_crop)
            if feats["near_edge"] and feats["contrast"] < EDGE_CONTRAST_FLOOR:
                dropped_edge += 1
                continue
            analyzed.append((i, row, crop, feats))
        # one numbered overview per source image
        stem = re.sub(r"[^A-Za-z0-9_.-]", "_",
                      os.path.splitext(os.path.basename(path))[0])[:48]
        ov_boxes = [(int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"]), n)
                    for n, (i, r, c, f) in enumerate(analyzed, start=1)]
        ov_name = "%s__overview_numbered.jpg" % stem
        make_overview(arr, ov_boxes).save(
            os.path.join(overviews_dir, ov_name), quality=88)
        for n, (i, row, crop, feats) in enumerate(analyzed, start=1):
            flags = artifact_flags(feats)
            matches = find_matches(recs, i, groups)
            cls = evidence_class(flags, matches)
            feats["score"] = interest_score(feats, flags, matches)
            feats["evidence_class"] = cls
            feats["matches"] = matches
            feats["verdict"] = verdict_text(flags, cls, matches)
            feats["flags"] = ",".join(sorted(flags))

            strip = make_strip(
                enhance_variants(crop),
                box=(feats["fx"], feats["fy"], feats["fw"], feats["fh"]))
            x, y, w, h = int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"])
            strip_name = "%s__n%03d_x%04d_y%04d_%dx%d.jpg" % (stem, n, x, y, w, h)
            strip_path = os.path.join(crops_dir, strip_name)
            strip.save(strip_path, quality=92)
            feats["_strip"] = os.path.join("crops", strip_name)
            feats["_overview"] = os.path.join("overviews", ov_name)
            feats["_num"] = n
            feats["image"] = row["image"]
            feats["path"] = path
            evaluated.append(feats)
            done += 1
            if done % 500 == 0:
                print("analyzed %d/%d" % (done, len(rows)), flush=True)

    evaluated.sort(key=lambda r: r["score"], reverse=True)
    fields = ["image", "x", "y", "w", "h", "contrast", "area_px", "aspect", "fill",
              "polarity", "sat_frac", "dark_frac", "on_grid8", "near_edge",
              "in_corner", "column_smear", "matches", "grid_energy",
              "edge_sharpness", "contrast_stability",
              "evidence_class", "score", "verdict", "flags"]
    common.atomic_csv_write(os.path.join(a.out, "evaluated.csv"), evaluated, fields)

    llm_notes = []
    if a.llm and os.environ.get("AI_LLM_KEY"):
        for r in evaluated[:a.top]:
            verdict = llm_verdict(os.path.join(a.out, r["_strip"]), r, r.get("flags", ""), r["evidence_class"])
            llm_notes.append((r, verdict))
    elif a.llm:
        print("LLM requested but AI_LLM_KEY not set; skipping LLM verdicts.")

    write_report(a.out, evaluated, llm_notes,
                 {"skipped_overlays": skipped_overlays, "dropped_edge": dropped_edge})
    common.log("info", "analyze: %d candidates -> %s" % (len(evaluated), a.out))
    common.audit({
        "event": "analyze",
        "cmd": " ".join(sys.argv),
        "candidates": len(rows), "evaluated": len(evaluated), "skipped": skipped,
        "skipped_overlays": skipped_overlays, "dropped_edge": dropped_edge,
        "out": os.path.abspath(a.out),
        "candidates_sha256": common.sha256_file(a.candidates),
        "evaluated_sha256": common.sha256_file(os.path.join(a.out, "evaluated.csv")),
        "seconds": round(common.time.time() - start, 1),
    })


def _rel(path, out):
    """Relative URL from the report directory to a file path (forward slashes)."""
    return os.path.relpath(path, out).replace("\\", "/")


def _url(p):
    """Asset URL relative to the report dir, always forward-slashed."""
    return p.replace("\\", "/")


def write_report(out, evaluated, llm_notes, stats=None):
    by_img = {}
    for r in evaluated:
        by_img.setdefault(r["image"], []).append(r)

    stats = stats or {}
    notes = []
    if stats.get("skipped_overlays"):
        notes.append("%d candidate(s) from text/annotation-overlaid images were excluded" %
                     stats["skipped_overlays"])
    if stats.get("dropped_edge"):
        notes.append("%d border-touching candidate(s) below the contrast floor were dropped" %
                     stats["dropped_edge"])
    notes_html = (" <span class='notes'>(%s)</span>" % "; ".join(notes)) if notes else ""

    cards = []
    for r in evaluated:
        flags = r["flags"].split(",") if r["flags"] else []
        flag_html = "".join(f"<li>{html.escape(f)}</li>" for f in flags) or "<li>no artifact flags</li>"
        llm = "".join(
            f"<div class='llm'><b>LLM:</b> {html.escape(v)}</div>"
            for rr, v in llm_notes if rr is r)
        orig_link = _rel(r["path"], out) if r.get("path") else ""
        name_html = (f"<a href='{html.escape(orig_link)}'>{html.escape(r['image'])}</a>"
                     if orig_link else html.escape(r["image"]))
        ov_rel = html.escape(_url(r["_overview"]))
        strip_url = html.escape(_url(r["_strip"]))
        cards.append(
            "<div class='card'>"
            "<div class='imgs'>"
            f"<figure><a href='{ov_rel}'><img src='{ov_rel}'></a>"
            "<figcaption>original frame &mdash; all anomalies numbered</figcaption></figure>"
            "<figure><img src='{strip}'>"
            f"<figcaption>zoomed crop <b class='num'>#{r['_num']}</b> &middot; anomaly boxed</figcaption></figure>"
            "</div>"
            f"<p><span class='num'>#{r['_num']}</span> <b>{name_html}</b> bbox {r['x']},{r['y']} {r['w']}x{r['h']} "
            f"<span class='cls'>class {r['evidence_class']}</span> "
            f"<span class='sc'>interest {r['score']}</span></p>"
            "<p class='links'>source: <a href='{orig}'>{fname}</a> "
            "&middot; numbered map: <a href='{ovlink}'>{oname}</a> "
            "&middot; zoomed crop: <b>{cname}</b></p>"
            "<p>contrast {contrast} | {area_px}px&sup2; | aspect {aspect} | fill {fill} | "
            "polarity {polarity} | matches {matches}</p>"
            "<p class='verdict'>{verdict}</p>"
            "<ul class='flags'>{flags}</ul>{llm}</div>".format(
                strip=strip_url,
                image=name_html, x=r["x"], y=r["y"], w=r["w"], h=r["h"],
                cls=r["evidence_class"], score=r["score"],
                orig=html.escape(orig_link), fname=html.escape(r["image"]),
                ovlink=ov_rel, oname=html.escape(os.path.basename(r["_overview"])),
                cname=html.escape(os.path.basename(r["_strip"])),
                contrast=r["contrast"],
                area_px=r["area_px"], aspect=r["aspect"], fill=r["fill"],
                polarity=r["polarity"], matches=r["matches"], verdict=html.escape(r["verdict"]),
                flags=flag_html, llm=llm))

    top = evaluated[:15]
    top_html = "".join(
        "<tr><td>{}</td><td>{}</td><td>{},{}</td><td>{}</td><td>{}</td></tr>".format(
            f"<span class='num'>#{r['_num']}</span> "
            f"<a href='{html.escape(_url(r['_overview']))}'>{r['image']}</a>",
            r["score"], r["x"], r["y"], r["evidence_class"], html.escape(r["verdict"]))
        for r in top)

    img_summary = "".join(
        "<tr><td>{}</td><td>{}</td><td>{:.0%}</td></tr>".format(
            html.escape(img), len(lst), sum(r["evidence_class"] >= 3 for r in lst) / max(1, len(lst)))
        for img, lst in sorted(by_img.items()))

    style = ("body{font-family:sans-serif;background:#0d1117;color:#d8dee6;margin:1.5rem}"
             ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(560px,1fr));gap:1rem}"
             ".card{border:1px solid #2a3138;padding:.6rem;background:#151b23}"
             ".card img{max-width:100%;border:1px solid #333}"
             ".imgs{display:flex;gap:.6rem;align-items:flex-start;margin-bottom:.4rem}"
             ".imgs figure{margin:0;flex:1 1 0;min-width:0}"
             ".imgs figcaption{font-size:.7rem;color:#8b949e;margin-top:.15rem}"
             ".num{color:#ffd24a;font-weight:bold}"
             ".cls{color:#f0b429}.sc{color:#7ee787}.links{font-size:.75rem}"
             ".links a,.card h3 a,a{color:#58a6ff}"
             "table{border-collapse:collapse;width:100%;margin-bottom:1rem}"
             "th,td{border:1px solid #2a3138;padding:.3rem .5rem;font-size:.8rem;text-align:left}"
             ".verdict{font-weight:bold}.flags{margin:.3rem 0 0 1rem;font-size:.75rem;color:#ff9b9b}"
             ".notes{color:#8b949e;font-size:.85rem}"
             ".llm{background:#1c2733;padding:.4rem;font-size:.8rem;margin-top:.3rem}")
    page = ("<!doctype html><html><head><meta charset='utf-8'><title>Anomaly investigation</title>"
            "<style>{}</style></head><body>"
            "<h1>Anomaly investigation</h1>"
            "<p>{} candidates analyzed, top interest {:.1f}, {} with artifact flags, "
            "{} class-3+ candidates.{}</p>"
            "<h2>Top candidates</h2><table><tr><th>image</th><th>score</th><th>xy</th>"
            "<th>class</th><th>verdict</th></tr>{}</table>"
            "<h2>Per image</h2><table><tr><th>image</th><th>candidates</th><th>class3+</th></tr>"
            "{}</table>"
            "<h2>All candidates</h2><div class='grid'>{}</div></body></html>".format(
                style, len(evaluated), evaluated[0]["score"] if evaluated else 0,
                sum(1 for r in evaluated if r["flags"]),
                sum(1 for r in evaluated if r["evidence_class"] >= 3),
                notes_html, top_html, img_summary, "".join(cards)))
    common.atomic_text_write(os.path.join(out, "report.html"), page)


if __name__ == "__main__":
    main()
