"""
Variant-Comparison Engine — B&W vs filtered vs ortho vs DTM-shaded
==================================================================
For every EXTRAS footprint (observation or stereo pair) this module
treats the downloaded sibling files as ONE comparison set:

  • B&W reference     = *_RED.browse.* / *_RED_C_01_ORTHO.*  (panchromatic, least processing)
  • Filtered color    = *_IRB*, *_MIRB/MRGB/RGB/COLOR*        (stretched / filtered)
  • Orthorectified    = *ORTHO* vs *NOMAP*                     (geometric correction check)
  • DTM-shaded        = DTEEC shaded derivatives (.ab/.br/.ca/.sa...) + FOM

It aligns each variant to the B&W reference (phase-correlation translation),
computes per-variant difference maps, and scores persistence:

  persistent terrain  → feature survives B&W → color → ortho → DTM-shaded
  processing artifact → feature collapses in B&W or DTM (filter / stretch / seam)

Outputs (per footprint)
  data/processed/extras_compare/<footprint>/
    diff_<variant>_vs_RED.png      absolute difference (registered)
    blink_<a>_vs_<b>.gif           optional blink animation (if PIL gif available)
    compare_report.json            machine-readable scores
    compare_report.md              human-readable finding draft
    composite_strip.jpg            B&W | color | ortho | DTM-shaded strip

The adjudicator (pipeline/adjudicate.py) can ingest compare_report.json
as an additional signal: a candidate whose contrast collapses outside the
filtered variant is likely a stretch artifact; one that survives into the
DTM shaded relief is terrain.

Design notes
  - Pure numpy + PIL; opencv/scipy optional accelerators degrade gracefully.
  - All registrations are translation-only (PDS EXTRAS browses are already
    map-projected to the same grid per footprint; sub-pixel rotation is rare
    and flagged as a warning).
  - 8-bit browse JPGs are normalised to [0,1] before differencing; elevation
    DTMs are percentile-stretched before comparison.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

try:
    from scipy.ndimage import shift as _nd_shift  # type: ignore

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# Import hardened infra
try:
    import common  # when pipeline/ is on sys.path
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import common

# ---------------------------------------------------------------------------
# Variant taxonomy helpers (mirrors download_hirise_extras.py)
# ---------------------------------------------------------------------------

RED_RX = re.compile(r"_RED(\.NOMAP|\.QLOOK|_C_\d+_ORTHO)?\.", re.I)
IRB_RX = re.compile(r"_IRB", re.I)
MIRB_RX = re.compile(r"_MIRB", re.I)
MRGB_RX = re.compile(r"_MRGB", re.I)
ORTHO_RX = re.compile(r"ORTHO", re.I)
NOMAP_RX = re.compile(r"NOMAP", re.I)
DTM_RX = re.compile(r"^DTEEC", re.I)
FOM_RX = re.compile(r"^DTFEC|^FOM", re.I)

# DTM browse suffixes -> human label
DTM_LABELS = {
    ".ab.jpg": "shaded-relief A",
    ".br.jpg": "browse B",
    ".ca.jpg": "colorized A",
    ".cb.jpg": "colorized B",
    ".ct.jpg": "contour/terrain",
    ".sa.jpg": "slope A",
    ".sb.jpg": "slope B",
    ".st.jpg": "stereo helper",
    ".th.jpg": "thumbnail",
}

BROWSE_RX = re.compile(r"\.(browse|abrowse|thumb)\.jpg$", re.I)


def _taxonomy(path: str) -> str:
    name = os.path.basename(path)
    low = name.lower()
    if DTM_RX.match(name):
        for suf, lbl in DTM_LABELS.items():
            if low.endswith(suf):
                return f"DTM {lbl}"
        if low.endswith(".jp2"):
            return "DTM elevation (JP2)"
        return "DTM derivative"
    if FOM_RX.match(name):
        return "FOM correlation map"
    if ORTHO_RX.search(name) and RED_RX.search(name):
        return "ORTHO B&W (RED)"
    if ORTHO_RX.search(name) and IRB_RX.search(name):
        return "ORTHO color (IRB)"
    if IRB_RX.search(name):
        return "filtered color (IRB)"
    if MIRB_RX.search(name):
        return "filtered color (MIRB)"
    if MRGB_RX.search(name):
        return "filtered color (MRGB)"
    if RED_RX.search(name):
        return "B&W panchromatic (RED)"
    return "browse variant"


def _variant_role(path: str) -> str:
    """Canonical role used for alignment priority: red | color | ortho_red | ortho_color | dtm | fom | other"""
    name = os.path.basename(path)
    if FOM_RX.match(name):
        return "fom"
    if DTM_RX.match(name):
        return "dtm"
    is_ortho = bool(ORTHO_RX.search(name))
    is_red = bool(RED_RX.search(name))
    is_irb = bool(IRB_RX.search(name) or MIRB_RX.search(name) or MRGB_RX.search(name))
    if is_ortho and is_red:
        return "ortho_red"
    if is_ortho and is_irb:
        return "ortho_color"
    if is_red:
        return "red"
    if is_irb:
        return "color"
    return "other"


# ---------------------------------------------------------------------------
# Image I/O
# ---------------------------------------------------------------------------

def _load_gray(path: str) -> np.ndarray | None:
    try:
        return common.load_gray(path)
    except Exception as e:
        print(f"[warn] load_gray failed {path}: {e}")
        return None


def _norm01(arr: np.ndarray) -> np.ndarray:
    a = np.asarray(arr, dtype=np.float32)
    if a.size == 0:
        return a
    # Percentile stretch to [0,1] so DTM elevation and 8-bit browses share a scale
    lo, hi = np.percentile(a[np.isfinite(a)], [1, 99]) if np.isfinite(a).any() else (a.min(), a.max())
    if hi <= lo:
        return np.zeros_like(a, dtype=np.float32)
    out = (a - lo) / (hi - lo)
    return np.clip(out, 0, 1).astype(np.float32)


def _resize_to(arr: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Resize arr to shape (H, W) via PIL bilinear (preserves aspect if needed)."""
    h, w = shape
    im = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    im2 = im.resize((w, h), Image.BILINEAR)
    return np.asarray(im2, dtype=np.float32) / 255.0


# ---------------------------------------------------------------------------
# Registration (translation-only, phase correlation)
# ---------------------------------------------------------------------------

def _phase_shift(ref: np.ndarray, mov: np.ndarray) -> tuple[float, float]:
    """Estimate (dy, dx) shift to align mov onto ref via phase correlation (numpy only)."""
    # Window to suppress edge effects
    h, w = ref.shape
    # Use 512² crop centred for speed if large
    if h > 700 or w > 700:
        ch, cw = 512, 512
        y0, x0 = (h - ch) // 2, (w - cw) // 2
        ref_c = ref[y0 : y0 + ch, x0 : x0 + cw]
        mov_c = mov[y0 : y0 + ch, x0 : x0 + cw]
    else:
        ref_c = ref
        mov_c = mov
    F1 = np.fft.rfft2(ref_c)
    F2 = np.fft.rfft2(mov_c)
    R = F1 * np.conj(F2)
    R /= np.abs(R) + 1e-9
    corr = np.fft.irfft2(R, s=ref_c.shape)
    # Peak
    y, x = np.unravel_index(int(np.argmax(corr)), corr.shape)
    # Wrap to signed shift
    if y > ref_c.shape[0] // 2:
        y -= ref_c.shape[0]
    if x > ref_c.shape[1] // 2:
        x -= ref_c.shape[1]
    # If we cropped, same shift applies to full image
    return float(y), float(x)


def _apply_shift(arr: np.ndarray, dy: float, dx: float) -> np.ndarray:
    if abs(dy) < 0.25 and abs(dx) < 0.25:
        return arr
    if HAS_SCIPY:
        return _nd_shift(arr, shift=(dy, dx), order=1, mode="nearest")
    # Pure numpy integer shift fallback
    iy, ix = int(round(dy)), int(round(dx))
    out = np.roll(arr, shift=(iy, ix), axis=(0, 1))
    # Zero the wrapped edge (mark as invalid rather than circulant)
    if iy > 0:
        out[:iy, :] = arr[:iy, :].mean() if arr.size else 0
    elif iy < 0:
        out[iy:, :] = arr[iy:, :].mean() if arr.size else 0
    if ix > 0:
        out[:, :ix] = arr[:, :ix].mean() if arr.size else 0
    elif ix < 0:
        out[:, ix:] = arr[:, ix:].mean() if arr.size else 0
    return out


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _diff_stats(ref: np.ndarray, mov_aligned: np.ndarray) -> dict:
    diff = np.abs(ref - mov_aligned).astype(np.float32)
    # Mask out NaN / border artefacts (shift fill) by ignoring extreme values
    valid = np.isfinite(diff)
    if not valid.any():
        return {"mean_abs_diff": 0.0, "max_abs_diff": 0.0, "p95": 0.0, "ssim_proxy": 0.0}
    d = diff[valid]
    # SSIM proxy: 1 - mean_abs_diff (0=identical, 1=opposite), quick and stable
    ssim_proxy = float(1.0 - float(np.clip(d.mean(), 0, 1)))
    return {
        "mean_abs_diff": round(float(d.mean()), 4),
        "max_abs_diff": round(float(d.max()), 4),
        "p95": round(float(np.percentile(d, 95)), 4),
        "ssim_proxy": round(ssim_proxy, 4),
    }


def _candidate_persistence(candidates: list[dict], ref_arr: np.ndarray, cmp_arr: np.ndarray, shift: tuple[float, float]) -> dict[tuple, float]:
    """
    For each candidate box (x,y,w,h in ref coords), measure contrast persistence:
    contrast_in_cmp / contrast_in_ref  (median-filter robust). Returns key->persistence.
    """
    if not candidates:
        return {}
    # Align cmp -> ref coords (translate)
    dy, dx = shift
    # For box-level persistence we just shift the crop window
    H, W = ref_arr.shape
    out: dict[tuple, float] = {}
    for c in candidates:
        try:
            x, y, w, h = int(c["x"]), int(c["y"]), int(c["w"]), int(c["h"])
        except Exception:
            continue
        if not common.validate_box(x, y, w, h, W, H):
            continue
        # Extract ref crop stats
        ref_crop = ref_arr[y : y + h, x : x + w]
        # Shifted cmp crop
        cx, cy = int(round(x + dx)), int(round(y + dy))
        if not common.validate_box(cx, cy, w, h, cmp_arr.shape[1], cmp_arr.shape[0]):
            continue
        cmp_crop = cmp_arr[cy : cy + h, cx : cx + w]
        if ref_crop.size == 0 or cmp_crop.size == 0:
            continue
        # Contrast = |fg mean - bg ring mean| / bg std ; here simplified to std-normalised range
        def _contrast(crop: np.ndarray) -> float:
            # local contrast proxy: (p90 - p10) / (std+eps)
            vals = crop[np.isfinite(crop)]
            if vals.size < 4:
                return 0.0
            return float((np.percentile(vals, 90) - np.percentile(vals, 10)) / (float(vals.std()) + 1e-6))

        cr = _contrast(ref_crop)
        cc = _contrast(cmp_crop)
        persist = float(cc / (cr + 1e-6))
        out[(c.get("image", ""), x, y, w, h)] = round(float(np.clip(persist, 0, 2)), 3)
    return out


# ---------------------------------------------------------------------------
# Per-footprint comparison
# ---------------------------------------------------------------------------

def compare_footprint(footprint_dir: Path, candidates: list[dict], out_root: Path) -> dict:
    """
    footprint_dir: e.g. data/raw/mars/hirise_extras/ESP_013948_1410
    Returns a report dict and writes artefacts to out_root/<footprint>/.
    """
    footprint = footprint_dir.name
    # Collect image siblings (jpg/png/jp2 that Pillow can open; skip LBL/txt/legend manifest logs)
    siblings: list[Path] = []
    for p in sorted(footprint_dir.iterdir()):
        if p.name.startswith("_variant_manifest"):
            continue
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".jp2"):
            siblings.append(p)
        elif p.suffix.lower() == ".jpg" and p.name.lower().endswith(".jpg"):
            siblings.append(p)
    # Also catch .ab.jpg etc (suffix is .jpg but name contains .ab)
    # Already covered via iterdir above (suffix check .jpg matches .ab.jpg)
    if not siblings:
        return {"footprint": footprint, "error": "no image siblings found", "variants": []}

    # Choose reference: B&W RED browse preferred, else largest image
    ref_path: Path | None = None
    # priority: red browse > red ortho > any red > largest
    for role in ("red", "ortho_red", "other"):
        cands = [p for p in siblings if _variant_role(str(p)) == role]
        if cands:
            # Prefer full browse over ab/th
            cands.sort(key=lambda p: (0 if "browse" in p.name.lower() else 1, -p.stat().st_size))
            ref_path = cands[0]
            break
    if ref_path is None:
        ref_path = max(siblings, key=lambda p: p.stat().st_size)
    ref_arr_raw = _load_gray(str(ref_path))
    if ref_arr_raw is None:
        return {"footprint": footprint, "error": f"failed to load reference {ref_path.name}", "variants": []}
    ref_arr = _norm01(ref_arr_raw)
    H, W = ref_arr.shape

    out_dir = out_root / footprint
    out_dir.mkdir(parents=True, exist_ok=True)

    variants: list[dict] = []
    # Persistence accumulator per candidate
    persist_by_variant: dict[str, dict] = {}

    for sib in siblings:
        role = _variant_role(str(sib))
        tax = _taxonomy(str(sib))
        if sib == ref_path:
            variants.append(
                {
                    "file": sib.name,
                    "path": str(sib),
                    "taxonomy": tax,
                    "role": role,
                    "reference": True,
                    "shape": [int(W), int(H)],
                    "shift_dy": 0.0,
                    "shift_dx": 0.0,
                    "metrics": {"mean_abs_diff": 0.0, "max_abs_diff": 0.0, "p95": 0.0, "ssim_proxy": 1.0},
                    "verdict": "REFERENCE (B&W baseline)",
                }
            )
            # save normalised reference strip for the composite
            continue
        arr_raw = _load_gray(str(sib))
        if arr_raw is None:
            variants.append({"file": sib.name, "taxonomy": tax, "role": role, "error": "load failed"})
            continue
        arr = _norm01(arr_raw)
        # Normalise resolution: resample variant to reference shape for pixel comparison
        if arr.shape != (H, W):
            arr_rs = _resize_to(arr, (H, W))
        else:
            arr_rs = arr
        # Register via phase correlation
        try:
            dy, dx = _phase_shift(ref_arr, arr_rs)
            # Guard: huge shift means mis-registration / different coverage, not a translation
            if abs(dy) > H * 0.15 or abs(dx) > W * 0.15:
                # flag but still record metrics without shift
                dy, dx = 0.0, 0.0
                reg_note = "large shift suppressed (different coverage?)"
            else:
                reg_note = ""
        except Exception as e:
            dy, dx = 0.0, 0.0
            reg_note = f"registration failed: {e}"
        aligned = _apply_shift(arr_rs, dy, dx)
        metrics = _diff_stats(ref_arr, aligned)
        # Candidate persistence if we have candidates for this footprint
        # Filter candidates to this footprint by path substring
        footprint_cands = [c for c in candidates if footprint in c.get("path", "") or footprint in c.get("image", "")]
        persist = _candidate_persistence(footprint_cands, ref_arr, arr_rs, (dy, dx))
        if persist:
            persist_by_variant[sib.name] = persist
        # Verdict heuristic
        # mean_abs_diff < 0.08 => near-identical (terrain persists)
        # 0.08-0.18 => color filter divergence (expected for filtered variants)
        # >0.35 => strong divergence (likely DTM shading vs photographic)
        mad = metrics["mean_abs_diff"]
        if role == "fom":
            verdict = "FOM — correlation quality, not terrain (ignore for morphology)"
        elif mad < 0.06:
            verdict = "PERSISTS — near-identical to B&W (terrain, not filter artifact)"
        elif mad < 0.14:
            verdict = "COLOR DIVERGENCE — expected for filtered color vs B&W (compare contrast)"
        elif mad < 0.28:
            verdict = "MODERATE DIVERGENCE — ortho / DTM shading difference"
        else:
            verdict = "STRONG DIVERGENCE — visualization or coverage difference; not a morphology proof"
        if reg_note:
            verdict += f" [{reg_note}]"
        rec: dict = {
            "file": sib.name,
            "path": str(sib),
            "taxonomy": tax,
            "role": role,
            "reference": False,
            "shape": [int(arr_rs.shape[1]), int(arr_rs.shape[0])],
            "shift_dy": round(float(dy), 2),
            "shift_dx": round(float(dx), 2),
            "metrics": metrics,
            "verdict": verdict,
        }
        if persist:
            # summarise median persistence across candidates
            vals = list(persist.values())
            rec["candidate_median_persistence"] = round(float(np.median(vals)), 3)
        variants.append(rec)
        # Write diff image
        try:
            diff = (np.abs(ref_arr - aligned) * 255).astype(np.uint8)
            # Enhance diff for visibility: percentile stretch
            lo, hi = np.percentile(diff, [2, 98])
            if hi > lo:
                diff = np.clip((diff.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
            Image.fromarray(diff).save(out_dir / f"diff_{sib.stem}_vs_{ref_path.stem}.png")
        except Exception:
            pass

    # Composite strip: reference | up to 3 variants (color, ortho, DTM) thumbnailed
    try:
        thumbs: list[Image.Image] = []
        # Reference thumb
        ref_thumb = Image.fromarray((np.clip(ref_arr, 0, 1) * 255).astype(np.uint8)).resize((320, 320), Image.BILINEAR)
        thumbs.append(ref_thumb)
        # Pick one of each role
        for role in ("color", "ortho_red", "ortho_color", "dtm"):
            for v in variants:
                if v.get("role") == role and not v.get("reference"):
                    p = Path(v["path"])
                    if p.exists():
                        arr = _load_gray(str(p))
                        if arr is not None:
                            arr_n = _norm01(arr)
                            im = Image.fromarray((np.clip(arr_n, 0, 1) * 255).astype(np.uint8)).resize((320, 320), Image.BILINEAR)
                            thumbs.append(im)
                            break
            if len(thumbs) >= 4:
                break
        if len(thumbs) >= 2:
            strip_w = sum(t.width for t in thumbs)
            strip_h = max(t.height for t in thumbs)
            strip = Image.new("L", (strip_w, strip_h))
            x = 0
            for t in thumbs:
                strip.paste(t, (x, 0))
                x += t.width
            # Convert to RGB for better display
            strip.convert("RGB").save(out_dir / "composite_strip.jpg", quality=92)
    except Exception:
        pass

    report = {
        "footprint": footprint,
        "source_dir": str(footprint_dir),
        "reference": ref_path.name if ref_path else None,
        "reference_taxonomy": _taxonomy(str(ref_path)) if ref_path else None,
        "variants": variants,
        "summary": {
            "siblings": len(siblings),
            "compared": sum(1 for v in variants if not v.get("reference") and "metrics" in v),
            "note": "B&W RED is the baseline (least processing). Color/ortho/DTM variants should diverge only photometrically, not morphologically, for real terrain.",
        },
    }
    # Persist candidate persistence detail if any
    if persist_by_variant:
        report["candidate_persistence"] = {k: dict(list(v.items())[:50]) for k, v in persist_by_variant.items()}
    # Write JSON + MD
    common.atomic_text_write(str(out_dir / "compare_report.json"), json.dumps(report, indent=2))
    md_lines = [
        f"# Variant comparison — {footprint}",
        "",
        f"Reference (B&W baseline): **{ref_path.name}** — {_taxonomy(str(ref_path))}",
        f"Source dir: `{footprint_dir}`",
        "",
        "| file | role | taxonomy | shift (dy,dx) | meanΔ | p95 | SSIM∝ | verdict |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for v in variants:
        m = v.get("metrics", {})
        md_lines.append(
            f"| {v.get('file','')} | {v.get('role','')} | {v.get('taxonomy','')} | {v.get('shift_dy','')},{v.get('shift_dx','')} | {m.get('mean_abs_diff','')} | {m.get('p95','')} | {m.get('ssim_proxy','')} | {v.get('verdict','')} |"
        )
    md_lines += [
        "",
        "Interpretation",
        "- PERSISTS (Δ<0.06): same morphology in B&W and variant — terrain or shared artifact (needs independent acquisition).",
        "- COLOR DIVERGENCE (0.06-0.14): expected between B&W and filtered color; compare candidate contrast, not raw Δ.",
        "- MODERATE/STRONG DIVERGENCE: visualization difference (DTM shading, FOM) — not a morphology proof.",
        "- Large shift suppressed: variant has different coverage/grid — not directly comparable pixel-for-pixel.",
    ]
    common.atomic_text_write(str(out_dir / "compare_report.md"), "\n".join(md_lines))
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compare HiRISE EXTRAS variant sets (B&W vs filtered vs ortho vs DTM)")
    p.add_argument("--extras-root", default="data/raw/mars/hirise_extras", help="root containing footprint subdirs (each with _variant_manifest.json)")
    p.add_argument("--out", default="data/processed/extras_compare", help="output root for diff maps + reports")
    p.add_argument("--candidates", default="data/anomalies/candidates.csv", help="candidates.csv for per-candidate persistence scoring (optional)")
    p.add_argument("--footprint", default="", help="only process this footprint subdir name (e.g. ESP_013948_1410_ESP_013236_1410)")
    args = p.parse_args(argv)

    extras_root = Path(args.extras_root)
    out_root = Path(args.out)
    if not extras_root.is_dir():
        print(f"[extras_compare] no EXTRAS root at {extras_root} — run download_hirise_extras.py first", file=sys.stderr)
        return 2
    # Load candidates if present (optional — comparison works without them)
    candidates: list[dict] = []
    if args.candidates and os.path.exists(args.candidates):
        try:
            with open(args.candidates, newline="", encoding="utf-8") as f:
                candidates = list(csv.DictReader(f))
            print(f"[extras_compare] loaded {len(candidates)} candidates from {args.candidates}")
        except Exception as e:
            print(f"[warn] candidates load failed: {e}")
    else:
        print(f"[extras_compare] no candidates file at {args.candidates} — running footprint-level comparison only")

    footprints = [d for d in extras_root.iterdir() if d.is_dir()]
    if args.footprint:
        footprints = [d for d in footprints if d.name == args.footprint]
        if not footprints:
            print(f"[error] footprint {args.footprint!r} not found in {extras_root}", file=sys.stderr)
            return 2
    if not footprints:
        print(f"[error] no footprint subdirs in {extras_root}", file=sys.stderr)
        return 2
    print(f"[extras_compare] {len(footprints)} footprint(s) -> {out_root}")
    out_root.mkdir(parents=True, exist_ok=True)
    all_reports: list[dict] = []
    start = common.time.time()
    for fp in sorted(footprints):
        print(f"  • {fp.name}")
        report = compare_footprint(fp, candidates, out_root)
        all_reports.append(report)
        n_compared = report.get("summary", {}).get("compared", 0)
        print(f"    -> {n_compared} variant(s) compared, reference={report.get('reference')}")

    # Index
    common.atomic_text_write(str(out_root / "index.json"), json.dumps(all_reports, indent=2))
    # Quick HTML index
    rows = "\n".join(
        f"<tr><td><a href='{r['footprint']}/compare_report.md'>{r['footprint']}</a></td><td>{r.get('reference','')}</td><td>{r.get('summary',{}).get('compared',0)}</td><td><a href='{r['footprint']}/composite_strip.jpg'>strip</a></td></tr>"
        for r in all_reports
    )
    html_doc = (
        "<!doctype html><html><head><meta charset='utf-8'><title>EXTRAS variant comparison</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:2rem;background:#0d1117;color:#d8dee6}"
        "table{border-collapse:collapse}th,td{border:1px solid #2a3138;padding:.4rem .6rem}"
        "a{color:#4aa3ff}</style></head><body>"
        "<h1>EXTRAS variant comparison — B&W vs filtered vs ortho vs DTM</h1>"
        f"<p>{len(all_reports)} footprint(s). Reference is always the B&W RED browse (least processing).</p>"
        "<table><tr><th>footprint</th><th>reference</th><th>variants compared</th><th>strip</th></tr>"
        + rows
        + "</table></body></html>"
    )
    common.atomic_text_write(str(out_root / "index.html"), html_doc)
    elapsed = round(common.time.time() - start, 1)
    print(f"[extras_compare] done in {elapsed}s -> {out_root}/index.html")
    # Audit
    common.set_audit(common.audit_path_for(str(out_root)))
    common.audit(
        {
            "event": "extras_compare",
            "cmd": " ".join(sys.argv),
            "extras_root": str(extras_root.resolve()),
            "out": str(out_root.resolve()),
            "footprints": len(all_reports),
            "seconds": elapsed,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
