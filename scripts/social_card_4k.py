"""High-quality 4K (3840x2160) "anomaly dossier" social card generator.

Premium mission-intelligence theme: vertical space gradient, fine grid +
scanlines, gold registration brackets, rounded info panels with soft shadows,
LANCZOS upscaling for imagery (BICUBIC for rotations), crisp 4K raster.

Layout:
  * EVIDENCE BOARD (left): target-lock (boxed anomaly) + a raw source + a
    MARKED source (anomaly flagged in full frame) + enhancement crop strips.
  * DOSSIER (right): verdict/metrics + assessment + "verify this lead".
  * PROVENANCE / FEATURE SIGNATURE / METHODOLOGY & DEBUNK (bottom, 3 cols):
    everything a sceptic, scientist or astronomer needs to investigate.

Same call signature as the legacy _make_social_card().
"""

import os
import sys
import math
import random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "pipeline"), os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import common
except Exception:  # noqa: BLE001
    common = None

from PIL import Image, ImageDraw, ImageFont


# --------------------------------------------------------------------------- #
# fonts / image helpers
# --------------------------------------------------------------------------- #
def _load_font(size, bold=False):
    names = (["DejaVuSans-Bold.ttf", "arialbd.ttf", "LiberationSans-Bold.ttf"]
             if bold else ["DejaVuSans.ttf", "arial.ttf", "LiberationSans-Regular.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except Exception:
            continue
    try:
        return ImageFont.truetype("arial", size)
    except Exception:
        return ImageFont.load_default()


def _open_rgb(path):
    try:
        im = Image.open(path)
        im.load()
        return im.convert("RGB")
    except Exception:
        return None


def _wrap(text, font, max_w):
    if not text:
        return [""]
    words = text.split()
    lines, cur = [], ""
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for word in words:
        trial = (cur + " " + word).strip()
        if tmp.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _fmt(v):
    if v is None or v == "":
        return "—"
    if isinstance(v, float):
        if math.isnan(v):
            return "—"
        return ("%.3f" % v).rstrip("0").rstrip(".")
    return str(v)


def _vgradient(w, h, c1, c2):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=c)
    return img


def _polaroid(im, caption, target_w, border, font,
              bg=(245, 245, 248), cap_fg=(20, 20, 24)):
    w, h = im.size
    tw = max(1, int(round(target_w)))
    th = max(1, int(round(target_w * h / w)))
    pic = im.resize((tw, th), Image.LANCZOS)
    cap_h = border + int(font.size * 1.5)
    panel = Image.new("RGB", (tw + border * 2, th + border * 2 + cap_h), bg)
    panel.paste(pic, (border, border))
    d = ImageDraw.Draw(panel)
    d.text((border, th + border * 2), caption, fill=cap_fg, font=font)
    return panel


def _target_panel(im, box, target_w, caption, font, red, acc):
    """Zoomed 'target lock' view of the anomaly with a boxed reticle + ticks."""
    x, y, w, h = [int(v) for v in box]
    iw, ih = im.size
    pad = max(w, h) * 7 + 1
    cx0 = max(0, int(x - pad)); cy0 = max(0, int(y - pad))
    cx1 = min(iw, int(x + w + pad)); cy1 = min(ih, int(y + h + pad))
    crop = im.crop((cx0, cy0, cx1, cy1))
    scale = target_w / float(crop.width)
    tgt_h = max(1, int(round(crop.height * scale)))
    crop = crop.resize((target_w, tgt_h), Image.LANCZOS)
    bx0 = (x - cx0) * scale; by0 = (y - cy0) * scale
    bx1 = (x + w - cx0) * scale; by1 = (y + h - cy0) * scale
    d = ImageDraw.Draw(crop)
    lw = max(4, int(target_w / 150))
    d.rectangle([bx0, by0, bx1, by1], outline=red, width=lw)
    t = int(target_w / 36) + 8
    for (tx, ty, dx, dy) in [(bx0, by0, 1, 1), (bx1, by0, -1, 1),
                             (bx0, by1, 1, -1), (bx1, by1, -1, -1)]:
        d.line([(tx, ty), (tx + dx * t, ty)], fill=acc, width=lw)
        d.line([(tx, ty), (tx, ty + dy * t)], fill=acc, width=lw)
    mxc = (bx0 + bx1) / 2; myc = (by0 + by1) / 2
    d.line([(mxc - target_w / 18, myc), (mxc + target_w / 18, myc)], fill=red, width=lw - 1)
    d.line([(mxc, myc - target_w / 18), (mxc, myc + target_w / 18)], fill=red, width=lw - 1)
    lbl = "ANOMALY"
    tw = d.textlength(lbl, font=font)
    d.rectangle([bx0, by0 - 28, bx0 + tw + 18, by0 - 4], fill=red + (210,))
    d.text((bx0 + 9, by0 - 24), lbl, fill=(255, 255, 255), font=font)
    panel = _polaroid(crop, caption, target_w, 16, font,
                      bg=(248, 247, 244), cap_fg=(150, 40, 38))
    pd = ImageDraw.Draw(panel)
    pd.rectangle([2, 2, panel.width - 3, panel.height - 3], outline=red, width=5)
    return panel


def _panel(d, box, fill, outline, width, radius=18, shadow=True):
    if shadow:
        d.rounded_rectangle([box[0] + 8, box[1] + 10, box[2] + 8, box[3] + 10],
                            radius=radius, fill=(0, 0, 0, 150))
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _bullets(d, x, y, items, font, color, gap=30, bullet="•  "):
    yy = y
    for it in items:
        d.text((x, yy), bullet + it, fill=color, font=font)
        yy += gap
    return yy


# --------------------------------------------------------------------------- #
# main card
# --------------------------------------------------------------------------- #
def make_card(src_images, crop_images, primary, product, box, out, dry_run,
              width=3840, leads_count=1, meta=None):
    from PIL import Image, ImageDraw

    x, y, w, h = [int(v) for v in box]
    if dry_run:
        return True

    W = width
    H = 2160
    canvas = _vgradient(W, H, (13, 17, 28), (6, 9, 16)).convert("RGBA")
    d = ImageDraw.Draw(canvas)

    fg = (233, 237, 245)
    dim = (140, 149, 168)
    acc = (255, 196, 48)
    red = (226, 60, 58)
    mono = _load_font(30)
    mono_sm = _load_font(24)
    mono_xs = _load_font(20)
    title_f = _load_font(78, True)
    sub_f = _load_font(34)
    stamp_f = _load_font(66, True)
    sect_f = _load_font(30, True)

    serial = "DX-%05d" % (abs(hash((product, box))) % 90000 + 10000)
    prefix = product.split("_")[0]
    extras_url = "https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/RDR/%s/%s/" % (prefix, product)
    view_url = "https://www.uahirise.org/%s" % product.lower()
    rnd = random.Random(abs(hash((product, box)) & 0xffffffff))
    m = meta or {}
    bands = m.get("bands") or []
    lat = m.get("site_lat")
    lon = m.get("site_lon")

    # fine grid + faint scanlines
    for gx in range(0, W, 60):
        d.line([(gx, 0), (gx, H)], fill=(255, 255, 255, 8), width=1)
    for gy in range(0, H, 60):
        d.line([(0, gy), (W, gy)], fill=(255, 255, 255, 8), width=1)
    for yy in range(170, H - 90, 4):
        d.line([(0, yy), (W, yy)], fill=(0, 0, 0, 9), width=1)

    def bracket(ox, oy, sx, sy):
        L, t = 72, 6
        d.line([(ox, oy), (ox + sx * L, oy)], fill=acc, width=t)
        d.line([(ox, oy), (ox, oy + sy * L)], fill=acc, width=t)

    bracket(24, 24, 1, 1)
    bracket(W - 24, 24, -1, 1)
    bracket(24, H - 24, 1, -1)
    bracket(W - 24, H - 24, -1, -1)

    # ---- header ----
    d.rectangle([0, 0, W, 160], fill=(8, 10, 16, 255))
    d.rectangle([0, 0, W, 8], fill=red)
    d.rectangle([0, 8, W, 15], fill=acc)
    d.text((60, 36), "CLASSIFIED  //  ANOMALY DOSSIER", fill=red, font=title_f)
    d.text((64, 126),
           "SUBJECT: %s    ·    REF GRID x=%d y=%d    ·    BOX %dx%d px    ·    SERIAL %s"
           % (product, x, y, w, h, serial), fill=fg, font=sub_f)
    tab = "EYES ONLY"
    tw = d.textlength(tab, font=mono_sm)
    d.rounded_rectangle([W - 60 - tw - 32, 44, W - 60, 88], radius=9, outline=acc, width=3)
    d.text((W - 60 - tw - 16, 53), tab, fill=acc, font=mono_sm)

    # ---- evidence board (left) ----
    board = [60, 186, 2360, 1500]
    _panel(d, board, (11, 15, 24, 230), (255, 255, 255, 40), 2, radius=18)
    d.text((board[0] + 28, board[1] + 22), "E V I D E N C E   B O A R D",
           fill=acc, font=sect_f)

    src_panels = []
    for i, p in enumerate(src_images):
        im = _open_rgb(p)
        if im is None:
            continue
        cap = os.path.splitext(os.path.basename(p))[0]
        if i == 0:
            src_panels.append((_target_panel(im, box, 1020,
                              "TARGET LOCK // " + product, mono_sm, red, acc), 96, 250, 0))
        else:
            is_marked = os.path.basename(p).lower().startswith("marked_")
            cap2 = ("MARKED // " + cap) if is_marked else cap
            src_panels.append((_polaroid(im, cap2, 500, 16, mono_sm),
                               1230 + (len(src_panels) - 1) * 560, 270, rnd.uniform(-2, 2)))

    placements = []
    if src_panels:
        placements.append(src_panels[0])
    for sp in src_panels[1:3]:
        placements.append(sp)

    def place(panel, px, py, ang):
        rot = panel.convert("RGBA").rotate(ang, expand=True, resample=Image.BICUBIC)
        canvas.paste(rot, (int(px), int(py)), rot)

    for panel, px, py, ang in placements:
        place(panel, px, py, ang)

    # crop strips along the bottom of the board
    crop_panels = []
    for i, p in enumerate(crop_images):
        im = _open_rgb(p)
        if im is None:
            continue
        cap = os.path.splitext(os.path.basename(p))[0][:42]
        crop_panels.append(_polaroid(im, cap, 344, 14, mono_xs))
    for i, panel in enumerate(crop_panels[:6]):
        place(panel, 96 + i * 372, 1188, rnd.uniform(-3, 3))

    # stamps (decorative, kept clear of text)
    stamp = Image.new("RGBA", (460, 250), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.rounded_rectangle([12, 12, 448, 238], radius=10, outline=red + (255,), width=8)
    sd.rounded_rectangle([24, 24, 436, 226], radius=8, outline=red + (150,), width=3)
    sd.text((64, 84), "CONFIRMED\nLEAD", fill=red + (255,), font=stamp_f)
    stamp = stamp.rotate(14, expand=True, resample=Image.BICUBIC)
    canvas.paste(stamp, (1980, 250), stamp)

    stamp2 = Image.new("RGBA", (360, 150), (0, 0, 0, 0))
    s2 = ImageDraw.Draw(stamp2)
    s2.rounded_rectangle([10, 10, 350, 140], radius=8, outline=acc + (255,), width=5)
    s2.text((44, 50), "TOP\nSECRET", fill=acc + (255,), font=_load_font(44, True))
    stamp2 = stamp2.rotate(-10, expand=True, resample=Image.BICUBIC)
    canvas.paste(stamp2, (104, 1232), stamp2)

    # ---- dossier (right) ----
    px0, py0, px1, py1 = 2430, 186, W - 60, 1500
    _panel(d, [px0, py0, px1, py1], (10, 14, 22, 235), acc, 3, radius=18)
    d.text((px0 + 28, py0 + 24), "D O S S I E R", fill=acc, font=sect_f)
    d.line([(px0 + 28, py0 + 64), (px1 - 28, py0 + 64)], fill=(255, 255, 255, 30), width=1)

    fields = [
        ("VERDICT", _fmt(primary.get("verdict", ""))),
        ("CONFIDENCE", _fmt(primary.get("confidence", ""))),
        ("SCORE / INTEREST", "%s / %s" % (_fmt(primary.get("score", "")), _fmt(primary.get("interest", "")))),
        ("POLARITY / CLASS", "%s / %s" % (_fmt(primary.get("polarity", "")), _fmt(primary.get("evidence_class", "")))),
        ("PIXEL SCALE (m)", _fmt(m.get("eff_pixel_scale_m") or m.get("pixel_scale_m"))),
        ("SIZE (m)", _fmt(m.get("size_m"))),
        ("SOLAR ELEV (deg)", _fmt(m.get("solar_elevation_deg"))),
        ("SOLAR AZIM (deg)", _fmt(m.get("solar_azimuth_deg"))),
        ("INFERRED H (m)", ("≈ " + _fmt(m.get("inferred_height_m"))) if m.get("inferred_height_m") else "—"),
        ("LEADS MERGED", _fmt(leads_count)),
    ]
    ty = py0 + 84
    for k, v in fields:
        d.text((px0 + 30, ty), k, fill=acc, font=mono_sm)
        d.text((px0 + 320, ty), str(v), fill=fg, font=mono_sm)
        ty += 38

    rec = (primary.get("recommendation", "") or "").replace("\n", " ")
    d.text((px0 + 30, ty + 4), "ASSESSMENT:", fill=acc, font=mono_sm)
    ry = ty + 40
    for ln in _wrap(rec, mono_sm, px1 - px0 - 60)[:6]:
        d.text((px0 + 30, ry), ln, fill=fg, font=mono_sm)
        ry += 30

    # verify-this-lead block
    vy = ry + 18
    d.text((px0 + 30, vy), "VERIFY THIS LEAD", fill=acc, font=sect_f)
    vy += 36
    trek = ("Mars Trek @ %.3f, %.3f" % (lat, lon)) if (lat is not None and lon is not None) else "Mars Trek (geolocate via catalog)"
    verify = [
        "EDR original: hirise-pds.lpl.arizona.edu/EXTRAS",
        trek,
        "Cross-band persistence: %s" % (", ".join(bands) if bands else "n/a"),
        "Seek independent pass, diff. solar angle",
        "FDR q=%s vs negative-control baseline" % _fmt(primary.get("fdr_q", "")),
    ]
    vy = _bullets(d, px0 + 30, vy, verify, mono_xs, dim, gap=28)

    chip_y = vy + 10
    d.rounded_rectangle([px0 + 24, chip_y, px1 - 24, chip_y + 74], radius=10, outline=acc, width=3)
    d.text((px0 + 40, chip_y + 12), "ORIGINAL SOURCE", fill=acc, font=mono_sm)
    for ln in _wrap(extras_url, mono_sm, px1 - px0 - 90)[:2]:
        d.text((px0 + 40, chip_y + 46), ln, fill=fg, font=mono_sm)

    # ---- bottom: provenance / feature signature / methodology ----
    bx0, by0, bx1, by1 = 60, 1540, W - 60, 2004
    _panel(d, [bx0, by0, bx1, by1], (10, 14, 22, 235), acc, 3, radius=18)
    d.text((bx0 + 36, by0 + 22), "PROVENANCE", fill=acc, font=sect_f)
    d.text((bx0 + 1300, by0 + 22), "FEATURE SIGNATURE", fill=acc, font=sect_f)
    d.text((bx0 + 2520, by0 + 22), "METHODOLOGY & DEBUNK", fill=acc, font=sect_f)

    left = [
        ("PRODUCT", product),
        ("ACQUISITION", m.get("acq_date") or "—"),
        ("ORBIT", _fmt(m.get("orbit"))),
        ("BAND VARIANTS", ", ".join(bands) if bands else "—"),
        ("SITE LAT/LON", ("%.3f, %.3f" % (lat, lon)) if (lat is not None and lon is not None) else "—"),
        ("LOCAL SOL TIME", _fmt(m.get("local_time"))),
        ("BOUNDING BOX", "x=%d y=%d w=%d h=%d" % (x, y, w, h)),
        ("VERDICT", _fmt(primary.get("verdict", ""))),
        ("CONFIDENCE", _fmt(primary.get("confidence", ""))),
        ("SCORE / INTEREST", "%s / %s" % (_fmt(primary.get("score", "")), _fmt(primary.get("interest", "")))),
    ]
    ly = by0 + 66
    for k, v in left:
        d.text((bx0 + 40, ly), k, fill=acc, font=mono_sm)
        d.text((bx0 + 320, ly), str(v), fill=fg, font=mono_sm)
        ly += 32

    right = [
        ("CONTRAST", _fmt(primary.get("contrast", ""))),
        ("AREA (px)", _fmt(primary.get("area_px", ""))),
        ("ASPECT", _fmt(primary.get("aspect", ""))),
        ("PERSISTENCE", _fmt(primary.get("persistence", ""))),
        ("COMPACTNESS", _fmt(primary.get("compactness", ""))),
        ("EDGE SHARPNESS", _fmt(primary.get("edge_sharpness", ""))),
        ("CONTRAST STABILITY", _fmt(primary.get("contrast_stability", ""))),
        ("FDR Q-VALUE", _fmt(primary.get("fdr_q", ""))),
        ("NEAR EDGE", _fmt(primary.get("near_edge", ""))),
        ("MATCHES COORD", _fmt(primary.get("matches_coord", ""))),
        ("AGREE / DISAGREE", "%s / %s" % (_fmt(primary.get("agrees", "")), _fmt(primary.get("disagrees", "")))),
        ("FLAGS", _fmt(primary.get("flags", ""))),
    ]
    ry2 = by0 + 66
    for k, v in right:
        d.text((bx0 + 1300, ry2), k, fill=acc, font=mono_sm)
        d.text((bx0 + 1580, ry2), str(v), fill=fg, font=mono_sm)
        ry2 += 32

    method = [
        "Pipeline: multi-scale local-contrast flag -> cross-band confirm ->",
        "artifact debunk -> solar-geometry score -> 3D stereo height check.",
        "What to check before calling it real:",
        "- Pull the EDR original - never trust processed JPEGs.",
        "- Confirm it persists across RED / MIRB / MRGB variants.",
        "- Rule out hot pixels, CCD bleed, compression, LROC streaks.",
        "- Compare shadow direction to the solar azimuth above.",
        "- Require an independent image at a different lighting.",
    ]
    my = by0 + 66
    for ln in method:
        d.text((bx0 + 2520, my), ln, fill=(200, 206, 220), font=mono_xs)
        my += 28

    rec_y = max(ly, ry2, my) + 8
    d.text((bx0 + 40, rec_y), "RECOMMENDATION:", fill=acc, font=mono_sm)
    for ln in _wrap(rec, mono_sm, bx1 - bx0 - 80)[:2]:
        rec_y += 28
        d.text((bx0 + 40, rec_y), ln, fill=dim, font=mono_sm)

    # ---- footer ----
    fy = 2064
    d.rectangle([0, fy, W, H], fill=(8, 10, 16, 255))
    d.rectangle([0, fy, W, fy + 5], fill=red)
    d.text((60, fy + 22), "SOURCE  " + extras_url, fill=acc, font=mono_sm)
    d.text((60, fy + 56), "VIEW    " + view_url, fill=dim, font=mono_sm)
    d.text((W - 460, fy + 40), "CASE %s" % product, fill=acc, font=mono_sm)
    bx = W - 420
    while bx < W - 60:
        bw = rnd.randint(3, 9)
        bh = rnd.randint(34, 60)
        d.rectangle([bx, H - 74, bx + bw, H - 74 + bh], fill=dim, width=0)
        bx += bw + rnd.randint(3, 8)

    final = canvas.convert("RGB")
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        final.save(out, quality=95)
        return True
    except Exception as e:  # noqa: BLE001
        if common is not None:
            common.log("warn", "social card failed: %s" % e)
        return False


if __name__ == "__main__":
    import tempfile
    out = os.path.join(tempfile.gettempdir(), "social_card_test.png")
    row = {"verdict": "CONFIRMED-LEAD", "confidence": "high", "score": "100.0",
           "interest": "60.9", "polarity": "dark", "evidence_class": "3",
           "contrast": "3.77", "area_px": "336", "aspect": "2.33",
           "persistence": "1.0", "compactness": "1.0", "edge_sharpness": "1.26",
           "contrast_stability": "0.97", "fdr_q": "0.025", "near_edge": "False",
           "matches_coord": "2", "agrees": "2", "disagrees": "0", "flags": "small_blob",
           "recommendation": "Real feature confirmed at the same pixels in the corresponding band variant(s) of one acquisition."}
    meta = {"bands": ["MIRB", "RED"], "site_lat": -8.5, "site_lon": 140.2,
            "acq_date": "2023-04-12", "orbit": 81234, "local_time": "14:32",
            "eff_pixel_scale_m": 0.5, "size_m": 14.0, "solar_elevation_deg": 45.0,
            "solar_azimuth_deg": 130.0, "inferred_height_m": 14.0}
    ok = make_card([], [], row, "ESP_013236_1410", (752, 5296, 12, 28), out, False, meta=meta)
    print("self-test ok:", ok, "->", out)
