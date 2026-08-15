"""Photometric and shadow physics.

Two purposes:
  1. Photometric normalization (Lambert / Lommel-Seeliger) so that features
     can be compared between passes taken at different sun angles, which is
     the precondition for honest multi-pass change detection.
  2. Sun-aware sanity checks: an elevated object casts a shadow whose
     direction is fixed by the solar azimuth, and whose length bounds the
     object's physical height. A candidate whose elongation or shadow does
     not point along the solar direction needs an explanation.

All functions are pure numpy/PIL and offline.
"""

import math

import numpy as np

import metadata

DEG = math.pi / 180.0


def _cos(deg):
    return math.cos(max(0.0, min(89.9, float(deg))) * DEG)


def lambert_normalize(img, incidence_deg, emission_deg=0.0):
    """Reflectance estimate assuming a Lambertian surface: I / cos(i) / cos(e)."""
    arr = np.asarray(img, dtype=np.float32)
    c = _cos(incidence_deg) * _cos(emission_deg)
    if c < 1e-3:
        return arr
    return arr / c


def lommelseeliger_normalize(img, incidence_deg, emission_deg, phase_deg=None):
    """Lommel-Seeliger (surface-scattering) normalized reflectance.

    I0 = I * (cos i + cos e) / cos i, bounded to avoid division blowups near
    grazing incidence. Closer to planetary photometry than Lambert for
    regolith at high incidence.
    """
    arr = np.asarray(img, dtype=np.float32)
    ci = _cos(incidence_deg)
    ce = _cos(emission_deg)
    denom = ci + ce
    if denom < 1e-3:
        return arr
    factor = (ci + ce) / ci
    return arr * factor


def sun_ground_vector(solar_elevation_deg, azimuth_deg):
    """Unit vector from the target toward the Sun, in ground-plane image coords.

    Returns (nx, ny, nz) with +x = east, +y = north (up in a north-up image),
    +z = up. Elevation measured above the local horizon.
    """
    el = solar_elevation_deg * DEG
    az = azimuth_deg * DEG
    return (math.cos(el) * math.sin(az),
            math.cos(el) * math.cos(az),
            math.sin(el))


def shadow_direction(solar_azimuth_deg, north_up=True):
    """Unit vector a shadow falls along, in image pixel coords (y down).

    north_up=True means image +y is south (standard map-projected products).
    The vector points away from the Sun. Returns (dx, dy) or None when the
    geometry is unknown.
    """
    if solar_azimuth_deg is None:
        return None
    az = float(solar_azimuth_deg) * DEG
    if north_up:
        return (-math.sin(az), math.cos(az))
    return None


def _mask_for_region(crop, fx, fy, fw, fh):
    mask = np.zeros(crop.shape, dtype=bool)
    mask[fy:fy + fh, fx:fx + fw] = True
    return mask


def elongation_angle(mask):
    """Angle (degrees, image coords, y down) of the principal axis of a mask.

    Uses PCA on the foreground pixel coordinates. Returns None for degenerate
    masks. The returned angle is measured from image +x (east) counterclockwise
    in screen terms.
    """
    ys, xs = np.where(mask)
    if len(xs) < 4:
        return None
    x = xs.astype(np.float64)
    y = ys.astype(np.float64)
    x -= x.mean()
    y -= y.mean()
    cov = np.array([[np.dot(x, x), np.dot(x, y)],
                    [np.dot(x, y), np.dot(y, y)]])
    evals, evecs = np.linalg.eigh(cov)
    v = evecs[:, int(np.argmax(evals))]
    ang = math.degrees(math.atan2(v[1], v[0]))
    return ang % 180.0


def _angdist(a, b):
    d = abs((a - b) % 180.0)
    return min(d, 180.0 - d)


def shadow_alignment(crop, solar_azimuth_deg, solar_elevation_deg=None,
                     north_up=True, polarity="bright"):
    """How well the candidate's elongation matches the expected shadow axis.

    Returns a dict:
      score      0..1 (1 = perfectly aligned with the sun-shadow axis)
      angle_deg  principal-axis angle of the feature in image coords
      shadow_deg expected shadow azimuth in image coords
      skipped    True when the geometry makes the check meaningless
                 (no azimuth, grazing sun, or a dark feature where the
                 'shadow' concept does not constrain orientation)
    """
    if solar_azimuth_deg is None or not north_up:
        return {"score": None, "skipped": True, "reason": "no solar azimuth / non-north-up"}
    if polarity != "bright":
        return {"score": None, "skipped": True, "reason": "dark feature: shadow check n/a"}
    if solar_elevation_deg is not None and solar_elevation_deg >= 80:
        return {"score": None, "skipped": True, "reason": "sun near zenith, shadows negligible"}

    arr = np.asarray(crop, dtype=np.float32)
    flat = arr - np.median(arr)
    s = float(np.std(arr)) + 1e-6
    bright = flat > 1.5 * s
    if bright.sum() < 9:
        return {"score": None, "skipped": True, "reason": "no dominant bright core"}
    feats = elongation_angle(bright)
    if feats is None:
        return {"score": None, "skipped": True, "reason": "degenerate shape"}
    d = shadow_direction(solar_azimuth_deg, north_up=north_up)
    shadow_deg = (math.degrees(math.atan2(d[1], d[0])) % 180.0)
    score = max(0.0, 1.0 - _angdist(feats, shadow_deg) / 45.0)
    return {
        "score": round(float(score), 3),
        "angle_deg": round(float(feats), 2),
        "shadow_deg": round(float(shadow_deg), 2),
        "skipped": False,
    }


def measure_shadow(crop, fx, fy, fw, fh, solar_azimuth_deg, north_up=True):
    """Shadow length in pixels cast by a bright feature, along the solar axis.

    Scans from the bright core outward in the shadow direction and measures the
    furthest contiguous dark run. Returns (shadow_px, confidence) where
    confidence is the fraction of the ray that was dark (long cohesive shadows
    score higher). Returns (None, 0.0) when no shadow is resolvable.
    """
    if solar_azimuth_deg is None or not north_up:
        return None, 0.0
    arr = np.asarray(crop, dtype=np.float32)
    h, w = arr.shape
    if fx + fw > w or fy + fh > h:
        return None, 0.0
    region = arr[fy:fy + fh, fx:fx + fw]
    bg = np.median(arr)
    s = float(np.std(arr)) + 1e-6
    bright = (region - np.median(region)) > 1.5 * s
    if bright.sum() < 9:
        return None, 0.0
    ys, xs = np.where(bright)
    cy, cx = float(ys.mean()), float(xs.mean())
    d = shadow_direction(solar_azimuth_deg, north_up=north_up)
    dx, dy = d
    cx = fx + cx
    cy = fy + cy
    # march along the ray up to the crop edge
    max_steps = int(max(h, w) * 1.5)
    dark = 0
    contiguous = 0
    best = 0
    for k in range(1, max_steps):
        x = int(round(cx + dx * k))
        y = int(round(cy + dy * k))
        if not (0 <= x < w and 0 <= y < h):
            break
        if arr[y, x] < bg - 0.75 * s:
            contiguous += 1
            dark += 1
        else:
            if contiguous > best:
                best = contiguous
            contiguous = 0
    if contiguous > best:
        best = contiguous
    if best < 3:
        return None, 0.0
    conf = dark / float(max(1, dark + contiguous))
    return best, round(float(conf), 2)
