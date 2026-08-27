"""Check whether a detected candidate is actually 3D using a stereo pair.

Uses pipeline/stereo.py block-matching disparity: a real topographic bump
(rock, rim, structure) has a disparity offset against the flat ground around
it; a 2D albedo/shadow patch does not.

Example:
  python scripts/check_stereo.py --left a_L.png --right a_R.png \
      --candidates data/anomalies/candidates.csv --box 0 \
      --altitude-km 300 --baseline-km 1.2 --out data/anomalies/stereo

The baseline comes from the product label (spacecraft positions at the two
stereo frames) or from the HiRISE stereo-pair metadata; 1.2 km is a typical
MRO orbit shift between stereo frames.
"""

import argparse
import csv
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline")
)

import common
import stereo


def main():
    p = argparse.ArgumentParser(description="3D-confirm a candidate with stereo disparity")
    p.add_argument("--left", required=True, help="left (or lower-phase) frame")
    p.add_argument("--right", required=True, help="right (or higher-phase) frame")
    p.add_argument("--candidates", required=True, help="candidates.csv from detect.py")
    p.add_argument("--box", type=int, default=0, help="index into candidates sorted by score")
    p.add_argument("--altitude-km", type=float, default=300.0, help="spacecraft altitude")
    p.add_argument("--baseline-km", type=float, default=1.2, help="stereo baseline")
    p.add_argument("--focal-px", type=float, default=700.0, help="focal length in pixels")
    p.add_argument("--max-crop", type=int, default=512)
    p.add_argument("--out", default="data/anomalies/stereo")
    a = p.parse_args()

    with open(a.candidates, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: float(r["score"]), reverse=True)
    if a.box >= len(rows):
        print("--box %d out of range (%d candidates)" % (a.box, len(rows)))
        return 1
    row = rows[a.box]
    x, y, w, h = (int(row[k]) for k in ("x", "y", "w", "h"))

    left = common.load_gray(a.left)
    right = common.load_gray(a.right)
    if left.shape != right.shape:
        print("resizing right %s -> %s" % (right.shape, left.shape))
        right = np.asarray(
            Image.fromarray(right).resize((left.shape[1], left.shape[0])), dtype=np.float32
        )

    H, W = left.shape
    margin = int(0.5 * max(w, h)) + 16
    x0, y0 = max(0, x - margin), max(0, y - margin)
    x1, y1 = min(W, x + w + margin), min(H, y + h + margin)
    if x1 - x0 < w or y1 - y0 < h or x1 <= x0 or y1 <= y0:
        print(
            "candidate box (%d,%d %dx%d) does not fit the pair images (%dx%d); "
            "candidates must come from the same framing as the stereo pair." % (x, y, w, h, W, H)
        )
        return 1
    crop_l = left[y0:y1, x0:x1]
    crop_r = right[y0:y1, x0:x1]
    fx, fy = x - x0, y - y0

    relief, mean_in, mean_out = stereo.disparity_relief(crop_l, crop_r, fx, fy, w, h)
    bdx, bdy, ssd = stereo.disparity_map(crop_l, crop_r, block=9, search=32)

    disp = np.abs(bdx)
    disp_img = np.nan_to_num(disp)
    lo, hi = np.percentile(disp_img, (1, 99))
    span = max(1.0, float(hi - lo))
    disp8 = np.clip((disp_img - lo) * (255.0 / span), 0, 255).astype(np.uint8)
    anag = stereo.anaglyph(crop_l, crop_r)

    os.makedirs(a.out, exist_ok=True)
    Image.fromarray(disp8).save(os.path.join(a.out, "disparity.png"))
    Image.fromarray(anag).save(os.path.join(a.out, "anaglyph.png"))

    altitude = a.altitude_km * 1000.0
    baseline = a.baseline_km * 1000.0
    dh = stereo.height_from_disparity(relief, altitude, baseline, a.focal_px)

    print("candidate: image=%s box=%s,%s %sx%s" % (row["image"], x, y, w, h))
    print(
        "disparity: mean in-box=%.2f px, out-of-box=%.2f px, relief=%.2f px"
        % ((mean_in or 0.0), (mean_out or 0.0), (relief or 0.0))
    )
    print("implied height difference: %s m" % ("n/a" if dh is None else "%.1f" % dh))
    if relief is not None:
        if abs(relief) >= 0.6:
            print(
                "VERDICT: consistent with a real 3D topographic feature (relief %.2f px)." % relief
            )
        elif abs(relief) < 0.3:
            print(
                "VERDICT: ~flat disparity — consistent with a 2D albedo/shadow/artifact, NOT elevated."
            )
        else:
            print(
                "VERDICT: weak relief (%.2f px) — inconclusive, re-check with the full-res pair."
                % relief
            )
    print("outputs ->", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
