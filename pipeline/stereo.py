"""Stereo disparity and 3D confirmation.

A feature that is a real topographic bump (rock, rim, structure) produces a
measurable disparity between the left and right images of a stereo pair,
proportional to its height. A feature that is only albedo / shadow on flat
ground produces ~zero relative disparity. This module gives the pipeline the
"is it actually 3D" check that the methodology wants before any finding.

Disparity is computed by exhaustive block matching (SSD over a shift window),
vectorized with running sums so it stays usable on candidate-sized crops.
"""

import numpy as np


def _box_sum(arr, k):
    """Sum over k x k windows at every pixel (cumsum trick)."""
    k = int(k)
    pad = k // 2
    h, w = arr.shape
    if k <= 1:
        return arr
    padded = np.pad(arr.astype(np.float64), ((pad, pad), (pad, pad)), mode="edge")
    cs = np.zeros((h + 2 * pad + 1, w + 2 * pad + 1), dtype=np.float64)
    cs[1:, 1:] = np.cumsum(np.cumsum(padded, axis=0), axis=1)
    a = cs[k:k + h, k:k + w]
    b = cs[:h, k:k + w]
    c = cs[k:k + h, :w]
    d = cs[:h, :w]
    return (a - b - c + d) / float(k * k)


def disparity_map(left, right, block=9, search=16):
    """Block-match `right` into `left`.

    Returns (bdx, bdy, ssd) where bdx/bdy are int arrays giving, for each pixel
    of `left`, the displacement into `right` with the lowest SSD, and ssd is
    the matching cost. Arrays are float32 for bdx/bdy.
    """
    l = np.asarray(left, dtype=np.float32)
    r = np.asarray(right, dtype=np.float32)
    h, w = l.shape
    if h * w > 1_500_000:
        raise ValueError("disparity_map too large (%dx%d); downscale first" % (h, w))
    if l.shape != r.shape:
        raise ValueError("stereo frames must be same size: %s vs %s" % (l.shape, r.shape))

    s = int(search)
    best = np.full((h, w), np.inf, dtype=np.float64)
    bdx = np.zeros((h, w), dtype=np.float32)
    bdy = np.zeros((h, w), dtype=np.float32)
    valid = np.zeros((h, w), dtype=bool)

    for dy in range(-s, s + 1):
        for dx in range(-s, s + 1):
            shifted = np.zeros_like(l)
            r0 = max(0, dy)
            r1 = min(h, h + dy)
            c0 = max(0, dx)
            c1 = min(w, w + dx)
            shifted[r0:r1, c0:c1] = r[r0 - dy:r1 - dy, c0 - dx:c1 - dx]
            d2 = (l - shifted) ** 2
            ssd = _box_sum(d2, block)
            m = ssd < best
            bdx[m] = dx
            bdy[m] = dy
            best[m] = ssd[m]
            valid[m] = True

    best[~valid] = np.nan
    bdx[~valid] = np.nan
    bdy[~valid] = np.nan
    return bdx, bdy, best


def disparity_relief(left, right, x, y, w, h, block=9, search=16):
    """Is the boxed region a real 3D feature, or flat albedo?

    Compares the absolute disparity inside the box against the local ring
    around it. A bump stands out against its surroundings; a 2D albedo patch
    does not. Returns (relief, mean_in, mean_out) with relief = mean_in -
    mean_out (positive = elevated/relieved). One of the two crops must be
    trimmed to equal sizes before calling.
    """
    bdx, _, _ = disparity_map(left, right, block=block, search=search)
    absd = np.abs(bdx)
    m = np.isfinite(absd)
    if not m.any():
        return None, None, None
    H, W = absd.shape
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return None, None, None
    in_mask = np.zeros((H, W), dtype=bool)
    in_mask[y0:y1, x0:x1] = True
    ring = ~in_mask
    vals_in = absd[in_mask & m]
    vals_out = absd[ring & m]
    if len(vals_in) < 8 or len(vals_out) < 8:
        return None, None, None
    mean_in = float(vals_in.mean())
    mean_out = float(vals_out.mean())
    return round(mean_in - mean_out, 2), round(mean_in, 2), round(mean_out, 2)


def height_from_disparity(disp_px, altitude_m, baseline_m, focal_px):
    """Height difference in meters implied by a disparity in pixels.

    For a pair acquired from an orbit, depth ~= altitude. Two features at
    heights h1, h2 differ in disparity by ~ baseline*focal*(1/z1 - 1/z2), so
    with z ~ altitude the height difference is approximately
        dh ~ disp_px * altitude_m^2 / (baseline_m * focal_px)
    Order-of-magnitude only; never a precise measurement without the full
    camera model.
    """
    if None in (disp_px, altitude_m, baseline_m, focal_px):
        return None
    if baseline_m <= 0 or focal_px <= 0 or altitude_m <= 0:
        return None
    return disp_px * altitude_m * altitude_m / (baseline_m * focal_px)


def anaglyph(left, right, shift=None):
    """Red-cyan anaglyph from a stereo pair (left = red, right = cyan)."""
    l = np.asarray(left, dtype=np.float32)
    r = np.asarray(right, dtype=np.float32)
    if l.shape != r.shape:
        raise ValueError("anaglyph needs equal-size frames")
    lo = min(l.min(), r.min())
    hi = max(l.max(), r.max())
    span = max(1.0, float(hi - lo))
    scale = 255.0 / span
    l8 = np.clip((l - lo) * scale, 0, 255).astype(np.uint8)
    r8 = np.clip((r - lo) * scale, 0, 255).astype(np.uint8)
    out = np.zeros(l.shape + (3,), dtype=np.uint8)
    out[..., 0] = l8
    out[..., 1] = r8
    out[..., 2] = r8
    return out


def make_anaglyph(left, right):
    return anaglyph(left, right)
