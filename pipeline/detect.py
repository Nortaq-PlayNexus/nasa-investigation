import argparse
import csv
import os
import re

import numpy as np
from PIL import Image

import common

try:
    from scipy.ndimage import label as _scipy_label

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

def box_blur(arr, size):
    pad = size // 2
    arr = np.asarray(arr, dtype=np.float32)
    if pad == 0:
        return arr
    padded = np.pad(arr, ((pad, pad), (pad, pad)), mode="edge")
    h, w = arr.shape
    cs = np.zeros((h + 2 * pad + 1, w + 2 * pad + 1), dtype=np.float64)
    cs[1:, 1:] = np.cumsum(np.cumsum(padded, axis=0), axis=1)
    k = 2 * pad + 1
    a = cs[k:k + h, k:k + w]
    b = cs[:h, k:k + w]
    c = cs[k:k + h, :w]
    d = cs[:h, :w]
    return ((a - b - c + d) / float(k * k)).astype(np.float32)


def mask_components(mask):
    if HAS_SCIPY:
        labels, n = _scipy_label(mask.astype(np.uint8))
        return labels, int(n)
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    label = 0
    for y in range(h):
        for x in range(w):
            if mask[y, x] and labels[y, x] == 0:
                label += 1
                stack = [(y, x)]
                labels[y, x] = label
                while stack:
                    cy, cx = stack.pop()
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and labels[ny, nx] == 0:
                                labels[ny, nx] = label
                                stack.append((ny, nx))
    return labels, label


def _overlap_frac(a, b):
    ax0, ay0, ax1, ay1 = a["x"], a["y"], a["x"] + a["w"], a["y"] + a["h"]
    bx0, by0, bx1, by1 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    return inter / float(min(a["w"] * a["h"], b["w"] * b["h"]))


def dedupe(found):
    kept = []
    for box in sorted(found, key=lambda b: b["scale"]):
        if any(_overlap_frac(box, k) > 0.5 for k in kept):
            continue
        kept.append(box)
    return kept


def component_pixels(mask, labels):
    ys_all, xs_all = np.where(mask)
    if len(ys_all) == 0:
        return []
    lab = labels[ys_all, xs_all]
    order = np.argsort(lab, kind="stable")
    ys_s, xs_s, lab_s = ys_all[order], xs_all[order], lab[order]
    cuts = np.flatnonzero(np.diff(lab_s)) + 1
    idx = np.split(np.arange(len(lab_s)), cuts)
    return [(ys_s[s], xs_s[s]) for s in idx]


def analyze(path, scales, z, min_size, max_scale_pixels):
    arr = common.load_gray(path)
    return analyze_array(arr, scales, z, min_size, max_scale_pixels, path=path)


def local_contrast_field(arr, rin=5, rout=15):
    """Local contrast of each pixel vs. an annular background ring.

    The classic 'military-grade' background estimator: instead of a flat blur,
    each pixel is compared to the mean/std of the ring around it, so a feature
    is only flagged when it stands out against *its immediate surroundings*,
    not against the coarse image mean. Implemented with running sums.
    """
    a = np.asarray(arr, dtype=np.float64)
    rin = max(1, int(rin))
    rout = max(rin + 1, int(rout))
    h, w = a.shape
    pad = rout
    padded = np.pad(a, ((pad, pad), (pad, pad)), mode="edge")
    cs = np.zeros((h + 2 * pad + 1, w + 2 * pad + 1), dtype=np.float64)
    cs2 = np.zeros_like(cs)
    p2 = padded * padded
    cs[1:, 1:] = np.cumsum(np.cumsum(padded, axis=0), axis=1)
    cs2[1:, 1:] = np.cumsum(np.cumsum(p2, axis=0), axis=1)

    def box(r):
        k = 2 * r + 1
        a_ = cs[k:k + h, k:k + w]
        b_ = cs[:h, k:k + w]
        c_ = cs[k:k + h, :w]
        d_ = cs[:h, :w]
        a2 = cs2[k:k + h, k:k + w]
        b2 = cs2[:h, k:k + w]
        c2 = cs2[k:k + h, :w]
        d2 = cs2[:h, :w]
        return (a_ - b_ - c_ + d_), (a2 - b2 - c2 + d2), float(k * k)

    so, s2o, no = box(rout)
    si, s2i, ni = box(rin)
    # ring = outer box minus inner box
    rs, rs2 = so - si, s2o - s2i
    ra = no - ni
    mean = rs / ra
    var = rs2 / ra - mean * mean
    var = np.clip(var, 0, None)
    field = (a - mean) / (np.sqrt(var) + 1e-6)
    return field.astype(np.float32)


def analyze_array(arr, scales, z, min_size, max_scale_pixels, method="box",
                  rin=5, rout=15, path=""):
    """Run the local-contrast detector on a loaded array.

    method:
      box     absolute deviation from a box blur (default, matches original)
      annulus local contrast vs. an annular ring background
    Returns a list of candidate dicts in the original (downscale-scaled)
    coordinate space.
    """
    im = Image.fromarray(arr.astype(np.float32))
    w0, h0 = im.size
    found = []
    for scale in sorted(scales, reverse=True):
        sw, sh = max(8, w0 // scale), max(8, h0 // scale)
        if sw * sh > max_scale_pixels:
            continue
        im_small = im.resize((sw, sh), Image.BILINEAR)
        a = np.asarray(im_small, dtype=np.float32)
        if method == "annulus":
            detail = np.abs(local_contrast_field(a, rin, rout))
            dmean, dstd = detail.mean(), detail.std() + 1e-6
            mask = detail > (dmean + z * dstd)
        else:
            smooth = box_blur(a, 9)
            detail = np.abs(a - smooth)
            dmean, dstd = detail.mean(), detail.std() + 1e-6
            mask = detail > (dmean + z * dstd)
        labels, n = mask_components(mask)
        for ys, xs in component_pixels(mask, labels):
            if len(xs) < min_size:
                continue
            y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
            box_area = (y1 - y0 + 1) * (x1 - x0 + 1)
            fill = len(xs) / float(box_area)
            score = float((detail[ys, xs].mean() - dmean) / dstd)
            found.append({
                "image": os.path.basename(path), "path": path, "scale": scale,
                "x": x0 * scale, "y": y0 * scale,
                "w": (x1 - x0 + 1) * scale, "h": (y1 - y0 + 1) * scale,
                "fill": round(fill, 3), "score": round(score, 2),
            })
    return dedupe(found)


def sun_shadow_sanity(arr, x, y, w, h, solar_azimuth_deg, solar_elevation_deg,
                      north_up=True, polarity="bright"):
    """How well a candidate's elongation/shadow matches the solar geometry.

    Thin wrapper over pipeline/photometry; returns a dict with score, angle,
    expected shadow direction, and a flag for 'no shadow where physics says
    there should be one'. A genuine elevated object leaves a shadow aligned
    with the sun's azimuth; a flat albedo patch or processing artifact does
    not.
    """
    import photometry
    margin = int(0.5 * max(w, h))
    H, W = arr.shape
    x0, y0 = max(0, x - margin), max(0, y - margin)
    x1, y1 = min(W, x + w + margin), min(H, y + h + margin)
    crop = arr[y0:y1, x0:x1]
    fx, fy = x - x0, y - y0
    align = photometry.shadow_alignment(
        crop, solar_azimuth_deg, solar_elevation_deg, north_up, polarity)
    shadow_px, conf = photometry.measure_shadow(
        crop, fx, fy, w, h, solar_azimuth_deg, north_up)
    return {
        "shadow_alignment": align.get("score"),
        "alignment_skipped": align.get("skipped"),
        "feature_angle_deg": align.get("angle_deg"),
        "expected_shadow_deg": align.get("shadow_deg"),
        "shadow_px": shadow_px,
        "shadow_confidence": conf,
    }


def main():
    p = argparse.ArgumentParser(description="Flag local contrast anomalies and emit a candidates CSV")
    p.add_argument("--dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--scales", default="4", help="downsample factors; finer scales find smaller features")
    p.add_argument("--z", type=float, default=3.0, help="z-score threshold on the detail map (lower = more candidates)")
    p.add_argument("--min-size", type=int, default=12, help="min blob area in downsampled pixels")
    p.add_argument("--max-scale-pixels", type=int, default=8000000,
                   help="skip a scale if it would process more pixels than this")
    p.add_argument("--method", choices=("box", "annulus"), default="box",
                   help="background estimator: box blur vs annular ring contrast")
    p.add_argument("--rin", type=int, default=5, help="annulus inner radius (pixels)")
    p.add_argument("--rout", type=int, default=15, help="annulus outer radius (pixels)")
    p.add_argument("--exts", default=".png")
    p.add_argument("--exclude-patterns", default="",
                   help="comma-separated regexes; any image whose basename matches any "
                        "pattern is skipped (e.g. annotated press graphics, infographics)")
    a = p.parse_args()

    scales = sorted({int(s) for s in a.scales.split(",") if s.strip()})
    exts = tuple(a.exts.split(","))
    exclude = [re.compile(pat) for pat in a.exclude_patterns.split(",") if pat.strip()]
    os.makedirs(a.out, exist_ok=True)
    candidates = []
    scanned = 0
    files = []
    for root, dirs, names in os.walk(a.dir):
        for n in names:
            if n.lower().endswith(exts):
                files.append(os.path.join(root, n))
    for path in sorted(files):
        base = os.path.basename(path)
        if any(pat.search(base) for pat in exclude):
            print("exclude {} (annotated/press graphic)".format(base))
            continue
        try:
            if a.method == "annulus":
                arr = common.load_gray(path)
                found = analyze_array(arr, scales, a.z, a.min_size,
                                      a.max_scale_pixels, method="annulus",
                                      rin=a.rin, rout=a.rout, path=path)
            else:
                found = analyze(path, scales, a.z, a.min_size, a.max_scale_pixels)
        except Exception as e:
            print("skip {} ({})".format(path, e))
            continue
        scanned += 1
        candidates.extend(found)
        print("{}: {} candidates".format(os.path.basename(path), len(found)))

    for box in candidates:
        box.pop("scale", None)
    with open(os.path.join(a.out, "candidates.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["image", "path", "x", "y", "w", "h", "fill", "score"])
        w.writeheader()
        w.writerows(candidates)
    print("scanned {} images, {} candidate regions -> {}".format(scanned, len(candidates), a.out))


if __name__ == "__main__":
    main()
