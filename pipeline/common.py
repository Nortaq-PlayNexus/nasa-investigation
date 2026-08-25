"""Shared hardened infrastructure for the pipeline.

Thin, stdlib-only layer that makes every step:
  - auditable: JSONL audit records with input/output hashes and parameters,
  - crash-safe: atomic file writes (write temp + fsync + rename),
  - deterministic: one seeding routine for all RNGs,
  - reproducible: parameters come from config/pipeline.json unless overridden,
  - defensive: input coordinate validation and path containment.

Importing this module never touches the network or filesystem.
"""

import argparse
import hashlib
import json
import os
import random
import sys
import time

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    _bundle = os.path.abspath(sys._MEIPASS)
    if os.path.exists(os.path.join(_exe_dir, "config", "pipeline.json")) or os.path.exists(os.path.join(_exe_dir, "data")):
        PROJECT_ROOT = _exe_dir
    else:
        PROJECT_ROOT = _bundle
else:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(PROJECT_ROOT, "config", "pipeline.json")
DEFAULT_AUDIT = os.path.join(PROJECT_ROOT, "data", "anomalies", "audit.jsonl")

# Box colors shared by mark.py / triage.py / bot overlays.
PALETTE = [
    (255, 40, 40),
    (255, 190, 40),
    (60, 230, 120),
    (70, 170, 255),
    (255, 90, 210),
]

_AUDIT_PATH = None


# --------------------------------------------------------------------------
# logging / audit
# --------------------------------------------------------------------------

def log(level, msg):
    print("[%s] %s" % (level.upper(), msg), flush=True)


def set_audit(path):
    """Direct subsequent audit() records to path."""
    global _AUDIT_PATH
    _AUDIT_PATH = path


def audit(record):
    """Append one JSON record (with a timestamp) to the audit trail."""
    rec = dict(record)
    rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    path = _AUDIT_PATH or DEFAULT_AUDIT
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    except OSError as e:
        log("warn", "audit write failed (%s): %s" % (path, e))


def audit_path_for(out_dir):
    """Audit-trail path for a step writing into out_dir (sibling audit.jsonl)."""
    return os.path.normpath(os.path.join(out_dir, "..", "audit.jsonl"))


# --------------------------------------------------------------------------
# hashing / atomic writes
# --------------------------------------------------------------------------

def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_text_write(path, text):
    """Write text to a temp file, flush to disk, then atomically rename.

    The temp file is removed if anything fails, so a crash never leaves
    half-written output (or stray .tmp* litter) behind.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp%d" % os.getpid()
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def atomic_csv_write(path, rows, fieldnames, extras="ignore"):
    """Atomically write rows as CSV; same crash-safety as atomic_text_write."""
    import csv
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp%d" % os.getpid()
    try:
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction=extras)
            w.writeheader()
            w.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------
# image loading (16-bit / PDS aware)
# --------------------------------------------------------------------------

def load_gray(path):
    """Read an image as float32 grayscale, preserving >8-bit data.

    Handles Pillow formats, native 16-bit PNG/TIF (mode I;16 / I / F), and PDS
    .IMG/.LBL products via pipeline/pds. Never silently truncates to 8-bit.
    """
    import numpy as np
    from PIL import Image

    low = path.lower()
    if low.endswith((".img", ".lbl", ".xml")):
        import pds
        arr = pds.read_image(path, dtype_float=True)
        return np.nan_to_num(arr).astype(np.float32)

    Image.MAX_IMAGE_PIXELS = None  # orbital EDRs routinely exceed PIL's default cap
    im = Image.open(path)
    im.load()
    mode = im.mode
    if mode in ("I;16", "I;16L", "I;16B", "I", "F"):
        arr = np.asarray(im, dtype=np.float32)
    elif mode == "L":
        arr = np.asarray(im, dtype=np.float32)
    else:
        arr = np.asarray(im.convert("L"), dtype=np.float32)
    return arr


def load_image(path):
    """Read an image as a numpy array (float32 for >8-bit, else native).

    Falls back to Pillow -> PDS -> imagecodecs (if installed) for formats
    Pillow cannot open, notably JPEG2000.
    """
    import numpy as np
    from PIL import Image

    low = path.lower()
    if low.endswith((".img", ".lbl", ".xml")):
        import pds
        return pds.read_image(path, dtype_float=True)
    Image.MAX_IMAGE_PIXELS = None  # orbital EDRs routinely exceed PIL's default cap
    try:
        im = Image.open(path)
        if im.mode in ("I;16", "I;16L", "I;16B", "I", "F"):
            return np.asarray(im, dtype=np.float32)
        return np.asarray(im)
    except Exception:
        try:
            import imagecodecs  # optional
            return np.asarray(imagecodecs.imread(path))
        except Exception:
            raise


def image_dims(path):
    """(width, height) for any supported format without decoding pixels."""
    from PIL import Image
    low = path.lower()
    if low.endswith((".img", ".lbl", ".xml")):
        import pds
        g = pds.image_geometry(path)
        if g:
            return g[1], g[0]
    Image.MAX_IMAGE_PIXELS = None  # orbital EDRs routinely exceed PIL's default cap
    with Image.open(path) as im:
        return im.size


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def load_config(path=None, overrides=None):
    """Load pipeline.json; CLI/override values win over file values."""
    cfg = {}
    path = path or DEFAULT_CONFIG
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            log("warn", "config load failed (%s): %s" % (path, e))
    if overrides:
        for key, val in overrides.items():
            if val is not None:
                cfg[key] = val
    validate_config(cfg)
    return cfg


# --------------------------------------------------------------------------
# deterministic RNG
# --------------------------------------------------------------------------

def set_seed(seed):
    import numpy as np
    random.seed(seed)
    np.random.seed(seed)


# --------------------------------------------------------------------------
# defensive validation
# --------------------------------------------------------------------------

def validate_box(x, y, w, h, W, H, margin_ok=False):
    """True if the box is inside the image and has sane dimensions."""
    try:
        x, y, w, h, W, H = int(x), int(y), int(w), int(h), int(W), int(H)
    except (TypeError, ValueError):
        return False
    if w < 1 or h < 1 or W < 1 or H < 1:
        return False
    if w > W or h > H:
        return False
    if not margin_ok and (x < 0 or y < 0 or x + w > W or y + h > H):
        return False
    return x >= 0 and y >= 0 and x + w <= W and y + h <= H


def contain_path(path):
    """Reject paths escaping the project root (defense in depth)."""
    p = os.path.abspath(path)
    root = os.path.abspath(PROJECT_ROOT)
    common = os.path.commonpath([p, root]) if os.name != "nt" else os.path.normcase(os.path.commonpath([p, root]))
    return common == root


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------

def z_pvalue(z):
    """One-sided upper-tail Gaussian p-value from a z-score. Stdlib-only."""
    import math
    z = float(z)
    if z <= 0:
        return 0.5
    if z >= 8:
        return 0.0
    x = z / math.sqrt(2.0)
    # 7-term rational approximation of erfc(x), error < 1.2e-7
    t = 1.0 / (1.0 + 0.5 * x)
    tau = t * math.exp(-x * x - 1.26551223 + t * (
        1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (
            -0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (
                1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))))
    return max(0.0, min(0.5, 0.5 * tau))


def benjamini_hochberg(pvals, q=0.05):
    """BH-FDR adjusted q-values. Returns list aligned with input order.

    pvals: iterable of p-values (kept as-is; already-known-null entries should
    be excluded by the caller before applying correction).
    """
    p = [float(v) for v in pvals]
    n = len(p)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: p[i])
    raw = [min(1.0, p[i] * n / rank) for rank, i in enumerate(order, 1)]
    qvals = [0.0] * n
    running = raw[-1]
    for rank in range(n - 1, -1, -1):
        running = min(running, raw[rank])
        qvals[order[rank]] = running
    return qvals


def help_parser(prog, description, cfg):
    """Parser factory that reads defaults from the config file."""
    p = argparse.ArgumentParser(prog=prog, description=description)
    p.set_defaults(**{k: v for k, v in cfg.items()
                      if not callable(v) and not isinstance(v, (dict, list))})
    return p


def option_default(cfg, name, fallback):
    v = cfg.get(name)
    return v if v is not None else fallback


# --------------------------------------------------------------------------
# config validation
# --------------------------------------------------------------------------

CONFIG_SCHEMA = {
    "detect_z": float,
    "detect_min_size": int,
    "detect_scales": str,
    "detect_max_scale_pixels": int,
    "analyze_max_crop": int,
    "adjudicate_max_crop": int,
    "adjudicate_top": int,
    "adjudicate_contrast_bar": float,
    "adjudicate_area_min": int,
    "adjudicate_area_max": int,
    "adjudicate_q": float,
    "benchmark_seed": int,
    "benchmark_sizes": str,
}


def validate_config(cfg, schema=None):
    """Check config types against the schema; log a warning per mismatch.

    Returns True when the config is fully valid (unknown extra keys are
    allowed so forward-compatible configs keep working).
    """
    schema = schema or CONFIG_SCHEMA
    ok = True
    for key, typ in schema.items():
        if key not in cfg:
            continue
        val = cfg[key]
        try:
            ok_type = isinstance(val, typ)
        except TypeError:
            ok_type = True
        if not ok_type:
            log("warn", "config key %r has wrong type %s (expected %s)" %
                (key, type(val).__name__, typ.__name__))
            ok = False
    return ok
