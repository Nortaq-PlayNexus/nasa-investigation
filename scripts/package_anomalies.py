"""Package every unique CONFIRMED-LEAD anomaly into its own self-contained folder.

Leads that are the SAME physical feature (same product + same bounding box,
just seen in different band variants such as MIRB/MRGB/RED) are merged into a
single deduplicated package. One folder per unique anomaly.

Each package lives under data/anomalies/packages/<id>/ with:

    imagery/    every distinct source image the detection appears in (+ overlays)
    evidence/   cropped bbox image(s), matching analysis crops, reports
    data/       all sibling lead records (CSV+JSON), full provenance CSVs
    sources/    sources.yaml, the raw-download manifest slice, catalog, README

A top-level MANIFEST.jsonl and index.csv summarize every package so the run is
auditable (same spirit as pipeline/common.audit).

Try it:

    python scripts/package_anomalies.py
    python scripts/package_anomalies.py --dry-run
    python scripts/package_anomalies.py --out-dir data/anomalies/packages
"""

import argparse
import csv
import json
import math
import os
import re
import shutil
import sys

# Make pipeline/ and scripts/ importable (flat layout, no __init__.py).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "pipeline"), os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import common  # noqa: E402
from _common import safe_name  # noqa: E402

# 4K high-quality social card (scripts/social_card_4k.py); fall back to the
# legacy in-module renderer if the module is unavailable.
try:
    from social_card_4k import make_card as _make_social_card_4k  # noqa: E402
except Exception:  # noqa: BLE001
    _make_social_card_4k = None

CROP_RE = re.compile(r"_x(\d+)_y(\d+)_(\d+)x(\d+)\.jpg$", re.IGNORECASE)

LEADS_CSV = os.path.join(ROOT, "data", "anomalies", "conclusions", "leads.csv")
CROPS_DIR = os.path.join(ROOT, "data", "anomalies", "analysis", "crops")
MARKED_DIR = os.path.join(ROOT, "data", "anomalies", "marked")
CONCLUSIONS_DIR = os.path.join(ROOT, "data", "anomalies", "conclusions")
ANALYSIS_DIR = os.path.join(ROOT, "data", "anomalies", "analysis")
RAW_MANIFEST = os.path.join(ROOT, "data", "raw", "manifest.jsonl")
SOURCES_YAML = os.path.join(ROOT, "config", "sources.yaml")
CATALOG_CSV = os.path.join(ROOT, "data", "catalog", "catalog.csv")
CATALOG_JSON = os.path.join(ROOT, "data", "catalog", "catalog.json")
DEFAULT_OUT = os.path.join(ROOT, "data", "anomalies", "packages")


def _sanitize(s):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s).strip("._") or "item"


def _resolve_src(path):
    """Resolve a leads.csv `path` (mixed slashes) to an existing file."""
    if not path:
        return None
    full = os.path.normpath(os.path.join(ROOT, path.replace("\\", "/")))
    if os.path.exists(full):
        return full
    alt = os.path.normpath(os.path.join(ROOT, path.replace("/", "\\")))
    if os.path.exists(alt):
        return alt
    return None


def _product_of(path):
    parts = os.path.normpath(path).split(os.sep)
    # data / processed / <product> / file.png
    if len(parts) >= 3 and parts[0] in ("data",) and parts[1] in ("processed",):
        return parts[2]
    base = os.path.basename(path)
    return base.split("_")[0] + "_" + base.split("_")[1] if "_" in base else base


def _index_crops():
    """Map (x, y, w, h) -> list of crop file paths in analysis/crops/."""
    by_box = {}
    if not os.path.isdir(CROPS_DIR):
        return by_box
    for entry in os.scandir(CROPS_DIR):
        if not entry.is_file():
            continue
        m = CROP_RE.search(entry.name)
        if not m:
            continue
        box = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
        by_box.setdefault(box, []).append(entry.path)
    return by_box


def _write_record_json(path, row):
    common.atomic_text_write(path, json.dumps(row, indent=2, sort_keys=True))


def _copy(src, dst, dry_run):
    if not src or not os.path.exists(src):
        return False
    if os.path.exists(dst):
        return True  # already present (idempotent: cheap re-runs)
    if dry_run:
        return True
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _crop_bbox(src_img, box, dst, dry_run):
    """Write a cropped bbox image from src_img. Returns True on success."""
    from PIL import Image

    if not src_img or not os.path.exists(src_img):
        return False
    x, y, w, h = [int(v) for v in box]
    if not common.validate_box(x, y, w, h, 10_000_000, 10_000_000, margin_ok=True):
        return False
    if dry_run:
        return True
    try:
        im = Image.open(src_img)
        im.load()
        W, H = im.size
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(W, x + w)
        y1 = min(H, y + h)
        if x1 <= x0 or y1 <= y0:
            return False
        tile = im.crop((x0, y0, x1, y1))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tile.save(dst)
        return True
    except Exception as e:  # noqa: BLE001
        common.log("warn", "crop failed for %s: %s" % (src_img, e))
        return False


def _load_font(size):
    """Best-effort TrueType font with a safe fallback."""
    from PIL import ImageFont
    for name in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.truetype("arial", size)
    except Exception:
        return ImageFont.load_default()


def _open_rgb(path):
    from PIL import Image
    try:
        im = Image.open(path)
        im.load()
        return im.convert("RGB")
    except Exception:
        return None


def _make_montage(images, out, dry_run, tile_h=220, gap=8, bg=(20, 20, 24)):
    """Compose images side-by-side into one strip. Returns True on success."""
    from PIL import Image, ImageDraw

    if not images:
        return False
    if dry_run:
        return True
    tiles = []
    for p in images:
        im = _open_rgb(p)
        if im is None:
            continue
        w, h = im.size
        if h <= 0:
            continue
        nw = max(1, int(round(tile_h * w / h)))
        tiles.append(im.resize((nw, tile_h)))
    if not tiles:
        return False
    W = sum(t.size[0] for t in tiles) + gap * (len(tiles) + 1)
    canvas = Image.new("RGB", (W, tile_h + gap * 2), bg)
    x = gap
    for t in tiles:
        canvas.paste(t, (x, gap))
        x += t.size[0] + gap
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        canvas.save(out)
        return True
    except Exception as e:  # noqa: BLE001
        common.log("warn", "montage failed: %s" % e)
        return False


def _wrap(text, font, max_w):
    """Wrap text to max_w pixels using the given PIL font."""
    from PIL import Image, ImageDraw
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


def _polaroid(im, caption, target_w, border, font, bg=(245, 245, 248),
             cap_fg=(20, 20, 24)):
    """White-bordered 'evidence photo' panel with a caption strip."""
    from PIL import Image, ImageDraw
    w, h = im.size
    tw = max(1, int(round(target_w)))
    th = max(1, int(round(target_w * h / w)))
    pic = im.resize((tw, th))
    cap_h = border + int(font.size * 1.4)
    panel = Image.new("RGB", (tw + border * 2, th + border * 2 + cap_h), bg)
    panel.paste(pic, (border, border))
    d = ImageDraw.Draw(panel)
    d.text((border, th + border * 2), caption, fill=cap_fg, font=font)
    return panel


def _target_panel(im, box, target_w, caption, font, red, acc):
    """Zoomed 'target lock' view of the anomaly with a boxed reticle + ticks."""
    from PIL import Image, ImageDraw
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
    d.rectangle([bx0, by0, bx1, by1], outline=red, width=4)
    t = 16
    for (tx, ty, dx, dy) in [(bx0, by0, 1, 1), (bx1, by0, -1, 1),
                             (bx0, by1, 1, -1), (bx1, by1, -1, -1)]:
        d.line([(tx, ty), (tx + dx * t, ty)], fill=acc, width=3)
        d.line([(tx, ty), (tx, ty + dy * t)], fill=acc, width=3)
    mxc = (bx0 + bx1) / 2; myc = (by0 + by1) / 2
    d.line([(mxc - 26, myc), (mxc + 26, myc)], fill=red, width=2)
    d.line([(mxc, myc - 26), (mxc, myc + 26)], fill=red, width=2)
    lbl = "ANOMALY"
    tw = d.textlength(lbl, font=font)
    d.rectangle([bx0, by0 - 24, bx0 + tw + 14, by0 - 4], fill=red + (200,))
    d.text((bx0 + 7, by0 - 21), lbl, fill=(255, 255, 255), font=font)
    panel = _polaroid(crop, caption, target_w, 18, font,
                      bg=(248, 247, 244), cap_fg=(150, 40, 38))
    pd = ImageDraw.Draw(panel)
    pd.rectangle([2, 2, panel.width - 3, panel.height - 3], outline=red, width=4)
    return panel


def _make_social_card(src_images, crop_images, primary, product, box, out, dry_run,
                      width=1600, leads_count=1, meta=None):
    """Big 'classified dossier' collage: overlapping styled imagery + crops + metadata."""
    from PIL import Image, ImageDraw
    import random

    x, y, w, h = [int(v) for v in box]
    if dry_run:
        return True

    bg = (12, 13, 17)
    fg = (228, 230, 236)
    dim = (150, 154, 165)
    acc = (255, 196, 48)
    red = (220, 60, 58)
    mono = _load_font(22)
    mono_sm = _load_font(17)
    title_f = _load_font(54)
    stamp_f = _load_font(46)

    prefix = product.split("_")[0]
    extras_url = "https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/RDR/%s/%s/" % (prefix, product)
    view_url = "https://www.uahirise.org/%s" % product.lower()
    serial = "DX-%05d" % (abs(hash((product, box))) % 90000 + 10000)

    # --- build polaroid panels; FIRST source becomes a zoomed target-lock view ---
    src_panels = []
    for i, p in enumerate(src_images):
        im = _open_rgb(p)
        if im is None:
            continue
        cap = os.path.splitext(os.path.basename(p))[0]
        if i == 0:
            src_panels.append(_target_panel(im, box, 520,
                                            "TARGET LOCK // " + product,
                                            mono_sm, red, acc))
        else:
            src_panels.append(_polaroid(im, cap, 440, 16, mono_sm))
    crop_panels = []
    for i, p in enumerate(crop_images):
        im = _open_rgb(p)
        if im is None:
            continue
        cap = os.path.splitext(os.path.basename(p))[0][:34]
        crop_panels.append(_polaroid(im, cap, 280, 14, mono_sm))

    header_h = 140
    collage_h = 900
    meta_h = 480
    footer_h = 80
    canvas_h = header_h + collage_h + meta_h + footer_h

    canvas = Image.new("RGBA", (width, canvas_h), bg + (255,))
    d = ImageDraw.Draw(canvas)

    rnd = random.Random(abs(hash((product, box))) & 0xffffffff)

    # faint grid backdrop
    for gx in range(0, width, 48):
        d.line([(gx, 0), (gx, canvas_h)], fill=(255, 255, 255, 12), width=1)
    for gy in range(0, canvas_h, 48):
        d.line([(0, gy), (width, gy)], fill=(255, 255, 255, 12), width=1)

    def _bracket(ox, oy, sx, sy):
        L, t = 56, 5
        d.line([(ox, oy), (ox + sx * L, oy)], fill=acc, width=t)
        d.line([(ox, oy), (ox, oy + sy * L)], fill=acc, width=t)

    # corner registration brackets
    _bracket(10, 10, 1, 1)
    _bracket(width - 10, 10, -1, 1)
    _bracket(10, canvas_h - 10, 1, -1)
    _bracket(width - 10, canvas_h - 10, -1, -1)

    # scanline overlay (printed / CRT feel)
    for yy in range(header_h, canvas_h - footer_h, 3):
        d.line([(0, yy), (width, yy)], fill=(0, 0, 0, 16), width=1)

    # --- header band ---
    d.rectangle([0, 0, width, header_h], fill=(8, 9, 12, 255))
    d.rectangle([0, 0, width, 9], fill=red, width=0)
    d.rectangle([0, 9, width, 15], fill=acc, width=0)
    d.text((40, 34), "CLASSIFIED  //  ANOMALY DOSSIER", fill=red, font=title_f)
    d.text((44, 100), "SUBJECT: %s    REF GRID x=%d y=%d  BOX %dx%d px    SERIAL %s" % (
        product, x, y, w, h, serial), fill=fg, font=mono)
    tab = "EYES ONLY"
    tw = d.textlength(tab, font=mono_sm)
    d.rectangle([width - 40 - tw - 24, 30, width - 40, 64], outline=acc, width=2)
    d.text((width - 40 - tw - 12, 36), tab, fill=acc, font=mono_sm)

    def place(panel, base_x, base_y, ang_range):
        ang = rnd.uniform(-ang_range, ang_range)
        rot = panel.convert("RGBA").rotate(ang, expand=True, resample=Image.BICUBIC)
        px = int(base_x + rnd.randint(-30, 30))
        py = int(base_y + rnd.randint(-20, 20))
        canvas.paste(rot, (px, py), rot)

    cx0, cy0 = 50, header_h + 30
    # target lock (first source) prominent on the left
    if src_panels:
        place(src_panels[0], cx0, cy0, 2.2)
    # other source panels overlap lower-left
    for i, panel in enumerate(src_panels[1:4], start=1):
        place(panel, cx0 + 250 + (i - 1) * 120, cy0 + 380 + (i - 1) * 170, 5.0)
    # crop panels across the middle, overlapping
    cxs = [600, 820, 680, 880]
    cys = [cy0 + 40, cy0 + 330, cy0 + 600, cy0 + 230]
    for i, panel in enumerate(crop_panels[:6]):
        bx = cxs[i % len(cxs)]
        by = cys[i % len(cys)] + (i // len(cxs)) * 60
        place(panel, bx, by, 7.0)

    # --- right sidebar dossier ---
    mx = width - 540
    my = header_h + 30
    d.rectangle([mx - 20, my - 20, width - 30, my + 432], fill=(8, 9, 12, 225))
    d.rectangle([mx - 20, my - 20, width - 30, my - 8], outline=acc, width=2)
    m = meta or {}
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
    ty = my
    for k, v in fields:
        d.text((mx, ty), k, fill=acc, font=mono_sm)
        d.text((mx + 250, ty), v or "—", fill=fg, font=mono_sm)
        ty += 34

    rec = (primary.get("recommendation", "") or "").replace("\n", " ")
    ry = my + 312
    d.text((mx, ry), "ASSESSMENT:", fill=acc, font=mono_sm)
    for ln in _wrap(rec, mono_sm, 490)[:6]:
        ry += 26
        d.text((mx, ry), ln, fill=fg, font=mono_sm)

    # redaction flavor
    d.text((mx, ry + 24), "FILED BY:", fill=acc, font=mono_sm)
    d.rectangle([mx + 110, ry + 22, mx + 300, ry + 42], fill=(6, 7, 9), width=0)

    # source link chip (gold box, clickable look)
    chip_y = ry + 64
    d.rectangle([mx - 6, chip_y - 6, width - 36, chip_y + 56], outline=acc, width=2)
    d.text((mx, chip_y), "ORIGINAL SOURCE", fill=acc, font=mono_sm)
    for ln in _wrap(extras_url, mono_sm, 470)[:2]:
        chip_y += 24
        d.text((mx, chip_y), ln, fill=fg, font=mono_sm)

    # --- lower provenance + feature-signature block (two columns) ---
    my2 = header_h + collage_h + 24
    block_bottom = canvas_h - footer_h - 16
    d.rectangle([20, my2 - 10, width - 20, block_bottom], fill=(8, 9, 12, 235))
    d.text((40, my2), "DETECTIONS  /  PROVENANCE  /  FEATURE SIGNATURE", fill=acc, font=mono)
    bands = m.get("bands") or []
    left = [
        ("PRODUCT", product),
        ("ACQUISITION", m.get("acq_date") or "—"),
        ("ORBIT", _fmt(m.get("orbit"))),
        ("BAND VARIANTS", ", ".join(bands) if bands else "—"),
        ("SITE LAT/LON", ("%.3f, %.3f" % (m["site_lat"], m["site_lon"]))
         if (m.get("site_lat") is not None and m.get("site_lon") is not None) else "—"),
        ("LOCAL SOL TIME", _fmt(m.get("local_time"))),
        ("BOUNDING BOX", "x=%d y=%d w=%d h=%d" % (x, y, w, h)),
        ("VERDICT", _fmt(primary.get("verdict", ""))),
        ("CONFIDENCE", _fmt(primary.get("confidence", ""))),
        ("SCORE / INTEREST", "%s / %s" % (_fmt(primary.get("score", "")), _fmt(primary.get("interest", "")))),
    ]
    ly = my2 + 40
    for k, v in left:
        d.text((44, ly), k, fill=acc, font=mono_sm)
        d.text((300, ly), str(v), fill=fg, font=mono_sm)
        ly += 27
    d.text((44, ly), "ORIGINAL SOURCE", fill=acc, font=mono_sm)
    sy = ly
    for ln in _wrap(extras_url, mono_sm, 700)[:3]:
        d.text((44, sy + 22), ln, fill=dim, font=mono_sm)
        sy += 22

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
    ry2 = my2 + 40
    for k, v in right:
        d.text((840, ry2), k, fill=acc, font=mono_sm)
        d.text((1100, ry2), str(v), fill=fg, font=mono_sm)
        ry2 += 27

    rec_y = max(ly + 30, ry2) + 12
    d.text((44, rec_y), "RECOMMENDATION:", fill=acc, font=mono_sm)
    for ln in _wrap(rec, mono_sm, width - 120)[:4]:
        rec_y += 24
        d.text((44, rec_y), ln, fill=dim, font=mono_sm)

    # --- footer with source links + barcode ---
    fy = canvas_h - footer_h
    d.rectangle([0, fy, width, canvas_h], fill=(8, 9, 12, 255))
    d.rectangle([0, fy, width, fy + 4], fill=red, width=0)
    d.text((40, fy + 16), "SOURCE  " + extras_url, fill=acc, font=mono_sm)
    d.text((40, fy + 44), "VIEW    " + view_url, fill=dim, font=mono_sm)
    d.text((width - 360, fy + 30), "CASE %s" % _sanitize(product), fill=acc, font=mono_sm)
    bx = width - 320
    while bx < width - 40:
        bw = rnd.randint(2, 7)
        bh = rnd.randint(28, 52)
        d.rectangle([bx, canvas_h - 64, bx + bw, canvas_h - 64 + bh], fill=dim, width=0)
        bx += bw + rnd.randint(2, 6)

    # rotated red CONFIRMED LEAD stamp (top-right)
    stamp = Image.new("RGBA", (360, 200), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.rectangle([10, 10, 350, 190], outline=red + (255,), width=6)
    sd.rectangle([20, 20, 340, 180], outline=red + (160,), width=2)
    sd.text((40, 60), "CONFIRMED\nLEAD", fill=red + (255,), font=stamp_f)
    stamp = stamp.rotate(18, expand=True, resample=Image.BICUBIC)
    canvas.paste(stamp, (width - 430, header_h + 20), stamp)

    # secondary TOP SECRET stamp (gold, lower-left collage)
    stamp2 = Image.new("RGBA", (320, 130), (0, 0, 0, 0))
    s2 = ImageDraw.Draw(stamp2)
    s2.rectangle([8, 8, 312, 122], outline=acc + (255,), width=4)
    s2.text((40, 44), "TOP\nSECRET", fill=acc + (255,), font=_load_font(40))
    stamp2 = stamp2.rotate(-12, expand=True, resample=Image.BICUBIC)
    canvas.paste(stamp2, (40, header_h + collage_h - 210), stamp2)

    final = canvas.convert("RGB")
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        final.save(out)
        return True
    except Exception as e:  # noqa: BLE001
        common.log("warn", "social card failed: %s" % e)
        return False


def _read_leads(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return -1.0


def _fmt(v):
    """Format a value for the dossier; blank/None becomes a dash."""
    if v is None or v == "":
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f):
        return str(int(f))
    return ("%.3f" % f).rstrip("0").rstrip(".")


_LBL_CACHE = {}


def _parse_lbl(path):
    """Parse a PDS .LBL label for the handful of fields we surface.

    PDS keywords live both at top level and inside OBJECT/GROUP blocks (all
    indented). Each scalar we care about is single-line, so we parse every
    line independently rather than trying to stitch wrapped continuations.
    """
    out = {}
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except Exception:
        return out
    want = {"INCIDENCE_ANGLE", "SUB_SOLAR_AZIMUTH", "CENTER_LATITUDE",
            "CENTER_LONGITUDE", "LOCAL_TIME", "MAP_SCALE", "LINE_SAMPLES",
            "ORBIT_NUMBER", "START_TIME", "MRO:OBSERVATION_START_TIME"}
    for ln in text.split("\n"):
        m = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.+)$", ln)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith('"'):
            out[key] = val.strip('"')
            continue
        if key in ("START_TIME", "MRO:OBSERVATION_START_TIME"):
            out[key] = val
            continue
        arr = "(" in val and ")" in val
        num = re.match(r"(-?\d+\.?\d*)", val)
        if arr:
            if key in want:
                nums = re.findall(r"-?\d+\.?\d*", val)
                if nums:
                    try:
                        out[key] = float(nums[0])
                    except ValueError:
                        pass
            continue
        if num:
            try:
                out[key] = float(num.group(1))
            except ValueError:
                pass
    return out


def _load_label(product):
    """Cache + locate the PDS label for a HiRISE product (real pixel scale + geometry)."""
    if product in _LBL_CACHE:
        return _LBL_CACHE[product]
    _LBL_CACHE[product] = None
    base = os.path.join(ROOT, "data", "raw", "mars", "hirise_extras", product)
    if os.path.isdir(base):
        for name in os.listdir(base):
            if name.upper().endswith(".LBL"):
                lbl = _parse_lbl(os.path.join(base, name))
                if lbl:
                    _LBL_CACHE[product] = lbl
                    break
    return _LBL_CACHE[product]


def _band_of(path):
    """Extract the band/variant token from an image path (MIRB, RED, COLOR, ...)."""
    name = os.path.basename(path).split(".")[0]
    return name.split("_")[-1]


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="package_anomalies.py",
        description="Build a deduplicated, self-contained package folder per unique anomaly.",
    )
    ap.add_argument("--leads-csv", default=LEADS_CSV,
                    help="CSV of leads (default: data/anomalies/conclusions/leads.csv)")
    ap.add_argument("--out-dir", default=DEFAULT_OUT,
                    help="Where to write the packages (default: data/anomalies/packages)")
    ap.add_argument("--verdict", default="CONFIRMED-LEAD",
                    help="Only package leads whose `verdict` equals this (default CONFIRMED-LEAD)")
    ap.add_argument("--force", action="store_true",
                    help="Rebuild packages even if the folder already exists")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be done without writing files")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    if not os.path.exists(args.leads_csv):
        common.log("error", "leads csv not found: %s" % args.leads_csv)
        return 1

    leads = _read_leads(args.leads_csv)
    fieldnames = list(leads[0].keys()) if leads else []
    common.log("info", "loaded %d lead rows from %s" % (len(leads), args.leads_csv))

    # Only the requested verdict; group by (product, bbox) to dedupe band variants.
    targets = [r for r in leads if r.get("verdict", "").strip() == args.verdict]
    groups = {}
    order = []
    for r in targets:
        try:
            box = (int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"]))
        except (KeyError, ValueError):
            continue
        product = _product_of(r.get("path", ""))
        key = (product, box)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)
    common.log("info", "%d %s rows -> %d unique anomalies (deduped)" % (
        len(targets), args.verdict, len(groups)))

    crops_by_box = _index_crops()
    common.log("info", "indexed %d crop boxes from %s" % (len(crops_by_box), CROPS_DIR))

    out_dir = os.path.normpath(args.out_dir)
    if not args.dry_run:
        os.makedirs(out_dir, exist_ok=True)

    manifest_rows = []
    built = 0
    skipped = 0

    for idx, key in enumerate(order, 1):
        product, box = key
        rows = groups[key]
        # primary = highest score (tie-break: first)
        primary = max(rows, key=lambda r: _as_float(r.get("score")))

        pkg_id = _sanitize("%03d__%s__x%d_y%d_%dx%d" % (idx, product, *box))
        pkg_dir = os.path.join(out_dir, pkg_id)
        card_path = os.path.join(pkg_dir, "evidence", "social_card.png")

        # Skip only when the defining artifact (the social card) is already
        # present — this keeps re-runs resumable and lets a card-only refresh
        # (delete the cards, re-run without --force) regenerate just those.
        if os.path.exists(card_path) and not args.force and not args.dry_run:
            common.log("skip", "exists: %s" % pkg_id)
            skipped += 1
            continue

        imagery_files = []
        evidence_files = []
        data_files = []
        sources_files = []

        if not args.dry_run:
            for sub in ("imagery", "evidence", "evidence/crops", "data", "sources"):
                os.makedirs(os.path.join(pkg_dir, sub), exist_ok=True)

        # --- imagery/ : every distinct source image (+ marked overlay) ---
        seen_imgs = set()
        for r in rows:
            src_img = _resolve_src(r.get("path", ""))
            if src_img and src_img not in seen_imgs:
                seen_imgs.add(src_img)
                dst = os.path.join(pkg_dir, "imagery", os.path.basename(src_img))
                if _copy(src_img, dst, args.dry_run):
                    imagery_files.append(os.path.relpath(dst, pkg_dir))
            # marked overlay for this specific band
            image = r.get("image", "")
            if image:
                cand = os.path.join(MARKED_DIR, "marked_" + image)
                if os.path.exists(cand) and cand not in seen_imgs:
                    seen_imgs.add(cand)
                    dst = os.path.join(pkg_dir, "imagery", os.path.basename(cand))
                    if _copy(cand, dst, args.dry_run):
                        imagery_files.append(os.path.relpath(dst, pkg_dir))

        # --- side-by-side montage of the matching crops (analysis/crops) ---
        crop_imgs = list(crops_by_box.get(box, []))
        montage_dst = os.path.join(pkg_dir, "evidence", "anomaly_montage.png")
        if not os.path.exists(montage_dst):
            if _make_montage(crop_imgs, montage_dst, args.dry_run):
                evidence_files.append(os.path.relpath(montage_dst, pkg_dir))
        elif os.path.exists(montage_dst):
            evidence_files.append(os.path.relpath(montage_dst, pkg_dir))

        # --- single social-media "full diagram": imagery + crops + metadata ---
        src_only = [s for s in seen_imgs
                    if not os.path.dirname(s).lower().endswith("marked")]

        # --- enrich metadata from the PDS label + lead feature metrics ---
        meta = {}
        label = _load_label(product)
        bands = sorted({_band_of(r.get("path", "")) for r in rows if r.get("path")})
        meta["bands"] = bands
        if label:
            st = label.get("START_TIME") or label.get("MRO:OBSERVATION_START_TIME") or ""
            meta["acq_date"] = st.split("T")[0] if "T" in st else st
            if "ORBIT_NUMBER" in label:
                meta["orbit"] = int(label["ORBIT_NUMBER"])
            meta["local_time"] = label.get("LOCAL_TIME")
            meta["site_lat"] = label.get("CENTER_LATITUDE")
            meta["site_lon"] = label.get("CENTER_LONGITUDE")
            meta["pixel_scale_m"] = label.get("MAP_SCALE")
            meta["line_samples"] = label.get("LINE_SAMPLES")
            if label.get("INCIDENCE_ANGLE") is not None:
                meta["solar_elevation_deg"] = round(90.0 - label["INCIDENCE_ANGLE"], 2)
            meta["solar_azimuth_deg"] = label.get("SUB_SOLAR_AZIMUTH")
        # effective pixel scale (label MAP_SCALE is for the full-res product) and
        # ground size, derived from the actual displayed image width.
        prim_src = _resolve_src(primary.get("path", ""))
        W = None
        if prim_src and os.path.exists(prim_src):
            try:
                from PIL import Image as _Im
                W = _Im.open(prim_src).size[0]
            except Exception:
                W = None
        eff = meta.get("pixel_scale_m")
        if eff and meta.get("line_samples") and W:
            eff = eff * (meta["line_samples"] / float(W))
        meta["eff_pixel_scale_m"] = round(eff, 3) if eff else None
        if eff:
            meta["size_m"] = round(max(box[2], box[3]) * eff, 1)
        if meta.get("solar_elevation_deg") and meta.get("size_m"):
            meta["inferred_height_m"] = round(
                meta["size_m"] * math.tan(math.radians(meta["solar_elevation_deg"])), 1)

        card_dst = card_path
        if args.force or not os.path.exists(card_dst):
            _card_fn = _make_social_card_4k or _make_social_card
            if _card_fn(src_only, crop_imgs, primary, product, box,
                        card_dst, args.dry_run, leads_count=len(rows),
                        meta=meta):
                evidence_files.append(os.path.relpath(card_dst, pkg_dir))
        elif os.path.exists(card_dst):
            evidence_files.append(os.path.relpath(card_dst, pkg_dir))

        # --- evidence/ : cropped bbox per source image + matching crops + reports ---
        for src_img in seen_imgs:
            if src_img.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")) and \
               os.path.dirname(src_img).lower().endswith("marked"):
                continue  # don't crop the overlay itself; only the source imagery
            stem = os.path.splitext(os.path.basename(src_img))[0]
            crop_dst = os.path.join(pkg_dir, "evidence", "lead_crop__%s.png" % _sanitize(stem))
            if not os.path.exists(crop_dst):
                if _crop_bbox(src_img, box, crop_dst, args.dry_run):
                    evidence_files.append(os.path.relpath(crop_dst, pkg_dir))
            elif os.path.exists(crop_dst):
                evidence_files.append(os.path.relpath(crop_dst, pkg_dir))
        for c in crops_by_box.get(box, []):
            dst = os.path.join(pkg_dir, "evidence", "crops", os.path.basename(c))
            if _copy(c, dst, args.dry_run):
                evidence_files.append(os.path.relpath(dst, pkg_dir))

        for src, name in (
            (os.path.join(CONCLUSIONS_DIR, "report.html"), "evidence/report.html"),
            (os.path.join(CONCLUSIONS_DIR, "SUMMARY.md"), "evidence/SUMMARY.md"),
            (os.path.join(ANALYSIS_DIR, "report.html"), "evidence/analysis_report.html"),
        ):
            if os.path.exists(src):
                dst = os.path.join(pkg_dir, name)
                if _copy(src, dst, args.dry_run):
                    evidence_files.append(os.path.relpath(dst, pkg_dir))

        # --- data/ : all sibling lead records + full provenance CSVs ---
        grp_csv = os.path.join(pkg_dir, "data", "group_leads.csv")
        if not args.dry_run:
            with open(grp_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
        data_files.append("data/group_leads.csv")

        rec_json = os.path.join(pkg_dir, "data", "lead_record.json")
        if not args.dry_run:
            _write_record_json(rec_json, primary)
        data_files.append("data/lead_record.json")

        for src, name in (
            (args.leads_csv, "data/leads.csv"),
            (os.path.join(CONCLUSIONS_DIR, "adjudicated.csv"), "data/adjudicated.csv"),
            (os.path.join(ROOT, "data", "anomalies", "candidates_filtered.csv"),
             "data/candidates_filtered.csv"),
        ):
            if os.path.exists(src):
                dst = os.path.join(pkg_dir, name)
                if _copy(src, dst, args.dry_run):
                    data_files.append(name)

        # --- sources/ : sources.yaml, raw manifest slice, catalog, README ---
        if os.path.exists(SOURCES_YAML):
            dst = os.path.join(pkg_dir, "sources", "sources.yaml")
            if _copy(SOURCES_YAML, dst, args.dry_run):
                sources_files.append("sources/sources.yaml")

        if os.path.exists(RAW_MANIFEST):
            mpath = os.path.join(pkg_dir, "sources", "manifest.jsonl")
            count = 0
            if not args.dry_run:
                with open(RAW_MANIFEST, encoding="utf-8") as f, \
                        open(mpath, "w", encoding="utf-8") as out:
                    for line in f:
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        hay = " ".join(str(rec.get(k, "")) for k in ("file", "url"))
                        if product and product in hay:
                            out.write(line if line.endswith("\n") else line + "\n")
                            count += 1
            else:
                count = 1
            if count:
                sources_files.append("sources/manifest.jsonl")

        for src, name in (
            (CATALOG_CSV, "sources/catalog.csv"),
            (CATALOG_JSON, "sources/catalog.json"),
        ):
            if os.path.exists(src):
                dst = os.path.join(pkg_dir, name)
                if _copy(src, dst, args.dry_run):
                    sources_files.append(name)

        readme = _package_readme(primary, product, box, rows, seen_imgs,
                                 imagery_files, evidence_files, data_files, sources_files)
        if not args.dry_run:
            common.atomic_text_write(os.path.join(pkg_dir, "README.md"), readme)

        common.audit({
            "step": "package_anomalies",
            "package": pkg_id,
            "product": product,
            "box": list(box),
            "verdict": primary.get("verdict"),
            "confidence": primary.get("confidence"),
            "leads_in_package": len(rows),
            "imagery": len(imagery_files),
            "evidence": len(evidence_files),
            "data": len(data_files),
            "sources": len(sources_files),
        })

        manifest_rows.append({
            "package": pkg_id,
            "product": product,
            "x": box[0], "y": box[1], "w": box[2], "h": box[3],
            "verdict": primary.get("verdict"),
            "confidence": primary.get("confidence"),
            "score": primary.get("score"),
            "leads_in_package": len(rows),
            "imagery": imagery_files,
            "evidence": evidence_files,
            "data": data_files,
            "sources": sources_files,
            "dir": os.path.relpath(pkg_dir, ROOT),
        })
        built += 1
        common.log("ok", "packaged %s (%d leads, %d img / %d ev / %d data / %d src)" % (
            pkg_id, len(rows), len(imagery_files), len(evidence_files),
            len(data_files), len(sources_files)))

    if not args.dry_run:
        common.atomic_text_write(
            os.path.join(out_dir, "MANIFEST.jsonl"),
            "".join(json.dumps(r) + "\n" for r in manifest_rows))
        with open(os.path.join(out_dir, "index.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["package", "product", "x", "y", "w", "h", "verdict",
                        "confidence", "score", "leads_in_package", "dir"])
            for r in manifest_rows:
                w.writerow([r["package"], r["product"], r["x"], r["y"], r["w"], r["h"],
                            r["verdict"], r["confidence"], r["score"],
                            r["leads_in_package"], r["dir"]])

    common.log("done", "built %d packages (from %d leads), skipped %d -> %s" % (
        built, len(targets), skipped, out_dir))
    return 0


def _package_readme(primary, product, box, rows, seen_imgs, imagery, evidence, data, sources):
    x, y, w, h = box
    lines = []
    lines.append("# Anomaly Package: %s" % product)
    lines.append("")
    lines.append("Self-contained, deduplicated evidence package for one unique CONFIRMED-LEAD")
    lines.append("feature (all band-variant detections at this location are merged here).")
    lines.append("")
    lines.append("## Detection")
    lines.append("")
    lines.append("- **Product:** %s" % product)
    lines.append("- **Bounding box:** x=%d y=%d w=%d h=%d (px in source image)" % (x, y, w, h))
    lines.append("- **Verdict:** %s" % primary.get("verdict", ""))
    lines.append("- **Confidence:** %s" % primary.get("confidence", ""))
    lines.append("- **Top score / interest:** %s / %s" % (primary.get("score", ""), primary.get("interest", "")))
    lines.append("- **Polarity / class:** %s / %s" % (primary.get("polarity", ""), primary.get("evidence_class", "")))
    lines.append("- **Leads merged into this package:** %d" % len(rows))
    lines.append("")
    lines.append("## Recommendation (from adjudication)")
    lines.append("")
    lines.append("> %s" % (primary.get("recommendation", "") or "").replace("\n", " "))
    lines.append("")
    lines.append("## Source images in this package (%d)" % len(seen_imgs))
    lines.append("")
    for s in sorted(seen_imgs):
        lines.append("- `%s`" % os.path.basename(s))
    lines.append("")
    lines.append("## Contents")
    lines.append("")
    lines.append("- `imagery/` — every distinct source image the feature appears in (+ marked overlays)")
    lines.append("- `evidence/` — `lead_crop__*.png` (bbox crops), `anomaly_montage.png` (side-by-side crops), `social_card.png` (classified dossier), and reports")
    lines.append("- `data/` — all sibling lead records (CSV), primary record (JSON), full provenance CSVs")
    lines.append("- `sources/` — sources.yaml, raw-download manifest slice, catalog")
    lines.append("")
    lines.append("## Verification steps")
    lines.append("")
    lines.append("1. Open `imagery/` and `evidence/lead_crop__*.png` to inspect the feature.")
    lines.append("2. Cross-check the band variants listed above (persistence across renderings).")
    lines.append("3. Fetch the EDR original and geolocate on Mars Trek (see sources/ provenance).")
    lines.append("4. Confirm an independent pass at different lighting before writing a finding.")
    lines.append("")
    lines.append("Generated by `scripts/package_anomalies.py`.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
