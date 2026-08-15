import argparse
import glob
import os

import numpy as np
from PIL import Image

import common


def sigma_clip_stack(frames, clip=3.0):
    """Median stack after rejecting per-pixel outliers beyond clip*MAD.

    Median-of-frames already removes transients (planes crossing frame to
    frame); the MAD-based pre-clip additionally suppresses cosmic-ray hits and
    hot pixels that survive a plain median across few frames.
    """
    s = np.stack(frames, axis=0)
    med = np.median(s, axis=0)
    mad = np.median(np.abs(s - med), axis=0) + 1e-6
    lo = med - clip * 1.4826 * mad
    hi = med + clip * 1.4826 * mad
    clipped = np.clip(s, lo, hi)
    return np.median(clipped, axis=0)


def destripe(arr, tol=3.0):
    """Column median destriping for CCD pushbroom imagery (HiRISE-style).

    Estimates the per-column median offset vs. the global median and removes
    columns that deviate by more than tol MADs. Detector striping is one of the
    most common causes of false 'anomalies'; removing it before detection is
    the honest move.
    """
    a = np.asarray(arr, dtype=np.float32)
    col_med = np.median(a, axis=0)
    g = np.median(col_med)
    mad = np.median(np.abs(col_med - g)) + 1e-6
    off = col_med - g
    keep = np.abs(off) <= tol * 1.4826 * mad
    out = a.copy()
    out[:, ~keep] -= off[~keep]
    return out


def main():
    p = argparse.ArgumentParser(description="Sigma-clipped median stack + destripe; residual/change maps")
    p.add_argument("--dir", required=True)
    p.add_argument("--pattern", default="*_enh.png")
    p.add_argument("--out", required=True)
    p.add_argument("--clip", type=float, default=3.0,
                   help="MAD sigma threshold for per-pixel outlier rejection")
    p.add_argument("--destripe", action="store_true",
                   help="column-median destripe the stack before saving")
    a = p.parse_args()

    files = sorted(glob.glob(os.path.join(a.dir, a.pattern)))
    if not files:
        print("no files match", a.pattern)
        return
    frames = []
    for f in files:
        try:
            frames.append(common.load_gray(f))
        except Exception as e:
            print("skip {} ({})".format(f, e))
    if len(frames) < 2:
        print("need at least 2 readable frames")
        return
    h, w = frames[0].shape
    frames = [f for f in frames if f.shape == (h, w)]
    if len(frames) < 2:
        print("need at least 2 same-size frames")
        return

    stack = sigma_clip_stack(frames, a.clip)
    if a.destripe:
        stack = destripe(stack)
    residual = np.std(np.stack(frames), axis=0)
    os.makedirs(a.out, exist_ok=True)
    lo, hi = np.percentile(stack, (1, 99))
    span = max(1.0, float(hi - lo))
    out8 = np.clip((stack - lo) * (255.0 / span), 0, 255).astype(np.uint8)
    Image.fromarray(out8).save(os.path.join(a.out, "stack.png"))
    norm = np.clip((residual / (residual.max() + 1e-9)) * 255, 0, 255).astype(np.uint8)
    Image.fromarray(norm).save(os.path.join(a.out, "residual_std.png"))
    for i, f in enumerate(frames):
        diff = np.abs(f - stack)
        Image.fromarray(np.clip(diff, 0, 255).astype(np.uint8)).save(
            os.path.join(a.out, "diff_{:03d}.png".format(i)))
    print("stacked {} frames -> {}".format(len(frames), a.out))


if __name__ == "__main__":
    main()
