"""Text / annotation overlay detector.

Processed press images, captioned JPEGs and map products frequently carry
baked-in overlays: scale bars ("500 meters"), image IDs, north arrows and
feature labels. The anomaly detector happily flags those high-contrast
glyphs as "anomalies". This module finds such overlays BEFORE detection so
the pipeline can skip the image or mask the overlay regions.

Classical CV, fully offline (numpy + Pillow, scipy optional):

  1. contrast-normalize, high-pass filter to isolate ink strokes,
  2. morphological horizontal close so glyph strokes merge into words,
  3. connected-component analysis and line grouping,
  4. score each line on the forensic signatures of typeset text:
     uniform glyph height, aligned baselines, regular letter spacing,
  5. a solid elongated bar (scale bar) adjacent to a text line adds weight.

text_overlay_score() returns a dict; `flagged` is True when the overlay
confidence reaches OVERLAY_THRESHOLD, meaning the whole image should be
treated as an annotated product rather than a science frame.
"""

import numpy as np
from PIL import Image

import detect  # noqa: E402

OVERLAY_THRESHOLD = 0.5


def _normalize(arr):
    """Stretch to 0-255 by percentile so 8/16-bit/PDS data behave the same."""
    a = np.asarray(arr, dtype=np.float32)
    lo, hi = np.percentile(a, (1.0, 99.0))
    if hi - lo < 1e-6:
        return np.zeros_like(a)
    return np.clip((a - lo) * (255.0 / (hi - lo)), 0.0, 255.0)


def _h_dilate(mask, rx):
    out = mask.copy()
    for dx in range(1, rx + 1):
        out[:, dx:] |= mask[:, :-dx]
        out[:, :-dx] |= mask[:, dx:]
    return out


def _h_erode(mask, rx):
    out = mask.copy()
    for dx in range(1, rx + 1):
        out[:, dx:] &= mask[:, :-dx]
        out[:, :-dx] &= mask[:, dx:]
    return out


def _ink_masks(a):
    """Signed stroke masks (bright ink, dark ink) from a high-pass filter."""
    smooth = detect.box_blur(a, 7)
    detail = a - smooth
    ad = np.abs(detail)
    thr = max(10.0, float(ad.mean()) + 3.0 * float(ad.std()))
    return detail > thr, detail < -thr


def _components(mask):
    labels, n = detect.mask_components(mask)
    out = []
    for ys, xs in detect.component_pixels(mask, labels):
        y0, y1 = int(ys.min()), int(ys.max())
        x0, x1 = int(xs.min()), int(xs.max())
        cw, ch = x1 - x0 + 1, y1 - y0 + 1
        out.append({
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "w": cw, "h": ch, "area": int(len(xs)),
            "fill": len(xs) / float(cw * ch), "cy": (y0 + y1) / 2.0,
        })
    return out


def _group_lines(comps):
    """Greedy clustering of glyph components into horizontal text lines."""
    comps = sorted(comps, key=lambda c: c["cy"])
    lines = []
    for c in comps:
        placed = False
        for ln in lines:
            ref_h = float(np.median([m["h"] for m in ln]))
            ref_cy = float(np.median([m["cy"] for m in ln]))
            if (abs(c["cy"] - ref_cy) <= max(3.0, 0.7 * ref_h)
                    and max(c["h"], ref_h) / max(1.0, min(c["h"], ref_h)) <= 2.5):
                ln.append(c)
                placed = True
                break
        if not placed:
            lines.append([c])
    return lines


def _line_score(ln):
    """0-1 text-likeness of one line of glyph components.

    Beyond geometry (uniform glyph height, aligned baselines, loose gap
    regularity) two forensic discriminators separate typeset text from
    terrain alignments:
      - polarity purity: real ink is single-polarity; crater rims mix
        bright highlights with dark shadows,
      - fill uniformity: glyphs have similar stroke density; rocks do not.
    """
    n = len(ln)
    if n < 2:
        return 0.0
    hs = np.array([c["h"] for c in ln], dtype=np.float64)
    cys = np.array([c["cy"] for c in ln], dtype=np.float64)
    fills = np.array([c["fill"] for c in ln], dtype=np.float64)
    mean_h = float(hs.mean())
    h_cv = float(hs.std()) / max(mean_h, 1.0)
    base_dev = float(cys.std()) / max(mean_h, 1.0)
    fill_cv = float(fills.std()) / max(float(fills.mean()), 1e-6)
    pols = [c["pol"] for c in ln]
    purity = max(pols.count(1), pols.count(-1)) / float(n)
    ln = sorted(ln, key=lambda c: c["x0"])
    score = (np.exp(-2.2 * h_cv) * np.exp(-2.5 * base_dev)
             * float(purity) * float(purity))
    if n >= 3:
        # Word gaps in typeset labels are only loosely regular (underscores,
        # periods and spaces break the rhythm), so this stays a weak signal.
        gaps = np.diff([c["x0"] for c in ln]).astype(np.float64)
        gap_cv = float(gaps.std()) / max(float(gaps.mean()), 1.0)
        score *= float(np.exp(-0.6 * max(0.0, gap_cv - 0.5)))
    score *= float(np.exp(-1.5 * max(0.0, fill_cv - 0.35)))
    score *= min(1.0, (n - 1) / 4.0)
    return float(min(1.0, score))


def _scale_bar_boost(bars, ln, img_h):
    """+confidence when a solid bar sits next to a text line (scale bars)."""
    boost = 0.0
    for b in bars:
        if abs(b["cy"] - float(np.median([m["cy"] for m in ln]))) <= 4.0 * b["h"] + img_h * 0.02:
            boost = max(boost, 0.15)
    return boost


def text_overlay_score(arr, max_side=1600):
    """Detect baked-in text/annotation overlays in a grayscale array.

    Returns dict with:
      score    0-1 overlay confidence (max text-line score)
      flagged  True when score >= OVERLAY_THRESHOLD
      boxes    [(x, y, w, h), ...] overlay regions in `arr` coordinates
      coverage fraction of the image covered by overlay boxes
      lines    number of accepted text lines
    """
    a = _normalize(arr)
    H, W = a.shape
    s = min(1.0, max_side / float(max(H, W)))
    if s < 1.0:
        im = Image.fromarray(a.astype(np.uint8)).resize(
            (max(8, int(W * s)), max(8, int(H * s))), Image.BILINEAR)
        a = np.asarray(im, dtype=np.float32)
    h, w = a.shape
    ink_pos, ink_neg = _ink_masks(a)
    glyphs = []
    for mask, pol in ((ink_pos, 1), (ink_neg, -1)):
        for c in _components(mask):
            c["pol"] = pol
            if (0.004 * h <= c["h"] <= 0.12 * h
                    and c["w"] <= 0.5 * w
                    and 0.10 <= c["fill"] <= 0.95
                    and c["area"] >= 6):
                glyphs.append(c)

    bars = [c for c in _components(ink_pos | ink_neg)
            if c["fill"] >= 0.85 and 1.5 <= c["w"] / max(1.0, c["h"]) <= 30.0
            and c["h"] <= 0.06 * h and c["w"] >= 0.02 * w]

    best = 0.0
    boxes = []
    accepted = 0
    band = 0.06  # annotation prior: text in the outer 6% band is the classic
    for ln in _group_lines(glyphs):  # label / scale-bar position
        base = _line_score(ln)
        sc = base + _scale_bar_boost(bars, ln, h)
        x0 = min(c["x0"] for c in ln)
        y0 = min(c["y0"] for c in ln)
        x1 = max(c["x1"] for c in ln)
        y1 = max(c["y1"] for c in ln)
        # the position bonus only lifts lines that are already strong text
        # candidates, never marginal terrain alignments
        if base >= 0.45 and (y1 <= band * h or y0 >= (1.0 - band) * h
                             or x1 <= band * w or x0 >= (1.0 - band) * w):
            sc += 0.15
        sc = min(1.0, sc)
        if sc >= 0.45:
            accepted += 1
            best = max(best, sc)
            boxes.append((x0, y0, x1 - x0 + 1, y1 - y0 + 1))

    flagged = best >= OVERLAY_THRESHOLD
    out_boxes = []
    for (x, y, bw, bh) in boxes:
        out_boxes.append((int(x / s), int(y / s),
                          int(bw / s), int(bh / s)))
    cov = sum(bw * bh for (_, _, bw, bh) in out_boxes) / float(max(1, W * H))
    return {"score": round(best, 3), "flagged": bool(flagged),
            "boxes": out_boxes, "coverage": round(cov, 4), "lines": accepted}


def box_overlaps_any(box, boxes, frac=0.3):
    """True when `box` overlaps any of `boxes` by > `frac` of its own area."""
    x, y, w, h = box
    for (bx, by, bw, bh) in boxes:
        ix0, iy0 = max(x, bx), max(y, by)
        ix1, iy1 = min(x + w, bx + bw), min(y + h, by + bh)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        if (ix1 - ix0) * (iy1 - iy0) > frac * float(w * h):
            return True
    return False
