"""Multi-pass, co-registered change detection.

The classic "something appeared / disappeared between two passes" question
done honestly: images of the same site from different orbits or dates are
never pixel-aligned, so the second image is registered to the first with a
phase-correlation shift, then only the residual difference above the local
noise floor is reported as a change candidate.

Co-registration assumes near-parallel, roughly co-oriented views (e.g. the
same HiRISE/CTX footprint imaged again at a different time). Large rotation or
perspective differences need map-projected products; that case is noted but
not handled here.
"""

import numpy as np
from detect import box_blur, component_pixels, mask_components


def phase_correlate(a, b):
    """Estimate the integer shift aligning b onto a.

    Returns (dy, dx, score): the shift to apply to b so it lines up with a,
    and the peak correlation score in [0, 1].
    """
    fa = np.fft.fft2(a)
    fb = np.fft.fft2(b)
    cross = fa * np.conj(fb)
    cross = cross / (np.abs(cross) + 1e-12)
    corr = np.fft.ifft2(cross).real
    peak = np.unravel_index(int(np.argmax(corr)), corr.shape)
    h, w = corr.shape
    dy = peak[0] if peak[0] <= h // 2 else peak[0] - h
    dx = peak[1] if peak[1] <= w // 2 else peak[1] - w
    scores = np.sort(corr.ravel())[-3:]
    score = float(corr[peak] - scores[0]) / (float(corr[peak]) + 1e-12)
    score = max(0.0, min(1.0, score))
    return dy, dx, score


def shift_image(img, dy, dx):
    """Translate an array by integer (dy, dx); out-of-range fills with zero.

    Vectorized slice copy: dst[r0:r1, c0:c1] = src[r0-dy:r1-dy, c0-dx:c1-dx]
    over the overlap region only.
    """
    arr = np.asarray(img)
    out = np.zeros_like(arr)
    h, w = arr.shape
    r0, r1 = max(0, dy), min(h, h + dy)
    c0, c1 = max(0, dx), min(w, w + dx)
    if r1 > r0 and c1 > c0:
        out[r0:r1, c0:c1] = arr[r0 - dy:r1 - dy, c0 - dx:c1 - dx]
    return out


def register(base, other, subsample=1):
    """Register `other` onto `base`; returns (aligned, dy, dx, score)."""
    a = np.asarray(base, dtype=np.float32)
    b = np.asarray(other, dtype=np.float32)
    if a.shape != b.shape:
        raise ValueError("register requires same-size frames: %s vs %s" % (a.shape, b.shape))
    if subsample > 1:
        a_s = a[::subsample, ::subsample]
        b_s = b[::subsample, ::subsample]
        dy, dx, score = phase_correlate(a_s, b_s)
        dy *= subsample
        dx *= subsample
    else:
        dy, dx, score = phase_correlate(a, b)
    return shift_image(b, dy, dx), dy, dx, score


def change_map(base, other, smooth=9):
    """Absolute normalized residual between two co-registered frames."""
    a = np.asarray(base, dtype=np.float32)
    b = np.asarray(other, dtype=np.float32)
    d = np.abs(a - b)
    d = box_blur(d, smooth)
    bg = np.median(d)
    sd = float(np.std(d)) + 1e-6
    return (d - bg) / sd, d


def changes(base, other, smooth=9, z=3.0, min_size=12):
    """Change candidates between two co-registered frames.

    Returns a list of dicts (x, y, w, h, score) in the shared coordinate
    space, built from the same connected-component machinery detect.py uses.
    """
    field, _ = change_map(base, other, smooth)
    mask = field > z
    labels, n = mask_components(mask)
    out = []
    for ys, xs in component_pixels(mask, labels):
        if len(xs) < min_size:
            continue
        y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
        out.append({
            "x": x0, "y": y0, "w": x1 - x0 + 1, "h": y1 - y0 + 1,
            "score": round(float(field[ys, xs].mean()), 2),
        })
    out.sort(key=lambda c: c["score"], reverse=True)
    return out


def register_and_changes(base_arr, other_arr, smooth=9, z=3.0, min_size=12):
    """One-shot: register other onto base, then report change candidates."""
    aligned, dy, dx, score = register(base_arr, other_arr)
    cand = changes(base_arr, aligned, smooth=smooth, z=z, min_size=min_size)
    return cand, (dy, dx, score)
