"""Synthetic-positives sensitivity calibration + negative controls.

Injects bright/dark Gaussian blobs of known size into either (a) a controlled
synthetic textured scene or (b) a real image, runs the real detector, and
measures recall per size -- so we know the honest minimum object size this
pipeline can see. A negative-control run on the clean scene/image counts
false positives, giving the baseline the candidates are judged against.

Use after detect.py to calibrate how much weight any candidate can carry.
"""

import argparse
import os
import random
import sys

import common
import detect
import numpy as np
from PIL import Image


def synthetic_scene(shape, seed=1):
    """Mid-tone textured background: smooth sinusoid field + gaussian noise."""
    rng = np.random.default_rng(seed)
    H, W = shape
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    field = (
        128.0
        + 18.0 * np.sin(2 * np.pi * xx / 540.0 + 0.5) * np.cos(2 * np.pi * yy / 540.0)
        + 12.0 * np.sin(2 * np.pi * (xx + yy) / 233.0)
        + 6.0 * np.sin(2 * np.pi * (xx - yy) / 97.0)
    )
    field += rng.normal(0.0, 7.0, field.shape).astype(np.float32)
    return np.clip(field, 0, 255)


def gaussian_disk(size, peak):
    r = size / 2.0
    sig = max(1.0, size / 6.0)
    y, x = np.mgrid[0:size, 0:size]
    d = np.sqrt((x - r + 0.5) ** 2 + (y - r + 0.5) ** 2)
    return peak * np.exp(-(d * d) / (2 * sig * sig))


def inject_blobs(arr, blobs):
    out = arr.copy()
    for cx, cy, size, peak in blobs:
        s = int(size)
        disk = gaussian_disk(s, peak)
        x0, y0 = int(cx - s / 2), int(cy - s / 2)
        x1, y1 = x0 + s, y0 + s
        rx0, ry0 = max(0, x0), max(0, y0)
        rx1, ry1 = min(arr.shape[1], x1), min(arr.shape[0], y1)
        if rx1 <= rx0 or ry1 <= ry0:
            continue
        d = disk[ry0 - y0:ry1 - y0, rx0 - x0:rx1 - x0]
        out[ry0:ry1, rx0:rx1] = np.clip(out[ry0:ry1, rx0:rx1] + d, 0, 255)
    return out


def blob_box(b):
    cx, cy, size, _ = b
    return (int(cx - size / 2), int(cy - size / 2), int(size), int(size))


def hit(box, blob):
    """Hit if the detected box covers the blob center or overlaps it well."""
    cx, cy, size, _ = blob
    if box["x"] <= cx <= box["x"] + box["w"] and box["y"] <= cy <= box["y"] + box["h"]:
        return True
    b0 = blob_box(blob)
    return iou(box, b0) > 0.2


def iou(a, b):
    ax0, ay0 = a["x"], a["y"]
    bx0, by0 = b[0], b[1]
    ax1, ay1 = ax0 + a["w"], ay0 + a["h"]
    bx1, by1 = bx0 + b[2], by0 + b[3]
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    a_area, b_area = a["w"] * a["h"], b[2] * b[3]
    return inter / float(a_area + b_area - inter)


def place_blobs(shape, sizes, seed, margin=60):
    rng = random.Random(seed)
    H, W = shape
    max_size = max(sizes)
    spacing = int(max_size * 3)
    cols = max(1, W // spacing)
    rows = max(1, H // spacing)
    grid = []
    for r in range(rows):
        for c in range(cols):
            grid.append((spacing * (c + 0.5), spacing * (r + 0.5)))
    rng.shuffle(grid)
    blobs = []
    si = 0
    for size in sizes:
        for polarity in (+1, -1):
            if si >= len(grid):
                break
            cx, cy = grid[si]
            si += 1
            cx += rng.uniform(-spacing * 0.2, spacing * 0.2)
            cy += rng.uniform(-spacing * 0.2, spacing * 0.2)
            cx = min(max(size + margin, cx), W - size - margin)
            cy = min(max(size + margin, cy), H - size - margin)
            if not common.validate_box(int(cx - size / 2), int(cy - size / 2),
                                       int(size), int(size), W, H):
                continue
            blobs.append((cx, cy, size, 220.0 * polarity))
    return blobs


def run_bench(arr, sizes, scales, z, min_size, seed, out_dir, scene_name,
              max_scale_pixels=8_000_000):
    """Inject blobs into `arr`, run the detector, report recall + clean FP count.

    Writes temporary scene PNGs into out_dir and removes them before returning,
    so direct callers (tests) do not leak files.
    """
    blobs = place_blobs(arr.shape, sizes, seed)
    injected = inject_blobs(arr, blobs)
    tmp = os.path.join(out_dir, "_bench_%s.png" % scene_name)
    clean_tmp = os.path.join(out_dir, "_clean_%s.png" % scene_name)
    try:
        Image.fromarray(injected.astype(np.uint8)).save(tmp)

        det = detect.analyze(tmp, scales, z, min_size, max_scale_pixels)
        matched = [False] * len(blobs)
        for box in det:
            for ti, t in enumerate(blobs):
                if not matched[ti] and hit(box, t):
                    matched[ti] = True

        recall = {}
        for size in sizes:
            n = sum(1 for b in blobs if b[2] == size)
            hit_n = sum(1 for i, b in enumerate(blobs) if b[2] == size and matched[i])
            recall[size] = (hit_n, n)

        Image.fromarray(arr.astype(np.uint8)).save(clean_tmp)
        neg = len(detect.analyze(clean_tmp, scales, z, min_size, max_scale_pixels))
        return recall, neg, len(det)
    finally:
        for f in (tmp, clean_tmp):
            try:
                os.remove(f)
            except OSError:
                pass


def main(argv=None):
    cfg = common.load_config()
    p = argparse.ArgumentParser(description="Measure detector sensitivity with injected blobs")
    p.add_argument("--image", default=None,
                   help="real image to inject into; default is a synthetic textured scene")
    p.add_argument("--out", default="data/anomalies/benchmark")
    p.add_argument("--scales", default=common.option_default(cfg, "detect_scales", "4"))
    p.add_argument("--z", type=float, default=common.option_default(cfg, "detect_z", 3.0))
    p.add_argument("--min-size", type=int,
                   default=common.option_default(cfg, "detect_min_size", 12))
    p.add_argument("--max-scale-pixels", type=int,
                   default=common.option_default(cfg, "detect_max_scale_pixels", 8_000_000),
                   help="skip a detector scale if it would process more pixels than this")
    p.add_argument("--sizes", default=common.option_default(cfg, "benchmark_sizes", "8,16,24,32,48,64,96,128"))
    p.add_argument("--seed", type=int, default=common.option_default(cfg, "benchmark_seed", 7))
    a = p.parse_args(argv)
    common.set_seed(a.seed)
    common.set_audit(common.audit_path_for(a.out))
    start = common.time.time()

    scales = [int(s) for s in a.scales.split(",")]
    sizes = [int(s) for s in a.sizes.split(",")]
    os.makedirs(a.out, exist_ok=True)

    if a.image and os.path.exists(a.image):
        arr = np.asarray(Image.open(a.image).convert("L"), dtype=np.float32)
        scene_name = os.path.splitext(os.path.basename(a.image))[0]
    else:
        arr = synthetic_scene((1800, 1800), seed=a.seed)
        scene_name = "synthetic"
        a.image = "synthetic textured scene (control)"

    recall, neg, n_det = run_bench(arr, sizes, scales, a.z, a.min_size, a.seed,
                                   a.out, scene_name, a.max_scale_pixels)

    lines = []
    lines.append("# Detector sensitivity calibration\n")
    lines.append("- Scene: `%s` (scales %s, z=%.1f, min-size %d, seed %d)" % (
        a.image, a.scales, a.z, a.min_size, a.seed))
    lines.append("- Blobs injected as Gaussian bright+dark pairs per size.\n")
    lines.append("| blob size (px) | recall |")
    lines.append("|---|---|")
    for size in sizes:
        hit_n, n = recall[size]
        pct = 100.0 * hit_n / max(1, n)
        lines.append("| %d | %d/%d (%.0f%%) |" % (size, hit_n, n, pct))
    lines.append("")
    lines.append("- Detector fired %d boxes on the injected scene." % n_det)
    lines.append("- Negative control: %d false positives on the same clean scene.\n" % neg)
    lines.append("## Reading this")
    lines.append("The blob size at which recall crosses ~50%% is the honest "
                 "minimum object size this configuration can see on such a "
                 "scene. Objects far below that size are invisible; near it, "
                 "candidates are detected at reduced reliability. The negative "
                 "control FP count is the baseline any candidate must beat.")
    lines.append("")

    common.atomic_text_write(os.path.join(a.out, "benchmark_%s.md" % scene_name), "\n".join(lines))
    rows = [{"scene": scene_name, "blob_size_px": size, "recall_hit": hit_n,
             "recall_total": n, "recall_pct": round(100.0 * hit_n / max(1, n), 1)}
            for size in sizes for hit_n, n in [recall[size]]]
    rows.append({"scene": scene_name + "_negative_control_fp", "blob_size_px": neg,
                 "recall_hit": "", "recall_total": "", "recall_pct": ""})
    common.atomic_csv_write(os.path.join(a.out, "benchmark_%s.csv" % scene_name), rows,
                            ["scene", "blob_size_px", "recall_hit", "recall_total", "recall_pct"])

    print("scene:", scene_name, "| injected boxes fired:", n_det, "| clean FPs:", neg)
    for size in sizes:
        hit_n, n = recall[size]
        print("  %4d px  %d/%d" % (size, hit_n, n))
    print("->", os.path.join(a.out, "benchmark_%s.md" % scene_name))
    common.audit({
        "event": "benchmark",
        "cmd": " ".join(sys.argv),
        "scene": scene_name, "scales": a.scales, "z": a.z, "min_size": a.min_size,
        "seed": a.seed, "sizes": sizes, "n_detections": n_det,
        "negative_control_fp": neg, "recall": {str(k): list(v) for k, v in recall.items()},
        "out": os.path.abspath(a.out),
        "seconds": round(common.time.time() - start, 1),
    })


if __name__ == "__main__":
    main()
